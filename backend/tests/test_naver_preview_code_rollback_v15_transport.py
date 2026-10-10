"""V15 uses the original bounded rollback encoder and credential-cleared remote dispatcher."""
import json
from pathlib import Path

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_rollback_transport as previous
import test_naver_preview_code_only as legacy


class V15RollbackTransportTest(previous.RollbackTransportTest):
    def setUp(self):
        super().setUp()
        self.code = shared.load('naver_preview_code_upgrade_v15')
        self.package = dict(release=dict(baseline=self.code.EXPECTED_BASELINE,
            source_commit=self.code.TARGET_COMMIT, source_tar_gz_sha256=self.code.TARGET_SOURCE_SHA256,
            ciphertext_sha256='c'*64, run_id='123456', operation='code-prepare'),
            apply_operation_id='9'*32, operation_id='8'*32)
        self.inputs['ad_expected_baseline'] = json.dumps(self.package)

    def test_v15_encoder_selects_two_file_helper_and_keeps_v14_policy(self):
        bundle = self.decode(self.encoded())
        tools = Path(__file__).parents[1]/'tools'
        self.assertEqual(bundle['code_source'], (tools/'naver_preview_code_upgrade_v15.py').read_text())
        self.assertEqual(self.code.CODE_PATHS, {'naver_engine/report_views.py', 'naver_engine/store.py'})
        self.assertEqual(self.policy.code_module_name(self.code.TARGET_COMMIT), 'naver_preview_code_upgrade_v15')
        v14 = shared.load('naver_preview_code_upgrade_v14')
        self.assertEqual(self.policy.code_module_name(v14.TARGET_COMMIT), 'naver_preview_code_upgrade_v14')
        self.helper.require_review(self.policy, v14)
        self.helper.require_review(self.policy, self.code)

    def test_v15_remote_forged_archive_scope_or_prior_helper_refuses_before_host(self):
        original = self.decode(self.encoded())
        tools = Path(__file__).parents[1]/'tools'
        edits = (
            {'package':dict(self.package, release=dict(self.package['release'], source_tar_gz_sha256='0'*64))},
            {'code_source':original['code_source'].replace(
                "CODE_PATHS = {'naver_engine/report_views.py', 'naver_engine/store.py'}",
                "CODE_PATHS = {'naver_engine/web.py'}")},
            {'code_source':(tools/'naver_preview_code_upgrade_v14.py').read_text()},
        )
        for edit, expected in zip(edits, ('CODE_TARGET_SOURCE_CHANGED', 'CODE_ONLY_RELEASE_NOT_REVIEWED', 'CODE_TARGET')):
            bundle = dict(original, **edit)
            bundle['host_source'] = 'class NativeHost:\n    def baseline(self): raise AssertionError("PRIVATE_HOST_ACTION")\n'
            with self.subTest(edit=next(iter(edit))):
                status, result = legacy.CodeOnlyTest().run_remote_script(
                    self.remote, 'PREVIEW_OPS_B64', self.encode(bundle), 'NAVER_PREVIEW_OPS=')
                self.assertEqual(status, 1)
                self.assertEqual(result['error_code'], expected)
                self.assertNotIn('PRIVATE', json.dumps(result))


if __name__ == '__main__':
    import unittest
    unittest.main()
