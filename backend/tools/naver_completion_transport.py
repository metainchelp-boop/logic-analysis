"""Dedicated completion codec; historical preview encoders/decoders untouched."""
import ast
import base64
import gzip
import io
import lzma
import json
import os
from pathlib import Path
import stat
import tokenize
import types
import zlib

PREFIX='completion-xz-v1:'
MAX_JSON=393216
MAX_WIRE=98304
MAX_SOURCE_GZIP=3*1024*1024
MAX_CIPHERTEXT=3*1024*1024
MAX_PAYLOAD=4*1024*1024
FUNCTIONS={'preview-completion-prepare':'prepare','preview-completion-apply':'apply','preview-completion-rollback':'rollback',
    'preview-completion-recover-failed-apply':'recover_failed_apply'}
SOURCE_FILES={'controller':'naver_preview_completion_release.py','host':'naver_erp_tunnel_service_install.py',
    'release':'naver_preview_release.py','lifecycle':'naver_preview_lifecycle.py','upgrade':'naver_preview_upgrade.py',
    'exports_binding':'naver_completion_exports.py','exports_helper':'naver_saved_exports.py',
    'product_exporter':'../naver_product_export.py','market_exporter':'../naver_market_export.py',
    'failed_apply_recovery':'naver_completion_failed_apply_recovery.py'}
EXPORT_DIRECTORIES={
    Path('/srv/metainc/ad-deploy-staging/saved-exports'):0o700,
    Path('/opt/metainc'):0o755,
    Path('/opt/metainc/naver-saved-exports'):0o755}


class CompletionRelease:
    """Only this new route uses the larger sealed source envelope."""
    def __init__(self,release):self._release=release
    def __getattr__(self,name):return getattr(self._release,name)

    def received_ciphertext(self,path,expected_sha256):
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


def _prepare_export_directories():
    """Create only fixed missing directories; never repair an existing path."""
    if os.geteuid()!=0:raise ValueError('COMPLETION_EXPORT_DIRECTORY')
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    leaves=(Path('/srv/metainc/ad-deploy-staging/saved-exports'),Path('/opt/metainc/naver-saved-exports'))
    def checked(fd,path):
        info=os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:
            raise ValueError('COMPLETION_EXPORT_DIRECTORY')
        if path in EXPORT_DIRECTORIES and (info.st_gid!=0 or stat.S_IMODE(info.st_mode)!=EXPORT_DIRECTORIES[path]):
            raise ValueError('COMPLETION_EXPORT_DIRECTORY')
    # Validate every existing ancestor before creating either leaf.
    for create in (False,True):
        for leaf in leaves:
            fd=os.open('/',flags)
            try:
                current=Path('/');checked(fd,current)
                parts=leaf.parts[1:]
                for index,part in enumerate(parts):
                    current=current/part;new=False
                    try:child=os.open(part,flags,dir_fd=fd)
                    except FileNotFoundError:
                        remaining=[current.joinpath(*parts[index+1:offset+1]) for offset in range(index,len(parts))]
                        if any(path not in EXPORT_DIRECTORIES for path in remaining):
                            raise ValueError('COMPLETION_EXPORT_DIRECTORY') from None
                        if not create:break
                        os.mkdir(part,EXPORT_DIRECTORIES[current],dir_fd=fd);new=True
                        child=os.open(part,flags,dir_fd=fd)
                    except OSError:
                        raise ValueError('COMPLETION_EXPORT_DIRECTORY') from None
                    try:
                        if new:
                            # Only this invocation's new inode receives exact ownership/mode.
                            os.fchown(child,0,0);os.fchmod(child,EXPORT_DIRECTORIES[current])
                            os.fsync(child);os.fsync(fd)
                        checked(child,current)
                    except BaseException:
                        os.close(child);raise
                    os.close(fd);fd=child
            finally:os.close(fd)


def validate(bundle):
    if (type(bundle) is not dict or set(bundle)!={'version','operation','package','sources','approved_config_operation_id'}
        or type(bundle['version']) is not int or bundle['version']!=1 or type(bundle['operation']) is not str or bundle['operation'] not in FUNCTIONS
        or type(bundle['package']) is not dict or type(bundle['sources']) is not dict or set(bundle['sources'])!=set(SOURCE_FILES)
        or any(type(value) is not str or not value or len(value.encode())>160000 for value in bundle['sources'].values())
        or bundle['approved_config_operation_id']!=('74c912dddf824fae99012849bc4c19a5' if bundle['operation']=='preview-completion-prepare' else None)):
        raise ValueError('COMPLETION_BUNDLE')
    return bundle


def encode(bundle):
    raw=json.dumps(validate(bundle),separators=(',',':')).encode()
    if len(raw)>MAX_JSON:raise ValueError('COMPLETION_JSON_SIZE')
    wire=PREFIX+base64.b64encode(lzma.compress(raw,format=lzma.FORMAT_XZ,check=lzma.CHECK_CRC64,preset=6)).decode()
    if len(wire)>MAX_WIRE:raise ValueError('COMPLETION_WIRE_SIZE')
    return wire


def decode(wire):
    if type(wire) is not str or not wire.startswith(PREFIX) or len(wire)>MAX_WIRE:raise ValueError('COMPLETION_ENCODING')
    packed=base64.b64decode(wire[len(PREFIX):],validate=True)
    decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=32*1024*1024)
    raw=decoder.decompress(packed,max_length=MAX_JSON+1)
    if len(raw)>MAX_JSON or not decoder.eof or decoder.unused_data:raise ValueError('COMPLETION_XZ')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('COMPLETION_DUPLICATE')
            result[key]=value
        return result
    return validate(json.loads(raw,object_pairs_hook=unique))


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
    return result


def bundle(operation,package,root):
    if operation not in FUNCTIONS:raise ValueError('COMPLETION_OPERATION')
    import naver_preview_completion_release as C
    C.require_pins()
    import naver_completion_exports as E
    E.require_pins()
    sources={name:((Path(root)/filename).read_text() if name in ('exports_helper','product_exporter','market_exporter') else compact((Path(root)/filename).read_text())) for name,filename in SOURCE_FILES.items()}
    return validate({'version':1,'operation':operation,'package':package,'sources':sources,
        'approved_config_operation_id':C.APPROVED_CONFIG_OPERATION_ID if operation=='preview-completion-prepare' else None})


def modules(bundle):
    validate(bundle);result={}
    # Controller pin refusal precedes host/release execution and all external effects.
    for name in ('controller','host','release','lifecycle','upgrade','exports_binding','exports_helper','failed_apply_recovery'):
        module=types.ModuleType('approved_completion_'+name);exec(bundle['sources'][name],module.__dict__);result[name]=module
        if name in ('controller','exports_binding'):module.require_pins()
    result['release']=CompletionRelease(result['release'])
    return result


def _remember_failure(controller, error, *, primary=None):
    """Carry only closed diagnostics across independently loaded controllers."""
    def details(value):
        return {key:item for key,item in controller.failure_report(value).items()
                if key not in ('stage', 'error_kind', 'error_code')}
    saved=details(error)
    if primary is not None:
        # The original failure and its already captured recovery facts win.
        saved.update(details(primary))
    for key,value in controller._capture_failure(error, 'cleanup' if primary is not None else 'failed').items():
        saved.setdefault(key,value)
    error.failure_details=saved


def _cleanup_failure(controller, binding, error):
    _remember_failure(controller,error)
    try:binding.rollback()
    except Exception as cleanup:
        _remember_failure(controller,cleanup,primary=error)
        raise


def execute(bundle,*,incoming=False):
    validate(bundle);m=modules(bundle);C=m['controller'];release=m['release'];host=m['host'].NativeHost()
    if bundle['operation']=='preview-completion-recover-failed-apply':
        if incoming:raise ValueError('COMPLETION_OPERATION')
        return m['failed_apply_recovery'].recover(bundle['package'],host,release,m['lifecycle'],m['upgrade'],C)
    if incoming:
        if bundle['operation']!='preview-completion-prepare':raise ValueError('COMPLETION_OPERATION')
        package=C.validate_package(bundle['package'],release)
        if os.geteuid()!=0 or host.baseline()!=package['baseline']:raise ValueError('HOST_BASELINE')
        for path in (release.ROOT,release.ROOT/'incoming'):release.trusted_dir(path,mode=0o700)
        _prepare_export_directories()
        release.trusted_dir(release.ROOT/'incoming'/package['run_id'],mode=0o700,new=True)
        return {'ok':True,'stage':'incoming_ready','source_commit':C.TARGET_COMMIT}
    try:
        C.STAGE='saved_exports_binding'
        binding=m['exports_binding'].Binding(C,m['exports_helper'],release,bundle['sources']['exports_helper'].encode(),
            {'naver_product_export.py':bundle['sources']['product_exporter'].encode(),
             'naver_market_export.py':bundle['sources']['market_exporter'].encode()})
        if bundle['operation']=='preview-completion-prepare':
            try:
                C.STAGE='saved_exports_prepare'
                wrapped=binding.prepare(bundle['package'])
                result=C.prepare(bundle['package'],host,wrapped,m['lifecycle'],m['upgrade'],approved_config_operation_id=bundle['approved_config_operation_id'],prepare_exports=binding.install)
                binding.save(bundle['package']);return {**result,'saved_export_companion_prepared':True,'export_jobs_started':True,'export_engine_verified':False}
            except Exception as error:
                _cleanup_failure(C,binding,error)
                raise
        package=bundle['package']
        wrapped=binding.load(package['release'],verify=bundle['operation']!='preview-completion-rollback')
        if bundle['operation']=='preview-completion-rollback':binding.preflight_rollback()
        try:result=getattr(C,FUNCTIONS[bundle['operation']])(package,host,wrapped,m['lifecycle'],m['upgrade'])
        except Exception as error:
            # A rejected/replayed request must not remove exports from a live target.
            # Only the controller's verified paired rollback authorizes cleanup.
            if bundle['operation']=='preview-completion-apply' and type(error) is RuntimeError and error.args==('CODE_FAILED_ROLLED_BACK_DB_PRESERVED',):
                _cleanup_failure(C,binding,error)
            raise
        if bundle['operation']=='preview-completion-rollback':binding.rollback()
        return result
    except Exception as error:
        _remember_failure(C,error)
        raise
