"""Fixed source4d current-inspection read; no collector, writer or provider call.

Only a byte-authenticated transport may bind the four approved public receipts
and its externally authenticated self identity in memory. The frozen reader's
five slots remain None on disk. This module never reads an environment file.
"""
import hashlib
import json
import os
from pathlib import Path
import pwd
import re

SOURCE = '4d5802360c1ba23aa801b1145ca8483db3edd35f'
PREVIOUS = '32878e8ecec616772b619c23e796931d44f0bee1'
ARCHIVE = '1db45b8e54e562bd83c12b4cf53c791426ea45fccd85162bfb0e5f27179873fe'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
MODE = 'daily-current-source-4d-v3-fixed-0710'
PREPARE_RUN = '38313890510'
APPLY_RUN = '38314514027'
APPLY_OPERATION = '93a3d17df45942068faf936ee71c57b9'
CONFIG_OPERATION = '74c912dddf824fae99012849bc4c19a5'
P9_CONTROLLER_SHA256 = '77e9162979683b067a34d7ed9e9589030cebb0466e49dcdb65f9b28e57f85968'
READER_SHA256 = '799c04ca239cf11d17776fc3a6e2cd291b642e475415a8c3cbe3cd9b4e954def'
APPROVED_RECEIPTS = {
    'native_receipt': '640d65e1de4110fe8d420e4a6dfc271f32d7febea57105d2b163c6ec81823e75',
    'canonical_receipt': 'b1ce7e10044552e9d50427ba15f1e201836d88747fd0d16476a917cf72dab5c8',
    'deployed_prepare': '1067d59f9cf14261a2622fad8fd19ef3a8b8741e5c9cfdcb8c7259aaec11d6fa',
    'deployed_apply': '9a5ab33a7624a0baf82a55fa0f56049eab229a0569f410f42329d527dc7298f2',
}
EXECUTION_PINS = dict.fromkeys((*APPROVED_RECEIPTS, 'controller_transport_identity'))
TRANSPORT_IDENTITY = None
NATIVE_AUTHORIZATION = None
EVENT_SELECTOR = {
    'possibility_id': 51952, 'ad_account_no': 1030001,
    'period_key': 'weekly:2026-10-05:2026-10-11', 'numeric_revision': 4,
    'strategy_revision': 0, 'reserved_from': '2026-10-13T07:10:00+09:00',
    'reserved_before': '2026-10-13T07:11:00+09:00',
}
MAX_OUTPUT = 16384
STAGE = 'input'
FAILURES = frozenset(('D3_PINS_PENDING D3_PIN_MISMATCH D3_PACKAGE D3_ROOT D3_BASELINE '
    'D3_RECEIPT D3_SOURCE_NOT_READY D3_COMPOSE D3_UNIT D3_CONTAINER D3_READER_SOURCE '
    'D3_READER_FAILED D3_OUTPUT D3_POST_ENGINE D3_POST_LEGACY D3_POST_PROOF D3_INTERNAL').split())


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bind_verified_evidence(evidence, transport_identity, native_authorization):
    """Called only after T verifies all raw/compact sources and its own raw SHA."""
    global EXECUTION_PINS, TRANSPORT_IDENTITY, NATIVE_AUTHORIZATION
    expected = dict(APPROVED_RECEIPTS, controller_transport_identity=transport_identity)
    if (type(evidence) is not dict or evidence != expected or set(evidence) != set(expected)
            or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in evidence.values())
            or type(native_authorization) is not dict or set(native_authorization) != {'head', 'run_id', 'receipt_sha256'}
            or type(native_authorization['head']) is not str or re.fullmatch('[0-9a-f]{40}', native_authorization['head']) is None
            or type(native_authorization['run_id']) is not int or native_authorization['run_id'] <= 0
            or type(native_authorization['receipt_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', native_authorization['receipt_sha256']) is None):
        raise ValueError('D3_PIN_MISMATCH')
    EXECUTION_PINS = dict(evidence)
    TRANSPORT_IDENTITY = transport_identity
    NATIVE_AUTHORIZATION = dict(native_authorization)


def require_pins():
    if (TRANSPORT_IDENTITY is None or NATIVE_AUTHORIZATION is None
            or set(EXECUTION_PINS) != {*APPROVED_RECEIPTS, 'controller_transport_identity'}
            or any(v is None for v in EXECUTION_PINS.values())):
        raise ValueError('D3_PINS_PENDING')
    if (EXECUTION_PINS != dict(APPROVED_RECEIPTS, controller_transport_identity=TRANSPORT_IDENTITY)
            or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in EXECUTION_PINS.values())):
        raise ValueError('D3_PIN_MISMATCH')


def package_expected():
    require_pins()
    return dict(mode=MODE, baseline=BASELINE, source_commit=SOURCE,
        source_tar_gz_sha256=ARCHIVE, p9_controller_sha256=P9_CONTROLLER_SHA256,
        native_run_id='38307879311', event_selector=EVENT_SELECTOR,
        evidence=EXECUTION_PINS, diagnostic_native=NATIVE_AUTHORIZATION)


def validate_package(package):
    require_pins()
    expected = package_expected()
    def typed_equal(left, right):
        return type(left) is type(right) and (set(left) == set(right) and all(
            typed_equal(left[k], right[k]) for k in right) if type(right) is dict else left == right)
    if not typed_equal(package, expected):
        raise ValueError('D3_PACKAGE')
    return package


def script(reader_source):
    require_pins()
    if type(reader_source) is not str or digest(reader_source.encode()) != READER_SHA256:
        raise ValueError('D3_READER_SOURCE')
    # No inherited key is inspected; only this new child process clears its env.
    # The fixed minute tests reservation time, never provider completion time.
    prefix = 'import hashlib,json,os,socket,sys\n'
    body = r'''
try:
 if os.geteuid()!=10001: raise ValueError('D3_ROOT')
 os.environ.clear()
 def refused(*a,**k): raise ValueError('D3_NETWORK_FORBIDDEN')
 socket.socket.connect=refused
 socket.socket.connect_ex=refused
 socket.create_connection=refused
 if hashlib.sha256(READER_SOURCE.encode()).hexdigest()!=READER_SHA: raise ValueError('D3_READER_SOURCE')
 scope={'__name__':'approved_daily_current_reader'}
 exec(compile(READER_SOURCE,'<approved-source4d-reader>','exec'),scope)
 if (scope['SOURCE']!=SOURCE or scope['EVENT_FROM'].isoformat()!='2026-10-13T07:10:00+09:00'
     or scope['EVENT_UNTIL'].isoformat()!='2026-10-13T07:11:00+09:00'
     or scope['PID']!=51952 or scope['ADNO']!=1030001 or len(scope['SOURCE_FILES'])!=163
     or any(v is not None for v in scope['EXECUTION_PINS'].values())): raise ValueError('D3_READER_SOURCE')
 scope['EXECUTION_PINS']=EVIDENCE
 result=scope['read_database']('/var/lib/naver-engine/engine.db','/opt/naver-engine')
 scope['validate_result'](result)
 encoded=json.dumps(result,sort_keys=True,allow_nan=False,separators=(',',':'))
 if len(encoded.encode())>16384: raise ValueError('D3_OUTPUT')
 print(encoded)
except Exception:
 print(json.dumps({'error_code':'D3_READER_FAILED'}))
'''
    return (prefix+'SOURCE='+repr(SOURCE)+'\nREADER_SHA='+repr(READER_SHA256)
        +'\nREADER_SOURCE='+repr(reader_source)+'\nEVIDENCE='+repr(EXECUTION_PINS)+'\n'+body).encode()


def read_receipts(release):
    require_pins()
    path, prepared_path = release.prepared_paths(SOURCE)
    started_path = prepared_path.with_name('preview-start-'+SOURCE+'.json')
    bodies = {}
    for item in (prepared_path, started_path):
        release.trusted_private_file(item)
        if item.stat().st_size > 32768:
            raise ValueError('D3_RECEIPT')
        bodies[item] = item.read_bytes()
    prepared, started = (json.loads(bodies[p], object_pairs_hook=release.unique)
                         for p in (prepared_path, started_path))
    expected_package = dict(baseline=BASELINE, source_commit=SOURCE,
                            source_tar_gz_sha256=ARCHIVE, run_id=PREPARE_RUN)
    if (prepared.get('ok') is not True or prepared.get('stage') != 'prepared'
            or prepared.get('source_commit') != SOURCE or type(prepared.get('package')) is not dict
            or any(type(prepared['package'].get(k)) is not type(v) or prepared['package'].get(k) != v
                   for k, v in expected_package.items())
            or prepared.get('config_operation_id') != CONFIG_OPERATION
            or prepared.get('runtime_environment_preserved') is not True
            or prepared.get('inventory_enabled') is not True or prepared.get('execution_enabled') is not False
            or prepared.get('runtime_flags_verified') is not True
            or any(type(started.get(k)) is not type(v) or started.get(k) != v for k, v in {
                'ok': True, 'stage': 'internal_ready', 'source_commit': SOURCE,
                'previous_commit': PREVIOUS, 'operation_id': APPLY_OPERATION, 'database_schema': 21,
                'database_policy': 'preserve-in-place', 'database_opened_by_controller': False,
                'source_warmup_performed': False, 'database_snapshot_verified': False,
                'rollback_requires_matching_database': False, 'saved_export_companion_preserved': True,
                'execution_enabled': False, 'runtime_flags_verified': True}.items())):
        raise ValueError('D3_SOURCE_NOT_READY')
    if type(prepared.get('images')) is not dict or set(prepared['images']) != {'engine', 'relay'}:
        raise ValueError('D3_CONTAINER')
    return path, prepared, bodies


def safe_runtime_files(path, prepared, release, lifecycle):
    require_pins()
    result = {}
    for name in ('compose.naver-engine.yml', 'compose.naver-relay.yml',
                 'preview-engine.override.yml', 'preview-relay.override.yml',
                 'deploy/naver-engine-backup.override.yml'):
        item = path/name
        if item.is_symlink() or item.resolve() != item or not item.is_file():
            raise ValueError('D3_COMPOSE')
        raw = item.read_bytes()
        if len(raw) > 32768 or release.sha(raw) != prepared.get('files', {}).get(str(item)):
            raise ValueError('D3_COMPOSE')
        result[item] = raw
    expected = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, release)
    for item, body in expected.items():
        if item.is_symlink() or not item.is_file() or item.stat().st_size > 32768 or item.read_bytes() != body:
            raise ValueError('D3_UNIT')
        result[item] = body
    for unit in ('docker.service', lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('D3_UNIT')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('D3_UNIT')
    return result


def engine_details(identity, image, release):
    require_pins()
    if re.fullmatch('[0-9a-f]{64}', identity) is None:
        raise ValueError('D3_CONTAINER')
    fields = {'id': '.Id', 'image': '.Image', 'user': '.Config.User',
        'running': '.State.Running', 'restarting': '.State.Restarting', 'pid': '.State.Pid',
        'started': '.State.StartedAt', 'restarts': '.RestartCount',
        'source': '(index .Config.Labels "metainc.naver.preview.source")',
        'project': '(index .Config.Labels "com.docker.compose.project")',
        'service': '(index .Config.Labels "com.docker.compose.service")',
        'readonly': '.HostConfig.ReadonlyRootfs'}
    fmt = '{'+','.join(json.dumps(k)+':{{json '+v+'}}' for k, v in fields.items())
    fmt += ',"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}'
    raw = release.command(['docker', 'inspect', '--format', fmt, identity], timeout=10)
    if type(raw) is not bytes or not 0 < len(raw) <= 8192:
        raise ValueError('D3_CONTAINER')
    value = json.loads(raw, object_pairs_hook=release.unique)
    expected = dict(id=identity, image=image, user='10001:10001', running=True,
        restarting=False, source=SOURCE, project='naver-engine', service='naver-engine', readonly=True)
    if (type(value) is not dict or set(value) != {*fields, 'data'}
            or any(type(value.get(k)) is not type(v) or value.get(k) != v for k, v in expected.items())
            or type(value['pid']) is not int or value['pid'] <= 0 or type(value['restarts']) is not int
            or value['restarts'] != 0 or type(value['started']) is not str or not value['started']
            or type(value['data']) is not list or len(value['data']) != 1):
        raise ValueError('D3_CONTAINER')
    mount = value['data'][0]
    if type(mount) is not dict or any(mount.get(k) != v for k, v in {
            'Type': 'bind', 'Source': '/var/lib/metainc/naver-engine',
            'Destination': '/var/lib/naver-engine', 'RW': True}.items()):
        raise ValueError('D3_CONTAINER')
    return value


def run(package, host, release, lifecycle, reader_source, reader_module):
    global STAGE
    require_pins()
    validate_package(package)
    STAGE = 'preflight'
    if os.geteuid() != 0:
        raise ValueError('D3_ROOT')
    if host.baseline() != BASELINE:
        raise ValueError('D3_BASELINE')
    path, prepared, proof = read_receipts(release)
    runtime = safe_runtime_files(path, prepared, release, lifecycle)
    before = lifecycle._snapshot(release, path, prepared['images'])
    details = engine_details(before['engine']['id'], prepared['images']['engine'], release)
    primary = post_engine = post_legacy = post_proof = None
    result = None
    STAGE = 'readonly'
    try:
        raw = release.command(['docker', 'exec', '-i', '--user', '10001:10001',
            before['engine']['id'], 'python', '-I', '-B', '-'], data=script(reader_source), timeout=30)
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_OUTPUT:
            raise ValueError('D3_OUTPUT')
        result = json.loads(raw, object_pairs_hook=release.unique)
        if type(result) is dict and set(result) == {'error_code'}:
            raise ValueError('D3_READER_FAILED')
        reader_module.validate_result(result)
    except Exception as error:
        primary = error.args[0] if type(error) is ValueError and len(error.args) == 1 and type(error.args[0]) is str and error.args[0] in FAILURES else 'D3_READER_FAILED'
    STAGE = 'postflight'
    try:
        if lifecycle._snapshot(release, path, prepared['images']) != before or engine_details(
                before['engine']['id'], prepared['images']['engine'], release) != details:
            post_engine = 'D3_POST_ENGINE'
    except Exception:
        post_engine = 'D3_POST_ENGINE'
    try:
        if host.baseline() != BASELINE:
            post_legacy = 'D3_POST_LEGACY'
    except Exception:
        post_legacy = 'D3_POST_LEGACY'
    try:
        _, _, after_proof = read_receipts(release)
        if after_proof != proof or safe_runtime_files(path, prepared, release, lifecycle) != runtime:
            post_proof = 'D3_POST_PROOF'
    except Exception:
        post_proof = 'D3_POST_PROOF'
    common = dict(mode=MODE, source_commit=SOURCE, mutations=0,
        database_opened_by_controller=False, collection_completion_verified=False)
    if any(v is not None for v in (primary, post_engine, post_legacy, post_proof)):
        return dict(common, ok=False, failure=dict(primary_code=primary, post_engine_code=post_engine,
            post_legacy_code=post_legacy, post_proof_code=post_proof))
    return dict(common, ok=True, existing_app_baseline_unchanged=True,
        reader_mode='sqlite-mode-ro-query-only-authorizer', diagnostics=result)
