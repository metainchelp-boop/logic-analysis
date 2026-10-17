"""Offline core flow; optional actual-product integration still uses fake transport."""
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
SCHEMA_SHA256='b617c5387a4b25e2814058231e73ee3279c08276440d7023d6f20885ccdbb7cc'
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

spec=importlib.util.spec_from_file_location('naver_claude_capture_probe',Path(__file__).parents[1]/'tools/naver_claude_capture_probe.py')
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

class MinimalProbeTests(unittest.TestCase):
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
    def test_success_one_call_keeps_existing_model_thinking_and_token_policy(self):
        response=Response(success());r,calls=self.call(response)
        self.assertTrue(r['ok']);self.assertEqual(r['stage'],'completed');self.assertEqual(r['diagnostic'],'none')
        self.assertEqual(r['checks'],dict.fromkeys(('http_200','end_turn','text_nonempty','exact_ok'),True))
        request,timeout=calls[0];body=json.loads(request.data)
        self.assertEqual(body,{'model':'claude-sonnet-5-5','max_tokens':4096,'messages':[{'role':'user','content':'Reply with OK.'}],'thinking':{'type':'between_tools'},'output_config':{'effort':'medium','format':P.SCHEMA}})
        self.assertEqual((request.full_url,request.get_method(),request.allow_redirects,timeout),('https://api.anthropic.com/v1/messages','POST',False,20))
        self.assertEqual(set(request.headers),{'x-api-key','anthropic-version','Content-Type'});self.assertNotIn(KEY,repr(request))
        self.assertEqual((response.reads,response.closes,r['response_closed']),([131073],1,True))
        self.assertEqual((r['usage']['input_tokens'],r['usage']['output_tokens']),(7,1))
    def test_fixed_schema_is_exact_runtime_empty_basis_shape_without_advertiser_values(self):
        import hashlib
        encoded=(json.dumps(P.SCHEMA,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode()
        self.assertEqual(hashlib.sha256(encoded).hexdigest(),SCHEMA_SHA256)
        root=P.SCHEMA['schema'];self.assertEqual(set(root['definitions']),{'t','plan','hypothesis'})
        self.assertEqual(root['properties']['appeal_points']['items']['properties']['basis_id'],{'type':'string'})
        self.assertEqual(root['properties']['funnel_comment'],{'$ref':'#/definitions/hypothesis'})
        self.assertNotIn('competitive_response',root['properties'])
        if os.environ.get('MINIMAL_PROBE_ACTUAL_PRODUCT')=='1':
            from naver_runtime import report_output_schema as output
            context={'connected':{'product':True,'market':False},'setup':{},'funnel':{},
                'metrics':[{'key':key,'current':None,'status':'unavailable','absolute':None} for key in ('impressions','clicks','conversions','ctr','cvr')],
                'quality':{'basic':{'complete':False}}}
            expected=output.output_format(context,basis_ids=());pattern=expected['schema']['definitions']['t']['pattern'];self.assertEqual(pattern.count('(?:'),1);expected['schema']['definitions']['t']['pattern']=pattern.replace('(?:','(',1);self.assertEqual(P.SCHEMA,expected)
        for field,reason in (('messages[0].content[0]','http-messages-parameter'),('max_tokens','http-max-tokens-parameter'),('system','http-system-parameter')):
            raw=json.dumps({'type':'error','error':{'type':'invalid_request_error','message':field+': '+CANARY}}).encode()
            result,_=self.call(Response(raw,400));self.assertEqual(result['diagnostic'],reason)
    def test_disabled_invalid_configuration_and_limited_policy_never_call(self):
        variants=[dict(ENV,NAVER_CLAUDE_ENABLED='false'),dict(ENV,ANTHROPIC_API_KEY=''),dict(ENV,CLAUDE_MODEL=''),dict(ENV,NAVER_CLAUDE_INPUT_USD_PER_MILLION='invalid'),dict(ENV,NAVER_CLAUDE_TIMEOUT_SECONDS='21'),dict(ENV,NAVER_CLAUDE_MONTHLY_CAP_USD='1')]
        for index,env in enumerate(variants):
            with self.subTest(index=index):
                r,calls=self.call(env=env);self.assertFalse(r['ok']);self.assertEqual(calls,[]);self.assertIsNone(r['http_status']);self.assertEqual(r['stage'],'configuration')
        self.assertEqual(self.call(env=variants[0])[0]['diagnostic'],'not-enabled')
        self.assertEqual(self.call(env=variants[-1])[0]['diagnostic'],'unsupported-policy')
    def test_disabled_does_not_read_credentials_and_other_model_omits_thinking(self):
        class Disabled(dict):
            def get(self,key,default=None):
                if 'KEY' in key:raise AssertionError('Credential read')
                return 'false' if key=='NAVER_CLAUDE_ENABLED' else default
        self.assertEqual(self.call(env=Disabled())[0]['diagnostic'],'not-enabled')
        _,calls=self.call(Response(success()),env=dict(ENV,CLAUDE_MODEL='synthetic-model'))
        self.assertEqual(set(json.loads(calls[0][0].data)),{'model','max_tokens','messages','output_config'});self.assertEqual(json.loads(calls[0][0].data)['output_config'],{'format':P.SCHEMA})
    def test_transport_failure_is_closed_before_http_and_has_no_retry(self):
        for error,code in ((TimeoutError(CANARY),'timeout'),(OSError(CANARY),'network'),(RuntimeError(CANARY),'unknown')):
            with self.subTest(code=code):
                r,calls=self.call(error=error);self.assertEqual(len(calls),1);self.assertFalse(r['ok']);self.assertEqual(r['diagnostic'],code);self.assertIsNone(r['http_status']);self.assertIsNone(r['response_closed'])
    def test_http400_reuses_bounded_closed_classifier_and_other_statuses_do_not_read(self):
        for raw,code in ((b'{"type":"error","error":{"type":"invalid_request_error","message":"Schema is too complex for compilation."}}','http-schema-complexity'),(b'{"type":"error","error":{"type":"invalid_request_error","message":"'+CANARY.encode()+b'"}}','http-error-unclassified'),(b'x'*4097,'http-error-body-size')):
            response=Response(raw,400);r,_=self.call(response);self.assertEqual((r['diagnostic'],r['http_status'],response.reads,response.closes),(code,400,[4097],1));self.assertFalse(r['ok'])
        for status in (302,401,403,429,500):
            response=Response(CANARY.encode(),status);r,_=self.call(response);self.assertEqual((r['diagnostic'],response.reads,response.closes),('http',[],1))
    def test_success_body_json_shape_and_exact_size_boundaries(self):
        good=success()
        examples=[(b'not-json','envelope-json'),(b'\xff','envelope-json'),(b'{"a":1,"a":2}','envelope-json'),(b'{"x":NaN}','envelope-json'),(b'[]','response-shape'),(success(stop_reason='max_tokens'),'truncated'),(success(stop_reason='refusal'),'response-shape'),(success(stop_reason='stop_sequence'),'response-shape'),(success(stop_reason=None),'response-shape'),(success('  '),'response-shape'),(b'x'*131073,'response-size')]
        for raw,code in examples:
            with self.subTest(code=code):
                response=Response(raw);r,_=self.call(response);self.assertFalse(r['ok']);self.assertEqual(r['diagnostic'],code);self.assertEqual((response.reads,response.closes),([131073],1))
        response=Response(good+b' '*(131072-len(good)));self.assertTrue(self.call(response)[0]['ok'])
    def test_nonempty_text_and_usage_are_sanitized_without_echo_or_fake_cost(self):
        r,_=self.call(Response(success(CANARY,usage={'input_tokens':True,'output_tokens':'7','cache_read_input_tokens':-1,'cache_creation_input_tokens':2**53})))
        self.assertTrue(r['ok']);self.assertFalse(r['checks']['exact_ok']);self.assertEqual(r['usage']['status'],'invalid');self.assertTrue(all(r['usage'][key] is None for key in TOKENS))
        self.assertNotIn('cost',json.dumps(r))
    def test_read_and_close_failures_never_echo_exception_or_repeat_request(self):
        class ReadFail(Response):
            def read(self,limit=-1):self.reads.append(limit);raise OSError(CANARY)
        response=ReadFail(b'');r,_=self.call(response);self.assertEqual((r['diagnostic'],response.closes),('network',1))
        class CloseFail(Response):
            def close(self):super().close();raise OSError(CANARY)
        response=CloseFail(success());r,_=self.call(response);self.assertFalse(r['ok']);self.assertEqual((r['diagnostic'],r['stage'],r['response_closed'],response.closes),('response-close','response-close',False,1))
        response=CloseFail(b'{}',400);r,_=self.call(response);self.assertFalse(r['ok']);self.assertEqual((r['http_status'],r['response_closed'],response.closes),(400,False,1))
    def test_invalid_status_type_and_nonbytes_response_fail_closed(self):
        response=Response(b'',True);r,_=self.call(response);self.assertEqual(r['diagnostic'],'response-shape');self.assertIsNone(r['http_status']);self.assertEqual(response.closes,1)
        class Nonbytes(Response):
            def read(self,limit=-1):self.reads.append(limit);return CANARY
        response=Nonbytes(b'');r,_=self.call(response);self.assertEqual((r['diagnostic'],response.closes),('response-shape',1))

    def test_capture_change_has_same_language_tree_and_boundary_acceptance(self):
        import re
        new=P.SCHEMA['schema']['definitions']['t']['pattern']
        # Only the optional second component of the case reference changed.
        old=new.replace(r'(\.[a-z_]+)?',r'(?:\.[a-z_]+)?',1)
        self.assertEqual(old.count('(?:'),1);self.assertEqual(new,old.replace('(?:','(',1))
        def tree(nodes):
            result=[]
            for operation,argument in nodes:
                name=str(operation)
                self.assertNotIn(name,{'GROUPREF','GROUPREF_EXISTS','ASSERT','ASSERT_NOT'})
                if name=='SUBPATTERN':
                    group,added,deleted,child=argument;self.assertEqual((added,deleted),(0,0));result.extend(tree(child))
                else:result.append((name,normalize(argument)))
            return tuple(result)
        def normalize(value):
            if isinstance(value,re._parser.SubPattern):return tree(value)
            if isinstance(value,(tuple,list)):return tuple(normalize(v) for v in value)
            return value
        self.assertEqual(tree(re._parser.parse(old,0)),tree(re._parser.parse(new,0)))
        self.assertEqual(re.compile(new).groups,re.compile(old).groups+1)
        values=('설명','{{case:1.foo}}','{{case:5.foo.bar}}','{{case:0.foo}}','{{case:6.foo}}','{{case:01.foo}}',
            '{{case:1.foo.bar.more}}','{{case:1.FOO}}','{{case:1.foo1}}','{{case:1.foo.}}','{{case:1.foo}',
            '{{case:1.foo}}}','{{metric:spend.current}}','{{product:3.price}}','{{product:4.price}}',
            '{{market:1.price}}','{{funnel:coverage}}','본문 {{case:2.foo.bar}} 뒤','', '{', '}', '{{}}')
        for index,value in enumerate(values):
            with self.subTest(index=index):self.assertEqual(re.search(old,value) is not None,re.search(new,value) is not None)
    def test_message_terms_are_closed_lexical_flags_only_after_all_guards_one_read(self):
        keys={'schema','regex','pattern','noncapturing','group','anchor','reference','unsupported','compile','complexity'}
        message='Schema regex pattern non-capturing group anchor reference unsupported compilation complexity '+CANARY
        raw=json.dumps({'type':'error','error':{'type':'invalid_request_error','message':message},'request_id':CANARY}).encode()
        response=Response(raw,400);result,_=self.call(response)
        self.assertEqual(set(result['message_terms']),keys);self.assertTrue(all(type(v) is bool and v for v in result['message_terms'].values()))
        self.assertEqual(result['diagnostic'],'http-error-unclassified');self.assertEqual(response.reads,[4097])
        plain=json.dumps({'type':'error','error':{'type':'invalid_request_error','message':'unrelated '+CANARY}}).encode()
        r,_=self.call(Response(plain,400));self.assertEqual(r['message_terms'],dict.fromkeys(keys,False))
        variants=(b'{}',b'[]',b'not JSON',b'\xff',b'x'*4097,
            b'{"type":"error","error":{"type":"other","message":"regex"}}',
            b'{"type":"error","error":{"type":"invalid_request_error","message":3}}',
            b'{"type":"error","error":{"type":"invalid_request_error","message":"regex\\npattern"}}',
            b'{"type":"error","type":"error","error":{"type":"invalid_request_error","message":"regex"}}')
        for index,body in enumerate(variants):
            with self.subTest(index=index):
                response=Response(body,400);r,_=self.call(response);self.assertIsNone(r['message_terms']);self.assertEqual(response.reads,[4097])
        for status in (200,401,500):
            r,_=self.call(Response(success() if status==200 else raw,status));self.assertIsNone(r['message_terms'])
        class Failed(Response):
            def read(self,limit=-1):self.reads.append(limit);raise OSError(CANARY)
        response=Failed(raw,400);r,_=self.call(response);self.assertEqual(r['diagnostic'],'http-error-read');self.assertIsNone(r['message_terms']);self.assertEqual(response.reads,[4097])
        class Nonbytes(Response):
            def read(self,limit=-1):self.reads.append(limit);return CANARY
        response=Nonbytes(raw,400);r,_=self.call(response);self.assertEqual(r['diagnostic'],'http-error-body-type');self.assertIsNone(r['message_terms']);self.assertEqual(response.reads,[4097])

if __name__=='__main__':unittest.main(verbosity=2)
