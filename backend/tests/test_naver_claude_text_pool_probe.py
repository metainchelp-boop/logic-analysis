"""Offline core flow; optional actual-product integration still uses fake transport."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import types
import unittest
from unittest.mock import patch

KEY='SYNTHETIC_PRIVATE_KEY';CANARY='SYNTHETIC_PRIVATE_RESPONSE'
ENV={'NAVER_CLAUDE_ENABLED':'true','ANTHROPIC_API_KEY':KEY,'CLAUDE_MODEL':'claude-sonnet-5-5',
    'NAVER_CLAUDE_MONTHLY_CAP_USD':'unlimited','NAVER_CLAUDE_INPUT_USD_PER_MILLION':'3',
    'NAVER_CLAUDE_OUTPUT_USD_PER_MILLION':'15','NAVER_CLAUDE_TIMEOUT_SECONDS':'20'}
TOKENS=('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens',
    'cache_creation_5m_input_tokens','cache_creation_1h_input_tokens')


def fake_modules():
    engine=types.ModuleType('naver_engine');runtime=types.ModuleType('naver_runtime')
    s=types.ModuleType('naver_engine.marketing_strategy');c=types.ModuleType('naver_runtime.claude_provider')
    l=types.ModuleType('naver_runtime.learning_provider');o=types.ModuleType('naver_runtime.provider_observability')
    class Refused(ValueError):
        def __init__(self,code):self.code=code;super().__init__(code)
    def pairs(rows):
        result={}
        for k,v in rows:
            if k in result:raise ValueError('duplicate')
            result[k]=v
        return result
    s.StrategyRefused=Refused;s._json=lambda text:json.loads(text,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('constant')))
    class Request:
        full_url='https://api.anthropic.com/v1/messages';allow_redirects=False
        def __init__(self,*,data,headers):self.data,self.headers=data,headers
        def get_method(self):return 'POST'
        def __repr__(self):return 'ProviderRequest(fixed_endpoint)'
    c.ProviderRequest=Request;c.MAX_OUTPUT_TOKENS=4096;c.MAX_RESPONSE_BYTES=131072
    def text(blocks):
        if type(blocks) is not list or len(blocks)!=1 or type(blocks[0]) is not dict or blocks[0].get('type')!='text' or type(blocks[0].get('text')) is not str:raise Refused('PROVIDER_RESPONSE_INVALID')
        return blocks[0]['text']
    c._response_text=text
    def classify(response):
        try:raw=response.read(4097)
        except Exception:return 'http-error-read'
        if type(raw) is not bytes:return 'http-error-body-type'
        if len(raw)>4096:return 'http-error-body-size'
        try:value=s._json(raw.decode())
        except Exception:return 'http-error-json'
        return 'http-schema-complexity' if value.get('error',{}).get('message')=='Schema is too complex for compilation.' else 'http-error-unclassified'
    c._http400_diagnostic=classify
    def factory(env=None):
        env=os.environ if env is None else env
        if env.get('NAVER_CLAUDE_ENABLED')!='true':return None
        try:
            if not env.get('ANTHROPIC_API_KEY') or not env.get('CLAUDE_MODEL'):raise ValueError()
            for field in ('NAVER_CLAUDE_INPUT_USD_PER_MILLION','NAVER_CLAUDE_OUTPUT_USD_PER_MILLION'):
                if not 0<float(env[field])<=10000:raise ValueError()
            timeout=float(env.get('NAVER_CLAUDE_TIMEOUT_SECONDS','10'))
            if not 1<=timeout<=20:raise ValueError()
        except Exception:raise Refused('PROVIDER_CONFIGURATION_INVALID') from None
        return types.SimpleNamespace(model=env['CLAUDE_MODEL'],_api_key=env['ANTHROPIC_API_KEY'],_timeout=timeout,monthly_budget_unlimited=env.get('NAVER_CLAUDE_MONTHLY_CAP_USD')=='unlimited')
    l.provider_from_environment=factory;l._transport=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Uninjected transport'))
    l._transport_error=lambda error:'PROVIDER_TIMEOUT' if isinstance(error,TimeoutError) else 'PROVIDER_NETWORK_ERROR' if isinstance(error,OSError) else 'PROVIDER_UNAVAILABLE'
    o._HTTP400_DIAGNOSTICS=frozenset(('http-schema-complexity','http-error-read','http-error-body-type','http-error-body-size','http-error-json','http-error-unclassified'))
    codes={'PROVIDER_CONFIGURATION_INVALID':'configuration','PROVIDER_NOT_CONFIGURED':'configuration','PROVIDER_TIMEOUT':'timeout','PROVIDER_NETWORK_ERROR':'network','PROVIDER_UNAVAILABLE':'unknown','PROVIDER_RESPONSE_INVALID':'response-shape','PROVIDER_RESPONSE_SIZE':'response-size','PROVIDER_ENVELOPE_JSON_INVALID':'envelope-json','PROVIDER_RESPONSE_TRUNCATED':'truncated'}
    o.diagnostic=lambda e:codes.get(e if type(e) is str else getattr(e,'code',None),'unknown')
    def usage(raw):
        result={key:None for key in TOKENS}
        if raw is None:return {'status':'unavailable',**result}
        if type(raw) is not dict:return {'status':'invalid',**result}
        invalid=False
        for key in TOKENS[:4]:
            if key not in raw:continue
            if type(raw[key]) is int and 0<=raw[key]<=2**53-1:result[key]=raw[key]
            else:invalid=True
        return {'status':'invalid' if invalid else 'partial' if any(v is not None for v in result.values()) else 'unavailable',**result}
    o.parse_usage=usage
    engine.marketing_strategy=s;runtime.claude_provider=c;runtime.learning_provider=l;runtime.provider_observability=o
    return {m.__name__:m for m in (engine,runtime,s,c,l,o)}

spec=importlib.util.spec_from_file_location('naver_claude_text_pool_probe',Path(__file__).parents[1]/'tools/naver_claude_text_pool_probe.py')
P=importlib.util.module_from_spec(spec)
if os.environ.get('MINIMAL_PROBE_ACTUAL_PRODUCT')=='1':spec.loader.exec_module(P)
else:
    with patch.dict(sys.modules,fake_modules()):spec.loader.exec_module(P)


def success(text='OK',**extra):
    return json.dumps({'stop_reason':'end_turn','content':[{'type':'text','text':text}],
        'usage':{'input_tokens':7,'output_tokens':1},'id':CANARY,**extra}).encode()

class Response(io.BytesIO):
    def __init__(self,raw,status=200):super().__init__(raw);self.status=status;self.reads=[];self.closes=0
    def read(self,limit=-1):self.reads.append(limit);return super().read(limit)
    def close(self):self.closes+=1;super().close()
    @property
    def headers(self):raise AssertionError('Header read forbidden')

class TextPoolSchemaProbeTests(unittest.TestCase):
    def setUp(self):
        for method in ('connect','connect_ex'):
            guard=patch.object(socket.socket,method,side_effect=AssertionError('Real network forbidden'));guard.start();self.addCleanup(guard.stop)

    def call(self,response=None,env=None,error=None):
        calls=[]
        def transport(request,*,timeout):
            calls.append((request,timeout))
            if error is not None:raise error
            return response
        with patch.object(P.LP,'_transport',side_effect=transport):result=P.run(dict(ENV) if env is None else env)
        self.assertEqual(set(result),{'version','probe','ok','stage','diagnostic','http_status','transport_calls','response_closed','message_terms','checks','usage','elapsed_ms'})
        self.assertEqual(result['transport_calls'],len(calls));self.assertLessEqual(len(calls),1)
        self.assertEqual(set(result['checks']),{'http_200','end_turn','text_nonempty','exact_ok'})
        self.assertTrue(all(v is None or type(v) is bool for v in result['checks'].values()))
        encoded=json.dumps(result,allow_nan=False)
        for private in (KEY,CANARY,'x-api-key','request_id'):self.assertNotIn(private,encoded)
        self.assertTrue(type(result['elapsed_ms']) is int and 0<=result['elapsed_ms']<=2**53-1)
        self.assertEqual(set(result['usage']),{'status',*TOKENS})
        self.assertTrue(all(v is None or type(v) is int and 0<=v<=2**53-1 for k,v in result['usage'].items() if k!='status'))
        return result,calls

    def test_fixed_schema_matches_frozen_generation_witness_and_preserves_shape(self):
        raw=json.dumps(P.SCHEMA,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'a355cbed9cc83350cfd371169d35ae59bb463fcf9c1b6f01e3aa4b9d7ef5255d')
        self.assertEqual(len(raw),2059)
        schema=P.SCHEMA['schema']
        self.assertEqual(P.PROBE,'claude-text-pool-schema-v1')
        self.assertEqual(set(schema['properties']),{'diagnosis','direction','shared_comment','appeal_points','weekly_plan','monthly_plan','funnel_comment','texts'})
        self.assertEqual(set(schema['required']),set(schema['properties']))
        self.assertIs(schema['additionalProperties'],False)
        self.assertEqual(set(schema['definitions']),{'t','plan','hypothesis'})
        self.assertEqual(schema['properties']['texts'],{'type':'array','items':{'$ref':'#/definitions/t'},'minItems':1})
        self.assertEqual(schema['properties']['appeal_points']['items']['properties']['basis_id'],{'type':'string'})
        self.assertEqual(hashlib.sha256(schema['definitions']['t']['pattern'].encode()).hexdigest(),'6a7c09b8c7c5eca439c68b5a761178205429501d5c6c5a26ef6689ce6f099d5a')
        self.assertEqual(raw.count(b'"$ref":"#/definitions/t"'),1)
        def check(node):
            if type(node) is dict:
                self.assertFalse({'minimum','maximum','maxItems'} & set(node))
                if node.get('type')=='object':
                    self.assertEqual(set(node['properties']),set(node['required']))
                    self.assertIs(node['additionalProperties'],False)
                for value in node.values():check(value)
            elif type(node) is list:
                for value in node:check(value)
        check(P.SCHEMA)

    def test_only_format_variable_in_fixed_request_one_call_and_original_envelope_checks(self):
        response=Response(success('{"texts":["OK"]}'));r,calls=self.call(response)
        body=json.loads(calls[0][0].data)
        self.assertEqual(body,{'model':'claude-sonnet-5-5','max_tokens':4096,'messages':[{'role':'user','content':'Reply with OK.'}],'thinking':{'type':'between_tools'},'output_config':{'effort':'medium','format':P.SCHEMA}})
        self.assertEqual(calls[0][1],20)
        self.assertEqual(calls[0][0].headers,{'x-api-key':KEY,'anthropic-version':'2023-06-01','Content-Type':'application/json'})
        self.assertEqual((r['probe'],r['http_status'],r['transport_calls'],r['response_closed']),(P.PROBE,200,1,True))
        self.assertTrue(r['ok']);self.assertFalse(r['checks']['exact_ok']);self.assertIsNone(r['message_terms'])
        self.assertEqual((response.reads,response.closes),([131073],1))
        self.assertNotIn('system',body)
        self.assertEqual(P.MAX_ERROR_BODY_BYTES,4096)
        self.assertEqual(P.CP.MAX_RESPONSE_BYTES,131072)

if __name__=='__main__':unittest.main(verbosity=2)
