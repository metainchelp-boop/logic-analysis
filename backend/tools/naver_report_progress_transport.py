"""동일 schema 상세 AI 연결 전용 코드 보존 전송. 과거 전송 원문 불변."""
import ast
import base64
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import stat
import tokenize
import types
import zlib

PREFIX='report-progress-xz85-v1:'
MAX_JSON=393216
MAX_WIRE=100352
MAX_SOURCE=160000
MAX_SOURCE_GZIP=3*1024*1024
MAX_CIPHERTEXT=3*1024*1024
MAX_PAYLOAD=4*1024*1024
MAX_BOOTSTRAP_B64=32768
MAX_SSH=131072
# Public scaffold aliases remain available for deterministic template checks.
MAX_JSON_BYTES=MAX_JSON
MAX_WIRE_BYTES=MAX_WIRE
MAX_SOURCE_BYTES=MAX_SOURCE
MAX_SOURCE_GZIP_BYTES=MAX_SOURCE_GZIP
MAX_CIPHERTEXT_BYTES=MAX_CIPHERTEXT
MAX_PAYLOAD_BYTES=MAX_PAYLOAD
MAX_BOOTSTRAP_B64_BYTES=MAX_BOOTSTRAP_B64
MAX_SSH_BYTES=MAX_SSH
TARGET_SOURCE = '513e52eaee4d1bb722461961639cd588df9080cd'
CODE_PATHS = ('backend/naver_page/operations-ui.js', 'naver_engine/collection_diagnostics.py', 'naver_engine/inspection_reads.py', 'naver_engine/inspection_store.py', 'naver_runtime/runtime_status.py')
# An external, independently verified template supplies this self-source hash.
# It must never be embedded by rewriting this module with its own hash.
TRANSPORT_RAW_SHA256=None
EXPECTED_TARGET_SOURCE = '513e52eaee4d1bb722461961639cd588df9080cd'
EXPECTED_CODE_PATHS = ('backend/naver_page/operations-ui.js', 'naver_engine/collection_diagnostics.py', 'naver_engine/inspection_reads.py', 'naver_engine/inspection_store.py', 'naver_runtime/runtime_status.py')
FUNCTIONS={'preview-report-progress-prepare':'prepare','preview-report-progress-apply':'apply','preview-report-progress-rollback':'rollback'}
SOURCE_FILES = {'host': 'naver_erp_tunnel_service_install.py', 'release': 'naver_preview_release.py', 'lifecycle': 'naver_preview_lifecycle.py', 'upgrade': 'naver_preview_upgrade.py', 'exports_binding': 'naver_completion_exports.py', 'exports_helper': 'naver_saved_exports.py', 'product_exporter': '../naver_product_export.py', 'market_exporter': '../naver_market_export.py', 'controller': 'naver_preview_completion_release.py', 'patch': 'naver_report_progress_patch.py'}
# Exact raw and AST-equivalent compact sources match the reviewed target proof.
SOURCE_SHA256 = {'patch': '510aaeeb84d8ac05da4f626515c5c424d6853b77176c0f79daf774dd1f1b8cf7', 'controller': '3be9c0360a6f75192455d6b139317319dd111b4e404628505ae62783b37977e2', 'host': '236cdd596bae2f8d5e0dfea5822bdd7216c44addac2bbb643306dfbff00fdd3a', 'release': '7288d51eba4e2c0320d196b8da2ee14f852b87f33304c221878c218cd1dacb84', 'lifecycle': '4f5f85c197b5efe2c323b2c784814eb1bd177dd60d44b8c7ead943b0af98abc4', 'upgrade': '6aa60100ba8ae39c07be4016498a4c79076c540707bee6a44e651c8de8e62c28', 'exports_binding': '1dc92cd674161c408032f2fd7fa5ef7bb220c91d168af10541a5490c8edcbfed', 'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737', 'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59', 'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'}
COMPACT_SHA256 = {'host': '4e95c24f9da93d814cc90e919ffb9fdfb6113667f16205f382406b7369085b95', 'release': 'd9b4456ecd3de6bfe9fa12430616cf6b9cedadf4ba4dbe28582ad3ea22f84367', 'lifecycle': '0c3ffaa303ad066f23117b304b8f9289e0e3bc78a9c59a8dced8d58e54f498bd', 'upgrade': 'e4dd1f3c29c04439321bff785d803a12356d56e2b83986cf81f286d4dce46f60', 'exports_binding': '2c7f944b2b992eead34508ba671422c50d9becbc5ae5ff39933ab00a5958f32f', 'exports_helper': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737', 'product_exporter': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59', 'market_exporter': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8', 'controller': '4d937e6c55c36853f6d9e6b0f7557558e074a66910ab03c8b43aae92c5ef3fba', 'patch': '20e1638171992dc9d8716e86812ec720125d80f67848b1602e694475d3d20020'}


# Compatibility alias; both public views must agree with the pinned map.
COMPACT_SOURCE_SHA256=COMPACT_SHA256


def require_pins():
    def digest(value):
        return type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    for pins in (SOURCE_SHA256,COMPACT_SHA256,COMPACT_SOURCE_SHA256):
        if (type(pins) is not dict or set(pins)!=set(SOURCE_FILES)
            or any(not digest(value) for value in pins.values())):
            raise ValueError('DETAIL_AI_PINS_PENDING')
    if (COMPACT_SOURCE_SHA256!=COMPACT_SHA256 or not digest(TRANSPORT_RAW_SHA256)
        or type(TARGET_SOURCE)is not str or len(TARGET_SOURCE)!=40 or TARGET_SOURCE!=EXPECTED_TARGET_SOURCE or type(CODE_PATHS) is not tuple
        or len(CODE_PATHS)!=5 or set(CODE_PATHS)!=set(EXPECTED_CODE_PATHS)):
        raise ValueError('DETAIL_AI_PINS_PENDING')


def extra_arguments(args,kwargs):
    if args or kwargs:raise ValueError('PATCH_BUNDLE')


def validate(value=None):
    require_pins()
    if (type(value) is not dict or set(value)!={'version','operation','package','sources'}
        or type(value['version']) is not int or value['version']!=1 or type(value['operation']) is not str
        or value['operation'] not in FUNCTIONS or type(value['package']) is not dict
        or type(value['sources']) is not dict or set(value['sources'])!=set(SOURCE_FILES)):
        raise ValueError('PATCH_BUNDLE')
    for name,body in value['sources'].items():
        if (type(body) is not str or not 0<len(body.encode())<=MAX_SOURCE
            or hashlib.sha256(body.encode()).hexdigest()!=COMPACT_SHA256[name]):raise ValueError('PATCH_SOURCE')
    return value


def encode(value=None):
    raw=json.dumps(validate(value),ensure_ascii=False,separators=(',',':')).encode()
    if len(raw)>MAX_JSON:raise ValueError('PATCH_JSON_SIZE')
    wire=PREFIX+base64.b85encode(lzma.compress(raw,format=lzma.FORMAT_XZ,check=lzma.CHECK_CRC64,filters=[{'id':lzma.FILTER_LZMA2,'preset':6|lzma.PRESET_EXTREME,'lc':3,'pb':0}])).decode()
    if len(wire)>MAX_WIRE:raise ValueError('PATCH_WIRE_SIZE')
    return wire


def decode(wire=None):
    require_pins()
    if type(wire) is not str or not wire.startswith(PREFIX) or len(wire)>MAX_WIRE:raise ValueError('PATCH_ENCODING')
    try:
        body=wire[len(PREFIX):]
        alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{|}~'
        if not body or any(char not in alphabet for char in body):raise ValueError('PATCH_BASE85')
        packed=base64.b85decode(body.encode('ascii'))
        if base64.b85encode(packed).decode('ascii')!=body:raise ValueError('PATCH_BASE85')
        decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=32*1024*1024)
        raw=decoder.decompress(packed,max_length=MAX_JSON+1)
        if len(raw)>MAX_JSON or not decoder.eof or decoder.unused_data:raise ValueError('PATCH_XZ')
        return validate(json.loads(raw,object_pairs_hook=unique))
    except (ValueError,TypeError,UnicodeError,lzma.LZMAError):raise ValueError('PATCH_ENCODING') from None


def unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('PATCH_DUPLICATE')
        value[key]=item
    return value


def _compact_horizontal_layout(source):
    tokens=list(tokenize.generate_tokens(io.StringIO(source).readline));lines=source.splitlines(True);offsets=[0]
    for line in lines:offsets.append(offsets[-1]+len(line))
    layout={tokenize.INDENT,tokenize.DEDENT,tokenize.NEWLINE,tokenize.NL,tokenize.ENDMARKER}
    changes=[];active_fstring=0
    def pair_exact(a,b):
        if a.type in (tokenize.NAME,tokenize.NUMBER)and b.type in (tokenize.NAME,tokenize.NUMBER):return False
        try:
            rows=[]
            for token in tokenize.generate_tokens(io.StringIO(a.string+b.string).readline):
                if token.type not in layout:rows.append((token.type,token.string))
                if len(rows)==2:break
            return rows==[(a.type,a.string),(b.type,b.string)]
        except (tokenize.TokenError,IndentationError,SyntaxError):return False
    previous=None
    for token in tokens:
        kind=tokenize.tok_name[token.type]
        if kind=='FSTRING_START':active_fstring+=1
        inside=active_fstring>0
        if kind=='FSTRING_END':active_fstring-=1
        if (not inside and previous is not None and previous.type not in layout and token.type not in layout
                and previous.end[0]==token.start[0] and (previous.type==tokenize.OP or token.type==tokenize.OP)):
            start=offsets[previous.end[0]-1]+previous.end[1];end=offsets[token.start[0]-1]+token.start[1]
            gap=source[start:end]
            if gap and all(char in ' \t'for char in gap)and pair_exact(previous,token):changes.append((start,end))
        previous=token
    result=source
    for start,end in reversed(changes):result=result[:start]+result[end:]
    actual=list(tokenize.generate_tokens(io.StringIO(result).readline))
    if ([(token.type,token.string)for token in actual]!=[(token.type,token.string)for token in tokens]
            or ast.dump(ast.parse(source),include_attributes=False)!=ast.dump(ast.parse(result),include_attributes=False)):
        raise ValueError('COMPLETION_SOURCE_AST')
    return result


def _compact_continuation_layout(source):
    tokens=list(tokenize.generate_tokens(io.StringIO(source).readline))
    lines=source.splitlines(keepends=True);starts=[0]
    for line in lines:starts.append(starts[-1]+len(line))
    start_kind=getattr(tokenize,'FSTRING_START',-1);end_kind=getattr(tokenize,'FSTRING_END',-2)
    depth=0;fstrings=0;edits=[]
    for token in tokens:
        if token.type==start_kind:fstrings+=1;continue
        if token.type==end_kind:fstrings-=1;continue
        if fstrings:continue
        if token.type==tokenize.OP:
            if token.string in ('(','[','{'):depth+=1
            elif token.string in (')',']','}'):depth-=1
            if depth<0:raise ValueError('COMPLETION_SOURCE_AST')
        if token.type==tokenize.NL and depth>0:
            begin=starts[token.start[0]-1]+token.start[1]
            end=starts[token.end[0]-1]+token.end[1]
            while end<len(source)and source[end]in (' ','\t'):end+=1
            edits.append((begin,end))
    if depth or fstrings:raise ValueError('COMPLETION_SOURCE_AST')
    result=source
    for begin,end in reversed(edits):result=result[:begin]+' '+result[end:]
    after=list(tokenize.generate_tokens(io.StringIO(result).readline))
    keep=lambda sequence:[(t.type,t.string)for t in sequence if t.type!=tokenize.NL]
    if keep(tokens)!=keep(after)or ast.dump(ast.parse(source),include_attributes=False)!=ast.dump(ast.parse(result),include_attributes=False):
        raise ValueError('COMPLETION_SOURCE_AST')
    return result


def compact(source):
    def fields(value):
        if isinstance(value,ast.AST):return(type(value).__name__,tuple((name,fields(item)) for name,item in ast.iter_fields(value)))
        if isinstance(value,list):return tuple(fields(item) for item in value)
        return value
    def literals(tokens):return[(t.type,t.string) for t in tokens if t.type==tokenize.STRING or tokenize.tok_name[t.type].startswith('FSTRING')]
    lines=source.splitlines(keepends=True);strings=set();tokens=list(tokenize.generate_tokens(io.StringIO(source).readline))
    for token in tokens:
        if token.type==tokenize.STRING or tokenize.tok_name[token.type].startswith('FSTRING'):strings.update(range(token.start[0],token.end[0]+1))
    for token in tokens:
        if token.type==tokenize.COMMENT:
            index=token.start[0]-1;lines[index]=lines[index][:token.start[1]].rstrip()+'\n'
    text=''.join(line for number,line in enumerate(lines,1) if line.strip() or number in strings);pairs=[];level=0
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        value=token.string
        if token.type==tokenize.INDENT:level+=1;value=' '*level
        elif token.type==tokenize.DEDENT:level-=1
        pairs.append((token.type,value))
    result=tokenize.untokenize(pairs)
    if literals(tokens)!=literals(tokenize.generate_tokens(io.StringIO(result).readline)) or fields(ast.parse(source))!=fields(ast.parse(result)):
        raise ValueError('COMPLETION_SOURCE_AST')
    return _compact_horizontal_layout(_compact_continuation_layout(result))

class CompletionRelease:
    """Preserve the existing fixed sealed source envelope."""
    def __init__(self,release):self._release=release
    def __getattr__(self,name):return getattr(self._release,name)

    def received_ciphertext(self,path,expected_sha256):
        require_pins()
        info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid) not in ((0,0),(1000,1000))
            or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or not 0<info.st_size<=MAX_CIPHERTEXT):
            raise ValueError('CIPHERTEXT_FILE')
        body=path.read_bytes()
        if not 0<len(body)<=MAX_CIPHERTEXT or self._release.sha(body)!=expected_sha256:
            raise ValueError('CIPHERTEXT_HASH')
        if info.st_uid!=0:os.chown(path,0,0)
        return body

    def decode_payload(self,plain,commit,source_hash):
        require_pins()
        if not isinstance(plain,bytes) or not 0<len(plain)<=MAX_PAYLOAD:raise ValueError('PLAINTEXT_SIZE')
        magic=b'NAVER-PREVIEW-PAYLOAD-GZIP-1\n'
        if plain.startswith(magic):
            try:
                decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
                raw=decoder.decompress(plain[len(magic):],MAX_PAYLOAD+1)
            except zlib.error:raise ValueError('PAYLOAD_COMPRESSION') from None
            if len(raw)>MAX_PAYLOAD or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError('PAYLOAD_COMPRESSION')
            plain=raw
        try:payload=json.loads(plain,object_pairs_hook=self._release.unique)
        except (ValueError,UnicodeError):raise ValueError('PAYLOAD_JSON') from None
        return self.validate_payload(payload,commit,source_hash)

    def validate_payload(self,payload,commit,source_hash):
        require_pins()
        if not isinstance(payload,dict) or set(payload)!={'schema','purpose','source_commit','source_tar_gz_b64','files'}:
            raise ValueError('PAYLOAD_FIELDS')
        if payload['schema']!=1 or payload['purpose']!='naver-owner-verification-runtime' or payload['source_commit']!=commit:
            raise ValueError('PAYLOAD_SOURCE')
        source=base64.b64decode(payload['source_tar_gz_b64'],validate=True)
        if not 0<len(source)<MAX_SOURCE_GZIP or self._release.sha(source)!=source_hash:raise ValueError('PAYLOAD_HASH')
        files=payload['files']
        if not isinstance(files,list) or len(files)!=4:raise ValueError('PAYLOAD_FILES')
        found=set()
        for item in files:
            if not isinstance(item,dict) or set(item)!={'path','mode','uid','gid','content'}:raise ValueError('FILE_FIELDS')
            name=Path(item['path']).name
            if name not in self._release.SECRET_OWNERS or item['path']!=str(self._release.SECRET_ROOT/name) or name in found:
                raise ValueError('FILE_PATH')
            if (item['uid'],item['gid'])!=self._release.SECRET_OWNERS[name] or item['mode']!=0o600:raise ValueError('FILE_OWNER')
            if not isinstance(item['content'],str) or not 0<len(item['content'].encode())<=32768:raise ValueError('FILE_CONTENT')
            found.add(name)
        return source,files


class ExportProxy:
    """Keep the existing verified companion for both images, including rollback."""
    def __init__(self,release,binding,patch):
        self._release=release;self._binding=binding;self._patch=patch
    def __getattr__(self,name):return getattr(self._release,name)
    def compose(self,path,name):
        require_pins()
        command=self._release.compose(path,name)
        if name=='engine' and Path(path).name in ('naver-'+self._patch.OLD_COMMIT,'naver-'+self._patch.TARGET_COMMIT):
            _,folder,_=self._binding.h._prepared(self._binding.receipt)
            command=command+['-f',str(folder/self._binding.h.COMPANION)]
        return command
    def verify_exports(self):
        require_pins()
        return self._binding.operation(lambda:self._binding.h.verify(self._binding.receipt,command=self._binding.command))


def bundle(operation=None,package=None,root=None,*args,**kwargs):
    require_pins()
    extra_arguments(args,kwargs)
    if operation not in FUNCTIONS:raise ValueError('PATCH_OPERATION')
    import naver_report_progress_patch as P
    P.require_pins()
    sources={}
    for name,filename in SOURCE_FILES.items():
        raw=(Path(root)/filename).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=SOURCE_SHA256[name]:raise ValueError('PATCH_SOURCE')
        text=raw.decode('utf-8')
        sources[name]=text if name in ('exports_helper','product_exporter','market_exporter') else compact(text)
    return validate({'version':1,'operation':operation,'package':package,'sources':sources})


def modules(value=None,*args,**kwargs):
    require_pins();extra_arguments(args,kwargs)
    validate(value);result={}
    # Static target pins fail before host adapters or private data are touched.
    patch=types.ModuleType('approved_postcompletion_patch')
    exec(value['sources']['patch'],patch.__dict__);patch.require_target_pins()
    if patch.TARGET_COMMIT!=TARGET_SOURCE or set(patch.CODE_PATHS)!=set(CODE_PATHS):
        raise ValueError('PATCH_SCOPE')
    result['patch']=patch
    for name in ('controller','host','release','lifecycle','upgrade','exports_binding','exports_helper'):
        module=types.ModuleType('approved_postcompletion_'+name)
        exec(value['sources'][name],module.__dict__);result[name]=module
        if name in ('controller','exports_binding'):module.require_pins()
    if SOURCE_SHA256['controller']!=patch.BASE_CONTROLLER_SHA256:raise ValueError('PATCH_BASELINE')
    patch.bind_base(result['controller'])
    result['release']=CompletionRelease(result['release'])
    return result


def execute(value=None,*,incoming=False):
    validate(value);m=modules(value);P=m['patch'];release=m['release']
    try:
        P.STAGE='input';P.OPERATION='package'
        host=m['host'].NativeHost();operation=value['operation'];package=value['package']
        if incoming:
            P.STAGE='incoming'
            if operation!='preview-report-progress-prepare':raise ValueError('PATCH_OPERATION')
            P.validate_package(package,release)
            if os.geteuid()!=0 or host.baseline()!=P.EXPECTED_BASELINE:raise ValueError('HOST_BASELINE')
            for path in (release.ROOT,release.ROOT/'incoming'):release.trusted_dir(path,mode=0o700)
            release.trusted_dir(release.ROOT/'incoming'/package['run_id'],mode=0o700,new=True)
            return {'ok':True,'stage':'incoming_ready','source_commit':P.TARGET_COMMIT}
        if operation=='preview-report-progress-prepare':P.validate_package(package,release)
        elif operation=='preview-report-progress-rollback':P.validate_rollback_package(package,release)
        else:
            if type(package) is not dict or set(package)!={'release','operation_id'}:raise ValueError('CODE_APPLY_FIELDS')
            P.validate_package(package['release'],release)
        P.base_success(release,m['upgrade'])
        _,base_receipt,_=P.historical_success(release,m['upgrade'])
        E=m['exports_binding'];H=m['exports_helper'];C=m['controller']
        binding=E.Binding(C,H,release,value['sources']['exports_helper'].encode(),
            {'naver_product_export.py':value['sources']['product_exporter'].encode(),
             'naver_market_export.py':value['sources']['market_exporter'].encode()})
        binding.load(dict(base_receipt['package'],operation='code-prepare'))
        wrapped=ExportProxy(release,binding,P)
        if operation=='preview-report-progress-prepare':
            return P.prepare(package,host,wrapped,m['lifecycle'],m['upgrade'],approved_config_operation_id=P.APPROVED_CONFIG_OPERATION_ID)
        return getattr(P,FUNCTIONS[operation])(package,host,wrapped,m['lifecycle'],m['upgrade'])
    except Exception as error:
        # The workflow uses a separate pristine reporter module. Carry only its
        # closed enums, never traceback, environment, paths, or service output.
        report=P.failure_report(error)
        details=getattr(error,'failure_details',{})
        saved={k:v for k,v in report.items() if k not in ('stage','error_kind','error_code')}
        for key,item in {'failed_stage':report['stage'],'failed_error_kind':report['error_kind'],'failed_error_code':report['error_code']}.items():saved.setdefault(key,item)
        error.failure_details={**(details if type(details) is dict else {}),**saved}
        raise



def bootstrap(source=None,*args,**kwargs):
    """Encode only an externally pinned transport; never read or execute it."""
    require_pins();extra_arguments(args,kwargs)
    if (type(source) is not bytes or not source or len(source)>MAX_SOURCE
        or hashlib.sha256(source).hexdigest()!=TRANSPORT_RAW_SHA256):
        raise ValueError('PATCH_SOURCE')
    encoded=base64.b64encode(source).decode('ascii')
    if len(encoded)>MAX_BOOTSTRAP_B64:raise ValueError('PATCH_BOOTSTRAP_SIZE')
    return encoded


def main(*args,**kwargs):
    require_pins()
    raise ValueError('APPEAL_SUFFIX_DIRECT_ENTRYPOINT_REFUSED')


if __name__=='__main__':
    try:main()
    except ValueError as error:raise SystemExit(str(error)) from None
