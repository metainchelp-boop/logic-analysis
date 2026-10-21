"""Fixed 799 schema21 read-only setup and terminal-job observation diagnosis.

No writer, scheduler tick, collector, provider, environment or raw log reads.
Only setup policy, selected scope, current binding checks, five failure fields and one closed decision reason leave the reader.
"""
import hashlib
import json
import os
from pathlib import Path
import re

STAGE = 'input'
SOURCE = '799d80225a8df0c897a125dcab75fd04978b1dbb'
ARCHIVE = '5de3b31c0eac7a021f360a68c9fa5d849dc385d498136a9143c2a1479e46fafa'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
SCHEMA = 21
PREPARE_RUN = '38275892133'
APPLY_OPERATION = '292df5809d8d49c49256c3bc3314bb7a'
PREVIOUS_SOURCE = 'dc168ff8cf8dac519ea38597305a0d9dd6f6c843'
MODE = 'observation-diagnostics-ad-account-799-v2'
P6_CONTROLLER_SHA256 = '8dddb4156047f9a0bb64b3ad0db23eac62ca0cd858ff9c1cbffe4bbbbbc81426'
NATIVE_RUN = '38268019380'
CANONICAL_SHA256 = 'c6bb211aa96f181755a0130484618b5d7977f286ef402380bc8c196c5804513e'
EVENT_SELECTOR = {'possibility_id':51952,'ad_account_no':1030001,'period_key':'weekly:2026-10-05:2026-10-11',
    'numeric_revision':4,'strategy_revision':0,'reserved_from':'2026-10-13T01:27:00+09:00','reserved_before':'2026-10-13T01:28:00+09:00'}
TARGET_NAMESPACE = 'ad_account_no'
# These are UI advertising-account numbers, never internal customer IDs.
TARGETS = (('gomso', 74789, 2488728), ('foodin', 51952, 1030001))
MAX_OUTPUT = 16384
CODE_PINS = {'naver_engine/store.py': '50a49f123095e76536ad77e7bb7ebbcb988c747014ed3cfdb9ce0e7f21da904f', 'naver_engine/inspection_store.py': 'aa694ce93b6094d2598f4f3e06eaacfed4a04b1f787e6bc715a22a9f30253799', 'naver_engine/inspection_reads.py': '965f5dac65cbf867a6232c5af2d3992a6324b81cc6470e65167e06d674d0e543', 'naver_engine/inspection_fields.py': '102028ecb4f35647043b5efc1751e516c92f326252b88c3ab6c983ca7c61ba6a', 'naver_engine/management.py': '84862507d3831053edf618c6d68e800f1f1a1ec4019bcc88030eacb4d14f37e4', 'naver_engine/management_store.py': '13ee58e1d4383acf3ab8da469e7e09b9032640c2629e601809a3991b4c650fc5', 'naver_engine/inventory.py': '2a5c4d5f6acb0b431daa9e16be517322a43008aa636cfdf90c49c4a9305ae28e', 'naver_engine/product_evidence.py': '755c97900d34e06ac4a7f46c4ac3aafb3477f5a616cb560bb002f86deac87711', 'naver_engine/sync.py': '7ddd57ccce8a8edcf13e3d4495d748d122b067e1bba32becfa6326a4dda32dad', 'backend/app/naver_auto/org_snapshot.py': '34da0635ee7d071c3dd02bf4001343f2c42001ebc70d7e5548e692d687920f97', 'backend/app/naver_auto/scope.py': 'fd25fae418f27e6bd9b01415489164eb85241a5151a3e5fa1ad085edec7b3cd7', 'naver_engine/inspection_catalog.py': '3d0652bcb8ef6a5eef6bf16ec85f1e0319b96a078abd68381af070aa3dad46b6'}
READ_FAILURE_CODES = frozenset(('SOURCE_DIAGNOSTICS_READER_FAILED SOURCE_DIAGNOSTICS_READ_FAILED '
    'SOURCE_DIAGNOSTICS_DEADLINE SOURCE_DIAGNOSTICS_TIME SOURCE_DIAGNOSTICS_ROW_LIMIT '
    'SOURCE_DIAGNOSTICS_DATABASE_PATH SOURCE_DIAGNOSTICS_READER_MODE SOURCE_DIAGNOSTICS_TARGETS '
    'SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS '
    'SOURCE_DIAGNOSTICS_SCHEMA SOURCE_DIAGNOSTICS_ACCOUNT_LIMIT SOURCE_DIAGNOSTICS_DUPLICATE '
    'SOURCE_DIAGNOSTICS_IDENTITY SOURCE_DIAGNOSTICS_NETWORK_FORBIDDEN SOURCE_DIAGNOSTICS_CODE_PIN '
    'SOURCE_DIAGNOSTICS_MUTATION SOURCE_DIAGNOSTICS_OUTPUT_LIMIT SOURCE_DIAGNOSTICS_OUTPUT_FIELDS '
    'SOURCE_DIAGNOSTICS_OUTPUT_SCHEMA SOURCE_DIAGNOSTICS_OUTPUT_TARGETS SOURCE_DIAGNOSTICS_OUTPUT_ENUM '
    'SOURCE_DIAGNOSTICS_OUTPUT_NUMBER SOURCE_DIAGNOSTICS_OUTPUT_COUNTS SOURCE_DIAGNOSTICS_OUTPUT_LIMITS SOURCE_DIAGNOSTICS_PROJECTION_MISMATCH').split())

PROJECTION_SOURCE = r'''
KST = timezone(timedelta(hours=9))
MAX_ACCOUNTS, MAX_JOBS = 4000, 20000
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
JOB_COLUMNS = ('job_key,customer_id,possibility_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,'
    "stage_revision,matching_fingerprint,generation,requested_at,actor,status,checked_at,next_try_at,attempts,error_code,"
    "CASE WHEN progress_json IS NULL THEN NULL ELSE '' END AS progress_json,progress_hash")
MAX_PROGRESS_BYTES, MAX_PROGRESS_TOTAL = 8*1024*1024, 32*1024*1024

READ_PHASE = 'source-pin'
READ_STAGES = frozenset(('source-pin','import','open','bounds','policy','source-snapshot','scope',
    'source-validation','setup','proof','learning-failure','output','cleanup','reader-command'))
READ_KINDS = frozenset(('sqlite-busy','sqlite-interrupted','sqlite-error','shape-invalid','internal','closed-refusal'))

def set_read_stage(stage):
    global READ_PHASE
    if stage not in READ_STAGES:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    READ_PHASE=stage

def validate_failure_detail(value):
    if type(value) is not dict or set(value)!={'stage','kind'} or type(value['stage']) is not str or value['stage'] not in READ_STAGES or type(value['kind']) is not str or value['kind'] not in READ_KINDS:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    return value

def classify_failure(error,stage=None):
    stage=READ_PHASE if stage is None else stage
    code=getattr(error,'sqlite_errorcode',None)
    if isinstance(error,sqlite3.Error):
        code=code & 255 if type(code) is int else None
        kind='sqlite-busy' if code in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED) else 'sqlite-interrupted' if code==sqlite3.SQLITE_INTERRUPT else 'sqlite-error'
    elif type(error) is ValueError and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in READ_FAILURE_CODES:
        kind='closed-refusal'
    elif isinstance(error,(KeyError,TypeError,AttributeError,ValueError,OverflowError,RecursionError,UnicodeError)):
        kind='shape-invalid'
    else:kind='internal'
    return validate_failure_detail({'stage':stage,'kind':kind})

def closed_reader_failure(error):
    code=error.args[0] if isinstance(error,ValueError) and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED'
    return {'failure':code,'failure_detail':classify_failure(error)}

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


BRANCHES = frozenset(('NO_OBSERVATION','POLICY_INACTIVE','MANUAL_PENDING','NO_CURRENT_SCOPE_ROW',
    'CYCLE_NOT_CURRENT','CURRENT_ROW_INVALID','FUTURE_CHECKED_AT','CURRENT_PARTIAL','CHECKPOINT_INVALID','CURRENT_COMPLETE'))
OBS_ERRORS = ERRORS | {'SOURCE_STALE','MANUAL_PENDING','CHECKPOINT_INVALID'}
MAX_HISTORY_ROWS = 200

def optional_match(left,right):
    return left is not None and right is not None and left==right

def bounded_bodies(connection,cid,pid,revision,row,deadline,total):
    # Inspect sizes in SQLite before SELECT * / setup_observation can read bodies.
    if row is not None:
        values=rows(connection,'SELECT length(CAST(progress_json AS BLOB)) AS size FROM naver_auto_inspection_job WHERE job_key=?',
            (row['job_key'],),1,deadline)
        size=values[0]['size'] if values else None
        if size is not None:
            if type(size) is not int or not 0<=size<=MAX_PROGRESS_BYTES:
                raise ValueError('SOURCE_DIAGNOSTICS_ROW_LIMIT')
            total[0]+=size
    history=rows(connection,'SELECT length(CAST(body_json AS BLOB)) AS size FROM naver_auto_setting_observation '
        'WHERE customer_id=? AND possibility_id IS ? AND stage_revision=? ORDER BY history_id DESC LIMIT 200',
        (cid,pid,revision),MAX_HISTORY_ROWS,deadline)
    for item in history:
        size=item['size']
        if type(size) is not int or not 0<=size<=MAX_PROGRESS_BYTES:
            raise ValueError('SOURCE_DIAGNOSTICS_ROW_LIMIT')
        total[0]+=size
    if total[0]>MAX_PROGRESS_TOTAL:
        raise ValueError('SOURCE_DIAGNOSTICS_ROW_LIMIT')
    return len(history)

def actual_projection(observation):
    if observation is None:
        return {'present':False,'status':None,'error_code':None,'stale':None,'complete':False,
            'generation_present':False,'checked_at_present':False}
    return {'present':True,'status':closed(observation['status'],STATUSES|{'pending'}),
        'error_code':None if observation['error_code'] is None else closed(observation['error_code'],OBS_ERRORS),
        'stale':observation['stale'],'complete':observation['complete'],
        'generation_present':observation['generation'] is not None,'checked_at_present':observation['checked_at'] is not None}

def expected_projection(branch,row=None):
    out={'present':True,'status':'pending','error_code':None,'stale':True,'complete':False,
        'generation_present':False,'checked_at_present':False}
    if branch=='NO_OBSERVATION':return dict(out,present=False,status=None,stale=None)
    if branch in ('POLICY_INACTIVE','CURRENT_ROW_INVALID'):out['error_code']='SOURCE_STALE'
    elif branch=='MANUAL_PENDING':out.update(error_code='MANUAL_PENDING',stale=False,generation_present=True)
    elif branch in ('FUTURE_CHECKED_AT','CURRENT_PARTIAL','CHECKPOINT_INVALID','CURRENT_COMPLETE'):
        out.update(status=closed(row['status'],STATUSES),error_code=None if row['error_code'] is None else closed(row['error_code'],OBS_ERRORS),
            stale=False,generation_present=True,checked_at_present=True)
        if branch=='FUTURE_CHECKED_AT':out.update(status='pending',error_code='CHECKPOINT_INVALID',stale=True,checked_at_present=False)
        elif branch=='CHECKPOINT_INVALID':out.update(status='limited',error_code='CHECKPOINT_INVALID')
        elif branch=='CURRENT_COMPLETE':out['complete']=True
    return out

def context_binding_matches(proof,row,IC,IS):
    try:
        return bool(proof and 'binding' in proof and IC._dump(proof['binding'])==IC._dump(IC._binding(row,IS._ERROR_CODES)))
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError):
        return False

def target_projection(store,now,deadline,modules,cid,pid,policy,states,catalog,catalog_state,snapshot,fingerprint,org_current,total):
    S,MS,P,IS,IC= (modules[key] for key in ('S','MS','P','IS','IC'))
    c=store._conn
    set_read_stage('scope')
    exists=c.execute('SELECT 1 FROM naver_auto_inspection_job WHERE customer_id=? LIMIT 1',(cid,)).fetchone() is not None
    requests=rows(c,'SELECT * FROM naver_auto_manual_read WHERE customer_id=?',(cid,),1,deadline)
    request=requests[0] if requests else None
    active=policy is not None and policy['decision'].cadence!='blocked'
    current_pid,revision=(policy['possibility_id'],policy['stage_revision']) if policy else (None,None)
    manual=None
    if active and request and catalog and snapshot is not None:
        manual=store._inspection_manual_job(request,policy,snapshot,catalog['generated_at'],fingerprint,now)
    cadence=policy['decision'].cadence if policy else None
    cycle=str(P.period_for(cadence,now).cycle_day) if active else None
    selected=rows(c,'SELECT '+JOB_COLUMNS+' FROM naver_auto_inspection_job WHERE customer_id=? '
        'AND possibility_id IS ? AND stage_revision=? AND ((kind=? AND cycle_day=?) OR (kind=\'manual\' AND generation=?)) '
        'ORDER BY generation DESC,checked_at DESC,rowid DESC LIMIT 1',
        (cid,current_pid,revision,cadence,cycle,manual['generation'] if manual else None),1,deadline) if active else []
    row=selected[0] if selected else None
    set_read_stage('bounds')
    history_count=bounded_bodies(c,cid,current_pid,revision,row,deadline,total) if active and (exists or manual) else 0
    if row is not None:
        row=rows(c,'SELECT * FROM naver_auto_inspection_job WHERE job_key=?',(row['job_key'],),1,deadline)[0]
    set_read_stage('source-validation')
    job=IS._job(row) if row else None
    current_cycle=bool(row and (row['cycle_day']==cycle if row['kind']!='manual' else
        row['cycle_day']==str(now.date()) and manual is not None and row['generation']==manual['generation']))
    core_valid=bool(job and store._inspection_account_valid(job,now))
    full_valid=bool(job and store.inspection_account_valid(job,now))
    catalog_proof=store._inspection_catalog_proof(now)
    proof=store._inspection_read_proof(c,IC.checkpoint_key(row['job_key']),4096) if row else None
    context=store._inspection_context(c,row,now,catalog_proof) if row else None
    state=states.get(cid)
    scope_matches=bool(row and state and IC._scope_matches(row,job,state['possibility_id']))
    row_binding=bool(row and state and IS._binding(row,job,state['possibility_id']))
    request_today=bool(request and datetime.fromisoformat(request['requested_at']).astimezone(KST).date()==now.date())
    newer_manual=bool(job and job['kind']!='manual' and manual and manual['generation']>job['generation'])
    set_read_stage('setup')
    observation=store.setup_observation(cid,now)
    actual=actual_projection(observation)
    if not exists and not request or not exists and manual is None:branch='NO_OBSERVATION'
    elif not active:branch='POLICY_INACTIVE'
    elif manual is not None and (row is None or row['generation']<manual['generation']):branch='MANUAL_PENDING'
    elif row is None:branch='NO_CURRENT_SCOPE_ROW'
    elif not current_cycle:branch='CYCLE_NOT_CURRENT'
    elif not full_valid:branch='CURRENT_ROW_INVALID'
    elif datetime.fromisoformat(row['checked_at'])>now:branch='FUTURE_CHECKED_AT'
    elif row['status']!='ok':branch='CURRENT_PARTIAL'
    elif not actual['complete']:branch='CHECKPOINT_INVALID'
    else:branch='CURRENT_COMPLETE'
    expected=expected_projection(branch,row)
    if actual!=expected:raise ValueError('SOURCE_DIAGNOSTICS_PROJECTION_MISMATCH')
    set_read_stage('proof')
    checks=None if row is None else {
        'account_snapshot_matches':snapshot is not None and row['snapshot_at']==S._kst_text(snapshot,'계정 원천'),
        'catalog_accepted':catalog_state=='accepted',
        'catalog_stamp_matches':catalog is not None and row['catalog_at']==catalog['generated_at'],
        'organization_current':org_current,
        'matching_fingerprint_matches':row['matching_fingerprint']==fingerprint,
        'account_present':c.execute('SELECT present FROM naver_auto_account WHERE customer_id=?',(cid,)).fetchone()==(1,),
        'management_revision_matches':state is not None and row['stage_revision']==state['stage_revision'],
        'management_pair_matches':state is not None and row['possibility_id']==state['possibility_id'],
        'row_binding_matches':row_binding,'row_scope_matches':scope_matches,
        'current_cycle_matches':current_cycle,'core_account_valid':core_valid,'full_account_valid':full_valid,
        'catalog_proof_current':catalog_proof is not None,'context_proof_present':proof is not None,
        'context_proof_sealed':bool(proof and IC._sealed(proof,IC._CHECKPOINT_FIELDS)),
        'context_binding_matches':context_binding_matches(proof,row,IC,IS),
        'context_catalog_content_matches':bool(type(proof) is dict and type(catalog_proof) is dict and all(proof.get(k)==catalog_proof[k] for k in ('content_digest','content_epoch','stable_content_at'))),
        'context_current':context is not None,'newer_valid_manual_generation':newer_manual,
        'manual_generation_matches':bool(manual and row['kind']=='manual' and row['generation']==manual['generation'])}
    reasons=[]
    if checks is not None:
        for key in ('account_present','account_snapshot_matches','catalog_accepted','catalog_stamp_matches','organization_current',
            'matching_fingerprint_matches','management_revision_matches','management_pair_matches','row_binding_matches',
            'row_scope_matches','current_cycle_matches','catalog_proof_current','context_proof_present',
            'context_proof_sealed','context_binding_matches','context_catalog_content_matches','context_current'):
            if checks[key] is False:reasons.append(key.upper())
        if newer_manual:reasons.append('NEWER_VALID_MANUAL_GENERATION')
        if not core_valid:reasons.append('CORE_ACCOUNT_INVALID')
        if not full_valid:reasons.append('FULL_ACCOUNT_INVALID')
    return {'policy':{'present':policy is not None,'active':active,'cadence':closed(cadence,CADENCES) if policy else None,
        'reason':closed(policy['decision'].reason,REASONS) if policy else None,
        'expected_pair_matches':bool(policy and policy['possibility_id']==pid and policy['matched'] is True),
        'source_current':bool(policy and policy['source_current'])},
        'scope':{'any_job_present':exists,'current_row_present':row is not None,
            'kind':closed(row['kind'],frozenset(('daily','weekly','manual'))) if row else None,
            'status':closed(row['status'],STATUSES) if row else None,'history_rows_checked':history_count},
        'manual':{'present':request is not None,'requested_today':request_today,
            'expected_pair_matches':bool(request and request['possibility_id']==pid),'current_valid_request':manual is not None,
            'kind':closed(request['request_kind'] or 'manual',frozenset(('manual','manual_period'))) if request else None},
        'binding_checks':checks,'failed_checks':reasons,'observation':dict(actual,branch=branch,projection_matches_actual=True)}

FAILURE_DETAIL_KEYS = frozenset(('stage','error_class','provider_invocation_attempted','observation_bound','observation_flushed'))
FAILURE_DETAIL_STAGES = frozenset(('reserve','observation-bind','invoke-wrapper','context-build','pre-invoke-guard','provider-invoke','document-validation','draft-save'))
FAILURE_DETAIL_CLASSES = frozenset(('store-busy','store-refused','store-error','sqlite-busy','sqlite-error','provider-refused','authority-refused','internal'))
LEARNING_PERIOD = 'weekly:2026-10-05:2026-10-11'
NUMERIC_REVISION, STRATEGY_REVISION = 4, 0
LEARNING_JOB_KEYS = frozenset(('job_id actor narrowed report_id account_key revision_fingerprint expected_version expires_at proof_hash state created_at updated_at diagnostic result_version').split())
LEARNING_DIAGNOSTICS = frozenset(('context-changed token-expired job-interrupted unknown timeout tls network protocol request-size response-size response-shape envelope-json document-json truncated configuration context-invalid document-invalid numeric-citation-required reference-unavailable unconnected-evidence http').split())

def private_json(raw, maximum):
    if type(raw) is not str or len(raw.encode('utf8'))>maximum:raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('SOURCE_DIAGNOSTICS_DUPLICATE')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _x:(_ for _ in ()).throw(ValueError('SOURCE_DIAGNOSTICS_IDENTITY')))

def valid_learning_detail(value):
    if (type(value) is not dict or set(value)!=FAILURE_DETAIL_KEYS or type(value['stage']) is not str
            or value['stage'] not in FAILURE_DETAIL_STAGES or type(value['error_class']) is not str
            or value['error_class'] not in FAILURE_DETAIL_CLASSES or type(value['provider_invocation_attempted']) is not bool
            or any(value[key] is not None and type(value[key]) is not bool for key in ('observation_bound','observation_flushed'))):
        raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    return dict(value)

def learning_identity(job):
    return hashlib.sha256(json.dumps([job['actor'],job['narrowed'],job['report_id'],job['account_key'],
        job['revision_fingerprint'],job['expected_version']],separators=(',',':')).encode()).hexdigest()

def valid_learning_job(value):
    # Exact 799 LJ.clean ABI, without importing another product runtime module.
    if type(value) is not dict or set(value)!=LEARNING_JOB_KEYS:raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    for key,size in (('job_id',32),('account_key',64),('revision_fingerprint',64),('proof_hash',64)):
        if type(value[key]) is not str or re.fullmatch('[0-9a-f]{'+str(size)+'}',value[key]) is None:raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    if (type(value['actor']) is not int or not 0<=value['actor']<2**63 or type(value['narrowed']) is not bool
            or type(value['report_id']) is not int or not 0<value['report_id']<2**63
            or type(value['expected_version']) is not int or not 0<=value['expected_version']<2**53
            or type(value['state']) is not str or value['state'] not in ('queued','running','succeeded','failed','interrupted')):
        raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    for key in ('expires_at','created_at','updated_at'):
        if type(value[key]) is not str or not 20<=len(value[key])<=40 or datetime.fromisoformat(value[key]).utcoffset() is None:
            raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    diagnostic=value['diagnostic']
    if diagnostic is not None:
        if (type(diagnostic) is not dict or set(diagnostic)!={'code','http_status'} or type(diagnostic['code']) is not str
                or diagnostic['code'] not in LEARNING_DIAGNOSTICS
                or (diagnostic['code']=='http' and (type(diagnostic['http_status']) is not int or not 100<=diagnostic['http_status']<=599))
                or (diagnostic['code']!='http' and diagnostic['http_status'] is not None)):
            raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    version=value['result_version']
    if ((value['state']=='succeeded' and (type(version) is not int or not 0<version<2**53))
            or (value['state']!='succeeded' and version is not None)
            or (value['state'] in ('queued','running','succeeded') and diagnostic is not None)
            or (value['state'] in ('failed','interrupted') and diagnostic is None)):
        raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
    return value

def learning_failure_projection(store,now,deadline,cid,pid,policy):
    # Never infer the UI's numeric revision as a report ID. No raw JSON leaves this function.
    if pid!=51952 or not policy or policy['possibility_id']!=pid or policy['matched'] is not True or policy['source_current'] is not True:
        return None
    try:
        c=store._conn
        account_key=hashlib.sha256(str(cid).encode('ascii')).hexdigest()
        selected=rows(c,'SELECT report_id,revision_fingerprint,CASE WHEN length(CAST(payload_json AS BLOB))<=8388608 THEN payload_json END AS payload '
            'FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1',
            (pid,LEARNING_PERIOD),1,deadline)
        if len(selected)!=1:return None
        report=selected[0];rid,fp=report['report_id'],report['revision_fingerprint']
        if type(rid) is not int or rid<=0 or type(fp) is not str or re.fullmatch('[0-9a-f]{64}',fp) is None:return None
        payload=private_json(report['payload'],8388608)
        expected_period={'kind':'weekly','start':'2026-10-05','end':'2026-10-11'}
        if (type(payload) is not dict or payload.get('revision_fingerprint')!=fp or payload.get('period_key')!=LEARNING_PERIOD
                or type(payload.get('period')) is not dict or any(payload['period'].get(k)!=v for k,v in expected_period.items())
                or type(payload.get('_account_reports')) is not dict):return None
        revision=payload['revision_no'] if 'revision_no' in payload else c.execute('SELECT count(*) FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? AND report_id<=?',(pid,LEARNING_PERIOD,rid)).fetchone()[0]
        account=payload['_account_reports'].get(str(cid))
        if (type(revision) is not int or revision!=NUMERIC_REVISION or type(account) is not dict
                or account.get('period')!=payload['period'] or account.get('period_key')!=LEARNING_PERIOD
                or type(account.get('revision_no')) is not int or account['revision_no']!=NUMERIC_REVISION):return None
        if '_expected_customers' in account and (type(account['_expected_customers']) is not list
                or len(account['_expected_customers'])!=1 or type(account['_expected_customers'][0]) is not int
                or account['_expected_customers']!=[cid]):return None
        dirty=c.execute('SELECT pending FROM naver_auto_report_dirty WHERE possibility_id=? AND period_key=?',(pid,LEARNING_PERIOD)).fetchone()
        if dirty and (type(dirty[0]) is not int or dirty[0]!=0):return None
        # Current observed strategy revision is exactly zero: any saved head means a changed scope.
        if c.execute('SELECT 1 FROM naver_auto_meta WHERE key=?',('report-strategy-head:'+str(rid)+':'+account_key,)).fetchone():return None
        window_from=datetime.fromisoformat(EVENT_SELECTOR['reserved_from']);window_before=datetime.fromisoformat(EVENT_SELECTOR['reserved_before'])
        records=rows(c,'SELECT key,CASE WHEN length(CAST(value AS BLOB))<=4096 THEN value END AS value FROM naver_auto_meta '
            'WHERE key>=? AND key<? ORDER BY key LIMIT 101',('learning-job:','learning-job:\uffff'),100,deadline)
        found=[]
        for record in records:
            job=valid_learning_job(private_json(record['value'],4096))
            identity=learning_identity(job)
            if record['key']!='learning-job:'+identity:return None
            if (job['report_id'],job['account_key'],job['revision_fingerprint'],job['expected_version'])!=(rid,account_key,fp,STRATEGY_REVISION):continue
            reservation=c.execute('SELECT CASE WHEN length(CAST(value AS BLOB))<=2048 THEN value END FROM naver_auto_meta WHERE key=?',('learning-call:'+job['job_id'],)).fetchone()
            if reservation is None:continue
            reserved=private_json(reservation[0],2048)
            if (type(reserved) is not dict or set(reserved)!={'actor','at','reserved_microusd','proof_hash','report_id','account_key','possibility_id'}
                    or any(reserved.get(k)!=v for k,v in {'actor':job['actor'],'proof_hash':job['proof_hash'],'report_id':rid,'account_key':account_key,'possibility_id':pid}.items())
                    or type(reserved['actor']) is not int or type(reserved['report_id']) is not int or type(reserved['possibility_id']) is not int
                    or type(reserved['reserved_microusd']) is not int or not 0<reserved['reserved_microusd']<=10**12
                    or type(reserved['at']) is not str or stamp(reserved['at']) is None):return None
            at=datetime.fromisoformat(reserved['at'])
            if not window_from<=at<window_before:continue
            # Fixed authenticated manual event, never an assumed current login actor.
            updated=datetime.fromisoformat(job['updated_at'])
            if not datetime.fromisoformat(job['created_at'])<=at<=updated<=now:return None
            # Historical terminal reading is permitted only for an event completed while authorized.
            # This never revives a token or grants execution authority; current scope is checked below.
            if not updated<datetime.fromisoformat(job['expires_at']):return None
            found.append(job)
        if len(found)!=1 or found[0]['state'] not in ('failed','interrupted'):return None
        job=found[0]
        # Pure current organization, CID ownership and ACT_APPROVE checks for the observed event owner.
        store._learning_actor(pid,account_key,job['actor'],now,narrowed=job['narrowed'])
        side=c.execute('SELECT CASE WHEN length(CAST(value AS BLOB))<=1024 THEN value END FROM naver_auto_meta WHERE key=?',('learning-failure:'+learning_identity(job),)).fetchone()
        saved=private_json(side[0],1024) if side else None
        if type(saved) is not dict or set(saved)!={'job_id','detail'} or saved['job_id']!=job['job_id']:return None
        check_deadline(deadline)
        return valid_learning_detail(saved['detail'])
    except Exception:
        # Missing/ambiguous/malformed/unauthorized is unknown, never a fabricated False.
        return None

LEARNING_FAILURE_REASONS=frozenset(('CURRENT_AUTHORITY_REFUSED', 'EVENT_AMBIGUOUS', 'EVENT_NOT_FOUND', 'EVENT_NOT_TERMINAL', 'EVENT_TIME_INVALID', 'JOB_SET_INVALID', 'NOT_SELECTED_TARGET', 'NUMERIC_REVISION_MISMATCH', 'OBSERVED', 'POLICY_NOT_CURRENT', 'READ_BOUND_EXCEEDED', 'READ_INTERNAL_ERROR', 'READ_SHAPE_ERROR', 'READ_SQL_BUSY', 'READ_SQL_ERROR', 'REPORT_DIRTY', 'REPORT_NOT_FOUND', 'REPORT_SCOPE_MISMATCH', 'RESERVATION_INVALID', 'SIDECAR_JOB_MISMATCH', 'SIDECAR_MISSING', 'SIDECAR_SHAPE_INVALID', 'STRATEGY_REVISION_CHANGED'))

def learning_resolution_result(reason, detail=None):
    return {'learning_failure': detail, 'learning_failure_reason': reason}

def learning_failure_resolution(store, now, deadline, cid, pid, policy, *, authority_refusals=()):
    if pid != 51952:
        return learning_resolution_result('NOT_SELECTED_TARGET')
    if not policy or policy['possibility_id'] != pid or policy['matched'] is not True or (policy['source_current'] is not True):
        return learning_resolution_result('POLICY_NOT_CURRENT')
    try:
        c = store._conn
        account_key = hashlib.sha256(str(cid).encode('ascii')).hexdigest()
        selected = rows(c, 'SELECT report_id,revision_fingerprint,CASE WHEN length(CAST(payload_json AS BLOB))<=8388608 THEN payload_json END AS payload FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1', (pid, LEARNING_PERIOD), 1, deadline)
        if len(selected) != 1:
            return learning_resolution_result('REPORT_NOT_FOUND')
        report = selected[0]
        rid, fp = (report['report_id'], report['revision_fingerprint'])
        if type(rid) is not int or rid <= 0 or type(fp) is not str or (re.fullmatch('[0-9a-f]{64}', fp) is None):
            return learning_resolution_result('REPORT_SCOPE_MISMATCH')
        payload = private_json(report['payload'], 8388608)
        expected_period = {'kind': 'weekly', 'start': '2026-10-05', 'end': '2026-10-11'}
        if type(payload) is not dict or payload.get('revision_fingerprint') != fp or payload.get('period_key') != LEARNING_PERIOD or (type(payload.get('period')) is not dict) or any((payload['period'].get(k) != v for k, v in expected_period.items())) or (type(payload.get('_account_reports')) is not dict):
            return learning_resolution_result('REPORT_SCOPE_MISMATCH')
        revision = payload['revision_no'] if 'revision_no' in payload else c.execute('SELECT count(*) FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? AND report_id<=?', (pid, LEARNING_PERIOD, rid)).fetchone()[0]
        account = payload['_account_reports'].get(str(cid))
        if type(revision) is not int or revision != NUMERIC_REVISION:
            return learning_resolution_result('NUMERIC_REVISION_MISMATCH')
        if type(account) is not dict or account.get('period') != payload['period'] or account.get('period_key') != LEARNING_PERIOD:
            return learning_resolution_result('REPORT_SCOPE_MISMATCH')
        if type(account.get('revision_no')) is not int or account['revision_no'] != NUMERIC_REVISION:
            return learning_resolution_result('NUMERIC_REVISION_MISMATCH')
        if '_expected_customers' in account and (type(account['_expected_customers']) is not list or len(account['_expected_customers']) != 1 or type(account['_expected_customers'][0]) is not int or (account['_expected_customers'] != [cid])):
            return learning_resolution_result('REPORT_SCOPE_MISMATCH')
        dirty = c.execute('SELECT pending FROM naver_auto_report_dirty WHERE possibility_id=? AND period_key=?', (pid, LEARNING_PERIOD)).fetchone()
        if dirty and (type(dirty[0]) is not int or dirty[0] != 0):
            return learning_resolution_result('REPORT_DIRTY')
        if c.execute('SELECT 1 FROM naver_auto_meta WHERE key=?', ('report-strategy-head:' + str(rid) + ':' + account_key,)).fetchone():
            return learning_resolution_result('STRATEGY_REVISION_CHANGED')
        window_from = datetime.fromisoformat(EVENT_SELECTOR['reserved_from'])
        window_before = datetime.fromisoformat(EVENT_SELECTOR['reserved_before'])
        try:
            records = rows(c, 'SELECT key,CASE WHEN length(CAST(value AS BLOB))<=4096 THEN value END AS value FROM naver_auto_meta WHERE key>=? AND key<? ORDER BY key LIMIT 101', ('learning-job:', 'learning-job:\uffff'), 100, deadline)
        except ValueError:
            return learning_resolution_result('READ_BOUND_EXCEEDED' if time.monotonic() > deadline else 'JOB_SET_INVALID')
        found = []
        for record in records:
            try:
                job = valid_learning_job(private_json(record['value'], 4096))
                identity = learning_identity(job)
            except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
                return learning_resolution_result('JOB_SET_INVALID')
            if record['key'] != 'learning-job:' + identity:
                return learning_resolution_result('JOB_SET_INVALID')
            if (job['report_id'], job['account_key'], job['revision_fingerprint'], job['expected_version']) != (rid, account_key, fp, STRATEGY_REVISION):
                continue
            reservation = c.execute('SELECT CASE WHEN length(CAST(value AS BLOB))<=2048 THEN value END FROM naver_auto_meta WHERE key=?', ('learning-call:' + job['job_id'],)).fetchone()
            if reservation is None:
                continue
            try:
                reserved = private_json(reservation[0], 2048)
            except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
                return learning_resolution_result('RESERVATION_INVALID')
            if type(reserved) is not dict or set(reserved) != {'actor', 'at', 'reserved_microusd', 'proof_hash', 'report_id', 'account_key', 'possibility_id'} or any((reserved.get(k) != v for k, v in {'actor': job['actor'], 'proof_hash': job['proof_hash'], 'report_id': rid, 'account_key': account_key, 'possibility_id': pid}.items())) or (type(reserved['actor']) is not int) or (type(reserved['report_id']) is not int) or (type(reserved['possibility_id']) is not int) or (type(reserved['reserved_microusd']) is not int) or (not 0 < reserved['reserved_microusd'] <= 10 ** 12) or (type(reserved['at']) is not str) or (stamp(reserved['at']) is None):
                return learning_resolution_result('RESERVATION_INVALID')
            at = datetime.fromisoformat(reserved['at'])
            if not window_from <= at < window_before:
                continue
            updated = datetime.fromisoformat(job['updated_at'])
            if not datetime.fromisoformat(job['created_at']) <= at <= updated <= now:
                return learning_resolution_result('EVENT_TIME_INVALID')
            if not updated < datetime.fromisoformat(job['expires_at']):
                return learning_resolution_result('EVENT_TIME_INVALID')
            found.append(job)
        if not found:
            return learning_resolution_result('EVENT_NOT_FOUND')
        if len(found) != 1:
            return learning_resolution_result('EVENT_AMBIGUOUS')
        if found[0]['state'] not in ('failed', 'interrupted'):
            return learning_resolution_result('EVENT_NOT_TERMINAL')
        job = found[0]
        try:
            store._learning_actor(pid, account_key, job['actor'], now, narrowed=job['narrowed'])
        except authority_refusals:
            return learning_resolution_result('CURRENT_AUTHORITY_REFUSED')
        side = c.execute('SELECT CASE WHEN length(CAST(value AS BLOB))<=1024 THEN value END FROM naver_auto_meta WHERE key=?', ('learning-failure:' + learning_identity(job),)).fetchone()
        if side is None:
            return learning_resolution_result('SIDECAR_MISSING')
        try:
            saved = private_json(side[0], 1024)
        except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
            return learning_resolution_result('SIDECAR_SHAPE_INVALID')
        if type(saved) is not dict or set(saved) != {'job_id', 'detail'}:
            return learning_resolution_result('SIDECAR_SHAPE_INVALID')
        if saved['job_id'] != job['job_id']:
            return learning_resolution_result('SIDECAR_JOB_MISMATCH')
        check_deadline(deadline)
        try:
            detail = valid_learning_detail(saved['detail'])
        except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
            return learning_resolution_result('SIDECAR_SHAPE_INVALID')
        return learning_resolution_result('OBSERVED', detail)
    except sqlite3.DatabaseError as error:
        code = getattr(error, 'sqlite_errorcode', None)
        busy = type(code) is int and code & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        return learning_resolution_result('READ_SQL_BUSY' if busy else 'READ_SQL_ERROR')
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeError):
        return learning_resolution_result('READ_BOUND_EXCEEDED' if time.monotonic() > deadline else 'READ_SHAPE_ERROR')
    except Exception:
        return learning_resolution_result('READ_INTERNAL_ERROR')

def collect(store,now,deadline,modules,targets=TARGETS):
    if targets!=TARGETS:raise ValueError('SOURCE_DIAGNOSTICS_TARGETS')
    now=now.astimezone(KST);c=store._conn
    set_read_stage('bounds')
    if c.execute("SELECT CASE WHEN length(CAST(value AS BLOB))<=2 THEN value END FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=('21',):
        raise ValueError('SOURCE_DIAGNOSTICS_SCHEMA')
    if c.execute('SELECT COUNT(*) FROM naver_auto_inspection_job').fetchone()[0]>MAX_JOBS:
        raise ValueError('SOURCE_DIAGNOSTICS_ROW_LIMIT')
    accounts=rows(c,'SELECT customer_id,ad_account_no,present FROM naver_auto_account',(),MAX_ACCOUNTS,deadline)
    # Bound all metadata before pinned Store parsers can read catalog/org bodies.
    sizes=rows(c,'SELECT length(CAST(value AS BLOB)) AS size FROM naver_auto_meta',(),20000,deadline)
    if any(type(x['size']) is not int or x['size']>16*1024*1024 for x in sizes) or sum(x['size'] for x in sizes)>64*1024*1024:
        raise ValueError('SOURCE_DIAGNOSTICS_ROW_LIMIT')
    resolved=[]
    for label,pid,adno in targets:
        found=[a for a in accounts if a['present']==1 and type(a['ad_account_no']) is int and a['ad_account_no']==adno]
        if not found:raise ValueError('SOURCE_DIAGNOSTICS_TARGET_NOT_FOUND')
        if len(found)!=1:raise ValueError('SOURCE_DIAGNOSTICS_TARGET_AMBIGUOUS')
        cid=found[0]['customer_id']
        if type(cid) is not int or not 0<cid<10**15:raise ValueError('SOURCE_DIAGNOSTICS_IDENTITY')
        resolved.append((label,pid,cid))
    S,MS,I,O,Y=(modules[k] for k in ('S','MS','I','O','Y'))
    set_read_stage('policy')
    states=store.management_states();policies=MS.snapshot(store,now,stage_states=states)
    set_read_stage('source-snapshot')
    catalog,state=I.catalog_status(store,now);snapshot=store.inventory_snapshot(now)
    fingerprint=store.decision_fingerprint();org_current=O.allows_raising(Y.org_freshness(store,now))
    total=[0];result={}
    for label,pid,cid in resolved:
        check_deadline(deadline)
        result[label]=target_projection(store,now,deadline,modules,cid,pid,policies.get(cid),states,
            catalog,state,snapshot,fingerprint,org_current,total)
        set_read_stage('learning-failure')
        resolution=learning_failure_resolution(store,now,deadline,cid,pid,policies.get(cid),authority_refusals=(S.StoreRefused,modules['SC'].ScopeError,modules['RV'].QueryInvalid,modules['RV'].SourceUnavailable)) if label=='foodin' else {'learning_failure':None,'learning_failure_reason':'NOT_SELECTED_TARGET'}
        result[label].update(resolution)
    return {'schema_version':21,'projection_model':'799-setup-observation-v2','target_identifier_namespace':TARGET_NAMESPACE,
        'targets':result,'limits':{'stored_snapshot_only':True,'source_guards_unchanged':True,'management_not_synchronized':True,
            'collection_completion_not_proven':True,'scheduler_budget_unobserved':True,'ads_unchanged':True},'mutations':0}
'''

_HEADER = ('import hashlib,json,re,sqlite3,time\nfrom datetime import date,datetime,timedelta,timezone\n'
           + 'TARGETS='+repr(TARGETS)+'\nTARGET_NAMESPACE='+repr(TARGET_NAMESPACE)+'\nEVENT_SELECTOR='+repr(EVENT_SELECTOR)+'\n')
exec(compile(_HEADER+PROJECTION_SOURCE, '<completion-source-diagnostics>', 'exec'))


def validate_package(package):
    selector={'possibility_id':51952,'ad_account_no':1030001,'period_key':'weekly:2026-10-05:2026-10-11','numeric_revision':4,'strategy_revision':0,'reserved_from':'2026-10-13T01:27:00+09:00','reserved_before':'2026-10-13T01:28:00+09:00'}
    if type(EVENT_SELECTOR) is not dict or EVENT_SELECTOR!=selector or any(type(EVENT_SELECTOR[k]) is not type(v) for k,v in selector.items()):
        raise ValueError('SOURCE_DIAGNOSTICS_NOT_PINNED')
    expected = {'baseline':BASELINE,'source_commit':SOURCE,'source_tar_gz_sha256':ARCHIVE,'mode':MODE,
        'p6_controller_sha256':P6_CONTROLLER_SHA256,'native_run_id':NATIVE_RUN,'canonical_sha256':CANONICAL_SHA256,'event_selector':EVENT_SELECTOR}
    if type(package) is not dict or set(package) != set(expected) or package != expected:
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')
    given=package['event_selector']
    if type(given) is not dict or set(given)!=set(selector) or any(type(given[k]) is not type(v) for k,v in selector.items()):
        raise ValueError('SOURCE_DIAGNOSTICS_PACKAGE')


def script():
    prefix = ('import hashlib,json,os,re,socket,sqlite3,sys,time\nfrom pathlib import Path\n'
              'from datetime import date,datetime,timedelta,timezone\nTARGETS='+repr(TARGETS)
              +'\nTARGET_NAMESPACE='+repr(TARGET_NAMESPACE)+'\nEVENT_SELECTOR='+repr(EVENT_SELECTOR)+'\n')
    body = r'''
pending_failure=None
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
    set_read_stage('import')
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S,management_store as MS,inventory as I,management as P,inspection_store as IS,inspection_reads as IR,inspection_catalog as IC,sync as Y,product_evidence as PE
    from app.naver_auto import org_snapshot as O,scope as SC
    from naver_engine import report_views as RV
    modules=dict(S=S,MS=MS,I=I,P=P,IS=IS,IR=IR,IC=IC,O=O,Y=Y,PE=PE,SC=SC,RV=RV)
    deadline=time.monotonic()+20
    set_read_stage('open')
    connection=connect_reader(Path('/var/lib/naver-engine/engine.db'))
    reader=S.Store(connection,'/var/lib/naver-engine/engine.db',None,writer=False)
    try:
        connection.set_progress_handler(lambda:time.monotonic()>=deadline,1000)
        connection.execute('BEGIN')
        result=collect(reader,datetime.now(KST),deadline,modules)
        if connection.total_changes!=0:
            raise ValueError('SOURCE_DIAGNOSTICS_MUTATION')
    except Exception as error:
        pending_failure=closed_reader_failure(error)
        raise
    finally:
        set_read_stage('cleanup')
        try:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
        finally:
            reader.close()
    set_read_stage('output')
    check_deadline(deadline)
    encoded=json.dumps(result,sort_keys=True,allow_nan=False,separators=(',',':'))
    if len(encoded.encode())>16384:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
    print(encoded)
except Exception as error:
    print(json.dumps(pending_failure if pending_failure is not None else closed_reader_failure(error)))
'''
    return (prefix+'CODE_PINS='+repr(CODE_PINS)+'\nREAD_FAILURE_CODES='+repr(READ_FAILURE_CODES)+'\n'+PROJECTION_SOURCE+body).encode()


def validate_result(value):
    if type(value) is not dict or set(value)!={'schema_version','projection_model','target_identifier_namespace','targets','limits','mutations'}:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    if type(value['schema_version']) is not int or value['schema_version']!=21 or type(value['mutations']) is not int or value['mutations']!=0:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_SCHEMA')
    if value['projection_model']!='799-setup-observation-v2' or value['target_identifier_namespace']!=TARGET_NAMESPACE or type(value['targets']) is not dict or set(value['targets'])!={x[0] for x in TARGETS}:
        raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_TARGETS')
    def exact(row,keys):
        if type(row) is not dict or set(row)!=set(keys):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    def boolean(row,keys):
        if any(type(row[k]) is not bool for k in keys):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
    check_keys={'account_present','account_snapshot_matches','catalog_accepted','catalog_stamp_matches','organization_current',
        'matching_fingerprint_matches','management_revision_matches','management_pair_matches','row_binding_matches',
        'row_scope_matches','current_cycle_matches','core_account_valid','full_account_valid','catalog_proof_current',
        'context_proof_present','context_proof_sealed','context_binding_matches','context_catalog_content_matches',
        'context_current','newer_valid_manual_generation','manual_generation_matches'}
    failed_keys=(check_keys-{'core_account_valid','full_account_valid','newer_valid_manual_generation','manual_generation_matches'})
    for label,row in value['targets'].items():
        exact(row,('policy','scope','manual','binding_checks','failed_checks','observation','learning_failure','learning_failure_reason'))
        reason=row['learning_failure_reason']
        if type(reason) is not str or reason not in LEARNING_FAILURE_REASONS or (reason=='OBSERVED')!=(row['learning_failure'] is not None):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        if (label=='gomso' and reason!='NOT_SELECTED_TARGET') or (label=='foodin' and reason=='NOT_SELECTED_TARGET'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_TARGETS')
        if row['learning_failure'] is not None:
            if label!='foodin':raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_FIELDS')
            valid_learning_detail(row['learning_failure'])
        p=row['policy'];exact(p,('present','active','cadence','reason','expected_pair_matches','source_current'))
        boolean(p,('present','active','expected_pair_matches','source_current'))
        if row['learning_failure'] is not None and not all(p[k] for k in ('present','expected_pair_matches','source_current')):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if p['cadence'] not in (None,'daily','weekly','blocked','UNRECOGNIZED') or p['reason'] not in REASONS|{None,'UNRECOGNIZED'}:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        if p['active']!=(p['present'] and p['cadence']!='blocked') or (not p['present'] and (p['cadence'] is not None or p['reason'] is not None or p['expected_pair_matches'] or p['source_current'])):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        s=row['scope'];exact(s,('any_job_present','current_row_present','kind','status','history_rows_checked'))
        boolean(s,('any_job_present','current_row_present'))
        if type(s['history_rows_checked']) is not int or not 0<=s['history_rows_checked']<=200:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_NUMBER')
        if s['kind'] not in (None,'daily','weekly','manual','UNRECOGNIZED') or s['status'] not in STATUSES|{None,'UNRECOGNIZED'}:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        if s['current_row_present']!=(s['kind'] is not None and s['status'] is not None) or s['current_row_present'] and not s['any_job_present']:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        m=row['manual'];exact(m,('present','requested_today','expected_pair_matches','current_valid_request','kind'))
        boolean(m,('present','requested_today','expected_pair_matches','current_valid_request'))
        if m['kind'] not in (None,'manual','manual_period','UNRECOGNIZED') or m['present']!=(m['kind'] is not None) or (not m['present'] and any(m[k] for k in ('requested_today','expected_pair_matches','current_valid_request'))) or m['current_valid_request'] and (not m['requested_today'] or m['kind']!='manual'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        c=row['binding_checks'];f=row['failed_checks']
        if s['current_row_present']!=(c is not None):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        expected_failures=[]
        if c is not None:
            exact(c,check_keys);boolean(c,check_keys)
            expected_failures=[k.upper() for k in failed_keys if c[k] is False]
            if c['newer_valid_manual_generation']:expected_failures.append('NEWER_VALID_MANUAL_GENERATION')
            if not c['core_account_valid']:expected_failures.append('CORE_ACCOUNT_INVALID')
            if not c['full_account_valid']:expected_failures.append('FULL_ACCOUNT_INVALID')
            if c['full_account_valid'] and (not c['core_account_valid'] or not all(c[k] for k in failed_keys)):
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if type(f) is not list or any(type(x) is not str for x in f) or len(set(f))!=len(f) or set(f)!=set(expected_failures):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        o=row['observation'];exact(o,('present','status','error_code','stale','complete','generation_present','checked_at_present','branch','projection_matches_actual'))
        boolean(o,('present','complete','generation_present','checked_at_present','projection_matches_actual'))
        if o['stale'] is not None and type(o['stale']) is not bool or o['branch'] not in BRANCHES or o['status'] not in STATUSES|{None,'pending','UNRECOGNIZED'} or o['error_code'] not in OBS_ERRORS|{None,'UNRECOGNIZED'}:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_ENUM')
        if o['projection_matches_actual'] is not True or o['complete']!=(o['branch']=='CURRENT_COMPLETE'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='NO_OBSERVATION':
            if any(o[k] for k in ('present','complete','generation_present','checked_at_present')) or o['status'] is not None or o['error_code'] is not None or o['stale'] is not None:
                raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        elif not o['present'] or o['stale'] is None:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['error_code']=='SOURCE_STALE' and (o['branch'] not in ('POLICY_INACTIVE','CURRENT_ROW_INVALID') or o['generation_present'] or o['checked_at_present'] or o['stale'] is not True):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='POLICY_INACTIVE' and (p['active'] or o['error_code']!='SOURCE_STALE'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='CURRENT_ROW_INVALID' and (c is None or c['full_account_valid'] or not p['active'] or o['error_code']!='SOURCE_STALE'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='MANUAL_PENDING' and (not m['current_valid_request'] or o['stale'] or not o['generation_present'] or o['checked_at_present'] or o['error_code']!='MANUAL_PENDING'):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='CURRENT_PARTIAL' and (c is None or not c['full_account_valid'] or s['status']=='ok' or o['stale'] or not o['generation_present'] or not o['checked_at_present'] or o['status']!=s['status']):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['branch']=='NO_CURRENT_SCOPE_ROW' and (s['current_row_present'] or not p['active'] or o['error_code'] is not None or not o['stale']):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
        if o['complete'] and (c is None or not c['full_account_valid'] or not c['context_current'] or s['status']!='ok' or o['status']!='ok' or o['stale'] or not o['generation_present'] or not o['checked_at_present']):
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_COUNTS')
    exact(value['limits'],('stored_snapshot_only','source_guards_unchanged','management_not_synchronized','collection_completion_not_proven','scheduler_budget_unobserved','ads_unchanged'))
    if any(x is not True for x in value['limits'].values()):raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMITS')
    if len(json.dumps(value,allow_nan=False,separators=(',',':')).encode())>MAX_OUTPUT:raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
    return value


def run(package, host, release):
    """Same registered-read controller boundary, with an exact new closed profile.

    Only the separately registered 799 profile can invoke this controller.
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
            # P6 stores config/source/image proof here. The three policy fields
            # are in its returned prepare projection, not this persisted file.
            # The persisted started receipt below must still prove all three.
            or prepared.get('config_operation_id')!='74c912dddf824fae99012849bc4c19a5'
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
    failure_detail=None
    value=None
    try:
        try:
            raw=release.command(['docker','exec','-i','--user','10001:10001',identity,'python','-I','-B','-'],data=script(),timeout=30)
        except Exception as error:
            failure_detail=classify_failure(error,'reader-command')
            raise ValueError('SOURCE_DIAGNOSTICS_READER_FAILED') from None
        if len(raw)>MAX_OUTPUT:
            raise ValueError('SOURCE_DIAGNOSTICS_OUTPUT_LIMIT')
        value=json.loads(raw,object_pairs_hook=release.unique)
        if type(value) is dict and set(value) in ({'failure'},{'failure','failure_detail'}):
            if 'failure_detail' in value:failure_detail=validate_failure_detail(value['failure_detail'])
            code=value['failure']
            raise ValueError(code if type(code) is str and code in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED')
        validate_result(value)
    except Exception as error:
        primary=error.args[0] if isinstance(error,ValueError) and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in READ_FAILURE_CODES else 'SOURCE_DIAGNOSTICS_READ_FAILED'
        # Legacy one-field failures keep their original basic ABI. Locally
        # malformed output gains only a closed classification, never its text.
        if failure_detail is None and not (type(value) is dict and set(value)=={'failure'}):
            failure_detail=classify_failure(error,'output')
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
        failure={'ok':False,'mode':MODE,'source_commit':SOURCE,'mutations':0,
            'collection_completion_verified':False,'failure':{'primary_code':primary,
                'post_engine_code':post_engine,'post_legacy_baseline_code':post_legacy}}
        if primary is not None and failure_detail is not None:failure['failure_detail']=failure_detail
        return failure
    return {'ok':True,'mode':MODE,'source_commit':SOURCE,'reader_mode':'sqlite-mode-ro-query-only-authorizer',
        'database_opened_by_controller':False,'mutations':0,'existing_app_baseline_unchanged':True,
        'collection_completion_verified':False,'diagnostics':value}
