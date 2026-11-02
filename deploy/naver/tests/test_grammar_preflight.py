"""No real provider, database, Docker daemon, credential, or network needed."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('grammar_preflight', ROOT / 'deploy/naver/grammar_preflight.py')
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


def package():
    fmt = {'type': 'json_schema', 'schema': {'type': 'object',
        'properties': {'z': {'type': 'string'}, 'a': {'type': 'string'}},
        'required': ['z', 'a'], 'additionalProperties': False}}
    return {'version': 1, 'candidate': G.CANDIDATE, 'product_commit': 'a' * 40,
            'format': fmt, 'schema_sha256': G.digest(G.canonical(fmt))}


class Response(io.BytesIO):
    def __init__(self, raw, status=200, fail_close=False):
        super().__init__(raw)
        self.status, self.read_limits, self.fail_close = status, [], fail_close

    def read(self, limit=-1):
        self.read_limits.append(limit)
        return super().read(limit)

    def close(self):
        super().close()
        if self.fail_close:
            raise OSError('RESPONSE_CANARY')


class StrategyRefused(ValueError):
    def __init__(self, code):
        self.code = code


class GrammarPreflightTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden')))
        self.enterContext(patch.object(socket.socket, 'connect_ex', side_effect=AssertionError('network forbidden')))
        self.pkg = package()

    def invoke(self, *, response=None, transport_error=None, provider=True, **attrs):
        calls = []
        if response is None:
            response = Response(json.dumps({'stop_reason': 'end_turn',
                'content': [{'type': 'text', 'text': '{"z":"안내","a":"검토"}'}],
                'usage': {'input_tokens': 20, 'output_tokens': 7}}).encode())
        def transport(request, *, timeout):
            calls.append((request, timeout))
            if transport_error:
                raise transport_error
            return response
        obj = types.SimpleNamespace(monthly_budget_unlimited=True, model='claude-sonnet-5-5',
                                    _api_key='SYNTHETIC_KEY_CANARY', _timeout=10,
                                    _transport=transport)
        for key, value in attrs.items():
            setattr(obj, key, value)
        cp = types.SimpleNamespace(MAX_OUTPUT_TOKENS=4096, MAX_REQUEST_BYTES=32768,
            MAX_RESPONSE_BYTES=131072, ProviderRequest=lambda **kw: types.SimpleNamespace(**kw),
            _response_text=lambda blocks: ''.join(x['text'] for x in blocks if x['type'] == 'text'))
        lp = types.SimpleNamespace(HOST='api.anthropic.com', PATH='/v1/messages', _transport=transport,
            StrategyRefused=StrategyRefused,
            _transport_error=lambda e: 'PROVIDER_TIMEOUT' if isinstance(e, TimeoutError) else 'PROVIDER_NETWORK_ERROR')
        result = G.probe(self.pkg, obj if provider else None, cp, lp)
        G.validate_result(result, self.pkg)
        self.assertNotIn('CANARY', json.dumps(result))
        return result, calls, response

    def test_factory_wrapped_transport_timeout_keeps_closed_reason(self):
        result, calls, _ = self.invoke(transport_error=StrategyRefused('PROVIDER_TIMEOUT'))
        self.assertEqual(result['reason'], 'timeout')
        self.assertEqual(len(calls), 1)
        self.assertFalse(result['ok'])

    def test_request_preserves_property_order_and_format_and_one_call(self):
        result, calls, response = self.invoke()
        self.assertTrue(result['ok'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 10)
        request = calls[0][0]
        body = json.loads(request.data)
        self.assertEqual(body['output_config']['format'], self.pkg['format'])
        self.assertEqual(list(body['output_config']['format']['schema']['properties']), ['z', 'a'])
        self.assertEqual(body['max_tokens'], 4096)
        self.assertEqual(body['thinking'], {'type': 'between_tools'})
        self.assertEqual(response.read_limits, [131073])
        self.assertTrue(response.closed)
        self.assertEqual(result['usage']['input_tokens'], 20)
        self.assertNotIn('SYNTHETIC_KEY_CANARY', request.data.decode())

    def test_missing_provider_and_capped_policy_do_not_call(self):
        for attrs, reason in (({'provider': False}, 'configuration'),
                              ({'monthly_budget_unlimited': False}, 'policy-refused')):
            result, calls, _ = self.invoke(**attrs)
            self.assertFalse(result['ok'])
            self.assertEqual(result['reason'], reason)
            self.assertEqual(calls, [])

    def test_http400_classification_closes_response_without_raw_message(self):
        for message, reason in (
            ('Schema is too complex for compilation. RESPONSE_CANARY', 'http-schema-complexity'),
            ('schema pattern is not supported RESPONSE_CANARY', 'http-unsupported-schema'),
            ('PRIVATE_RESPONSE_CANARY', 'http-error-unclassified')):
            response = Response(json.dumps({'error': {'message': message}}).encode(), 400)
            result, calls, _ = self.invoke(response=response)
            self.assertEqual(result['reason'], reason)
            self.assertEqual(len(calls), 1)
            self.assertEqual(response.read_limits, [4097])
            self.assertTrue(response.closed)

    def test_timeout_and_server_error_have_no_retry(self):
        result, calls, _ = self.invoke(transport_error=TimeoutError('PRIVATE_CANARY'))
        self.assertEqual((result['reason'], len(calls)), ('timeout', 1))
        result, calls, response = self.invoke(response=Response(b'PRIVATE_CANARY', 503))
        self.assertEqual((result['reason'], len(calls)), ('http', 1))
        self.assertTrue(response.closed)

    def test_size_json_truncation_and_refusal_are_failures(self):
        cases = [(Response(b'x' * 131073), 'response-size'),
                 (Response(b'not JSON PRIVATE_CANARY'), 'response-json'),
                 (Response(b'{"stop_reason":"max_tokens"}'), 'truncated'),
                 (Response(b'{"stop_reason":"refusal"}'), 'refusal'),
                 (Response(b'{"stop_reason":"end_turn","content":[{"type":"text","text":"[]"}]}'), 'response-shape')]
        for response, reason in cases:
            result, calls, _ = self.invoke(response=response)
            self.assertEqual((result['reason'], len(calls)), (reason, 1))
            self.assertTrue(response.closed)

    def test_http200_json_must_match_the_actual_requested_schema(self):
        for value in ({}, {'z': '검토', 'a': 1}, {'z': '검토', 'a': '확인', 'private': 'CANARY'}):
            response = Response(json.dumps({'stop_reason': 'end_turn',
                'content': [{'type': 'text', 'text': json.dumps(value)}]}).encode())
            result, calls, _ = self.invoke(response=response)
            self.assertFalse(result['ok'])
            self.assertEqual(result['reason'], 'response-schema')
            self.assertEqual(len(calls), 1)
            self.assertTrue(response.closed)

    def test_schema_subset_refs_enum_pattern_nonempty_and_unknown_fail_closed(self):
        schema = {'type': 'object', 'properties': {'items': {'type': 'array',
            'minItems': 1, 'items': {'$ref': '#/definitions/prose'}},
            'title': {'type': 'string', 'enum': ['안내', '검토']}},
            'required': ['items', 'title'], 'additionalProperties': False,
            'definitions': {'prose': {'type': 'string', 'pattern': r'^[가-힣]+$'}}}
        good = {'items': ['확인'], 'title': '검토'}
        self.assertTrue(G.schema_matches(good, schema))
        for value in ({'items': [], 'title': '검토'}, {'items': ['<script>'], 'title': '검토'},
                      {'items': ['확인'], 'title': '임의'}, {'items': [True], 'title': '검토'}):
            self.assertFalse(G.schema_matches(value, schema))
        for mutated in ({**schema, 'oneOf': []}, {'$ref': 'https://example.invalid'},
                        {'$ref': '#/definitions/absent'}, {'type': 'any'}):
            self.assertFalse(G.schema_matches(good, mutated))
        self.assertFalse(G.schema_matches(True, {'type': 'integer', 'enum': [1]}))
        self.assertFalse(G.schema_matches(1, {'type': 'integer', 'enum': [True]}))

    @staticmethod
    def reference_branch(sources, fields):
        return {'properties': {'s': {'enum': sources}, 'f': {'enum': fields}}}

    @staticmethod
    def reference_schema(branches):
        return {'type': 'object', 'properties': {'s': {'type': 'string'}, 'f': {'type': 'string'}},
                'required': ['s', 'f'], 'additionalProperties': False, 'anyOf': branches}

    def reference_format(self):
        return {'type': 'json_schema', 'schema': {'type': 'object',
            'properties': {'ref': {'$ref': '#/definitions/reference'}},
            'required': ['ref'], 'additionalProperties': False,
            'definitions': {'reference': self.reference_schema([
                self.reference_branch(['metric:spend'], ['current', 'previous']),
                self.reference_branch(['case:1', 'case:2'], ['summary']),
                self.reference_branch([''], [''])])}}}

    def test_v14_reference_union_accepts_only_allowed_source_field_pairs(self):
        schema = self.reference_format()['schema']
        for ref in ({'s': 'metric:spend', 'f': 'current'}, {'s': 'metric:spend', 'f': 'previous'},
                    {'s': 'case:1', 'f': 'summary'}, {'s': 'case:2', 'f': 'summary'}, {'s': '', 'f': ''}):
            self.assertTrue(G.schema_matches({'ref': ref}, schema), ref)
        for ref in ({'s': 'metric:spend', 'f': 'summary'}, {'s': 'case:1', 'f': 'current'},
                    {'s': 'case:3', 'f': 'summary'}, {'s': '', 'f': 'summary'},
                    {'s': 'case:1', 'f': ''}, {'s': 'case:1'}, {'f': 'summary'},
                    {'s': 'case:1', 'f': 'summary', 'extra': 'PRIVATE_CANARY'},
                    {'s': True, 'f': 'summary'}, {'s': 'case:1', 'f': 1}, [], 'case:1.summary'):
            self.assertFalse(G.schema_matches({'ref': ref}, schema), ref)

    def test_reference_union_one_to_thirty_six_branches_and_no_general_union_support(self):
        valid = self.reference_branch(['case:1'], ['summary'])
        ref = {'s': 'case:1', 'f': 'summary'}
        for count in (1, 16, 19, 36):
            self.assertTrue(G.schema_matches(ref, self.reference_schema([copy.deepcopy(valid) for _ in range(count)])))
        for branches in ([], [valid] * 37, valid, [{'type': 'string', 'enum': ['case:1']}],
                         [valid, {'type': 'any'}], [valid, {'$ref': '#/definitions/x'}]):
            self.assertFalse(G.schema_matches(ref, self.reference_schema(branches)))
        for schema in ({'anyOf': [valid]}, {'oneOf': [valid]},
                       {**self.reference_schema([valid]), 'type': 'array'},
                       {**self.reference_schema([valid]), 'additionalProperties': True},
                       {**self.reference_schema([valid]), 'required': ['s']},
                       {**self.reference_schema([valid]), 'required': ['s', 's']},
                       {**self.reference_schema([valid]), 'required': ['s', 'f', 'extra']},
                       {**self.reference_schema([valid]), 'required': ['s', True]},
                       {**self.reference_schema([valid]), 'properties': {'s': {'type': 'string'}, 'f': {'type': 'integer'}}},
                       {**self.reference_schema([valid]), 'description': 'PRIVATE_CANARY'}):
            self.assertFalse(G.schema_matches(ref, schema))

    def test_all_reference_branches_are_checked_even_when_an_earlier_branch_matches(self):
        good = self.reference_branch(['case:1'], ['summary'])
        ref = {'s': 'case:1', 'f': 'summary'}
        bad = []
        for changes in ({'additionalProperties': False}, {'required': ['s', 'f']},
                        {'type': 'object'}, {'extra': 'PRIVATE_CANARY'},
                        {'properties': {'s': {'enum': ['case:1']}}}):
            bad.append({**copy.deepcopy(good), **changes})
        for leaf in ({'enum': []}, {'enum': 'summary'}, {'enum': [True]},
                     {'type': 'string', 'enum': ['summary']}, {'enum': ['summary'], 'pattern': '.*'},
                     {'anyOf': [{'enum': ['summary']}]}):
            branch = copy.deepcopy(good); branch['properties']['f'] = leaf; bad.append(branch)
        bad.extend([self.reference_branch(['case:1'], ['']), self.reference_branch([''], ['summary']),
                    self.reference_branch(['', 'case:1'], ['', 'summary'])])
        for branch in bad:
            self.assertFalse(G.schema_matches(ref, self.reference_schema([good, branch])), branch)

    def test_v14_http200_checks_grouped_references_without_retry_or_repair(self):
        fmt = self.reference_format()
        self.pkg = {**self.pkg, 'format': fmt, 'schema_sha256': G.digest(G.canonical(fmt))}
        G.validate_package(self.pkg)
        for ref, accepted in (({'s': 'case:2', 'f': 'summary'}, True),
                              ({'s': 'case:2', 'f': 'current'}, False)):
            response = Response(json.dumps({'stop_reason': 'end_turn',
                'content': [{'type': 'text', 'text': json.dumps({'ref': ref})}]}).encode())
            result, calls, _ = self.invoke(response=response)
            self.assertEqual(result['ok'], accepted)
            self.assertEqual(result['reason'], 'none' if accepted else 'response-schema')
            self.assertEqual(len(calls), 1)
            self.assertTrue(response.closed)
            self.assertEqual(json.loads(calls[0][0].data)['output_config']['format'], fmt)

    def test_live_source_and_candidate_are_fixed_to_reviewed_boundary(self):
        self.assertEqual(G.SOURCE, 'd633ff4450bb74206ecce5dda157387336256097')
        self.assertEqual(G.CANDIDATE, 'grounded-blocks-v16')
        self.assertEqual(G.MAX_REFERENCE_BRANCHES, 36)
        self.assertEqual(G.MAX_PACKAGE, 24576)
        self.assertEqual(G.blank_result(self.pkg)['live_source'], G.SOURCE)
        with self.assertRaises(ValueError):
            G.validate_package({**self.pkg, 'candidate': 'grounded-segments-v14'})

    def test_separate_text_and_references_require_closed_shapes_and_bare_references(self):
        schema = {'type': 'object', 'properties': {'note': {'$ref': '#/definitions/block'}},
            'required': ['note'], 'additionalProperties': False, 'definitions': {
                'block': {'type': 'object', 'properties': {
                    'text': {'type': 'string', 'pattern': '^[가-힣 .]+$'},
                    'refs': {'type': 'array', 'items': {'type': 'string',
                        'pattern': r'^\{\{metric:[a-z_]+\.current\}\}$'}}},
                    'required': ['text', 'refs'], 'additionalProperties': False}}}
        fmt = {'type': 'json_schema', 'schema': schema}
        self.pkg = {**self.pkg, 'format': fmt, 'schema_sha256': G.digest(G.canonical(fmt))}
        examples = [({'text': '자료를 확인합니다.', 'refs': ['{{metric:spend.current}}']}, True),
                    ({'text': '자료를 확인합니다.', 'refs': []}, True),
                    ({'text': '자료를 확인합니다.', 'refs': ['{{metric:spend.current}}원']}, False),
                    ({'text': '{{metric:spend.current}}원', 'refs': []}, False),
                    ({'text': '자료를 확인합니다.', 'refs': [], 'extra': 'PRIVATE_CANARY'}, False),
                    ('{{metric:spend.current}}원', False)]
        for note, accepted in examples:
            response = Response(json.dumps({'stop_reason': 'end_turn', 'content': [{
                'type': 'text', 'text': json.dumps({'note': note}, ensure_ascii=False)}]}).encode())
            result, calls, _ = self.invoke(response=response)
            self.assertEqual(result['ok'], accepted)
            self.assertEqual(result['schema_valid'], accepted)
            self.assertEqual(len(calls), 1)
            self.assertTrue(result['response_closed'])

    def test_previous_candidate_packages_refuse_before_transport(self):
        for candidate in ('grounded-text-v15', 'reference-segments-v14'):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                G.validate_package({**self.pkg, 'candidate': candidate})

    def test_close_failure_cannot_claim_success(self):
        response = Response(b'{"stop_reason":"end_turn","content":[{"type":"text","text":"{}"}]}', fail_close=True)
        result, calls, _ = self.invoke(response=response)
        self.assertFalse(result['ok'])
        self.assertEqual((result['reason'], len(calls)), ('response-close', 1))

    def test_invalid_usage_fields_never_escape(self):
        response = Response(json.dumps({'stop_reason': 'end_turn',
            'content': [{'type': 'text', 'text': '{}'}], 'usage': {
                'input_tokens': True, 'output_tokens': 'PRIVATE_CANARY',
                'cache_read_input_tokens': -1, 'cache_creation_input_tokens': 2**53,
                'extra': 'PRIVATE_CANARY'}}).encode())
        result, _, _ = self.invoke(response=response)
        self.assertTrue(all(value is None for value in result['usage'].values()))

    def test_package_hash_shape_candidate_commit_and_bounds(self):
        G.validate_package(self.pkg)
        for delta in ({'extra': 1}, {'version': True}, {'candidate': 'other'},
                      {'product_commit': '../main'}, {'schema_sha256': '0' * 64},
                      {'format': {'type': 'json_schema', 'schema': {}, 'url': 'PRIVATE_CANARY'}}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                G.validate_package({**self.pkg, **delta})
        value = copy.deepcopy(self.pkg)
        value['format']['schema']['description'] = 'x' * G.MAX_PACKAGE
        value['schema_sha256'] = G.digest(G.canonical(value['format']))
        with self.assertRaises(ValueError):
            G.validate_package(value)

    def test_builder_refuses_wrong_sha_and_dirty_source_before_importing_factory(self):
        for head, status in (('b' * 40, b''), ('a' * 40, b' M tracked.py\n'),
                             ('a' * 40, b'?? untracked.py\n')):
            with patch.object(G.subprocess, 'check_output', side_effect=[head.encode(), status]), \
                    patch.object(G.importlib, 'import_module') as importer, self.assertRaises(ValueError):
                G.build('/synthetic-product', 'a' * 40, '/unused-target')
            importer.assert_not_called()

    def test_safe_file_refuses_symlink_permissions_hash_and_oversize(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / 'package.json'
            raw = G.canonical(self.pkg)
            file.write_bytes(raw)
            file.chmod(0o600)
            self.assertEqual(G.safe_read(file, G.digest(raw)), self.pkg)
            with self.assertRaises(ValueError):
                G.safe_read(file, '0' * 64)
            link = Path(folder) / 'link'
            link.symlink_to(file)
            with self.assertRaises(OSError):
                G.safe_read(link, G.digest(raw))
            file.chmod(0o644)
            with self.assertRaises(ValueError):
                G.safe_read(file, G.digest(raw))
            file.chmod(0o600)
            file.write_bytes(b'x' * (G.MAX_PACKAGE + 1))
            with self.assertRaises(ValueError):
                G.safe_read(file, G.digest(file.read_bytes()))

    def test_closed_result_rejects_extra_raw_text_booleans_and_false_success(self):
        result, _, _ = self.invoke()
        for delta in ({'extra': 'PRIVATE_CANARY'}, {'reason': 'PRIVATE_CANARY'},
                      {'transport_calls': True}, {'http_status': True},
                      {'database_opened': True}, {'ad_changes': 1},
                      {'response_closed': False}, {'schema_valid': False}, {'product_commit': '0' * 40},
                      {'container_unchanged': 'yes'}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                G.validate_result({**result, **delta}, self.pkg)

    def host_fake(self, *, changed=False, wrong_image=False, child_extra=False, child_timeout=False):
        identity = '1' * 64
        before = {'id': identity, 'image': 'sha256:' + '2' * 64, 'running': True,
            'pid': 321, 'started': 'fixed', 'restarts': 0, 'user': '10001:10001', 'readonly': True}
        result, _, _ = self.invoke()
        if child_extra:
            result['raw_text'] = 'PRIVATE_CANARY'
        calls = []
        def command(args, **kwargs):
            calls.append((args, kwargs))
            if args[:2] == ['docker', 'ps']:
                return (identity + '\n').encode()
            if args[:3] == ['docker', 'image', 'inspect']:
                return G.canonical({'id': before['image'], 'source': '0' * 40 if wrong_image else G.SOURCE})
            if args[:2] == ['docker', 'exec']:
                self.assertEqual(args[2:5], ['-i', '--user', '10001:10001'])
                self.assertEqual(kwargs['timeout'], 210)
                compile(kwargs['data'], '<generated>', 'exec')
                if child_timeout:
                    raise TimeoutError('PRIVATE_CANARY')
                return G.canonical(result)
            raise AssertionError(args)
        with patch.object(G.os, 'geteuid', return_value=0), patch.object(G, 'command', side_effect=command), \
                patch.object(G, 'snapshot', side_effect=[before, {**before, 'pid': 999} if changed else before]):
            answer = G.host(self.pkg, source=Path(G.__file__).read_bytes())
        return answer, calls

    def test_host_identity_and_unchanged_boundary_and_one_exec(self):
        result, calls = self.host_fake()
        self.assertTrue(result['ok'])
        self.assertTrue(result['container_unchanged'])
        self.assertTrue(result['child_execution_attempted'])
        self.assertFalse(result['transport_outcome_unknown'])
        self.assertEqual(sum(args[:2] == ['docker', 'exec'] for args, _ in calls), 1)
        self.assertNotIn('CANARY', json.dumps(result))

    def test_host_refuses_old_image_and_changed_container(self):
        result, calls = self.host_fake(wrong_image=True)
        self.assertFalse(result['ok'])
        self.assertFalse(result['child_execution_attempted'])
        self.assertEqual(result['transport_calls'], 0)
        self.assertFalse(any(args[:2] == ['docker', 'exec'] for args, _ in calls))
        result, _ = self.host_fake(changed=True)
        self.assertEqual(result['reason'], 'container-changed')
        self.assertFalse(result['ok'])

    def test_host_rejects_raw_or_unbounded_child_result(self):
        result, _ = self.host_fake(child_extra=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'child-failed')
        self.assertTrue(result['transport_outcome_unknown'])
        self.assertIsNone(result['transport_calls'])
        self.assertNotIn('CANARY', json.dumps(result))

    def test_lost_child_receipt_is_unknown_not_zero_calls_and_has_no_retry(self):
        result, calls = self.host_fake(child_timeout=True)
        self.assertFalse(result['ok'])
        self.assertTrue(result['child_execution_attempted'])
        self.assertTrue(result['transport_outcome_unknown'])
        self.assertIsNone(result['transport_calls'])
        self.assertEqual(sum(args[:2] == ['docker', 'exec'] for args, _ in calls), 1)
        self.assertTrue(result['container_unchanged'])
        self.assertNotIn('CANARY', json.dumps(result))
        for delta in ({'ok': True}, {'transport_calls': 0}, {'child_execution_attempted': False}):
            with self.assertRaises(ValueError):
                G.validate_result({**result, **delta}, self.pkg)

    def test_pins_cover_current_transport_import_closure_and_forbid_sqlite(self):
        self.assertEqual(len(G.PINS), 16)
        for name, value in G.PINS.items():
            self.assertRegex(name, r'^(naver_runtime|naver_engine)/[a-z_]+\.py$')
            self.assertRegex(value, r'^[0-9a-f]{64}$')
        with patch.object(G.os, 'geteuid', return_value=0):
            result = G.inside(self.pkg)
        self.assertEqual((result['reason'], result['transport_calls']), ('source-refused', 0))
        source = Path(G.__file__).read_text()
        self.assertIn('sqlite3.connect = denied', source)
        self.assertNotIn('print(raw', source)

    def test_workflow_manual_owner_main_pin_private_and_no_artifact(self):
        source = (ROOT / '.github/workflows/naver-grammar-preflight.yml').read_text()
        for text in ('workflow_dispatch:', 'test "$ACTOR" = metainchelp-boop',
                     'test "$TRIGGERING_ACTOR" = metainchelp-boop', 'test "$REF" = refs/heads/main',
                     'test "$ATTEMPT" = 1', 'RUN_ONE_SYNTHETIC_GRAMMAR',
                     'concurrency:', 'group: deploy-logic-analysis', 'cancel-in-progress: false',
                     'persist-credentials: false', 'flock -n 9', 'chmod 700',
                     '2>/dev/null', 'NAVER_GRAMMAR_PRIVATE_FILES_REMOVED'):
            self.assertIn(text, source)
        for forbidden in ('upload-artifact', 'pull_request:', 'push:', 'cat package.json',
                          'cat "$RUNNER_TEMP/grammar-private/build.log"', 'set -x', 'docker restart'):
            self.assertNotIn(forbidden, source)
        import re
        actions = re.findall(r'uses: ([^\s]+)', source)
        self.assertTrue(actions)
        for action in actions:
            self.assertRegex(action, r'@[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
