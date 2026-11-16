"""Independent synthetic contracts; no live /proc, Docker, SSH or database."""
import contextlib
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


SPEC = importlib.util.spec_from_file_location(
    'independent_backup_bundle', Path(__file__).parents[1] / 'backup_bundle.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
CANARY = 'PRIVATE_PATH_MUST_NOT_APPEAR'
TARGET = (os.makedev(1, 7), 9001)
FOLDER = (os.makedev(1, 7), 9002)
UNRELATED = (os.makedev(1, 7), 9999)


def metadata(identity=TARGET):
    return dict(device=identity[0], inode=identity[1], mode=0o600, uid=10001,
                gid=10001, size=4096, links=1, mtime_ns=100, ctime_ns=100,
                allocated_bytes=4096)


def mapping(identity=TARGET, permissions='r--p'):
    device, inode = identity
    return (f'1000-2000 {permissions} 00000000 '
            f'{os.major(device):x}:{os.minor(device):x} {inode} /{CANARY}\n').encode()


class SyntheticProc:
    def __init__(self, people=((101, 101),)):
        self.tasks = {person: dict(generation=(1000 + person[1], 1, 1, 11, 1, 12),
                                  fds={}, maps=b'', cwd=UNRELATED, root=UNRELATED)
                      for person in people}

    def visible(self):
        pass

    def population(self, budget):
        budget.check()
        return {person: row['generation'] for person, row in self.tasks.items()}

    def identity(self, pid, tid):
        if (pid, tid) not in self.tasks:
            raise ProcessLookupError(CANARY)
        return self.tasks[(pid, tid)]['generation']

    def present(self, pid, tid):
        return (pid, tid) in self.tasks

    def fds(self, pid, tid):
        return set(self.tasks[(pid, tid)]['fds'])

    def fd_metadata(self, pid, tid, number):
        return dict(self.tasks[(pid, tid)]['fds'][number][0])

    def fd_flags(self, pid, tid, number):
        return self.tasks[(pid, tid)]['fds'][number][1]

    def fd(self, pid, tid, number):
        return self.fd_metadata(pid, tid, number), self.fd_flags(pid, tid, number)

    def maps(self, pid, tid):
        return self.tasks[(pid, tid)]['maps']

    def link(self, pid, tid, name):
        return self.tasks[(pid, tid)][name]


class AllModeReferenceContractTests(unittest.TestCase):
    def scan(self, proc, **kwargs):
        return B.scan_references({TARGET, FOLDER}, B.A.Budget(clock=lambda: 0),
                                 proc=proc, **kwargs)

    def refused(self, proc, **kwargs):
        with self.assertRaises(B.Refused) as caught:
            self.scan(proc, **kwargs)
        self.assertNotIn(CANARY, str(caught.exception))
        return str(caught.exception)

    def test_every_fd_access_mode_and_same_inode_different_path_are_in_use(self):
        for flags in (0, 1, 2, getattr(os, 'O_PATH', 0o10000000)):
            with self.subTest(flags=flags):
                proc = SyntheticProc()
                proc.tasks[(101, 101)]['fds'][3] = (metadata(), flags)
                with mock.patch.object(proc, 'fd_flags', side_effect=AssertionError('flags unnecessary')) as read:
                    self.assertEqual(self.refused(proc), 'SOURCE_IN_USE')
                read.assert_not_called()

    def test_all_file_backed_maps_and_directory_references_are_in_use(self):
        for perms in ('r--p', 'rw-p', '---p', 'r-xs', 'rw-s'):
            with self.subTest(perms=perms):
                proc = SyntheticProc()
                proc.tasks[(101, 101)]['maps'] = mapping(permissions=perms)
                self.assertEqual(B.mapped_identities(mapping(permissions=perms)), {TARGET})
                self.assertEqual(self.refused(proc), 'SOURCE_IN_USE')
        for kind in ('fd', 'cwd', 'root'):
            with self.subTest(kind=kind):
                proc = SyntheticProc()
                if kind == 'fd':
                    proc.tasks[(101, 101)]['fds'][3] = (metadata(FOLDER), 0)
                else:
                    proc.tasks[(101, 101)][kind] = FOLDER
                self.assertEqual(self.refused(proc), 'SOURCE_IN_USE')

    def test_exact_observer_exception_never_skips_other_fds_or_threads(self):
        proc = SyntheticProc(((101, 101), (101, 102)))
        meta = metadata()
        proc.tasks[(101, 101)]['fds'][3] = (meta, 0)
        exception = (101, 101, proc.identity(101, 101), 3, meta, 0)
        observed = self.scan(proc, observer_fds=(exception,))
        self.assertEqual(observed['reference_count'], 0)
        self.assertEqual(observed['process_generations'], 2)
        for person, number in (((101, 101), 4), ((101, 102), 3)):
            with self.subTest(person=person, number=number):
                proc.tasks[person]['fds'][number] = (meta, 0)
                self.assertEqual(self.refused(proc, observer_fds=(exception,)), 'SOURCE_IN_USE')
                del proc.tasks[person]['fds'][number]
        for index, replacement in ((2, (999, 1, 1, 11, 1, 12)),
                                   (4, dict(meta, mtime_ns=101)), (5, 2)):
            changed = list(exception)
            changed[index] = replacement
            with self.subTest(index=index):
                self.assertEqual(self.refused(proc, observer_fds=(tuple(changed),)), 'SOURCE_IN_USE')

    def test_observer_descriptor_identity_is_rechecked(self):
        proc = SyntheticProc()
        meta = metadata()
        proc.tasks[(101, 101)]['fds'][3] = (meta, 0)
        exception = (101, 101, proc.identity(101, 101), 3, meta, 0)
        with mock.patch.object(proc, 'fd', return_value=(dict(meta, inode=9003), 0)) as reread:
            self.assertEqual(self.refused(proc, observer_fds=(exception,)), 'PROC_CHANGED')
        reread.assert_called_once_with(101, 101, 3)

    def test_unknown_visibility_permissions_or_live_task_read_gaps_refuse(self):
        for method, error in (('visible', B.Refused('PROC_UNAVAILABLE')),
                              ('population', PermissionError(CANARY)),
                              ('fds', PermissionError(CANARY)),
                              ('maps', PermissionError(CANARY)),
                              ('fds', FileNotFoundError(CANARY)),
                              ('maps', FileNotFoundError(CANARY))):
            with self.subTest(method=method, error=type(error).__name__):
                proc = SyntheticProc()
                with mock.patch.object(proc, method, side_effect=error):
                    self.refused(proc)

    def test_still_listed_descriptor_cannot_be_treated_as_a_closed_fd(self):
        proc = SyntheticProc()
        proc.tasks[(101, 101)]['fds'][3] = (metadata(), 0)
        with mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(CANARY)):
            self.refused(proc)

    def test_closed_descriptor_is_bounded_churn_when_no_longer_in_the_table(self):
        proc = SyntheticProc()
        listings = iter(({3}, set()))
        with mock.patch.object(proc, 'fds', side_effect=lambda *args: next(listings, set())), \
                mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(CANARY)):
            result = self.scan(proc)
        self.assertEqual(result['reference_count'], 0)
        self.assertEqual(result['exited_generations'], 0)

    def test_confirmed_exit_is_counted_but_live_generation_change_refuses(self):
        proc = SyntheticProc()
        def exited(pid, tid):
            proc.tasks.pop((pid, tid), None)
            raise ProcessLookupError(CANARY)
        with mock.patch.object(proc, 'identity', side_effect=exited):
            observed = self.scan(proc)
        self.assertEqual(observed['exited_generations'], 1)
        proc = SyntheticProc()
        generation = proc.identity(101, 101)
        with mock.patch.object(proc, 'identity', return_value=(generation[0] + 1,) + generation[1:]):
            self.assertEqual(self.refused(proc), 'PROC_CHANGED')

    def test_repeated_missing_identity_never_proves_exit_of_a_present_task(self):
        proc = SyntheticProc()
        with self.subTest(adapter='synthetic'), \
                mock.patch.object(proc, 'identity', side_effect=FileNotFoundError(CANARY)):
            self.refused(proc)
        self.assertIn((101, 101), proc.tasks)
        with tempfile.TemporaryDirectory() as temporary:
            task = Path(temporary) / '101' / 'task' / '101'
            task.mkdir(parents=True)
            native = B.Proc(temporary)
            population = {(101, 101): (1101, 1, 1, 11, 1, 12)}
            with self.subTest(adapter='native_task_directory'), \
                    mock.patch.object(native, 'visible', return_value=None), \
                    mock.patch.object(native, 'population', return_value=population), \
                    mock.patch.object(native, 'identity', side_effect=FileNotFoundError(CANARY)):
                self.refused(native)
            self.assertTrue(task.is_dir())
            native_stat, native_lstat = os.stat, os.lstat
            def denied(delegate, path, *args, **kwargs):
                if Path(path) == task:
                    raise PermissionError(CANARY)
                return delegate(path, *args, **kwargs)
            with self.subTest(adapter='native_inaccessible_task_directory'), \
                    mock.patch.object(native, 'visible', return_value=None), \
                    mock.patch.object(native, 'population', return_value=population), \
                    mock.patch.object(native, 'identity', side_effect=FileNotFoundError(CANARY)), \
                    mock.patch.object(B.os, 'stat', side_effect=lambda *a, **k: denied(native_stat, *a, **k)), \
                    mock.patch.object(B.os, 'lstat', side_effect=lambda *a, **k: denied(native_lstat, *a, **k)):
                self.refused(native)
            self.assertTrue(task.is_dir())

    def test_late_thread_and_pid_reuse_are_observed_or_refused_at_closure(self):
        for late in ((202, 202), (101, 102)):
            with self.subTest(late=late):
                proc = SyntheticProc(((101, 101), late))
                both = proc.population(B.A.Budget(clock=lambda: 0))
                first = {(101, 101): both[(101, 101)]}
                with mock.patch.object(proc, 'population', side_effect=[first, first, both, both]):
                    result = self.scan(proc)
                self.assertEqual(result['late_generations'], 1)
                self.assertEqual(result['process_generations'], 2)
                proc.tasks[late]['fds'][3] = (metadata(), 0)
                with mock.patch.object(proc, 'population', side_effect=[first, first, both, both]):
                    self.assertEqual(self.refused(proc), 'SOURCE_IN_USE')
        proc = SyntheticProc()
        first = proc.population(B.A.Budget(clock=lambda: 0))
        replaced = {(101, 101): (99999, 1, 1, 11, 1, 12)}
        with mock.patch.object(proc, 'population', side_effect=[first, first, first, replaced]):
            self.assertEqual(self.refused(proc), 'PROC_CHANGED')

    def test_fd_birth_is_scanned_and_unresolved_repeated_birth_refuses(self):
        proc = SyntheticProc()
        proc.tasks[(101, 101)]['fds'][3] = (metadata(), 0)
        with mock.patch.object(proc, 'fds', side_effect=[set(), {3}, {3}]):
            self.assertEqual(self.refused(proc), 'SOURCE_IN_USE')
        proc.tasks[(101, 101)]['fds'][3] = (metadata(UNRELATED), 0)
        with mock.patch.object(proc, 'fds', side_effect=[set(), {3}, {3, 4}]):
            self.assertEqual(self.refused(proc), 'PROC_CHANGED')

    def test_shared_deadline_and_global_generation_fd_tail_caps(self):
        proc = SyntheticProc()
        clock = [0]
        budget = B.A.Budget(clock=lambda: clock[0])
        native = proc.population
        calls = 0
        def population(shared):
            nonlocal calls
            calls += 1
            if calls == 2:
                clock[0] = 601
            return native(shared)
        with mock.patch.object(proc, 'population', side_effect=population), self.assertRaisesRegex(B.Refused, 'TIME_LIMIT'):
            B.scan_references({TARGET}, budget, proc=proc)
        with mock.patch.object(B, 'MAX_PROCESSES', 1):
            self.assertEqual(self.refused(SyntheticProc(((101, 101), (101, 102)))), 'PROC_LIMIT')
        proc = SyntheticProc()
        proc.tasks[(101, 101)]['fds'][3] = (metadata(UNRELATED), 0)
        with mock.patch.object(B, 'MAX_FDS', 1):
            self.assertEqual(self.refused(proc), 'PROC_LIMIT')
        proc = SyntheticProc(((101, 101), (202, 202)))
        both = proc.population(B.A.Budget(clock=lambda: 0))
        first = {(101, 101): both[(101, 101)]}
        with mock.patch.object(B, 'MAX_LATE', 0), mock.patch.object(proc, 'population', side_effect=[first, first, both]):
            self.assertEqual(self.refused(proc), 'PROC_LIMIT')

    def test_maps_parser_rejects_unbounded_or_malformed_input_without_names(self):
        self.assertEqual(B.mapped_identities(b'1000-2000 rw-p 0 00:00 0 [anonymous]\n'), set())
        self.assertEqual(B.mapped_identities(mapping() + mapping()), {TARGET})
        for raw in (CANARY, b'x' * (B.MAX_MAPS + 1), mapping(permissions='r--z'),
                    b'1000-2000 r--p 0 00:00 not-an-inode /' + CANARY.encode()):
            with self.subTest(kind=type(raw).__name__), self.assertRaises(B.Refused) as caught:
                B.mapped_identities(raw)
            self.assertNotIn(CANARY, str(caught.exception))

    def test_native_proc_adapter_uses_task_tables_and_enforces_local_caps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = root / '101' / 'task' / '102'
            (task / 'fd').mkdir(parents=True)
            (task / 'fdinfo').mkdir()
            payload = root / 'opaque'
            payload.write_bytes(b'SYNTHETIC_NOT_A_DATABASE')
            (task / 'fd' / '3').symlink_to(payload)
            (task / 'fdinfo' / '3').write_bytes(b'flags:\t10000000\nmnt_id:\t1\n')
            proc = B.Proc(root)
            self.assertEqual(proc.fds(101, 102), {3})
            opened = []
            native_open = os.open
            def open_metadata(path, flags, *args, **kwargs):
                opened.append(Path(path))
                return native_open(path, flags, *args, **kwargs)
            with mock.patch.object(B.os, 'open', side_effect=open_metadata):
                info, flags = proc.fd(101, 102, 3)
            self.assertEqual(opened, [task / 'fdinfo' / '3'])
            self.assertEqual((info['device'], info['inode']), (payload.stat().st_dev, payload.stat().st_ino))
            self.assertEqual(flags, 0o10000000)
            with mock.patch.object(B, 'MAX_TABLE_FDS', 0), self.assertRaisesRegex(B.Refused, 'PROC_LIMIT'):
                proc.fds(101, 102)
            with mock.patch.object(proc, 'identity', return_value=(1, 1, 1, 1, 1, 1)), mock.patch.object(B, 'MAX_PROCESSES', 0), self.assertRaisesRegex(B.Refused, 'PROC_LIMIT'):
                proc.population(B.A.Budget(clock=lambda: 0))
            (task / 'fdinfo' / '3').write_bytes(b'flags:\t0\nflags:\t2\n')
            with self.assertRaisesRegex(B.Refused, 'PROC_INVALID'):
                proc.fd(101, 102, 3)

    def test_population_cannot_omit_a_still_visible_unidentified_thread(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = root / '101' / 'task' / '102'
            task.mkdir(parents=True)
            proc = B.Proc(root)
            with mock.patch.object(proc, 'identity', side_effect=FileNotFoundError(CANARY)):
                with self.assertRaises(B.Refused) as caught:
                    proc.population(B.A.Budget(clock=lambda: 0))
            self.assertNotIn(CANARY, str(caught.exception))
            def gone(pid, tid):
                task.rmdir()
                raise ProcessLookupError(CANARY)
            with mock.patch.object(proc, 'identity', side_effect=gone):
                self.assertEqual(proc.population(B.A.Budget(clock=lambda: 0)), {})


class BundlePreservationContractTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        temporary = self.stack.enter_context(tempfile.TemporaryDirectory(
            prefix='bundle-independent-', dir=Path.home()))
        self.base = Path(temporary)
        self.backups, self.archives = self.base / 'cold', self.base / 'archives'
        self.regular = self.base / 'regular'
        for path in (self.backups, self.archives, self.regular):
            path.mkdir(mode=0o700)
        self.local = self.regular / 'local'
        self.local.mkdir(mode=0o700)
        self.profile = B.A.profile_for(B.DEPLOYMENT_SCOPE)
        self.deployment = self.backups / self.profile.backup
        self.deployment.mkdir(mode=0o700)
        self.building = self.local / '.building-abcdefgh'
        self.building.mkdir(mode=0o700)
        self.payloads = {'engine.db': b'SYNTHETIC_DEPLOYMENT_BYTES\0' * 1024,
                         'snapshot.sqlite': bytes(range(256)) * 32}
        for path, data in ((self.deployment / 'engine.db', self.payloads['engine.db']),
                           (self.building / 'snapshot.sqlite', self.payloads['snapshot.sqlite'])):
            path.write_bytes(data)
            path.chmod(0o600)
            os.utime(path, ns=(1700000000123456789, 1700000000123456789))
        self.raw_manifest = (json.dumps({'engine.db': {
            'size': len(self.payloads['engine.db']),
            'sha256': hashlib.sha256(self.payloads['engine.db']).hexdigest()}},
            indent=3) + '\n').encode()
        manifest = self.deployment / 'manifest.json'
        manifest.write_bytes(self.raw_manifest)
        manifest.chmod(0o600)
        os.utime(manifest, ns=(1700000000234567890, 1700000000234567890))
        self.protected_zips = []
        for index in range(3):
            path = self.local / f'naver-20261101T010203Z-{index:032x}.zip'
            path.write_bytes(b'SYNTHETIC_PROTECTED_ZIP' + bytes([index]))
            path.chmod(0o600)
            self.protected_zips.append(path)
        os.utime(self.building, ns=(1700000000345678000, 1700000000345678000))
        self.stack.enter_context(mock.patch.multiple(B.A, ROOT_UID=os.getuid(), ROOT_GID=os.getgid(),
            BACKUP_PARENT=str(self.backups), ARCHIVE_PARENT=str(self.archives)))
        self.stack.enter_context(mock.patch.multiple(B, ENGINE_UID=os.getuid(), ENGINE_GID=os.getgid(),
            BACKUP_ROOT=str(self.regular), CANDIDATE_BYTES=len(self.payloads['snapshot.sqlite']),
            CANDIDATE_MTIME_US=self.building.stat().st_mtime_ns // 1000))
        self.stack.enter_context(mock.patch.object(B.A.subprocess, 'run',
            side_effect=AssertionError('external commands forbidden')))
        self.assertEqual((self.building / 'snapshot.sqlite').stat().st_blocks * 512,
                         len(self.payloads['snapshot.sqlite']))
        self.protected = dict(containers=[dict(id=f'{i:064x}', image=f'sha256:{i + 10:064x}',
            running=True, pid=i + 1000, started='2026-11-03T01:00:00Z', restarts=0)
            for i in range(1, 6)], images=[f'sha256:{i + 10:064x}' for i in range(1, 6)])
        self.source_before = self.source_state()
        self.zip_before = self.zip_state()
        self.budget = B.A.Budget(clock=lambda: 0)

    def state(self, path):
        return B.A.identity(path.stat()), path.read_bytes() if path.is_file() else None

    def source_state(self):
        return {str(path.relative_to(self.base)): self.state(path)
                for folder in (self.deployment, self.building)
                for path in (folder, *sorted(folder.iterdir()))}

    def zip_state(self):
        return {path.name: self.state(path) for path in self.protected_zips}

    @property
    def bundle(self):
        return self.archives / B.ARCHIVE_NAME

    def runner(self, command):
        self.assertEqual(command[:2], B.A.DOCKER)
        args = command[2:]
        if args == ('ps', '-aq', '--no-trunc'):
            value = '\n'.join(row['id'] for row in self.protected['containers'])
        elif args == ('image', 'ls', '-aq', '--no-trunc'):
            value = '\n'.join(self.protected['images'])
        else:
            self.assertEqual(args[:4], ('inspect', '--type=container', '--format', B.A.INSPECT_FORMAT))
            self.assertEqual(set(args[4:]), {row['id'] for row in self.protected['containers']})
            value = '\n'.join(B.A.canonical(row) for row in self.protected['containers'])
        return types.SimpleNamespace(returncode=0, stdout=value.encode(), stderr=b'')

    def execute(self, mode='plan', plan=None, **kwargs):
        kwargs.setdefault('runner', self.runner)
        kwargs.setdefault('free', lambda: 10 * 1024 ** 3)
        kwargs.setdefault('budget', self.budget)
        # Producer/source-generation and all-mode scanning have independent
        # fixtures. This seam isolates actual filesystem preservation only.
        kwargs.setdefault('producer_probe', lambda *args: {'synthetic_generation': 1})
        kwargs.setdefault('reference_probe', lambda *args: None)
        if mode == 'plan':
            return B.execute(mode, **kwargs)
        return B.execute(mode, plan['plan_sha256'], B.CONFIRM,
                         B.A.canonical(plan['plan']), **kwargs)

    def planned(self):
        result = self.execute()
        self.assertEqual(result['status'], 'planned', result)
        self.assertFalse(self.bundle.exists())
        self.assertEqual(self.source_state(), self.source_before)
        return result

    def assert_sources_untouched(self):
        self.assertEqual(self.source_state(), self.source_before)
        self.assertEqual(self.zip_state(), self.zip_before)

    def restore(self, result):
        manifest = json.loads((self.bundle / 'archive-manifest.json').read_bytes())
        self.assertEqual(B.hash_object(manifest), result['archive_manifest_sha256'])
        B.A.restore_isolated(str(self.bundle / 'deployment'), str(self.base),
            'restore-check-1111111111111111', manifest['deployment_archive_sha256'],
            scope=B.DEPLOYMENT_SCOPE)
        B.restore_snapshot_isolated(str(self.bundle / 'snapshot'), str(self.base),
            'restore-check-2222222222222222', manifest['snapshot_archive_sha256'])
        return self.base / 'restore-check-1111111111111111', self.base / 'restore-check-2222222222222222'

    def test_two_real_gzip_archives_restore_exact_bytes_manifest_and_metadata(self):
        planned = self.planned()
        compress = B.A.compress
        compressed = []
        def measured(fd, budget, sink, *, level=1):
            compressed.append(level)
            return compress(fd, budget, sink, level=level)
        with mock.patch.object(B.A, 'compress', side_effect=measured):
            result = self.execute('apply', planned)
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(compressed, [6, 6])
        self.assertEqual(result['removed_files'], 3)
        self.assertFalse(self.deployment.exists())
        self.assertFalse(self.building.exists())
        self.assertEqual(self.zip_state(), self.zip_before)
        for child, name in (('deployment', 'engine.db'), ('snapshot', 'snapshot.sqlite')):
            compressed_bytes = (self.bundle / child / (name + '.gz')).read_bytes()
            self.assertEqual(gzip.decompress(compressed_bytes), self.payloads[name])
        self.assertEqual((self.bundle / 'deployment' / 'source-manifest.json').read_bytes(), self.raw_manifest)
        deployment, snapshot = self.restore(result)
        for target, original in ((deployment, self.deployment), (snapshot, self.building)):
            for path in (target, *target.iterdir()):
                source_path = original if path == target else original / path.name
                before, raw = self.source_before[str(source_path.relative_to(self.base))]
                after, actual = self.state(path)
                self.assertEqual(actual, raw)
                for key in ('uid', 'gid', 'mode', 'mtime_ns') + (() if raw is None else ('size',)):
                    self.assertEqual(after[key], before[key], (path.name, key))

    def test_both_round_trips_and_all_markers_precede_first_source_unlink(self):
        plan = self.planned()
        events = []
        verify_deployment, verify_snapshot = B.A.verify_archive, B.verify_snapshot_archive
        remove_deployment, remove_snapshot = B.A.remove_source, B.remove_snapshot
        def deployment_verified(*args, **kwargs):
            value = verify_deployment(*args, **kwargs)
            events.append('deployment_verified')
            return value
        def snapshot_verified(*args, **kwargs):
            value = verify_snapshot(*args, **kwargs)
            events.append('snapshot_verified')
            return value
        def remove(callback, label, *args):
            self.assertIn('deployment_verified', events)
            self.assertIn('snapshot_verified', events)
            for folder in (self.bundle, self.bundle / 'deployment', self.bundle / 'snapshot'):
                self.assertTrue((folder / 'archive-manifest.json').is_file())
            events.append(label)
            return callback(*args)
        with mock.patch.object(B.A, 'verify_archive', side_effect=deployment_verified), \
                mock.patch.object(B, 'verify_snapshot_archive', side_effect=snapshot_verified), \
                mock.patch.object(B.A, 'remove_source', side_effect=lambda *a: remove(remove_deployment, 'deployment_unlink', *a)), \
                mock.patch.object(B, 'remove_snapshot', side_effect=lambda *a: remove(remove_snapshot, 'snapshot_unlink', *a)):
            result = self.execute('apply', plan)
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(events, ['deployment_verified', 'snapshot_verified', 'deployment_unlink', 'snapshot_unlink'])

    def test_failed_second_round_trip_keeps_both_originals_and_unpublished_artifacts(self):
        plan = self.planned()
        verify = B.verify_snapshot_archive
        def corrupt_then_verify(folder, *args):
            fd = os.open('snapshot.sqlite.gz', os.O_WRONLY | os.O_NOFOLLOW, dir_fd=folder)
            try:
                os.write(fd, b'BAD')
            finally:
                os.close(fd)
            return verify(folder, *args)
        with mock.patch.object(B, 'verify_snapshot_archive', side_effect=corrupt_then_verify):
            result = self.execute('apply', plan)
        self.assertEqual((result['status'], result['reason']), ('refused', 'ARCHIVE_VERIFY_FAILED'))
        self.assertTrue(result['archive_started'])
        self.assertFalse(result['archive_published'])
        self.assertFalse(result['cleanup_started'])
        self.assert_sources_untouched()
        for folder in (self.bundle, self.bundle / 'deployment', self.bundle / 'snapshot'):
            self.assertFalse((folder / 'archive-manifest.json').exists())
        self.assertTrue((self.bundle / 'deployment' / 'engine.db.gz').is_file())
        self.assertTrue((self.bundle / 'snapshot' / 'snapshot.sqlite.gz').is_file())

    def test_snapshot_restore_rejects_truncation_and_changed_raw_bytes_with_rehashed_envelope(self):
        result = self.execute('apply', self.planned())
        self.assertEqual(result['status'], 'applied', result)
        folder = self.bundle / 'snapshot'
        compressed = folder / 'snapshot.sqlite.gz'
        manifest_path = folder / 'archive-manifest.json'
        original_manifest = manifest_path.read_bytes()
        original_compressed = compressed.read_bytes()
        restore_name = 'restore-check-3333333333333333'
        for kind in ('truncated', 'different_raw_bytes'):
            with self.subTest(kind=kind):
                manifest = json.loads(original_manifest)
                if kind == 'truncated':
                    changed = original_compressed[:-1]
                else:
                    different = b'X' + self.payloads['snapshot.sqlite'][1:]
                    changed = gzip.compress(different, compresslevel=6, mtime=0)
                    # Even an attacker-provided matching outer receipt and
                    # compressed hash cannot replace the promised raw bytes.
                    manifest['file']['gzip_size'] = len(changed)
                    manifest['file']['gzip_sha256'] = hashlib.sha256(changed).hexdigest()
                compressed.write_bytes(changed)
                manifest_path.write_bytes(B.A.canonical(manifest).encode())
                before = {path.name: self.state(path) for path in folder.iterdir()}
                with self.assertRaises(B.Refused):
                    B.restore_snapshot_isolated(str(folder), str(self.base), restore_name,
                        hashlib.sha256(manifest_path.read_bytes()).hexdigest())
                self.assertFalse((self.base / restore_name).exists())
                self.assertEqual({path.name: self.state(path) for path in folder.iterdir()}, before)

    def test_snapshot_restore_closed_manifest_and_existing_target_never_overwrite(self):
        result = self.execute('apply', self.planned())
        self.assertEqual(result['status'], 'applied', result)
        folder = self.bundle / 'snapshot'
        path = folder / 'archive-manifest.json'
        original = path.read_bytes()
        variants = []
        for kind, value in (('level', True), ('level', 1), ('owner', os.getuid() + 100),
                            ('kind', 'sqlite-verified'), ('extra', CANARY)):
            candidate = json.loads(original)
            if kind == 'level':
                candidate['codec']['level'] = value
            elif kind == 'owner':
                candidate['source_file']['uid'] = value
            else:
                candidate[kind] = value
            variants.append(candidate)
        target_name = 'restore-check-4444444444444444'
        for candidate in variants:
            with self.subTest(kind=candidate.get('kind')):
                raw = B.A.canonical(candidate).encode()
                path.write_bytes(raw)
                with self.assertRaises(B.Refused):
                    B.restore_snapshot_isolated(str(folder), str(self.base), target_name,
                                                hashlib.sha256(raw).hexdigest())
                self.assertFalse((self.base / target_name).exists())
        path.write_bytes(original)
        target = self.base / target_name
        target.mkdir(mode=0o700)
        sentinel = target / 'keep'
        sentinel.write_bytes(b'PRESERVE_EXISTING_RESTORE_TARGET')
        before = (self.state(target), self.state(sentinel))
        with self.assertRaises((B.Refused, OSError)):
            B.restore_snapshot_isolated(str(folder), str(self.base), target_name,
                                        hashlib.sha256(original).hexdigest())
        self.assertEqual((self.state(target), self.state(sentinel)), before)

    def test_shared_timeout_after_real_compression_preserves_both_originals(self):
        plan = self.planned()
        clock = [0]
        budget = B.A.Budget(clock=lambda: clock[0])
        compress = B.A.compress
        def expire_after_compress(*args, **kwargs):
            result = compress(*args, **kwargs)
            clock[0] = 601
            return result
        with mock.patch.object(B.A, 'compress', side_effect=expire_after_compress):
            result = self.execute('apply', plan, budget=budget)
        self.assertEqual(result['reason'], 'TIME_LIMIT', result)
        self.assertFalse(result['archive_published'])
        self.assertFalse(result['cleanup_started'])
        self.assert_sources_untouched()

    def test_shared_timeout_during_actual_decoder_preserves_both_originals(self):
        plan = self.planned()
        clock, decoded = [0], []
        budget = B.A.Budget(clock=lambda: clock[0])
        native = B.A.zlib.decompressobj
        class Decoder:
            def __init__(self, *args, **kwargs):
                self.decoder = native(*args, **kwargs)
            def __getattr__(self, name):
                return getattr(self.decoder, name)
            def decompress(self, *args, **kwargs):
                data = self.decoder.decompress(*args, **kwargs)
                decoded.append(len(data))
                clock[0] = 601
                return data
        with mock.patch.object(B.A.zlib, 'decompressobj', Decoder):
            result = self.execute('apply', plan, budget=budget)
        self.assertTrue(decoded)
        self.assertGreater(sum(decoded), 0)
        self.assertEqual(result['reason'], 'TIME_LIMIT', result)
        self.assertFalse(result['archive_published'])
        self.assertFalse(result['cleanup_started'])
        self.assert_sources_untouched()

    def test_timeout_after_publication_keeps_recoverable_bundle_and_refuses_retry(self):
        plan = self.planned()
        clock = [0]
        budget = B.A.Budget(clock=lambda: clock[0])
        stage = B.stage_bundle
        def expire_after_stage(*args, **kwargs):
            manifest = stage(*args, **kwargs)
            clock[0] = 601
            return manifest
        with mock.patch.object(B, 'stage_bundle', side_effect=expire_after_stage):
            result = self.execute('apply', plan, budget=budget)
        self.assertEqual(result['reason'], 'TIME_LIMIT', result)
        self.assertTrue(result['archive_published'])
        self.assertTrue(result['archive_verified'])
        self.assertFalse(result['cleanup_started'])
        self.assert_sources_untouched()
        archive_before = {str(path.relative_to(self.bundle)): self.state(path)
                          for path in (self.bundle, *sorted(self.bundle.rglob('*')))}
        self.restore(result)
        retried = self.execute('apply', plan)
        self.assertEqual(retried['reason'], 'ARCHIVE_EXISTS', retried)
        self.assert_sources_untouched()
        self.assertEqual({str(path.relative_to(self.bundle)): self.state(path)
                          for path in (self.bundle, *sorted(self.bundle.rglob('*')))}, archive_before)

    def test_partial_cleanup_keeps_snapshot_and_both_complete_restore_paths(self):
        plan = self.planned()
        with mock.patch.object(B, 'remove_snapshot', side_effect=OSError(CANARY)):
            result = self.execute('apply', plan)
        self.assertEqual((result['status'], result['reason']), ('refused', 'INTERNAL_ERROR'))
        self.assertTrue(result['archive_verified'])
        self.assertTrue(result['cleanup_started'])
        self.assertFalse(result['cleanup_complete'])
        self.assertEqual(result['removed_files'], 2)
        self.assertFalse(self.deployment.exists())
        for path in (self.building, self.building / 'snapshot.sqlite'):
            self.assertEqual(self.state(path), self.source_before[str(path.relative_to(self.base))])
        self.assertEqual(self.zip_state(), self.zip_before)
        self.assertNotIn(CANARY, B.A.canonical(result))
        deployment, snapshot = self.restore(result)
        self.assertEqual((deployment / 'engine.db').read_bytes(), self.payloads['engine.db'])
        self.assertEqual((snapshot / 'snapshot.sqlite').read_bytes(), self.payloads['snapshot.sqlite'])


    @contextlib.contextmanager
    def metadata_only(self):
        payload_ids = {(path.stat().st_dev, path.stat().st_ino) for path in
                       (self.deployment / 'engine.db', self.building / 'snapshot.sqlite')}
        native_read = os.read
        def read(fd, size):
            info = os.fstat(fd)
            self.assertNotIn((info.st_dev, info.st_ino), payload_ids,
                             'diagnose must not read backup payloads')
            return native_read(fd, size)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(B.os, 'read', side_effect=read))
            forbidden = []
            for owner, names in ((B, ('make_plan', 'check_plan_sources', 'rehash', 'new_bundle',
                                     'stage_bundle', 'remove_snapshot')),
                                 (B.A, ('compress', 'verify_gzip', 'remove_source')),
                                 (B.os, ('mkdir', 'unlink', 'rmdir', 'rename', 'replace'))):
                for name in names:
                    forbidden.append(stack.enter_context(mock.patch.object(
                        owner, name, side_effect=AssertionError('metadata-only boundary'))))
            yield
            for operation in forbidden:
                operation.assert_not_called()
        self.assert_sources_untouched()
        self.assertEqual(list(self.archives.iterdir()), [])

    def diagnose(self, **kwargs):
        defaults = dict(runner=self.runner, free=lambda: 10 * 1024 ** 3, budget=self.budget,
                        producer_probe=lambda *args: {'synthetic_generation': 1},
                        reference_probe=lambda *args: None)
        defaults.update(kwargs)
        return B.execute('diagnose', **defaults)

    def test_diagnose_observes_once_rechecks_generation_and_never_reads_or_writes_payloads(self):
        events = []
        def producer(*args):
            events.append('producer')
            return {'generation': 1}
        def reference(*args):
            events.append('references')
        with self.metadata_only(), mock.patch.object(B.A, 'snapshot', wraps=B.A.snapshot) as protected:
            result = self.diagnose(producer_probe=producer, reference_probe=reference)
        self.assertEqual(events, ['producer', 'references', 'producer'])
        self.assertEqual(protected.call_count, 2)
        self.assertEqual((result['version'], result['status'], result['reason']),
                         (3, 'observed', 'METADATA_READY'))
        self.assertEqual(result['reference_checks'], 1)
        self.assertTrue(result['protected_unchanged'])
        self.assertIsNone(result['limit_diagnostic'])
        self.assertEqual(B.validate_report(result), result)
        for key in ('plan', 'plan_sha256', 'archive_manifest_sha256', 'source_bytes',
                    'source_allocated_bytes', 'compressed_bytes', 'archive_budget_bytes',
                    'projected_free_bytes', 'removed_files'):
            self.assertIsNone(result[key], key)
        for key in ('capacity_ok', 'archive_started', 'archive_published', 'archive_verified',
                    'cleanup_started', 'cleanup_complete', 'database_opened',
                    'services_changed', 'external_network_used'):
            self.assertIs(result[key], False, key)

    def test_diagnose_refusals_emit_only_closed_limit_metadata_without_retry_or_payload_access(self):
        cap = B.MAX_FDS
        for failure, diagnostic in (
                (B.LimitRefused('fd_total', cap, cap + 1),
                 dict(kind='fd_total', cap=cap, observed_lower_bound=cap + 1)),
                (B.Refused('PROC_LIMIT'), None), (B.Refused('PROC_INVALID'), None)):
            with self.subTest(reason=str(failure), diagnostic=diagnostic), self.metadata_only():
                probe = mock.Mock(side_effect=failure)
                producer = mock.Mock(return_value={'generation': 1})
                result = self.diagnose(reference_probe=probe, producer_probe=producer)
            self.assertEqual((result['status'], result['reason']), ('refused', str(failure)))
            self.assertEqual(result['limit_diagnostic'], diagnostic)
            self.assertEqual(result['reference_checks'], 0)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(producer.call_count, 1)
            self.assertIsNone(result['plan'])
            self.assertNotIn(CANARY, B.A.canonical(result))

    def test_diagnose_retains_protected_generation_and_shared_deadline_refusals(self):
        changed = dict(self.protected, images=[])
        for kind in ('protected', 'producer', 'deadline'):
            with self.subTest(kind=kind), self.metadata_only(), contextlib.ExitStack() as stack:
                kwargs = {}
                if kind == 'protected':
                    stack.enter_context(mock.patch.object(B.A, 'snapshot',
                        side_effect=[self.protected, changed]))
                    reason = 'PROTECTED_CHANGED'
                elif kind == 'producer':
                    kwargs['producer_probe'] = mock.Mock(side_effect=[{'generation': 1}, {'generation': 2}])
                    reason = 'PRODUCER_CHANGED'
                else:
                    clock = [0]
                    kwargs['budget'] = B.A.Budget(clock=lambda: clock[0])
                    kwargs['reference_probe'] = lambda *args: clock.__setitem__(0, 601)
                    reason = 'TIME_LIMIT'
                result = self.diagnose(**kwargs)
            self.assertEqual((result['status'], result['reason']), ('refused', reason))
            self.assertEqual(result['reference_checks'], 1)
            self.assertIsNone(result['limit_diagnostic'])

    def test_diagnose_rejects_plan_arguments_before_any_metadata_probe(self):
        for supplied in ({'plan_sha': '1' * 64}, {'confirm': B.CONFIRM}, {'plan_json': '{}'}):
            with self.subTest(field=next(iter(supplied))), self.metadata_only(), \
                    mock.patch.object(B.A, 'snapshot') as snapshot:
                result = self.diagnose(**supplied)
            self.assertEqual(result['reason'], 'INPUT_REFUSED')
            snapshot.assert_not_called()

    def test_receipt_version_three_does_not_upgrade_persisted_plan_or_archive_versions(self):
        plan = self.planned()
        self.assertEqual(plan['version'], 3)
        self.assertEqual(plan['plan']['version'], 1)
        result = self.execute('apply', plan)
        self.assertEqual(result['status'], 'applied', result)
        self.assertEqual(result['version'], 3)
        for parent in (self.bundle, self.bundle / 'deployment', self.bundle / 'snapshot'):
            manifest = json.loads((parent / 'archive-manifest.json').read_bytes())
            self.assertEqual(manifest['version'], 1)


class LimitDiagnosticContractTests(unittest.TestCase):
    def budget(self):
        return B.A.Budget(clock=lambda: 0)

    def limit(self, operation, kind, cap, observed):
        with self.assertRaises(B.LimitRefused) as caught:
            operation()
        self.assertIsInstance(caught.exception, B.Refused)
        self.assertEqual(str(caught.exception), 'PROC_LIMIT')
        value = caught.exception.diagnostic
        self.assertEqual(value, dict(kind=kind, cap=cap, observed_lower_bound=observed))
        self.assertEqual(B.validate_limit_diagnostic(value), value)
        self.assertNotIn(CANARY, B.A.canonical(value))

    @contextlib.contextmanager
    def traced(self, proc):
        with contextlib.ExitStack() as stack:
            calls = {name: stack.enter_context(mock.patch.object(proc, name, wraps=getattr(proc, name)))
                     for name in ('visible', 'population', 'identity', 'present', 'fds',
                                  'fd_metadata', 'fd_flags', 'fd', 'maps', 'link')}
            yield calls

    def counts(self, calls, **expected):
        self.assertEqual({key: call.call_count for key, call in calls.items()},
                         {key: expected.get(key, 0) for key in calls})

    def test_fixed_caps_and_closed_receipt_reject_extra_keys_wrong_types_and_forged_bounds(self):
        self.assertEqual(B.limit_caps(), dict(task_population=4096, task_generations=4096,
            fd_table=4096, fd_total=131072, maps_bytes=262144, late_generations=64,
            stat_bytes=4096, fdinfo_bytes=4096))
        report = B.receipt('diagnose')
        self.assertEqual(set(report), {'version', 'scope', 'mode', 'status', 'reason', 'plan',
            'limit_diagnostic', 'proc_diagnostic', 'source_bytes', 'source_allocated_bytes', 'compressed_bytes',
            'archive_budget_bytes', 'free_before_bytes', 'projected_free_bytes', 'free_after_bytes',
            'removed_files', 'containers', 'images', 'reference_checks', 'plan_sha256',
            'archive_manifest_sha256', 'protected_sha256', 'capacity_ok', 'archive_started',
            'archive_published', 'archive_verified', 'cleanup_started', 'cleanup_complete',
            'protected_unchanged', 'database_opened', 'services_changed', 'external_network_used'})
        for kind, cap in B.limit_caps().items():
            good = dict(kind=kind, cap=cap, observed_lower_bound=cap + 1)
            B.validate_report(dict(report, reason='PROC_LIMIT', limit_diagnostic=good))
            for bad in (dict(good, cap=True), dict(good, cap=cap + 1),
                        dict(good, observed_lower_bound=True), dict(good, observed_lower_bound=cap),
                        dict(good, observed_lower_bound=2 ** 63), dict(good, path=CANARY),
                        dict(good, kind=CANARY), {'kind': kind, 'cap': cap}):
                with self.subTest(kind=kind, bad=bad), self.assertRaises(B.Refused):
                    B.validate_report(dict(report, reason='PROC_LIMIT', limit_diagnostic=bad))
        for kind in ('malformed_fd_table', 'malformed_maps'):
            good = dict(kind=kind, cap=None, observed_lower_bound=None)
            B.validate_report(dict(report, reason='PROC_LIMIT', limit_diagnostic=good))
            for bad in (dict(good, cap=0), dict(good, observed_lower_bound=0)):
                with self.assertRaises(B.Refused):
                    B.validate_limit_diagnostic(bad)
        for bad in (dict(report, version=1), dict(report, version=True), dict(report, extra=CANARY),
                    dict(report, limit_diagnostic=dict(kind='fd_table', cap=4096, observed_lower_bound=4097))):
            with self.assertRaises(B.Refused):
                B.validate_report(bad)
        observed = dict(report, status='observed', reason='METADATA_READY', reference_checks=1,
                        protected_unchanged=True)
        B.validate_report(observed)
        for change in ({'mode': 'plan'}, {'reason': 'PLAN_READY'}, {'reference_checks': 2},
                       {'protected_unchanged': False}, {'source_bytes': 0}, {'plan_sha256': '1' * 64},
                       {'archive_started': True}, {'capacity_ok': True}):
            with self.subTest(change=change), self.assertRaises(B.Refused):
                B.validate_report(dict(observed, **change))

    def test_population_and_fd_table_report_existing_list_sizes_without_relisting(self):
        proc = B.Proc('/synthetic-proc')
        with mock.patch.object(B.os, 'listdir', side_effect=[['101'], ['101', '102']]) as listing, \
                mock.patch.object(proc, 'identity', return_value=(1, 1, 1, 1, 1, 1)) as identity, \
                mock.patch.object(B, 'MAX_PROCESSES', 1):
            self.limit(lambda: proc.population(self.budget()), 'task_population', 1, 2)
        self.assertEqual(listing.call_count, 2)
        self.assertEqual(identity.call_count, 2)
        with mock.patch.object(B.os, 'listdir', return_value=['3', '4', '5']) as listing, \
                mock.patch.object(B, 'MAX_TABLE_FDS', 2):
            self.limit(lambda: proc.fds(101, 101), 'fd_table', 2, 3)
        listing.assert_called_once()
        with mock.patch.object(B.os, 'listdir', return_value=[CANARY]) as listing:
            self.limit(lambda: proc.fds(101, 101), 'malformed_fd_table', None, None)
        listing.assert_called_once()

    def test_native_byte_limits_read_only_cap_plus_one_once_and_close_on_refusal(self):
        proc = B.Proc('/synthetic-proc')
        for name, kind, cap in (('stat', 'stat_bytes', 4096), ('fdinfo/3', 'fdinfo_bytes', 4096),
                                ('maps', 'maps_bytes', B.MAX_MAPS)):
            for length in (cap, cap + 1):
                with self.subTest(kind=kind, length=length), \
                        mock.patch.object(B.os, 'open', return_value=99) as opened, \
                        mock.patch.object(B.os, 'read', return_value=b'x' * length) as read, \
                        mock.patch.object(B.os, 'close') as closed:
                    if length == cap:
                        self.assertEqual(len(proc.read(101, 101, name, cap)), cap)
                    else:
                        self.limit(lambda: proc.read(101, 101, name, cap), kind, cap, cap + 1)
                opened.assert_called_once_with(proc.path(101, 101, name), B.READ_FLAGS)
                read.assert_called_once_with(99, cap + 1)
                closed.assert_called_once_with(99)

    def test_maps_diagnostic_preserves_line_grammar_refusal_and_does_not_publish_raw_data(self):
        self.limit(lambda: B.mapped_identities(CANARY), 'malformed_maps', None, None)
        self.limit(lambda: B.mapped_identities(b'x' * (B.MAX_MAPS + 7)),
                   'maps_bytes', B.MAX_MAPS, B.MAX_MAPS + 7)
        with self.assertRaises(B.Refused) as caught:
            B.mapped_identities(mapping(permissions='r--z'))
        self.assertNotIsInstance(caught.exception, B.LimitRefused)
        self.assertEqual(str(caught.exception), 'PROC_INVALID')
        self.assertFalse(hasattr(caught.exception, 'diagnostic'))

    def test_global_generation_and_fd_limits_do_not_collect_extra_observations(self):
        proc = SyntheticProc(((101, 101), (101, 102)))
        with self.traced(proc) as calls, mock.patch.object(B, 'MAX_PROCESSES', 1):
            self.limit(lambda: B.scan_references({TARGET}, self.budget(), proc=proc),
                       'task_generations', 1, 2)
        self.counts(calls, visible=1, population=1, identity=2, fds=3, maps=2, link=2)
        proc = SyntheticProc()
        proc.tasks[(101, 101)]['fds'][3] = (metadata(UNRELATED), 0)
        with self.traced(proc) as calls, mock.patch.object(B, 'MAX_FDS', 1):
            self.limit(lambda: B.scan_references({TARGET}, self.budget(), proc=proc), 'fd_total', 1, 2)
        self.counts(calls, visible=1, population=2, identity=3, fds=4, fd_metadata=1, maps=2, link=2)

    def test_late_generation_limit_uses_existing_tail_without_extra_population_or_identity(self):
        proc = SyntheticProc(((101, 101), (202, 202)))
        both = proc.population(self.budget())
        first = {(101, 101): both[(101, 101)]}
        with self.traced(proc) as calls, mock.patch.object(B, 'MAX_LATE', 0):
            calls['population'].side_effect = [first, first, both]
            self.limit(lambda: B.scan_references({TARGET}, self.budget(), proc=proc),
                       'late_generations', 0, 1)
        self.counts(calls, visible=1, population=3, identity=4, fds=6, maps=4, link=4)

    def test_successful_scan_keeps_original_two_passes_and_exact_metadata_call_counts(self):
        proc = SyntheticProc()
        proc.tasks[(101, 101)]['fds'][3] = (metadata(UNRELATED), 0)
        with self.traced(proc) as calls:
            result = B.scan_references({TARGET}, self.budget(), proc=proc)
        self.assertEqual(result, dict(process_generations=1, fd_observations=2, map_observations=0,
            late_generations=0, exited_generations=0, reference_count=0, passes=2))
        self.counts(calls, visible=1, population=4, identity=4, fds=6, fd_metadata=2, maps=4, link=4)

    @contextlib.contextmanager
    def native_descriptor(self, fdinfo):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = root / '101' / 'task' / '101'
            (task / 'fd').mkdir(parents=True)
            (task / 'fdinfo').mkdir()
            payload = root / 'unrelated-file'
            payload.write_bytes(b'SYNTHETIC_UNRELATED_FILE')
            (task / 'fd' / '3').symlink_to(payload)
            if fdinfo is not None:
                (task / 'fdinfo' / '3').write_bytes(fdinfo)
            meta = B.A.identity(payload.stat())
            proc, synthetic = B.Proc(root), SyntheticProc()
            with contextlib.ExitStack() as stack:
                for name in ('visible', 'population', 'identity', 'present', 'maps', 'link'):
                    stack.enter_context(mock.patch.object(proc, name, side_effect=getattr(synthetic, name)))
                yield proc, meta

    def test_unrelated_oversized_native_fdinfo_does_not_block_complete_observation(self):
        for fdinfo in (b'flags:\t0\n' + b'x' * 4088, None):
            with self.subTest(fdinfo='oversized' if fdinfo else 'absent'), \
                    self.native_descriptor(fdinfo) as (proc, meta), self.traced(proc) as calls:
                with mock.patch.object(proc, 'read', wraps=proc.read) as read:
                    try:
                        result = B.scan_references({TARGET}, self.budget(), proc=proc)
                    except B.Refused as error:
                        self.fail('unrelated descriptor blocked observation: ' + str(error) +
                                  ' ' + B.A.canonical(getattr(error, 'diagnostic', None)))
                read.assert_not_called()
                self.counts(calls, visible=1, population=4, identity=4, fds=6,
                            fd_metadata=2, maps=4, link=4)
            self.assertEqual(result['passes'], 2)
            self.assertEqual(result['fd_observations'], 2)
            self.assertEqual(result['reference_count'], 0)

    def test_native_target_all_modes_refuse_without_opening_oversized_or_absent_fdinfo(self):
        for flags in (0, 1, 2, getattr(os, 'O_PATH', 0o10000000)):
            prefix = ('flags:\t%o\n' % flags).encode()
            for raw in (prefix + b'x' * (4097 - len(prefix)), None):
                with self.subTest(flags=flags, fdinfo='oversized' if raw else 'absent'), \
                        self.native_descriptor(raw) as (proc, meta), \
                        mock.patch.object(proc, 'read', side_effect=AssertionError('flags unnecessary')) as read:
                    with self.assertRaisesRegex(B.Refused, '^SOURCE_IN_USE$'):
                        B.scan_references({(meta['device'], meta['inode'])}, self.budget(), proc=proc)
                read.assert_not_called()

    def test_native_exact_observer_retains_bounded_flags_and_full_double_observation(self):
        prefix = b'flags:\t0\n'
        for raw, reason in ((prefix, None), (prefix + b'x' * (4096 - len(prefix)), None),
                            (prefix + b'x' * (4097 - len(prefix)), 'PROC_LIMIT'),
                            (b'', 'PROC_INVALID'), (b'flags:\t0\nflags:\t0\n', 'PROC_INVALID'),
                            (b'flags:\t2\n', 'SOURCE_IN_USE')):
            with self.subTest(size=len(raw), reason=reason), self.native_descriptor(raw) as (proc, meta):
                target = (meta['device'], meta['inode'])
                exception = (101, 101, proc.identity(101, 101), 3, meta, 0)
                with self.traced(proc) as calls:
                    def scan():
                        return B.scan_references({target}, self.budget(), proc=proc, observer_fds=(exception,))
                    if reason == 'PROC_LIMIT':
                        self.limit(scan, 'fdinfo_bytes', 4096, 4097)
                    elif reason:
                        with self.assertRaisesRegex(B.Refused, '^' + reason + '$'):
                            scan()
                    else:
                        result = scan()
                        self.assertEqual(result['fd_observations'], 2)
                        self.counts(calls, visible=1, population=4, identity=4, fds=6,
                                    fd_metadata=4, fd_flags=4, fd=2, maps=4, link=4)

    def test_observer_stat_flags_reuse_and_live_read_gaps_still_refuse(self):
        for changed, failure, expected in (
                ('fd_metadata', PermissionError(CANARY), 'PROC_UNAVAILABLE'),
                ('fd_flags', FileNotFoundError(CANARY), 'PROC_UNAVAILABLE'),
                ('fd', FileNotFoundError(CANARY), 'PROC_UNAVAILABLE'),
                ('fd_flags', [0, 2], 'PROC_CHANGED'),
                ('fd_metadata', [metadata(), metadata(UNRELATED)], 'PROC_CHANGED')):
            proc = SyntheticProc()
            meta = metadata()
            proc.tasks[(101, 101)]['fds'][3] = (meta, 0)
            exception = (101, 101, proc.identity(101, 101), 3, meta, 0)
            with self.subTest(seam=changed, expected=expected), \
                    mock.patch.object(proc, changed, side_effect=failure), \
                    self.assertRaisesRegex(B.Refused, '^' + expected + '$'):
                B.scan_references({TARGET}, self.budget(), proc=proc, observer_fds=(exception,))


if __name__ == '__main__':
    unittest.main()
