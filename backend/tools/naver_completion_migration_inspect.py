"""One fixed failed migration: private snapshot only, bounded read-only probe.

Rows, table names, keys, SQL, row hashes, exception text and ledger content never
leave the disposable container. Quarantined operating files are only stat'ed.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

OPERATION='91725d2c8b9249258b894e6e965af68a'
OLD='737a65952f2ddbc05a235cf2b139a4a11f4e7673'
TARGET='e7649acfc71c25d7ae9c981a6ba036b77d97897b'
MAX_DB=2*1024**3
CHUNK=1024**2
MEMORY=768*1024**2
TMP=64*1024**2
DATA=Path('/var/lib/metainc/naver-engine')
ROOT_UID=ROOT_GID=0
ERROR_KINDS=frozenset(('DatabaseError','DataError','OperationalError','IntegrityError',
    'InternalError','ProgrammingError','NotSupportedError','ValueError','TypeError','OverflowError',
    'UnicodeError','UnicodeDecodeError','UnicodeEncodeError','MemoryError','OSError','RuntimeError','OtherError'))
SQL_ERRORS={number:'SQLITE_'+name for number,name in enumerate(
    'ERROR INTERNAL PERM ABORT BUSY LOCKED NOMEM READONLY INTERRUPT IOERR CORRUPT NOTFOUND FULL CANTOPEN '
    'PROTOCOL EMPTY SCHEMA TOOBIG CONSTRAINT MISMATCH MISUSE NOLFS AUTH FORMAT RANGE NOTADB NOTICE WARNING'.split(),1)}
PHASES=frozenset(('open','schema','json_valid','rows_before','complete'))
STAGES=frozenset(('input','pins','snapshot_receipt','snapshot_file','quarantine_metadata','image',
    'container_create','container_identity','container_start','container_wait','container_result','cleanup','complete'))
CODES=frozenset(('INSPECT_ROOT','INSPECT_PINS','INSPECT_RECEIPT','INSPECT_SNAPSHOT','INSPECT_CHANGED',
    'INSPECT_SIDECAR','INSPECT_IMAGE','INSPECT_CONTAINER','INSPECT_OUTPUT','INSPECT_CLEANUP','INSPECT_INTERNAL'))
STAGE='input'

SCRIPT_BODY=r'''
import hashlib,json,re,sqlite3
phase='open';invalid=None
result={'ok':False,'phase':phase,'error_kind':None,'sqlite_primary':None,
        'invalid_learning_call_json':None,'row_hash_completed':False}
try:
 c=sqlite3.connect('file:/inspection/snapshot.sqlite?mode=ro&immutable=1',uri=True,timeout=1)
 c.execute('PRAGMA query_only=ON');c.execute('PRAGMA trusted_schema=OFF')
 phase='schema'
 shaped=c.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
 actual=hashlib.sha256(json.dumps([(k,n,t,re.sub(r'\s+',' ',s or '').strip()) for k,n,t,s in shaped],separators=(',',':')).encode()).hexdigest()
 if c.execute("SELECT value FROM naver_auto_meta WHERE key='schema_version'").fetchone()!=('11',) or actual!=OLD_SCHEMA_HASH:raise ValueError()
 tables={}
 for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
  if re.fullmatch('[a-z][a-z0-9_]{0,100}',t) is None:raise ValueError()
  columns=[r[1] for r in c.execute('PRAGMA table_info('+t+')')]
  if not columns or any(type(v) is not str or re.fullmatch('[a-z][a-z0-9_]{0,100}',v) is None for v in columns):raise ValueError()
  tables[t]=columns
 if not 1<=len(tables)<=512:raise ValueError()
 def authorize(action,a,b,database,trigger):
  if action==sqlite3.SQLITE_SELECT:return sqlite3.SQLITE_OK
  if action==sqlite3.SQLITE_READ and database=='main' and (a in tables or a=='sqlite_master'):return sqlite3.SQLITE_OK
  if action==sqlite3.SQLITE_FUNCTION and a is None and b in ('like','json_valid'):return sqlite3.SQLITE_OK
  return sqlite3.SQLITE_DENY
 c.set_authorizer(authorize)
 phase='json_valid'
 invalid=bool(c.execute("SELECT EXISTS(SELECT 1 FROM naver_auto_meta WHERE key LIKE 'learning-call:%' AND json_valid(value) IS NOT 1)").fetchone()[0])
 phase='rows_before';total=0;out={}
 for t,columns in tables.items():
  query='SELECT '+','.join(columns)+' FROM '+t
  if t=='naver_auto_meta':query+=" WHERE key != 'schema_version'"
  query+=' ORDER BY rowid'
  h=hashlib.sha256();count=0
  for row in c.execute(query):
   count+=1;total+=1
   if total>10000000:raise ValueError()
   h.update(json.dumps(list(row),ensure_ascii=True,separators=(',',':'),allow_nan=False).encode()+b'\n')
  out[t]=(count,h.hexdigest())
 phase='complete';result.update(ok=True,row_hash_completed=True)
 c.close()
except Exception as error:
 kind=type(error).__name__;result['error_kind']=kind if kind in ERROR_KINDS else 'OtherError'
 number=getattr(error,'sqlite_errorcode',None)
 if isinstance(error,sqlite3.Error) and type(number) is int:result['sqlite_primary']=SQL_ERRORS.get(number&255)
result.update(phase=phase,invalid_learning_call_json=invalid)
print(json.dumps(result,separators=(',',':')))
'''


def _script(C):
    return ('OLD_SCHEMA_HASH='+repr(C.SCHEMA_SHA256['old'])+'\nERROR_KINDS='+repr(sorted(ERROR_KINDS))+
            '\nSQL_ERRORS='+repr(SQL_ERRORS)+'\n')+SCRIPT_BODY


def _identity(info):
    return (info.st_dev,info.st_ino,info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode),
        info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _check_fd(path,fd,*,minimum=1,maximum=MAX_DB):
    info=os.fstat(fd);named=path.lstat()
    if (path.resolve()!=path or not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
        or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(ROOT_UID,ROOT_GID,0o600)
        or not minimum<=info.st_size<=maximum or _identity(named)!=_identity(info)):
        raise ValueError('INSPECT_SNAPSHOT')
    return _identity(info)


def _absent_sidecars(path):
    if any(os.path.lexists(str(path)+suffix) for suffix in ('-wal','-shm','-journal')):
        raise ValueError('INSPECT_SIDECAR')


def _receipt(path,release):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=_check_fd(path,fd,maximum=32768)
        raw=os.read(fd,32769)
        if len(raw)!=before[6] or _check_fd(path,fd,maximum=32768)!=before:raise ValueError('INSPECT_CHANGED')
        value=json.loads(raw,object_pairs_hook=release.unique)
    except (UnicodeError,ValueError,TypeError):raise ValueError('INSPECT_RECEIPT') from None
    finally:os.close(fd)
    if (type(value) is not dict or set(value)!={'source_commit','target_commit','operation_id','database_sha256','schema','snapshot_restore_verified'}
        or value['source_commit']!=OLD or value['target_commit']!=TARGET or value['operation_id']!=OPERATION
        or type(value['schema']) is not int or value['schema']!=11 or value['snapshot_restore_verified'] is not True
        or type(value['database_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',value['database_sha256']) is None):
        raise ValueError('INSPECT_RECEIPT')
    return value


def _metadata(release):
    release.trusted_dir(DATA,uid=10001,gid=10001,mode=0o750)
    quarantine=DATA/('.completion-failed-db-'+OPERATION)
    if os.path.lexists(quarantine):release.trusted_dir(quarantine,mode=0o700)
    rows=[]
    for suffix,role in (('','database'),('-wal','wal'),('-shm','shm'),('-journal','journal')):
        path=quarantine/('engine.db'+suffix)
        if not os.path.lexists(path):rows.append({'role':role,'exists':False,'regular':None,'uid':None,'gid':None,'mode':None,'nlink':None,'size_bytes':None});continue
        info=path.lstat()
        rows.append({'role':role,'exists':True,'regular':stat.S_ISREG(info.st_mode),'uid':info.st_uid,'gid':info.st_gid,
            'mode':format(stat.S_IMODE(info.st_mode),'04o'),'nlink':info.st_nlink,'size_bytes':info.st_size})
    free=os.statvfs(DATA)
    return rows,free.f_bavail*free.f_frsize


def _raw_json(release,args,*,maximum=16384):
    raw=release.command(args,timeout=30)
    if type(raw) is not bytes or not 1<=len(raw)<=maximum:raise ValueError('INSPECT_CONTAINER')
    try:return json.loads(raw,object_pairs_hook=release.unique)
    except (ValueError,UnicodeError,TypeError):raise ValueError('INSPECT_CONTAINER') from None


def _container(release,identity,image,name,snapshot,script):
    fields={'image':'.Image','user':'.Config.User',
        'operation':'(index .Config.Labels "metainc.naver.inspect.operation")',
        'source':'(index .Config.Labels "metainc.naver.inspect.source")',
        'image_source':'(index .Config.Labels "metainc.naver.preview.source")',
        'project':'(index .Config.Labels "com.docker.compose.project")','entrypoint':'.Config.Entrypoint',
        'cmd':'.Config.Cmd','readonly':'.HostConfig.ReadonlyRootfs','network':'.HostConfig.NetworkMode',
        'memory':'.HostConfig.Memory','swap':'.HostConfig.MemorySwap','pids':'.HostConfig.PidsLimit',
        'cpu':'.HostConfig.NanoCpus','caps':'.HostConfig.CapDrop','security':'.HostConfig.SecurityOpt',
        'tmpfs':'.HostConfig.Tmpfs','mounts':'.Mounts','name':'.Name'}
    fmt='{'+','.join(json.dumps(k)+':{{json '+v+'}}' for k,v in fields.items())+'}'
    row=_raw_json(release,['docker','inspect','--format',fmt,identity],maximum=32768)
    expected={'image':image,'user':'0:0','operation':OPERATION,'source':TARGET,'image_source':TARGET,
        'entrypoint':['python'],'cmd':['-I','-B','-c',script],
        'readonly':True,'network':'none','memory':MEMORY,'swap':MEMORY,'pids':64,'cpu':1000000000,
        'caps':['ALL'],'security':['no-new-privileges'],'tmpfs':{'/tmp':'rw,noexec,nosuid,nodev,size='+str(TMP)+',mode=1777'},'name':'/'+name}
    if (type(row) is not dict or set(row)!=set(fields)
        or any(type(row[k]) is not type(v) or row[k]!=v for k,v in expected.items())):raise ValueError('INSPECT_CONTAINER')
    # Missing Go map[string]string indices encode as an empty string; some
    # adapters encode a missing label as null. Neither admits a compose project.
    if row['project'] is not None and (type(row['project']) is not str or row['project']!=''):
        raise ValueError('INSPECT_CONTAINER')
    mounts=row['mounts']
    if (type(mounts) is not list or len(mounts)!=1 or type(mounts[0]) is not dict
        or mounts[0].get('Type')!='bind' or mounts[0].get('Source')!=str(snapshot)
        or mounts[0].get('Destination')!='/inspection/snapshot.sqlite' or mounts[0].get('RW') is not False
        or mounts[0].get('Propagation')!='rprivate'):raise ValueError('INSPECT_CONTAINER')


def _result(raw,release):
    if type(raw) is not bytes or not 1<=len(raw)<=2048:raise ValueError('INSPECT_OUTPUT')
    try:value=json.loads(raw,object_pairs_hook=release.unique)
    except (ValueError,UnicodeError,TypeError):raise ValueError('INSPECT_OUTPUT') from None
    if (type(value) is not dict or set(value)!={'ok','phase','error_kind','sqlite_primary','invalid_learning_call_json','row_hash_completed'}
        or type(value['ok']) is not bool or type(value['row_hash_completed']) is not bool
        or type(value['phase']) is not str or value['phase'] not in PHASES
        or value['error_kind'] is not None and (type(value['error_kind']) is not str or value['error_kind'] not in ERROR_KINDS)
        or value['sqlite_primary'] is not None and (type(value['sqlite_primary']) is not str or value['sqlite_primary'] not in SQL_ERRORS.values())
        or value['invalid_learning_call_json'] is not None and type(value['invalid_learning_call_json']) is not bool
        or value['row_hash_completed']!=value['ok']
        or value['phase'] in ('rows_before','complete') and type(value['invalid_learning_call_json']) is not bool
        or value['ok']!=(value['phase']=='complete' and value['row_hash_completed'] is True)
        or value['ok'] and (value['error_kind'] is not None or value['sqlite_primary'] is not None)
        or not value['ok'] and value['error_kind'] is None):raise ValueError('INSPECT_OUTPUT')
    return value


def _probe(snapshot,image,script,release,fd,before):
    global STAGE
    name='naver-migration-inspect-'+OPERATION+'-'+uuid.uuid4().hex
    find=['docker','ps','--all','--no-trunc','--filter','name=^/'+name+'$','--format','{{.ID}}']
    if release.command(find,timeout=30).strip():raise ValueError('INSPECT_CONTAINER')
    attempted=False;identity=None;failure=None;failed_stage=None;result=None;process=None
    try:
        STAGE='container_create';attempted=True
        args=['docker','create','--name',name,'--label','metainc.naver.inspect.operation='+OPERATION,
            '--label','metainc.naver.inspect.source='+TARGET,'--network','none','--read-only','--user','0:0',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--memory',str(MEMORY),'--memory-swap',str(MEMORY),
            '--pids-limit','64','--cpus','1','--tmpfs','/tmp:rw,noexec,nosuid,nodev,size='+str(TMP)+',mode=1777',
            '--mount','type=bind,source='+str(snapshot)+',target=/inspection/snapshot.sqlite,readonly',
            '--env','TMPDIR=/tmp','--log-driver','json-file','--log-opt','max-size=4k','--log-opt','max-file=1',
            '--entrypoint','python',image,'-I','-B','-c',script]
        raw=release.command(args,timeout=60)
        if type(raw) is not bytes or len(raw)>128:raise ValueError('INSPECT_CONTAINER')
        identity=raw.decode('ascii').strip()
        if re.fullmatch('[0-9a-f]{64}',identity) is None:raise ValueError('INSPECT_CONTAINER')
        STAGE='container_identity';_container(release,identity,image,name,snapshot,script)
        if _check_fd(snapshot,fd)!=before:raise ValueError('INSPECT_CHANGED')
        _absent_sidecars(snapshot)
        STAGE='container_start';release.command(['docker','start',identity],timeout=30)
        STAGE='container_wait'
        status=release.command(['docker','wait',identity],timeout=180).strip()
        STAGE='container_result'
        process=_raw_json(release,['docker','inspect','--format',
            '{"exit_code":{{json .State.ExitCode}},"oom_killed":{{json .State.OOMKilled}},"running":{{json .State.Running}}}',identity])
        if (type(process) is not dict or set(process)!={'exit_code','oom_killed','running'}
            or type(process['exit_code']) is not int or not 0<=process['exit_code']<=255
            or type(process['oom_killed']) is not bool or process['running'] is not False
            or status!=str(process['exit_code']).encode()):raise ValueError('INSPECT_CONTAINER')
        raw=release.command(['docker','logs',identity],timeout=30)
        if type(raw) is not bytes or len(raw)>2048:raise ValueError('INSPECT_OUTPUT')
        if raw.strip():result=_result(raw,release)
        elif process['exit_code']==0:raise ValueError('INSPECT_OUTPUT')
        process={key:process[key] for key in ('exit_code','oom_killed')}
    except Exception as error:failure=error;failed_stage=STAGE
    finally:
        if attempted:
            try:
                STAGE='cleanup'
                raw=release.command(find,timeout=30)
                if type(raw) is not bytes or len(raw)>128:raise ValueError('INSPECT_CLEANUP')
                found=raw.decode('ascii').strip()
                if found:
                    if re.fullmatch('[0-9a-f]{64}',found) is None or identity is not None and found!=identity:raise ValueError('INSPECT_CLEANUP')
                    _container(release,found,image,name,snapshot,script)
                    release.command(['docker','rm','--force',found],timeout=45)
                elif identity is None:raise ValueError('INSPECT_CLEANUP')
                if release.command(find,timeout=30).strip():raise ValueError('INSPECT_CLEANUP')
            except Exception:raise ValueError('INSPECT_CLEANUP') from None
    if failure is not None:STAGE=failed_stage;raise failure
    if _check_fd(snapshot,fd)!=before:raise ValueError('INSPECT_CHANGED')
    _absent_sidecars(snapshot)
    return result,process


def inspect_host(C,release,upgrade):
    global STAGE
    STAGE='input';fd=None
    try:
        if os.geteuid()!=0:raise ValueError('INSPECT_ROOT')
        STAGE='pins';C.require_pins()
        if (C.OLD_COMMIT!=OLD or C.TARGET_COMMIT!=TARGET or C.OLD_SCHEMA!=11 or C.TARGET_SCHEMA!=21
            or type(C.SCHEMA_SHA256) is not dict or type(C.SCHEMA_SHA256.get('old')) is not str
            or re.fullmatch('[0-9a-f]{64}',C.SCHEMA_SHA256['old']) is None):raise ValueError('INSPECT_PINS')
        folder=release.ROOT/'receipts';release.trusted_dir(folder,mode=0o700)
        STAGE='snapshot_receipt';receipt=_receipt(folder/('completion-snapshot-'+OPERATION+'.json'),release)
        snapshot=folder/('completion-db-'+OPERATION+'.sqlite');_absent_sidecars(snapshot)
        STAGE='snapshot_file';fd=os.open(snapshot,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        before=_check_fd(snapshot,fd);fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        digest=hashlib.sha256();size=0
        while True:
            chunk=os.read(fd,CHUNK)
            if not chunk:break
            size+=len(chunk)
            if size>MAX_DB:raise ValueError('INSPECT_SNAPSHOT')
            digest.update(chunk)
        if size!=before[6] or digest.hexdigest()!=receipt['database_sha256']:raise ValueError('INSPECT_SNAPSHOT')
        if _check_fd(snapshot,fd)!=before:raise ValueError('INSPECT_CHANGED')
        STAGE='quarantine_metadata';metadata,free=_metadata(release)
        STAGE='image';path,prepared=upgrade.manifest(release,TARGET)
        if (path.name!='naver-'+TARGET or prepared.get('source_commit')!=TARGET
            or type(prepared.get('images')) is not dict or set(prepared['images'])!={'engine','relay'}
            or type(prepared['images']['engine']) is not str or re.fullmatch('sha256:[0-9a-f]{64}',prepared['images']['engine']) is None):
            raise ValueError('INSPECT_IMAGE')
        result,process=_probe(snapshot,prepared['images']['engine'],_script(C),release,fd,before)
        STAGE='complete'
        return {'version':1,'ok':True,'diagnostic_only':True,'operation_id':OPERATION,'snapshot_verified':True,
            'snapshot_hash_verified':True,'snapshot_size_bytes':size,'snapshot_schema':11,'quarantine_files':metadata,
            'filesystem_available_bytes':free,'row_check':result,'process':process,'containers_remaining':0,'network_calls':0,
            'database_writes':False,'source_writes':False,'service_changes':False,
            'sandbox':{'network':'none','read_only':True,'memory_bytes':MEMORY,'tmpfs_bytes':TMP}}
    except Exception as error:
        code=error.args[0] if error.args else None
        return {'version':1,'ok':False,'diagnostic_only':True,'stage':STAGE if STAGE in STAGES else 'input',
            'code':code if type(code) is str and code in CODES else 'INSPECT_INTERNAL',
            'error_kind':type(error).__name__ if type(error).__name__ in ERROR_KINDS else 'OtherError',
            'network_calls':0,'database_writes':False,'source_writes':False,'service_changes':False}
    finally:
        if fd is not None:os.close(fd)
