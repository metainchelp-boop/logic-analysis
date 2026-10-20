"""New epoch boundaries only; synthetic receipts, public source bytes, no operating I/O."""
import ast, copy, hashlib, json, subprocess, types, unittest
from pathlib import Path
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
TOOLS=ROOT/'backend/tools'
BASE_HEAD='4522a8bbcfed7a17cd3cb044737f24226d697978'
DEPLOY=TOOLS
T711='711a245ea14b590a83eb6746b760ce53275b6602'
R1='382f143ad72a5fb0389d79ba0fac199566016e8b'
PATH='naver_engine/backup.py'
# 382f143 changes only the backup restore cap constant over the running 711a245.
TARGET_PATHS={PATH}
def load(path):
 m=types.ModuleType('synthetic_epoch');m.__file__=str(path);exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__);return m
def prior_raw(name):
 return subprocess.run(['git','show',BASE_HEAD+':backend/tools/'+name],cwd=ROOT,check=True,capture_output=True,timeout=10).stdout
def load_prior(name):
 raw=prior_raw(name);expected={'naver_report_progress_patch.py':'4c2f4c91ab0b25debac9a9a23580e84d3ebe7aba6ce252fec46a6720e083095c','naver_report_progress_transport.py':'0456361b2e5ba5125119990019e7ae93de2818d6b9e3930b26b977b5ee3b3173'}
 if hashlib.sha256(raw).hexdigest()!=expected[name]:raise AssertionError('historical public source')
 m=types.ModuleType('historical_public');exec(compile(raw,'<historical-public>','exec'),m.__dict__);return m
def source(commit,path):
 if path==PATH:return SOURCE_FUNCTION_FIXTURES[commit]
 if path=='naver_engine/store.py':return b"SCHEMA_VERSION=21\n_SCHEMA=''\n_REVISION_COLUMNS={}\ndef _migrate():pass\n"
 raise AssertionError('fixed public fixture only')
def bound():
 c=load(TOOLS/'naver_report_progress_patch.py');c.bind_base(load(DEPLOY/'naver_preview_completion_release.py'));return c
# Exact module-level excerpts of naver_engine/backup.py (everything above class BackupError) at each commit;
# the full files are pinned separately by the manifest rows (16760 B 1bc2561e... -> 17027 B d783dea4...).
SOURCE_FUNCTION_FIXTURES = {T711: '"""S14 백업 파일 처리. DB/암호화 실행/전송은 주입한 함수만 사용한다.\n\n로컬 압축본과 보내는 암호문은 다른 private 폴더에 둔다. READY는 전송 성공이\n아니다. 수신 영수증의 파일 해시와 길이가 맞아야 OFFSITE_OK가 된다.\n"""\nfrom __future__ import annotations\n\nimport hashlib\nimport json\nimport os\nimport pathlib\nimport re\nimport shutil\nimport stat\nimport tempfile\nimport uuid\nimport zipfile\nfrom dataclasses import dataclass, field, replace\nfrom datetime import date, datetime, timedelta, timezone\nfrom typing import Callable, Mapping, Optional\n\nNAME = re.compile(r"naver-(\\d{8}T\\d{6}Z)-[0-9a-f]{32}\\.(zip|cms)\\Z")\nMAX_BYTES = 2 * 1024 * 1024 * 1024\nUTC = timezone.utc\nKST = timezone(timedelta(hours=9))\nSTATUS_CODES = frozenset({"NEVER", "IN_PROGRESS", "LOCAL_FAILED", "ENCRYPTION_FAILED", "READY",\n                          "LOCAL_READY", "UPLOAD_FAILED", "OFFSITE_OK", "RETENTION_FAILED"})\n\n\n'.encode(),
 R1: '"""S14 백업 파일 처리. DB/암호화 실행/전송은 주입한 함수만 사용한다.\n\n로컬 압축본과 보내는 암호문은 다른 private 폴더에 둔다. READY는 전송 성공이\n아니다. 수신 영수증의 파일 해시와 길이가 맞아야 OFFSITE_OK가 된다.\n"""\nfrom __future__ import annotations\n\nimport hashlib\nimport json\nimport os\nimport pathlib\nimport re\nimport shutil\nimport stat\nimport tempfile\nimport uuid\nimport zipfile\nfrom dataclasses import dataclass, field, replace\nfrom datetime import date, datetime, timedelta, timezone\nfrom typing import Callable, Mapping, Optional\n\nNAME = re.compile(r"naver-(\\d{8}T\\d{6}Z)-[0-9a-f]{32}\\.(zip|cms)\\Z")\n# 복원 검증이 받는 snapshot.sqlite 상한. 운영 DB 가 2 GiB 를 넘어(2026-10-20 실측 2.18 GiB) 밤 백업이\n# 정상으로 만들어져도 복원 검증이 거절하던 것을 막는다. 압축본 자체 상한(restore_check)도 이 값을 따른다.\nMAX_BYTES = 16 * 1024 * 1024 * 1024\nUTC = timezone.utc\nKST = timezone(timedelta(hours=9))\nSTATUS_CODES = frozenset({"NEVER", "IN_PROGRESS", "LOCAL_FAILED", "ENCRYPTION_FAILED", "READY",\n                          "LOCAL_READY", "UPLOAD_FAILED", "OFFSITE_OK", "RETENTION_FAILED"})\n\n\n'.encode()}
class EpochTest(unittest.TestCase):
 def test_manifest_baseline_711_and_exact_one_target_file(self):
  c=bound();old=load_prior('naver_report_progress_patch.py');old.bind_base(c.BASE)
  self.assertEqual(c.OLD_MANIFEST,old.TARGET_MANIFEST);self.assertEqual(len(c.TARGET_MANIFEST),166)
  self.assertEqual({n for n in c.OLD_MANIFEST if c.OLD_MANIFEST[n]!=c.TARGET_MANIFEST[n]},TARGET_PATHS)
  self.assertEqual(c.TARGET_MANIFEST[PATH],(420,17027,'d783dea45821e22be8ac1ea6a677bc1fc8929523c21ebfcd4b00e0e11416913d'))
  self.assertEqual(c.REPORT_ASSETS,c.OLD_REPORT_ASSETS)
  self.assertEqual((c.OLD_COMMIT,c.ROLLBACK_COMMIT,c.BASE_PREPARE_RUN,c.BASE_APPLY_OPERATION),(T711,T711,'39259799686','e50d76775650a9382a52bfae563af893'))
  self.assertEqual(c.STORE_SHA256['old'],c.STORE_SHA256['target']);self.assertEqual(c.OLD_SCHEMA,c.TARGET_SCHEMA)
 def test_historical_pins_tamper_rejected(self):
  for key,value in [('E21_R','38852615205'),('E21_O','0'*32),('B00_M','0'*64),('B00_D',{}),('B0_C','0'*40),('B0_S','0'*64),('B0_R','39108589826'),('B0_O','0'*32),('T7_M','0'*64),('T7_D',{}),('BASE_PREPARE_RUN','39259799687'),('BASE_APPLY_OPERATION','0'*32)]:
   with self.subTest(key=key):
    c=bound();setattr(c,key,value)
    with self.assertRaisesRegex(ValueError,'PATCH_SCOPE'):c.require_pins()
 def fixture(self,c):
  f={'/synthetic-secret/sentinel':'synthetic-digest-only'}
  commits=[(c.E21_C,c.E21_S,c.E21_R,c.SR_C,c.E21_O),(c.B0_C,c.B0_S,c.B0_R,c.E21_C,c.B0_O),(c.OLD_COMMIT,c.OLD_SOURCE_SHA256,c.BASE_PREPARE_RUN,c.B0_C,c.BASE_APPLY_OPERATION)]
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
  for commit in (c.E21_C,c.B0_C,c.OLD_COMMIT):expected=hashlib.sha256(expected+b'\0'+json.dumps(s[commit],sort_keys=True).encode()).digest()
  self.assertEqual(chain,expected);self.assertIs(receipt,p[c.OLD_COMMIT]);self.assertEqual(seen,[c.E21_C,c.B0_C,c.OLD_COMMIT])
 def test_new_baseline_wrong_prepare_operation_and_guards_rejected(self):
  changes=[('package','run_id','39108589825'),('started','operation_id','0'*32),('started','previous_commit','0'*40),('prepared','config_operation_id','0'*32),('started','execution_enabled',True),('started','database_schema',True),('prepared','runtime_environment_preserved',False)]
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
  c=bound();r,u,p,s,seen=self.fixture(c);s[c.B0_C]['operation_id']=c.BASE_APPLY_OPERATION
  with self.assertRaisesRegex(ValueError,'PATCH_BASELINE'):c.base_success(r,u)
  self.assertEqual(seen,[c.E21_C,c.B0_C])
 def test_one_function_scope_and_unrelated_edit_refusal(self):
  c=bound();before=source(T711,PATH);after=source(R1,PATH);c.python_contract(PATH,before,after)
  wrong=after+b'\nEXTRA_UNAPPROVED_CONSTANT = 1\n'
  with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):c.python_contract(PATH,before,wrong)
  with self.assertRaisesRegex(ValueError,'CODE_SCOPE_CHANGED'):c.python_contract(PATH,before,before)
 def test_store_identical_and_original_protection_functions_unchanged(self):
  c=bound();before=source(T711,'naver_engine/store.py');after=source(R1,'naver_engine/store.py')
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
