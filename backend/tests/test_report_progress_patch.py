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
if __name__=='__main__':unittest.main()
