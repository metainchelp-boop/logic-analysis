"""Opaque, reversible archives for one already-rolled-back failed deployment.

No SQLite connection, service command, network request or operating DB write.
The canonical snapshot mode is deliberately separate from quarantine archival.
An unreceipted partial file is refused; it is never assumed safe to delete.
"""
import gzip
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from contextlib import contextmanager

OPERATION_ID = '91725d2c8b9249258b894e6e965af68a'
OLD_COMMIT = '737a65952f2ddbc05a235cf2b139a4a11f4e7673'
TARGET_COMMIT = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
DATA = Path('/var/lib/metainc/naver-engine')
RECEIPTS = Path('/srv/metainc/ad-deploy-staging/receipts')
CONTROL_UID = CONTROL_GID = 0
DATA_UID = DATA_GID = 10001
CHUNK = 1024 * 1024
MAX_FILE = 2 * 1024**3
MAX_GZIP = MAX_FILE + MAX_FILE // 1000 + 65536
RESERVE = 64 * 1024**2
MAX_JSON = 32768
RECEIPT_ALLOWANCE = 4 * MAX_JSON
ACTIONS = frozenset({'inspect','archive_quarantine','archive_canonical_snapshot',
                     'restore_quarantine','restore_canonical_snapshot'})
CODES = frozenset({'ARCHIVE_ACTION','ARCHIVE_POLICY','ARCHIVE_RECEIPT','ARCHIVE_SOURCE_CHANGED',
    'ARCHIVE_SPACE','ARCHIVE_VERIFY','ARCHIVE_CONFLICT','ARCHIVE_IO'})
ROLES = ('canonical_snapshot','quarantine_database','quarantine_wal','quarantine_shm','quarantine_journal')
IDENTITY_KEYS = frozenset({'device','inode','size','mtime_ns','ctime_ns','uid','gid','mode','nlink'})
STAGES = frozenset({'input','policy','receipt','inventory','dry_run','space','compress',
    'verify','archive_receipt','remove_original','restore','restore_publish','complete'})
STAGE = 'input'


class ArchiveInvalid(ValueError):
    pass


def _fail(code):
    raise ArchiveInvalid(code)


def _stage(value):
    global STAGE
    STAGE=value


def failure_report(error):
    code=error.args[0] if len(error.args)==1 and type(error.args[0]) is str and error.args[0] in CODES else 'ARCHIVE_IO'
    return {'ok':False,'status':'failed','stage':STAGE if STAGE in STAGES else 'input','code':code}


def _identity(info):
    fields={'device':info.st_dev,'inode':info.st_ino,'size':info.st_size,
        'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns,'uid':info.st_uid,
        'gid':info.st_gid,'mode':stat.S_IMODE(info.st_mode),'nlink':info.st_nlink}
    if any(type(v) is not int or not 0<=v<2**63 for v in fields.values()):_fail('ARCHIVE_POLICY')
    return fields


def _directory(path, uid, gid, mode):
    # Walk every component with O_NOFOLLOW; never traverse a parent symlink.
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            os.close(fd);fd=child
        info=os.fstat(fd)
        if (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode))!=(uid,gid,mode):_fail('ARCHIVE_POLICY')
        return (info.st_dev,info.st_ino)
    finally:os.close(fd)


def _paths():
    return dict(zip(ROLES,(RECEIPTS/('completion-db-'+OPERATION_ID+'.sqlite'),
        *(DATA/('.completion-failed-db-'+OPERATION_ID)/('engine.db'+suffix)
          for suffix in ('','-wal','-shm','-journal')))))


def _base_directories():
    if os.geteuid()!=0:_fail('ARCHIVE_POLICY')
    _directory(DATA,DATA_UID,DATA_GID,0o750)
    _directory(RECEIPTS,CONTROL_UID,CONTROL_GID,0o700)


def _owner(role):
    return (CONTROL_UID,CONTROL_GID) if role=='canonical_snapshot' else (DATA_UID,DATA_GID)


def _open(path, uid, gid, *, maximum=MAX_FILE, minimum=0):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        found=_checked(path,fd,uid,gid,maximum=maximum,minimum=minimum)
        return fd,found
    except BaseException:
        os.close(fd);raise


def _checked(path,fd,uid,gid,*,maximum=MAX_FILE,minimum=0):
    info=os.fstat(fd);named=os.lstat(path);found=_identity(info)
    if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(named.st_mode)
        or (info.st_dev,info.st_ino)!=(named.st_dev,named.st_ino)
        or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode),info.st_nlink)!=(uid,gid,0o600,1)
        or not minimum<=info.st_size<=maximum):_fail('ARCHIVE_POLICY')
    return found


def _sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def _capacity(path):
    row=os.statvfs(path)
    if (type(row.f_bavail) is not int or type(row.f_frsize) is not int
        or row.f_bavail<0 or row.f_frsize<=0 or row.f_bavail*row.f_frsize>=2**63):_fail('ARCHIVE_POLICY')
    return row.f_bavail*row.f_frsize


def _space(path, amount):
    if type(amount) is not int or amount<0 or _capacity(path)<amount+RESERVE:_fail('ARCHIVE_SPACE')


def inspect_host():
    _base_directories();rows=[];q=DATA/('.completion-failed-db-'+OPERATION_ID)
    if os.path.lexists(q):_directory(q,CONTROL_UID,CONTROL_GID,0o700)
    for role,path in _paths().items():
        try:
            info=os.lstat(path)
        except FileNotFoundError:
            rows.append({'role':role,'exists':False,**{key:None for key in IDENTITY_KEYS},'allocated_bytes':None});continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:_fail('ARCHIVE_POLICY')
        if (info.st_uid,info.st_gid)!=_owner(role):_fail('ARCHIVE_POLICY')
        value=_identity(info);blocks=getattr(info,'st_blocks',None)
        if type(blocks) is not int or not 0<=blocks<2**54:_fail('ARCHIVE_POLICY')
        rows.append({'role':role,'exists':True,**value,'allocated_bytes':blocks*512})
    return {'ok':True,'version':1,'operation_id':OPERATION_ID,'action':'inspect','status':'observed',
        'files':rows,'available_bytes':_capacity(RECEIPTS),'reserve_bytes':RESERVE,
        'operating_database_modified':False,'service_changes':False,'network_calls':0}


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:_fail('ARCHIVE_RECEIPT')
        result[key]=value
    return result


def _json_read(path):
    fd,identity=_open(path,CONTROL_UID,CONTROL_GID,maximum=MAX_JSON,minimum=1)
    try:
        body=bytearray()
        while len(body)<=MAX_JSON:
            chunk=os.read(fd,min(CHUNK,MAX_JSON+1-len(body)))
            if not chunk:break
            body.extend(chunk)
        if len(body)>MAX_JSON or _checked(path,fd,CONTROL_UID,CONTROL_GID,maximum=MAX_JSON)!=identity:_fail('ARCHIVE_RECEIPT')
        try:
            return json.loads(body,object_pairs_hook=_unique,
                parse_constant=lambda value:_fail('ARCHIVE_RECEIPT'))
        except (UnicodeError,json.JSONDecodeError):_fail('ARCHIVE_RECEIPT')
    finally:os.close(fd)


def _snapshot_proof():
    _stage('receipt')
    if os.path.lexists(RECEIPTS/('preview-start-'+TARGET_COMMIT+'.json')):_fail('ARCHIVE_RECEIPT')
    proof=_json_read(RECEIPTS/('completion-snapshot-'+OPERATION_ID+'.json'))
    keys={'source_commit','target_commit','operation_id','database_sha256','schema','snapshot_restore_verified'}
    if (type(proof) is not dict or set(proof)!=keys or proof['source_commit']!=OLD_COMMIT
        or proof['target_commit']!=TARGET_COMMIT or proof['operation_id']!=OPERATION_ID
        or type(proof['schema']) is not int or proof['schema']!=11
        or proof['snapshot_restore_verified'] is not True
        or type(proof['database_sha256']) is not str or re.fullmatch('[0-9a-f]{64}',proof['database_sha256']) is None):
        _fail('ARCHIVE_RECEIPT')
    return proof


def _folder():
    path=RECEIPTS/('completion-failed-archive-'+OPERATION_ID)
    if not os.path.lexists(path):
        os.mkdir(path,0o700);os.chown(path,CONTROL_UID,CONTROL_GID);os.chmod(path,0o700)
        _sync_directory(RECEIPTS)
    _directory(path,CONTROL_UID,CONTROL_GID,0o700)
    return path


def _created_unlink(path, fd, identity):
    try:named=os.lstat(path)
    except FileNotFoundError:return
    current=os.fstat(fd)
    if ((named.st_dev,named.st_ino)!=(identity['device'],identity['inode'])
        or (current.st_dev,current.st_ino)!=(named.st_dev,named.st_ino)):_fail('ARCHIVE_SOURCE_CHANGED')
    os.unlink(path)


def _create(path, uid, gid):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
    identity=_identity(os.fstat(fd))
    try:
        os.fchown(fd,uid,gid);os.fchmod(fd,0o600)
        return fd,_identity(os.fstat(fd))
    except BaseException:
        try:_created_unlink(path,fd,identity)
        finally:os.close(fd)
        raise


def _write(fd, body, directory):
    _space(directory,len(body));view=memoryview(body)
    while view:
        n=os.write(fd,view)
        if n<=0:_fail('ARCHIVE_IO')
        view=view[n:]


def _json_new(path, value):
    body=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if not 1<=len(body)<=MAX_JSON:_fail('ARCHIVE_RECEIPT')
    fd,created=_create(path,CONTROL_UID,CONTROL_GID)
    try:
        _write(fd,body,path.parent);os.fsync(fd);_sync_directory(path.parent)
        return _checked(path,fd,CONTROL_UID,CONTROL_GID,maximum=MAX_JSON,minimum=1)
    except BaseException:
        try:_created_unlink(path,fd,created);_sync_directory(path.parent)
        except Exception:pass
        raise
    finally:os.close(fd)


class _Sink:
    def __init__(self, directory=None, fd=None):
        self.directory=directory;self.fd=fd;self.size=0;self.digest=hashlib.sha256()

    def write(self, body):
        self.size+=len(body)
        if self.size>MAX_GZIP:_fail('ARCHIVE_POLICY')
        if self.fd is not None:_write(self.fd,body,self.directory)
        self.digest.update(body)
        return len(body)

    def flush(self):
        pass


def _compress(fd, sink):
    os.lseek(fd,0,os.SEEK_SET);raw=hashlib.sha256();count=0
    with gzip.GzipFile(filename='',fileobj=sink,mode='wb',compresslevel=6,mtime=0) as compressed:
        while True:
            chunk=os.read(fd,CHUNK)
            if not chunk:break
            count+=len(chunk)
            if count>MAX_FILE:_fail('ARCHIVE_POLICY')
            raw.update(chunk);compressed.write(chunk)
    return count,raw.hexdigest(),sink.size,sink.digest.hexdigest()


def _validate_identity(value):
    if (type(value) is not dict or set(value)!=IDENTITY_KEYS
        or any(type(n) is not int or not 0<=n<2**63 for n in value.values())
        or value['nlink']!=1 or value['mode']!=0o600 or value['size']>MAX_GZIP):_fail('ARCHIVE_RECEIPT')
    return value


def _digest_fd(fd,maximum):
    os.lseek(fd,0,os.SEEK_SET);digest=hashlib.sha256();count=0
    while True:
        chunk=os.read(fd,CHUNK)
        if not chunk:break
        count+=len(chunk)
        if count>maximum:_fail('ARCHIVE_VERIFY')
        digest.update(chunk)
    return count,digest.hexdigest()


def _decompress(path, expected, *, output=None):
    fd,identity=_open(path,CONTROL_UID,CONTROL_GID,maximum=MAX_GZIP,minimum=1)
    try:
        if identity!=expected['compressed_identity']:_fail('ARCHIVE_SOURCE_CHANGED')
        if _digest_fd(fd,MAX_GZIP)!=(expected['compressed_size'],expected['compressed_sha256']):_fail('ARCHIVE_VERIFY')
        os.lseek(fd,0,os.SEEK_SET);digest=hashlib.sha256();count=0
        with os.fdopen(os.dup(fd),'rb') as source,gzip.GzipFile(fileobj=source,mode='rb') as stream:
            while True:
                chunk=stream.read(CHUNK)
                if not chunk:break
                count+=len(chunk)
                if count>expected['source_identity']['size'] or count>MAX_FILE:_fail('ARCHIVE_VERIFY')
                digest.update(chunk)
                if output is not None:_write(output,chunk,expected['_restore_parent'])
        if (count,digest.hexdigest())!=(expected['source_identity']['size'],expected['source_sha256']):_fail('ARCHIVE_VERIFY')
        if _checked(path,fd,CONTROL_UID,CONTROL_GID,maximum=MAX_GZIP)!=identity:_fail('ARCHIVE_SOURCE_CHANGED')
    except (EOFError,gzip.BadGzipFile):_fail('ARCHIVE_VERIFY')
    finally:os.close(fd)


def _manifest(folder,role,proof):
    row=_json_read(folder/(role+'.json'))
    keys={'version','operation_id','role','snapshot_sha256','source_identity','source_sha256',
        'compressed_identity','compressed_size','compressed_sha256','decompression_verified'}
    if (type(row) is not dict or set(row)!=keys or type(row['version']) is not int or row['version']!=1
        or row['operation_id']!=OPERATION_ID or row['role']!=role or row['snapshot_sha256']!=proof['database_sha256']
        or row['decompression_verified'] is not True):_fail('ARCHIVE_RECEIPT')
    for key in ('source_sha256','compressed_sha256'):
        if type(row[key]) is not str or re.fullmatch('[0-9a-f]{64}',row[key]) is None:_fail('ARCHIVE_RECEIPT')
    for key in ('source_identity','compressed_identity'):_validate_identity(row[key])
    if (row['source_identity']['size']>MAX_FILE or type(row['compressed_size']) is not int
        or row['compressed_size']!=row['compressed_identity']['size'] or not 1<=row['compressed_size']<=MAX_GZIP
        or (row['source_identity']['uid'],row['source_identity']['gid'])!=_owner(role)
        or (row['compressed_identity']['uid'],row['compressed_identity']['gid'])!=(CONTROL_UID,CONTROL_GID)
        or (role=='canonical_snapshot' and row['source_sha256']!=proof['database_sha256'])):_fail('ARCHIVE_RECEIPT')
    return row


def _original_unchanged(path,fd,identity,role):
    if _checked(path,fd,*_owner(role))!=identity:_fail('ARCHIVE_SOURCE_CHANGED')
    operating=os.lstat(DATA/'engine.db')
    if (identity['device'],identity['inode'])==(operating.st_dev,operating.st_ino):_fail('ARCHIVE_POLICY')


def _remove_original(path,fd,identity,role,proof):
    if _snapshot_proof()!=proof:_fail('ARCHIVE_RECEIPT')
    _stage('remove_original')
    _original_unchanged(path,fd,identity,role);os.unlink(path);_sync_directory(path.parent)
    if os.path.lexists(path):_fail('ARCHIVE_SOURCE_CHANGED')


def _archive_one(role,folder,proof,expected_identity=None):
    path=_paths()[role];compressed=folder/(role+'.gz');receipt=folder/(role+'.json')
    if os.path.lexists(receipt):
        _stage('verify');row=_manifest(folder,role,proof);_decompress(compressed,row)
        if expected_identity is not None and row['source_identity']!=expected_identity:_fail('ARCHIVE_RECEIPT')
        if not os.path.lexists(path):return False
        fd,identity=_open(path,*_owner(role))
        try:
            if identity!=row['source_identity']:_fail('ARCHIVE_SOURCE_CHANGED')
            _stage('remove_original');_remove_original(path,fd,identity,role,proof)
        finally:os.close(fd)
        return True
    if os.path.lexists(compressed):_fail('ARCHIVE_CONFLICT')
    fd,identity=_open(path,*_owner(role))
    created=None;output=None;durable=False
    try:
        if expected_identity is not None and identity!=expected_identity:_fail('ARCHIVE_SOURCE_CHANGED')
        _original_unchanged(path,fd,identity,role);_stage('dry_run')
        count,digest,amount,compressed_digest=_compress(fd,_Sink())
        _original_unchanged(path,fd,identity,role)
        if count!=identity['size'] or (role=='canonical_snapshot' and digest!=proof['database_sha256']):_fail('ARCHIVE_VERIFY')
        _stage('space');_space(folder,amount+RECEIPT_ALLOWANCE)
        output,created=_create(compressed,CONTROL_UID,CONTROL_GID);_stage('compress')
        result=_compress(fd,_Sink(folder,output))
        if result!=(count,digest,amount,compressed_digest):_fail('ARCHIVE_SOURCE_CHANGED')
        _original_unchanged(path,fd,identity,role);os.fsync(output)
        complete=_checked(compressed,output,CONTROL_UID,CONTROL_GID,maximum=MAX_GZIP,minimum=1)
        row={'version':1,'operation_id':OPERATION_ID,'role':role,'snapshot_sha256':proof['database_sha256'],
            'source_identity':identity,'source_sha256':digest,'compressed_identity':complete,
            'compressed_size':amount,'compressed_sha256':compressed_digest,'decompression_verified':True}
        _stage('verify');_decompress(compressed,row);_original_unchanged(path,fd,identity,role)
        _stage('archive_receipt');_json_new(receipt,row);durable=True
        _stage('remove_original');_remove_original(path,fd,identity,role,proof)
        return True
    except BaseException:
        if output is not None and not durable:
            try:_created_unlink(compressed,output,created);_sync_directory(folder)
            except Exception:pass
        raise
    finally:
        if output is not None:os.close(output)
        os.close(fd)


def _verified_restore_temporary(path,folder,role,proof,source_identity):
    row=_manifest(folder,role,proof)
    if row['source_identity']!=source_identity:_fail('ARCHIVE_RECEIPT')
    intent=folder/(role+'.restore-intent.json')
    if not os.path.lexists(intent):_fail('ARCHIVE_RECEIPT')
    wanted=_restore_record(intent,role,row)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd);named=os.lstat(path);found=_identity(info)
        stable=('device','inode','size','mtime_ns','uid','gid','mode')
        if (not stat.S_ISREG(info.st_mode) or not stat.S_ISREG(named.st_mode)
            or _identity(named)!=found or any(found[k]!=wanted[k] for k in stable)):
            _fail('ARCHIVE_SOURCE_CHANGED')
        original=_paths()[role]
        if found['nlink']==1:
            if os.path.lexists(original) or found!=wanted:_fail('ARCHIVE_SOURCE_CHANGED')
        elif found['nlink']==2:
            linked=os.lstat(original)
            if (not stat.S_ISREG(linked.st_mode) or _identity(linked)!=found):_fail('ARCHIVE_SOURCE_CHANGED')
        else:_fail('ARCHIVE_SOURCE_CHANGED')
        operating=os.lstat(DATA/'engine.db')
        if (found['device'],found['inode'])==(operating.st_dev,operating.st_ino):_fail('ARCHIVE_POLICY')
        if _digest_fd(fd,MAX_FILE)!=(wanted['size'],row['source_sha256']):_fail('ARCHIVE_VERIFY')
        if _identity(os.fstat(fd))!=found or _identity(os.lstat(path))!=found:_fail('ARCHIVE_SOURCE_CHANGED')
    finally:os.close(fd)


def _quarantine_roles(folder,proof,*,restore=False):
    _stage('inventory');q=DATA/('.completion-failed-db-'+OPERATION_ID)
    directory_identity=_directory(q,CONTROL_UID,CONTROL_GID,0o700)
    names={'engine.db':ROLES[1],'engine.db-wal':ROLES[2],'engine.db-shm':ROLES[3],'engine.db-journal':ROLES[4]}
    present=set(os.listdir(q))
    temporary={name+'.restore-'+OPERATION_ID+'.part':role for name,role in names.items()}
    extra=present-set(names)
    if extra and (not restore or extra-set(temporary)):_fail('ARCHIVE_POLICY')
    inventory=folder/'quarantine-set.json'
    if os.path.lexists(inventory):
        row=_json_read(inventory)
        if (type(row) is not dict or set(row)!={'version','operation_id','snapshot_sha256','directory','roles','identities'}
            or type(row['version']) is not int or row['version']!=1 or row['operation_id']!=OPERATION_ID
            or row['snapshot_sha256']!=proof['database_sha256'] or row['directory']!=list(directory_identity)
            or type(row['roles']) is not list or not row['roles'] or row['roles'][0]!=ROLES[1]
            or row['roles']!=[r for r in ROLES[1:] if r in row['roles']]
            or any(r not in row['roles'] for n,r in names.items() if n in present)
            or type(row['identities']) is not dict or set(row['identities'])!=set(row['roles'])):_fail('ARCHIVE_RECEIPT')
        for value in row['identities'].values():_validate_identity(value)
        for name in sorted(extra):
            role=temporary[name]
            if role not in row['roles']:_fail('ARCHIVE_RECEIPT')
            _verified_restore_temporary(q/name,folder,role,proof,row['identities'][role])
        return row['roles'],row['identities']
    if extra:_fail('ARCHIVE_RECEIPT')
    if 'engine.db' not in present:_fail('ARCHIVE_POLICY')
    roles=[role for name,role in names.items() if name in present]
    identities={}
    for role in roles:
        fd,found=_open(_paths()[role],*_owner(role))
        try:_original_unchanged(_paths()[role],fd,found,role);identities[role]=found
        finally:os.close(fd)
    _json_new(inventory,{'version':1,'operation_id':OPERATION_ID,'snapshot_sha256':proof['database_sha256'],
        'directory':list(directory_identity),'roles':roles,'identities':identities})
    return roles,identities


def _restore_record(path, role, row):
    value=_json_read(path)
    if (type(value) is not dict or set(value)!={'version','operation_id','role','source_sha256','identity'}
        or type(value['version']) is not int or value['version']!=1 or value['operation_id']!=OPERATION_ID
        or value['role']!=role or value['source_sha256']!=row['source_sha256']):_fail('ARCHIVE_RECEIPT')
    found=_validate_identity(value['identity'])
    if ((found['uid'],found['gid'])!=_owner(role) or found['size']!=row['source_identity']['size']
        or found['mtime_ns']!=row['source_identity']['mtime_ns']):_fail('ARCHIVE_RECEIPT')
    return found


def _finish_restore(path, temporary, fd, identity, role, folder, row):
    _stage('restore_publish')
    info=os.fstat(fd);found=_identity(info)
    if ((found['device'],found['inode'],found['size'],found['mtime_ns'],found['uid'],found['gid'],found['mode'])!=
        (identity['device'],identity['inode'],identity['size'],identity['mtime_ns'],*_owner(role),0o600)
        or found['nlink'] not in (1,2)
        or _digest_fd(fd,MAX_FILE)!=(identity['size'],row['source_sha256'])):_fail('ARCHIVE_SOURCE_CHANGED')
    if not os.path.lexists(path):
        temp=os.lstat(temporary)
        if (temp.st_dev,temp.st_ino)!=(found['device'],found['inode']):_fail('ARCHIVE_SOURCE_CHANGED')
        os.link(temporary,path,follow_symlinks=False)
    named=os.lstat(path)
    if (named.st_dev,named.st_ino)!=(found['device'],found['inode']):_fail('ARCHIVE_SOURCE_CHANGED')
    if os.path.lexists(temporary):_created_unlink(temporary,fd,identity)
    os.fsync(fd);_sync_directory(path.parent)
    restored=_checked(path,fd,*_owner(role))
    receipt=folder/(role+'.restored.json')
    if os.path.lexists(receipt):
        if _restore_record(receipt,role,row)!=restored:_fail('ARCHIVE_SOURCE_CHANGED')
    else:_json_new(receipt,{'version':1,'operation_id':OPERATION_ID,'role':role,
        'source_sha256':row['source_sha256'],'identity':restored})
    return True


def _restore_one(role,folder,proof,expected_identity=None):
    _stage('restore');path=_paths()[role];receipt=folder/(role+'.json')
    if not os.path.lexists(receipt):
        fd,identity=_open(path,*_owner(role))
        try:
            _original_unchanged(path,fd,identity,role)
            if expected_identity is not None and identity!=expected_identity:_fail('ARCHIVE_SOURCE_CHANGED')
            if role=='canonical_snapshot' and _digest_fd(fd,MAX_FILE)[1]!=proof['database_sha256']:_fail('ARCHIVE_VERIFY')
        finally:os.close(fd)
        return False
    row=_manifest(folder,role,proof)
    if expected_identity is not None and row['source_identity']!=expected_identity:_fail('ARCHIVE_RECEIPT')
    _decompress(folder/(role+'.gz'),row)
    intent=folder/(role+'.restore-intent.json');complete=folder/(role+'.restored.json')
    temporary=path.with_name(path.name+'.restore-'+OPERATION_ID+'.part')
    if os.path.lexists(complete):
        wanted=_restore_record(complete,role,row);fd,found=_open(path,*_owner(role))
        try:
            if found!=wanted or _digest_fd(fd,MAX_FILE)!=(found['size'],row['source_sha256']):_fail('ARCHIVE_SOURCE_CHANGED')
        finally:os.close(fd)
        return False
    if os.path.lexists(intent):
        wanted=_restore_record(intent,role,row)
        existing=path if os.path.lexists(path) else temporary
        fd=os.open(existing,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        try:return _finish_restore(path,temporary,fd,wanted,role,folder,row)
        finally:os.close(fd)
    if os.path.lexists(path):
        fd,found=_open(path,*_owner(role))
        try:
            if found!=row['source_identity']:_fail('ARCHIVE_SOURCE_CHANGED')
            _original_unchanged(path,fd,found,role)
        finally:os.close(fd)
        return False
    _space(path.parent,row['source_identity']['size']+RECEIPT_ALLOWANCE)
    output,created=_create(temporary,*_owner(role));durable=False
    try:
        _decompress(folder/(role+'.gz'),dict(row,_restore_parent=path.parent),output=output)
        os.utime(output,ns=(row['source_identity']['mtime_ns'],row['source_identity']['mtime_ns']))
        os.fsync(output);found=_checked(temporary,output,*_owner(role))
        _json_new(intent,{'version':1,'operation_id':OPERATION_ID,'role':role,
            'source_sha256':row['source_sha256'],'identity':found});durable=True
        return _finish_restore(path,temporary,output,found,role,folder,row)
    except BaseException:
        if not durable:
            try:_created_unlink(temporary,output,created);_sync_directory(path.parent)
            except Exception:pass
        raise
    finally:os.close(output)


@contextmanager
def _operation_lock(folder):
    path=folder/'operation.lock'
    if not os.path.lexists(path):
        try:
            fd,_=_create(path,CONTROL_UID,CONTROL_GID);os.close(fd);_sync_directory(folder)
        except FileExistsError:pass
    fd,_=_open(path,CONTROL_UID,CONTROL_GID,maximum=0)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:_fail('ARCHIVE_CONFLICT')
        yield
    finally:os.close(fd)


def execute(action):
    _stage('input')
    if type(action) is not str or action not in ACTIONS:_fail('ARCHIVE_ACTION')
    if action=='inspect':return inspect_host()
    _stage('policy');_base_directories();proof=_snapshot_proof();folder=_folder()
    with _operation_lock(folder):
        restore=action.startswith('restore_')
        roles,identities=_quarantine_roles(folder,proof,restore=restore) if action.endswith('quarantine') else (['canonical_snapshot'],{})
        operation=_restore_one if restore else _archive_one
        changed=sum(operation(role,folder,proof,identities.get(role)) for role in roles)
    _stage('complete')
    return {'ok':True,'version':1,'operation_id':OPERATION_ID,'action':action,
        'status':('restored' if changed else 'already_restored') if restore else ('archived' if changed else 'already_archived'),
        'files_changed':changed,
        'available_bytes':_capacity(RECEIPTS),'reserve_bytes':RESERVE,
        'operating_database_modified':False,'service_changes':False,'network_calls':0}


def main(argv=None):
    _stage('input')
    argv=sys.argv[1:] if argv is None else argv
    try:
        if len(argv)!=1:_fail('ARCHIVE_ACTION')
        result=execute(argv[0])
    except Exception as error:
        print(json.dumps(failure_report(error),sort_keys=True));return 1
    print(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False));return 0


if __name__=='__main__':
    raise SystemExit(main())
