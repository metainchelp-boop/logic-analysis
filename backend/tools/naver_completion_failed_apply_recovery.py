"""Restart only the old services after the exact pre-migration failed APPLY.

No source, database, unit, image or secret is repaired. Immutable SQLite is used
only while both exact old writers are stopped and all three sidecars are absent.
The 2 GiB metadata bound preserves the observed 0600 policy; it never reads the
whole database into memory. This is not an APPLY, migration, or DB restoration.
"""
from contextlib import closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import sqlite3
import stat

FAILED_SOURCE = '3be8d004df3b231069a2a7a8d8cdeeb4b816d523'
FAILED_OPERATION = '22edf4cf8c1c4bbcb63592cc9689fc96'
PACKAGE_SHA256 = '844362649c7507e31740323390327768412a3a3e00495f823c4804ac9aaadd25'
OLD_COMMIT = '737a65952f2ddbc05a235cf2b139a4a11f4e7673'
TARGET_COMMIT = 'e7649acfc71c25d7ae9c981a6ba036b77d97897b'
DATA = Path('/var/lib/metainc/naver-engine')
# Confirmed by metadata-only run 38199399403; no permissions are relaxed.
DB_UID = DB_GID = 10001
DB_MODE = 0o600
DB_MAXIMUM = 2 * 1024**3
STAGE = 'input'
STAGES = frozenset(('input','package','old_manifest','recovery_receipt','absence',
    'old_units','stopped_writers','database_schema','pre_start','start_old','verify_old','write_receipt'))
CODES = frozenset(('RECOVERY_PACKAGE','RECOVERY_ROOT','RECOVERY_PINS','RECOVERY_BASELINE',
    'RECOVERY_OLD_MANIFEST','RECOVERY_BACKUP','RECOVERY_EVIDENCE_EXISTS','RECOVERY_UNIT_CHANGED',
    'RECOVERY_DEPENDENCY','RECOVERY_CONTAINER','RECOVERY_DB_POLICY','RECOVERY_DB_SIDECAR',
    'RECOVERY_DB_LOCK','RECOVERY_DB_CHANGED','RECOVERY_DB_SCHEMA','RECOVERY_ALREADY_ATTEMPTED',
    'RECOVERY_STATE_CHANGED','RECOVERY_FLAGS','RECOVERY_RECEIPT','RECOVERY_INTERNAL'))


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',',':')).encode()


def _absent(paths):
    if any(os.path.lexists(path) for path in paths):
        raise ValueError('RECOVERY_EVIDENCE_EXISTS')


def _sidecars():
    return tuple(DATA/name for name in ('engine.db-wal','engine.db-shm','engine.db-journal'))


def _no_sidecars():
    if any(os.path.lexists(path) for path in _sidecars()):
        raise ValueError('RECOVERY_DB_SIDECAR')


def _identity(info):
    return (info.st_dev,info.st_ino,info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode),
            info.st_nlink,info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _db_info(fd,path):
    info=os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink!=1
        or (info.st_uid,info.st_gid)!=(DB_UID,DB_GID)
        or stat.S_IMODE(info.st_mode)!=DB_MODE or not 1<=info.st_size<=DB_MAXIMUM
        or path.is_symlink() or path.resolve()!=path
        or _identity(path.lstat())!=_identity(info)):
        raise ValueError('RECOVERY_DB_POLICY')
    return _identity(info)


def _database_schema(release,C):
    release.trusted_dir(DATA,uid=DB_UID,gid=DB_GID,mode=0o750)
    _no_sidecars()
    path=DATA/'engine.db'
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=_db_info(fd,path)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:raise ValueError('RECOVERY_DB_LOCK') from None
        _no_sidecars()
        # Immutable disables SQLite sidecar creation and WAL handling. It is
        # appropriate here only because no live writer/sidecar is admitted.
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=1)) as conn:
            conn.execute('PRAGMA query_only=ON')
            conn.execute('PRAGMA trusted_schema=OFF')
            budget=[0]
            def progress():
                budget[0]+=1
                return int(budget[0]>10000)
            conn.set_progress_handler(progress,100)
            def authorizer(action,arg1,arg2,database,trigger):
                if action==sqlite3.SQLITE_SELECT:return sqlite3.SQLITE_OK
                if (action==sqlite3.SQLITE_READ and database=='main'
                    and arg1 in ('sqlite_master','naver_auto_meta')):return sqlite3.SQLITE_OK
                if action==sqlite3.SQLITE_FUNCTION and arg1 is None and arg2=='like':return sqlite3.SQLITE_OK
                return sqlite3.SQLITE_DENY
            conn.set_authorizer(authorizer)
            try:C.database_contract(conn,OLD_COMMIT)
            except Exception:raise ValueError('RECOVERY_DB_SCHEMA') from None
        _no_sidecars()
        if _db_info(fd,path)!=before:raise ValueError('RECOVERY_DB_CHANGED')
        return before
    finally:os.close(fd)


def _database_unchanged(expected,release):
    release.trusted_dir(DATA,uid=DB_UID,gid=DB_GID,mode=0o750)
    _no_sidecars()
    path=DATA/'engine.db';fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        if _db_info(fd,path)!=expected:raise ValueError('RECOVERY_DB_CHANGED')
    finally:os.close(fd)


def _read_json(path,release,upgrade):
    try:
        raw=upgrade.read_file(path,uid=0,gid=0,mode=0o600,maximum=32768)
        return json.loads(raw,object_pairs_hook=release.unique)
    except Exception:raise ValueError('RECOVERY_RECEIPT') from None


def _containers(path,receipt,release,lifecycle,C):
    rows={}
    fields={'id':'.Id','image':'.Image','running':'.State.Running','restarting':'.State.Restarting',
        'pid':'.State.Pid','source':'(index .Config.Labels "metainc.naver.preview.source")',
        'project':'(index .Config.Labels "com.docker.compose.project")',
        'service':'(index .Config.Labels "com.docker.compose.service")'}
    fmt='{'+','.join(json.dumps(k)+':{{json '+v+'}}' for k,v in fields.items())+'}'
    for name,unit in zip(('engine','relay'),lifecycle.UNITS):
        C.stopped_writer(release,lifecycle,path,{OLD_COMMIT:receipt['images']},unit)
        raw=release.command(release.compose(path,name)+['ps','--all','--quiet'],timeout=30)
        if type(raw) is not bytes or len(raw)>256:raise ValueError('RECOVERY_CONTAINER')
        identity=raw.decode('ascii').strip()
        if not re.fullmatch('[0-9a-f]{64}',identity):raise ValueError('RECOVERY_CONTAINER')
        raw=release.command(['docker','inspect','--format',fmt,identity],timeout=30)
        if type(raw) is not bytes or not 1<=len(raw)<=4096:raise ValueError('RECOVERY_CONTAINER')
        row=json.loads(raw,object_pairs_hook=release.unique)
        if (type(row) is not dict or set(row)!=set(fields) or row['id']!=identity
            or row['image']!=receipt['images'][name] or row['source']!=OLD_COMMIT
            or row['project']!='naver-'+name or row['service']!='naver-'+name
            or row['running'] is not False or row['restarting'] is not False
            or type(row['pid']) is not int or row['pid']!=0):raise ValueError('RECOVERY_CONTAINER')
        rows[name]=row
    return rows


def _units(old_files,release,lifecycle,upgrade):
    for parent in (lifecycle.UNIT_DIR,lifecycle.TMPFILES.parent):release.trusted_dir(parent)
    for filename,body in old_files.items():
        if upgrade.read_file(filename,mode=0o644,maximum=32768)!=body:
            raise ValueError('RECOVERY_UNIT_CHANGED')
    for unit in ('docker.service',lifecycle.TUNNEL):
        if lifecycle._state(release,unit,'ActiveState')!='active':raise ValueError('RECOVERY_DEPENDENCY')
    for unit in lifecycle.UNITS:
        if lifecycle._state(release,unit,'UnitFileState')!='enabled':raise ValueError('RECOVERY_UNIT_CHANGED')


def _recover(package,host,release,lifecycle,upgrade,C):
    global STAGE
    STAGE='package'
    if (type(package) is not dict or set(package)!={'release','operation_id'}
        or package.get('operation_id')!=FAILED_OPERATION
        or hashlib.sha256(_json(package)).hexdigest()!=PACKAGE_SHA256):raise ValueError('RECOVERY_PACKAGE')
    if os.geteuid()!=0:raise ValueError('RECOVERY_ROOT')
    if (C.OLD_COMMIT!=OLD_COMMIT or C.TARGET_COMMIT!=TARGET_COMMIT
        or C.OLD_SCHEMA!=11 or C.TARGET_SCHEMA!=21 or C.DATA!=DATA):raise ValueError('RECOVERY_PINS')
    C.require_pins();prepared=C.validate_package(package['release'],release)
    if host.baseline()!=prepared['baseline']:raise ValueError('RECOVERY_BASELINE')
    folder=release.ROOT/'receipts';release.trusted_dir(folder,mode=0o700)
    absent=(folder/('preview-start-'+TARGET_COMMIT+'.json'),
        folder/('completion-snapshot-'+FAILED_OPERATION+'.json'),
        folder/('completion-db-'+FAILED_OPERATION+'.sqlite'),
        folder/('completion-db-'+FAILED_OPERATION+'.verify.sqlite'))
    STAGE='absence';_absent(absent)
    STAGE='old_manifest'
    path,receipt=upgrade.manifest(release,OLD_COMMIT,started=True)
    if (path.name!='naver-'+OLD_COMMIT or receipt.get('source_commit')!=OLD_COMMIT
        or receipt.get('package',{}).get('baseline')!=prepared['baseline']
        or receipt.get('package',{}).get('source_tar_gz_sha256')!=C.OLD_SOURCE_SHA256):
        raise ValueError('RECOVERY_OLD_MANIFEST')
    old_files=lifecycle.unit_files(path,pwd.getpwnam('www-data').pw_gid,release)
    STAGE='recovery_receipt'
    backup=_read_json(folder/('code-upgrade-'+FAILED_OPERATION+'.json'),release,upgrade)
    expected={'source_commit':OLD_COMMIT,'target_commit':TARGET_COMMIT,'images':receipt['images'],
        'units':{str(p):body.decode() for p,body in old_files.items() if p!=lifecycle.TMPFILES}}
    if backup!=expected:raise ValueError('RECOVERY_BACKUP')
    success=folder/('completion-failed-apply-recovered-'+FAILED_OPERATION+'.json')
    intent=folder/('completion-failed-apply-recovery-'+FAILED_OPERATION+'.json')
    STAGE='old_units';_units(old_files,release,lifecycle,upgrade)
    result={'ok':True,'stage':'failed_apply_recovery','failed_source_commit':FAILED_SOURCE,
        'source_commit':OLD_COMMIT,'failed_apply_operation_id':FAILED_OPERATION,
        'old_services_restored':True,'database_schema':11,'database_writes':False,
        'source_writes':False,'database_restored':False,'migration_performed':False,
        'new_apply_performed':False,'execution_enabled':False,'runtime_flags_verified':True}
    if os.path.lexists(success):
        if _read_json(success,release,upgrade)!=result:raise ValueError('RECOVERY_RECEIPT')
        # Never use immutable SQLite once the old writer is live.
        C.verify_running(path,receipt,release,lifecycle,upgrade)
        if C.container_runtime_flags(path,receipt,release,lifecycle)['execution_enabled'] is not False:
            raise ValueError('RECOVERY_FLAGS')
        return result
    if os.path.lexists(intent):raise ValueError('RECOVERY_ALREADY_ATTEMPTED')
    STAGE='stopped_writers';containers=_containers(path,receipt,release,lifecycle,C)
    bootstrap=C.bootstrap_state(release,upgrade)
    STAGE='database_schema';identity=_database_schema(release,C)
    STAGE='pre_start'
    _absent(absent);_units(old_files,release,lifecycle,upgrade)
    if (_containers(path,receipt,release,lifecycle,C)!=containers
        or host.baseline()!=prepared['baseline'] or C.bootstrap_state(release,upgrade)!=bootstrap):
        raise ValueError('RECOVERY_STATE_CHANGED')
    _database_unchanged(identity,release)
    release.write_new(intent,_json({'version':1,'operation_id':FAILED_OPERATION,
        'failed_source_commit':FAILED_SOURCE,'package_sha256':PACKAGE_SHA256,
        'source_commit':OLD_COMMIT,'database_identity':list(identity),'state':'start_attempted'}))
    STAGE='start_old'
    try:
        for unit in lifecycle.UNITS:release.command(['/usr/bin/systemctl','start',unit],timeout=90)
        STAGE='verify_old';C.verify_running(path,receipt,release,lifecycle,upgrade)
        if C.container_runtime_flags(path,receipt,release,lifecycle)['execution_enabled'] is not False:
            raise ValueError('RECOVERY_FLAGS')
        if host.baseline()!=prepared['baseline'] or C.bootstrap_state(release,upgrade)!=bootstrap:
            raise ValueError('RECOVERY_STATE_CHANGED')
        STAGE='write_receipt';release.write_new(success,_json(result))
    except Exception:
        # An ambiguous/failed restart never falls through to another APPLY.
        for unit in reversed(lifecycle.UNITS):
            try:release.command(['/usr/bin/systemctl','stop',unit],timeout=90)
            except Exception:pass
        raise
    return result


def recover(package,host,release,lifecycle,upgrade,C):
    global STAGE
    STAGE='input'
    try:return _recover(package,host,release,lifecycle,upgrade,C)
    except Exception as error:
        value=error.args[0] if error.args else None
        code=value if type(value) is str and value in CODES else 'RECOVERY_INTERNAL'
        return {'ok':False,'stage':'failed_apply_recovery','error_code':'RECOVERY_REFUSED',
            'failed_stage':STAGE if type(STAGE) is str and STAGE in STAGES else 'input',
            'failed_error_code':code}
