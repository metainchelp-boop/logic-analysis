"""New three-source ledger delivery tests; synthetic observe, no host/API access."""
import base64
import contextlib
import io
import json
import lzma
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

def load(name):
 m=types.ModuleType('ledger_delivery_test_'+name);m.__file__=str(HERE/(name+'.py'))
 exec(compile((HERE/(name+'.py')).read_bytes(),m.__file__,'exec'),m.__dict__);return m
D,Q=load('delivery'),load('qualification')
with patch.dict(sys.modules,{'qualification':Q}):R=load('receiver');C=load('ci')
DEPS={n:(HERE/(n+'.py')).read_bytes() for n in ('transition','journal')}
SYNTHETIC=("APPLY="+repr(D.PAIR[0])+"\nROLLBACK="+repr(D.PAIR[1])+"\nPLAN_SHA256="+repr(D.PLAN_SHA256)+"\nDEPENDENCY_PINS="+repr(D.DEPENDENCY_PINS)+"\n"
 "calls=0\ndef observe(dependencies):\n global calls\n calls+=1\n if set(dependencies)!={'transition','journal'} or not all(type(x) is bytes for x in dependencies.values()):raise ValueError('private input')\n print('private output')\n return {'calls':calls}\n"
 "def validate(v):\n if type(v) is not dict or v!={'calls':1}:raise ValueError('private result')\n return v\n"
 "def closed_json(v):\n validate(v)\n return '{\"calls\":1}'\n").encode()

def rendered(source=SYNTHETIC):
 with patch.object(D,'CORE_SHA256',D.sha(source)):return D.render(source,DEPS,D.sha(source))

def boot_source(source=SYNTHETIC):
 return rendered(source)['script'].split("<<'READONLY_AUDIT_PY'\n",1)[1].rsplit('READONLY_AUDIT_PY\n',1)[0]

def execute_boot(body):
 output=io.StringIO()
 with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(output):exec(compile(body,'<synthetic-ledger-bootstrap>','exec'),{})
 raw=output.getvalue();assert len(raw.splitlines())==1 and raw.startswith(D.MARKER.decode())
 assert 'private' not in raw
 return D.strict(raw.strip().encode()[len(D.MARKER):])

def replace_package(body,raw):
 wire=base64.b85encode(lzma.compress(raw,format=lzma.FORMAT_XZ,preset=6)).decode()
 return 'WIRE='+repr(wire)+'\n'+body.split('\n',1)[1]

def package():return {'version':1,'core':SYNTHETIC.decode(),'dependencies':{n:v.decode() for n,v in DEPS.items()}}

def step(name,n):return dict(name=name,number=n,status='completed',conclusion='success',started_at='2026-10-18T00:00:00Z',completed_at='2026-10-18T00:00:00Z')

@contextlib.contextmanager
def simulated_receiver(change=None):
 head='a'*40
 native_ref=dict(run_id=7,workflow_id=70,job_id=700,head_sha=head)
 registry={'evidence':{'native':{'ref':native_ref},'audit':{'ref':dict(run_id=8,workflow_id=80,head_sha=head)}}}
 fixed=dict(head_sha=head,native_run_id=7,audit_run_id=8,workflow_id=80,registry_sha256='b'*64,script_sha256='c'*64,source={'closed':True})
 build=dict(native='PASS',audit='PASS',registry_sha256=fixed['registry_sha256'],core_sha256=D.sha(SYNTHETIC),script_sha256=fixed['script_sha256'])
 value=dict(schema='readonly-operation-ledger-transport-v1',transport_ok=True,phase='complete',error=None,observation={'calls':1})
 if change:change(build,value)
 raw=b'2026-10-18T00:00:00.100Z '+Q.BUILD_MARKER.encode()+D.canonical(build)+b'\n'+b'2026-10-18T00:00:00.100Z out: '+D.MARKER+D.canonical(value)+b'\n'
 def run(run_id):
  return dict(id=run_id,head_sha=head,head_branch=Q.BRANCH,path=Q.NATIVE_WORKFLOW if run_id==7 else Q.WORKFLOW,event='workflow_dispatch' if run_id==9 else 'push',run_attempt=1,status='completed',conclusion='success',workflow_id=70 if run_id==7 else 80,repository={'full_name':Q.REPO})
 def jobs(run_id):
  common=dict(run_id=run_id,head_sha=head,run_attempt=1,status='completed')
  if run_id==7:return {'total_count':1,'jobs':[dict(common,id=700,name='synthetic-export',conclusion='success',steps=[step('registered native step',1)])]}
  rows=[step(Q.BUILD_WRAPPER,1)]+[step(n,i+2) for i,n in enumerate(Q.DISPATCH_STEPS)]
  return {'total_count':2,'jobs':[dict(common,id=901,name='observe-once',conclusion='success',steps=rows),dict(common,id=902,name='qualify-readonly',conclusion='skipped',steps=[])]}
 A=types.SimpleNamespace(run=run,jobs=jobs,job_log=lambda _:raw)
 @contextlib.contextmanager
 def deps(_):yield {'fixed_actions_api':A,'workflow_delivery':None,'native_contract':types.SimpleNamespace(REQUIRED_STEPS=('registered native step',))}
 bodies={'core.py':SYNTHETIC,'delivery.py':b'synthetic',**{n+'.py':v for n,v in DEPS.items()}}
 with patch.object(R,'fixed_input',return_value=fixed),patch.object(Q,'registration',return_value=(bodies,fixed['source'])),patch.object(Q,'module',return_value=D),patch.object(Q,'dependencies',deps),patch.object(Q,'SOURCE_PINS',{'core.py':D.sha(SYNTHETIC)}),patch.object(D,'CORE_SHA256',D.sha(SYNTHETIC)):
  yield registry,fixed

class LedgerDeliveryTests(unittest.TestCase):
 def test_exact_three_source_pressure_without_execution(self):
  body=(HERE/'core.py').read_bytes();built=D.render(body,DEPS,D.sha(body))
  for name,cap in (('source',49152),('package',65536),('wire',32768),('bootstrap',8192),('ssh',49152)):
   self.assertLessEqual(built['sizes'][name],cap)
  self.assertEqual(built['sizes']['dependencies'],sum(map(len,DEPS.values())))
  self.assertEqual(D.DECODER_MEMORY,33554432)
  self.assertEqual(built['script_sha256'],D.sha(built['script'].encode()))
 def test_core_pin_is_registered_not_caller_selected(self):
  for pin in (None,True,'0'*64,D.sha(SYNTHETIC)):
   with self.assertRaises(D.Refused):D.render(SYNTHETIC,DEPS,pin)
 def test_render_never_executes_any_source(self):
  source=b"raise RuntimeError('private do not execute')\n"
  with patch.object(D,'CORE_SHA256',D.sha(source)):
   self.assertIn('script',D.render(source,DEPS,D.sha(source)))
 def test_dependency_set_and_types_before_core_load(self):
  source=b"raise RuntimeError('private do not execute')\n"
  with patch.object(D,'CORE_SHA256',D.sha(source)):
   cases=[{},dict(DEPS,extra=b'x'),{'transition':DEPS['transition']},{'transition':bytearray(DEPS['transition']),'journal':DEPS['journal']}]
   for deps in cases:
    with self.assertRaises(D.Refused):D.load_core(source,deps,D.sha(source))
 def test_three_source_tampering_before_load(self):
  source=b"raise RuntimeError('private do not execute')\n"
  with patch.object(D,'CORE_SHA256',D.sha(source)):
   with self.assertRaises(D.Refused):D.load_core(source+b' ',DEPS,D.sha(source))
   for name in DEPS:
    changed=dict(DEPS);changed[name]+=b' '
    with self.assertRaises(D.Refused):D.load_core(source,changed,D.sha(source))
 def test_source_size_limits_before_load(self):
  source=b' '*(D.MAX_SOURCE+1)
  with patch.object(D,'CORE_SHA256',D.sha(source)),self.assertRaises(D.Refused):D.render(source,DEPS,D.sha(source))
  with patch.object(D,'CORE_SHA256',D.sha(SYNTHETIC)):
   for name in DEPS:
    changed=dict(DEPS);changed[name]=b' '*(D.MAX_DEPENDENCY+1)
    with self.assertRaises(D.Refused):D.render(SYNTHETIC,changed,D.sha(SYNTHETIC))
 def test_loaded_core_exact_pair_plan_and_dependency_contract(self):
  for old,new in ((D.PAIR[0],'1'*32),(D.PLAN_SHA256,'2'*64),(D.DEPENDENCY_PINS['journal'],'3'*64)):
   body=SYNTHETIC.replace(old.encode(),new.encode())
   with patch.object(D,'CORE_SHA256',D.sha(body)),self.assertRaises(D.Refused):D.load_core(body,DEPS,D.sha(body))
 def test_bootstrap_single_observe_receives_exact_dependencies(self):
  value=execute_boot(boot_source());self.assertTrue(value['transport_ok']);self.assertEqual(value['observation'],{'calls':1})
 def test_bootstrap_dependency_module_collision_refused_before_observe(self):
  for name in DEPS:
   with patch.dict(sys.modules,{name:types.ModuleType(name)}):value=execute_boot(boot_source())
   self.assertFalse(value['transport_ok']);self.assertEqual((value['phase'],value['error']),('load','SOURCE'));self.assertIsNone(value['observation'])
 def test_bootstrap_closed_exception_without_partial_value(self):
  body=SYNTHETIC.replace(b"return {'calls':calls}",b"raise RuntimeError('private detail')")
  value=execute_boot(boot_source(body));self.assertEqual((value['phase'],value['error']),('observe','HOST_UNAVAILABLE'));self.assertIsNone(value['observation'])
 def test_bootstrap_three_parts_tamper(self):
  for key in ('core','transition','journal'):
   p=package()
   if key=='core':p[key]+=' '
   else:p['dependencies'][key]+=' '
   value=execute_boot(replace_package(boot_source(),D.canonical(p)))
   self.assertEqual((value['phase'],value['error']),('decode','PACKAGE'))
 def test_bootstrap_package_unknown_version_extra_and_alias(self):
  for delta in ({'version':True},{'version':2},{'extra':0},{'dependencies':{'transition':DEPS['transition'].decode()}}):
   p=package();p.update(delta)
   value=execute_boot(replace_package(boot_source(),D.canonical(p)));self.assertFalse(value['transport_ok'])
 def test_bootstrap_duplicate_noncanonical_and_nan_refused(self):
  raw=D.canonical(package())
  for changed in (b' '+raw,raw[:-1]+b',"version":1}',raw.replace(b'"version":1',b'"version":NaN')):
   value=execute_boot(replace_package(boot_source(),changed));self.assertEqual(value['error'],'PACKAGE')
 def test_bootstrap_compression_bomb_and_extra_stream_refused(self):
  body=boot_source();bomb=replace_package(body,b' '*(D.MAX_PACKAGE+1))
  self.assertFalse(execute_boot(bomb)['transport_ok'])
  combined=lzma.compress(D.canonical(package()))+lzma.compress(b'{}')
  body='WIRE='+repr(base64.b85encode(combined).decode())+'\n'+body.split('\n',1)[1]
  self.assertFalse(execute_boot(body)['transport_ok'])
 def test_result_type_enum_and_no_extra_history(self):
  with patch.object(D,'CORE_SHA256',D.sha(SYNTHETIC)):core=D.load_core(SYNTHETIC,DEPS,D.sha(SYNTHETIC))
  good=dict(schema='readonly-operation-ledger-transport-v1',transport_ok=True,phase='complete',error=None,observation={'calls':1})
  self.assertIs(D.result(good,core),good)
  for change in ({'transport_ok':1},{'phase':'ledger_read'},{'raw_events':[]},{'error':'SOURCE'}):
   with self.assertRaises(D.Refused):D.result(dict(good,**change),core)
 def test_result_refusal_cannot_contain_observation(self):
  value=dict(schema='readonly-operation-ledger-transport-v1',transport_ok=False,phase='observe',error='HOST_UNAVAILABLE',observation={'calls':1})
  with self.assertRaises(D.Refused):D.result(value,None)
 def test_provenance_distinguishes_primary_pair_and_supporting_audit(self):
  p=Q.TARGET_PROVENANCE
  self.assertEqual(p['pair'],list(D.PAIR));self.assertEqual(p['plan_sha256'],D.PLAN_SHA256)
  self.assertEqual(set(p['primary']),{'failed_apply','restored_rollback'})
  self.assertEqual([p['primary'][n]['run_id'] for n in ('failed_apply','restored_rollback')],[39092917351,39095445014])
  self.assertEqual(p['supporting_metadata_audit']['run_id'],39095055596)
 def test_dispatch_no_plan_path_or_pair_inputs(self):
  inputs=dict(confirm=Q.CONFIRM,native_run_id='7',audit_run_id='8',registry_sha256='0'*64)
  context=dict(repository=Q.REPO,ref='refs/heads/'+Q.BRANCH,event='workflow_dispatch',run_attempt=1,head_sha='a'*40,run_id=9)
  with patch.object(Q,'qualify') as call:
   for key in ('plan','path','pair','command'):
    with self.assertRaises(Q.Refused):Q.build(HERE,dict(inputs,**{key:'private'}),context)
   call.assert_not_called()
 def test_registry_binding_precedes_three_source_render(self):
  inputs=dict(confirm=Q.CONFIRM,native_run_id='7',audit_run_id='8',registry_sha256='0'*64)
  context=dict(repository=Q.REPO,ref='refs/heads/'+Q.BRANCH,event='workflow_dispatch',run_attempt=1,head_sha='a'*40,run_id=9)
  with patch.object(Q,'qualify',return_value=({'closed':True},{})),patch.object(Q,'module') as call,self.assertRaisesRegex(Q.Refused,'REGISTRY_BINDING'):Q.build(HERE,inputs,context)
  call.assert_not_called()
 def test_receiver_rejects_different_fixed_request_before_loading(self):
  expected={'closed':True}
  with patch.object(R,'fixed_input',return_value=expected),patch.object(Q,'registration') as call,self.assertRaisesRegex(Q.Refused,'FIXED_INPUT'):R.receive(HERE,{},dict(expected,plan='other'),9)
  call.assert_not_called()
 def test_fixed_registry_pair_plan_and_head_rebinding_refused(self):
  source={'target':Q.TARGET_PROVENANCE}
  registry=dict(schema='readonly-operation-ledger-qualified-v1',head_sha='a'*40,pair=list(D.PAIR),source=source,evidence={})
  cases=[dict(registry,pair=['1'*32,D.PAIR[1]]),dict(registry,head_sha=True),dict(registry,source={'target':dict(Q.TARGET_PROVENANCE,plan_sha256='0'*64)})]
  with patch.object(Q,'registration',return_value=({},source)),patch.object(Q,'module') as call:
   for value in cases:
    with self.assertRaises(Q.Refused):R.fixed_input(HERE,value)
   call.assert_not_called()
 def test_result_marker_exact_family_and_duplicate(self):
  good=b'2026-10-18T00:00:00.100Z out: '+D.MARKER+b'{"x":1}\n';window=step('result',1)
  self.assertEqual(R.marker(good,D.MARKER,window,D),{'x':1})
  for raw in (good+good,b'2026-10-18T00:00:00.100Z out: NAVER_MARKET_OPERATION_LEDGER_V2={}\n'+good):
   with self.assertRaises(Q.Refused):R.marker(raw,D.MARKER,window,D)
 def test_dispatch_known_docker_and_number_gap_binding(self):
  rows=[step('Set up job',1),step(Q.BUILD_WRAPPER,2)]+[step(n,i+3) for i,n in enumerate(Q.DISPATCH_STEPS)]+[step('Post Python 3.12',21),step('Post Checkout exact source',22),step('Complete job',23)]
  self.assertEqual(tuple(Q.steps({'steps':rows},Q.DISPATCH_STEPS,docker=True)),Q.DISPATCH_STEPS)
  rows[-1]['number']=True
  with self.assertRaises(Q.Refused):Q.steps({'steps':rows},Q.DISPATCH_STEPS,docker=True)
 def test_new_audit_source_head_exact(self):
  item=dict(id=99,size_in_bytes=10,digest='sha256:'+'b'*64);head='a'*40
  A=types.SimpleNamespace(run=lambda _: {},jobs=lambda _: {},artifacts=lambda _: {},artifact_zip=lambda _:b'zip')
  G=types.SimpleNamespace(unpack=lambda *args:{'source-sha.txt':head.encode(),'source-manifest.closed.json':b'{}','audit.closed.json':b'{}'})
  with patch.object(Q,'run_bound',return_value={'workflow_id':11}),patch.object(Q,'selected_job',return_value={'id':12}),patch.object(Q,'steps'),patch.object(Q,'artifact',return_value=item),self.assertRaisesRegex(Q.Refused,'AUDIT_SOURCE_HEAD'):Q.collect_audit(A,G,7,head,{})
 def test_fixture_failure_or_extra_field_cannot_qualify(self):
  good=json.loads(json.dumps(Q.FIXTURE_EXPECTED));self.assertIs(Q.fixture_result(good),good)
  for delta in ({'status':'failed'},{'unregistered':False}):
   bad=dict(good,**delta)
   with self.assertRaises(Q.Refused):Q.fixture_result(bad)
 def test_receiver_binds_actual_style_metadata_and_closed_result(self):
  with simulated_receiver() as (registry,fixed):result=R.receive(HERE,registry,fixed,9)
  self.assertEqual(result['workflow_run_id'],9);self.assertEqual(result['result']['observation'],{'calls':1})
  self.assertFalse(result['cleanup_executed']);self.assertFalse(result['original_export_success_verified'])
  self.assertEqual(result['target'],Q.TARGET_PROVENANCE)
 def test_receiver_wrong_build_digest_cannot_adopt_valid_result(self):
  for key in ('registry_sha256','script_sha256','core_sha256'):
   with simulated_receiver(lambda b,v:b.update({key:'0'*64})) as (registry,fixed),self.assertRaisesRegex(Q.Refused,'BUILD_BINDING'):R.receive(HERE,registry,fixed,9)
 def test_receiver_refuses_unregistered_raw_history_field(self):
  with simulated_receiver(lambda b,v:v.update(raw_events=[])) as (registry,fixed),self.assertRaises(D.Refused):R.receive(HERE,registry,fixed,9)
 def test_receiver_dispatch_id_must_differ_from_qualification(self):
  with simulated_receiver() as (registry,fixed),self.assertRaisesRegex(Q.Refused,'RESULT_RUN_ID'):R.receive(HERE,registry,fixed,7)
 def test_new_test_runner_registered_counts_without_raw_values(self):
  body=b"import unittest\nclass Boundary(unittest.TestCase):\n def test_closed(self):self.fail('private path/value')\n"
  report=C.execute(body,HERE/'synthetic.py','synthetic_ledger_ci',1)
  self.assertEqual(report['status'],'failed');self.assertEqual(report['executed'],1)
  self.assertEqual(report['failed_ids'],['synthetic_ledger_ci.Boundary.test_closed']);self.assertNotIn('private',json.dumps(report))

if __name__=='__main__':unittest.main()
