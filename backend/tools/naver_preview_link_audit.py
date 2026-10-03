"""Approved one-GET ERP link diagnostic. No pairing records, credentials or identities exported."""
import json
import os
from pathlib import Path
import re

STAGE = 'input'
PROJECTION_SOURCE = r'''
URL = 'http://api.metainc.co.kr/api/ad-sync/naver-customer-ids'
FIELDS = ('possibility_id', 'vendor', 'customer_id')
TYPES = ('missing', 'null', 'string', 'number', 'boolean', 'other')
VENDORS = ('naver', 'other', 'null', 'missing', 'invalid')
ERRORS = frozenset('network other status too-large not-json bad-shape call-cap UNRECOGNIZED'.split())
REASONS = frozenset('customer-id-format customer-id-length not-linked ad-account-number ambiguous-space claimed-by-several confirmed-elsewhere rejected-by-human name-different name-points-elsewhere UNRECOGNIZED'.split())
MATCH_COUNTS = ('confirmed', 'auto', 'blocked', 'candidate', 'confirmed_missing', 'ignored', 'checkable_prospects')
COVERAGE = ('scope_prospects', 'present_accounts', 'in_scope_rows', 'in_scope_unique_prospects', 'valid_customer_id_rows', 'customer_id_matches', 'ad_account_number_matches')
RAW_STATES = ('not_called', 'transport_error', 'http_error', 'too_large', 'not_json', 'bad_envelope', 'bad_items', 'valid')


def number(value, nullable=False):
    if value is None and nullable:
        return None
    if type(value) is not int or not 0 <= value <= 2**63-1:
        raise ValueError('AUDIT_COUNT')
    return value


def fixed(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'UNRECOGNIZED'


def raw_empty():
    return {'state':'not_called', 'http_status':None, 'raw_items':None, 'non_object_rows':0,
            'vendor':{key:0 for key in VENDORS},
            'fields':{field:{kind:0 for kind in TYPES} for field in FIELDS}}


def summarize_wire(status, body):
    out = raw_empty()
    out['http_status'] = status if type(status) is int and 100 <= status <= 599 else None
    if status != 200:
        out['state'] = 'http_error'
        return out
    if not isinstance(body, (bytes, bytearray)) or len(body) > 16*1024*1024:
        out['state'] = 'too_large'
        return out
    try:
        value = json.loads(bytes(body).decode('utf-8'))
    except (ValueError, UnicodeError, RecursionError):
        out['state'] = 'not_json'
        return out
    if not isinstance(value, dict) or value.get('status') != 200 or not isinstance(value.get('result'), dict):
        out['state'] = 'bad_envelope'
        return out
    items = value['result'].get('items')
    if not isinstance(items, list):
        out['state'] = 'bad_items'
        return out
    out.update(state='valid', raw_items=len(items))
    for row in items:
        if not isinstance(row, dict):
            out['non_object_rows'] += 1
            continue
        for field in FIELDS:
            item = row.get(field)
            kind = ('missing' if field not in row else 'null' if item is None else 'boolean' if type(item) is bool
                    else 'string' if isinstance(item, str) else 'number' if type(item) in (int,float) else 'other')
            out['fields'][field][kind] += 1
        vendor = row.get('vendor')
        kind = ('missing' if 'vendor' not in row else 'null' if vendor is None else 'naver' if vendor == 'NAVER_SEARCHAD'
                else 'other' if isinstance(vendor, str) else 'invalid')
        out['vendor'][kind] += 1
    return out


class AuditTransport:
    def __init__(self, transport):
        self.transport, self.calls, self.summary = transport, 0, raw_empty()

    def send(self, request, timeout):
        if (self.calls != 0 or request.get_method() != 'GET' or request.full_url != URL
                or request.data is not None or type(timeout) not in (int,float) or not 0 < timeout <= 30):
            raise ValueError('ERP_CALL_SCOPE')
        self.calls += 1
        try:
            response = self.transport.send(request, timeout)
        except Exception:
            self.summary['state'] = 'transport_error'
            raise
        self.summary = summarize_wire(*response)
        return response


def count_map(value, allowed):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError('AUDIT_FIELDS')
    return {key:number(n) for key,n in value.items()}


def project(value):
    if not isinstance(value, dict) or set(value) != {'raw','reader','coverage','dry_match','erp_calls'}:
        raise ValueError('AUDIT_FIELDS')
    raw, reader, coverage, match = value['raw'], value['reader'], value['coverage'], value['dry_match']
    if not isinstance(raw, dict) or set(raw) != set(raw_empty()) or raw['state'] not in RAW_STATES:
        raise ValueError('AUDIT_RAW')
    status = raw['http_status']
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ValueError('AUDIT_HTTP')
    if not isinstance(raw['fields'], dict) or set(raw['fields']) != set(FIELDS):
        raise ValueError('AUDIT_FIELDS')
    raw = dict(state=raw['state'], http_status=status, raw_items=number(raw['raw_items'], True),
               non_object_rows=number(raw['non_object_rows']), vendor=count_map(raw['vendor'],VENDORS),
               fields={key:count_map(raw['fields'][key],TYPES) for key in FIELDS})
    if (not isinstance(reader, dict) or set(reader) != {'state','parsed_rows','error_code'}
            or reader['state'] not in ('ok','failed')):
        raise ValueError('AUDIT_READER')
    reader = dict(state=reader['state'], parsed_rows=number(reader['parsed_rows'],True),
                  error_code=None if reader['error_code'] is None else fixed(reader['error_code'],ERRORS))
    if coverage is not None:
        if not isinstance(coverage, dict) or set(coverage) != set(COVERAGE):
            raise ValueError('AUDIT_COVERAGE')
        coverage = count_map(coverage,COVERAGE)
    if (not isinstance(match, dict) or set(match) != {'state','counts','reasons'}
            or match['state'] not in ('not_run','ok','bad_input')):
        raise ValueError('AUDIT_MATCH')
    match = dict(state=match['state'], counts=count_map(match['counts'],MATCH_COUNTS),
                 reasons=count_map(match['reasons'],REASONS))
    calls = number(value['erp_calls'])
    if calls not in (0,1):
        raise ValueError('ERP_CALL_SCOPE')
    return dict(raw=raw,reader=reader,coverage=coverage,dry_match=match,erp_calls=calls)


def read_once(reader, audit, erp_errors):
    try:
        rows = reader.read_naver_customer_ids()
        result = {'state':'ok','parsed_rows':len(rows),'error_code':None}
    except erp_errors as error:
        rows = None
        result = {'state':'failed','parsed_rows':None,'error_code':fixed(error.kind,ERRORS)}
    return rows, dict(raw=audit.summary,reader=result,coverage=None,
                      dry_match={'state':'not_run','counts':{},'reasons':{}},erp_calls=audit.calls)


def dry_match(rows, store, now, links, matching):
    stage_at = store.stage_as_of()
    if stage_at is None or links._input_problems(store, now)[2]:
        return None, {'state':'not_run','counts':{},'reasons':{}}
    scope = links._scope(store, stage_at, now)
    scope_ids = {row.possibility_id for row in scope}
    accounts = {a['customer_id']:{'customerId':a['customer_id'],'adAccountNo':a['ad_account_no'],
                                 'adAccountName':a['account_name']} for a in store.accounts() if a['present']==1}
    winners, unused = store.link_decisions()
    decisions = [matching.HumanDecision(d.possibility_id,d.customer_id,d.decision) for d in winners]
    credentials = [matching.ErpCredential(r.possibility_id,r.vendor,r.customer_id_raw) for r in rows]
    selected = [r for r in rows if r.possibility_id in scope_ids]
    valid = [matching.parse_customer_id(r.customer_id_raw)[0] for r in selected if r.vendor==matching.VENDOR_NAVER]
    valid = [value for value in valid if value is not None]
    ad_numbers = {a['adAccountNo'] for a in accounts.values()}
    coverage = dict(scope_prospects=len(scope), present_accounts=len(accounts), in_scope_rows=len(selected),
                    in_scope_unique_prospects=len({r.possibility_id for r in selected}),
                    valid_customer_id_rows=len(valid), customer_id_matches=sum(v in accounts for v in valid),
                    ad_account_number_matches=sum(v in ad_numbers for v in valid))
    try:
        result = matching.match(scope,credentials,accounts,decisions,accounts_complete=True)
    except matching.BadInput:
        return coverage, {'state':'bad_input','counts':{},'reasons':{}}
    reasons = {}
    for row in result.blocked:
        code = fixed(row.reason,REASONS)
        reasons[code] = reasons.get(code,0)+1
    counts = dict(confirmed=sum(p.link=='confirmed' for p in result.pairs),
                  auto=sum(p.link=='auto' for p in result.pairs),blocked=len(result.blocked),
                  candidate=len(result.candidates),confirmed_missing=len(result.confirmed_missing),
                  ignored=result.ignored_rows,checkable_prospects=len(result.checkable()))
    return coverage, dict(state='ok',counts=counts,reasons=reasons)
'''
exec(compile(PROJECTION_SOURCE, '<link-audit-projection>', 'exec'))

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
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S, erp_read as E, links as L
    from app.naver_auto import matching as M
    from naver_runtime.config import Config
    from naver_runtime.erp_tunnel_transport import ErpTunnelTransport
    config=Config.from_env(os.environ)
    if config.db!='/var/lib/naver-engine/engine.db' or config.erp_tunnel_socket!='/run/naver-erp-tunnel/erp.sock':
        raise ValueError('RUNTIME_PATH')
    audit=AuditTransport(ErpTunnelTransport(config.erp_tunnel_socket))
    reader=E.ErpReader(E.load_erp_key(),transport=audit,max_calls=1)
    os.environ.clear()
    rows,result=read_once(reader,audit,E.ErpError)
    if rows is not None:
        store=S.open_reader('/var/lib/naver-engine/engine.db')
        try:
            store._conn.execute('BEGIN')
            result['coverage'],result['dry_match']=dry_match(rows,store,datetime.now(S.KST),L,M)
        finally:
            try:
                store._conn.execute('ROLLBACK')
            finally:
                store.close()
    print(json.dumps(project(result),sort_keys=True))
except Exception:
    sys.exit(1)
""")
    return '\n'.join(parts).encode()

def run(package, host, release):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
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
    STAGE = 'one_get_link_audit'
    raw = release.command(['docker', 'exec', '-i', '--user', '10001:10001', identity,
                           'python', '-I', '-B', '-'], data=script(), timeout=45)
    if len(raw) > 32768:
        raise ValueError('STATUS_SIZE')
    values = project(json.loads(raw, object_pairs_hook=release.unique))
    STAGE = 'postflight'
    if container() != before or host.baseline() != package['baseline']:
        raise ValueError('POST_BASELINE')
    return {'ok': True, 'mode': 'link-audit', 'source_commit': commit, 'audit': values,
            'reader_mode': 'store-mode-ro-authorizer', 'database_mutations': 0, 'naver_calls': 0,
            'existing_app_baseline_unchanged': True}

