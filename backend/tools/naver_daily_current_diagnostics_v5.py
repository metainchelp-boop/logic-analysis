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
import stat
import subprocess

SOURCE = '4d5802360c1ba23aa801b1145ca8483db3edd35f'
PREVIOUS = '32878e8ecec616772b619c23e796931d44f0bee1'
ARCHIVE = '1db45b8e54e562bd83c12b4cf53c791426ea45fccd85162bfb0e5f27179873fe'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
MODE = 'daily-current-source-4d-v5-fixed-0710'
PREPARE_RUN = '38313890510'
APPLY_RUN = '38314514027'
APPLY_OPERATION = '93a3d17df45942068faf936ee71c57b9'
CONFIG_OPERATION = '74c912dddf824fae99012849bc4c19a5'
P9_CONTROLLER_SHA256 = '77e9162979683b067a34d7ed9e9589030cebb0466e49dcdb65f9b28e57f85968'
READER_SHA256 = 'beb0293e52546b33a0f99fffb064f08921cbe43963857752ff043682f7889c72'
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
READER_STAGES = frozenset(('SOURCE IMPORT DB_OPEN DB_QUERY VALIDATE CLEANUP').split())
READER_REASONS = frozenset('D3_DATABASE_PATH D3_DEADLINE D3_EXECUTION_PINS_INVALID D3_EXECUTION_PINS_PENDING D3_MUTATION D3_OUTPUT_SHAPE D3_READER_MODE D3_READ_BOUND D3_SCHEMA D3_SETUP_SHAPE D3_SHAPE D3_SOURCE_IMPORT D3_SOURCE_PIN D3_TIME D3_UI_BRANCH_MISMATCH D3_SQLITE_AUTH D3_SQLITE_BUSY D3_SQLITE_OTHER D3_UNCLASSIFIED'.split())
MAX_OUTPUT = 16384
STAGE = 'input'
FAILURES = frozenset(('D3_PINS_PENDING D3_PIN_MISMATCH D3_PACKAGE D3_ROOT D3_BASELINE '
    'D3_RECEIPT D3_SOURCE_NOT_READY D3_COMPOSE D3_COMPANION D3_UNIT_BYTES D3_UNIT_ACTIVE D3_UNIT_ENABLED D3_CONTAINER D3_READER_SOURCE '
    'D3_HOST_SOURCE D3_READER_FAILED D3_READER_TIMEOUT D3_READER_COMMAND D3_READER_JSON D3_READER_VALIDATION D3_OUTPUT D3_POST_ENGINE D3_POST_LEGACY D3_POST_PROOF D3_INTERNAL').split())


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
scope={}
checkpoint='SOURCE'
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
     or len(scope['IMAGE_SOURCE_FILES'])!=106 or scope['IMAGE_SOURCE_MAP_SHA256']!='69d77f2c2ede33f35d8d424665dfd85b4a710fcf3ff5fc88a85b281ce564332f'
     or any(v is not None for v in scope['EXECUTION_PINS'].values())): raise ValueError('D3_READER_SOURCE')
 scope['EXECUTION_PINS']=EVIDENCE
 result=scope['read_database']('/var/lib/naver-engine/engine.db','/opt/naver-engine')
 checkpoint='VALIDATE'
 scope['validate_result'](result)
 encoded=json.dumps(result,sort_keys=True,allow_nan=False,separators=(',',':'))
 if len(encoded.encode())>16384: raise ValueError('D3_OUTPUT')
 print(encoded)
except Exception as error:
 stage=scope.get('READ_FAILURE_STAGE') or checkpoint
 if type(stage) is not str or stage not in ('SOURCE','IMPORT','DB_OPEN','DB_QUERY','VALIDATE','CLEANUP'): stage=checkpoint
 reason=scope.get('READ_FAILURE_REASON')
 if type(reason) is not str or reason not in REASONS:
  try: reason=scope['classify_reader_failure'](error)
  except Exception: reason='D3_UNCLASSIFIED'
 if type(reason) is not str or reason not in REASONS: reason='D3_UNCLASSIFIED'
 print(json.dumps({'error_code':'D3_READER_FAILED','reader_stage':stage,'reader_reason':reason}))
'''
    return (prefix+'SOURCE='+repr(SOURCE)+'\nREADER_SHA='+repr(READER_SHA256)
        +'\nREASONS='+repr(tuple(sorted(READER_REASONS)))+'\nREADER_SOURCE='+repr(reader_source)+'\nEVIDENCE='+repr(EXECUTION_PINS)+'\n'+body).encode()


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


EXPORT_SOURCE = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
EXPORT_ARCHIVE = '7d02a455ff2b8b2e2bbcd598b71f5e06ffe8e9d2099f08a2e87a8ea10cbae872'
EXPORT_PREPARE_RUN = '38198428850'
EXPORT_STAGE = Path('/srv/metainc/ad-deploy-staging/saved-exports')
EXPORT_COMPANION = 'naver-saved-exports.override.yml'
EXPORT_PINS = {
    'plan': {'ops_commit': '19586caf7fe5579e7da70d4a2d4205c3ed603996',
        'source_directory': '/root/logic-analysis-deploy/data', 'database_name': 'logic_data.db',
        'exporter_user': 'nobody', 'source_group': None, 'python_executable': '/usr/bin/python3'},
    'helper_sha256': '062dd090978a66002cece04531219d2e75085b2a47c69bf9cf192f628a3a6737',
    'scripts': {'naver_product_export.py': '42a901a450db12504cdc55be6a736a309a237ced616c11a1c2925dc5effb3d59',
        'naver_market_export.py': 'd491688fac98e0a4d1ebe80fc8acccae8defe5f80854581c1f2c9b03b75760d8'},
    'companion_sha256': '4569587ade5f0c6575e7c2504790dbb0efb300b3091d834c2d1471913c499c95'}
EXPORT_NAMES = frozenset({'python-export', EXPORT_COMPANION,
    'naver_product_export.py', 'naver_market_export.py',
    'naver_product_coordinate.py', 'naver_market_coordinate.py',
    'naver-product-export.service', 'naver-product-export.timer',
    'naver-market-export.service', 'naver-market-export.timer',
    'naver-product-export-reader.service', 'naver-market-export-reader.service'})


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def read_export_artifact(item, release, *, private):
    """Read bounded root-owned public configuration/proof, never source DB/env/logs."""
    require_pins()
    if item.resolve() != item or item.is_symlink():
        raise ValueError('D3_COMPANION')
    if private:
        release.trusted_private_file(item)
    before = item.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_gid != 0
            or stat.S_IMODE(before.st_mode) != (0o600 if private else 0o644)
            or before.st_nlink != 1 or not 0 < before.st_size <= 32768):
        raise ValueError('D3_COMPANION')
    raw = item.read_bytes()
    after = item.lstat()
    fields = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns')
    if len(raw) != before.st_size or any(getattr(before, k) != getattr(after, k) for k in fields):
        raise ValueError('D3_COMPANION')
    return raw


class CompanionProxy:
    """Reproduce only P9's current-source engine compose; accept no caller path."""
    def __init__(self, release, path, companion):
        self._release, self._path, self._companion = release, path, companion
    def __getattr__(self, name):
        return getattr(self._release, name)
    def compose(self, path, name):
        require_pins()
        if path != self._path or path.name != 'naver-'+SOURCE or name not in ('engine', 'relay'):
            raise ValueError('D3_COMPANION')
        command = self._release.compose(path, name)
        return command+['-f', str(self._companion)] if name == 'engine' else command


def verified_companion(path, release):
    """Authenticate the same persisted export binding P9 used, without its writers.

    Identity, plan, original package, staged proof and exact companion bytes must
    agree. No exporter execution, source DB stat/open, interpreter read, timer or
    helper verify call occurs. All read proof bytes enter the postflight snapshot.
    """
    require_pins()
    try:
        if path != release.ROOT/'releases'/('naver-'+SOURCE):
            raise ValueError('D3_COMPANION')
        _, original_path = release.prepared_paths(EXPORT_SOURCE)
        original_raw = read_export_artifact(original_path, release, private=True)
        original = json.loads(original_raw, object_pairs_hook=release.unique)
        package = original.get('package') if type(original) is dict else None
        expected = {'baseline': BASELINE, 'source_commit': EXPORT_SOURCE,
                    'source_tar_gz_sha256': EXPORT_ARCHIVE, 'run_id': EXPORT_PREPARE_RUN}
        if (original.get('ok') is not True or original.get('stage') != 'prepared'
                or original.get('source_commit') != EXPORT_SOURCE or type(package) is not dict
                or set(package) != {*expected, 'ciphertext_sha256'}
                or any(type(package.get(k)) is not type(v) or package.get(k) != v for k, v in expected.items())
                or type(package['ciphertext_sha256']) is not str
                or re.fullmatch('[0-9a-f]{64}', package['ciphertext_sha256']) is None):
            raise ValueError('D3_COMPANION')
        package_digest = digest(canonical(dict(package, operation='code-prepare')))
        binding_path = release.ROOT/'receipts'/('completion-exports-'+EXPORT_SOURCE+'.json')
        release.trusted_dir(binding_path.parent, mode=0o700)
        binding_raw = read_export_artifact(binding_path, release, private=True)
        binding = json.loads(binding_raw, object_pairs_hook=release.unique)
        identity = {'source_commit': EXPORT_SOURCE, 'package_sha256': package_digest,
                    'pins_sha256': digest(canonical(EXPORT_PINS))}
        if (type(binding) is not dict or set(binding) != {*identity, 'exports'}
                or any(type(binding.get(k)) is not type(v) or binding.get(k) != v for k, v in identity.items())):
            raise ValueError('D3_COMPANION')
        exports = binding['exports']
        if (type(exports) is not dict or set(exports) != {'version', 'operation_id', 'plan',
                'plan_sha256', 'source_identity', 'runtime_identity', 'manifest', 'companion_sha256', 'interpreter'}
                or type(exports['version']) is not int or exports['version'] != 4
                or exports['operation_id'] != package_digest[:32]
                or exports['plan'] != EXPORT_PINS['plan']
                or exports['plan_sha256'] != digest(canonical(EXPORT_PINS['plan']))
                or exports['companion_sha256'] != EXPORT_PINS['companion_sha256']
                or type(exports['manifest']) is not dict or set(exports['manifest']) != EXPORT_NAMES
                or any(type(v) is not str or re.fullmatch('[0-9a-f]{64}', v) is None for v in exports['manifest'].values())
                or exports['manifest'][EXPORT_COMPANION] != EXPORT_PINS['companion_sha256']):
            raise ValueError('D3_COMPANION')
        folder = EXPORT_STAGE/package_digest[:32]
        release.trusted_dir(EXPORT_STAGE, mode=0o700)
        release.trusted_dir(folder, mode=0o700)
        prepared_path, companion = folder/'prepared.json', folder/EXPORT_COMPANION
        staged_raw = read_export_artifact(prepared_path, release, private=True)
        companion_raw = read_export_artifact(companion, release, private=False)
        if staged_raw != canonical(exports) or digest(companion_raw) != EXPORT_PINS['companion_sha256']:
            raise ValueError('D3_COMPANION')
        return CompanionProxy(release, path, companion), {
            original_path: original_raw, binding_path: binding_raw,
            prepared_path: staged_raw, companion: companion_raw}
    except Exception:
        raise ValueError('D3_COMPANION') from None


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
    wrapped, companion_proof = verified_companion(path, release)
    result.update(companion_proof)
    expected = lifecycle.unit_files(path, pwd.getpwnam('www-data').pw_gid, wrapped)
    for item, body in expected.items():
        if item.is_symlink() or not item.is_file() or item.stat().st_size > 32768 or item.read_bytes() != body:
            raise ValueError('D3_UNIT_BYTES')
        result[item] = body
    for unit in ('docker.service', lifecycle.TUNNEL, *lifecycle.UNITS):
        if lifecycle._state(release, unit, 'ActiveState') != 'active':
            raise ValueError('D3_UNIT_ACTIVE')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release, unit, 'UnitFileState') != 'enabled':
            raise ValueError('D3_UNIT_ENABLED')
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
    # Authenticate every approved public file on the host, not only image files.
    try:
        reader_module.verify_host_source(path)
    except Exception:
        raise ValueError('D3_HOST_SOURCE') from None
    before = lifecycle._snapshot(release, path, prepared['images'])
    details = engine_details(before['engine']['id'], prepared['images']['engine'], release)
    primary = post_engine = post_legacy = post_proof = reader_stage = reader_reason = None
    result = None
    STAGE = 'readonly'
    try:
        try:
            # This unchanged 30s bound covers source hashing, imports and DB read;
            # the reader separately bounds its query snapshot to 20s.
            raw = release.command(['docker', 'exec', '-i', '--user', '10001:10001',
                before['engine']['id'], 'python', '-I', '-B', '-'], data=script(reader_source), timeout=30)
        except subprocess.TimeoutExpired:
            raise ValueError('D3_READER_TIMEOUT') from None
        except Exception:
            raise ValueError('D3_READER_COMMAND') from None
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_OUTPUT:
            raise ValueError('D3_OUTPUT')
        try:
            result = json.loads(raw, object_pairs_hook=release.unique)
        except Exception:
            raise ValueError('D3_READER_JSON') from None
        if type(result) is dict and 'error_code' in result:
            if (set(result) != {'error_code', 'reader_stage', 'reader_reason'}
                    or result['error_code'] != 'D3_READER_FAILED'
                    or type(result['reader_stage']) is not str
                    or result['reader_stage'] not in READER_STAGES
                    or type(result['reader_reason']) is not str
                    or result['reader_reason'] not in READER_REASONS):
                raise ValueError('D3_OUTPUT')
            reader_stage = result['reader_stage']
            reader_reason = result['reader_reason']
            raise ValueError('D3_READER_FAILED')
        try:
            reader_module.validate_result(result)
        except Exception:
            raise ValueError('D3_READER_VALIDATION') from None
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
        reader_module.verify_host_source(path)
        if after_proof != proof or safe_runtime_files(path, prepared, release, lifecycle) != runtime:
            post_proof = 'D3_POST_PROOF'
    except Exception:
        post_proof = 'D3_POST_PROOF'
    common = dict(mode=MODE, source_commit=SOURCE, mutations=0,
        database_opened_by_controller=False, collection_completion_verified=False)
    if any(v is not None for v in (primary, post_engine, post_legacy, post_proof)):
        return dict(common, ok=False, failure=dict(primary_code=primary, post_engine_code=post_engine,
            post_legacy_code=post_legacy, post_proof_code=post_proof, reader_stage=reader_stage, reader_reason=reader_reason))
    return dict(common, ok=True, existing_app_baseline_unchanged=True,
        reader_mode='sqlite-mode-ro-query-only-authorizer', diagnostics=result)
