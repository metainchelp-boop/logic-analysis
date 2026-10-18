"""One refresh adapter using existing exact Actions/native/marker/CI primitives.
No operation on import. Only host_run calls the fixed single-use core.
"""
import base64
import contextlib
import hashlib
import json
import lzma
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import types

BASE='backend/tools/naver_original_market_refresh/'
OLD='backend/tools/naver_market_diagnostic_transition/'
WORKFLOW='.github/workflows/naver-original-market-refresh.yml'
REPO='metainchelp-boop/logic-analysis'
BRANCH='codex/naver-claude-reference-ops-20261011'
CONFIRM='REFRESH_ORIGINAL_MARKET_ONCE'
REQUEST={'version':1,'refresh_id':'5375b7cd33134b23b3df27ae23efbd03'}
REQUEST_RECEIPT='0ccbd37ab58a7b9d1973f9473c8fd92d6c2f35bed5ec540eb81c9f6796bff185'
CORE_PIN='3f4b4576b45ac689d96b209163233cc5d5aa4992d1adc200fbc9accf1ccdd1ba'
CORE_TEST_PIN='714c573a9a4bad44513f63c4beceaf91beea6f468172692d52a7921ac3714030'
FIXTURE_PIN='df4d91cdf8a76c6d1db9f4130a649f73aea3c77a6aa3b177bed315959bc70545'
ADAPTER_TEST_PIN='aafdadcec2e481abb6112b0f710af171b9f1a431b29e17da481e9c90e3ad307c'
CORE_COUNT=18
ADAPTER_COUNT=18
FIXTURE_CHECKS=('empty_host_gate','exact_public_pins','real_root_systemd','timer_unix_output',
 'timer_300s_refused','original_failure_preserved','durable_intent_before_start',
 'single_original_start','same_id_replay_refused','interrupted_intent_replay_refused',
 'original_helper_verified','original_files_db_preserved')
FIXTURE_FLAGS=('operating_host_access','production_receipt_verified','current_docker_verified','original_SOURCE_LIMIT_cause_verified')
MODULE_PINS={
 'transition':'89ab4f61004846a90ec75a147b398d5f17eae016a268e375e7c44433143c3a92',
 'journal':'27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333',
 'preflight':'0a48d024d352bb2d32cfa920ee530501001bb889d32219ff8b14dcca0984b7c3',
 'systemd_boundary':'a0559bdca3bee319a8bc3d37425a6854185ec06245b69ec494a4513221fe72ac',
 'current_guard':'6a9377b6ed3d511e054c1234b0b830314331ddadad3b5887b79a8c36e611e5d8'}
PUBLIC={
 'exports_binding':('backend/tools/naver_completion_exports.py','1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed'),
 'exports_helper':('backend/tools/naver_saved_exports.py','062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737'),
 'product_exporter':('backend/naver_product_export.py','42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59'),
 'market_exporter':('backend/naver_market_export.py','d491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'),
 'diagnostic_exporter':(OLD+'diagnostic_market_export.py','9bb25d4acda4edca44aa71c238a6bf53be7dab5e093bc4f0c69d45c0d0891851')}
DELIVERY_PIN='93f7b0fedd713e5be03a2df2501bc57e825ef41564accf9bc5ea6d4590c30504'
LIBRARIES={
 'refresh_output_primitives':(OLD+'qualification.py','6a74ea15bef32330d580c96a2a31ddde36512bf053bd7c23a631c0e07b5ce70c'),
 'qualification':('backend/tools/naver_market_operation_invocation/qualification.py','7cf179f4a6eb257b0b557e467d5040ae3c9252c2c5068b5680a23ea07a497e3f'),
 'refresh_ci_primitives':('backend/tools/naver_market_operation_invocation/ci.py','576cbfe8e012be6c6469df34c6ce483ae3ded293201c9937ff01b016e94cb194'),
 'refresh_marker_primitives':(OLD+'result_receiver.py','b959189c5432643fcb34080f9891146e1c4a4ed862506d932c061e845b08b412')}
WIRE_MAX=102400
JSON_MAX=393216
BOOT_MAX=32768
HOST_MAX=32768
SSH_MAX=131072
DECODER_MEMORY=33554432
RESULT_MARKER='NAVER_ORIGINAL_MARKET_REFRESH_V1='
BUILD_MARKER='NAVER_ORIGINAL_MARKET_REFRESH_QUALIFICATION_V1='
JOBS=('portable-refresh','linux-refresh','refresh-once')
PORTABLE_STEPS=('Checkout exact source','Python 3.12','Check exact refresh core and delivery','Retain closed refresh tests')
LINUX_STEPS=('Checkout exact source','Python 3.12','Qualify refresh on empty Linux root','Retain closed refresh Linux')
DISPATCH_STEPS=('Checkout exact source','Python 3.12','Validate refresh qualifications and build fixed script','Refresh original market once')

class Refused(ValueError):pass
def need(v,code):
 if v is not True:raise Refused(code)
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
def same(a,b):return canonical(a)==canonical(b)
def digest(v,n=64):return type(v) is str and re.fullmatch('[0-9a-f]{'+str(n)+'}',v) is not None
def positive(v):return type(v) is int and 0<v<2**63

def strict(raw,maximum=JSON_MAX):
 need(type(raw) is bytes and 0<len(raw)<=maximum,'JSON_SIZE')
 def unique(pairs):
  d={}
  for k,v in pairs:
   need(k not in d,'JSON_DUPLICATE');d[k]=v
  return d
 try:value=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:need(False,'JSON_VALUE'))
 except (ValueError,UnicodeError):raise Refused('JSON_VALUE') from None
 need(canonical(value)==raw,'JSON_CANONICAL');return value

def fixed_read(root,relative,pin=None,maximum=131072):
 # Bootstrap only; subsequent native/artifact reads reuse the existing bounded reader.
 root=Path(root).absolute();path=root/relative
 need(type(relative) is str and not relative.startswith('/') and '..' not in Path(relative).parts,'SOURCE_PATH')
 need(not any(p.is_symlink() for p in (path,*path.parents)),'SOURCE_PATH')
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  before=os.fstat(fd);need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<before.st_size<=maximum,'SOURCE_FILE')
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
def modules(buffers):
 need(type(buffers) is dict and not any(n in sys.modules for n in buffers),'MODULE_COLLISION')
 loaded={}
 try:
  for name,body in buffers.items():
   need(type(body) is bytes,'MODULE_SOURCE');m=types.ModuleType(name);loaded[name]=m;sys.modules[name]=m
   exec(compile(body,'<exact-refresh-'+name+'>','exec'),m.__dict__)
  yield loaded
 finally:
  for n,m in loaded.items():
   if sys.modules.get(n) is m:del sys.modules[n]

@contextlib.contextmanager
def libraries(root):
 buffers={n:fixed_read(root,p,h) for n,(p,h) in LIBRARIES.items()}
 with modules(buffers) as values:
  Q=values['qualification']
  with Q.dependencies(root) as deps:
   yield Q,values['refresh_ci_primitives'],values['refresh_marker_primitives'],deps

def registration(root):
 pins={'core.py':CORE_PIN,'test_core.py':CORE_TEST_PIN,'linux_fixture.py':FIXTURE_PIN,'test_adapter.py':ADAPTER_TEST_PIN}
 need(all(digest(v) for v in pins.values()) and positive(ADAPTER_COUNT),'REGISTRATION_REQUIRED')
 bodies={n:fixed_read(root,BASE+n,p) for n,p in pins.items()}
 bodies['adapter.py']=fixed_read(root,BASE+'adapter.py')
 runtime={n:fixed_read(root,OLD+n+'.py',p,32768) for n,p in MODULE_PINS.items()}
 public={n:fixed_read(root,p,h,65536) for n,(p,h) in PUBLIC.items()}
 delivery=fixed_read(root,OLD+'delivery.py',DELIVERY_PIN,32768)
 with libraries(root) as (Q,CI,R,deps):
  native_pin=sha(Q.read(root,Q.NATIVE_WORKFLOW,Q.NATIVE_WORKFLOW_PIN))
 source=dict(schema='original-market-refresh-source-v1',request=REQUEST,request_receipt_sha256=REQUEST_RECEIPT,
  files={**pins,'adapter.py':sha(bodies['adapter.py'])},runtime=dict(MODULE_PINS),public={k:v[1] for k,v in PUBLIC.items()},
  libraries={k:v[1] for k,v in LIBRARIES.items()},delivery_sha256=DELIVERY_PIN,
  workflow_sha256=sha(fixed_read(root,WORKFLOW)),native_workflow_sha256=native_pin,
  counts=dict(core=CORE_COUNT,adapter=ADAPTER_COUNT),linux_checks=list(FIXTURE_CHECKS))
 return bodies,runtime,public,delivery,source

def request(v):
 need(type(v) is dict and same(v,REQUEST),'REQUEST');return v

def host_payload(payload):
 need(type(payload) is dict and set(payload)=={'request','core','modules','public','delivery'},'PAYLOAD')
 request(payload['request'])
 host=payload['delivery'];need(type(host) is str and len(host.encode())<=32768 and sha(host.encode())==DELIVERY_PIN,'DELIVERY_PIN')
 D=types.ModuleType('refresh_exact_delivery');exec(compile(host,'<exact-delivery>','exec'),D.__dict__)
 runtime=D.exact(payload['modules'],MODULE_PINS,32768)
 public=D.exact(payload['public'],{n:p[1] for n,p in PUBLIC.items()},65536)
 body=payload['core'];need(type(body) is str and 0<len(body.encode())<=32768 and sha(body.encode())==CORE_PIN,'CORE_PIN')
 return body.encode(),runtime,public

@contextlib.contextmanager
def core_module(payload):
 body,runtime,public=host_payload(payload)
 with modules(runtime) as loaded:
  C=types.ModuleType('original_refresh_core');exec(compile(body,'<exact-refresh-core>','exec'),C.__dict__)
  yield C,public

def host_run(payload):
 with core_module(payload) as (C,public):
  baseline={k:public[k] for k in ('exports_binding','exports_helper','product_exporter','market_exporter')}
  sources={'helper':public['exports_helper'],'product':public['product_exporter'],'old_market':public['market_exporter'],'market':public['diagnostic_exporter']}
  return C.validate(C.run(REQUEST,sources=sources,baseline_sources=baseline))

def package(bodies,runtime,public,delivery):
 payload=dict(request=REQUEST,core=bodies['core.py'].decode(),modules={k:v.decode() for k,v in runtime.items()},
  public={k:v.decode() for k,v in public.items()},delivery=delivery.decode())
 host_payload(payload)
 return dict(adapter=bodies['adapter.py'].decode(),payload=payload)

def encode(value):
 raw=canonical(value);need(0<len(raw)<=JSON_MAX,'JSON_SIZE')
 wire=base64.b85encode(lzma.compress(raw,format=lzma.FORMAT_XZ,check=lzma.CHECK_CRC64,preset=6)).decode('ascii')
 need(0<len(wire)<=WIRE_MAX,'WIRE_SIZE');return wire

def decode(wire):
 need(type(wire) is str and wire.isascii() and 0<len(wire)<=WIRE_MAX,'WIRE_SIZE')
 try:
  d=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=DECODER_MEMORY)
  raw=d.decompress(base64.b85decode(wire),max_length=JSON_MAX+1)
  need(len(raw)<=JSON_MAX and d.eof and not d.unused_data,'COMPRESSED_SIZE')
 except (ValueError,lzma.LZMAError):raise Refused('COMPRESSED_SIZE') from None
 return strict(raw)

def render(value):
 need(type(value) is dict and set(value)=={'adapter','payload'} and type(value['adapter']) is str,'PACKAGE')
 need(0<len(value['adapter'].encode())<=HOST_MAX,'HOST_SIZE')
 host_payload(value['payload']);wire=encode(value)
 need(same(decode(wire),value),'ROUNDTRIP')
 boot="""import base64,hashlib,json,lzma,os,types
result=dict(version=1,transport_ok=False,phase='decode',error_code='TRANSPORT_REFUSED',result=None)
def refuse():raise ValueError()
def unique(rows):
 d={}
 for k,v in rows:
  if k in d:refuse()
  d[k]=v
 return d
try:
 wire=os.environ.pop('NAVER_REFRESH_WIRE')
 os.environ.clear();os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',LANG='C')
 if not wire.isascii() or not 0<len(wire)<=102400:refuse()
 d=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=33554432)
 raw=d.decompress(base64.b85decode(wire),max_length=393217)
 if len(raw)>393216 or not d.eof or d.unused_data:refuse()
 value=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:refuse())
 if type(value) is not dict or set(value)!={'adapter','payload'}:refuse()
 source=value['adapter']
 if type(source) is not str or len(source.encode())>32768 or hashlib.sha256(source.encode()).hexdigest()!=ADAPTER_PIN:refuse()
 result['phase']='load'
 m=types.ModuleType('fixed_original_refresh');exec(compile(source,'<pinned-original-refresh-adapter>','exec'),m.__dict__)
 m.strict(raw);m.host_payload(value['payload'])
 result['phase']='entrypoint';result['result']=m.host_run(value['payload'])
 result.update(transport_ok=True,phase='complete',error_code=None)
except BaseException:pass
print('NAVER_ORIGINAL_MARKET_REFRESH_V1='+json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False))
"""
 boot='ADAPTER_PIN='+repr(sha(value['adapter'].encode()))+'\n'+boot
 need(len(boot.encode())<=BOOT_MAX,'BOOT_SIZE')
 script='export NAVER_REFRESH_WIRE='+shlex.quote(wire)+"\n/usr/bin/python3 -I -B - <<'PYCODE'\n"+boot+'PYCODE\n'
 need(len(script.encode())<=SSH_MAX,'SSH_SIZE')
 return dict(script=script,script_sha256=sha(script.encode()),request_sha256=sha(canonical(REQUEST)),
  sizes=dict(json=len(canonical(value)),wire=len(wire),boot=len(boot.encode()),ssh=len(script.encode())))

def selected_jobs(raw,run_id,head,event):
 need(type(raw) is dict and set(raw)=={'total_count','jobs'} and type(raw['total_count']) is int and raw['total_count']==3
  and type(raw['jobs']) is list and len(raw['jobs'])==3,'JOBS')
 need(all(type(j) is dict for j in raw['jobs']) and {j.get('name') for j in raw['jobs']}==set(JOBS),'JOBS')
 active=JOBS[:2] if event=='push' else JOBS[2:];chosen={}
 for j in raw['jobs']:
  expected=dict(run_id=run_id,head_sha=head,run_attempt=1,status='completed',conclusion='success' if j['name'] in active else 'skipped')
  need(positive(j.get('id')) and same({k:j.get(k) for k in expected},expected),'JOBS')
  if j['name'] in active:chosen[j['name']]=j
  else:need(j.get('steps') is None or j['steps']==[],'SKIPPED_STEPS')
 return chosen

def fixture_result(v):
 expected=dict(schema='original-market-refresh-empty-linux-vm-v1',status='passed',checks={k:True for k in FIXTURE_CHECKS},**{k:False for k in FIXTURE_FLAGS})
 need(same(v,expected),'LINUX_CHECKS');return v

def collect_refresh(A,G,Q,run_id,head,source):
 run=Q.run_bound(A.run(run_id),run_id,head,WORKFLOW,'push');jobs=selected_jobs(A.jobs(run_id),run_id,head,'push')
 Q.steps(jobs['portable-refresh'],PORTABLE_STEPS);Q.steps(jobs['linux-refresh'],LINUX_STEPS)
 raw=A.artifacts(run_id)
 need(type(raw) is dict and set(raw)=={'total_count','artifacts'} and type(raw['total_count']) is int and raw['total_count']==2
  and type(raw['artifacts']) is list and len(raw['artifacts'])==2,'ARTIFACTS')
 results={}
 for kind,jobname in (('tests','portable-refresh'),('linux','linux-refresh')):
  prefix='naver-original-market-refresh-'+kind+'-'
  items=[x for x in raw['artifacts'] if type(x) is dict and x.get('name')==prefix+str(run_id)]
  item=Q.artifact({'total_count':len(items),'artifacts':items},run_id,head,prefix)
  ref=dict(run_id=run_id,head_sha=head,workflow_id=run['workflow_id'],job_id=jobs[jobname]['id'],artifact_id=item['id'],artifact_size=item['size_in_bytes'],artifact_digest=item.get('digest'))
  packed=A.artifact_zip(item['id']);members=G.unpack(packed,ref,{'source-sha.txt','refresh.closed.json','source-manifest.closed.json'})
  need(members['source-sha.txt']==(head+'\n').encode(),'ARTIFACT_HEAD')
  need(same(G.strict(members['source-manifest.closed.json'],16384),source),'ARTIFACT_MANIFEST')
  result=G.strict(members['refresh.closed.json'],16384)
  if kind=='tests':expected=dict(schema='original-market-refresh-tests-v1',status='passed',core_tests=CORE_COUNT,adapter_tests=ADAPTER_COUNT,source_manifest_sha256=sha(canonical(source)))
  else:expected=dict(schema='original-market-refresh-linux-v1',status='passed',fixture=fixture_result(result.get('fixture')),source_manifest_sha256=sha(canonical(source)))
  need(same(result,expected),'ARTIFACT_RESULT');results[kind]=dict(ref=ref,result=result,artifact_sha256=sha(packed))
 return results

def qualify(root,head,native_run_id,refresh_run_id):
 need(digest(head,40) and positive(native_run_id) and positive(refresh_run_id) and native_run_id!=refresh_run_id,'INPUT')
 bodies,runtime,public,delivery,source=registration(root)
 with libraries(root) as (Q,CI,R,deps):
  A,G=deps['fixed_actions_api'],deps['workflow_delivery']
  native=Q.collect_native(A,G,native_run_id,head)
  fresh=collect_refresh(A,G,Q,refresh_run_id,head,source)
 registry=dict(schema='original-market-refresh-qualified-v1',head_sha=head,source=source,request=REQUEST,evidence=dict(native=native,refresh=fresh))
 need(len(canonical(registry))<=32768,'REGISTRY_SIZE')
 return registry,package(bodies,runtime,public,delivery)

def build(root,inputs,context):
 need(type(inputs) is dict and set(inputs)=={'confirm','native_run_id','refresh_run_id','registry_sha256'} and inputs['confirm']==CONFIRM and digest(inputs['registry_sha256']),'INPUT')
 want=dict(repository=REPO,ref='refs/heads/'+BRANCH,event='workflow_dispatch',run_attempt=1)
 need(type(context) is dict and set(context)==set(want)|{'head_sha','run_id'} and same({k:context[k] for k in want},want)
  and digest(context['head_sha'],40) and positive(context['run_id']),'CONTEXT')
 ids=[]
 for name in ('native_run_id','refresh_run_id'):
  v=inputs[name];need(type(v) is str and re.fullmatch('[1-9][0-9]{0,18}',v) is not None and positive(int(v)),'INPUT');ids.append(int(v))
 need(context['run_id'] not in ids,'INPUT')
 registry,value=qualify(root,context['head_sha'],*ids)
 need(sha(canonical(registry))==inputs['registry_sha256'],'REGISTRY_BINDING')
 prepared=render(value)
 return registry,prepared

def fixed_input(root,registry,workflow_id):
 need(positive(workflow_id),'WORKFLOW_ID')
 bodies,runtime,public,delivery,source=registration(root);need(same(source,registry['source']) and same(registry['request'],REQUEST),'SOURCE_REGISTRY')
 prepared=render(package(bodies,runtime,public,delivery))
 return dict(schema='original-market-refresh-fixed-input-v1',registry_sha256=sha(canonical(registry)),request_sha256=sha(canonical(REQUEST)),
  workflow_id=workflow_id,workflow_path=WORKFLOW,head_sha=registry['head_sha'],script_sha256=prepared['script_sha256'])

def validate_observation(observed,payload):
 need(type(observed) is dict and set(observed)=={'version','transport_ok','phase','error_code','result'}
  and type(observed['version']) is int and observed['version']==1 and type(observed['transport_ok']) is bool,'RESULT_SCHEMA')
 if observed['transport_ok']:
  need(observed['phase']=='complete' and observed['error_code'] is None,'RESULT_SCHEMA')
  with core_module(payload) as (C,_):C.validate(observed['result'])
 else:need(observed['phase'] in ('decode','load','entrypoint') and observed['error_code']=='TRANSPORT_REFUSED' and observed['result'] is None,'RESULT_SCHEMA')
 return observed

def receive(root,registry,fixed,run_id):
 need(positive(run_id) and type(fixed) is dict and same(fixed,fixed_input(root,registry,fixed.get('workflow_id'))),'FIXED_INPUT')
 need(run_id not in (registry['evidence']['native']['ref']['run_id'],registry['evidence']['refresh']['tests']['ref']['run_id']),'RESULT_RUN')
 bodies,runtime,public,delivery,source=registration(root);payload=package(bodies,runtime,public,delivery)['payload']
 with libraries(root) as (Q,CI,R,deps):
  A,G=deps['fixed_actions_api'],deps['workflow_delivery'];head=registry['head_sha']
  Q.run_bound(A.run(run_id),run_id,head,WORKFLOW,'workflow_dispatch',fixed['workflow_id'])
  job=selected_jobs(A.jobs(run_id),run_id,head,'workflow_dispatch')['refresh-once'];steps=Q.steps(job,DISPATCH_STEPS,docker=True)
  raw=A.job_log(job['id'])
  # Reject unknown/malformed family markers while leaving echoed source lines out.
  for line in raw.splitlines():
   m=re.fullmatch(rb'(\S+Z)\s+(?:out: )?(NAVER_ORIGINAL_MARKET_REFRESH_.*)',line)
   if m:need(any(m[2].startswith(s.encode()) for s in (RESULT_MARKER,BUILD_MARKER)),'MARKER_FAMILY')
  def marker(lit,step):
   result=R.marker(raw,lit.encode(),step,G);return G.strict(result[len(lit):-1],4096)
  built=marker(BUILD_MARKER,steps[DISPATCH_STEPS[2]])
  need(same(built,dict(native='PASS',refresh='PASS',registry_sha256=fixed['registry_sha256'],request_sha256=fixed['request_sha256'],script_sha256=fixed['script_sha256'])),'BUILD_BINDING')
  observed=marker(RESULT_MARKER,steps[DISPATCH_STEPS[3]])
 validate_observation(observed,payload)
 return dict(schema='original-market-refresh-operating-v1',workflow_run_id=run_id,head_sha=registry['head_sha'],fixed_input_sha256=sha(canonical(fixed)),
  request_binding='fixed_workflow_input_and_build_marker',attempt_status_known=observed['transport_ok'],automatic_retry_allowed=False,observation=observed)

def ci(root,mode):
 need(mode in ('tests','fixture'),'CI_ARGS')
 need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('RUNNER_ENVIRONMENT')=='github-hosted'
  and os.environ.get('RUNNER_OS')=='Linux' and os.environ.get('GITHUB_EVENT_NAME')=='push'
  and os.environ.get('GITHUB_REPOSITORY')==REPO and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH
  and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','CI_CONTEXT')
 head=os.environ.get('GITHUB_SHA');need(digest(head,40),'CI_HEAD')
 bodies,runtime,public,delivery,source=registration(root);folder=Path(root)/('refresh-'+mode+'-evidence');folder.mkdir(mode=0o755)
 with libraries(root) as (Q,CI,R,deps):
  if mode=='tests':
   reports={}
   for name,count in (('test_core.py',CORE_COUNT),('test_adapter.py',ADAPTER_COUNT)):
    before_path=list(sys.path);before_modules=set(sys.modules)
    try:reports[name]=CI.execute(bodies[name],Path(root)/BASE/name,'refresh_ci_'+name[:-3],count)
    finally:
     sys.path[:]=before_path
     for added in set(sys.modules)-before_modules:
      if added in MODULE_PINS:del sys.modules[added]
   good=all(r['status']=='passed' for r in reports.values())
   value=dict(schema='original-market-refresh-tests-v1',status='passed' if good else 'failed',core_tests=CORE_COUNT,adapter_tests=ADAPTER_COUNT,source_manifest_sha256=sha(canonical(source)))
   if not good:value['test_reports']=reports
  else:
   f=types.ModuleType('refresh_linux_fixture');f.__file__=str(Path(root)/BASE/'linux_fixture.py')
   exec(compile(bodies['linux_fixture.py'],f.__file__,'exec'),f.__dict__)
   observed=f.run('github-hosted-empty-vm-only-v1')
   try:fixture_result(observed);good=True
   except Exception:good=False
   value=dict(schema='original-market-refresh-linux-v1',status='passed' if good else 'failed',fixture=observed,source_manifest_sha256=sha(canonical(source)))
  CI.write_new(folder/'source-sha.txt',(head+'\n').encode())
  CI.write_new(folder/'source-manifest.closed.json',canonical(source))
  CI.write_new(folder/'refresh.closed.json',canonical(value))
 need(good,'REFRESH_CI_REFUSED')

def main():
 need(len(sys.argv)==2 and sys.argv[1] in ('tests','fixture','build'),'CLI')
 root=Path(__file__).absolute().parents[3]
 if sys.argv[1]!='build':ci(root,sys.argv[1]);return
 need(os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_RUN_ATTEMPT')=='1','CONTEXT')
 rid=os.environ.get('GITHUB_RUN_ID');need(type(rid) is str and re.fullmatch('[1-9][0-9]{0,18}',rid) is not None,'CONTEXT')
 inputs={k:os.environ.get('REFRESH_'+k.upper()) for k in ('confirm','native_run_id','refresh_run_id','registry_sha256')}
 context=dict(repository=os.environ.get('GITHUB_REPOSITORY'),ref=os.environ.get('GITHUB_REF'),event=os.environ.get('GITHUB_EVENT_NAME'),
  run_attempt=1,head_sha=os.environ.get('GITHUB_SHA'),run_id=int(rid))
 registry,prepared=build(root,inputs,context)
 # Reuse the original transition's unchanged 128KiB fixed output writer.
 with libraries(root) as (Q,CI,R,deps):sys.modules['refresh_output_primitives'].output_script(os.environ.get('GITHUB_OUTPUT'),prepared['script'])
 print(BUILD_MARKER+canonical(dict(native='PASS',refresh='PASS',registry_sha256=sha(canonical(registry)),
  request_sha256=prepared['request_sha256'],script_sha256=prepared['script_sha256'])).decode())

if __name__=='__main__':
 try:main()
 except BaseException:raise SystemExit('ORIGINAL_MARKET_REFRESH_REFUSED') from None
