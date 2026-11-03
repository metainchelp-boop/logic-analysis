"""Synthetic metadata-only inspection contracts; no host or service access."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import unittest
from unittest import mock

import test_backup_bundle as T

B = T.B
SLOTS = (
    'bundle:.manifest.pending', 'bundle:archive-manifest.json',
    'deployment:engine.db.gz', 'deployment:source-manifest.json',
    'deployment:.manifest.pending', 'deployment:archive-manifest.json',
    'snapshot:snapshot.sqlite.gz', 'snapshot:.manifest.pending',
    'snapshot:archive-manifest.json',
)
FALSE_FIELDS = ('payload_read', 'payload_verified', 'archive_mutated',
                'source_mutated', 'database_opened', 'services_changed',
                'external_network_used')


class BundleInspectionTests(T.BundleFixture):
    def setUp(self):
        super().setUp()
        self.measured = self.plan()
        self.bundle = self.archives / B.ARCHIVE_NAME

    def path(self, slot):
        folder, name = slot.split(':')
        return self.bundle / name if folder == 'bundle' else self.bundle / folder / name

    def write(self, slot, data):
        path = self.path(slot)
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    def partial(self):
        self.bundle.mkdir(mode=0o700)
        for folder in ('deployment', 'snapshot'):
            (self.bundle / folder).mkdir(mode=0o700)
        self.write('deployment:engine.db.gz', b'incomplete-gzip')

    def published(self):
        calls = []
        def stop_before_cleanup(*args):
            calls.append(True)
            if len(calls) == 3:
                raise B.Refused('SOURCE_IN_USE')
        result = self.execute('apply', self.measured, reference_probe=stop_before_cleanup)
        self.assertEqual(result['reason'], 'SOURCE_IN_USE', result)
        self.assertTrue(result['archive_verified'])
        self.assertFalse(result['cleanup_started'])

    def inspect(self, **kwargs):
        kwargs.setdefault('runner', self.runner)
        kwargs.setdefault('free', self.free)
        return B.inspect_execute(self.measured['plan_sha256'],
                                 B.A.canonical(self.measured['plan']), **kwargs)

    def filesystem(self):
        return {str(path.relative_to(self.base)): (B.A.identity(path.stat()),
                    path.read_bytes() if path.is_file() else None)
                for path in sorted(self.base.rglob('*'))}

    @contextlib.contextmanager
    def read_only(self):
        """Permit only manifest reads; detect attempted forbidden I/O too."""
        original_open, original_read = os.open, os.read
        manifest_ids = {(p.stat().st_dev, p.stat().st_ino) for slot in SLOTS
                        if not slot.endswith('.gz') and (p := self.path(slot)).is_file()}
        calls, reads = [], []
        def opened(path, flags, *args, **kwargs):
            calls.append(os.fspath(path))
            self.assertFalse(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
            self.assertNotIn(Path(path).name, ('engine.db', 'snapshot.sqlite', 'manifest.json'))
            self.assertFalse(str(path).endswith(('.gz', '.zip')))
            return original_open(path, flags, *args, **kwargs)
        def read(fd, count):
            info = os.fstat(fd)
            self.assertIn((info.st_dev, info.st_ino), manifest_ids)
            self.assertLessEqual(count, 65537)
            data = original_read(fd, count)
            reads.append(len(data))
            return data
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(os, 'open', side_effect=opened))
            stack.enter_context(mock.patch.object(os, 'read', side_effect=read))
            forbidden = []
            for obj, names in ((os, ('write', 'unlink', 'remove', 'rename', 'replace', 'link', 'mkdir', 'rmdir', 'fsync')),
                    (B.A, ('source', 'compress', 'verify_gzip', 'verify_archive', 'create_file', 'write_bytes', 'publish', 'remove_source')),
                    (B, ('snapshot_source', 'make_plan', 'check_plan_sources', 'rehash', 'stage_bundle', 'new_bundle',
                         'producer_state', 'scan_references', 'observe_sources', 'remove_snapshot', 'verify_snapshot_archive'))):
                for name in names:
                    forbidden.append(stack.enter_context(mock.patch.object(obj, name,
                        side_effect=AssertionError('inspection attempted forbidden operation: ' + name))))
            yield calls, reads
            for operation in forbidden:
                operation.assert_not_called()

    def assert_observed(self, result):
        self.assertEqual((result['status'], result['reason']), ('observed', 'METADATA_READY'), result)
        self.assertEqual(set(result['files']), set(SLOTS))
        self.assertEqual(set(result['directories']), {'bundle', 'deployment', 'snapshot'})
        self.assertTrue(result['protected_unchanged'])
        for key in FALSE_FIELDS:
            self.assertIs(result[key], False)
        self.assertEqual(B.validate_inspect_report(result), result)

    def test_partial_gzip_is_only_sized_without_payload_io_or_mutation(self):
        self.partial()
        before = self.filesystem()
        with self.read_only() as (_, reads):
            result = self.inspect()
        self.assert_observed(result)
        self.assertEqual(reads, [])
        self.assertEqual(result['files']['deployment:engine.db.gz']['payload_size_relation'], 'short')
        self.assertIs(result['files']['snapshot:snapshot.sqlite.gz']['present'], False)
        self.assertEqual(result['marker_pairs'], dict(bundle='absent', deployment='absent', snapshot='absent'))
        self.assertEqual(before, self.filesystem())

    def test_missing_bundle_has_exact_absent_slots_and_no_source_access(self):
        before = self.filesystem()
        with self.read_only() as (_, reads):
            result = self.inspect()
        self.assert_observed(result)
        self.assertEqual(reads, [])
        self.assertTrue(all(row['present'] is False for row in result['files'].values()))
        self.assertTrue(all(row['present'] is False for row in result['directories'].values()))
        self.assertEqual(result['total_allocated_bytes'], 0)
        self.assertEqual(before, self.filesystem())

    def test_real_published_manifests_are_bound_without_reverifying_payload(self):
        self.published()
        before = self.filesystem()
        with self.read_only() as (_, reads):
            result = self.inspect()
        self.assert_observed(result)
        self.assertEqual(len(reads), 4)
        self.assertTrue(result['bundle_child_hashes_match'])
        self.assertTrue(result['deployment_source_manifest_matches'])
        self.assertEqual(result['marker_pairs'], dict.fromkeys(('bundle', 'deployment', 'snapshot'), 'published'))
        for slot, row in result['files'].items():
            if row['present'] and not slot.endswith('.gz'):
                self.assertTrue(row['manifest_shape_valid'])
                self.assertTrue(row['manifest_plan_bound'])
        self.assertEqual(before, self.filesystem())

    def test_equal_and_long_corrupt_payload_sizes_never_imply_verified(self):
        self.partial()
        expected = self.measured['plan']['files']['deployment']['gzip_size']
        for size, relation in ((expected, 'equal'), (expected + 1, 'long')):
            with self.subTest(relation=relation):
                self.write('deployment:engine.db.gz', b'!' * size)
                with self.read_only():
                    result = self.inspect()
                self.assert_observed(result)
                row = result['files']['deployment:engine.db.gz']
                self.assertEqual(row['payload_size_relation'], relation)
                self.assertIsNone(row['manifest_sha256'])
                self.assertIsNone(row['manifest_shape_valid'])
                self.assertFalse(result['payload_verified'])

    def test_exact_plan_hash_and_schema_refused_before_any_observation(self):
        plan = self.measured['plan']
        bad_plan = dict(plan, caller_path='/synthetic-unapproved')
        for raw, digest, reason in ((B.A.canonical(plan), 'f' * 64, 'PLAN_MISMATCH'),
                (B.A.canonical(bad_plan), B.hash_object(bad_plan), 'INPUT_REFUSED'),
                ('{"version":1,"version":1}', 'f' * 64, 'INPUT_REFUSED')):
            with self.subTest(reason=reason), mock.patch.object(B.A, 'snapshot') as observed, \
                    mock.patch.object(os, 'open') as opened:
                result = B.inspect_execute(digest, raw, runner=self.runner, free=self.free)
                self.assertEqual(result['reason'], reason)
                observed.assert_not_called()
                opened.assert_not_called()

    def test_link_window_only_deduplicates_same_directory_marker_inode(self):
        self.published()
        for folder in ('bundle', 'deployment', 'snapshot'):
            os.link(self.path(folder + ':archive-manifest.json'), self.path(folder + ':.manifest.pending'))
        before = self.filesystem()
        unique = {}
        for path in self.bundle.rglob('*'):
            info = path.stat()
            unique[(info.st_dev, info.st_ino)] = B.A.identity(info)['allocated_bytes']
        info = self.bundle.stat()
        unique[(info.st_dev, info.st_ino)] = B.A.identity(info)['allocated_bytes']
        with self.read_only() as (_, reads):
            result = self.inspect()
        self.assert_observed(result)
        self.assertEqual(len(reads), 4, 'one bounded read per unique manifest inode')
        self.assertEqual(result['marker_pairs'], dict.fromkeys(('bundle', 'deployment', 'snapshot'), 'link_window'))
        self.assertEqual(result['total_allocated_bytes'], sum(unique.values()))
        self.assertEqual(before, self.filesystem())

    def test_cross_role_cross_directory_and_outside_hardlinks_are_refused(self):
        self.published()
        cases = (('deployment:engine.db.gz', 'deployment:source-manifest.json'),
                 ('deployment:archive-manifest.json', 'snapshot:archive-manifest.json'),
                 ('bundle:archive-manifest.json', None))
        for original, destination in cases:
            with self.subTest(original=original, destination=destination):
                target = self.path(destination) if destination else self.base / 'outside-link'
                old = target.read_bytes() if destination else None
                if destination:
                    target.unlink()
                os.link(self.path(original), target)
                before = self.filesystem()
                with self.read_only():
                    result = self.inspect()
                self.assertEqual(result['reason'], 'PATH_REFUSED', result)
                self.assertEqual(before, self.filesystem())
                target.unlink()
                if destination:
                    self.write(destination, old)

    def test_seven_manifest_boundaries_allow_exact_cap_and_refuse_cap_plus_one(self):
        self.partial()
        slots = [slot for slot in SLOTS if not slot.endswith('.gz')]
        self.assertEqual(len(slots), 7)
        for slot in slots:
            self.write(slot, b' ' * 65536)
        with self.read_only() as (_, reads):
            result = self.inspect()
        self.assert_observed(result)
        self.assertEqual(reads, [65536] * 7)
        self.assertEqual(sum(reads), 7 * 65536)
        self.assertTrue(all(result['files'][slot]['manifest_shape_valid'] is False for slot in slots))
        self.assertEqual(result['marker_pairs'], dict.fromkeys(('bundle', 'deployment', 'snapshot'), 'conflict'))
        self.write(slots[0], b' ' * 65537)
        with self.read_only() as (_, reads):
            refused = self.inspect()
        self.assertEqual(refused['reason'], 'MANIFEST_LIMIT', refused)
        self.assertEqual(reads, [])

    def test_unexpected_name_and_symlink_are_refused_without_following(self):
        self.partial()
        outside = self.base / 'canary-target'
        outside.write_bytes(b'synthetic-content-never-read')
        slot = 'snapshot:archive-manifest.json'
        os.symlink(outside, self.path(slot))
        with mock.patch.object(os, 'read') as read:
            result = self.inspect()
        self.assertEqual(result['reason'], 'PATH_REFUSED', result)
        read.assert_not_called()
        self.path(slot).unlink()
        (self.bundle / 'unexpected-child').mkdir(mode=0o700)
        with self.read_only():
            result = self.inspect()
        self.assertEqual(result['reason'], 'PATH_REFUSED', result)

    def test_manifest_open_must_match_the_lstat_inode(self):
        self.partial()
        self.write('deployment:source-manifest.json', self.raw)
        alternate = self.base / 'alternate-manifest'
        alternate.write_bytes(self.raw)
        alternate.chmod(0o600)
        real_open = os.open
        def substituted(path, flags, *args, **kwargs):
            if path == 'source-manifest.json':
                return real_open(alternate, flags)
            return real_open(path, flags, *args, **kwargs)
        with mock.patch.object(os, 'open', side_effect=substituted), \
                mock.patch.object(os, 'read') as read:
            result = self.inspect()
        self.assertEqual(result['reason'], 'SOURCE_CHANGED', result)
        read.assert_not_called()

    def test_last_file_stat_cannot_hide_a_late_child_entry(self):
        self.partial()
        original_stat = os.stat
        counts = []
        def late_entry(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if path == 'engine.db.gz' and kwargs.get('dir_fd') is not None:
                counts.append(True)
                if len(counts) == 2:
                    self.write('deployment:source-manifest.json', self.raw)
            return info
        with mock.patch.object(os, 'stat', side_effect=late_entry):
            result = self.inspect()
        self.assertEqual(len(counts), 2)
        self.assertEqual(result['reason'], 'SOURCE_CHANGED', result)

    def test_malformed_manifest_and_exception_canaries_never_escape_closed_receipt(self):
        self.partial()
        canary = 'SYNTHETIC_PRIVATE_MANIFEST_CANARY_829c'
        self.write('deployment:source-manifest.json', ('{"private":"' + canary + '"}').encode())
        output = io.StringIO()
        with self.read_only(), contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = self.inspect()
        self.assert_observed(result)
        self.assertFalse(result['files']['deployment:source-manifest.json']['manifest_shape_valid'])
        self.assertNotIn(canary, B.A.canonical(result) + output.getvalue())
        self.assertNotIn(str(self.base), B.A.canonical(result))
        with mock.patch.object(B.A, 'snapshot', side_effect=RuntimeError(canary)):
            refused = self.inspect()
        self.assertEqual(refused['reason'], 'INTERNAL_ERROR')
        self.assertNotIn(canary, B.A.canonical(refused))

    def test_receipt_rejects_extra_slots_types_and_false_verification_claims(self):
        self.partial()
        result = self.inspect()
        self.assert_observed(result)
        bad = []
        row = copy.deepcopy(result)
        row['files']['caller:file'] = B.inspect_file_receipt()
        bad.append(row)
        row = copy.deepcopy(result)
        row['directories']['fourth'] = dict(present=False, identity_sha256=None)
        bad.append(row)
        for key, value in (('version', True), ('total_allocated_bytes', True), ('payload_verified', True)):
            row = copy.deepcopy(result)
            row[key] = value
            bad.append(row)
        row = copy.deepcopy(result)
        row['files']['deployment:engine.db.gz']['size'] = True
        bad.append(row)
        for row in bad:
            with self.subTest(change=list(row)), self.assertRaises(B.Refused):
                B.validate_inspect_report(row)

    def test_manifest_claims_and_copied_raw_hash_remain_separate_observations(self):
        self.published()
        # Whitespace preserves the source JSON assertion but changes its raw hash.
        self.write('deployment:source-manifest.json', self.raw + b'\n')
        with self.read_only():
            result = self.inspect()
        self.assert_observed(result)
        self.assertTrue(result['files']['deployment:source-manifest.json']['manifest_plan_bound'])
        self.assertFalse(result['deployment_source_manifest_matches'])
        self.assertTrue(result['bundle_child_hashes_match'])
        marker = 'snapshot:archive-manifest.json'
        value = json.loads(self.path(marker).read_bytes())
        value['file']['gzip_sha256'] = 'f' * 64
        self.write(marker, B.A.canonical(value).encode())
        with self.read_only():
            changed = self.inspect()
        self.assert_observed(changed)
        self.assertTrue(changed['files'][marker]['manifest_shape_valid'])
        self.assertFalse(changed['files'][marker]['manifest_plan_bound'])
        self.assertFalse(changed['bundle_child_hashes_match'])

    def test_manifest_changed_after_read_is_refused_without_payload_access(self):
        self.partial()
        path = self.write('deployment:source-manifest.json', self.raw)
        original_read = os.read
        def changed(fd, *args, **kwargs):
            data = original_read(fd, *args, **kwargs)
            path.write_bytes(data + b'\n')
            return data
        with mock.patch.object(os, 'read', side_effect=changed) as read:
            result = self.inspect()
        self.assertEqual(read.call_count, 1)
        self.assertEqual(result['reason'], 'SOURCE_CHANGED', result)
        self.assertFalse(result['payload_read'])

    def test_shared_deadline_expiring_after_manifest_read_refuses_without_mutation(self):
        self.partial()
        self.write('deployment:source-manifest.json', self.raw)
        clock = [0]
        budget = B.A.Budget(clock=lambda: clock[0])
        before = self.filesystem()
        with self.read_only():
            guarded_read = os.read
            def expire(fd, *args, **kwargs):
                data = guarded_read(fd, *args, **kwargs)
                clock[0] = 601
                return data
            with mock.patch.object(os, 'read', side_effect=expire) as read:
                result = self.inspect(budget=budget)
                self.assertEqual(read.call_count, 1)
        self.assertEqual(result['reason'], 'TIME_LIMIT', result)
        self.assertFalse(result['payload_read'])
        self.assertEqual(before, self.filesystem())

    def test_current_protected_difference_is_reported_and_midscan_change_is_refused(self):
        self.partial()
        first = B.A.snapshot(self.runner)
        changed = copy.deepcopy(first)
        changed['containers'][0]['restarts'] += 1
        with self.read_only(), mock.patch.object(B.A, 'snapshot', side_effect=(changed, changed)):
            result = self.inspect()
        self.assert_observed(result)
        self.assertFalse(result['protected_matches_plan'])
        with self.read_only(), mock.patch.object(B.A, 'snapshot', side_effect=(first, changed)):
            refused = self.inspect()
        self.assertEqual(refused['reason'], 'PROTECTED_CHANGED', refused)
        self.assertFalse(refused['protected_unchanged'])

    def test_inspection_lock_requires_existing_file_and_never_creates_or_writes_it(self):
        lockdir = self.base / 'locks'
        lockdir.mkdir(mode=0o700)
        lock = lockdir / 'lock'
        with mock.patch.object(B.A, 'LOCK_PARENT', str(lockdir)), self.read_only():
            with self.assertRaises(FileNotFoundError), B.inspection_lock():
                self.fail('missing lock must not be created')
        self.assertFalse(lock.exists())
        lock.write_bytes(b'unchanged-lock')
        lock.chmod(0o600)
        before = self.filesystem()
        with mock.patch.object(B.A, 'LOCK_PARENT', str(lockdir)), self.read_only():
            with B.inspection_lock():
                pass
        self.assertEqual(before, self.filesystem())


if __name__ == '__main__':
    unittest.main()
