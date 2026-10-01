"""Approved code-only transition from f7eb2e5. Never create bootstrap approvals."""
import ast
import json
import os
from pathlib import Path
import pwd
import re
import stat
import uuid

OLD_COMMIT = 'f7eb2e58aafad81e27978f175d83cca0eb5c5733'
TARGET_COMMIT = 'abf24060eaf907416439bf3e57d83242bb1b7bb5'
EXPECTED_BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
OLD_SOURCE_SHA256 = '23b4a2fe6d85ba52b082907801e8494eceb7a14ea32f33b8ac9ee296a9f93d0e'
CODE_PATHS = {'naver_engine/web.py', 'naver_engine/sync.py',
              'naver_runtime/__main__.py', 'naver_runtime/writer.py',
              'naver_runtime/scheduler.py', 'naver_runtime/collection_requests.py',
              'backend/naver_page/app.js', 'backend/naver_page/index.html'}
TEST_PATHS = {'naver_engine/tests/test_verified_collection.py',
              'naver_engine/tests/test_verified_collection_screen.py',
              'naver_engine/tests/verified_collection_browser.js',
              'naver_runtime/tests/test_collection_requests.py',
              'naver_runtime/tests/test_collection_integration.py'}
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
    # No schema migration, runtime/bootstrap contract, environment or infrastructure changes.
    read = lambda path: upgrade.read_file(path, mode=0o644, maximum=1024*1024, minimum=0)
    for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                 'deploy/naver-engine-backup.override.yml', 'Dockerfile.naver-engine',
                 'Dockerfile.naver-relay', 'backend/requirements.txt', 'naver_runtime/bootstrap.py'):
        if read(old/name) != read(new/name):
            raise ValueError('CODE_INFRASTRUCTURE_CHANGED')
    if schema_contract(read(old/'naver_engine/store.py')) != schema_contract(read(new/'naver_engine/store.py')):
        raise ValueError('CODE_SCHEMA_CHANGED')
    for name in ('engine', 'relay'):
        before = upgrade.read_file(old/('preview-'+name+'.override.yml'), mode=0o600)
        after = upgrade.read_file(new/('preview-'+name+'.override.yml'), mode=0o600)
        if after != before.replace(OLD_COMMIT.encode(), TARGET_COMMIT.encode()):
            raise ValueError('CODE_OVERRIDE_CHANGED')
    compatible_code_scope(old, new, upgrade)


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


def verify_running(path, receipt, release, lifecycle, upgrade):
    upgrade.probe(release)
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
    overrides = {name: upgrade.read_file(old[0]/('preview-'+name+'.override.yml'), mode=0o600).decode().replace(OLD_COMMIT, TARGET_COMMIT)
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
    try:
        STAGE = 'code_stop_isolated'
        for unit in reversed(lifecycle.UNITS):
            release.command(['/usr/bin/systemctl','stop',unit], timeout=90)
        if bootstrap_state(release, upgrade) != bootstrap:
            raise ValueError('BOOTSTRAP_CHANGED')
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
        release.write_new(started, json.dumps(result, sort_keys=True).encode())
        return result
    except Exception:
        STAGE = 'code_rollback'
        failed = False
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
        for target in reversed(replaced):
            attempt(restore, target)
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
