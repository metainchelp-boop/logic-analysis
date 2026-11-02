import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('cold_archive', Path(__file__).parents[1] / 'cold_backup_archive.py')
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='naver-archive-test-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.backups = self.base / 'backups'
        self.archives = self.base / 'archives'
        self.backups.mkdir(mode=0o700)
        self.original = self.backups / A.BACKUP_NAME
        self.original.mkdir(mode=0o700)
        self.payloads = {'engine.db': b'fixture-not-sqlite\0' * 8000,
                         'engine.db-wal': bytes(range(256)) * 4, 'engine.db-shm': b'\0' * 4096}
        self.identities = {}
        for name, data in self.payloads.items():
            path = self.original / name
            path.write_bytes(data)
            path.chmod(0o640 if name == 'engine.db' else 0o600)
        self.raw = json.dumps({name: {'sha256': A.digest(data), 'size': len(data)}
                               for name, data in self.payloads.items()}, indent=3).encode() + b'\n'
        path = self.original / 'manifest.json'
        path.write_bytes(self.raw)
        path.chmod(0o600)
        for path in self.original.iterdir():
            self.identities[path.name] = A.identity(path.stat())
        self.patches = mock.patch.multiple(A, BACKUP_PARENT=str(self.backups), ARCHIVE_PARENT=str(self.archives),
                                           ROOT_UID=os.getuid(), ROOT_GID=os.getgid())
        self.patches.start()
        self.addCleanup(self.patches.stop)
        self.commands = []
        self.inspect_calls = 0
        self.free = lambda: 10 * 1024 ** 3

    def runner(self, command):
        self.commands.append(command)
        self.assertEqual(command[:2], A.DOCKER)
        args = command[2:]
        ids = ['%064x' % value for value in range(1, 6)]
        images = ['sha256:%064x' % value for value in range(11, 16)]
        if args == ('ps', '-aq', '--no-trunc'):
            output = '\n'.join(ids)
        elif args == ('image', 'ls', '-aq', '--no-trunc'):
            output = '\n'.join(images)
        else:
            self.assertEqual(args[:4], ('inspect', '--type=container', '--format', A.INSPECT_FORMAT))
            self.assertEqual(list(args[4:]), ids)
            self.inspect_calls += 1
            output = '\n'.join(A.canonical(dict(id=cid, image=image, running=True, pid=i + 1,
                       started='2026-11-02T17:00:00Z', restarts=0)) for i, (cid, image) in enumerate(zip(ids, images)))
        return types.SimpleNamespace(returncode=0, stdout=output.encode(), stderr=b'')

    def execute(self, mode='plan', plan='', confirm='', **kwargs):
        return A.execute(mode, plan, confirm, runner=self.runner, free=self.free, **kwargs)

    def plan(self):
        result = self.execute()
        self.assertEqual(result['status'], 'planned', result)
        return result

    def apply(self, plan=None):
        return self.execute('apply', (plan or self.plan())['plan_sha256'], A.CONFIRM)

    @property
    def archive(self):
        return self.archives / A.ARCHIVE_NAME

    def restore(self, receipt, target='restore-check-0123456789abcdef'):
        A.restore_isolated(str(self.archive), str(self.base), target, receipt['archive_manifest_sha256'])
        return self.base / target

    def test_plan_is_read_only_and_counts_exact_deterministic_gzip(self):
        first = self.plan()
        second = self.plan()
        self.assertEqual(first, second)
        self.assertFalse(self.archives.exists())
        self.assertEqual(first['source_files'], 3)
        self.assertEqual(first['source_bytes'], sum(map(len, self.payloads.values())))
        self.assertGreater(first['source_allocated_bytes'], 0)
        self.assertTrue(first['capacity_ok'])
        self.assertFalse(first['archive_started'])
        self.assertFalse(first['database_opened'])
        self.assertFalse(first['services_changed'])
        for name, row in self.identities.items():
            self.assertEqual(A.identity((self.original / name).stat()), row)

    def test_apply_round_trip_exact_bytes_manifest_and_metadata(self):
        result = self.apply()
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(result['removed_files'], 4)
        self.assertFalse(self.original.exists())
        self.assertEqual(stat.S_IMODE(self.archive.stat().st_mode), 0o700)
        self.assertEqual((self.archive / 'source-manifest.json').read_bytes(), self.raw)
        self.assertEqual(set(path.name for path in self.archive.iterdir()),
                         {name + '.gz' for name in self.payloads} | {'source-manifest.json', 'archive-manifest.json'})
        for path in self.archive.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.stat().st_nlink, 1)
        target = self.restore(result)
        for name, data in dict(self.payloads, **{'manifest.json': self.raw}).items():
            self.assertEqual((target / name).read_bytes(), data)
            actual = A.identity((target / name).stat())
            for key in ('uid', 'gid', 'mode', 'mtime_ns', 'size'):
                self.assertEqual(actual[key], self.identities[name][key], (name, key))

    def test_source_fds_closed_before_free_after_measurement(self):
        original_remove = A.remove_source
        captured = []
        def remove(src, result, budget):
            captured.extend(src['handles'].values())
            original_remove(src, result, budget)
            self.assertEqual(src['handles'], {})
            for fd in captured:
                with self.assertRaises(OSError):
                    os.fstat(fd)
        with mock.patch.object(A, 'remove_source', side_effect=remove):
            result = self.apply()
        self.assertEqual(result['status'], 'applied', result)

    def test_actual_statvfs_and_unlinked_file_release_smoke(self):
        # Exercise the real filesystem accounting instead of claiming the fake
        # capacity provider proves a production disk budget.
        with A.directory(str(self.base), True) as fd:
            before = A.free_bytes(fd)
            path = self.base / 'allocation-fixture'
            out = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                for _ in range(8):
                    os.write(out, os.urandom(1024 * 1024))
                os.fsync(out)
                allocated = os.fstat(out).st_blocks * 512
                os.unlink(path)
                retained = A.free_bytes(fd)
            finally:
                os.close(out)
            released = A.free_bytes(fd)
            self.assertGreater(allocated, 0)
            self.assertIsInstance(before, int)
            self.assertGreaterEqual(released, retained)

    def test_low_space_plan_informative_apply_refused_before_archive(self):
        self.free = lambda: 256 * 1024 ** 2
        plan = self.plan()
        self.assertFalse(plan['capacity_ok'])
        result = self.apply(plan)
        self.assertEqual(result['reason'], 'SPACE_REFUSED')
        self.assertFalse(self.archives.exists())
        self.assertTrue(self.original.exists())

    def test_free_after_under_floor_does_not_claim_capacity_success(self):
        original_remove = A.remove_source
        def remove(*args):
            original_remove(*args)
            self.free_value = A.MIN_FREE_AFTER - 1
        self.free_value = 10 * 1024 ** 3
        self.free = lambda: self.free_value
        plan = self.plan()
        with mock.patch.object(A, 'remove_source', side_effect=remove):
            result = self.apply(plan)
        self.assertEqual(result['reason'], 'SPACE_REFUSED', result)
        self.assertTrue(result['archive_verified'])
        self.assertTrue(result['cleanup_complete'])
        self.assertFalse(result['capacity_ok'])
        self.restore(result)

    def test_wrong_plan_or_confirm_cannot_create_archive(self):
        for plan, confirm, reason in [('0' * 64, A.CONFIRM, 'PLAN_MISMATCH'),
                                     ('0' * 64, 'wrong', 'INPUT_REFUSED')]:
            with self.subTest(reason=reason):
                result = self.execute('apply', plan, confirm)
                self.assertEqual(result['reason'], reason)
                self.assertFalse(self.archives.exists())
                self.assertTrue(self.original.exists())

    def test_content_or_metadata_drift_invalidates_plan(self):
        plan = self.plan()
        path = self.original / 'engine.db'
        path.chmod(0o600)
        result = self.apply(plan)
        self.assertEqual(result['reason'], 'PLAN_MISMATCH')
        self.assertFalse(self.archives.exists())

    def test_original_manifest_hash_mismatch_refused(self):
        (self.original / 'engine.db').write_bytes(b'x' * len(self.payloads['engine.db']))
        result = self.execute()
        self.assertEqual(result['reason'], 'HASH_MISMATCH')
        self.assertTrue(self.original.exists())

    def test_duplicate_manifest_key_refused(self):
        (self.original / 'manifest.json').write_text('{"engine.db":{},"engine.db":{}}')
        self.assertEqual(self.execute()['reason'], 'SOURCE_REFUSED')

    def test_unexpected_or_symlink_source_files_refused(self):
        for name in ('other.db', 'engine.db.gz'):
            with self.subTest(name=name):
                path = self.original / name
                path.write_bytes(b'no')
                self.assertEqual(self.execute()['reason'], 'SOURCE_REFUSED')
                path.unlink()
        path = self.original / 'engine.db'
        path.unlink()
        path.symlink_to(self.base / 'missing')
        self.assertEqual(self.execute()['status'], 'refused')

    def test_hardlinked_source_refused(self):
        os.link(self.original / 'engine.db', self.base / 'extra-link')
        self.assertEqual(self.execute()['reason'], 'SOURCE_REFUSED')

    def test_source_special_mode_refused_before_archive(self):
        plan = self.plan()
        (self.original / 'engine.db').chmod(0o4600)
        self.assertEqual(self.execute()['reason'], 'SOURCE_REFUSED')
        self.assertEqual(self.apply(plan)['reason'], 'SOURCE_REFUSED')
        self.assertTrue(self.original.exists())
        self.assertFalse(self.archives.exists())

    def test_source_group_unrestorable_refused_during_measurement(self):
        plan = self.plan()
        identity = A.identity
        inode = (self.original / 'engine.db').stat().st_ino
        def unsupported(info):
            row = identity(info)
            if info.st_ino == inode:
                row['gid'] = 12345
            return row
        with mock.patch.object(A, 'identity', side_effect=unsupported):
            self.assertEqual(self.execute()['reason'], 'ARCHIVE_REFUSED')
            self.assertEqual(self.apply(plan)['reason'], 'ARCHIVE_REFUSED')
        self.assertTrue(self.original.exists())
        self.assertFalse(self.archives.exists())

    def test_decompression_chunks_bound_expansion_to_expected_size(self):
        path = self.base / 'large-synthetic'
        path.write_bytes(b'\0' * (2 * A.CHUNK + 7))
        source = os.open(path, os.O_RDONLY)
        with A.directory(str(self.base), True) as parent:
            output = A.create_file(parent, 'engine.db.gz')
            try:
                row = A.compress(source, A.Budget(), A.Sink(A.Budget(), fd=output))
            finally:
                os.close(output)
                os.close(source)
            A.verify_gzip(parent, 'engine.db', row, A.Budget())
            row['size'] = A.CHUNK
            with self.assertRaisesRegex(A.Refused, 'ARCHIVE_VERIFY_FAILED'):
                A.verify_gzip(parent, 'engine.db', row, A.Budget())

    def test_source_parent_symlink_refused(self):
        link = self.base / 'link'
        link.symlink_to(self.backups, target_is_directory=True)
        with mock.patch.object(A, 'BACKUP_PARENT', str(link)):
            self.assertEqual(self.execute()['reason'], 'PATH_REFUSED')

    def test_archive_parent_symlink_refused(self):
        self.archives.symlink_to(self.backups, target_is_directory=True)
        self.assertEqual(self.execute()['reason'], 'PATH_REFUSED')

    def test_existing_partial_archive_refused_no_retry_or_removal(self):
        self.archive.mkdir(mode=0o700, parents=True)
        self.archives.chmod(0o700)
        marker = self.archive / 'partial'
        marker.write_bytes(b'retain')
        self.assertEqual(self.execute()['reason'], 'ARCHIVE_EXISTS')
        self.assertEqual(marker.read_bytes(), b'retain')

    def test_source_change_during_measurement_refused(self):
        original_compress = A.compress
        changed = False
        def compress(*args):
            nonlocal changed
            result = original_compress(*args)
            if not changed:
                changed = True
                (self.original / 'engine.db').chmod(0o600)
            return result
        with mock.patch.object(A, 'compress', side_effect=compress):
            result = self.execute()
        self.assertEqual(result['reason'], 'SOURCE_CHANGED')
        self.assertFalse(self.archives.exists())

    def test_corrupt_compressed_file_never_unlinks_source(self):
        original_verify = A.verify_archive
        def verify(fd, *args):
            handle = os.open('engine.db.gz', os.O_WRONLY, dir_fd=fd)
            os.write(handle, b'BAD')
            os.close(handle)
            return original_verify(fd, *args)
        plan = self.plan()
        with mock.patch.object(A, 'verify_archive', side_effect=verify):
            result = self.apply(plan)
        self.assertEqual(result['reason'], 'ARCHIVE_VERIFY_FAILED')
        self.assertFalse(result['cleanup_started'])
        self.assertTrue(self.original.exists())
        self.assertFalse((self.archive / 'archive-manifest.json').exists())

    def test_publication_failure_preserves_source(self):
        plan = self.plan()
        with mock.patch.object(A, 'publish', side_effect=OSError('private failure')):
            result = self.apply(plan)
        self.assertEqual(result['reason'], 'INTERNAL_ERROR')
        self.assertFalse(result['archive_published'])
        self.assertTrue(self.original.exists())
        self.assertNotIn('private failure', A.canonical(result))

    def test_source_changed_after_publication_never_deleted(self):
        original_publish = A.publish
        def publish(fd):
            original_publish(fd)
            (self.original / 'engine.db').chmod(0o600)
        plan = self.plan()
        with mock.patch.object(A, 'publish', side_effect=publish):
            result = self.apply(plan)
        self.assertEqual(result['reason'], 'SOURCE_CHANGED')
        self.assertTrue(result['archive_published'])
        self.assertFalse(result['cleanup_started'])
        self.restore(result)

    def test_partial_cleanup_error_retains_full_recoverable_archive(self):
        unlink = os.unlink
        def fail_second(name, *args, **kwargs):
            if name == 'engine.db-shm':
                raise OSError('synthetic deletion interruption')
            return unlink(name, *args, **kwargs)
        plan = self.plan()
        with mock.patch.object(A.os, 'unlink', side_effect=fail_second):
            result = self.apply(plan)
        self.assertEqual(result['status'], 'refused')
        self.assertTrue(result['archive_verified'])
        self.assertEqual(result['removed_files'], 1)
        self.assertFalse(result['cleanup_complete'])
        self.restore(result)

    def test_timeout_refuses_without_source_deletion(self):
        clock = mock.Mock(side_effect=[0, A.TIME_BUDGET + 1])
        result = self.execute(budget=A.Budget(clock))
        self.assertEqual(result['reason'], 'TIME_LIMIT')
        self.assertTrue(self.original.exists())

    def test_protected_container_change_refused(self):
        snapshot = A.snapshot
        calls = 0
        def changed(*args):
            nonlocal calls
            calls += 1
            value = snapshot(*args)
            if calls > 1:
                value['containers'][0]['pid'] += 1
            return value
        with mock.patch.object(A, 'snapshot', side_effect=changed):
            result = self.execute()
        self.assertEqual(result['reason'], 'PROTECTED_CHANGED')
        self.assertFalse(self.archives.exists())

    def test_restore_rejects_overwrite_and_bad_receipt_hash(self):
        result = self.apply()
        target = self.restore(result)
        with self.assertRaises(FileExistsError):
            self.restore(result)
        self.assertEqual((target / 'engine.db').read_bytes(), self.payloads['engine.db'])
        with self.assertRaises(A.Refused):
            A.restore_isolated(str(self.archive), str(self.base), 'restore-check-1111111111111111', '0' * 64)
        self.assertFalse((self.base / 'restore-check-1111111111111111').exists())

    def test_restore_malformed_metadata_rejected_before_target_creation(self):
        result = self.apply()
        path = self.archive / 'archive-manifest.json'
        original = json.loads(path.read_bytes())
        for key, bad in [('mode', 0o4600), ('uid', 12345), ('gid', 12345),
                         ('mtime_ns', True), ('size', -1), ('links', 2)]:
            with self.subTest(key=key):
                plan = json.loads(A.canonical(original))
                plan['files']['engine.db']['source'][key] = bad
                raw = A.canonical(plan).encode()
                path.write_bytes(raw)
                result['archive_manifest_sha256'] = A.digest(raw)
                with self.assertRaises(A.Refused):
                    self.restore(result)
                self.assertFalse((self.base / 'restore-check-0123456789abcdef').exists())

    def test_gzip_trailing_member_and_truncation_rejected(self):
        result = self.apply()
        path = self.archive / 'engine.db.gz'
        original = path.read_bytes()
        manifest_path = self.archive / 'archive-manifest.json'
        plan = json.loads(manifest_path.read_bytes())
        for content in (original[:-1], original + original, original + b'junk'):
            with self.subTest(size=len(content)):
                path.write_bytes(content)
                plan['files']['engine.db'].update(gzip_size=len(content), gzip_sha256=A.digest(content))
                raw = A.canonical(plan).encode()
                manifest_path.write_bytes(raw)
                result['archive_manifest_sha256'] = A.digest(raw)
                with self.assertRaises(A.Refused):
                    self.restore(result)
                self.assertFalse((self.base / 'restore-check-0123456789abcdef').exists())

    def test_receipt_closed_types_and_status(self):
        valid = self.plan()
        for key, bad in [('unknown', 'private'), ('source_bytes', True), ('plan_sha256', 'bad'),
                         ('cleanup_started', True), ('database_opened', True), ('reason', 'raw error')]:
            with self.subTest(key=key):
                value = dict(valid)
                value[key] = bad
                with self.assertRaises(A.Refused):
                    A.validate_report(value)

    def test_main_does_not_expose_restore_mode(self):
        with mock.patch.object(A, 'deployment_lock', return_value=contextlib.nullcontext()), \
                mock.patch.object(A.os, 'geteuid', return_value=A.ROOT_UID), \
                mock.patch.object(A.os, 'nice'), mock.patch.object(A.os, 'umask'), \
                mock.patch('builtins.print') as output:
            self.assertEqual(A.main(['restore', '', '']), 2)
        value = json.loads(output.call_args.args[0])
        self.assertEqual(value['reason'], 'INPUT_REFUSED')

    def test_deployment_lock_excludes_second_holder(self):
        lockdir = self.base / 'lockdir'
        lockdir.mkdir(mode=0o700)
        with mock.patch.object(A, 'LOCK_PARENT', str(lockdir)):
            with A.deployment_lock():
                with self.assertRaisesRegex(A.Refused, 'LOCKED'):
                    with A.deployment_lock():
                        self.fail('second lock acquired')


if __name__ == '__main__':
    unittest.main()
