"""Fixed readonly-audit qualification; no SSH/host execution in this module."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

REPO='metainchelp-boop/logic-analysis'
BRANCH='codex/naver-claude-reference-ops-20261011'
BASE='backend/tools/naver_market_operation_invocation/'
WORKFLOW='.github/workflows/naver-market-operation-invocation.yml'
NATIVE_WORKFLOW='.github/workflows/naver-product-export-tests.yml'
NATIVE_WORKFLOW_PIN='d6f504478e5141d7861a278013fd26f99a73347f26a829dcbc7568f41fc40289'
CONFIRM='READ_MARKET_OPERATION_INVOCATION_ONCE'
PAIR=('7abd8b3965ed4b51a3b071cd218e024f','4aa3189c384847178ecafbfa34eb060e')
BUILD_MARKER='NAVER_MARKET_OPERATION_INVOCATION_QUALIFICATION_V1='
TARGET_PROVENANCE={'pair': ['7abd8b3965ed4b51a3b071cd218e024f','4aa3189c384847178ecafbfa34eb060e'], 'plan_sha256': 'b9b63866d280845df60d99aa0ba7c5f0d00f90b128583c291abfe1a542ed35a3', 'ledger': {'run_id': 39097606812, 'receipt_sha256': '7dcdfc8b2ef2bf99766b2bd59595b27b22da3c6407fbcca0b735d96e95dfe3c6'}, 'restored_rollback': {'run_id': 39095445014, 'receipt_sha256': 'd11910a1312430ca5f69bf3318b7d9b044f87ae0d0bd67fc442a5bd0dee0db2e'}, 'prior_apply_step': {'run_id': 39092917351, 'receipt_sha256': 'e38e550f57d4d3d11e00407e2f6d615c1e517c04a9a52e301bf25b6ddd49ca0b', 'window_utc': ['2026-10-18T03:14:45Z','2026-10-18T03:15:18Z'], 'host_clock_equivalence_proven': False}}
DEPENDENCY_BASE='backend/tools/naver_market_diagnostic_transition/qualification_deps/'
DEPENDENCIES={
 'native_contract':'7c157b45c150f3597e9e126b0d6a2348d9fb90421976c534591426d268f2303a',
 'workflow_delivery':'8379ed5d1d6bfe69f8e5bfe1c9d0dfa1f4f464d5363aaaf8d01ccfd66a3cda51',
 'fixed_actions_api':'fa5b25f8a64ad98b1bad2f9008003654eef98f03976c7c4992a0be3909f4befc'}
# Populated only from completed reviewed bytes, before any CI integration.
SOURCE_PINS={'core.py': 'b03caa1cb0b886e3098b1446dd70c953f05da90abbc449a901ffd74b7449f8e1', 'test_core.py': '96ac18a98104afa71e59b70a0bc2779ce159230703842ca58e7213c774e4b6e3', 'linux_fixture.py': '75b9db211c5367ed3830a18162dfef6a4b5d7b5154d085bb3d9f02235d040d2f', 'delivery.py': '9d1d780bafb2a15122001dc772d5e97eef47a58b5ebed5d83d28a0898eed34be', 'receiver.py': '3edeeb876071d25a0903c91d2c1f3e1d82e3f074dc35c518977bec766d08476a', 'test_delivery.py': '6a09d1c17392c90f1afbfb2e5981d9fc40a91546c9c515656aefb779c7370aff', 'ci.py': '576cbfe8e012be6c6469df34c6ce483ae3ded293201c9937ff01b016e94cb194'}
CORE_TEST_COUNT=22
DELIVERY_TEST_COUNT=18
FIXTURE_EXPECTED={'version': 1, 'status': 'passed', 'stage': 'complete', 'checks': {'hosted_root_gate': True, 'fixed_core_pin': True, 'unit_paths_initially_absent': True, 'exact_created_files': True, 'two_single_start_attempts': True, 'pid1_metadata_without_message': True, 'success_terminal': True, 'failure_terminal': True, 'parser_closed_result': True, 'owned_cleanup': True}, 'core_sha256': 'b03caa1cb0b886e3098b1446dd70c953f05da90abbc449a901ffd74b7449f8e1', 'operating_observed': False, 'database_opened': False, 'message_requested': False, 'fixture_units_started': 2}
AUDIT_STEPS=('Checkout exact source','Python 3.12','Check readonly transport and core',
 'Qualify readonly audit on empty Linux root','Retain only closed audit qualification')
DISPATCH_STEPS=('Checkout exact source','Python 3.12','Validate readonly qualifications and build script','Read fixed operation invocation metadata once')
BUILD_WRAPPER='Build appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262'
MAX_REGISTRY=32768

class Refused(ValueError):pass

def need(value,code):
 if value is not True:raise Refused(code)

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def sha(value):return hashlib.sha256(value).hexdigest()
def same(a,b):return canonical(a)==canonical(b)
def positive(v):return type(v) is int and 0<v<2**63
def digest(v,n=64):return type(v) is str and re.fullmatch('[0-9a-f]{'+str(n)+'}',v) is not None

def read(root,relative,pin=None,maximum=131072):
 root=Path(root).absolute();path=root/relative
 need(type(relative) is str and not relative.startswith('/') and '..' not in Path(relative).parts,'SOURCE_PATH')
 need(path.is_relative_to(root) and not any(p.is_symlink() for p in (path,*path.parents)),'SOURCE_PATH')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  before=os.fstat(fd)
  need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<=maximum,'SOURCE_FILE')
  body=bytearray()
  while len(body)<=maximum:
   part=os.read(fd,min(65536,maximum+1-len(body)))
   if not part:break
   body.extend(part)
  after=os.fstat(fd);named=path.stat(follow_symlinks=False)
  identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
  need(identity(before)==identity(after)==identity(named) and len(body)==before.st_size,'SOURCE_CHANGED')
 finally:os.close(fd)
 body=bytes(body)
 if pin is not None:need(digest(pin) and sha(body)==pin,'SOURCE_PIN')
 return body

@contextlib.contextmanager
def dependencies(root):
 need(not any(n in sys.modules for n in DEPENDENCIES),'MODULE_COLLISION')
 buffers={n:read(root,DEPENDENCY_BASE+n+'.py',pin) for n,pin in DEPENDENCIES.items()}
 loaded={}
 try:
  for name,body in buffers.items():
   m=types.ModuleType(name);sys.modules[name]=m;loaded[name]=m
   exec(compile(body,'<exact-readonly-dependency>','exec'),m.__dict__)
  yield loaded
 finally:
  for name,m in loaded.items():
   if sys.modules.get(name) is m:del sys.modules[name]


def registration(root):
 expected={'core.py','test_core.py','linux_fixture.py','delivery.py','receiver.py','test_delivery.py','ci.py'}
 need(type(SOURCE_PINS) is dict and set(SOURCE_PINS)==expected and all(digest(v) for v in SOURCE_PINS.values()),'REGISTRATION_REQUIRED')
 need(positive(CORE_TEST_COUNT) and positive(DELIVERY_TEST_COUNT) and type(FIXTURE_EXPECTED) is dict,'REGISTRATION_REQUIRED')
 bodies={n:read(root,BASE+n,pin,49152 if n=='core.py' else 131072) for n,pin in SOURCE_PINS.items()}
 outward=dict(schema='readonly-operation-invocation-source-v1',pair=list(PAIR),sources=dict(SOURCE_PINS),dependencies=dict(DEPENDENCIES),target=TARGET_PROVENANCE,
  qualifier_sha256=sha(read(root,BASE+'qualification.py')),workflow_sha256=sha(read(root,WORKFLOW)),
  native_workflow_sha256=sha(read(root,NATIVE_WORKFLOW,NATIVE_WORKFLOW_PIN)),
  counts=dict(core=CORE_TEST_COUNT,delivery=DELIVERY_TEST_COUNT),fixture=FIXTURE_EXPECTED)
 return bodies,outward


def steps(job,required,*,docker=False):
 rows=job.get('steps');need(type(rows) is list and 0<len(rows)<=64,'STEPS')
 names=[];numbers=[];selected={};build_seen=False
 wrappers={'Set up job','Post Python 3.12','Post Checkout exact source','Complete job'}
 for row in rows:
  need(type(row) is dict and positive(row.get('number')) and row.get('status')=='completed' and row.get('conclusion')=='success' and type(row.get('name')) is str,'STEPS')
  name=row['name'];numbers.append(row['number']);names.append(name)
  if name in required:selected[name]=row
  elif docker and name==BUILD_WRAPPER:
   need(not build_seen and not selected,'STEPS');build_seen=True
  else:need(name in wrappers,'STEPS')
 need(len(names)==len(set(names)) and numbers==sorted(numbers) and len(numbers)==len(set(numbers)) and tuple(selected)==required,'STEPS')
 return selected


def selected_job(raw,run_id,head,event):
 need(type(raw) is dict and set(raw)=={'total_count','jobs'} and type(raw['total_count']) is int and raw['total_count']==2 and type(raw['jobs']) is list and len(raw['jobs'])==2,'JOBS')
 want='qualify-readonly' if event=='push' else 'observe-once';skip='observe-once' if event=='push' else 'qualify-readonly'
 need(all(type(j) is dict for j in raw['jobs']),'JOBS')
 need({j.get('name') for j in raw['jobs']}=={want,skip},'JOBS')
 result=None
 for job in raw['jobs']:
  expected=dict(run_id=run_id,head_sha=head,run_attempt=1,status='completed',conclusion='success' if job['name']==want else 'skipped')
  need(positive(job.get('id')) and same({k:job.get(k) for k in expected},expected),'JOBS')
  if job['name']==want:result=job
  else:need(job.get('steps') is None or (type(job['steps']) is list and not job['steps']),'SKIPPED_STEPS')
 return result


def run_bound(run,run_id,head,path,event,workflow_id=None):
 want=dict(id=run_id,head_sha=head,head_branch=BRANCH,path=path,event=event,run_attempt=1,status='completed',conclusion='success')
 need(type(run) is dict and same({k:run.get(k) for k in want},want) and positive(run.get('workflow_id')) and type(run.get('repository')) is dict and run['repository'].get('full_name')==REPO,'RUN')
 if workflow_id is not None:need(type(workflow_id) is int and run['workflow_id']==workflow_id,'WORKFLOW_ID')
 return run


def artifact(raw,run_id,head,prefix):
 need(type(raw) is dict and set(raw)=={'total_count','artifacts'} and type(raw['total_count']) is int and raw['total_count']==1 and type(raw['artifacts']) is list and len(raw['artifacts'])==1,'ARTIFACT')
 item=raw['artifacts'][0]
 need(type(item) is dict and positive(item.get('id')) and positive(item.get('size_in_bytes')) and item['size_in_bytes']<4*1024*1024 and item.get('name')==prefix+str(run_id) and item.get('expired') is False,'ARTIFACT')
 origin=item.get('workflow_run');want=dict(id=run_id,head_sha=head,head_branch=BRANCH)
 need(type(origin) is dict and same({k:origin.get(k) for k in want},want),'ARTIFACT_SOURCE')
 return item


def collect_native(A,G,run_id,head):
 run=run_bound(A.run(run_id),run_id,head,NATIVE_WORKFLOW,'push');jobs=A.jobs(run_id)
 need(type(jobs) is dict and set(jobs)=={'total_count','jobs'} and type(jobs['total_count']) is int and jobs['total_count']==1 and type(jobs['jobs']) is list and len(jobs['jobs'])==1,'NATIVE_JOBS')
 item=artifact(A.artifacts(run_id),run_id,head,'naver-product-export-tests-')
 job=jobs['jobs'][0];need(type(job) is dict and positive(job.get('id')),'NATIVE_JOB')
 ref=dict(run_id=run_id,head_sha=head,workflow_id=run['workflow_id'],job_id=job['id'],artifact_id=item['id'],artifact_size=item['size_in_bytes'],artifact_digest=item.get('digest'))
 result=G.native(ref,run,jobs['jobs'],[item],A.artifact_zip(item['id']))
 need(result['total']==1997 and len(result['suites'])==32,'NATIVE_COUNT')
 return dict(ref=ref,result=result)



def fixture_result(value):
 need(type(FIXTURE_EXPECTED) is dict and same(value,FIXTURE_EXPECTED),'AUDIT_FIXTURE')
 return value

def collect_audit(A,G,run_id,head,source):
 run=run_bound(A.run(run_id),run_id,head,WORKFLOW,'push');job=selected_job(A.jobs(run_id),run_id,head,'push');steps(job,AUDIT_STEPS)
 item=artifact(A.artifacts(run_id),run_id,head,'naver-market-operation-invocation-')
 ref=dict(run_id=run_id,head_sha=head,workflow_id=run['workflow_id'],job_id=job['id'],artifact_id=item['id'],artifact_size=item['size_in_bytes'],artifact_digest=item.get('digest'))
 names={'source-sha.txt','audit.closed.json','source-manifest.closed.json'}
 packed=A.artifact_zip(item['id']);members=G.unpack(packed,ref,names)
 need(members['source-sha.txt']==(head+'\n').encode('ascii'),'AUDIT_SOURCE_HEAD')
 manifest=G.strict(members['source-manifest.closed.json'],16384)
 need(same(manifest,source),'AUDIT_SOURCE_MANIFEST')
 value=G.strict(members['audit.closed.json'],16384)
 need(type(value) is dict,'AUDIT_CHECKS')
 observed_fixture=fixture_result(value.get('fixture'))
 expected=dict(schema='readonly-operation-invocation-qualification-v1',status='passed',core_tests=CORE_TEST_COUNT,
  delivery_tests=DELIVERY_TEST_COUNT,source_manifest_sha256=sha(canonical(source)),fixture=observed_fixture,
  operating_host_access=False,production_state_observed=False)
 need(same(value,expected),'AUDIT_CHECKS')
 return dict(ref=ref,artifact_sha256=sha(packed),result_sha256=sha(members['audit.closed.json']),result=value)


def qualify(root,head,native_run_id,audit_run_id):
 need(digest(head,40) and positive(native_run_id) and positive(audit_run_id) and native_run_id!=audit_run_id,'INPUT')
 bodies,source=registration(root)
 with dependencies(root) as loaded:
  A,G=loaded['fixed_actions_api'],loaded['workflow_delivery']
  native=collect_native(A,G,native_run_id,head)
  audit=collect_audit(A,G,audit_run_id,head,source)
 registry=dict(schema='readonly-operation-invocation-qualified-v1',head_sha=head,pair=list(PAIR),source=source,evidence=dict(native=native,audit=audit))
 need(len(canonical(registry))<=MAX_REGISTRY,'REGISTRY_SIZE')
 return registry,bodies


def module(body,name):
 m=types.ModuleType(name);exec(compile(body,'<pinned-readonly-'+name+'>','exec'),m.__dict__);return m


def build(root,inputs,context):
 need(type(inputs) is dict and set(inputs)=={'confirm','native_run_id','audit_run_id','registry_sha256'} and inputs['confirm']==CONFIRM and digest(inputs['registry_sha256']),'INPUT')
 want=dict(repository=REPO,ref='refs/heads/'+BRANCH,event='workflow_dispatch',run_attempt=1)
 need(type(context) is dict and set(context)==set(want)|{'head_sha','run_id'} and same({k:context[k] for k in want},want) and digest(context['head_sha'],40) and positive(context['run_id']),'CONTEXT')
 numbers=[]
 for key in ('native_run_id','audit_run_id'):
  v=inputs[key];need(type(v) is str and re.fullmatch('[1-9][0-9]{0,18}',v) is not None and positive(int(v)),'INPUT_ID');numbers.append(int(v))
 need(context['run_id'] not in numbers,'INPUT_ID')
 registry,bodies=qualify(root,context['head_sha'],*numbers)
 need(sha(canonical(registry))==inputs['registry_sha256'],'REGISTRY_BINDING')
 D=module(bodies['delivery.py'],'readonly_delivery')
 prepared=D.render(bodies['core.py'],SOURCE_PINS['core.py'])
 return registry,prepared


def output(path,script):
 need(type(path) is str and path.startswith('/') and type(script) is str and 0<len(script.encode())<=49152 and '\x00' not in script,'OUTPUT')
 delimiter='READONLY_SCRIPT_'+sha(script.encode())
 need(delimiter not in script.splitlines(),'OUTPUT')
 data=('script<<'+delimiter+'\n'+script+delimiter+'\n').encode()
 fd=os.open(path,os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW)
 try:
  st=os.fstat(fd);need(stat.S_ISREG(st.st_mode) and st.st_nlink==1 and st.st_uid==os.geteuid(),'OUTPUT')
  offset=0
  while offset<len(data):
   size=os.write(fd,data[offset:]);need(size>0,'OUTPUT');offset+=size
 finally:os.close(fd)


def main():
 need(sys.argv[1:]==['build'],'CLI')
 root=Path(__file__).absolute().parents[3]
 need(os.environ.get('GITHUB_ACTIONS')=='true','CONTEXT')
 inputs={k:os.environ.get('AUDIT_'+k.upper()) for k in ('confirm','native_run_id','audit_run_id','registry_sha256')}
 attempt=os.environ.get('GITHUB_RUN_ATTEMPT');run_id=os.environ.get('GITHUB_RUN_ID')
 need(attempt=='1' and type(run_id) is str and re.fullmatch('[1-9][0-9]{0,18}',run_id) is not None,'CONTEXT')
 context=dict(repository=os.environ.get('GITHUB_REPOSITORY'),ref=os.environ.get('GITHUB_REF'),event=os.environ.get('GITHUB_EVENT_NAME'),run_attempt=1,head_sha=os.environ.get('GITHUB_SHA'),run_id=int(run_id))
 registry,prepared=build(root,inputs,context)
 output(os.environ.get('GITHUB_OUTPUT'),prepared['script'])
 marker=dict(native='PASS',audit='PASS',registry_sha256=sha(canonical(registry)),core_sha256=SOURCE_PINS['core.py'],script_sha256=prepared['script_sha256'])
 print(BUILD_MARKER+canonical(marker).decode())

if __name__=='__main__':
 try:main()
 except BaseException:raise SystemExit('READONLY_QUALIFICATION_REFUSED') from None
