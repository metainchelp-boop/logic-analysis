"""Exact V19 September conversion state diagnosis. No collection or business writes."""
import json
import os
from pathlib import Path
import re

STAGE = 'input'
SOURCE = '00701771c0583477357010e9ac731263770f1da5'
ARCHIVE = '5c77d0197fb088600e11234660f3bf3013c03eafd8e3b756b8be7b91f34fc0e3'
STORE = 'aa39afff20c48225d70e80a899234c68b862aeaa53fae43c2e0769346f3b6d62'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
MAX_OUTPUT = 16384

CONVERSION_SOURCE = r'''
def field_kind(value):
    if value is None:
        return 'missing_or_null'
    if not R._number(value):
        return 'invalid'
    return 'zero' if value == 0 else 'positive'


def day_kind(row, pid, now):
    if row is None:
        return 'row_missing'
    if row['possibility_id'] != pid:
        return 'owner_mismatch'
    if R._collected(row, row['day'], now) is None:
        return 'source_unverified'
    fields = [field_kind(row[key]) for key in R.CONVERSION_FIELDS]
    if 'missing_or_null' in fields:
        return 'field_missing_or_null'
    if 'invalid' in fields:
        return 'field_invalid'
    suffix = 'zero' if fields == ['zero', 'zero'] else 'positive'
    return ('complete_' if row['conversion_complete'] == 1 else 'present_flagfalse_')+suffix


def account_kind(kinds):
    if all(kind in ('complete_zero', 'complete_positive') for kind in kinds):
        return 'complete_positive' if 'complete_positive' in kinds else 'complete_zero'
    if any(kind in ('row_missing', 'owner_mismatch', 'source_unverified') for kind in kinds):
        return 'source_gap'
    if 'field_missing_or_null' in kinds:
        return 'field_missing_or_null'
    if 'field_invalid' in kinds:
        return 'field_invalid'
    return 'present_flagfalse_positive' if any(kind.endswith('_positive') for kind in kinds) else 'present_flagfalse_zero'


def campaign_kind(job):
    if job is None:
        return 'no_matching_progress'
    count, index, evidence = job['campaign_count'], job['next_index'], job['evidence']
    if (job['progress_safe'] != 1 or type(count) is not int or not 0 <= count <= MAX_ROWS
            or type(index) is not int or not 0 <= index <= count
            or job['campaign_type'] != 'array' or job['index_type'] != 'integer'
            or job['evidence_type'] not in ('true', 'false') or type(evidence) is not int or evidence not in (0, 1)):
        return 'invalid_metadata'
    if count == 0:
        return 'no_campaigns' if index == 0 and evidence == 0 else 'invalid_metadata'
    if index < count:
        return 'partial_campaigns'
    return 'all_campaigns_evidence_true' if evidence == 1 else 'all_campaigns_evidence_false'


def collect(store, decisions, now, fingerprint, deadline):
    # Current account×day denominator. Historical company membership is not substituted.
    targets = {cid:row['possibility_id'] for cid, row in decisions.items()
        if row.get('matched') is True and row['decision'].cadence == 'daily' and row['decision'].attributable}
    if (len(targets) != EXPECTED_ACCOUNTS or len(set(targets.values())) != EXPECTED_COMPANIES
            or any(type(cid) is not int or cid <= 0 or type(pid) is not int or pid <= 0 for cid, pid in targets.items())):
        raise ValueError('CONVERSION_POPULATION_CHANGED')
    daily, jobs, scanned_jobs = {}, [], 0
    for offset in range(0, len(targets), 200):
        check_deadline(deadline)
        ids = sorted(targets)[offset:offset+200]
        marks = ','.join('?' for _ in ids)
        found = rows(store._conn, 'SELECT customer_id,possibility_id,day,conversion_complete,conversions,conversion_value,'
            'checked_at,source_at,campaign_fingerprint,source_generation FROM naver_auto_daily_performance '
            'WHERE customer_id IN ('+marks+') AND day BETWEEN ? AND ?', (*ids,START,END), MAX_ROWS-len(daily), deadline)
        for row in found:
            check_deadline(deadline)
            if row['conversion_complete'] not in (0,1) or type(row['conversion_complete']) is not int:
                raise ValueError('CONVERSION_FLAG')
            day(row['day'])
            key = (row['customer_id'], row['day'])
            if key in daily:
                raise ValueError('CONVERSION_DUPLICATE')
            daily[key] = row
        # Never select progress/campaign/raw JSON. Only bounded scalar metadata is projected.
        safe = '(progress_json IS NOT NULL AND length(progress_json)<=1048576 AND json_valid(progress_json))'
        selected = rows(store._conn, 'SELECT customer_id,possibility_id,kind,period_start,period_end,status,error_code,'
            'checked_at,last_success_at,next_try_at,generation,'+safe+' AS progress_safe,'
            'CASE WHEN '+safe+" THEN json_array_length(progress_json,'$.campaign_ids') END AS campaign_count,"
            'CASE WHEN '+safe+" THEN json_type(progress_json,'$.campaign_ids') END AS campaign_type,"
            'CASE WHEN '+safe+" THEN json_extract(progress_json,'$.next_index') END AS next_index,"
            'CASE WHEN '+safe+" THEN json_type(progress_json,'$.next_index') END AS index_type,"
            'CASE WHEN '+safe+" THEN json_extract(progress_json,'$.conversion_evidence') END AS evidence,"
            'CASE WHEN '+safe+" THEN json_type(progress_json,'$.conversion_evidence') END AS evidence_type,"
            'CASE WHEN '+safe+" THEN json_extract(progress_json,'$.fingerprint') END AS fingerprint "
            'FROM naver_auto_performance_job WHERE customer_id IN ('+marks+') AND period_start<=? AND period_end>=? '
            'ORDER BY checked_at,job_key', (*ids,END,START), MAX_JOBS-scanned_jobs, deadline)
        scanned_jobs += len(selected)
        for job in selected:
            check_deadline(deadline)
            if targets.get(job['customer_id']) != job['possibility_id']:
                continue
            start, end = date.fromisoformat(day(job['period_start'])), date.fromisoformat(day(job['period_end']))
            if not 0 <= (end-start).days < 31:
                raise ValueError('CONVERSION_JOB_PERIOD')
            for key in ('checked_at', 'last_success_at', 'next_try_at', 'generation'):
                job[key] = stamp(job[key])
            jobs.append(job)
    check_deadline(deadline)
    # Source-progress metadata is only joined to the actual row generation+campaign fingerprint.
    matching = {}
    for job in jobs:
        for offset in range(30):
            check_deadline(deadline)
            d = str(date(2026,9,1)+timedelta(days=offset))
            row = daily.get((job['customer_id'], d))
            if (row is not None and row['possibility_id'] == targets[job['customer_id']]
                    and job['period_start'] <= d <= job['period_end']
                    and job['generation'] == stamp(row['source_generation'])
                    and type(job['fingerprint']) is str and re.fullmatch('[0-9a-f]{64}',job['fingerprint'])
                    and job['fingerprint'] == row['campaign_fingerprint']):
                key = (job['customer_id'], d)
                previous = matching.get(key)
                if previous is None or (job['checked_at'] or '') > (previous['checked_at'] or ''):
                    matching[key] = job
    day_counts = dict.fromkeys(DAY_KINDS, 0)
    account_counts = dict.fromkeys(ACCOUNT_KINDS, 0)
    field_counts = {key:dict.fromkeys(FIELD_KINDS,0) for key in R.CONVERSION_FIELDS}
    campaign_counts = dict.fromkeys(CAMPAIGN_KINDS, 0)
    false_campaign_counts = dict.fromkeys(CAMPAIGN_KINDS, 0)
    campaign_sizes = dict.fromkeys(('zero','one','multiple','invalid_or_missing'),0)
    owned, field_rows, metadata_days = 0, 0, 0
    for cid, pid in sorted(targets.items()):
        kinds = []
        for offset in range(30):
            check_deadline(deadline)
            d = str(date(2026,9,1)+timedelta(days=offset))
            row = daily.get((cid,d))
            kind = day_kind(row,pid,now)
            day_counts[kind] += 1
            kinds.append(kind)
            campaign = campaign_kind(matching.get((cid,d)))
            campaign_counts[campaign] += 1
            metadata_days += campaign != 'no_matching_progress'
            selected_job = matching.get((cid,d))
            count = selected_job['campaign_count'] if selected_job is not None else None
            size = 'invalid_or_missing' if campaign in ('no_matching_progress','invalid_metadata') else (
                'zero' if count == 0 else 'one' if count == 1 else 'multiple')
            campaign_sizes[size] += 1
            if kind.startswith('present_flagfalse_'):
                false_campaign_counts[campaign] += 1
            if row is not None and row['possibility_id'] == pid:
                owned += 1
                if R._collected(row,d,now) is not None:
                    field_rows += 1
                    for key in R.CONVERSION_FIELDS:
                        field_counts[key][field_kind(row[key])] += 1
        account_counts[account_kind(kinds)] += 1
    statuses = dict.fromkeys(sorted(STATES|{'UNRECOGNIZED'}),0)
    errors = dict.fromkeys(sorted(ERRORS|{'NONE','UNRECOGNIZED'}),0)
    for job in jobs:
        check_deadline(deadline)
        statuses[enum(job['status'],STATES)] += 1
        errors['NONE' if job['error_code'] is None else enum(job['error_code'],ERRORS)] += 1
    check_deadline(deadline)
    return {'schema_version':11,'period':'2026-09','observed_at':stamp(now.isoformat()),
        'population':{'scope':'current-managed-linked','accounts':len(targets),'companies':len(set(targets.values())),
            'expected_account_days':len(targets)*30,'current_pid_rows':owned,'verified_source_rows':field_rows},
        'account_days':day_counts,'accounts':account_counts,'conversion_fields':field_counts,
        'source_campaign_coverage':{'account_days':campaign_counts,'present_flagfalse_account_days':false_campaign_counts,
            'campaign_count_account_days':campaign_sizes,
            'matching_metadata_account_days':metadata_days,'metadata_is_stored_progress_not_independent_source_proof':True},
        'jobs':{'count':len(jobs),'statuses':statuses,'errors':errors,
            'checked_at':time_bounds(job['checked_at'] for job in jobs),
            'last_success_at':time_bounds(job['last_success_at'] for job in jobs),
            'next_try_at':time_bounds(job['next_try_at'] for job in jobs)},
        'limits':{'missing_and_explicit_null_indistinguishable':True,'tracking_installation_not_determined':True,
            'numeric_zero_is_not_conversion_completion':True,'no_metric_values_or_identifiers_returned':True},'mutations':0}
'''

PROJECTION_SOURCE = r'''
START, END = '2026-09-01', '2026-09-30'
EXPECTED_ACCOUNTS, EXPECTED_COMPANIES = 569, 568
MAX_ACCOUNTS, MAX_ROWS, MAX_JOBS, MAX_PROGRESS = 4000, 20000, 20000, 1048576
KST = timezone(timedelta(hours=9))
DAY_KINDS = ('row_missing', 'owner_mismatch', 'source_unverified', 'field_missing_or_null',
    'field_invalid', 'complete_zero', 'complete_positive', 'present_flagfalse_zero', 'present_flagfalse_positive')
ACCOUNT_KINDS = ('complete_zero', 'complete_positive', 'source_gap', 'field_missing_or_null',
    'field_invalid', 'present_flagfalse_zero', 'present_flagfalse_positive')
FIELD_KINDS = ('missing_or_null', 'invalid', 'zero', 'positive')
CAMPAIGN_KINDS = ('no_matching_progress', 'invalid_metadata', 'no_campaigns', 'partial_campaigns',
    'all_campaigns_evidence_true', 'all_campaigns_evidence_false')
STATES = frozenset('reading partial ok retry limited reauth_required source_wait superseded'.split())
ERRORS = frozenset(('KEY_REJECTED RATE SERVER BAD_REQUEST NOT_FOUND NETWORK BAD_RESPONSE MISMATCH OTHER '
    'CHECKPOINT_PENDING CHECKPOINT_INVALID SOURCE_AGGREGATING CAMPAIGNS_CHANGED REQUEST_BUDGET REQUEST_DEADLINE '
    'REQUEST_CALL_CAP STATS_INCOMPLETE STATS_SHAPE STATS_SHAPE_UNKNOWN STATS_NUMERIC_INVALID STATS_ROW_ID_INVALID '
    'STATS_DATE_INVALID STATS_PERIOD_OPEN STATS_METRIC_MISSING STATS_METRIC_INVALID STATS_DATE_INCOMPLETE '
    'STATS_CYCLE_INVALID STATS_CYCLE_FUTURE STATS_CAMPAIGNS_INVALID UNEXPECTED RETRY_EXHAUSTED RECHECK_COVERED').split())


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise ValueError('CONVERSION_DEADLINE')

def number(value):
    if type(value) is not int or not 0 <= value <= 2**63-1:
        raise ValueError('CONVERSION_NUMBER')
    return value

def stamp(value):
    if value is None or value == '':
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(KST).isoformat()
    except (TypeError, ValueError):
        raise ValueError('CONVERSION_TIME') from None

def day(value):
    try:
        if type(value) is not str or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError('CONVERSION_DAY') from None
    return value

def enum(value, allowed):
    return value if type(value) is str and value in allowed else 'UNRECOGNIZED'

def rows(connection, query, params, limit, deadline):
    check_deadline(deadline)
    cursor = connection.execute(query, params)
    names = [column[0] for column in cursor.description]
    values = cursor.fetchmany(limit+1)
    cursor.close()
    if len(values) > limit:
        raise ValueError('CONVERSION_ROW_LIMIT')
    check_deadline(deadline)
    return [dict(zip(names, row)) for row in values]

def time_bounds(values):
    values = [stamp(value) for value in values if value is not None and value != '']
    return {'first': min(values, default=None), 'last': max(values, default=None)}

def readonly_authorizer(action, arg1, arg2, database, source):
    # Initialization PRAGMAs finish before installing this authorizer.
    allowed = (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION,
               sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE)
    if action in allowed:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or '').lower() in (
            'load_extension', 'readfile', 'writefile', 'shell', 'eval', 'fts3_tokenizer') else sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg2 is None and (arg1 or '').lower() in (
            'query_only', 'database_list', 'user_version'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or '').lower() == 'table_info' and arg2 == 'naver_auto_link_memory':
        return sqlite3.SQLITE_OK  # The public management snapshot checks this exact additive column.
    return sqlite3.SQLITE_DENY

def connect_reader(path):
    # Only the fixed engine path is supplied by the script, never by its package.
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('CONVERSION_DATABASE_PATH')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, isolation_level=None, timeout=1)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA busy_timeout=1000')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.set_authorizer(readonly_authorizer)
        if connection.execute('PRAGMA query_only').fetchone() != (1,):
            raise ValueError('CONVERSION_READER_MODE')
        if connection.execute('PRAGMA database_list').fetchall() != [(0, 'main', str(path))]:
            raise ValueError('CONVERSION_DATABASE_PATH')
        return connection
    except Exception:
        connection.close()
        raise
'''

PROJECTION_SOURCE += CONVERSION_SOURCE
exec(compile('import json,re,sqlite3,time\nfrom datetime import date,datetime,timedelta,timezone\n'+PROJECTION_SOURCE,
             '<conversion-diagnostics-projection>', 'exec'))

def validate_package(package):
    if (type(SOURCE) is not str or not re.fullmatch('[0-9a-f]{40}', SOURCE)
            or any(type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value) for value in (ARCHIVE, STORE))):
        raise ValueError('CONVERSION_TARGET_NOT_PINNED')
    expected = {'baseline': BASELINE, 'source_commit': SOURCE, 'source_tar_gz_sha256': ARCHIVE,
                'period': '2026-09', 'scope': 'current-managed-linked'}
    if type(package) is not dict or set(package) != set(expected):
        raise ValueError('CONVERSION_PACKAGE_FIELDS')
    if package != expected:
        raise ValueError('CONVERSION_PACKAGE_PIN')

def script():
    prefix = 'import hashlib,json,os,re,sqlite3,sys,time\nfrom pathlib import Path\nfrom datetime import date,datetime,timedelta,timezone\n'
    return (prefix+PROJECTION_SOURCE+'''
try:
    if os.geteuid()!=10001:
        raise ValueError('CONVERSION_IDENTITY')
    os.environ.clear()
    source=Path('/opt/naver-engine/naver_engine/store.py')
    if source.is_symlink() or not source.is_file() or source.stat().st_size>1048576 or hashlib.sha256(source.read_bytes()).hexdigest()!=__STORE_SHA__:
        raise ValueError('CONVERSION_STORE_PIN')
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S, management_store as MS, reporting as R
    deadline=time.monotonic()+20
    connection=connect_reader(Path('/var/lib/naver-engine/engine.db'))
    reader=S.Store(connection,'/var/lib/naver-engine/engine.db',None,writer=False)
    try:
        connection.set_progress_handler(lambda: time.monotonic()>=deadline,1000)
        connection.execute('BEGIN')
        if connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=('11',):
            raise ValueError('CONVERSION_SCHEMA')
        if connection.execute('SELECT COUNT(*) FROM naver_auto_account').fetchone()[0]>MAX_ACCOUNTS:
            raise ValueError('CONVERSION_ACCOUNT_LIMIT')
        now=datetime.now(KST)
        result=collect(reader,MS.snapshot(reader,now),now,reader.decision_fingerprint(),deadline)
        if connection.total_changes!=0:
            raise ValueError('CONVERSION_MUTATION')
    finally:
        try:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
        finally:
            reader.close()
    check_deadline(deadline)
    encoded=json.dumps(result,sort_keys=True)
    if len(encoded.encode())>16384:
        raise ValueError('CONVERSION_OUTPUT_LIMIT')
    check_deadline(deadline)
    print(encoded)
except Exception as error:
    code=str(error)
    print(json.dumps({'failure':code if re.fullmatch('CONVERSION_[A-Z_]{1,48}',code) else 'CONVERSION_READ_FAILED'}))
'''.replace('__STORE_SHA__', repr(STORE))).encode()

def run(package, host, release):
    global STAGE
    STAGE = 'preflight'
    validate_package(package)
    if os.geteuid() != 0 or host.baseline() != BASELINE:
        raise ValueError('HOST_BASELINE')
    path, prepared_path = release.prepared_paths(SOURCE)
    start_path = prepared_path.with_name('preview-start-'+SOURCE+'.json')
    release.trusted_private_file(start_path)
    if any(item.stat().st_size > 32768 for item in (prepared_path, start_path)):
        raise ValueError('RECEIPT_SIZE')
    prepared = json.loads(prepared_path.read_bytes(), object_pairs_hook=release.unique)
    started = json.loads(start_path.read_bytes(), object_pairs_hook=release.unique)
    if (prepared.get('ok') is not True or prepared.get('stage') != 'prepared'
            or prepared.get('source_commit') != SOURCE or started.get('ok') is not True
            or started.get('stage') != 'internal_ready' or started.get('source_commit') != SOURCE
            or any(prepared.get('package', {}).get(key) != package[key] for key in ('baseline','source_commit','source_tar_gz_sha256'))):
        raise ValueError('SOURCE_NOT_READY')
    for file in (path/'compose.naver-engine.yml', path/'preview-engine.override.yml', path/'deploy/naver-engine-backup.override.yml'):
        if file.resolve() != file or release.sha(file.read_bytes()) != prepared.get('files', {}).get(str(file)):
            raise ValueError('COMPOSE_CHANGED')
    image_id = prepared.get('images', {}).get('engine')
    if type(image_id) is not str or not re.fullmatch('sha256:[0-9a-f]{64}', image_id):
        raise ValueError('PREPARED_IMAGE')
    fmt = '{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
    image = json.loads(release.command(['docker','image','inspect','--format',fmt,'metainc/naver-engine:'+SOURCE]))
    if image != {'id': image_id, 'user': '10001:10001', 'source': SOURCE}:
        raise ValueError('PREPARED_IMAGE_CHANGED')
    identity = release.command(release.compose(path,'engine')+['ps','--all','--quiet']).decode().strip()
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('PREVIEW_CONTAINER_ID')
    fmt = '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"user":{{json .Config.User}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}'
    def container():
        return json.loads(release.command(['docker','inspect','--format',fmt,identity]))
    before = container()
    if (any(before.get(key) != value for key, value in {'id':identity,'image':image_id,'running':True,'user':'10001:10001',
            'project':'naver-engine','service':'naver-engine','readonly':True}.items())):
        raise ValueError('PREVIEW_CONTAINER_CHANGED')
    mounts = before.get('data')
    if (not isinstance(mounts,list) or len(mounts)!=1 or not isinstance(mounts[0],dict)
            or any(mounts[0].get(key)!=value for key,value in {'Type':'bind','Destination':'/var/lib/naver-engine',
                'Source':'/var/lib/metainc/naver-engine'}.items())):
        raise ValueError('PREVIEW_DATA_MOUNT')
    STAGE = 'read_only_conversion_diagnostics'
    failure = None
    try:
        raw = release.command(['docker','exec','-i','--user','10001:10001',identity,'python','-I','-B','-'], data=script(), timeout=30)
    except Exception:
        failure = ValueError('CONVERSION_READER_FAILED')
    finally:
        STAGE = 'postflight'
        if container()!=before or host.baseline()!=BASELINE:
            raise ValueError('POST_BASELINE')
    if failure is not None:
        raise failure from None
    if len(raw)>MAX_OUTPUT:
        raise ValueError('CONVERSION_OUTPUT_LIMIT')
    value = json.loads(raw, object_pairs_hook=release.unique)
    if type(value) is dict and set(value)=={'failure'}:
        raise ValueError(value['failure'] if type(value['failure']) is str and re.fullmatch('CONVERSION_[A-Z_]{1,48}',value['failure']) else 'CONVERSION_READ_FAILED')
    validate_result(value)
    result = {'ok':True,'mode':'conversion-diagnostics-v19','source_commit':SOURCE,
        'reader_mode':'sqlite-mode-ro-query-only-authorizer','mutations':0,'existing_app_baseline_unchanged':True,
        'collection_completion_verified':False,'diagnostics':value}
    validate_operation_result(result)
    return result


def fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError('CONVERSION_OUTPUT_FIELDS')


def distribution(value, names, total):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('CONVERSION_OUTPUT_FIELDS')
    for count in value.values():
        number(count)
    if sum(value.values()) != total:
        raise ValueError('CONVERSION_OUTPUT_COUNTS')


def bounds(value):
    fields(value, 'first last')
    for item in value.values():
        if item is not None and (type(item) is not str or stamp(item) != item):
            raise ValueError('CONVERSION_OUTPUT_TIME')
    if (value['first'] is None) != (value['last'] is None) or (
            value['first'] is not None and value['first'] > value['last']):
        raise ValueError('CONVERSION_OUTPUT_TIME')


def validate_result(value):
    fields(value, 'schema_version period observed_at population account_days accounts conversion_fields '
        'source_campaign_coverage jobs limits mutations')
    if (type(value['schema_version']) is not int or value['schema_version'] != 11
            or type(value['period']) is not str or value['period'] != '2026-09'
            or type(value['mutations']) is not int or value['mutations'] != 0
            or type(value['observed_at']) is not str or stamp(value['observed_at']) != value['observed_at']):
        raise ValueError('CONVERSION_OUTPUT_PIN')
    population = value['population']
    fields(population, 'scope accounts companies expected_account_days current_pid_rows verified_source_rows')
    if type(population['scope']) is not str or population['scope'] != 'current-managed-linked':
        raise ValueError('CONVERSION_OUTPUT_SCOPE')
    for key in set(population)-{'scope'}:
        number(population[key])
    expected = EXPECTED_ACCOUNTS*30
    if (population['accounts'] != EXPECTED_ACCOUNTS or population['companies'] != EXPECTED_COMPANIES
            or population['expected_account_days'] != expected
            or not 0 <= population['verified_source_rows'] <= population['current_pid_rows'] <= expected):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    days, accounts = value['account_days'], value['accounts']
    distribution(days,DAY_KINDS,expected)
    distribution(accounts,ACCOUNT_KINDS,EXPECTED_ACCOUNTS)
    verified = expected-sum(days[key] for key in ('row_missing','owner_mismatch','source_unverified'))
    if (population['current_pid_rows'] != expected-days['row_missing']-days['owner_mismatch']
            or population['verified_source_rows'] != verified):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    for key in ('complete_zero','complete_positive'):
        if accounts[key]*30 > days['complete_zero']+days['complete_positive']:
            raise ValueError('CONVERSION_OUTPUT_COUNTS')
    if (accounts['complete_zero']*30 > days['complete_zero']
            or accounts['complete_positive'] > days['complete_positive']
            or accounts['present_flagfalse_positive'] > days['complete_positive']+days['present_flagfalse_positive']):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    if (accounts['source_gap'] > sum(days[key] for key in ('row_missing','owner_mismatch','source_unverified'))
            or accounts['field_missing_or_null'] > days['field_missing_or_null']
            or accounts['field_invalid'] > days['field_invalid']
            or accounts['present_flagfalse_zero']+accounts['present_flagfalse_positive'] >
                days['present_flagfalse_zero']+days['present_flagfalse_positive']):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    fields(value['conversion_fields'], 'conversions conversion_value')
    for counts in value['conversion_fields'].values():
        distribution(counts,FIELD_KINDS,verified)
    missing = sum(counts['missing_or_null'] for counts in value['conversion_fields'].values())
    invalid = sum(counts['invalid'] for counts in value['conversion_fields'].values())
    if not days['field_missing_or_null'] <= missing <= 2*days['field_missing_or_null']:
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    if invalid < days['field_invalid'] or invalid > 2*(days['field_invalid']+days['field_missing_or_null']):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    campaigns = value['source_campaign_coverage']
    fields(campaigns, 'account_days present_flagfalse_account_days campaign_count_account_days matching_metadata_account_days '
        'metadata_is_stored_progress_not_independent_source_proof')
    distribution(campaigns['account_days'],CAMPAIGN_KINDS,expected)
    false_days = days['present_flagfalse_zero']+days['present_flagfalse_positive']
    distribution(campaigns['present_flagfalse_account_days'],CAMPAIGN_KINDS,false_days)
    distribution(campaigns['campaign_count_account_days'],('zero','one','multiple','invalid_or_missing'),expected)
    number(campaigns['matching_metadata_account_days'])
    if (campaigns['matching_metadata_account_days'] != expected-campaigns['account_days']['no_matching_progress']
            or campaigns['metadata_is_stored_progress_not_independent_source_proof'] is not True
            or any(count > campaigns['account_days'][key] for key,count in campaigns['present_flagfalse_account_days'].items())):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    sizes = campaigns['campaign_count_account_days']
    if (sizes['zero'] != campaigns['account_days']['no_campaigns']
            or sizes['invalid_or_missing'] != campaigns['account_days']['no_matching_progress']+campaigns['account_days']['invalid_metadata']):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    jobs = value['jobs']
    fields(jobs, 'count statuses errors checked_at last_success_at next_try_at')
    number(jobs['count'])
    if jobs['count'] > MAX_JOBS:
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    distribution(jobs['statuses'],STATES|{'UNRECOGNIZED'},jobs['count'])
    distribution(jobs['errors'],ERRORS|{'NONE','UNRECOGNIZED'},jobs['count'])
    for key in ('checked_at','last_success_at','next_try_at'):
        bounds(jobs[key])
    fields(value['limits'], 'missing_and_explicit_null_indistinguishable tracking_installation_not_determined '
        'numeric_zero_is_not_conversion_completion no_metric_values_or_identifiers_returned')
    if any(item is not True for item in value['limits'].values()):
        raise ValueError('CONVERSION_OUTPUT_LIMITS')
    if len(json.dumps(value,sort_keys=True).encode()) > MAX_OUTPUT:
        raise ValueError('CONVERSION_OUTPUT_LIMIT')


def validate_operation_result(result):
    validate_package({'baseline':BASELINE,'source_commit':SOURCE,'source_tar_gz_sha256':ARCHIVE,
        'period':'2026-09','scope':'current-managed-linked'})
    fields(result, 'ok mode source_commit reader_mode mutations existing_app_baseline_unchanged '
        'collection_completion_verified diagnostics')
    expected = {'ok':True,'mode':'conversion-diagnostics-v19','source_commit':SOURCE,
        'reader_mode':'sqlite-mode-ro-query-only-authorizer','mutations':0,
        'existing_app_baseline_unchanged':True,'collection_completion_verified':False}
    if any(type(result[key]) is not type(item) or result[key] != item for key,item in expected.items()):
        raise ValueError('CONVERSION_RESULT_PIN')
    validate_result(result['diagnostics'])

