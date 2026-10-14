"""P22 new history/scope tests; all prior P21 tests remain immutable and run separately."""
import ast,hashlib,importlib.util,json
from pathlib import Path
from copy import deepcopy
import unittest
from unittest.mock import patch
TOOLS=Path(__file__).resolve().parents[1]/'tools'
def load(name):
 spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def pinned():
 p=load('naver_report_progress_patch');base=load('naver_preview_completion_release')
 p.TARGET_COMMIT=p.APPROVED_TARGET_COMMIT='b'*40
 p.TARGET_SOURCE_SHA256=p.APPROVED_TARGET_SOURCE_SHA256='e'*64
 p.TARGET_CANONICAL_SHA256=p.APPROVED_CANONICAL_SHA256='f'*64
 p.CI_PROOF=p.APPROVED_CI_PROOF=dict(source_commit='b'*40,tooling_head='d'*40,run_id='91827364509182736450',receipt_sha256='f'*64)
 p.TARGET_DELTA=p.EXPECTED_TARGET_DELTA={name:(420,100,'d'*64)for name in p.CODE_PATHS}
 p.APPROVED_AST_SCOPE=p.EXPECTED_AST_SCOPE={name:dict(changed=(),added=(),removed=(),optional_abi={},imports_added=(),imports_removed=())for name in p.CODE_PATHS if name.endswith('.py')}
 p.bind_base(base);return p

class ReportProgressPatchTests(unittest.TestCase):
 def test_pending_pins_refuse_before_base_or_host_access(self):
  p=load('naver_report_progress_patch')
  p.TARGET_COMMIT=None
  with self.assertRaisesRegex(ValueError,'PINS_PENDING'):p.require_target_pins()
  with self.assertRaisesRegex(ValueError,'PINS_PENDING'):p.bind_base(object())
 def test_baseline_exact_ten_existing_paths_manifest166_store_and_schema(self):
  p=pinned();self.assertEqual(p.OLD_COMMIT,'7b61f64223cbd386c6971b8bc93b9ab17c11f34f')
  self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21));self.assertEqual(p.NEW_PATHS,frozenset());self.assertEqual(len(p.CODE_PATHS),10)
  self.assertEqual((len(p.OLD_MANIFEST),len(p.TARGET_MANIFEST)),(166,166));self.assertEqual(set(p.OLD_MANIFEST),set(p.TARGET_MANIFEST))
  self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]},p.CODE_PATHS)
  self.assertEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target']);self.assertEqual(p.ROLLBACK_COMMIT,p.OLD_COMMIT)
 def test_historical_ten_rows_one_new_and_receipt_constants_cannot_mutate(self):
  for name,value in [('P_M','a'*64),('P_A','a'*64),('F_C','a'*40),('F_S','a'*64),('F_R','12345678901'),('F_O','a'*32),('P_D',{})]:
   p=pinned();setattr(p,name,value)
   with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
 def test_new_runtime_or_missing_manifest_scope_is_rejected(self):
  for name,value in [('NEW_PATHS',frozenset({'unapproved.py'})),('CODE_PATHS',frozenset({'unapproved.py'})),('TARGET_COMMIT','7b61f64223cbd386c6971b8bc93b9ab17c11f34f')]:
   p=pinned();setattr(p,name,value)
   with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
 def test_scope_requires_exact_seven_python_files_and_no_optional_signature_grant(self):
  p=pinned();self.assertEqual(len(p.APPROVED_AST_SCOPE),7)
  for mutate in [lambda x:x.pop(next(iter(x))),lambda x:x.update({'unapproved.py':{}}),lambda x:x[next(iter(x))].update(optional_abi={'unknown':('new',)})]:
   value=deepcopy(p.APPROVED_AST_SCOPE);mutate(value)
   with self.assertRaises(ValueError):p.validate_ast_scope(value)
 def test_python_contract_rejects_extra_globals_imports_and_signature_change(self):
  p=pinned();name='naver_engine/strategy_validation.py'
  p.APPROVED_AST_SCOPE[name].update(changed=('normalize',),added=('proposal_pair','PROPOSAL_REASONS'))
  before=b'def normalize(value):\n return value\n';after=b'PROPOSAL_REASONS={}\ndef proposal_pair(value):\n return False\ndef normalize(value):\n return dict(value)\n'
  p.python_contract(name,before,after)
  for bad in [after+b'UNAPPROVED=True\n',b'import os\n'+after,after.replace(b'normalize(value)',b'normalize(value, bypass=False)')]:
   with self.assertRaises(ValueError):p.python_contract(name,before,bad)
 def test_prior_lifecycle_and_off_security_functions_ast_are_exact(self):
  old=ast.parse((TOOLS/'naver_budget_format_patch.py').read_bytes())if(TOOLS/'naver_budget_format_patch.py').is_file()else None
  if old is None:
   root=next(x for x in TOOLS.parents if(x/'naver-claude-reference-ops-20261011/backend/tools/naver_budget_format_patch.py').is_file())
   old=ast.parse((root/'naver-claude-reference-ops-20261011/backend/tools/naver_budget_format_patch.py').read_bytes())
  new=ast.parse((TOOLS/'naver_report_progress_patch.py').read_bytes())
  for name in ('prepare','apply','rollback','compatible_inverse_source','compatible_code_scope','current_state','target_override','verify_running','target_engine_snapshot','runtime_flags','container_environment_flags','container_runtime_flags','stopped_writer','safe_source_path','preserve_approved_config','migration_contract'):
   a=next(x for x in old.body if isinstance(x,ast.FunctionDef)and x.name==name);b=next(x for x in new.body if isinstance(x,ast.FunctionDef)and x.name==name)
   self.assertEqual(ast.dump(a),ast.dump(b),name)
 def test_new_receipt_step_uses_exact_applied7b61_after_original539(self):
  p=pinned()
  with patch.object(p,'_receipt_step',return_value='proof')as check:
   self.assertEqual(p.proposal_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.shape_success,p.F_C,p.F_S,p.F_R,p.Q_C,p.F_O))
   self.assertEqual(p.base_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.proposal_success,p.OLD_COMMIT,p.OLD_SOURCE_SHA256,'38509559215',p.F_C,'47d10b22631c4e158ad1697e27eaec08'))

def _approved_observation_fixture():
 p=pinned()
 p.APPROVED_AST_SCOPE['naver_engine/observation_store.py']['added']=('ObservationStorage.learning_strategy_validation',)
 common=b'public synthetic infrastructure\n'
 store=b"SCHEMA_VERSION=21\n_SCHEMA=''\n_REVISION_COLUMNS={}\ndef _migrate():pass\n"
 jobs=b'def clean():pass\ndef public():pass\ndef identity():pass\n'
 obs_before=b'class ObservationStorage:\n def prior(self):return True\n'
 obs_after=obs_before+b' def learning_strategy_validation(self,job):return None\n'
 p.ENGINE_COMPOSE_SHA256=hashlib.sha256(common).hexdigest()
 p.STORE_SHA256={role:hashlib.sha256(store).hexdigest()for role in ('old','target')}
 class Reader:
  mutation=None
  def read_file(self,path,**kw):
   name=Path(*path.parts[2:]).as_posix();target=path.parts[1]=='new'
   if name=='naver_engine/store.py':body=store
   elif name=='naver_runtime/learning_jobs.py':body=jobs
   elif name=='naver_engine/observation_store.py':body=obs_after if target else obs_before
   elif name in ('preview-engine.override.yml','preview-relay.override.yml'):
    before=('source:'+p.OLD_COMMIT).encode();body=p.target_override(before,'engine')if target else before
   elif name in p.CODE_PATHS and name.endswith('.py'):body=b'pass\n'
   else:body=common
   return body+b'\n# unauthorized infrastructure\n'if target and name==self.mutation else body
 return p,Reader(),obs_before,obs_after

class ReportProgressApprovedObservationTests(unittest.TestCase):
 def test_approved_observation_path_reaches_strict_ast_and_final_source_inventory(self):
  p,reader,before,after=_approved_observation_fixture();old,new=Path('/old'),Path('/new')
  with patch.object(p,'python_contract',wraps=p.python_contract)as python,patch.object(p,'compatible_code_scope')as inventory:
   p.compatible_source(old,new,reader)
  self.assertIn(('naver_engine/observation_store.py',before,after),[row.args for row in python.call_args_list])
  self.assertEqual({row.args[0]for row in python.call_args_list},{name for name in p.CODE_PATHS if name.endswith('.py')})
  inventory.assert_called_once_with(old,new,reader)
 def test_observation_unapproved_global_and_existing_method_changes_stay_rejected(self):
  p,_,before,after=_approved_observation_fixture();name='naver_engine/observation_store.py'
  p.python_contract(name,before,after)
  for mutant in (after+b'UNAPPROVED=True\n',after.replace(b'return True',b'return False')):
   with self.subTest(mutant=hashlib.sha256(mutant).hexdigest()),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):
    p.python_contract(name,before,mutant)
 def test_genuine_infrastructure_mutations_still_refuse_before_final_inventory(self):
  for name in ('compose.naver-engine.yml','Dockerfile.naver-engine','backend/requirements.txt'):
   p,reader,_,_=_approved_observation_fixture();reader.mutation=name
   with self.subTest(name=name),patch.object(p,'compatible_code_scope')as inventory:
    with self.assertRaisesRegex(ValueError,'CODE_INFRASTRUCTURE_CHANGED'):p.compatible_source(Path('/old'),Path('/new'),reader)
    inventory.assert_not_called()

if __name__=='__main__':unittest.main()
