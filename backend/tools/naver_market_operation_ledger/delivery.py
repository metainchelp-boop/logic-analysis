"""Bounded exact-source readonly ledger transport; no execution during rendering."""
import base64
import hashlib
import json
import lzma
import types

MARKER = b'NAVER_MARKET_OPERATION_LEDGER_V1='
PAIR = ('7abd8b3965ed4b51a3b071cd218e024f','4aa3189c384847178ecafbfa34eb060e')
CORE_SHA256 = 'd7fedc6bae4abe13cf7a53636ea288de6f33598337fe48b5183616af924a6f8f'
PLAN_SHA256 = 'b9b63866d280845df60d99aa0ba7c5f0d00f90b128583c291abfe1a542ed35a3'
DEPENDENCY_PINS = {'transition':'acd5636795506381c89ac0aa8657c7ea1b4f6a26985f50b0297fba62c7d5591a','journal':'27e2ec8c7b332951151dcb19bd60ec527eb768d1b1711f40069b8dd1ac191333'}
MAX_SOURCE, MAX_DEPENDENCY, MAX_PACKAGE, MAX_WIRE = 49152, 32768, 65536, 32768
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


def check_sources(body, dependencies, pin):
    need(type(pin) is str and pin == CORE_SHA256 and type(body) is bytes
         and 0<len(body)<=MAX_SOURCE and sha(body)==pin,'SOURCE')
    need(type(dependencies) is dict and set(dependencies)==set(DEPENDENCY_PINS),'SOURCE_SET')
    for name,expected in DEPENDENCY_PINS.items():
        raw=dependencies[name]
        need(type(raw) is bytes and 0<len(raw)<=MAX_DEPENDENCY and sha(raw)==expected,'SOURCE')
    return body, dict(dependencies)


def load_core(body, dependencies, pin):
    check_sources(body,dependencies,pin)
    module=types.ModuleType('fixed_operation_ledger_core')
    exec(compile(body,'<pinned-readonly-operation-ledger>','exec'),module.__dict__)
    need(module.APPLY==PAIR[0] and module.ROLLBACK==PAIR[1]
         and module.PLAN_SHA256==PLAN_SHA256 and module.DEPENDENCY_PINS==DEPENDENCY_PINS,'PAIR')
    return module


def result(value, core):
    keys={'schema','transport_ok','phase','error','observation'}
    need(type(value) is dict and set(value)==keys and value['schema']=='readonly-operation-ledger-transport-v1'
         and type(value['transport_ok']) is bool and type(value['phase']) is str and value['phase'] in PHASES,'RESULT')
    if value['transport_ok']:
        need(value['phase']=='complete' and value['error'] is None,'RESULT')
        need(core.validate(value['observation']) is value['observation'],'OBSERVATION')
    else:
        need(value['phase']!='complete' and type(value['error']) is str and value['error'] in ERRORS
             and value['observation'] is None,'RESULT')
    need(len(canonical(value))<=MAX_RESULT,'RESULT_SIZE')
    return value


def render(body, dependencies, pin):
    body, dependencies=check_sources(body,dependencies,pin)
    # load_core is deliberately not called: render never imports or observes host core.
    package=canonical({'version':1,'core':body.decode('utf-8'),'dependencies':{n:raw.decode('utf-8') for n,raw in dependencies.items()}})
    need(len(package)<=MAX_PACKAGE,'PACKAGE')
    wire=base64.b85encode(lzma.compress(package,format=lzma.FORMAT_XZ,preset=6)).decode('ascii')
    need(0<len(wire)<=MAX_WIRE,'WIRE')
    boot='''import base64,contextlib,hashlib,json,lzma,os,sys,types
os.environ.clear();os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',LANG='C',LC_ALL='C')
result=dict(schema='readonly-operation-ledger-transport-v1',transport_ok=False,phase='decode',error='HOST_UNAVAILABLE',observation=None)
class Rejected(Exception):pass
def reject():raise Rejected()
def unique(pairs):
    value={}
    for k,v in pairs:
        if k in value:reject()
        value[k]=v
    return value
class Discard:
    def write(self,value):return len(value)
    def flush(self):pass
try:
    if not 0<len(WIRE)<=32768 or not WIRE.isascii():reject()
    decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=33554432)
    raw=decoder.decompress(base64.b85decode(WIRE),max_length=65537)
    if len(raw)>65536 or not decoder.eof or decoder.unused_data:reject()
    package=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:reject())
    if type(package) is not dict or set(package)!={'version','core','dependencies'} or type(package['version']) is not int or package['version']!=1 or type(package['core']) is not str:reject()
    if json.dumps(package,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')!=raw:reject()
    if type(package['dependencies']) is not dict or set(package['dependencies'])!=set(DEPENDENCY_PINS):reject()
    dependencies={}
    for name,pin in DEPENDENCY_PINS.items():
        source=package['dependencies'][name]
        if type(source) is not str:reject()
        source=source.encode()
        if not 0<len(source)<=32768 or hashlib.sha256(source).hexdigest()!=pin:reject()
        dependencies[name]=source
    body=package['core'].encode()
    if not 0<len(body)<=49152 or hashlib.sha256(body).hexdigest()!=CORE_SHA:reject()
    result['phase']='load'
    if any(name in sys.modules for name in DEPENDENCY_PINS):reject()
    with contextlib.redirect_stdout(Discard()),contextlib.redirect_stderr(Discard()):
        core=types.ModuleType('fixed_operation_ledger_core')
        exec(compile(body,'<pinned-readonly-operation-ledger>','exec'),core.__dict__)
        if core.APPLY!='7abd8b3965ed4b51a3b071cd218e024f' or core.ROLLBACK!='4aa3189c384847178ecafbfa34eb060e' or core.PLAN_SHA256!=PLAN_SHA256 or core.DEPENDENCY_PINS!=DEPENDENCY_PINS:reject()
        result['phase']='observe'
        value=core.observe(dependencies)
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
print('NAVER_MARKET_OPERATION_LEDGER_V1='+closed)
'''
    need(len(boot.encode())<=MAX_BOOT,'BOOT')
    source='WIRE='+repr(wire)+'\nCORE_SHA='+repr(pin)+'\nDEPENDENCY_PINS='+repr(DEPENDENCY_PINS)+'\nPLAN_SHA256='+repr(PLAN_SHA256)+'\n'+boot
    script="/usr/bin/python3 -I -B - <<'READONLY_AUDIT_PY'\n"+source+'READONLY_AUDIT_PY\n'
    need(len(script.encode())<=MAX_SSH,'SSH')
    return {'script':script,'script_sha256':sha(script.encode()),'sizes':{'source':len(body),'dependencies':sum(map(len,dependencies.values())),'package':len(package),'wire':len(wire),'bootstrap':len(boot.encode()),'ssh':len(script.encode())}}
