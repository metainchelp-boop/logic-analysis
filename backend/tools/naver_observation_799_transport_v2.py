"""Closed four-source transport for one fixed, read-only source diagnostic."""
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

OPERATION='preview-observation-799-diagnostics-v2'
PREFIX='observation-diagnostics-ad-account-799-xz-v2:'
SOURCE='799d80225a8df0c897a125dcab75fd04978b1dbb'
ARCHIVE='5de3b31c0eac7a021f360a68c9fa5d849dc385d498136a9143c2a1479e46fafa'
BASELINE='5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
MODE='observation-diagnostics-ad-account-799-v2'
IDENTIFIER_NAMESPACE='ad_account_no'
P6_CONTROLLER_SHA256='8dddb4156047f9a0bb64b3ad0db23eac62ca0cd858ff9c1cbffe4bbbbbc81426'
NATIVE_RUN='38268019380'
CANONICAL_SHA256='c6bb211aa96f181755a0130484618b5d7977f286ef402380bc8c196c5804513e'
EVENT_SELECTOR={'possibility_id':51952,'ad_account_no':1030001,'period_key':'weekly:2026-10-05:2026-10-11',
 'numeric_revision':4,'strategy_revision':0,'reserved_from':'2026-10-13T01:27:00+09:00','reserved_before':'2026-10-13T01:28:00+09:00'}
PACKAGE={'baseline':BASELINE,'source_commit':SOURCE,'source_tar_gz_sha256':ARCHIVE,'mode':MODE,
 'p6_controller_sha256':P6_CONTROLLER_SHA256,'native_run_id':NATIVE_RUN,'canonical_sha256':CANONICAL_SHA256,'event_selector':EVENT_SELECTOR}
TARGETS=(('gomso',74789,2488728),('foodin',51952,1030001))
MAX_JSON=196608
MAX_WIRE=65536
MAX_SOURCE=98304
MAX_RESULT=20480
MAX_TRANSPORT_BASE64=32768
SOURCE_FILES={'diagnostic':'naver_observation_799_diagnostics_v2.py',
    'host':'naver_erp_tunnel_service_install.py','release':'naver_preview_release.py','p6':'naver_learning_failure_patch.py'}
SOURCE_SHA256={'diagnostic': 'ec5c367d42ad9babc27361c2d70800e6ed21a5e61b95d291e74a6c73c47ea09a', 'host': '236cdd596bae2f8d5e0dfea5822bdd7216c44addac2bbb643306dfbff00fdd3a', 'release': '7288d51eba4e2c0320d196b8da2ee14f852b87f33304c221878c218cd1dacb84', 'p6': '8dddb4156047f9a0bb64b3ad0db23eac62ca0cd858ff9c1cbffe4bbbbbc81426'}
COMPACT_SHA256={'diagnostic': '0e8b04a168312ddc16e40bc8efab59507ed643b13245edc0134e5483afd8420a', 'host': 'cd6daeb55fe3ed1fd2553404c012d16f46b05bb9a1d651bd929b9787aa758840', 'release': '9681437257dd92309eb0ab2ad33c7c5c3c1e2abed334f1fa1c253fad2288c64a', 'p6': '462b0093e77ccfcdc4b218c2bc4a08bce16b860bbe9da840623d09ab130199b6'}
DEFAULTS={name:'off' for name in ('collector','rank_link','capacity','structure','expired','queue','urlshape','use_branch_code')}
STAGES=frozenset(('input','bootstrap','preflight','read_only_source_diagnostics','postflight'))
PREFLIGHT_CODES=frozenset(('SOURCE_DIAGNOSTICS_NOT_PINNED SOURCE_DIAGNOSTICS_SOURCE SOURCE_DIAGNOSTICS_BUNDLE '
    'SOURCE_DIAGNOSTICS_PACKAGE SOURCE_DIAGNOSTICS_MODULE SOURCE_DIAGNOSTICS_RESULT HOST_BASELINE '
    'RECEIPT_SIZE SOURCE_NOT_READY COMPOSE_CHANGED PREPARED_IMAGE PREPARED_IMAGE_CHANGED '
    'PREVIEW_CONTAINER_ID PREVIEW_CONTAINER_CHANGED PREVIEW_DATA_MOUNT COMMAND_FAILED DIRECTORY_POLICY '
    'SYMLINKED_PRIVATE_FILE PRIVATE_FILE_POLICY SYMLINKED_PARENT SOURCE_DIAGNOSTICS_TRANSPORT_SIZE '
    'SOURCE_DIAGNOSTICS_TRANSPORT_SOURCE SOURCE_DIAGNOSTICS_BOOTSTRAP_REFUSED UNRECOGNIZED').split())
POST_ENGINE_CODES=frozenset(('POST_ENGINE_CHANGED','POST_ENGINE_UNVERIFIED'))
POST_LEGACY_CODES=frozenset(('POST_LEGACY_BASELINE_CHANGED','POST_LEGACY_BASELINE_UNVERIFIED'))


def require_pins():
    selector={'possibility_id':51952,'ad_account_no':1030001,'period_key':'weekly:2026-10-05:2026-10-11','numeric_revision':4,'strategy_revision':0,'reserved_from':'2026-10-13T01:27:00+09:00','reserved_before':'2026-10-13T01:28:00+09:00'}
    if type(EVENT_SELECTOR) is not dict or EVENT_SELECTOR!=selector or any(type(EVENT_SELECTOR[k]) is not type(v) for k,v in selector.items()):
        raise ValueError('SOURCE_DIAGNOSTICS_NOT_PINNED')
    for pins in (SOURCE_SHA256,COMPACT_SHA256):
        if (type(pins) is not dict or set(pins)!=set(SOURCE_FILES)
                or any(type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None for value in pins.values())):
            raise ValueError('SOURCE_DIAGNOSTICS_NOT_PINNED')


def unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('SOURCE_DIAGNOSTICS_DUPLICATE')
        result[key]=value
    return result


def validate_package(package):
    if type(package) is not dict or set(package)!=set(PACKAGE) or package!=PACKAGE:
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')
    given=package['event_selector']
    if type(given) is not dict or set(given)!=set(EVENT_SELECTOR) or any(type(given[k]) is not type(v) for k,v in EVENT_SELECTOR.items()):
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')
    return package


def validate_dispatch_inputs(inputs):
    if type(inputs) is not dict or set(inputs)!={'ad_prepare','ad_expected_baseline',*DEFAULTS}:
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')
    if inputs['ad_prepare']!=OPERATION or any(inputs[name]!='off' for name in DEFAULTS):
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')
    try:package=json.loads(inputs['ad_expected_baseline'],object_pairs_hook=unique)
    except (ValueError,TypeError):raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE') from None
    return validate_package(package)


def validate(value):
    require_pins()
    if (type(value) is not dict or set(value)!={'version','operation','package','sources'}
            or type(value['version']) is not int or value['version']!=1 or value['operation']!=OPERATION
            or type(value['sources']) is not dict or set(value['sources'])!=set(SOURCE_FILES)):
        raise ValueError('SOURCE_DIAGNOSTICS_BUNDLE')
    validate_package(value['package'])
    for name,body in value['sources'].items():
        if type(body) is not str or not 0<len(body.encode())<=MAX_SOURCE or hashlib.sha256(body.encode()).hexdigest()!=COMPACT_SHA256[name]:
            raise ValueError('SOURCE_DIAGNOSTICS_SOURCE')
    return value


def encode(value):
    raw=json.dumps(validate(value),allow_nan=False,separators=(',',':')).encode()
    if len(raw)>MAX_JSON:raise ValueError('SOURCE_DIAGNOSTICS_JSON_SIZE')
    wire=PREFIX+base64.b64encode(lzma.compress(raw,format=lzma.FORMAT_XZ,check=lzma.CHECK_CRC64,preset=6)).decode()
    if len(wire)>MAX_WIRE:raise ValueError('SOURCE_DIAGNOSTICS_WIRE_SIZE')
    return wire


def decode(wire):
    if type(wire) is not str or not wire.startswith(PREFIX) or len(wire)>MAX_WIRE:
        raise ValueError('SOURCE_DIAGNOSTICS_ENCODING')
    try:
        decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=32*1024*1024)
        raw=decoder.decompress(base64.b64decode(wire[len(PREFIX):],validate=True),max_length=MAX_JSON+1)
        if len(raw)>MAX_JSON or not decoder.eof or decoder.unused_data:
            raise ValueError('SOURCE_DIAGNOSTICS_ENCODING')
        return validate(json.loads(raw,object_pairs_hook=unique))
    except (ValueError,TypeError,UnicodeError,lzma.LZMAError):
        raise ValueError('SOURCE_DIAGNOSTICS_ENCODING') from None


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



def bundle(package,root):
    require_pins();validate_package(package)
    sources={}
    for name,filename in SOURCE_FILES.items():
        raw=(Path(root)/filename).read_bytes()
        if not 0<len(raw)<=MAX_SOURCE or hashlib.sha256(raw).hexdigest()!=SOURCE_SHA256[name]:
            raise ValueError('SOURCE_DIAGNOSTICS_SOURCE')
        sources[name]=compact(raw.decode())
    return validate({'version':1,'operation':OPERATION,'package':package,'sources':sources})


def modules(value):
    validate(value)
    # The immutable P6 controller is authenticated as bytes and constants; never executed.
    if SOURCE_SHA256['p6']!=P6_CONTROLLER_SHA256:raise ValueError('SOURCE_DIAGNOSTICS_MODULE')
    constants={}
    for node in ast.parse(value['sources']['p6']).body:
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in ('TARGET_COMMIT','TARGET_SOURCE_SHA256','OLD_COMMIT','CI_PROOF'):
                    if target.id in constants:raise ValueError('SOURCE_DIAGNOSTICS_MODULE')
                    constants[target.id]=ast.literal_eval(node.value)
    if constants!={'TARGET_COMMIT':SOURCE,'TARGET_SOURCE_SHA256':ARCHIVE,
            'OLD_COMMIT':'dc168ff8cf8dac519ea38597305a0d9dd6f6c843',
            'CI_PROOF':{'source_commit':SOURCE,'tooling_head':'3f00365c6f8043fb48ec3f33aa0071531f27b9b4',
                'run_id':NATIVE_RUN,'receipt_sha256':CANONICAL_SHA256}}:
        raise ValueError('SOURCE_DIAGNOSTICS_MODULE')
    diagnostic=types.ModuleType('approved_completion_source_diagnostic')
    exec(value['sources']['diagnostic'],diagnostic.__dict__)
    if (diagnostic.SOURCE!=SOURCE or diagnostic.ARCHIVE!=ARCHIVE or diagnostic.BASELINE!=BASELINE
            or diagnostic.SCHEMA!=21 or diagnostic.MODE!=MODE or diagnostic.TARGETS!=TARGETS
            or getattr(diagnostic,'TARGET_NAMESPACE',None)!=IDENTIFIER_NAMESPACE
            or getattr(diagnostic,'P6_CONTROLLER_SHA256',None)!=P6_CONTROLLER_SHA256
            or getattr(diagnostic,'NATIVE_RUN',None)!=NATIVE_RUN or getattr(diagnostic,'CANONICAL_SHA256',None)!=CANONICAL_SHA256):
        raise ValueError('SOURCE_DIAGNOSTICS_MODULE')
    if getattr(diagnostic,'EVENT_SELECTOR',None)!=EVENT_SELECTOR:raise ValueError('SOURCE_DIAGNOSTICS_MODULE')
    diagnostic.validate_package(value['package'])
    result={'diagnostic':diagnostic}
    for name in ('host','release'):
        module=types.ModuleType('approved_completion_source_'+name)
        exec(value['sources'][name],module.__dict__);result[name]=module
    return result


def project_result(value,diagnostic):
    if type(value) is not dict or type(value.get('ok')) is not bool:
        raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
    common={'mode':MODE,'source_commit':SOURCE,'mutations':0,'collection_completion_verified':False}
    if any(type(value.get(key)) is not type(item) or value.get(key)!=item for key,item in common.items()):
        raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
    if value['ok']:
        if set(value)!={'ok',*common,'reader_mode','database_opened_by_controller','existing_app_baseline_unchanged','diagnostics'}:
            raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
        if (value['reader_mode']!='sqlite-mode-ro-query-only-authorizer' or value['database_opened_by_controller'] is not False
                or value['existing_app_baseline_unchanged'] is not True):raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
        if type(value['diagnostics']) is not dict or value['diagnostics'].get('target_identifier_namespace')!=IDENTIFIER_NAMESPACE:
            raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
        diagnostic.validate_result(value['diagnostics'])
    elif 'failure' in value:
        if set(value) not in ({'ok',*common,'failure'},{'ok',*common,'failure','failure_detail'}) or type(value['failure']) is not dict or set(value['failure'])!={'primary_code','post_engine_code','post_legacy_baseline_code'}:
            raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
        failure=value['failure']
        for key,allowed in (('primary_code',diagnostic.READ_FAILURE_CODES),('post_engine_code',POST_ENGINE_CODES),('post_legacy_baseline_code',POST_LEGACY_CODES)):
            if failure[key] is not None and (type(failure[key]) is not str or failure[key] not in allowed):
                raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
        if all(item is None for item in failure.values()):raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
        if 'failure_detail' in value:
            if failure['primary_code'] is None:raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
            diagnostic.validate_failure_detail(value['failure_detail'])
    else:
        if (set(value)!={'ok',*common,'stage','error_code'} or value['stage'] not in STAGES
                or value['error_code'] not in PREFLIGHT_CODES):raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
    if len(json.dumps(value,allow_nan=False,separators=(',',':')).encode())>MAX_RESULT:
        raise ValueError('SOURCE_DIAGNOSTICS_RESULT')
    return value


def failure(error,stage='preflight'):
    code=error.args[0] if type(error) in (ValueError,RuntimeError) and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in PREFLIGHT_CODES else 'UNRECOGNIZED'
    return {'ok':False,'mode':MODE,'source_commit':SOURCE,'mutations':0,'collection_completion_verified':False,
        'stage':stage if type(stage) is str and stage in STAGES else 'preflight','error_code':code}


def execute(value):
    diagnostic=None
    try:
        m=modules(value);diagnostic=m['diagnostic']
        result=diagnostic.run(value['package'],m['host'].NativeHost(),m['release'])
        return project_result(result,diagnostic)
    except Exception as error:
        return failure(error,getattr(diagnostic,'STAGE','preflight'))
