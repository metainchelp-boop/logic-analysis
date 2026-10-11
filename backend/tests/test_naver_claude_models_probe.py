"""Read-only models diagnostic tests. Every network/process call is mocked."""
import ast
import base64
import copy
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock

import test_naver_claude_config as shared

spec = importlib.util.spec_from_file_location('models_under_test', shared.TOOLS / 'naver_claude_models_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def request():
    return dict(shared.request(), operation='probe-models')


class ModelsTests(unittest.TestCase):
    def setUp(self):
        self.program = {'__name__': 'offline_test'}
        exec(compile(probe.PROGRAM, '<offline-models-probe>', 'exec'), self.program)
        self.environment = dict(ANTHROPIC_API_KEY='SYNTHETIC-NOT-A-CREDENTIAL', CLAUDE_MODEL='claude-sonnet-5-5',
                                NAVER_CLAUDE_ENABLED='true', NAVER_CLAUDE_MONTHLY_CAP_USD='unlimited')

    @staticmethod
    def body(*models, partial=False):
        return json.dumps(dict(data=[dict(id=model, display_name='PRIVATE-DO-NOT-PRINT') for model in models], has_more=partial)).encode()

    def call(self, response=None, failure=None, environment=None):
        connection = mock.Mock()
        if failure is not None:
            connection.getresponse.side_effect = failure
        else:
            connection.getresponse.return_value = response
        with mock.patch.object(self.program['http'].client, 'HTTPSConnection', return_value=connection) as constructor, \
                mock.patch.object(self.program['signal'], 'signal'), mock.patch.object(self.program['signal'], 'alarm'):
            result = self.program['probe'](environment or self.environment)
        return result, connection, constructor

    def test_exact_host_one_get_no_retry_redirect_messages_and_no_body_output(self):
        response = mock.Mock(status=200)
        response.read.return_value = self.body('claude-sonnet-5-5', 'claude-sonnet-4-6', 'PRIVATE-OTHER-MODEL')
        result, connection, constructor = self.call(response)
        constructor.assert_called_once_with('api.anthropic.com', timeout=5)
        connection.request.assert_called_once_with('GET', '/v1/models', headers={
            'x-api-key': 'SYNTHETIC-NOT-A-CREDENTIAL', 'anthropic-version': '2023-06-01', 'Accept': 'application/json'})
        response.read.assert_called_once_with(262145)
        connection.close.assert_called_once()
        self.assertEqual(result, dict(http_status=200, configured_model_present=True, fallback_model_present=True, classification='models_complete'))
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertNotIn('SYNTHETIC', json.dumps(result))

    def test_complete_and_partial_presence_are_distinguished(self):
        project = self.program['project']
        complete = project(200, self.body('claude-sonnet-4-6'))
        partial = project(200, self.body('claude-sonnet-4-6', partial=True))
        self.assertFalse(complete['configured_model_present'])
        self.assertTrue(complete['fallback_model_present'])
        self.assertEqual(complete['classification'], 'models_complete')
        self.assertEqual(partial['classification'], 'models_partial')

    def test_non200_never_reads_or_exposes_error_body_or_retries(self):
        for status, expected in ((301, 'http_error'), (400, 'bad_request'), (401, 'unauthorized'),
                                 (403, 'forbidden'), (404, 'not_found'), (429, 'rate_limited'), (500, 'server_error')):
            response = mock.Mock(status=status)
            result, connection, _ = self.call(response)
            self.assertEqual(result['classification'], expected)
            self.assertEqual(result['http_status'], status)
            self.assertFalse(result['configured_model_present'])
            response.read.assert_not_called()
            connection.request.assert_called_once()

    def test_timeout_tls_network_protocol_error_is_fixed_and_never_retried(self):
        for failure, expected in ((TimeoutError('PRIVATE'), 'timeout'),
                                 (self.program['ssl'].SSLError('PRIVATE'), 'tls_error'),
                                 (OSError('PRIVATE'), 'network_error'),
                                 (self.program['http'].client.HTTPException('PRIVATE'), 'protocol_error')):
            result, connection, _ = self.call(failure=failure)
            self.assertEqual(result['classification'], expected)
            connection.request.assert_called_once()
            self.assertNotIn('PRIVATE', json.dumps(result))

    def test_invalid_json_shape_duplicate_oversize_and_config_do_not_leak(self):
        for body in (b'PRIVATE NOT JSON', b'{"data":[],"data":[],"has_more":false}',
                     b'{"data":[],"has_more":1}', b'{"data":[{}],"has_more":false}'):
            response = mock.Mock(status=200)
            response.read.return_value = body
            self.assertEqual(self.call(response)[0]['classification'], 'invalid_response')
        response = mock.Mock(status=200)
        response.read.return_value = b'x' * 262145
        self.assertEqual(self.call(response)[0]['classification'], 'response_too_large')
        result, connection, constructor = self.call(environment=dict(self.environment, CLAUDE_MODEL='wrong'))
        self.assertEqual(result['classification'], 'config_mismatch')
        constructor.assert_not_called()
        connection.request.assert_not_called()

    def test_alarm_is_cancelled_and_handler_restored(self):
        response = mock.Mock(status=401)
        connection = mock.Mock()
        connection.getresponse.return_value = response
        old = object()
        with mock.patch.object(self.program['http'].client, 'HTTPSConnection', return_value=connection), \
                mock.patch.object(self.program['signal'], 'signal', return_value=old) as signals, \
                mock.patch.object(self.program['signal'], 'alarm') as alarm:
            self.program['probe'](self.environment)
        self.assertEqual(alarm.call_args_list, [mock.call(8), mock.call(0)])
        self.assertEqual(signals.call_args_list[-1], mock.call(self.program['signal'].SIGALRM, old))

    def test_closed_request_and_public_result(self):
        probe.validate_request(request(), shared.config)
        for value in (dict(request(), operation='activate'), dict(request(), source_commit='0' * 40), dict(request(), extra=True)):
            with self.assertRaises(ValueError):
                probe.validate_request(value, shared.config)
        value = dict(http_status=200, configured_model_present=False, fallback_model_present=True, classification='models_complete')
        probe.public_result(value)
        for invalid in (dict(value, http_status=True), dict(value, configured_model_present=1), dict(value, extra='PRIVATE'),
                        dict(value, http_status=401), dict(value, classification='PRIVATE')):
            with self.assertRaises(ValueError):
                probe.public_result(invalid)

    def test_run_has_exact_identity_pre_and_post_without_db_key_or_mutation_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = shared.Fixture(Path(temporary).resolve())
            before = copy.deepcopy(fixture.rows)
            result = dict(http_status=200, configured_model_present=False, fallback_model_present=True, classification='models_complete')
            with mock.patch.object(shared.config.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_gid=33)), \
                    mock.patch.object(fixture, 'command', return_value=(json.dumps(result) + '\n').encode()) as command, \
                    mock.patch.object(shared.config.Transaction, 'key', side_effect=AssertionError('NO_KEY_READ')), \
                    mock.patch.object(shared.config.Transaction, 'prepare', side_effect=AssertionError('NO_MUTATION')):
                self.assertEqual(probe.run(request(), fixture.host, fixture, fixture, fixture, shared.config), result)
            command.assert_called_once_with(['docker', 'exec', before['engine']['id'], 'python', '-I', '-S', '-B', '-c', probe.PROGRAM], timeout=15)
            self.assertEqual(fixture.commands, [])
            self.assertEqual(fixture.rows, before)
            self.assertFalse((fixture.ROOT / 'claude-config').exists())

    def test_run_refuses_changed_engine_after_get(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = shared.Fixture(Path(temporary).resolve())
            def changed(args, timeout):
                fixture.rows['engine']['id'] = 'b' * 64
                return b'{"http_status":200,"configured_model_present":false,"fallback_model_present":true,"classification":"models_complete"}\n'
            with mock.patch.object(shared.config.pwd, 'getpwnam', return_value=types.SimpleNamespace(pw_gid=33)), \
                    mock.patch.object(fixture, 'command', side_effect=changed):
                with self.assertRaisesRegex(ValueError, '^MODEL_PROBE_SOURCE_CHANGED$'):
                    probe.run(request(), fixture.host, fixture, fixture, fixture, shared.config)


class WorkflowTests(unittest.TestCase):
    @staticmethod
    def block(start, end):
        text = shared.WORKFLOW.read_text()
        return textwrap.dedent(text.split('# ' + start + '\n', 1)[1].split('# ' + end, 1)[0])

    def test_job_exact_branch_mode_concurrency_and_all_other_jobs_skip(self):
        text = shared.WORKFLOW.read_text()
        job = text.split('  claude-models:\n', 1)[1]
        self.assertIn("github.ref == 'refs/heads/codex/naver-claude-model-probe-20261011'", job)
        self.assertIn("inputs.claude_config == 'probe-models'", job)
        self.assertIn('group: deploy-logic-analysis\n      cancel-in-progress: false', job)
        self.assertIn('appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262', job)
        old = text.split('  claude-config:\n', 1)[0]
        self.assertEqual(old.count("(!inputs.claude_config || inputs.claude_config == 'off') && ("), 9)
        self.assertIn("inputs.claude_config == 'activate' || inputs.claude_config == 'recover'", text)

    def test_public_package_and_bounded_remote_transport(self):
        with tempfile.TemporaryDirectory() as temporary:
            envfile = Path(temporary) / 'env'
            inputs = {name: 'off' for name in ('ad_prepare', 'collector', 'rank_link', 'capacity', 'structure', 'expired', 'queue', 'urlshape', 'use_branch_code')}
            expected_request = request()
            inputs.update(claude_config='probe-models', ad_expected_baseline=json.dumps(expected_request))
            read_text = Path.read_text
            with mock.patch.dict(os.environ, INPUTS_JSON=json.dumps(inputs), GITHUB_ENV=str(envfile)), \
                    mock.patch.object(Path, 'read_text', autospec=True, side_effect=lambda path, *a, **k: read_text(shared.TOOLS.parents[1] / path, *a, **k)):
                exec(compile(self.block('CLAUDE_MODELS_PACKAGE_BEGIN', 'CLAUDE_MODELS_PACKAGE_END'), '<models-package>', 'exec'), {})
            encoded = envfile.read_text().strip().split('=', 1)[1]
        remote = self.block('CLAUDE_MODELS_REMOTE_BEGIN', 'CLAUDE_MODELS_REMOTE_END')
        nodes = [node for node in ast.parse(remote).body if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
        namespace = {}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), '<models-decode>', 'exec'), namespace)
        self.assertEqual(namespace['decode'](encoded)['request'], expected_request)
        for bad in ('!', encoded + 'x' * 65536, base64.b64encode(base64.b64decode(encoded) + b'tail').decode(),
                    base64.b64encode(gzip.compress(b'x' * 262145)).decode()):
            with self.assertRaises(ValueError):
                namespace['decode'](bad)

    def test_remote_redacts_unknown_exception_and_stray_output(self):
        sources = {name: 'pass' for name in ('naver_claude_models_probe', 'naver_claude_config', 'naver_preview_release',
                   'naver_preview_upgrade', 'naver_preview_lifecycle', 'naver_erp_tunnel_service_install')}
        sources['naver_claude_models_probe'] = "print('PRIVATE STRAY');raise RuntimeError('PRIVATE EXCEPTION')"
        encoded = base64.b64encode(gzip.compress(json.dumps(dict(request=request(), modules=sources)).encode())).decode()
        output, errors = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, CLAUDE_MODELS_B64=encoded), mock.patch('sys.stdout', output), mock.patch('sys.stderr', errors):
            with self.assertRaises(SystemExit):
                exec(compile(self.block('CLAUDE_MODELS_REMOTE_BEGIN', 'CLAUDE_MODELS_REMOTE_END'), '<models-remote>', 'exec'), {})
        self.assertEqual(json.loads(output.getvalue()), dict(classification='source_refused', configured_model_present=False,
                         fallback_model_present=False, http_status=None))
        self.assertEqual(errors.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
