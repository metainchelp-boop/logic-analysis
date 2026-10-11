"""Exact V26 September missing-conversion recovery diagnosis. No collection or business writes."""
import json
import os
from pathlib import Path
import re

STAGE = 'input'
SOURCE = '737a65952f2ddbc05a235cf2b139a4a11f4e7673'
ARCHIVE = '957ed0362ba9e3775a832c78011dc838c39297855d1f8ce901038d4e0c4e4450'
STORE = 'a78560f42cd3e4ee774135b3b148f0e518ce59a41f1c9d74ae475769aa643856'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
MAX_OUTPUT = 16384

CONVERSION_SOURCE = r'''
DAY_KINDS = ('row_missing','owner_null','owner_other','basic_incomplete','source_unverified',
    'conversion_missing_or_null','conversion_invalid','numeric_zero','numeric_positive')
ACCOUNT_KINDS = DAY_KINDS
INVENTORY_KINDS = ('zero','one','multiple','invalid_or_missing')
PROGRESS_KINDS = ('no_matching_progress','invalid_metadata','no_campaigns','partial_campaigns',
    'all_campaigns_evidence_true','all_campaigns_evidence_false')
MANUAL_KINDS = ('history_missing','owner_or_attribution_gap','request_pending_or_recent',
    'collection_in_progress','history_preconditions_met')
EXPECTED_TARGETS = 23
BASE_GENERATION = '2026-10-03T00:01:00+09:00'


def day_kind(row, pid, now, newest, queued):
    if row is None:
        return 'row_missing'
    if row['possibility_id'] != pid:
        return 'owner_null' if row['possibility_id'] is None else 'owner_other'
    if row['basic_complete'] != 1 or not all(R._number(row.get(key)) for key in R.BASIC_FIELDS):
        return 'basic_incomplete'
    checked, source, generation = (stamp(row.get(key)) for key in ('checked_at','source_at','source_generation'))
    fresh = bool(checked and source and generation and BASE_GENERATION <= generation <= checked <= stamp(now.isoformat())
        and source <= checked and source[:10] >= generation[:10] and R._collected(row,row['day'],now) is not None)
    if newest is not None:
        at, required = newest['checked_at'], newest['generation']
        fresh = bool(fresh and at and at <= stamp(now.isoformat()) and required and generation >= required
            and not (newest['status'] != 'ok' and at >= checked))
    if queued:
        fresh = False
    if not fresh:
        return 'source_unverified'
    values = [row.get(key) for key in R.CONVERSION_FIELDS]
    if any(value is None for value in values):
        return 'conversion_missing_or_null'
    if not all(R._number(value) for value in values):
        return 'conversion_invalid'
    return 'numeric_zero' if all(value == 0 for value in values) else 'numeric_positive'


def account_kind(kinds):
    for kind in ACCOUNT_KINDS[:-2]:
        if kind in kinds:
            return kind
    return 'numeric_positive' if 'numeric_positive' in kinds else 'numeric_zero'


def campaign_kind(job):
    if job is None:
        return 'no_matching_progress'
    count, index, evidence = job['campaign_count'], job['next_index'], job['evidence']
    if (job['progress_safe'] != 1 or type(count) is not int or not 0 <= count <= MAX_ROWS
            or type(index) is not int or not 0 <= index <= count or job['campaign_type'] != 'array'
            or job['index_type'] != 'integer' or job['evidence_type'] not in ('true','false')
            or type(evidence) is not int or evidence not in (0,1)):
        return 'invalid_metadata'
    if count == 0:
        return 'no_campaigns' if index == 0 and evidence == 0 else 'invalid_metadata'
    if index < count:
        return 'partial_campaigns'
    return 'all_campaigns_evidence_true' if evidence else 'all_campaigns_evidence_false'


def newest_job(jobs):
    return max(jobs,key=lambda job:(job['checked_at'] or '9999',job['generation'] or '9999',
        job['status'] != 'ok',job['status'] in ('retry','limited','reauth_required')),default=None)


def collect(store, decisions, now, fingerprint, deadline):
    targets = {cid:row['possibility_id'] for cid,row in decisions.items()
        if row.get('matched') is True and row['decision'].cadence == 'daily' and row['decision'].attributable}
    if (len(targets) != EXPECTED_ACCOUNTS or len(set(targets.values())) != EXPECTED_COMPANIES
            or any(type(cid) is not int or cid <= 0 or type(pid) is not int or pid <= 0 for cid,pid in targets.items())):
        raise ValueError('CONVERSION_POPULATION_CHANGED')
    daily, jobs, inventory, requests = {}, {}, {}, {}
    scanned_jobs = 0
    for offset in range(0,len(targets),200):
        check_deadline(deadline)
        ids = sorted(targets)[offset:offset+200]
        marks = ','.join('?' for _ in ids)
        found = rows(store._conn,'SELECT customer_id,possibility_id,day,basic_complete,conversion_complete,'
            'imp,clk,spend,conversions,conversion_value,checked_at,source_at,campaign_fingerprint,source_generation '
            'FROM naver_auto_daily_performance WHERE customer_id IN ('+marks+') AND day BETWEEN ? AND ?',
            (*ids,START,END),MAX_ROWS-len(daily),deadline)
        for row in found:
            check_deadline(deadline)
            if any(type(row[key]) is not int or row[key] not in (0,1) for key in ('basic_complete','conversion_complete')):
                raise ValueError('CONVERSION_FLAG')
            key = (row['customer_id'],day(row['day']))
            if key in daily:
                raise ValueError('CONVERSION_DUPLICATE')
            daily[key] = row
        safe = '(progress_json IS NOT NULL AND length(progress_json)<=1048576 AND json_valid(progress_json))'
        selected = rows(store._conn,'SELECT customer_id,possibility_id,period_start,period_end,status,error_code,'
            'checked_at,generation,'+safe+' AS progress_safe,'
            'CASE WHEN '+safe+" THEN json_array_length(progress_json,'$.campaign_ids') END AS campaign_count,"
            'CASE WHEN '+safe+" THEN json_type(progress_json,'$.campaign_ids') END AS campaign_type,"
            'CASE WHEN '+safe+" THEN CASE WHEN json_type(progress_json,'$.next_index')='integer' "
            "THEN json_extract(progress_json,'$.next_index') END END AS next_index,"
            'CASE WHEN '+safe+" THEN json_type(progress_json,'$.next_index') END AS index_type,"
            'CASE WHEN '+safe+" THEN CASE WHEN json_type(progress_json,'$.conversion_evidence') IN ('true','false') "
            "THEN json_extract(progress_json,'$.conversion_evidence') END END AS evidence,"
            'CASE WHEN '+safe+" THEN json_type(progress_json,'$.conversion_evidence') END AS evidence_type,"
            'CASE WHEN '+safe+" THEN CASE WHEN json_type(progress_json,'$.fingerprint')='text' "
            "AND length(json_extract(progress_json,'$.fingerprint'))=64 "
            "THEN json_extract(progress_json,'$.fingerprint') END END AS fingerprint "
            'FROM naver_auto_performance_job WHERE customer_id IN ('+marks+') AND period_start<=? AND period_end>=?',
            (*ids,END,START),MAX_JOBS-scanned_jobs,deadline)
        scanned_jobs += len(selected)
        for job in selected:
            if job['possibility_id'] != targets[job['customer_id']]:
                continue
            if not 0 <= (date.fromisoformat(day(job['period_end']))-date.fromisoformat(day(job['period_start']))).days < 31:
                raise ValueError('CONVERSION_JOB_PERIOD')
            job['checked_at'],job['generation'] = stamp(job['checked_at']),stamp(job['generation'])
            jobs.setdefault(job['customer_id'],[]).append(job)
        # Project scalar counts only; never bring campaign/checkpoint payloads into Python or output.
        for table in ('naver_auto_performance_job','naver_auto_inventory_check'):
            safe = '(t.campaigns_json IS NOT NULL AND length(t.campaigns_json)<=1048576 AND json_valid(t.campaigns_json))'
            found = rows(store._conn,'SELECT t.customer_id,t.status,t.checked_at,'
                'CASE WHEN '+safe+' THEN json_array_length(t.campaigns_json) END AS campaign_count,'
                'CASE WHEN '+safe+' THEN json_type(t.campaigns_json) END AS campaign_type '
                'FROM '+table+' t WHERE t.customer_id IN ('+marks+') AND t.rowid=(SELECT x.rowid FROM '+table+
                ' x WHERE x.customer_id=t.customer_id ORDER BY x.checked_at DESC,x.rowid DESC LIMIT 1)',
                ids,len(ids),deadline)
            for observed in found:
                observed['checked_at'] = stamp(observed['checked_at'])
                cid = observed['customer_id']
                previous = inventory.get(cid)
                if previous is None or (observed['checked_at'] or '9999',observed['status'] != 'ok') > (
                        previous['checked_at'] or '9999',previous['status'] != 'ok'):
                    inventory[cid] = observed
        for request in rows(store._conn,'SELECT customer_id,possibility_id,requested_at,consumed_at,period_start,period_end '
                'FROM naver_auto_manual_read WHERE customer_id IN ('+marks+')',ids,len(ids),deadline):
            request['requested_at'],request['consumed_at'] = stamp(request['requested_at']),stamp(request['consumed_at'])
            for key in ('period_start','period_end'):
                if request[key] is not None:
                    day(request[key])
            requests[request['customer_id']] = request
    account_days, accounts = dict.fromkeys(DAY_KINDS,0),dict.fromkeys(ACCOUNT_KINDS,0)
    classifications = {}
    for cid,pid in sorted(targets.items()):
        kinds = []
        for offset in range(30):
            check_deadline(deadline)
            d = str(date(2026,9,1)+timedelta(days=offset))
            applicable = [job for job in jobs.get(cid,()) if job['period_start'] <= d <= job['period_end']]
            request = requests.get(cid)
            queued = bool(request and request['possibility_id'] == pid and request['consumed_at'] is None
                and request['period_start'] is not None and request['period_end'] is not None
                and request['period_start'] <= d <= request['period_end'])
            kind = day_kind(daily.get((cid,d)),pid,now,newest_job(applicable),queued)
            account_days[kind] += 1
            kinds.append(kind)
        classification = account_kind(kinds)
        accounts[classification] += 1
        classifications[cid] = classification
    focus = {cid:pid for cid,pid in targets.items() if classifications[cid] not in ('numeric_zero','numeric_positive')}
    if len(focus) != EXPECTED_TARGETS:
        raise ValueError('CONVERSION_TARGET_POPULATION_CHANGED')
    focus_accounts = dict.fromkeys(ACCOUNT_KINDS,0)
    source_progress = dict.fromkeys(PROGRESS_KINDS,0)
    campaign_counts = dict.fromkeys(INVENTORY_KINDS,0)
    inventory_statuses = dict.fromkeys(sorted(STATES|{'UNRECOGNIZED','MISSING'}),0)
    inventory_groups = {kind:dict.fromkeys(sorted(STATES|{'UNRECOGNIZED','MISSING'}),0) for kind in INVENTORY_KINDS}
    manual = dict.fromkeys(MANUAL_KINDS,0)
    latest_statuses = dict.fromkeys(sorted(STATES|{'UNRECOGNIZED','MISSING'}),0)
    latest_errors = dict.fromkeys(sorted(ERRORS|{'NONE','UNRECOGNIZED','MISSING'}),0)
    inventory_times, job_times = [],[]
    for cid,pid in sorted(focus.items()):
        focus_accounts[classifications[cid]] += 1
        history = [daily.get((cid,str(date(2026,9,1)+timedelta(days=n)))) for n in range(30)]
        for row in history:
            check_deadline(deadline)
            matching = [] if row is None or row['possibility_id'] != pid else [job for job in jobs.get(cid,())
                if job['period_start'] <= row['day'] <= job['period_end'] and job['generation'] == stamp(row['source_generation'])
                and type(job['fingerprint']) is str and re.fullmatch('[0-9a-f]{64}',job['fingerprint'])
                and job['fingerprint'] == row['campaign_fingerprint']]
            source_progress[campaign_kind(newest_job(matching))] += 1
        observed = inventory.get(cid)
        bucket = 'invalid_or_missing'
        if observed is not None:
            count = observed['campaign_count']
            if (observed['campaign_type'] == 'array' and type(count) is int and 0 <= count <= MAX_ROWS
                    and observed['checked_at'] and observed['checked_at'] <= stamp(now.isoformat())):
                bucket = 'zero' if count == 0 else 'one' if count == 1 else 'multiple'
            inventory_times.append(observed['checked_at'])
        campaign_counts[bucket] += 1
        observed_status = 'MISSING' if observed is None else enum(observed['status'],STATES)
        inventory_statuses[observed_status] += 1
        inventory_groups[bucket][observed_status] += 1
        latest = newest_job(jobs.get(cid,()))
        latest_statuses['MISSING' if latest is None else enum(latest['status'],STATES)] += 1
        latest_errors['MISSING' if latest is None else 'NONE' if latest['error_code'] is None else enum(latest['error_code'],ERRORS)] += 1
        if latest:
            job_times.append(latest['checked_at'])
        # Read-only subset of manual_period guards. Caller permission is deliberately not asserted.
        request = requests.get(cid)
        if any(row is None for row in history):
            gate = 'history_missing'
        elif any(row['possibility_id'] != pid for row in history) or (
                (boundary := store._performance_attribution_start(cid,pid)) is not None and START < boundary):
            gate = 'owner_or_attribution_gap'
        elif request and ((request['consumed_at'] is None and request['possibility_id'] == pid)
                or request['requested_at'] is None or datetime.fromisoformat(request['requested_at'])+timedelta(hours=1)>now):
            gate = 'request_pending_or_recent'
        elif any(job['status'] in ('reading','retry','partial','source_wait') for job in jobs.get(cid,())):
            gate = 'collection_in_progress'
        else:
            gate = 'history_preconditions_met'
        manual[gate] += 1
    check_deadline(deadline)
    return {'schema_version':11,'period':'2026-09','observed_at':stamp(now.isoformat()),
        'population':{'scope':'current-managed-linked','accounts':len(targets),'companies':len(set(targets.values())),
            'expected_account_days':len(targets)*30,'target_accounts':len(focus)},
        'account_days':account_days,'accounts':accounts,'target_accounts':focus_accounts,
        'target_source_progress_account_days':source_progress,
        'target_latest_campaign_inventory':{'campaign_count_buckets':campaign_counts,'statuses':inventory_statuses,
            'statuses_by_campaign_count_bucket':inventory_groups,'checked_at':time_bounds(inventory_times)},
        'target_latest_period_jobs':{'statuses':latest_statuses,'errors':latest_errors,'checked_at':time_bounds(job_times)},
        'target_monthly_manual_preconditions':manual,
        'limits':{'missing_and_explicit_null_indistinguishable':True,'tracking_installation_not_determined':True,
            'numeric_zero_is_not_conversion_completion':True,'no_metric_values_or_identifiers_returned':True,
            'campaign_inventory_is_stored_observation_not_live_api':True,'zero_inventory_non_ok_status_is_not_setup_proof':True,
            'source_progress_is_stored_metadata_not_independent_proof':True,'manual_preconditions_not_caller_authorization':True,
            'no_collection_or_manual_request_executed':True},'mutations':0}
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
                'period': '2026-09', 'scope': 'current-managed-linked','store_sha256':STORE,
                'schema_version':11,'expected_accounts':EXPECTED_ACCOUNTS,'expected_companies':EXPECTED_COMPANIES,
                'expected_targets':EXPECTED_TARGETS}
    if type(package) is not dict or set(package) != set(expected):
        raise ValueError('CONVERSION_PACKAGE_FIELDS')
    if any(type(package[key]) is not type(value) or package[key] != value for key,value in expected.items()):
        raise ValueError('CONVERSION_PACKAGE_PIN')

def script():
    prefix = 'import hashlib,json,os,re,signal,sqlite3,sys,time\nfrom pathlib import Path\nfrom datetime import date,datetime,timedelta,timezone\n'
    return (prefix+PROJECTION_SOURCE+'''
class ReadDeadline(BaseException):
    pass
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
    def expire(signum,frame):
        raise ReadDeadline('CONVERSION_DEADLINE')
    signal.signal(signal.SIGALRM,expire)
    signal.setitimer(signal.ITIMER_REAL,20)
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
    signal.setitimer(signal.ITIMER_REAL,0)
    print(encoded)
except (Exception,ReadDeadline) as error:
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
    result = {'ok':True,'mode':'conversion-recovery-diagnostics-v26','source_commit':SOURCE,
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
    fields(value,'schema_version period observed_at population account_days accounts target_accounts '
        'target_source_progress_account_days target_latest_campaign_inventory target_latest_period_jobs '
        'target_monthly_manual_preconditions limits mutations')
    if (type(value['schema_version']) is not int or value['schema_version'] != 11 or value['period'] != '2026-09'
            or type(value['mutations']) is not int or value['mutations'] != 0
            or type(value['observed_at']) is not str or stamp(value['observed_at']) != value['observed_at']):
        raise ValueError('CONVERSION_OUTPUT_PIN')
    pop=value['population']
    fields(pop,'scope accounts companies expected_account_days target_accounts')
    expected={'scope':'current-managed-linked','accounts':EXPECTED_ACCOUNTS,'companies':EXPECTED_COMPANIES,
              'expected_account_days':EXPECTED_ACCOUNTS*30,'target_accounts':EXPECTED_TARGETS}
    if any(type(pop[key]) is not type(item) or pop[key] != item for key,item in expected.items()):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    distribution(value['account_days'],DAY_KINDS,EXPECTED_ACCOUNTS*30)
    distribution(value['accounts'],ACCOUNT_KINDS,EXPECTED_ACCOUNTS)
    distribution(value['target_accounts'],ACCOUNT_KINDS,EXPECTED_TARGETS)
    for kind in ACCOUNT_KINDS:
        if (value['target_accounts'][kind] != (value['accounts'][kind] if kind not in ('numeric_zero','numeric_positive') else 0)
                or value['accounts'][kind] > value['account_days'][kind]):
            raise ValueError('CONVERSION_OUTPUT_COUNTS')
    distribution(value['target_source_progress_account_days'],PROGRESS_KINDS,EXPECTED_TARGETS*30)
    inventory=value['target_latest_campaign_inventory']
    fields(inventory,'campaign_count_buckets statuses statuses_by_campaign_count_bucket checked_at')
    distribution(inventory['campaign_count_buckets'],INVENTORY_KINDS,EXPECTED_TARGETS)
    distribution(inventory['statuses'],STATES|{'UNRECOGNIZED','MISSING'},EXPECTED_TARGETS)
    fields(inventory['statuses_by_campaign_count_bucket'],' '.join(INVENTORY_KINDS))
    for kind,group in inventory['statuses_by_campaign_count_bucket'].items():
        distribution(group,STATES|{'UNRECOGNIZED','MISSING'},inventory['campaign_count_buckets'][kind])
    if any(sum(group[state] for group in inventory['statuses_by_campaign_count_bucket'].values()) != count
            for state,count in inventory['statuses'].items()):
        raise ValueError('CONVERSION_OUTPUT_COUNTS')
    bounds(inventory['checked_at'])
    jobs=value['target_latest_period_jobs']
    fields(jobs,'statuses errors checked_at')
    distribution(jobs['statuses'],STATES|{'UNRECOGNIZED','MISSING'},EXPECTED_TARGETS)
    distribution(jobs['errors'],ERRORS|{'NONE','UNRECOGNIZED','MISSING'},EXPECTED_TARGETS)
    bounds(jobs['checked_at'])
    if any(section['checked_at']['last'] is not None and section['checked_at']['last'] > value['observed_at']
            for section in (inventory,jobs)):
        raise ValueError('CONVERSION_OUTPUT_TIME')
    distribution(value['target_monthly_manual_preconditions'],MANUAL_KINDS,EXPECTED_TARGETS)
    fields(value['limits'],'missing_and_explicit_null_indistinguishable tracking_installation_not_determined '
        'numeric_zero_is_not_conversion_completion no_metric_values_or_identifiers_returned '
        'campaign_inventory_is_stored_observation_not_live_api zero_inventory_non_ok_status_is_not_setup_proof '
        'source_progress_is_stored_metadata_not_independent_proof manual_preconditions_not_caller_authorization '
        'no_collection_or_manual_request_executed')
    if any(item is not True for item in value['limits'].values()):
        raise ValueError('CONVERSION_OUTPUT_LIMITS')
    if len(json.dumps(value,sort_keys=True).encode()) > MAX_OUTPUT:
        raise ValueError('CONVERSION_OUTPUT_LIMIT')


def validate_operation_result(result):
    validate_package({'baseline':BASELINE,'source_commit':SOURCE,'source_tar_gz_sha256':ARCHIVE,
        'period':'2026-09','scope':'current-managed-linked','store_sha256':STORE,
        'schema_version':11,'expected_accounts':EXPECTED_ACCOUNTS,'expected_companies':EXPECTED_COMPANIES,
        'expected_targets':EXPECTED_TARGETS})
    fields(result, 'ok mode source_commit reader_mode mutations existing_app_baseline_unchanged '
        'collection_completion_verified diagnostics')
    expected = {'ok':True,'mode':'conversion-recovery-diagnostics-v26','source_commit':SOURCE,
        'reader_mode':'sqlite-mode-ro-query-only-authorizer','mutations':0,
        'existing_app_baseline_unchanged':True,'collection_completion_verified':False}
    if any(type(result[key]) is not type(item) or result[key] != item for key,item in expected.items()):
        raise ValueError('CONVERSION_RESULT_PIN')
    validate_result(result['diagnostics'])
    if len(json.dumps(result,sort_keys=True).encode()) > MAX_OUTPUT:
        raise ValueError('CONVERSION_OUTPUT_LIMIT')

