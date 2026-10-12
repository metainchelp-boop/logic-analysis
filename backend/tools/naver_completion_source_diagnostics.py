"""Fixed two-account, schema21 source diagnosis. Prepared locally; not registered.

No writer, scheduler tick, collector, provider, environment or raw log reads.
The candidate order is a stored-snapshot projection, never a dispatch promise.
"""
import hashlib
import json
import os
from pathlib import Path
import re

STAGE = 'input'
SOURCE = '70e6657ac789ce4d72a165dbf6a6e552d2b84043'
ARCHIVE = '499d3ad004e93ecbcd7fcebd2e6f0aae1cd1b127be219d09c3763800b115de4c'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
SCHEMA = 21
MODE = 'inspection-source-diagnostics-v1'
TARGETS = (('gomso', 74789, 2488728), ('foodin', 51952, 1030001))
MAX_OUTPUT = 16384
CODE_PINS = {
    'naver_engine/store.py': 'f7dfb3d3e6d7ed5951ade140d52e971b4ec6e9215803113b3a787efdcc283d7a',
    'naver_engine/inspection_store.py': 'ec915226e4f05743a4a78bd0a07c029c9ea4b0a3150454571e732ebca5f7e8fe',
    'naver_engine/inspection_reads.py': '965f5dac65cbf867a6232c5af2d3992a6324b81cc6470e65167e06d674d0e543',
    'naver_engine/inspection_fields.py': '102028ecb4f35647043b5efc1751e516c92f326252b88c3ab6c983ca7c61ba6a',
    'naver_engine/management.py': '84862507d3831053edf618c6d68e800f1f1a1ec4019bcc88030eacb4d14f37e4',
    'naver_engine/management_store.py': '13ee58e1d4383acf3ab8da469e7e09b9032640c2629e601809a3991b4c650fc5',
    'naver_engine/inventory.py': '2a5c4d5f6acb0b431daa9e16be517322a43008aa636cfdf90c49c4a9305ae28e',
    'naver_engine/product_evidence.py': '755c97900d34e06ac4a7f46c4ac3aafb3477f5a616cb560bb002f86deac87711',
    'naver_engine/sync.py': '7ddd57ccce8a8edcf13e3d4495d748d122b067e1bba32becfa6326a4dda32dad',
    'backend/app/naver_auto/org_snapshot.py': '34da0635ee7d071c3dd02bf4001343f2c42001ebc70d7e5548e692d687920f97',
    'backend/app/naver_auto/scope.py': 'fd25fae418f27e6bd9b01415489164eb85241a5151a3e5fa1ad085edec7b3cd7',
}
READ_FAILURE_CODES = frozenset(('SOURCE_DIAGNOSTICS_READER_FAILED SOURCE_DIAGNOSTICS_READ_FAILED '
    'SOURCE_DIAGNOSTICS_DEADLINE SOURCE_DIAGNOSTICS_TIME SOURCE_DIAGNOSTICS_ROW_LIMIT '
    'SOURCE_DIAGNOSTICS_DATABASE_PATH SOURCE_DIAGNOSTICS_READER_MODE SOURCE_DIAGNOSTICS_TARGETS '
    'SOURCE_DIAGNOSTICS_SCHEMA SOURCE_DIAGNOSTICS_ACCOUNT_LIMIT SOURCE_DIAGNOSTICS_DUPLICATE '
    'SOURCE_DIAGNOSTICS_IDENTITY SOURCE_DIAGNOSTICS_NETWORK_FORBIDDEN SOURCE_DIAGNOSTICS_CODE_PIN '
    'SOURCE_DIAGNOSTICS_MUTATION SOURCE_DIAGNOSTICS_OUTPUT_LIMIT SOURCE_DIAGNOSTICS_OUTPUT_FIELDS '
    'SOURCE_DIAGNOSTICS_OUTPUT_SCHEMA SOURCE_DIAGNOSTICS_OUTPUT_TARGETS SOURCE_DIAGNOSTICS_OUTPUT_ENUM '
    'SOURCE_DIAGNOSTICS_OUTPUT_NUMBER SOURCE_DIAGNOSTICS_OUTPUT_COUNTS SOURCE_DIAGNOSTICS_OUTPUT_LIMITS').split())

PROJECTION_SOURCE = r'''
KST = timezone(timedelta(hours=9))
MAX_ACCOUNTS, MAX_JOBS = 4000, 20000
MAX_SETTING_ROWS = 20
STAGES = frozenset(('진행중', '전략관리', '사후관리', '재계약진행중', '홀딩중', '환불중', '계약만료'))
CADENCES = frozenset(('daily', 'weekly', 'blocked'))
REASONS = frozenset(('AUTHORITY_INVALID', 'SOURCE_STALE', 'UNMATCHED_ACCOUNT', 'UNKNOWN_STAGE', 'MANAGED_STAGE', 'NONMANAGED_STAGE'))
STATUSES = frozenset(('reading', 'partial', 'ok', 'retry', 'limited', 'reauth_required', 'source_wait', 'superseded'))
ERRORS = frozenset(('KEY_REJECTED RATE SERVER BAD_REQUEST NOT_FOUND NETWORK BAD_RESPONSE MISMATCH OTHER '
    'CHECKPOINT_PENDING CHECKPOINT_INVALID SETTINGS_CHANGED REQUEST_BUDGET REQUEST_DEADLINE REQUEST_CALL_CAP '
    'STATS_INCOMPLETE STATS_SHAPE STATS_SHAPE_UNKNOWN STATS_NUMERIC_INVALID STATS_ROW_ID_INVALID STATS_DATE_INVALID '
    'STATS_PERIOD_OPEN STATS_METRIC_MISSING STATS_METRIC_INVALID STATS_DATE_INCOMPLETE STATS_CYCLE_INVALID '
    'STATS_CYCLE_FUTURE STATS_CAMPAIGNS_INVALID UNEXPECTED RETRY_EXHAUSTED SOURCE_AGGREGATING CAMPAIGNS_CHANGED '
    'RECHECK_COVERED').split())
GATES = frozenset(('ELIGIBLE', 'BEFORE_START', 'SOURCE_NOT_READY', 'POLICY_BLOCKED', 'MANAGEMENT_SYNC_PENDING',
    'RETRY_NOT_DUE', 'WEEKLY_NOT_DUE', 'ACCOUNT_BACKOFF', 'CURRENT_BINDING_INVALID', 'ACCOUNT_NOT_IN_SNAPSHOT'))
JOB_COLUMNS = ('job_key,customer_id,possibility_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,'
    'stage_revision,matching_fingerprint,generation,requested_at,actor,status,checked_at,next_try_at,attempts,error_code')

def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise ValueError('SOURCE_DIAGNOSTICS_DEADLINE')

def stamp(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError('SOURCE_DIAGNOSTICS_TIME')
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(KST).isoformat()
    except (TypeError, ValueError):
        raise ValueError('SOURCE_DIAGNOSTICS_TIME') from None

def closed(value, allowed):
    return value if type(value) is str and value in allowed else 'UNRECOGNIZED'

def rows(connection, query, parameters, limit, deadline):
    check_deadline(deadline)
    cursor = connection.execute(query, parameters)
    names = [column[0] for column in cursor.description]
    values = cursor.fetchmany(limit+1)
    cursor.close()
    if len(values) > limit:
        raise ValueError('SOURCE_DIAGNOSTICS_ROW_LIMIT')
    check_deadline(deadline)
    return [dict(zip(names, row)) for row in values]

def readonly_authorizer(action, arg1, arg2, database, source):
    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_TRANSACTION,
                  sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or '').lower() in (
            'load_extension', 'readfile', 'writefile', 'shell', 'eval', 'fts3_tokenizer') else sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg2 is None and (arg1 or '').lower() in ('query_only', 'database_list'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or '').lower() == 'table_info' and arg2 == 'naver_auto_link_memory':
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY

def connect_reader(path):
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('SOURCE_DIAGNOSTICS_DATABASE_PATH')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, isolation_level=None, timeout=1)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA busy_timeout=1000')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.set_authorizer(readonly_authorizer)
        if connection.execute('PRAGMA query_only').fetchone() != (1,):
            raise ValueError('SOURCE_DIAGNOSTICS_READER_MODE')
        if connection.execute('PRAGMA database_list').fetchall() != [(0, 'main', str(path))]:
            raise ValueError('SOURCE_DIAGNOSTICS_DATABASE_PATH')
        return connection
    except Exception:
        connection.close()
        raise

def job_projection(row, expected_pid):
    if row is None:
        return None
    return {'scope': 'expected_pair' if row['possibility_id'] == expected_pid else 'unattributed' if row['possibility_id'] is None else 'other_pair',
        'status': closed(row['status'], STATUSES),
        'diagnostic': None if row['error_code'] is None else closed(row['error_code'], ERRORS),
        'checked_at': stamp(row['checked_at']), 'next_try_at': stamp(row['next_try_at'])}

def backoff_projection(connection,cid,deadline):
    found=[]
    for kind,table in (('performance','naver_auto_performance_job'),('structure','naver_auto_structure_job'),
            ('inspection','naver_auto_inspection_job'),('funnel','naver_auto_funnel_job'),('experiment','naver_auto_experiment_job')):
        saved=rows(connection,'SELECT status,error_code,checked_at,next_try_at FROM '+table+
            " WHERE customer_id=? AND (status='ok' OR error_code IN ('KEY_REJECTED','RATE','SERVER','NETWORK')) "
            'ORDER BY checked_at DESC,rowid DESC LIMIT 1',(cid,),1,deadline)
        if saved:
            found.append((kind,saved[0]))
    if not found:
        return None
    kind,row=max(found,key=lambda entry:(entry[1]['checked_at'],entry[1]['status']!='ok'))
    return {'source':kind,'status':closed(row['status'],STATUSES),
        'diagnostic':None if row['error_code'] is None else closed(row['error_code'],ERRORS),
        'checked_at':stamp(row['checked_at']),'next_try_at':stamp(row['next_try_at'])}

def pending_state(policy, state):
    return policy['decision'].cadence != 'blocked' and (state is None or
        (state['possibility_id'], state['stage_key'], state['stage_revision']) !=
        (policy['possibility_id'], policy['stage_key'], policy['stage_revision']))

def setting_date(value):
    if type(value) is not str or len(value) > 48:
        return None
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            return date.fromisoformat(value).isoformat()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}T[0-9:.+Z-]+',value):
            return datetime.fromisoformat(value).date().isoformat()
    except ValueError:
        pass
    return None

def setting_integer(value):
    if type(value) is int and 0 <= value <= 10**15:
        return value
    if type(value) is float and 0 <= value <= 10**15 and value.is_integer():
        return int(value)
    return None

def settings_projection(store, saved, current_valid, modules, now):
    # Reuse the pinned parser and its checksum/shape/relationship checks. Do not
    # select an unchecked JSON body or turn a saved stale observation current.
    out={'source_state':'missing','checked_at':None,'current_valid':False,'complete':False,
         'total_setting_entities':0,'truncated':False,'items':[]}
    if saved is None:
        return out
    out['checked_at']=stamp(saved['checked_at'])
    try:
        progress=store.inspection_progress(modules['IS']._job(saved))
    except modules['IR'].CheckpointInvalid:
        out['source_state']='invalid'
        return out
    if progress is None:
        return out
    if datetime.fromisoformat(saved['checked_at'])>now or any(datetime.fromisoformat(at)>now
            for at in modules['IS']._observed_times(progress)):
        out['source_state']='invalid'
        return out
    complete=progress['confirmed'] and progress['next_index']==len(progress['queue'])
    out.update(source_state='current_complete' if current_valid and complete else 'current_partial' if current_valid else 'stored_stale',
               current_valid=current_valid,complete=complete)
    campaign_ids=[row['nccCampaignId'] for row in progress['campaigns']]
    campaign_ordinals={identifier:index+1 for index,identifier in enumerate(sorted(campaign_ids))}
    entities=[row for row in progress['entities'].values() if row['entity'] in ('campaign','adgroup')]
    entities.sort(key=lambda row:(row['entity']!='campaign',row['id']))
    out.update(total_setting_entities=len(entities),truncated=len(entities)>MAX_SETTING_ROWS)
    for ordinal,row in enumerate(entities[:MAX_SETTING_ROWS],1):
        settings=row['settings']
        out['items'].append({'entity':row['entity'],'ordinal':ordinal,
            'campaign_ordinal':campaign_ordinals.get(row['campaign_id']),
            'daily_budget':setting_integer(settings.get('dailyBudget')),
            'use_daily_budget':settings.get('useDailyBudget') if type(settings.get('useDailyBudget')) is bool else None,
            'use_period':settings.get('usePeriod') if type(settings.get('usePeriod')) is bool else None,
            'period_start':setting_date(settings.get('periodStartDt')),'period_end':setting_date(settings.get('periodEndDt')),
            'bid_amount':setting_integer(settings.get('bidAmt'))})
    return out

def candidate_projection(store, now, policies, source, prior, deadline, modules):
    P, IS = modules['P'], modules['IS']
    gates, current_jobs, entries = {}, {}, []
    sync_pending = sum(pending_state(row, source.states.get(cid)) for cid, row in policies.items())
    at, day = modules['S']._kst_text(now,'현재'), now.date()
    for cid, row in policies.items():
        check_deadline(deadline)
        if now.time().replace(tzinfo=None) < P.COLLECTION_START:
            gates[cid] = 'BEFORE_START'
            continue
        if source.snapshot is None or source.catalog is None:
            gates[cid] = 'SOURCE_NOT_READY'
            continue
        cadence = row['decision'].cadence
        if cadence == 'blocked':
            gates[cid] = 'POLICY_BLOCKED'
            continue
        if pending_state(row, source.states.get(cid)):
            gates[cid] = 'MANAGEMENT_SYNC_PENDING'
            continue
        manual = store._inspection_manual_job(source.manual_requests.get(cid), row, source.snapshot,
            source.catalog['generated_at'], source.fingerprint, now, source)
        period = P.period_for(cadence, day)
        automatic = store._performance_job(cid, cadence, period.cycle_day, period.since, period.until,
            row, source.snapshot, source.catalog['generated_at'], matching_fingerprint=source.fingerprint)
        automatic['job_key'] = 'inspection:'+automatic['job_key']
        job = manual or automatic
        current_jobs[cid] = job
        old = prior.get(job['job_key'])
        started = old is not None and old['stage_revision'] == job['stage_revision'] and \
            old['possibility_id'] == row['possibility_id'] and old['generation'] == job['generation']
        if not IS._binding(old, job, row['possibility_id']):
            old = None
        if old and not store._collection_retry_ready(old, at):
            gates[cid] = 'RETRY_NOT_DUE'
        elif job['kind'] == 'weekly' and not P.is_due(row['decision'], day,
                started_cycle=period.cycle_day if started else None):
            gates[cid] = 'WEEKLY_NOT_DUE'
        elif not store._collection_account_ready(cid, at):
            gates[cid] = 'ACCOUNT_BACKOFF'
        elif not store._inspection_account_valid(job, now, source):
            gates[cid] = 'CURRENT_BINDING_INVALID'
        else:
            gates[cid] = 'ELIGIBLE'
            entries.append((-1 if manual else 0 if cadence == 'daily' else 1,
                            '' if old is None else old['checked_at'], cid))
    ordered = sorted(entries)
    selected, manual_selected = [], False
    has_daily = any(entry[0] == 0 for entry in ordered)
    eligible_order = []
    for priority, checked, cid in ordered:
        if priority == -1 and has_daily and manual_selected:
            continue
        eligible_order.append(cid)
        manual_selected |= priority == -1
        if len(selected) < 24:
            selected.append(cid)
    return {'gates': gates, 'current_jobs': current_jobs, 'order': eligible_order, 'selected': selected,
        'observed_eligible_count': len(entries), 'selector_order_count': len(eligible_order),
        'management_sync_pending_count': sync_pending, 'rank_exact': sync_pending == 0}

def collect(store, now, deadline, modules, targets=TARGETS):
    # Only the compiled, fixed target tuple can reach the read process.
    if targets != TARGETS:
        raise ValueError('SOURCE_DIAGNOSTICS_TARGETS')
    now = now.astimezone(KST)
    S, MS, I, P, IS, O, Y, PE = (modules[key] for key in ('S','MS','I','P','IS','O','Y','PE'))
    connection = store._conn
    if connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone() != ('21',):
        raise ValueError('SOURCE_DIAGNOSTICS_SCHEMA')
    if connection.execute('SELECT COUNT(*) FROM naver_auto_account').fetchone()[0] > MAX_ACCOUNTS:
        raise ValueError('SOURCE_DIAGNOSTICS_ACCOUNT_LIMIT')
    states = store.management_states()
    policies = MS.snapshot(store, now, stage_states=states)
    if len(policies) > MAX_ACCOUNTS:
        raise ValueError('SOURCE_DIAGNOSTICS_ACCOUNT_LIMIT')
    requests = rows(connection, 'SELECT customer_id,possibility_id,requested_at,actor,request_kind,period_start,period_end '
        'FROM naver_auto_manual_read', (), MAX_ACCOUNTS, deadline)
    catalog, catalog_state = I.catalog_status(store, now, header_only=True)
    source = S._PerformanceSelectionSource(store, now, store.inventory_snapshot(now),
        frozenset(row[0] for row in connection.execute('SELECT customer_id FROM naver_auto_account WHERE present=1')),
        catalog, catalog_state, O.allows_raising(Y.org_freshness(store, now)), MS._organization(store),
        store.decision_fingerprint(), states, policies, {row['customer_id']: row for row in requests})
    saved = rows(connection, 'SELECT '+JOB_COLUMNS+' FROM naver_auto_inspection_job WHERE cycle_day>=?',
        ((now.date()-timedelta(days=8)).isoformat(),), MAX_JOBS, deadline)
    prior = {row['job_key']: row for row in saved}
    if len(prior) != len(saved):
        raise ValueError('SOURCE_DIAGNOSTICS_DUPLICATE')
    candidates = candidate_projection(store, now, policies, source, prior, deadline, modules)
    result = {}
    for label, pid, cid in targets:
        check_deadline(deadline)
        policy = policies.get(cid)
        expected_pair = policy is not None and policy['possibility_id'] == pid and policy['matched'] is True
        latest = rows(connection, 'SELECT '+JOB_COLUMNS+' '
            'FROM naver_auto_inspection_job WHERE customer_id=? ORDER BY checked_at DESC,rowid DESC LIMIT 1',
            (cid,), 1, deadline)
        paired = rows(connection, 'SELECT '+JOB_COLUMNS+' '
            'FROM naver_auto_inspection_job WHERE customer_id=? AND possibility_id=? ORDER BY checked_at DESC,rowid DESC LIMIT 1',
            (cid,pid), 1, deadline)
        any_other = connection.execute('SELECT EXISTS(SELECT 1 FROM naver_auto_inspection_job '
            'WHERE customer_id=? AND possibility_id IS NOT ?)',(cid,pid)).fetchone()[0] == 1
        readiness = store.collection_account_ready(cid, now)
        # The actual product linkage rule includes current ERP stage timestamp and canonical key.
        linked = rows(connection, 'SELECT l.store_key FROM naver_auto_product_link l JOIN naver_auto_prospect p '
            'ON p.possibility_id=l.possibility_id WHERE l.possibility_id=? AND p.present=1 AND p.stage_conflict=0 '
            'AND l.stage_as_of=p.stage_synced_at', (pid,), 1, deadline)
        key = linked[0]['store_key'] if linked else None
        product_link = type(key) is str and len(key) <= 2048 and PE.canonical_store(key) == key
        job = candidates['current_jobs'].get(cid)
        saved_job = prior.get(job['job_key']) if job else None
        binding_current = bool(job and saved_job and IS._binding(saved_job, job, pid)) if expected_pair else None
        latest_pair=paired[0] if paired else None
        latest_valid=bool(expected_pair and latest_pair and datetime.fromisoformat(latest_pair['checked_at'])<=now
            and store._inspection_account_valid(IS._job(latest_pair),now,source))
        binding=None if latest_pair is None else {
            'account_snapshot_matches':source.snapshot is not None and latest_pair['snapshot_at']==S._kst_text(source.snapshot,'계정 원천'),
            'catalog_generation_matches':source.catalog is not None and latest_pair['catalog_at']==source.catalog['generated_at'],
            'matching_revision_matches':latest_pair['matching_fingerprint']==source.fingerprint,
            'management_revision_matches':states.get(cid) is not None and latest_pair['stage_revision']==states[cid]['stage_revision'],
            'current_expected_pair_matches':expected_pair,
            'current_valid':latest_valid}
        request=source.manual_requests.get(cid)
        requested_today=bool(request and datetime.fromisoformat(request['requested_at']).astimezone(KST).date()==now.date())
        active_manual=bool(job and job['kind']=='manual')
        manual={'present':request is not None,'requested_today':requested_today,
            'request_kind':closed(request.get('request_kind') or 'manual',frozenset(('manual','manual_period'))) if request else None,
            'requested_at':stamp(request['requested_at']) if request else None,
            'expected_pair_matches':request['possibility_id']==pid if request else None,
            'valid_current_inspection_request':active_manual}
        exact = candidates['rank_exact'] and expected_pair
        rank = candidates['order'].index(cid)+1 if exact and cid in candidates['order'] else None
        result[label] = {
            'account_present': cid in source.present, 'current_expected_pair': expected_pair,
            'cadence': closed(policy['decision'].cadence,CADENCES) if policy else None,
            'policy_reason': closed(policy['decision'].reason,REASONS) if policy else None,
            'current_stage': closed(policy['stage_key'],STAGES) if expected_pair else None,
            'source_current': policy['source_current'] if policy else False,
            'management_sync_pending': pending_state(policy,states.get(cid)) if policy else False,
            'collection_account_ready': readiness,
            'account_backoff':backoff_projection(connection,cid,deadline),
            'inspection_job_exists_for_account': bool(latest), 'inspection_job_exists_for_expected_pair': bool(paired),
            'inspection_job_exists_for_other_pair': any_other,
            'latest_account_job': job_projection(latest[0],pid) if latest else None,
            'latest_pair_job': job_projection(paired[0],pid) if paired else None,
            'latest_pair_binding':binding,'manual_read':manual,
            'current_job_binding_matches': binding_current,
            'snapshot_candidate_gate': candidates['gates'].get(cid,'ACCOUNT_NOT_IN_SNAPSHOT'),
            'snapshot_candidate_rank': rank, 'snapshot_within_selected_24': cid in candidates['selected'] if exact else None,
            'canonical_erp_product_link_present': product_link if expected_pair else None,
            'settings':settings_projection(store,latest_pair if expected_pair else None,latest_valid,modules,now),
        }
    return {'schema_version':21,'observed_at':now.isoformat(),'targets':result,
        'sources':{'account_snapshot_current':source.snapshot is not None,'catalog_state':closed(source.catalog_state,
            frozenset(('missing','failed','stale','accepted'))),'organization_current':source.org_allowed},
        'candidate_snapshot': {'rank_exact':candidates['rank_exact'],
            'eligible_count':candidates['observed_eligible_count'] if candidates['rank_exact'] else None,
            'selector_order_count':candidates['selector_order_count'] if candidates['rank_exact'] else None,
            'observed_eligible_count':candidates['observed_eligible_count'],
            'management_sync_pending_count':candidates['management_sync_pending_count'], 'selected_limit':24},
        'limits': {'stored_snapshot_only':True,'management_not_synchronized':True,
            'scheduler_memory_exclusions_unobserved':True,'scheduler_remaining_budget_unobserved':True,
            'dispatch_order_not_proven':True,'collection_completion_not_proven':True,
            'product_link_is_not_product_data_completeness':True}, 'mutations':0}
'''

_HEADER = ('import json,re,sqlite3,time\nfrom datetime import date,datetime,timedelta,timezone\n'
           + 'TARGETS='+repr(TARGETS)+'\n')
exec(compile(_HEADER+PROJECTION_SOURCE, '<completion-source-diagnostics>', 'exec'))


def validate_package(package):
    expected = {'baseline':BASELINE,'source_commit':SOURCE,'source_tar_gz_sha256':ARCHIVE,'mode':MODE}
    if type(package) is not dict or set(package) != set(expected) or package != expected:
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')


def script():
    prefix = ('import hashlib,json,os,re,socket,sqlite3,sys,time\nfrom pathlib import Path\n'
              'from datetime import date,datetime,timedelta,timezone\nTARGETS='+repr(TARGETS)+'\n')
    body = r'''
try:
    if os.geteuid()!=10001:
        raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    os.environ.clear()
    def no_network(*args, **kwargs):
        raise ValueError('SOURCE_DIAGNOSTICS_NETWORK_FORBIDDEN')
    socket.socket.connect=socket.socket.connect_ex=no_network
    for relative,digest in CODE_PINS.items():
        path=Path('/opt/naver-engine')/relative
        if path.is_symlink() or path.resolve()!=path or not path.is_file() or path.stat().st_size>1048576 or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('SOURCE_DIAGNOSTICS_CODE_PIN')
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S,management_store as MS,inventory as I,management as P,inspection_store as IS,inspection_reads as IR,sync as Y,product_evidence as PE
    from app.naver_auto import org_snapshot as O
    modules=dict(S=S,MS=MS,I=I,P=P,IS=IS,IR=IR,O=O,Y=Y,PE=PE)
    deadline=time.monotonic()+20
    connection=connect_reader(Path('/var/lib/naver-engine/engine.db'))
    reader=S.Store(connection,'/var/lib/naver-engine/engine.db',None,writer=False)
    try:
        connection.set_progress_handler(lambda:time.monotonic()>=deadline,1000)
        connection.execute('BEGIN')
        result=collect(reader,datetime.now(KST),deadline,modules)
        if connection.total_changes!=0:
            raise ValueError('SOURCE_DIAGNOSTICS_MUTATION')
    finally:
        try:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
        finally:
            reader.close()
    check_deadline(deadline)
    encoded=json.dumps(result,sort_keys=True,allow_nan=False,separators=(',',':'))
    if len(encoded.encode())>16384:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
    print(encoded)
except Exception as error:
    code=str(error) if isinstance(error,ValueError) else ''
    print(json.dumps({'failure':code if re.fullmatch('SOURCE_DIAGNOSTICS_[A-Z_]{1,48}',code) else 'SOURCE_DIAGNOSTICS_READ_FAILED'}))
'''
    return (prefix+'CODE_PINS='+repr(CODE_PINS)+'\n'+PROJECTION_SOURCE+body).encode()


def validate_result(value):
    """Reconstruct the complete closed result; never return unknown nested fields."""
    if type(value) is not dict or set(value) != {'schema_version','observed_at','targets','sources','candidate_snapshot','limits','mutations'}:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    if type(value['schema_version']) is not int or value['schema_version'] != SCHEMA or value['mutations'] != 0 or type(value['mutations']) is not int:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_SCHEMA')
    stamp(value['observed_at'])
    source=value['sources']
    if type(source) is not dict or set(source)!={'account_snapshot_current','catalog_state','organization_current'} \
            or type(source['account_snapshot_current']) is not bool or type(source['organization_current']) is not bool \
            or source['catalog_state'] not in ('missing','failed','stale','accepted','UNRECOGNIZED'):
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    if type(value['targets']) is not dict or set(value['targets']) != {row[0] for row in TARGETS}:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_TARGETS')
    bools = {'account_present','current_expected_pair','source_current','management_sync_pending','collection_account_ready',
        'inspection_job_exists_for_account','inspection_job_exists_for_expected_pair','inspection_job_exists_for_other_pair'}
    nullable_bools = {'current_job_binding_matches','snapshot_within_selected_24','canonical_erp_product_link_present'}
    fields = bools | nullable_bools | {'cadence','policy_reason','current_stage','latest_account_job','latest_pair_job',
        'snapshot_candidate_gate','snapshot_candidate_rank','latest_pair_binding','manual_read','settings','account_backoff'}
    for row in value['targets'].values():
        if type(row) is not dict or set(row) != fields or any(type(row[key]) is not bool for key in bools):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
        if any(row[key] is not None and type(row[key]) is not bool for key in nullable_bools):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
        for key, allowed in (('cadence',CADENCES),('policy_reason',REASONS),('current_stage',STAGES)):
            if row[key] is not None and (type(row[key]) is not str or row[key] not in allowed | {'UNRECOGNIZED'}):
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        if row['snapshot_candidate_gate'] not in GATES:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        rank=row['snapshot_candidate_rank']
        if rank is not None and (type(rank) is not int or not 1 <= rank <= MAX_ACCOUNTS):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_NUMBER')
        for key in ('latest_account_job','latest_pair_job'):
            job=row[key]
            if job is None:
                continue
            if type(job) is not dict or set(job) != {'scope','status','diagnostic','checked_at','next_try_at'}:
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
            if job['scope'] not in ('expected_pair','other_pair','unattributed') or job['status'] not in STATUSES | {'UNRECOGNIZED'} \
                    or job['diagnostic'] is not None and job['diagnostic'] not in ERRORS | {'UNRECOGNIZED'}:
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
            stamp(job['checked_at']); stamp(job['next_try_at'])
        backoff=row['account_backoff']
        if backoff is not None:
            if type(backoff) is not dict or set(backoff)!={'source','status','diagnostic','checked_at','next_try_at'} \
                    or backoff['source'] not in ('performance','structure','inspection','funnel','experiment') \
                    or backoff['status'] not in STATUSES | {'UNRECOGNIZED'} or backoff['diagnostic'] is not None \
                    and backoff['diagnostic'] not in ERRORS | {'UNRECOGNIZED'}:
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
            stamp(backoff['checked_at']);stamp(backoff['next_try_at'])
        binding=row['latest_pair_binding']
        if binding is not None and (type(binding) is not dict or set(binding)!={'account_snapshot_matches',
                'catalog_generation_matches','matching_revision_matches','management_revision_matches',
                'current_expected_pair_matches','current_valid'} or any(type(item) is not bool for item in binding.values())):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
        manual=row['manual_read']
        if type(manual) is not dict or set(manual)!={'present','requested_today','request_kind','requested_at',
                'expected_pair_matches','valid_current_inspection_request'} or any(type(manual[key]) is not bool for key in
                ('present','requested_today','valid_current_inspection_request')) or manual['expected_pair_matches'] is not None \
                and type(manual['expected_pair_matches']) is not bool or manual['request_kind'] not in (None,'manual','manual_period','UNRECOGNIZED'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
        stamp(manual['requested_at'])
        settings=row['settings']
        if type(settings) is not dict or set(settings)!={'source_state','checked_at','current_valid','complete',
                'total_setting_entities','truncated','items'} or settings['source_state'] not in (
                'missing','invalid','current_complete','current_partial','stored_stale') or any(type(settings[key]) is not bool
                for key in ('current_valid','complete','truncated')) or type(settings['total_setting_entities']) is not int \
                or not 0 <= settings['total_setting_entities'] <= 10000 or type(settings['items']) is not list \
                or len(settings['items'])>MAX_SETTING_ROWS:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
        stamp(settings['checked_at'])
        if len(settings['items'])!=min(settings['total_setting_entities'],MAX_SETTING_ROWS) \
                or settings['truncated']!=(settings['total_setting_entities']>MAX_SETTING_ROWS):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        for ordinal,item in enumerate(settings['items'],1):
            if type(item) is not dict or set(item)!={'entity','ordinal','campaign_ordinal','daily_budget','use_daily_budget',
                    'use_period','period_start','period_end','bid_amount'} or item['entity'] not in ('campaign','adgroup') \
                    or type(item['ordinal']) is not int or item['ordinal']!=ordinal:
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
            for key in ('campaign_ordinal','daily_budget','bid_amount'):
                number=item[key]
                if number is not None and (type(number) is not int or not 0 <= number <= (10000 if key=='campaign_ordinal' else 10**15)):
                    raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_NUMBER')
            for key in ('use_daily_budget','use_period'):
                if item[key] is not None and type(item[key]) is not bool:
                    raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
            for key in ('period_start','period_end'):
                if item[key] is not None and setting_date(item[key])!=item[key]:
                    raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    candidate=value['candidate_snapshot']
    if type(candidate) is not dict or set(candidate) != {'rank_exact','eligible_count','selector_order_count',
            'observed_eligible_count','management_sync_pending_count','selected_limit'} or type(candidate['rank_exact']) is not bool:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    for key in ('eligible_count','selector_order_count','observed_eligible_count','management_sync_pending_count','selected_limit'):
        number=candidate[key]
        if number is None and key in ('eligible_count','selector_order_count') and not candidate['rank_exact']:
            continue
        if type(number) is not int or not 0 <= number <= MAX_ACCOUNTS:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_NUMBER')
    if candidate['selected_limit'] != 24 or candidate['rank_exact'] != (candidate['management_sync_pending_count'] == 0):
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    if candidate['rank_exact'] and (candidate['eligible_count']!=candidate['observed_eligible_count'] or
            candidate['selector_order_count']>candidate['eligible_count']):
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    for row in value['targets'].values():
        rank=row['snapshot_candidate_rank']
        if not candidate['rank_exact'] and (rank is not None or row['snapshot_within_selected_24'] is not None) \
                or rank is not None and (rank>candidate['selector_order_count'] or row['snapshot_within_selected_24']!=(rank<=24)):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    expected_limits={'stored_snapshot_only','management_not_synchronized','scheduler_memory_exclusions_unobserved',
        'scheduler_remaining_budget_unobserved','dispatch_order_not_proven','collection_completion_not_proven',
        'product_link_is_not_product_data_completeness'}
    if type(value['limits']) is not dict or set(value['limits']) != expected_limits or any(item is not True for item in value['limits'].values()):
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMITS')
    if len(json.dumps(value,allow_nan=False,separators=(',',':')).encode()) > MAX_OUTPUT:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
    return value


def run(package, host, release):
    """Same registered-read controller boundary, with an exact new closed profile.

    Registration is deliberately not included in this file or this work item.
    """
    global STAGE
    STAGE='preflight'
    validate_package(package)
    if os.geteuid()!=0 or host.baseline()!=BASELINE:
        raise ValueError('HOST_BASELINE')
    path,prepared_path=release.prepared_paths(SOURCE)
    started_path=prepared_path.with_name('preview-start-'+SOURCE+'.json')
    for item in (prepared_path,started_path):
        release.trusted_private_file(item)
        if item.stat().st_size>32768:
            raise ValueError('RECEIPT_SIZE')
    prepared=json.loads(prepared_path.read_bytes(),object_pairs_hook=release.unique)
    started=json.loads(started_path.read_bytes(),object_pairs_hook=release.unique)
    if (prepared.get('ok') is not True or prepared.get('stage')!='prepared' or prepared.get('source_commit')!=SOURCE
            or any(prepared.get('package',{}).get(key)!=package[key] for key in ('baseline','source_commit','source_tar_gz_sha256'))
            or prepared.get('inventory_enabled') is not True or prepared.get('execution_enabled') is not False
            or prepared.get('runtime_flags_verified') is not True or started.get('ok') is not True
            or started.get('stage')!='internal_ready' or started.get('source_commit')!=SOURCE
            or type(started.get('database_schema')) is not int or started['database_schema']!=21
            or started.get('execution_enabled') is not False or started.get('runtime_flags_verified') is not True):
        raise ValueError('SOURCE_NOT_READY')
    for item in (path/'compose.naver-engine.yml',path/'preview-engine.override.yml',path/'deploy/naver-engine-backup.override.yml'):
        if item.resolve()!=item or release.sha(item.read_bytes())!=prepared.get('files',{}).get(str(item)):
            raise ValueError('COMPOSE_CHANGED')
    image_id=prepared.get('images',{}).get('engine')
    if type(image_id) is not str or re.fullmatch('sha256:[0-9a-f]{64}',image_id) is None:
        raise ValueError('PREPARED_IMAGE')
    image_format='{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
    image=json.loads(release.command(['docker','image','inspect','--format',image_format,'metainc/naver-engine:'+SOURCE]))
    if image!={'id':image_id,'user':'10001:10001','source':SOURCE}:
        raise ValueError('PREPARED_IMAGE_CHANGED')
    identity=release.command(release.compose(path,'engine')+['ps','--all','--quiet']).decode().strip()
    if re.fullmatch('[0-9a-f]{64}',identity) is None:
        raise ValueError('PREVIEW_CONTAINER_ID')
    fmt='{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"user":{{json .Config.User}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"data":[{{range .Mounts}}{{if eq .Destination "/var/lib/naver-engine"}}{{json .}}{{end}}{{end}}]}'
    def container():
        return json.loads(release.command(['docker','inspect','--format',fmt,identity]))
    before=container()
    if any(before.get(key)!=value for key,value in {'id':identity,'image':image_id,'running':True,'user':'10001:10001',
            'project':'naver-engine','service':'naver-engine','readonly':True}.items()):
        raise ValueError('PREVIEW_CONTAINER_CHANGED')
    mounts=before.get('data')
    if type(mounts) is not list or len(mounts)!=1 or type(mounts[0]) is not dict or any(mounts[0].get(key)!=value
            for key,value in {'Type':'bind','Destination':'/var/lib/naver-engine','Source':'/var/lib/metainc/naver-engine'}.items()):
        raise ValueError('PREVIEW_DATA_MOUNT')
    STAGE='read_only_source_diagnostics'
    primary=None
    value=None
    try:
        try:
            raw=release.command(['docker','exec','-i','--user','10001:10001',identity,'python','-I','-B','-'],data=script(),timeout=30)
        except Exception:
            raise ValueError('SOURCE_DIAGNOSTICS_READER_FAILED') from None
        if len(raw)>MAX_OUTPUT:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
        value=json.loads(raw,object_pairs_hook=release.unique)
        if type(value) is dict and set(value)=={'failure'}:
            code=value['failure']
            raise ValueError(code if type(code) is str and code in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED')
        validate_result(value)
    except Exception as error:
        primary=str(error) if isinstance(error,ValueError) and str(error) in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED'
    STAGE='postflight'
    post_engine=post_legacy=None
    try:
        if container()!=before:
            post_engine='POST_ENGINE_CHANGED'
    except Exception:
        post_engine='POST_ENGINE_UNVERIFIED'
    try:
        if host.baseline()!=BASELINE:
            post_legacy='POST_LEGACY_BASELINE_CHANGED'
    except Exception:
        post_legacy='POST_LEGACY_BASELINE_UNVERIFIED'
    if primary is not None or post_engine is not None or post_legacy is not None:
        # Never overwrite an original closed reader failure with a postflight
        # failure, or expose a partial response as a successful diagnostic.
        return {'ok':False,'mode':MODE,'source_commit':SOURCE,'mutations':0,
            'collection_completion_verified':False,'failure':{'primary_code':primary,
                'post_engine_code':post_engine,'post_legacy_baseline_code':post_legacy}}
    return {'ok':True,'mode':MODE,'source_commit':SOURCE,'reader_mode':'sqlite-mode-ro-query-only-authorizer',
        'database_opened_by_controller':False,'mutations':0,'existing_app_baseline_unchanged':True,
        'collection_completion_verified':False,'diagnostics':value}
