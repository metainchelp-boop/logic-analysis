"""P12 순수 code-only 경계. 합성 핀·가짜 호스트만 사용하며 운영 실행은 없다."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

STAGE=Path(__file__).resolve().parents[1]
TOOLS=STAGE/'tools'
OPS_TOOLS=(TOOLS if (TOOLS/'naver_preview_completion_release.py').is_file() else TOOLS.parents[2]/'naver-claude-reference-ops-20261011/backend/tools')
OPS=OPS_TOOLS.parent


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def empty_scope(p):
    return {name:dict(changed=(),added=(),removed=(),optional_abi={},imports_added=(),imports_removed=())
            for name in p.CODE_PATHS-p.NEW_PATHS if name.endswith('.py')}


def pinned():
    p=load(TOOLS/'naver_detail_ai_patch.py','p12_synthetic_core')
    base=load(OPS_TOOLS/'naver_preview_completion_release.py','p12_historical_base')
    p.TARGET_COMMIT=p.APPROVED_TARGET_COMMIT='b'*40
    p.TARGET_SOURCE_SHA256=p.APPROVED_TARGET_SOURCE_SHA256='e'*64
    p.TARGET_CANONICAL_SHA256=p.APPROVED_CANONICAL_SHA256='f'*64
    p.CI_PROOF=dict(source_commit=p.TARGET_COMMIT,tooling_head='d'*40,run_id='12345678901',receipt_sha256='f'*64)
    p.APPROVED_CI_PROOF=dict(p.CI_PROOF)
    p.TARGET_DELTA={name:(0o644,100,'d'*64) for name in p.CODE_PATHS};p.EXPECTED_TARGET_DELTA=dict(p.TARGET_DELTA)
    p.APPROVED_AST_SCOPE=empty_scope(p);p.EXPECTED_AST_SCOPE=empty_scope(p)
    p.bind_base(base);return p,base


def package(p):
    return dict(operation='code-prepare',baseline=p.EXPECTED_BASELINE,source_commit=p.TARGET_COMMIT,
        source_tar_gz_sha256=p.TARGET_SOURCE_SHA256,ciphertext_sha256='d'*64,run_id='12345678901')


class ScopeTests(unittest.TestCase):
    def test_all_unresolved_evidence_stops_before_io_or_adapters(self):
        for field in ('TARGET_COMMIT','TARGET_DELTA','TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','CI_PROOF','APPROVED_AST_SCOPE','EXPECTED_AST_SCOPE'):
            p,_=pinned();setattr(p,field,None)
            for method in ('prepare','apply','rollback'):
                adapters=[Mock() for _ in range(4)]
                with self.subTest(field=field,method=method),patch.object(Path,'read_bytes',side_effect=AssertionError('read')) as read,self.assertRaisesRegex(ValueError,'^DETAIL_AI_PINS_PENDING$'):
                    getattr(p,method)({},*adapters)
                read.assert_not_called();self.assertTrue(all(not value.mock_calls for value in adapters))

    def test_actual_fd_baseline_new_one_exact_ten_and_store_changes_are_explicit(self):
        p,_=pinned()
        self.assertEqual(p.OLD_COMMIT,'fd9132c07031cae7162fb8af2a5131a8b1aeaba0')
        self.assertEqual(p.BASE_PREPARE_RUN,'38338518726')
        self.assertEqual(p.BASE_APPLY_OPERATION,'0c867a2aed8d43d091b4c0be5e198c58')
        self.assertEqual(len(p.OLD_MANIFEST),163);self.assertEqual(len(p.TARGET_MANIFEST),164)
        self.assertEqual(set(p.TARGET_MANIFEST)-set(p.OLD_MANIFEST),{'naver_engine/setup_strategy_evidence.py'})
        self.assertEqual(len(p.CODE_PATHS),10)
        self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21))
        self.assertNotEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target'])
        self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]},p.CODE_PATHS-p.NEW_PATHS)

    def test_current_pending_slots_are_not_presented_as_success_evidence(self):
        fields=('TARGET_COMMIT','TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','CI_PROOF','TARGET_DELTA','APPROVED_AST_SCOPE')
        for configured in (False,True):
            p=pinned()[0] if configured else load(TOOLS/'naver_detail_ai_patch.py','p12_pending')
            if configured:p.require_bound_pins()
            with self.subTest(configured=configured),patch.multiple(p,**{name:None for name in fields}),patch.object(Path,'read_bytes',side_effect=AssertionError('read')) as read:
                for field in fields:self.assertIsNone(getattr(p,field),field)
                with self.assertRaisesRegex(ValueError,'^DETAIL_AI_PINS_PENDING$'):p.require_target_pins()
                for method in ('prepare','apply','rollback'):
                    adapters=[Mock() for _ in range(4)]
                    with self.assertRaisesRegex(ValueError,'^DETAIL_AI_PINS_PENDING$'):getattr(p,method)({},*adapters)
                    self.assertTrue(all(not value.mock_calls for value in adapters))
                read.assert_not_called()

    def test_closed_scope_and_paired_source_evidence_reject_mutations(self):
        for mutate in (lambda p:setattr(p,'CODE_PATHS',p.CODE_PATHS|{'naver_runtime/config.py'}),
                       lambda p:setattr(p,'NEW_PATHS',frozenset()),
                       lambda p:p.TARGET_DELTA.update({'naver_engine/store.py':p.OLD_MANIFEST['naver_engine/store.py']}),
                       lambda p:p.CI_PROOF.update(run_id='99999999999'),lambda p:setattr(p,'OLD_SOURCE_SHA256','0'*64),
                       lambda p:setattr(p,'BASE_APPLY_OPERATION','0'*32),lambda p:p.OLD_MANIFEST.update({'naver_engine/store.py':(0o644,1,'a'*64)}),
                       lambda p:p.TARGET_MANIFEST.update({'naver_engine/invented.py':(0o644,1,'a'*64)}),
                       lambda p:p.REPORT_ASSETS.update({'/naver/report-ui.js':(1,'a'*64,'text/plain')}),
                       lambda p:setattr(p,'ROLLBACK_COMMIT',p.PREFIX_COMMIT)):
            p,_=pinned();mutate(p)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):p.require_pins()

    def test_each_historical_delta_is_validated_before_it_can_be_masked(self):
        for key,field in (('naver_runtime/claude_provider.py','SUFFIX_DELTA'),('naver_runtime/claude_provider.py','PREFIX_DELTA'),
                          ('naver_engine/marketing_strategy.py','STRATEGY_DELTA'),('naver_engine/store.py','BINDING_DELTA')):
            p,_=pinned();getattr(p,field)[key]=(0o644,1,'0'*64)
            with self.assertRaisesRegex(ValueError,'^PATCH_SCOPE$'):p.require_pins()

    def test_no_database_open_or_forbidden_path_source_read(self):
        p,_=pinned();source=(TOOLS/'naver_detail_ai_patch.py').read_text()
        for word in ('sqlite3.connect','snapshot_to(','restore_from(','._migrate('):self.assertNotIn(word,source)
        for name in ('naver_engine/store 2.py','HANDOVER.md','deploy/runtime.env','naver_engine/../x','/tmp/x'):
            self.assertFalse(p.safe_source_path(name))

    def test_lifecycle_inverse_and_unreferenced_removals_preserve_all_active_guards(self):
        before=(OPS_TOOLS/'naver_appeal_suffix_patch.py').read_bytes();after=(TOOLS/'naver_detail_ai_patch.py').read_bytes()
        def functions(body):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(body).body if isinstance(n,ast.FunctionDef)}
        old,new=functions(before),functions(after)
        removed={'additive_class_contract','observation_store_contract','scheduled_reserve_contract'}
        self.assertEqual(set(old)-set(new),removed)
        for name in ('prepare','apply','rollback','compatible_inverse_source','compatible_code_scope','current_state','target_override','verify_running','target_engine_snapshot','runtime_flags','container_environment_flags','container_runtime_flags','stopped_writer','safe_source_path','preserve_approved_config'):
            self.assertEqual(old[name],new[name],name)
        # The closed operation table and all public dependency sources contain no dynamic/string reference to removed helpers.
        sources=[after,(TOOLS/'naver_detail_ai_transport.py').read_bytes()]
        dependencies=('naver_preview_completion_release.py','naver_erp_tunnel_service_install.py','naver_preview_release.py','naver_preview_lifecycle.py','naver_preview_upgrade.py','naver_completion_exports.py','naver_saved_exports.py','../naver_product_export.py','../naver_market_export.py')
        sources.extend((OPS_TOOLS/name).read_bytes() for name in dependencies)
        for body in sources:
            for node in ast.walk(ast.parse(body)):
                if isinstance(node,ast.Name):self.assertNotIn(node.id,removed)
                if isinstance(node,ast.Constant) and type(node.value)is str:self.assertNotIn(node.value,removed)

    def test_shared_historical_helper_is_exact_original_guard_after_static_name_substitution(self):
        old=ast.parse((OPS_TOOLS/'naver_appeal_suffix_patch.py').read_bytes())
        new=ast.parse((TOOLS/'naver_detail_ai_patch.py').read_bytes())
        helper=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='_receipt_step')
        params=('previous_success','commit','source_sha','prepare_run','previous_commit','operation_id')
        for name,values in {'strategy_success':('faa0_success','STRATEGY_COMMIT','STRATEGY_SOURCE_SHA256','STRATEGY_PREPARE_RUN','FAA0_COMMIT','STRATEGY_APPLY_OPERATION'),
                            'continuity_success':('strategy_success','CONTINUITY_COMMIT','CONTINUITY_SOURCE_SHA256','CONTINUITY_PREPARE_RUN','STRATEGY_COMMIT','CONTINUITY_APPLY_OPERATION'),
                            'budget_success':('continuity_success','BUDGET_COMMIT','BUDGET_SOURCE_SHA256','BUDGET_PREPARE_RUN','CONTINUITY_COMMIT','BUDGET_APPLY_OPERATION'),
                            'learning_success':('budget_success','LEARNING_COMMIT','LEARNING_SOURCE_SHA256','LEARNING_PREPARE_RUN','BUDGET_COMMIT','LEARNING_APPLY_OPERATION'),
                            'binding_success':('learning_success','BINDING_COMMIT','BINDING_SOURCE_SHA256','BINDING_PREPARE_RUN','LEARNING_COMMIT','BINDING_APPLY_OPERATION'),
                            'appeal_success':('binding_success','APPEAL_COMMIT','APPEAL_SOURCE_SHA256','APPEAL_PREPARE_RUN','BINDING_COMMIT','APPEAL_APPLY_OPERATION'),
                            'base_success':('appeal_success','OLD_COMMIT','OLD_SOURCE_SHA256','BASE_PREPARE_RUN','APPEAL_COMMIT','BASE_APPLY_OPERATION')}.items():
            node=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==name)
            class Normalize(ast.NodeTransformer):
                def visit_Name(self,n):
                    if n.id in values:return ast.copy_location(ast.Name(id=params[values.index(n.id)],ctx=n.ctx),n)
                    return n
            node=Normalize().visit(node);node.name='_receipt_step';node.args.args.extend(ast.arg(arg=k) for k in params)
            self.assertEqual(ast.dump(node,include_attributes=False),ast.dump(helper,include_attributes=False),name)

    def test_inverse_validates_forward_then_exact_reverse_inventory(self):
        p,_=pinned();old=Path('/synthetic/old');target=Path('/synthetic/target');u=Mock()
        with patch.object(p,'compatible_source') as forward,patch.object(p,'compatible_code_scope') as scope:
            p.compatible_inverse_source(target,old,u);forward.assert_called_once_with(old,target,u);scope.assert_called_once_with(target,old,u,inverse=True)
        with patch.object(p,'compatible_source',side_effect=ValueError('CODE_SCOPE_CHANGED')),patch.object(p,'compatible_code_scope') as scope:
            with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.compatible_inverse_source(target,old,u)
            scope.assert_not_called()


class PythonContractTests(unittest.TestCase):
    path='naver_engine/store.py'
    def fixture(self):
        p,_=pinned();p.APPROVED_AST_SCOPE[self.path]=dict(changed=('ManagedStorage.prepare',),added=('ManagedStorage.setup',),removed=(),optional_abi={},imports_added=(),imports_removed=())
        before=b'x=1\nclass ManagedStorage:\n def prepare(self,x):\n  return x\n def reserve(self,x):\n  return x\n'
        after=b'x=1\nclass ManagedStorage:\n def prepare(self,x):\n  return x+1\n def setup(self,x):\n  return x\n def reserve(self,x):\n  return x\n'
        return p,before,after

    def test_only_reviewed_method_addition_and_change_accept(self):
        p,before,after=self.fixture();p.python_contract(self.path,before,after)

    def test_unrelated_guard_body_class_header_import_assignment_and_signature_mutants_reject(self):
        p,before,after=self.fixture()
        for bad in (after.replace(b'x=1',b'x=2'),after.replace(b'class ManagedStorage:',b'class ManagedStorage(object):'),
                    after.replace(b'def reserve(self,x):\n  return x',b'def reserve(self,x):\n  return None'),
                    after.replace(b'def prepare(self,x)',b'def prepare(self,x=None)'),
                    after.replace(b'def prepare(self,x):',b'def prepare(self,x)->int:'),
                    after.replace(b' def prepare(self,x):',b' @staticmethod\n def prepare(self,x):'),after+b'\nimport os\n',
                    after.replace(b'def reserve(self,x):\n  return x\n',b''),after+b'\ndef forbidden():pass\n'):
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.python_contract(self.path,before,bad)

    def test_optional_none_only_and_exact_literal_import_scopes(self):
        p,_=pinned();name='naver_engine/marketing_strategy.py'
        before=b'def generate(payload,*,provider=None):\n return payload\n'
        after=b'from . import setup_strategy_evidence as SE\ndef generate(payload,*,provider=None,setup_context=None,setup_labels=None):\n return SE.canonical(payload)\n'
        p.APPROVED_AST_SCOPE[name]=dict(changed=('generate',),added=(),removed=(),optional_abi={'generate':('setup_context','setup_labels')},imports_added=('from . import setup_strategy_evidence as SE',),imports_removed=())
        p.python_contract(name,before,after)
        for bad in (after.replace(b'setup_context=None',b'setup_context={}'),after.replace(b'provider=None',b'provider=True'),
                    after.replace(b' as SE',b' as OTHER'),b'from . import setup_strategy_evidence as SE\n'+after,
                    after.replace(b'setup_labels=None',b'setup_labels=None,extra=None')):
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.python_contract(name,before,bad)

    def test_only_reviewed_private_provenance_allows_one_trailing_positional_none(self):
        p,_=pinned();name='naver_engine/marketing_strategy.py'
        p.APPROVED_AST_SCOPE[name]=dict(changed=('_with_learning_provenance',),added=(),removed=(),optional_abi={'_with_learning_provenance':('setup_context',)},imports_added=(),imports_removed=())
        before=b'def _with_learning_provenance(result,context,funnel_context=None):\n return result\n'
        after=b'def _with_learning_provenance(result,context,funnel_context=None,setup_context=None):\n return context\n'
        p.python_contract(name,before,after)
        for bad in (after.replace(b'setup_context=None',b'setup_context=True'),after.replace(b'setup_context=None',b'setup_labels=None'),
                    after.replace(b'funnel_context=None',b'funnel_context=True'),after.replace(b'setup_context=None',b'setup_context=None,raw=None')):
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.python_contract(name,before,bad)
        p.APPROVED_AST_SCOPE[name]=dict(changed=('generate',),added=(),removed=(),optional_abi={'generate':('setup_context',)},imports_added=(),imports_removed=())
        with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.python_contract(name,before.replace(b'_with_learning_provenance',b'generate'),after.replace(b'_with_learning_provenance',b'generate'))

    def test_scope_shape_removed_class_scope_and_unauthorized_optional_arguments_reject(self):
        for mutate in (lambda v:v.update(removed=('x',)),lambda v:v.update(extra=True),lambda v:v.update(changed=['x']),
                       lambda v:v.update(optional_abi={'x':('raw',)}),lambda v:v.update(imports_added=('x=1',))):
            p,_=pinned();value=p.APPROVED_AST_SCOPE[self.path];mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):p.validate_ast_scope(p.APPROVED_AST_SCOPE)
        p,before,after=self.fixture();p.APPROVED_AST_SCOPE[self.path]['changed']=('ManagedStorage',)
        with self.assertRaises(ValueError):p.python_contract(self.path,before,after)

    def test_schema_and_migration_are_unchanged_even_with_approved_store_methods(self):
        p,_=pinned();before=b'SCHEMA_VERSION=21\n_SCHEMA=("CREATE TABLE x(a)",)\n_REVISION_COLUMNS={}\ndef _migrate():\n return None\nclass ManagedStorage:\n def prepare(self,x):\n  return x\n'
        after=before.replace(b'return x',b'return x+1')
        p.APPROVED_AST_SCOPE[self.path].update(changed=('ManagedStorage.prepare',))
        p.STORE_SHA256={'old':hashlib.sha256(before).hexdigest(),'target':hashlib.sha256(after).hexdigest()}
        p.migration_contract(before,after)
        for bad in (after.replace(b'SCHEMA_VERSION=21',b'SCHEMA_VERSION=22'),after.replace(b'CREATE TABLE x(a)',b'CREATE TABLE x(a,b)'),after.replace(b'return None',b'return True')):
            p.STORE_SHA256['target']=hashlib.sha256(bad).hexdigest()
            with self.assertRaisesRegex(ValueError,'^PATCH_SCHEMA$'):p.migration_contract(before,bad)

    def test_job_identity_and_public_clean_contract_are_preserved(self):
        p,_=pinned();job=b'def clean(x):\n return x\ndef public(x):\n return x\ndef identity(x):\n return x\n'
        p.learning_job_contract(job,job)
        for name in (b'clean',b'public',b'identity'):
            with self.assertRaisesRegex(ValueError,'^PATCH_SCHEMA$'):p.learning_job_contract(job,job.replace(b'def '+name+b'(x):\n return x',b'def '+name+b'(x):\n return None'))


class BaselineChainTests(unittest.TestCase):
    def fixture(self):
        p,c=pinned();secret=Path('/synthetic/secrets');files={str(secret/'runtime.env'):'a'*64,str(secret/'other'):'b'*64}
        r=SimpleNamespace(ROOT=Path('/synthetic/release'),unique=dict,SECRET_ROOT=secret,SECRET_OWNERS={'runtime.env':(0,0),'other':(0,0)})
        roles=[(p.HISTORICAL_TARGET,c.TARGET_SOURCE_SHA256,p.HISTORICAL_PREPARE_RUN,p.BASE_PREVIOUS_COMMIT,p.HISTORICAL_APPLY_OPERATION),
            (p.DADB_COMMIT,p.DADB_SOURCE_SHA256,p.DADB_PREPARE_RUN,p.HISTORICAL_TARGET,p.DADB_APPLY_OPERATION),
            (p.FAA0_COMMIT,p.FAA0_SOURCE_SHA256,p.FAA0_PREPARE_RUN,p.DADB_COMMIT,p.FAA0_APPLY_OPERATION),
            (p.STRATEGY_COMMIT,p.STRATEGY_SOURCE_SHA256,p.STRATEGY_PREPARE_RUN,p.FAA0_COMMIT,p.STRATEGY_APPLY_OPERATION),
            (p.CONTINUITY_COMMIT,p.CONTINUITY_SOURCE_SHA256,p.CONTINUITY_PREPARE_RUN,p.STRATEGY_COMMIT,p.CONTINUITY_APPLY_OPERATION),
            (p.BUDGET_COMMIT,p.BUDGET_SOURCE_SHA256,p.BUDGET_PREPARE_RUN,p.CONTINUITY_COMMIT,p.BUDGET_APPLY_OPERATION),
            (p.LEARNING_COMMIT,p.LEARNING_SOURCE_SHA256,p.LEARNING_PREPARE_RUN,p.BUDGET_COMMIT,p.LEARNING_APPLY_OPERATION),
            (p.BINDING_COMMIT,p.BINDING_SOURCE_SHA256,p.BINDING_PREPARE_RUN,p.LEARNING_COMMIT,p.BINDING_APPLY_OPERATION),
            (p.APPEAL_COMMIT,p.APPEAL_SOURCE_SHA256,p.APPEAL_PREPARE_RUN,p.BINDING_COMMIT,p.APPEAL_APPLY_OPERATION),
            (p.PREFIX_COMMIT,p.PREFIX_SOURCE_SHA256,p.PREFIX_PREPARE_RUN,p.APPEAL_COMMIT,p.PREFIX_APPLY_OPERATION),
            (p.OLD_COMMIT,p.OLD_SOURCE_SHA256,p.BASE_PREPARE_RUN,p.PREFIX_COMMIT,p.BASE_APPLY_OPERATION)]
        receipts={};starts={}
        for commit,source,run,previous,operation in roles:
            receipts[commit]=dict(source_commit=commit,package=dict(source_tar_gz_sha256=source,run_id=run,baseline=p.EXPECTED_BASELINE),runtime_environment_preserved=True,config_operation_id=p.APPROVED_CONFIG_OPERATION_ID,runtime_flags_verified=True,inventory_enabled=True,execution_enabled=False,files=dict(files))
            starts[commit]=dict(ok=True,stage='internal_ready',source_commit=commit,previous_commit=previous,operation_id=operation,database_policy='preserve-in-place',database_schema=21,database_opened_by_controller=False,database_snapshot_verified=False,source_warmup_performed=False,rollback_requires_matching_database=False,runtime_flags_verified=True,execution_enabled=False,saved_export_companion_preserved=True)
        starts[p.HISTORICAL_TARGET].update(database_policy='paired-snapshot',database_opened_by_controller=True,database_snapshot_verified=True,source_status=dict(ok=True,schema=21,old_schema=11,old_tables=36,old_rows=389163,preserved_rows=True,migration_repeatable=True,network_calls=0,randomized_tables=sorted(c.RANDOMIZED_TABLES),randomized_tables_empty=True))
        receipts[c.OLD_COMMIT]={'source_commit':c.OLD_COMMIT}
        u=SimpleNamespace(manifest=Mock(side_effect=lambda _r,commit,**_:(Path('/synthetic/naver-'+commit),receipts[commit])),read_file=Mock(side_effect=lambda path,**_:json.dumps(starts[Path(path).name.removeprefix('preview-start-').removesuffix('.json')]).encode()))
        return p,c,r,u,receipts,starts,roles

    def test_all_eleven_historical_proofs_and_exact_read_order(self):
        p,c,r,u,receipts,starts,roles=self.fixture();self.assertEqual(p.base_success(r,u)[1],receipts[p.OLD_COMMIT])
        self.assertEqual([call.args[0].name for call in u.read_file.call_args_list],['preview-start-'+row[0]+'.json' for row in roles])

    def test_every_historical_source_run_previous_operation_config_schema_and_off_guard(self):
        for index in range(11):
            for mutation in ('run','source','previous','operation','execution','schema','db','env','companion','null','missing'):
                p,c,r,u,receipts,starts,roles=self.fixture();commit=roles[index][0]
                if mutation=='run':receipts[commit]['package']['run_id']='99999999999'
                elif mutation=='source':receipts[commit]['package']['source_tar_gz_sha256']='0'*64
                elif mutation=='previous':starts[commit]['previous_commit']='0'*40
                elif mutation=='operation':starts[commit]['operation_id']='0'*32
                elif mutation=='execution':starts[commit]['execution_enabled']=True
                elif mutation=='schema':starts[commit]['database_schema']=True
                elif mutation=='db':starts[commit]['database_opened_by_controller']=not starts[commit]['database_opened_by_controller']
                elif mutation=='env':receipts[commit]['files'].pop(str(r.SECRET_ROOT/'runtime.env'))
                elif mutation=='companion':receipts[commit]['runtime_environment_preserved']=False
                elif mutation=='null':starts[commit]['runtime_flags_verified']=None
                else:starts[commit].pop('runtime_flags_verified')
                with self.subTest(index=index,mutation=mutation),self.assertRaises((ValueError,KeyError)):p.base_success(r,u)

    def test_current_config_is_same_historical_bytes_and_never_writes(self):
        p,c,r,u,receipts,starts,roles=self.fixture();files=[dict(path=str(r.SECRET_ROOT/name),content='synthetic-'+name) for name in r.SECRET_OWNERS]
        for value in receipts.values():
            if 'files' in value:value['files']={v['path']:hashlib.sha256(v['content'].encode()).hexdigest() for v in files}
        with patch.object(c,'preserve_approved_config',return_value=(files,('historical-proof',))):
            self.assertEqual(p.preserve_approved_config(files,p.APPROVED_CONFIG_OPERATION_ID,receipts[p.OLD_COMMIT],r,u)[0],files)
            receipts[p.OLD_COMMIT]['files'][files[0]['path']]='0'*64
            with self.assertRaisesRegex(ValueError,'^PATCH_CONFIG$'):p.preserve_approved_config(files,p.APPROVED_CONFIG_OPERATION_ID,receipts[p.OLD_COMMIT],r,u)


# Prior synthetic same-image/service/rollback/runtime guards remain unchanged.
H=load(OPS/'tests/test_naver_inspection_continuity_transport.py','p12_historical_tests')
class LifecycleTest(H.LifecycleTests):
    def setUp(self):
        binding=patch.object(H,'pinned',pinned);binding.start();self.addCleanup(binding.stop)
class RuntimeFlagTest(H.ActualFlagHelpersTests):
    def setUp(self):
        binding=patch.object(H,'pinned',pinned);binding.start();self.addCleanup(binding.stop)

if __name__=='__main__':unittest.main()
