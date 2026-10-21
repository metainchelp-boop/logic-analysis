"""V12 rollback uses the existing bounded transport, exact code policy and closed defaults."""
import json
from pathlib import Path
from unittest.mock import patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_rollback_transport as previous


class V12RollbackTransportTest(previous.RollbackTransportTest):
    def setUp(self):
        super().setUp()
        self.code = shared.load('naver_preview_code_upgrade_v12')
        self.package = dict(release=dict(baseline=self.code.EXPECTED_BASELINE,
            source_commit=self.code.TARGET_COMMIT,
            source_tar_gz_sha256=self.code.TARGET_SOURCE_SHA256,
            ciphertext_sha256='c' * 64, run_id='123456', operation='code-prepare'),
            apply_operation_id='9' * 32, operation_id='8' * 32)
        self.inputs['ad_expected_baseline'] = json.dumps(self.package)

    def test_v12_transport_is_separate_and_preserves_prior_v5_policy(self):
        bundle = self.decode(self.encoded())
        tools = Path(__file__).parents[1] / 'tools'
        self.assertEqual(bundle['code_source'], (tools / 'naver_preview_code_upgrade_v12.py').read_text())
        self.assertEqual(self.code.CODE_PATHS, {'naver_engine/store.py', 'naver_engine/web.py', 'naver_engine/views.py', 'backend/naver_page/app.js', 'naver_runtime/writer.py', 'naver_runtime/__main__.py', 'naver_engine/collection_diagnostics.py'})
        self.assertEqual(self.policy.code_module_name(self.code.TARGET_COMMIT), 'naver_preview_code_upgrade_v12')
        old = shared.load('naver_preview_code_upgrade_v5')
        self.assertEqual(self.policy.code_module_name(old.TARGET_COMMIT), 'naver_preview_code_upgrade_v5')
        self.helper.require_review(self.policy, old)
        self.helper.require_review(self.policy, self.code)

    def test_remote_v12_mismatched_source_archive_or_scope_refuses_before_host(self):
        original = self.decode(self.encoded())
        for edit in (
                {'package': dict(self.package, release=dict(self.package['release'], source_commit='0' * 40))},
                {'package': dict(self.package, release=dict(self.package['release'], source_tar_gz_sha256='0' * 64))},
                {'code_source': original['code_source'].replace(
                    "CODE_PATHS = {'naver_engine/store.py', 'naver_engine/web.py', 'naver_engine/views.py', 'backend/naver_page/app.js', 'naver_runtime/writer.py', 'naver_runtime/__main__.py', 'naver_engine/collection_diagnostics.py'}",
                    "CODE_PATHS = {'naver_engine/web.py'}")},
                {'code_source': (Path(__file__).parents[1] / 'tools/naver_preview_code_upgrade_v5.py').read_text()}):
            bundle = dict(original, **edit,
                host_source='class NativeHost:\n    def baseline(self): raise AssertionError("PRIVATE_HOST_ACTION")\n')
            with self.subTest(fields=set(edit)):
                code, result = previous.legacy.CodeOnlyTest().run_remote_script(
                    self.remote, 'PREVIEW_OPS_B64', self.encode(bundle), 'NAVER_PREVIEW_OPS=')
            self.assertEqual(code, 1)
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertIn(result['error_code'], {'CODE_TARGET', 'CODE_TARGET_SOURCE_CHANGED',
                'CODE_ONLY_RELEASE_NOT_REVIEWED', 'CODE_ROLLBACK_NOT_REVIEWED'})
