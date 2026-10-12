"""One closed faa0/schema21 strategy validation observation transition. No database/export mutation.

The immutable completion controller remains the historical paired baseline.
New target pins intentionally remain absent until exact source/CI/seal review.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
from types import SimpleNamespace
import uuid

OLD_COMMIT = 'faa0df6225aa5fff5c4e4884245a4884c0b5f77a'
BASE_PREVIOUS_COMMIT = '737a65952f2ddbc05a235cf2b139a4a11f4e7673'
BASE_PREPARE_RUN = '38226368092'
BASE_APPLY_OPERATION = '5ae979f5fabf4f43a4651337281d8712'
BASE_CONTROLLER_SHA256 = '3be9c0360a6f75192455d6b139317319dd111b4e404628505ae62783b37977e2'
EXPECTED_BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
APPROVED_CONFIG_OPERATION_ID = '74c912dddf824fae99012849bc4c19a5'
OLD_SCHEMA = TARGET_SCHEMA = 21
CODE_PATHS = frozenset({'naver_engine/marketing_strategy.py', 'naver_engine/strategy_validation.py',
    'naver_engine/observation_store.py', 'naver_engine/observation_views.py', 'naver_engine/web.py',
    'naver_runtime/observation_binding.py', 'backend/naver_page/operations-ui.js', 'backend/naver_page/report-ui.js'})
NEW_PATHS = frozenset({'naver_engine/strategy_validation.py'})
TARGET_COMMIT = '70e6657ac789ce4d72a165dbf6a6e552d2b84043'
TARGET_SOURCE_SHA256 = '499d3ad004e93ecbcd7fcebd2e6f0aae1cd1b127be219d09c3763800b115de4c'
TARGET_DELTA = {'naver_engine/marketing_strategy.py': (420, 87244, 'e0c96eba8e525bd7942007e50acbaf05dcf70ab73b2bd3fb7d9f3a70add5d136'), 'backend/naver_page/operations-ui.js': (420, 15052, '47618e32f3145a269ff11225e7fff72ed1e68ccf9bb084df043959f91d56c0e8'), 'naver_engine/web.py': (420, 123886, '2a7a4bfde5fb44b7469f240c9d054be5b485aa3811a8a6cc2f03c19264630c0c'), 'naver_engine/strategy_validation.py': (420, 2946, '91ecd1edfd13553967886408022ff3d6e99a05b9123302ec3b62feb2a3380055'), 'naver_engine/observation_views.py': (420, 4202, '9b95662b7a39a0c36d175b6d28dbfeee4d9057d5f7713943d44bfdd088961de4'), 'naver_runtime/observation_binding.py': (420, 1965, '1b00d9498e4e0f7684c6f33d5b2ecf9a26b03dbefa4670abd1d02cb5eefb6a9d'), 'naver_engine/observation_store.py': (420, 14625, 'da22ce811a8ec9cf7df382fe06eb4ac95dd82016ba5286713a29af72a98a45b4'), 'backend/naver_page/report-ui.js': (420, 102791, 'd5d48ee9839c0fb0e30d0e2264cf5916a89dd6a12094053f6161606184d00389')}
TARGET_MANIFEST = None
REPORT_ASSETS = None
# receipt_sha256 is the exact native-CI canonical-source.json receipt digest.
CI_PROOF = {'source_commit': '70e6657ac789ce4d72a165dbf6a6e552d2b84043', 'tooling_head': '298c3e8c77d14744263dedd487a00c6acf9ea1b7', 'run_id': '38230581325', 'receipt_sha256': '26a299b7a040b1418675a5a10d08ff37d330bf9d8fed2fa2b15bca548356919b'}
BASE = None
OLD_SOURCE_SHA256 = 'ed06d35bcae09180e3b6c2fa23fe9c3b6a8cd07db9af4b88b2425bc1aa824de5'
OLD_MANIFEST = None
OLD_REPORT_ASSETS = None
STORE_SHA256 = None

# Fixed historical paired release and the successful dadb code-only baseline.
HISTORICAL_TARGET = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
HISTORICAL_PREPARE_RUN = '38198428850'
HISTORICAL_APPLY_OPERATION = '0e33647f9255442bbc94c274db23d438'
DADB_DELTA = {'backend/naver_page/report-ui.js': (420, 102832, '1f268f25770568c7dd3e4824085ac6d887e75f3aec06213c3697d6ec3936d1c3'), 'naver_engine/inspection_store.py': (420, 30640, 'ec915226e4f05743a4a78bd0a07c029c9ea4b0a3150454571e732ebca5f7e8fe'), 'naver_engine/management_store.py': (420, 11723, '13ee58e1d4383acf3ab8da469e7e09b9032640c2629e601809a3991b4c650fc5'), 'naver_engine/store.py': (420, 448743, 'f7dfb3d3e6d7ed5951ade140d52e971b4ec6e9215803113b3a787efdcc283d7a')}
DADB_MANIFEST_SHA256 = '79a702995d96db0f10c66f83e68b622473b2152befbe9874d6ba9d0686672d5f'
DADB_ASSETS_SHA256 = '22c31c812b21820953bef7174ce9170d5a94bc35650a65f3b1ab0074f73609b0'
DADB_SOURCE_SHA256 = '0d07a026f4bca2f45c1641c2a24014ea7a3271288cf67093a7d940e5c8b94a2f'
DADB_PROVIDER_ROW = (420, 45467, '6325f4bf3aa3c95009fb3fe1e2ee4778b8356784aa478091f04166a57c209982')
FAA0_PROVIDER_ROW = (420, 46107, 'ed51f955279d03bc25bb69db6bdeca148c356364eb7ac7cf9901f8a243324977')
FAA0_MANIFEST_SHA256 = 'fbf1a448f6080fee96d75a4dd8cae97bd0952f280695f68e65f51e694aee8549'
DADB_COMMIT = 'dadb4e89bb28021db50f1c5bb3682a6c81398003'
DADB_PREPARE_RUN = '38218759974'
DADB_APPLY_OPERATION = '9db823ad59c3475c9f80f1e574af16de'
FAA0_SOURCE_SHA256 = 'ed06d35bcae09180e3b6c2fa23fe9c3b6a8cd07db9af4b88b2425bc1aa824de5'
# Exact new source/CI/delta remain absent until separately reviewed.

STAGE = 'input'
OPERATION = 'none'
FAILURE_KINDS = frozenset('ValueError RuntimeError TimeoutError TimeoutExpired CalledProcessError OSError PermissionError FileNotFoundError BlockingIOError JSONDecodeError TypeError KeyError AttributeError AssertionError ImportError ModuleNotFoundError ExportInstallInvalid'.split())
FAILURE_STAGES = frozenset('input incoming code_prepare_preflight code_prepare_runtime_config code_prepare_runtime_postflight code_prepare_postflight code_build_engine code_build_relay code_config_engine code_config_relay code_check_config code_apply_preflight code_stop_isolated code_recreate code_replace_units code_start code_verify code_rollback rollback_preflight rollback_stop rollback_restore rollback_start rollback_verify rollback_failed_stop'.split())
FAILURE_CODES = frozenset('PATCH_NOT_PINNED PATCH_BASELINE PATCH_SCOPE PATCH_STORE PATCH_SCHEMA PATCH_EXPORTS PATCH_CONFIG PATCH_RECEIPT PATCH_PACKAGE PATCH_DEPENDENCY CODE_APPLY_FIELDS CODE_OPERATION_ID CODE_ALREADY_ATTEMPTED CODE_POST_STATE CODE_ONLY_FAILED_ROLLED_BACK CODE_ROLLBACK_FAILED CODE_ROLLBACK_FIELDS CODE_ROLLBACK_OPERATION_ID CODE_ROLLBACK_SOURCE CODE_ROLLBACK_UNIT CODE_ROLLBACK_RECOVERY CODE_ROLLBACK_STARTED CODE_ROLLBACK_ALREADY_ATTEMPTED CODE_ROLLBACK_STATE CODE_POST_ROLLBACK_FAILED HOST_BASELINE OLD_BASELINE OLD_SOURCE_CHANGED OLD_UNIT_CHANGED OLD_UNIT_NOT_ENABLED DEPENDENCY_NOT_ACTIVE TMPFILES_CHANGED ACCOUNT_WRITER_NOT_STOPPED CODE_INFRASTRUCTURE_CHANGED CODE_STORE_CHANGED CODE_SCHEMA_CHANGED CODE_OVERRIDE_CHANGED CODE_SOURCE_PATH CODE_SCOPE_CHANGED CODE_PROBE_SOURCE CODE_ROUTE_STATUS PAGE_NOT_READY REPORT_ASSET_NOT_READY CODE_SERVICE_NOT_ACTIVE CODE_SERVICE_NOT_ENABLED VERIFIED_WRITE_AUTH_NOT_REQUIRED RUNTIME_CONFIG_PROOF RUNTIME_CONFIG_DRIFT EXECUTION_ENABLED RUNTIME_SECRET_CHANGED CONFIG_PRESERVE_PROOF CONFIG_PRESERVE_DRIFT CONFIG_PRESERVE_NOT_APPROVED PREEXISTING_RELEASE SYMLINKED_PARENT SYMLINKED_ENVELOPE_PARENT PLAINTEXT_SIZE OLD_STATE_CHANGED SOURCE_DIRECTORY_CHANGED SOURCE_INVENTORY_CHANGED SOURCE_CONTENT_CHANGED FILE_POLICY FILE_PATH DIRECTORY_POLICY COMMAND_FAILED PREPARED_MANIFEST PREPARED_DIGEST PREPARED_FILE_CHANGED PREPARED_IMAGE PREPARED_IMAGE_CHANGED SOURCE_NOT_READY BOOTSTRAP_REQUEST BOOTSTRAP_NOT_FINISHED'.split())



def valid_row(row):
    return (type(row) is tuple and len(row)==3 and type(row[0]) is int and row[0]==0o644
            and type(row[1]) is int and 0<row[1]<=1024*1024 and type(row[2]) is str
            and re.fullmatch('[0-9a-f]{64}',row[2]) is not None)


def manifest_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def require_target_pins():
    if (type(TARGET_COMMIT) is not str or re.fullmatch('[0-9a-f]{40}',TARGET_COMMIT) is None
        or TARGET_COMMIT in (OLD_COMMIT,HISTORICAL_TARGET,DADB_COMMIT,BASE_PREVIOUS_COMMIT) or type(TARGET_SOURCE_SHA256) is not str
        or re.fullmatch('[0-9a-f]{64}',TARGET_SOURCE_SHA256) is None
        or type(CI_PROOF) is not dict or set(CI_PROOF)!={'source_commit','tooling_head','run_id','receipt_sha256'}
        or CI_PROOF.get('source_commit')!=TARGET_COMMIT
        or type(CI_PROOF.get('tooling_head')) is not str or re.fullmatch('[0-9a-f]{40}',CI_PROOF['tooling_head']) is None
        or type(CI_PROOF.get('run_id')) is not str or re.fullmatch('[0-9]{6,20}',CI_PROOF['run_id']) is None
        or type(CI_PROOF.get('receipt_sha256')) is not str or re.fullmatch('[0-9a-f]{64}',CI_PROOF['receipt_sha256']) is None
        or type(TARGET_DELTA) is not dict or set(TARGET_DELTA)!=CODE_PATHS
        or any(not valid_row(row) for row in TARGET_DELTA.values())):
        raise ValueError('PATCH_NOT_PINNED')
    # receipt_sha256 is the exact canonical-source.json bytes SHA, as in C/P1.


def bind_base(base):
    global BASE,OLD_MANIFEST,TARGET_MANIFEST,OLD_REPORT_ASSETS,REPORT_ASSETS,STORE_SHA256
    require_target_pins();base.require_pins()
    if (base.TARGET_COMMIT!=HISTORICAL_TARGET or base.OLD_COMMIT!=BASE_PREVIOUS_COMMIT
        or base.TARGET_SCHEMA!=21 or base.APPROVED_CONFIG_OPERATION_ID!=APPROVED_CONFIG_OPERATION_ID
        or base.EXPECTED_BASELINE!=EXPECTED_BASELINE):raise ValueError('PATCH_BASELINE')
    if (type(DADB_DELTA) is not dict or set(DADB_DELTA)!={'naver_engine/inspection_store.py','naver_engine/store.py','naver_engine/management_store.py','backend/naver_page/report-ui.js'}
        or any(not valid_row(row) or name not in base.TARGET_MANIFEST or row==base.TARGET_MANIFEST[name] for name,row in DADB_DELTA.items())):
        raise ValueError('PATCH_BASELINE')
    old={**base.TARGET_MANIFEST,**DADB_DELTA}
    if manifest_digest(old)!=DADB_MANIFEST_SHA256 or old['naver_runtime/claude_provider.py']!=DADB_PROVIDER_ROW:
        raise ValueError('PATCH_BASELINE')
    old={**old,'naver_runtime/claude_provider.py':FAA0_PROVIDER_ROW}
    if manifest_digest(old)!=FAA0_MANIFEST_SHA256:raise ValueError('PATCH_BASELINE')
    if (NEW_PATHS!=frozenset({'naver_engine/strategy_validation.py'})
        or CODE_PATHS!=frozenset({'naver_engine/marketing_strategy.py','naver_engine/strategy_validation.py',
            'naver_engine/observation_store.py','naver_engine/observation_views.py','naver_engine/web.py',
            'naver_runtime/observation_binding.py','backend/naver_page/operations-ui.js','backend/naver_page/report-ui.js'})
        or NEW_PATHS & set(old) or CODE_PATHS-NEW_PATHS-set(old)
        or any(TARGET_DELTA[name]==old[name] for name in CODE_PATHS-NEW_PATHS)):
        raise ValueError('PATCH_SCOPE')
    BASE=base;OLD_MANIFEST=old;TARGET_MANIFEST={**old,**TARGET_DELTA}
    OLD_REPORT_ASSETS={route:(old['backend/naver_page/'+route.removeprefix('/naver/')][1],old['backend/naver_page/'+route.removeprefix('/naver/')][2],row[2])
                       for route,row in base.REPORT_ASSETS.items()}
    REPORT_ASSETS={route:(TARGET_MANIFEST['backend/naver_page/'+route.removeprefix('/naver/')][1],
        TARGET_MANIFEST['backend/naver_page/'+route.removeprefix('/naver/')][2],row[2]) for route,row in base.REPORT_ASSETS.items()}
    STORE_SHA256={role:old['naver_engine/store.py'][2] for role in ('old','target')}
    for name in ('ENGINE_COMPOSE_SHA256','CHECK_CONFIG_FIELDS','CONFIG_SWITCHES','ENV_FLAGS_SCRIPT',
                 'OWNER_ACTION_ROUTES','TARGET_ACTION_ROUTES','CLOSED_LINK_ROUTES','SALES_GET_ROUTES'):
        globals()[name]=getattr(base,name)
    require_pins()


def require_pins():
    require_target_pins()
    if BASE is None:return  # Static workflow gate, before payload/host operations.
    expected_old={**BASE.TARGET_MANIFEST,**DADB_DELTA,'naver_runtime/claude_provider.py':FAA0_PROVIDER_ROW}
    expected_paths=frozenset({'naver_engine/marketing_strategy.py','naver_engine/strategy_validation.py',
        'naver_engine/observation_store.py','naver_engine/observation_views.py','naver_engine/web.py',
        'naver_runtime/observation_binding.py','backend/naver_page/operations-ui.js','backend/naver_page/report-ui.js'})
    expected_assets={route:(TARGET_MANIFEST['backend/naver_page/'+route.removeprefix('/naver/')][1],
        TARGET_MANIFEST['backend/naver_page/'+route.removeprefix('/naver/')][2],row[2]) for route,row in BASE.REPORT_ASSETS.items()}
    if (OLD_COMMIT!='faa0df6225aa5fff5c4e4884245a4884c0b5f77a' or OLD_SOURCE_SHA256!=FAA0_SOURCE_SHA256
        or CODE_PATHS!=expected_paths or NEW_PATHS!=frozenset({'naver_engine/strategy_validation.py'})
        or OLD_MANIFEST!=expected_old or manifest_digest(OLD_MANIFEST)!=FAA0_MANIFEST_SHA256
        or TARGET_MANIFEST!={**expected_old,**TARGET_DELTA}
        or set(TARGET_MANIFEST)-set(OLD_MANIFEST)!=NEW_PATHS or set(OLD_MANIFEST)-set(TARGET_MANIFEST)
        or {name for name in OLD_MANIFEST if OLD_MANIFEST[name]!=TARGET_MANIFEST[name]}!=CODE_PATHS-NEW_PATHS
        or REPORT_ASSETS!=expected_assets or manifest_digest(OLD_REPORT_ASSETS)!=DADB_ASSETS_SHA256
        or STORE_SHA256!={role:expected_old['naver_engine/store.py'][2] for role in ('old','target')}):
        raise ValueError('PATCH_SCOPE')


def require_bound_pins():
    require_pins()
    if BASE is None:raise ValueError('PATCH_NOT_PINNED')


def validate_package(package,release):
    require_bound_pins()
    if type(package) is not dict or package.get('operation') != 'code-prepare':raise ValueError('PATCH_PACKAGE')
    release.validate_package(dict(package,operation='upgrade-prepare'))
    if (package.get('source_commit') != TARGET_COMMIT or package.get('source_tar_gz_sha256') != TARGET_SOURCE_SHA256
        or package.get('baseline') != EXPECTED_BASELINE):raise ValueError('PATCH_PACKAGE')
    return package


def historical_success(release,upgrade):
    require_bound_pins()
    path,receipt=upgrade.manifest(release,HISTORICAL_TARGET,started=True)
    body=upgrade.read_file(release.ROOT/'receipts'/('preview-start-'+HISTORICAL_TARGET+'.json'),mode=0o600,maximum=32768)
    started=json.loads(body,object_pairs_hook=release.unique)
    migration=started.get('source_status')
    if (type(migration) is not dict or set(migration)!={'ok','schema','old_schema','old_tables','old_rows','preserved_rows','migration_repeatable','network_calls','randomized_tables','randomized_tables_empty'}
        or migration.get('ok') is not True or type(migration.get('schema')) is not int or migration['schema']!=21
        or type(migration.get('old_schema')) is not int or migration['old_schema']!=11
        or type(migration.get('old_tables')) is not int or migration['old_tables']!=36
        or type(migration.get('old_rows')) is not int or migration['old_rows']!=389163
        or migration.get('preserved_rows') is not True or migration.get('migration_repeatable') is not True
        or migration.get('randomized_tables_empty') is not True
        or migration.get('randomized_tables')!=sorted(BASE.RANDOMIZED_TABLES)
        or type(migration.get('network_calls')) is not int or migration['network_calls']!=0):raise ValueError('PATCH_BASELINE')
    if (receipt.get('package',{}).get('source_tar_gz_sha256') != BASE.TARGET_SOURCE_SHA256
        or receipt['package'].get('run_id') != HISTORICAL_PREPARE_RUN or receipt['package'].get('baseline') != EXPECTED_BASELINE
        or receipt.get('runtime_environment_preserved') is not True or receipt.get('config_operation_id') != APPROVED_CONFIG_OPERATION_ID
        or receipt.get('runtime_flags_verified') is not True or type(receipt.get('inventory_enabled')) is not bool or receipt.get('execution_enabled') is not False
        or started.get('ok') is not True or started.get('stage') != 'internal_ready'
        or started.get('source_commit') != HISTORICAL_TARGET or started.get('previous_commit') != BASE_PREVIOUS_COMMIT
        or started.get('operation_id') != HISTORICAL_APPLY_OPERATION or started.get('database_policy') != 'paired-snapshot'
        or type(started.get('database_schema')) is not int or started.get('database_schema') != 21
        or started.get('database_opened_by_controller') is not True or started.get('database_snapshot_verified') is not True
        or started.get('runtime_flags_verified') is not True
        or started.get('execution_enabled') is not False):raise ValueError('PATCH_BASELINE')
    return path,receipt,body


def dadb_success(release,upgrade):
    require_bound_pins()
    _,historical,historical_started=historical_success(release,upgrade)
    path,receipt=upgrade.manifest(release,DADB_COMMIT,started=True)
    body=upgrade.read_file(release.ROOT/'receipts'/('preview-start-'+DADB_COMMIT+'.json'),mode=0o600,maximum=32768)
    started=json.loads(body,object_pairs_hook=release.unique)
    if (receipt.get('package',{}).get('source_tar_gz_sha256')!=DADB_SOURCE_SHA256
        or receipt['package'].get('run_id')!=DADB_PREPARE_RUN or receipt['package'].get('baseline')!=EXPECTED_BASELINE
        or receipt.get('runtime_environment_preserved') is not True or receipt.get('config_operation_id')!=APPROVED_CONFIG_OPERATION_ID
        or receipt.get('runtime_flags_verified') is not True or type(receipt.get('inventory_enabled')) is not bool
        or receipt.get('execution_enabled') is not False
        or started.get('ok') is not True or started.get('stage')!='internal_ready'
        or started.get('source_commit')!=DADB_COMMIT or started.get('previous_commit')!=HISTORICAL_TARGET
        or started.get('operation_id')!=DADB_APPLY_OPERATION or started.get('database_policy')!='preserve-in-place'
        or type(started.get('database_schema')) is not int or started['database_schema']!=21
        or started.get('database_opened_by_controller') is not False or started.get('database_snapshot_verified') is not False
        or started.get('source_warmup_performed') is not False or started.get('rollback_requires_matching_database') is not False
        or started.get('runtime_flags_verified') is not True or started.get('execution_enabled') is not False
        or started.get('saved_export_companion_preserved') is not True):raise ValueError('PATCH_BASELINE')
    secret_paths={str(release.SECRET_ROOT/name) for name in release.SECRET_OWNERS}
    if (type(receipt.get('files')) is not dict or type(historical.get('files')) is not dict
        or any(name not in receipt['files'] or name not in historical['files']
               or receipt['files'][name]!=historical['files'][name] for name in secret_paths)):
        raise ValueError('PATCH_CONFIG')
    return path,receipt,hashlib.sha256(historical_started+b'\0'+body).digest()


def base_success(release,upgrade):
    require_bound_pins()
    _,historical,historical_started=dadb_success(release,upgrade)
    path,receipt=upgrade.manifest(release,OLD_COMMIT,started=True)
    body=upgrade.read_file(release.ROOT/'receipts'/('preview-start-'+OLD_COMMIT+'.json'),mode=0o600,maximum=32768)
    started=json.loads(body,object_pairs_hook=release.unique)
    if (receipt.get('package',{}).get('source_tar_gz_sha256')!=OLD_SOURCE_SHA256
        or receipt['package'].get('run_id')!=BASE_PREPARE_RUN or receipt['package'].get('baseline')!=EXPECTED_BASELINE
        or receipt.get('runtime_environment_preserved') is not True or receipt.get('config_operation_id')!=APPROVED_CONFIG_OPERATION_ID
        or receipt.get('runtime_flags_verified') is not True or type(receipt.get('inventory_enabled')) is not bool
        or receipt.get('execution_enabled') is not False
        or started.get('ok') is not True or started.get('stage')!='internal_ready'
        or started.get('source_commit')!=OLD_COMMIT or started.get('previous_commit')!=DADB_COMMIT
        or started.get('operation_id')!=BASE_APPLY_OPERATION or started.get('database_policy')!='preserve-in-place'
        or type(started.get('database_schema')) is not int or started['database_schema']!=21
        or started.get('database_opened_by_controller') is not False or started.get('database_snapshot_verified') is not False
        or started.get('source_warmup_performed') is not False or started.get('rollback_requires_matching_database') is not False
        or started.get('runtime_flags_verified') is not True or started.get('execution_enabled') is not False
        or started.get('saved_export_companion_preserved') is not True):raise ValueError('PATCH_BASELINE')
    secret_paths={str(release.SECRET_ROOT/name) for name in release.SECRET_OWNERS}
    if (type(receipt.get('files')) is not dict or type(historical.get('files')) is not dict
        or any(name not in receipt['files'] or name not in historical['files']
               or receipt['files'][name]!=historical['files'][name] for name in secret_paths)):
        raise ValueError('PATCH_CONFIG')
    return path,receipt,hashlib.sha256(historical_started+b'\0'+body).digest()


def preserve_approved_config(files,operation_id,active,release,upgrade):
    if operation_id!=APPROVED_CONFIG_OPERATION_ID:raise ValueError('PATCH_CONFIG')
    _,historical=upgrade.manifest(release,BASE.OLD_COMMIT,started=True)
    resolved,proof=BASE.preserve_approved_config(files,operation_id,historical,release,upgrade)
    _,receipt,started_proof=base_success(release,upgrade)
    if receipt!=active:raise ValueError('PATCH_CONFIG')
    current={item['path']:item for item in resolved}
    if set(current)!={str(release.SECRET_ROOT/name) for name in release.SECRET_OWNERS}:raise ValueError('PATCH_CONFIG')
    for filename,item in current.items():
        if receipt['files'].get(filename)!=hashlib.sha256(item['content'].encode()).hexdigest():raise ValueError('PATCH_CONFIG')
    return resolved,(proof,started_proof)


def store_contract(body,role):
    if role not in ('old','target') or hashlib.sha256(body).hexdigest() != STORE_SHA256[role]:raise ValueError('PATCH_STORE')
    tree=ast.parse(body)
    versions=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SCHEMA_VERSION' for t in n.targets)]
    if (len(versions)!=1 or not isinstance(versions[0].value,ast.Constant)
        or type(versions[0].value.value) is not int or versions[0].value.value != 21):raise ValueError('PATCH_SCHEMA')
    return schema_contract(body)


def migration_contract(before,after):
    if store_contract(before,'old') != store_contract(after,'target'):raise ValueError('PATCH_SCHEMA')


def failure_report(error):
    kind=type(error).__name__
    code=error.args[0] if type(error) in (ValueError,RuntimeError) and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in FAILURE_CODES else 'UNRECOGNIZED'
    result={'stage':STAGE if STAGE in FAILURE_STAGES else 'unknown','error_kind':kind if kind in FAILURE_KINDS else 'OtherError','error_code':code}
    details=getattr(error,'failure_details',{})
    if type(details) is dict:
        for prefix in ('failed','rollback'):
            stage=details.get(prefix+'_stage');operation=details.get(prefix+'_operation');error_kind=details.get(prefix+'_error_kind');error_code=details.get(prefix+'_error_code')
            if type(stage) is str and stage in FAILURE_STAGES:result[prefix+'_stage']=stage
            if type(operation) is str and operation in FAILURE_OPERATIONS:result[prefix+'_operation']=operation
            if type(error_kind) is str and error_kind in FAILURE_KINDS:result[prefix+'_error_kind']=error_kind
            if type(error_code) is str and error_code in FAILURE_CODES:result[prefix+'_error_code']=error_code
        if type(details.get('isolated_stop_verified')) is bool:result['isolated_stop_verified']=details['isolated_stop_verified']
    return result


def _capture_failure(error,prefix='failed'):
    report=failure_report(error)
    result={prefix+'_stage':report['stage'],prefix+'_error_kind':report['error_kind'],prefix+'_error_code':report['error_code']}
    if OPERATION in FAILURE_OPERATIONS:result[prefix+'_operation']=OPERATION
    return result

FAILURE_OPERATIONS=frozenset('none package current_state target_manifest compatible_source unit_manifest write_recovery_receipt bootstrap_check daemon_reload verify_running post_state write_started_receipt rollback_state old_manifest unchanged stop_isolated'.split()) | frozenset(prefix+'_'+name for prefix in ('stop','stop_check','recreate','replace_unit','start','restore_unit','replace') for name in ('engine','relay'))


def safe_source_path(name):
    return (type(name) is str and 0 < len(name) <= 300 and not name.startswith('/')
        and all(part not in ('','..','.') for part in name.split('/'))
        and name not in ('HANDOVER.md',) and not any(part in ('store 2.py','.git','tests','__pycache__') for part in name.split('/'))
        and not name.endswith(('.env','.pyc','.pem','.key')) and '.env.' not in name
        and (name.startswith(('naver_engine/','naver_runtime/','backend/app/naver_auto/','backend/naver_page/','deploy/'))
             or name in {'backend/requirements.txt','backend/app/__init__.py','backend/app/naver_relay.py',
                 'backend/app/routers/__init__.py','backend/app/routers/naver.py','backend/app/naver_entry.py',
                 '.dockerignore','Dockerfile.naver-engine','Dockerfile.naver-engine.dockerignore',
                 'Dockerfile.naver-relay','Dockerfile.naver-relay.dockerignore','compose.naver-engine.yml','compose.naver-relay.yml'}))


def bootstrap_state(release, upgrade):
    request = upgrade.REQUEST
    if not os.path.lexists(request):
        return None
    release.trusted_dir(request.parent, uid=10001, gid=10001, mode=0o750)
    raw = upgrade.read_file(request, uid=0, gid=10001, mode=0o440, maximum=4096)
    data = json.loads(raw, object_pairs_hook=release.unique)
    identity = data.get('request_id')
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('BOOTSTRAP_REQUEST')
    folder = request.parent/'bootstrap'
    release.trusted_dir(folder, uid=10001, gid=10001, mode=0o700)
    snapshot = {'request': raw}
    for suffix in ('.json', '.result.json'):
        body = upgrade.read_file(folder/('bootstrap-'+identity+suffix), uid=10001, gid=10001,
        mode=0o600, maximum=32768)
        value = json.loads(body, object_pairs_hook=release.unique)
        if value.get('request_id') != identity or value.get('status') not in (
        ('started',) if suffix == '.json' else ('completed', 'partial', 'failed_partial')):
            raise ValueError('BOOTSTRAP_NOT_FINISHED')
        snapshot[suffix] = body
    return snapshot


def current_state(package, host, release, lifecycle, upgrade):
    if os.geteuid() != 0 or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')
    path, receipt, _ = base_success(release, upgrade)
    if receipt['package'].get('baseline') != package['baseline']:
        raise ValueError('OLD_BASELINE')
    if receipt['package'].get('source_tar_gz_sha256') != OLD_SOURCE_SHA256:
        raise ValueError('OLD_SOURCE_CHANGED')
    files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    for parent in (lifecycle.UNIT_DIR, lifecycle.TMPFILES.parent):
        release.trusted_dir(parent)
    for filename, body in files.items():
        if upgrade.read_file(filename, mode=0o644, maximum=32768) != body:
            raise ValueError('OLD_UNIT_CHANGED')
    for unit in ('docker.service', lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('DEPENDENCY_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('OLD_UNIT_NOT_ENABLED')
    return path, receipt, files, lifecycle._snapshot(release, path, receipt['images']), bootstrap_state(release, upgrade)


def schema_contract(body):
    tree = ast.parse(body)
    selected = {}
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign):
            for target in node.targets:
                if isinstance(target,ast.Name) and target.id in ('SCHEMA_VERSION','_SCHEMA','_REVISION_COLUMNS'):
                    selected[target.id]=selected.get(target.id,'')+ast.dump(node,include_attributes=False)
        elif isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='_SCHEMA':
            selected['_SCHEMA']=selected.get('_SCHEMA','')+ast.dump(node,include_attributes=False)
        elif isinstance(node,ast.FunctionDef) and node.name=='_migrate':
            selected[node.name]=ast.dump(node,include_attributes=False)
    if set(selected)!={'SCHEMA_VERSION','_SCHEMA','_REVISION_COLUMNS','_migrate'}:
        raise ValueError('SCHEMA_CONTRACT_MISSING')
    return selected


def compatible_engine_compose(before, after):
    if (type(before) is not bytes or type(after) is not bytes
            or before != after
            or hashlib.sha256(before).hexdigest() != ENGINE_COMPOSE_SHA256):
        raise ValueError('CODE_INFRASTRUCTURE_CHANGED')


def compatible_source(old, new, upgrade):
    read = lambda path: upgrade.read_file(path, mode=0o644, maximum=1024*1024, minimum=0)
    compatible_engine_compose(read(old/'compose.naver-engine.yml'), read(new/'compose.naver-engine.yml'))
    for name in ('compose.naver-relay.yml',
        'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
        'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py'):
        if read(old/name) != read(new/name):
            raise ValueError('CODE_INFRASTRUCTURE_CHANGED')
    before, after = read(old/'naver_engine/store.py'), read(new/'naver_engine/store.py')
    migration_contract(before, after)
    for name in ('engine', 'relay'):
        before = upgrade.read_file(old/('preview-'+name+'.override.yml'), mode=0o600)
        after = upgrade.read_file(new/('preview-'+name+'.override.yml'), mode=0o600)
        if after != target_override(before, name):
            raise ValueError('CODE_OVERRIDE_CHANGED')
    compatible_code_scope(old, new, upgrade)


def target_override(before, name):
    return before.replace(OLD_COMMIT.encode(), TARGET_COMMIT.encode())


def stopped_writer(release, lifecycle, path, images, unit):
    if (unit not in lifecycle.UNITS or path.name not in ('naver-'+OLD_COMMIT,'naver-'+TARGET_COMMIT)
        or not isinstance(images,dict) or not images or set(images)-{OLD_COMMIT,TARGET_COMMIT}):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    name='engine' if unit==lifecycle.UNITS[0] else 'relay'
    allowed={source:value.get(name) for source,value in images.items() if isinstance(value,dict)}
    if len(allowed)!=len(images) or any(not isinstance(v,str) or not re.fullmatch('sha256:[0-9a-f]{64}',v)
        for v in allowed.values()):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    if (lifecycle._state(release,unit,'ActiveState') not in ('inactive','failed')
        or lifecycle._state(release,unit,'SubState') not in ('dead','failed')
        or lifecycle._state(release,unit,'MainPID')!='0'):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    ids=release.command(['docker','ps','--all','--no-trunc','--filter',
        'label=com.docker.compose.project=naver-'+name,'--format','{{.ID}}']).decode().strip().splitlines()
    if len(ids)>1 or any(not re.fullmatch('[0-9a-f]{64}',identity) for identity in ids):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    if not ids:
        return
    fields={'id':'.Id','image':'.Image','running':'.State.Running','restarting':'.State.Restarting','pid':'.State.Pid',
        'source':'(index .Config.Labels "metainc.naver.preview.source")',
        'project':'(index .Config.Labels "com.docker.compose.project")',
        'service':'(index .Config.Labels "com.docker.compose.service")'}
    fmt='{'+','.join(json.dumps(k)+':{{json '+v+'}}' for k,v in fields.items())+'}'
    row=json.loads(release.command(['docker','inspect','--format',fmt,ids[0]]))
    if (not isinstance(row,dict) or not isinstance(row.get('source'),str) or row['source'] not in allowed
        or row.get('id')!=ids[0] or row.get('image')!=allowed[row['source']]
        or row.get('project')!='naver-'+name or row.get('service')!='naver-'+name
        or row.get('running') is not False or row.get('restarting') is not False
        or type(row.get('pid')) is not int or row['pid']!=0):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')


def compatible_code_scope(old, new, upgrade, *, inverse=False):
    require_pins()
    def inventory(root, wanted):
        actual={}
        for path in root.rglob('*'):
            if path.is_symlink() or path.resolve()!=path: raise ValueError('CODE_SOURCE_PATH')
            if path.is_dir(): continue
            name=path.relative_to(root).as_posix()
            if name in ('preview-engine.override.yml','preview-relay.override.yml'): continue
            # Check path before reading or hashing any forbidden object.
            if not safe_source_path(name) or name not in wanted: raise ValueError('CODE_SCOPE_CHANGED')
            mode=stat.S_IMODE(path.stat().st_mode)
            body=upgrade.read_file(path,mode=mode,maximum=1024*1024,minimum=0)
            actual[name]=(mode,len(body),hashlib.sha256(body).hexdigest())
        if actual!=wanted: raise ValueError('CODE_SCOPE_CHANGED')
    inventory(old, TARGET_MANIFEST if inverse else OLD_MANIFEST)
    inventory(new, OLD_MANIFEST if inverse else TARGET_MANIFEST)


def compatible_inverse_source(target, old, upgrade):
    compatible_source(old,target,upgrade)
    compatible_code_scope(target,old,upgrade,inverse=True)


def probe(release, source_commit, upgrade):
    management_target = source_commit in (OLD_COMMIT, TARGET_COMMIT)
    old_source = source_commit == OLD_COMMIT
    if (not isinstance(TARGET_COMMIT, str) or not re.fullmatch('[0-9a-f]{40}', TARGET_COMMIT)
        or source_commit not in (OLD_COMMIT, TARGET_COMMIT)):
        raise ValueError('CODE_PROBE_SOURCE')
    def request(path, route, method='GET'):
        status, headers, body = release.unix_request(path, route, method)
        key = route.removeprefix('/api/naver-auto')
        opened = key in OWNER_ACTION_ROUTES or key in TARGET_ACTION_ROUTES
        if method == 'POST' and (route == '/api/naver-auto/links/confirm' or opened):
            if status != 401:
                raise ValueError('VERIFIED_WRITE_AUTH_NOT_REQUIRED')
            return 403, headers, body
        return status, headers, body
    upgrade.probe(SimpleNamespace(unix_request=request))
    relay = '/run/metainc/naver-relay/relay.sock'
    if release.unix_request(relay, '/api/naver-auto/dashboard', 'GET')[0] != 401:
        raise ValueError('CODE_ROUTE_STATUS')
    status, headers, body = release.unix_request(relay, '/naver/dashboard', 'GET')
    headers = {key.lower():value for key,value in headers.items()}
    if (status != 200 or b'id="s-dashboard"' not in body or headers.get('referrer-policy') != 'no-referrer'
            or headers.get('cache-control') != 'no-store'):
        raise ValueError('PAGE_NOT_READY')
    if management_target:
        for route, method in (('/reports', 'GET'),
        ('/reports/history?possibility_id=1&limit=20', 'GET'),
        ('/accounts/reasons?ad_account_no=1&page=0&selection=all', 'GET'),
        ('/management/update', 'POST'),
        ('/management/collect', 'POST'), ('/reports/review', 'POST')):
            if release.unix_request(relay, '/api/naver-auto'+route, method)[0] != 401:
                raise ValueError('CODE_ROUTE_STATUS')
    if release.unix_request(relay, '/api/naver-auto/reports/strategy/jobs?job_id=' + '0' * 32, 'GET')[0] != 401:
        raise ValueError('CODE_ROUTE_STATUS')
    for route, method, expected in (
            ('/collection/status', 'GET', 401), ('/collection/request', 'POST', 401),
            *((r, 'POST', 401) for r in OWNER_ACTION_ROUTES),
            *((r, 'POST', 401) for r in TARGET_ACTION_ROUTES),
            *((r, 'POST', 403) for r in CLOSED_LINK_ROUTES)):
        if release.unix_request(relay, '/api/naver-auto' + route, method)[0] != expected:
            raise ValueError('CODE_ROUTE_STATUS')
    if management_target:
        for route in ('/reports/accounts?selection=all&kind=weekly&page=0',
                      '/reports/detail?report_id=1&account_key=company'):
            if release.unix_request(relay, '/api/naver-auto'+route, 'GET')[0] != 401:
                raise ValueError('CODE_ROUTE_STATUS')
        assets = dict(OLD_REPORT_ASSETS if old_source else REPORT_ASSETS)
        account_query='?possibility_id=1&account_key='+'0'*64
        new_reads=('/experiments'+account_query,'/experiments/randomized'+account_query,'/execution'+account_query,
            '/automation/learning/source'+account_query+'&asset_id=auto-exec-'+'0'*32,
            '/reports/schedule'+account_query,'/operations'+account_query)
        for route in SALES_GET_ROUTES + new_reads:
            if release.unix_request(relay, '/api/naver-auto'+route, 'GET')[0] != 401:
                raise ValueError('CODE_ROUTE_STATUS')
        if management_target:
            for route in ('/experiments','/experiments/randomized','/execution','/automation/learning/source','/reports/schedule'):
                if release.unix_request(relay,'/api/naver-auto'+route,'POST')[0]!=401:
                    raise ValueError('CODE_ROUTE_STATUS')
        if release.unix_request(relay, '/api/naver-auto/automation?possibility_id=1&account_key=customer-1', 'GET')[0] != 401:
            raise ValueError('CODE_ROUTE_STATUS')
        for route,(size,digest,mime) in assets.items():
            status,headers,body = release.unix_request(relay, route, 'GET')
            headers = {key.lower():value for key,value in headers.items()}
            if (status != 200 or len(body) != size or hashlib.sha256(body).hexdigest() != digest
                    or headers.get('content-type') != mime or headers.get('cache-control') != 'no-store'
                    or headers.get('x-content-type-options') != 'nosniff'
                    or headers.get('referrer-policy') != 'no-referrer' or headers.get('content-encoding')):
                raise ValueError('REPORT_ASSET_NOT_READY')


def runtime_flags(raw, *, environment=False):
    """Accept only a bounded, closed boolean proof; never return raw config."""
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('RUNTIME_CONFIG_PROOF')
            value[key] = item
        return value
    def invalid_constant(_):
        raise ValueError('RUNTIME_CONFIG_PROOF')
    if type(raw) is not bytes or not 1 <= len(raw) <= 4096:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('RUNTIME_CONFIG_PROOF') from None
    if environment:
        if (type(value) is not dict or set(value) != {'inventory_enabled', 'execution_enabled'}
                or any(type(v) is not bool for v in value.values())):
            raise ValueError('RUNTIME_CONFIG_PROOF')
        result = value
    else:
        if (type(value) is not dict or set(value) != CHECK_CONFIG_FIELDS
                or value['command'] != 'check-config' or value['configuration'] != 'valid'
                or any(value[k] is not False for k in CHECK_CONFIG_FIELDS-{'command','configuration','switches'})
                or type(value['switches']) is not dict or set(value['switches']) != CONFIG_SWITCHES
                or any(type(v) is not bool for v in value['switches'].values())):
            raise ValueError('RUNTIME_CONFIG_PROOF')
        result = {'inventory_enabled':value['switches']['inventory'], 'execution_enabled':value['switches']['execution']}
    if result['execution_enabled'] is not False:
        raise ValueError('EXECUTION_ENABLED')
    return dict(result)


def target_runtime_flags(path, release, identity, *, override=None):
    """Same target compose/env, with networking disabled and no runtime startup."""
    check = release.compose(path, 'engine')
    check[check.index('--project-name')+1] = 'naver-check-'+TARGET_COMMIT+'-'+uuid.uuid4().hex
    created = override is None
    if created:
        override = release.ROOT/'receipts'/('completion-config-'+identity+'-'+uuid.uuid4().hex+'.override.yml')
        release.write_new(override, b'services:\n  naver-engine:\n    network_mode: none\n')
    try:
        raw = release.command(check+['-f',str(override),'run','--rm','--no-deps','--pull','never',
            'naver-engine','python','-B','-m','naver_runtime','check-config'], timeout=60)
        return runtime_flags(raw)
    finally:
        if created:
            override.unlink()


def container_environment_flags(raw):
    """Reduce private immutable Docker Env in memory to the two safe flags only."""
    if type(raw) is not bytes or not 1 <= len(raw) <= 65536:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    try:
        values = json.loads(raw)
        if type(values) is not list or len(values) > 256:
            raise ValueError('RUNTIME_CONFIG_PROOF')
        selected = {}
        names = {'NAVER_ENGINE_INVENTORY_ENABLED':'inventory_enabled',
            'NAVER_ENGINE_EXECUTION_ENABLED':'execution_enabled'}
        for item in values:
            if type(item) is not str or '\x00' in item:
                raise ValueError('RUNTIME_CONFIG_PROOF')
            name, separator, value = item.partition('=')
            if name not in names:
                continue
            if not separator or name in selected:
                raise ValueError('RUNTIME_CONFIG_PROOF')
            lowered = value.strip().lower()
            if lowered not in ('false','off','0','','true','on','1'):
                raise ValueError('RUNTIME_CONFIG_PROOF')
            selected[name] = lowered in ('true','on','1')
        flags = {public:selected.get(name,False) for name,public in names.items()}
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('RUNTIME_CONFIG_PROOF') from None
    return runtime_flags(json.dumps(flags,separators=(',',':')).encode(),environment=True)


def target_engine_snapshot(path, receipt, release, lifecycle, *, stopped):
    """Bound one actual target container without inspecting or returning secrets."""
    source=receipt.get('source_commit')
    if (source not in (OLD_COMMIT,TARGET_COMMIT) or path.name != 'naver-'+source
            or not isinstance(receipt.get('images'),dict)
            or not isinstance(receipt['images'].get('engine'),str)
            or re.fullmatch('sha256:[0-9a-f]{64}',receipt['images']['engine']) is None):
        raise ValueError('RUNTIME_CONFIG_PROOF')
    if stopped and (lifecycle._state(release,lifecycle.UNITS[0],'ActiveState') not in ('inactive','failed')
            or lifecycle._state(release,lifecycle.UNITS[0],'SubState') not in ('dead','failed')
            or lifecycle._state(release,lifecycle.UNITS[0],'MainPID') != '0'):
        raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
    raw = release.command(release.compose(path,'engine')+['ps','--all','--quiet'],timeout=30)
    if type(raw) is not bytes or len(raw) > 256:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    try:
        identities = raw.decode('ascii').strip().splitlines()
    except UnicodeError:
        raise ValueError('RUNTIME_CONFIG_PROOF') from None
    if len(identities) != 1 or re.fullmatch('[0-9a-f]{64}',identities[0]) is None:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    fields = {'id':'.Id','image':'.Image','running':'.State.Running',
        'restarting':'.State.Restarting','pid':'.State.Pid',
        'source':'(index .Config.Labels "metainc.naver.preview.source")',
        'project':'(index .Config.Labels "com.docker.compose.project")',
        'service':'(index .Config.Labels "com.docker.compose.service")'}
    fmt = '{'+','.join(json.dumps(k)+':{{json '+v+'}}' for k,v in fields.items())+'}'
    raw = release.command(['docker','inspect','--format',fmt,identities[0]],timeout=30)
    if type(raw) is not bytes or not 1 <= len(raw) <= 4096:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    try:
        row = json.loads(raw)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError('RUNTIME_CONFIG_PROOF') from None
    if (type(row) is not dict or set(row) != set(fields) or row['id'] != identities[0]
            or row['image'] != receipt['images']['engine'] or row['source'] != source
            or row['project'] != 'naver-engine' or row['service'] != 'naver-engine'
            or row['running'] is not (not stopped) or row['restarting'] is not False
            or type(row['pid']) is not int or (row['pid'] != 0 if stopped else row['pid'] <= 0)):
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    return row


def stopped_container_runtime_flags(path, receipt, release, lifecycle):
    before = target_engine_snapshot(path,receipt,release,lifecycle,stopped=True)
    # Docker Env may contain secrets. It stays transient server memory: never hash,
    # log, persist, or include it in any receipt or returned proof.
    flags = container_environment_flags(release.command(
        ['docker','inspect','--format','{{json .Config.Env}}',before['id']],timeout=30))
    if target_engine_snapshot(path,receipt,release,lifecycle,stopped=True) != before:
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    return flags,before


def container_runtime_flags(path, receipt, release, lifecycle, *, target=False, expected=None):
    """Inspect only the already-verified exact engine container's safe flags."""
    before = lifecycle._snapshot(release, path, receipt['images'])
    identity = before.get('engine',{}).get('id')
    if not isinstance(identity,str) or re.fullmatch('[0-9a-f]{64}',identity) is None:
        raise ValueError('RUNTIME_CONFIG_PROOF')
    if expected is not None:
        actual = target_engine_snapshot(path,receipt,release,lifecycle,stopped=False)
        identity_fields = ('id','image','source','project','service')
        if (not target or actual['id'] != identity or type(expected) is not dict
                or any(actual[key] != expected.get(key) for key in identity_fields)):
            raise ValueError('RUNTIME_CONFIG_DRIFT')
    command = (['python','-B','-m','naver_runtime','check-config'] if target else
        ['python','-I','-B','-c',ENV_FLAGS_SCRIPT])
    flags = runtime_flags(release.command(['docker','exec',identity]+command, timeout=60), environment=not target)
    if lifecycle._snapshot(release, path, receipt['images']) != before:
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    if expected is not None and target_engine_snapshot(path,receipt,release,lifecycle,stopped=False) != actual:
        raise ValueError('RUNTIME_CONFIG_DRIFT')
    return flags


def prepare(package, host, release, lifecycle, upgrade, *, approved_config_operation_id=None):
    global STAGE
    STAGE = 'code_prepare_preflight'
    validate_package(package, release)
    if approved_config_operation_id != APPROVED_CONFIG_OPERATION_ID: raise ValueError('CONFIG_PRESERVE_NOT_APPROVED')
    old = current_state(package, host, release, lifecycle, upgrade)
    destination = release.ROOT/'releases'/('naver-'+TARGET_COMMIT)
    receipt_path = release.ROOT/'receipts'/('preview-'+TARGET_COMMIT+'.json')
    if os.path.lexists(receipt_path):
        raise ValueError('PREEXISTING_RELEASE')
    for folder in (release.ROOT, release.ROOT/'incoming', release.ROOT/'releases', release.ROOT/'receipts',
                   release.ROOT/'incoming'/package['run_id']):
        if folder.resolve() != folder:
            raise ValueError('SYMLINKED_PARENT')
        release.trusted_dir(folder, mode=0o700)
    ciphertext = release.received_ciphertext(release.ROOT/'incoming'/package['run_id']/'runtime-secrets.cms', package['ciphertext_sha256'])
    key = upgrade.ENVELOPE_KEY
    if key.parent.resolve() != key.parent:
        raise ValueError('SYMLINKED_ENVELOPE_PARENT')
    release.trusted_dir(key.parent, mode=0o700)
    release.trusted_private_file(key)
    plain = release.command(['openssl','cms','-decrypt','-binary','-inform','DER','-inkey',str(key)], data=ciphertext)
    if len(plain) > 4*1024*1024:
        raise ValueError('PLAINTEXT_SIZE')
    source, files = release.decode_payload(plain, TARGET_COMMIT, package['source_tar_gz_sha256'])
    release.source_members(source)[0].close()
    original_files = files
    config_proof = None
    if approved_config_operation_id is not None:
        STAGE = 'code_prepare_runtime_config'
        files, config_proof = preserve_approved_config(files, approved_config_operation_id, old[1], release, upgrade)
    for item in files:
        if upgrade.read_file(item['path'], uid=item['uid'], gid=item['gid'], mode=0o600) != item['content'].encode():
            raise ValueError('RUNTIME_SECRET_CHANGED')
    overrides = {name: target_override(upgrade.read_file(old[0]/('preview-'+name+'.override.yml'), mode=0o600), name).decode()
                 for name in ('engine', 'relay')}
    if os.path.lexists(destination):
        upgrade.verify_interrupted_source(source, destination, overrides, release)
    else:
        release.extract_source(source, destination)
        for name, body in overrides.items():
            release.write_new(destination/('preview-'+name+'.override.yml'), body.encode())
    compatible_source(old[0], destination, upgrade)
    for name in ('engine', 'relay'):
        STAGE = 'code_build_'+name
        release.command(['docker','build','--label','metainc.naver.preview.source='+TARGET_COMMIT,
                         '-t','metainc/naver-'+name+':'+TARGET_COMMIT,'-f',str(destination/('Dockerfile.naver-'+name)),str(destination)], timeout=600)
        STAGE = 'code_config_'+name
        release.command(release.compose(destination, name)+['config','--quiet'])
    STAGE = 'code_check_config'
    check_override = release.ROOT/'incoming'/package['run_id']/'check-config.override.yml'
    release.write_new(check_override, b'services:\n  naver-engine:\n    network_mode: none\n')
    flags = target_runtime_flags(destination, release, package['run_id'], override=check_override)
    STAGE = 'code_prepare_postflight'
    if current_state(package, host, release, lifecycle, upgrade) != old:
        raise ValueError('OLD_STATE_CHANGED')
    if config_proof is not None:
        STAGE = 'code_prepare_runtime_postflight'
        current_files, current_proof = preserve_approved_config(original_files, approved_config_operation_id, old[1], release, upgrade)
        if current_files != files or current_proof != config_proof:
            raise ValueError('CONFIG_PRESERVE_DRIFT')
        for item in files:
            if upgrade.read_file(item['path'], uid=item['uid'], gid=item['gid'], mode=0o600) != item['content'].encode():
                raise ValueError('RUNTIME_SECRET_CHANGED')
    images = {name: json.loads(release.command(['docker','image','inspect','--format','{{json .Id}}','metainc/naver-'+name+':'+TARGET_COMMIT])) for name in ('engine','relay')}
    paths = {str(destination/'deploy/naver-engine-backup.override.yml')}
    paths.update(str(destination/(prefix+name+suffix)) for name in ('engine','relay')
                 for prefix, suffix in (('compose.naver-', '.yml'), ('preview-', '.override.yml')))
    paths.update(item['path'] for item in files)
    receipt = {'ok':True, 'stage':'prepared', 'source_commit':TARGET_COMMIT,
               'package':{k:v for k,v in package.items() if k!='operation'}, 'images':images,
               'files':{path:release.sha(Path(path).read_bytes()) for path in sorted(paths)}}
    receipt.update(flags, runtime_flags_verified=True)
    if config_proof is not None:
        receipt.update(runtime_environment_preserved=True, config_operation_id=approved_config_operation_id)
    release.write_new(receipt_path, json.dumps(receipt, sort_keys=True).encode())
    upgrade.manifest(release, TARGET_COMMIT, package)
    release.verify_exports()
    result = {'ok':True,'stage':'prepared','source_commit':TARGET_COMMIT,'previous_commit':OLD_COMMIT,
              'services_started':False,'nginx_changed':False,'bootstrap_unchanged':True}
    result.update(flags, runtime_flags_verified=True)
    if config_proof is not None:
        result.update(runtime_environment_preserved=True, config_operation_id=approved_config_operation_id)
    return dict(result,database_policy='preserve-in-place',database_opened_by_controller=False,saved_export_companion_preserved=True)


def apply(package, host, release, lifecycle, upgrade):
    global STAGE, OPERATION
    STAGE, OPERATION = 'code_apply_preflight', 'package'
    require_pins()
    if not isinstance(package, dict) or set(package) != {'release', 'operation_id'}:
        raise ValueError('CODE_APPLY_FIELDS')
    identity = package['operation_id']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('CODE_OPERATION_ID')
    prepared = validate_package(package['release'], release)
    OPERATION = 'current_state'
    old_path, old_receipt, old_files, _, bootstrap = current_state(prepared, host, release, lifecycle, upgrade)
    baseline_proof = base_success(release, upgrade)
    OPERATION = 'target_manifest'
    path, receipt = upgrade.manifest(release, TARGET_COMMIT, prepared)
    OPERATION = 'compatible_source'
    compatible_source(old_path, path, upgrade)
    old_flags=container_runtime_flags(old_path,old_receipt,release,lifecycle)
    if old_flags != {'inventory_enabled':old_receipt['inventory_enabled'],'execution_enabled':False}:raise ValueError('RUNTIME_CONFIG_DRIFT')
    OPERATION = 'unit_manifest'
    new_files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    if new_files[lifecycle.TMPFILES] != old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    started = release.ROOT/'receipts'/('preview-start-'+TARGET_COMMIT+'.json')
    recovery = release.ROOT/'receipts'/('code-upgrade-'+identity+'.json')
    if any(os.path.lexists(p) for p in (started, recovery)):
        raise ValueError('CODE_ALREADY_ATTEMPTED')
    OPERATION = 'write_recovery_receipt'
    release.write_new(recovery, json.dumps({
        'source_commit':OLD_COMMIT, 'target_commit':TARGET_COMMIT,
        'database_policy':'preserve-in-place', 'images':old_receipt['images'],
        'units':{str(p):b.decode() for p,b in old_files.items() if p != lifecycle.TMPFILES}},
        sort_keys=True).encode())
    replaced = []

    def unchanged_state():
        require_pins()
        if (host.baseline() != prepared['baseline'] or bootstrap_state(release, upgrade) != bootstrap
            or base_success(release,upgrade) != baseline_proof):
            raise ValueError('CODE_POST_STATE')
        release.verify_exports()

    def name(unit):
        return 'engine' if unit == lifecycle.UNITS[0] else 'relay'

    try:
        STAGE = 'code_stop_isolated'
        for unit in reversed(lifecycle.UNITS):
            OPERATION = 'stop_'+name(unit)
            release.command(['/usr/bin/systemctl', 'stop', unit], timeout=90)
            OPERATION = 'stop_check_'+name(unit)
            stopped_writer(release, lifecycle, old_path, {OLD_COMMIT:old_receipt['images']}, unit)
        OPERATION = 'bootstrap_check'
        unchanged_state()
        STAGE = 'code_recreate'
        for service in ('engine', 'relay'):
            OPERATION = 'recreate_'+service
            release.command(release.compose(path, service)+['up', '--no-start', '--no-build', '--force-recreate'], timeout=90)
        new_flags,frozen=stopped_container_runtime_flags(path,receipt,release,lifecycle)
        if new_flags != old_flags:raise ValueError('RUNTIME_CONFIG_DRIFT')
        STAGE = 'code_replace_units'
        for unit in lifecycle.UNITS:
            OPERATION = 'replace_unit_'+name(unit)
            target = lifecycle.UNIT_DIR/unit
            replaced.append(target)
            upgrade.replace_unit(target, old_files[target], new_files[target], identity, release)
        OPERATION = 'daemon_reload'
        release.command(['/usr/bin/systemctl', 'daemon-reload'])
        STAGE = 'code_start'
        for unit in lifecycle.UNITS:
            OPERATION = 'start_'+name(unit)
            release.command(['/usr/bin/systemctl', 'start', unit], timeout=90)
        STAGE, OPERATION = 'code_verify', 'verify_running'
        verify_running(path, receipt, release, lifecycle, upgrade, expected=frozen)
        OPERATION = 'post_state'
        unchanged_state()
        result = dict(database_schema=21,execution_enabled=False,runtime_flags_verified=True,saved_export_companion_preserved=True,ok=True, stage='internal_ready', source_commit=TARGET_COMMIT,
                      previous_commit=OLD_COMMIT, operation_id=identity, nginx_changed=False,
                      legacy_containers_unchanged=True, bootstrap_unchanged=True,
                      unauthenticated_read_status=401, business_post_status=403,
                      database_policy='preserve-in-place', database_opened_by_controller=False,
                      database_snapshot_verified=False, source_warmup_performed=False,
                      rollback_requires_matching_database=False, collection_completion_verified=False)
        OPERATION = 'write_started_receipt'
        release.write_new(started, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception as error:
        details = _capture_failure(error)
        STAGE = 'code_rollback'
        failed = False

        def attempt(function, *args, **kwargs):
            nonlocal failed
            try:
                function(*args, **kwargs)
                return True
            except Exception as rollback_error:
                if 'rollback_stage' not in details:
                    details.update(_capture_failure(rollback_error, 'rollback'))
                failed = True
                return False

        def restore_unit(target):
            if upgrade.read_file(target, mode=0o644, maximum=32768) != old_files[target]:
                upgrade.replace_unit(target, new_files[target], old_files[target], identity+'-rollback', release)

        for unit in reversed(lifecycle.UNITS):
            OPERATION = 'stop_'+name(unit)
            attempt(release.command, ['/usr/bin/systemctl', 'stop', unit], timeout=90)
        for unit in lifecycle.UNITS:
            OPERATION = 'stop_check_'+name(unit)
            attempt(stopped_writer, release, lifecycle, old_path,
                    {OLD_COMMIT:old_receipt['images'], TARGET_COMMIT:receipt['images']}, unit)
        if not failed:
            OPERATION = 'rollback_state'
            attempt(unchanged_state)
        if not failed:
            OPERATION = 'compatible_source'
            attempt(compatible_source, old_path, path, upgrade)
        if not failed:
            OPERATION = 'old_manifest'
            attempt(upgrade.manifest, release, OLD_COMMIT, started=True)
        if not failed:
            for target in reversed(replaced):
                OPERATION = 'restore_unit_'+name(target.name)
                if not attempt(restore_unit, target):
                    break
        if not failed:
            for service in ('engine', 'relay'):
                OPERATION = 'recreate_'+service
                if not attempt(release.command, release.compose(old_path, service)+
                               ['up', '--no-start', '--no-build', '--force-recreate'], timeout=90):
                    break
        if not failed:
            try:
                rollback_flags,rollback_frozen=stopped_container_runtime_flags(old_path,old_receipt,release,lifecycle)
                if rollback_flags != old_flags:raise ValueError('RUNTIME_CONFIG_DRIFT')
            except Exception as rollback_error:
                details.update(_capture_failure(rollback_error,'rollback'));failed=True
        if not failed:
            OPERATION = 'daemon_reload'
            attempt(release.command, ['/usr/bin/systemctl', 'daemon-reload'])
        if not failed:
            for unit in lifecycle.UNITS:
                OPERATION = 'start_'+name(unit)
                if not attempt(release.command, ['/usr/bin/systemctl', 'start', unit], timeout=90):
                    break
            if not failed:
                OPERATION = 'verify_running'
                attempt(verify_running, old_path, old_receipt, release, lifecycle, upgrade, expected=rollback_frozen)
        OPERATION = 'rollback_state'
        attempt(unchanged_state)
        if failed:
            for unit in reversed(lifecycle.UNITS):
                OPERATION = 'stop_'+name(unit)
                attempt(release.command, ['/usr/bin/systemctl', 'stop', unit], timeout=90)
        refused = RuntimeError('CODE_ROLLBACK_FAILED' if failed else 'CODE_ONLY_FAILED_ROLLED_BACK')
        refused.failure_details = details
        raise refused from None


def verify_running(path, receipt, release, lifecycle, upgrade, *, expected=None, probe_http=True):
    # Only exact HTTP/container/config/export proofs; no DB reader or warmup.
    source = receipt.get('source_commit')
    if source not in (OLD_COMMIT, TARGET_COMMIT) or path.name != 'naver-'+source:
        raise ValueError('CODE_PROBE_SOURCE')
    if probe_http:probe(release, source, upgrade)
    lifecycle._snapshot(release, path, receipt['images'])
    flags=container_runtime_flags(path,receipt,release,lifecycle,target=expected is not None,expected=expected)
    if flags != {'inventory_enabled':receipt['inventory_enabled'],'execution_enabled':False}:raise ValueError('RUNTIME_CONFIG_DRIFT')
    release.verify_exports()
    for unit in (lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('CODE_SERVICE_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('CODE_SERVICE_NOT_ENABLED')


def validate_rollback_package(package,release):
    require_pins()
    if type(package) is not dict or set(package)!={'release','apply_operation_id','operation_id'}:raise ValueError('CODE_ROLLBACK_FIELDS')
    original,identity=package['apply_operation_id'],package['operation_id']
    if (type(original) is not str or re.fullmatch('[0-9a-f]{32}',original) is None
        or type(identity) is not str or re.fullmatch('[0-9a-f]{32}',identity) is None or original==identity):raise ValueError('CODE_ROLLBACK_OPERATION_ID')
    return validate_package(package['release'],release)

def rollback(package, host, release, lifecycle, upgrade):
    global STAGE, OPERATION
    STAGE, OPERATION = ('rollback_preflight', 'package')
    prepared = validate_rollback_package(package, release)
    original, identity = (package['apply_operation_id'], package['operation_id'])
    if os.geteuid() != 0 or host.baseline() != prepared['baseline']:
        raise ValueError('HOST_BASELINE')
    old_path, old_receipt = upgrade.manifest(release, OLD_COMMIT, started=True)
    path, receipt = upgrade.manifest(release, TARGET_COMMIT, prepared, started=True)
    for value, digest in ((old_receipt, OLD_SOURCE_SHA256), (receipt, TARGET_SOURCE_SHA256)):
        if value['package'].get('baseline') != prepared['baseline'] or value['package'].get('source_tar_gz_sha256') != digest:
            raise ValueError('CODE_ROLLBACK_SOURCE')
    compatible_source(old_path, path, upgrade)
    files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    old_files = lifecycle.unit_files(old_path, pwd.getpwnam('www-data').pw_gid, release)
    if files[lifecycle.TMPFILES] != old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    for parent in (lifecycle.UNIT_DIR, lifecycle.TMPFILES.parent, release.ROOT / 'receipts'):
        release.trusted_dir(parent)
    for filename, body in files.items():
        if upgrade.read_file(filename, mode=420, maximum=32768) != body:
            raise ValueError('CODE_ROLLBACK_UNIT')
    if lifecycle._state(release, 'docker.service', 'ActiveState') != 'active':
        raise ValueError('DEPENDENCY_NOT_ACTIVE')
    # A broken target HTTP page is a reason to roll back; exact live identity,
    # immutable environment flags and unit ownership remain mandatory.
    verify_running(path, receipt, release, lifecycle, upgrade, probe_http=False)
    saved_path = release.ROOT / 'receipts' / ('code-upgrade-' + original + '.json')
    started_path = release.ROOT / 'receipts' / ('preview-start-' + TARGET_COMMIT + '.json')
    read = lambda filename: upgrade.read_file(filename, mode=384, maximum=32768)
    saved_raw, started_raw = (read(saved_path), read(started_path))
    saved = json.loads(saved_raw, object_pairs_hook=release.unique)
    started = json.loads(started_raw, object_pairs_hook=release.unique)
    expected_saved = dict(source_commit=OLD_COMMIT, target_commit=TARGET_COMMIT, database_policy='preserve-in-place', images=old_receipt['images'], units={str(p): b.decode() for p, b in old_files.items() if p != lifecycle.TMPFILES})
    if saved != expected_saved:
        raise ValueError('CODE_ROLLBACK_RECOVERY')
    if started.get('ok') is not True or started.get('stage') != 'internal_ready' or started.get('source_commit') != TARGET_COMMIT or (started.get('previous_commit') != OLD_COMMIT) or (started.get('operation_id') != original) or (started.get('database_policy') != 'preserve-in-place') or (started.get('database_opened_by_controller') is not False) or (started.get('source_warmup_performed') is not False):
        raise ValueError('CODE_ROLLBACK_STARTED')
    bootstrap = bootstrap_state(release, upgrade)
    baseline_proof = base_success(release,upgrade)
    attempt = release.ROOT / 'receipts' / ('code-post-rollback-' + identity + '.json')
    result_path = attempt.with_name('code-post-rollback-' + identity + '.result.json')
    if any((os.path.lexists(p) for p in (attempt, result_path))):
        raise ValueError('CODE_ROLLBACK_ALREADY_ATTEMPTED')
    release.write_new(attempt, json.dumps(dict(source_commit=TARGET_COMMIT, target_commit=OLD_COMMIT, apply_operation_id=original, operation_id=identity, database_policy='preserve-in-place'), sort_keys=True).encode())

    def unchanged():
        require_pins()
        if base_success(release,upgrade) != baseline_proof:raise ValueError('PATCH_BASELINE')
        release.verify_exports()
        if host.baseline() != prepared['baseline'] or bootstrap_state(release, upgrade) != bootstrap or read(saved_path) != saved_raw or (read(started_path) != started_raw):
            raise ValueError('CODE_ROLLBACK_STATE')
        if upgrade.manifest(release, OLD_COMMIT, started=True) != (old_path, old_receipt) or upgrade.manifest(release, TARGET_COMMIT, prepared, started=True) != (path, receipt):
            raise ValueError('CODE_ROLLBACK_SOURCE')
        compatible_source(old_path, path, upgrade)
    try:
        STAGE = 'rollback_stop'
        for unit in reversed(lifecycle.UNITS):
            OPERATION = 'stop_' + unit
            release.command(['/usr/bin/systemctl', 'stop', unit], timeout=90)
            stopped_writer(release, lifecycle, path, {TARGET_COMMIT: receipt['images']}, unit)
        OPERATION = 'unchanged'
        unchanged()
        STAGE = 'rollback_restore'
        for name in ('engine', 'relay'):
            OPERATION = 'recreate_' + name
            release.command(release.compose(old_path, name) + ['up', '--no-start', '--no-build', '--force-recreate'], timeout=90)
        for unit in reversed(lifecycle.UNITS):
            OPERATION = 'replace_' + unit
            filename = lifecycle.UNIT_DIR / unit
            upgrade.replace_unit(filename, files[filename], old_files[filename], identity, release)
        rollback_flags,frozen=stopped_container_runtime_flags(old_path,old_receipt,release,lifecycle)
        if rollback_flags != {'inventory_enabled':old_receipt['inventory_enabled'],'execution_enabled':False}:raise ValueError('RUNTIME_CONFIG_DRIFT')
        OPERATION = 'daemon_reload'
        release.command(['/usr/bin/systemctl', 'daemon-reload'])
        unchanged()
        STAGE = 'rollback_start'
        for unit in lifecycle.UNITS:
            OPERATION = 'start_' + unit
            release.command(['/usr/bin/systemctl', 'start', unit], timeout=90)
        STAGE, OPERATION = ('rollback_verify', 'verify_running')
        verify_running(old_path, old_receipt, release, lifecycle, upgrade, expected=frozen)
        for filename, body in old_files.items():
            if upgrade.read_file(filename, mode=420, maximum=32768) != body:
                raise ValueError('CODE_ROLLBACK_UNIT')
        unchanged()
        result = dict(database_schema=21,execution_enabled=False,runtime_flags_verified=True,saved_export_companion_preserved=True,ok=True, stage='internal_ready', operation='code-only-rollback', source_commit=OLD_COMMIT, previous_commit=TARGET_COMMIT, operation_id=identity, apply_operation_id=original, database_policy='preserve-in-place', database_opened_by_controller=False, source_warmup_performed=False, nginx_changed=False)
        release.write_new(result_path, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception as error:
        failed_stage, failed_operation = (STAGE, OPERATION)
        STAGE, OPERATION = ('rollback_failed_stop', 'stop_isolated')
        stop_verified = True
        for unit in reversed(lifecycle.UNITS):
            try:
                release.command(['/usr/bin/systemctl', 'stop', unit], timeout=90)
            except Exception:
                stop_verified = False
        for unit in lifecycle.UNITS:
            try:
                stopped_writer(release, lifecycle, path, {OLD_COMMIT: old_receipt['images'], TARGET_COMMIT: receipt['images']}, unit)
            except Exception:
                stop_verified = False
        refused = RuntimeError('CODE_POST_ROLLBACK_FAILED')
        kind = type(error).__name__
        refused.failure_details = dict(failed_stage=failed_stage, failed_operation=failed_operation, failed_error_kind=kind if kind in FAILURE_KINDS else 'UNRECOGNIZED', isolated_stop_verified=stop_verified)
        raise refused from None
