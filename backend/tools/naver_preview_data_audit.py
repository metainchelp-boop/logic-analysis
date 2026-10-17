"""Read-only initial-stage hold audit. No refresh, approval, credential or business write."""
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

STAGE = 'input'
# Incident 2026-10-05: no live engine-DB reads while this engine release runs.
LIVE_READER_SUSPENDED_COMMITS = frozenset(('a38c53775c112cdf5db420f979093d6bee9e5376',))
PROJECTION_SOURCE = r'''
import hashlib
from collections import Counter
KST = timezone(timedelta(hours=9))
STAGES = ('진행중', '전략관리', '사후관리', '홀딩중', '재계약진행중', '환불중', '계약만료')
SPELLINGS = ('진행중', '진행 중', '전략 관리', '전략관리', '사후 관리', '사후관리', '홀딩중', '홀딩 중', '재계약 진행중', '재계약진행중', '재계약 진행 중', '환불중', '환불 중', '계약 만료', '계약만료')
HOLD_CODES = frozenset(('IMPLAUSIBLE_FIRST', 'STAGE_EMPTY_FIRST', 'BRAKE', 'BRAKE_STAGE', 'BRAKE_BASELINE'))


def unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('AUDIT_DUPLICATE_FIELD')
        out[key] = value
    return out


def timestamp(raw):
    try:
        value = raw if isinstance(raw, datetime) else datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        raise ValueError('AUDIT_TIME') from None
    if value.tzinfo is None:
        raise ValueError('AUDIT_TIME')
    return value.astimezone(KST)


def positive(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError('AUDIT_ID_SHAPE')
    return value


def collect(conn, now, hold_ttl, future_slack):
    now = timestamp(now)
    held = conn.execute("SELECT sync_id,at,codes,body,used_at,used_by FROM naver_auto_hold WHERE kind='stages'").fetchone()
    if held is None:
        raise ValueError('HOLD_NOT_FOUND')
    hid, at, codes, raw, used, by = held
    positive(hid)
    at = timestamp(at)
    if (used is not None or by is not None or now-at > hold_ttl or at > now+future_slack
            or at.date() != now.date()):
        raise ValueError('HOLD_NOT_CURRENT')
    if not isinstance(raw, str) or not 0 < len(raw.encode()) <= 32*1024*1024:
        raise ValueError('HOLD_BODY_SIZE')
    body = json.loads(raw, object_pairs_hook=unique)
    codes = json.loads(codes)
    if not isinstance(codes, list) or not codes or any(code not in HOLD_CODES for code in codes):
        raise ValueError('HOLD_CODES')
    if not isinstance(body, dict) or set(body) != {'as_of', 'rows', 'conflicts', 'per_spelling'}:
        raise ValueError('HOLD_BODY_SHAPE')
    as_of = timestamp(body['as_of'])
    if as_of != at:
        raise ValueError('HOLD_TIME_MISMATCH')
    rows, conflicts, per = body['rows'], body['conflicts'], body['per_spelling']
    if (not isinstance(rows, list) or len(rows) > 100000 or not isinstance(conflicts, list)
            or len(conflicts) > 100000 or not isinstance(per, dict) or set(per) != set(SPELLINGS)
            or any(type(n) is not int or not 0 <= n < 2**31 for n in per.values())):
        raise ValueError('HOLD_BODY_SHAPE')
    pids, stages, ends = set(), Counter(), Counter()
    for row in rows:
        if not isinstance(row, list) or len(row) != 5:
            raise ValueError('HOLD_ROW_SHAPE')
        pid, name, stage, end, unread = row
        positive(pid)
        if (pid in pids or stage not in STAGES or not (name is None or isinstance(name, str) and len(name) <= 200)
                or unread not in (None, 0, 1) or isinstance(unread, bool)):
            raise ValueError('HOLD_ROW_SHAPE')
        pids.add(pid)
        stages[stage] += 1
        ends['missing' if end is None else 'present'] += 1
        ends['unreadable'] += unread == 1
        ends['unreadable_flag_unknown'] += unread is None
        if end is not None:
            if not isinstance(end, str) or date.fromisoformat(end).isoformat() != end:
                raise ValueError('HOLD_END_DATE')
            age = (now.date()-date.fromisoformat(end)).days
            ends['expired' if age > 0 else 'ends_today' if age == 0 else 'future'] += 1
            ends['expired_over_14_days'] += age > 14
    conflicts = [positive(pid) for pid in conflicts]
    if len(set(conflicts)) != len(conflicts) or pids.intersection(conflicts):
        raise ValueError('HOLD_CONFLICT_SHAPE')
    all_ids = pids | set(conflicts)
    observations = sum(per.values())
    if observations < len(all_ids):
        raise ValueError('HOLD_OBSERVATION_COUNT')
    org = conn.execute("SELECT generated_at,received_at,body FROM naver_auto_org WHERE slot='current'").fetchone()
    org_out = {'available': org is not None, 'generated_at': None, 'received_at': None,
               'owner_rows': None, 'held_ids_with_owner_row': None, 'held_ids_without_owner_row': None}
    if org is not None:
        org_body = json.loads(org[2], object_pairs_hook=unique)
        owners = org_body['owners']
        if not isinstance(owners, list):
            raise ValueError('ORG_SHAPE')
        owner_ids = {positive(row['possibility_id']) for row in owners}
        org_out.update(generated_at=timestamp(org[0]).isoformat(), received_at=timestamp(org[1]).isoformat(),
                       owner_rows=len(owners), held_ids_with_owner_row=len(all_ids & owner_ids),
                       held_ids_without_owner_row=len(all_ids-owner_ids))
    def meta_time(key):
        row = conn.execute('SELECT value FROM naver_auto_meta WHERE key=?', (key,)).fetchone()
        return None if row is None else timestamp(row[0]).isoformat()
    accepted_at = meta_time('prospects_synced_at')
    return {'hold': {'hold_id': hid, 'body_sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                    'at': at.isoformat(), 'as_of': as_of.isoformat(), 'expires_at': (at+hold_ttl).isoformat(),
                    'kst_date': now.date().isoformat(), 'ttl_seconds': int(hold_ttl.total_seconds()),
                    'same_kst_day': True, 'unconsumed': True, 'within_ttl': True, 'codes': sorted(set(codes))},
            'counts': {'normalized_rows': len(rows), 'unique_total': len(all_ids), 'stage_conflicts': len(conflicts),
                       'normalized_duplicate_rows': 0, 'source_observations': observations,
                       'repeated_source_observations': observations-len(all_ids)},
            'per_stage': {key: stages[key] for key in STAGES}, 'per_spelling': {key: per[key] for key in SPELLINGS},
            'contract_end': {key: ends[key] for key in ('present', 'missing', 'unreadable', 'unreadable_flag_unknown',
                                                       'expired', 'ends_today', 'future', 'expired_over_14_days')},
            'org': org_out, 'accounts': {'present': conn.execute('SELECT COUNT(*) FROM naver_auto_account WHERE present=1').fetchone()[0],
                                        'read_at': meta_time('accounts_read_at'), 'linkage_overlap_available': False},
            'initial_stage_snapshot': accepted_at is None, 'accepted_stage_as_of': accepted_at,
            'raw_duplicate_distribution_available': False, 'conflict_stage_distribution_available': False}
'''
exec(compile(PROJECTION_SOURCE, '<data-audit-projection>', 'exec'))


def validate_result(value):
    schema = {
        'hold': {'hold_id': 'positive', 'body_sha256': 'hash', 'at': 'time', 'as_of': 'time',
                 'expires_at': 'time', 'kst_date': 'day', 'ttl_seconds': 'count', 'same_kst_day': True,
                 'unconsumed': True, 'within_ttl': True, 'codes': 'codes'},
        'counts': dict.fromkeys(('normalized_rows', 'unique_total', 'stage_conflicts', 'normalized_duplicate_rows',
                                'source_observations', 'repeated_source_observations'), 'count'),
        'per_stage': dict.fromkeys(STAGES, 'count'), 'per_spelling': dict.fromkeys(SPELLINGS, 'count'),
        'contract_end': dict.fromkeys(('present', 'missing', 'unreadable', 'unreadable_flag_unknown',
                                      'expired', 'ends_today', 'future', 'expired_over_14_days'), 'count'),
        'org': {'available': 'bool', 'generated_at': 'time?', 'received_at': 'time?', 'owner_rows': 'count?',
                'held_ids_with_owner_row': 'count?', 'held_ids_without_owner_row': 'count?'},
        'accounts': {'present': 'count', 'read_at': 'time?', 'linkage_overlap_available': False},
        'initial_stage_snapshot': 'bool', 'accepted_stage_as_of': 'time?',
        'raw_duplicate_distribution_available': False, 'conflict_stage_distribution_available': False}
    def check(item, rule):
        if isinstance(rule, dict):
            if not isinstance(item, dict) or set(item) != set(rule):
                raise ValueError('AUDIT_FIELDS')
            for key in rule:
                check(item[key], rule[key])
            return
        if type(rule) is bool:
            valid = item is rule
        elif rule.endswith('?') and item is None:
            return
        else:
            rule = rule.rstrip('?')
            if rule == 'time':
                valid = isinstance(item, str) and len(item) <= 40 and timestamp(item).isoformat() == item
            elif rule == 'day':
                valid = isinstance(item, str) and date.fromisoformat(item).isoformat() == item
            elif rule == 'hash':
                valid = isinstance(item, str) and re.fullmatch('[0-9a-f]{64}', item)
            elif rule == 'codes':
                valid = isinstance(item, list) and 0 < len(item) <= 5 and all(type(x) is str and x in HOLD_CODES for x in item)
            elif rule == 'bool':
                valid = type(item) is bool
            else:
                valid = type(item) is int and (1 if rule == 'positive' else 0) <= item < 2**63
        if not valid:
            raise ValueError('AUDIT_VALUE')
    check(value, schema)
    return value


def script():
    return ('import json,os,sys\nfrom datetime import date,datetime,timedelta,timezone\n'+PROJECTION_SOURCE+'''
try:
    if os.geteuid()!=10001:
        raise ValueError('READER_IDENTITY')
    os.environ.clear()
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S, erp_read as E
    if set(E.STAGE_SPELLINGS)!=set(STAGES) or {s for spellings in E.STAGE_SPELLINGS.values() for s in spellings}!=set(SPELLINGS):
        raise ValueError('SOURCE_STAGE_CONTRACT')
    reader=S.open_reader('/var/lib/naver-engine/engine.db')
    try:
        reader._conn.execute('BEGIN')
        held=reader.hold('stages')
        if held is None:
            raise ValueError('HOLD_NOT_FOUND')
        S._stage_body(held['body'])
        result=collect(reader._conn,datetime.now(timezone.utc),S.HOLD_TTL,S.FUTURE_SLACK)
    finally:
        try:
            reader._conn.execute('ROLLBACK')
        finally:
            reader.close()
    print(json.dumps(result,sort_keys=True))
except Exception:
    sys.exit(1)
''').encode()


def validate_package(package):
    if not isinstance(package, dict) or set(package) != {'baseline', 'source_commit', 'source_tar_gz_sha256'}:
        raise ValueError('PACKAGE_FIELDS')
    for key, value in package.items():
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}' if key == 'source_commit' else '[0-9a-f]{64}', value):
            raise ValueError('PACKAGE_SHAPE')


def run(package, host, release):
    # Identity gates intentionally match naver_preview_status.run; no generic command seam.
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
    STAGE = 'read_only_data_audit'
    raw = release.command(['docker', 'exec', '-i', '--user', '10001:10001', identity,
                           'python', '-I', '-B', '-'], data=script(), timeout=30)
    if len(raw) > 32768:
        raise ValueError('AUDIT_SIZE')
    result = validate_result(json.loads(raw, object_pairs_hook=release.unique))
    STAGE = 'postflight'
    if container() != before or host.baseline() != package['baseline']:
        raise ValueError('POST_BASELINE')
    return {'ok': True, 'mode': 'data-audit', 'source_commit': commit, 'audit': result,
            'reader_mode': 'store-mode-ro-authorizer', 'mutations': 0, 'external_calls': 0,
            'approval_performed': False, 'existing_app_baseline_unchanged': True}
