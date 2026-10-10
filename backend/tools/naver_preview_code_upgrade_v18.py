"""V18 read-only report freshness; exact four-path transition and unchanged schema 11."""
import ast
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import sqlite3
from types import SimpleNamespace
import uuid
OLD_COMMIT = '7c99e18e29e6cb4d3f32eb41b6983529126d8f3a'
TARGET_COMMIT = 'c3ce2b47ce088483c734e8ba5cef569ecfa66e77'
EXPECTED_BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
# Current V17 canonical archive.
OLD_SOURCE_SHA256 = '874ea72edfef7c5a375f26cf8bdb103aa487779bd06e208aada7b1a5184dcee2'
# Exact canonical archive.
TARGET_SOURCE_SHA256 = '7a23f9717056b483915a076d658f85aab5f5cf662e7bc5454a64788db847123e'
# Exact old and target Store implementation pins; schema unchanged.
STORE_SHA256 = {'old': 'cc050c8c3d8c0d2a8e4977ec0e8e5b271ff7fc932a8d35a6c0f10dadc11ddb56', 'target': 'b01a1e21cc87df1ef5a3935a30cc25d96b0ec3ced0fcc42a2bc9999685ef7d95'}
# Only reviewed report runtime paths; one added read projection module.
CODE_PATHS = {'naver_engine/report_refresh.py', 'naver_engine/report_views.py', 'naver_engine/store.py', 'backend/naver_page/report-ui.js'}
ADDED_SOURCE_PATHS = frozenset({'naver_engine/report_refresh.py'})
ENGINE_COMPOSE_SHA256 = '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'
# Neither archive ships test folders; their removal is covered by REMOVABLE_SOURCE_PREFIXES.
TEST_PATHS = frozenset()
# The seal no longer ships test folders (ad-dashboard tools/naver-preview-seal.py SOURCE_EXCLUDED_PATHS);
# old deployed trees may still carry them. Tests never run on the server, so only these may disappear.
REMOVABLE_SOURCE_PREFIXES = ('naver_engine/tests/', 'naver_runtime/tests/')
# Named writes open on both sides of this release: the owner-actions writes (8dd4292) and the CEO-only
# pair revoke the screen overhaul (a981b35) opened. 401 without a token on both sides.
OWNER_ACTION_ROUTES = ('/issues/1/ack', '/issues/1/resolve', '/issues/1/except', '/bell/1/read', '/bell/read-all',
    '/settings/thresholds', *('/holds/'+k+'/confirm' for k in ('org', 'stages', 'accounts')), '/links/revoke')
# Both sides retain reviewed report-annotation writes; unauthenticated requests must be 401.
TARGET_ACTION_ROUTES = ('/reports/notes',)
# Closed on both sides.
CLOSED_LINK_ROUTES = ('/links/reject', '/links/preview')
OLD_REPORT_UI = (60450, 'c629f0f2485f9ba5d524b6cbf1329e562958b7099fad5b568c944a03ec855cb8', 'text/javascript; charset=utf-8')
REPORT_ASSETS = {
    '/naver/'+name:(size,digest,'application/gzip' if name.endswith('.gz') else 'text/css; charset=utf-8' if name.endswith('.css') else 'text/javascript; charset=utf-8')
    for name,size,digest in (
        ('report-ui.js', 62639, 'af40b3903436e9dbb419abb414e08bda5cbe4d1336a2ee71a87f308418d78ab7'),
        ('report-pdf.js', 35168, '45d15c2862cd83a223e52cf85c1feb9327ffe6cc5753d558a8f6d67e1cd8f6bc'),
        ('app.js', 218303, 'ccc7591759a448f8299610b32c60715b408246b9a7a094369fc5c71884a41984'),
        ('app.css', 53635, 'bacdae44e6e99a2be2e84c53c3347029ef8845b110c2367a0fb8ed54594ea5db'),
        ('vendor/report-pdf/NanumGothic-Regular.ttf.gz',697020,'72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07'),
        ('vendor/report-pdf/pdf-lib-1.17.1.min.js',525099,'0f9a5cad07941f0826586c94e089d89b918c46e5c17cf2d5a3c6f666e3bc694f'),
        ('vendor/report-pdf/fontkit-1.1.1.umd.min.js',758440,'d8df561b9fba98e24f2e5130e40948809281bbbc55a20c412359f1a0a5eb35a6'),
        ('vendor/report-pdf/sha256-1.0.0.min.js',8156,'a050d794e170699bd1a69d33908d0942c68901cb88347016064b60b240f0067e'))}
DATA = Path('/var/lib/metainc/naver-engine')
STAGE = 'input'
OPERATION = 'none'
FAILURE_STAGES = frozenset('input code_apply_preflight code_stop_isolated account_database_snapshot '
    'account_sources_warm code_recreate code_replace_units code_start code_verify code_rollback'.split())
FAILURE_OPERATIONS = frozenset('none package current_state target_manifest compatible_source unit_manifest '
    'write_recovery_receipt bootstrap_check snapshot_directory snapshot_identity snapshot_lock snapshot_create '
    'snapshot_schema snapshot_copy snapshot_integrity snapshot_fsync snapshot_digest warm_sources warm_create '
    'warm_wait warm_logs warm_result warm_cleanup_find warm_cleanup_identity warm_cleanup_remove '
    'warm_cleanup_absence warm_config warm_store_open warm_schema warm_org_sync warm_org_contract warm_accounts_sync '
    'warm_catalog_sync warm_summary daemon_reload verify_running post_state write_started_receipt restore_database '
    'old_manifest rollback_schema rollback_state'.split()) | frozenset(prefix+'_'+name for prefix in
        ('stop','stop_check','recreate','replace_unit','start','restore_unit') for name in ('engine','relay'))
FAILURE_KINDS = frozenset('ValueError RuntimeError TimeoutError TimeoutExpired CalledProcessError OSError '
    'PermissionError FileNotFoundError BlockingIOError JSONDecodeError OperationalError IntegrityError '
    'TypeError KeyError AttributeError AssertionError ImportError ModuleNotFoundError ConfigError StoreRefused'.split())
SQL_ERRORS={n:'SQLITE_'+s for n,s in zip((1,5,6,8,10,11,14,15,26),'ERROR BUSY LOCKED READONLY IOERR CORRUPT CANTOPEN PROTOCOL NOTADB'.split())}
FAILURE_CODES = frozenset(SQL_ERRORS.values()) | frozenset('CODE_TARGET_NOT_PINNED CODE_PACKAGE CODE_TARGET CODE_BASELINE CODE_APPLY_FIELDS '
    'CODE_OPERATION_ID CODE_ALREADY_ATTEMPTED CODE_POST_STATE CODE_TARGET_SOURCE_CHANGED CODE_FAILED_ROLLED_BACK_DB_PRESERVED '
    'CODE_ROLLBACK_FAILED HOST_BASELINE OLD_BASELINE OLD_SOURCE_CHANGED OLD_UNIT_CHANGED OLD_UNIT_NOT_ENABLED '
    'DEPENDENCY_NOT_ACTIVE BOOTSTRAP_REQUEST BOOTSTRAP_NOT_FINISHED BOOTSTRAP_CHANGED TMPFILES_CHANGED '
    'CODE_INFRASTRUCTURE_CHANGED CODE_SCHEMA_CHANGED CODE_STORE_CHANGED CODE_OVERRIDE_CHANGED CODE_SOURCE_PATH CODE_SOURCE_MODE_CHANGED '
    'CODE_SOURCE_REMOVED CODE_SCOPE_CHANGED SCHEMA_CONTRACT_MISSING CODE_PROBE_SOURCE CODE_ROUTE_STATUS '
    'CODE_SERVICE_NOT_ACTIVE CODE_SERVICE_NOT_ENABLED VERIFIED_WRITE_AUTH_NOT_REQUIRED '
    'ACCOUNT_WRITER_NOT_STOPPED DB_IDENTITY DB_OLD_SCHEMA DB_TARGET_SCHEMA DB_SNAPSHOT_INTEGRITY DB_SNAPSHOT_CHANGED '
    'WARM_CONTAINER_ID WARM_CONTAINER_REMAINS WARM_CREATE_UNCONFIRMED WARM_CLEANUP_FAILED SOURCE_WARM_FAILED '
    'ORG_NOT_ACCEPTED MANAGEMENT_FIELD_MISSING ACCOUNTS_NOT_ACCEPTED CATALOG_NOT_ACCEPTED '
    'COMMAND_FAILED DIRECTORY_POLICY FILE_PATH FILE_POLICY PREPARED_MANIFEST PREPARED_DIGEST '
    'PREPARED_FILE_CHANGED PREPARED_IMAGE PREPARED_IMAGE_CHANGED SOURCE_NOT_READY UNIT_CHANGED ENGINE_NOT_READY '
    'PAGE_NOT_READY REPORT_ASSET_NOT_READY UNAUTHENTICATED_READ_NOT_DENIED BUSINESS_WRITE_NOT_DENIED SERVICES_NOT_READY'.split())
FAILURE_CODES |= frozenset({'CODE_ONLY_REQUIRED', 'PROBE_RESPONSE_SIZE'})
def _error_labels(error):
    kind = type(error).__name__
    code = error.args[0] if len(error.args) == 1 and isinstance(error.args[0], str) else None
    if isinstance(error,sqlite3.Error):
        fallback=dict(zip(('database is locked|database table is locked|attempt to write a readonly database|'
        'unable to open database file|database disk image is malformed|file is not a database|disk I/O error|'
        'locking protocol').split('|'),(5,6,8,14,11,26,10,15)))
        code=SQL_ERRORS.get(getattr(error,'sqlite_errorcode',fallback.get(code,0))&255)
    return {'error_kind':kind if kind in FAILURE_KINDS else 'OtherError',
        'error_code':code if code in FAILURE_CODES else 'UNRECOGNIZED'}
def _capture_failure(error, prefix='failed'):
    details = {'stage':STAGE if STAGE in FAILURE_STAGES else 'unknown',
        'operation':OPERATION if OPERATION in FAILURE_OPERATIONS else 'unknown', **_error_labels(error)}
    return {prefix+'_'+key:value for key,value in details.items()}
def failure_report(error):
    result = {'stage':STAGE if STAGE in FAILURE_STAGES else 'unknown', **_error_labels(error)}
    choices = {'stage':FAILURE_STAGES|{'unknown'}, 'operation':FAILURE_OPERATIONS|{'unknown'},
        'error_kind':FAILURE_KINDS|{'OtherError'}, 'error_code':FAILURE_CODES|{'UNRECOGNIZED'}}
    details = getattr(error, 'failure_details', {})
    if isinstance(details, dict):
        for prefix in ('failed', 'cleanup', 'rollback'):
            for suffix, allowed in choices.items():
                key = prefix+'_'+suffix
                value = details.get(key)
                if isinstance(value, str) and value in allowed:
                    result[key] = value
    return result
def validate_package(package, release):
    if (not isinstance(TARGET_COMMIT, str) or not re.fullmatch('[0-9a-f]{40}', TARGET_COMMIT)
        or TARGET_COMMIT == OLD_COMMIT
        or not isinstance(TARGET_SOURCE_SHA256, str)
        or not re.fullmatch('[0-9a-f]{64}', TARGET_SOURCE_SHA256)
        or any(not isinstance(STORE_SHA256.get(role), str)
        or not re.fullmatch('[0-9a-f]{64}', STORE_SHA256[role]) for role in ('old', 'target'))):
        raise ValueError('CODE_TARGET_NOT_PINNED')
    if any(type(REPORT_ASSETS.get('/naver/'+name, (None,None,None))[0]) is not int
        or REPORT_ASSETS['/naver/'+name][0] <= 0
        or type(REPORT_ASSETS['/naver/'+name][1]) is not str
        or not re.fullmatch('[0-9a-f]{64}', REPORT_ASSETS['/naver/'+name][1])
        for name in ('report-ui.js','report-pdf.js','app.js','app.css')):
        raise ValueError('CODE_TARGET_NOT_PINNED')
    if not isinstance(package, dict) or package.get('operation') != 'code-prepare':
        raise ValueError('CODE_PACKAGE')
    release.validate_package(dict(package, operation='upgrade-prepare'))
    if package['source_commit'] != TARGET_COMMIT:
        raise ValueError('CODE_TARGET')
    if package['source_tar_gz_sha256'] != TARGET_SOURCE_SHA256:
        raise ValueError('CODE_TARGET_SOURCE_CHANGED')
    if package['baseline'] != EXPECTED_BASELINE:
        raise ValueError('CODE_BASELINE')
    return package
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
    path, receipt = upgrade.manifest(release, OLD_COMMIT, started=True)
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
def store_contract(body, role):
    if role not in ('old', 'target') or hashlib.sha256(body).hexdigest() != STORE_SHA256.get(role):
        raise ValueError('CODE_STORE_CHANGED')
    tree = ast.parse(body)
    versions = [node for node in tree.body if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=='SCHEMA_VERSION' for target in node.targets)]
    if (len(versions) != 1 or len(versions[0].targets) != 1
        or not isinstance(versions[0].value, ast.Constant)
        or type(versions[0].value.value) is not int or versions[0].value.value != 11):
        raise ValueError('CODE_SCHEMA_CHANGED')
    sql = None
    for node in tree.body:
        if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='_SCHEMA'
        for target in node.targets):
            if sql is not None or len(node.targets) != 1:
                raise ValueError('CODE_SCHEMA_CHANGED')
            sql = ast.literal_eval(node.value)
        elif isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id=='_SCHEMA':
            if sql is None or not isinstance(node.op,ast.Add):
                raise ValueError('CODE_SCHEMA_CHANGED')
            extra = ast.literal_eval(node.value)
            if not isinstance(extra, tuple) or not isinstance(sql, tuple):
                raise ValueError('CODE_SCHEMA_CHANGED')
            sql += extra
    if sql is None:
        raise ValueError('SCHEMA_CONTRACT_MISSING')
    if not isinstance(sql, tuple) or any(not isinstance(statement, str) for statement in sql):
        raise ValueError('CODE_SCHEMA_CHANGED')
    return sql
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
MONITORING_SQL = (
    """CREATE TABLE IF NOT EXISTS naver_auto_morning_progress (
        customer_id INTEGER PRIMARY KEY, possibility_id INTEGER NOT NULL, day TEXT NOT NULL,
        binding TEXT NOT NULL, campaign_fingerprint TEXT NOT NULL, generation INTEGER NOT NULL,
        status TEXT NOT NULL, next_try_at TEXT NOT NULL, payload_bytes INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_morning_chunk (
        customer_id INTEGER NOT NULL, kind TEXT NOT NULL, slot INTEGER NOT NULL,
        generation INTEGER NOT NULL, body TEXT, checksum TEXT, size INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (customer_id, kind, slot))""",
)
def migration_contract(before, after):
    old_sql, new_sql = store_contract(before, 'old'), store_contract(after, 'target')
    if new_sql != old_sql or schema_contract(before) != schema_contract(after):
        raise ValueError('CODE_SCHEMA_CHANGED')
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
def db_snapshot(identity, release, upgrade):
    global OPERATION
    OPERATION = 'snapshot_directory'
    release.trusted_dir(DATA, uid=10001, gid=10001, mode=0o750)
    db = DATA/'engine.db'
    upgrade.read_file(db, uid=10001, gid=10001, mode=0o600, maximum=1024**3)
    destination = release.ROOT/'receipts'/('account-db-'+identity+'.sqlite')
    fd = os.open(db, os.O_RDWR | os.O_NOFOLLOW)
    try:
        OPERATION = 'snapshot_identity'
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
        or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (10001, 10001, 0o600)
        or (info.st_dev, info.st_ino) != (db.stat().st_dev, db.stat().st_ino)):
            raise ValueError('DB_IDENTITY')
        OPERATION = 'snapshot_lock'
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        OPERATION = 'snapshot_create'
        release.write_new(destination, b'')
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as source, closing(sqlite3.connect(destination)) as target:
            OPERATION = 'snapshot_schema'
            database_contract(source, OLD_COMMIT)
            OPERATION = 'snapshot_copy'
            source.backup(target)
            OPERATION = 'snapshot_integrity'
            if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('DB_SNAPSHOT_INTEGRITY')
        os.chmod(destination, 0o600)
        OPERATION = 'snapshot_fsync'
        durable = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(durable)
        finally:
            os.close(durable)
        OPERATION = 'snapshot_digest'
        raw = upgrade.read_file(destination, mode=0o600, maximum=1024**3)
        return destination, hashlib.sha256(raw).hexdigest()
    finally:
        os.close(fd)
def restore_db(snapshot, identity, release, upgrade):
    path, digest = snapshot
    raw = upgrade.read_file(path, mode=0o600, maximum=1024**3)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('DB_SNAPSHOT_CHANGED')
    release.trusted_dir(DATA, uid=10001, gid=10001, mode=0o750)
    quarantine = DATA/('.account-failed-db-'+identity)
    release.trusted_dir(quarantine, mode=0o700, new=True)
    for suffix in ('', '-wal', '-shm', '-journal'):
        source = DATA/('engine.db'+suffix)
        if os.path.lexists(source):
            upgrade.read_file(source, uid=10001, gid=10001, mode=0o600, maximum=1024**3, minimum=0)
            os.replace(source, quarantine/source.name)
    temporary = DATA/('account-restore-'+identity+'.sqlite')
    release.write_new(temporary, raw, uid=10001, gid=10001, mode=0o600)
    os.replace(temporary, DATA/'engine.db')
    fd = os.open(DATA, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
WARM_SCRIPT = r'''
import json,os,sys,threading
sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
step='warm_config'
try:
    from naver_engine import store as S,sync as Y,inventory as I,links as L
    from naver_runtime.__main__ import dependencies,InterruptibleClock
    from naver_runtime.config import Config
    clock=InterruptibleClock(threading.Event())
    config=Config.from_env(os.environ)
    options=dependencies(config,os.environ,clock)
    step='warm_store_open'
    with S.open_writer(config.db) as store:
        step='warm_schema'
        if S.SCHEMA_VERSION!=11 or store.meta('schema_version')!='11': raise ValueError('DB_TARGET_SCHEMA')
        step='warm_org_sync'
        org=Y.sync_org(options['erp_factory'](),store,clock.now())
        if org.outcome!='accepted': raise ValueError('ORG_NOT_ACCEPTED')
        step='warm_org_contract'
        body=store.org_current()['body']
        if not body['employees'] or any(type(e.get('is_management')) is not bool for e in body['employees']):
            raise ValueError('MANAGEMENT_FIELD_MISSING')
        step='warm_accounts_sync'
        accounts=L.sync_accounts(options['naver_factory'](),store,clock.now())
        if accounts.outcome!='accepted': raise ValueError('ACCOUNTS_NOT_ACCEPTED')
        step='warm_catalog_sync'
        I.sync_catalog(options['erp_factory'](),store,clock.now())
        if store.account_catalog_status().get('state')!='accepted': raise ValueError('CATALOG_NOT_ACCEPTED')
        step='warm_summary'
        print(json.dumps({'ok':True,'org_fresh':True,'management_count':sum(e['is_management'] for e in body['employees']),
                          'catalog_total':store.account_catalog()['total'],'accounts_total':accounts.rows,
                          'schema':int(store.meta('schema_version'))}))
except Exception as error:
    code=error.args[0] if len(error.args)==1 and isinstance(error.args[0],str) else None
    allowed={'DB_TARGET_SCHEMA','ORG_NOT_ACCEPTED','MANAGEMENT_FIELD_MISSING','ACCOUNTS_NOT_ACCEPTED','CATALOG_NOT_ACCEPTED'}
    print(json.dumps({'ok':False,'warm_step':step,'warm_error_code':code if code in allowed else 'UNRECOGNIZED'}))
    sys.exit(1)
'''
def warm_sources(path, release):
    global STAGE, OPERATION
    STAGE = 'account_sources_warm'
    check = release.compose(path, 'engine')
    name = 'naver-warm-'+TARGET_COMMIT+'-'+uuid.uuid4().hex
    identity = None
    failure = None
    try:
        OPERATION = 'warm_create'
        identity = release.command(check+['run', '--detach', '--no-deps', '--pull', 'never',
        '--name', name, '--label', 'metainc.naver.warm.source='+TARGET_COMMIT,
        '--entrypoint', 'python', 'naver-engine', '-I', '-B', '-c', WARM_SCRIPT], timeout=60).decode().strip()
        if not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('WARM_CONTAINER_ID')
        OPERATION = 'warm_wait'
        status = release.command(['docker', 'wait', identity], timeout=180).strip()
        OPERATION = 'warm_logs'
        result = json.loads(release.command(['docker', 'logs', identity], timeout=30))
        OPERATION = 'warm_result'
        if status != b'0':
            if isinstance(result, dict) and result.get('warm_step') in {
        'warm_config','warm_store_open','warm_schema','warm_org_sync','warm_org_contract',
        'warm_accounts_sync','warm_catalog_sync','warm_summary'}:
                OPERATION = result['warm_step']
            code = result.get('warm_error_code') if isinstance(result, dict) else None
            raise ValueError(code if isinstance(code,str) and code in FAILURE_CODES else 'SOURCE_WARM_FAILED')
        if (result.get('ok') is not True or result.get('org_fresh') is not True
        or type(result.get('schema')) is not int or result['schema'] != 11
        or type(result.get('catalog_total')) is not int or result['catalog_total'] < 1
        or type(result.get('management_count')) is not int or result['management_count'] < 1):
            raise ValueError('SOURCE_WARM_FAILED')
        return result
    except Exception as error:
        error.failure_details = _capture_failure(error)
        failure = error.failure_details
        raise
    finally:
        # Prove cleanup after CLI timeout.
        try:
            OPERATION = 'warm_cleanup_find'
            found = release.command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                'name=^/'+name+'$', '--format', '{{.ID}}'], timeout=30).decode().strip()
            if found:
                OPERATION = 'warm_cleanup_identity'
                if not re.fullmatch('[0-9a-f]{64}', found):
                    raise ValueError('WARM_CONTAINER_ID')
                fmt = '{"source":{{json (index .Config.Labels "metainc.naver.warm.source")}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"user":{{json .Config.User}}}'
                meta = json.loads(release.command(['docker', 'inspect', '--format', fmt, found]))
                if meta != {'source':TARGET_COMMIT, 'project':'naver-engine', 'user':'10001:10001'}:
                    raise ValueError('WARM_CONTAINER_ID')
                OPERATION = 'warm_cleanup_remove'
                release.command(['docker', 'rm', '--force', found], timeout=45)
            elif identity is None:
        # Late create after timeout.
                raise ValueError('WARM_CREATE_UNCONFIRMED')
            OPERATION = 'warm_cleanup_absence'
            if release.command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                    'name=^/'+name+'$', '--format', '{{.ID}}'], timeout=30).strip():
                raise ValueError('WARM_CONTAINER_REMAINS')
        except Exception as error:
            refused = RuntimeError('WARM_CLEANUP_FAILED')
            refused.failure_details = {**(failure or _capture_failure(error)), **_capture_failure(error,'cleanup')}
            raise refused from None
def compatible_code_scope(old, new, upgrade, *, inverse=False):
    def inventory(root):
        files = {}
        for path in root.rglob('*'):
            if path.is_symlink() or path.resolve() != path:
                raise ValueError('CODE_SOURCE_PATH')
            if path.is_dir():
                continue
            name = path.relative_to(root).as_posix()
            if name in ('preview-engine.override.yml', 'preview-relay.override.yml'):
                continue
            files[name] = (stat.S_IMODE(path.stat().st_mode),
                upgrade.read_file(path, maximum=1024*1024, minimum=0))
        return files
    before, after = inventory(old), inventory(new)
    added, removed = after.keys()-before.keys(), before.keys()-after.keys()
    # V18 admits only its one reviewed added production path.
    if inverse:
        if removed != ADDED_SOURCE_PATHS or any(not name.startswith(REMOVABLE_SOURCE_PREFIXES) for name in added):
            raise ValueError('CODE_SOURCE_REMOVED')
    else:
        if any(not name.startswith(REMOVABLE_SOURCE_PREFIXES) for name in removed):
            raise ValueError('CODE_SOURCE_REMOVED')
        if added != ADDED_SOURCE_PATHS:
            raise ValueError('CODE_SCOPE_CHANGED')
        if any(after[name][0] != 0o644 for name in added):
            raise ValueError('CODE_SOURCE_MODE_CHANGED')
    for name, value in after.items():
        if name in before and before[name][0] != value[0]:
            raise ValueError('CODE_SOURCE_MODE_CHANGED')
        restored_test = inverse and name in added and name.startswith(REMOVABLE_SOURCE_PREFIXES)
        if before.get(name) != value and name not in CODE_PATHS | TEST_PATHS and not restored_test:
            raise ValueError('CODE_SCOPE_CHANGED')


def compatible_inverse_source(target, old, upgrade):
    # Forward verification fixes Store roles, schema, infrastructure and image overrides.
    # The inverse tree check does not widen any earlier release's removal policy.
    compatible_source(old, target, upgrade)
    compatible_code_scope(target, old, upgrade, inverse=True)
def probe(release, source_commit, upgrade):
    management_target = source_commit in (OLD_COMMIT, TARGET_COMMIT)
    old_source = source_commit == OLD_COMMIT
    if source_commit == OLD_COMMIT:
        source_commit = TARGET_COMMIT
    if (not isinstance(TARGET_COMMIT, str) or not re.fullmatch('[0-9a-f]{40}', TARGET_COMMIT)
        or source_commit != TARGET_COMMIT):
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
        assets = dict(REPORT_ASSETS)
        if old_source:
            assets['/naver/report-ui.js'] = OLD_REPORT_UI
        for route,(size,digest,mime) in assets.items():
            status,headers,body = release.unix_request(relay, route, 'GET')
            headers = {key.lower():value for key,value in headers.items()}
            if (status != 200 or len(body) != size or hashlib.sha256(body).hexdigest() != digest
                    or headers.get('content-type') != mime or headers.get('cache-control') != 'no-store'
                    or headers.get('x-content-type-options') != 'nosniff'
                    or headers.get('referrer-policy') != 'no-referrer' or headers.get('content-encoding')):
                raise ValueError('REPORT_ASSET_NOT_READY')
def verify_running(path, receipt, release, lifecycle, upgrade):
    source = receipt.get('source_commit')
    if source not in (OLD_COMMIT, TARGET_COMMIT) or path.name != 'naver-' + source:
        raise ValueError('CODE_PROBE_SOURCE')
    probe(release, source, upgrade)
    if source == TARGET_COMMIT:
        # Old release: no DB read while it runs; rollback checks the DB before start.
        verify_database_schema(source, release, upgrade)
    lifecycle._snapshot(release, path, receipt['images'])
    for unit in (lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('CODE_SERVICE_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('CODE_SERVICE_NOT_ENABLED')
def verify_database_schema(source, release, upgrade):
    if source not in (OLD_COMMIT, TARGET_COMMIT):
        raise ValueError('CODE_PROBE_SOURCE')
    release.trusted_dir(DATA, uid=10001, gid=10001, mode=0o750)
    db = DATA/'engine.db'
    upgrade.read_file(db, uid=10001, gid=10001, mode=0o600, maximum=1024**3)
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA trusted_schema=OFF')
        database_contract(connection, source)
def database_contract(connection, source):
    if source not in (OLD_COMMIT, TARGET_COMMIT):
        raise ValueError('CODE_PROBE_SOURCE')
    error = 'DB_OLD_SCHEMA' if source == OLD_COMMIT else 'DB_TARGET_SCHEMA'
    if connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone() != ('11',):
        raise ValueError(error)
    columns = connection.execute('PRAGMA table_info(naver_auto_link_memory)').fetchall()
    old_columns = [(0,'possibility_id','INTEGER',1,None,1),
        (1,'customer_id','INTEGER',1,None,2),
        (2,'link','TEXT',1,None,3),
        (3,'first_matched_at','TEXT',1,None,0),
        (4,'last_matched_at','TEXT',1,None,0)]
    wanted = old_columns+[(5,'auto_identity_fingerprint','TEXT',0,None,0)]
    if columns != wanted:
        raise ValueError(error)
    with closing(sqlite3.connect(':memory:')) as reference:
        for statement in MONITORING_SQL:
            reference.execute(statement)
        for table in ('naver_auto_morning_progress', 'naver_auto_morning_chunk'):
            if connection.execute('PRAGMA table_info('+table+')').fetchall() != \
                    reference.execute('PRAGMA table_info('+table+')').fetchall():
                raise ValueError(error)
def prepare(package, host, release, lifecycle, upgrade):
    global STAGE
    STAGE = 'code_prepare_preflight'
    validate_package(package, release)
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
    if len(plain) > 3*1024*1024:
        raise ValueError('PLAINTEXT_SIZE')
    source, files = release.decode_payload(plain, TARGET_COMMIT, package['source_tar_gz_sha256'])
    release.source_members(source)[0].close()
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
    check = release.compose(destination, 'engine')
    check[check.index('--project-name')+1] = 'naver-check-'+TARGET_COMMIT+'-'+uuid.uuid4().hex
    STAGE = 'code_check_config'
    check_override = release.ROOT/'incoming'/package['run_id']/'check-config.override.yml'
    release.write_new(check_override, b'services:\n  naver-engine:\n    network_mode: none\n')
    check += ['-f', str(check_override)]
    release.command(check+['run','--rm','--no-deps','--pull','never','naver-engine','python','-m','naver_runtime','check-config'], timeout=60)
    STAGE = 'code_prepare_postflight'
    if current_state(package, host, release, lifecycle, upgrade) != old:
        raise ValueError('OLD_STATE_CHANGED')
    images = {name: json.loads(release.command(['docker','image','inspect','--format','{{json .Id}}','metainc/naver-'+name+':'+TARGET_COMMIT])) for name in ('engine','relay')}
    paths = {str(destination/'deploy/naver-engine-backup.override.yml')}
    paths.update(str(destination/(prefix+name+suffix)) for name in ('engine','relay')
                 for prefix, suffix in (('compose.naver-', '.yml'), ('preview-', '.override.yml')))
    paths.update(item['path'] for item in files)
    receipt = {'ok':True, 'stage':'prepared', 'source_commit':TARGET_COMMIT,
               'package':{k:v for k,v in package.items() if k!='operation'}, 'images':images,
               'files':{path:release.sha(Path(path).read_bytes()) for path in sorted(paths)}}
    release.write_new(receipt_path, json.dumps(receipt, sort_keys=True).encode())
    upgrade.manifest(release, TARGET_COMMIT, package)
    return {'ok':True,'stage':'prepared','source_commit':TARGET_COMMIT,'previous_commit':OLD_COMMIT,
            'services_started':False,'nginx_changed':False,'bootstrap_unchanged':True}
def apply(package, host, release, lifecycle, upgrade):
    # This release only supports the separate preserve-in-place code-only entry point.
    raise ValueError("CODE_ONLY_REQUIRED")
