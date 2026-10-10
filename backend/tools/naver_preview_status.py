"""Approved engine status only: aggregate projection, no credentials or business writes."""
import json
import os
from pathlib import Path
import re
from datetime import datetime

STAGE = 'input'
# Incident 2026-10-05: no live engine-DB reads while this engine release runs.
LIVE_READER_SUSPENDED_COMMITS = frozenset(('a38c53775c112cdf5db420f979093d6bee9e5376',))
PROJECTION_SOURCE = r'''
KINDS = ('org', 'stages', 'accounts', 'pairing')
NETWORK_CODES = 'network other status too-large not-json bad-shape call-cap deadline duplicate KEY_REJECTED RATE SERVER BAD_REQUEST NOT_FOUND NETWORK BAD_RESPONSE MISMATCH OTHER'.split()
CODES = frozenset('FORMAT EMPTY CYCLE PARENT_LOST ORPHAN_TEAM UNKNOWN_STATUS UNKNOWN_TEAM_REF UNKNOWN_OWNER_SOURCE TOP_MANAGER_NONE TOP_MANAGER_LIMIT TOP_MANAGER_COUNT FUTURE STALE INPUTS_CHANGED ACCOUNTS_NONE ACCOUNTS_STALE STAGES_NONE STAGES_STALE BAD_INPUT ACCOUNTS_HELD STAGES_HELD ACCOUNTS_UNUSABLE CLOCK_BEHIND INCOMPLETE_LIST RUN_ABORT HANDLE_INVALID STORE_REFUSED IMPLAUSIBLE_FIRST STAGE_EMPTY_FIRST unexpected CONFIRMED ACTIVE_DROP OWNER_DROP OWNER_BLANK_SPIKE TOP_MANAGER_ADDED SYSTEM_TEAM_LOST MANAGER_SPIKE ACTIVE_DROP_BASELINE OWNER_DROP_BASELINE MANAGER_SPIKE_BASELINE BRAKE BRAKE_STAGE BRAKE_BASELINE BRAKE_MANAGER BRAKE_CONFIRMED STORED_UNREADABLE UNRECOGNIZED'.split()+NETWORK_CODES+[code+'-'+str(status) for code in NETWORK_CODES for status in range(100,600)])
COUNT_KEYS = ('prospects', 'ignored', 'confirmed', 'auto', 'missing', 'broken', 'blocked', 'candidate', 'superseded')


def stamp(value):
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError('STATUS_TIME') from None
    if parsed.tzinfo is None:
        raise ValueError('STATUS_TIME')
    return parsed.isoformat()


def count(value):
    if value is not None and (type(value) is not int or not 0 <= value <= 2**63-1):
        raise ValueError('STATUS_COUNT')
    return value


def project(row, pairing=False):
    if row is None:
        return None
    outcomes = ('accepted', 'refused', 'failed') if pairing else ('accepted', 'refused', 'braked', 'failed')
    if not isinstance(row, dict) or row.get('outcome') not in outcomes:
        raise ValueError('STATUS_OUTCOME')
    codes = row.get('codes')
    if not isinstance(codes, list) or len(codes) > 100:
        raise ValueError('STATUS_CODES')
    out = {'at': stamp(row.get('at')), 'outcome': row['outcome'],
           'codes': sorted({code if isinstance(code, str) and code in CODES else 'UNRECOGNIZED' for code in codes})}
    if out['at'] is None:
        raise ValueError('STATUS_TIME')
    if pairing:
        values = row.get('counts')
        if values is not None and (not isinstance(values, dict) or set(values)-set(COUNT_KEYS)):
            raise ValueError('STATUS_COUNTS')
        out['counts'] = None if values is None else {key: count(values[key]) for key in COUNT_KEYS if key in values}
        for key in ('accounts_read_at', 'stages_as_of'):
            out[key] = stamp(row.get(key))
    else:
        for key in ('row_count', 'manager_count', 'absent_count'):
            out[key] = count(row.get(key))
    return out


def collect(store):
    out = {}
    for kind in KINDS:
        read = store.last_pairing if kind == 'pairing' else lambda outcome=None: store.last_sync(kind, outcome)
        out[kind] = {'latest': project(read(), kind == 'pairing'),
                     'latest_accepted': project(read('accepted'), kind == 'pairing')}
    return out
'''
# Only this literal, reviewed projection is shared with the isolated reader process.
exec(compile(PROJECTION_SOURCE, '<status-projection>', 'exec'))


def validate_package(package):
    if not isinstance(package, dict) or set(package) != {'baseline', 'source_commit', 'source_tar_gz_sha256'}:
        raise ValueError('PACKAGE_FIELDS')
    for key, value in package.items():
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}' if key == 'source_commit' else '[0-9a-f]{64}', value):
            raise ValueError('PACKAGE_SHAPE')


def script():
    parts = ['import json,os,sys\nfrom datetime import datetime\n', PROJECTION_SOURCE]
    parts.append("""
try:
    if os.geteuid()!=10001:
        raise ValueError('READER_IDENTITY')
    os.environ.clear()
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S
    reader=S.open_reader('/var/lib/naver-engine/engine.db')
    try:
        reader._conn.execute('BEGIN')
        result=collect(reader)
    finally:
        try:
            reader._conn.execute('ROLLBACK')
        finally:
            reader.close()
    print(json.dumps(result,sort_keys=True))
except Exception:
    sys.exit(1)
""")
    return '\n'.join(parts).encode()


def run(package, host, release):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
    if package['source_commit'] in LIVE_READER_SUSPENDED_COMMITS:
        raise ValueError('LIVE_READER_SUSPENDED')
    if os.geteuid() != 0 or host.baseline() != package['baseline']:
        raise ValueError('HOST_BASELINE')
    commit = package['source_commit']
    path, prepared_path = release.prepared_paths(commit)
    start_path = prepared_path.with_name('preview-start-'+commit+'.json')
    release.trusted_private_file(start_path)
    if any(item.stat().st_size > 32768 for item in (prepared_path, start_path)):
        raise ValueError('RECEIPT_SIZE')
    prepared = json.loads(prepared_path.read_bytes(), object_pairs_hook=release.unique)
    started = json.loads(start_path.read_bytes(), object_pairs_hook=release.unique)
    if (prepared.get('ok') is not True or prepared.get('stage') != 'prepared'
            or prepared.get('source_commit') != commit or started.get('ok') is not True
            or started.get('stage') != 'internal_ready' or started.get('source_commit') != commit
            or any(prepared.get('package', {}).get(key) != value for key, value in package.items())):
        raise ValueError('SOURCE_NOT_READY')
    for file in (path/'compose.naver-engine.yml', path/'preview-engine.override.yml',
                 path/'deploy/naver-engine-backup.override.yml'):
        if file.resolve() != file or release.sha(file.read_bytes()) != prepared.get('files', {}).get(str(file)):
            raise ValueError('COMPOSE_CHANGED')
    expected_image = prepared.get('images', {}).get('engine')
    if not isinstance(expected_image, str) or not re.fullmatch('sha256:[0-9a-f]{64}', expected_image):
        raise ValueError('PREPARED_IMAGE')
    fmt = '{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
    image = json.loads(release.command(['docker', 'image', 'inspect', '--format', fmt, 'metainc/naver-engine:'+commit]))
    if image != {'id': expected_image, 'user': '10001:10001', 'source': commit}:
        raise ValueError('PREPARED_IMAGE_CHANGED')
    identity = release.command(release.compose(path, 'engine')+['ps', '--all', '--quiet']).decode().strip()
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('PREVIEW_CONTAINER_ID')
    fmt = '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"user":{{json .Config.User}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}'
    def container():
        return json.loads(release.command(['docker', 'inspect', '--format', fmt, identity]))
    before = container()
    if (any(before.get(key) != value for key, value in {'id': identity, 'image': expected_image,
            'user': '10001:10001', 'project': 'naver-engine', 'service': 'naver-engine'}.items())
            or before.get('running') is not True or before.get('readonly') is not True):
        raise ValueError('PREVIEW_CONTAINER_CHANGED')
    data = before.get('data')
    if (not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict)
            or any(data[0].get(key) != value for key, value in {'Type': 'bind',
                'Destination': '/var/lib/naver-engine', 'Source': '/var/lib/metainc/naver-engine'}.items())):
        raise ValueError('PREVIEW_DATA_MOUNT')
    STAGE = 'read_only_status'
    raw = release.command(['docker', 'exec', '-i', '--user', '10001:10001', identity,
                           'python', '-I', '-B', '-'], data=script(), timeout=30)
    if len(raw) > 32768:
        raise ValueError('STATUS_SIZE')
    values = json.loads(raw, object_pairs_hook=release.unique)
    if not isinstance(values, dict) or set(values) != set(KINDS):
        raise ValueError('STATUS_FIELDS')
    projected = {}
    for kind in KINDS:
        row = values[kind]
        if not isinstance(row, dict) or set(row) != {'latest', 'latest_accepted'}:
            raise ValueError('STATUS_FIELDS')
        projected[kind] = {key: project(row[key], kind == 'pairing') for key in ('latest', 'latest_accepted')}
        accepted = projected[kind]['latest_accepted']
        if accepted is not None and accepted['outcome'] != 'accepted':
            raise ValueError('STATUS_ACCEPTED')
    STAGE = 'postflight'
    if container() != before or host.baseline() != package['baseline']:
        raise ValueError('POST_BASELINE')
    return {'ok': True, 'mode': 'status', 'source_commit': commit, 'sources': projected,
            'all_latest_accepted': all(row['latest'] is not None and row['latest']['outcome'] == 'accepted'
                                       for row in projected.values()),
            'runtime_state_not_used_as_data_success': True, 'reader_mode': 'store-mode-ro-authorizer',
            'mutations': 0, 'existing_app_baseline_unchanged': True}
