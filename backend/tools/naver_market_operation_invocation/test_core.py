import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('invocation_core', HERE / 'core.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def record(role='reader', kind=C.SUCCESS, index=1):
    value = {'_PID': '1', '_UID': '0', '_COMM': 'systemd', '_TRANSPORT': 'journal',
        'UNIT': C.UNITS[role], 'INVOCATION_ID': ('1' if role == 'reader' else '2') * 32,
        'MESSAGE_ID': kind, '__CURSOR': 'fixed-cursor-' + str(index),
        '__REALTIME_TIMESTAMP': str(C.START_US + index),
        '__MONOTONIC_TIMESTAMP': str(index), '_BOOT_ID': 'a' * 32}
    if kind == C.FAILURE: value['UNIT_RESULT'] = 'exit-code'
    if kind == C.EXIT: value.update(EXIT_CODE='exited', EXIT_STATUS='1')
    return value


def raw(*rows):
    return b'\n'.join(json.dumps(x, separators=(',', ':')).encode() for x in rows)


class InvocationCoreTests(unittest.TestCase):
    def rejected(self, *rows, code=None):
        with self.assertRaises(C.Refused) as caught: C.parse(raw(*rows))
        if code is not None: self.assertEqual(caught.exception.args, (code,))

    def test_fixed_query_has_only_fixed_units_window_and_metadata(self):
        argv = C._argv()
        self.assertEqual(argv[0], '/usr/bin/journalctl')
        self.assertEqual({x[5:] for x in argv if x.startswith('UNIT=')}, set(C.UNITS.values()))
        fields = next(x.split('=', 1)[1] for x in argv if x.startswith('--output-fields='))
        self.assertEqual(fields.split(','), list(C.FIELDS))
        self.assertNotIn('MESSAGE', fields.split(','))
        self.assertNotIn('COMMAND', fields.split(','))
        self.assertNotIn('--follow', argv)
        self.assertIn(str(C.MAX_ROWS + 1), argv)
        self.assertEqual(C.FAILED_RUN_ID, 39092917351)

    def test_positive_two_units_do_not_verify_export(self):
        value = C.parse(raw(record('reader'), record('coordinator', index=2)))
        self.assertTrue(all(r['state'] == 'unit_success' for r in value['roles'].values()))
        self.assertTrue(all(value[k] is False for k in C.FLAGS))
        self.assertIs(C.validate(value), value)
        self.assertNotIn('1' * 32, C.closed_json(value))
        self.assertIsInstance(C.closed_json(value), str)

    def test_manager_failure_and_exit_are_distinct_from_source_limit(self):
        value = C.parse(raw(record(kind=C.EXIT), record(kind=C.FAILURE, index=2)))
        r = value['roles']['reader']
        self.assertEqual((r['state'], r['unit_result'], r['exit_status']), ('unit_failure', 'exit-code', 1))
        self.assertNotIn('limit_issue', r)
        self.assertEqual(value['roles']['coordinator']['state'], 'not_observed')

    def test_empty_is_not_observed_never_nonexecution(self):
        value = C.parse(b'')
        self.assertEqual(value['roles']['reader'], C._role_empty())
        self.assertFalse(value['nonexecution_proven'])

    def test_process_only_has_no_unit_success_claim(self):
        row = record(kind=C.EXIT)
        for code, expected in [('0', 'process_success'), ('1', 'process_failure')]:
            row['EXIT_STATUS'] = code
            with self.subTest(code=code):
                value = C.parse(raw(row))['roles']['reader']
                self.assertEqual(value['state'], expected)
                self.assertEqual(value['terminal_count'], 0)

    def test_sender_and_target_spoofing_rejected(self):
        for key, value in [('_PID', '2'), ('_UID', '1'), ('_COMM', 'python'),
                           ('_TRANSPORT', 'stdout'), ('UNIT', 'unrelated.service')]:
            with self.subTest(key=key):
                row = record(); row[key] = value; self.rejected(row, code='provenance')

    def test_exact_record_keys_and_no_payload(self):
        for mutation in ['missing', 'message', 'extra', 'wrong_event']:
            with self.subTest(mutation=mutation):
                row = record()
                if mutation == 'missing': del row['_UID']
                elif mutation == 'message': row['MESSAGE'] = 'forbidden sentinel'
                elif mutation == 'extra': row['COMMAND'] = 'forbidden sentinel'
                else: row['MESSAGE_ID'] = 'b' * 32
                self.rejected(row, code='schema')

    def test_multivalued_bool_null_and_duplicate_json_rejected(self):
        for value in [True, 1, None, [], ['1'], {'x': 1}]:
            with self.subTest(value=value):
                row = record(); row['_PID'] = value; self.rejected(row, code='schema')
        body = raw(record()).replace(b'"_PID":"1"', b'"_PID":"1","_PID":"1"')
        with self.assertRaises(C.Refused): C.parse(body)
        for body in [b'{"x":NaN}', b'{', b'\xff', b'[]']:
            with self.subTest(body=body), self.assertRaises(C.Refused): C.parse(body)

    def test_invocation_boot_and_cross_role_identity(self):
        for key in ('INVOCATION_ID', '_BOOT_ID'):
            for value in ['', '0' * 32, 'A' * 32, 'f' * 31]:
                with self.subTest(key=key, value=value):
                    row = record(); row[key] = value; self.rejected(row, code='provenance')
        a, b = record(kind=C.EXIT), record(kind=C.FAILURE, index=2)
        b['INVOCATION_ID'] = 'c' * 32; self.rejected(a, b, code='multiple_invocations')
        b = record('coordinator', index=2); b['INVOCATION_ID'] = a['INVOCATION_ID']
        self.rejected(a, b, code='conflict')
        b = record('coordinator', index=2); b['_BOOT_ID'] = 'c' * 32
        self.rejected(a, b, code='provenance')

    def test_window_precision_and_order(self):
        for number in (C.START_US, C.END_US):
            row = record(); row['__REALTIME_TIMESTAMP'] = str(number); C.parse(raw(row))
        for number in (C.START_US - 1, C.END_US + 1):
            row = record(); row['__REALTIME_TIMESTAMP'] = str(number)
            self.rejected(row, code='time_window')
        self.rejected(record(index=2), record('coordinator', index=1), code='order')
        row = record('coordinator', index=2); row['__MONOTONIC_TIMESTAMP'] = '0'
        self.rejected(record(), row, code='order')

    def test_repeated_and_contradictory_events_refused(self):
        self.rejected(record(), record(index=2), code='duplicate')
        self.rejected(record(), record(kind=C.FAILURE, index=2), code='duplicate')
        self.rejected(record(kind=C.EXIT), record(index=2), code='conflict')
        a = record(kind=C.EXIT); a['EXIT_STATUS'] = '0'
        self.rejected(a, record(kind=C.FAILURE, index=2), code='conflict')
        b = record(kind=C.FAILURE, index=2); b['UNIT_RESULT'] = 'signal'
        self.rejected(record(kind=C.EXIT), b, code='conflict')

    def test_unknown_failure_and_invalid_exit_status_refused(self):
        for value in ['success', 'unknown', '', True]:
            row = record(kind=C.FAILURE); row['UNIT_RESULT'] = value
            self.rejected(row)
        for value in ['256', '-1', '01', True, 'nan']:
            row = record(kind=C.EXIT); row['EXIT_STATUS'] = value; self.rejected(row)
        row = record(kind=C.EXIT); row.update(EXIT_CODE='killed', EXIT_STATUS='0')
        self.rejected(row)

    def test_cursor_size_rows_and_byte_limits(self):
        row = record('coordinator', index=2); row['__CURSOR'] = record()['__CURSOR']
        self.rejected(record(), row, code='duplicate')
        row = record(); row['__CURSOR'] = 'a' * 513; self.rejected(row, code='schema')
        with self.assertRaises(C.Refused): C.parse(b'x' * (C.MAX_BYTES + 1))
        with self.assertRaises(C.Refused): C.parse(b'{}\n' * (C.MAX_ROWS + 1))

    def test_result_validator_rejects_fabricated_or_inconsistent_claims(self):
        good = C.parse(raw(record()))
        for key, value in [('export_verified', True), ('message_read', True), ('version', True)]:
            v = copy.deepcopy(good); v[key] = value
            with self.subTest(key=key), self.assertRaises(C.Refused): C.validate(v)
        for key, value in [('evidence_count', True), ('terminal_count', 0),
                           ('exit_status', 0), ('unit_result', 'exit-code'), ('invocation', 'none')]:
            v = copy.deepcopy(good); v['roles']['reader'][key] = value
            with self.subTest(key=key), self.assertRaises(C.Refused): C.validate(v)
        v = C.parse(raw(record(kind=C.EXIT), record(kind=C.FAILURE, index=2)))
        v['roles']['reader']['unit_result'] = 'signal'
        with self.assertRaises(C.Refused): C.validate(v)

    def test_observe_is_single_fixed_query_and_platform_failure_is_closed(self):
        with patch.object(C.sys, 'platform', 'linux'), patch.object(C.os, 'geteuid', return_value=0), patch.object(C, '_capture', return_value=raw(record())) as capture:
            value = C.observe()
            capture.assert_called_once_with(C._argv())
            self.assertEqual(value['status'], 'observed')
        with patch.object(C.sys, 'platform', 'darwin'), patch.object(C, '_capture') as capture:
            self.assertEqual(C.observe()['refusal'], 'platform'); capture.assert_not_called()

    def test_observe_never_leaks_command_exception_or_partial_body(self):
        for error, code in [(C.Refused('command_limit'), 'command_limit'),
                            (RuntimeError('PRIVATE_SENTINEL'), 'unavailable')]:
            with patch.object(C.sys, 'platform', 'linux'), patch.object(C.os, 'geteuid', return_value=0), patch.object(C, '_capture', side_effect=error):
                value = C.observe(); self.assertEqual(value['refusal'], code)
                self.assertIsNone(value['roles']); self.assertNotIn('PRIVATE', C.closed_json(value))

    def test_real_subprocess_bounded_success_and_nonzero(self):
        self.assertEqual(C._capture([sys.executable, '-I', '-B', '-c', 'print("ok")']), b'ok\n')
        with self.assertRaises(C.Refused) as caught:
            C._capture([sys.executable, '-I', '-B', '-c', 'print("private");raise SystemExit(1)'])
        self.assertEqual(caught.exception.args, ('command_failed',))

    def test_real_subprocess_live_limit_and_timeout(self):
        started = time.monotonic()
        with self.assertRaises(C.Refused) as caught:
            C._capture([sys.executable, '-I', '-B', '-c', 'import os,time;os.write(1,b"x"*4096);time.sleep(3)'], limit=128)
        self.assertEqual(caught.exception.args, ('command_limit',))
        self.assertLess(time.monotonic() - started, 2)
        with self.assertRaises(C.Refused) as caught:
            C._capture([sys.executable, '-I', '-B', '-c', 'import time;time.sleep(3)'], timeout=0.1)
        self.assertEqual(caught.exception.args, ('deadline',))


class FixtureBoundaryTests(unittest.TestCase):
    @staticmethod
    def fixture():
        spec = importlib.util.spec_from_file_location('invocation_linux_fixture', HERE / 'linux_fixture.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_fixture_gate_refuses_before_command_or_file_creation(self):
        f = self.fixture()
        with patch.object(f.sys, 'argv', ['fixture']), patch.object(f, '_command') as command, patch.object(f, '_create') as create:
            value = f.run()
        command.assert_not_called(); create.assert_not_called()
        self.assertEqual(value['stage'], 'hosted_root_gate')
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['fixture_units_started'], 0)

    def test_fixture_creation_is_noclobber(self):
        f = self.fixture()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'fixed.service'; path.write_bytes(b'preserve')
            with self.assertRaises(FileExistsError): f._create(path, b'new')
            self.assertEqual(path.read_bytes(), b'preserve')

    def test_fixture_partial_creation_failure_removes_only_own_inode(self):
        f = self.fixture()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'fixed.service'
            with patch.object(f.os, 'fchown'), patch.object(f.os, 'write', side_effect=OSError('simulated')):
                with self.assertRaises(OSError): f._create(path, b'new')
            self.assertFalse(path.exists())

    def test_fixture_identity_failure_cleanup_and_exact_core_pin(self):
        f = self.fixture()
        self.assertEqual(f.CORE_SHA256, f._hash((HERE / 'core.py').read_bytes()))
        self.assertEqual(len(f.CHECKS), 10)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'fixed.service'
            with patch.object(f.os, 'fchown'), patch.object(f, '_identity', side_effect=ValueError('simulated')):
                with self.assertRaises(ValueError): f._create(path, b'new')
            self.assertFalse(path.exists())


if __name__ == '__main__': unittest.main()
