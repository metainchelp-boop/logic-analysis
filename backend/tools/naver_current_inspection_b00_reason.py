"""Fixed Foodin-only schema21 read-only source diagnosis for exact b00.

No writer, scheduler tick, collector, provider, environment or raw log reads.
The candidate order is a stored-snapshot projection, never a dispatch promise.
"""
import hashlib
import json
import os
from pathlib import Path
import re

STAGE = 'input'
SOURCE = 'b00d6bf805b43b282c04dd95970ae9ccb7d8247d'
ARCHIVE = '60af02472770f2c0e6eb340375fe75a18d3b6dd593cf714a7a64d012be27d212'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
SCHEMA = 21
PREPARE_RUN = '39108589825'
APPLY_OPERATION = 'a29c6a8810a748d2b5bff766a507ec05'
PREVIOUS_SOURCE = '21cd739cf171c066b84683b24e3340feda495858'
MODE = 'current-inspection-b00-foodin-reason-v1'
TARGET_NAMESPACE = 'ad_account_no'
# These are UI advertising-account numbers, never internal customer IDs.
TARGETS = (('foodin', 51952, 1030001),)
MAX_OUTPUT = 16384
CODE_PINS = {'naver_engine/store.py': '4d7baab1808777b2a4cc86d4761d5a89fdea3d5f6f075c3277733ccae3a28129', 'naver_engine/inspection_store.py': '49066bc37e04ac23e1cc60724b044593bb8888b04fb093c99d3cc39227ee9ad7', 'naver_engine/inspection_reads.py': '8fb5d3f90dcf83f24682d61a9f73d01e2771cd09ae4347050c7e0d1341dd2c3e', 'naver_engine/inspection_fields.py': '102028ecb4f35647043b5efc1751e516c92f326252b88c3ab6c983ca7c61ba6a', 'naver_engine/management.py': '84862507d3831053edf618c6d68e800f1f1a1ec4019bcc88030eacb4d14f37e4', 'naver_engine/management_store.py': '13ee58e1d4383acf3ab8da469e7e09b9032640c2629e601809a3991b4c650fc5', 'naver_engine/inventory.py': '2a5c4d5f6acb0b431daa9e16be517322a43008aa636cfdf90c49c4a9305ae28e', 'naver_engine/product_evidence.py': '755c97900d34e06ac4a7f46c4ac3aafb3477f5a616cb560bb002f86deac87711', 'naver_engine/sync.py': '7ddd57ccce8a8edcf13e3d4495d748d122b067e1bba32becfa6326a4dda32dad', 'backend/app/naver_auto/org_snapshot.py': '34da0635ee7d071c3dd02bf4001343f2c42001ebc70d7e5548e692d687920f97', 'backend/app/naver_auto/scope.py': 'fd25fae418f27e6bd9b01415489164eb85241a5151a3e5fa1ad085edec7b3cd7', 'naver_engine/inspection_catalog.py': '7f6bdc58d716dd2d5b559d944211682c81f0efad9024c8f147861ecb5e977103'}
READ_FAILURE_CODES = frozenset(('SOURCE_DIAGNOSTICS_READER_FAILED SOURCE_DIAGNOSTICS_READ_FAILED '
    'SOURCE_DIAGNOSTICS_DEADLINE SOURCE_DIAGNOSTICS_TIME SOURCE_DIAGNOSTICS_ROW_LIMIT '
    'SOURCE_DIAGNOSTICS_DATABASE_PATH SOURCE_DIAGNOSTICS_READER_MODE SOURCE_DIAGNOSTICS_TARGETS '
    'SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS '
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
    "stage_revision,matching_fingerprint,generation,requested_at,actor,status,checked_at,next_try_at,attempts,error_code,"
    "CASE WHEN progress_json IS NULL THEN NULL ELSE '' END AS progress_json,progress_hash")
MAX_PROGRESS_BYTES, MAX_PROGRESS_TOTAL = 8*1024*1024, 32*1024*1024

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

def pending_state(policy, state):
    return policy['decision'].cadence != 'blocked' and (state is None or
        (state['possibility_id'], state['stage_key'], state['stage_revision']) !=
        (policy['possibility_id'], policy['stage_key'], policy['stage_revision']))

def full_progress(connection,row,deadline,cache,total):
    if row is None or row['progress_json'] is None:
        return row
    key=row['job_key']
    if key in cache:
        return cache[key]
    check_deadline(deadline)
    raw=connection.execute('SELECT substr(progress_json,1,?),length(progress_json) FROM naver_auto_inspection_job WHERE job_key=?',
        (MAX_PROGRESS_BYTES+1,key)).fetchone()
    if raw is None or type(raw[0]) is not str or raw[1]>MAX_PROGRESS_BYTES:
        raise ValueError('SOURCE_DIAGNOSTICS_ROW_LIMIT')
    size=len(raw[0].encode())
    if size>MAX_PROGRESS_BYTES or total[0]+size>MAX_PROGRESS_TOTAL:
        raise ValueError('SOURCE_DIAGNOSTICS_ROW_LIMIT')
    total[0]+=size
    value=dict(row,progress_json=raw[0]);cache[key]=value
    check_deadline(deadline)
    return value

def candidate_projection(store, now, policies, source, prior, deadline, modules):
    P, IS, IC = modules['P'], modules['IS'], modules['IC']
    catalog_proof = store._inspection_catalog_proof(now)
    progress_cache, progress_total = {}, [0]
    gates, current_jobs, entries = {}, {}, []
    continuity_cache = {}
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
        attempted_at = IS._inspection_order_attempt(old, job, row['possibility_id'], now)
        bound = IS._binding(old, job, row['possibility_id']) and IC._scope_matches(old, job, row['possibility_id'])
        if bound and old['status']=='ok' and store._inspection_context(store._conn,old,now,catalog_proof) is None:
            bound=False
        if not bound:
            candidate_old=full_progress(store._conn,old,deadline,progress_cache,progress_total) if old is not None else None
            if not store._inspection_resumable(store._conn,candidate_old,job,row['possibility_id'],now,catalog_proof,continuity_cache):
                old=None
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
                            attempted_at, cid))
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
        'management_sync_pending_count': sync_pending, 'rank_exact': sync_pending == 0,
        'catalog_proof':catalog_proof,'progress_cache':progress_cache,'progress_total':progress_total}

# Added closed-only projection. Pure proof validators remain the exact b00 ones.
TARGET_DAY = '2026-10-18'
GATES = GATES | {'MANUAL_TAKES_PRECEDENCE'}
SCOPE_FIELDS = ('job_key','customer_id','possibility_id','kind','cycle_day','period_start','period_end',
    'snapshot_at','catalog_at','stage_revision','matching_fingerprint','generation','requested_at','actor')
FACTS = ('checkpoint_sealed','checkpoint_binding_equal','catalog_digest_equal','catalog_epoch_equal',
    'catalog_stable_at_equal','direct_context_valid','bridge_sealed','current_scope_available',
    'bridge_checkpoint_equal','bridge_catalog_equal','bridge_scope_equal','current_scope_binding_equal')
BRANCHES = frozenset(('row_missing job_missing catalog_unavailable direct_valid bridge_missing bridge_null '
    'bridge_invalid bridge_seal_invalid checkpoint_seal_invalid checkpoint_role_invalid current_scope_unavailable '
    'bridge_checkpoint_mismatch bridge_catalog_mismatch bridge_scope_mismatch anchor_context_rejected '
    'anchor_role_invalid anchor_status_invalid scope_binding_mismatch attempt_time_invalid progress_missing '
    'progress_size_invalid progress_hash_mismatch progress_shape_invalid progress_confirmed progress_future '
    'anchor_resumable_rejected continuity_valid').split())
LIMITS = dict(stored_snapshot_only=True,management_not_synchronized=True,dispatch_order_not_proven=True,
    worker_current_job_unobserved=True,collection_completion_not_proven=True,scope_hash_components_unrecoverable=True)


def proof_read(store, key, limit, modules):
    row=store._conn.execute('SELECT CASE WHEN length(CAST(value AS BLOB))<=? THEN value END FROM naver_auto_meta WHERE key=?',
        (limit,key)).fetchone()
    if row is None:
        return 'missing',None
    if row[0] is None:
        return 'invalid',None
    if type(row[0]) is str and row[0].strip()=='null':
        return 'null',None
    value=modules['IC'].decode_proof(row[0],limit)
    return ('decoded',value) if value is not None else ('invalid',None)


def scope_equal(row, job, pid, IC):
    if row is None or job is None:
        return {k:None for k in SCOPE_FIELDS}
    expected=dict(job,possibility_id=pid,snapshot_at=IC._kst_text(job['snapshot_at']),
        requested_at=job.get('requested_at'),actor=job.get('actor'))
    return {k:IC._dump(row[k])==IC._dump(expected[k]) for k in SCOPE_FIELDS}


def anchor_failure(IC, IR, IS, checkpoint, row, job, pid, now, anchor):
    # Called only after exact IC.resumable_continuity has returned False.
    if IC.context(checkpoint,row,now,anchor,IS._ERROR_CODES) is None:
        return 'anchor_context_rejected'
    if checkpoint['role']!='checkpoint':return 'anchor_role_invalid'
    if row['status'] not in {'reading','partial','retry','limited'}:return 'anchor_status_invalid'
    if not IC._scope_matches(row,job,pid):return 'scope_binding_mismatch'
    if not IC.last_attempt(row,job,pid,now):return 'attempt_time_invalid'
    raw=row['progress_json']
    if type(raw) is not str:return 'progress_missing'
    if len(raw.encode())>IS._MAX_BYTES:return 'progress_size_invalid'
    if hashlib.sha256(raw.encode()).hexdigest()!=row['progress_hash']:return 'progress_hash_mismatch'
    try:
        progress=IR.validate_progress(json.loads(raw),job)
    except (IR.CheckpointInvalid,KeyError,TypeError,ValueError,OverflowError,RecursionError):
        return 'progress_shape_invalid'
    if progress['confirmed']:return 'progress_confirmed'
    times=[record['checked_at'] for record in progress['entities'].values()]
    times += [record['checked_at'] for group in progress['targets'].values() for record in group.values()]
    times += [record['checked_at'] for record in progress['performance'].values()]
    if any(datetime.fromisoformat(at)>now for at in times):return 'progress_future'
    return 'anchor_resumable_rejected'


def continuation_projection(store,row,job,pid,now,catalog,modules):
    IC,IS,IR=(modules[k] for k in ('IC','IS','IR'))
    out=dict(checkpoint_state='missing',bridge_state='missing',facts={k:False for k in FACTS},
        resumable=False,branch='row_missing',historical_scope_components='unknown')
    if row is None:return out
    if job is None:return dict(out,branch='job_missing')
    if catalog is None:return dict(out,branch='catalog_unavailable')
    cp_state,checkpoint=proof_read(store,IC.checkpoint_key(row['job_key']),4096,modules)
    bridge_state,bridge=proof_read(store,IC.continuity_key(row['job_key']),4096,modules)
    out.update(checkpoint_state=cp_state,bridge_state=bridge_state)
    facts=out['facts']
    cp_sealed=IC._sealed(checkpoint,IC._CHECKPOINT_FIELDS)
    facts['checkpoint_sealed']=cp_sealed
    if cp_sealed:
        facts['checkpoint_binding_equal']=IC._dump(checkpoint['binding'])==IC._dump(IC._binding(row,IS._ERROR_CODES))
        for public,key in (('catalog_digest_equal','content_digest'),('catalog_epoch_equal','content_epoch'),
                           ('catalog_stable_at_equal','stable_content_at')):
            facts[public]=checkpoint[key]==catalog[key]
    facts['current_scope_binding_equal']=IC._scope_matches(row,job,pid)
    facts['direct_context_valid']=IC.context(checkpoint,row,now,catalog,IS._ERROR_CODES) is not None
    if IC.resumable(checkpoint,row,job,pid,now,catalog,IS._ERROR_CODES,IS._MAX_BYTES):
        return dict(out,resumable=True,branch='direct_valid')
    # Exactly the original bridge sequence: no scope recomputation when bridge is absent.
    if bridge is None:return dict(out,branch='bridge_'+bridge_state)
    facts['bridge_sealed']=IC._sealed(bridge,IC._CONTINUITY_FIELDS)
    scopes=store._inspection_continuity_scopes(store._conn,store.account_catalog(),now,{row['customer_id']})
    scope=scopes.get(row['customer_id'])
    facts['current_scope_available']=IC._hex(scope)
    if facts['bridge_sealed'] and cp_sealed:
        facts['bridge_checkpoint_equal']=bridge['checkpoint_hash']==IC._hash(checkpoint)
        facts['bridge_catalog_equal']=bridge['catalog_hash']==IC._hash(catalog)
        facts['bridge_scope_equal']=facts['current_scope_available'] and bridge['scope_hash']==scope
    ordered=(('bridge_seal_invalid',facts['bridge_sealed']),('checkpoint_seal_invalid',cp_sealed),
        ('checkpoint_role_invalid',cp_sealed and checkpoint['role'] in {'reading','checkpoint'}),
        ('current_scope_unavailable',facts['current_scope_available']),
        ('bridge_checkpoint_mismatch',facts['bridge_checkpoint_equal']),
        ('bridge_catalog_mismatch',facts['bridge_catalog_equal']),('bridge_scope_mismatch',facts['bridge_scope_equal']))
    for branch,ok in ordered:
        if not ok:return dict(out,branch=branch)
    valid=IC.resumable_continuity(bridge,checkpoint,row,job,pid,now,catalog,scope,IS._ERROR_CODES,IS._MAX_BYTES)
    if valid:return dict(out,resumable=True,branch='continuity_valid')
    if checkpoint['role']!='checkpoint':return dict(out,branch='anchor_role_invalid')
    anchor=dict(catalog,generated_at=row['catalog_at'],**{k:checkpoint[k] for k in ('content_digest','content_epoch','stable_content_at')})
    return dict(out,branch=anchor_failure(IC,IR,IS,checkpoint,row,job,pid,now,anchor))


def checkpoint_metadata(row,now,modules):
    out=dict(state='missing',checked_at=None,next_try_at=None,attempts=None,next_index=None,queue_tasks=None,confirmed=None)
    if row is None:return out
    out.update(checked_at=stamp(row['checked_at']),next_try_at=stamp(row['next_try_at']),attempts=row['attempts'])
    if row['progress_json'] is None:return out
    IS,IR=modules['IS'],modules['IR']
    try:
        raw=row['progress_json']
        if type(raw) is not str or len(raw.encode())>IS._MAX_BYTES or hashlib.sha256(raw.encode()).hexdigest()!=row['progress_hash']:
            return dict(out,state='invalid')
        progress=IR.validate_progress(json.loads(raw),IS._job(row))
        if datetime.fromisoformat(row['checked_at'])>now or any(datetime.fromisoformat(at)>now for at in IS._observed_times(progress)):
            return dict(out,state='invalid')
        return dict(out,state='valid',next_index=progress['next_index'],queue_tasks=len(progress['queue']),confirmed=progress['confirmed'])
    except (IR.CheckpointInvalid,KeyError,TypeError,ValueError,OverflowError,RecursionError):
        return dict(out,state='invalid')


def collect(store, now, deadline, modules, targets=TARGETS):
    if targets!=TARGETS:raise ValueError('SOURCE_DIAGNOSTICS_TARGETS')
    now=now.astimezone(KST); c=store._conn
    if now.date().isoformat()!=TARGET_DAY:raise ValueError('SOURCE_DIAGNOSTICS_TIME')
    S,MS,I,O,Y,IS=(modules[k] for k in ('S','MS','I','O','Y','IS'))
    if c.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=('21',):
        raise ValueError('SOURCE_DIAGNOSTICS_SCHEMA')
    accounts=rows(c,'SELECT customer_id,ad_account_no,present FROM naver_auto_account',(),MAX_ACCOUNTS,deadline)
    label,pid,adno=TARGETS[0]
    matching=[r for r in accounts if r['present']==1 and type(r['ad_account_no']) is int and r['ad_account_no']==adno]
    if not matching:raise ValueError('SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND')
    if len(matching)!=1:raise ValueError('SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS')
    cid=matching[0]['customer_id']
    if type(cid) is not int or not 0<cid<10**15:raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    states=store.management_states();policies=MS.snapshot(store,now,stage_states=states)
    if len(policies)>MAX_ACCOUNTS:raise ValueError('SOURCE_DIAGNOSTICS_ACCOUNT_LIMIT')
    requests=rows(c,'SELECT customer_id,possibility_id,requested_at,actor,request_kind,period_start,period_end FROM naver_auto_manual_read',(),MAX_ACCOUNTS,deadline)
    catalog,catalog_state=I.catalog_status(store,now,header_only=True)
    source=S._PerformanceSelectionSource(store,now,store.inventory_snapshot(now),
        frozenset(r['customer_id'] for r in accounts if r['present']==1),catalog,catalog_state,
        O.allows_raising(Y.org_freshness(store,now)),MS._organization(store),store.decision_fingerprint(),states,policies,
        {r['customer_id']:r for r in requests})
    saved=rows(c,'SELECT '+JOB_COLUMNS+' FROM naver_auto_inspection_job WHERE cycle_day>=?',
        ((now.date()-timedelta(days=8)).isoformat(),),MAX_JOBS,deadline)
    prior={r['job_key']:r for r in saved}
    if len(prior)!=len(saved):raise ValueError('SOURCE_DIAGNOSTICS_DUPLICATE')
    candidates=candidate_projection(store,now,policies,source,prior,deadline,modules)
    policy=policies.get(cid); pair=bool(policy and policy['possibility_id']==pid and policy['matched'] is True)
    selected_job=candidates['current_jobs'].get(cid) if pair else None
    job=None
    if pair and policy['decision'].cadence=='daily' and source.snapshot is not None and source.catalog is not None:
        period=modules['P'].period_for('daily',now.date())
        job=store._performance_job(cid,'daily',period.cycle_day,period.since,period.until,policy,source.snapshot,
            source.catalog['generated_at'],matching_fingerprint=source.fingerprint)
        job['job_key']='inspection:'+job['job_key']
    current=prior.get(job['job_key']) if job else None
    current=full_progress(c,current,deadline,candidates['progress_cache'],candidates['progress_total'])
    latest=rows(c,'SELECT '+JOB_COLUMNS+" FROM naver_auto_inspection_job WHERE customer_id=? AND possibility_id=? AND kind='daily' AND cycle_day=? ORDER BY checked_at DESC,rowid DESC LIMIT 1",(cid,pid,TARGET_DAY),1,deadline)
    latest=full_progress(c,latest[0] if latest else None,deadline,candidates['progress_cache'],candidates['progress_total'])
    continuation=continuation_projection(store,current,job,pid,now,candidates['catalog_proof'],modules)
    if current is not None and job is not None:
        expected=store._inspection_resumable(c,current,job,pid,now,candidates['catalog_proof'])
        if continuation['resumable'] is not expected:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    same_selected=bool(job and selected_job and selected_job['job_key']==job['job_key'])
    exact=candidates['rank_exact'] and pair and same_selected
    rank=candidates['order'].index(cid) if exact and cid in candidates['order'] else None
    attempted=IS._inspection_order_attempt(current,job,pid,now) if current and job else ''
    result=dict(schema_version=21,selector_model='b00-foodin-readonly-v1',target_identifier_namespace=TARGET_NAMESPACE,
        observed_at=now.isoformat(),target=label,
        sources=dict(account_snapshot_current=source.snapshot is not None,catalog_current=candidates['catalog_proof'] is not None,
            organization_current=source.org_allowed,current_expected_pair=pair,management_sync_pending=bool(policy and pending_state(policy,states.get(cid)))),
        job=dict(kind=job['kind'] if job else None,current_daily=bool(job and job['kind']=='daily' and job['cycle_day']==now.date().isoformat()),
            current_record_present=current is not None,latest_matches_current=bool(latest and job and latest['job_key']==job['job_key']),
            ordering_attempt_at=stamp(attempted) if attempted else None,checkpoint=checkpoint_metadata(latest,now,modules)),
        scope_equal=scope_equal(current,job,pid,modules['IC']),continuation=continuation,
        selection=dict(gate='MANUAL_TAKES_PRECEDENCE' if selected_job and selected_job['kind']=='manual' else candidates['gates'].get(cid,'ACCOUNT_NOT_IN_SNAPSHOT'),rank_exact=exact,
            eligible_count=candidates['observed_eligible_count'] if exact else None,ahead_count=rank,
            within_selected_24=cid in candidates['selected'] if exact else None,ordering_hint_only=True),
        limits=dict(LIMITS),mutations=0)
    validate_projection(result);check_deadline(deadline)
    return result


def validate_projection(v):
    def shape(value,keys):
        if type(value) is not dict or set(value)!=set(keys):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    def boolean(value):
        if type(value) is not bool:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    def number(value,maximum,nullable=False):
        if nullable and value is None:return
        if type(value) is not int or not 0<=value<=maximum:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_NUMBER')
    shape(v,('schema_version','selector_model','target_identifier_namespace','observed_at','target','sources','job','scope_equal','continuation','selection','limits','mutations'))
    if type(v['schema_version']) is not int or v['schema_version']!=21 or type(v['mutations']) is not int or v['mutations']!=0:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_SCHEMA')
    if v['selector_model']!='b00-foodin-readonly-v1' or v['target_identifier_namespace']!='ad_account_no' or v['target']!='foodin':
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_TARGETS')
    if v['observed_at'] is None:raise ValueError('SOURCE_DIAGNOSTICS_TIME')
    stamp(v['observed_at'])
    shape(v['sources'],('account_snapshot_current','catalog_current','organization_current','current_expected_pair','management_sync_pending'))
    for value in v['sources'].values():boolean(value)
    j=v['job'];shape(j,('kind','current_daily','current_record_present','latest_matches_current','ordering_attempt_at','checkpoint'))
    if j['kind'] not in (None,'daily','weekly','manual'):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
    for k in ('current_daily','current_record_present','latest_matches_current'):boolean(j[k])
    stamp(j['ordering_attempt_at'])
    p=j['checkpoint'];shape(p,('state','checked_at','next_try_at','attempts','next_index','queue_tasks','confirmed'))
    if p['state'] not in ('missing','invalid','valid'):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
    stamp(p['checked_at']);stamp(p['next_try_at']);number(p['attempts'],4,True)
    for k in ('next_index','queue_tasks'):number(p[k],1000000,True)
    if p['confirmed'] is not None:boolean(p['confirmed'])
    if p['state']=='valid' and (p['next_index'] is None or p['queue_tasks'] is None or p['confirmed'] is None or p['next_index']>p['queue_tasks']):
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    shape(v['scope_equal'],SCOPE_FIELDS)
    for value in v['scope_equal'].values():
        if value is not None:boolean(value)
    a=v['continuation'];shape(a,('checkpoint_state','bridge_state','facts','resumable','branch','historical_scope_components'))
    for k in ('checkpoint_state','bridge_state'):
        if a[k] not in ('missing','null','invalid','decoded'):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
    shape(a['facts'],FACTS)
    for value in a['facts'].values():boolean(value)
    boolean(a['resumable'])
    if a['branch'] not in BRANCHES or a['historical_scope_components']!='unknown':raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
    if a['resumable']!=(a['branch'] in ('direct_valid','continuity_valid')):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    q=v['selection'];shape(q,('gate','rank_exact','eligible_count','ahead_count','within_selected_24','ordering_hint_only'))
    if q['gate'] not in GATES:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
    boolean(q['rank_exact']);boolean(q['ordering_hint_only'])
    if q['ordering_hint_only'] is not True:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMITS')
    for k in ('eligible_count','ahead_count'):number(q[k],MAX_ACCOUNTS,True)
    if q['within_selected_24'] is not None:boolean(q['within_selected_24'])
    if not q['rank_exact'] and any(q[k] is not None for k in ('eligible_count','ahead_count','within_selected_24')):
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    if type(v['limits']) is not dict or v['limits']!=LIMITS or any(type(x) is not bool for x in v['limits'].values()):
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMITS')
    if len(json.dumps(v,allow_nan=False,separators=(',',':')).encode())>16384:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
    return v

'''

_HEADER = ('import json,re,sqlite3,time\nfrom datetime import date,datetime,timedelta,timezone\n'
           + 'TARGETS='+repr(TARGETS)+'\nTARGET_NAMESPACE='+repr(TARGET_NAMESPACE)+'\n')
exec(compile(_HEADER+PROJECTION_SOURCE, '<completion-source-diagnostics>', 'exec'))


def validate_package(package):
    expected = {'baseline':BASELINE,'source_commit':SOURCE,'source_tar_gz_sha256':ARCHIVE,'mode':MODE}
    if type(package) is not dict or set(package) != set(expected) or package != expected:
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')


def script():
    prefix = ('import hashlib,json,os,re,socket,sqlite3,sys,time\nfrom pathlib import Path\n'
              'from datetime import date,datetime,timedelta,timezone\nTARGETS='+repr(TARGETS)
              +'\nTARGET_NAMESPACE='+repr(TARGET_NAMESPACE)+'\n')
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
    from naver_engine import store as S,management_store as MS,inventory as I,management as P,inspection_store as IS,inspection_reads as IR,inspection_catalog as IC,sync as Y,product_evidence as PE
    from app.naver_auto import org_snapshot as O
    modules=dict(S=S,MS=MS,I=I,P=P,IS=IS,IR=IR,IC=IC,O=O,Y=Y,PE=PE)
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
    return validate_projection(value)


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
            or prepared.get('package',{}).get('run_id')!=PREPARE_RUN
            # P4 stores config/source/image proof here. The three policy fields
            # are in its returned prepare projection, not this persisted file.
            # The persisted started receipt below must still prove all three.
            or prepared.get('runtime_environment_preserved') is not True
            or prepared.get('inventory_enabled') is not True or prepared.get('execution_enabled') is not False
            or prepared.get('runtime_flags_verified') is not True or started.get('ok') is not True
            or started.get('previous_commit')!=PREVIOUS_SOURCE or started.get('operation_id')!=APPLY_OPERATION
            or started.get('database_policy')!='preserve-in-place' or started.get('database_opened_by_controller') is not False
            or started.get('source_warmup_performed') is not False or started.get('database_snapshot_verified') is not False
            or started.get('rollback_requires_matching_database') is not False or started.get('saved_export_companion_preserved') is not True
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
