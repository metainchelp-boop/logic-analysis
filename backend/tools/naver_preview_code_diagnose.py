"""Pinned failed-rollout aggregate reader; no keys, external calls or DB writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

OPERATION_ID = 'a49a7ccfe32840298914f121883caee5'
TARGET_COMMIT = 'e1c4b3526db55d78175a1d6598f3403fdb9398f7'
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
    if schema not in ('7','8'):
        raise ValueError('DIAG_SCHEMA')
    inventory={'available':schema=='8','day':INVENTORY_DAY,'rows':0,'groups':[]}
    if schema=='8':
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
    if type(value['schema_version']) is not int or value['schema_version'] not in (7,8):
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
    if inventory['available'] is not (value['schema_version']==8) or inventory['day']!=INVENTORY_DAY:
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


def relay_journal(release):
    unit='metainc-naver-relay.service'
    since,until='2026-10-02 03:52:00 UTC','2026-10-02 04:13:10 UTC'
    raw=release.command(['/usr/bin/journalctl','--no-pager','--output=json','--output-fields=UNIT,_PID,MESSAGE',
        '--since',since,'--until',until,'--lines=513','UNIT='+unit,'_PID=1'],timeout=30)
    if len(raw)>1048576:
        raise ValueError('DIAG_JOURNAL_SIZE')
    rows=raw.splitlines()
    if len(rows)>512:
        raise ValueError('DIAG_JOURNAL_LIMIT')
    exits,results={},{}
    unrecognized=0
    for line in rows:
        row=json.loads(line,object_pairs_hook=release.unique)
        if not isinstance(row,dict) or row.get('UNIT')!=unit or row.get('_PID')!='1' or not isinstance(row.get('MESSAGE'),str) or len(row['MESSAGE'])>4096:
            raise ValueError('DIAG_JOURNAL_FIELDS')
        message=row['MESSAGE']
        event=re.fullmatch(re.escape(unit)+r': Main process exited, code=([a-z-]+), status=([0-9]{1,3})/([A-Za-z0-9/_-]+)',message)
        failure=re.fullmatch(re.escape(unit)+r": Failed with result '([^']{1,64})'\.",message)
        if event and int(event[2])<=255:
            kind=event[1] if event[1] in ('exited','killed','dumped') else 'UNRECOGNIZED'
            label=event[3] if event[3] in ('SUCCESS','FAILURE','n/a','TERM','KILL','INT','ABRT','SEGV','PIPE','HUP','QUIT') else 'UNRECOGNIZED'
            key=(kind,int(event[2]),label)
            exits[key]=exits.get(key,0)+1
        elif failure or message==unit+': Deactivated successfully.':
            result=failure[1] if failure else 'success'
            if result not in ('success','exit-code','signal','core-dump','timeout','watchdog','start-limit-hit','resources','protocol','oom-kill'):
                result='UNRECOGNIZED'
            results[result]=results.get(result,0)+1
        else:
            unrecognized+=1
    return {'since_utc':'2026-10-02T03:52:00Z','until_utc':'2026-10-02T04:13:10Z',
        'entries_inspected':len(rows),'main_process_exit_count':sum(exits.values()),'unrecognized_event_count':unrecognized,
        'exits':[{'exit_type':k[0],'exit_status':k[1],'status_label':k[2],'count':v} for k,v in sorted(exits.items())],
        'results':[{'result':k,'count':v} for k,v in sorted(results.items())]}


def run(package,host,release,lifecycle,upgrade,code):
    global STAGE
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
    if not os.path.lexists(folder):
        STAGE='diagnose_journal'
        journal=relay_journal(release)
        STAGE='diagnose_postflight'
        if (os.path.lexists(folder) or upgrade.manifest(release,code.TARGET_COMMIT,prepared)!=(path,receipt)
                or code.current_state(prepared,host,release,lifecycle,upgrade)!=before):
            raise ValueError('DIAG_POST_BASELINE')
        return {'ok':True,'mode':'failed-code-relay-journal','source_commit':code.TARGET_COMMIT,'operation_id':OPERATION_ID,
            'quarantine_present':False,'relay_journal':journal,'existing_app_baseline_unchanged':True,
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
            'diagnosis':result,'database_files_unchanged':True,'existing_app_baseline_unchanged':True,
            'database_mutations':0,'external_calls':0,'diagnostic_container_secrets_mounted':False,'services_changed':False}
