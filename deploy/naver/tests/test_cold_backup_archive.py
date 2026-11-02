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
    scope = A.SCOPE

    def setUp(self):
        self.profile = A.profile_for(self.scope)
        self.temp = tempfile.TemporaryDirectory(prefix='naver-archive-test-', dir=Path.home())
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.backups = self.base / 'backups'
        self.archives = self.base / 'archives'
        self.backups.mkdir(mode=0o700)
        self.original = self.backups / self.profile.backup
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
        kwargs.setdefault('scope', self.scope)
        return A.execute(mode, plan, confirm, runner=self.runner, free=self.free, **kwargs)

    def plan(self):
        result = self.execute()
        self.assertEqual(result['status'], 'planned', result)
        return result

    def apply(self, plan=None):
        return self.execute('apply', (plan or self.plan())['plan_sha256'], self.profile.confirm)

    @property
    def archive(self):
        return self.archives / self.profile.archive

    def restore(self, receipt, target='restore-check-0123456789abcdef'):
        A.restore_isolated(str(self.archive), str(self.base), target, receipt['archive_manifest_sha256'], scope=self.scope)
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
        for plan, confirm, reason in [('0' * 64, self.profile.confirm, 'PLAN_MISMATCH'),
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


    def other_profile(self):
        return next(profile for profile in A.PROFILES.values() if profile.scope != self.scope)

    @unittest.skipUnless(os.geteuid() == 0, 'root Linux ownership fixture')
    def test_engine_uid_gid_10001_round_trip_on_root_linux(self):
        for name in self.payloads:
            path = self.original / name
            os.chown(path, 10001, 10001)
            self.identities[name] = A.identity(path.stat())
        result = self.apply()
        self.assertEqual(result['status'], 'applied', result)
        restored = self.restore(result)
        for name in self.payloads:
            path = restored / name
            self.assertEqual(path.read_bytes(), self.payloads[name])
            actual = A.identity(path.stat())
            for key in ('uid', 'gid', 'mode', 'mtime_ns', 'size'):
                self.assertEqual(actual[key], self.identities[name][key])

    def test_scope_matches_source_archive_manifest_and_receipt(self):
        plan = self.plan()
        self.assertEqual(plan['scope'], self.scope)
        A.validate_report(plan, expected_scope=self.scope)
        with self.assertRaises(A.Refused):
            A.validate_report(plan, expected_scope=self.other_profile().scope)
        applied = self.apply(plan)
        manifest = json.loads((self.archive / 'archive-manifest.json').read_bytes())
        self.assertEqual((manifest['scope'], manifest['backup'], manifest['archive']),
                         (self.scope, self.profile.backup, self.profile.archive))
        self.assertEqual(A.digest(A.canonical(manifest).encode()), plan['plan_sha256'])
        self.assertEqual(applied['archive_manifest_sha256'], plan['plan_sha256'])

    def test_other_profile_confirmation_is_refused_before_any_io(self):
        result = self.execute('apply', 'a' * 64, self.other_profile().confirm)
        self.assertEqual(result['reason'], 'INPUT_REFUSED')
        self.assertEqual(self.commands, [])
        self.assertFalse(self.archives.exists())
        self.assertTrue(self.original.exists())

    def test_other_profile_plan_cannot_authorize_this_source(self):
        # Same bytes and file metadata in both allowlisted source folders are
        # intentionally not interchangeable: the plan binds the fixed scope.
        other = self.other_profile()
        target = self.backups / other.backup
        target.mkdir(mode=0o700)
        for name, data in dict(self.payloads, **{'manifest.json': self.raw}).items():
            path = target / name
            path.write_bytes(data)
            path.chmod(self.identities[name]['mode'])
            os.utime(path, ns=(self.identities[name]['mtime_ns'], self.identities[name]['mtime_ns']))
        other_plan = self.execute(scope=other.scope)
        self.assertEqual(other_plan['status'], 'planned', other_plan)
        own_plan = self.plan()
        self.assertNotEqual(own_plan['plan_sha256'], other_plan['plan_sha256'])
        result = self.apply(other_plan)
        self.assertEqual(result['reason'], 'PLAN_MISMATCH')
        self.assertFalse(self.archives.exists())
        self.assertTrue(self.original.exists())
        self.assertTrue(target.exists())

    def test_other_source_and_published_archive_untouched(self):
        other = self.other_profile()
        other_source = self.backups / other.backup
        other_source.mkdir(mode=0o700)
        other_archive = self.archives / other.archive
        other_archive.mkdir(mode=0o700, parents=True)
        self.archives.chmod(0o700)
        paths = []
        for folder, name in ((other_source, 'engine.db'), (other_archive, 'archive-manifest.json'),
                             (other_archive, 'engine.db.gz')):
            path = folder / name
            path.write_bytes(b'synthetic-other-profile-must-remain')
            path.chmod(0o600)
            paths.append(path)
        before = {str(path): (path.read_bytes(), A.identity(path.stat())) for path in paths}
        directories = {str(path): A.identity(path.stat()) for path in (other_source, other_archive)}
        result = self.apply()
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(before, {str(path): (path.read_bytes(), A.identity(path.stat())) for path in paths})
        self.assertEqual(directories, {str(path): A.identity(path.stat()) for path in (other_source, other_archive)})

    def test_restore_wrong_expected_scope_refused_before_target_creation(self):
        result = self.apply()
        name = 'restore-check-1111111111111111'
        with self.assertRaises(A.Refused):
            A.restore_isolated(str(self.archive), str(self.base), name,
                               result['archive_manifest_sha256'], scope=self.other_profile().scope)
        self.assertFalse((self.base / name).exists())
        self.restore(result)

    def test_restore_scope_path_mixture_refused_even_with_matching_receipt_hash(self):
        result = self.apply()
        path = self.archive / 'archive-manifest.json'
        original = path.read_bytes()
        other = self.other_profile()
        for key, bad in [('scope', other.scope), ('backup', other.backup), ('archive', other.archive),
                         ('backup', '../engine'), ('scope', 'arbitrary-profile')]:
            with self.subTest(key=key, value=bad):
                manifest = json.loads(original)
                manifest[key] = bad
                raw = A.canonical(manifest).encode()
                path.write_bytes(raw)
                result['archive_manifest_sha256'] = A.digest(raw)
                with self.assertRaises(A.Refused):
                    self.restore(result)
                self.assertFalse((self.base / 'restore-check-0123456789abcdef').exists())

    def test_unknown_scope_is_closed_and_does_not_echo_input(self):
        for scope in ('PRIVATE_SYNTHETIC_CANARY', '../engine.db', '', None, [], True):
            with self.subTest(scope=scope):
                result = self.execute(scope=scope)
                self.assertEqual(result['reason'], 'INPUT_REFUSED')
                self.assertNotIn('PRIVATE_SYNTHETIC_CANARY', A.canonical(result))
                self.assertFalse(self.archives.exists())
                self.assertTrue(self.original.exists())
        self.assertEqual(self.commands, [])

    def test_cli_keeps_legacy_c44_and_binds_explicit_scope(self):
        for args, expected_scope in ((['plan', '', ''], A.SCOPE),
                                     (['plan', '', '', self.scope], self.scope)):
            with mock.patch.object(A, 'deployment_lock', return_value=contextlib.nullcontext()), \
                    mock.patch.object(A.os, 'geteuid', return_value=A.ROOT_UID), \
                    mock.patch.object(A.os, 'nice'), mock.patch.object(A.os, 'umask'), \
                    mock.patch.object(A, 'execute', return_value=A.receipt('plan', expected_scope)) as call, \
                    mock.patch('builtins.print') as output:
                self.assertEqual(A.main(args), 2)
                call.assert_called_once_with('plan', '', '', scope=expected_scope)
                self.assertEqual(json.loads(output.call_args.args[0])['scope'], expected_scope)
        with mock.patch.object(A, 'deployment_lock') as lock, mock.patch('builtins.print') as output:
            self.assertEqual(A.main(['plan', '', '', 'PRIVATE_SYNTHETIC_CANARY']), 2)
            lock.assert_not_called()
            value = output.call_args.args[0]
            self.assertNotIn('PRIVATE_SYNTHETIC_CANARY', value)
            self.assertEqual(json.loads(value)['reason'], 'INPUT_REFUSED')


class ArchiveA377Test(ArchiveTest):
    # Run every byte/metadata, corruption, interrupted-cleanup, path and capacity
    # guard above against the second fixed profile as well.
    scope = 'a377-cold-backup-lossless-v1'


class FixedProfileTest(unittest.TestCase):
    def test_only_two_fixed_profiles_and_original_c44_format_preserved(self):
        self.assertEqual(set(A.PROFILES), {'c44-cold-backup-lossless-v1', 'a377-cold-backup-lossless-v1'})
        self.assertEqual(A.profile_for(), A.Profile(A.SCOPE, A.BACKUP_NAME, A.ARCHIVE_NAME, A.CONFIRM))
        self.assertEqual(A.profile_for('a377-cold-backup-lossless-v1'), A.Profile(
            'a377-cold-backup-lossless-v1', '20261102T185748Z-a3770876f746',
            '20261102T185748Z-a3770876f746-v1', 'ARCHIVE_A377_COLD_BACKUP_LOSSLESSLY'))
        with self.assertRaises(TypeError):
            A.PROFILES['arbitrary'] = A.profile_for()
        with self.assertRaises(AttributeError):
            A.profile_for().backup = 'arbitrary'


if __name__ == '__main__':
    unittest.main()
