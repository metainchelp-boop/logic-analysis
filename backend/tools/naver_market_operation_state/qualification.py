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
BASE='backend/tools/naver_market_operation_state/'
WORKFLOW='.github/workflows/naver-market-operation-state.yml'
NATIVE_WORKFLOW='.github/workflows/naver-product-export-tests.yml'
NATIVE_WORKFLOW_PIN='d6f504478e5141d7861a278013fd26f99a73347f26a829dcbc7568f41fc40289'
CONFIRM='READ_MARKET_OPERATION_STATE_ONCE'
PAIR=('7abd8b3965ed4b51a3b071cd218e024f','4aa3189c384847178ecafbfa34eb060e')
BUILD_MARKER='NAVER_MARKET_OPERATION_STATE_QUALIFICATION_V1='
DEPENDENCY_BASE='backend/tools/naver_market_diagnostic_transition/qualification_deps/'
DEPENDENCIES={
 'native_contract':'7c157b45c150f3597e9e126b0d6a2348d9fb90421976c534591426d268f2303a',
 'workflow_delivery':'8379ed5d1d6bfe69f8e5bfe1c9d0dfa1f4f464d5363aaaf8d01ccfd66a3cda51',
 'fixed_actions_api':'fa5b25f8a64ad98b1bad2f9008003654eef98f03976c7c4992a0be3909f4befc'}
# Populated only from completed reviewed bytes, before any CI integration.
SOURCE_PINS={'core.py': '2b3c8bdc78bc65f97045951bffb6df3a0c103e0280a8ece3f429518786f36895', 'test_core.py': '5fdfcab1f1a75abdae9e5a3f2e9ffb300346c78a7ce9f6cae2afe3a96d8957b8', 'linux_fixture.py': 'b957778f8ea224a5f0fcddcbc08d0cacb8158f220dd700f34dc4095715dab664', 'delivery.py': '1ffd6f3cec82c2f0533ed3218214c845abe88fde63a3600039d861d8417b5f17', 'receiver.py': '4c7c523cad9b3c54c172d86d5b34bc76b865389a1cab1c0a3d451da8e8ab6c62', 'test_delivery.py': 'fd58c7df3e177931e8c238d9dfdaa0cd1e3cbad7ce04dbaf3f09e38d4fbb7b17', 'ci.py': '2291808de474f48b95763e2dfcfe9f3a83b5a3c8b7995da1da118f943884d43f'}
CORE_TEST_COUNT=20
DELIVERY_TEST_COUNT=31
FIXTURE_EXPECTED={'checks': {'absent_metadata': True,
            'ancestor_replacement_detected': True,
            'ancestor_symlink_rejected': True,
            'cleanup_verified': True,
            'hosted_linux_root': True,
            'leaf_replacement_detected': True,
            'mask_target_exact': True,
            'opath_kernel': True,
            'regular_hardlink_two': True,
            'root_anchor_nofollow': True,
            'source_pin': True,
            'unit_absent_schema': True,
            'unit_service_ten': True,
            'unit_timer_nine': True,
            'wrong_mask_rejected': True},
 'core_sha256': '2b3c8bdc78bc65f97045951bffb6df3a0c103e0280a8ece3f429518786f36895',
 'database_opened': False,
 'operating_observe_called': False,
 'production_units_touched': False,
 'stage': 'complete',
 'status': 'passed',
 'version': 1}
AUDIT_STEPS=('Checkout exact source','Python 3.12','Check readonly transport and core',
 'Qualify readonly audit on empty Linux root','Retain only closed audit qualification')
DISPATCH_STEPS=('Checkout exact source','Python 3.12','Validate readonly qualifications and build script','Read fixed operation state once')
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
 outward=dict(schema='readonly-operation-state-source-v1',pair=list(PAIR),sources=dict(SOURCE_PINS),dependencies=dict(DEPENDENCIES),
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
 need(type(value) is dict and set(value)==set(FIXTURE_EXPECTED)|{'absent_service'}
  and same({k:value[k] for k in FIXTURE_EXPECTED},FIXTURE_EXPECTED),'AUDIT_FIXTURE')
 item=value['absent_service']
 need(type(item) is dict and set(item)=={'exit_status','schema_issue','load_not_found','invocation_format'}
  and type(item['exit_status']) is int and 0<=item['exit_status']<=255
  and item['schema_issue']=='none' and type(item['schema_issue']) is str
  and item['load_not_found'] is True and type(item['invocation_format']) is str
  and item['invocation_format'] in ('empty','zero32'),'AUDIT_ABSENT_SCHEMA')
 return value

def collect_audit(A,G,run_id,head,source):
 run=run_bound(A.run(run_id),run_id,head,WORKFLOW,'push');job=selected_job(A.jobs(run_id),run_id,head,'push');steps(job,AUDIT_STEPS)
 item=artifact(A.artifacts(run_id),run_id,head,'naver-market-operation-state-')
 ref=dict(run_id=run_id,head_sha=head,workflow_id=run['workflow_id'],job_id=job['id'],artifact_id=item['id'],artifact_size=item['size_in_bytes'],artifact_digest=item.get('digest'))
 names={'source-sha.txt','audit.closed.json','source-manifest.closed.json'}
 packed=A.artifact_zip(item['id']);members=G.unpack(packed,ref,names)
 need(members['source-sha.txt']==(head+'\n').encode('ascii'),'AUDIT_SOURCE_HEAD')
 manifest=G.strict(members['source-manifest.closed.json'],16384)
 need(same(manifest,source),'AUDIT_SOURCE_MANIFEST')
 value=G.strict(members['audit.closed.json'],16384)
 need(type(value) is dict,'AUDIT_CHECKS')
 observed_fixture=fixture_result(value.get('fixture'))
 expected=dict(schema='readonly-operation-state-qualification-v1',status='passed',core_tests=CORE_TEST_COUNT,
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
 registry=dict(schema='readonly-operation-state-qualified-v1',head_sha=head,pair=list(PAIR),source=source,evidence=dict(native=native,audit=audit))
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
