import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('content_preflight', Path(__file__).resolve().parents[1] / 'content_runtime_preflight.py')
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)
ID, IMAGE, CANARY = 'a' * 64, 'sha256:' + 'b' * 64, 'PRIVATE_CUSTOMER_KEY_CANARY'


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.pids = [(100, 1, 'python')]
        self.mounts = []
        self.changed = False

    def __call__(self, argv, timeout):
        self.calls.append(argv)
        if argv[:2] == ['docker', 'inspect']:
            identity = {'id': ID, 'name': '/content-studio', 'image': IMAGE, 'pid': 100, 'running': True, 'mounts': self.mounts}
            if self.changed and sum(call[1] == 'inspect' for call in self.calls) > 1:
                identity['pid'] = 999
            return subject.CommandResult('ok', json.dumps(identity))
        if argv[:2] == ['docker', 'top']:
            return subject.CommandResult('ok', 'PID PPID COMMAND\n' + '\n'.join('%d %d %s' % row for row in self.pids))
        raise AssertionError('Only approved synthetic Docker reads are allowed')


class PreflightTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(os.path.realpath(self.temp.name))
        self.proc = self.base / 'proc'
        self.root = self.base / 'container'
        (self.root / 'tmp').mkdir(parents=True)
        self.make_process(100, 1)
        self.reader = subject.Proc(str(self.proc))
        self.runner = FakeRunner()

    def tearDown(self):
        self.temp.cleanup()

    def make_process(self, pid, ppid, shared_namespace=True):
        folder = self.proc / str(pid)
        (folder / 'ns').mkdir(parents=True)
        (folder / 'fd').mkdir()
        (folder / 'fdinfo').mkdir()
        fields = ['S', str(ppid)] + ['0'] * 17 + [str(pid * 10)]
        (folder / 'stat').write_text(str(pid) + ' (' + CANARY + ') ' + ' '.join(fields))
        for namespace in ('pid', 'mnt'):
            path = folder / 'ns' / namespace
            if pid != 100 and shared_namespace:
                os.link(self.proc / '100/ns' / namespace, path)
            else:
                path.write_text('namespace metadata only')
        os.symlink(self.root, folder / 'root')
        (folder / 'mountinfo').write_text('1 0 0:1 / / rw - overlay overlay rw\n2 1 0:2 / /tmp rw - tmpfs tmpfs rw\n')

    def make_fd(self, number, path, flags='0100002', pid=100):
        os.symlink(path, self.proc / str(pid) / 'fd' / str(number))
        (self.proc / str(pid) / 'fdinfo' / str(number)).write_text('pos:\t0\nflags:\t' + flags + '\n')

    def collect(self):
        return subject.Preflight(self.runner, self.reader).collect(ID, IMAGE, 100)

    def test_empty_candidates_and_zero_fds_never_prove_effective_paths_or_writer_absence(self):
        result = self.collect()
        self.assertEqual(result['status'], 'bounded_observations_complete')
        self.assertEqual(len(result['candidate_files']), 32)
        self.assertTrue(all(r['status'] == 'absent_or_process_exited' for r in result['candidate_files']))
        self.assertIn('unverified', result['writer_absence'])
        self.assertTrue(result['effective_database_paths'].startswith('unknown'))
        self.assertEqual(result['stop_safety'], 'not_determined')
        self.assertNotIn(CANARY, json.dumps(result))

    def test_invalid_or_stale_identity_does_not_read_proc(self):
        with mock.patch.object(self.reader, 'identity', side_effect=AssertionError('Must not read proc')):
            result = subject.Preflight(self.runner, self.reader).collect('../secret', IMAGE, 100)
            self.assertEqual(result['error'], 'request_refused')
            self.assertEqual(self.runner.calls, [])
            result = subject.Preflight(self.runner, self.reader).collect(ID, IMAGE, 101)
            self.assertEqual(result['error'], 'container_identity_unconfirmed')

    def test_only_fixed_candidate_metadata_is_read_and_database_content_is_never_opened(self):
        database = self.root / 'tmp/studio_clients.db'
        database.write_text(CANARY)
        self.make_fd(3, database)
        original = subject.os.open
        def opened(name, flags, **kwargs):
            self.assertFalse(str(name).endswith(('.db', '.env', '.key')))
            return original(name, flags, **kwargs)
        with mock.patch.object(subject.os, 'open', side_effect=opened):
            result = self.collect()
        row = result['candidate_files'][0]
        self.assertEqual(row['size_bytes'], len(CANARY))
        self.assertEqual(result['processes'][0]['fd']['known_db_writable'], 1)
        self.assertNotIn(CANARY, json.dumps(result))

    def test_candidate_and_ancestor_symlinks_are_refused(self):
        os.symlink('/' + CANARY, self.root / 'tmp/studio_clients.db')
        result = self.collect()
        self.assertEqual(result['candidate_files'][0]['status'], 'non_regular_or_symlink_refused')
        self.assertEqual(result['status'], 'incomplete')
        (self.root / 'tmp/studio_clients.db').unlink()
        (self.root / 'tmp').rmdir()
        os.symlink(self.base, self.root / 'tmp')
        result = self.collect()
        self.assertTrue(all(r['status'] == 'symlink_or_non_directory_refused' for r in result['candidate_files']))
        self.assertNotIn(CANARY, json.dumps(result))

    def test_directory_swap_is_detected_and_all_owned_fds_are_closed(self):
        original, opened_fds, replaced = subject.os.open, [], False
        def opened(name, flags, **kwargs):
            nonlocal replaced
            if name == 'tmp' and not replaced:
                replaced = True
                (self.root / 'tmp').rename(self.root / 'old-tmp')
                (self.root / 'tmp').mkdir()
            fd = original(name, flags, **kwargs)
            opened_fds.append(fd)
            return fd
        with mock.patch.object(subject.os, 'open', side_effect=opened):
            rows = self.reader.candidates(100)
        self.assertEqual(rows[0]['status'], 'changed_during_query')
        for fd in opened_fds:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_unknown_writable_file_and_deleted_open_file_are_reported_without_a_path(self):
        path = self.root / ('tmp/' + CANARY + '.db')
        path.write_text(CANARY)
        self.make_fd(3, path)
        result = self.collect()
        self.assertEqual(result['processes'][0]['fd']['unclassified_regular_writable'], 1)
        self.assertEqual(result['status'], 'incomplete')
        with mock.patch.object(subject.os, 'readlink', return_value='/tmp/' + CANARY + '.db (deleted)'):
            result = self.collect()
        fd = result['processes'][0]['fd']
        self.assertEqual(fd['unclassified_deleted_writable'], 1)
        self.assertNotIn(CANARY, json.dumps(result))

    def test_readonly_unknown_file_is_not_reported_as_a_writer(self):
        path = self.root / ('tmp/' + CANARY)
        path.write_text(CANARY)
        self.make_fd(3, path, flags='0100000')
        result = self.collect()
        self.assertEqual(result['processes'][0]['fd']['unclassified_regular_writable'], 0)
        self.assertIn('unverified', result['writer_absence'])

    def test_fd_count_and_fdinfo_bytes_are_bounded(self):
        path = self.root / 'tmp/studio_clients.db'
        path.write_text(CANARY)
        for number in (3, 4, 5):
            self.make_fd(number, path)
        counts = self.reader.fd_counts(100, set(), time.monotonic() + 5, max_fds=2)
        self.assertEqual(counts['observed_fds'], 2)
        self.assertNotEqual(counts['status'], 'ok')
        (self.proc / '100/fdinfo/3').write_text(CANARY * 500)
        result = self.collect()
        self.assertGreater(result['processes'][0]['fd']['failed_fds'], 0)
        self.assertEqual(result['status'], 'incomplete')
        self.assertNotIn(CANARY, json.dumps(result))

    def test_proc_stat_and_mountinfo_bytes_are_bounded(self):
        (self.proc / '100/stat').write_text(CANARY * 5000)
        result = self.collect()
        self.assertEqual(result['error'], 'proc_output_limit')
        self.assertEqual(result['candidate_files'], [])
        self.assertNotIn(CANARY, json.dumps(result))

    def test_pid_starttime_change_discards_all_observations(self):
        original, calls = self.reader.identity, 0
        def identity(pid):
            nonlocal calls
            result = original(pid)
            calls += 1
            if calls >= 3:
                result['start_ticks'] += 1
            return result
        with mock.patch.object(self.reader, 'identity', side_effect=identity):
            result = self.collect()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['candidate_files'], [])
        self.assertEqual(result['processes'], [])

    def test_container_identity_change_discards_observations(self):
        self.runner.changed = True
        result = self.collect()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['processes'], [])

    def test_worker_namespace_failure_remains_incomplete(self):
        self.make_process(200, 100, shared_namespace=False)
        self.runner.pids.append((200, 100, CANARY))
        result = self.collect()
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['processes'][1]['status'], 'worker_identity_unconfirmed')
        self.assertEqual(result['processes'][1]['executable_basename'], 'other')
        self.assertNotIn(CANARY, json.dumps(result))

    def test_worker_cap_and_command_failure_remain_explicit(self):
        self.runner.pids += [(number, 100, 'python') for number in range(200, 265)]
        result = self.collect()
        self.assertTrue(result['worker_limit_exceeded'])
        self.assertLessEqual(len(result['processes']), 64)
        self.assertEqual(result['status'], 'incomplete')
        def bad(*_):
            return subject.CommandResult(CANARY, CANARY)
        result = subject.Preflight(bad, self.reader).collect(ID, IMAGE, 100)
        self.assertEqual(result['error'], 'command_failed')
        self.assertNotIn(CANARY, json.dumps(result))

    def test_exceptions_and_permissions_do_not_leak_messages(self):
        with mock.patch.object(self.reader, 'candidates', side_effect=PermissionError(CANARY)):
            result = self.collect()
        self.assertEqual(result['error'], 'permission_denied')
        self.assertNotIn(CANARY, json.dumps(result))

    def test_parent_and_nested_mounts_are_resolved_per_fixed_candidate(self):
        raw = '1 0 0:1 / / rw - overlay overlay rw\n2 1 0:2 / /tmp rw - tmpfs tmpfs rw\n'
        raw += '3 2 0:3 / /tmp/studio_clients.db rw - ext4 /dev/REDACT rw\n'
        result = subject.mount_summary(raw, [{'destination': '/tmp/studio_clients.db', 'type': 'bind'}])
        self.assertEqual(result['status'], 'ok')
        self.assertTrue(result['paths'][0]['memory_backed'])
        self.assertIsNone(result['paths'][1]['memory_backed'])
        self.assertTrue(result['paths'][1]['declared_bind'])
        self.assertTrue(all(r['persistence_after_stop'] == 'unverified' for r in result['paths']))
        self.assertEqual(subject.mount_summary(CANARY, [])['status'], 'unknown')

    def test_time_limit_prevents_commands_and_does_not_claim_absence(self):
        result = subject.Preflight(self.runner, self.reader, time_budget=0).collect(ID, IMAGE, 100)
        self.assertEqual(result['error'], 'time_limit')
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(result['stop_safety'], 'not_determined')

    def test_changed_top_membership_discards_observations(self):
        original, top_calls = self.runner, 0
        def runner(argv, timeout):
            nonlocal top_calls
            if argv[:2] == ['docker', 'top']:
                top_calls += 1
                if top_calls == 2:
                    original.pids.append((200, 100, 'python'))
            return original(argv, timeout)
        result = subject.Preflight(runner, self.reader).collect(ID, IMAGE, 100)
        self.assertEqual(result['error'], 'container_or_init_changed')
        self.assertEqual(result['candidate_files'], [])
        self.assertEqual(result['processes'], [])

    def test_unconfirmed_access_mode_does_not_become_readonly(self):
        path = self.root / 'tmp/studio_clients.db'
        path.write_text(CANARY)
        self.make_fd(3, path, flags='0100003')
        result = self.collect()
        self.assertEqual(result['processes'][0]['fd']['failed_fds'], 1)
        self.assertEqual(result['status'], 'incomplete')

    def test_inspect_requires_typed_identity_and_valid_mount_metadata(self):
        for override in ({'running': 1}, {'pid': True},
                         {'mounts': [{'type': 'bind', 'destination': '/tmp/../' + CANARY}]}):
            def runner(*_):
                identity = {'id': ID, 'name': '/content-studio', 'image': IMAGE, 'pid': 100, 'running': True, 'mounts': []}
                identity.update(override)
                return subject.CommandResult('ok', json.dumps(identity))
            result = subject.Preflight(runner, self.reader).collect(ID, IMAGE, 100)
            self.assertEqual(result['status'], 'incomplete')
            self.assertEqual(result['processes'], [])
            self.assertNotIn(CANARY, json.dumps(result))

    def test_other_container_name_is_refused_before_proc_without_echoing_it(self):
        def runner(*_):
            return subject.CommandResult('ok', json.dumps({'id': ID, 'name': '/' + CANARY,
                'image': IMAGE, 'pid': 100, 'running': True, 'mounts': []}))
        with mock.patch.object(self.reader, 'identity', side_effect=AssertionError('Must not read other container proc')):
            result = subject.Preflight(runner, self.reader).collect(ID, IMAGE, 100)
        self.assertEqual(result['error'], 'container_identity_unconfirmed')
        self.assertEqual(result['processes'], [])
        self.assertNotIn(CANARY, json.dumps(result))

    def test_command_runner_bounds_both_streams_and_timeout_without_raw_output(self):
        result = subject.run_command([sys.executable, '-c', 'import sys; sys.stdout.write("x" * 70000)'], 1)
        self.assertEqual(result.status, 'command_output_limit')
        self.assertEqual(result.stdout, '')
        result = subject.run_command([sys.executable, '-c', 'import sys; sys.stderr.write("' + CANARY + '"); sys.exit(1)'], 1)
        self.assertEqual(result.status, 'command_failed')
        self.assertEqual(result.stdout, '')
        result = subject.run_command([sys.executable, '-c', 'import time; time.sleep(2)'], .05)
        self.assertEqual(result.status, 'command_timeout')

    def test_cli_rejected_values_do_not_echo_and_alarm_cannot_be_swallowed(self):
        errors = io.StringIO()
        with mock.patch('sys.argv', ['helper', '--expected-init-pid', CANARY]), contextlib.redirect_stderr(errors):
            with self.assertRaises(SystemExit):
                subject.main()
        self.assertEqual(errors.getvalue(), 'request_refused\n')
        with mock.patch.object(self.reader, 'candidates', side_effect=subject.DeadlineExpired()):
            with self.assertRaises(subject.DeadlineExpired):
                self.collect()
        output = io.StringIO()
        with mock.patch('sys.argv', ['helper', '--container-id', ID, '--expected-image', IMAGE, '--expected-init-pid', '100']), \
                mock.patch.object(subject.Preflight, 'collect', side_effect=subject.DeadlineExpired()), \
                mock.patch.object(subject.signal, 'signal'), mock.patch.object(subject.signal, 'setitimer'), \
                contextlib.redirect_stdout(output):
            self.assertEqual(subject.main(), 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result['error'], 'time_limit')
        self.assertEqual(result['stop_safety'], 'not_determined')


if __name__ == '__main__':
    unittest.main()
