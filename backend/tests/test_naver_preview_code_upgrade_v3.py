"""Third release pins, workflow selection and code-only safety. No live host or DB."""
import ast
import base64
from contextlib import redirect_stdout
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_only as legacy_policy


MODULE = 'naver_preview_code_upgrade_v3'
PINS = ('e4f64e165ebdf81d4127218d5c91ff6904e75958',
        '953c2ccdb1d74a4fd339de013a1bbbbc5f50e3b6',
        '716d849b68d72cb03489bc16da1cee3d9a0f31cb16612287b407fe244dea84c6',
        '461be6b6ae6d09d74108f9f96a5e2bcf68feffdd2728c43f1b5e460be743ac80',
        '5fa2618f3d74bdfaa10581f6ac759d605544ab0e0e8178eef89f68d8e6840c94',
        'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862',
        '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76')
PATHS = {'naver_engine/inventory.py', 'naver_engine/store.py',
         'naver_engine/naver_read.py', 'naver_engine/morning.py'}


def pins(code):
    return (code.OLD_COMMIT,code.TARGET_COMMIT,code.OLD_SOURCE_SHA256,code.TARGET_SOURCE_SHA256,
            code.STORE_SHA256['old'],code.STORE_SHA256['target'],code.EXPECTED_BASELINE)


def package(code):
    return dict(baseline=code.EXPECTED_BASELINE,source_commit=code.TARGET_COMMIT,
                ciphertext_sha256='c'*64,source_tar_gz_sha256=code.TARGET_SOURCE_SHA256,
                run_id='999999',operation='code-prepare')


class V3ContractTest(unittest.TestCase):
    def test_exact_separate_pins_and_file_scopes(self):
        code,old,policy = (shared.load(name) for name in (MODULE,'naver_preview_code_upgrade','naver_preview_code_only'))
        self.assertEqual(pins(code),PINS)
        self.assertEqual(policy.REVIEWED_TRANSITION_V3,PINS)
        self.assertEqual(code.CODE_PATHS,PATHS)
        self.assertEqual(code.TEST_PATHS,frozenset())
        self.assertNotEqual(pins(old),pins(code))
        self.assertIsNot(old.CODE_PATHS,code.CODE_PATHS)
        self.assertIsNot(old.STORE_SHA256,code.STORE_SHA256)
        policy.require_review(old)
        policy.require_review(code)

    def test_v3_shared_control_functions_are_ast_identical_and_paired_db_apply_is_closed(self):
        root=Path(__file__).parents[1]/'tools'
        def functions(name):
            return {node.name:ast.dump(node,include_attributes=False)
                    for node in ast.parse((root/(name+'.py')).read_text()).body
                    if isinstance(node,(ast.FunctionDef,ast.ClassDef)) and node.name!='apply'}
        self.assertEqual(functions(MODULE),functions('naver_preview_code_upgrade'))
        code=shared.load(MODULE)
        adapters=[Mock() for _ in range(4)]
        with self.assertRaisesRegex(ValueError,'^CODE_ONLY_REQUIRED$'):
            code.apply({},*adapters)
        self.assertTrue(all(not adapter.mock_calls for adapter in adapters))
        self.assertEqual(code.failure_report(ValueError('CODE_ONLY_REQUIRED'))['error_code'],'CODE_ONLY_REQUIRED')

    def test_exact_module_selection_rejects_other_sources_and_invalid_types(self):
        policy=shared.load('naver_preview_code_only')
        self.assertEqual(policy.code_module_name(PINS[1]),MODULE)
        self.assertEqual(policy.code_module_name(policy.REVIEWED_TRANSITION[1]),'naver_preview_code_upgrade')
        for source in ('0'*40, None, {}, [], True, PINS[1]+'PRIVATE'):
            with self.subTest(source_type=type(source).__name__), self.assertRaisesRegex(
                    ValueError,'^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                policy.code_module_name(source)

    def test_each_pin_mutation_refuses_before_host_action(self):
        fields=('OLD_COMMIT','TARGET_COMMIT','OLD_SOURCE_SHA256','TARGET_SOURCE_SHA256',
                'STORE_OLD','STORE_TARGET','EXPECTED_BASELINE')
        for index,name in enumerate(fields):
            for operation in ('prepare','apply'):
                code,policy=shared.load(MODULE),shared.load('naver_preview_code_only')
                if name.startswith('STORE_'):
                    code.STORE_SHA256[name[6:].lower()]='0'*64
                else:
                    setattr(code,name,'0'*len(PINS[index]))
                adapters=[Mock() for _ in range(4)]
                with self.subTest(pin=name,operation=operation), self.assertRaisesRegex(
                        ValueError,'^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                    getattr(policy,operation)({},*adapters,code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_v3_scope_is_exact_and_does_not_authorize_legacy_store_changes(self):
        policy=shared.load('naver_preview_code_only')
        for changes in (PATHS-{'naver_engine/morning.py'},PATHS|{'naver_engine/web.py'},
                        {'naver_engine/catalog_links.py','naver_engine/dashboard.py','naver_engine/inventory.py'}):
            code=shared.load(MODULE); code.CODE_PATHS=changes
            with self.subTest(paths=changes), self.assertRaisesRegex(ValueError,'CODE_ONLY_RELEASE_NOT_REVIEWED'):
                policy.require_review(code)
        code=shared.load(MODULE);code.TEST_PATHS=frozenset({'naver_engine/tests/test_web.py'})
        with self.assertRaisesRegex(ValueError,'CODE_ONLY_RELEASE_NOT_REVIEWED'):
            policy.require_review(code)
        old=shared.load('naver_preview_code_upgrade');old.CODE_PATHS|={'naver_engine/store.py'}
        with self.assertRaisesRegex(ValueError,'CODE_ONLY_RELEASE_NOT_REVIEWED'):
            policy.require_review(old)

    def test_archive_and_baseline_mismatch_refuse_before_any_host_action(self):
        for field in ('baseline','source_commit','source_tar_gz_sha256'):
            code,policy=shared.load(MODULE),shared.load('naver_preview_code_only')
            release=shared.load('naver_preview_release')
            good=package(code);bad=dict(good,**{field:'0'*len(good[field])})
            for operation in ('prepare','apply'):
                adapters=[Mock() for _ in range(3)]
                supplied=bad if operation=='prepare' else {'release':bad,'operation_id':'9'*32}
                with self.subTest(field=field,operation=operation), self.assertRaises(ValueError):
                    getattr(policy,operation)(supplied,adapters[0],release,adapters[1],adapters[2],code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_v3_code_only_success_and_rollback_never_touch_database_or_warmup(self):
        old=PINS[0]
        for failure in (None,'recreate','start','stop','probe'):
            with self.subTest(failure=failure), patch.object(shared.sqlite3,'connect',side_effect=AssertionError('DB forbidden')):
                result,commands,writes,restored,state=shared.ContractTest().scenario(
                    failure,code_only=True,code_module=MODULE)
            if failure is None:
                self.assertTrue(result['ok'])
                self.assertEqual(set(state.values()),{'b'*40})
                self.assertFalse(result['database_opened_by_controller'])
                self.assertFalse(result['source_warmup_performed'])
            else:
                self.assertEqual(str(result),'CODE_ONLY_FAILED_ROLLED_BACK')
                self.assertEqual(set(state.values()),{old})
                self.assertTrue(restored)
            self.assertFalse(any('exec' in args or 'run' in args for args in commands))
            self.assertFalse(any('nginx' in ' '.join(args) for args in commands))
            self.assertFalse(any(p.name=='bootstrap-request.json' or p.parent.name=='secrets' for p,_ in writes))

    def test_v3_unsafe_rollback_keeps_services_stopped(self):
        for failure in ('stop_writer_running','rollback_writer_running','rollback_recreate','bootstrap_changed'):
            with self.subTest(failure=failure):
                result,commands,_,_,_=shared.ContractTest().scenario(failure,code_only=True,code_module=MODULE)
                self.assertEqual(str(result),'CODE_ROLLBACK_FAILED')
                self.assertEqual(commands[-2:],[['/usr/bin/systemctl','stop','metainc-naver-relay.service'],
                                               ['/usr/bin/systemctl','stop','metainc-naver-engine.service']])


class V3StoreScopeTest(unittest.TestCase):
    def setUp(self):
        self.code=shared.load(MODULE)
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        self.old,self.new=(Path(folder.name).resolve()/name for name in ('old','new'))
        self.before=shared.StoreScopeTest.SOURCE
        self.after=self.before+b'\n# reviewed read projection\n'
        self.code.STORE_SHA256={'old':hashlib.sha256(self.before).hexdigest(),
                                'target':hashlib.sha256(self.after).hexdigest()}
        for root in (self.old,self.new):
            for name in ('compose.naver-engine.yml','compose.naver-relay.yml','deploy/naver-engine-backup.override.yml',
                         'Dockerfile.naver-engine','Dockerfile.naver-relay','backend/requirements.txt','naver_runtime/bootstrap.py',
                         'naver_engine/inventory.py','naver_engine/naver_read.py','naver_engine/morning.py'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                body=b'unchanged' if name not in PATHS else b'old' if root==self.old else b'new'
                path.write_bytes(body)
            (root/'naver_engine/store.py').write_bytes(self.before if root==self.old else self.after)
            for name in ('engine','relay'):
                body=('image: '+self.code.OLD_COMMIT).encode()
                (root/('preview-'+name+'.override.yml')).write_bytes(
                    body if root==self.old else self.code.target_override(body,name))
        self.upgrade=Mock()
        self.upgrade.read_file.side_effect=lambda path,**kwargs:Path(path).read_bytes()

    def test_four_runtime_file_changes_with_unchanged_schema11_are_accepted(self):
        self.code.compatible_source(self.old,self.new,self.upgrade)

    def test_repinning_cannot_authorize_schema_sql_revision_or_migration_drift(self):
        changes=(self.after.replace(b'SCHEMA_VERSION=11',b'SCHEMA_VERSION=12'),
                 self.after+b'\n_SCHEMA += ("CREATE TABLE unreviewed (id INTEGER)",)\n',
                 self.after.replace(b'source_wait_attempts',b'changed_attempts'),
                 self.after.replace(b'if column not in columns:',b'if column in columns:'))
        for source in changes:
            self.assertNotEqual(source,self.after)
            (self.new/'naver_engine/store.py').write_bytes(source)
            self.code.STORE_SHA256['target']=hashlib.sha256(source).hexdigest()
            with self.subTest(change=source[-50:]),self.assertRaisesRegex(ValueError,'CODE_SCHEMA_CHANGED'):
                self.code.compatible_source(self.old,self.new,self.upgrade)

    def test_every_file_outside_v3_scope_refuses_before_service_control(self):
        for name in ('naver_engine/web.py','naver_engine/catalog_links.py','naver_runtime/__main__.py',
                     'backend/app/naver_auto/scope.py','deploy/unapproved.conf'):
            path=self.new/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'new')
            with self.subTest(path=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
                self.code.compatible_source(self.old,self.new,self.upgrade)
            path.unlink()

    def test_missing_file_symlink_and_mode_drift_are_rejected(self):
        path=self.new/'naver_engine/morning.py'
        body=path.read_bytes();path.unlink()
        with self.assertRaisesRegex(ValueError,'CODE_SOURCE_REMOVED'):
            self.code.compatible_source(self.old,self.new,self.upgrade)
        path.symlink_to(self.old/'naver_engine/morning.py')
        with self.assertRaisesRegex(ValueError,'CODE_SOURCE_PATH'):
            self.code.compatible_source(self.old,self.new,self.upgrade)
        path.unlink();path.write_bytes(body);path.chmod(0o755)
        with self.assertRaisesRegex(ValueError,'CODE_SOURCE_MODE_CHANGED'):
            self.code.compatible_source(self.old,self.new,self.upgrade)


class V3WorkflowTest(unittest.TestCase):
    def scripts(self):
        return legacy_policy.CodeOnlyTest().workflow_scripts()

    def test_apply_encoder_selects_only_the_reviewed_release_with_existing_wire_bounds(self):
        encode,decode,_=shared.ContractTest().workflow_transport()
        script=self.scripts()[0]
        for name in (MODULE,'naver_preview_code_upgrade'):
            code=shared.load(name)
            with tempfile.TemporaryDirectory() as folder:
                env_file=Path(folder)/'env'
                inputs=dict(ad_prepare='preview-code-only-upgrade',ad_expected_baseline=json.dumps(
                    dict(release=package(code),operation_id='9'*32)))
                with patch.dict(os.environ,INPUTS_JSON=json.dumps(inputs),GITHUB_ENV=str(env_file)):
                    exec(compile(script,'<apply-encoder>','exec'),{})
                wire=env_file.read_text().split('=',1)[1].strip()
            bundle=decode(wire)
            self.assertEqual(bundle['code_source'],(Path(__file__).parents[1]/'tools'/(name+'.py')).read_text())
            self.assertLessEqual(len(wire),65536)
            self.assertLessEqual(len(json.dumps(bundle).encode()),196608)
            self.assertEqual(encode(bundle),wire)

    def test_prepare_encoder_selects_after_verified_download_and_uses_existing_remote_name(self):
        script=legacy_policy.CodeOnlyTest().prepare_encoder()
        downloader=shared.load('naver_preview_download')
        for name in (MODULE,'naver_preview_code_upgrade'):
            code=shared.load(name);fields=package(code)
            fields={key:value for key,value in fields.items() if key not in ('operation','run_id')}
            with tempfile.TemporaryDirectory() as folder:
                env_file=Path(folder)/'env'
                with patch.dict(sys.modules,naver_preview_download=downloader), \
                        patch.object(downloader,'download',return_value=fields) as download, \
                        patch.dict(os.environ,INPUTS_JSON=json.dumps(dict(ad_prepare='preview-code-only-prepare',
                            ad_expected_baseline=json.dumps({'source_commit':code.TARGET_COMMIT}))),RUN_ID='999999',GITHUB_ENV=str(env_file)):
                    exec(compile(script,'<prepare-encoder>','exec'),{})
                    download.assert_called_once()
                wire=env_file.read_text().split('=',1)[1].strip()
            raw=gzip.decompress(base64.b64decode(wire.split(':',1)[1]));bundle=json.loads(raw)
            self.assertEqual(bundle['code_source'],(Path(__file__).parents[1]/'tools'/(name+'.py')).read_text())
            self.assertLessEqual(len(raw),180000);self.assertLessEqual(len(wire),65536)
            remote_code=next(s for s in self.scripts() if "print('NAVER_PREVIEW_RELEASE=" in s)
            self.assertIn("types.ModuleType('approved_code')",remote_code)

    def test_unknown_source_and_wrong_archive_refuse_without_building_a_bundle(self):
        script=self.scripts()[0];code=shared.load(MODULE)
        for changed in ({'source_commit':'0'*40},{'source_tar_gz_sha256':'0'*64},{'baseline':'0'*64}):
            with tempfile.TemporaryDirectory() as folder:
                env_file=Path(folder)/'env'
                inputs=dict(ad_prepare='preview-code-only-upgrade',ad_expected_baseline=json.dumps(
                    dict(release=dict(package(code),**changed),operation_id='9'*32)))
                with patch.dict(os.environ,INPUTS_JSON=json.dumps(inputs),GITHUB_ENV=str(env_file)),self.assertRaises(ValueError):
                    exec(compile(script,'<refused-encoder>','exec'),{})
                self.assertFalse(env_file.exists())

    def test_unknown_prepare_source_refuses_before_download(self):
        script=legacy_policy.CodeOnlyTest().prepare_encoder()
        downloader=shared.load('naver_preview_download')
        for source in ('0'*40,None,'PRIVATE'):
            with patch.dict(sys.modules,naver_preview_download=downloader),patch.object(downloader,'download') as download, \
                    patch.dict(os.environ,INPUTS_JSON=json.dumps(dict(ad_prepare='preview-code-only-prepare',
                        ad_expected_baseline=json.dumps({'source_commit':source})))),redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as stopped:
                    exec(compile(script,'<prepare-refused>','exec'),{})
            self.assertEqual(stopped.exception.code,1);download.assert_not_called()
            self.assertEqual(output.getvalue(),'PREVIEW_ENCRYPTED_INPUT_REFUSED\n')


if __name__=='__main__':
    unittest.main()
