"""Refresh-only transport/qualification boundaries; no API or host operation."""
import base64
import copy
import importlib.util
import lzma
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('refresh_adapter_tested',HERE/'adapter.py')
A=importlib.util.module_from_spec(spec);spec.loader.exec_module(A)
ROOT=next((p for p in HERE.parents if (p/A.OLD/'delivery.py').is_file()),None)
if ROOT is None:ROOT=Path('/Users/sinyosub/Documents/Codex/2026-10-07/new-chat-2/work/naver-claude-reference-ops-20261011')

def buffers():
 return ({'core.py':(HERE/'core.py').read_bytes(),'adapter.py':(HERE/'adapter.py').read_bytes()},
  {n:A.fixed_read(ROOT,A.OLD+n+'.py',p) for n,p in A.MODULE_PINS.items()},
  {n:A.fixed_read(ROOT,p,h) for n,(p,h) in A.PUBLIC.items()},
  A.fixed_read(ROOT,A.OLD+'delivery.py',A.DELIVERY_PIN))

def jobs(event='push'):
 return {'total_count':3,'jobs':[dict(id=i+10,name=n,run_id=23,head_sha='a'*40,run_attempt=1,status='completed',
  conclusion='success' if (event=='push')==(n!='refresh-once') else 'skipped',steps=[]) for i,n in enumerate(A.JOBS)]}

class AdapterTests(unittest.TestCase):
 def test_fixed_id_and_type(self):
  self.assertIs(A.request(A.REQUEST),A.REQUEST)
  for v in ({'version':True,'refresh_id':A.REQUEST['refresh_id']},{'version':1,'refresh_id':'a'*32},{**A.REQUEST,'action':'refresh'}):
   with self.assertRaises(A.Refused):A.request(v)
 def test_duplicate_nonfinite_canonical(self):
  for raw in (b'{"x":1,"x":2}',b'{"x":NaN}',b'{ "x":1}',b'{"x":Infinity}'):
   with self.assertRaises(A.Refused):A.strict(raw)
 def test_wire_bounds(self):
  for wire in ('','x'*(A.WIRE_MAX+1),'\u2603'):
   with self.assertRaises(A.Refused):A.decode(wire)
 def test_decoder_bomb_trailing_and_truncated(self):
  raws=(lzma.compress(b'x'*(A.JSON_MAX+1)),lzma.compress(b'{}')+b'x',lzma.compress(b'{}')[:-1])
  for raw in raws:
   with self.assertRaises(A.Refused):A.decode(base64.b85encode(raw).decode())
 def test_exact_sources_and_roundtrip(self):
  value=A.package(*buffers());self.assertEqual(A.decode(A.encode(value)),value)
  report=A.render(value)
  for field,limit in (('json',A.JSON_MAX),('wire',A.WIRE_MAX),('boot',A.BOOT_MAX),('ssh',A.SSH_MAX)):
   self.assertLessEqual(report['sizes'][field],limit)
 def test_core_tamper(self):
  value=A.package(*buffers())['payload'];value['core']+='\n'
  with self.assertRaises(A.Refused):A.host_payload(value)
 def test_module_and_public_tamper(self):
  original=A.package(*buffers())['payload']
  for group,name in (('modules','transition'),('public','exports_helper')):
   value=copy.deepcopy(original);value[group][name]+='\n'
   with self.assertRaises(ValueError):A.host_payload(value)
 def test_source_missing_extra_alias(self):
  original=A.package(*buffers())['payload']
  for change in ('missing','extra','alias'):
   value=copy.deepcopy(original)
   if change=='missing':del value['modules']['journal']
   elif change=='extra':value['public']['unknown']='x'
   else:value['request']['version']=True
   with self.assertRaises(ValueError):A.host_payload(value)
 def test_module_collision_and_cleanup(self):
  with patch.dict(sys.modules,{'refresh_collision':object()}):
   with self.assertRaises(A.Refused):
    with A.modules({'refresh_collision':b'x=1'}):pass
  with self.assertRaises(RuntimeError):
   with A.modules({'refresh_clean':b'x=1'}):raise RuntimeError()
  self.assertNotIn('refresh_clean',sys.modules)
 def test_actual_dependency_order(self):
  self.assertEqual(tuple(A.MODULE_PINS),('transition','journal','preflight','systemd_boundary','current_guard'))
  with A.core_module(A.package(*buffers())['payload']) as (core,public):
   self.assertEqual(core.RESTORED_APPLY,'fe01f9ef77664899845a10f45b614a61')
   self.assertIs(core.J,sys.modules['journal']);self.assertEqual(len(public),5)
  self.assertNotIn('transition',sys.modules)
 def test_three_jobs_exact(self):
  self.assertEqual(set(A.selected_jobs(jobs(),23,'a'*40,'push')),{'portable-refresh','linux-refresh'})
  self.assertEqual(set(A.selected_jobs(jobs('workflow_dispatch'),23,'a'*40,'workflow_dispatch')),{'refresh-once'})
 def test_extra_duplicate_wrong_jobs(self):
  for change in ('extra','duplicate','head','attempt','skipped'):
   value=jobs()
   if change=='extra':value['jobs'].append(copy.deepcopy(value['jobs'][0]));value['total_count']=4
   elif change=='duplicate':value['jobs'][2]['name']='portable-refresh'
   elif change=='head':value['jobs'][0]['head_sha']='b'*40
   elif change=='attempt':value['jobs'][0]['run_attempt']=True
   else:value['jobs'][2]['steps']=[{}]
   with self.assertRaises(A.Refused):A.selected_jobs(value,23,'a'*40,'push')
 def test_fixture_exact_not_workflow_green(self):
  value=dict(schema='original-market-refresh-empty-linux-vm-v1',status='passed',checks={k:True for k in A.FIXTURE_CHECKS},**{k:False for k in A.FIXTURE_FLAGS})
  self.assertIs(A.fixture_result(value),value)
  for change in ('missing','false','alias','extra','operating'):
   v=copy.deepcopy(value)
   if change=='missing':del v['checks'][A.FIXTURE_CHECKS[0]]
   elif change=='false':v['checks'][A.FIXTURE_CHECKS[0]]=False
   elif change=='alias':v['checks'][A.FIXTURE_CHECKS[0]]=1
   elif change=='extra':v['unregistered']=False
   else:v[A.FIXTURE_FLAGS[0]]=True
   with self.assertRaises(A.Refused):A.fixture_result(v)
 def test_build_wrong_context_no_api(self):
  inputs=dict(confirm=A.CONFIRM,native_run_id='1',refresh_run_id='2',registry_sha256='a'*64)
  context=dict(repository=A.REPO,ref='refs/heads/'+A.BRANCH,event='workflow_dispatch',run_attempt=1,head_sha='a'*40,run_id=3)
  for key,value in (('repository','elsewhere/repo'),('event','push'),('run_attempt',True),('run_id',1)):
   bad=dict(context);bad[key]=value
   with patch.object(A,'qualify',side_effect=AssertionError('unexpected API')):
    with self.assertRaises(A.Refused):A.build(ROOT,inputs,bad)
 def test_build_mismatched_registry_before_render(self):
  inputs=dict(confirm=A.CONFIRM,native_run_id='1',refresh_run_id='2',registry_sha256='a'*64)
  context=dict(repository=A.REPO,ref='refs/heads/'+A.BRANCH,event='workflow_dispatch',run_attempt=1,head_sha='a'*40,run_id=3)
  with patch.object(A,'qualify',return_value=({'fixed':True},{})),patch.object(A,'render',side_effect=AssertionError('unexpected render')):
   with self.assertRaises(A.Refused):A.build(ROOT,inputs,context)
 def test_read_exact_bytes_symlink_and_hash(self):
  with tempfile.TemporaryDirectory() as p:
   root=Path(p).resolve();(root/'source.py').write_bytes(b'x=1\n')
   self.assertEqual(A.fixed_read(root,'source.py',A.sha(b'x=1\n')),b'x=1\n')
   (root/'link.py').symlink_to(root/'source.py')
   for rel,pin in (('link.py',None),('source.py','0'*64),('../escape.py',None)):
    with self.assertRaises(A.Refused):A.fixed_read(root,rel,pin)
 def test_public_result_failure_not_export_success(self):
  payload=A.package(*buffers())['payload']
  unknown=dict(version=1,transport_ok=False,phase='entrypoint',error_code='TRANSPORT_REFUSED',result=None)
  self.assertIs(A.validate_observation(unknown,payload),unknown)
  for change in ({**unknown,'result':{'attempt_consumed':False}},{**unknown,'phase':'unknown'},{**unknown,'transport_ok':0}):
   with self.assertRaises(A.Refused):A.validate_observation(change,payload)
  with A.core_module(payload) as (C,_):
   value=C._result('REFRESH_REFUSED')
   self.assertEqual(value['status'],'refused');self.assertFalse(value['original_export_success_verified'])
   value['original_export_success_verified']=True
   with self.assertRaises(ValueError):C.validate(value)
 def test_caps_and_request_receipt(self):
  self.assertEqual(A.HOST_MAX,32768)
  with self.assertRaisesRegex(A.Refused,'^HOST_SIZE$'):A.render({'adapter':'x'*32769,'payload':{}})
  self.assertEqual((A.WIRE_MAX,A.JSON_MAX,A.BOOT_MAX,A.SSH_MAX,A.DECODER_MEMORY),(102400,393216,32768,131072,33554432))
  self.assertEqual(A.REQUEST,{'version':1,'refresh_id':'5375b7cd33134b23b3df27ae23efbd03'})
  self.assertEqual(A.REQUEST_RECEIPT,'0ccbd37ab58a7b9d1973f9473c8fd92d6c2f35bed5ec540eb81c9f6796bff185')

if __name__=='__main__':unittest.main()
