import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import naver_claude_minimal_probe_host as H


class HostProbeTests(unittest.TestCase):
    def setUp(self):
        self.core = b'def run(): return {}\n'
        self.pins = {f'naver_runtime/m{i}.py': '1' * 64 for i in range(109)}
        self.identity = '2' * 64
        self.image = 'sha256:' + '3' * 64
        self.before = dict(id=self.identity, image=self.image, running=True,
                           user='10001:10001', readonly=True, started='fixed',
                           restarts=0, source=H.SOURCE)
        self.calls = []
        self.patchers = [
            patch.object(H, 'CORE_SHA256', hashlib.sha256(self.core).hexdigest()),
            patch.object(H, 'PINS_SHA256', hashlib.sha256(json.dumps(self.pins, sort_keys=True, separators=(',', ':')).encode()).hexdigest())]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def command(self, args, *, data=None):
        self.calls.append((args, data))
        if args[1] == 'ps':
            return self.identity.encode() + b'\n'
        if args[1] == 'inspect':
            return json.dumps(self.before).encode()
        if args[1] == 'image':
            return json.dumps({'id': self.image, 'source': H.SOURCE}).encode()
        if args[1] == 'exec':
            return json.dumps(self.result()).encode()
        self.fail('unexpected command')

    def result(self):
        return dict(version=1, probe='claude-minimal-text-v1', ok=False, stage='http',
            diagnostic='http-error-unclassified', http_status=400, transport_calls=1,
            response_closed=True, checks=dict(http_200=False, end_turn=None, text_nonempty=None, exact_ok=None),
            usage=dict(status='unavailable', **{key: None for key in H.TOKEN_FIELDS}), elapsed_ms=100)

    def test_one_exec_and_failure_not_retried(self):
        with patch.object(H, 'command', side_effect=self.command):
            result = H.run(self.core, self.pins)
        executions = [(a, d) for a, d in self.calls if a[1] == 'exec']
        self.assertEqual(len(executions), 1)
        args, program = executions[0]
        self.assertEqual(args[2:7], ['-i', '--user', '10001:10001', self.identity, 'python'])
        self.assertEqual(result['result']['http_status'], 400)
        self.assertFalse(result['database_opened'])
        self.assertFalse(result['product_deployed'])
        self.assertNotIn('engine.db', program.decode())
        self.assertIn("os.environ.get('NAVER_ENGINE_EXECUTION_ENABLED','false')", program.decode())

    def test_changed_source_fails_before_any_command(self):
        with patch.object(H, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
                H.run(self.core + b'\n', self.pins)
            command.assert_not_called()

    def test_changed_pin_fails_before_any_command(self):
        self.pins['naver_runtime/m0.py'] = '4' * 64
        with patch.object(H, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'SOURCE_CHANGED'):
                H.run(self.core, self.pins)
            command.assert_not_called()

    def test_multiple_containers_refuse_without_exec(self):
        with patch.object(H, 'command', return_value=(self.identity + '\n' + '4' * 64).encode()) as command:
            with self.assertRaisesRegex(ValueError, 'CONTAINER_IDENTITY'):
                H.run(self.core, self.pins)
            self.assertEqual(command.call_count, 1)

    def test_wrong_image_refuses_without_exec(self):
        self.before['image'] = 'sha256:' + '4' * 64
        with patch.object(H, 'command', side_effect=self.command):
            with self.assertRaisesRegex(ValueError, 'CONTAINER_CHANGED'):
                H.run(self.core, self.pins)
        self.assertFalse(any(a[1] == 'exec' for a, _ in self.calls))

    def test_after_container_change_is_not_success(self):
        def command(args, *, data=None):
            if args[1] == 'exec':
                self.before['restarts'] = 1
            return self.command(args, data=data)
        with patch.object(H, 'command', side_effect=command):
            with self.assertRaisesRegex(ValueError, 'CONTAINER_CHANGED_AFTER_PROBE'):
                H.run(self.core, self.pins)
        self.assertEqual(sum(a[1] == 'exec' for a, _ in self.calls), 1)

    def test_execution_exception_still_checks_container_and_never_retries(self):
        def command(args, *, data=None):
            if args[1] == 'exec':
                self.calls.append((args, data))
                raise ValueError('COMMAND_REFUSED')
            return self.command(args, data=data)
        with patch.object(H, 'command', side_effect=command):
            with self.assertRaisesRegex(ValueError, 'COMMAND_REFUSED'):
                H.run(self.core, self.pins)
        self.assertEqual(sum(a[1] == 'exec' for a, _ in self.calls), 1)
        self.assertEqual(sum(a[1] == 'inspect' for a, _ in self.calls), 2)

    def test_result_rejects_raw_data_and_false_success(self):
        for key, value in [('message', 'private'), ('diagnostic', 'private'),
                           ('usage', {'status': 'private'}), ('ok', True), ('transport_calls', True)]:
            result = self.result()
            result[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                H.validate_result(result)


if __name__ == '__main__':
    unittest.main()
