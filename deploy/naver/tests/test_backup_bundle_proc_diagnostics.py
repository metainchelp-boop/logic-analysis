"""Closed failure details from synthetic metadata; no operating host observation."""
import contextlib
import errno
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import test_backup_bundle_independent as I

B = I.B
CANARY = I.CANARY


class ProcFailureDiagnosticsTests(unittest.TestCase):
    def budget(self):
        return B.A.Budget(clock=lambda: 0)

    def failure(self, operation, phase, bucket):
        with self.assertRaises(B.Refused) as caught:
            operation()
        self.assertEqual(str(caught.exception), 'PROC_UNAVAILABLE')
        value = getattr(caught.exception, 'proc_diagnostic', None)
        self.assertEqual(value, {'phase': phase, 'errno_bucket': bucket})
        self.assertNotIn(CANARY, json.dumps(value))
        return caught.exception

    @contextlib.contextmanager
    def population(self, missing, state=b'S'):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = root / '101' / 'task' / '101'
            (task / 'ns').mkdir(parents=True)
            (task / 'stat').write_bytes(b'101 (synthetic) ' + state + b' 1 ' + b'0 ' * 17 + b'123\n')
            for name in ('pid', 'mnt'):
                (task / 'ns' / name).write_bytes(b'namespace-fixture')
            (task / missing).unlink()
            yield B.Proc(root)

    def test_native_population_missing_stat_or_namespace_is_distinct_without_retries(self):
        for missing, phase in (
                ('stat', 'population_stat_missing_present'),
                ('ns/pid', 'population_pidns_missing_present'),
                ('ns/mnt', 'population_mntns_missing_present')):
            with self.subTest(missing=missing), self.population(missing) as proc, \
                    mock.patch.object(proc, 'identity', wraps=proc.identity) as identity, \
                    mock.patch.object(proc, 'present', wraps=proc.present) as present:
                self.failure(lambda: proc.population(self.budget()), phase, 'ENOENT')
                identity.assert_called_once_with(101, 101)
                present.assert_called_once_with(101, 101)

    def test_already_read_zombie_state_distinguishes_namespace_failure_without_skipping(self):
        for missing, phase in (
                ('ns/pid', 'population_pidns_missing_present_zombie_at_identity_read'),
                ('ns/mnt', 'population_mntns_missing_present_zombie_at_identity_read')):
            with self.subTest(missing=missing), self.population(missing, state=b'Z') as proc, \
                    mock.patch.object(proc, 'read', wraps=proc.read) as reads:
                self.failure(lambda: proc.population(self.budget()), phase, 'ENOENT')
                reads.assert_called_once_with(101, 101, 'stat', 4096)

    def test_reused_namespace_error_cannot_retain_old_zombie_state(self):
        proc = B.Proc('/synthetic-proc')
        error = FileNotFoundError(errno.ENOENT, CANARY)
        for state, phase in ((b'Z', 'population_pidns_missing_present_zombie_at_identity_read'),
                             (b'S', 'population_pidns_missing_present')):
            raw = b'101 (synthetic) ' + state + b' 1 ' + b'0 ' * 17 + b'123\n'
            with mock.patch.object(B.os, 'listdir', side_effect=[['101'], ['101']]), \
                    mock.patch.object(proc, 'read', return_value=raw) as reads, \
                    mock.patch.object(B.os, 'stat', side_effect=error) as stats, \
                    mock.patch.object(proc, 'present', return_value=True):
                self.failure(lambda: proc.population(self.budget()), phase, 'ENOENT')
            reads.assert_called_once()
            stats.assert_called_once()

    def test_primitive_rethrows_same_exception_and_reused_object_gets_current_phase(self):
        error = PermissionError(errno.EACCES, CANARY, '/' + CANARY)
        proc = B.Proc('/synthetic-proc')
        for operation, phase in ((lambda: proc.fds(101, 101), 'fd_list'),
                                 (lambda: proc.population(self.budget()), 'population')):
            with mock.patch.object(B.os, 'listdir', side_effect=error) as call:
                with self.assertRaises(PermissionError) as caught:
                    operation()
            self.assertIs(caught.exception, error)
            self.assertEqual(B.proc_fault(error), {'phase': phase, 'errno_bucket': 'EACCES'})
            call.assert_called_once()

    def test_recovered_closed_fd_does_not_label_later_permission_error(self):
        proc = I.SyntheticProc(((101, 101), (202, 202)))
        proc.tasks[(101, 101)]['fds'][3] = (I.metadata(I.UNRELATED), 0)
        original_fds = proc.fds
        native = B.Proc('/synthetic-proc')
        calls = []
        def fds(pid, tid):
            calls.append(('fds', pid))
            if pid == 202:
                with mock.patch.object(B.os, 'listdir', side_effect=PermissionError(errno.EACCES, CANARY)):
                    return native.fds(pid, tid)
            return original_fds(pid, tid)
        def closed(pid, tid, number):
            calls.append(('fd_metadata', pid))
            proc.tasks[(pid, tid)]['fds'].pop(number)
            with mock.patch.object(B.os, 'stat', side_effect=FileNotFoundError(errno.ENOENT, CANARY)):
                return native.fd_metadata(pid, tid, number)
        with mock.patch.object(proc, 'fds', side_effect=fds), \
                mock.patch.object(proc, 'fd_metadata', side_effect=closed):
            self.failure(lambda: B.scan_references({I.TARGET}, self.budget(), proc=proc),
                         'fd_list', 'EACCES')
        self.assertEqual(calls, [('fds', 101), ('fd_metadata', 101), ('fds', 101),
                                 ('fds', 101), ('fds', 101), ('fds', 202)])

    def test_semantic_namespace_mismatch_has_no_invented_errno(self):
        proc = B.Proc('/synthetic-proc')
        first = mock.Mock(st_dev=1, st_ino=2)
        second = mock.Mock(st_dev=1, st_ino=3)
        with mock.patch.object(B.os, 'stat', side_effect=[first, second]) as calls:
            self.failure(lambda: B.scan_references({I.TARGET}, self.budget(), proc=proc),
                         'namespace_mismatch', None)
        self.assertEqual(calls.call_count, 2)

    def test_recovered_task_exit_does_not_contaminate_next_task_failure(self):
        proc = I.SyntheticProc(((101, 101), (202, 202)))
        identity = proc.identity
        native = B.Proc('/synthetic-proc')
        def disappearing(pid, tid):
            if pid == 101:
                proc.tasks.pop((pid, tid), None)
                with mock.patch.object(B.os, 'open', side_effect=ProcessLookupError(errno.ESRCH, CANARY)):
                    return native.identity(pid, tid)
            return identity(pid, tid)
        def denied(pid, tid):
            with mock.patch.object(B.os, 'listdir', side_effect=PermissionError(errno.EPERM, CANARY)):
                return native.fds(pid, tid)
        with mock.patch.object(proc, 'identity', side_effect=disappearing) as identities, \
                mock.patch.object(proc, 'fds', side_effect=denied) as tables, \
                mock.patch.object(proc, 'present', wraps=proc.present) as present:
            self.failure(lambda: B.scan_references({I.TARGET}, self.budget(), proc=proc),
                         'fd_list', 'EPERM')
        self.assertEqual(identities.call_count, 3)
        tables.assert_called_once_with(202, 202)
        present.assert_called_once_with(101, 101)

    def test_semantic_refusals_preserve_missing_errno_and_existing_calls(self):
        for kind, phase in (('fd_metadata', 'fd_missing_listed'),
                            ('maps', 'same_generation_metadata_missing'),
                            ('cwd', 'cwd_missing_with_refs'), ('root', 'root_missing_with_refs')):
            with self.subTest(kind=kind):
                proc = I.SyntheticProc()
                proc.tasks[(101, 101)]['fds'][3] = (I.metadata(I.UNRELATED), 0)
                error = FileNotFoundError(errno.ENOENT, CANARY)
                native = B.Proc('/synthetic-proc')
                if kind == 'fd_metadata':
                    def missing(*args):
                        with mock.patch.object(B.os, 'stat', side_effect=error):
                            return native.fd_metadata(*args)
                    patch = mock.patch.object(proc, kind, side_effect=missing)
                elif kind == 'maps':
                    def missing(*args):
                        with mock.patch.object(B.os, 'open', side_effect=error):
                            return native.maps(*args)
                    patch = mock.patch.object(proc, kind, side_effect=missing)
                else:
                    original = proc.link
                    def missing(pid, tid, name):
                        if name == kind:
                            with mock.patch.object(B.os, 'stat', side_effect=error):
                                return native.link(pid, tid, name)
                        return original(pid, tid, name)
                    patch = mock.patch.object(proc, 'link', side_effect=missing)
                with patch, mock.patch.object(proc, 'identity', wraps=proc.identity) as identities:
                    self.failure(lambda: B.scan_references({I.TARGET}, self.budget(), proc=proc),
                                 phase, 'ENOENT')
                self.assertEqual(identities.call_count, 2 if kind == 'maps' else 1)

    def test_still_listed_self_fd_is_distinguished_and_still_refused(self):
        for self_pid, phase in ((101, 'fd_missing_listed_self'), (202, 'fd_missing_listed')):
            proc = I.SyntheticProc()
            proc.tasks[(101, 101)]['fds'][3] = (I.metadata(I.UNRELATED), 0)
            with mock.patch.object(B.os, 'getpid', return_value=self_pid) as getpid, \
                    mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(errno.ENOENT, CANARY)), \
                    mock.patch.object(proc, 'fds', wraps=proc.fds) as listings:
                self.failure(lambda: B.scan_references({I.TARGET}, self.budget(), proc=proc), phase, 'ENOENT')
            getpid.assert_called_once()
            self.assertEqual(listings.call_count, 2)

    def test_failed_generation_recheck_reports_its_actual_permission_error(self):
        proc = I.SyntheticProc()
        identity = proc.identity
        native = B.Proc('/synthetic-proc')
        count = [0]
        def recheck(pid, tid):
            count[0] += 1
            if count[0] == 1:
                return identity(pid, tid)
            with mock.patch.object(B.os, 'open', side_effect=PermissionError(errno.EACCES, CANARY)):
                return native.identity(pid, tid)
        with mock.patch.object(proc, 'identity', side_effect=recheck), \
                mock.patch.object(proc, 'maps', side_effect=FileNotFoundError(errno.ENOENT, CANARY)):
            self.failure(lambda: B.scan_references({I.TARGET}, self.budget(), proc=proc),
                         'identity_stat', 'EACCES')
        self.assertEqual(count[0], 2)

    def test_errno_buckets_are_closed_and_preserve_errors_without_raw_exception_values(self):
        cases = ((FileNotFoundError(errno.ENOENT, CANARY), 'ENOENT'),
                 (ProcessLookupError(errno.ESRCH, CANARY), 'ESRCH'),
                 (PermissionError(errno.EACCES, CANARY), 'EACCES'),
                 (PermissionError(errno.EPERM, CANARY), 'EPERM'),
                 (OSError(errno.EIO, CANARY), 'EIO'),
                 (OSError(errno.EMFILE, CANARY), 'OTHER_OS'),
                 (ValueError(CANARY), 'INVALID_VALUE'),
                 (UnicodeError(CANARY), 'INVALID_ENCODING'))
        for error, bucket in cases:
            with self.subTest(bucket=bucket), mock.patch.object(B.os, 'listdir', side_effect=error) as call:
                self.failure(lambda: B.scan_references({I.TARGET}, self.budget(),
                    proc=type('VisibleProc', (B.Proc,), {'visible': lambda self: None})('/synthetic')),
                    'population', bucket)
            call.assert_called_once()

    def test_actual_execute_refusal_keeps_plan_payload_and_mutations_unstarted(self):
        fixture = I.BundlePreservationContractTests('test_diagnose_observes_once_rechecks_generation_and_never_reads_or_writes_payloads')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        proc = B.Proc('/synthetic-proc')
        error = PermissionError(errno.EACCES, CANARY, '/' + CANARY)
        def denied(*args):
            with mock.patch.object(proc, 'visible', return_value=None), \
                    mock.patch.object(B.os, 'listdir', side_effect=error):
                B.scan_references({I.TARGET}, self.budget(), proc=proc)
        for mode in ('diagnose', 'plan'):
            with self.subTest(mode=mode), fixture.metadata_only():
                probe = mock.Mock(side_effect=denied)
                result = B.execute(mode, runner=fixture.runner, free=lambda: 10 * 1024 ** 3,
                    budget=fixture.budget, producer_probe=lambda *args: {'generation': 1},
                    reference_probe=probe)
            probe.assert_called_once()
            self.assertEqual(result['reason'], 'PROC_UNAVAILABLE')
            self.assertEqual(result['proc_diagnostic'], {'phase': 'population', 'errno_bucket': 'EACCES'})
            self.assertIsNone(result['plan'])
            self.assertIsNone(result['limit_diagnostic'])
            self.assertEqual(result['reference_checks'], 0)
            self.assertNotIn(CANARY, B.A.canonical(result))
            for field in ('source_bytes', 'compressed_bytes', 'projected_free_bytes'):
                self.assertIsNone(result[field])
            for field in ('archive_started', 'cleanup_started', 'database_opened', 'services_changed'):
                self.assertFalse(result[field])

    def test_closed_receipt_v3_rejects_raw_values_incompatible_reasons_and_old_shape(self):
        report = B.receipt('diagnose')
        self.assertEqual(report['version'], 3)
        self.assertIsNone(report['proc_diagnostic'])
        good = {'phase': 'fd_metadata', 'errno_bucket': 'EACCES'}
        refused = dict(report, reason='PROC_UNAVAILABLE', proc_diagnostic=good)
        self.assertEqual(B.validate_report(refused), refused)
        for bad in (dict(good, path=CANARY), dict(good, phase=CANARY),
                    dict(good, errno_bucket=13), dict(good, errno_bucket=True),
                    dict(good, errno_bucket=CANARY), {'phase': 'fd_metadata'}):
            with self.subTest(bad=bad), self.assertRaises(B.Refused):
                B.validate_report(dict(refused, proc_diagnostic=bad))
        for change in ({'version': 2}, {'reason': 'PROC_LIMIT'}, {'status': 'planned'},
                       {'limit_diagnostic': {'kind': 'fdinfo_bytes', 'cap': 4096,
                                             'observed_lower_bound': 4097}}):
            with self.subTest(change=change), self.assertRaises(B.Refused):
                B.validate_report(dict(refused, **change))
        missing = dict(report)
        del missing['proc_diagnostic']
        with self.assertRaises(B.Refused):
            B.validate_report(missing)


if __name__ == '__main__':
    unittest.main()
