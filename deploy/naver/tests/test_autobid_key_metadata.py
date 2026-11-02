"""Synthetic filesystem races and information boundaries; never touch the live path."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    'autobid_key_metadata', Path(__file__).resolve().parents[1] / 'autobid_key_metadata.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = 'PRIVATE_SYNTHETIC_KEY_CANARY'


class KeyMetadataTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(os.path.realpath(self.temp.name))
        self.parent = self.base.joinpath(*subject.PARENTS)
        self.parent.mkdir(parents=True)
        self.leaf = self.parent / '.env'
        self.leaf.write_text(CANARY)
        self.leaf.chmod(0o600)
        self.root = os.open(self.base, subject.DIRECTORY_FLAGS)

    def tearDown(self):
        os.close(self.root)
        self.temp.cleanup()

    def inspect(self):
        report = subject.observe(self.root)
        public = json.dumps(report)
        for forbidden in (CANARY, str(self.base), 'content-studio-deploy', '.env'):
            self.assertNotIn(forbidden, public)
        self.assertEqual(report['original_key_available'], 'unknown')
        self.assertEqual(report['stop_safety'], 'not_determined')
        return report

    def failed(self, expected):
        report = self.inspect()
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(report['error'], expected)
        self.assertEqual(report['candidate'], {'alias': subject.ALIAS, 'exists': None, 'kind': 'unknown'})
        return report

    def test_regular_candidate_metadata_matches_without_claiming_a_key(self):
        report = self.inspect()
        self.assertEqual(report['status'], 'complete')
        self.assertIsNone(report['error'])
        self.assertTrue(report['candidate']['exists'])
        self.assertEqual(report['candidate']['kind'], 'regular_file')
        self.assertEqual(report['candidate']['size_bytes'], len(CANARY))
        self.assertEqual(report['candidate']['mode'], 0o600)
        self.assertEqual(report['candidate']['inode'], self.leaf.stat().st_ino)
        for key, value in report['candidate'].items():
            if key not in {'alias', 'kind', 'exists'}:
                self.assertIs(type(value), int)

    def test_empty_candidate_is_not_key_availability_proof(self):
        self.leaf.write_bytes(b'')
        self.assertEqual(self.inspect()['candidate']['size_bytes'], 0)

    def test_stable_absence_of_leaf_is_distinct_from_failure(self):
        self.leaf.unlink()
        report = self.inspect()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['error'], 'target_absent')
        self.assertFalse(report['candidate']['exists'])

    def test_each_missing_parent_is_not_a_permission_or_key_result(self):
        for index in range(len(subject.PARENTS)):
            path = self.base.joinpath(*subject.PARENTS[:index + 1])
            moved = path.with_name(path.name + '-moved')
            path.rename(moved)
            try:
                report = self.inspect()
                self.assertEqual(report['status'], 'complete')
                self.assertEqual(report['error'], 'parent_absent')
                self.assertFalse(report['candidate']['exists'])
            finally:
                moved.rename(path)

    def test_each_parent_symlink_is_refused_even_when_destination_is_valid(self):
        for index in range(len(subject.PARENTS)):
            path = self.base.joinpath(*subject.PARENTS[:index + 1])
            moved = path.with_name(path.name + '-moved')
            path.rename(moved)
            path.symlink_to(moved, target_is_directory=True)
            try:
                self.failed('parent_symlink_refused')
            finally:
                path.unlink()
                moved.rename(path)

    def test_non_directory_parent_is_refused(self):
        self.leaf.unlink()
        self.parent.rmdir()
        self.parent.write_text(CANARY)
        self.failed('parent_type_refused')

    def test_target_symlink_is_not_followed(self):
        self.leaf.unlink()
        self.leaf.symlink_to(self.base / CANARY)
        self.failed('target_symlink_refused')

    def test_target_directory_is_refused(self):
        self.leaf.unlink()
        self.leaf.mkdir()
        self.failed('target_type_refused')

    def test_target_fifo_does_not_block_or_open(self):
        self.leaf.unlink()
        os.mkfifo(self.leaf)
        self.failed('target_type_refused')

    def test_permission_error_never_becomes_absence_or_leaks_message(self):
        real_stat = os.stat

        def denied(path, *args, **kwargs):
            if path == subject.LEAF:
                raise PermissionError(CANARY)
            return real_stat(path, *args, **kwargs)

        with mock.patch.object(subject.os, 'stat', side_effect=denied):
            self.failed('permission_denied')

    def test_unexpected_metadata_failure_is_sanitized(self):
        with mock.patch.object(subject.os, 'fstat', side_effect=RuntimeError(CANARY)):
            self.failed('metadata_failed')

    def test_parent_replaced_between_stat_and_open_is_refused(self):
        real_open = os.open

        def replace(path, flags, *args, **kwargs):
            if path == 'autobid':
                self.parent.rename(self.parent.with_name('old-parent'))
                self.parent.mkdir()
            return real_open(path, flags, *args, **kwargs)

        with mock.patch.object(subject.os, 'open', side_effect=replace):
            self.failed('changed_during_query')

    def test_open_parent_path_replacement_is_detected_even_though_fd_survives(self):
        real_stat = os.stat
        changed = False

        def replace(path, *args, **kwargs):
            nonlocal changed
            answer = real_stat(path, *args, **kwargs)
            if path == subject.LEAF and not changed:
                changed = True
                self.parent.rename(self.parent.with_name('old-parent'))
                self.parent.mkdir()
            return answer

        with mock.patch.object(subject.os, 'stat', side_effect=replace):
            self.failed('changed_during_query')

    def test_parent_replaced_during_final_leaf_stat_is_refused(self):
        real_stat = os.stat
        leaf_queries = 0

        def replace(path, *args, **kwargs):
            nonlocal leaf_queries
            answer = real_stat(path, *args, **kwargs)
            if path == subject.LEAF:
                leaf_queries += 1
                if leaf_queries == 2:
                    self.parent.rename(self.parent.with_name('old-parent'))
                    self.parent.mkdir()
            return answer

        with mock.patch.object(subject.os, 'stat', side_effect=replace):
            self.failed('changed_during_query')

    def test_leaf_rotation_is_refused(self):
        real_stat = os.stat
        changed = False

        def rotate(path, *args, **kwargs):
            nonlocal changed
            answer = real_stat(path, *args, **kwargs)
            if path == subject.LEAF and not changed:
                changed = True
                replacement = self.parent / 'replacement'
                replacement.write_text(CANARY)
                replacement.replace(self.leaf)
            return answer

        with mock.patch.object(subject.os, 'stat', side_effect=rotate):
            self.failed('changed_during_query')

    def test_disappearing_leaf_is_refused(self):
        real_stat = os.stat
        changed = False

        def disappear(path, *args, **kwargs):
            nonlocal changed
            answer = real_stat(path, *args, **kwargs)
            if path == subject.LEAF and not changed:
                changed = True
                self.leaf.unlink()
            return answer

        with mock.patch.object(subject.os, 'stat', side_effect=disappear):
            self.failed('changed_during_query')

    def test_appearing_leaf_is_refused(self):
        self.leaf.unlink()
        real_stat = os.stat

        def appear(path, *args, **kwargs):
            try:
                return real_stat(path, *args, **kwargs)
            except FileNotFoundError:
                if path == subject.LEAF:
                    self.leaf.write_text(CANARY)
                raise

        with mock.patch.object(subject.os, 'stat', side_effect=appear):
            self.failed('changed_during_query')

    def test_missing_parent_appearing_during_query_is_refused(self):
        self.leaf.unlink()
        self.parent.rmdir()
        real_stat = os.stat

        def appear(path, *args, **kwargs):
            try:
                return real_stat(path, *args, **kwargs)
            except FileNotFoundError:
                if path == 'autobid':
                    self.parent.mkdir()
                raise

        with mock.patch.object(subject.os, 'stat', side_effect=appear):
            self.failed('changed_during_query')

    def test_only_fixed_directory_opens_no_reads_enumeration_env_or_target_open(self):
        real_open = os.open

        def directory_only(path, flags, *args, **kwargs):
            self.assertIn(path, subject.PARENTS)
            self.assertEqual(flags, subject.DIRECTORY_FLAGS)
            return real_open(path, flags, *args, **kwargs)

        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(subject.os, 'open', side_effect=directory_only))
            for name in ('read', 'pread', 'listdir', 'scandir', 'readlink', 'getenv'):
                stack.enter_context(mock.patch.object(subject.os, name, side_effect=AssertionError(CANARY)))
            stack.enter_context(mock.patch('builtins.open', side_effect=AssertionError(CANARY)))
            self.assertEqual(self.inspect()['status'], 'complete')

    def test_all_acquired_descriptors_are_closed_on_success_and_failure(self):
        real_open, real_close = os.open, os.close
        for failure in (False, True):
            opened, closed = [], []

            def track_open(*args, **kwargs):
                fd = real_open(*args, **kwargs)
                opened.append(fd)
                return fd

            def track_close(fd):
                closed.append(fd)
                real_close(fd)

            with mock.patch.object(subject.os, 'open', side_effect=track_open), \
                    mock.patch.object(subject.os, 'close', side_effect=track_close):
                if failure:
                    with mock.patch.object(subject, 'validate_chain', side_effect=PermissionError(CANARY)):
                        self.failed('permission_denied')
                else:
                    self.inspect()
            self.assertEqual(sorted(opened), sorted(closed))
            self.assertNotIn(self.root, closed)

    def test_non_directory_root_descriptor_is_refused(self):
        with self.leaf.open('rb') as synthetic_file:
            answer = subject.observe(synthetic_file.fileno())
        self.assertEqual(answer['error'], 'root_type_refused')


class KeyMetadataCliTest(unittest.TestCase):
    def call(self, argv=(), uid=0, returned=None, error=None):
        stream = io.StringIO()
        with mock.patch.object(subject.sys, 'argv', ['helper'] + list(argv)), \
                mock.patch.object(subject.os, 'geteuid', return_value=uid), \
                mock.patch.object(subject, 'collect', return_value=returned, side_effect=error) as collector, \
                mock.patch.object(subject.signal, 'signal'), mock.patch.object(subject.signal, 'alarm') as alarm, \
                contextlib.redirect_stdout(stream):
            rc = subject.main()
        self.assertNotIn(CANARY, stream.getvalue())
        return rc, json.loads(stream.getvalue()), collector, alarm

    def test_cli_rejects_any_argument_before_filesystem_access(self):
        for argv in (['--path', CANARY], ['--help'], [CANARY]):
            rc, answer, collector, alarm = self.call(argv=argv)
            self.assertEqual(rc, 2)
            self.assertEqual(answer['error'], 'arguments_not_allowed')
            collector.assert_not_called()
            alarm.assert_not_called()

    def test_non_root_is_rejected_without_probe(self):
        rc, answer, collector, _ = self.call(uid=501)
        self.assertEqual((rc, answer['error']), (2, 'root_required'))
        collector.assert_not_called()

    def test_deadline_fails_closed_and_clears_alarm(self):
        rc, answer, _, alarm = self.call(error=subject.DeadlineExpired())
        self.assertEqual((rc, answer['error']), (2, 'deadline_exceeded'))
        self.assertIsNone(answer['candidate']['exists'])
        self.assertEqual(alarm.call_args_list, [mock.call(subject.TIME_BUDGET), mock.call(0)])

    def test_unexpected_cli_failure_never_prints_exception(self):
        rc, answer, _, _ = self.call(error=RuntimeError(CANARY))
        self.assertEqual((rc, answer['error']), (2, 'metadata_failed'))

    def test_oversized_report_is_replaced_with_fixed_failure(self):
        report = subject.result()
        report['untrusted'] = CANARY * 1000
        rc, answer, _, _ = self.call(returned=report)
        self.assertEqual((rc, answer['error']), (2, 'report_limit_exceeded'))

    def test_complete_result_only_controls_exit_not_key_or_stop_claim(self):
        report = subject.result()
        report.update(status='complete', error='target_absent')
        rc, answer, collector, _ = self.call(returned=report)
        self.assertEqual(rc, 0)
        collector.assert_called_once_with()
        self.assertEqual(answer['original_key_available'], 'unknown')
        self.assertEqual(answer['stop_safety'], 'not_determined')


if __name__ == '__main__':
    unittest.main()
