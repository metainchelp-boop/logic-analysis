"""Bounded exact-source readonly invocation transport; no execution during rendering."""
import base64
import hashlib
import json
import lzma
import types

MARKER = b'NAVER_MARKET_OPERATION_INVOCATION_V1='
PAIR = ('7abd8b3965ed4b51a3b071cd218e024f','4aa3189c384847178ecafbfa34eb060e')
CORE_SHA256 = 'b03caa1cb0b886e3098b1446dd70c953f05da90abbc449a901ffd74b7449f8e1'
CORE_CONTRACT = {'APPLY': '7abd8b3965ed4b51a3b071cd218e024f', 'ROLLBACK': '4aa3189c384847178ecafbfa34eb060e', 'PLAN_SHA256': 'b9b63866d280845df60d99aa0ba7c5f0d00f90b128583c291abfe1a542ed35a3', 'FAILED_RUN_ID': 39092917351, 'UNITS': {'coordinator': 'naver-market-diagnostic-7abd8b3965ed4b51a3b071cd218e024f.service', 'reader': 'naver-market-diagnostic-7abd8b3965ed4b51a3b071cd218e024f-reader.service'}, 'WINDOW': {'start': '2026-10-18T03:14:45Z', 'end': '2026-10-18T03:15:18Z'}, 'PROVENANCE': {'ledger': '7dcdfc8b2ef2bf99766b2bd59595b27b22da3c6407fbcca0b735d96e95dfe3c6', 'window': 'e38e550f57d4d3d11e00407e2f6d615c1e517c04a9a52e301bf25b6ddd49ca0b', 'apply': 'e37524077eb2f84bf678999a47a7fe0a5b9c5f3df318949be9aaf64050aa5b99', 'restored': 'd11910a1312430ca5f69bf3318b7d9b044f87ae0d0bd67fc442a5bd0dee0db2e', 'helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737', 'transition': 'acd5636795506381c89ac0aa8657c7ea1b4f6a26985f50b0297fba62c7d5591a'}}
PLAN_SHA256 = 'b9b63866d280845df60d99aa0ba7c5f0d00f90b128583c291abfe1a542ed35a3'
CONTRACT_KEYS = frozenset(('APPLY','ROLLBACK','PLAN_SHA256','FAILED_RUN_ID','UNITS','WINDOW','PROVENANCE'))
MAX_SOURCE, MAX_PACKAGE, MAX_WIRE = 49152, 65536, 32768
MAX_BOOT, MAX_SSH, MAX_RESULT = 8192, 49152, 17408
DECODER_MEMORY = 32 * 1024 * 1024
PHASES = frozenset(('decode','load','observe','validate','complete'))
ERRORS = frozenset(('PACKAGE','SOURCE','HOST_UNAVAILABLE'))

class Refused(ValueError): pass

def need(value, code):
    if value is not True: raise Refused(code)

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')

def sha(value): return hashlib.sha256(value).hexdigest()

def strict(raw, maximum=MAX_RESULT):
    need(type(raw) is bytes and 0<len(raw)<=maximum,'JSON_SIZE')
    def unique(pairs):
        value={}
        for key,item in pairs:
            need(key not in value,'JSON_DUPLICATE');value[key]=item
        return value
    def invalid(_): raise Refused('JSON_CONSTANT')
    try:
        # Public source/result has a small fixed depth; bound before JSON parsing.
        depth=tokens=0;quoted=escaped=False
        for ch in raw.decode('ascii'):
            if quoted:
                if escaped: escaped=False
                elif ch=='\\': escaped=True
                elif ch=='"': quoted=False
            elif ch=='"': quoted=True;tokens+=1
            elif ch in '[{': depth+=1;tokens+=1;need(depth<=12,'JSON_DEPTH')
            elif ch in ']}': depth-=1;need(depth>=0,'JSON_DEPTH')
            elif ch in ',:': tokens+=1
            need(tokens<=4096,'JSON_TOKENS')
        need(not quoted and not escaped and depth==0,'JSON_SHAPE')
        value=json.loads(raw,object_pairs_hook=unique,parse_constant=invalid)
        need(canonical(value)==raw,'JSON_CANONICAL')
        return value
    except (UnicodeError,RecursionError,TypeError): raise Refused('JSON_SHAPE') from None


def identical(actual, expected):
    if type(actual) is not type(expected): return False
    if type(expected) is dict:
        return set(actual)==set(expected) and all(identical(actual[k],v) for k,v in expected.items())
    if type(expected) in (list,tuple):
        return len(actual)==len(expected) and all(identical(a,b) for a,b in zip(actual,expected))
    return actual==expected


def check_source(body, pin):
    need(type(pin) is str and pin == CORE_SHA256 and type(body) is bytes
         and 0<len(body)<=MAX_SOURCE and sha(body)==pin,'SOURCE')
    need(type(CORE_CONTRACT) is dict and set(CORE_CONTRACT)==CONTRACT_KEYS
         and CORE_CONTRACT['APPLY']==PAIR[0] and CORE_CONTRACT['ROLLBACK']==PAIR[1]
         and CORE_CONTRACT['PLAN_SHA256']==PLAN_SHA256
         and type(CORE_CONTRACT['FAILED_RUN_ID']) is int and CORE_CONTRACT['FAILED_RUN_ID']==39092917351,'CONTRACT')
    return body


def load_core(body, pin):
    check_source(body,pin)
    module=types.ModuleType('fixed_operation_invocation_core')
    exec(compile(body,'<pinned-readonly-operation-invocation>','exec'),module.__dict__)
    need(all(identical(getattr(module,k,None),v) for k,v in CORE_CONTRACT.items()),'CONTRACT')
    return module


def result(value, core):
    keys={'schema','transport_ok','phase','error','observation'}
    need(type(value) is dict and set(value)==keys and value['schema']=='readonly-operation-invocation-transport-v1'
         and type(value['transport_ok']) is bool and type(value['phase']) is str and value['phase'] in PHASES,'RESULT')
    if value['transport_ok']:
        need(value['phase']=='complete' and value['error'] is None,'RESULT')
        need(core.validate(value['observation']) is value['observation'],'OBSERVATION')
    else:
        need(value['phase']!='complete' and type(value['error']) is str and value['error'] in ERRORS
             and value['observation'] is None,'RESULT')
    need(len(canonical(value))<=MAX_RESULT,'RESULT_SIZE')
    return value


def render(body, pin):
    body=check_source(body,pin)
    # load_core is deliberately not called: render never imports or observes host core.
    package=canonical({'version':1,'core':body.decode('utf-8')})
    need(len(package)<=MAX_PACKAGE,'PACKAGE')
    wire=base64.b85encode(lzma.compress(package,format=lzma.FORMAT_XZ,preset=6)).decode('ascii')
    need(0<len(wire)<=MAX_WIRE,'WIRE')
    boot='''import base64,contextlib,hashlib,json,lzma,os,sys,types
os.environ.clear();os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',LANG='C',LC_ALL='C')
result=dict(schema='readonly-operation-invocation-transport-v1',transport_ok=False,phase='decode',error='HOST_UNAVAILABLE',observation=None)
class Rejected(Exception):pass
def reject():raise Rejected()
def unique(pairs):
    value={}
    for k,v in pairs:
        if k in value:reject()
        value[k]=v
    return value
def identical(actual,expected):
    if type(actual) is not type(expected):return False
    if type(expected) is dict:return set(actual)==set(expected) and all(identical(actual[k],v) for k,v in expected.items())
    if type(expected) in (list,tuple):return len(actual)==len(expected) and all(identical(a,b) for a,b in zip(actual,expected))
    return actual==expected
class Discard:
    def write(self,value):return len(value)
    def flush(self):pass
try:
    if not 0<len(WIRE)<=32768 or not WIRE.isascii():reject()
    decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=33554432)
    raw=decoder.decompress(base64.b85decode(WIRE),max_length=65537)
    if len(raw)>65536 or not decoder.eof or decoder.unused_data:reject()
    package=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:reject())
    if type(package) is not dict or set(package)!={'version','core'} or type(package['version']) is not int or package['version']!=1 or type(package['core']) is not str:reject()
    if json.dumps(package,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')!=raw:reject()
    body=package['core'].encode()
    if not 0<len(body)<=49152 or hashlib.sha256(body).hexdigest()!=CORE_SHA:reject()
    result['phase']='load'
    with contextlib.redirect_stdout(Discard()),contextlib.redirect_stderr(Discard()):
        core=types.ModuleType('fixed_operation_invocation_core')
        exec(compile(body,'<pinned-readonly-operation-invocation>','exec'),core.__dict__)
        if not all(identical(getattr(core,k,None),v) for k,v in CORE_CONTRACT.items()):reject()
        result['phase']='observe'
        value=core.observe()
        result['phase']='validate'
        if core.validate(value) is not value:reject()
        raw_result=core.closed_json(value)
        if type(raw_result) is not str or not 0<len(raw_result.encode())<=16384:reject()
    result.update(transport_ok=True,phase='complete',error=None,observation=value)
except Rejected:
    result['error']='PACKAGE' if result['phase']=='decode' else 'SOURCE'
except BaseException:
    result['error']='HOST_UNAVAILABLE'
closed=json.dumps(result,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
if len(closed.encode())>17408:raise SystemExit('RESULT_SIZE')
print('NAVER_MARKET_OPERATION_INVOCATION_V1='+closed)
'''
    need(len(boot.encode())<=MAX_BOOT,'BOOT')
    source='WIRE='+repr(wire)+'\nCORE_SHA='+repr(pin)+'\nCORE_CONTRACT='+repr(CORE_CONTRACT)+'\n'+boot
    script="/usr/bin/python3 -I -B - <<'READONLY_AUDIT_PY'\n"+source+'READONLY_AUDIT_PY\n'
    need(len(script.encode())<=MAX_SSH,'SSH')
    return {'script':script,'script_sha256':sha(script.encode()),'sizes':{'source':len(body),'package':len(package),'wire':len(wire),'bootstrap':len(boot.encode()),'ssh':len(script.encode())}}
