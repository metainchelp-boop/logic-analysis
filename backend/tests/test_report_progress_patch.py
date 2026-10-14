"""Pending two-file basis epoch; synthetic fixtures do not claim actual source CI."""
import ast,hashlib,importlib.util
from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch
TOOLS=Path(__file__).resolve().parents[1]/'tools'
CP='naver_runtime/claude_provider.py'
SCHEMA='naver_runtime/report_output_schema.py'
PATHS=frozenset((CP,SCHEMA))

def load(name):
 spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def fixture_scope():
 return {CP:dict(changed=('chosen',),added=(),removed=(),optional_abi={},imports_added=(),imports_removed=()),
  SCHEMA:dict(changed=('FORMAT_VERSION','output_format'),added=(),removed=(),optional_abi={},imports_added=(),imports_removed=())}

def pinned():
 p=load('naver_report_progress_patch')
 p.TARGET_COMMIT=p.APPROVED_TARGET_COMMIT='b'*40
 p.TARGET_SOURCE_SHA256=p.APPROVED_TARGET_SOURCE_SHA256='e'*64
 p.TARGET_CANONICAL_SHA256=p.APPROVED_CANONICAL_SHA256='f'*64
 p.CI_PROOF=p.APPROVED_CI_PROOF=dict(source_commit='b'*40,tooling_head='d'*40,run_id='91827364509182736450',receipt_sha256='f'*64)
 p.TARGET_DELTA=p.EXPECTED_TARGET_DELTA={name:(420,100,'d'*64)for name in PATHS}
 p.APPROVED_AST_SCOPE=p.EXPECTED_AST_SCOPE=fixture_scope()
 p.bind_base(load('naver_preview_completion_release'));return p

def bodies():
 before={CP:b"def chosen(context):return 'old'\ndef keep():return True\n",
  SCHEMA:b"FORMAT_VERSION='v4'\ndef output_format(context):return {}\ndef text_pattern():return 'fixed'\n"}
 after={CP:b"def chosen(context):return 'new'\ndef keep():return True\n",
  SCHEMA:b"FORMAT_VERSION='v5'\ndef output_format(context):return {'type':'json_schema'}\ndef text_pattern():return 'fixed'\n"}
 return before,after

class ProductBasisPatchTests(unittest.TestCase):
 def test_pending_fresh_target_scope_refuses_before_base_or_host_access(self):
  p=load('naver_report_progress_patch')
  values={key:None for key in ('TARGET_COMMIT','APPROVED_TARGET_COMMIT','TARGET_SOURCE_SHA256','APPROVED_TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','APPROVED_CANONICAL_SHA256','CI_PROOF','APPROVED_CI_PROOF','TARGET_DELTA','EXPECTED_TARGET_DELTA','APPROVED_AST_SCOPE','EXPECTED_AST_SCOPE')}
  with patch.multiple(p,**values):
   for key in ('TARGET_COMMIT','APPROVED_TARGET_COMMIT','TARGET_SOURCE_SHA256','APPROVED_TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','APPROVED_CANONICAL_SHA256','CI_PROOF','APPROVED_CI_PROOF','TARGET_DELTA','EXPECTED_TARGET_DELTA','APPROVED_AST_SCOPE','EXPECTED_AST_SCOPE'):self.assertIsNone(getattr(p,key))
   with self.assertRaisesRegex(ValueError,'PINS_PENDING'):p.require_target_pins()
   with self.assertRaisesRegex(ValueError,'PINS_PENDING'):p.bind_base(object())
 def test_actual_c200_baseline_two_existing_paths_manifest166_same_store_schema_and_assets(self):
  p=pinned();self.assertEqual(p.OLD_COMMIT,'c20089be6c2e397bedea913a8ba9448f44a03de8')
  self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21));self.assertEqual(p.CODE_PATHS,PATHS);self.assertEqual(p.NEW_PATHS,frozenset())
  self.assertEqual((len(p.OLD_MANIFEST),len(p.TARGET_MANIFEST)),(166,166));self.assertEqual(set(p.OLD_MANIFEST),set(p.TARGET_MANIFEST))
  self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]},PATHS)
  self.assertEqual(p.manifest_digest(p.OLD_MANIFEST),'40282323d1d38ebbcc4b38755c7cf81fe8b585fd6152708feaddd66656c7093b')
  self.assertEqual(p.H_M,'51620b5091b7374d6739ff022f3eed09088751c6e3bcd21277e12d96d61d8fc5')
  self.assertEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target']);self.assertEqual(p.ROLLBACK_COMMIT,p.OLD_COMMIT);self.assertEqual(p.OLD_REPORT_ASSETS,p.REPORT_ASSETS)
 def test_all_old_history_and_new_c200_layer_and_receipt_pairs_cannot_mutate(self):
  for name,value in [('H_M','a'*64),('H_A','a'*64),('H_C','a'*40),('H_S','a'*64),('H_R','12345678901'),('H_O','a'*32),('H_D',{}),('Z_M','a'*64),('Z_A','a'*64),('Z_C','a'*40),('Z_S','a'*64),('Z_R','12345678901'),('Z_O','a'*32),('Z_D',{}),('BASE_PREPARE_RUN','38523201246'),('BASE_APPLY_OPERATION','a'*32)]:
   p=pinned();setattr(p,name,value)
   with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
 def test_foreign_new_missing_paths_and_previous_source_pins_refuse(self):
  for name,value in [('NEW_PATHS',frozenset({'unapproved.py'})),('CODE_PATHS',frozenset({'unapproved.py'})),('TARGET_COMMIT','c20089be6c2e397bedea913a8ba9448f44a03de8'),('TARGET_COMMIT','7f138a8d42bb292567ccb3e117bd0305efc42ad7'),('OLD_COMMIT','7f138a8d42bb292567ccb3e117bd0305efc42ad7'),('OLD_SOURCE_SHA256','a'*64)]:
   p=pinned();setattr(p,name,value)
   with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
 def test_exact_scope_field_shape_and_unapproved_ABI_remain_closed(self):
  p=pinned();self.assertEqual(set(p.APPROVED_AST_SCOPE),PATHS)
  for mutation in (lambda x:x.pop(CP),lambda x:x.update({'unapproved.py':{}}),lambda x:x[CP].update(optional_abi={'chosen':('bypass',)})):
   scope=deepcopy(p.APPROVED_AST_SCOPE);mutation(scope)
   with self.assertRaises(ValueError):p.validate_ast_scope(scope)
 def test_python_contract_accepts_only_approved_body_and_version_names(self):
  p=pinned();before,after=bodies()
  for name in PATHS:p.python_contract(name,before[name],after[name])
  for name,bad in [(CP,after[CP]+b'UNAPPROVED=True\n'),(CP,b'import os\n'+after[CP]),(CP,after[CP].replace(b'chosen(context)',b'chosen(context,bypass=False)')),(CP,after[CP].replace(b'keep():return True',b'keep():return False')),(SCHEMA,after[SCHEMA].replace(b"return 'fixed'",b"return 'changed'"))]:
   with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(name,before[name],bad)
 def test_schema_basis_optional_ABI_is_one_exact_None_keyword_only_combination(self):
  p=pinned();scope=fixture_scope();scope[SCHEMA]['optional_abi']={'output_format':('basis_ids',)};p.APPROVED_AST_SCOPE=p.EXPECTED_AST_SCOPE=scope;p.validate_ast_scope(scope)
  before=b"FORMAT_VERSION='v4'\ndef output_format(context):return {}\ndef text_pattern():return 'fixed'\n"
  after=b"FORMAT_VERSION='v5'\ndef output_format(context, *, basis_ids=None):return {'type':'json_schema'}\ndef text_pattern():return 'fixed'\n"
  p.python_contract(SCHEMA,before,after)
  for signature in ('output_format(context, *, basis_ids=False)','output_format(context, *, basis_ids=())','output_format(context, basis_ids=None)','output_format(context, *, other=None)','output_format(other, *, basis_ids=None)','output_format(context, *, basis_ids=0)'):
   bad=after.replace(b'output_format(context, *, basis_ids=None)',signature.encode())
   with self.subTest(signature=signature),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(SCHEMA,before,bad)
  # Generic optional-argument normalization permits a new argument annotation;
  # the unchanged exact inventory still rejects those unregistered bytes.
  annotated=after.replace(b'basis_ids=None',b'basis_ids: tuple=None');p.python_contract(SCHEMA,before,annotated)
  with tempfile.TemporaryDirectory()as temp:
   old,new=Path(temp).resolve()/'old',Path(temp).resolve()/'new';old.mkdir();new.mkdir()
   before_cp,after_cp=bodies();before_map={CP:before_cp[CP],SCHEMA:before};expected_map={CP:after_cp[CP],SCHEMA:after};actual_map={**expected_map,SCHEMA:annotated}
   for root,values in ((old,before_map),(new,actual_map)):
    (root/'naver_runtime').mkdir()
    for name,raw in values.items():(root/name).write_bytes(raw);(root/name).chmod(0o644)
   wanted=lambda raw:(420,len(raw),hashlib.sha256(raw).hexdigest())
   p.OLD_MANIFEST={name:wanted(raw)for name,raw in before_map.items()};p.TARGET_MANIFEST={name:wanted(raw)for name,raw in expected_map.items()}
   class Reader:
    def read_file(self,path,**kw):return path.read_bytes()
   with patch.object(p,'require_pins'),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.compatible_code_scope(old,new,Reader())
  for value in ({'output_format':('other',)},{'text_pattern':('basis_ids',)},{'output_format':['basis_ids']}):
   bad=deepcopy(scope);bad[SCHEMA]['optional_abi']=value
   with self.subTest(value=value),self.assertRaises(ValueError):p.validate_ast_scope(bad)
 def test_all_prior_ABI_rows_and_both_generic_predicates_are_preserved(self):
  p=pinned()
  prior={'naver_engine/web.py':('App._learning_job_response',('finalization',),None,False),'naver_engine/execution_store.py':('ExecutionStorage.execution_record_spend',('campaign_budget_proof',),None,False),'naver_engine/naver_write.py':('issue_spend_handle',('campaign_budget_proof',),None,False),'naver_engine/inspection_reads.py':('_initial',('detail_reads',),False,False),'naver_engine/setup_checks.py':('_budget_item',('proof','now'),None,True)}
  for name,row in prior.items():self.assertEqual(p._abi(name),row)
  self.assertEqual(p._abi(SCHEMA),('output_format',('basis_ids',),None,False));self.assertIsNone(p._abi('unapproved.py'))
  old=ast.parse((TOOLS/'naver_budget_format_patch.py').read_bytes());new=ast.parse((TOOLS/'naver_report_progress_patch.py').read_bytes())
  for name in ('validate_ast_scope','python_contract'):
   a=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name==name);b=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name==name);self.assertEqual(ast.dump(a),ast.dump(b),name)
 def test_lifecycle_migration_off_and_security_function_AST_remain_original(self):
  old=ast.parse((TOOLS/'naver_budget_format_patch.py').read_bytes());new=ast.parse((TOOLS/'naver_report_progress_patch.py').read_bytes())
  for name in ('prepare','apply','rollback','compatible_inverse_source','compatible_code_scope','current_state','target_override','verify_running','target_engine_snapshot','runtime_flags','container_environment_flags','container_runtime_flags','stopped_writer','safe_source_path','preserve_approved_config','migration_contract'):
   a=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name==name);b=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name==name);self.assertEqual(ast.dump(a),ast.dump(b),name)
 def test_exact_receipt_chain_preserves7f_then_requires_applied_c200_uuid(self):
  p=pinned()
  with patch.object(p,'_receipt_step',return_value='proof')as check:
   self.assertEqual(p.inspection_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.proposal_success,p.H_C,p.H_S,p.H_R,p.F_C,p.H_O))
   self.assertEqual(p.funnel_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.inspection_success,p.Z_C,p.Z_S,'38523201246',p.H_C,'56e0a8bbfcf04b1e82129cdeffa28811'))
   self.assertEqual(p.base_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.funnel_success,p.OLD_COMMIT,p.OLD_SOURCE_SHA256,'38531626583',p.Z_C,'e5864b94306c4736a5ecadd10b16d998'))
 def test_both_approved_paths_reach_strict_AST_and_then_final_inventory(self):
  p,reader,before,after=fixture()
  with patch.object(p,'python_contract',wraps=p.python_contract)as contract,patch.object(p,'compatible_code_scope')as inventory:p.compatible_source(Path('/old'),Path('/new'),reader)
  self.assertEqual({call.args for call in contract.call_args_list},{(name,before[name],after[name])for name in PATHS})
  inventory.assert_called_once_with(Path('/old'),Path('/new'),reader)
 def test_unrelated_infrastructure_and_store_changes_remain_refused(self):
  for name in ('compose.naver-engine.yml','Dockerfile.naver-engine','backend/requirements.txt','naver_engine/store.py'):
   p,reader,_,_=fixture();reader.mutation=name
   with self.subTest(name=name),patch.object(p,'compatible_code_scope')as inventory:
    with self.assertRaises(ValueError):p.compatible_source(Path('/old'),Path('/new'),reader)
    inventory.assert_not_called()
 def test_final_inventory_rejects_different_approved_body_after_AST_acceptance(self):
  p=pinned();before,after=bodies();mutant=after[CP].replace(b"return 'new'",b"return 'different'");p.python_contract(CP,before[CP],mutant)
  with tempfile.TemporaryDirectory()as temp:
   old,new=Path(temp).resolve()/'old',Path(temp).resolve()/'new';old.mkdir();new.mkdir()
   for root,bodies_ in ((old,before),(new,{**after,CP:mutant})):
    (root/'naver_runtime').mkdir()
    for name,body in bodies_.items():(root/name).write_bytes(body);(root/name).chmod(0o644)
   wanted=lambda body:(420,len(body),hashlib.sha256(body).hexdigest())
   p.OLD_MANIFEST={name:wanted(body)for name,body in before.items()};p.TARGET_MANIFEST={name:wanted(body)for name,body in after.items()}
   class Reader:
    def read_file(self,path,**kw):return path.read_bytes()
   with patch.object(p,'require_pins')as pins,self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.compatible_code_scope(old,new,Reader())
   pins.assert_called_once()
 def test_inverse_source_calls_forward_guards_and_reversed_inventory(self):
  p=pinned();old,target=Path('/old'),Path('/target')
  with patch.object(p,'compatible_source')as forward,patch.object(p,'compatible_code_scope')as inventory:p.compatible_inverse_source(target,old,'reader')
  forward.assert_called_once_with(old,target,'reader');inventory.assert_called_once_with(target,old,'reader',inverse=True)

def fixture():
 p=pinned();before,after=bodies();common=b'public synthetic infrastructure\n';store=b"SCHEMA_VERSION=21\n_SCHEMA=''\n_REVISION_COLUMNS={}\ndef _migrate():pass\n";jobs=b'def clean():pass\ndef public():pass\ndef identity():pass\n'
 p.ENGINE_COMPOSE_SHA256=hashlib.sha256(common).hexdigest();p.STORE_SHA256={k:hashlib.sha256(store).hexdigest()for k in ('old','target')}
 class Reader:
  mutation=None
  def read_file(self,path,**kw):
   name=Path(*path.parts[2:]).as_posix();target=path.parts[1]=='new'
   if name in PATHS:body=after[name]if target else before[name]
   elif name=='naver_engine/store.py':body=store
   elif name=='naver_runtime/learning_jobs.py':body=jobs
   elif name in ('preview-engine.override.yml','preview-relay.override.yml'):
    prior=('source:'+p.OLD_COMMIT).encode();body=p.target_override(prior,'engine')if target else prior
   else:body=common
   return body+b'\n# unauthorized mutation\n'if target and name==self.mutation else body
 return p,Reader(),before,after
if __name__=='__main__':unittest.main()
