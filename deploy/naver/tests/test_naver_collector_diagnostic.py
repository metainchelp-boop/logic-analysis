"""Synthetic only: no Docker daemon, app HTTP, database connection, or real logs."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('collector_diag', Path(__file__).parents[1] / 'naver_collector_diagnostic.py')
D = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(D)
CANARY = 'SECRET_SYNTHETIC_CREDENTIAL'
TICK = '2026-11-02T10:00:00.123456789Z'


def state(alias):
    identifier, image = D.TARGETS[alias]
    return dict(id=identifier, image=image, pid=100 if alias == 'engine' else 200,
        running=True, paused=False, restarting=False, started_at=TICK,
        restart_count=0, oom_killed=False, user='10001:10001', readonly=True,
        source=D.SOURCE, data=[dict(Type='bind', Source='/var/lib/metainc/naver-engine',
            Destination='/var/lib/naver-engine', RW=True)] if alias == 'engine' else [])


def line(message, tick=TICK):
    return (tick + ' ' + message + '\n').encode()


class FakeDocker:
    def __init__(self):
        self.calls = []; self.changed = None
    def state(self, alias):
        self.calls.append(('state', alias))
        row = state(alias)
        if self.changed and self.calls.count(('state', alias)) == 2:
            row[self.changed] = row[self.changed] + 1 if type(row[self.changed]) is int else CANARY
        return row
    def logs(self, alias):
        self.calls.append(('logs', alias))
        return (b'', line('WARNING naver_engine.web 열람·쓰기 기록 실패: StoreBusy')) if alias == 'engine' else (b'', b'')


class FilesFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.folder = self.base / 'var/lib/metainc/naver-engine'
        self.folder.mkdir(parents=True, mode=0o700)
        for path in (self.base, *self.folder.parents):
            if path == self.base or self.base in path.parents:
                path.chmod(0o700)
        (self.folder / 'engine.db').write_bytes(CANARY.encode())
    def files(self):
        return D.Files(str(self.base), root_uid=os.getuid(), data_uid=os.getuid())
    def test_observed_report_is_closed_and_no_file_body_read(self):
        actual_open = D.os.open
        def guarded(path, flags, *args, **kwargs):
            self.assertNotIn(str(path), ('engine.db', 'engine.db-wal', 'engine.db-shm'))
            self.assertTrue(flags & os.O_DIRECTORY)
            return actual_open(path, flags, *args, **kwargs)
        with mock.patch.object(D.os, 'open', side_effect=guarded):
            result = D.diagnose(FakeDocker(), self.files())
        D.validate_report(result)
        self.assertEqual(result['status'], 'observed')
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertEqual(result['logs'][0]['categories']['audit_write_failed']['kinds'], {'StoreBusy': 1})
    def test_leaf_symlink_is_lstat_only_and_never_followed(self):
        (self.folder / 'engine.db').unlink()
        (self.folder / 'engine.db').symlink_to(self.base / CANARY)
        result = D.diagnose(FakeDocker(), self.files())
        self.assertEqual(result['storage']['files'][0]['kind'], 'symlink')
        self.assertNotIn(CANARY, json.dumps(result))
    def test_parent_symlink_refused(self):
        moved = self.folder.with_name('moved'); self.folder.rename(moved); self.folder.symlink_to(moved)
        result = D.diagnose(FakeDocker(), self.files())
        self.assertEqual(result['error'], 'unsafe_directory'); self.assertIsNone(result['logs'])
    def test_writable_parent_refused(self):
        self.folder.parent.chmod(0o777)
        self.assertEqual(D.diagnose(FakeDocker(), self.files())['error'], 'unsafe_directory')
    def test_directory_replacement_during_observation_is_refused(self):
        files = self.files(); files.observe()
        self.addCleanup(files.close)
        self.folder.rename(self.folder.with_name('old')); self.folder.mkdir(mode=0o700)
        with self.assertRaisesRegex(D.Refused, 'directory_changed'): files.validate()
    def test_owner_mismatch_refused(self):
        files = D.Files(str(self.base), root_uid=os.getuid() + 1, data_uid=os.getuid())
        self.assertEqual(D.diagnose(FakeDocker(), files)['error'], 'unsafe_directory')
    def test_each_container_state_drift_discards_all_projected_evidence(self):
        for key in ('pid', 'started_at', 'restart_count', 'image', 'data'):
            with self.subTest(key=key):
                docker = FakeDocker(); docker.changed = key
                result = D.diagnose(docker, self.files())
                self.assertEqual(result['error'], 'container_changed')
                self.assertTrue(all(result[k] is None for k in ('logs', 'storage', 'containers')))
                D.validate_report(result)
    def test_cleanup_failure_discards_previously_observed_results(self):
        files = self.files(); close = files.close
        def failed_close():
            close(); raise OSError(CANARY)
        files.close = failed_close
        result = D.diagnose(FakeDocker(), files)
        self.assertEqual(result['error'], 'metadata_unavailable'); D.validate_report(result)
    def test_raw_exception_never_leaves_diagnose(self):
        docker = FakeDocker(); docker.logs = mock.Mock(side_effect=RuntimeError(CANARY))
        result = D.diagnose(docker, self.files())
        self.assertEqual(result['error'], 'internal_failure'); self.assertNotIn(CANARY, json.dumps(result))
    def test_output_rejects_extra_keys_arbitrary_kind_and_guard_failure(self):
        good = D.diagnose(FakeDocker(), self.files())
        for change in ('extra', 'kind', 'guard', 'counter', 'http'):
            bad = copy.deepcopy(good)
            if change == 'extra': bad[CANARY] = 1
            elif change == 'kind': bad['logs'][0]['categories']['audit_write_failed']['kinds'] = {CANARY: 1}
            elif change == 'guard': bad['postflight_unchanged'] = False
            elif change == 'counter': bad['logs'][0]['entries_inspected'] = 2
            else: bad['application_http_calls'] = True
            with self.subTest(change=change), self.assertRaises(D.Refused): D.validate_report(bad)


class ProjectionTest(unittest.TestCase):
    def test_each_current_scheduler_job_is_counted_by_fixed_name_and_kind(self):
        expected = {'product_source', 'market_source', 'learning_sources', 'org', 'stages',
            'accounts', 'pairing', 'inventory_catalog', 'inventory', 'reports', 'readiness',
            'morning', 'alerts', 'backup', 'metrics', 'execution'}
        self.assertEqual(D.JOBS, expected | {'unrecognized'})
        data = b''.join(line('ERROR naver_runtime.scheduler 예약 작업 실패: ' + name + ' StoreBusy')
                        for name in sorted(expected))
        result = D.log_projection(data, b'', 'engine')
        self.assertEqual(set(result['jobs']), expected)
        self.assertEqual(result['categories']['job_failed']['count'], len(expected))
        for row in result['jobs'].values():
            self.assertEqual(row['count'], 1)
            self.assertEqual(row['kinds'], {'StoreBusy': 1})
            self.assertEqual(row['first_at'], row['last_at'])

    def test_job_failure_aggregates_times_and_kinds_without_raw_names(self):
        first = line('ERROR naver_runtime.scheduler 예약 작업 실패: reports StoreBusy')
        later = line('ERROR naver_runtime.scheduler 예약 작업 실패: reports ValueError',
                     '2026-11-02T10:00:01Z')
        unknown = line('ERROR naver_runtime.scheduler 예약 작업 실패: private_job ' + CANARY)
        result = D.log_projection(first + unknown, later, 'engine')
        self.assertEqual(result['jobs']['reports']['count'], 2)
        self.assertEqual(result['jobs']['reports']['kinds'], {'StoreBusy': 1, 'ValueError': 1})
        self.assertLess(result['jobs']['reports']['first_at'], result['jobs']['reports']['last_at'])
        self.assertEqual(result['jobs']['unrecognized']['kinds'], {'unrecognized': 1})
        self.assertNotIn('private_job', json.dumps(result))
        self.assertNotIn(CANARY, json.dumps(result))

    def test_only_exact_product_log_prefix_is_matched_for_job_failures(self):
        good = 'ERROR naver_runtime.scheduler 예약 작업 실패: inventory RuntimeError'
        bad = [good + ' ' + CANARY, good.replace('ERROR ', 'WARNING '),
               good.replace('naver_runtime.scheduler', 'naver_runtime'),
               good.replace('예약 작업 실패:', '예약 작업실패:'),
               good.replace('inventory', 'inventory/customer')]
        result = D.log_projection(b''.join(line(item) for item in [good, *bad]), b'', 'engine')
        self.assertEqual(result['jobs']['inventory']['count'], 1)
        self.assertEqual(result['ignored_entries'], len(bad))
        self.assertEqual(D.log_projection(line(good), b'', 'relay')['jobs'], {})

    def test_stderr_and_stdout_count_together_with_utc_times(self):
        result = D.log_projection(line('WARNING naver_engine.web 열람·쓰기 기록 실패: StoreBusy'),
            line('WARNING naver_engine.web 열람·쓰기 기록 실패: StoreError', '2026-11-02T19:00:01+09:00'), 'engine')
        row = result['categories']['audit_write_failed']
        self.assertEqual(row['count'], 2); self.assertEqual(row['kinds'], {'StoreBusy': 1, 'StoreError': 1})
        self.assertTrue(row['last_at'].endswith('+00:00'))
    def test_unknown_kind_is_fixed_enum_and_suffix_does_not_match(self):
        data = line('WARNING naver_engine.web 열람·쓰기 기록 실패: ' + CANARY)
        data += line('WARNING naver_engine.web 열람·쓰기 기록 실패: StoreBusy ' + CANARY)
        data += line('Traceback ' + CANARY)
        result = D.log_projection(data, b'', 'engine')
        self.assertEqual(result['categories']['audit_write_failed']['kinds'], {'unrecognized': 1})
        self.assertEqual(result['ignored_entries'], 2); self.assertNotIn(CANARY, json.dumps(result))
    def test_bad_utf8_time_and_overlong_line_are_ignored_without_echo(self):
        result = D.log_projection(b'\xff\n' + line(CANARY, 'not-a-timestamp') + b'x' * 8193, b'', 'engine')
        self.assertEqual(result['ignored_entries'], 3); self.assertEqual(result['categories'], {})
    def test_combined_byte_limit_and_combined_line_limit_refuse(self):
        for out, err in ((b'x' * D.MAX_LOG, b'x'), (b'\n' * 200, b'\n' * 101)):
            with self.assertRaises(D.Refused): D.log_projection(out, err, 'engine')
    def test_limit_reached_means_sample_only(self):
        self.assertTrue(D.log_projection(b'\n' * 300, b'', 'relay')['sample_limit_reached'])
    def test_duplicate_json_and_nonfinite_refused(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(D.Refused): D.decode(raw)


class JobReportTest(unittest.TestCase):
    setUp = FilesFixture.setUp
    files = FilesFixture.files

    def test_job_breakdown_is_closed_and_must_match_category_totals(self):
        docker = FakeDocker()
        docker.logs = lambda alias: (line('ERROR naver_runtime.scheduler 예약 작업 실패: reports StoreBusy'), b'') if alias == 'engine' else (b'', b'')
        good = D.diagnose(docker, self.files())
        D.validate_report(good)
        for change in ('name', 'count', 'kind', 'missing', 'relay', 'extra', 'time'):
            bad = copy.deepcopy(good)
            jobs = bad['logs'][0]['jobs']
            if change == 'name': jobs[CANARY] = jobs.pop('reports')
            elif change == 'count': jobs['reports']['count'] += 1
            elif change == 'kind': jobs['reports']['kinds'] = {'ValueError': 1}
            elif change == 'missing': jobs.clear()
            elif change == 'relay': bad['logs'][1]['jobs'] = copy.deepcopy(jobs)
            elif change == 'extra': jobs['reports'][CANARY] = 1
            else: jobs['reports']['last_at'] = '2026-11-02T10:00:09Z'
            with self.subTest(change=change), self.assertRaises(D.Refused):
                D.validate_report(bad)


class DockerTest(unittest.TestCase):
    def test_current_source_and_distinct_nonplaceholder_container_pins(self):
        self.assertEqual(D.SOURCE, '0b9a6e23915c63c9834278545d7f6032f99a13de')
        self.assertEqual(len({target[0] for target in D.TARGETS.values()}), 2)
        for identifier, image in D.TARGETS.values():
            self.assertRegex(identifier, r'^[0-9a-f]{64}$')
            self.assertNotEqual(identifier, '0' * 64)
            self.assertRegex(image, r'^sha256:[0-9a-f]{64}$')

    def run_state(self, alias='engine', mutate=None):
        row = state(alias)
        if mutate: mutate(row)
        runner = mock.Mock(return_value=(json.dumps(row).encode(), b'', 0))
        return D.Docker('/synthetic-empty-config', runner).state(alias), runner
    def test_exact_fixed_target_socket_and_metadata_only_template(self):
        for alias in D.TARGETS:
            row, runner = self.run_state(alias)
            argv = runner.call_args.args[0]
            self.assertEqual(argv[:5], ['/usr/bin/docker', '--host', 'unix:///var/run/docker.sock', '--config', '/synthetic-empty-config'])
            self.assertEqual(argv[-1], D.TARGETS[alias][0]); self.assertNotIn('.Config.Env', argv[-2])
            self.assertEqual(row['source'], D.SOURCE)
    def test_identity_privilege_state_and_mount_drift_refused(self):
        changes = [lambda r: r.update(id='f'*64), lambda r: r.update(image='sha256:'+'f'*64),
            lambda r: r.update(source='f'*40), lambda r: r.update(pid=True), lambda r: r.update(paused=True),
            lambda r: r.update(readonly=False), lambda r: r.update(user='0'), lambda r: r.update(running=False),
            lambda r: r.update(data=[]), lambda r: r['data'][0].update(Source='/other'),
            lambda r: r['data'][0].update(RW=False)]
        for change in changes:
            with self.assertRaises(D.Refused): self.run_state(mutate=change)
    def test_logs_bounded_recent_and_no_raw_failed_stderr(self):
        runner = mock.Mock(return_value=(b'', CANARY.encode(), 1))
        with self.assertRaisesRegex(D.Refused, '^docker_failed$'): D.Docker('/empty', runner).logs('engine')
        argv = runner.call_args.args[0]
        self.assertEqual(argv[5:-1], ['logs', '--since', '1h', '--tail', '300', '--timestamps'])
        self.assertEqual(runner.call_args.kwargs, dict(limit=D.MAX_LOG, timeout=8))


class ProcessTest(unittest.TestCase):
    def test_both_pipes_drained_and_actual_rc_returned(self):
        out, err, rc = D.command([sys.executable, '-c', 'import os;os.write(1,b"out");os.write(2,b"err");raise SystemExit(3)'])
        self.assertEqual((out, err, rc), (b'out', b'err', 3))
    def test_combined_limit_reaps_child(self):
        with self.assertRaisesRegex(D.Refused, 'command_limit'):
            D.command([sys.executable, '-c', 'import os,time;os.write(1,b"x"*60);os.write(2,b"y"*60);time.sleep(2)'], limit=100)
    def test_deadline_reaps_child(self):
        with self.assertRaisesRegex(D.Refused, 'command_timeout'):
            D.command([sys.executable, '-c', 'import time;time.sleep(2)'], timeout=.05)
    def test_spawn_return_signal_registered_then_killed_and_reaped(self):
        actual = D.subprocess.Popen; children = []
        def spawn(*args, **kwargs):
            child = actual(*args, **kwargs); children.append(child)
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return child
        with mock.patch.object(D.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaisesRegex(D.Refused, 'interrupted'):
                D.command([sys.executable, '-c', 'import time;time.sleep(2)'])
        self.assertIsNotNone(children[0].poll()); self.assertTrue(children[0].stdout.closed)
    def test_cleanup_failure_is_distinct_and_never_safe(self):
        docker = FakeDocker(); docker.state = mock.Mock(side_effect=D.Refused('child_cleanup_failed'))
        files = mock.Mock()
        result = D.diagnose(docker, files)
        self.assertFalse(result['child_cleanup_confirmed']); D.validate_report(result)


class EntryTest(unittest.TestCase):
    def invoke(self, argv, uid=0, platform='linux', result=None):
        with mock.patch.object(D.os, 'geteuid', return_value=uid), mock.patch.object(D.sys, 'platform', platform), \
             mock.patch.object(D.resource, 'setrlimit'), mock.patch.object(D.os, 'umask'), \
             mock.patch.object(D, 'diagnose', return_value=result) as diagnose, \
             mock.patch.object(D.signal, 'alarm') as alarm, mock.patch.object(D.sys, 'stdout', new_callable=io.StringIO) as out:
            rc = D.main(argv)
            return rc, json.loads(out.getvalue()), diagnose, alarm
    def test_no_argument_nonroot_nonlinux_refused_before_docker(self):
        for args, uid, platform, code in [(['/arbitrary'],0,'linux','arguments_refused'),
            ([],1000,'linux','uid_required'), ([],0,'darwin','platform_refused')]:
            rc, row, called, _ = self.invoke(args, uid, platform)
            self.assertEqual((rc,row['error']), (2,code)); called.assert_not_called()
    def test_total_alarm_installed_then_cancelled_and_failure_schema_preserved(self):
        result = D.empty_report(); result['error'] = 'docker_failed'
        rc, row, _, alarm = self.invoke([], result=result)
        self.assertEqual(rc, 2); D.validate_report(row)
        self.assertEqual(alarm.call_args_list, [mock.call(60), mock.call(0)])
    def test_invalid_result_never_prints_raw_canary(self):
        rc, row, _, _ = self.invoke([], result={'secret': CANARY})
        self.assertEqual(rc,2); self.assertNotIn(CANARY, json.dumps(row))


if __name__ == '__main__': unittest.main()
