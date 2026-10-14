"""P23 pending one-file funnel source epoch; synthetic controller guard tests."""
import ast,hashlib,importlib.util
from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch
TOOLS=Path(__file__).resolve().parents[1]/'tools'
PATH='naver_engine/funnel_store.py'
def load(name):
 spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def pinned():
 p=load('naver_report_progress_patch')
 p.TARGET_COMMIT=p.APPROVED_TARGET_COMMIT='b'*40
 p.TARGET_SOURCE_SHA256=p.APPROVED_TARGET_SOURCE_SHA256='e'*64
 p.TARGET_CANONICAL_SHA256=p.APPROVED_CANONICAL_SHA256='f'*64
 p.CI_PROOF=p.APPROVED_CI_PROOF=dict(source_commit='b'*40,tooling_head='d'*40,run_id='91827364509182736450',receipt_sha256='f'*64)
 p.TARGET_DELTA=p.EXPECTED_TARGET_DELTA={PATH:(420,100,'d'*64)}
 p.bind_base(load('naver_preview_completion_release'));return p

def bodies():
 before=b'class FunnelStorage:\n def funnel_work(self,now,limit=24):return []\n def funnel_account_valid(self,job,now):return False\n def keep(self):return True\n'
 after=b'class FunnelStorage:\n def funnel_work(self,now,limit=24):return [now]\n def funnel_account_valid(self,job,now):return self._funnel_account_valid(job,now)\n def _funnel_account_valid(self,job,now,source=None):return False\n def keep(self):return True\n_FUNNEL_SELECTION_DEFAULTS=(FunnelStorage.funnel_account_valid,FunnelStorage._funnel_account_valid)\n'
 return before,after

class FunnelWriterPatchTests(unittest.TestCase):
 def test_pending_fresh_target_proof_refuses_before_any_base_or_host_access(self):
  p=load('naver_report_progress_patch');p.TARGET_COMMIT=None
  with self.assertRaisesRegex(ValueError,'PINS_PENDING'):p.require_target_pins()
  with self.assertRaisesRegex(ValueError,'PINS_PENDING'):p.bind_base(object())
 def test_baseline_exact7f_one_existing_path_manifest166_same_store_schema_and_assets(self):
  p=pinned();self.assertEqual(p.OLD_COMMIT,'7f138a8d42bb292567ccb3e117bd0305efc42ad7')
  self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21));self.assertEqual(p.CODE_PATHS,frozenset({PATH}));self.assertEqual(p.NEW_PATHS,frozenset())
  self.assertEqual((len(p.OLD_MANIFEST),len(p.TARGET_MANIFEST)),(166,166))
  self.assertEqual(set(p.OLD_MANIFEST),set(p.TARGET_MANIFEST));self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]},p.CODE_PATHS)
  self.assertEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target']);self.assertEqual(p.ROLLBACK_COMMIT,p.OLD_COMMIT);self.assertEqual(p.OLD_REPORT_ASSETS,p.REPORT_ASSETS)
 def test_new7f_history_and_applied_receipt_constants_cannot_be_reused_or_mutated(self):
  for name,value in [('H_M','a'*64),('H_A','a'*64),('H_C','a'*40),('H_S','a'*64),('H_R','12345678901'),('H_O','a'*32),('H_D',{}),('BASE_PREPARE_RUN','38520767973'),('BASE_APPLY_OPERATION','a'*32)]:
   p=pinned();setattr(p,name,value)
   with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
 def test_foreign_new_or_missing_path_and_predecessor_source_pins_reject(self):
  for name,value in [('NEW_PATHS',frozenset({'unapproved.py'})),('CODE_PATHS',frozenset({'unapproved.py'})),('TARGET_COMMIT','7f138a8d42bb292567ccb3e117bd0305efc42ad7'),('OLD_COMMIT','7b61f64223cbd386c6971b8bc93b9ab17c11f34f'),('OLD_SOURCE_SHA256','a'*64)]:
   p=pinned();setattr(p,name,value)
   with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
 def test_scope_exact_two_changed_methods_private_helper_constant_and_no_ABI_grant(self):
  p=pinned();scope=p.APPROVED_AST_SCOPE;self.assertEqual(set(scope),{PATH})
  self.assertEqual(scope[PATH],dict(changed=('FunnelStorage.funnel_work','FunnelStorage.funnel_account_valid'),added=('FunnelStorage._funnel_account_valid','_FUNNEL_SELECTION_DEFAULTS'),removed=(),optional_abi={},imports_added=(),imports_removed=()))
  for mutation in (lambda x:x.pop(PATH),lambda x:x.update({'unapproved.py':{}}),lambda x:x[PATH].update(optional_abi={'FunnelStorage.funnel_work':('bypass',)})):
   changed=deepcopy(scope);mutation(changed)
   with self.assertRaises(ValueError):p.validate_ast_scope(changed)
 def test_python_contract_accepts_only_approved_names_and_keeps_original_public_ABI(self):
  p=pinned();before,after=bodies();p.python_contract(PATH,before,after)
  for bad in (after+b'UNAPPROVED=True\n',b'import os\n'+after,after.replace(b'funnel_work(self,now,limit=24)',b'funnel_work(self,now,limit=24,bypass=False)'),after.replace(b'def keep(self):return True',b'def keep(self):return False')):
   with self.subTest(digest=hashlib.sha256(bad).hexdigest()),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(PATH,before,bad)
 def test_lifecycle_and_off_security_function_AST_remain_original(self):
  old=ast.parse((TOOLS/'naver_budget_format_patch.py').read_bytes());new=ast.parse((TOOLS/'naver_report_progress_patch.py').read_bytes())
  for name in ('prepare','apply','rollback','compatible_inverse_source','compatible_code_scope','current_state','target_override','verify_running','target_engine_snapshot','runtime_flags','container_environment_flags','container_runtime_flags','stopped_writer','safe_source_path','preserve_approved_config','migration_contract'):
   a=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name==name);b=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name==name);self.assertEqual(ast.dump(a),ast.dump(b),name)
 def test_receipt_chain_inserts_only_actual7f_after_7b61_and_keeps_paired_apply(self):
  p=pinned()
  with patch.object(p,'_receipt_step',return_value='proof')as check:
   self.assertEqual(p.inspection_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.proposal_success,p.H_C,p.H_S,p.H_R,p.F_C,p.H_O))
   self.assertEqual(p.base_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.inspection_success,p.OLD_COMMIT,p.OLD_SOURCE_SHA256,'38523201246',p.H_C,'56e0a8bbfcf04b1e82129cdeffa28811'))
 def test_approved_funnel_path_reaches_strict_AST_then_final_inventory(self):
  p,reader,before,after=fixture()
  with patch.object(p,'python_contract',wraps=p.python_contract)as contract,patch.object(p,'compatible_code_scope')as inventory:
   p.compatible_source(Path('/old'),Path('/new'),reader)
  contract.assert_called_once_with(PATH,before,after);inventory.assert_called_once_with(Path('/old'),Path('/new'),reader)
 def test_unrelated_infrastructure_and_store_changes_remain_refused(self):
  for name in ('compose.naver-engine.yml','Dockerfile.naver-engine','backend/requirements.txt','naver_engine/store.py'):
   p,reader,_,_=fixture();reader.mutation=name
   with self.subTest(name=name),patch.object(p,'compatible_code_scope')as inventory:
    with self.assertRaises(ValueError):p.compatible_source(Path('/old'),Path('/new'),reader)
    inventory.assert_not_called()
 def test_final_inventory_rejects_changed_approved_body_after_AST_acceptance(self):
  p=pinned();before,after=bodies();mutant=after.replace(b'return [now]',b'return [False]');p.python_contract(PATH,before,mutant)
  with tempfile.TemporaryDirectory()as temp:
   old,new=Path(temp).resolve()/'old',Path(temp).resolve()/'new';old.mkdir();new.mkdir()
   for root,body in ((old,before),(new,mutant)):
    (root/'naver_engine').mkdir();(root/PATH).write_bytes(body);(root/PATH).chmod(0o644)
   wanted=lambda body:(420,len(body),hashlib.sha256(body).hexdigest())
   p.OLD_MANIFEST={PATH:wanted(before)};p.TARGET_MANIFEST={PATH:wanted(after)}
   class Reader:
    def read_file(self,path,**kw):return path.read_bytes()
   with patch.object(p,'require_pins')as pins,self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
    p.compatible_code_scope(old,new,Reader())
   pins.assert_called_once()
 def test_inverse_source_calls_forward_guards_and_reversed_inventory(self):
  p=pinned();old,target=Path('/old'),Path('/target')
  with patch.object(p,'compatible_source')as forward,patch.object(p,'compatible_code_scope')as inventory:
   p.compatible_inverse_source(target,old,'reader')
  forward.assert_called_once_with(old,target,'reader');inventory.assert_called_once_with(target,old,'reader',inverse=True)

def fixture():
 p=pinned();before,after=bodies();common=b'public synthetic infrastructure\n';store=b"SCHEMA_VERSION=21\n_SCHEMA=''\n_REVISION_COLUMNS={}\ndef _migrate():pass\n";jobs=b'def clean():pass\ndef public():pass\ndef identity():pass\n'
 p.ENGINE_COMPOSE_SHA256=hashlib.sha256(common).hexdigest();p.STORE_SHA256={k:hashlib.sha256(store).hexdigest()for k in ('old','target')}
 class Reader:
  mutation=None
  def read_file(self,path,**kw):
   name=Path(*path.parts[2:]).as_posix();target=path.parts[1]=='new'
   if name==PATH:body=after if target else before
   elif name=='naver_engine/store.py':body=store
   elif name=='naver_runtime/learning_jobs.py':body=jobs
   elif name in ('preview-engine.override.yml','preview-relay.override.yml'):
    prior=('source:'+p.OLD_COMMIT).encode();body=p.target_override(prior,'engine')if target else prior
   else:body=common
   return body+b'\n# unauthorized mutation\n'if target and name==self.mutation else body
 return p,Reader(),before,after
if __name__=='__main__':unittest.main()
