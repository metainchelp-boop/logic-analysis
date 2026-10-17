"""Offline P5/T5 exact four-file transition; no host or credential access."""
import ast
import base64
import copy
import hashlib
import importlib.util
import json
import lzma
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

TOOLS = Path(__file__).parents[1] / 'tools'


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / (name+'.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def pinned():
    p=load('naver_budget_draft_patch'); c=load('naver_preview_completion_release')
    p.TARGET_COMMIT='f'*40; p.TARGET_SOURCE_SHA256='e'*64
    p4=load('naver_inspection_continuity_patch'); p4.bind_base(c)
    p.TARGET_DELTA={name:(0o644,p4.TARGET_MANIFEST[name][1]+1,hashlib.sha256(name.encode()).hexdigest()) for name in p.CODE_PATHS}
    p.CI_PROOF=dict(source_commit=p.TARGET_COMMIT,tooling_head='d'*40,run_id='12345678901',receipt_sha256='b'*64)
    p.bind_base(c); return p,c


def package(p):
    return dict(operation='code-prepare',baseline=p.EXPECTED_BASELINE,source_commit=p.TARGET_COMMIT,
                source_tar_gz_sha256=p.TARGET_SOURCE_SHA256,ciphertext_sha256='d'*64,run_id='12345678901')


class ExactPinsTests(unittest.TestCase):
    def test_unpopulated_target_fails_before_adapter_access(self):
        p=load('naver_budget_draft_patch');p.TARGET_COMMIT=None
        for name in ('prepare','apply','rollback'):
            adapters=[Mock() for _ in range(4)]
            with self.subTest(name=name), self.assertRaisesRegex(ValueError,'^PATCH_NOT_PINNED$'):
                getattr(p,name)({},*adapters)
            self.assertTrue(all(not a.mock_calls for a in adapters))

    def test_exact_baseline_is_p4_and_only_four_existing_paths_change(self):
        p,c=pinned(); old=load('naver_inspection_continuity_patch');old.bind_base(c)
        self.assertEqual(p.OLD_MANIFEST,old.TARGET_MANIFEST)
        self.assertEqual(p.OLD_SOURCE_SHA256,old.TARGET_SOURCE_SHA256)
        self.assertEqual(p.OLD_COMMIT,'15f3a23c2255de98cba3670fce3b489309698e1f')
        self.assertEqual(p.BASE_PREPARE_RUN,'38247492655');self.assertEqual(p.BASE_APPLY_OPERATION,'66a3ac90ed9c4db6a38aee0cca626f42')
        self.assertEqual(len(p.TARGET_MANIFEST),163);self.assertEqual(set(p.TARGET_MANIFEST),set(p.OLD_MANIFEST));self.assertEqual(p.NEW_PATHS,frozenset())
        self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]},p.CODE_PATHS)
        self.assertEqual(p.TARGET_MANIFEST['naver_engine/store.py'],p.OLD_MANIFEST['naver_engine/store.py'])
        self.assertEqual({k for k in p.REPORT_ASSETS if p.REPORT_ASSETS[k]!=p.OLD_REPORT_ASSETS[k]},{'/naver/automation-ui.js'})
        self.assertEqual(p.REPORT_ASSETS['/naver/automation-ui.js'][2],p.OLD_REPORT_ASSETS['/naver/automation-ui.js'][2])

    def test_scope_store_assets_ci_and_base_tampering_are_closed(self):
        for mutation in ('scope','store','add','remove','asset','ci','old','bridge','manifest','same','unchanged','continuity'):
            p,_=pinned()
            if mutation=='scope':p.CODE_PATHS|={'naver_engine/store.py'}
            if mutation=='store':p.TARGET_MANIFEST['naver_engine/store.py']=(0o644,1,'a'*64)
            if mutation=='add':p.TARGET_MANIFEST['naver_engine/new.py']=(0o644,1,'a'*64)
            if mutation=='remove':p.TARGET_MANIFEST.pop('naver_engine/setup_checks.py')
            if mutation=='asset':p.REPORT_ASSETS['/naver/automation-ui.js']=(1,'a'*64,'text/plain')
            if mutation=='ci':p.CI_PROOF['source_commit']='0'*40
            if mutation=='old':p.OLD_SOURCE_SHA256='0'*64
            if mutation=='bridge':p.BASE_APPLY_OPERATION='0'*32
            if mutation=='manifest':p.OLD_MANIFEST['naver_engine/store.py']=(0o644,1,'a'*64)
            if mutation=='same':p.TARGET_COMMIT=p.OLD_COMMIT
            if mutation=='unchanged':p.TARGET_DELTA['naver_engine/setup_checks.py']=p.OLD_MANIFEST['naver_engine/setup_checks.py']
            if mutation=='continuity':p.CONTINUITY_DELTA['naver_engine/store.py']=(0o644,1,'a'*64)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):p.require_pins()

    def test_unsafe_path_is_rejected_without_read_or_hash(self):
        p,_=pinned()
        for name in ('naver_engine/store 2.py','HANDOVER.md','/tmp/x','naver_engine/../x','deploy/runtime.env'):
            self.assertFalse(p.safe_source_path(name))

    def test_historical_sources_cannot_be_target(self):
        for name in ('OLD_COMMIT','STRATEGY_COMMIT','FAA0_COMMIT','DADB_COMMIT','HISTORICAL_TARGET','BASE_PREVIOUS_COMMIT'):
            p,_=pinned();p.TARGET_COMMIT=getattr(p,name);p.CI_PROOF['source_commit']=p.TARGET_COMMIT
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'^PATCH_NOT_PINNED$'):p.require_pins()

    def test_unbound_static_pins_cannot_execute(self):
        p,_=pinned();p.BASE=None;p.require_pins();adapters=[Mock() for _ in range(4)]
        with self.assertRaisesRegex(ValueError,'^PATCH_NOT_PINNED$'):p.prepare(package(p),*adapters)
        self.assertTrue(all(not x.mock_calls for x in adapters))


class BaselineTests(unittest.TestCase):
    def fixture(self):
        p,c=pinned();secret=Path('/synthetic/secrets');files={str(secret/'runtime.env'):'a'*64,str(secret/'other'):'b'*64}
        r=SimpleNamespace(ROOT=Path('/synthetic/release'),unique=dict,SECRET_ROOT=secret,SECRET_OWNERS={'runtime.env':(0,0),'other':(0,0)})
        roles=[(p.HISTORICAL_TARGET,c.TARGET_SOURCE_SHA256,p.HISTORICAL_PREPARE_RUN,p.BASE_PREVIOUS_COMMIT,p.HISTORICAL_APPLY_OPERATION),
               (p.DADB_COMMIT,p.DADB_SOURCE_SHA256,p.DADB_PREPARE_RUN,p.HISTORICAL_TARGET,p.DADB_APPLY_OPERATION),
               (p.FAA0_COMMIT,p.FAA0_SOURCE_SHA256,p.FAA0_PREPARE_RUN,p.DADB_COMMIT,p.FAA0_APPLY_OPERATION),
               (p.STRATEGY_COMMIT,p.STRATEGY_SOURCE_SHA256,p.STRATEGY_PREPARE_RUN,p.FAA0_COMMIT,p.STRATEGY_APPLY_OPERATION),
               (p.OLD_COMMIT,p.OLD_SOURCE_SHA256,p.BASE_PREPARE_RUN,p.STRATEGY_COMMIT,p.BASE_APPLY_OPERATION)]
        receipts={};starts={}
        for commit,source,run,previous,operation in roles:
            receipts[commit]=dict(source_commit=commit,package=dict(source_tar_gz_sha256=source,run_id=run,baseline=p.EXPECTED_BASELINE),runtime_environment_preserved=True,config_operation_id=p.APPROVED_CONFIG_OPERATION_ID,runtime_flags_verified=True,inventory_enabled=True,execution_enabled=False,files=dict(files))
            starts[commit]=dict(ok=True,stage='internal_ready',source_commit=commit,previous_commit=previous,operation_id=operation,database_policy='preserve-in-place',database_schema=21,database_opened_by_controller=False,database_snapshot_verified=False,source_warmup_performed=False,rollback_requires_matching_database=False,runtime_flags_verified=True,execution_enabled=False,saved_export_companion_preserved=True)
        starts[p.HISTORICAL_TARGET].update(database_policy='paired-snapshot',database_opened_by_controller=True,database_snapshot_verified=True,source_status=dict(ok=True,schema=21,old_schema=11,old_tables=36,old_rows=389163,preserved_rows=True,migration_repeatable=True,network_calls=0,randomized_tables=sorted(c.RANDOMIZED_TABLES),randomized_tables_empty=True))
        receipts[c.OLD_COMMIT]={'source_commit':c.OLD_COMMIT}
        u=SimpleNamespace(manifest=Mock(side_effect=lambda _r,commit,**_:(Path('/synthetic/naver-'+commit),receipts[commit])),read_file=Mock(side_effect=lambda path,**_:json.dumps(starts[Path(path).name.removeprefix('preview-start-').removesuffix('.json')]).encode()))
        return p,c,r,u,receipts,starts,roles

    def test_exact_five_step_chain_and_current_15f_are_required(self):
        p,_,r,u,receipts,_,roles=self.fixture()
        self.assertEqual(p.base_success(r,u)[1],receipts[p.OLD_COMMIT])
        self.assertEqual([call.args[0].name for call in u.read_file.call_args_list],['preview-start-'+role[0]+'.json' for role in roles])

    def test_each_historical_source_run_previous_operation_off_and_config_is_bound(self):
        for index in range(5):
            for mutation in ('run','source','previous','operation','execution','schema','db','env','companion'):
                p,_,r,u,receipts,starts,roles=self.fixture();commit=roles[index][0]
                if mutation=='run':receipts[commit]['package']['run_id']='99999999999'
                if mutation=='source':receipts[commit]['package']['source_tar_gz_sha256']='0'*64
                if mutation=='previous':starts[commit]['previous_commit']='0'*40
                if mutation=='operation':starts[commit]['operation_id']='0'*32
                if mutation=='execution':starts[commit]['execution_enabled']=True
                if mutation=='schema':starts[commit]['database_schema']=22
                if mutation=='db':starts[commit]['database_opened_by_controller']=not starts[commit]['database_opened_by_controller']
                if mutation=='env':receipts[commit]['files'].pop(str(r.SECRET_ROOT/'runtime.env'))
                if mutation=='companion':receipts[commit]['runtime_environment_preserved']=False
                with self.subTest(index=index,mutation=mutation),self.assertRaises(ValueError):p.base_success(r,u)

    def test_current_env_must_equal_historical_without_output_or_write(self):
        p,c,r,u,receipts,_,_=self.fixture()
        files=[dict(path=str(r.SECRET_ROOT/name),content='synthetic-'+name) for name in r.SECRET_OWNERS]
        for receipt in receipts.values():
            if 'files' in receipt:receipt['files']={v['path']:hashlib.sha256(v['content'].encode()).hexdigest() for v in files}
        with patch.object(c,'preserve_approved_config',return_value=(files,('historical-proof',))):
            resolved,proof=p.preserve_approved_config(files,p.APPROVED_CONFIG_OPERATION_ID,receipts[p.OLD_COMMIT],r,u)
            self.assertEqual(resolved,files);self.assertEqual(proof[0],('historical-proof',))
            receipts[p.OLD_COMMIT]['files'][files[0]['path']]='0'*64
            with self.assertRaisesRegex(ValueError,'^PATCH_CONFIG$'):p.preserve_approved_config(files,p.APPROVED_CONFIG_OPERATION_ID,receipts[p.OLD_COMMIT],r,u)


# Preserve the separately tested lifecycle semantics using P5's exact pair.
spec=importlib.util.spec_from_file_location('historical_continuity_tests',Path(__file__).with_name('test_naver_inspection_continuity_transport.py'))
HISTORICAL=importlib.util.module_from_spec(spec);spec.loader.exec_module(HISTORICAL)

class LifecycleTests(HISTORICAL.LifecycleTests):
    def setUp(self):
        self.original=patch.object(HISTORICAL,'pinned',pinned);self.original.start();self.addCleanup(self.original.stop)

class ActualFlagHelpersTests(HISTORICAL.ActualFlagHelpersTests):
    def setUp(self):
        self.original=patch.object(HISTORICAL,'pinned',pinned);self.original.start();self.addCleanup(self.original.stop)


class TransportTests(unittest.TestCase):
    def test_unpopulated_transport_closes_before_source_read(self):
        t=load('naver_budget_draft_transport');t.SOURCE_SHA256=None
        with patch.object(Path,'read_bytes',side_effect=AssertionError('read')):
            with self.assertRaisesRegex(ValueError,'^PATCH_NOT_PINNED$'):t.bundle('preview-budget-draft-patch-prepare',{},TOOLS)

    def fixture(self):
        t=load('naver_budget_draft_transport');sources={key:'x=1\n' for key in t.SOURCE_FILES}
        t.SOURCE_SHA256={key:hashlib.sha256(value.encode()).hexdigest() for key,value in sources.items()};t.COMPACT_SHA256=dict(t.SOURCE_SHA256)
        return t,dict(version=1,operation='preview-budget-draft-patch-prepare',package={},sources=sources)

    def test_roundtrip_has_dedicated_closed_operations_and_ten_sources(self):
        t,value=self.fixture();self.assertEqual(len(t.SOURCE_FILES),10)
        self.assertEqual(set(t.FUNCTIONS),{'preview-budget-draft-patch-'+x for x in ('prepare','apply','rollback')})
        self.assertEqual(t.decode(t.encode(value)),value)
        for change in ({'operation':'preview-inspection-continuity-patch-prepare'},{'extra':True},{'version':True},{'sources':{}}):
            with self.subTest(change=change),self.assertRaises(ValueError):t.encode(dict(value,**change))

    def test_truncated_trailing_duplicate_or_oversize_data_is_rejected(self):
        t,value=self.fixture();wire=t.encode(value)
        for changed in (wire[:-3],wire+'aaaa',t.PREFIX+'x'*(t.MAX_WIRE+1),'legacy:'+wire):
            with self.assertRaises(ValueError):t.decode(changed)
        raw=b'{"version":1,"version":1}'
        with self.assertRaises(ValueError):t.decode(t.PREFIX+base64.b64encode(lzma.compress(raw)).decode())
        value['sources']['patch']='tampered'
        with self.assertRaisesRegex(ValueError,'^PATCH_SOURCE$'):t.encode(value)

    def test_compaction_preserves_all_ast_fields_and_string_literals(self):
        t=load('naver_budget_draft_transport');source='x = "# preserve"\n# discard\ndef f():\n    return "ok"\n'
        compact=t.compact(source);self.assertEqual(ast.dump(ast.parse(source)),ast.dump(ast.parse(compact)))
        self.assertIn('# preserve',compact)

    def test_controller_has_no_database_open_or_export_reinstall_dependency(self):
        p,_=pinned();source=(TOOLS/'naver_budget_draft_patch.py').read_text()
        self.assertNotIn('sqlite3.connect',source);self.assertNotIn('snapshot_to(',source);self.assertNotIn('restore_from(',source)
        self.assertEqual(p.OLD_SCHEMA,p.TARGET_SCHEMA);self.assertEqual(p.OLD_SCHEMA,21)
        t=load('naver_budget_draft_transport');self.assertEqual(t.MAX_WIRE,98304);self.assertEqual(t.MAX_JSON,393216)
        self.assertEqual(t.SOURCE_FILES['controller'],'naver_preview_completion_release.py')

    def test_failure_projection_never_outputs_exception_or_private_fields(self):
        p,_=pinned();p.STAGE='code_rollback';e=RuntimeError('PRIVATE runtime.env value')
        e.failure_details=dict(failed_stage='code_start',failed_error_code='RUNTIME_CONFIG_DRIFT',private='SECRET')
        result=p.failure_report(e);self.assertEqual(result['error_code'],'UNRECOGNIZED');self.assertEqual(result['failed_stage'],'code_start')
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('SECRET',json.dumps(result))

    def test_export_proxy_preserves_both_engine_mounts_and_never_reinstalls(self):
        t,_=self.fixture();p,_=pinned();h=SimpleNamespace(COMPANION='saved.yml',_prepared=Mock(return_value=(None,Path('/synthetic/staging'),None)),verify=Mock(return_value=True))
        binding=SimpleNamespace(h=h,receipt={'bound':True},command=Mock(),operation=lambda callback:callback(),install=Mock(),rollback=Mock())
        r=SimpleNamespace(compose=lambda path,name:['compose',str(path),name])
        proxy=t.ExportProxy(r,binding,p)
        for commit in (p.OLD_COMMIT,p.TARGET_COMMIT):
            self.assertEqual(proxy.compose(Path('/synthetic/naver-'+commit),'engine')[-2:],['-f','/synthetic/staging/saved.yml'])
        self.assertNotIn('-f',proxy.compose(Path('/synthetic/naver-'+'0'*40),'engine'))
        self.assertNotIn('-f',proxy.compose(Path('/synthetic/naver-'+p.TARGET_COMMIT),'relay'))
        proxy.verify_exports();binding.install.assert_not_called();binding.rollback.assert_not_called()


    def test_execute_transports_first_failure_across_pristine_reporter_module(self):
        t,v=self.fixture();v['operation']='preview-budget-draft-patch-apply';p,_=pinned();r=Mock();r.unique=lambda pairs:dict(pairs)
        base_receipt={'package':{'run_id':p.BASE_PREPARE_RUN}}
        historical_receipt={'package':{'run_id':p.HISTORICAL_PREPARE_RUN,'source_commit':p.HISTORICAL_TARGET}}
        binding=Mock();e=SimpleNamespace(Binding=Mock(return_value=binding))
        modules=dict(patch=p,release=r,host=SimpleNamespace(NativeHost=Mock(return_value=Mock())),
                     controller=Mock(),exports_binding=e,exports_helper=Mock(),lifecycle=Mock(),upgrade=Mock())
        error=RuntimeError('CODE_ONLY_FAILED_ROLLED_BACK')
        error.failure_details={'failed_stage':'code_start','failed_error_code':'RUNTIME_CONFIG_DRIFT','failed_error_kind':'ValueError'}
        def fail(*_):p.STAGE='code_rollback';raise error
        v['package']={'release':package(p),'operation_id':'a'*32}
        with patch.object(t,'modules',return_value=modules),patch.object(p,'base_success',return_value=(Path('/old'),base_receipt,b'proof')),patch.object(p,'historical_success',return_value=(Path('/historical'),historical_receipt,b'historical-proof')),patch.object(p,'apply',side_effect=fail):
            with self.assertRaises(RuntimeError):t.execute(v)
        reporter=load('naver_budget_draft_patch');report=reporter.failure_report(error)
        self.assertEqual(report['failed_stage'],'code_start')
        self.assertEqual(report['failed_error_code'],'RUNTIME_CONFIG_DRIFT')
        binding.install.assert_not_called();binding.rollback.assert_not_called()
        binding.load.assert_called_once_with(dict(historical_receipt['package'],operation='code-prepare'))


if __name__=='__main__':unittest.main()
