"""Code-only deployment sequencing; no operating DB or service is used."""
import unittest
import json
import ast
import base64
import gzip
import io
import os
import sys
import tempfile
import textwrap
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared


class CodeOnlyTest(unittest.TestCase):
    def scenario(self, failure=None, mode='apply'):
        return shared.ContractTest().scenario(failure, mode, code_only=True)

    def test_explicit_code_only_apply_transport_preserves_sources_and_bounds(self):
        encode, decode, _ = shared.ContractTest().workflow_transport()
        tools = shared.Path(__file__).parents[1]/'tools'
        names = {'source':'naver_preview_code_only', 'code_source':'naver_preview_code_upgrade',
                 'release_source':'naver_preview_release', 'host_source':'naver_erp_tunnel_service_install',
                 'lifecycle_source':'naver_preview_lifecycle', 'upgrade_source':'naver_preview_upgrade'}
        bundle = {key:(tools/(name+'.py')).read_text() for key,name in names.items()}
        bundle.update(operation='preview-code-only-upgrade', function='apply', package={
            'release':dict(baseline='a'*64,source_commit='b'*40,ciphertext_sha256='c'*64,
                          source_tar_gz_sha256='d'*64,run_id='9'*20,operation='code-prepare'),
            'operation_id':'e'*32})
        self.assertLessEqual(len(json.dumps(bundle).encode()),229376)
        encoded = encode(bundle)
        self.assertTrue(encoded.startswith('code-gzip-v1:'))
        self.assertLessEqual(len(encoded),73728)
        self.assertEqual(decode(encoded),bundle)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
            decode(encode(dict(bundle,function='run')))

    def test_unreviewed_release_refuses_before_any_host_action(self):
        code = shared.load('naver_preview_code_upgrade')
        policy = shared.load('naver_preview_code_only')
        for name in ('prepare', 'apply'):
            with self.subTest(name=name), patch.object(policy,'REVIEWED_TRANSITION',None):
                adapters = [Mock() for _ in range(4)]
                with self.assertRaisesRegex(ValueError, '^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                    getattr(policy, name)({}, *adapters, code)
                for adapter in adapters:
                    self.assertEqual(adapter.mock_calls, [])

    def test_success_changes_only_code_without_database_access_or_source_warmup(self):
        result, commands, writes, _, state = self.scenario()
        self.assertIsInstance(result, dict, str(result))
        self.assertTrue(result['ok'])
        self.assertEqual(state, {'engine': 'b'*40, 'relay': 'b'*40})
        self.assertEqual(result['database_policy'], 'preserve-in-place')
        self.assertFalse(result['database_opened_by_controller'])
        self.assertFalse(result['database_snapshot_verified'])
        self.assertFalse(result['source_warmup_performed'])
        self.assertFalse(result['rollback_requires_matching_database'])
        self.assertNotIn('database_schema', result)
        self.assertNotIn('source_status', result)
        self.assertFalse(any('exec' in args or 'run' in args for args in commands))
        self.assertFalse(any(p.name == 'bootstrap-request.json' or p.parent.name == 'secrets'
                             for p, _ in writes))

    def test_prepare_builds_without_stopping_services_or_opening_any_database(self):
        with patch.object(shared.sqlite3, 'connect', side_effect=AssertionError('DB access forbidden')):
            result, commands, _, restored, state = self.scenario(mode='prepare')
        self.assertIsInstance(result, dict, str(result))
        self.assertFalse(result['services_started'])
        self.assertTrue(restored)
        self.assertEqual(set(state.values()), {shared.load('naver_preview_code_upgrade').OLD_COMMIT})
        self.assertEqual(sum(args[:2] == ['docker', 'build'] for args in commands), 2)
        self.assertFalse(any(args[:2] in (['/usr/bin/systemctl', 'stop'], ['/usr/bin/systemctl', 'start'])
                             for args in commands))

    def test_partial_failures_restore_only_old_code_and_keep_existing_guards(self):
        for failure in ('recreate', 'start', 'stop', 'probe'):
            with self.subTest(failure=failure), patch.object(
                    shared.sqlite3, 'connect', side_effect=AssertionError('DB access forbidden')):
                result, commands, _, restored, state = self.scenario(failure)
                self.assertEqual(str(result), 'CODE_ONLY_FAILED_ROLLED_BACK')
                self.assertTrue(restored)
                self.assertEqual(set(state.values()), {shared.load('naver_preview_code_upgrade').OLD_COMMIT})
                self.assertNotIn('PRIVATE_ERROR_SENTINEL', str(result))
                self.assertTrue(result.failure_details['failed_stage'].startswith('code_'))
                self.assertFalse(any('exec' in args or 'run' in args for args in commands))

    def test_unproved_stop_or_failed_rollback_does_not_restart_old_services(self):
        for failure in ('stop_writer_running', 'rollback_writer_running', 'rollback_recreate'):
            with self.subTest(failure=failure):
                result, commands, _, _, _ = self.scenario(failure)
                self.assertEqual(str(result), 'CODE_ROLLBACK_FAILED')
                self.assertEqual(commands[-2:], [
                    ['/usr/bin/systemctl', 'stop', 'metainc-naver-relay.service'],
                    ['/usr/bin/systemctl', 'stop', 'metainc-naver-engine.service']])

    def test_schema_infrastructure_or_unapproved_scope_is_rejected_before_stop(self):
        for failure in ('image', 'unit', 'manifest', 'schema', 'infrastructure', 'override',
                        'bootstrap_pending', 'old_source', 'unapproved_code', 'unapproved_new'):
            with self.subTest(failure=failure):
                result, commands, writes, _, _ = self.scenario(failure)
                self.assertIsInstance(result, Exception)
                self.assertEqual(writes, [])
                self.assertFalse(any(args[:2] == ['/usr/bin/systemctl', 'stop'] for args in commands))

    def test_review_is_bound_to_each_release_pin_and_cannot_be_set_by_input(self):
        code = shared.load('naver_preview_code_upgrade')
        policy = shared.load('naver_preview_code_only')
        pins = (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256, code.TARGET_SOURCE_SHA256,
                code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)
        for index in range(len(pins)):
            changed = list(pins)
            changed[index] = '0'*len(pins[index])
            with self.subTest(index=index), patch.object(policy, 'REVIEWED_TRANSITION', tuple(changed)):
                adapters = [Mock() for _ in range(4)]
                with self.assertRaisesRegex(ValueError, '^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                    policy.apply({'REVIEWED_TRANSITION': pins}, *adapters, code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_changed_bootstrap_refuses_old_code_restart_without_repairing_data(self):
        result, commands, _, _, _ = self.scenario('bootstrap_changed')
        self.assertEqual(str(result), 'CODE_ROLLBACK_FAILED')
        # Initial target recreations are allowed; rollback must not recreate the old writer.
        self.assertEqual(sum('--force-recreate' in args for args in commands), 2)
        self.assertEqual(result.failure_details['rollback_stage'], 'code_rollback')
        self.assertEqual(result.failure_details['rollback_operation'], 'rollback_state')

    def test_review_refuses_scope_expansion_even_when_release_pins_are_identical(self):
        code = shared.load('naver_preview_code_upgrade')
        policy = shared.load('naver_preview_code_only')
        for name, value in (('CODE_PATHS', code.CODE_PATHS | {'naver_engine/store.py'}),
                            ('CODE_PATHS', code.CODE_PATHS | {'backend/app/naver_auto/scope.py'}),
                            ('TEST_PATHS', frozenset({'naver_engine/tests/test_web.py'}))):
            with self.subTest(name=name, value=value), patch.object(code, name, value):
                adapters = [Mock() for _ in range(4)]
                with self.assertRaisesRegex(ValueError, '^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                    policy.prepare({}, *adapters, code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_host_or_source_drift_before_rollback_refuses_old_code_restart(self):
        for failure, expected in (('rollback_host_changed', 'CODE_POST_STATE'),
                                  ('rollback_source_changed', 'CODE_STORE_CHANGED')):
            with self.subTest(failure=failure):
                result, commands, _, _, _ = self.scenario(failure)
                self.assertEqual(str(result), 'CODE_ROLLBACK_FAILED')
                self.assertEqual(sum('--force-recreate' in args for args in commands), 2)
                self.assertEqual(result.failure_details['rollback_error_code'], expected)
                self.assertEqual(commands[-2:], [
                    ['/usr/bin/systemctl', 'stop', 'metainc-naver-relay.service'],
                    ['/usr/bin/systemctl', 'stop', 'metainc-naver-engine.service']])

    def test_failure_reporting_never_exposes_untrusted_error_text(self):
        policy = shared.load('naver_preview_code_only')
        code = shared.load('naver_preview_code_upgrade')
        for label in ('CODE_ONLY_RELEASE_NOT_REVIEWED', 'CODE_ONLY_FAILED_ROLLED_BACK'):
            self.assertEqual(policy.failure_report(ValueError(label), code)['error_code'], label)
        self.assertEqual(policy.failure_report(RuntimeError('PRIVATE_ERROR_SENTINEL'), code)['error_code'],
                         'UNRECOGNIZED')

    def test_workflow_keeps_explicit_code_only_and_legacy_paths(self):
        workflow = (shared.Path(__file__).parents[2]/'.github/workflows/debug-rank.yml').read_text()
        self.assertIn("'preview-code-only-upgrade':('naver_preview_code_only','apply')", workflow)
        self.assertIn("policy.prepare(bundle['package'],host.NativeHost(),release,lifecycle,upgrade,module)", workflow)
        self.assertIn("'preview-code-upgrade':('naver_preview_code_upgrade','apply')", workflow)

    def test_reviewed_transition_is_sealed_to_the_exact_latency_release(self):
        code,policy=shared.load('naver_preview_code_upgrade'),shared.load('naver_preview_code_only')
        expected=('6198be366344a82923e10ba5e323877026d82f48',
                  'e4f64e165ebdf81d4127218d5c91ff6904e75958',
                  'b9071a746aa1879d518849bb5a76a8d2259a5d77853e28298fcd26fc7ea0d90e',
                  '716d849b68d72cb03489bc16da1cee3d9a0f31cb16612287b407fe244dea84c6',
                  '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
                  '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
                  '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')
        self.assertEqual(policy.REVIEWED_TRANSITION,expected)
        self.assertEqual((code.OLD_COMMIT,code.TARGET_COMMIT,code.OLD_SOURCE_SHA256,
                         code.TARGET_SOURCE_SHA256,code.STORE_SHA256['old'],code.STORE_SHA256['target'],
                         code.EXPECTED_BASELINE),expected)
        self.assertIsNone(policy.require_review(code))

    def workflow_scripts(self):
        workflow = (shared.Path(__file__).parents[2]/'.github/workflows/debug-rank.yml').read_text()
        scripts, lines = [], None
        for line in workflow.splitlines():
            if line.rstrip().endswith("<<'PY'"):
                lines = []
            elif lines is not None:
                if line.strip() == 'PY':
                    scripts.append(textwrap.dedent('\n'.join(lines))); lines = None
                else:
                    lines.append(line)
        return scripts

    def prepare_encoder(self):
        return next(script for script in self.workflow_scripts() if 'PREPARE_BUNDLE_SIZE' in script)

    def run_remote_script(self, script, variable, wire, marker):
        # Only synthetic source modules are supplied; no host adapter or operating path is used.
        with patch.dict(os.environ,{variable:wire}), redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as stopped:
                exec(compile(script,'<code-only-remote>','exec'),{})
        return stopped.exception.code,json.loads(output.getvalue().split(marker,1)[1])

    def test_apply_workflow_dispatches_explicit_policy_and_preserves_legacy_route(self):
        encode,_,script=shared.ContractTest().workflow_transport()
        for operation in ('preview-code-upgrade','preview-code-only-upgrade'):
            with self.subTest(operation=operation):
                is_code_only=operation=='preview-code-only-upgrade'
                parameters='package,host,release,lifecycle,upgrade'+(',code' if is_code_only else '')
                bundle=dict(operation=operation,function='apply',package={'identity':'synthetic'},
                    source=f'def apply({parameters}):\n    return dict(ok=True,route={operation!r},package=package)\n',
                    host_source='class NativeHost: pass\n',release_source='',lifecycle_source='',
                    upgrade_source='',code_source='')
                status,result=self.run_remote_script(script,'PREVIEW_OPS_B64',encode(bundle),'NAVER_PREVIEW_OPS=')
                self.assertEqual(status,0)
                self.assertEqual(result,dict(ok=True,route=operation,package=bundle['package']))

    def test_prepare_workflow_dispatches_explicit_policy_and_preserves_legacy_route(self):
        script=next(script for script in self.workflow_scripts() if "print('NAVER_PREVIEW_RELEASE=" in script)
        for is_code_only in (False,True):
            with self.subTest(code_only=is_code_only):
                bundle=dict(package={'operation':'code-prepare'},source='',upgrade_source='',lifecycle_source='',
                    host_source='class NativeHost: pass\n',code_source=
                    'def prepare(package,host,release,lifecycle,upgrade):\n    return dict(ok=True,route="legacy")\n')
                if is_code_only:
                    bundle.update(operation='preview-code-only-prepare',code_only_source=
                        'def prepare(package,host,release,lifecycle,upgrade,code):\n    return dict(ok=True,route="code-only")\n')
                wire='prepare-gzip-v1:'+base64.b64encode(gzip.compress(json.dumps(bundle).encode(),mtime=0)).decode()
                status,result=self.run_remote_script(script,'PREVIEW_RELEASE_B64',wire,'NAVER_PREVIEW_RELEASE=')
                self.assertEqual(status,0)
                self.assertEqual(result,dict(ok=True,route='code-only' if is_code_only else 'legacy'))

    def test_code_only_prepare_cannot_fall_back_to_a_legacy_mode(self):
        script=next(script for script in self.workflow_scripts() if "print('NAVER_PREVIEW_RELEASE=" in script)
        for operation,package_operation in (('preview-code-only-prepare','prepare'),
                                            (None,'code-prepare'),('unrecognized','code-prepare')):
            with self.subTest(operation=operation,package_operation=package_operation):
                bundle=dict(package={'operation':package_operation},source=
                    'def prepare(package,host): return dict(ok=True)\n',host_source='class NativeHost: pass\n',
                    upgrade_source='',lifecycle_source='',code_source=
                    'def prepare(package,host,release,lifecycle,upgrade): return dict(ok=True)\n',
                    code_only_source='def prepare(package,host,release,lifecycle,upgrade,code): return dict(ok=True)\n')
                if operation is not None:
                    bundle['operation']=operation
                wire='prepare-gzip-v1:'+base64.b64encode(gzip.compress(json.dumps(bundle).encode(),mtime=0)).decode()
                status,result=self.run_remote_script(script,'PREVIEW_RELEASE_B64',wire,'NAVER_PREVIEW_RELEASE=')
                self.assertEqual(status,1)
                self.assertFalse(result['ok'])

    def test_unreviewed_prepare_workflow_refuses_before_download(self):
        code, policy, downloader = (shared.load(name) for name in (
            'naver_preview_code_upgrade','naver_preview_code_only','naver_preview_download'))
        inputs = dict(ad_prepare='preview-code-only-prepare',ad_expected_baseline=json.dumps({'source_commit':code.TARGET_COMMIT}))
        with patch.dict(sys.modules,naver_preview_code_upgrade=code,naver_preview_code_only=policy,
                        naver_preview_download=downloader), patch.object(policy,'REVIEWED_TRANSITION',None), \
                patch.dict(os.environ,INPUTS_JSON=json.dumps(inputs)), \
                patch.object(downloader,'download') as download, redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as stopped:
                exec(compile(self.prepare_encoder(),'<code-only-prepare>','exec'),{})
            self.assertEqual(stopped.exception.code,1)
            download.assert_not_called()
            self.assertEqual(output.getvalue(),'PREVIEW_ENCRYPTED_INPUT_REFUSED\n')

    def test_reviewed_prepare_workflow_packages_policy_with_existing_size_limits(self):
        code, policy, downloader = (shared.load(name) for name in (
            'naver_preview_code_upgrade','naver_preview_code_only','naver_preview_download'))
        policy.REVIEWED_TRANSITION = (code.OLD_COMMIT,code.TARGET_COMMIT,code.OLD_SOURCE_SHA256,
            code.TARGET_SOURCE_SHA256,code.STORE_SHA256['old'],code.STORE_SHA256['target'],code.EXPECTED_BASELINE)
        fields = dict(baseline=code.EXPECTED_BASELINE,source_commit=code.TARGET_COMMIT,
                      source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,ciphertext_sha256='c'*64)
        with tempfile.TemporaryDirectory() as folder:
            env_file = shared.Path(folder)/'env'
            with patch.dict(sys.modules,naver_preview_code_upgrade=code,naver_preview_code_only=policy,
                            naver_preview_download=downloader), patch.object(downloader,'download',return_value=fields), \
                    patch.dict(os.environ,INPUTS_JSON=json.dumps(dict(ad_prepare='preview-code-only-prepare',
                        ad_expected_baseline=json.dumps({'source_commit':code.TARGET_COMMIT}))),RUN_ID='999999',GITHUB_ENV=str(env_file)):
                exec(compile(self.prepare_encoder(),'<code-only-prepare>','exec'),{})
            encoded = env_file.read_text().split('=',1)[1].strip()
        self.assertTrue(encoded.startswith('prepare-gzip-v1:'))
        self.assertLessEqual(len(encoded),73728)
        raw = gzip.decompress(base64.b64decode(encoded.split(':',1)[1]))
        self.assertLessEqual(len(raw),229376)
        bundle = json.loads(raw)
        self.assertEqual(bundle['operation'],'preview-code-only-prepare')
        self.assertEqual(bundle['package']['operation'],'code-prepare')
        self.assertEqual(bundle['code_only_source'],(shared.Path(__file__).parents[1]/'tools/naver_preview_code_only.py').read_text())

    def test_code_only_workflow_error_reporting_uses_safe_policy_labels(self):
        _, _, script = shared.ContractTest().workflow_transport()
        guarded = next(node for node in ast.parse(script).body if isinstance(node,ast.Try))
        handler = compile(ast.Module(body=guarded.handlers[0].body,type_ignores=[]),'<workflow-error>','exec')
        code, policy = shared.load('naver_preview_code_upgrade'), shared.load('naver_preview_code_only')
        for label in ('CODE_ONLY_RELEASE_NOT_REVIEWED','PRIVATE_CREDENTIAL_MARKER'):
            scope = dict(error=ValueError(label),bundle={'operation':'preview-code-only-upgrade'},
                         module=policy,code=code,re=shared.re)
            exec(handler,scope)
            self.assertEqual(scope['result']['error_code'],label if label.startswith('CODE_ONLY_') else 'UNRECOGNIZED')
            self.assertNotIn('PRIVATE',json.dumps(scope['result']))

    def test_code_only_prepare_error_reporting_never_echoes_untrusted_labels(self):
        workflow = (shared.Path(__file__).parents[2]/'.github/workflows/debug-rank.yml').read_text()
        scripts, lines = [], None
        for line in workflow.splitlines():
            if line.rstrip().endswith("<<'PY'"):
                lines=[]
            elif lines is not None:
                if line.strip()=='PY':
                    scripts.append(textwrap.dedent('\n'.join(lines)));lines=None
                else: lines.append(line)
        script=next(script for script in scripts if "print('NAVER_PREVIEW_RELEASE=" in script)
        guarded=next(node for node in ast.parse(script).body if isinstance(node,ast.Try))
        handler=compile(ast.Module(body=guarded.handlers[0].body,type_ignores=[]),'<prepare-error>','exec')
        code,policy=shared.load('naver_preview_code_upgrade'),shared.load('naver_preview_code_only')
        scope=dict(error=ValueError('PRIVATE_CREDENTIAL_MARKER'),module=code,policy=policy,
                   bundle={'operation':'preview-code-only-prepare'},re=shared.re)
        exec(handler,scope)
        self.assertNotIn('PRIVATE',json.dumps(scope['result']))
        self.assertEqual(scope['result']['error_code'],'UNRECOGNIZED')


if __name__ == '__main__':
    unittest.main()
