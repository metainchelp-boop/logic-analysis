"""V26 scoped allowed-reference prompt; preserve the reviewed V24/V25 configuration chain, schema 11."""
import ast
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
OLD_COMMIT = 'da8e1c071f848898b8857221ac3d618786b5d0b7'
TARGET_COMMIT = '737a65952f2ddbc05a235cf2b139a4a11f4e7673'
EXPECTED_BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
OLD_SOURCE_SHA256 = 'bbf90eaf2b9377e58739bfa8038f3d43478c0150786e0d2c4745354eebc64e6f'
TARGET_SOURCE_SHA256 = '957ed0362ba9e3775a832c78011dc838c39297855d1f8ce901038d4e0c4e4450'
STORE_SHA256 = {'old': 'a78560f42cd3e4ee774135b3b148f0e518ce59a41f1c9d74ae475769aa643856', 'target': 'a78560f42cd3e4ee774135b3b148f0e518ce59a41f1c9d74ae475769aa643856'}
CODE_PATHS = {'naver_runtime/claude_provider.py'}
ADDED_SOURCE_PATHS = frozenset()
ENGINE_COMPOSE_SHA256 = '62e33c3d2815579a28031973b956cd36031171f26ead4e21ad2d72adfe2a5ef7'
TEST_PATHS = frozenset()
REMOVABLE_SOURCE_PREFIXES = ()
OWNER_ACTION_ROUTES = ('/issues/1/ack', '/issues/1/resolve', '/issues/1/except', '/bell/1/read', '/bell/read-all',
    '/settings/thresholds', *('/holds/'+k+'/confirm' for k in ('org', 'stages', 'accounts')), '/links/revoke')
TARGET_ACTION_ROUTES = ('/reports/notes', '/reports/strategy', '/automation/plans', '/automation/learning')
CLOSED_LINK_ROUTES = ('/links/reject', '/links/preview')
OLD_REPORT_UI = (89541, '24aba1490a188ab52e6cb22a412030ef42ed1d89da356cdea595f314180e6ead', 'text/javascript; charset=utf-8')
OLD_APP = (222000, 'f119f80f3fac01de107f7ce45a2ed39f5443dfc4a79db8f8c67ad06678549078', 'text/javascript; charset=utf-8')
SALES_GET_ROUTES = ('/sales/clients', '/sales/detail', '/sales/report')
REPORT_ASSETS = {'/naver/sso-bootstrap.js': (4588, 'b32369913287c49fa43fa210db73742f51c203066273b0334b4d6ebbb335b289', 'text/javascript; charset=utf-8'), '/naver/report-ui.js': (89541, '24aba1490a188ab52e6cb22a412030ef42ed1d89da356cdea595f314180e6ead', 'text/javascript; charset=utf-8'), '/naver/report-pdf.js': (37921, '454ccb5f20b3a8f125ac9f1e1cc765041a0d23e8a881fa11ccbfea5b5c848964', 'text/javascript; charset=utf-8'), '/naver/sales-ui.js': (17774, '00553781030990970c88dcd6d86c11730cf9c60cf9ce7a7963f2b091cd5aa2ff', 'text/javascript; charset=utf-8'), '/naver/automation-ui.js': (22976, '0828746fd2c60d43dd9e6f448782d1c46d543ecf2eb243590df8130ac5f6d2d3', 'text/javascript; charset=utf-8'), '/naver/learning-ui.js': (23619, '9cae047e4cf163d20e9e597df364da3565c88ed622b4cfe2d6ab651a1274ef7e', 'text/javascript; charset=utf-8'), '/naver/app.js': (222000, 'f119f80f3fac01de107f7ce45a2ed39f5443dfc4a79db8f8c67ad06678549078', 'text/javascript; charset=utf-8'), '/naver/app.css': (57115, '82174f6c25649692b68df439bb8f61329a218f6d052e77b8e9b0e9dd1970bee7', 'text/css; charset=utf-8'), '/naver/sales.css': (5905, 'f27843cb1e1e63a41d85f5f794035f47c62ec72dda5971f95dd9ed58226ba09d', 'text/css; charset=utf-8'), '/naver/vendor/report-pdf/NanumGothic-Regular.ttf.gz': (697020, '72d1bf88a642ede8ff7da422031106fc697ea4c79b1cfd2994bffc57df4dab07', 'application/gzip'), '/naver/vendor/report-pdf/pdf-lib-1.17.1.min.js': (525099, '0f9a5cad07941f0826586c94e089d89b918c46e5c17cf2d5a3c6f666e3bc694f', 'text/javascript; charset=utf-8'), '/naver/vendor/report-pdf/fontkit-1.1.1.umd.min.js': (758440, 'd8df561b9fba98e24f2e5130e40948809281bbbc55a20c412359f1a0a5eb35a6', 'text/javascript; charset=utf-8'), '/naver/vendor/report-pdf/sha256-1.0.0.min.js': (8156, 'a050d794e170699bd1a69d33908d0942c68901cb88347016064b60b240f0067e', 'text/javascript; charset=utf-8')}
OLD_REPORT_ASSETS = {**REPORT_ASSETS, '/naver/report-ui.js': OLD_REPORT_UI}
APPROVED_CONFIG_OPERATION_ID = '74c912dddf824fae99012849bc4c19a5'
CONFIG_SOURCE_COMMIT = '9ddb0a30e16e4177e8d419318a6f23eb6c206e2f'
CONFIG_ROLLBACK_COMMIT = '09b216f26509fed97179114ee97cb0d4169ce5f8'
CONFIG_SETTINGS = {'NAVER_CLAUDE_ENABLED': 'true', 'CLAUDE_MODEL': 'claude-sonnet-5-5',
    'NAVER_CLAUDE_MONTHLY_CAP_USD': 'unlimited', 'NAVER_CLAUDE_INPUT_USD_PER_MILLION': '2',
    'NAVER_CLAUDE_OUTPUT_USD_PER_MILLION': '10', 'NAVER_CLAUDE_TIMEOUT_SECONDS': '20'}
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
FAILURE_CODES |= frozenset({'RUNTIME_SECRET_CHANGED', 'CONFIG_PRESERVE_NOT_APPROVED', 'CONFIG_PRESERVE_PROOF', 'CONFIG_PRESERVE_DRIFT'})
FAILURE_STAGES |= frozenset({'code_prepare_runtime_config', 'code_prepare_runtime_postflight'})


CONFIG_PREDECESSOR_COMMIT = OLD_COMMIT
CONFIG_PREDECESSOR_ARCHIVE = OLD_SOURCE_SHA256
CONFIG_PREDECESSOR_PREPARE_RUN = '38126684468'
CONFIG_PRESERVATION_CHAIN = (
    ('10a46ddce2116e274e27fabaf73c7a94be6cda62', '6a2a1075b1b2c31f47d45d8afdd080e8da786e49c3fdf173e82e51c0a3e3705c', '38122455056', CONFIG_SOURCE_COMMIT),
    (CONFIG_PREDECESSOR_COMMIT, CONFIG_PREDECESSOR_ARCHIVE, CONFIG_PREDECESSOR_PREPARE_RUN, '10a46ddce2116e274e27fabaf73c7a94be6cda62'),
)

def preserve_approved_config(files, operation_id, active, release, upgrade):
    """Resolve one historical env against its committed server-local transaction.

    No environment, manifest, envelope, or journal is written. The authenticated
    ciphertext and six-field package retain their original identity. Only the
    verified runtime.env comparison value changes in memory; three other secrets
    keep the ordinary byte comparison. All proof bytes remain server-local.
    """
    if operation_id != APPROVED_CONFIG_OPERATION_ID or OLD_COMMIT != CONFIG_PREDECESSOR_COMMIT:
        raise ValueError('CONFIG_PRESERVE_NOT_APPROVED')
    root = release.ROOT / 'claude-config'
    folder = root / APPROVED_CONFIG_OPERATION_ID
    for parent in (root, folder):
        if parent.resolve() != parent:
            raise ValueError('CONFIG_PRESERVE_PROOF')
        release.trusted_dir(parent, mode=0o700)
    read = lambda path: upgrade.read_file(path, mode=0o600, maximum=32768)
    journal_body = read(folder / 'journal.json')
    journal = json.loads(journal_body, object_pairs_hook=release.unique)
    paths = [release.SECRET_ROOT / 'runtime.env'] + [release.ROOT / 'receipts' / ('preview-' + source + '.json')
        for source in (CONFIG_SOURCE_COMMIT, CONFIG_ROLLBACK_COMMIT)]
    if (not isinstance(journal, dict) or set(journal) != {'schema', 'operation_id', 'source_commit',
            'rollback_commit', 'baseline', 'state', 'files', 'images', 'before'} or type(journal['schema']) is not int
            or journal['schema'] != 1 or journal['operation_id'] != APPROVED_CONFIG_OPERATION_ID
            or journal['source_commit'] != CONFIG_SOURCE_COMMIT or journal['rollback_commit'] != CONFIG_ROLLBACK_COMMIT
            or journal['baseline'] != EXPECTED_BASELINE or journal['state'] != 'committed'
            or not isinstance(journal['images'], dict)
            or set(journal['images']) != {'engine', 'relay'} or not isinstance(journal['before'], dict)
            or set(journal['before']) != {'engine', 'relay'} or not isinstance(journal['files'], list)
            or len(journal['files']) != 3):
        raise ValueError('CONFIG_PRESERVE_PROOF')
    for name, image in journal['images'].items():
        before = journal['before'][name]
        if (not isinstance(image, str) or not re.fullmatch('sha256:[0-9a-f]{64}', image)
                or not isinstance(before, dict) or set(before) != {'id', 'image', 'running', 'started', 'restarts', 'project', 'service'}
                or not isinstance(before['id'], str) or not re.fullmatch('[0-9a-f]{64}', before['id'])
                or before['image'] != image or before['running'] is not True or type(before['restarts']) is not int
                or before['restarts'] != 0 or not isinstance(before['started'], str) or not before['started']
                or before['project'] != 'naver-' + name or before['service'] != 'naver-' + name):
            raise ValueError('CONFIG_PRESERVE_PROOF')
    historical_path, historical = upgrade.manifest(release, CONFIG_SOURCE_COMMIT, started=True)
    if journal['images'] != historical['images']:
        raise ValueError('CONFIG_PRESERVE_PROOF')
    old, new = [], []
    for index, (row, path) in enumerate(zip(journal['files'], paths)):
        if (not isinstance(row, dict) or set(row) != {'path', 'old', 'new'} or row['path'] != str(path)
                or any(not isinstance(row[key], str) or not re.fullmatch('[0-9a-f]{64}', row[key]) for key in ('old', 'new'))):
            raise ValueError('CONFIG_PRESERVE_PROOF')
        old.append(read(folder / ('old-' + str(index))))
        new.append(read(folder / ('new-' + str(index))))
        if hashlib.sha256(old[-1]).hexdigest() != row['old'] or hashlib.sha256(new[-1]).hexdigest() != row['new']:
            raise ValueError('CONFIG_PRESERVE_PROOF')
        if read(path) != new[-1]:
            raise ValueError('CONFIG_PRESERVE_DRIFT')
    allowed = {key.encode() for key in CONFIG_SETTINGS} | {b'ANTHROPIC_API_KEY'}
    unrelated = lambda body: b''.join(line for line in body.splitlines(keepends=True) if line.split(b'=', 1)[0] not in allowed)
    if (b'\x00' in old[0] or b'\x00' in new[0] or not old[0].endswith(b'\n') or not new[0].endswith(b'\n')
            or unrelated(old[0]) != unrelated(new[0])):
        raise ValueError('CONFIG_PRESERVE_PROOF')
    configured = {}
    for line in new[0].splitlines():
        name, separator, value = line.partition(b'=')
        if name in allowed:
            if not separator or name in configured:
                raise ValueError('CONFIG_PRESERVE_PROOF')
            configured[name] = value
    if (set(configured) != allowed or any(configured[key.encode()] != value.encode() for key, value in CONFIG_SETTINGS.items())
            or not re.fullmatch(rb'[\x21-\x7e]{1,4096}', configured[b'ANTHROPIC_API_KEY'])):
        raise ValueError('CONFIG_PRESERVE_PROOF')
    for index, source in enumerate((CONFIG_SOURCE_COMMIT, CONFIG_ROLLBACK_COMMIT), 1):
        before = json.loads(old[index], object_pairs_hook=release.unique)
        after = json.loads(new[index], object_pairs_hook=release.unique)
        if (not isinstance(before, dict) or before.get('ok') is not True or before.get('stage') != 'prepared'
                or before.get('source_commit') != source or not isinstance(before.get('files'), dict)
                or before['files'].get(str(paths[0])) != journal['files'][0]['old']):
            raise ValueError('CONFIG_PRESERVE_PROOF')
        before['files'][str(paths[0])] = journal['files'][0]['new']
        if before != after:
            raise ValueError('CONFIG_PRESERVE_PROOF')
    # Both historical manifests must still validate against the current live files.
    upgrade.manifest(release, CONFIG_SOURCE_COMMIT, started=True)
    upgrade.manifest(release, CONFIG_ROLLBACK_COMMIT, started=True)
    chain_bodies = []
    for index, (source, archive, run_id, previous) in enumerate(CONFIG_PRESERVATION_CHAIN):
        _, bridge = upgrade.manifest(release, source, started=True)
        bridge_file = release.ROOT / 'receipts' / ('preview-' + source + '.json')
        bridge_body = read(bridge_file)
        started_body = read(bridge_file.with_name('preview-start-' + source + '.json'))
        started = json.loads(started_body, object_pairs_hook=release.unique)
        if ((index == len(CONFIG_PRESERVATION_CHAIN) - 1 and bridge != active)
                or json.loads(bridge_body, object_pairs_hook=release.unique) != bridge
                or bridge.get('runtime_environment_preserved') is not True
                or bridge.get('config_operation_id') != APPROVED_CONFIG_OPERATION_ID
                or bridge.get('source_commit') != source
                or bridge.get('package', {}).get('source_commit') != source
                or bridge['package'].get('source_tar_gz_sha256') != archive
                or bridge['package'].get('baseline') != EXPECTED_BASELINE
                or bridge['package'].get('run_id') != run_id
                or bridge.get('files', {}).get(str(paths[0])) != journal['files'][0]['new']
                or started.get('ok') is not True or started.get('stage') != 'internal_ready'
                or started.get('source_commit') != source
                or started.get('previous_commit') != previous
                or started.get('database_policy') != 'preserve-in-place'
                or started.get('database_opened_by_controller') is not False):
            raise ValueError('CONFIG_PRESERVE_PROOF')
        chain_bodies.extend((bridge_body, started_body))
    candidates = [item for item in files if item['path'] == str(paths[0])]
    if len(candidates) != 1 or candidates[0]['content'].encode() != old[0]:
        raise ValueError('RUNTIME_SECRET_CHANGED')
    resolved = [dict(item, content=new[0].decode()) if item is candidates[0] else dict(item) for item in files]
    return resolved, (journal_body, tuple(old), tuple(new), tuple(chain_bodies))
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
        for name in ('sso-bootstrap.js','report-ui.js','report-pdf.js','app.js','app.css','sales-ui.js','sales.css','automation-ui.js','learning-ui.js')):
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
    # V26 changes only the provider prompt; both source trees retain every existing path.
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
        for route in SALES_GET_ROUTES:
            if release.unix_request(relay, '/api/naver-auto'+route, 'GET')[0] != 401:
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
def prepare(package, host, release, lifecycle, upgrade, *, approved_config_operation_id=None):
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
    if config_proof is not None:
        receipt.update(runtime_environment_preserved=True, config_operation_id=approved_config_operation_id)
    release.write_new(receipt_path, json.dumps(receipt, sort_keys=True).encode())
    upgrade.manifest(release, TARGET_COMMIT, package)
    result = {'ok':True,'stage':'prepared','source_commit':TARGET_COMMIT,'previous_commit':OLD_COMMIT,
              'services_started':False,'nginx_changed':False,'bootstrap_unchanged':True}
    if config_proof is not None:
        result.update(runtime_environment_preserved=True, config_operation_id=approved_config_operation_id)
    return result
def apply(package, host, release, lifecycle, upgrade):
    # This release only supports the separate preserve-in-place code-only entry point.
    raise ValueError("CODE_ONLY_REQUIRED")
