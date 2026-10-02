"""Pinned account-first release with a stopped-writer schema rollback snapshot."""
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

OLD_COMMIT = 'abf24060eaf907416439bf3e57d83242bb1b7bb5'
TARGET_COMMIT = 'e1c4b3526db55d78175a1d6598f3403fdb9398f7'
EXPECTED_BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
OLD_SOURCE_SHA256 = '99482e833f9bb1035bc2c87e2fd662cc3900c908f5276b7e936ad68d279111e5'
STORE_HASHES = ('a3ba0734762ae256ef564f824c0b04b8ea3def01da45070bc92623d6d1c79d19',
                'd674c3224097d61ac173aa87fa59b3fd80c2f6433371c8e90339b00958e64a8f')
CODE_PATHS = {'backend/app/naver_auto/org_snapshot.py', 'backend/app/naver_auto/scope.py',
    'backend/naver_page/app.css', 'backend/naver_page/app.js', 'backend/naver_page/index.html',
    'deploy/naver-erp-tunnel/be-nginx.conf', 'naver_engine/erp_read.py', 'naver_engine/fields.py',
    'naver_engine/handles.py', 'naver_engine/inventory.py', 'naver_engine/inventory_reads.py',
    'naver_engine/naver_read.py', 'naver_engine/store.py', 'naver_engine/views.py', 'naver_engine/web.py',
    'naver_runtime/__main__.py', 'naver_runtime/config.py', 'naver_runtime/erp_tunnel_transport.py',
    'naver_runtime/scheduler.py'}
TEST_PATHS = {'deploy/naver-erp-tunnel/test_policy.py',
    *('naver_engine/tests/'+name for name in ('inventory_screen_browser.js', 'screen_browser.js',
        'test_account_catalog.py', 'test_alerts.py', 'test_board_rows.py', 'test_inventory_name_index.py',
        'test_inventory_reads.py', 'test_inventory_screen.py', 'test_metrics.py', 'test_naver_ids_snapshot.py',
        'test_owner_verification.py', 'test_screen.py', 'test_sync.py', 'test_web.py')),
    *('naver_runtime/tests/'+name for name in ('test_config.py', 'test_erp_tunnel_transport.py',
        'test_guardrails.py', 'test_scheduler.py'))}
DATA = Path('/var/lib/metainc/naver-engine')
STAGE = 'input'


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
    # Infrastructure and credentials stay identical. Only the exact reviewed schema 7->8 is allowed.
    read = lambda path: upgrade.read_file(path, mode=0o644, maximum=1024*1024, minimum=0)
    for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                 'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
                 'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py'):
        if read(old/name) != read(new/name):
            raise ValueError('CODE_INFRASTRUCTURE_CHANGED')
    before, after = read(old/'naver_engine/store.py'), read(new/'naver_engine/store.py')
    if schema_contract(before) != schema_contract(after):
        if tuple(hashlib.sha256(body).hexdigest() for body in (before, after)) != STORE_HASHES:
            raise ValueError('CODE_SCHEMA_CHANGED')
    for name in ('engine', 'relay'):
        before = upgrade.read_file(old/('preview-'+name+'.override.yml'), mode=0o600)
        after = upgrade.read_file(new/('preview-'+name+'.override.yml'), mode=0o600)
        if after != target_override(before, name):
            raise ValueError('CODE_OVERRIDE_CHANGED')
    compatible_code_scope(old, new, upgrade)


def target_override(before, name):
    body = before.replace(OLD_COMMIT.encode(), TARGET_COMMIT.encode())
    if name == 'engine':
        body += b'      NAVER_ENGINE_INVENTORY_ENABLED: "true"\n'
    return body


def db_snapshot(identity, release, upgrade):
    """Called only after both services stop; no live-copy or recovery-key use."""
    release.trusted_dir(DATA, uid=10001, gid=10001, mode=0o750)
    db = DATA/'engine.db'
    upgrade.read_file(db, uid=10001, gid=10001, mode=0o600, maximum=1024**3)
    destination = release.ROOT/'receipts'/('account-db-'+identity+'.sqlite')
    fd = os.open(db, os.O_RDWR | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (10001, 10001, 0o600)
                or (info.st_dev, info.st_ino) != (db.stat().st_dev, db.stat().st_ino)):
            raise ValueError('DB_IDENTITY')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release.write_new(destination, b'')
        with closing(sqlite3.connect(db.as_uri()+'?mode=ro', uri=True)) as source, closing(sqlite3.connect(destination)) as target:
            if source.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone() != ('7',):
                raise ValueError('DB_OLD_SCHEMA')
            source.backup(target)
            if target.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('DB_SNAPSHOT_INTEGRITY')
        os.chmod(destination, 0o600)
        durable = os.open(destination, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(durable)
        finally:
            os.close(durable)
        raw = upgrade.read_file(destination, mode=0o600, maximum=1024**3)
        return destination, hashlib.sha256(raw).hexdigest()
    finally:
        os.close(fd)


def restore_db(snapshot, identity, release, upgrade):
    """Keep the failed schema8 files recoverable; restore matching schema7 before old image."""
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
from naver_engine import store as S,sync as Y,inventory as I,links as L
from naver_runtime.__main__ import dependencies,InterruptibleClock
from naver_runtime.config import Config
clock=InterruptibleClock(threading.Event())
config=Config.from_env(os.environ)
options=dependencies(config,os.environ,clock)
with S.open_writer(config.db) as store:
    org=Y.sync_org(options['erp_factory'](),store,clock.now())
    if org.outcome!='accepted': raise ValueError('ORG_NOT_ACCEPTED')
    body=store.org_current()['body']
    if not body['employees'] or any(type(e.get('is_management')) is not bool for e in body['employees']):
        raise ValueError('MANAGEMENT_FIELD_MISSING')
    accounts=L.sync_accounts(options['naver_factory'](),store,clock.now())
    if accounts.outcome!='accepted': raise ValueError('ACCOUNTS_NOT_ACCEPTED')
    catalog=I.sync_catalog(options['erp_factory'](),store,clock.now())
    if store.account_catalog_status().get('state')!='accepted': raise ValueError('CATALOG_NOT_ACCEPTED')
    print(json.dumps({'ok':True,'org_fresh':True,'management_count':sum(e['is_management'] for e in body['employees']),
                      'catalog_total':store.account_catalog()['total'],'accounts_total':accounts.rows,'schema':S.SCHEMA_VERSION}))
'''


def warm_sources(path, release):
    check = release.compose(path, 'engine')
    name = 'naver-warm-'+TARGET_COMMIT+'-'+uuid.uuid4().hex
    check[check.index('--project-name')+1] = name
    identity = None
    try:
        identity = release.command(check+['run', '--detach', '--no-deps', '--pull', 'never',
            '--name', name, '--label', 'metainc.naver.warm.source='+TARGET_COMMIT,
            '--entrypoint', 'python', 'naver-engine', '-I', '-B', '-c', WARM_SCRIPT], timeout=60).decode().strip()
        if not re.fullmatch('[0-9a-f]{64}', identity):
            raise ValueError('WARM_CONTAINER_ID')
        if release.command(['docker', 'wait', identity], timeout=180).strip() != b'0':
            raise ValueError('SOURCE_WARM_FAILED')
        result = json.loads(release.command(['docker', 'logs', identity], timeout=30))
        if (result.get('ok') is not True or result.get('org_fresh') is not True or result.get('schema') != 8
                or type(result.get('catalog_total')) is not int or result['catalog_total'] < 1
                or type(result.get('management_count')) is not int or result['management_count'] < 1):
            raise ValueError('SOURCE_WARM_FAILED')
        return result
    finally:
        # Timeout kills only the CLI, not Docker. Verify and remove this exact one-off writer first.
        try:
            found = release.command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                'name=^/'+name+'$', '--format', '{{.ID}}'], timeout=30).decode().strip()
            if found:
                if not re.fullmatch('[0-9a-f]{64}', found):
                    raise ValueError('WARM_CONTAINER_ID')
                fmt = '{"source":{{json (index .Config.Labels "metainc.naver.warm.source")}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"user":{{json .Config.User}}}'
                meta = json.loads(release.command(['docker', 'inspect', '--format', fmt, found]))
                if meta != {'source':TARGET_COMMIT, 'project':name, 'user':'10001:10001'}:
                    raise ValueError('WARM_CONTAINER_ID')
                release.command(['docker', 'rm', '--force', found], timeout=45)
            elif identity is None:
                # An in-flight Docker create may complete after a CLI timeout.
                raise ValueError('WARM_CREATE_UNCONFIRMED')
            if release.command(['docker', 'ps', '--all', '--no-trunc', '--filter',
                    'name=^/'+name+'$', '--format', '{{.ID}}'], timeout=30).strip():
                raise ValueError('WARM_CONTAINER_REMAINS')
        except Exception:
            raise RuntimeError('WARM_CLEANUP_FAILED') from None


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
    global STAGE
    STAGE = 'code_apply_preflight'
    if not isinstance(package, dict) or set(package) != {'release', 'operation_id'}:
        raise ValueError('CODE_APPLY_FIELDS')
    identity = package['operation_id']
    if not isinstance(identity, str) or not re.fullmatch('[0-9a-f]{32}', identity):
        raise ValueError('CODE_OPERATION_ID')
    prepared = validate_package(package['release'], release)
    old_path, old_receipt, old_files, _, bootstrap = current_state(prepared, host, release, lifecycle, upgrade)
    path, receipt = upgrade.manifest(release, TARGET_COMMIT, prepared)
    compatible_source(old_path, path, upgrade)
    new_files = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    if new_files[lifecycle.TMPFILES] != old_files[lifecycle.TMPFILES]:
        raise ValueError('TMPFILES_CHANGED')
    started = release.ROOT/'receipts'/('preview-start-'+TARGET_COMMIT+'.json')
    backup = release.ROOT/'receipts'/('code-upgrade-'+identity+'.json')
    if any(os.path.lexists(p) for p in (started, backup)):
        raise ValueError('CODE_ALREADY_ATTEMPTED')
    release.write_new(backup, json.dumps({'source_commit':OLD_COMMIT,'target_commit':TARGET_COMMIT,
        'images':old_receipt['images'],'units':{str(p):b.decode() for p,b in old_files.items() if p!=lifecycle.TMPFILES}}, sort_keys=True).encode())
    replaced = []
    snapshot = None
    source_status = None
    try:
        STAGE = 'code_stop_isolated'
        for unit in reversed(lifecycle.UNITS):
            release.command(['/usr/bin/systemctl','stop',unit], timeout=90)
            if lifecycle._state(release, unit, 'ActiveState') != 'inactive':
                raise ValueError('ACCOUNT_WRITER_NOT_STOPPED')
        if bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('BOOTSTRAP_CHANGED')
        STAGE = 'account_database_snapshot'
        snapshot = db_snapshot(identity, release, upgrade)
        STAGE = 'account_sources_warm'
        source_status = warm_sources(path, release)
        for name in ('engine','relay'):
            release.command(release.compose(path,name)+['up','--no-start','--no-build','--force-recreate'], timeout=90)
        for unit in lifecycle.UNITS:
            target = lifecycle.UNIT_DIR/unit
            replaced.append(target)
            upgrade.replace_unit(target, old_files[target], new_files[target], identity, release)
        release.command(['/usr/bin/systemctl','daemon-reload'])
        for unit in lifecycle.UNITS:
            release.command(['/usr/bin/systemctl','start',unit], timeout=90)
        STAGE = 'code_verify'
        verify_running(path, receipt, release, lifecycle, upgrade)
        if host.baseline() != prepared['baseline'] or bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('CODE_POST_STATE')
        result = {'ok':True,'stage':'internal_ready','source_commit':TARGET_COMMIT,'previous_commit':OLD_COMMIT,
                  'nginx_changed':False,'legacy_containers_unchanged':True,'bootstrap_unchanged':True,
                  'operation_id':identity,'unauthenticated_read_status':401,'business_post_status':403}
        result.update(database_snapshot_verified=True, database_schema=8, inventory_enabled=True,
                      source_status=source_status, rollback_requires_matching_database=True)
        release.write_new(started, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception as error:
        STAGE = 'code_rollback'
        failed = str(error) == 'WARM_CLEANUP_FAILED'
        def attempt(function, *args, **kwargs):
            nonlocal failed
            try:
                function(*args, **kwargs)
                return True
            except Exception:
                failed = True
                return False
        def restore(target):
            if upgrade.read_file(target, mode=0o644, maximum=32768) != old_files[target]:
                upgrade.replace_unit(target, new_files[target], old_files[target], identity+'-rollback', release)
        for unit in reversed(lifecycle.UNITS):
            attempt(release.command, ['/usr/bin/systemctl','stop',unit], timeout=90)
        if snapshot is not None:
            for unit in lifecycle.UNITS:
                try:
                    if lifecycle._state(release, unit, 'ActiveState') != 'inactive':
                        failed = True
                except Exception:
                    failed = True
        for target in reversed(replaced):
            attempt(restore, target)
        if snapshot is not None and not failed:
            attempt(restore_db, snapshot, identity, release, upgrade)
        if attempt(upgrade.manifest, release, OLD_COMMIT, started=True):
            for name in ('engine','relay'):
                attempt(release.command, release.compose(old_path,name)+['up','--no-start','--no-build','--force-recreate'], timeout=90)
        attempt(release.command, ['/usr/bin/systemctl','daemon-reload'])
        if not failed:
            for unit in lifecycle.UNITS:
                if not attempt(release.command, ['/usr/bin/systemctl','start',unit], timeout=90):
                    break
            attempt(verify_running, old_path, old_receipt, release, lifecycle, upgrade)
        try:
            if host.baseline() != prepared['baseline'] or bootstrap_state(release, upgrade) != bootstrap:
                failed = True
        except Exception:
            failed = True
        if failed:
            for unit in reversed(lifecycle.UNITS):
                attempt(release.command, ['/usr/bin/systemctl','stop',unit], timeout=90)
            raise RuntimeError('CODE_ROLLBACK_FAILED') from None
        raise RuntimeError('CODE_FAILED_ROLLED_BACK_DB_PRESERVED') from None
