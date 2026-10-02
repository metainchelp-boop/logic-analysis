"""Pinned transfer-page release with an unchanged schema8 rollback snapshot."""
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

OLD_COMMIT = 'f8daabe19ee4bdd4d6e79159f431a5dfd49058e6'
TARGET_COMMIT = 'd6542c37d1b247801f3f10259b2098d14e7b6dc8'
EXPECTED_BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
OLD_SOURCE_SHA256 = '67ee1cd94f40efb7d701ed7cdba53562a8e344763153240e08c7ffc4eb7b7a5e'
CODE_PATHS = {'backend/naver_page/app.css', 'backend/naver_page/app.js', 'backend/naver_page/index.html',
              'naver_engine/inventory.py', 'naver_engine/web.py'}
TEST_PATHS = {'naver_engine/tests/inventory_screen_browser.js',
              'naver_engine/tests/test_inventory_summary.py'}
DATA = Path('/var/lib/metainc/naver-engine')
STAGE = 'input'
OPERATION = 'none'
FAILURE_STAGES = frozenset('input code_apply_preflight code_stop_isolated account_database_snapshot '
    'account_sources_warm code_recreate code_replace_units code_start code_verify code_rollback'.split())
FAILURE_OPERATIONS = frozenset('none package current_state target_manifest compatible_source unit_manifest '
    'write_recovery_receipt bootstrap_check snapshot_directory snapshot_identity snapshot_lock snapshot_create '
    'snapshot_schema snapshot_copy snapshot_integrity snapshot_fsync snapshot_digest warm_sources warm_create '
    'warm_wait warm_logs warm_result warm_cleanup_find warm_cleanup_identity warm_cleanup_remove '
    'warm_cleanup_absence warm_config warm_store_open warm_org_sync warm_org_contract warm_accounts_sync '
    'warm_catalog_sync warm_summary daemon_reload verify_running post_state write_started_receipt restore_database '
    'old_manifest rollback_state'.split()) | frozenset(prefix+'_'+name for prefix in
        ('stop','stop_check','recreate','replace_unit','start','restore_unit') for name in ('engine','relay'))
FAILURE_KINDS = frozenset('ValueError RuntimeError TimeoutError TimeoutExpired CalledProcessError OSError '
    'PermissionError FileNotFoundError BlockingIOError JSONDecodeError OperationalError IntegrityError '
    'TypeError KeyError AttributeError AssertionError ImportError ModuleNotFoundError ConfigError StoreRefused'.split())
FAILURE_CODES = frozenset('CODE_TARGET_NOT_PINNED CODE_PACKAGE CODE_TARGET CODE_BASELINE CODE_APPLY_FIELDS '
    'CODE_OPERATION_ID CODE_ALREADY_ATTEMPTED CODE_POST_STATE CODE_FAILED_ROLLED_BACK_DB_PRESERVED '
    'CODE_ROLLBACK_FAILED HOST_BASELINE OLD_BASELINE OLD_SOURCE_CHANGED OLD_UNIT_CHANGED OLD_UNIT_NOT_ENABLED '
    'DEPENDENCY_NOT_ACTIVE BOOTSTRAP_REQUEST BOOTSTRAP_NOT_FINISHED BOOTSTRAP_CHANGED TMPFILES_CHANGED '
    'CODE_INFRASTRUCTURE_CHANGED CODE_SCHEMA_CHANGED CODE_OVERRIDE_CHANGED CODE_SOURCE_PATH CODE_SOURCE_MODE_CHANGED '
    'CODE_SOURCE_REMOVED CODE_SCOPE_CHANGED SCHEMA_CONTRACT_MISSING CODE_PROBE_SOURCE CODE_ROUTE_STATUS '
    'CODE_SERVICE_NOT_ACTIVE CODE_SERVICE_NOT_ENABLED VERIFIED_WRITE_AUTH_NOT_REQUIRED '
    'ACCOUNT_WRITER_NOT_STOPPED DB_IDENTITY DB_OLD_SCHEMA DB_SNAPSHOT_INTEGRITY DB_SNAPSHOT_CHANGED '
    'WARM_CONTAINER_ID WARM_CONTAINER_REMAINS WARM_CREATE_UNCONFIRMED WARM_CLEANUP_FAILED SOURCE_WARM_FAILED '
    'ORG_NOT_ACCEPTED MANAGEMENT_FIELD_MISSING ACCOUNTS_NOT_ACCEPTED CATALOG_NOT_ACCEPTED '
    'COMMAND_FAILED DIRECTORY_POLICY FILE_PATH FILE_POLICY PREPARED_MANIFEST PREPARED_DIGEST '
    'PREPARED_FILE_CHANGED PREPARED_IMAGE PREPARED_IMAGE_CHANGED SOURCE_NOT_READY UNIT_CHANGED ENGINE_NOT_READY '
    'PAGE_NOT_READY UNAUTHENTICATED_READ_NOT_DENIED BUSINESS_WRITE_NOT_DENIED SERVICES_NOT_READY'.split())


def _error_labels(error):
    kind = type(error).__name__
    code = error.args[0] if len(error.args) == 1 and isinstance(error.args[0], str) else None
    return {'error_kind':kind if kind in FAILURE_KINDS else 'OtherError',
            'error_code':code if code in FAILURE_CODES else 'UNRECOGNIZED'}


def _capture_failure(error, prefix='failed'):
    details = {'stage':STAGE if STAGE in FAILURE_STAGES else 'unknown',
               'operation':OPERATION if OPERATION in FAILURE_OPERATIONS else 'unknown', **_error_labels(error)}
    return {prefix+'_'+key:value for key,value in details.items()}


def failure_report(error):
    """Fixed labels only: exception text, command args, stderr, paths and env never escape."""
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
            or TARGET_COMMIT == OLD_COMMIT):
        raise ValueError('CODE_TARGET_NOT_PINNED')
    if not isinstance(package, dict) or package.get('operation') != 'code-prepare':
        raise ValueError('CODE_PACKAGE')
    release.validate_package(dict(package, operation='upgrade-prepare'))
    if package['source_commit'] != TARGET_COMMIT:
        raise ValueError('CODE_TARGET')
    if package['baseline'] != EXPECTED_BASELINE:
        raise ValueError('CODE_BASELINE')
    return package


def bootstrap_state(release, upgrade):
    """Require durable prior completion; snapshot only, never replay or repair approvals."""
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
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('SCHEMA_VERSION', '_SCHEMA'):
                    selected[target.id] = ast.dump(node, include_attributes=False)
        elif isinstance(node, ast.FunctionDef) and node.name == '_migrate':
            selected[node.name] = ast.dump(node, include_attributes=False)
    if set(selected) != {'SCHEMA_VERSION', '_SCHEMA', '_migrate'}:
        raise ValueError('SCHEMA_CONTRACT_MISSING')
    return selected


def compatible_source(old, new, upgrade):
    # This read-side summary release cannot change storage, runtime, infrastructure or credentials.
    read = lambda path: upgrade.read_file(path, mode=0o644, maximum=1024*1024, minimum=0)
    for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                 'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
                 'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py'):
        if read(old/name) != read(new/name):
            raise ValueError('CODE_INFRASTRUCTURE_CHANGED')
    before, after = read(old/'naver_engine/store.py'), read(new/'naver_engine/store.py')
    if before != after:
        raise ValueError('CODE_SCHEMA_CHANGED')
    for name in ('engine', 'relay'):
        before = upgrade.read_file(old/('preview-'+name+'.override.yml'), mode=0o600)
        after = upgrade.read_file(new/('preview-'+name+'.override.yml'), mode=0o600)
        if after != target_override(before, name):
            raise ValueError('CODE_OVERRIDE_CHANGED')
    compatible_code_scope(old, new, upgrade)


def target_override(before, name):
    return before.replace(OLD_COMMIT.encode(), TARGET_COMMIT.encode())


def stopped_writer(release, lifecycle, path, images, unit):
    """Prove no writer; a failed supervisor alone is neither success nor failure.

    images maps only pinned source commits to their prepared engine/relay digests.
    Rollback may encounter either source after a partial container recreation.
    """
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
    """Called only after both services stop; no live-copy or recovery-key use."""
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
            if source.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone() != ('8',):
                raise ValueError('DB_OLD_SCHEMA')
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
    """Keep failed files recoverable; restore the matching schema8 snapshot before the old image."""
    path, digest = snapshot
    raw = upgrade.read_file(path, mode=0o600, maximum=1024**3)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('DB_SNAPSHOT_CHANGED')
    release.trusted_dir(DATA, uid=10001, gid=10001, mode=0o750)
    # Keep rename on the same filesystem even when /srv and /var use separate volumes.
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
                          'catalog_total':store.account_catalog()['total'],'accounts_total':accounts.rows,'schema':S.SCHEMA_VERSION}))
except Exception as error:
    code=error.args[0] if len(error.args)==1 and isinstance(error.args[0],str) else None
    allowed={'ORG_NOT_ACCEPTED','MANAGEMENT_FIELD_MISSING','ACCOUNTS_NOT_ACCEPTED','CATALOG_NOT_ACCEPTED'}
    print(json.dumps({'ok':False,'warm_step':step,'warm_error_code':code if code in allowed else 'UNRECOGNIZED'}))
    sys.exit(1)
'''


def warm_sources(path, release):
    global STAGE, OPERATION
    STAGE = 'account_sources_warm'
    check = release.compose(path, 'engine')
    name = 'naver-warm-'+TARGET_COMMIT+'-'+uuid.uuid4().hex
    check[check.index('--project-name')+1] = name
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
                    'warm_config','warm_store_open','warm_org_sync','warm_org_contract',
                    'warm_accounts_sync','warm_catalog_sync','warm_summary'}:
                OPERATION = result['warm_step']
            code = result.get('warm_error_code') if isinstance(result, dict) else None
            raise ValueError(code if isinstance(code,str) and code in FAILURE_CODES else 'SOURCE_WARM_FAILED')
        if (result.get('ok') is not True or result.get('org_fresh') is not True or result.get('schema') != 8
                or type(result.get('catalog_total')) is not int or result['catalog_total'] < 1
                or type(result.get('management_count')) is not int or result['management_count'] < 1):
            raise ValueError('SOURCE_WARM_FAILED')
        return result
    except Exception as error:
        error.failure_details = _capture_failure(error)
        failure = error.failure_details
        raise
    finally:
        # Timeout kills only the CLI, not Docker. Verify and remove this exact one-off writer first.
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
                if meta != {'source':TARGET_COMMIT, 'project':name, 'user':'10001:10001'}:
                    raise ValueError('WARM_CONTAINER_ID')
                OPERATION = 'warm_cleanup_remove'
                release.command(['docker', 'rm', '--force', found], timeout=45)
            elif identity is None:
                # An in-flight Docker create may complete after a CLI timeout.
                raise ValueError('WARM_CREATE_UNCONFIRMED')
            OPERATION = 'warm_cleanup_absence'
            if release.command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                    'name=^/'+name+'$', '--format', '{{.ID}}'], timeout=30).strip():
                raise ValueError('WARM_CONTAINER_REMAINS')
        except Exception as error:
            refused = RuntimeError('WARM_CLEANUP_FAILED')
            refused.failure_details = {**(failure or _capture_failure(error)), **_capture_failure(error,'cleanup')}
            raise refused from None


def compatible_code_scope(old, new, upgrade):
    """Only the reviewed runtime delta may differ; no deletions or filesystem escapes."""
    def inventory(root):
        files = {}
        for path in root.rglob('*'):
            if path.is_symlink() or path.resolve() != path:
                raise ValueError('CODE_SOURCE_PATH')
            if path.is_dir():
                continue
            name = path.relative_to(root).as_posix()
            if name in ('preview-engine.override.yml', 'preview-relay.override.yml'):
                continue  # Separately compared byte-for-byte with only the commit substituted.
            files[name] = (stat.S_IMODE(path.stat().st_mode),
                           upgrade.read_file(path, maximum=1024*1024, minimum=0))
        return files
    before, after = inventory(old), inventory(new)
    if before.keys() - after.keys():
        raise ValueError('CODE_SOURCE_REMOVED')
    for name, value in after.items():
        if name in before and before[name][0] != value[0]:
            raise ValueError('CODE_SOURCE_MODE_CHANGED')
        if before.get(name) != value and name not in CODE_PATHS | TEST_PATHS:
            raise ValueError('CODE_SCOPE_CHANGED')


def probe(release, source_commit, upgrade):
    """The old rollback contract stays unchanged; only the pinned target gains auth gates."""
    if source_commit == OLD_COMMIT:
        # The deployed base already has authenticated verified-link and collection routes.
        source_commit = TARGET_COMMIT
    if (not isinstance(TARGET_COMMIT, str) or not re.fullmatch('[0-9a-f]{40}', TARGET_COMMIT)
            or source_commit != TARGET_COMMIT):
        raise ValueError('CODE_PROBE_SOURCE')
    def request(path, route, method='GET'):
        status, headers, body = release.unix_request(path, route, method)
        if route == '/api/naver-auto/links/confirm' and method == 'POST':
            if status != 401:
                raise ValueError('VERIFIED_WRITE_AUTH_NOT_REQUIRED')
            # Real 401 was checked above; retain the legacy probe's other checks verbatim.
            return 403, headers, body
        return status, headers, body
    upgrade.probe(SimpleNamespace(unix_request=request))
    relay = '/run/metainc/naver-relay/relay.sock'
    for route, method, expected in (
            ('/collection/status', 'GET', 401), ('/collection/request', 'POST', 401),
            *((r, 'POST', 403) for r in ('/issues/1/resolve', '/issues/1/except',
                '/links/reject', '/links/revoke', '/links/preview', '/bell/1/read', '/bell/read-all'))):
        if release.unix_request(relay, '/api/naver-auto' + route, method)[0] != expected:
            raise ValueError('CODE_ROUTE_STATUS')


def verify_running(path, receipt, release, lifecycle, upgrade):
    source = receipt.get('source_commit')
    if source not in (OLD_COMMIT, TARGET_COMMIT) or path.name != 'naver-' + source:
        raise ValueError('CODE_PROBE_SOURCE')
    probe(release, source, upgrade)
    lifecycle._snapshot(release, path, receipt['images'])
    for unit in (lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('CODE_SERVICE_NOT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('CODE_SERVICE_NOT_ENABLED')


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
    source, files = release.validate_payload(json.loads(plain, object_pairs_hook=release.unique), TARGET_COMMIT, package['source_tar_gz_sha256'])
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
        release.command(release.compose(destination, name)+['config','--quiet'])
    check = release.compose(destination, 'engine')
    check[check.index('--project-name')+1] = 'naver-check-'+TARGET_COMMIT+'-'+uuid.uuid4().hex
    release.command(check+['run','--rm','--no-deps','--pull','never','naver-engine','python','-m','naver_runtime','check-config'], timeout=60)
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
    global STAGE, OPERATION
    STAGE = 'code_apply_preflight'
    OPERATION = 'package'
    if not isinstance(package, dict) or set(package) != {'release', 'operation_id'}:
        raise ValueError('CODE_APPLY_FIELDS')
    identity = package['operation_id']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('CODE_OPERATION_ID')
    prepared = validate_package(package['release'], release)
    OPERATION = 'current_state'
    old_path, old_receipt, old_files, _, bootstrap = current_state(prepared, host, release, lifecycle, upgrade)
    OPERATION = 'target_manifest'
    path, receipt = upgrade.manifest(release, TARGET_COMMIT, prepared)
    OPERATION = 'compatible_source'
    compatible_source(old_path, path, upgrade)
    OPERATION = 'unit_manifest'
    new_files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    if new_files[lifecycle.TMPFILES] != old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    started = release.ROOT/'receipts'/('preview-start-'+TARGET_COMMIT+'.json')
    backup = release.ROOT/'receipts'/('code-upgrade-'+identity+'.json')
    if any(os.path.lexists(p) for p in (started, backup)):
        raise ValueError('CODE_ALREADY_ATTEMPTED')
    OPERATION = 'write_recovery_receipt'
    release.write_new(backup, json.dumps({'source_commit':OLD_COMMIT,'target_commit':TARGET_COMMIT,
        'images':old_receipt['images'],'units':{str(p):b.decode() for p,b in old_files.items() if p!=lifecycle.TMPFILES}}, sort_keys=True).encode())
    replaced = []
    snapshot = None
    source_status = None
    try:
        STAGE = 'code_stop_isolated'
        for unit in reversed(lifecycle.UNITS):
            name = 'engine' if unit == lifecycle.UNITS[0] else 'relay'
            OPERATION = 'stop_'+name
            release.command(['/usr/bin/systemctl','stop',unit], timeout=90)
            OPERATION = 'stop_check_'+name
            stopped_writer(release, lifecycle, old_path, {OLD_COMMIT:old_receipt['images']}, unit)
        OPERATION = 'bootstrap_check'
        if bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('BOOTSTRAP_CHANGED')
        STAGE = 'account_database_snapshot'
        OPERATION = 'snapshot_create'
        snapshot = db_snapshot(identity, release, upgrade)
        STAGE = 'account_sources_warm'
        OPERATION = 'warm_sources'
        source_status = warm_sources(path, release)
        STAGE = 'code_recreate'
        for name in ('engine','relay'):
            OPERATION = 'recreate_'+name
            release.command(release.compose(path,name)+['up','--no-start','--no-build','--force-recreate'], timeout=90)
        STAGE = 'code_replace_units'
        for unit in lifecycle.UNITS:
            OPERATION = 'replace_unit_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
            target = lifecycle.UNIT_DIR/unit
            replaced.append(target)
            upgrade.replace_unit(target, old_files[target], new_files[target], identity, release)
        OPERATION = 'daemon_reload'
        release.command(['/usr/bin/systemctl','daemon-reload'])
        STAGE = 'code_start'
        for unit in lifecycle.UNITS:
            OPERATION = 'start_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
            release.command(['/usr/bin/systemctl','start',unit], timeout=90)
        STAGE = 'code_verify'
        OPERATION = 'verify_running'
        verify_running(path, receipt, release, lifecycle, upgrade)
        OPERATION = 'post_state'
        if host.baseline() != prepared['baseline'] or bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('CODE_POST_STATE')
        result = {'ok':True,'stage':'internal_ready','source_commit':TARGET_COMMIT,'previous_commit':OLD_COMMIT,
                  'nginx_changed':False,'legacy_containers_unchanged':True,'bootstrap_unchanged':True,
                  'operation_id':identity,'unauthenticated_read_status':401,'business_post_status':403}
        result.update(database_snapshot_verified=True, database_schema=8, inventory_enabled=True,
                      source_status=source_status, rollback_requires_matching_database=True)
        OPERATION = 'write_started_receipt'
        release.write_new(started, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception as error:
        details = {key:value for key,value in failure_report(error).items()
                   if key.startswith(('failed_', 'cleanup_'))} or _capture_failure(error)
        STAGE = 'code_rollback'
        failed = str(error) == 'WARM_CLEANUP_FAILED'
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
        def restore(target):
            if upgrade.read_file(target, mode=0o644, maximum=32768) != old_files[target]:
                upgrade.replace_unit(target, new_files[target], old_files[target], identity+'-rollback', release)
        for unit in reversed(lifecycle.UNITS):
            OPERATION = 'stop_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
            attempt(release.command, ['/usr/bin/systemctl','stop',unit], timeout=90)
        for unit in lifecycle.UNITS:
            OPERATION = 'stop_check_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
            attempt(stopped_writer, release, lifecycle, old_path,
                    {OLD_COMMIT:old_receipt['images'], TARGET_COMMIT:receipt['images']}, unit)
        if not failed:
            for target in reversed(replaced):
                OPERATION = 'restore_unit_'+('engine' if target.name == lifecycle.UNITS[0] else 'relay')
                attempt(restore, target)
        if snapshot is not None and not failed:
            OPERATION = 'restore_database'
            attempt(restore_db, snapshot, identity, release, upgrade)
        OPERATION = 'old_manifest'
        if not failed and attempt(upgrade.manifest, release, OLD_COMMIT, started=True):
            for name in ('engine','relay'):
                OPERATION = 'recreate_'+name
                attempt(release.command, release.compose(old_path,name)+['up','--no-start','--no-build','--force-recreate'], timeout=90)
        if not failed:
            OPERATION = 'daemon_reload'
            attempt(release.command, ['/usr/bin/systemctl','daemon-reload'])
        if not failed:
            for unit in lifecycle.UNITS:
                OPERATION = 'start_'+('engine' if unit == lifecycle.UNITS[0] else 'relay')
                if not attempt(release.command, ['/usr/bin/systemctl','start',unit], timeout=90):
                    break
            OPERATION = 'verify_running'
            attempt(verify_running, old_path, old_receipt, release, lifecycle, upgrade)
        try:
            OPERATION = 'rollback_state'
            if host.baseline() != prepared['baseline'] or bootstrap_state(release, upgrade) != bootstrap:
                failed = True
        except Exception:
            failed = True
        if failed:
            for unit in reversed(lifecycle.UNITS):
                attempt(release.command, ['/usr/bin/systemctl','stop',unit], timeout=90)
            refused = RuntimeError('CODE_ROLLBACK_FAILED')
        else:
            refused = RuntimeError('CODE_FAILED_ROLLED_BACK_DB_PRESERVED')
        refused.failure_details = details
        raise refused from None
