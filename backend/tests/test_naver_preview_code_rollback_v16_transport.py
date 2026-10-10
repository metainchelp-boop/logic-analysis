"""V16 exact UI-only transport guards; synthetic inputs only, no SSH, downloads or DB."""
import base64
import gzip
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_rollback_transport as previous
import test_naver_preview_code_only as legacy


MODULE = 'naver_preview_code_upgrade_v16'
PATHS = {'backend/naver_page/report-ui.js', 'backend/naver_page/report-pdf.js',
         'backend/naver_page/app.css'}
OLD = '702bc6ed3f224638524511a6ef7d43b6dd825343'
OLD_ARCHIVE = '5ad8a0e90e37c9025cf2e3e91ccb1c7db9f3fa6b05b17668a4b873ed6983723f'
STORE = 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56'


class V16RollbackTransportTest(previous.RollbackTransportTest):
    def setUp(self):
        super().setUp()
        self.code = shared.load(MODULE)
        self.package = dict(release=dict(baseline=self.code.EXPECTED_BASELINE,
            source_commit=self.code.TARGET_COMMIT, source_tar_gz_sha256=self.code.TARGET_SOURCE_SHA256,
            ciphertext_sha256='c'*64, run_id='123456', operation='code-prepare'),
            apply_operation_id='9'*32, operation_id='8'*32)
        self.inputs['ad_expected_baseline'] = json.dumps(self.package)

    def test_v16_encoder_selects_exact_three_ui_files_and_keeps_v15_policy(self):
        bundle = self.decode(self.encoded())
        tools = Path(__file__).parents[1]/'tools'
        self.assertEqual(bundle['code_source'], (tools/(MODULE+'.py')).read_text())
        self.assertEqual(self.code.CODE_PATHS, PATHS)
        self.assertEqual(self.code.ADDED_SOURCE_PATHS, frozenset())
        self.assertEqual(self.code.OLD_COMMIT, OLD)
        self.assertEqual(self.code.OLD_SOURCE_SHA256, OLD_ARCHIVE)
        self.assertEqual(self.code.STORE_SHA256, {'old':STORE, 'target':STORE})
        self.assertEqual(self.code.TARGET_ACTION_ROUTES, ('/reports/notes',))
        self.assertEqual(self.policy.code_module_name(self.code.TARGET_COMMIT), MODULE)
        v15 = shared.load('naver_preview_code_upgrade_v15')
        self.assertEqual(v15.TARGET_COMMIT, OLD)
        self.assertEqual(v15.TARGET_SOURCE_SHA256, OLD_ARCHIVE)
        self.assertEqual(v15.CODE_PATHS, {'naver_engine/report_views.py', 'naver_engine/store.py'})
        self.assertEqual(self.policy.code_module_name(v15.TARGET_COMMIT), 'naver_preview_code_upgrade_v15')
        self.helper.require_review(self.policy, v15)
        self.helper.require_review(self.policy, self.code)

    def test_v16_remote_forged_archive_scope_or_prior_helper_refuses_before_host(self):
        original = self.decode(self.encoded())
        tools = Path(__file__).parents[1]/'tools'
        edits = (
            {'package':dict(self.package, release=dict(self.package['release'], source_tar_gz_sha256='0'*64))},
            {'code_source':original['code_source']+"\nCODE_PATHS = {'naver_engine/web.py'}\n"},
            {'code_source':(tools/'naver_preview_code_upgrade_v15.py').read_text()},
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

    def test_v16_pending_target_closes_actual_encoder_before_env_output(self):
        package = dict(self.package, release=dict(self.package['release'],
            source_commit=self.code.TARGET_COMMIT or 'b'*40,
            source_tar_gz_sha256=self.code.TARGET_SOURCE_SHA256 or 'd'*64))
        with patch.dict(sys.modules, {MODULE:self.code}), patch.object(self.code, 'TARGET_COMMIT', None):
            with self.assertRaisesRegex(ValueError, '^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                self.encoded(dict(self.inputs, ad_expected_baseline=json.dumps(package)))

    def prepare_wire(self):
        """Run the actual workflow encoder, replacing its downloader with a synthetic adapter."""
        downloader = shared.load('naver_preview_download')
        release = shared.load('naver_preview_release')
        fields = {key:value for key,value in self.package['release'].items()
                  if key not in ('run_id', 'operation')}
        inputs = dict(self.inputs, ad_prepare='preview-code-only-prepare',
                      ad_expected_baseline=json.dumps({'source_commit':self.code.TARGET_COMMIT}))
        with tempfile.TemporaryDirectory() as folder:
            env_file = Path(folder)/'env'
            with patch.dict(sys.modules, {MODULE:self.code, 'naver_preview_code_only':self.policy,
                    'naver_preview_download':downloader, 'naver_preview_release':release}), \
                 patch.object(downloader, 'download', return_value=fields) as download, \
                 patch.dict(os.environ, INPUTS_JSON=json.dumps(inputs), RUN_ID='123456', GITHUB_ENV=str(env_file)):
                exec(compile(legacy.CodeOnlyTest().prepare_encoder(), '<v16-prepare-encoder>', 'exec'), {})
                download.assert_called_once_with({'source_commit':self.code.TARGET_COMMIT}, 'preview-payload')
            return env_file.read_text().split('=', 1)[1].strip()

    def wire_bundles(self):
        prepare = self.prepare_wire()
        self.assertTrue(prepare.startswith('prepare-gzip-v1:'))
        prepared = json.loads(gzip.decompress(base64.b64decode(prepare.split(':', 1)[1])))
        apply_package = dict(release=self.package['release'], operation_id=self.package['apply_operation_id'])
        passive_package = {key:self.package['release'][key] for key in
                           ('baseline', 'source_commit', 'source_tar_gz_sha256')}
        passive_package['passive_runtime_only'] = True
        apply_wire = self.encoded(dict(self.inputs, ad_prepare='preview-code-only-upgrade',
                                      ad_expected_baseline=json.dumps(apply_package)))
        rollback_wire = self.encoded()
        passive_wire = self.encoded(dict(self.inputs, ad_prepare='preview-collection-status',
                                        ad_expected_baseline=json.dumps(passive_package)))
        return {
            'prepare':(prepare, prepared),
            'apply':(apply_wire, self.decode(apply_wire)),
            'rollback':(rollback_wire, self.decode(rollback_wire)),
            'passive':(passive_wire, self.decode(passive_wire)),
        }

    def transport_sizes(self):
        """Same four workflow bundles on macOS or Linux; do not reconstruct or sort wire keys."""
        sizes = {}
        prepare_remote = next(script for script in legacy.CodeOnlyTest().workflow_scripts()
                              if "print('NAVER_PREVIEW_RELEASE=" in script)
        for name,(wire,bundle) in self.wire_bundles().items():
            variable = 'PREVIEW_RELEASE_B64' if name == 'prepare' else 'PREVIEW_OPS_B64'
            remote = prepare_remote if name == 'prepare' else self.remote
            shell = 'export '+variable+'='+shlex.quote(wire)+";\nset -eu\n/usr/bin/python3 -I -B - <<'PY'\n"+remote+'\nPY\n'
            sizes[name] = {'raw_bytes':len(json.dumps(bundle).encode()), 'wire_bytes':len(wire.encode()),
                           'shell_bytes':len(('/bin/bash -c '+shlex.quote(shell)).encode())}
        return sizes

    def test_v16_four_actual_bundles_preserve_order_and_original_bounds(self):
        bundles = self.wire_bundles()
        orders = {
            'prepare':['package','source','host_source','upgrade_source','lifecycle_source','code_source','operation','code_only_source'],
            'apply':['package','operation','function','source','release_source','host_source','lifecycle_source','upgrade_source','code_source'],
            'rollback':['package','operation','function','source','release_source','host_source','lifecycle_source','upgrade_source','code_source','code_only_source'],
            'passive':['package','operation','function','source','release_source','host_source'],
        }
        tools = Path(__file__).parents[1]/'tools'
        for name,(wire,bundle) in bundles.items():
            with self.subTest(bundle=name):
                self.assertEqual(list(bundle), orders[name])
                self.assertEqual(bundle['package']['source_commit'] if name in ('prepare','passive')
                                 else bundle['package']['release']['source_commit'], self.code.TARGET_COMMIT)
                if name != 'passive':
                    self.assertEqual(bundle['code_source'], (tools/(MODULE+'.py')).read_text())
                else:
                    self.assertIs(bundle['package']['passive_runtime_only'], True)
                if name in ('prepare','rollback'):
                    self.assertEqual(bundle['code_only_source'], (tools/'naver_preview_code_only.py').read_text())
                if name != 'prepare':
                    self.assertEqual(self.encode(bundle), wire)
                self.assertLessEqual(len(json.dumps(bundle).encode()), 229376 if name == 'prepare' else 229376)
                self.assertLessEqual(len(wire.encode()), 73728)
        for name,size in self.transport_sizes().items():
            with self.subTest(shell=name):
                self.assertLess(size['shell_bytes'], 120000)


if __name__ == '__main__':
    if sys.argv[1:] == ['--wire-sizes']:
        case = V16RollbackTransportTest()
        case.setUp()
        print(json.dumps(case.transport_sizes()))
    else:
        unittest.main()
