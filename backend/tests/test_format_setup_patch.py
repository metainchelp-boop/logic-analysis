"""P19 d599→후보 진단 세 파일 code-only 경계. 합성 핀과 가짜 호스트만 사용하며 운영 실행은 없다."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

STAGE=Path(__file__).resolve().parents[1]
TOOLS=STAGE/'tools'
OPS_TOOLS=(TOOLS if (TOOLS/'naver_preview_completion_release.py').is_file() else next(parent/'naver-claude-reference-ops-20261011/backend/tools' for parent in TOOLS.parents if (parent/'naver-claude-reference-ops-20261011/backend/tools/naver_preview_completion_release.py').is_file()))
OPS=OPS_TOOLS.parent


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def empty_scope(p):
    return {name:dict(changed=(),added=(),removed=(),optional_abi={},imports_added=(),imports_removed=())
            for name in p.CODE_PATHS-p.NEW_PATHS if name.endswith('.py')}


def pinned():
    p=load(TOOLS/'naver_format_setup_patch.py','p15_synthetic_core')
    base=load(OPS_TOOLS/'naver_preview_completion_release.py','p15_historical_base')
    p.CODE_PATHS=p.EXPECTED_CODE_PATHS=frozenset({'naver_engine/inspection_reads.py','naver_runtime/report_output_schema.py','naver_engine/marketing_strategy.py'})
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
        for field in ('TARGET_COMMIT','TARGET_DELTA','TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','CI_PROOF','APPROVED_AST_SCOPE','EXPECTED_AST_SCOPE','APPROVED_TARGET_COMMIT','APPROVED_TARGET_SOURCE_SHA256','APPROVED_CI_PROOF','APPROVED_CANONICAL_SHA256','EXPECTED_TARGET_DELTA'):
            p,_=pinned();setattr(p,field,None)
            for method in ('prepare','apply','rollback'):
                adapters=[Mock() for _ in range(4)]
                with self.subTest(field=field,method=method),patch.object(Path,'read_bytes',side_effect=AssertionError('read')) as read,self.assertRaisesRegex(ValueError,'^DETAIL_AI_PINS_PENDING$'):
                    getattr(p,method)({},*adapters)
                read.assert_not_called();self.assertTrue(all(not value.mock_calls for value in adapters))

    def test_actual_be97_baseline_exact_six_new_one_and_store_bytes_preserved(self):
        p,_=pinned()
        self.assertEqual(p.OLD_COMMIT,'07890f1da91f09aca87f2b093852f46778971ba1')
        self.assertEqual(p.BASE_PREPARE_RUN,'38484358780')
        self.assertEqual(p.BASE_APPLY_OPERATION,'fd9ff1f12a104778bc24ee2b92649ea9')
        self.assertEqual(len(p.OLD_MANIFEST),165);self.assertEqual(len(p.TARGET_MANIFEST),165)
        self.assertEqual(set(p.TARGET_MANIFEST)-set(p.OLD_MANIFEST),set())
        self.assertEqual(len(p.CODE_PATHS),3)
        self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21))
        self.assertEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target'])
        self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]},p.CODE_PATHS-p.NEW_PATHS)

    def test_current_pending_slots_are_not_presented_as_success_evidence(self):
        fields=('TARGET_COMMIT','TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','CI_PROOF','TARGET_DELTA','APPROVED_AST_SCOPE')
        for configured in (False,True):
            p=pinned()[0] if configured else load(TOOLS/'naver_format_setup_patch.py','p15_pending')
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
                       lambda p:setattr(p,'NEW_PATHS',frozenset({'unapproved.py'})),
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

    def test_new_38_manifest_step_cannot_be_masked_by_target_delta(self):
        for name in pinned()[0].DETAIL_DELTA:
            p,_=pinned();p.DETAIL_DELTA[name]=(0o644,1,'0'*64)
            with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()

    def test_be97_historical_delta_source_run_operation_and_rollback_cannot_be_masked(self):
        for name in pinned()[0].WRITER_RECOVERY_DELTA:
            p,_=pinned();p.WRITER_RECOVERY_DELTA[name]=(0o644,1,'0'*64)
            with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
        for field,bad in (('OLD_COMMIT','0'*40),('OLD_SOURCE_SHA256','0'*64),('BASE_PREPARE_RUN','99999999999'),('BASE_APPLY_OPERATION','0'*32),('ROLLBACK_COMMIT','7d9b8e05ff847fabc74fdc6f1cd01fd63d77e06b')):
            p,_=pinned();setattr(p,field,bad)
            with self.subTest(field=field),self.assertRaises(ValueError):p.require_pins()


    def test_8876_historical_delta_and_be97_identity_cannot_be_masked(self):
        for name in pinned()[0].PROVIDER_DIAGNOSTICS_DELTA:
            p,_=pinned();p.PROVIDER_DIAGNOSTICS_DELTA[name]=(0o644,1,'0'*64)
            with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
        for field,bad in (('WRITER_RECOVERY_COMMIT','0'*40),('WRITER_RECOVERY_SOURCE_SHA256','0'*64),('WRITER_RECOVERY_PREPARE_RUN','99999999999'),('WRITER_RECOVERY_APPLY_OPERATION','0'*32)):
            p,_=pinned();setattr(p,field,bad)
            with self.subTest(field=field),self.assertRaises(ValueError):p.require_pins()

    def test_historical_fd_source_run_and_operation_remain_fixed(self):
        for field,bad in (('SUFFIX_COMMIT','0'*40),('SUFFIX_SOURCE_SHA256','0'*64),
                          ('SUFFIX_PREPARE_RUN','99999999999'),('SUFFIX_APPLY_OPERATION','0'*32)):
            p,_=pinned();setattr(p,field,bad)
            with self.subTest(field=field),self.assertRaises(ValueError):p.require_pins()

    def test_shared_expected_manifest_is_exact_full_historical_expansion(self):
        p,_=pinned()
        expected={**p.BASE.TARGET_MANIFEST,**p.DADB_DELTA,'naver_runtime/claude_provider.py':p.FAA0_PROVIDER_ROW,
            **p.STRATEGY_DELTA,**p.CONTINUITY_DELTA,**p.BUDGET_DELTA,**p.LEARNING_DELTA,
            **p.BINDING_DELTA,**p.APPEAL_DELTA,**p.PREFIX_DELTA,**p.SUFFIX_DELTA,**p.DETAIL_DELTA,**p.REPORT_DEFECT_DELTA,**p.WRITER_RECOVERY_DELTA,**p.PROVIDER_DIAGNOSTICS_DELTA,**p.CONTEXT_REUSE_DELTA,**p.E_DELTA}
        self.assertEqual(p.OLD_MANIFEST,expected)
        self.assertEqual(p.manifest_digest(expected),p.E_MANIFEST)
        source=ast.parse((TOOLS/'naver_format_setup_patch.py').read_bytes())
        method=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='require_pins')
        assignments=[n for n in ast.walk(method) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='expected_old' for t in n.targets)]
        self.assertEqual(len(assignments),1);self.assertIsInstance(assignments[0].value,ast.Name)
        self.assertEqual(assignments[0].value.id,'chain')
        self.assertFalse(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name)
            and n.func.value.id in ('chain','expected_old') for n in ast.walk(method)))

    def test_no_database_open_or_forbidden_path_source_read(self):
        p,_=pinned();source=(TOOLS/'naver_format_setup_patch.py').read_text()
        for word in ('sqlite3.connect','snapshot_to(','restore_from(','._migrate('):self.assertNotIn(word,source)
        for name in ('naver_engine/store 2.py','HANDOVER.md','deploy/runtime.env','naver_engine/../x','/tmp/x'):
            self.assertFalse(p.safe_source_path(name))

    def test_lifecycle_inverse_and_unreferenced_removals_preserve_all_active_guards(self):
        before=(OPS_TOOLS/'naver_report_defect_patch.py').read_bytes();after=(TOOLS/'naver_format_setup_patch.py').read_bytes()
        def functions(body):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(body).body if isinstance(n,ast.FunctionDef)}
        # Only the authorized receipts directory policy bug differs from the historical lifecycle.
        historical=ast.parse(before)
        rollback=next(node for node in historical.body if isinstance(node,ast.FunctionDef) and node.name=='rollback')
        expected=ast.parse("for parent in (lifecycle.UNIT_DIR, lifecycle.TMPFILES.parent, release.ROOT / 'receipts'):\n release.trusted_dir(parent)\n").body[0]
        matches=[(index,node)for index,node in enumerate(rollback.body)if ast.dump(node,include_attributes=False)==ast.dump(expected,include_attributes=False)]
        self.assertEqual(len(matches),1)
        index,_=matches[0]
        rollback.body[index:index+1]=ast.parse("for parent in (lifecycle.UNIT_DIR, lifecycle.TMPFILES.parent):\n release.trusted_dir(parent)\nrelease.trusted_dir(release.ROOT / 'receipts', mode=0o700)\n").body
        old,new=functions(ast.unparse(historical)),functions(after)
        removed=set()
        self.assertEqual(set(old)-set(new),removed)
        for name in ('prepare','apply','rollback','compatible_inverse_source','compatible_code_scope','current_state','target_override','verify_running','target_engine_snapshot','runtime_flags','container_environment_flags','container_runtime_flags','stopped_writer','safe_source_path','preserve_approved_config'):
            self.assertEqual(old[name],new[name],name)
        # The closed operation table and all public dependency sources contain no dynamic/string reference to removed helpers.
        sources=[after,(TOOLS/'naver_format_setup_transport.py').read_bytes()]
        dependencies=('naver_preview_completion_release.py','naver_erp_tunnel_service_install.py','naver_preview_release.py','naver_preview_lifecycle.py','naver_preview_upgrade.py','naver_completion_exports.py','naver_saved_exports.py','../naver_product_export.py','../naver_market_export.py')
        sources.extend((OPS_TOOLS/name).read_bytes() for name in dependencies)
        for body in sources:
            for node in ast.walk(ast.parse(body)):
                if isinstance(node,ast.Name):self.assertNotIn(node.id,removed)
                if isinstance(node,ast.Constant) and type(node.value)is str:self.assertNotIn(node.value,removed)

    def test_shared_historical_helper_and_existing_wrappers_remain_exact(self):
        old=ast.parse((OPS_TOOLS/'naver_report_defect_patch.py').read_bytes())
        new=ast.parse((TOOLS/'naver_format_setup_patch.py').read_bytes())
        functions=lambda tree:{n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,ast.FunctionDef)}
        a,b=functions(old),functions(new)
        for name in ('_receipt_step','historical_success','dadb_success','faa0_success','strategy_success',
                     'continuity_success','budget_success','learning_success','binding_success','appeal_success','prefix_success'):
            self.assertEqual(a[name],b[name],name)
        suffix=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='detail_success')
        base=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='base_success')
        class OriginalNames(ast.NodeTransformer):
            def visit_Name(self,n):
                names={'DETAIL_COMMIT':'OLD_COMMIT','DETAIL_SOURCE_SHA256':'OLD_SOURCE_SHA256',
                       'DETAIL_PREPARE_RUN':'BASE_PREPARE_RUN','DETAIL_APPLY_OPERATION':'BASE_APPLY_OPERATION'}
                return ast.copy_location(ast.Name(id=names[n.id],ctx=n.ctx),n) if n.id in names else n
        suffix=OriginalNames().visit(suffix);suffix.name='base_success'
        self.assertEqual(ast.dump(base,include_attributes=False),ast.dump(suffix,include_attributes=False))

    def test_inverse_validates_forward_then_exact_reverse_inventory(self):
        p,_=pinned();old=Path('/synthetic/old');target=Path('/synthetic/target');u=Mock()
        with patch.object(p,'compatible_source') as forward,patch.object(p,'compatible_code_scope') as scope:
            p.compatible_inverse_source(target,old,u);forward.assert_called_once_with(old,target,u);scope.assert_called_once_with(target,old,u,inverse=True)
        with patch.object(p,'compatible_source',side_effect=ValueError('CODE_SCOPE_CHANGED')),patch.object(p,'compatible_code_scope') as scope:
            with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.compatible_inverse_source(target,old,u)
            scope.assert_not_called()


class PythonContractTests(unittest.TestCase):
    path='naver_runtime/report_output_schema.py'
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

    def test_new_scope_does_not_grant_unapproved_optional_arguments(self):
        p,_=pinned();name='naver_runtime/report_output_schema.py'
        before=b'def generated(context):\n return context\n'
        for after in (b'def generated(context,*,finalization=None):\n return context\n',
                      b'def generated(context,*,finalization={}):\n return context\n',
                      b'def generated(context,*,raw=None):\n return context\n'):
            p.APPROVED_AST_SCOPE[name]=dict(changed=('generated',),added=(),removed=(),
                optional_abi={},imports_added=(),imports_removed=())
            with self.subTest(after=after),self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):
                p.python_contract(name,before,after)
        p.APPROVED_AST_SCOPE[name]['optional_abi']={'generated':('finalization',)}
        with self.assertRaises(ValueError):p.validate_ast_scope(p.APPROVED_AST_SCOPE)
        p.APPROVED_AST_SCOPE['naver_engine/web.py']=p.APPROVED_AST_SCOPE[name]
        with self.assertRaises(ValueError):p.validate_ast_scope(p.APPROVED_AST_SCOPE)

    def test_scope_shape_removed_class_scope_and_unauthorized_optional_arguments_reject(self):
        for mutate in (lambda v:v.update(removed=('x',)),lambda v:v.update(extra=True),lambda v:v.update(changed=['x']),
                       lambda v:v.update(optional_abi={'x':('raw',)}),lambda v:v.update(imports_added=('x=1',))):
            p,_=pinned();value=p.APPROVED_AST_SCOPE[self.path];mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):p.validate_ast_scope(p.APPROVED_AST_SCOPE)
        p,before,after=self.fixture();p.APPROVED_AST_SCOPE[self.path]['changed']=('ManagedStorage',)
        with self.assertRaises(ValueError):p.python_contract(self.path,before,after)

    def test_unchanged_store_bytes_and_schema_are_required_outside_code_scope(self):
        p,_=pinned()
        before=b'SCHEMA_VERSION=21\n_SCHEMA=("CREATE TABLE x(a)",)\n_REVISION_COLUMNS={}\ndef _migrate():\n return None\n'
        p.STORE_SHA256={'old':hashlib.sha256(before).hexdigest(),'target':hashlib.sha256(before).hexdigest()}
        p.migration_contract(before,before)
        for bad in (before+b' ',before.replace(b'CREATE TABLE x(a)',b'CREATE TABLE x(b)'),before.replace(b'SCHEMA_VERSION=21',b'SCHEMA_VERSION=22')):
            with self.assertRaisesRegex(ValueError,'^PATCH_STORE$'):p.migration_contract(before,bad)
        for bad,code in ((before+b' ','PATCH_STORE'),(before.replace(b'SCHEMA_VERSION=21',b'SCHEMA_VERSION=22'),'PATCH_SCHEMA')):
            p.STORE_SHA256['target']=hashlib.sha256(bad).hexdigest()
            with self.assertRaisesRegex(ValueError,'^'+code+'$'):p.migration_contract(before,bad)

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
            (p.SUFFIX_COMMIT,p.SUFFIX_SOURCE_SHA256,p.SUFFIX_PREPARE_RUN,p.PREFIX_COMMIT,p.SUFFIX_APPLY_OPERATION),
            (p.DETAIL_COMMIT,p.DETAIL_SOURCE_SHA256,p.DETAIL_PREPARE_RUN,p.SUFFIX_COMMIT,p.DETAIL_APPLY_OPERATION),
            (p.REPORT_DEFECT_COMMIT,p.REPORT_DEFECT_SOURCE_SHA256,p.REPORT_DEFECT_PREPARE_RUN,p.DETAIL_COMMIT,p.REPORT_DEFECT_APPLY_OPERATION),
            (p.WRITER_RECOVERY_COMMIT,p.WRITER_RECOVERY_SOURCE_SHA256,p.WRITER_RECOVERY_PREPARE_RUN,p.REPORT_DEFECT_COMMIT,p.WRITER_RECOVERY_APPLY_OPERATION),
            (p.PROVIDER_DIAGNOSTICS_COMMIT,p.PROVIDER_DIAGNOSTICS_SOURCE_SHA256,p.PROVIDER_DIAGNOSTICS_PREPARE_RUN,p.WRITER_RECOVERY_COMMIT,p.PROVIDER_DIAGNOSTICS_APPLY_OPERATION),
            (p.R_COMMIT,p.R_ARCHIVE,p.R_RUN,p.PROVIDER_DIAGNOSTICS_COMMIT,p.R_OP),
            (p.OLD_COMMIT,p.OLD_SOURCE_SHA256,p.BASE_PREPARE_RUN,p.R_COMMIT,p.BASE_APPLY_OPERATION)]
        receipts={};starts={}
        for commit,source,run,previous,operation in roles:
            receipts[commit]=dict(source_commit=commit,package=dict(source_tar_gz_sha256=source,run_id=run,baseline=p.EXPECTED_BASELINE),runtime_environment_preserved=True,config_operation_id=p.APPROVED_CONFIG_OPERATION_ID,runtime_flags_verified=True,inventory_enabled=True,execution_enabled=False,files=dict(files))
            starts[commit]=dict(ok=True,stage='internal_ready',source_commit=commit,previous_commit=previous,operation_id=operation,database_policy='preserve-in-place',database_schema=21,database_opened_by_controller=False,database_snapshot_verified=False,source_warmup_performed=False,rollback_requires_matching_database=False,runtime_flags_verified=True,execution_enabled=False,saved_export_companion_preserved=True)
        starts[p.HISTORICAL_TARGET].update(database_policy='paired-snapshot',database_opened_by_controller=True,database_snapshot_verified=True,source_status=dict(ok=True,schema=21,old_schema=11,old_tables=36,old_rows=389163,preserved_rows=True,migration_repeatable=True,network_calls=0,randomized_tables=sorted(c.RANDOMIZED_TABLES),randomized_tables_empty=True))
        receipts[c.OLD_COMMIT]={'source_commit':c.OLD_COMMIT}
        u=SimpleNamespace(manifest=Mock(side_effect=lambda _r,commit,**_:(Path('/synthetic/naver-'+commit),receipts[commit])),read_file=Mock(side_effect=lambda path,**_:json.dumps(starts[Path(path).name.removeprefix('preview-start-').removesuffix('.json')]).encode()))
        return p,c,r,u,receipts,starts,roles

    def test_all_fifteen_historical_proofs_and_exact_read_order(self):
        p,c,r,u,receipts,starts,roles=self.fixture();self.assertEqual(p.base_success(r,u)[1],receipts[p.OLD_COMMIT])
        self.assertEqual([call.args[0].name for call in u.read_file.call_args_list],['preview-start-'+row[0]+'.json' for row in roles])

    def test_every_historical_source_run_previous_operation_config_schema_and_off_guard(self):
        for index in range(17):
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


class NewSourceInventoryTests(unittest.TestCase):
    def fixture(self,temp):
        p,_=pinned();old=Path(temp).resolve()/'old';target=Path(temp).resolve()/'target';old.mkdir();target.mkdir()
        before={'naver_engine/store.py':b'x=1\n','naver_runtime/claude_provider.py':b'x=1\n'}
        after={**before,'naver_engine/store.py':b'x=2\n'}
        for root,items in ((old,before),(target,after)):
            for name,body in items.items():
                file=root/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(body);os.chmod(file,0o644)
        rows=lambda items:{name:(0o644,len(body),hashlib.sha256(body).hexdigest())for name,body in items.items()}
        p.OLD_MANIFEST=rows(before);p.TARGET_MANIFEST=rows(after)
        upgrade=SimpleNamespace(read_file=Mock(side_effect=lambda path,**_:path.read_bytes()))
        return p,old,target,upgrade
    def test_exact_new_file_accepts_forward_and_inverse_and_missing_file_refuses(self):
        with tempfile.TemporaryDirectory()as temp:
            p,old,target,u=self.fixture(temp)
            # Pure inventory algorithm test uses small synthetic files; separate
            # source-binding tests prove the full historical165-to165 manifests.
            with patch.object(p,'require_pins'):
                p.compatible_code_scope(old,target,u)
                p.compatible_code_scope(target,old,u,inverse=True)
                (target/'naver_engine/store.py').unlink()
                with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.compatible_code_scope(old,target,u)
    def test_new_file_one_byte_unapproved_extra_mode_and_symlink_refuse(self):
        for mutation in ('byte','extra','mode','symlink','new_file_in_old'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory()as temp:
                p,old,target,u=self.fixture(temp);file=target/'naver_engine/store.py'
                if mutation=='byte':file.write_bytes(file.read_bytes()+b' ')
                elif mutation=='extra':(target/'naver_runtime/unapproved.py').write_bytes(b'x=1\n')
                elif mutation=='mode':os.chmod(file,0o600)
                elif mutation=='new_file_in_old':(old/'naver_engine/unapproved.py').write_bytes(b'CONTRACT=1\n')
                else:file.unlink();file.symlink_to(old/'naver_runtime/claude_provider.py')
                with patch.object(p,'require_pins'),self.assertRaisesRegex(ValueError,'^CODE_(SCOPE_CHANGED|SOURCE_PATH)$'):p.compatible_code_scope(old,target,u)
                if mutation=='extra':self.assertNotIn(target/'naver_runtime/unapproved.py',[x.args[0]for x in u.read_file.call_args_list])
                if mutation=='symlink':self.assertNotIn(file,[x.args[0]for x in u.read_file.call_args_list])


# Prior synthetic same-image/service/rollback/runtime guards remain unchanged.
H=load(OPS/'tests/test_naver_inspection_continuity_transport.py','p15_historical_tests')
class LifecycleTest(H.LifecycleTests):
    def setUp(self):
        binding=patch.object(H,'pinned',pinned);binding.start();self.addCleanup(binding.stop)
class RuntimeFlagTest(H.ActualFlagHelpersTests):
    def setUp(self):
        binding=patch.object(H,'pinned',pinned);binding.start();self.addCleanup(binding.stop)



class RollbackDirectoryPolicyTests(unittest.TestCase):
    """Actual rollback body and trusted_dir policy, synthetic stat-only ownership.

    Existing lifecycle adapters are synthetic; no host, Docker, API or operating
    database is opened. Directory projections use lstat metadata and never chmod.
    """
    def fixture(self):
        import stat
        from types import SimpleNamespace
        p,c=pinned()
        with patch.object(H,'pinned',return_value=(p,c)):
            f=H.LifecycleFixture(self)
        f.apply()
        f.commands.clear()
        release_source=(OPS_TOOLS/'naver_preview_release.py').read_text()
        method=next(node for node in ast.parse(release_source).body if isinstance(node,ast.FunctionDef)and node.name=='trusted_dir')
        policies={f.unitdir:dict(kind=stat.S_IFDIR,uid=0,gid=0,mode=0o755),
                  f.tmp.parent:dict(kind=stat.S_IFDIR,uid=0,gid=0,mode=0o755),
                  f.r.ROOT/'receipts':dict(kind=stat.S_IFDIR,uid=0,gid=0,mode=0o700)}
        observed=[]
        class ProjectedPath:
            def __init__(self,path):self.path=path
            def lstat(self):
                value=policies[self.path];observed.append(self.path)
                return SimpleNamespace(st_mode=value['kind']|value['mode'],st_uid=value['uid'],st_gid=value['gid'])
        scope={'Path':ProjectedPath,'stat':stat,'os':Mock(),'CREATED':[]}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<exact-public-trusted-dir>','exec'),scope)
        f.r.trusted_dir=scope['trusted_dir']
        return f,policies,observed,scope

    def rollback(self,f):
        return f.p.rollback(dict(release=package(f.p),apply_operation_id='a'*32,operation_id='b'*32),f.h,f.r,f.l,f.u)

    def test_normal_private_receipts_0700_and_system_parents_0755_complete_exact_rollback(self):
        f,policies,observed,scope=self.fixture()
        result=self.rollback(f)
        self.assertTrue(result['ok']);self.assertEqual(result['operation'],'code-only-rollback')
        self.assertEqual(result['source_commit'],f.p.OLD_COMMIT);self.assertEqual(result['previous_commit'],f.p.TARGET_COMMIT)
        self.assertEqual(result['apply_operation_id'],'a'*32);self.assertEqual(result['operation_id'],'b'*32)
        self.assertFalse(result['database_opened_by_controller']);self.assertFalse(result['execution_enabled'])
        self.assertEqual(result['database_policy'],'preserve-in-place')
        self.assertEqual(set(f.version.values()),{f.p.OLD_COMMIT})
        self.assertEqual(observed,[f.unitdir,f.tmp.parent,f.r.ROOT/'receipts'])
        scope['os'].assert_not_called();self.assertFalse(scope['os'].mock_calls)
        f.assert_preserved()

    def test_private_receipts_wrong_owner_or_group_never_stops_services(self):
        for field in ('uid','gid'):
            with self.subTest(field=field):
                f,policies,observed,scope=self.fixture();policies[f.r.ROOT/'receipts'][field]=1000
                with self.assertRaisesRegex(ValueError,'^DIRECTORY_POLICY$'):self.rollback(f)
                self.assertEqual(f.p.STAGE,'rollback_preflight');self.assertEqual(f.commands,[])
                self.assertFalse(any(path.name.startswith('code-post-rollback-')for path in (f.r.ROOT/'receipts').iterdir()))
                self.assertFalse(scope['os'].mock_calls);f.assert_preserved()

    def test_private_receipts_0755_is_rejected_before_stop_or_attempt_write(self):
        f,policies,observed,scope=self.fixture();policies[f.r.ROOT/'receipts']['mode']=0o755
        with self.assertRaisesRegex(ValueError,'^DIRECTORY_POLICY$'):self.rollback(f)
        self.assertEqual(f.p.STAGE,'rollback_preflight');self.assertEqual(f.commands,[])
        self.assertFalse(any(path.name.startswith('code-post-rollback-')for path in (f.r.ROOT/'receipts').iterdir()))
        self.assertFalse(scope['os'].mock_calls);f.assert_preserved()

    def test_private_receipts_symlink_is_rejected_before_stop_or_attempt_write(self):
        import stat
        f,policies,observed,scope=self.fixture();policies[f.r.ROOT/'receipts']['kind']=stat.S_IFLNK
        with self.assertRaisesRegex(ValueError,'^DIRECTORY_POLICY$'):self.rollback(f)
        self.assertEqual(f.p.STAGE,'rollback_preflight');self.assertEqual(f.commands,[])
        self.assertFalse(any(path.name.startswith('code-post-rollback-')for path in (f.r.ROOT/'receipts').iterdir()))
        self.assertFalse(scope['os'].mock_calls);f.assert_preserved()

    def test_system_parent_policy_remains_exact_0755_root_root_no_new_override(self):
        for which in ('unitdir','tmp_parent'):
            for field,value in (('mode',0o700),('uid',1000),('gid',1000)):
                with self.subTest(which=which,field=field):
                    f,policies,observed,scope=self.fixture()
                    path=f.unitdir if which=='unitdir' else f.tmp.parent
                    policies[path][field]=value
                    with self.assertRaisesRegex(ValueError,'^DIRECTORY_POLICY$'):self.rollback(f)
                    self.assertEqual(f.commands,[]);self.assertEqual(f.p.STAGE,'rollback_preflight')
                    self.assertFalse(scope['os'].mock_calls);f.assert_preserved()

class ErrorShapeScopeTests(unittest.TestCase):
    def test_exact_python_scope_and_no_extra_data_or_signature(self):
        p,_=pinned();name='naver_runtime/report_output_schema.py'
        self.assertEqual(set(p.APPROVED_AST_SCOPE),set(p.CODE_PATHS))
        before=b'def _http400_diagnostic(body):\n return body\n'
        after=b'def _http400_diagnostic(body):\n return body or "http-error-json"\n'
        p.APPROVED_AST_SCOPE[name]=dict(changed=('_http400_diagnostic',),added=(),removed=(),optional_abi={},imports_added=(),imports_removed=())
        p.python_contract(name,before,after)
        for bad in (after+b'raw_error="private"\n',after.replace(b'diagnostic(body)',b'diagnostic(body, raw=None)'),after+b'import socket\n'):
            with self.assertRaisesRegex(ValueError,'^CODE_SCOPE_CHANGED$'):p.python_contract(name,before,bad)
        p.APPROVED_AST_SCOPE.pop(name)
        with self.assertRaisesRegex(ValueError,'^PATCH_NOT_PINNED$'):p.validate_ast_scope(p.APPROVED_AST_SCOPE)

    def test_d599_historical_store_layer_and_8876_identity_cannot_be_masked(self):
        p,_=pinned();p.CONTEXT_REUSE_DELTA['naver_engine/store.py']=(0o644,1,'0'*64)
        with self.assertRaises(ValueError):p.require_pins()
        for field,bad in (('PROVIDER_DIAGNOSTICS_COMMIT','0'*40),('PROVIDER_DIAGNOSTICS_SOURCE_SHA256','0'*64),('PROVIDER_DIAGNOSTICS_PREPARE_RUN','99999999999'),('PROVIDER_DIAGNOSTICS_APPLY_OPERATION','0'*32)):
            p,_=pinned();setattr(p,field,bad)
            with self.subTest(field=field),self.assertRaises(ValueError):p.require_pins()

    def test_current07890_history_delta_and_d599_identity_are_exact_before_pending_candidate(self):
        p,_=pinned()
        self.assertEqual(set(p.E_DELTA),{'backend/naver_page/operations-ui.js','naver_runtime/claude_provider.py','naver_runtime/provider_observability.py'})
        for name in p.E_DELTA:
            p,_=pinned();p.E_DELTA[name]=(0o644,1,'0'*64)
            with self.subTest(path=name),self.assertRaises(ValueError):p.require_pins()
        for field,bad in (('R_COMMIT','0'*40),('R_ARCHIVE','0'*64),('R_RUN','99999999999'),('R_OP','0'*32)):
            p,_=pinned();setattr(p,field,bad)
            with self.subTest(field=field),self.assertRaises(ValueError):p.require_pins()


if __name__=='__main__':unittest.main()
