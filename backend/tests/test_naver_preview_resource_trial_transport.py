"""Explicit resource trial transport; fixed mode, closed inputs, no operating host."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_only as legacy


class ResourceTrialTransportTest(unittest.TestCase):
    def setUp(self):
        self.helper=shared.load('naver_preview_resource_trial')
        self.encode,self.decode,self.remote=shared.ContractTest().workflow_transport()
        self.script=legacy.CodeOnlyTest().workflow_scripts()[0]
        self.package=dict(release=dict(source_commit=self.helper.SOURCE_COMMIT,
            source_tar_gz_sha256=self.helper.SOURCE_SHA256,baseline=self.helper.BASELINE),
            operation_id='9'*32,action='apply')
        self.inputs=dict(ad_prepare='preview-resource-trial',ad_expected_baseline=json.dumps(self.package),
            **{k:'off' for k in ('collector','rank_link','capacity','structure','expired','queue','urlshape','use_branch_code')})

    def encoded(self,inputs=None):
        with tempfile.TemporaryDirectory() as folder:
            env_file=Path(folder)/'env'
            original=Path.cwd()
            try:
                os.chdir(Path(__file__).parents[2])
                with patch.dict(os.environ,INPUTS_JSON=json.dumps(inputs or self.inputs),GITHUB_ENV=str(env_file)):
                    exec(compile(self.script,'<resource-encoder>','exec'),{})
                return env_file.read_text().split('=',1)[1].strip()
            finally: os.chdir(original)

    def test_apply_and_same_operation_rollback_have_bounded_three_source_transport(self):
        for action in ('apply','rollback'):
            wire=self.encoded(dict(self.inputs,ad_expected_baseline=json.dumps(dict(self.package,action=action))))
            bundle=self.decode(wire)
            self.assertEqual(bundle['operation'],'preview-resource-trial')
            self.assertEqual(bundle['function'],'run')
            self.assertEqual(bundle['package'],dict(self.package,action=action))
            self.assertEqual(set(bundle),{'operation','function','package','source','release_source','host_source'})
            self.assertLessEqual(len(wire),65536)
            self.assertLessEqual(len(json.dumps(bundle).encode()),196608)

    def test_bad_source_general_resources_container_selection_and_other_inputs_refuse_locally(self):
        changes=[dict(self.package,release=dict(self.package['release'],source_commit='0'*40)),
            dict(self.package,release=dict(self.package['release'],source_tar_gz_sha256='0'*64)),
            dict(self.package,cpus=2),dict(self.package,container_id='d'*64),dict(self.package,action='inspect')]
        for package in changes:
            with self.subTest(package=package),self.assertRaises(ValueError):
                self.encoded(dict(self.inputs,ad_expected_baseline=json.dumps(package)))
        for key in self.inputs.keys()-{'ad_prepare','ad_expected_baseline'}:
            with self.subTest(key=key),self.assertRaises(AssertionError): self.encoded(dict(self.inputs,**{key:'on'}))

    def test_plain_wire_wrong_function_and_oversize_refuse(self):
        bundle=self.decode(self.encoded())
        with self.assertRaisesRegex(ValueError,'CODE_OPS_ENCODING'):
            self.decode(base64.b64encode(json.dumps(bundle).encode()).decode())
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
            self.decode(self.encode(dict(bundle,function='apply')))
        with self.assertRaisesRegex(ValueError,'CODE_OPS_JSON_SIZE'):
            self.encode(dict(bundle,source='x'*196608))

    def test_remote_resource_run_has_release_only_and_credential_environment_is_cleared(self):
        bundle=self.decode(self.encoded())
        bundle.update(source='''import os
def run(package,host,release):
    assert set(os.environ)=={"PATH","LANG"}
    return dict(ok=True,route="resource",package=package)
''',release_source='',host_source='class NativeHost: pass\n')
        code,result=legacy.CodeOnlyTest().run_remote_script(self.remote,'PREVIEW_OPS_B64',
            self.encode(bundle),'NAVER_PREVIEW_OPS=')
        self.assertEqual(code,0)
        self.assertEqual(result,dict(ok=True,route='resource',package=self.package))

    def test_remote_bad_package_refuses_before_host_and_unknown_error_is_redacted(self):
        bundle=self.decode(self.encoded())
        bundle['host_source']='class NativeHost:\n    def baseline(self): raise AssertionError("PRIVATE_HOST_ACTION")\n'
        bundle['package']=dict(self.package,release=dict(self.package['release'],source_commit='0'*40))
        code,result=legacy.CodeOnlyTest().run_remote_script(self.remote,'PREVIEW_OPS_B64',
            self.encode(bundle),'NAVER_PREVIEW_OPS=')
        self.assertEqual(code,1)
        self.assertEqual(result['error_code'],'RESOURCE_SOURCE')
        self.assertNotIn('PRIVATE',json.dumps(result))
        bundle=self.decode(self.encoded())
        bundle['source']+='\ndef run(*args): raise type("PRIVATE_EXCEPTION",(Exception,),{})("PRIVATE_CREDENTIAL")\n'
        bundle['host_source']='class NativeHost: pass\n'
        code,result=legacy.CodeOnlyTest().run_remote_script(self.remote,'PREVIEW_OPS_B64',
            self.encode(bundle),'NAVER_PREVIEW_OPS=')
        self.assertEqual(code,1)
        self.assertEqual(result['error_code'],'UNRECOGNIZED')
        self.assertEqual(result['error_kind'],'OtherError')
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_existing_workflow_branch_permissions_concurrency_and_defaults_are_preserved(self):
        workflow=(Path(__file__).parents[2]/'.github/workflows/debug-rank.yml').read_text()
        job=workflow.split('  preview-ops:',1)[1].split('  preview-start:',1)[0]
        self.assertIn("github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'",job)
        self.assertIn("default: 'off'",workflow)
        self.assertIn('contents: read',job)
        self.assertIn('group: deploy-logic-analysis',job)
        self.assertIn('cancel-in-progress: false',job)
        self.assertIn('host: ${{ secrets.VPS_HOST }}',job)
        self.assertIn("'preview-resource-trial':('naver_preview_resource_trial','run')",job)


if __name__=='__main__': unittest.main()
