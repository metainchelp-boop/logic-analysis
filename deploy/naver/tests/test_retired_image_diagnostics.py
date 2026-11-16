"""Failure diagnostics identify bounded command phases, never Docker output."""

import contextlib
import copy
import errno
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'retired_image_diagnostics_fixtures',
    Path(__file__).with_name('test_retired_image_inspect.py'))
F = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(F)
R = F.R
CANARY = F.CANARY


def failed_report(index=1, error=None, fixture=None):
    """Inject failure after successful earlier commands in a realistic inventory."""
    docker = F.FakeDocker(fixture)
    calls = 0

    def run(command):
        nonlocal calls
        calls += 1
        if calls == index:
            raise error if error is not None else R.Refused('COMMAND_FAILED')
        return docker(command)

    return R.collect_report(run)


class FailurePhaseTests(unittest.TestCase):
    def assert_safe_failure(self, report):
        self.assertEqual(report['schema_version'], 2)
        self.assertEqual(report['status'], 'INCOMPLETE')
        self.assertIsNone(report['docker'])
        self.assertIs(report['delete_authorized'], False)
        self.assertIs(report['backup_currently_verified'], False)
        self.assertIsNone(report['reclaimable_bytes'])
        for candidate in report['candidates']:
            self.assertEqual(candidate['status'], 'UNKNOWN')
            self.assertIsNone(candidate['image'])
            self.assertIsNone(candidate['references'])
        self.assertNotIn(CANARY, R.canonical(report))
        self.assertIs(R.validate_report(report), report)

    def test_identical_command_failure_can_identify_first_or_second_snapshot(self):
        for index, snapshot, stage in ((1, 1, 'INFO'), (10, 2, 'INFO'),
                                       (18, 2, 'ANCESTOR_FILTER')):
            with self.subTest(index=index):
                report = failed_report(index)
                self.assert_safe_failure(report)
                self.assertEqual(report['reason'], 'COMMAND_FAILED')
                self.assertEqual(report['diagnostic'], dict(
                    snapshot=snapshot, command_index=index, stage=stage,
                    code='COMMAND_NONZERO', exit_code=None))

    def test_all_command_kinds_have_fixed_stage_names(self):
        value = F.fixture()
        value['containers'][F.CONTAINER] = dict(
            id=F.CONTAINER, image=F.EXTRA_IMAGE, state='exited')
        stages = ('INFO', 'IMAGE_LIST', 'CONTAINER_LIST', 'IMAGE_INSPECT',
                  'CONTAINER_INSPECT', 'ANCESTOR_FILTER')
        for index, stage in enumerate(stages, 1):
            with self.subTest(stage=stage):
                report = failed_report(index, fixture=value)
                self.assert_safe_failure(report)
                self.assertEqual(report['diagnostic']['stage'], stage)
                self.assertEqual(report['diagnostic']['command_index'], index)
                self.assertEqual(report['diagnostic']['snapshot'], 1)

    def test_exit_codes_and_fixed_failure_classes_survive_projection(self):
        cases = [('COMMAND_FAILED', code, 1) for code in (
            'PARENT_KEY_MISSING', 'TEMPLATE_ERROR', 'DAEMON_UNAVAILABLE',
            'OBJECT_NOT_FOUND', 'COMMAND_NONZERO')]
        cases += [('COMMAND_FAILED', code, None) for code in (
            'OS_NOT_FOUND', 'OS_PERMISSION', 'OS_OTHER')]
        cases += [(code, code, None) for code in (
            'COMMAND_TIMEOUT', 'OUTPUT_LIMIT', 'INVALID_METADATA')]
        for reason, code, exit_code in cases:
            with self.subTest(code=code):
                report = failed_report(error=R.Refused(
                    reason, code=code, exit_code=exit_code))
                self.assert_safe_failure(report)
                self.assertEqual(report['reason'], reason)
                self.assertEqual(report['diagnostic']['code'], code)
                self.assertEqual(report['diagnostic']['exit_code'], exit_code)

    def test_session_output_type_and_budget_failures_keep_the_command_phase(self):
        for result, expected in ((CANARY, 'INVALID_METADATA'),
                                 (b'x' * (R.MAX_COMMAND_BYTES + 1), 'OUTPUT_LIMIT')):
            with self.subTest(reason=expected):
                report = R.collect_report(lambda command: result)
                self.assert_safe_failure(report)
                self.assertEqual(report['reason'], expected)
                self.assertEqual(report['diagnostic'], dict(
                    snapshot=1, command_index=1, stage='INFO',
                    code=expected, exit_code=None))

    def test_success_and_changed_inventory_have_no_failure_diagnostic(self):
        first = F.fixture()
        second = copy.deepcopy(first)
        second['info']['server_version'] = '29.0.0'
        for runner, status in ((F.FakeDocker(), 'COMPLETE_STABLE'),
                               (F.FakeDocker(first, second), 'CHANGED')):
            with self.subTest(status=status):
                report = R.collect_report(runner)
                self.assertEqual(report['status'], status)
                self.assertEqual(report['schema_version'], 2)
                self.assertIsNone(report['diagnostic'])
                self.assertIs(R.validate_report(report), report)

    def test_generic_private_errors_are_not_promoted_to_diagnostics(self):
        for error in (ValueError(CANARY), R.Refused(CANARY)):
            with self.subTest(error=type(error).__name__):
                report = failed_report(error=error)
                self.assert_safe_failure(report)
                self.assertEqual(report['reason'], 'INTERNAL_ERROR')
                self.assertIsNone(report['diagnostic'])

    def test_platform_and_argument_guards_emit_null_diagnostic_without_commands(self):
        for platform, uid, args, reason in (
            ('darwin', 0, [], 'UNSUPPORTED_PLATFORM'),
            ('linux', 1000, [], 'NOT_ROOT'),
            ('linux', 0, ['--delete'], 'INPUT_REFUSED'),
        ):
            with self.subTest(reason=reason), patch.object(R.sys, 'platform', platform), \
                    patch.object(R.os, 'geteuid', return_value=uid), \
                    patch.object(R, 'collect_report') as collect:
                output, error = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    self.assertEqual(R.main(args), 2)
                collect.assert_not_called()
                self.assertEqual(error.getvalue(), '')
                report = R.strict_json(output.getvalue())
                self.assert_safe_failure(report)
                self.assertEqual(report['reason'], reason)
                self.assertIsNone(report['diagnostic'])


class DiagnosticSchemaTests(unittest.TestCase):
    def setUp(self):
        self.report = failed_report(error=R.Refused(
            'COMMAND_FAILED', code='TEMPLATE_ERROR', exit_code=1))

    def test_diagnostic_is_a_closed_object(self):
        for change in ('extra', 'missing', 'list', 'string'):
            with self.subTest(change=change):
                value = copy.deepcopy(self.report)
                if change == 'extra':
                    value['diagnostic']['stderr'] = CANARY
                elif change == 'missing':
                    del value['diagnostic']['exit_code']
                elif change == 'list':
                    value['diagnostic'] = []
                else:
                    value['diagnostic'] = CANARY
                with self.assertRaises(R.Refused):
                    R.validate_report(value)

    def test_fields_reject_forged_strings_booleans_and_out_of_range_numbers(self):
        cases = {
            'snapshot': (True, False, 0, 3, '1', None),
            'command_index': (True, 0, 305, -1, '1', None),
            'stage': (CANARY, '', 'info', None, 1, []),
            'code': (CANARY, '', 'INPUT_REFUSED', None, 1, []),
            'exit_code': (True, False, 0, -65, 256, '1', 1.0, None),
        }
        for field, replacements in cases.items():
            for replacement in replacements:
                with self.subTest(field=field, replacement=replacement):
                    value = copy.deepcopy(self.report)
                    value['diagnostic'][field] = replacement
                    with self.assertRaises(R.Refused):
                        R.validate_report(value)

    def test_only_legacy_command_nonzero_allows_missing_process_exit_code(self):
        for code in ('PARENT_KEY_MISSING', 'TEMPLATE_ERROR', 'DAEMON_UNAVAILABLE',
                     'OBJECT_NOT_FOUND', 'COMMAND_NONZERO'):
            value = copy.deepcopy(self.report)
            value['diagnostic'].update(code=code, exit_code=None)
            with self.subTest(code=code):
                if code == 'COMMAND_NONZERO':
                    self.assertIs(R.validate_report(value), value)
                else:
                    with self.assertRaises(R.Refused):
                        R.validate_report(value)

    def test_os_and_session_errors_cannot_claim_a_process_exit_status(self):
        for code in ('OS_NOT_FOUND', 'OS_PERMISSION', 'OS_OTHER',
                     'COMMAND_TIMEOUT', 'OUTPUT_LIMIT', 'INVALID_METADATA'):
            value = copy.deepcopy(self.report)
            value['diagnostic'].update(code=code, exit_code=1)
            if code in ('COMMAND_TIMEOUT', 'OUTPUT_LIMIT', 'INVALID_METADATA'):
                value['reason'] = code
            with self.subTest(code=code), self.assertRaises(R.Refused):
                R.validate_report(value)

    def test_reason_and_diagnostic_cannot_contradict_each_other(self):
        for reason in ('COMMAND_TIMEOUT', 'OUTPUT_LIMIT', 'INVALID_METADATA',
                       'INPUT_REFUSED', 'NOT_ROOT', 'INTERNAL_ERROR'):
            value = copy.deepcopy(self.report)
            value['reason'] = reason
            with self.subTest(reason=reason), self.assertRaises(R.Refused):
                R.validate_report(value)

    def test_complete_or_changed_report_cannot_carry_a_failure_diagnostic(self):
        for report in (R.collect_report(F.FakeDocker()),
                       R.empty_report('INVENTORY_CHANGED', True)):
            report['diagnostic'] = copy.deepcopy(self.report['diagnostic'])
            with self.subTest(status=report['status']), self.assertRaises(R.Refused):
                R.validate_report(report)

    def test_schema_version_must_be_exactly_two_and_diagnostic_must_be_present(self):
        for version in (1, 3, True, '2', 2.0, None):
            value = copy.deepcopy(self.report)
            value['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(R.Refused):
                R.validate_report(value)
        value = copy.deepcopy(self.report)
        del value['diagnostic']
        with self.assertRaises(R.Refused):
            R.validate_report(value)


class ProcessDiagnosticTests(unittest.TestCase):
    def run_python_report(self, script, **limits):
        real_popen = subprocess.Popen

        def launch(command, **kwargs):
            return real_popen((sys.executable, '-c', script), **kwargs)

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(R.subprocess, 'Popen', side_effect=launch))
            for name, value in limits.items():
                stack.enter_context(patch.object(R, name, value))
            output, error = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                report = R.collect_report(R.Runner())
            self.assertEqual(output.getvalue(), '')
            self.assertEqual(error.getvalue(), '')
        self.assertNotIn(CANARY, R.canonical(report))
        self.assertIs(R.validate_report(report), report)
        return report

    def test_private_process_stderr_is_reduced_to_fixed_code_and_exit(self):
        cases = (
            ('template parsing error: secret-template', 'TEMPLATE_ERROR'),
            ('template execution error: secret-template', 'TEMPLATE_ERROR'),
            ('template execution error: executing at <.Parent>: '
             'map has no entry for key "Parent"', 'PARENT_KEY_MISSING'),
            ('Cannot connect to the Docker daemon at unix:///private.sock', 'DAEMON_UNAVAILABLE'),
            ('error during connect: private-address', 'DAEMON_UNAVAILABLE'),
            ('failed to connect to the docker API at private-address', 'DAEMON_UNAVAILABLE'),
            ('No such image: private/image:tag', 'OBJECT_NOT_FOUND'),
            ('No such container: private-container', 'OBJECT_NOT_FOUND'),
            ('No such object: private-object', 'OBJECT_NOT_FOUND'),
            ('unrecognized private failure', 'COMMAND_NONZERO'),
            ('<.Parent> without the missing-key error', 'COMMAND_NONZERO'),
            ('map has no entry for key "Parent" without the field marker', 'COMMAND_NONZERO'),
        )
        for message, expected in cases:
            with self.subTest(code=expected, message=message):
                stderr = (CANARY + ' ' + message).encode()
                script = ('import os; os.write(1, ' + repr(CANARY.encode()) + '); '
                          'os.write(2, ' + repr(stderr) + '); raise SystemExit(7)')
                report = self.run_python_report(script)
                self.assertEqual(report['reason'], 'COMMAND_FAILED')
                self.assertEqual(report['diagnostic'], dict(
                    snapshot=1, command_index=1, stage='INFO',
                    code=expected, exit_code=7))
                self.assertNotIn(message, R.canonical(report))

    def test_launch_os_errors_do_not_leak_private_paths(self):
        for number, expected in ((errno.ENOENT, 'OS_NOT_FOUND'),
                                 (errno.EACCES, 'OS_PERMISSION'),
                                 (errno.EPERM, 'OS_PERMISSION'),
                                 (errno.EIO, 'OS_OTHER')):
            with self.subTest(errno=number), patch.object(
                    R.subprocess, 'Popen', side_effect=OSError(number, CANARY, '/private/' + CANARY)):
                report = R.collect_report(R.Runner())
                self.assertEqual(report['reason'], 'COMMAND_FAILED')
                self.assertEqual(report['diagnostic'], dict(
                    snapshot=1, command_index=1, stage='INFO', code=expected, exit_code=None))
                self.assertNotIn(CANARY, R.canonical(report))
                self.assertIs(R.validate_report(report), report)

    def test_private_stderr_counts_toward_limit_and_timeout_has_no_exit_code(self):
        script = 'import os; os.write(2, ' + repr((CANARY * 1000).encode()) + ')'
        report = self.run_python_report(script, MAX_COMMAND_BYTES=256)
        self.assertEqual(report['reason'], 'OUTPUT_LIMIT')
        self.assertEqual(report['diagnostic']['code'], 'OUTPUT_LIMIT')
        self.assertIsNone(report['diagnostic']['exit_code'])
        report = self.run_python_report('import time; time.sleep(2)', COMMAND_SECONDS=0.05)
        self.assertEqual(report['reason'], 'COMMAND_TIMEOUT')
        self.assertEqual(report['diagnostic']['code'], 'COMMAND_TIMEOUT')
        self.assertIsNone(report['diagnostic']['exit_code'])


if __name__ == '__main__':
    unittest.main()
