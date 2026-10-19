"""New epoch boundaries only; synthetic receipts, public source bytes, no operating I/O."""
import ast, copy, hashlib, json, subprocess, types, unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
TOOLS=ROOT/'backend/tools'
BASE_HEAD='a37187f684d78c7bb762fb70bf79ab821eef67d8'
DEPLOY=TOOLS
C7='c7b552d0415d1962263ab66f756339004af2a078'
B00='b00d6bf805b43b282c04dd95970ae9ccb7d8247d'
PATH='naver_engine/inspection_store.py'
# 711a245 keeps c7b552d's inspection_store.py bytes (same size and sha256) and adds four report files.
TARGET_PATHS={'backend/naver_page/operations-ui.js',PATH,'naver_engine/strategy_validation.py','naver_runtime/claude_provider.py','naver_runtime/report_output_schema.py'}
def load(path):
 m=types.ModuleType('synthetic_epoch');m.__file__=str(path);exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__);return m
def prior_raw(name):
 return subprocess.run(['git','show',BASE_HEAD+':backend/tools/'+name],cwd=ROOT,check=True,capture_output=True,timeout=10).stdout
def load_prior(name):
 raw=prior_raw(name);expected={'naver_report_progress_patch.py':'6c5428889dbe342acdce3777891db994ee9824dd679b8f2201bec53ab2b3a7a3','naver_report_progress_transport.py':'9199f710b50db07f3635d0b3230f47f3ad9c2e63d3f95ed1732c540efe9b50b0'}
 if hashlib.sha256(raw).hexdigest()!=expected[name]:raise AssertionError('historical public source')
 m=types.ModuleType('historical_public');exec(compile(raw,'<historical-public>','exec'),m.__dict__);return m
def source(commit,path):
 if path==PATH:return SOURCE_FUNCTION_FIXTURES[commit]
 if path=='naver_engine/store.py':return b"SCHEMA_VERSION=21\n_SCHEMA=''\n_REVISION_COLUMNS={}\ndef _migrate():pass\n"
 raise AssertionError('fixed public fixture only')
def bound():
 c=load(TOOLS/'naver_report_progress_patch.py');c.bind_base(load(DEPLOY/'naver_preview_completion_release.py'));return c
# Exact approved function excerpts; surrounding inventory/source hashes are checked separately.
SOURCE_FUNCTION_FIXTURES = {'b00d6bf805b43b282c04dd95970ae9ccb7d8247d': b'class InspectionStorage:\n\n    def _inspection_continuity_scopes(self, c, catalog, now, customers):\n        """Bounded hashes only; actual matching sees the full current catalog.\n\n        Deliberately conservative: account snapshot, organization semantic epoch,\n        every ID claim and policy event remain exact. Only unrelated company\n        content may vary when the actual target match and full target row agree.\n        """\n        from dataclasses import asdict\n        from . import inventory as I, management_store as MS, sync as Y\n        from app.naver_auto import org_snapshot as O\n        S = _storage()\n        try:\n            snapshot = self.inventory_snapshot(now)\n            organization, sync = (self.org_current(), self.last_sync(S.SYNC_ORG))\n            if catalog is None or snapshot is None or organization is None or (sync is None) or (sync[\'outcome\'] != S.SYNC_ACCEPTED) or (not O.allows_raising(Y.org_freshness(self, now))):\n                return {}\n            accounts = {row[\'customer_id\']: row for row in self.accounts()}\n            states = self.management_states()\n            matches = MS.matching_result(self, accounts, self.current_decisions(), catalog, I.automatic_evidence(self))[0]\n            pairs = {pair.customer_id: pair for pair in matches.pairs}\n            companies = {row[\'possibility_id\']: row for row in catalog[\'items\']}\n            org_epoch = IC.org_continuity_epoch(self._inspection_read_proof(c, IC.ORG_CONTINUITY_KEY, 4096), organization[\'body\'])\n            if org_epoch is None:\n                return {}\n            common = dict(snapshot=S._kst_text(snapshot, \'\xea\xb3\x84\xec\xa0\x95 \xec\x9b\x90\xec\xb2\x9c\'), org_epoch=org_epoch, matching=self.decision_fingerprint(), claims=IC._hash(sorted(catalog[\'ids\'], key=IC._dump)), companies=sorted(companies))\n            common_hash = IC._hash(common)\n            result = {}\n            for cid in customers:\n                pair, state, account = (pairs.get(cid), states.get(cid), accounts.get(cid))\n                if not pair or not state or (not account) or (account[\'present\'] != 1) or (pair.possibility_id != state[\'possibility_id\']):\n                    continue\n                company = companies.get(pair.possibility_id)\n                if company is None or not company[\'stage_known\'] or company[\'stage_hidden\']:\n                    continue\n                event = c.execute(\'SELECT MAX(event_id) FROM naver_auto_management_event WHERE customer_id=?\', (cid,)).fetchone()[0]\n                result[cid] = IC._hash(dict(common_hash=common_hash, account=account, company=company, pair=asdict(pair), policy=state, policy_event=event))\n            return result\n        except (KeyError, TypeError, ValueError, OverflowError, RecursionError, S.StoreRefused):\n            return {}\n', 'c7b552d0415d1962263ab66f756339004af2a078': b'class InspectionStorage:\n\n    def _inspection_continuity_scopes(self, c, catalog, now, customers):\n        """Bounded hashes only; actual matching sees the full current catalog.\n\n        Account snapshot, organization semantic epoch, global human decisions,\n        target-related raw ID claims and policy events remain exact. Full catalog\n        matching still sees every company and ID row before target scopes form.\n        """\n        from dataclasses import asdict\n        from . import inventory as I, management_store as MS, sync as Y\n        from app.naver_auto import org_snapshot as O\n        S = _storage()\n        try:\n            snapshot = self.inventory_snapshot(now)\n            organization, sync = (self.org_current(), self.last_sync(S.SYNC_ORG))\n            if catalog is None or snapshot is None or organization is None or (sync is None) or (sync[\'outcome\'] != S.SYNC_ACCEPTED) or (not O.allows_raising(Y.org_freshness(self, now))):\n                return {}\n            accounts = {row[\'customer_id\']: row for row in self.accounts()}\n            states = self.management_states()\n            matches = MS.matching_result(self, accounts, self.current_decisions(), catalog, I.automatic_evidence(self))[0]\n            pairs = {pair.customer_id: pair for pair in matches.pairs}\n            companies = {row[\'possibility_id\']: row for row in catalog[\'items\']}\n            org_epoch = IC.org_continuity_epoch(self._inspection_read_proof(c, IC.ORG_CONTINUITY_KEY, 4096), organization[\'body\'])\n            if org_epoch is None:\n                return {}\n            common = dict(snapshot=S._kst_text(snapshot, \'\xea\xb3\x84\xec\xa0\x95 \xec\x9b\x90\xec\xb2\x9c\'), org_epoch=org_epoch, matching=self.decision_fingerprint())\n            claims_by_pid, claims_by_customer = ({}, {})\n            ad_owners = {str(row[\'ad_account_no\']): cid for cid, row in accounts.items() if row[\'present\'] == 1}\n            for index, claim in enumerate(catalog[\'ids\']):\n                claims_by_pid.setdefault(claim[\'possibility_id\'], set()).add(index)\n                if claim[\'vendor\'] != I.M.VENDOR_NAVER:\n                    continue\n                claimed, _ = I.M.parse_customer_id(claim[\'customer_id_raw\'])\n                targets = {claimed} if claimed in accounts else set()\n                explicit = claim[\'ad_account_no_raw\'] not in (None, \'\')\n                by_number = ad_owners.get(claim[\'ad_account_no_raw\'] if explicit else str(claimed))\n                if by_number is not None:\n                    targets.add(by_number)\n                for target in targets:\n                    claims_by_customer.setdefault(target, set()).add(index)\n            common_hash = IC._hash(common)\n            result = {}\n            for cid in customers:\n                pair, state, account = (pairs.get(cid), states.get(cid), accounts.get(cid))\n                if not pair or not state or (not account) or (account[\'present\'] != 1) or (pair.possibility_id != state[\'possibility_id\']):\n                    continue\n                company = companies.get(pair.possibility_id)\n                if company is None or not company[\'stage_known\'] or company[\'stage_hidden\']:\n                    continue\n                event = c.execute(\'SELECT MAX(event_id) FROM naver_auto_management_event WHERE customer_id=?\', (cid,)).fetchone()[0]\n                indices = claims_by_pid.get(pair.possibility_id, set()) | claims_by_customer.get(cid, set())\n                claims = sorted((catalog[\'ids\'][index] for index in indices), key=IC._dump)\n                result[cid] = IC._hash(dict(common_hash=common_hash, account=account, company=company, pair=asdict(pair), policy=state, policy_event=event, claims=IC._hash(claims)))\n            return result\n        except (KeyError, TypeError, ValueError, OverflowError, RecursionError, S.StoreRefused):\n            return {}\n'}
class EpochTest(unittest.TestCase):
 def test_manifest_baseline_b00_and_exact_one_target_file(self):
  c=bound();old=load_prior('naver_report_progress_patch.py');old.bind_base(c.BASE)
  self.assertEqual(c.OLD_MANIFEST,old.TARGET_MANIFEST);self.assertEqual(len(c.TARGET_MANIFEST),166)
  self.assertEqual({n for n in c.OLD_MANIFEST if c.OLD_MANIFEST[n]!=c.TARGET_MANIFEST[n]},TARGET_PATHS)
  self.assertEqual(c.TARGET_MANIFEST[PATH],(420,62048,'7e4d6990f0bf44900e334574784da817e8df3bb2e5fba00cde4c9da9ec289de2'))
  self.assertEqual({k for k in c.REPORT_ASSETS if c.REPORT_ASSETS[k]!=c.OLD_REPORT_ASSETS[k]},{'/naver/operations-ui.js'})
  self.assertEqual(c.REPORT_ASSETS['/naver/operations-ui.js'][:2],(35766,'30961f52726507a6302db7159788d2661f7b5ab1554fd86f0b80837cf6587cf9'))
  self.assertEqual(c.STORE_SHA256['old'],c.STORE_SHA256['target']);self.assertEqual(c.OLD_SCHEMA,c.TARGET_SCHEMA)
 def test_historical_pins_tamper_rejected(self):
  for key,value in [('E21_R','38852615205'),('E21_O','0'*32),('B00_M','0'*64),('B00_D',{})]:
   with self.subTest(key=key):
    c=bound();setattr(c,key,value)
    with self.assertRaisesRegex(ValueError,'PATCH_SCOPE'):c.require_pins()
 def fixture(self,c):
  f={'/synthetic-secret/sentinel':'synthetic-digest-only'}
  commits=[(c.E21_C,c.E21_S,c.E21_R,c.SR_C,c.E21_O),(c.OLD_COMMIT,c.OLD_SOURCE_SHA256,c.BASE_PREPARE_RUN,c.E21_C,c.BASE_APPLY_OPERATION)]
  prepared={};started={};seen=[]
  for commit,archive,run,previous,op in commits:
   prepared[commit]={'package':{'source_tar_gz_sha256':archive,'run_id':run,'baseline':c.EXPECTED_BASELINE},'runtime_environment_preserved':True,'config_operation_id':c.APPROVED_CONFIG_OPERATION_ID,'runtime_flags_verified':True,'inventory_enabled':True,'execution_enabled':False,'files':dict(f)}
   started[commit]={'ok':True,'stage':'internal_ready','source_commit':commit,'previous_commit':previous,'operation_id':op,'database_policy':'preserve-in-place','database_schema':21,'database_opened_by_controller':False,'database_snapshot_verified':False,'source_warmup_performed':False,'rollback_requires_matching_database':False,'runtime_flags_verified':True,'execution_enabled':False,'saved_export_companion_preserved':True}
  def manifest(release,commit,started):seen.append(commit);return Path('/synthetic'),prepared[commit]
  def read(path,**kw):
   self.assertEqual(kw,{'mode':384,'maximum':32768})
   return json.dumps(started[path.name[len('preview-start-'):-len('.json')]],sort_keys=True).encode()
  def unique(pairs):
   result={}
   for k,v in pairs:
    if k in result:raise ValueError('DUPLICATE')
    result[k]=v
   return result
  release=types.SimpleNamespace(ROOT=Path('/synthetic'),SECRET_ROOT=Path('/synthetic-secret'),SECRET_OWNERS=('sentinel',),unique=unique)
  upgrade=types.SimpleNamespace(manifest=manifest,read_file=read)
  c.selection_fairness_success=lambda *_:(None,{'files':dict(f)},b'prior-chain')
  return release,upgrade,prepared,started,seen
 def test_both_receipt_epochs_contribute_to_chain(self):
  c=bound();r,u,p,s,seen=self.fixture(c);_,receipt,chain=c.base_success(r,u)
  expected=b'prior-chain'
  for commit in (c.E21_C,c.OLD_COMMIT):expected=hashlib.sha256(expected+b'\0'+json.dumps(s[commit],sort_keys=True).encode()).digest()
  self.assertEqual(chain,expected);self.assertIs(receipt,p[c.OLD_COMMIT]);self.assertEqual(seen,[c.E21_C,c.OLD_COMMIT])
 def test_new_baseline_wrong_prepare_operation_and_guards_rejected(self):
  changes=[('package','run_id','38949191130'),('started','operation_id','0'*32),('started','previous_commit','0'*40),('prepared','config_operation_id','0'*32),('started','execution_enabled',True),('started','database_schema',True),('prepared','runtime_environment_preserved',False)]
  for area,key,value in changes:
   with self.subTest(area=area,key=key):
    c=bound();r,u,p,s,_=self.fixture(c)
    target=p[c.OLD_COMMIT]['package'] if area=='package' else s[c.OLD_COMMIT] if area=='started' else p[c.OLD_COMMIT]
    target[key]=value
    with self.assertRaisesRegex(ValueError,'PATCH_BASELINE'):c.base_success(r,u)
 def test_old_epoch_cannot_be_skipped_or_rewritten(self):
  c=bound();r,u,p,s,seen=self.fixture(c);s[c.E21_C]['operation_id']=c.BASE_APPLY_OPERATION
  with self.assertRaisesRegex(ValueError,'PATCH_BASELINE'):c.base_success(r,u)
  self.assertEqual(seen,[c.E21_C])
 def test_one_function_scope_and_unrelated_edit_refusal(self):
  c=bound();before=source(B00,PATH);after=source(C7,PATH);c.python_contract(PATH,before,after)
  wrong=after+b'\nEXTRA_UNAPPROVED_CONSTANT = 1\n'
  with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):c.python_contract(PATH,before,wrong)
  with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):c.python_contract(PATH,before,before)
 def test_store_identical_and_original_protection_functions_unchanged(self):
  c=bound();before=source(B00,'naver_engine/store.py');after=source(C7,'naver_engine/store.py')
  self.assertEqual(before,after);self.assertEqual(c.STORE_SHA256['old'],c.STORE_SHA256['target']);c.STORE_SHA256={k:hashlib.sha256(before).hexdigest() for k in ('old','target')};c.migration_contract(before,after)
  names={'_receipt_step','historical_success','preserve_approved_config','current_state','migration_contract','_store_runtime_contract','python_contract','compatible_source','prepare','apply','rollback'}
  def functions(raw):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef)}
  original=functions(prior_raw('naver_report_progress_patch.py'));candidate=functions((TOOLS/'naver_report_progress_patch.py').read_bytes())
  for name in names:self.assertEqual(original[name],candidate[name],name)
 def test_pending_full_qualification_refuses_before_io(self):
  c=bound();t=load(TOOLS/'naver_report_progress_transport.py');c.TARGET_CANONICAL_SHA256=None
  with patch('pathlib.Path.read_bytes',side_effect=AssertionError('unexpected I/O')):
   with self.assertRaisesRegex(ValueError,'DETAIL_AI_PINS_PENDING'):c.require_target_pins()
   with self.assertRaisesRegex(ValueError,'DETAIL_AI_PINS_PENDING'):t.require_pins()
 def test_transport_nine_dependencies_caps_and_codec_unchanged(self):
  before=load_prior('naver_report_progress_transport.py');after=load(TOOLS/'naver_report_progress_transport.py')
  self.assertEqual({k:v for k,v in before.SOURCE_SHA256.items() if k!='patch'},{k:v for k,v in after.SOURCE_SHA256.items() if k!='patch'})
  self.assertEqual(len(after.SOURCE_SHA256)-1,9)
  for name in ('MAX_JSON','MAX_WIRE','MAX_SOURCE','MAX_BOOTSTRAP_B64','MAX_SSH','SOURCE_FILES'):self.assertEqual(getattr(before,name),getattr(after,name))
  a={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(prior_raw('naver_report_progress_transport.py')).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
  b={n.name:ast.dump(n,include_attributes=False) for n in ast.parse((TOOLS/'naver_report_progress_transport.py').read_bytes()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
  self.assertEqual({k:v for k,v in a.items() if k!='require_pins'},{k:v for k,v in b.items() if k!='require_pins'})
  body=(TOOLS/'naver_report_progress_patch.py').read_text();compacted=after.compact(body)
  self.assertEqual(ast.dump(ast.parse(body)),ast.dump(ast.parse(compacted)))
if __name__=='__main__':unittest.main()
