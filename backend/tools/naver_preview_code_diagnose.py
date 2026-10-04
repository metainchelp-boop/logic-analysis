"""Pinned failed-rollout aggregate reader; no keys, external calls or DB writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import uuid

OPERATION_ID = 'a49a7ccfe32840298914f121883caee5'
TARGET_COMMIT = 'e1c4b3526db55d78175a1d6598f3403fdb9398f7'
REPORT_OPERATION = 'c33d41529d064cf68226e114707a3f8a'
REPORT_TARGET = 'a38c53775c112cdf5db420f979093d6bee9e5376'
REPORT_SOURCE_SHA256 = 'dc442fa19e4809b290124e8a72fa3243d911957176ba6988269ec27ef736302a'
REPORT_OLD = '0a302856c6177c4f53145abaf9ed31b6a39654f3'
STAGE = 'input'
STAGES = frozenset(('input','diagnose_preflight','diagnose_readonly','diagnose_journal','diagnose_postflight'))
FAILURES = frozenset(('DIAG_OPERATION','DIAG_PATH','DIAG_IMAGE','DIAG_IMAGE_CHANGED','DIAG_CONTAINER_CHANGED',
    'DIAG_CONTAINER_ID','DIAG_RESULT_SIZE','DIAG_FIELDS','DIAG_CODES','DIAG_COUNT','DIAG_SCHEMA','DIAG_TIME',
    'DIAG_BOOL','DIAG_CATALOG','DIAG_READ_FAILED','DIAG_CREATE_UNCONFIRMED','DIAG_CONTAINER_REMAINS',
    'DIAG_CLEANUP_FAILED','DIAG_POST_BASELINE','DIAG_SOURCE','DIAG_JOURNAL_PRESENT','DIAG_JOURNAL_SIZE',
    'DIAG_JOURNAL_LIMIT','DIAG_JOURNAL_FIELDS','HOST_BASELINE','OLD_BASELINE','OLD_SOURCE_CHANGED',
    'OLD_UNIT_CHANGED','DEPENDENCY_NOT_ACTIVE','OLD_UNIT_NOT_ENABLED','FILE_POLICY','FILE_PATH',
    'DIRECTORY_POLICY','COMMAND_FAILED','PREPARED_PACKAGE','PREPARED_SOURCE','IMAGE_CHANGED'))


def failure_report(error):
    kind=type(error).__name__
    reason=str(error)
    return {'ok':False,'stage':STAGE if STAGE in STAGES else 'UNRECOGNIZED',
            'error_kind':kind if kind in ('ValueError','RuntimeError','TimeoutExpired','JSONDecodeError',
                'PermissionError','FileNotFoundError','OSError') else 'UNRECOGNIZED',
            'error_code':reason if reason in FAILURES else 'UNRECOGNIZED'}
PROJECTION_SOURCE = r'''
import json,os,sqlite3
from datetime import datetime
OUTCOMES = frozenset(('accepted','refused','braked','failed','missing','UNRECOGNIZED'))
CODES = frozenset(('BRAKE','BRAKE_STAGE','BRAKE_BASELINE','BRAKE_MANAGER','BRAKE_CONFIRMED',
    'IMPLAUSIBLE_FIRST','STORE_REFUSED','ACTIVE_DROP_BASELINE','OWNER_DROP_BASELINE',
    'MANAGER_SPIKE_BASELINE','STORED_UNREADABLE','INCOMPLETE_LIST','RUN_ABORT','HANDLE_INVALID',
    'ACCOUNTS_UNUSABLE','CLOCK_BEHIND','unexpected','network','bad-shape','not-json','too-large'))
INVENTORY_DAY = '2026-10-02'
INVENTORY_STATES = frozenset(('reading','partial','ok','retry','reauth_required','limited','UNRECOGNIZED'))
INVENTORY_CODES = frozenset(('NONE','UNRECOGNIZED','KEY_REJECTED','RATE','SERVER','BAD_REQUEST','NOT_FOUND',
    'NETWORK','BAD_RESPONSE','MISMATCH','OTHER','CHECKPOINT_PENDING','STATS_INCOMPLETE','CAMPAIGNS_CHANGED',
    'STATS_SHAPE','CHECKPOINT_INVALID','REQUEST_BUDGET','UNEXPECTED','RETRY_EXHAUSTED'))

def number(value):
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError('DIAG_COUNT')
    return value

def timestamp(value):
    if value is None:
        return None
    if not isinstance(value,str) or len(value)>40:
        raise ValueError('DIAG_TIME')
    parsed=datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('DIAG_TIME')
    return parsed.isoformat()

def projection(conn):
    def meta(key,limit=4096):
        row=conn.execute('SELECT value FROM naver_auto_meta WHERE key=? AND length(value)<=?',(key,limit)).fetchone()
        return None if row is None else row[0]
    def latest(kind):
        row=conn.execute('SELECT outcome,codes,row_count FROM naver_auto_sync_log WHERE kind=? ORDER BY sync_id DESC LIMIT 1',(kind,)).fetchone()
        if row is None:
            return {'outcome':'missing','codes':[],'unrecognized_code_count':0,'rows':None}
        codes=json.loads(row[1])
        if not isinstance(codes,list) or len(codes)>20 or any(not isinstance(c,str) for c in codes):
            raise ValueError('DIAG_CODES')
        return {'outcome':row[0] if row[0] in OUTCOMES else 'UNRECOGNIZED',
                'codes':sorted(set(c for c in codes if c in CODES)),
                'unrecognized_code_count':sum(c not in CODES for c in codes),
                'rows':None if row[2] is None else number(row[2])}
    schema=meta('schema_version')
    if schema not in ('7','8','9'):
        raise ValueError('DIAG_SCHEMA')
    inventory={'available':schema in ('8','9'),'day':INVENTORY_DAY,'rows':0,'groups':[]}
    if schema in ('8','9'):
        states=sorted(INVENTORY_STATES-{'UNRECOGNIZED'})
        codes=sorted(INVENTORY_CODES-{'NONE','UNRECOGNIZED'})
        query=("SELECT CASE WHEN status IN ("+','.join('?' for _ in states)+") THEN status ELSE 'UNRECOGNIZED' END, "
            "CASE WHEN error_code IS NULL THEN 'NONE' WHEN error_code IN ("+','.join('?' for _ in codes)+") "
            "THEN error_code ELSE 'UNRECOGNIZED' END, COUNT(*) FROM naver_auto_inventory_check "
            "WHERE day=? GROUP BY 1,2 ORDER BY 1,2")
        inventory['groups']=[{'status':s,'error_code':c,'count':number(n)}
            for s,c,n in conn.execute(query,(*states,*codes,INVENTORY_DAY))]
        inventory['rows']=number(sum(row['count'] for row in inventory['groups']))
    org=conn.execute("SELECT body,generated_at,accepted_at FROM naver_auto_org WHERE slot='current' AND length(body)<=8388608").fetchone()
    employees=[]
    if org is not None:
        body=json.loads(org[0])
        if not isinstance(body,dict) or not isinstance(body.get('employees'),list) or len(body['employees'])>100000:
            raise ValueError('DIAG_ORG')
        employees=body['employees']
        if any(not isinstance(e,dict) for e in employees):
            raise ValueError('DIAG_ORG')
    catalog_status=meta('account_catalog_status')
    catalog_status={} if catalog_status is None else json.loads(catalog_status)
    if not isinstance(catalog_status,dict):
        raise ValueError('DIAG_CATALOG')
    state=catalog_status.get('state','missing')
    if state not in ('accepted','failed','missing'):
        state='UNRECOGNIZED'
    catalog=conn.execute("SELECT CASE WHEN json_valid(value) THEN json_extract(value,'$.total') END, CASE WHEN json_valid(value) THEN json_extract(value,'$.generated_at') END FROM naver_auto_meta WHERE key='account_catalog'").fetchone()
    return {'schema_version':int(schema),'inventory_check':inventory,
            'org':{'latest':latest('org'),'snapshot_available':org is not None,
                   'employee_count':len(employees),'management_count':sum(e.get('is_management') is True for e in employees),
                   'management_marker_missing_count':sum('is_management' not in e for e in employees),
                   'management_marker_invalid_count':sum('is_management' in e and type(e['is_management']) is not bool for e in employees),
                   'generated_at':None if org is None else timestamp(org[1]),
                   'accepted_at':None if org is None else timestamp(org[2])},
            'accounts':{'latest':latest('accounts'),'present_count':number(conn.execute('SELECT COUNT(*) FROM naver_auto_account WHERE present=1').fetchone()[0]),
                        'read_at':timestamp(meta('accounts_read_at'))},
            'catalog':{'state':state,'total':None if catalog is None or catalog[0] is None else number(catalog[0]),
                       'generated_at':None if catalog is None else timestamp(catalog[1])}}

def read_projection(path):
    if os.path.lexists(path+'-journal'):
        raise ValueError('DIAG_JOURNAL_PRESENT')
    # Only the frozen DB-only snapshot may bypass WAL initialization.
    option='' if any(os.path.lexists(path+s) for s in ('-wal','-shm')) else '&immutable=1'
    conn=sqlite3.connect('file:'+path+'?mode=ro'+option,uri=True,timeout=5)
    try:
        conn.execute('PRAGMA query_only=ON')
        allowed={sqlite3.SQLITE_SELECT,sqlite3.SQLITE_READ,sqlite3.SQLITE_FUNCTION,sqlite3.SQLITE_TRANSACTION}
        conn.set_authorizer(lambda action,*unused: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)
        conn.execute('BEGIN')
        return projection(conn)
    finally:
        conn.close()
'''
exec(compile(PROJECTION_SOURCE, '<failed-code-projection>', 'exec'))


def script():
    return (PROJECTION_SOURCE + '''
import os
if os.geteuid()!=10001:
    raise ValueError('DIAG_IDENTITY')
os.environ.clear()
try:
    result=read_projection('/diag/engine.db')
except Exception:
    result={'diagnostic_error':'READ_FAILED'}
print(json.dumps(result,sort_keys=True,separators=(',',':')))
''').encode()


def validate_result(value):
    if value=={'diagnostic_error':'READ_FAILED'}:
        raise ValueError('DIAG_READ_FAILED')
    def exact(item,fields):
        if not isinstance(item,dict) or set(item)!=set(fields):
            raise ValueError('DIAG_FIELDS')
    def nullable_number(item):
        if item is not None:
            number(item)
    def latest(item):
        exact(item,('outcome','codes','unrecognized_code_count','rows'))
        if item['outcome'] not in OUTCOMES or not isinstance(item['codes'],list) or len(item['codes'])>20 or any(c not in CODES for c in item['codes']):
            raise ValueError('DIAG_CODES')
        number(item['unrecognized_code_count'])
        nullable_number(item['rows'])
    exact(value,('schema_version','org','accounts','catalog','inventory_check'))
    if type(value['schema_version']) is not int or value['schema_version'] not in (7,8,9):
        raise ValueError('DIAG_SCHEMA')
    org,accounts,catalog=value['org'],value['accounts'],value['catalog']
    exact(org,('latest','snapshot_available','employee_count','management_count','management_marker_missing_count',
               'management_marker_invalid_count','generated_at','accepted_at'))
    latest(org['latest'])
    if type(org['snapshot_available']) is not bool:
        raise ValueError('DIAG_BOOL')
    for key in ('employee_count','management_count','management_marker_missing_count','management_marker_invalid_count'):
        number(org[key])
    for key in ('generated_at','accepted_at'):
        timestamp(org[key])
    exact(accounts,('latest','present_count','read_at'))
    latest(accounts['latest'])
    number(accounts['present_count'])
    timestamp(accounts['read_at'])
    exact(catalog,('state','total','generated_at'))
    if catalog['state'] not in ('accepted','failed','missing','UNRECOGNIZED'):
        raise ValueError('DIAG_CATALOG')
    nullable_number(catalog['total'])
    timestamp(catalog['generated_at'])
    inventory=value['inventory_check']
    exact(inventory,('available','day','rows','groups'))
    if inventory['available'] is not (value['schema_version'] in (8,9)) or inventory['day']!=INVENTORY_DAY:
        raise ValueError('DIAG_FIELDS')
    groups=inventory['groups']
    if not isinstance(groups,list) or len(groups)>len(INVENTORY_STATES)*len(INVENTORY_CODES):
        raise ValueError('DIAG_FIELDS')
    seen=set()
    for row in groups:
        exact(row,('status','error_code','count'))
        if (not isinstance(row['status'],str) or row['status'] not in INVENTORY_STATES
                or not isinstance(row['error_code'],str) or row['error_code'] not in INVENTORY_CODES):
            raise ValueError('DIAG_CODES')
        key=(row['status'],row['error_code'])
        if not number(row['count']) or key in seen:
            raise ValueError('DIAG_COUNT')
        seen.add(key)
    if number(inventory['rows'])!=sum(row['count'] for row in groups) or not inventory['available'] and groups:
        raise ValueError('DIAG_COUNT')
    return value


def files_snapshot(folder,upgrade):
    if os.path.lexists(folder/'engine.db-journal'):
        raise ValueError('DIAG_JOURNAL_PRESENT')
    result={}
    for suffix in ('','-wal','-shm'):
        path=folder/('engine.db'+suffix)
        if suffix and not os.path.lexists(path):
            continue
        raw=upgrade.read_file(path,uid=10001,gid=10001,mode=0o600,maximum=1024**3,minimum=0 if suffix else 1)
        info=path.lstat()
        result[str(path)]={'sha256':hashlib.sha256(raw).hexdigest(),'size':info.st_size,'device':info.st_dev,
            'inode':info.st_ino,'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns,
            'uid':info.st_uid,'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode),'links':info.st_nlink}
    return result


def report_schema_copy(folder,files,upgrade,code):
    # SQLite may write SHM even with mode=ro. Only disposable copies are opened.
    with tempfile.TemporaryDirectory(prefix='naver-report-diag-',dir='/tmp') as temporary:
        copied=Path(temporary).resolve()
        for filename,info in files.items():
            if Path(filename).name not in ('engine.db','engine.db-wal','engine.db-shm') or Path(filename).parent!=folder:
                raise ValueError('DIAG_PATH')
            raw=upgrade.read_file(Path(filename),uid=10001,gid=10001,mode=0o600,
                maximum=1024**3,minimum=0 if Path(filename).name!='engine.db' else 1)
            if len(raw)!=info['size'] or hashlib.sha256(raw).hexdigest()!=info['sha256']:
                raise ValueError('DIAG_POST_BASELINE')
            fd=os.open(copied/Path(filename).name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as output:
                output.write(raw)
        phase='open'
        connection=None
        try:
            connection=sqlite3.connect((copied/'engine.db').as_uri()+'?mode=ro',uri=True,timeout=5)
            phase='configure'
            connection.execute('PRAGMA query_only=ON')
            connection.execute('PRAGMA trusted_schema=OFF')
            tables={'naver_auto_link_memory','naver_auto_morning_progress','naver_auto_morning_chunk'}
            def authorize(action,arg1,arg2,*unused):
                allowed=(action in (sqlite3.SQLITE_SELECT,sqlite3.SQLITE_TRANSACTION)
                    or action==sqlite3.SQLITE_READ and arg1=='naver_auto_meta'
                    or action==sqlite3.SQLITE_PRAGMA and arg1=='table_info' and arg2 in tables)
                return sqlite3.SQLITE_OK if allowed else sqlite3.SQLITE_DENY
            connection.set_authorizer(authorize)
            deadline=time.monotonic()+5
            connection.set_progress_handler(lambda: int(time.monotonic()>deadline),1000)
            phase='contract'
            connection.execute('BEGIN')
            code.database_contract(connection,code.TARGET_COMMIT)
            return {'schema_contract':'passed','phase':'contract','error_kind':None,
                    'sqlite_errorcode':None,'sqlite_errorname':None}
        except sqlite3.Error as error:
            labels={1:'SQLITE_ERROR',5:'SQLITE_BUSY',6:'SQLITE_LOCKED',8:'SQLITE_READONLY',
                9:'SQLITE_INTERRUPT',10:'SQLITE_IOERR',11:'SQLITE_CORRUPT',14:'SQLITE_CANTOPEN',
                17:'SQLITE_SCHEMA',23:'SQLITE_AUTH',26:'SQLITE_NOTADB'}
            value=getattr(error,'sqlite_errorcode',None)
            primary=value&255 if type(value) is int else None
            primary=primary if primary in labels else None
            return {'schema_contract':'failed','phase':phase,'error_kind':'SQLiteError',
                    'sqlite_errorcode':primary,'sqlite_errorname':labels.get(primary,'UNRECOGNIZED')}
        except ValueError as error:
            if error.args!=('DB_TARGET_SCHEMA',):
                raise
            return {'schema_contract':'failed','phase':phase,'error_kind':'DB_TARGET_SCHEMA',
                    'sqlite_errorcode':None,'sqlite_errorname':None}
        finally:
            if connection is not None:
                connection.close()


def report_run(package,host,release,lifecycle,upgrade,code):
    global STAGE
    STAGE='diagnose_preflight'
    if set(package)!={'release','operation_id'} or package['operation_id']!=REPORT_OPERATION:
        raise ValueError('DIAG_OPERATION')
    if (code.TARGET_COMMIT!=REPORT_TARGET or code.OLD_COMMIT!=REPORT_OLD
            or code.TARGET_SOURCE_SHA256!=REPORT_SOURCE_SHA256):
        raise ValueError('DIAG_SOURCE')
    if not re.fullmatch(r'[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}',sqlite3.sqlite_version):
        raise ValueError('DIAG_SCHEMA')
    prepared=code.validate_package(package['release'],release)
    before=code.current_state(prepared,host,release,lifecycle,upgrade)
    target=upgrade.manifest(release,REPORT_TARGET,prepared)
    release.trusted_dir(code.DATA,uid=10001,gid=10001,mode=0o750)
    folder=code.DATA/('.account-failed-db-'+REPORT_OPERATION)
    if folder.resolve()!=folder or not folder.is_dir():
        raise ValueError('DIAG_PATH')
    release.trusted_dir(folder,mode=0o700)
    files=files_snapshot(folder,upgrade)
    try:
        STAGE='diagnose_readonly'
        result=report_schema_copy(folder,files,upgrade,code)
    finally:
        STAGE='diagnose_postflight'
        after=code.current_state(prepared,host,release,lifecycle,upgrade)
        target_after=upgrade.manifest(release,REPORT_TARGET,prepared)
        if files_snapshot(folder,upgrade)!=files or after!=before or target_after!=target:
            raise ValueError('DIAG_POST_BASELINE')
    return {'ok':True,'mode':'report-failed-schema-copy','source_commit':REPORT_TARGET,
        'operation_id':REPORT_OPERATION,'host_sqlite_version':sqlite3.sqlite_version,
        'host_python_version':'.'.join(str(n) for n in sys.version_info[:3]),
        'diagnosis':result,'database_files_unchanged':True,
        'existing_app_baseline_unchanged':True,'live_database_opened':False,
        'database_mutations':0,'external_calls':0,'services_changed':False}


def runtime_journal(release):
    since,until='2026-10-02 04:25:00 UTC','2026-10-02 04:26:35 UTC'
    kinds=frozenset(('AttributeError','TypeError','ValueError','RuntimeError','KeyError','NameError','IndexError',
        'ImportError','ModuleNotFoundError','PermissionError','FileNotFoundError','OSError','OperationalError',
        'StoreError','StoreRefused','TimeoutError'))
    exits,results,exceptions,sources={},{},{},[]
    total=unrecognized=0
    for name in ('engine','relay'):
        unit='metainc-naver-'+name+'.service'
        for source in ('systemd','app'):
            field='UNIT' if source=='systemd' else '_SYSTEMD_UNIT'
            match=[field+'='+unit]+(['_PID=1'] if source=='systemd' else [])
            raw=release.command(['/usr/bin/journalctl','--no-pager','--output=json',
                '--output-fields=UNIT,_SYSTEMD_UNIT,_PID,MESSAGE','--since',since,'--until',until,'--lines=513',*match],timeout=30)
            if len(raw)>1048576:
                raise ValueError('DIAG_JOURNAL_SIZE')
            rows=raw.splitlines()
            if len(rows)>512:
                raise ValueError('DIAG_JOURNAL_LIMIT')
            total+=len(rows)
            sources.append({'unit':name,'source':source,'count':len(rows)})
            for line in rows:
                row=json.loads(line,object_pairs_hook=release.unique)
                if (not isinstance(row,dict) or row.get(field)!=unit or not isinstance(row.get('_PID'),str)
                        or not re.fullmatch('[1-9][0-9]{0,9}',row['_PID']) or (row['_PID']=='1')!=(source=='systemd')
                        or not isinstance(row.get('MESSAGE'),str) or len(row['MESSAGE'])>4096):
                    raise ValueError('DIAG_JOURNAL_FIELDS')
                message=row['MESSAGE']
                if source=='app':
                    message=re.sub(r'^naver-'+name+r'(?:-1)?\s+\|\s*','',message)
                    tick=re.fullmatch(r'(?:ERROR naver_runtime )?예약 회차 실패: ([A-Za-z][A-Za-z0-9_]*)',message)
                    step=re.fullmatch(r'(?:ERROR naver_runtime.scheduler )?예약 작업 실패: (?:org|stages|accounts|pairing|readiness|morning|alerts|backup|metrics|inventory|inventory_catalog) ([A-Za-z][A-Za-z0-9_]*)',message)
                    event,kind=('scheduler_tick',tick[1]) if tick else ('scheduler_step',step[1]) if step else (None,None)
                    if event is None and message.startswith('{'):
                        try:
                            body=json.loads(message,object_pairs_hook=release.unique)
                        except ValueError:
                            body=None
                        if isinstance(body,dict) and set(body)=={'error','kind'} and body['error']=='startup-refused' and isinstance(body['kind'],str):
                            event,kind='startup_refused',body['kind']
                    if event:
                        key=(name,source,event,kind if kind in kinds else 'UNRECOGNIZED')
                        exceptions[key]=exceptions.get(key,0)+1
                    else:
                        unrecognized+=1
                    continue
                event=re.fullmatch(re.escape(unit)+r': Main process exited, code=([a-z-]+), status=([0-9]{1,3})/([A-Za-z0-9/_-]+)',message)
                failure=re.fullmatch(re.escape(unit)+r": Failed with result '([^']{1,64})'\.",message)
                if event and int(event[2])<=255:
                    kind=event[1] if event[1] in ('exited','killed','dumped') else 'UNRECOGNIZED'
                    label=event[3] if event[3] in ('SUCCESS','FAILURE','n/a','TERM','KILL','INT','ABRT','SEGV','PIPE','HUP','QUIT') else 'UNRECOGNIZED'
                    key=(name,source,kind,int(event[2]),label)
                    exits[key]=exits.get(key,0)+1
                elif failure or message==unit+': Deactivated successfully.':
                    result=failure[1] if failure else 'success'
                    if result not in ('success','exit-code','signal','core-dump','timeout','watchdog','start-limit-hit','resources','protocol','oom-kill'):
                        result='UNRECOGNIZED'
                    key=(name,source,result)
                    results[key]=results.get(key,0)+1
                else:
                    unrecognized+=1
    return {'scope':'journal_only','since_utc':'2026-10-02T04:25:00Z','until_utc':'2026-10-02T04:26:35Z',
        'entries_inspected':total,'sources':sources,'main_process_exit_count':sum(exits.values()),'unrecognized_event_count':unrecognized,
        'exceptions':[{'unit':k[0],'source':k[1],'event':k[2],'kind':k[3],'count':v} for k,v in sorted(exceptions.items())],
        'exits':[{'unit':k[0],'source':k[1],'exit_type':k[2],'exit_status':k[3],'status_label':k[4],'count':v} for k,v in sorted(exits.items())],
        'results':[{'unit':k[0],'source':k[1],'result':k[2],'count':v} for k,v in sorted(results.items())]}


def run(package,host,release,lifecycle,upgrade,code):
    global STAGE
    if isinstance(package,dict) and package.get('operation_id')==REPORT_OPERATION:
        return report_run(package,host,release,lifecycle,upgrade,code)
    STAGE='diagnose_preflight'
    if not isinstance(package,dict) or set(package)!={'release','operation_id'} or package['operation_id']!=OPERATION_ID:
        raise ValueError('DIAG_OPERATION')
    if code.TARGET_COMMIT!=TARGET_COMMIT:
        raise ValueError('DIAG_SOURCE')
    prepared=code.validate_package(package['release'],release)
    before=code.current_state(prepared,host,release,lifecycle,upgrade)
    path,receipt=upgrade.manifest(release,code.TARGET_COMMIT,prepared)
    release.trusted_dir(code.DATA,uid=10001,gid=10001,mode=0o750)
    folder=code.DATA/('.account-failed-db-'+OPERATION_ID)
    if folder.resolve()!=folder:
        raise ValueError('DIAG_PATH')
    STAGE='diagnose_journal'
    journal=runtime_journal(release)
    if not os.path.lexists(folder):
        STAGE='diagnose_postflight'
        if (os.path.lexists(folder) or upgrade.manifest(release,code.TARGET_COMMIT,prepared)!=(path,receipt)
                or code.current_state(prepared,host,release,lifecycle,upgrade)!=before):
            raise ValueError('DIAG_POST_BASELINE')
        return {'ok':True,'mode':'failed-code-runtime-journal','source_commit':code.TARGET_COMMIT,'operation_id':OPERATION_ID,
            'quarantine_present':False,'runtime_journal':journal,'existing_app_baseline_unchanged':True,
            'database_read':False,'database_mutations':0,'external_calls':0,'services_changed':False}
    release.trusted_dir(folder,mode=0o700)
    files=files_snapshot(folder,upgrade)
    image=receipt['images']['engine']
    if not isinstance(image,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',image):
        raise ValueError('DIAG_IMAGE')
    fmt='{"id":{{json .Id}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.preview.source")}}}'
    if json.loads(release.command(['docker','image','inspect','--format',fmt,image]))!={'id':image,'user':'10001:10001','source':code.TARGET_COMMIT}:
        raise ValueError('DIAG_IMAGE_CHANGED')
    name='naver-code-diag-'+OPERATION_ID+'-'+uuid.uuid4().hex
    container=None
    result=None
    def metadata(identity):
        fmt='{"id":{{json .Id}},"image":{{json .Image}},"user":{{json .Config.User}},"source":{{json (index .Config.Labels "metainc.naver.diagnose.source")}},"operation":{{json (index .Config.Labels "metainc.naver.diagnose.operation")}},"network":{{json .HostConfig.NetworkMode}},"readonly":{{json .HostConfig.ReadonlyRootfs}}}'
        value=json.loads(release.command(['docker','inspect','--format',fmt,identity]))
        if value!={'id':identity,'image':image,'user':'10001:10001','source':code.TARGET_COMMIT,
                   'operation':OPERATION_ID,'network':'none','readonly':True}:
            raise ValueError('DIAG_CONTAINER_CHANGED')
    try:
        STAGE='diagnose_readonly'
        command=['docker','run','--detach','--pull','never','--name',name,'--network','none','--read-only',
            '--user','10001:10001','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--log-driver','none','--pids-limit','16','--memory','256m','--cpus','0.5',
            '--label','metainc.naver.diagnose.source='+code.TARGET_COMMIT,
            '--label','metainc.naver.diagnose.operation='+OPERATION_ID,'--entrypoint','python']
        for filename in files:
            command+=['--mount','type=bind,src='+filename+',dst=/diag/'+Path(filename).name+',readonly']
        command+=[image,'-I','-B','-c','import time; time.sleep(120)']
        container=release.command(command,timeout=45).decode().strip()
        if not re.fullmatch(r'[0-9a-f]{64}',container):
            raise ValueError('DIAG_CONTAINER_ID')
        metadata(container)
        raw=release.command(['docker','exec','-i','--user','10001:10001',container,'python','-I','-B','-'],
                            data=script(),timeout=45)
        if len(raw)>16384:
            raise ValueError('DIAG_RESULT_SIZE')
        result=validate_result(json.loads(raw,object_pairs_hook=release.unique))
    finally:
        try:
            found=release.command(['docker','ps','--all','--no-trunc','--filter','name=^/'+name+'$','--format','{{.ID}}'],timeout=30).decode().strip()
            if found:
                if not re.fullmatch(r'[0-9a-f]{64}',found) or container is not None and container!=found:
                    raise ValueError('DIAG_CONTAINER_ID')
                metadata(found)
                release.command(['docker','rm','--force',found],timeout=30)
            elif container is None:
                raise ValueError('DIAG_CREATE_UNCONFIRMED')
            if release.command(['docker','ps','--all','--no-trunc','--filter','name=^/'+name+'$','--format','{{.ID}}'],timeout=30).strip():
                raise ValueError('DIAG_CONTAINER_REMAINS')
        except Exception:
            raise RuntimeError('DIAG_CLEANUP_FAILED') from None
    STAGE='diagnose_postflight'
    if files_snapshot(folder,upgrade)!=files or code.current_state(prepared,host,release,lifecycle,upgrade)!=before:
        raise ValueError('DIAG_POST_BASELINE')
    return {'ok':True,'mode':'failed-code-diagnose','source_commit':code.TARGET_COMMIT,'operation_id':OPERATION_ID,
            'diagnosis':result,'runtime_journal':journal,'database_files_unchanged':True,'existing_app_baseline_unchanged':True,
            'database_mutations':0,'external_calls':0,'diagnostic_container_secrets_mounted':False,'services_changed':False}
