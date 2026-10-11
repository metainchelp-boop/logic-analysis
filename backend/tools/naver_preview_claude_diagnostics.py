"""Pinned V24 read-only Foodin diagnostics. Never configure/call a live provider."""
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time
from datetime import datetime, timezone

SOURCE = '10a46ddce2116e274e27fabaf73c7a94be6cda62'
ARCHIVE = '6a2a1075b1b2c31f47d45d8afdd080e8da786e49c3fdf173e82e51c0a3e3705c'
STORE = '1f3ce4f659a88ebb607c2bb063aa4cd057d4e6776a3544eb08bdc43c08a12e17'
BASELINE = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
BRANCH = 'refs/heads/codex/naver-claude-diagnostics-v24-20261011'
STAGE = 'input'
MAX_OUTPUT = 16384
PROJECTION_SOURCE = r'''
KST = timezone(timedelta(hours=9))
TARGET_PID = 51952
TARGET_ACCOUNT = 1030001
PERIOD = 'weekly:2026-09-28:2026-10-04'
WINDOW_START = '2026-10-11T07:50:00+00:00'
WINDOW_END = '2026-10-11T07:55:00+00:00'
WINDOW_SQL_START = '2026-10-11T16:50:00+09:00'
WINDOW_SQL_END = '2026-10-11T16:55:00+09:00'
GENERATION_CODES = frozenset(('timeout','tls','network','protocol','request-size','response-size',
    'response-shape','envelope-json','document-json','truncated','configuration','context-invalid',
    'document-invalid','numeric-citation-required','reference-unavailable','unconnected-evidence','unknown'))
ERROR_CODES = frozenset('CLAUDE_DIAG_'+name for name in (
    'BUDGET_METADATA','COMPOSE_CHANGED','CONTAINER_CHANGED','CONTAINER_ID','DATABASE_PATH','DATA_MOUNT',
    'DEADLINE','HOST_BASELINE','IDENTITY','IMAGE','MUTATION','NUMBER','OUTPUT_FIELDS','OUTPUT_LIMIT',
    'OUTPUT_SCOPE','PACKAGE_PIN','POST_ENGINE','POST_RELAY','POST_LEGACY_BASELINE','POST_RUNTIME',
    'READER_MODE','READ_FAILED','RECEIPT_SIZE','RESERVATION_METADATA','RUNTIME_CHANGED','RUNTIME_SIZE',
    'SCHEMA','SOURCE_MOUNT','SOURCE_NOT_READY','STORE_PIN','STRATEGY_LIMIT','STRATEGY_METADATA',
    'TARGET_ACCOUNT','TARGET_REPORT','TIME','WINDOW_LIMIT','WINDOW_TIME'))
STATES = frozenset(('empty','draft','approved'))
SOURCES = frozenset(('claude','staff','rule_based'))
SAFE_CODES = frozenset(('CONTEXT_INVALID','LEARNING_CONTEXT_INVALID','PLAN_CONTEXT_INVALID',
    'PROVIDER_NOT_CONFIGURED','PROVIDER_CONFIGURATION_INVALID','PROVIDER_REQUEST_SIZE',
    'PROVIDER_TRANSPORT_DISABLED','PROVIDER_UNAVAILABLE','PROVIDER_RESPONSE_SIZE',
    'PROVIDER_RESPONSE_INVALID','DOCUMENT_INVALID','NUMERIC_CITATION_REQUIRED',
    'UNCONNECTED_EVIDENCE','REFERENCE_UNAVAILABLE','JSON_INVALID','SYNTHETIC_REFUSED',
    'SYNTHETIC_CONTEXT_REFUSED','SYNTHETIC_SCOPE_OR_REVISION_REFUSED','SYNTHETIC_INVALID',
    'PROVIDER_MODEL_UNAVAILABLE','ACTOR_UNAVAILABLE'))

def fields(value, names):
    if type(value) is not dict or set(value) != set(names.split()):
        raise ValueError('CLAUDE_DIAG_OUTPUT_FIELDS')

def number(value):
    if type(value) is not int or not 0 <= value <= 2**63-1:
        raise ValueError('CLAUDE_DIAG_NUMBER')
    return value

def stamp(value):
    if value is None:
        return None
    if type(value) is not str or not 20 <= len(value) <= 40:
        raise ValueError('CLAUDE_DIAG_TIME')
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        raise ValueError('CLAUDE_DIAG_TIME') from None

def window_stamp(value):
    normalized=stamp(value)
    if normalized is None or not WINDOW_START <= normalized < WINDOW_END:
        raise ValueError('CLAUDE_DIAG_WINDOW_TIME')
    return normalized

def generation_audit(connection):
    # These records do not carry a report/account identity. Never infer attribution.
    rows=connection.execute('SELECT at,result FROM naver_auto_access_log '
        "WHERE action='learning-ai-generation' AND at>=? AND at<? ORDER BY log_id LIMIT 33",
        (WINDOW_SQL_START,WINDOW_SQL_END)).fetchall()
    if len(rows)>32:
        raise ValueError('CLAUDE_DIAG_WINDOW_LIMIT')
    events=[];unrecognized=0
    for at,result in rows:
        normalized=window_stamp(at)
        if type(result) is str and result.startswith('failed-') and result[7:] in GENERATION_CODES:
            events.append(dict(at=normalized,code=result[7:],http_status=None))
        elif type(result) is str and re.fullmatch('failed-http-[1-5][0-9]{2}',result):
            events.append(dict(at=normalized,code='http',http_status=int(result[-3:])))
        else:
            unrecognized+=1
    return dict(start_at=WINDOW_START,end_at=WINDOW_END,scope='instance_window_not_account_attributed',
        matched_count=len(events),unrecognized_count=unrecognized,events=events)

def readonly_authorizer(action, arg1, arg2, database, source):
    if action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_TRANSACTION,
                  sqlite3.SQLITE_SAVEPOINT,sqlite3.SQLITE_RECURSIVE):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_DENY if (arg2 or '').lower() in (
            'load_extension','readfile','writefile','shell','eval','fts3_tokenizer') else sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and arg2 is None and (arg1 or '').lower() in ('query_only','database_list'):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_PRAGMA and (arg1 or '').lower() == 'table_info' and arg2 == 'naver_auto_link_memory':
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY

def connect_reader(path):
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('CLAUDE_DIAG_DATABASE_PATH')
    connection = sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,isolation_level=None,timeout=1)
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA busy_timeout=1000')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.set_authorizer(readonly_authorizer)
        if connection.execute('PRAGMA query_only').fetchone() != (1,):
            raise ValueError('CLAUDE_DIAG_READER_MODE')
        if connection.execute('PRAGMA database_list').fetchall() != [(0,'main',str(path))]:
            raise ValueError('CLAUDE_DIAG_DATABASE_PATH')
        return connection
    except Exception:
        connection.close()
        raise

def collect_metadata(connection, now):
    safe = '(length(value)<=2048 AND json_valid(value))'
    valid = safe+" AND json_type(value,'$.reserved_microusd')='integer' AND json_extract(value,'$.reserved_microusd') BETWEEN 1 AND 1000000000000 AND json_type(value,'$.at')='text'"
    row = connection.execute('SELECT COUNT(*),SUM(CASE WHEN '+safe+' THEN CASE WHEN '+valid+' THEN 0 ELSE 1 END ELSE 1 END),'
        'SUM(CASE WHEN '+safe+' THEN CASE WHEN '+valid+" THEN json_extract(value,'$.reserved_microusd') ELSE 0 END ELSE 0 END),"
        'MIN(CASE WHEN '+safe+" THEN json_extract(value,'$.at') END),MAX(CASE WHEN "+safe+" THEN json_extract(value,'$.at') END) "
        "FROM naver_auto_meta WHERE key>='learning-call:' AND key<'learning-call;' ").fetchone()
    count, invalid, amount, first, last = row
    if invalid:
        raise ValueError('CLAUDE_DIAG_RESERVATION_METADATA')
    reservations = dict(count=number(count),total_reserved_microusd=number(amount or 0),
        first_at=stamp(first),last_at=stamp(last),scope='instance_total_not_account_attributed',actual_billed_amount=False)
    row=connection.execute('SELECT COUNT(*),COALESCE(SUM(amount),0),MIN(at),MAX(at) FROM ('
        'SELECT CASE WHEN '+safe+' THEN CASE WHEN '+valid+" THEN json_extract(value,'$.reserved_microusd') END END amount,"
        'CASE WHEN '+safe+" THEN json_extract(value,'$.at') END at FROM naver_auto_meta "
        "WHERE key>='learning-call:' AND key<'learning-call;') WHERE at>=? AND at<?",
        (WINDOW_SQL_START,WINDOW_SQL_END)).fetchone()
    window_reservations=dict(count=number(row[0]),total_reserved_microusd=number(row[1]),
        first_at=window_stamp(row[2]) if row[2] is not None else None,
        last_at=window_stamp(row[3]) if row[3] is not None else None,
        scope='instance_window_not_account_attributed',actual_billed_amount=False)
    audit_window=generation_audit(connection)
    month = now.astimezone(KST).strftime('%Y-%m')
    row = connection.execute("SELECT length(value),substr(value,1,14) FROM naver_auto_meta WHERE key=?",('learning-budget:'+month,)).fetchone()
    if row is not None and (row[0]>13 or type(row[1]) is not str or not re.fullmatch('0|[1-9][0-9]{0,12}',row[1])):
        raise ValueError('CLAUDE_DIAG_BUDGET_METADATA')
    budget = dict(month=month,reserved_microusd=number(int(row[1]) if row else 0),actual_billed_amount=False)
    actions = ('learning-ai-reserve','learning-ai-draft')
    audit = {action:{'ok':0,'denied':0,'other':0} for action in actions}
    for action,result,count in connection.execute('SELECT action,result,COUNT(*) FROM naver_auto_access_log WHERE action IN (?,?) GROUP BY action,result',actions):
        audit[action][result if result in ('ok','denied') else 'other'] += number(count)
    # Only scalar account/report metadata is selected here; names and report JSON are excluded.
    accounts = connection.execute('SELECT customer_id FROM naver_auto_account WHERE ad_account_no=? AND present=1',(TARGET_ACCOUNT,)).fetchmany(2)
    if len(accounts)!=1 or type(accounts[0][0]) is not int or accounts[0][0]<=0:
        raise ValueError('CLAUDE_DIAG_TARGET_ACCOUNT')
    account_key = hashlib.sha256(str(accounts[0][0]).encode('ascii')).hexdigest()
    report = connection.execute('SELECT report_id,revision_fingerprint,generated_at,status,review_status FROM naver_auto_report_snapshot '
        'WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1',(TARGET_PID,PERIOD)).fetchone()
    if report is None:
        raise ValueError('CLAUDE_DIAG_TARGET_REPORT')
    report_id,fingerprint,generated,status,review = report
    if type(report_id) is not int or report_id<=0 or type(fingerprint) is not str or not re.fullmatch('[0-9a-f]{64}',fingerprint):
        raise ValueError('CLAUDE_DIAG_TARGET_REPORT')
    key='report-strategy-head:'+str(report_id)+':'+account_key
    safe = '(length(value)<=24000 AND json_valid(value))'
    row=connection.execute('SELECT '+safe+',CASE WHEN '+safe+" THEN json_extract(value,'$.version') END,CASE WHEN "+safe+
        " THEN json_extract(value,'$.state') END,CASE WHEN "+safe+" THEN json_extract(value,'$.source') END,CASE WHEN "+safe+
        " THEN json_extract(value,'$.author.at') END FROM naver_auto_meta WHERE key=?",(key,)).fetchone()
    target=dict(report_exists=True,period=PERIOD,report_generated_at=stamp(generated),strategy_exists=row is not None,
        version=0,state='empty',source=None,updated_at=None,claude_draft_versions=0)
    if row is not None:
        valid,version,state,source,at=row
        if valid!=1 or number(version)<1 or state not in STATES or source not in SOURCES:
            raise ValueError('CLAUDE_DIAG_STRATEGY_METADATA')
        target.update(version=version,state=state,source=source,updated_at=stamp(at))
    prefix='report-strategy-version:'+str(report_id)+':'+account_key+':'
    versions=connection.execute('SELECT '+safe+',CASE WHEN '+safe+" THEN json_extract(value,'$.version') END,CASE WHEN "+safe+
        " THEN json_extract(value,'$.state') END,CASE WHEN "+safe+" THEN json_extract(value,'$.source') END "
        'FROM naver_auto_meta WHERE key>=? AND key<? LIMIT 1001',(prefix,prefix+';')).fetchall()
    if len(versions)>1000:
        raise ValueError('CLAUDE_DIAG_STRATEGY_LIMIT')
    for valid,version,state,source in versions:
        if valid!=1 or number(version)<1 or state not in STATES or source not in SOURCES:
            raise ValueError('CLAUDE_DIAG_STRATEGY_METADATA')
        if state=='draft' and source=='claude':target['claude_draft_versions']+=1
    # Reuse only the most recent successful reserve actor internally. Never
    # invent owner 0, emit the actor, or interpret a new scope refusal as the
    # original paid-call failure. Scope is rechecked by prepare below.
    actor_row=connection.execute("SELECT emp_idx FROM naver_auto_access_log WHERE action='learning-ai-reserve' AND result='ok' ORDER BY log_id DESC LIMIT 1").fetchone()
    actor=actor_row[0] if actor_row and type(actor_row[0]) is int and 0<=actor_row[0]<=2**53-1 else None
    return dict(reservations=reservations,window_reservations=window_reservations,monthly_reservation=budget,
        audit=audit,audit_window=audit_window,target_strategy=target), (report_id,account_key,fingerprint,target['version'],actor)

def synthetic_preflight(reader, identity, now, model):
    # The real provider factory is never called. A fixed fake key and forced stub
    # exercise current context + request serialization + structural validation only.
    result=dict(status='refused',code='SYNTHETIC_CONTEXT_REFUSED',request_serialized=False,request_bytes=0,
        synthetic_transport_calls=0,learning_cases=0,conversion_complete=None,external_calls=0,draft_mutations=0)
    try:
        from naver_engine import marketing_strategy as STR, store as S
        from naver_runtime.claude_provider import AnthropicProvider
        report_id,key,fingerprint,version,actor=identity
        if actor is None:
            result.update(status='not_performed',code='ACTOR_UNAVAILABLE')
            return result
        try:
            prepared=reader.prepare_learning_strategy(report_id,key,fingerprint,actor,now,version)
        except Exception:
            result['code']='SYNTHETIC_SCOPE_OR_REVISION_REFUSED'
            return result
        context=STR.build_context(prepared['payload'],learning_context=prepared['learning_context'],plan_context=prepared['plan_context'])
        result['learning_cases']=len(context.get('learning',{}).get('cases',[]))
        result['conversion_complete']=context['quality']['conversion']['complete']
        if type(model) is not str or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',model):
            result['code']='PROVIDER_MODEL_UNAVAILABLE'
            return result
        class Response:
            status=200
            def read(self, maximum):
                return json.dumps({'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(STR.document_template(),ensure_ascii=False)}]},ensure_ascii=False).encode()
            def close(self):
                pass
        def stub(request, *, timeout):
            result['synthetic_transport_calls']+=1
            if (request.full_url!='https://api.anthropic.com/v1/messages' or request.get_method()!='POST' or
                    request.allow_redirects is not False or request.headers.get('x-api-key')!='synthetic-key-never-used' or
                    type(request.data) is not bytes or not 0<len(request.data)<=32768):
                raise STR.StrategyRefused('SYNTHETIC_INVALID')
            body=json.loads(request.data)
            if (set(body)!= {'model','max_tokens','system','messages'} or body['model']!=model or body['max_tokens']!=2500 or
                    len(body['messages'])!=1 or json.loads(body['messages'][0]['content'])!=context):
                raise STR.StrategyRefused('SYNTHETIC_INVALID')
            result.update(request_serialized=True,request_bytes=len(request.data))
            return Response()
        provider=AnthropicProvider('synthetic-key-never-used',model,timeout=20,transport=stub)
        generated=STR.generate(prepared['payload'],provider=provider,learning_context=prepared['learning_context'],plan_context=prepared['plan_context'])
        if generated.get('source')!='claude' or result['synthetic_transport_calls']!=1:
            raise STR.StrategyRefused('SYNTHETIC_INVALID')
        result.update(status='passed',code=None)
    except STR.StrategyRefused as error:
        result['code']=error.code if error.code in SAFE_CODES else 'SYNTHETIC_REFUSED'
    except Exception:
        result['code']='SYNTHETIC_CONTEXT_REFUSED'
    return result
'''

exec(compile('import hashlib,json,re,sqlite3\nfrom datetime import datetime,timedelta,timezone\n'+PROJECTION_SOURCE,
             '<claude-diagnostics-projection>', 'exec'))


def validate_package(package):
    expected=dict(baseline=BASELINE,source_commit=SOURCE,source_tar_gz_sha256=ARCHIVE,
                  target='foodin-weekly-20260928',mode='metadata-and-synthetic-only')
    if type(package) is not dict or set(package)!=set(expected) or package!=expected:
        raise ValueError('CLAUDE_DIAG_PACKAGE_PIN')


def script():
    prefix='import hashlib,json,os,re,sqlite3,sys,time,socket,http.client\nfrom pathlib import Path\nfrom datetime import datetime,timedelta,timezone\n'
    suffix=r'''
try:
    if os.geteuid()!=10001:
        raise ValueError('CLAUDE_DIAG_IDENTITY')
    model=os.environ.get('CLAUDE_MODEL') or os.environ.get('ANTHROPIC_MODEL')
    os.environ.clear()
    source=Path('/opt/naver-engine/naver_engine/store.py')
    if source.is_symlink() or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=__STORE_SHA__:
        raise ValueError('CLAUDE_DIAG_STORE_PIN')
    sys.path[:0]=['/opt/naver-engine','/opt/naver-engine/backend']
    from naver_engine import store as S
    def no_network(*args,**kwargs):
        raise RuntimeError('NETWORK_DISABLED')
    socket.create_connection=no_network
    socket.socket.connect=no_network
    socket.socket.connect_ex=no_network
    http.client.HTTPConnection.request=no_network
    http.client.HTTPSConnection.request=no_network
    deadline=time.monotonic()+20
    connection=connect_reader(Path('/var/lib/naver-engine/engine.db'))
    reader=S.Store(connection,'/var/lib/naver-engine/engine.db',None,writer=False)
    try:
        connection.set_progress_handler(lambda:time.monotonic()>=deadline,1000)
        connection.execute('BEGIN')
        if connection.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=('11',):
            raise ValueError('CLAUDE_DIAG_SCHEMA')
        now=datetime.now(timezone.utc)
        result,identity=collect_metadata(connection,now)
        result['synthetic_preflight']=synthetic_preflight(reader,identity,now,model)
        if connection.total_changes!=0:
            raise ValueError('CLAUDE_DIAG_MUTATION')
    finally:
        if connection.in_transaction:
            connection.execute('ROLLBACK')
        reader.close()
    if time.monotonic()>=deadline:
        raise ValueError('CLAUDE_DIAG_DEADLINE')
    encoded=json.dumps(result,sort_keys=True)
    if len(encoded.encode())>8192:
        raise ValueError('CLAUDE_DIAG_OUTPUT_LIMIT')
    print(encoded)
except Exception as error:
    code=str(error)
    print(json.dumps({'failure':code if code in ERROR_CODES else 'CLAUDE_DIAG_READ_FAILED'}))
'''
    return (prefix+PROJECTION_SOURCE+suffix.replace('__STORE_SHA__',repr(STORE))).encode()


def validate_result(value):
    fields(value,'reservations window_reservations monthly_reservation audit audit_window target_strategy synthetic_preflight')
    row=value['reservations'];fields(row,'count total_reserved_microusd first_at last_at scope actual_billed_amount')
    for key in ('count','total_reserved_microusd'):number(row[key])
    for key in ('first_at','last_at'):stamp(row[key])
    if row['scope']!='instance_total_not_account_attributed' or row['actual_billed_amount'] is not False:
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    row=value['window_reservations'];fields(row,'count total_reserved_microusd first_at last_at scope actual_billed_amount')
    for key in ('count','total_reserved_microusd'):number(row[key])
    if row['scope']!='instance_window_not_account_attributed' or row['actual_billed_amount'] is not False:
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    for key in ('first_at','last_at'):
        if row[key] is not None:window_stamp(row[key])
    if (row['count']==0)!=(row['first_at'] is None and row['last_at'] is None):
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    row=value['monthly_reservation'];fields(row,'month reserved_microusd actual_billed_amount')
    if type(row['month']) is not str or not re.fullmatch('[0-9]{4}-(0[1-9]|1[0-2])',row['month']) or row['actual_billed_amount'] is not False:
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    number(row['reserved_microusd'])
    fields(value['audit'],'learning-ai-reserve learning-ai-draft')
    for row in value['audit'].values():
        fields(row,'ok denied other')
        for count in row.values():number(count)
    row=value['audit_window'];fields(row,'start_at end_at scope matched_count unrecognized_count events')
    if (row['start_at']!=WINDOW_START or row['end_at']!=WINDOW_END or
            row['scope']!='instance_window_not_account_attributed' or type(row['events']) is not list or
            number(row['matched_count'])!=len(row['events']) or
            number(row['matched_count'])+number(row['unrecognized_count'])>32):
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    for event in row['events']:
        fields(event,'at code http_status');window_stamp(event['at'])
        if event['code']=='http':
            if type(event['http_status']) is not int or not 100<=event['http_status']<=599:
                raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
        elif event['code'] not in GENERATION_CODES or event['http_status'] is not None:
            raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    row=value['target_strategy'];fields(row,'report_exists period report_generated_at strategy_exists version state source updated_at claude_draft_versions')
    if (row['report_exists'] is not True or row['period']!=PERIOD or type(row['strategy_exists']) is not bool or
            row['state'] not in STATES or row['source'] not in SOURCES|{None}):
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    number(row['version']);stamp(row['report_generated_at']);stamp(row['updated_at']);number(row['claude_draft_versions'])
    if row['claude_draft_versions']>1000:raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    if (row['strategy_exists']!=(row['version']>0) or (not row['strategy_exists'] and (row['state']!='empty' or row['source'] is not None or row['updated_at'] is not None))):
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    row=value['synthetic_preflight'];fields(row,'status code request_serialized request_bytes synthetic_transport_calls learning_cases conversion_complete external_calls draft_mutations')
    if (row['status'] not in ('passed','refused','not_performed') or row['code'] not in SAFE_CODES|{None} or
            type(row['request_serialized']) is not bool or (row['conversion_complete'] is not None and type(row['conversion_complete']) is not bool) or
            type(row['external_calls']) is not int or row['external_calls']!=0 or type(row['draft_mutations']) is not int or row['draft_mutations']!=0):
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    for key in ('request_bytes','synthetic_transport_calls','learning_cases'):number(row[key])
    if row['request_bytes']>32768 or row['synthetic_transport_calls']>1 or row['learning_cases']>5:
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    if row['status']=='passed' and (row['code'] is not None or row['request_serialized'] is not True or row['synthetic_transport_calls']!=1 or row['request_bytes']<1):
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')
    if row['status']!='passed' and row['code'] is None:
        raise ValueError('CLAUDE_DIAG_OUTPUT_SCOPE')


LOG_PATTERNS = {
    'engine': (
        ('store_busy', r'WARNING naver_engine\.web 화면 API 저장소 바쁨: \S{1,64}'),
        ('store_refused', r'WARNING naver_engine\.web 화면 API 저장소 거절: \S{1,64}'),
        ('store_error', r'WARNING naver_engine\.web 화면 API 저장소 오류: \S{1,64}'),
        ('unexpected_error', r'ERROR naver_engine\.web 화면 API 뜻밖의 오류: \S{1,64}')),
    'relay': tuple((label,r'(?:WARNING:?[ ]+(?:(?:app\.)?naver_relay )?)?관제 엔진 중계 실패: '+kind)
        for label,kind in (('engine_timeout','engine-timeout'),('engine_cut','engine-cut')))}


def capture_docker_logs(identity):
    # Fixed command, bounded memory/time. Raw stdout/stderr never leave this process.
    if type(identity) is not str or not re.fullmatch('[0-9a-f]{64}',identity):
        raise ValueError('CLAUDE_DIAG_CONTAINER_ID')
    process=None
    try:
        process=subprocess.Popen(['docker','logs','--since',WINDOW_START,'--until',WINDOW_END,'--tail','300','--timestamps',identity],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,stdin=subprocess.DEVNULL,
            env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LANG':'C'})
        streams={process.stdout:bytearray(),process.stderr:bytearray()};total=0
        deadline=time.monotonic()+5
        with selectors.DefaultSelector() as ready:
            for stream in streams:ready.register(stream,selectors.EVENT_READ)
            while ready.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:return None
                for key,_ in ready.select(remaining):
                    chunk=os.read(key.fileobj.fileno(),min(65536,1048577-total))
                    if not chunk:ready.unregister(key.fileobj);continue
                    total+=len(chunk)
                    if total>1048576:return None
                    streams[key.fileobj].extend(chunk)
        if process.wait(timeout=max(0.001,deadline-time.monotonic()))!=0:return None
        return b'\n'.join(bytes(value).rstrip(b'\r\n') for value in streams.values() if value)
    except (OSError,subprocess.SubprocessError):
        return None
    finally:
        if process is not None:
            if process.poll() is None:
                try:process.kill()
                except ProcessLookupError:pass
            process.wait()
            for stream in (process.stdout,process.stderr):
                if stream is not None:stream.close()


def log_summary(engine, relay):
    result={name:dict(available=False,entries_inspected=0,unmatched_entries=0,
        engine_timeout=0,engine_cut=0,store_busy=0,store_refused=0,store_error=0,unexpected_error=0,events=[]) for name in ('engine','relay')}
    for unit,identity in (('engine',engine),('relay',relay)):
        raw=capture_docker_logs(identity)
        if raw is None:continue
        rows=raw.splitlines()
        if len(rows)>300:continue
        out=result[unit];out.update(available=True,entries_inspected=len(rows))
        for row in rows:
            try:
                text=row.decode('utf-8');tick,separator,message=text.partition(' ')
                if (not separator or len(message)>4096 or not re.fullmatch(
                    r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})',tick)):
                    raise ValueError('LOG_SHAPE')
                tick=window_stamp(tick.replace('Z','+00:00'))
                message=re.sub(r'^naver-'+unit+r'(?:-1)?\s+\|\s*','',message)
            except (ValueError,UnicodeError):
                out['unmatched_entries']+=1;continue
            for label,pattern in LOG_PATTERNS[unit]:
                if re.fullmatch(pattern,message):
                    out[label]+=1;out['events'].append(dict(at=tick,code=label));break
            else:out['unmatched_entries']+=1
        if len(out['events'])>32:
            result[unit]=dict(available=False,entries_inspected=0,unmatched_entries=0,
                engine_timeout=0,engine_cut=0,store_busy=0,store_refused=0,store_error=0,unexpected_error=0,events=[])
    return result


def runtime_fingerprint(release, prepared):
    # Whole-file preservation check only. The value and fingerprint never leave the host.
    path=release.SECRET_ROOT/'runtime.env'
    release.trusted_private_file(path)
    if path.stat().st_size>65536:
        raise ValueError('CLAUDE_DIAG_RUNTIME_SIZE')
    fingerprint=release.sha(path.read_bytes())
    if fingerprint!=prepared.get('files',{}).get(str(path)):
        raise ValueError('CLAUDE_DIAG_RUNTIME_CHANGED')
    return fingerprint


def fixed_error(error):
    code=str(error)
    return code if code in ERROR_CODES else 'CLAUDE_DIAG_READ_FAILED'


def postflight(host,release,identities,before,receipt,receipt_fingerprint,prepared,runtime_before):
    failure=None
    for name in before:
        try:
            if container(release,identities[name])!=before[name]:raise ValueError()
        except Exception:
            if failure is None:failure='CLAUDE_DIAG_POST_'+name.upper()
    try:
        legacy_unchanged=host.baseline()==BASELINE
    except Exception:
        legacy_unchanged=False
    if not legacy_unchanged and failure is None:failure='CLAUDE_DIAG_POST_LEGACY_BASELINE'
    try:
        runtime_unchanged=(receipt_fingerprint==release.sha(receipt.read_bytes()) and
            runtime_before==runtime_fingerprint(release,prepared))
    except Exception:
        runtime_unchanged=False
    if not runtime_unchanged and failure is None:failure='CLAUDE_DIAG_POST_RUNTIME'
    return failure,legacy_unchanged,runtime_unchanged


def run(package, host, release):
    global STAGE
    STAGE='preflight';validate_package(package)
    if os.geteuid()!=0 or host.baseline()!=BASELINE:
        raise ValueError('CLAUDE_DIAG_HOST_BASELINE')
    path,receipt=release.prepared_paths(SOURCE)
    release.trusted_private_file(receipt)
    if receipt.stat().st_size>32768:
        raise ValueError('CLAUDE_DIAG_RECEIPT_SIZE')
    prepared=json.loads(receipt.read_bytes(),object_pairs_hook=release.unique)
    if (prepared.get('ok') is not True or prepared.get('source_commit')!=SOURCE or prepared.get('stage')!='prepared' or
            prepared.get('package',{}).get('source_tar_gz_sha256')!=ARCHIVE or prepared.get('package',{}).get('baseline')!=BASELINE):
        raise ValueError('CLAUDE_DIAG_SOURCE_NOT_READY')
    receipt_fingerprint=release.sha(receipt.read_bytes())
    runtime_before=runtime_fingerprint(release,prepared)
    identities={}
    before={}
    for name in ('engine','relay'):
        for file in (path/('compose.naver-'+name+'.yml'),path/('preview-'+name+'.override.yml')):
            if file.resolve()!=file or release.sha(file.read_bytes())!=prepared.get('files',{}).get(str(file)):
                raise ValueError('CLAUDE_DIAG_COMPOSE_CHANGED')
        image=prepared.get('images',{}).get(name)
        if type(image) is not str or not re.fullmatch('sha256:[0-9a-f]{64}',image):
            raise ValueError('CLAUDE_DIAG_IMAGE')
        identity=release.command(release.compose(path,name)+['ps','--all','--quiet']).decode().strip()
        if not re.fullmatch('[0-9a-f]{64}',identity):
            raise ValueError('CLAUDE_DIAG_CONTAINER_ID')
        identities[name]=identity
        before[name]=container(release,identity)
        row=before[name]
        if (any(row.get(key)!=value for key,value in dict(id=identity,image=image,running=True,restarting=False,
                user='10001:10001',project='naver-'+name,service='naver-'+name,source=SOURCE,readonly=True).items()) or
                type(row.get('pid')) is not int or row['pid']<=0):
            raise ValueError('CLAUDE_DIAG_CONTAINER_CHANGED')
        mounts=row.get('mounts')
        if type(mounts) is not list or any(type(m) is not dict or str(m.get('Destination','')).startswith('/opt/naver-engine') for m in mounts):
            raise ValueError('CLAUDE_DIAG_SOURCE_MOUNT')
        if name=='engine' and len([m for m in mounts if m.get('Type')=='bind' and m.get('Source')=='/var/lib/metainc/naver-engine' and m.get('Destination')=='/var/lib/naver-engine'])!=1:
            raise ValueError('CLAUDE_DIAG_DATA_MOUNT')
    STAGE='read_only_metadata_and_synthetic'
    value=None;summary=None;primary_error=None
    try:
        raw=release.command(['docker','exec','-i','--user','10001:10001',identities['engine'],'python','-I','-B','-'],data=script(),timeout=30)
        if len(raw)>MAX_OUTPUT:
            raise ValueError('CLAUDE_DIAG_OUTPUT_LIMIT')
        candidate=json.loads(raw,object_pairs_hook=release.unique)
        if type(candidate) is dict and set(candidate)=={'failure'}:
            raise ValueError(candidate['failure'] if type(candidate['failure']) is str and candidate['failure'] in ERROR_CODES else 'CLAUDE_DIAG_READ_FAILED')
        validate_result(candidate)
        value=candidate
        summary=log_summary(identities['engine'],identities['relay'])
    except Exception as error:
        primary_error=fixed_error(error)
    finally:
        STAGE='postflight'
        post_error,legacy_unchanged,runtime_unchanged=postflight(host,release,identities,before,receipt,
            receipt_fingerprint,prepared,runtime_before)
    return dict(ok=primary_error is None and post_error is None,mode='claude-diagnostics-v24-readonly',
        source_commit=SOURCE,diagnostics=value,logs=summary,primary_error=primary_error,postflight_error=post_error,
        postflight_verified=post_error is None,
        logs_scope='fixed_0750_0755_utc_tail_300_patterns_not_account_attributed',paid_provider_calls=None,
        provider_outcome='closed_audit_codes_only_no_paid_call_receipt',database_mutations=0,external_calls=0,services_restarted=0,
        existing_app_baseline_unchanged=legacy_unchanged,runtime_config_unchanged=runtime_unchanged)


def container(release,identity):
    fmt='{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"restarting":{{json .State.Restarting}},"pid":{{json .State.Pid}},"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}},"user":{{json .Config.User}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}},"readonly":{{json .HostConfig.ReadonlyRootfs}},"mounts":{{json .Mounts}}}'
    return json.loads(release.command(['docker','inspect','--format',fmt,identity]),object_pairs_hook=release.unique)
