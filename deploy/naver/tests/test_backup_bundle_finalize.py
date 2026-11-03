"""Fixed pending-only recovery contracts, using synthetic local files only."""
import contextlib
import copy
import gzip
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

import test_backup_bundle as T

B = T.B


class PinnedGzipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='bundle-pinned-', dir=Path.home())
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'synthetic.gz'
        self.payload = b'synthetic-held-descriptor\x00' * 2048
        self.gz = gzip.compress(self.payload, compresslevel=6, mtime=0)

    def expected(self, compressed=None, raw=None):
        compressed = self.gz if compressed is None else compressed
        raw = self.payload if raw is None else raw
        return dict(size=len(raw), sha256=B.A.digest(raw),
                    gzip_size=len(compressed), gzip_sha256=B.A.digest(compressed))

    @contextlib.contextmanager
    def opened(self, value):
        self.path.write_bytes(value)
        self.path.chmod(0o600)
        fd = os.open(self.path, B.READ_FLAGS)
        try:
            yield fd
        finally:
            os.close(fd)

    def test_verifies_only_supplied_descriptor_without_reopening_writing_or_closing(self):
        with self.opened(self.gz) as fd:
            identity = B.A.identity(os.fstat(fd))
            real_read = os.read
            reads = []
            def read(actual, size):
                self.assertEqual(actual, fd)
                reads.append(actual)
                return real_read(actual, size)
            with mock.patch.object(os, 'open', side_effect=AssertionError('no reopen')) as opened, \
                    mock.patch.object(os, 'write', side_effect=AssertionError('no output')) as written, \
                    mock.patch.object(os, 'close', side_effect=AssertionError('caller owns fd')) as closed, \
                    mock.patch.object(os, 'read', side_effect=read):
                B.verify_pinned_gzip(fd, self.expected(), B.A.Budget())
            self.assertTrue(reads)
            opened.assert_not_called()
            written.assert_not_called()
            closed.assert_not_called()
            self.assertEqual(B.A.identity(os.fstat(fd)), identity)

    def test_hash_size_eof_trailing_members_and_expansion_are_each_rejected(self):
        changed = bytearray(self.gz)
        changed[len(changed) // 2] ^= 1
        truncated = self.gz[:-8]
        trailing = self.gz + b'not-a-member'
        concatenated = self.gz + gzip.compress(b'second-member', mtime=0)
        cases = (
            ('equal-size-corrupt', bytes(changed), self.expected()),
            ('compressed-sha', self.gz, dict(self.expected(), gzip_sha256='f' * 64)),
            ('raw-sha', self.gz, dict(self.expected(), sha256='f' * 64)),
            ('compressed-size', self.gz, dict(self.expected(), gzip_size=len(self.gz) + 1)),
            ('missing-eof', truncated, self.expected(truncated)),
            ('trailing', trailing, self.expected(trailing)),
            ('concatenated', concatenated, self.expected(concatenated)),
            ('expansion', self.gz, dict(self.expected(), size=len(self.payload) - 1)),
        )
        for name, value, expected in cases:
            with self.subTest(case=name), self.opened(value) as fd:
                with self.assertRaises(B.Refused):
                    B.verify_pinned_gzip(fd, expected, B.A.Budget())
                os.fstat(fd)  # A failed verification also leaves the caller's pin open.

    def test_shared_deadline_refuses_midstream_and_keeps_descriptor_open(self):
        clock = [0]
        budget = B.A.Budget(clock=lambda: clock[0])
        with self.opened(self.gz) as fd:
            original_read = os.read
            def expired(actual, size):
                data = original_read(actual, size)
                clock[0] = 601
                return data
            with mock.patch.object(os, 'read', side_effect=expired), self.assertRaisesRegex(B.Refused, 'TIME_LIMIT'):
                B.verify_pinned_gzip(fd, self.expected(), budget)
            os.fstat(fd)


class FinalizeFixture(T.BundleFixture):
    def setUp(self):
        super().setUp()
        self.measured = self.plan()
        before = self.source_bytes()
        with mock.patch.object(B.A, 'publish', side_effect=B.Refused('TIME_LIMIT')) as publish:
            result = self.execute('apply', self.measured)
        self.assertEqual(result['reason'], 'TIME_LIMIT', result)
        self.assertEqual(publish.call_count, 1)
        self.assertFalse(result['cleanup_started'])
        self.assertEqual(before, self.source_bytes())
        self.bundle = self.archives / B.ARCHIVE_NAME
        self.assertEqual({p.name for p in self.bundle.iterdir()}, {'deployment', 'snapshot'})
        self.assertEqual({p.name for p in (self.bundle / 'deployment').iterdir()},
                         {'engine.db.gz', 'source-manifest.json', '.manifest.pending'})
        self.assertEqual({p.name for p in (self.bundle / 'snapshot').iterdir()},
                         {'snapshot.sqlite.gz', '.manifest.pending'})
        self.ref_calls.clear()

    def finalize(self, **kwargs):
        kwargs.setdefault('runner', self.runner)
        kwargs.setdefault('free', self.free)
        kwargs.setdefault('producer_probe', self.producer)
        kwargs.setdefault('reference_probe', self.reference)
        return B.finalize_execute(self.measured['plan_sha256'], B.FINALIZE_CONFIRM,
            B.A.canonical(self.measured['plan']), **kwargs)

    def archive_bytes(self):
        return {str(p.relative_to(self.bundle)): (B.A.identity(p.stat()), p.read_bytes())
                for p in self.bundle.rglob('*') if p.is_file()}

    def archive_state(self):
        return {str(p.relative_to(self.bundle)): (B.A.identity(p.lstat()),
                    os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
                for p in self.bundle.rglob('*')}

    def reset_pending(self, saved):
        shutil.rmtree(self.bundle)
        self.bundle.mkdir(mode=0o700)
        for folder in ('deployment', 'snapshot'):
            (self.bundle / folder).mkdir(mode=0o700)
        for name, (_, raw) in saved.items():
            path = self.bundle / name
            path.write_bytes(raw)
            path.chmod(0o600)

    def assert_untouched_refusal(self, **kwargs):
        source, archive = self.source_bytes(), self.archive_state()
        with mock.patch.object(B.A, 'publish') as published, \
                mock.patch.object(B.A, 'compress', side_effect=AssertionError('no recompression')) as compressed:
            result = self.finalize(**kwargs)
        self.assertEqual(result['status'], 'refused')
        self.assertFalse(result['cleanup_started'])
        published.assert_not_called()
        compressed.assert_not_called()
        self.assertEqual(self.source_bytes(), source)
        self.assertEqual(self.archive_state(), archive)
        return result


class FinalizeTests(FinalizeFixture):
    def test_strict_pending_shape_refuses_mixed_alias_extra_symlink_and_partial_files(self):
        saved = self.archive_bytes()
        pending = self.bundle / 'deployment/.manifest.pending'
        published = self.bundle / 'deployment/archive-manifest.json'
        payload = self.bundle / 'snapshot/snapshot.sqlite.gz'
        def duplicate_marker():
            os.link(pending, published)
        def alias_payload():
            payload.unlink()
            os.link(self.bundle / 'deployment/engine.db.gz', payload)
        def symlink_payload():
            payload.unlink()
            payload.symlink_to(self.building / 'snapshot.sqlite')
        cases = (
            ('root-marker', lambda: (self.bundle / '.manifest.pending').write_bytes(b'{}')),
            ('published-child', lambda: pending.rename(published)),
            ('link-window', duplicate_marker),
            ('missing-payload', payload.unlink),
            ('partial-payload', lambda: payload.write_bytes(b'partial')),
            ('unexpected-child', lambda: (self.bundle / 'deployment/extra').mkdir()),
            ('cross-role-alias', alias_payload),
            ('symlink', symlink_payload),
            ('wrong-mode', lambda: payload.chmod(0o644)),
        )
        for name, change in cases:
            with self.subTest(shape=name):
                self.reset_pending(saved)
                change()
                self.assert_untouched_refusal()

    def test_equal_length_corruption_refuses_before_any_publish_or_original_unlink(self):
        path = self.bundle / 'deployment/engine.db.gz'
        raw = bytearray(path.read_bytes())
        raw[len(raw) // 2] ^= 1
        path.write_bytes(raw)
        result = self.assert_untouched_refusal()
        self.assertEqual(result['reason'], 'ARCHIVE_VERIFY_FAILED')
        self.assertFalse(result['payload_verified'])

    def test_exact_original_and_pending_bytes_are_required_not_only_selected_claims(self):
        saved = self.archive_bytes()
        for name in ('deployment/source-manifest.json', 'deployment/.manifest.pending', 'snapshot/.manifest.pending'):
            with self.subTest(name=name):
                self.reset_pending(saved)
                path = self.bundle / name
                path.write_bytes(path.read_bytes() + b'\n')
                result = self.assert_untouched_refusal()
                self.assertEqual(result['reason'], 'ARCHIVE_VERIFY_FAILED')
        self.reset_pending(saved)
        path = self.cold / 'engine.db'
        path.write_bytes(b'!' + self.payload[1:])
        self.assert_untouched_refusal()

    def test_changed_producer_and_current_source_binding_never_reuse_archive(self):
        result = self.assert_untouched_refusal(producer_probe=lambda *args: {'generation': 'changed'})
        self.assertEqual(result['reason'], 'PLAN_MISMATCH')
        self.assertEqual(result['reference_checks'], 1)

    def test_each_reference_gate_is_required_and_late_refusal_preserves_originals(self):
        saved = self.archive_bytes()
        source = self.source_bytes()
        for gate in (1, 2, 3):
            with self.subTest(gate=gate):
                self.reset_pending(saved)
                scans = []
                def refuse(*args):
                    scans.append(True)
                    if len(scans) == gate:
                        raise B.Refused('SOURCE_IN_USE')
                result = self.finalize(reference_probe=refuse)
                self.assertEqual(result['reason'], 'SOURCE_IN_USE')
                self.assertEqual(len(scans), gate)
                self.assertEqual(result['reference_checks'], gate - 1)
                self.assertFalse(result['cleanup_started'])
                self.assertEqual(source, self.source_bytes())
                if gate == 3:
                    self.assertTrue(result['archive_published'])
                    self.assertEqual(result['published_markers'], 3)
                else:
                    self.assertEqual(result['published_markers'], 0)

    def test_verified_gzip_same_inode_edit_or_path_swap_refuses_before_publication(self):
        saved = self.archive_bytes()
        original_verify = B.verify_pinned_gzip
        for change in ('edit', 'swap'):
            with self.subTest(change=change):
                self.reset_pending(saved)
                source = self.source_bytes()
                changed = []
                def verify_then_change(fd, expected, budget):
                    original_verify(fd, expected, budget)
                    if not changed:
                        path = self.bundle / 'deployment/engine.db.gz'
                        data = path.read_bytes()
                        if change == 'swap':
                            path.unlink()
                        path.write_bytes(b'!' + data[1:])
                        path.chmod(0o600)
                        changed.append(True)
                with mock.patch.object(B, 'verify_pinned_gzip', side_effect=verify_then_change), \
                        mock.patch.object(B.A, 'publish') as published:
                    result = self.finalize()
                self.assertEqual(result['reason'], 'SOURCE_CHANGED')
                published.assert_not_called()
                self.assertFalse(result['cleanup_started'])
                self.assertEqual(source, self.source_bytes())

    def test_interrupted_second_publish_preserves_first_marker_and_every_original(self):
        source, original_publish = self.source_bytes(), B.A.publish
        calls = []
        def interrupt(fd):
            calls.append(True)
            if len(calls) == 2:
                raise B.Refused('TIME_LIMIT')
            return original_publish(fd)
        with mock.patch.object(B.A, 'publish', side_effect=interrupt):
            result = self.finalize()
        self.assertEqual(result['reason'], 'TIME_LIMIT')
        self.assertTrue(result['payload_verified'])
        self.assertEqual(result['published_markers'], 1)
        self.assertFalse(result['archive_published'])
        self.assertFalse(result['cleanup_started'])
        self.assertTrue((self.bundle / 'deployment/archive-manifest.json').exists())
        self.assertTrue((self.bundle / 'snapshot/.manifest.pending').exists())
        self.assertFalse((self.bundle / 'archive-manifest.json').exists())
        self.assertEqual(source, self.source_bytes())

    def test_space_projection_uses_only_new_overhead_and_checks_final_actual_free(self):
        overhead = 2 * B.A.OVERHEAD
        source_allocated = sum(p.stat().st_blocks * 512 for p in
                               (self.cold / 'engine.db', self.building / 'snapshot.sqlite'))
        exact = B.A.MIN_FREE_AFTER - source_allocated + overhead
        result = self.assert_untouched_refusal(free=lambda: exact - 1)
        self.assertEqual(result['reason'], 'SPACE_REFUSED')
        self.assertFalse(result['capacity_ok'])
        def free():
            return B.A.MIN_FREE_AFTER if not self.building.exists() else exact
        result = self.finalize(free=free)
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(result['archive_budget_bytes'], overhead)
        self.assertEqual(result['projected_free_bytes'], B.A.MIN_FREE_AFTER)
        self.assertEqual(result['free_after_bytes'], B.A.MIN_FREE_AFTER)

    def test_reserve_and_late_actual_floor_refuse_without_claiming_success(self):
        saved, source = self.archive_bytes(), self.source_bytes()
        for delta, markers in ((-1, 0), (0, 2)):
            with self.subTest(reserve_delta=delta):
                self.reset_pending(saved)
                calls = []
                def reserve_free():
                    calls.append(True)
                    return self.free() if len(calls) <= 2 else B.A.RESERVE + delta
                result = self.finalize(free=reserve_free)
                self.assertEqual(result['reason'], 'SPACE_REFUSED')
                self.assertTrue(result['payload_verified'])
                self.assertEqual(result['published_markers'], markers)
                self.assertFalse(result['cleanup_started'])
                self.assertEqual(self.source_bytes(), source)
        self.reset_pending(saved)
        def late_free():
            return B.A.MIN_FREE_AFTER - 1 if not self.building.exists() else self.free()
        result = self.finalize(free=late_free)
        self.assertEqual(result['reason'], 'SPACE_REFUSED')
        self.assertEqual(result['status'], 'refused')
        self.assertTrue(result['cleanup_complete'])
        self.assertEqual(result['removed_files'], 3)
        self.assertFalse(result['capacity_ok'])

    def test_root_write_descriptor_cannot_be_replaced_before_readonly_pin(self):
        source = self.source_bytes()
        original_create, original_close = B.A.create_file, os.close
        created, replaced = [], []
        def create(parent, name):
            fd = original_create(parent, name)
            created.append((fd, os.fstat(fd).st_ino))
            return fd
        def close(fd):
            original_close(fd)
            if created and fd == created[0][0] and not replaced:
                path = self.bundle / '.manifest.pending'
                raw = path.read_bytes()
                temporary = self.bundle / 'synthetic-replacement'
                temporary.write_bytes(raw)
                temporary.chmod(0o600)
                os.replace(temporary, path)
                replaced.append((path.stat().st_ino, raw))
        with mock.patch.object(B.A, 'create_file', side_effect=create), mock.patch.object(os, 'close', side_effect=close):
            result = self.finalize()
        self.assertEqual(len(replaced), 1)
        self.assertNotEqual(created[0][1], replaced[0][0])
        self.assertEqual(result['reason'], 'SOURCE_CHANGED')
        self.assertEqual(result['published_markers'], 2)
        self.assertFalse(result['archive_published'])
        self.assertFalse(result['cleanup_started'])
        self.assertFalse((self.bundle / 'archive-manifest.json').exists())
        self.assertEqual((self.bundle / '.manifest.pending').read_bytes(), replaced[0][1])
        self.assertEqual(self.source_bytes(), source)

    def test_one_shared_deadline_covers_rehash_verification_and_precleanup(self):
        saved, source = self.archive_bytes(), self.source_bytes()
        for phase in ('rehash', 'verify', 'precleanup'):
            with self.subTest(phase=phase):
                self.reset_pending(saved)
                clock, scans = [0], []
                budget = B.A.Budget(clock=lambda: clock[0])
                rehash, verify = B.rehash, B.verify_pinned_gzip
                def rehashed(*args):
                    value = rehash(*args)
                    if phase == 'rehash':
                        clock[0] = 601
                    return value
                def verified(*args):
                    value = verify(*args)
                    if phase == 'verify':
                        clock[0] = 601
                    return value
                def referenced(*args):
                    scans.append(True)
                    if phase == 'precleanup' and len(scans) == 3:
                        clock[0] = 601
                with mock.patch.object(B, 'rehash', side_effect=rehashed), \
                        mock.patch.object(B, 'verify_pinned_gzip', side_effect=verified):
                    result = self.finalize(budget=budget, reference_probe=referenced)
                self.assertEqual(result['reason'], 'TIME_LIMIT')
                self.assertFalse(result['cleanup_started'])
                self.assertEqual(self.source_bytes(), source)
                self.assertEqual(result['published_markers'], 3 if phase == 'precleanup' else 0)

    def test_old_confirmation_and_invalid_receipt_cannot_claim_finalization(self):
        with mock.patch.object(B.A, 'snapshot') as snapshot:
            result = B.finalize_execute(self.measured['plan_sha256'], B.CONFIRM,
                B.A.canonical(self.measured['plan']), runner=self.runner, free=self.free)
        self.assertEqual(result['reason'], 'INPUT_REFUSED')
        snapshot.assert_not_called()
        for key, value in (('published_markers', True), ('gzip_created', True),
                           ('payload_verified', True), ('status', 'applied')):
            invalid = copy.deepcopy(result)
            invalid[key] = value
            with self.subTest(field=key), self.assertRaises(B.Refused):
                B.validate_finalize_report(invalid)

    def test_published_marker_edit_after_last_hash_cannot_authorize_cleanup(self):
        before = self.source_bytes()
        scans = []
        def altered_marker(*args):
            scans.append(True)
            if len(scans) == 3:
                path = self.bundle / 'deployment' / 'archive-manifest.json'
                info = path.stat()
                raw = path.read_bytes()
                path.write_bytes(b'!' + raw[1:])
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        result = self.finalize(reference_probe=altered_marker)
        self.assertEqual(len(scans), 3)
        self.assertEqual(result['status'], 'refused')
        self.assertFalse(result['cleanup_started'])
        self.assertEqual(before, self.source_bytes())

    def test_copied_source_manifest_edit_during_third_scan_cannot_authorize_cleanup(self):
        before = self.source_bytes()
        scans = []
        def altered_copy(*args):
            scans.append(True)
            if len(scans) == 3:
                path = self.bundle / 'deployment/source-manifest.json'
                info = path.stat()
                raw = path.read_bytes()
                path.write_bytes(b'!' + raw[1:])
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
        result = self.finalize(reference_probe=altered_copy)
        self.assertEqual(len(scans), 3)
        self.assertEqual(result['status'], 'refused')
        self.assertEqual(result['reason'], 'ARCHIVE_VERIFY_FAILED')
        self.assertFalse(result['cleanup_started'])
        self.assertTrue(result['archive_published'])
        self.assertEqual(before, self.source_bytes())

    def test_gzip_bytes_changed_during_third_scan_are_rehashed_even_with_coarse_ctime(self):
        before = self.source_bytes()
        path = self.bundle / 'deployment/engine.db.gz'
        original_info = path.stat()
        target = original_info.st_dev, original_info.st_ino
        identity = B.A.identity
        scans = []
        def coarse_identity(info):
            value = identity(info)
            if (info.st_dev, info.st_ino) == target:
                # Model the equal-ctime observation seen in Linux marker tests;
                # do not introduce sleeps or rely on filesystem clock precision.
                value['ctime_ns'] = original_info.st_ctime_ns
            return value
        def altered_gzip(*args):
            scans.append(True)
            if len(scans) == 3:
                raw = path.read_bytes()
                path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
                os.utime(path, ns=(original_info.st_atime_ns, original_info.st_mtime_ns))
        with mock.patch.object(B.A, 'identity', side_effect=coarse_identity):
            result = self.finalize(reference_probe=altered_gzip)
        self.assertEqual(len(scans), 3)
        self.assertEqual(result['status'], 'refused')
        self.assertEqual(result['reason'], 'ARCHIVE_VERIFY_FAILED')
        self.assertFalse(result['cleanup_started'])
        self.assertTrue(result['archive_published'])
        self.assertEqual(before, self.source_bytes())

    def test_success_reuses_verified_inodes_and_restores_both_sources_after_three_scans(self):
        archived = self.archive_bytes()
        root_inode = (self.bundle.stat().st_dev, self.bundle.stat().st_ino)
        verified, created, scans = [], [], []
        verify = B.verify_pinned_gzip
        create = B.A.create_file
        unlink = os.unlink
        def verify_same_fd(fd, expected, budget):
            value = B.A.identity(os.fstat(fd))
            verify(fd, expected, budget)
            self.assertEqual(B.A.identity(os.fstat(fd)), value)
            verified.append((fd, value))
        def create_root_only(parent, name):
            info = os.fstat(parent)
            self.assertEqual((info.st_dev, info.st_ino), root_inode)
            self.assertEqual(name, '.manifest.pending')
            created.append(name)
            return create(parent, name)
        def references(*args):
            scans.append(True)
            if len(scans) == 3:
                self.assertEqual(len(verified), 2)
                for fd, value in verified:
                    self.assertEqual(B.A.identity(os.fstat(fd)), value)
        def unlink_after_publication(path, *args, **kwargs):
            self.assertFalse(str(path).endswith('.gz'))
            if path in ('engine.db', 'manifest.json', 'snapshot.sqlite'):
                self.assertEqual(len(scans), 3)
                self.assertEqual(len(verified), 2)
                self.assertTrue((self.bundle / 'archive-manifest.json').is_file())
            return unlink(path, *args, **kwargs)
        with mock.patch.object(B.A, 'compress', side_effect=AssertionError('no recompression')) as compressed, \
                mock.patch.object(B, 'verify_pinned_gzip', side_effect=verify_same_fd), \
                mock.patch.object(B.A, 'create_file', side_effect=create_root_only), \
                mock.patch.object(os, 'unlink', side_effect=unlink_after_publication):
            result = self.finalize(reference_probe=references)
        compressed.assert_not_called()
        self.assertTrue(result['cleanup_complete'], result)
        self.assertEqual(result['removed_files'], 3)
        self.assertEqual(result['reference_checks'], 3)
        self.assertEqual(created, ['.manifest.pending'])
        self.assertFalse(self.cold.exists())
        self.assertFalse(self.building.exists())
        for name in ('deployment/engine.db.gz', 'snapshot/snapshot.sqlite.gz', 'deployment/source-manifest.json'):
            path = self.bundle / name
            self.assertEqual((B.A.identity(path.stat()), path.read_bytes()), archived[name])
        manifest = json.loads((self.bundle / 'archive-manifest.json').read_bytes())
        B.A.restore_isolated(str(self.bundle / 'deployment'), str(self.base), 'restore-check-3333333333333333',
            manifest['deployment_archive_sha256'], B.DEPLOYMENT_SCOPE)
        B.restore_snapshot_isolated(str(self.bundle / 'snapshot'), str(self.base), 'restore-check-4444444444444444',
            manifest['snapshot_archive_sha256'])
        self.assertEqual((self.base / 'restore-check-3333333333333333/engine.db').read_bytes(), self.payload)
        self.assertEqual((self.base / 'restore-check-3333333333333333/manifest.json').read_bytes(), self.raw)
        self.assertEqual((self.base / 'restore-check-4444444444444444/snapshot.sqlite').read_bytes(), self.payload)


if __name__ == '__main__':
    unittest.main()
