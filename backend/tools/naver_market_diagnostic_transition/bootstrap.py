"""Build a fixed Python bootstrap; no dispatch, host command or credential read.

The release workflow must pin this renderer and delivery.py. Inputs here are
reviewed public bytes, never an external request's script/command. The request
inside the envelope remains restricted to action and paired operation IDs.
"""
import hashlib
import re
import shlex
import delivery as D


def render(wire, host, module_sources):
    package = D.decode(wire)
    if type(host) is not bytes or package['host'].encode() != host: D.fail('BOOT_HOST')
    if module_sources != {k:v.encode() for k,v in package['modules'].items()}: D.fail('BOOT_MODULES')
    # Fixed literal refusal codes from the reviewed and hash-verified sources.
    # No arbitrary exception text/path/value can enter the public result.
    codes = sorted({code for body in module_sources.values()
                    for code in re.findall(r"fail\('([A-Z][A-Z0-9_]{0,63})'\)",body.decode())})
    source = '''import base64,hashlib,json,lzma,os,re,types
result=dict(version=1,transport='market-diagnostic-transition',transport_ok=False,
            phase='decode',error_code='HOST_REFUSED',result=None,
            paired_cleanup_may_be_required=True)
def refuse(code):raise ValueError(code)
def unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:refuse('PACKAGE_JSON')
        value[key]=item
    return value
try:
    wire=os.environ.pop('NAVER_DIAG_WIRE')
    os.environ.clear();os.environ.update(PATH='/usr/sbin:/usr/bin:/sbin:/bin',LANG='C')
    if not 0<len(wire)<=102400 or not wire.isascii():refuse('WIRE_SIZE')
    decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=33554432)
    raw=decoder.decompress(base64.b85decode(wire),max_length=393217)
    if len(raw)>393216 or not decoder.eof or decoder.unused_data:refuse('PACKAGE_SIZE')
    package=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:refuse('PACKAGE_JSON'))
    if type(package) is not dict or set(package)!={'version','host','modules','sources','request'}:refuse('PACKAGE_SHAPE')
    host=package['host']
    if type(host) is not str or not 0<len(host.encode())<=32768 or hashlib.sha256(host.encode()).hexdigest()!=HOST_PIN:refuse('HOST_CHANGED')
    result['phase']='load'
    module=types.ModuleType('fixed_diagnostic_delivery')
    exec(compile(host,'<pinned-diagnostic-delivery>','exec'),module.__dict__)
    module.validate(package)
    result['phase']='entrypoint'
    result['result']=module.run(package)
    result.update(transport_ok=True,phase='complete',error_code=None,
                  paired_cleanup_may_be_required=package['request']['action']=='apply')
except BaseException as error:
    # The only detail returned is a fixed public refusal enum. An ambiguous
    # apply can have durable intent; this process never retries or rolls back.
    if isinstance(error,KeyboardInterrupt):result['error_code']='INTERRUPTED'
    elif isinstance(error,OSError):result['error_code']='HOST_OS_ERROR'
    elif type(error).__name__=='Invalid' and str(error) in FIXED_CODES:result['error_code']=str(error)
    elif type(error) is ValueError and str(error) in {'WIRE_SIZE','PACKAGE_SIZE','PACKAGE_JSON','PACKAGE_SHAPE','HOST_CHANGED','SOURCE_SHAPE','SOURCE_CHANGED','REQUEST','MODULE_COLLISION','RESULT','RESULT_SIZE'}:result['error_code']=str(error)
closed=json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False)
if len(closed.encode())>4096:raise SystemExit('RESULT_SIZE')
print('NAVER_MARKET_DIAGNOSTIC_TRANSITION_V1='+closed)
'''
    source = 'HOST_PIN='+repr(hashlib.sha256(host).hexdigest())+'\nFIXED_CODES='+repr(tuple(codes))+'\n'+source
    if len(source.encode()) > D.MAX_BOOT: D.fail('BOOT_SIZE')
    script = "export NAVER_DIAG_WIRE="+shlex.quote(wire)+"\n/usr/bin/python3 -I -B - <<'PYCODE'\n"+source+"PYCODE\n"
    if len(script.encode()) > D.MAX_SSH: D.fail('SSH_SIZE')
    return source,script


if __name__=='__main__':raise SystemExit('PINNED_WORKFLOW_REQUIRED')
