"""Final74 explicit rollback transport pins and closed defaults; no SSH or DB."""
import ast
import base64
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_only as legacy


class RollbackTransportTest(unittest.TestCase):
    def setUp(self):
        self.code = shared.load('naver_preview_code_upgrade_v5')
        self.helper = shared.load('naver_preview_code_rollback')
        self.policy = shared.load('naver_preview_code_only')
        self.encode, self.decode, self.remote = shared.ContractTest().workflow_transport()
        self.script = legacy.CodeOnlyTest().workflow_scripts()[0]
        self.package = dict(release=dict(baseline=self.code.EXPECTED_BASELINE,
            source_commit=self.code.TARGET_COMMIT, source_tar_gz_sha256=self.code.TARGET_SOURCE_SHA256,
            ciphertext_sha256='c' * 64, run_id='123456', operation='code-prepare'),
            apply_operation_id='9' * 32, operation_id='8' * 32)
        self.inputs = dict(ad_prepare='preview-code-only-rollback',
            ad_expected_baseline=json.dumps(self.package),
            **{key: 'off' for key in ('collector', 'rank_link', 'capacity', 'structure',
                'expired', 'queue', 'urlshape', 'use_branch_code')})

    def encoded(self, inputs=None):
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder) / 'env'
            with patch.dict(os.environ, INPUTS_JSON=json.dumps(inputs or self.inputs), GITHUB_ENV=str(env_file)):
                exec(compile(self.script, '<rollback-encoder>', 'exec'), {})
            return env_file.read_text().split('=', 1)[1].strip()

    def test_final74_rollback_encoder_carries_only_pinned_code_and_policy_with_original_bounds(self):
        wire = self.encoded()
        bundle = self.decode(wire)
        tools = Path(__file__).parents[1] / 'tools'
        self.assertEqual(bundle['operation'], 'preview-code-only-rollback')
        self.assertEqual(bundle['function'], 'run')
        self.assertEqual(bundle['code_source'], (tools / (self.code.__name__ + '.py')).read_text())
        self.assertEqual(bundle['source'], (tools / 'naver_preview_code_rollback.py').read_text())
        self.assertEqual(bundle['code_only_source'], (tools / 'naver_preview_code_only.py').read_text())
        self.assertEqual(bundle['package'], self.package)
        self.assertLessEqual(len(wire), 73728)
        self.assertLessEqual(len(json.dumps(bundle).encode()), 229376)
        self.assertEqual(self.encode(bundle), wire)

    def test_request_source_archive_baseline_scope_override_or_bad_ids_cannot_open_another_transition(self):
        changes = ({'source_commit': '0' * 40}, {'source_tar_gz_sha256': '0' * 64},
                   {'baseline': '0' * 64}, {'operation': 'upgrade-prepare'})
        for change in changes:
            package = dict(self.package, release=dict(self.package['release'], **change))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.encoded(dict(self.inputs, ad_expected_baseline=json.dumps(package)))
        for change in ({'CODE_PATHS': ['naver_engine/store.py']}, {'REVIEWED_ROLLBACKS': []},
                       {'operation_id': self.package['apply_operation_id']}, {'apply_operation_id': '../escape'}):
            package = dict(self.package, **change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.encoded(dict(self.inputs, ad_expected_baseline=json.dumps(package)))

    def test_every_other_input_stays_off(self):
        for key in self.inputs.keys() - {'ad_prepare', 'ad_expected_baseline'}:
            with self.subTest(input=key), self.assertRaises(AssertionError):
                self.encoded(dict(self.inputs, **{key: 'on'}))

    def test_older_forward_targets_do_not_gain_rollback_permission(self):
        for name in ('naver_preview_code_upgrade', 'naver_preview_code_upgrade_v3', 'naver_preview_code_upgrade_v4'):
            code = shared.load(name)
            package = dict(self.package, release=dict(self.package['release'],
                source_commit=code.TARGET_COMMIT, source_tar_gz_sha256=code.TARGET_SOURCE_SHA256))
            with self.subTest(code=name), self.assertRaisesRegex(ValueError, 'CODE_ROLLBACK_NOT_REVIEWED'):
                self.encoded(dict(self.inputs, ad_expected_baseline=json.dumps(package)))

    def test_plain_encoding_wrong_function_and_gzip_overflow_refuse(self):
        bundle = self.decode(self.encoded())
        plain = base64.b64encode(json.dumps(bundle).encode()).decode()
        with self.assertRaisesRegex(ValueError, 'CODE_OPS_ENCODING'): self.decode(plain)
        with self.assertRaisesRegex(ValueError, 'CODE_OPS_OPERATION'):
            self.decode(self.encode(dict(bundle, function='apply')))
        with self.assertRaisesRegex(ValueError, 'CODE_OPS_JSON_SIZE'):
            self.encode(dict(bundle, source='x' * 229376))

    def test_remote_dispatch_loads_rollback_policy_separately_and_clears_credential_environment(self):
        bundle = self.decode(self.encoded())
        bundle.update(source='''import os
def run(package,host,release,lifecycle,upgrade,policy,code):
    assert policy.marker == "policy" and code.marker == "code"
    assert set(os.environ) == {"PATH","LANG"}
    return dict(ok=True,route="rollback",package=package)
''', code_only_source='marker="policy"\n', code_source='marker="code"\n',
            release_source='', lifecycle_source='', upgrade_source='', host_source='class NativeHost: pass\n')
        code, result = legacy.CodeOnlyTest().run_remote_script(self.remote, 'PREVIEW_OPS_B64',
            self.encode(bundle), 'NAVER_PREVIEW_OPS=')
        self.assertEqual(code, 0)
        self.assertEqual(result, dict(ok=True, route='rollback', package=self.package))

    def test_remote_refused_rollback_reports_safe_labels_without_host_commands(self):
        bundle = self.decode(self.encoded())
        bundle['host_source'] = 'class NativeHost:\n    def baseline(self): raise AssertionError("PRIVATE_HOST_ACTION")\n'
        bundle['package'] = {'untrusted': 'PRIVATE_INPUT'}
        code, result = legacy.CodeOnlyTest().run_remote_script(self.remote, 'PREVIEW_OPS_B64',
            self.encode(bundle), 'NAVER_PREVIEW_OPS=')
        self.assertEqual(code, 1)
        self.assertEqual(result['error_code'], 'CODE_ROLLBACK_FIELDS')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_remote_unknown_exception_text_and_kind_are_redacted(self):
        bundle = self.decode(self.encoded())
        # Keep the real helper's failure_report but replace its callable test entry.
        bundle['source'] += '\ndef run(*args): raise type("PRIVATE_EXCEPTION",(Exception,),{})("PRIVATE_CREDENTIAL")\n'
        bundle['host_source'] = 'class NativeHost: pass\n'
        code, result = legacy.CodeOnlyTest().run_remote_script(self.remote, 'PREVIEW_OPS_B64',
            self.encode(bundle), 'NAVER_PREVIEW_OPS=')
        self.assertEqual(code, 1)
        self.assertEqual(result['error_kind'], 'OtherError')
        self.assertEqual(result['error_code'], 'UNRECOGNIZED')
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_dispatch_ref_default_and_existing_host_are_unchanged(self):
        workflow = (Path(__file__).parents[2] / '.github/workflows/debug-rank.yml').read_text()
        job = workflow.split('  preview-ops:', 1)[1].split('  preview-start:', 1)[0]
        self.assertIn("github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'", job)
        self.assertNotIn('codex/naver-login-read-limit-release-20261009', workflow)
        self.assertIn("default: 'off'", workflow)
        self.assertIn("'preview-code-only-rollback':('naver_preview_code_rollback','run')", job)
        self.assertIn('host: ${{ secrets.VPS_HOST }}', job)
        self.assertIn("inputs.ad_prepare == 'preview-code-only-rollback' && 65", job)
        self.assertIn("inputs.ad_prepare == 'preview-code-only-rollback' && '60m'", job)


if __name__ == '__main__':
    unittest.main()
