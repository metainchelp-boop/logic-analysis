"""Current-task closed descriptors only; synthetic sources, no host operations."""
import ctypes
import errno
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

import test_backup_bundle_independent as I

B = I.B


class CurrentTaskClosedFdTests(unittest.TestCase):
    def setUp(self):
        self.person = (os.getpid(), threading.get_native_id())
        self.number = 1000000  # Closed synthetic descriptor, never a caller input.

    def proc(self, person=None):
        person = person or self.person
        proc = I.SyntheticProc((person,))
        proc.tasks[person]['fds'][self.number] = (I.metadata(I.UNRELATED), 0)
        return proc

    def scan(self, proc, **kwargs):
        return B.scan_references({I.TARGET}, B.A.Budget(clock=lambda: 0), proc=proc, **kwargs)

    def refused(self, proc, reason='PROC_UNAVAILABLE', **kwargs):
        with self.assertRaises(B.Refused) as caught:
            self.scan(proc, **kwargs)
        self.assertEqual(str(caught.exception), reason)
        return caught.exception

    def test_current_task_missing_metadata_closed_now_keeps_both_passes_and_rechecks(self):
        for missing in (FileNotFoundError(errno.ENOENT, I.CANARY),
                        ProcessLookupError(errno.ESRCH, I.CANARY)):
            with self.subTest(errno=missing.errno):
                proc = self.proc()
                with mock.patch.object(proc, 'fd_metadata', side_effect=missing), \
                        mock.patch.object(B.os, 'fstat', wraps=os.fstat) as direct, \
                        I.LimitDiagnosticContractTests().traced(proc) as calls:
                    result = self.scan(proc)
                self.assertEqual(result, dict(process_generations=1, fd_observations=2,
                    map_observations=0, late_generations=0, exited_generations=0,
                    reference_count=0, passes=2))
                self.assertEqual(direct.call_args_list, [mock.call(self.number)] * 2)
                self.assertEqual({k: v.call_count for k, v in calls.items()},
                    dict(visible=1, population=4, identity=4, present=0, fds=8,
                         fd_metadata=2, fd_flags=0, fd=0, maps=4, link=4))

    def test_other_pid_or_native_tid_never_probes_callers_descriptor_table(self):
        for person in ((self.person[0] + 1, self.person[1]),
                       (self.person[0], self.person[1] + 1)):
            proc = self.proc(person)
            with self.subTest(person=person), \
                    mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(errno.ENOENT, I.CANARY)), \
                    mock.patch.object(B.os, 'fstat', side_effect=AssertionError('wrong table')) as direct:
                self.refused(proc)
            direct.assert_not_called()

    def test_valid_descriptor_and_non_ebadf_probe_errors_remain_refused(self):
        with tempfile.TemporaryFile() as opened:
            for outcome in (os.fstat(opened.fileno()), OSError(errno.EIO, I.CANARY),
                            PermissionError(errno.EACCES, I.CANARY),
                            FileNotFoundError(errno.ENOENT, I.CANARY)):
                proc = self.proc()
                kwargs = {'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome}
                with self.subTest(outcome=type(outcome).__name__), \
                        mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(errno.ENOENT, I.CANARY)), \
                        mock.patch.object(B.os, 'fstat', **kwargs) as direct:
                    self.refused(proc)
                direct.assert_called_once_with(self.number)

    def test_nonmissing_metadata_error_cannot_use_closed_probe(self):
        for error in (PermissionError(errno.EACCES, I.CANARY), OSError(errno.EIO, I.CANARY),
                      FileNotFoundError(errno.EACCES, I.CANARY), FileNotFoundError(I.CANARY)):
            proc = self.proc()
            with self.subTest(error=type(error).__name__, errno=error.errno), \
                    mock.patch.object(proc, 'fd_metadata', side_effect=error), \
                    mock.patch.object(B.os, 'fstat', side_effect=AssertionError('not eligible')) as direct:
                self.refused(proc)
            direct.assert_not_called()

    def test_missing_pinned_observer_slot_cannot_be_excused_by_temporary_list_fd_reuse(self):
        proc = self.proc()
        meta = I.metadata()
        observer = (*self.person, proc.identity(*self.person), self.number, meta, 0)
        # The current listing may reuse the now-closed pinned slot. It remains a broken pin.
        with mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(errno.ENOENT, I.CANARY)), \
                mock.patch.object(B.os, 'fstat', side_effect=AssertionError('pinned slot')) as direct:
            self.refused(proc, observer_fds=(observer,))
        direct.assert_not_called()

    def test_positive_source_reference_all_modes_never_uses_closed_probe(self):
        for flags in (os.O_RDONLY, os.O_WRONLY, os.O_RDWR, getattr(os, 'O_PATH', 0o10000000)):
            proc = self.proc()
            proc.tasks[self.person]['fds'][self.number] = (I.metadata(), flags)
            with self.subTest(flags=flags), \
                    mock.patch.object(B.os, 'fstat', side_effect=AssertionError('positive reference')) as direct:
                self.refused(proc, 'SOURCE_IN_USE')
            direct.assert_not_called()

    def test_pinned_flags_missing_or_final_identity_changed_gets_no_closed_exception(self):
        for stage in ('flags', 'reread'):
            proc = self.proc()
            meta = I.metadata()
            proc.tasks[self.person]['fds'][self.number] = (meta, 0)
            observer = (*self.person, proc.identity(*self.person), self.number, meta, 0)
            change = (mock.patch.object(proc, 'fd_flags', side_effect=FileNotFoundError(errno.ENOENT, I.CANARY))
                      if stage == 'flags' else
                      mock.patch.object(proc, 'fd', return_value=(dict(meta, inode=meta['inode'] + 1), 0)))
            with self.subTest(stage=stage), change, \
                    mock.patch.object(B.os, 'fstat', side_effect=AssertionError('pinned evidence')) as direct:
                self.refused(proc, 'PROC_UNAVAILABLE' if stage == 'flags' else 'PROC_CHANGED',
                             observer_fds=(observer,))
            direct.assert_not_called()

    def test_generation_and_total_fd_limit_still_refuse_after_closed_probe(self):
        proc = self.proc()
        generation = proc.identity(*self.person)
        with mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(errno.ENOENT, I.CANARY)), \
                mock.patch.object(proc, 'identity', side_effect=[generation, (999,) + generation[1:]]):
            self.refused(proc, 'PROC_CHANGED')
        proc = self.proc()
        with mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(errno.ENOENT, I.CANARY)), \
                mock.patch.object(B, 'MAX_FDS', 1), mock.patch.object(B.os, 'fstat', wraps=os.fstat) as direct:
            self.refused(proc, 'PROC_LIMIT')
        direct.assert_called_once_with(self.number)

    def test_reuse_before_probe_refuses_and_persistent_reuse_after_probe_is_seen_next_pass(self):
        for timing in ('before', 'after'):
            with self.subTest(timing=timing), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'synthetic'
                path.write_bytes(b'SYNTHETIC-ONLY')
                number = os.open(path, os.O_RDONLY)
                os.close(number)
                self.number = number
                proc = self.proc()
                native_fstat = os.fstat
                handles = []
                def reuse():
                    current = os.open(path, os.O_RDONLY)
                    handles.append(current)
                    self.assertEqual(current, number)
                    proc.tasks[self.person]['fds'][number] = (I.metadata(), 0)
                def metadata(*args):
                    if handles:
                        return I.metadata()
                    if timing == 'before':
                        reuse()
                    raise FileNotFoundError(errno.ENOENT, I.CANARY)
                def direct(value):
                    try:
                        return native_fstat(value)
                    except OSError as error:
                        if timing == 'after' and error.errno == errno.EBADF:
                            reuse()
                        raise
                try:
                    with mock.patch.object(proc, 'fd_metadata', side_effect=metadata), \
                            mock.patch.object(B.os, 'fstat', side_effect=direct) as check:
                        self.refused(proc, 'PROC_UNAVAILABLE' if timing == 'before' else 'SOURCE_IN_USE')
                    check.assert_called_once_with(number)
                finally:
                    for fd in handles:
                        os.close(fd)


@unittest.skipUnless(sys.platform == 'linux', 'native Linux task/FD contract')
class NativeCurrentTaskTests(unittest.TestCase):
    class CurrentTaskProc(B.Proc):
        """Bounded native task fixture; does not inventory other host processes."""
        def population(self, budget):
            budget.check()
            person = (os.getpid(), threading.get_native_id())
            return {person: self.identity(*person)}

        def visible(self):
            pass  # Global host visibility is unchanged and covered independently.

    def scan(self, targets, proc=None):
        return B.scan_references(targets, B.A.Budget(), proc=proc or self.CurrentTaskProc())

    def test_native_list_temporary_closed_fd_no_longer_refuses_current_task(self):
        with mock.patch.object(B.os, 'fstat', wraps=os.fstat) as direct:
            result = self.scan({I.TARGET})
        self.assertEqual(result['reference_count'], 0)
        self.assertEqual(result['process_generations'], 1)
        self.assertEqual(result['passes'], 2)
        self.assertGreaterEqual(direct.call_count, 2)

    def test_native_readonly_readwrite_opath_and_unlinked_sources_are_all_in_use(self):
        for mode in (os.O_RDONLY, os.O_RDWR, os.O_PATH):
            for unlinked in (False, True):
                with self.subTest(mode=mode, unlinked=unlinked), tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / 'synthetic'
                    path.write_bytes(b'SYNTHETIC-ONLY')
                    fd = os.open(path, mode)
                    try:
                        info = os.fstat(fd)
                        if unlinked:
                            path.unlink()
                        with self.assertRaises(B.Refused) as caught:
                            self.scan({(info.st_dev, info.st_ino)})
                        self.assertEqual(str(caught.exception), 'SOURCE_IN_USE')
                    finally:
                        os.close(fd)

    def test_same_pid_other_thread_private_fd_table_never_uses_callers_ebadf(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'synthetic'
            path.write_bytes(b'SYNTHETIC-ONLY')
            source = os.open(path, os.O_RDONLY)
            kept, trigger = os.dup(source), os.dup(source)
            ready, release = threading.Event(), threading.Event()
            state = {}
            libc = ctypes.CDLL(None, use_errno=True)
            close_range = libc.close_range
            close_range.argtypes = (ctypes.c_uint, ctypes.c_uint, ctypes.c_int)
            close_range.restype = ctypes.c_int
            def worker():
                try:
                    state['tid'] = threading.get_native_id()
                    # An actual distinct file table within the same thread group.
                    if close_range(trigger, trigger, 2):  # CLOSE_RANGE_UNSHARE
                        raise AssertionError('native fixture unshare failed')
                    ready.set()
                    if not release.wait(5):
                        raise AssertionError('fixture release timeout')
                    state['valid'] = os.fstat(kept).st_ino == os.stat(path).st_ino
                    os.close(kept)
                except Exception as error:
                    state['error'] = type(error).__name__
                    ready.set()
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(ready.wait(5))
                self.assertNotIn('error', state)
                os.close(kept)
                person = (os.getpid(), state['tid'])
                proc = I.SyntheticProc((person,))
                proc.tasks[person]['fds'][kept] = (I.metadata(), 0)
                with mock.patch.object(proc, 'fd_metadata', side_effect=FileNotFoundError(errno.ENOENT, I.CANARY)), \
                        mock.patch.object(B.os, 'fstat', side_effect=AssertionError('other task table')) as direct:
                    with self.assertRaises(B.Refused) as caught:
                        self.scan({I.TARGET}, proc)
                    self.assertEqual(str(caught.exception), 'PROC_UNAVAILABLE')
                direct.assert_not_called()
                release.set()
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertNotIn('error', state)
                self.assertTrue(state['valid'])
            finally:
                release.set()
                thread.join(5)
                for fd in (kept, trigger, source):
                    try:
                        os.close(fd)
                    except OSError as error:
                        self.assertEqual(error.errno, errno.EBADF)


if __name__ == '__main__':
    unittest.main()
