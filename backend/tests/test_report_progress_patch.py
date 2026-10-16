"""Two-file text-pool epoch; synthetic fixtures do not claim actual source CI."""
import ast,hashlib,importlib.util
from pathlib import Path
from copy import deepcopy
import tempfile
import unittest
from unittest.mock import patch
TOOLS=Path(__file__).resolve().parents[1]/'tools'
CP='naver_engine/inspection_store.py'
SCHEMA='naver_engine/collection_diagnostics.py'
JS='backend/naver_page/operations-ui.js'
WEB='naver_engine/web.py'
PYTHON_PATHS=frozenset(('naver_engine/inspection_store.py',))
PATHS=frozenset(('naver_engine/inspection_store.py',))

def load(name):
 spec=importlib.util.spec_from_file_location(name,TOOLS/(name+'.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def fixture_scope():
 value={name:dict(changed=('chosen',),added=(),removed=(),optional_abi={},imports_added=(),imports_removed=()) for name in PYTHON_PATHS}
 value[SCHEMA]=dict(changed=('FORMAT_VERSION','output_format'),added=(),removed=(),optional_abi={},imports_added=(),imports_removed=())
 value['naver_runtime/runtime_status.py']={'added': ('InspectionWorkerObservation.SELECTION_EVENTS',), 'changed': ('InspectionWorkerObservation.__init__', 'InspectionWorkerObservation._put', 'InspectionWorkerObservation.note', 'InspectionWorkerObservation.snapshot'), 'imports_added': (), 'imports_removed': (), 'optional_abi': {}, 'removed': ()}
 return value

def pinned():
 p=load('naver_report_progress_patch')
 p.TARGET_COMMIT=p.APPROVED_TARGET_COMMIT='b'*40
 p.TARGET_SOURCE_SHA256=p.APPROVED_TARGET_SOURCE_SHA256='e'*64
 p.TARGET_CANONICAL_SHA256=p.APPROVED_CANONICAL_SHA256='f'*64
 p.CI_PROOF=p.APPROVED_CI_PROOF=dict(source_commit='b'*40,tooling_head='d'*40,run_id='91827364509182736450',receipt_sha256='f'*64)
 p.TARGET_DELTA=p.EXPECTED_TARGET_DELTA={name:(420,100,'d'*64)for name in PATHS}
 p.APPROVED_AST_SCOPE=p.EXPECTED_AST_SCOPE={name:row for name,row in fixture_scope().items() if name in PYTHON_PATHS}
 p.bind_base(load('naver_preview_completion_release'));return p

def bodies():
 before={name:b"def chosen(context):return 'old'\ndef keep():return True\n" for name in PYTHON_PATHS}
 after={name:b"def chosen(context):return 'new'\ndef keep():return True\n" for name in PYTHON_PATHS}
 before[SCHEMA]=b"FORMAT_VERSION='v4'\ndef output_format(context):return {}\ndef text_pattern():return 'fixed'\n"
 after[SCHEMA]=b"FORMAT_VERSION='v5'\ndef output_format(context):return {'type':'json_schema'}\ndef text_pattern():return 'fixed'\n"
 before[JS]=b'const approved = false;\n';after[JS]=b'const approved = true;\n'
 before['naver_runtime/runtime_status.py']=b"class RuntimeStatus:\n def snapshot(self):return 'fixed'\n"+BASELINE_OBSERVATION_CLASS.encode()
 after['naver_runtime/runtime_status.py']=b"class RuntimeStatus:\n def snapshot(self):return 'fixed'\n"+APPROVED_OBSERVATION_CLASS.encode()
 return before,after


def inverse_approved_predicate(node,name):
 node=deepcopy(node)
 new_loop=ast.parse("for key,args in value['optional_abi'].items():\n abi=_abi(name,key)\n if (not abi or type(args)is not tuple or args!=abi[1]):raise ValueError('PATCH_NOT_PINNED')").body[0]
 old_loop=ast.parse("abi=_abi(name)\nif value['optional_abi'] and (not abi or value['optional_abi']!={abi[0]:abi[1]} or any(type(args)is not tuple for args in value['optional_abi'].values())):raise ValueError('PATCH_NOT_PINNED')").body
 class_branch=ast.parse("if name=='naver_runtime/runtime_status.py' and not prefix and node.name=='InspectionWorkerObservation':continue").body[0]
 class_full_branch=ast.parse("if name == 'naver_runtime/runtime_status.py':\n    for class_index, class_tree in enumerate(trees):\n        classes = [n for n in class_tree.body if isinstance(n, ast.ClassDef) and n.name == 'InspectionWorkerObservation']\n        if len(classes) != 1:\n            raise ValueError('CODE_SCOPE_CHANGED')\n        for typed in ast.walk(classes[0]):\n            if isinstance(typed, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):\n                if getattr(typed, 'type_params', []) != []:\n                    raise ValueError('CODE_SCOPE_CHANGED')\n                if 'type_params' not in typed._fields:\n                    typed.type_params = []\n                    typed._fields = (*typed._fields, 'type_params')\n        full = ast.dump(classes[0], include_attributes=False, **{'show_empty': True} if 'show_empty' in ast.dump.__code__.co_varnames else {})\n        if hashlib.sha256(full.encode()).hexdigest() != ('42871023e225323376f947de3926ca7f912c9737080557254ee67c7d1f636da3', 'b61f1239d440064b3b1dc3eb0a7972874ec37cd833ec71eed89932d5a63790d7')[class_index]:\n            raise ValueError('CODE_SCOPE_CHANGED')").body[0]
 class Restore(ast.NodeTransformer):
  loops=calls=classes=0
  def visit_For(self,item):
   if name=='validate_ast_scope' and ast.dump(item.target)==ast.dump(new_loop.target) and ast.dump(item.iter)==ast.dump(new_loop.iter):
    assert ast.dump(item)==ast.dump(new_loop);self.loops+=1;return deepcopy(old_loop)
   return self.generic_visit(item)
  def visit_Call(self,item):
   if name=='python_contract' and isinstance(item.func,ast.Name) and item.func.id=='_abi':
    assert len(item.args)==2 and ast.dump(item.args[0])==ast.dump(ast.Name(id='name',ctx=ast.Load())) and ast.dump(item.args[1])==ast.dump(ast.Name(id='key',ctx=ast.Load()));self.calls+=1;item.args=item.args[:1]
   return self.generic_visit(item)
  def visit_If(self,item):
   if name=='python_contract' and ast.dump(item.test) in (ast.dump(class_branch.test),ast.dump(class_full_branch.test)):
    expected=class_branch if ast.dump(item.test)==ast.dump(class_branch.test) else class_full_branch
    assert ast.dump(item)==ast.dump(expected);self.classes+=1;return None
   return self.generic_visit(item)
 restore=Restore();result=restore.visit(node)
 assert (restore.loops,restore.calls,restore.classes)==((1,0,0) if name=='validate_ast_scope' else (0,1,2))
 return result

BASELINE_OBSERVATION_CLASS='class InspectionWorkerObservation:\n    """Bounded local branch evidence only; never a current source/job proof."""\n    MAX_ACCOUNTS = 256\n\n    def __init__(self, *, clock=None):\n        from datetime import datetime, timezone\n        self._clock = clock or (lambda: datetime.now(timezone.utc))\n        self._lock = threading.Lock()\n        self._sequence = 0\n        self._cycle_at = None\n        self._global = self._window = None\n        self._accounts = {}\n        self._performance = None\n        self._window_accounts = frozenset()\n\n    def note(self, event, *, job=None, jobs=None, customers=(), calls_remaining=None,\n             seconds_remaining=None, budget_scope=None, stored_status=None):\n        # Observation has a separate wall clock: no extra business clock/budget calls.\n        try:\n            from datetime import timezone\n            stamp = self._clock()\n            if stamp.tzinfo is None:\n                raise ValueError()\n            at = stamp.astimezone(timezone.utc).isoformat(timespec=\'microseconds\')\n            with self._lock:\n                if event == \'inventory_started\':\n                    self._sequence += 1\n                    self._cycle_at = at\n                    self._window = None\n                    self._window_accounts = frozenset()\n                    self._performance = None\n                if self._cycle_at is None or at < self._cycle_at:\n                    return\n                if event == \'performance_finished\':\n                    if type(customers) in (tuple, list, set, frozenset) and len(customers) <= 24 \\\n                            and all(type(cid) is int and cid > 0 for cid in customers):\n                        self._performance = frozenset(customers)\n                    else:\n                        self._cycle_at = self._global = self._window = None\n                    return\n                row = {\'version\': 1, \'scope\': \'process_memory\', \'current_job_match\': \'not_proven\',\n                       \'cycle_started_at\': self._cycle_at, \'observed_at\': at, \'in_latest_cycle\': True,\n                       \'event\': event, \'candidate_count\': None if self._window is None else len(self._window_accounts),\n                       \'calls_remaining\': calls_remaining, \'seconds_remaining\': seconds_remaining,\n                       \'budget_scope\': budget_scope, \'stored_status\': stored_status}\n                if event == \'candidate_window\':\n                    if type(jobs) not in (list, tuple) or len(jobs) > 24:\n                        return\n                    ids = [item.get(\'customer_id\') for item in jobs if type(item) is dict]\n                    if len(ids) != len(jobs) or any(type(cid) is not int or cid <= 0 for cid in ids):\n                        return\n                    self._window_accounts = frozenset(ids)\n                    row.update(event=\'window_not_returned\', candidate_count=len(jobs))\n                    self._window = dict(row)\n                    self._global = dict(row)\n                    for cid in ids:\n                        self._put(cid, dict(row, event=\'candidate_returned\'))\n                    return\n                if type(job) is dict and type(job.get(\'customer_id\')) is int and job[\'customer_id\'] > 0:\n                    cid = job[\'customer_id\']\n                    if event == \'excluded\':\n                        if self._performance is None:\n                            self._cycle_at = self._global = self._window = None\n                            return\n                        row[\'event\'] = (\'performance_same_cycle_excluded\' if cid in self._performance\n                                        else \'earlier_lane_excluded\')\n                    self._put(cid, row)\n                else:\n                    self._global = row\n                    if event in (\'call_budget_exhausted\', \'time_budget_exhausted\', \'rate_limited\',\n                                 \'source_changed\', \'execution_error\'):\n                        for cid, (sequence, prior) in tuple(self._accounts.items()):\n                            if sequence == self._sequence and prior[\'event\'] == \'candidate_returned\':\n                                self._put(cid, dict(row))\n        except Exception:\n            # Failed clock/read observation is unavailable, not fresh evidence.\n            with self._lock:\n                self._global = self._window = None\n                if event == \'inventory_started\':\n                    self._cycle_at = None\n            return\n\n    def _put(self, cid, row):\n        self._accounts.pop(cid, None)\n        self._accounts[cid] = (self._sequence, row)\n        while len(self._accounts) > self.MAX_ACCOUNTS:\n            self._accounts.pop(next(iter(self._accounts)))\n\n    def snapshot(self, possibility_id, customer_id):\n        """Read-only. Authority is resolved by the caller; no job/generation match is asserted."""\n        try:\n            if type(possibility_id) is not int or possibility_id <= 0 \\\n                    or type(customer_id) is not int or customer_id <= 0:\n                return None\n            with self._lock:\n                if self._global is None:\n                    return None\n                prior = self._accounts.get(customer_id)\n                if prior is not None and prior[0] == self._sequence:\n                    return dict(prior[1])\n                if self._window is not None and customer_id not in self._window_accounts:\n                    return dict(self._window)\n                if self._global[\'event\'] not in (\'inventory_started\', \'lane_entered\'):\n                    return dict(self._global)\n                if prior is not None:\n                    return dict(prior[1], in_latest_cycle=False)\n                return dict(self._global)\n        except Exception:\n            return None\n'
APPROVED_OBSERVATION_CLASS='class InspectionWorkerObservation:\n    """Bounded local branch evidence only; never a current source/job proof."""\n    MAX_ACCOUNTS = 256\n    SELECTION_EVENTS = frozenset({\n        \'selection_policy_blocked\', \'selection_retry_wait\', \'selection_weekly_not_due\',\n        \'selection_account_wait\', \'selection_account_scope_invalid\',\n        \'selection_manual_quota\', \'selection_behind_window\',\n    })\n\n    def __init__(self, *, clock=None):\n        from datetime import datetime, timezone\n        self._clock = clock or (lambda: datetime.now(timezone.utc))\n        self._lock = threading.Lock()\n        self._sequence = 0\n        self._cycle_at = None\n        self._global = self._window = None\n        self._accounts = {}\n        self._performance = None\n        self._window_accounts = frozenset()\n        self._selection_accounts = frozenset()\n        self._selection_offset = 0\n\n    def note(self, event, *, job=None, jobs=None, customers=(), calls_remaining=None,\n             seconds_remaining=None, budget_scope=None, stored_status=None):\n        # Observation has a separate wall clock: no extra business clock/budget calls.\n        try:\n            if event in self.SELECTION_EVENTS:\n                with self._lock:\n                    if type(job) is not dict or type(job.get(\'customer_id\')) is not int \\\n                            or job[\'customer_id\'] not in self._selection_accounts:\n                        return\n            from datetime import timezone\n            stamp = self._clock()\n            if stamp.tzinfo is None:\n                raise ValueError()\n            at = stamp.astimezone(timezone.utc).isoformat(timespec=\'microseconds\')\n            with self._lock:\n                if event == \'inventory_started\':\n                    self._sequence += 1\n                    self._cycle_at = at\n                    self._window = None\n                    self._window_accounts = frozenset()\n                    self._performance = None\n                    self._selection_accounts = frozenset()\n                if self._cycle_at is None or at < self._cycle_at:\n                    return\n                if event == \'selection_started\':\n                    # Reserve 24 of the existing 256 slots for the returned window.\n                    # Only the observation sample rotates; business selection is untouched.\n                    self._selection_accounts = frozenset()\n                    if type(customers) is not tuple or any(type(cid) is not int or cid <= 0 for cid in customers):\n                        return\n                    ids = sorted(set(customers))\n                    if ids:\n                        count = min(self.MAX_ACCOUNTS - 24, len(ids))\n                        start = self._selection_offset % len(ids)\n                        self._selection_accounts = frozenset(ids[(start + i) % len(ids)] for i in range(count))\n                        self._selection_offset = (start + count) % len(ids)\n                    return\n                if event == \'performance_finished\':\n                    if type(customers) in (tuple, list, set, frozenset) and len(customers) <= 24 \\\n                            and all(type(cid) is int and cid > 0 for cid in customers):\n                        self._performance = frozenset(customers)\n                    else:\n                        self._cycle_at = self._global = self._window = None\n                    return\n                row = {\'version\': 1, \'scope\': \'process_memory\', \'current_job_match\': \'not_proven\',\n                       \'cycle_started_at\': self._cycle_at, \'observed_at\': at, \'in_latest_cycle\': True,\n                       \'event\': event, \'candidate_count\': None if self._window is None else len(self._window_accounts),\n                       \'calls_remaining\': calls_remaining, \'seconds_remaining\': seconds_remaining,\n                       \'budget_scope\': budget_scope, \'stored_status\': stored_status}\n                if event == \'candidate_window\':\n                    if type(jobs) not in (list, tuple) or len(jobs) > 24:\n                        return\n                    ids = [item.get(\'customer_id\') for item in jobs if type(item) is dict]\n                    if len(ids) != len(jobs) or any(type(cid) is not int or cid <= 0 for cid in ids):\n                        return\n                    self._window_accounts = frozenset(ids)\n                    row.update(event=\'window_not_returned\', candidate_count=len(jobs))\n                    self._window = dict(row)\n                    self._global = dict(row)\n                    for cid, (sequence, prior) in tuple(self._accounts.items()):\n                        if sequence == self._sequence and prior[\'event\'] in self.SELECTION_EVENTS:\n                            self._accounts[cid] = (sequence, dict(prior, candidate_count=len(jobs)))\n                    for cid in ids:\n                        self._put(cid, dict(row, event=\'candidate_returned\'))\n                    return\n                if type(job) is dict and type(job.get(\'customer_id\')) is int and job[\'customer_id\'] > 0:\n                    cid = job[\'customer_id\']\n                    if event == \'excluded\':\n                        if self._performance is None:\n                            self._cycle_at = self._global = self._window = None\n                            return\n                        row[\'event\'] = (\'performance_same_cycle_excluded\' if cid in self._performance\n                                        else \'earlier_lane_excluded\')\n                    self._put(cid, row)\n                else:\n                    self._global = row\n                    if event in (\'call_budget_exhausted\', \'time_budget_exhausted\', \'rate_limited\',\n                                 \'source_changed\', \'execution_error\'):\n                        for cid, (sequence, prior) in tuple(self._accounts.items()):\n                            if sequence == self._sequence and prior[\'event\'] == \'candidate_returned\':\n                                self._put(cid, dict(row))\n        except Exception:\n            # Failed clock/read observation is unavailable, not fresh evidence.\n            with self._lock:\n                self._global = self._window = None\n                if event == \'inventory_started\':\n                    self._cycle_at = None\n            return\n\n    def _put(self, cid, row):\n        self._accounts.pop(cid, None)\n        self._accounts[cid] = (self._sequence, row)\n        while len(self._accounts) > self.MAX_ACCOUNTS:\n            victim = next((key for key in self._accounts if key not in self._selection_accounts), None)\n            if victim is None:\n                victim = next(iter(self._accounts))\n            self._accounts.pop(victim)\n\n    def snapshot(self, possibility_id, customer_id):\n        """Read-only. Authority is resolved by the caller; no job/generation match is asserted."""\n        try:\n            if type(possibility_id) is not int or possibility_id <= 0 \\\n                    or type(customer_id) is not int or customer_id <= 0:\n                return None\n            with self._lock:\n                if self._global is None:\n                    return None\n                prior = self._accounts.get(customer_id)\n                if prior is not None and prior[0] == self._sequence:\n                    return dict(prior[1])\n                if self._window is not None and customer_id not in self._window_accounts:\n                    if prior is not None and prior[1][\'event\'] in self.SELECTION_EVENTS:\n                        return dict(prior[1], in_latest_cycle=False)\n                    return dict(self._window)\n                if self._global[\'event\'] not in (\'inventory_started\', \'lane_entered\'):\n                    return dict(self._global)\n                if prior is not None:\n                    return dict(prior[1], in_latest_cycle=False)\n                return dict(self._global)\n        except Exception:\n            return None\n'

class ProductBasisPatchTests(unittest.TestCase):
 def test_pending_fresh_target_scope_refuses_before_base_or_host_access(self):
  p=load('naver_report_progress_patch')
  values={key:None for key in ('TARGET_COMMIT','APPROVED_TARGET_COMMIT','TARGET_SOURCE_SHA256','APPROVED_TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','APPROVED_CANONICAL_SHA256','CI_PROOF','APPROVED_CI_PROOF','TARGET_DELTA','EXPECTED_TARGET_DELTA','APPROVED_AST_SCOPE','EXPECTED_AST_SCOPE')}
  with patch.multiple(p,**values):
   for key in ('TARGET_COMMIT','APPROVED_TARGET_COMMIT','TARGET_SOURCE_SHA256','APPROVED_TARGET_SOURCE_SHA256','TARGET_CANONICAL_SHA256','APPROVED_CANONICAL_SHA256','CI_PROOF','APPROVED_CI_PROOF','TARGET_DELTA','EXPECTED_TARGET_DELTA','APPROVED_AST_SCOPE','EXPECTED_AST_SCOPE'):self.assertIsNone(getattr(p,key))
   with self.assertRaisesRegex(ValueError,'PINS_PENDING'):p.require_target_pins()
   with self.assertRaisesRegex(ValueError,'PINS_PENDING'):p.bind_base(object())
 def test_actual_1fc_baseline_two_existing_paths_manifest166_same_store_schema_and_assets(self):
  p=pinned();self.assertEqual(p.OLD_COMMIT,'513e52eaee4d1bb722461961639cd588df9080cd')
  self.assertEqual((p.OLD_SCHEMA,p.TARGET_SCHEMA),(21,21));self.assertEqual(p.CODE_PATHS,PATHS);self.assertEqual(p.NEW_PATHS,frozenset())
  self.assertEqual((len(p.OLD_MANIFEST),len(p.TARGET_MANIFEST)),(166,166));self.assertEqual(set(p.OLD_MANIFEST),set(p.TARGET_MANIFEST))
  self.assertEqual({k for k in p.OLD_MANIFEST if p.OLD_MANIFEST[k]!=p.TARGET_MANIFEST[k]},PATHS)
  self.assertEqual(p.manifest_digest(p.OLD_MANIFEST),'fe006d69ffebae1b303e9914b139417f7f1ad461881e864b4951fa60253b486a');self.assertEqual(p.K_M,'744bc24aadadd683dec7fa4b99d33669996d0b92eae78b654884cf3f9f404950');self.assertEqual(p.I_M,'9de931063d86a011682a0e38568de36532d2fb47077f50cca0ddfe24ad2f1d9f')
  self.assertEqual(p.H_M,'51620b5091b7374d6739ff022f3eed09088751c6e3bcd21277e12d96d61d8fc5')
  self.assertEqual(p.STORE_SHA256['old'],p.STORE_SHA256['target']);self.assertEqual(p.ROLLBACK_COMMIT,p.OLD_COMMIT);self.assertEqual(set(p.OLD_REPORT_ASSETS),set(p.REPORT_ASSETS));self.assertEqual({key for key in p.REPORT_ASSETS if p.REPORT_ASSETS[key]!=p.OLD_REPORT_ASSETS[key]}, set())
 def test_all_old_history_and_new_c200_layer_and_receipt_pairs_cannot_mutate(self):
  for name,value in [('H_M','a'*64),('H_A','a'*64),('H_C','a'*40),('H_S','a'*64),('H_R','12345678901'),('H_O','a'*32),('H_D',{}),('Z_M','a'*64),('Z_A','a'*64),('Z_C','a'*40),('Z_S','a'*64),('Z_R','12345678901'),('Z_O','a'*32),('Z_D',{}),('F','a'*64),('G','a'*64),('A','a'*40),('B','a'*64),('C','12345678901'),('D','a'*32),('E',{}),('I_M','a'*64),('I_A','a'*64),('I_C','a'*40),('I_S','a'*64),('I_R','12345678901'),('I_O','a'*32),('I_D',{}),('K_C','a'*40),('K_S','a'*64),('K_R','12345678901'),('K_O','a'*32),('K_D',{}),('K_M','a'*64),('K_A','a'*64),('U_C','a'*40),('U_S','a'*64),('U_R','12345678901'),('U_O','a'*32),('U_D',{}),('U_M','a'*64),('U_A','a'*64),('W_C','a'*40),('W_S','a'*64),('W_R','12345678901'),('W_O','a'*32),('W_D',{}),('W_M','a'*64),('W_A','a'*64),('X_C','a'*40),('X_S','a'*64),('X_R','12345678901'),('X_O','a'*32),('X_D',{}),('X_M','a'*64),('X_A','a'*64),('Y_C','a'*40),('Y_S','a'*64),('Y_R','12345678901'),('Y_O','a'*32),('Y_D',{}),('Y_M','a'*64),('Y_A','a'*64),('BASE_PREPARE_RUN','38523201246'),('BASE_APPLY_OPERATION','a'*32)]:
   p=pinned();setattr(p,name,value)
   with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
 def test_foreign_new_missing_paths_and_previous_source_pins_refuse(self):
  for name,value in [('TARGET_COMMIT','513e52eaee4d1bb722461961639cd588df9080cd'),('TARGET_COMMIT','70045db75473407591d79c3bfa4e69cbb217f6b9'),('TARGET_COMMIT','9379023a7a13b0d71b79a57ebf8979591b574f9f'),('NEW_PATHS',frozenset({'unapproved.py'})),('CODE_PATHS',frozenset({'unapproved.py'})),('TARGET_COMMIT','b5e40fa01e6432ab0a62541c330652e1cb4fae2c'),('TARGET_COMMIT','114dde8a45e1753ade0ff871f024c7e5880546c5'),('TARGET_COMMIT','621c5efeaf607b8227898bdf65d3ef040d1740fa'),('TARGET_COMMIT','1fc2c92a18ea50dfef4e0b3da9ddd973f4017715'),('TARGET_COMMIT','7f138a8d42bb292567ccb3e117bd0305efc42ad7'),('OLD_COMMIT','7f138a8d42bb292567ccb3e117bd0305efc42ad7'),('OLD_SOURCE_SHA256','a'*64)]:
   p=pinned();setattr(p,name,value)
   with self.subTest(name=name),self.assertRaises(ValueError):p.require_pins()
 def test_exact_scope_field_shape_and_unapproved_ABI_remain_closed(self):
  p=pinned();self.assertEqual(set(p.APPROVED_AST_SCOPE),PYTHON_PATHS)
  for mutation in (lambda x:x.pop(CP),lambda x:x.update({'unapproved.py':{}}),lambda x:x[CP].update(optional_abi={'chosen':('bypass',)})):
   scope=deepcopy(p.APPROVED_AST_SCOPE);mutation(scope)
   with self.assertRaises(ValueError):p.validate_ast_scope(scope)
 def test_python_contract_accepts_only_approved_body_and_version_names(self):
  p=pinned();before,after=bodies();p.APPROVED_AST_SCOPE=fixture_scope();p.EXPECTED_CODE_PATHS=p.CODE_PATHS=frozenset(p.APPROVED_AST_SCOPE)
  for name in PYTHON_PATHS:p.python_contract(name,before[name],after[name])
  for name,bad in [(CP,after[CP]+b'UNAPPROVED=True\n'),(CP,b'import os\n'+after[CP]),(CP,after[CP].replace(b'chosen(context)',b'chosen(context,bypass=False)')),(CP,after[CP].replace(b'keep():return True',b'keep():return False')),(SCHEMA,after[SCHEMA].replace(b"return 'fixed'",b"return 'changed'"))]:
   with self.subTest(name=name),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(name,before[name],bad)
 def test_schema_basis_optional_ABI_is_one_exact_None_keyword_only_combination(self):
  p=pinned();legacy='naver_runtime/report_output_schema.py';p.EXPECTED_CODE_PATHS=p.CODE_PATHS=frozenset((CP,legacy));scope={CP:fixture_scope()[CP],legacy:fixture_scope()[SCHEMA]};scope[legacy]['optional_abi']={'output_format':('basis_ids',)};p.APPROVED_AST_SCOPE=p.EXPECTED_AST_SCOPE=scope;p.validate_ast_scope(scope)
  before=b"FORMAT_VERSION='v4'\ndef output_format(context):return {}\ndef text_pattern():return 'fixed'\n"
  after=b"FORMAT_VERSION='v5'\ndef output_format(context, *, basis_ids=None):return {'type':'json_schema'}\ndef text_pattern():return 'fixed'\n"
  p.python_contract(legacy,before,after)
  for signature in ('output_format(context, *, basis_ids=False)','output_format(context, *, basis_ids=())','output_format(context, basis_ids=None)','output_format(context, *, other=None)','output_format(other, *, basis_ids=None)','output_format(context, *, basis_ids=0)'):
   bad=after.replace(b'output_format(context, *, basis_ids=None)',signature.encode())
   with self.subTest(signature=signature),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(legacy,before,bad)
  # Generic optional-argument normalization permits a new argument annotation;
  # the unchanged exact inventory still rejects those unregistered bytes.
  annotated=after.replace(b'basis_ids=None',b'basis_ids: tuple=None');p.python_contract(legacy,before,annotated)
  with tempfile.TemporaryDirectory()as temp:
   old,new=Path(temp).resolve()/'old',Path(temp).resolve()/'new';old.mkdir();new.mkdir()
   before_cp,after_cp=bodies();before_map={CP:before_cp[CP],legacy:before};expected_map={CP:after_cp[CP],legacy:after};actual_map={**expected_map,legacy:annotated}
   for root,values in ((old,before_map),(new,actual_map)):
    for name,raw in values.items():
     (root/name).parent.mkdir(parents=True,exist_ok=True);(root/name).write_bytes(raw);(root/name).chmod(0o644)
   wanted=lambda raw:(420,len(raw),hashlib.sha256(raw).hexdigest())
   p.OLD_MANIFEST={name:wanted(raw)for name,raw in before_map.items()};p.TARGET_MANIFEST={name:wanted(raw)for name,raw in expected_map.items()}
   class Reader:
    def read_file(self,path,**kw):return path.read_bytes()
   with patch.object(p,'require_pins'),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.compatible_code_scope(old,new,Reader())
  for value in ({'output_format':('other',)},{'text_pattern':('basis_ids',)},{'output_format':['basis_ids']}):
   bad=deepcopy(scope);bad[legacy]['optional_abi']=value
   with self.subTest(value=value),self.assertRaises(ValueError):p.validate_ast_scope(bad)
 def test_all_prior_ABI_rows_and_both_generic_predicates_are_preserved(self):
  p=pinned()
  prior={'naver_engine/web.py':('App._learning_job_response',('finalization',),None,False),'naver_engine/execution_store.py':('ExecutionStorage.execution_record_spend',('campaign_budget_proof',),None,False),'naver_engine/naver_write.py':('issue_spend_handle',('campaign_budget_proof',),None,False),'naver_engine/inspection_reads.py':('_initial',('detail_reads',),False,False),'naver_engine/setup_checks.py':('_budget_item',('proof','now'),None,True)}
  for name,row in prior.items():self.assertEqual(p._abi(name),row)
  self.assertEqual(p._abi('naver_runtime/report_output_schema.py'),('output_format',('basis_ids',),None,False));self.assertIsNone(p._abi('unapproved.py'))
  old=ast.parse((TOOLS/'naver_budget_format_patch.py').read_bytes());new=ast.parse((TOOLS/'naver_report_progress_patch.py').read_bytes())
  for name in ('validate_ast_scope','python_contract'):
   a=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name==name);b=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name==name);self.assertEqual(ast.dump(a),ast.dump(inverse_approved_predicate(b,name)),name)
 def test_lifecycle_migration_off_and_security_function_AST_remain_original(self):
  old=ast.parse((TOOLS/'naver_budget_format_patch.py').read_bytes());new=ast.parse((TOOLS/'naver_report_progress_patch.py').read_bytes())
  for name in ('prepare','apply','rollback','compatible_inverse_source','compatible_code_scope','current_state','target_override','verify_running','target_engine_snapshot','runtime_flags','container_environment_flags','container_runtime_flags','stopped_writer','safe_source_path','preserve_approved_config','migration_contract'):
   a=next(n for n in old.body if isinstance(n,ast.FunctionDef)and n.name==name);b=next(n for n in new.body if isinstance(n,ast.FunctionDef)and n.name==name);self.assertEqual(ast.dump(a),ast.dump(b),name)
 def test_exact_receipt_chain_preserves7f_then_requires_applied_c200_uuid(self):
  p=pinned()
  with patch.object(p,'_receipt_step',return_value='proof')as check:
   self.assertEqual(p.inspection_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.proposal_success,p.H_C,p.H_S,p.H_R,p.F_C,p.H_O))
   self.assertEqual(p.funnel_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.inspection_success,p.Z_C,p.Z_S,'38523201246',p.H_C,'56e0a8bbfcf04b1e82129cdeffa28811'))
   self.assertEqual(p.Y('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.funnel_success,p.A,p.B,'38531626583',p.Z_C,'e5864b94306c4736a5ecadd10b16d998'))
   self.assertEqual(p.J('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.Y,p.I_C,p.I_S,'38543952683',p.A,'10469ee6378f4e36bc314f81cebb1d7d'))
   self.assertEqual(p.reference_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.J,p.K_C,p.K_S,'38553360666',p.I_C,'029616671477434c85f452206e09ecd0'))
   self.assertEqual(p.binding_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.reference_success,p.U_C,p.U_S,'38708112912',p.K_C,'dfdd1a4c72ed4cafa57e2bbe7af6d370'))
   self.assertEqual(p.text_pool_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.binding_success,p.W_C,p.W_S,'38726899460',p.U_C,'9e72159e3ce146a6ba2846396a6ce4b4'))
   self.assertEqual(p.worker_observation_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.text_pool_success,p.X_C,p.X_S,'38789089753',p.W_C,'e70966984fa04ac0b9ee046f6fd7b917'))
   self.assertEqual(p.selection_observation_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.worker_observation_success,p.Y_C,p.Y_S,'38838921412',p.X_C,'efe877fb1b314df897e1b4c9ca2cd998'))
   self.assertEqual(p.base_success('r','u'),'proof');self.assertEqual(check.call_args.args,('r','u',p.selection_observation_success,p.OLD_COMMIT,p.OLD_SOURCE_SHA256,'38847877253',p.Y_C,'0cf4c00158704aa5988365314c56312b'))
 def test_both_approved_paths_reach_strict_AST_and_then_final_inventory(self):
  p,reader,before,after=fixture()
  with patch.object(p,'python_contract',wraps=p.python_contract)as contract,patch.object(p,'compatible_code_scope')as inventory:p.compatible_source(Path('/old'),Path('/new'),reader)
  self.assertEqual({call.args for call in contract.call_args_list},{(name,before[name],after[name])for name in PYTHON_PATHS})
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
    for name,body in bodies_.items():
     (root/name).parent.mkdir(parents=True,exist_ok=True);(root/name).write_bytes(body);(root/name).chmod(0o644)
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


 def test_two_new_optional_abi_rows_have_exact_None_and_reject_wrong_defaults(self):
  p=pinned()
  for path,method,parameter,before in ((WEB,'App.__init__','inspection_worker_status',b'class App:\n def __init__(self, *, existing=None):pass\n'),('naver_engine/inspection_reads.py','run_inspection','observe',b'def run_inspection(reader,store,clock):pass\n'),('naver_engine/inspection_store.py','InspectionStorage.inspection_work','observe',b'class InspectionStorage:\n def inspection_work(self,now):pass\n')):
   scope=deepcopy(p.APPROVED_AST_SCOPE);scope[path]=dict(changed=(method,),added=(),removed=(),optional_abi={method:(parameter,)},imports_added=(),imports_removed=());p.APPROVED_AST_SCOPE=scope;p.EXPECTED_CODE_PATHS=p.CODE_PATHS=frozenset(scope);p.validate_ast_scope(scope)
   if path==WEB:after=before.replace(b'existing=None',b'existing=None, inspection_worker_status=None')
   elif path=='naver_engine/inspection_store.py':after=before.replace(b'now)',b'now, *, observe=None)')
   else:after=before.replace(b'clock)',b'clock, *, observe=None)')
   p.python_contract(path,before,after)
   for default in ('True','False','0','()'):
    with self.subTest(path=path,default=default),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(path,before,after.replace((parameter+'=None').encode(),(parameter+'='+default).encode()))
   bad=deepcopy(scope);bad[path]['optional_abi']={method:[parameter]}
   with self.assertRaisesRegex(ValueError,'PATCH_NOT_PINNED'):p.validate_ast_scope(bad)
 def test_exact_new_class_ast_and_unapproved_body_bases_decorators_classes_refuse(self):
  p=pinned();path='naver_runtime/runtime_status.py'
  approved=APPROVED_OBSERVATION_CLASS.encode();prefix=b"class RuntimeStatus:\n def snapshot(self):return 'fixed'\n";before=prefix+BASELINE_OBSERVATION_CLASS.encode();after=prefix+approved
  scope=deepcopy(p.APPROVED_AST_SCOPE);scope[path]={'added': ('InspectionWorkerObservation.SELECTION_EVENTS',), 'changed': ('InspectionWorkerObservation.__init__', 'InspectionWorkerObservation._put', 'InspectionWorkerObservation.note', 'InspectionWorkerObservation.snapshot'), 'imports_added': (), 'imports_removed': (), 'optional_abi': {}, 'removed': ()};p.APPROVED_AST_SCOPE=scope;p.EXPECTED_CODE_PATHS=p.CODE_PATHS=frozenset(scope);p.validate_ast_scope(scope);p.python_contract(path,before,after)
  for part in ('body','bases','decorator','existing','extra','nested'):
   tree=ast.parse(after);node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='InspectionWorkerObservation')
   if part=='body':next(n for n in node.body if isinstance(n,ast.Assign)).value=ast.Constant(value=255)
   elif part=='bases':node.bases.append(ast.Name(id='object',ctx=ast.Load()))
   elif part=='decorator':node.decorator_list.append(ast.Name(id='object',ctx=ast.Load()))
   elif part=='existing':tree.body[0].body[0].body=[ast.Return(value=ast.Constant(value=None))]
   elif part=='nested':next(n for n in node.body if isinstance(n,ast.FunctionDef)).body.append(ast.ClassDef(name='Unapproved',bases=[],keywords=[],body=[ast.Pass()],decorator_list=[],type_params=[]))
   else:tree.body.append(ast.ClassDef(name='Unapproved',bases=[],keywords=[],body=[ast.Pass()],decorator_list=[],type_params=[]))
   bad=ast.unparse(ast.fix_missing_locations(tree)).encode()
   with self.subTest(part=part),self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(path,before,bad)
  with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(path,after,after)


 def test_new_class_empty_type_params_are_canonical_and_nonempty_values_refuse(self):
  import types
  p=pinned();path='naver_runtime/runtime_status.py'
  prefix=b"class RuntimeStatus:\n def snapshot(self):return 'fixed'\n";before=prefix+BASELINE_OBSERVATION_CLASS.encode();after=prefix+APPROVED_OBSERVATION_CLASS.encode()
  scope=deepcopy(p.APPROVED_AST_SCOPE);scope[path]={'added': ('InspectionWorkerObservation.SELECTION_EVENTS',), 'changed': ('InspectionWorkerObservation.__init__', 'InspectionWorkerObservation._put', 'InspectionWorkerObservation.note', 'InspectionWorkerObservation.snapshot'), 'imports_added': (), 'imports_removed': (), 'optional_abi': {}, 'removed': ()};p.APPROVED_AST_SCOPE=scope;p.EXPECTED_CODE_PATHS=p.CODE_PATHS=frozenset(scope)
  real_parse=ast.parse
  for mode in ('missing','empty','class_nonempty','function_nonempty','malformed'):
   def parse(*args,**kwargs):
    tree=real_parse(*args,**kwargs)
    for root in tree.body:
     if not isinstance(root,ast.ClassDef) or root.name!='InspectionWorkerObservation':continue
     for node in ast.walk(root):
      if not isinstance(node,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):continue
      if mode=='missing':
       node._fields=tuple(field for field in node._fields if field!='type_params')
       if hasattr(node,'type_params'):del node.type_params
      else:
       if 'type_params' not in node._fields:node._fields=(*node._fields,'type_params')
       node.type_params=[]
       if mode=='class_nonempty' and isinstance(node,ast.ClassDef) or mode=='function_nonempty' and isinstance(node,ast.FunctionDef):node.type_params=[ast.Name(id='T',ctx=ast.Load())]
       elif mode=='malformed':node.type_params=None
    return tree
   local_ast=types.SimpleNamespace(**{key:getattr(ast,key)for key in dir(ast)if key!='parse'},parse=parse)
   with self.subTest(mode=mode),patch.object(p,'ast',local_ast):
    if mode in ('missing','empty'):p.python_contract(path,before,after)
    else:
     with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):p.python_contract(path,before,after)

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
