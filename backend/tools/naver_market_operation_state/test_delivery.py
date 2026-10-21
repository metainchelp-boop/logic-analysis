"""New offline readonly delivery boundaries. No actual API or host observation."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import stat
import types
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent

def load(name):
 m=types.ModuleType('test_readonly_'+name);m.__file__=str(HERE/(name+'.py'))
 exec(compile((HERE/(name+'.py')).read_bytes(),m.__file__,'exec'),m.__dict__);return m
D,Q=load('delivery'),load('qualification')
with patch.dict(sys.modules,{'qualification':Q}):
 R=load('receiver');C=load('ci')

SYNTHETIC=("APPLY='"+D.PAIR[0]+"'\nROLLBACK='"+D.PAIR[1]+"'\n"
 "calls=0\ndef observe():\n global calls\n calls+=1\n print('not-public')\n return {'calls':calls}\n"
 "def validate(v):\n if type(v) is not dict or v!={'calls':1}: raise ValueError('bad')\n return v\n"
 "def closed_json(v):\n validate(v)\n return '{\"calls\":1}'\n").encode()

def bootstrap(source):
 script=D.render(source,D.sha(source))['script'];body=script.split("<<'READONLY_AUDIT_PY'\n",1)[1].rsplit('READONLY_AUDIT_PY\n',1)[0]
 output=io.StringIO()
 with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(output):exec(compile(body,'<synthetic-bootstrap>','exec'),{})
 return output.getvalue()

def step(name,n=1):return dict(name=name,number=n,status='completed',conclusion='success',started_at='2026-10-18T00:00:00Z',completed_at='2026-10-18T00:00:00Z')

class ReadonlyDeliveryTests(unittest.TestCase):
 def test_render_has_smaller_caps_and_no_core_execution(self):
  body=b"raise RuntimeError('must not execute while rendering')\n"
  built=D.render(body,D.sha(body))
  self.assertLessEqual(built['sizes']['wire'],D.MAX_WIRE);self.assertLessEqual(built['sizes']['ssh'],D.MAX_SSH)
  self.assertEqual(built['script_sha256'],D.sha(built['script'].encode()))
 def test_render_exact_pin_required(self):
  with self.assertRaises(D.Refused):D.render(SYNTHETIC,'0'*64)
 def test_render_source_cap(self):
  body=b' '*(D.MAX_SOURCE+1)
  with self.assertRaises(D.Refused):D.render(body,D.sha(body))
 def test_bootstrap_single_observe_and_discard(self):
  output=bootstrap(SYNTHETIC)
  self.assertEqual(len(output.splitlines()),1);self.assertNotIn('not-public',output)
  value=D.strict(output.strip().encode()[len(D.MARKER):])
  self.assertEqual(value['observation'],{'calls':1});self.assertTrue(value['transport_ok'])
 def test_bootstrap_exception_closed(self):
  body=SYNTHETIC.replace(b"return {'calls':calls}",b"raise RuntimeError('private exception path')")
  output=bootstrap(body);self.assertNotIn('private exception',output)
  value=D.strict(output.strip().encode()[len(D.MARKER):]);self.assertFalse(value['transport_ok']);self.assertEqual(value['error'],'HOST_UNAVAILABLE')
 def test_json_duplicate_nan_and_noncanonical(self):
  for raw in (b'{"x":1,"x":1}',b'{"x":NaN}',b'{"x": 1}'):
   with self.subTest(raw=raw),self.assertRaises((D.Refused,ValueError)):D.strict(raw)
 def test_json_depth_and_size(self):
  for raw in (b'['*13+b'0'+b']'*13,b' '*17409):
   with self.assertRaises(D.Refused):D.strict(raw)
 def test_result_exact_keys_and_bool(self):
  core=D.load_core(SYNTHETIC,D.sha(SYNTHETIC));good=dict(schema='readonly-operation-state-transport-v1',transport_ok=True,phase='complete',error=None,observation={'calls':1})
  self.assertIs(D.result(good,core),good)
  for change in ({'transport_ok':1},{'extra':0},{'phase':'unexpected'},{'error':'SOURCE'}):
   with self.assertRaises(D.Refused):D.result(dict(good,**change),core)
 def test_failure_cannot_carry_observation(self):
  core=D.load_core(SYNTHETIC,D.sha(SYNTHETIC));bad=dict(schema='readonly-operation-state-transport-v1',transport_ok=False,phase='observe',error='HOST_UNAVAILABLE',observation={'calls':1})
  with self.assertRaises(D.Refused):D.result(bad,core)
 def test_actual_docker_wrapper_and_post_step_gaps(self):
  rows=[step('Set up job',1),step(Q.BUILD_WRAPPER,2)]+[step(n,i+3) for i,n in enumerate(Q.DISPATCH_STEPS)]+[step('Post Python 3.12',21),step('Post Checkout exact source',22),step('Complete job',23)]
  self.assertEqual(tuple(Q.steps({'steps':rows},Q.DISPATCH_STEPS,docker=True)),Q.DISPATCH_STEPS)
 def test_duplicate_or_late_docker_step_refused(self):
  rows=[step(n,i+1) for i,n in enumerate(Q.DISPATCH_STEPS)]+[step(Q.BUILD_WRAPPER,9)]
  with self.assertRaises(Q.Refused):Q.steps({'steps':rows},Q.DISPATCH_STEPS,docker=True)
  rows=[step(Q.BUILD_WRAPPER,1),step(Q.BUILD_WRAPPER,2)]+[step(n,i+3) for i,n in enumerate(Q.DISPATCH_STEPS)]
  with self.assertRaises(Q.Refused):Q.steps({'steps':rows},Q.DISPATCH_STEPS,docker=True)
 def test_step_numbers_bool_duplicate_or_unsorted_refused(self):
  for numbers in ([True,2,3,4],[1,2,2,4],[1,3,2,4]):
   with self.subTest(numbers=numbers),self.assertRaises(Q.Refused):Q.steps({'steps':[step(n,i) for n,i in zip(Q.DISPATCH_STEPS,numbers)]},Q.DISPATCH_STEPS)
 def test_two_jobs_exact_event_split(self):
  base=dict(run_id=7,head_sha='a'*40,run_attempt=1,status='completed',steps=[])
  good={'total_count':2,'jobs':[dict(base,id=8,name='qualify-readonly',conclusion='success'),dict(base,id=9,name='observe-once',conclusion='skipped')]}
  self.assertEqual(Q.selected_job(good,7,'a'*40,'push')['id'],8)
  bad=json.loads(json.dumps(good));bad['jobs'][1]['conclusion']='success'
  with self.assertRaises(Q.Refused):Q.selected_job(bad,7,'a'*40,'push')
 def test_marker_exactly_one(self):
  line=b'2026-10-18T00:00:00.100Z out: '+D.MARKER+b'{"x":1}\n'
  self.assertEqual(R.marker(line,D.MARKER,step('x'),D),{'x':1})
  with self.assertRaises(Q.Refused):R.marker(line+line,D.MARKER,step('x'),D)
 def test_malformed_same_prefix_cannot_hide(self):
  good=b'2026-10-18T00:00:00.100Z out: '+D.MARKER+b'{"x":1}\n'
  for bad in (b'2026-10-18T00:00:00.100Z out: '+D.MARKER[:-1]+b'BROKEN\n',b'BAD out: '+D.MARKER+b'{"x":1}\n',D.MARKER+b'{"x":1}\n'):
   with self.subTest(bad=bad),self.assertRaises(Q.Refused):R.marker(bad+good,D.MARKER,step('x'),D)
 def test_marker_time_window_closed(self):
  line=b'2026-10-18T00:00:01.000Z out: '+D.MARKER+b'{"x":1}\n'
  with self.assertRaises(Q.Refused):R.marker(line,D.MARKER,step('x'),D)
 def test_run_metadata_alias_and_wrong_head_refused(self):
  run=dict(id=7,head_sha='a'*40,head_branch=Q.BRANCH,path=Q.WORKFLOW,event='push',run_attempt=1,status='completed',conclusion='success',workflow_id=3,repository={'full_name':Q.REPO})
  self.assertIs(Q.run_bound(run,7,'a'*40,Q.WORKFLOW,'push'),run)
  for change in ({'id':True},{'head_sha':'b'*40},{'run_attempt':True}):
   with self.assertRaises(Q.Refused):Q.run_bound(dict(run,**change),7,'a'*40,Q.WORKFLOW,'push')
 def test_unregistered_candidate_cannot_qualify(self):
  with patch.object(Q,'SOURCE_PINS',None),self.assertRaises(Q.Refused):Q.registration(HERE)

 def test_fixture_preserves_closed_actual_absent_values(self):
  for code,kind in ((0,'empty'),(4,'zero32')):
   value=json.loads(json.dumps(Q.FIXTURE_EXPECTED));value['absent_service']=dict(exit_status=code,schema_issue='none',load_not_found=True,invocation_format=kind)
   self.assertIs(Q.fixture_result(value),value)
 def test_fixture_failed_checks_and_aliases_refused(self):
  good=json.loads(json.dumps(Q.FIXTURE_EXPECTED));good['absent_service']=dict(exit_status=4,schema_issue='none',load_not_found=True,invocation_format='empty')
  cases=[]
  x=json.loads(json.dumps(good));x['checks']['root_anchor_nofollow']=False;cases.append(x)
  x=json.loads(json.dumps(good));x['checks']['root_anchor_nofollow']=1;cases.append(x)
  x=json.loads(json.dumps(good));x['absent_service']['exit_status']=True;cases.append(x)
  x=json.loads(json.dumps(good));x['extra']=False;cases.append(x)
  for value in cases:
   with self.assertRaises(Q.Refused):Q.fixture_result(value)
 def test_fixture_unobserved_or_raw_invocation_refused(self):
  good=json.loads(json.dumps(Q.FIXTURE_EXPECTED));good['absent_service']=dict(exit_status=4,schema_issue='none',load_not_found=True,invocation_format='empty')
  for key,value in (('invocation_format','a'*32),('schema_issue','unobserved'),('load_not_found',None),('exit_status',None)):
   bad=json.loads(json.dumps(good));bad['absent_service'][key]=value
   with self.assertRaises(Q.Refused):Q.fixture_result(bad)

 def test_unknown_marker_family_version_refused(self):
  good=b'2026-10-18T00:00:00.100Z out: '+D.MARKER+b'{"x":1}\n'
  for literal in (b'NAVER_MARKET_OPERATION_STATE_V2=',b'NAVER_MARKET_OPERATION_STATE_QUALIFICATION_V2=',b'NAVER_MARKET_OPERATION_STATE_OTHER='):
   with self.assertRaises(Q.Refused):R.marker(b'2026-10-18T00:00:00.100Z out: '+literal+b'{}\n'+good,D.MARKER,step('x'),D)
 def test_known_other_marker_and_script_echo_are_separate(self):
  good=b'2026-10-18T00:00:00.100Z out: '+D.MARKER+b'{"x":1}\n'
  other=b'2026-10-18T00:00:00.100Z '+Q.BUILD_MARKER.encode()+b'{"other":1}\n'
  echo=b"2026-10-18T00:00:00.100Z print('NAVER_MARKET_OPERATION_STATE_UNKNOWN=')\n"
  self.assertEqual(R.marker(other+echo+good,D.MARKER,step('x'),D),{'x':1})
 def test_ci_public_evidence_readable_and_exclusive(self):
  with tempfile.TemporaryDirectory() as folder:
   target=Path(folder)/'audit.closed.json';old=os.umask(0o077)
   try:C.write_new(target,b'{"status":"failed"}')
   finally:os.umask(old)
   self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o644)
   with self.assertRaises(FileExistsError):C.write_new(target,b'{}')
 def test_ci_failed_ids_counts_without_exception_text(self):
  source=b"import unittest\nclass Fixed(unittest.TestCase):\n def test_fail(self):self.fail('not-public-value')\n def test_error(self):raise RuntimeError('not-public-error')\n @unittest.skip('not-public-reason')\n def test_skip(self):pass\n"
  report=C.execute(source,HERE/'synthetic_ci.py','synthetic_ci',3)
  self.assertEqual(report['status'],'failed');self.assertEqual(report['phase'],'complete')
  self.assertEqual([report[x] for x in ('executed','failures','errors','skipped')],[3,1,1,1])
  self.assertEqual(report['failed_ids'],['synthetic_ci.Fixed.test_fail']);self.assertNotIn('not-public',json.dumps(report))
 def test_ci_subtest_id_binds_registered_parent(self):
  source=b"import unittest\nclass Fixed(unittest.TestCase):\n def test_parent(self):\n  with self.subTest(value='not-public'):self.fail('not-public')\n"
  report=C.execute(source,HERE/'synthetic_ci.py','synthetic_ci',1)
  self.assertEqual(report['failed_ids'],['synthetic_ci.Fixed.test_parent']);self.assertNotIn('not-public',json.dumps(report))
 def test_ci_registry_or_load_failure_cannot_pass(self):
  sources=(b"raise RuntimeError('not-public')",b"import unittest\nclass Fixed(unittest.TestCase):\n def test_only(self):pass\n")
  for source in sources:
   report=C.execute(source,HERE/'synthetic_ci.py','synthetic_ci',2)
   self.assertEqual(report['status'],'failed');self.assertEqual(report['executed'],0);self.assertNotIn('not-public',json.dumps(report))
 def test_registry_mismatch_precedes_renderer(self):
  inputs=dict(confirm=Q.CONFIRM,native_run_id='7',audit_run_id='8',registry_sha256='0'*64)
  ctx=dict(repository=Q.REPO,ref='refs/heads/'+Q.BRANCH,event='workflow_dispatch',run_attempt=1,head_sha='a'*40,run_id=9)
  with patch.object(Q,'qualify',return_value=({'closed':True},{})),patch.object(Q,'module') as module,self.assertRaises(Q.Refused):Q.build(HERE,inputs,ctx)
  module.assert_not_called()
 def test_audit_source_head_exact_newline_and_case(self):
  head='a'*40;item=dict(id=99,size_in_bytes=10,digest='sha256:'+'b'*64)
  A=types.SimpleNamespace(run=lambda _: {},jobs=lambda _: {},artifacts=lambda _: {},artifact_zip=lambda _:b'zip')
  for bad in (head.encode(),(head+'\r\n').encode(),('A'*40+'\n').encode()):
   members={'source-sha.txt':bad,'source-manifest.closed.json':b'{}','audit.closed.json':b'{}'}
   G=types.SimpleNamespace(unpack=lambda *args:members,strict=lambda *args:self.fail('manifest parsing must follow exact source binding'))
   with patch.object(Q,'run_bound',return_value={'workflow_id':11}),patch.object(Q,'selected_job',return_value={'id':12}),patch.object(Q,'steps'),patch.object(Q,'artifact',return_value=item),self.assertRaisesRegex(Q.Refused,'AUDIT_SOURCE_HEAD'):
    Q.collect_audit(A,G,7,head,{})

 def test_ci_failure_preserves_only_three_closed_artifact_members(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);location=root/Q.BASE/'ci.py';location.parent.mkdir(parents=True)
   environment=dict(GITHUB_ACTIONS='true',RUNNER_ENVIRONMENT='github-hosted',RUNNER_OS='Linux',GITHUB_EVENT_NAME='push',GITHUB_REPOSITORY=Q.REPO,GITHUB_REF='refs/heads/'+Q.BRANCH,GITHUB_RUN_ATTEMPT='1',GITHUB_SHA='a'*40)
   report=dict(status='failed',phase='complete',executed=1,failures=1,errors=0,skipped=0,failed_ids=['registered.Fixed.test_case'])
   with patch.object(C,'__file__',str(location)),patch.object(C.sys,'argv',[str(location),'tests']),patch.dict(os.environ,environment,clear=True),patch.object(Q,'registration',return_value=({'test_core.py':b'', 'test_delivery.py':b''},{'closed':True})),patch.object(C,'execute',return_value=report),self.assertRaisesRegex(Q.Refused,'AUDIT_TEST_FAILURE'):C.main()
   evidence=root/C.EVIDENCE
   self.assertEqual({x.name for x in evidence.iterdir()},{'source-sha.txt','source-manifest.closed.json','audit.closed.json'})
   value=json.loads((evidence/'audit.closed.json').read_bytes());self.assertEqual(value['status'],'failed');self.assertEqual(value['phase'],'tests')
   self.assertFalse(value['operating_host_access']);self.assertFalse(value['production_state_observed'])
   self.assertEqual((evidence/'source-sha.txt').read_bytes(),('a'*40+'\n').encode())

 def test_ci_registered_success_requires_exact_count(self):
  source=b"import unittest\nclass Fixed(unittest.TestCase):\n def test_one(self):pass\n def test_two(self):pass\n"
  report=C.execute(source,HERE/'synthetic_ci.py','synthetic_ci',2)
  self.assertEqual(report['status'],'passed');self.assertEqual(report['phase'],'complete')
  self.assertEqual([report[x] for x in ('declared','discovered','executed')],[2,2,2])
  self.assertEqual(report['failed_ids'],[]);self.assertEqual(report['error_ids'],[])

if __name__=='__main__':unittest.main()
