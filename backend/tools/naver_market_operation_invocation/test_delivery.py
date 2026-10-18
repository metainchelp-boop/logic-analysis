"""New fixed invocation delivery boundaries; synthetic observe only, no journal/API."""
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
 m=types.ModuleType('invocation_delivery_test_'+name);m.__file__=str(HERE/(name+'.py'))
 exec(compile((HERE/(name+'.py')).read_bytes(),m.__file__,'exec'),m.__dict__);return m
D,Q=load('delivery'),load('qualification')
with patch.dict(sys.modules,{'qualification':Q}):R=load('receiver')

def synthetic(contract=None):
 contract=D.CORE_CONTRACT if contract is None else contract
 head=''.join(k+'='+repr(v)+'\n' for k,v in contract.items())
 return (head+"calls=0\ndef observe():\n global calls\n calls+=1\n print('synthetic-private-message')\n return {'calls':calls}\n"
  "def validate(v):\n if type(v) is not dict or v!={'calls':1}:raise ValueError('synthetic-private-value')\n return v\n"
  "def closed_json(v):\n validate(v)\n return '{\"calls\":1}'\n").encode()

def boot(source=None):
 source=synthetic() if source is None else source
 with patch.object(D,'CORE_SHA256',D.sha(source)):script=D.render(source,D.sha(source))['script']
 return script.split("<<'READONLY_AUDIT_PY'\n",1)[1].rsplit('READONLY_AUDIT_PY\n',1)[0]

def run_boot(body):
 output=io.StringIO()
 with patch.dict(os.environ,{},clear=True),contextlib.redirect_stdout(output):exec(compile(body,'<synthetic-invocation-bootstrap>','exec'),{})
 result=output.getvalue();assert len(result.splitlines())==1 and 'synthetic-private' not in result
 assert result.startswith(D.MARKER.decode())
 return D.strict(result.strip().encode()[len(D.MARKER):])

def replace_wire(body,raw):
 wire=base64.b85encode(lzma.compress(raw,format=lzma.FORMAT_XZ,preset=6)).decode()
 return 'WIRE='+repr(wire)+'\n'+body.split('\n',1)[1]

def step(name,n=1):return dict(name=name,number=n,status='completed',conclusion='success',started_at='2026-10-18T03:14:45Z',completed_at='2026-10-18T03:15:18Z')

class InvocationDeliveryTests(unittest.TestCase):
 def test_exact_single_source_pressure_render_only(self):
  body=(HERE/'core.py').read_bytes();built=D.render(body,D.sha(body))
  for name,cap in (('source',49152),('package',65536),('wire',32768),('bootstrap',8192),('ssh',49152)):self.assertLessEqual(built['sizes'][name],cap)
  self.assertNotIn('dependencies',built['sizes']);self.assertEqual(D.DECODER_MEMORY,33554432)
 def test_source_hash_precedes_loading_or_observe(self):
  source=b"raise RuntimeError('synthetic-private-must-not-load')\n"
  with patch.object(D,'CORE_SHA256',D.sha(source)):
   self.assertIn('script',D.render(source,D.sha(source)))
   with self.assertRaises(D.Refused):D.load_core(source+b' ',D.sha(source))
 def test_core_contract_seven_exact_keys_and_fixed_failed_run(self):
  self.assertEqual(set(D.CORE_CONTRACT),{'APPLY','ROLLBACK','PLAN_SHA256','FAILED_RUN_ID','UNITS','WINDOW','PROVENANCE'})
  self.assertEqual(D.CORE_CONTRACT['FAILED_RUN_ID'],39092917351)
  for contract in (dict(D.CORE_CONTRACT,FAILED_RUN_ID=True),dict(D.CORE_CONTRACT,FAILED_RUN_ID=39092917352),dict(D.CORE_CONTRACT,extra=False)):
   with patch.object(D,'CORE_CONTRACT',contract),self.assertRaises(D.Refused):D.render((HERE/'core.py').read_bytes(),D.CORE_SHA256)
 def test_contract_recursive_type_aliases_refused(self):
  self.assertFalse(D.identical({'number':True},{'number':1}));self.assertFalse(D.identical(['same'],('same',)))
  self.assertFalse(D.identical({'x':[]},{'x':[]} | {'extra':False}))
  self.assertTrue(D.identical(D.CORE_CONTRACT,D.CORE_CONTRACT))
 def test_core_wrong_window_or_provenance_refused_before_observe(self):
  for key,bad in (('WINDOW',('other','window')),('UNITS',{'other':'unit'}),('PROVENANCE',{'other':'receipt'}),('PLAN_SHA256','0'*64)):
   values=dict(D.CORE_CONTRACT);values[key]=bad;source=synthetic(values)
   with patch.object(D,'CORE_SHA256',D.sha(source)),self.assertRaises(D.Refused):D.load_core(source,D.sha(source))
 def test_bootstrap_observe_once_without_arguments(self):
  value=run_boot(boot());self.assertTrue(value['transport_ok']);self.assertEqual(value['observation'],{'calls':1})
 def test_bootstrap_exception_is_closed_without_message(self):
  source=synthetic().replace(b"return {'calls':calls}",b"raise RuntimeError('synthetic-private-message')")
  value=run_boot(boot(source));self.assertEqual((value['phase'],value['error']),('observe','HOST_UNAVAILABLE'));self.assertIsNone(value['observation'])
 def test_bootstrap_extra_dependency_package_refused(self):
  raw=D.canonical({'version':1,'core':synthetic().decode(),'dependencies':{}})
  value=run_boot(replace_wire(boot(),raw));self.assertEqual((value['phase'],value['error']),('decode','PACKAGE'))
 def test_bootstrap_canonical_and_decoder_bound_preserved(self):
  raw=D.canonical({'version':1,'core':synthetic().decode()})
  for bad in (b' '+raw,b' '*(D.MAX_PACKAGE+1)):
   self.assertFalse(run_boot(replace_wire(boot(),bad))['transport_ok'])
 def test_closed_result_does_not_accept_raw_journal_or_message(self):
  source=synthetic()
  with patch.object(D,'CORE_SHA256',D.sha(source)):core=D.load_core(source,D.sha(source))
  good=dict(schema='readonly-operation-invocation-transport-v1',transport_ok=True,phase='complete',error=None,observation={'calls':1})
  self.assertIs(D.result(good,core),good)
  for key in ('MESSAGE','raw_journal','raw_events'):
   with self.assertRaises(D.Refused):D.result(dict(good,**{key:'synthetic-private'}),core)
 def test_unavailable_is_not_successful_observation(self):
  value=dict(schema='readonly-operation-invocation-transport-v1',transport_ok=False,phase='observe',error='HOST_UNAVAILABLE',observation=None)
  self.assertIs(D.result(value,None),value)
  with self.assertRaises(D.Refused):D.result(dict(value,transport_ok=True),None)
 def test_target_provenance_exact_three_receipts(self):
  p=Q.TARGET_PROVENANCE
  self.assertEqual(p['ledger']['run_id'],39097606812);self.assertEqual(p['restored_rollback']['run_id'],39095445014)
  self.assertEqual(p['ledger']['receipt_sha256'],'7dcdfc8b2ef2bf99766b2bd59595b27b22da3c6407fbcca0b735d96e95dfe3c6')
  self.assertEqual(p['restored_rollback']['receipt_sha256'],'d11910a1312430ca5f69bf3318b7d9b044f87ae0d0bd67fc442a5bd0dee0db2e')
  self.assertEqual(p['prior_apply_step']['receipt_sha256'],'e38e550f57d4d3d11e00407e2f6d615c1e517c04a9a52e301bf25b6ddd49ca0b')
  self.assertFalse(p['prior_apply_step']['host_clock_equivalence_proven'])
 def test_no_user_unit_window_path_command_inputs(self):
  inputs=dict(confirm=Q.CONFIRM,native_run_id='7',audit_run_id='8',registry_sha256='0'*64)
  ctx=dict(repository=Q.REPO,ref='refs/heads/'+Q.BRANCH,event='workflow_dispatch',run_attempt=1,head_sha='a'*40,run_id=9)
  with patch.object(Q,'qualify') as call:
   for key in ('units','window','path','command','operation_id'):
    with self.assertRaises(Q.Refused):Q.build(HERE,dict(inputs,**{key:'other'}),ctx)
   call.assert_not_called()
 def test_registry_mismatch_precedes_single_source_renderer(self):
  inputs=dict(confirm=Q.CONFIRM,native_run_id='7',audit_run_id='8',registry_sha256='0'*64)
  ctx=dict(repository=Q.REPO,ref='refs/heads/'+Q.BRANCH,event='workflow_dispatch',run_attempt=1,head_sha='a'*40,run_id=9)
  with patch.object(Q,'qualify',return_value=({'closed':True},{})),patch.object(Q,'module') as call,self.assertRaisesRegex(Q.Refused,'REGISTRY_BINDING'):Q.build(HERE,inputs,ctx)
  call.assert_not_called()
 def test_new_marker_family_exact_one_and_unknown_version(self):
  good=b'2026-10-18T03:14:46.100Z out: '+D.MARKER+b'{"closed":true}\n'
  self.assertEqual(R.marker(good,D.MARKER,step('result'),D),{'closed':True})
  for raw in (good+good,b'2026-10-18T03:14:46.100Z out: NAVER_MARKET_OPERATION_INVOCATION_V2={}\n'+good):
   with self.assertRaises(Q.Refused):R.marker(raw,D.MARKER,step('result'),D)
 def test_result_request_rebinding_precedes_api(self):
  with patch.object(R,'fixed_input',return_value={'fixed':True}),patch.object(Q,'registration') as call,self.assertRaisesRegex(Q.Refused,'FIXED_INPUT'):R.receive(HERE,{}, {'fixed':True,'window':'other'},9)
  call.assert_not_called()
 def test_unregistered_fixture_cannot_qualify(self):
  with patch.object(Q,'FIXTURE_EXPECTED',None),self.assertRaises(Q.Refused):Q.fixture_result({'status':'passed'})
 def test_invocation_push_unique_dispatch_shared_in_workflow(self):
  path=HERE/'naver-market-operation-invocation.yml'
  if not path.is_file():path=HERE.parents[2]/Q.WORKFLOW
  raw=path.read_text()
  self.assertIn("group: ${{ github.event_name == 'push' && 'qualify-market-operation-invocation' || 'deploy-logic-analysis' }}",raw)
  self.assertIn('cancel-in-progress: false',raw);self.assertIn('READ_MARKET_OPERATION_INVOCATION_ONCE',raw)

if __name__=='__main__':unittest.main()
