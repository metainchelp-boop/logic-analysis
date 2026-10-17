"""New-only source4d RO transport; source/native/self pins are pending by default."""
import ast
import base64
import hashlib
import io
import json
import lzma
from pathlib import Path
import re
import tokenize
import types

OPERATION = 'preview-daily-current-source-diagnostics-v5'
PREFIX = 'daily-current-source-4d-v5-xz:'
MARKER = 'NAVER_DAILY_CURRENT_DIAGNOSTICS_V5='
SOURCE = '4d5802360c1ba23aa801b1145ca8483db3edd35f'
MODE = 'daily-current-source-4d-v5-fixed-0710'
MAX_JSON, MAX_WIRE, MAX_SOURCE, MAX_RESULT = 196608, 65536, 98304, 20480
MAX_TRANSPORT_BASE64, MAX_SSH = 32768, 131072
SOURCE_FILES = {'controller': 'naver_daily_current_diagnostics_v5.py',
    'reader': 'naver_daily_current_reader_v5.py', 'host': 'naver_erp_tunnel_service_install.py',
    'release': 'naver_preview_release.py', 'lifecycle': 'naver_preview_lifecycle.py'}
SOURCE_SHA256 = {'controller': '306f39c8358003b85b8f16639b8cb2bf8a1cd056164a86fb90e34286158513e4', 'reader': 'beb0293e52546b33a0f99fffb064f08921cbe43963857752ff043682f7889c72', 'host': '236cdd596bae2f8d5e0dfea5822bdd7216c44addac2bbb643306dfbff00fdd3a', 'release': '7288d51eba4e2c0320d196b8da2ee14f852b87f33304c221878c218cd1dacb84', 'lifecycle': '4f5f85c197b5efe2c323b2c784814eb1bd177dd60d44b8c7ead943b0af98abc4'}
COMPACT_SHA256 = {'controller': 'f84eb3bd6f28a6f0624491bb54a63a896b810b23c67fa68d0d4fc8d0f2dbcc6d', 'reader': 'beb0293e52546b33a0f99fffb064f08921cbe43963857752ff043682f7889c72', 'host': 'cd6daeb55fe3ed1fd2553404c012d16f46b05bb9a1d651bd929b9787aa758840', 'release': '9681437257dd92309eb0ab2ad33c7c5c3c1e2abed334f1fa1c253fad2288c64a', 'lifecycle': '2020afcf0d616107c9043914a7e70ed8a842ccfb22ca05052d5be4b585d17b15'}
FIXED_RAW = {'reader': 'beb0293e52546b33a0f99fffb064f08921cbe43963857752ff043682f7889c72', 'host': '236cdd596bae2f8d5e0dfea5822bdd7216c44addac2bbb643306dfbff00fdd3a', 'release': '7288d51eba4e2c0320d196b8da2ee14f852b87f33304c221878c218cd1dacb84', 'lifecycle': '4f5f85c197b5efe2c323b2c784814eb1bd177dd60d44b8c7ead943b0af98abc4'}
APPROVED_RECEIPTS = {
    'native_receipt': '640d65e1de4110fe8d420e4a6dfc271f32d7febea57105d2b163c6ec81823e75',
    'canonical_receipt': 'b1ce7e10044552e9d50427ba15f1e201836d88747fd0d16476a917cf72dab5c8',
    'deployed_prepare': '1067d59f9cf14261a2622fad8fd19ef3a8b8741e5c9cfdcb8c7259aaec11d6fa',
    'deployed_apply': '9a5ab33a7624a0baf82a55fa0f56049eab229a0569f410f42329d527dc7298f2'}
VERIFIED_TRANSPORT_IDENTITY = None
VERIFIED_NATIVE_AUTHORIZATION = None
PRIMARY_CODES = frozenset(('D3_PINS_PENDING D3_PIN_MISMATCH D3_PACKAGE D3_ROOT D3_BASELINE '
    'D3_RECEIPT D3_SOURCE_NOT_READY D3_COMPOSE D3_COMPANION D3_UNIT_BYTES D3_UNIT_ACTIVE D3_UNIT_ENABLED D3_CONTAINER D3_READER_SOURCE '
    'D3_HOST_SOURCE D3_READER_FAILED D3_READER_TIMEOUT D3_READER_COMMAND D3_READER_JSON D3_READER_VALIDATION D3_OUTPUT D3_INTERNAL D3_TRANSPORT_REJECTED').split())
READER_STAGES = frozenset(('SOURCE IMPORT DB_OPEN DB_QUERY VALIDATE CLEANUP').split())
READER_REASONS = frozenset('D3_DATABASE_PATH D3_DEADLINE D3_EXECUTION_PINS_INVALID D3_EXECUTION_PINS_PENDING D3_MUTATION D3_OUTPUT_SHAPE D3_READER_MODE D3_READ_BOUND D3_SCHEMA D3_SETUP_SHAPE D3_SHAPE D3_SOURCE_IMPORT D3_SOURCE_PIN D3_TIME D3_UI_BRANCH_MISMATCH D3_SQLITE_AUTH D3_SQLITE_BUSY D3_SQLITE_OTHER D3_UNCLASSIFIED'.split())
DEFAULTS = {name: 'off' for name in ('collector', 'rank_link', 'capacity', 'structure',
                                    'expired', 'queue', 'urlshape', 'use_branch_code')}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def native_shape(value):
    return (type(value) is dict and set(value) == {'head', 'run_id', 'receipt_sha256'}
        and type(value['head']) is str and re.fullmatch('[0-9a-f]{40}', value['head']) is not None
        and type(value['run_id']) is int and value['run_id'] > 0
        and type(value['receipt_sha256']) is str and re.fullmatch('[0-9a-f]{64}', value['receipt_sha256']) is not None)


def authorize(transport_raw_sha256, native_authorization):
    """The authenticated bootstrap literal, never caller package fields, supplies these."""
    global VERIFIED_TRANSPORT_IDENTITY, VERIFIED_NATIVE_AUTHORIZATION
    if (type(transport_raw_sha256) is not str or re.fullmatch('[0-9a-f]{64}', transport_raw_sha256) is None
            or globals().get('__verified_self_sha__') != transport_raw_sha256
            or not native_shape(native_authorization)):
        raise ValueError('D3_TRANSPORT_UNPINNED')
    VERIFIED_TRANSPORT_IDENTITY = transport_raw_sha256
    VERIFIED_NATIVE_AUTHORIZATION = dict(native_authorization)


def require_pins():
    if (VERIFIED_TRANSPORT_IDENTITY is None or VERIFIED_NATIVE_AUTHORIZATION is None
            or any(type(pins) is not dict or set(pins) != set(SOURCE_FILES)
                or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in pins.values())
                for pins in (SOURCE_SHA256, COMPACT_SHA256))):
        raise ValueError('D3_TRANSPORT_UNPINNED')
    if any(SOURCE_SHA256[k] != v for k, v in FIXED_RAW.items()):
        raise ValueError('D3_TRANSPORT_SOURCE')
    if (globals().get('__verified_self_sha__') != VERIFIED_TRANSPORT_IDENTITY
            or not native_shape(VERIFIED_NATIVE_AUTHORIZATION)):
        raise ValueError('D3_TRANSPORT_UNPINNED')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('D3_TRANSPORT_DUPLICATE')
        result[key] = value
    return result


def validate_package(package):
    require_pins()
    expected = {'mode': MODE, 'baseline': '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76',
        'source_commit': SOURCE, 'source_tar_gz_sha256': '1db45b8e54e562bd83c12b4cf53c791426ea45fccd85162bfb0e5f27179873fe',
        'p9_controller_sha256': '77e9162979683b067a34d7ed9e9589030cebb0466e49dcdb65f9b28e57f85968',
        'native_run_id': '38307879311', 'event_selector': {'possibility_id': 51952,
            'ad_account_no': 1030001, 'period_key': 'weekly:2026-10-05:2026-10-11',
            'numeric_revision': 4, 'strategy_revision': 0,
            'reserved_from': '2026-10-13T07:10:00+09:00', 'reserved_before': '2026-10-13T07:11:00+09:00'},
        'evidence': dict(APPROVED_RECEIPTS, controller_transport_identity=VERIFIED_TRANSPORT_IDENTITY),
        'diagnostic_native': VERIFIED_NATIVE_AUTHORIZATION}
    def typed_equal(left, right):
        return type(left) is type(right) and (set(left) == set(right) and all(
            typed_equal(left[k], right[k]) for k in right) if type(right) is dict else left == right)
    if not typed_equal(package, expected):
        raise ValueError('D3_TRANSPORT_PACKAGE')
    return package


def validate_dispatch_inputs(inputs):
    require_pins()
    if (type(inputs) is not dict or set(inputs) != {'ad_prepare', 'ad_expected_baseline', *DEFAULTS}
            or inputs['ad_prepare'] != OPERATION or any(inputs[k] != v for k, v in DEFAULTS.items())):
        raise ValueError('D3_TRANSPORT_PACKAGE')
    try:
        return validate_package(json.loads(inputs['ad_expected_baseline'], object_pairs_hook=unique))
    except (TypeError, ValueError):
        raise ValueError('D3_TRANSPORT_PACKAGE') from None


def validate(value):
    require_pins()
    if (type(value) is not dict or set(value) != {'version', 'operation', 'package', 'sources'}
            or type(value['version']) is not int or value['version'] != 1 or value['operation'] != OPERATION
            or type(value['sources']) is not dict or set(value['sources']) != set(SOURCE_FILES)):
        raise ValueError('D3_TRANSPORT_BUNDLE')
    validate_package(value['package'])
    for key, body in value['sources'].items():
        if (type(body) is not str or not 0 < len(body.encode()) <= MAX_SOURCE
                or digest(body.encode()) != COMPACT_SHA256[key]):
            raise ValueError('D3_TRANSPORT_SOURCE')
    return value


def encode(value):
    raw = json.dumps(validate(value), allow_nan=False, separators=(',', ':')).encode()
    if len(raw) > MAX_JSON:
        raise ValueError('D3_TRANSPORT_JSON_SIZE')
    wire = PREFIX+base64.b64encode(lzma.compress(raw, format=lzma.FORMAT_XZ,
        check=lzma.CHECK_CRC64, preset=6)).decode()
    if len(wire.encode()) > MAX_WIRE:
        raise ValueError('D3_TRANSPORT_WIRE_SIZE')
    return wire


def decode(wire):
    require_pins()
    if type(wire) is not str or not wire.startswith(PREFIX) or len(wire.encode()) > MAX_WIRE:
        raise ValueError('D3_TRANSPORT_ENCODING')
    try:
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=32*1024*1024)
        raw = decoder.decompress(base64.b64decode(wire[len(PREFIX):], validate=True), max_length=MAX_JSON+1)
        if len(raw) > MAX_JSON or not decoder.eof or decoder.unused_data:
            raise ValueError('D3_TRANSPORT_ENCODING')
        return validate(json.loads(raw, object_pairs_hook=unique))
    except (ValueError, TypeError, UnicodeError, lzma.LZMAError):
        raise ValueError('D3_TRANSPORT_ENCODING') from None


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



def bundle(package, root):
    require_pins()
    validate_package(package)
    sources = {}
    for key, name in SOURCE_FILES.items():
        path = Path(root)/name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_SOURCE:
            raise ValueError('D3_TRANSPORT_SOURCE')
        raw = path.read_bytes()
        if not raw or digest(raw) != SOURCE_SHA256[key]:
            raise ValueError('D3_TRANSPORT_SOURCE')
        sources[key] = raw.decode() if key == 'reader' else compact(raw.decode())
    return validate(dict(version=1, operation=OPERATION, package=package, sources=sources))


def modules(value):
    validate(value)
    result = {}
    for key in SOURCE_FILES:
        module = types.ModuleType('approved_daily_current_'+key)
        exec(compile(value['sources'][key], '<approved-daily-current-'+key+'>', 'exec'), module.__dict__)
        result[key] = module
    c, r = result['controller'], result['reader']
    if (c.SOURCE != SOURCE or c.MODE != MODE or c.READER_SHA256 != FIXED_RAW['reader']
            or r.SOURCE != SOURCE or r.CANONICAL_SHA256 != APPROVED_RECEIPTS['canonical_receipt']
            or len(r.SOURCE_FILES) != 163 or len(r.IMAGE_SOURCE_FILES) != 106
            or r.READ_REASONS != READER_REASONS or c.READER_REASONS != READER_REASONS
            or r.IMAGE_SOURCE_MAP_SHA256 != '69d77f2c2ede33f35d8d424665dfd85b4a710fcf3ff5fc88a85b281ce564332f'
            or r.EVENT_FROM.isoformat() != '2026-10-13T07:10:00+09:00'
            or r.EVENT_UNTIL.isoformat() != '2026-10-13T07:11:00+09:00'
            or any(v is not None for v in r.EXECUTION_PINS.values())):
        raise ValueError('D3_TRANSPORT_MODULE')
    c.bind_verified_evidence(value['package']['evidence'], VERIFIED_TRANSPORT_IDENTITY, VERIFIED_NATIVE_AUTHORIZATION)
    c.validate_package(value['package'])
    # Frozen reader raw bytes must travel unchanged; compacting its quoted code
    # would change its authenticated digest. The controller executes the raw
    # body reconstructed in memory from the separately authenticated text below.
    return result


def project_result(value, reader):
    require_pins()
    common = dict(mode=MODE, source_commit=SOURCE, mutations=0,
        database_opened_by_controller=False, collection_completion_verified=False)
    if (type(value) is not dict or type(value.get('ok')) is not bool
            or any(type(value.get(k)) is not type(v) or value.get(k) != v for k, v in common.items())):
        raise ValueError('D3_TRANSPORT_RESULT')
    if value['ok']:
        if (set(value) != {*common, 'ok', 'existing_app_baseline_unchanged', 'reader_mode', 'diagnostics'}
                or value['existing_app_baseline_unchanged'] is not True
                or value['reader_mode'] != 'sqlite-mode-ro-query-only-authorizer'):
            raise ValueError('D3_TRANSPORT_RESULT')
        reader.validate_result(value['diagnostics'])
    else:
        if set(value) != {*common, 'ok', 'failure'} or type(value['failure']) is not dict:
            raise ValueError('D3_TRANSPORT_RESULT')
        choices = {'primary_code': PRIMARY_CODES, 'reader_stage': READER_STAGES, 'reader_reason': READER_REASONS, 'post_engine_code': {'D3_POST_ENGINE'},
            'post_legacy_code': {'D3_POST_LEGACY'}, 'post_proof_code': {'D3_POST_PROOF'}}
        if set(value['failure']) != set(choices) or all(v is None for v in value['failure'].values()):
            raise ValueError('D3_TRANSPORT_RESULT')
        if ((value['failure']['reader_stage'] is None) != (value['failure']['reader_reason'] is None)
                or value['failure']['reader_stage'] is not None and value['failure']['primary_code'] != 'D3_READER_FAILED'):
            raise ValueError('D3_TRANSPORT_RESULT')
        for k, v in value['failure'].items():
            if v is not None and (type(v) is not str or v not in choices[k]):
                raise ValueError('D3_TRANSPORT_RESULT')
    if len(json.dumps(value, allow_nan=False, separators=(',', ':')).encode()) > MAX_RESULT:
        raise ValueError('D3_TRANSPORT_RESULT')
    return value


def execute(value):
    require_pins()
    m = modules(value)
    # reader transport preserves its raw body while still authenticating all
    # other compacted modules. No fixture or test source reaches this process.
    try:
        result = m['controller'].run(value['package'], m['host'].NativeHost(),
            m['release'], m['lifecycle'], value['sources']['reader'], m['reader'])
    except Exception as error:
        code = (error.args[0] if type(error) is ValueError and len(error.args) == 1
            and type(error.args[0]) is str and error.args[0] in PRIMARY_CODES else 'D3_INTERNAL')
        result = dict(ok=False, mode=MODE, source_commit=SOURCE, mutations=0,
            database_opened_by_controller=False, collection_completion_verified=False,
            failure=dict(primary_code=code, post_engine_code=None, post_legacy_code=None, post_proof_code=None, reader_stage=None, reader_reason=None))
    return project_result(result, m['reader'])


def bootstrap(wire, transport_base64, transport_raw_sha256, native_authorization=None):
    # This builder receives only root-authenticated literals. No path or process
    # is touched while any native/self pin remains unknown.
    if (not native_shape(native_authorization) or type(transport_raw_sha256) is not str
            or re.fullmatch('[0-9a-f]{64}', transport_raw_sha256) is None
            or type(transport_base64) is not str or len(transport_base64) > MAX_TRANSPORT_BASE64
            or type(wire) is not str or not wire.startswith(PREFIX) or len(wire.encode()) > MAX_WIRE):
        raise ValueError('D3_TRANSPORT_UNPINNED')
    raw = base64.b64decode(transport_base64, validate=True)
    if digest(raw) != transport_raw_sha256:
        raise ValueError('D3_TRANSPORT_SOURCE')
    failure = dict(ok=False, mode=MODE, source_commit=SOURCE, mutations=0,
        database_opened_by_controller=False, collection_completion_verified=False,
        failure=dict(primary_code='D3_TRANSPORT_REJECTED', post_engine_code=None,
                     post_legacy_code=None, post_proof_code=None, reader_stage=None, reader_reason=None))
    code = ('import base64,hashlib,json,types\ntry:\n'
        +' raw=base64.b64decode('+repr(transport_base64)+',validate=True)\n'
        +' expected='+repr(transport_raw_sha256)+'\n'
        +" if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('D3_TRANSPORT_SOURCE')\n"
        +" m=types.ModuleType('approved_daily_current_transport')\n"
        +' exec(compile(raw,"<approved-daily-current-transport>","exec"),m.__dict__)\n'
        +' m.__verified_self_sha__=expected\n'
        +' m.authorize(expected,'+repr(native_authorization)+')\n'
        +' result=m.execute(m.decode('+repr(wire)+'))\n'
        +'except Exception:\n result='+repr(failure)+'\n'
        +'print('+repr(MARKER)+'+json.dumps(result,sort_keys=True,allow_nan=False,separators=(",",":")))\n')
    if len(code.encode()) > MAX_SSH:
        raise ValueError('D3_TRANSPORT_SSH_SIZE')
    return code
