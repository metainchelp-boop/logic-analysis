"""Explicit, pinned installation of two saved-data exporters; never an app/API client.

The controller supplies the observed host source directory and pinned script bytes.
Preparing artifacts does not start jobs. Only install() changes system units, and
only the release controller may call it after approval. No env, keys or DB rows
are returned. The engine receives dedicated sanitized directories, not SQLite.

Namespace contract: the unprivileged reader sees the whole source directory RO.
A separate bounded root coordinator sees that directory RW, but the main DB is
a nested read-only mount. SQLite mode=ro/query_only may create/update its WAL/SHM
coordination files while a read transaction holds them for the reader. No source
SQL rows, main DB bytes or permissions are written. Immutable/nolock are not used.
See https://www.freedesktop.org/software/systemd/man/systemd.exec.html and
https://www.sqlite.org/wal.html#read_only_databases . Actual namespace support and
WAL permissions must pass the one-shot runs on the target host.
"""
from datetime import datetime, timezone
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat

STAGING = Path('/srv/metainc/ad-deploy-staging/saved-exports')
INSTALL = Path('/opt/metainc/naver-saved-exports')
UNITS = Path('/etc/systemd/system')
OUTPUTS = {'product': Path('/var/lib/metainc/naver-product-source'),
           'market': Path('/var/lib/metainc/naver-market-source')}
COMPANION = 'naver-saved-exports.override.yml'
SOURCE_ALIAS = '/run/naver-saved-source'
SCRIPTS = ('naver_product_export.py', 'naver_market_export.py')
COORDINATORS = {'product': 'naver_product_coordinate.py', 'market': 'naver_market_coordinate.py'}
INTERPRETER = 'python-export'
KINDS = ('product', 'market')
MAX_BUNDLE = 5 * 1024 * 1024
MAX_FILE = 256 * 1024
MAX_INTERPRETER = 32 * 1024 * 1024
ROOT_UID = 0
READER_GID = 10001
PROFILE_KEYS = frozenset({'ops_commit', 'source_directory', 'database_name',
                         'exporter_user', 'source_group', 'python_executable'})

# This is generated as an exact root-owned script, never a shell command or argv
# payload. Older systemd limits expansion of each Exec argument to PATH_MAX-1.
# The main DB must be a kernel-RO mount while only SQLite's coordination directory
# is writable. Source application data never passes through this process.
COORDINATOR_SOURCE = '''import grp,json,os,pwd,sqlite3,stat,subprocess,sys

def emit(code):
    print(json.dumps({'status':'failed','code':code},sort_keys=True,separators=(',',':')),flush=True)

def coordinate(database=DATABASE,reader=READER,*,connect=sqlite3.connect,run=subprocess.run):
    connection=None
    code=None
    started=False
    try:
        directory=os.path.dirname(database)
        initial=os.lstat(database)
        if (reader not in ('naver-product-export-reader.service','naver-market-export-reader.service') or
                not stat.S_ISDIR(os.lstat(directory).st_mode) or
                not stat.S_ISREG(os.lstat(database).st_mode) or
                not os.statvfs(database).f_flag & os.ST_RDONLY or
                os.statvfs(directory).f_flag & os.ST_RDONLY):
            raise ValueError()
        uid=pwd.getpwnam(EXPORTER_USER).pw_uid
        groups={READER_GID}
        if SOURCE_GROUP is not None:
            groups.add(grp.getgrnam(SOURCE_GROUP).gr_gid)
        if uid==0 or 0 in groups:
            raise ValueError()
        def readable_sidecars():
            for suffix in ('-wal','-shm'):
                try:
                    info=os.lstat(database+suffix)
                except FileNotFoundError:
                    continue
                if (not stat.S_ISREG(info.st_mode) or not (
                        info.st_mode & stat.S_IROTH or
                        info.st_uid==uid and info.st_mode & stat.S_IRUSR or
                        info.st_gid in groups and info.st_mode & stat.S_IRGRP)):
                    raise ValueError()
        readable_sidecars()
    except Exception:
        emit('COORDINATION_INVALID')
        return 1
    try:
        connection=connect('file:'+database+'?mode=ro',uri=True,timeout=1,isolation_level=None)
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA busy_timeout=1000')
        def authorize(action,arg1,arg2,db,trigger):
            if action==sqlite3.SQLITE_PRAGMA and arg1=='schema_version' and arg2 is None:
                return sqlite3.SQLITE_OK
            if action==sqlite3.SQLITE_TRANSACTION and arg1 in ('BEGIN','ROLLBACK'):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        connection.set_authorizer(authorize)
        connection.execute('BEGIN')
        connection.execute('PRAGMA schema_version').fetchone()
        readable_sidecars()
        current=os.lstat(database)
        if (not stat.S_ISREG(current.st_mode) or
                (current.st_dev,current.st_ino)!=(initial.st_dev,initial.st_ino)):
            raise ValueError()
    except Exception:
        code='COORDINATION_SOURCE_OPEN'
    if code is None:
        try:
            current=os.lstat(database)
            if (not stat.S_ISREG(current.st_mode) or
                    (current.st_dev,current.st_ino)!=(initial.st_dev,initial.st_ino)):
                raise ValueError()
            started=True
            result=run(['/usr/bin/systemctl','start',reader],stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=50,check=False)
            if result.returncode!=0:
                code='COORDINATION_READER_FAILED'
        except subprocess.TimeoutExpired:
            code='COORDINATION_TIMEOUT'
        except Exception:
            code='COORDINATION_READER_FAILED'
    if code is not None and started:
        try:
            result=run(['/usr/bin/systemctl','stop',reader],stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,check=False)
            if result.returncode!=0:
                emit('COORDINATION_READER_STOP_FAILED')
        except Exception:
            emit('COORDINATION_READER_STOP_FAILED')
    if connection is not None:
        try:
            connection.close()
        except Exception:
            code=code or 'COORDINATION_SOURCE_OPEN'
    if code is not None:
        emit(code)
        return 1
    return 0

if __name__=='__main__':
    sys.exit(coordinate())
'''


class ExportInstallInvalid(ValueError):
    """Fixed, non-sensitive codes only."""


def _fail(code):
    raise ExportInstallInvalid(code)


def _json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _path(value):
    # A deliberately narrow path alphabet avoids systemd %, :, $ and YAML escapes.
    if (not isinstance(value, str) or len(value) > 512 or
            re.fullmatch(r'/[A-Za-z0-9_./-]+', value) is None or
            str(Path(value)) != value or '..' in Path(value).parts):
        _fail('EXPORT_PATH')
    return Path(value)


def build_plan(*, ops_commit, source_directory, database_name, exporter_user,
               source_group, python_executable):
    if not isinstance(ops_commit, str) or re.fullmatch(r'[0-9a-f]{40}', ops_commit) is None:
        _fail('EXPORT_PIN')
    source = _path(source_directory)
    if source in (Path('/'), Path('/root'), Path('/home'), Path('/etc'), Path('/var'),
                  Path('/var/lib'), Path('/run'), Path('/srv'), Path('/opt')):
        _fail('EXPORT_SOURCE_SCOPE')
    if any(source == path or source in path.parents or path in source.parents
           for path in (STAGING, INSTALL, UNITS, *OUTPUTS.values())):
        _fail('EXPORT_SOURCE_SCOPE')
    if (not isinstance(database_name, str) or
            re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\.db', database_name) is None):
        _fail('EXPORT_DATABASE_NAME')
    if (not isinstance(exporter_user, str) or
            re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', exporter_user) is None or exporter_user == 'root'):
        _fail('EXPORT_IDENTITY')
    if (source_group is not None and (not isinstance(source_group, str) or
            re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', source_group) is None or source_group == 'root')):
        _fail('EXPORT_IDENTITY')
    if python_executable not in ('/usr/bin/python3', '/usr/local/bin/python3'):
        _fail('EXPORT_PYTHON')
    return {'ops_commit': ops_commit, 'source_directory': str(source),
            'database_name': database_name, 'exporter_user': exporter_user,
            'source_group': source_group, 'python_executable': python_executable}


def _plan(value):
    if not isinstance(value, dict) or set(value) != PROFILE_KEYS:
        _fail('EXPORT_PROFILE')
    return build_plan(**value)


def render_companion(plan):
    _plan(plan)
    # JSON is YAML 1.2; closed structure is easy to compare without a YAML parser.
    return _json({'services': {'naver-engine': {
        'environment': {'NAVER_ENGINE_PRODUCT_EXPORT_FILE': '/var/lib/naver-product-source/bundle.json',
                        'NAVER_ENGINE_MARKET_EXPORT_FILE': '/var/lib/naver-market-source/bundle.json'},
        'volumes': [{'type': 'bind', 'source': str(OUTPUTS[kind]),
                     'target': '/var/lib/naver-' + kind + '-source', 'read_only': True,
                     'bind': {'create_host_path': False}} for kind in KINDS]}}}) + b'\n'


def _coordinator_source(plan, kind):
    plan = _plan(plan)
    if kind not in KINDS:
        _fail('EXPORT_PROFILE')
    constants = {'DATABASE': SOURCE_ALIAS + '/' + plan['database_name'],
                 'READER': f'naver-{kind}-export-reader.service',
                 'EXPORTER_USER': plan['exporter_user'], 'SOURCE_GROUP': plan['source_group'],
                 'READER_GID': READER_GID}
    source = ''.join(name + '=' + repr(value) + '\n' for name, value in constants.items()) + COORDINATOR_SOURCE
    if '%' in source or '$' in source or '\x00' in source or '\r' in source or not source.isascii():
        _fail('EXPORT_PATH')
    return source


def _unit(plan, kind):
    python = INSTALL / plan['ops_commit'] / INTERPRETER
    code = INSTALL / plan['ops_commit'] / COORDINATORS[kind]
    return (f'[Unit]\nDescription=Bounded SQLite coordination for saved {kind} export\nAfter=local-fs.target\n\n'
        f'[Service]\nType=oneshot\nUser=root\nGroup={READER_GID}\n'
        f'WorkingDirectory=/\nExecStart={python} -I -B {code}\n'
        'UMask=0022\nTimeoutStartSec=65\nMemoryMax=64M\nTasksMax=16\n'
        'NoNewPrivileges=true\nCapabilityBoundingSet=\nPrivateNetwork=true\nPrivateTmp=true\n'
        'PrivateDevices=true\nProtectSystem=strict\nProtectHome=tmpfs\n'
        'ProtectKernelTunables=true\nProtectKernelModules=true\nProtectControlGroups=true\n'
        'RestrictAddressFamilies=AF_UNIX\n'
        f'BindPaths={plan["source_directory"]}:{SOURCE_ALIAS}:norbind\n'
        f'ReadWritePaths={SOURCE_ALIAS}\n'
        f'ReadOnlyPaths={SOURCE_ALIAS}/{plan["database_name"]} {INSTALL / plan["ops_commit"]}\n'
        'StandardOutput=journal\nStandardError=journal\n').encode()


def _reader_unit(plan, kind):
    code = INSTALL / plan['ops_commit'] / ('naver_' + kind + '_export.py')
    python = INSTALL / plan['ops_commit'] / INTERPRETER
    group = ('SupplementaryGroups=' + plan['source_group'] + '\n') if plan['source_group'] else ''
    return (f'[Unit]\nDescription=Bounded saved {kind} export for Naver reports\nAfter=local-fs.target\n'
        f'PartOf=naver-{kind}-export.service\n\n'
        f'[Service]\nType=oneshot\nUser={plan["exporter_user"]}\nGroup={READER_GID}\n{group}'
        f'ExecStartPre={python} -I -B -c "import os,sys,encodings,json,sqlite3,dataclasses,importlib,math;sys.exit(0 if '
        f"os.statvfs('{SOURCE_ALIAS}').f_flag & os.ST_RDONLY else 1)\"\n"
        f'WorkingDirectory=/\nExecStart={python} -I -B {code} '
        f'--database {SOURCE_ALIAS}/{plan["database_name"]} --output {OUTPUTS[kind]}/bundle.json\n'
        'UMask=0027\nTimeoutStartSec=45\nTimeoutStopSec=5\nKillMode=control-group\nMemoryMax=256M\nTasksMax=16\n'
        'NoNewPrivileges=true\nCapabilityBoundingSet=\nPrivateNetwork=true\nPrivateTmp=true\n'
        'PrivateDevices=true\nProtectSystem=strict\nProtectHome=tmpfs\n'
        'ProtectKernelTunables=true\nProtectKernelModules=true\nProtectControlGroups=true\n'
        'RestrictAddressFamilies=AF_UNIX\n'
        f'BindReadOnlyPaths={plan["source_directory"]}:{SOURCE_ALIAS}:norbind\n'
        f'ReadOnlyPaths={INSTALL / plan["ops_commit"]}\nReadWritePaths={OUTPUTS[kind]}\n'
        'StandardOutput=journal\nStandardError=journal\n').encode()


def _timer(kind):
    # These times follow the source's configured 08:30 daily analysis, not a claim
    # that every analysis/collection succeeded. Original source timestamps remain.
    minute = '30' if kind == 'product' else '35'
    return (f'[Unit]\nDescription=Daily saved {kind} export\n\n[Timer]\n'
        f'OnCalendar=*-*-* 10:{minute}:00 Asia/Seoul\nRandomizedDelaySec=60\nPersistent=true\n'
        f'Unit=naver-{kind}-export.service\n\n[Install]\nWantedBy=timers.target\n').encode()


def artifacts(plan, scripts, pins):
    plan = _plan(plan)
    if (not isinstance(scripts, dict) or set(scripts) != set(SCRIPTS) or
            not isinstance(pins, dict) or set(pins) != set(SCRIPTS)):
        _fail('EXPORT_PIN')
    # Validate pins before touching any host source path.
    for name in SCRIPTS:
        body = scripts[name]
        if (type(body) is not bytes or not 100 <= len(body) <= MAX_FILE or
                not isinstance(pins[name], str) or re.fullmatch('[0-9a-f]{64}', pins[name]) is None or
                _sha(body) != pins[name]):
            _fail('EXPORT_PIN')
    result = dict(scripts)
    result[COMPANION] = render_companion(plan)
    for kind in KINDS:
        result[COORDINATORS[kind]] = _coordinator_source(plan, kind).encode()
        result[f'naver-{kind}-export.service'] = _unit(plan, kind)
        result[f'naver-{kind}-export-reader.service'] = _reader_unit(plan, kind)
        result[f'naver-{kind}-export.timer'] = _timer(kind)
    return result


def _regular(path, *, maximum=MAX_FILE, owner=None, mode=None, group=None):
    owner = ROOT_UID if owner is None else owner
    if path.resolve() != path:
        _fail('EXPORT_SYMLINK')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or
                info.st_mode & 0o022 or info.st_size > maximum or
                mode is not None and stat.S_IMODE(info.st_mode) != mode or
                group is not None and info.st_gid != group):
            _fail('EXPORT_FILE_POLICY')
        chunks=[]; size=0
        while size <= maximum:
            chunk=os.read(fd,min(65536,maximum+1-size))
            if not chunk:break
            chunks.append(chunk);size+=len(chunk)
        after=os.fstat(fd)
        if size > maximum or (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
            _fail('EXPORT_FILE_CHANGED')
        return b''.join(chunks)
    finally:
        os.close(fd)


def _directory(path, *, owner=None, mode=None):
    owner = ROOT_UID if owner is None else owner
    if path.resolve() != path:
        _fail('EXPORT_SYMLINK')
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022 or
            mode is not None and stat.S_IMODE(info.st_mode) != mode):
        _fail('EXPORT_DIRECTORY_POLICY')
    return info


def _file_identity(info):
    return {'device': info.st_dev, 'inode': info.st_ino, 'size': info.st_size,
            'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'uid': info.st_uid, 'gid': info.st_gid,
            'mode': stat.S_IMODE(info.st_mode), 'links': info.st_nlink}


def _valid_file_identity(value):
    keys = {'device', 'inode', 'size', 'mtime_ns', 'ctime_ns', 'uid', 'gid', 'mode', 'links'}
    return (isinstance(value, dict) and set(value) == keys and
            all(type(item) is int and item >= 0 for item in value.values()) and
            value['size'] <= MAX_INTERPRETER and value['mode'] <= 0o7777 and value['links'] == 1)


def _python_target(plan):
    """Permit the configured system alias, never an arbitrary symlink chain."""
    alias = _path(plan['python_executable'])
    for directory in (alias.parent, *alias.parent.parents):
        _directory(directory)
    info = alias.lstat()
    if info.st_uid != ROOT_UID:
        _fail('EXPORT_FILE_POLICY')
    if stat.S_ISLNK(info.st_mode):
        link = os.readlink(alias)
        target = Path(link) if link.startswith('/') else alias.parent / link
        if (target.parent != alias.parent or
                re.fullmatch(r'python3\.[0-9]{1,2}', target.name) is None):
            _fail('EXPORT_SYMLINK')
    else:
        target = alias
    if target.resolve() != target or not stat.S_ISREG(target.lstat().st_mode):
        _fail('EXPORT_SYMLINK')
    return target


def _binary(path, *, mode=None, group=None):
    """Read only a trusted bounded ELF using one fd and pre/post inode checks."""
    _directory(path.parent)
    if path.resolve() != path:
        _fail('EXPORT_SYMLINK')
    before = _file_identity(path.lstat())
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        identity = _file_identity(info)
        if (not stat.S_ISREG(info.st_mode) or identity != before or
                info.st_uid != ROOT_UID or info.st_mode & 0o6022 or info.st_nlink != 1 or
                not 4 <= info.st_size <= MAX_INTERPRETER or
                mode is not None and stat.S_IMODE(info.st_mode) != mode or
                group is not None and info.st_gid != group):
            _fail('EXPORT_FILE_POLICY')
        chunks = []; size = 0
        while size <= MAX_INTERPRETER:
            chunk = os.read(fd, min(65536, MAX_INTERPRETER + 1 - size))
            if not chunk: break
            chunks.append(chunk); size += len(chunk)
        if (size > MAX_INTERPRETER or size != info.st_size or
                identity != _file_identity(os.fstat(fd)) or identity != _file_identity(path.lstat())):
            _fail('EXPORT_FILE_CHANGED')
        body = b''.join(chunks)
        if not body.startswith(b'\x7fELF'):
            _fail('EXPORT_FILE_POLICY')
        return body, identity
    finally:
        os.close(fd)


def _python_snapshot(plan):
    target = _python_target(plan)
    body, identity = _binary(target)
    # Alias retargeting during the read must not silently change provenance.
    if _python_target(plan) != target:
        _fail('EXPORT_FILE_CHANGED')
    return body, {'source_path': str(target), 'source_identity': identity, 'sha256': _sha(body)}


def _source_identity(plan):
    directory = _path(plan['source_directory'])
    if directory.resolve() != directory:
        _fail('EXPORT_SOURCE_SYMLINK')
    parent = directory.lstat(); source = directory / plan['database_name']; info = source.lstat()
    if not stat.S_ISDIR(parent.st_mode) or not stat.S_ISREG(info.st_mode) or source.resolve() != source:
        _fail('EXPORT_SOURCE_PATH')
    for suffix in ('-wal', '-shm'):
        path = Path(str(source) + suffix)
        if path.exists() or path.is_symlink():
            if path.resolve() != path or not stat.S_ISREG(path.lstat().st_mode):
                _fail('EXPORT_SOURCE_PATH')
    # No file content/hash, environment, schema repair or SQLite open here.
    return {'directory_device': parent.st_dev, 'directory_inode': parent.st_ino,
            'database_device': info.st_dev, 'database_inode': info.st_ino}


def _identity(plan):
    user = pwd.getpwnam(plan['exporter_user'])
    if user.pw_uid == 0:
        _fail('EXPORT_IDENTITY')
    grp.getgrgid(READER_GID)
    source_gid = grp.getgrnam(plan['source_group']).gr_gid if plan['source_group'] is not None else None
    if source_gid == 0:
        _fail('EXPORT_IDENTITY')
    return {'exporter_uid': user.pw_uid, 'reader_gid': READER_GID, 'source_gid': source_gid}


def _write_new(path, body, mode, group=None):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    created = None
    try:
        created = os.fstat(fd)
        if group is not None:
            os.fchown(fd, ROOT_UID, group)
        os.fchmod(fd,mode)
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())
        identity = _file_identity(os.fstat(fd))
        _fsync_directory(path.parent)
        return identity
    except BaseException:
        # A failed write owns only the inode created by this fd. Never remove a
        # replacement at the same name, or mask the original failure with cleanup.
        try:
            current = path.lstat()
            if (created is not None and stat.S_ISREG(current.st_mode) and
                    (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino)):
                path.unlink()
        except OSError:
            pass
        raise
    finally:
        os.close(fd)


def _fsync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def prepare(plan, *, scripts, pins, operation_id):
    """Stage root-owned, exact pinned artifacts; no unit/engine/source mutation."""
    content = artifacts(plan, scripts, pins)
    if not isinstance(operation_id, str) or re.fullmatch('[0-9a-f]{32}', operation_id) is None:
        _fail('EXPORT_OPERATION')
    if os.geteuid() != ROOT_UID:
        _fail('EXPORT_ROOT_REQUIRED')
    plan = _plan(plan); identity = _identity(plan); source = _source_identity(plan)
    binary, interpreter = _python_snapshot(plan)
    _directory(STAGING, mode=0o700)
    folder = STAGING / operation_id
    folder.mkdir(mode=0o700)
    _fsync_directory(STAGING)
    for name, body in content.items():
        _write_new(folder / name, body, 0o644)
    staged_identity = _write_new(folder / INTERPRETER, binary, 0o600)
    staged_body, reopened_identity = _binary(folder / INTERPRETER, mode=0o600)
    if staged_identity != reopened_identity or staged_body != binary:
        _fail('EXPORT_PREPARED_CHANGED')
    content[INTERPRETER] = binary
    receipt = {'version': 4, 'operation_id': operation_id, 'plan': plan,
               'plan_sha256': _sha(_json(plan)), 'source_identity': source,
               'runtime_identity': identity,
               'manifest': {name: _sha(body) for name, body in sorted(content.items())},
               'companion_sha256': _sha(content[COMPANION]),
               'interpreter': {**interpreter, 'staged_identity': staged_identity}}
    _write_new(folder / 'prepared.json', _json(receipt), 0o600)
    return receipt


def _prepared(receipt):
    if (not isinstance(receipt, dict) or set(receipt) != {'version', 'operation_id', 'plan', 'plan_sha256',
            'source_identity', 'runtime_identity', 'manifest', 'companion_sha256', 'interpreter'} or
            type(receipt['version']) is not int or receipt['version'] != 4 or
            not isinstance(receipt['operation_id'], str) or re.fullmatch('[0-9a-f]{32}', receipt['operation_id']) is None):
        _fail('EXPORT_RECEIPT')
    plan = _plan(receipt['plan'])
    folder = STAGING / receipt['operation_id']; _directory(STAGING, mode=0o700); _directory(folder, mode=0o700)
    if _regular(folder / 'prepared.json', mode=0o600) != _json(receipt):
        _fail('EXPORT_RECEIPT')
    names = set(SCRIPTS) | set(COORDINATORS.values()) | {COMPANION, INTERPRETER} | {f'naver-{kind}-export.{suffix}' for kind in KINDS for suffix in ('service', 'timer')}
    names.update(f'naver-{kind}-export-reader.service' for kind in KINDS)
    if not isinstance(receipt['manifest'], dict) or set(receipt['manifest']) != names:
        _fail('EXPORT_RECEIPT')
    interpreter = receipt['interpreter']
    if (not isinstance(interpreter, dict) or set(interpreter) != {'source_path', 'source_identity', 'staged_identity', 'sha256'} or
            not _valid_file_identity(interpreter['source_identity']) or not _valid_file_identity(interpreter['staged_identity']) or
            not isinstance(interpreter['sha256'], str) or re.fullmatch('[0-9a-f]{64}', interpreter['sha256']) is None):
        _fail('EXPORT_RECEIPT')
    _path(interpreter['source_path'])
    content = {name: _regular(folder / name, mode=0o644) for name in names if name != INTERPRETER}
    binary, staged_identity = _binary(folder / INTERPRETER, mode=0o600)
    content[INTERPRETER] = binary
    if staged_identity != interpreter['staged_identity'] or _sha(binary) != interpreter['sha256']:
        _fail('EXPORT_PREPARED_CHANGED')
    if ({name: _sha(body) for name, body in content.items()} != receipt['manifest'] or
            receipt['plan_sha256'] != _sha(_json(plan)) or
            receipt['companion_sha256'] != _sha(render_companion(plan)) or
            content[COMPANION] != render_companion(plan) or
            any(content[COORDINATORS[kind]] != _coordinator_source(plan, kind).encode() or
                content[f'naver-{kind}-export.service'] != _unit(plan, kind) or
                content[f'naver-{kind}-export-reader.service'] != _reader_unit(plan, kind) or
                content[f'naver-{kind}-export.timer'] != _timer(kind) for kind in KINDS)):
        _fail('EXPORT_PREPARED_CHANGED')
    return plan, folder, content


def _command(command, args):
    try:
        return command(args)
    except Exception:
        _fail('EXPORT_COMMAND_FAILED')


def _journal(folder, receipt, state):
    # Replace only our exact journal. This is private recovery metadata, not data.
    path = folder / 'installed.json'
    if path.exists():
        old = _regular(path, mode=0o600)
        if json.loads(old).get('operation_id') != receipt['operation_id']:
            _fail('EXPORT_JOURNAL')
    temporary = folder / 'installed.pending'
    _write_new(temporary, _json(state), 0o600)
    os.replace(temporary, path)
    _fsync_directory(folder)


def install(receipt, *, command):
    """Apply coordinator+RO reader; timers start only after both export runs."""
    if os.geteuid() != ROOT_UID:
        _fail('EXPORT_ROOT_REQUIRED')
    plan, folder, content = _prepared(receipt)
    if (folder / 'installed.json').exists():
        _fail('EXPORT_ALREADY_ATTEMPTED')
    if _source_identity(plan) != receipt['source_identity']:
        _fail('EXPORT_SOURCE_CHANGED')
    identity = _identity(plan)
    if identity != receipt['runtime_identity']:
        _fail('EXPORT_IDENTITY_CHANGED')
    _, interpreter = _python_snapshot(plan)
    if interpreter != {key: receipt['interpreter'][key] for key in ('source_path', 'source_identity', 'sha256')}:
        _fail('EXPORT_PREPARED_CHANGED')
    uid = identity['exporter_uid']; _directory(UNITS); _directory(INSTALL)
    script_dir = INSTALL / plan['ops_commit']
    units = [name for name in content if name.endswith(('.service', '.timer'))]
    if script_dir.exists() or any((UNITS / name).exists() or (UNITS / name).is_symlink() for name in units):
        _fail('EXPORT_INSTALL_CONFLICT')
    for output in OUTPUTS.values():
        if output.exists() or output.is_symlink():
            info = _directory(output, owner=uid, mode=0o750)
            names = list(output.iterdir())
            if info.st_gid != READER_GID or any(path.name != 'bundle.json' for path in names):
                _fail('EXPORT_OUTPUT_CONFLICT')
            for path in names:
                _regular(path, maximum=MAX_BUNDLE, owner=uid, mode=0o640,group=READER_GID)
    state = {'version': 1, 'operation_id': receipt['operation_id'], 'state': 'installing',
             'created_files': [], 'created_directories': [], 'timers_enabled': False,
             'engine_verified': False, 'interpreter_identity': None}
    _journal(folder, receipt, state)
    try:
        state['created_directories'].append(str(script_dir)); _journal(folder, receipt, state)
        script_dir.mkdir(mode=0o755);os.chmod(script_dir,0o755);_fsync_directory(INSTALL)
        path = script_dir / INTERPRETER
        state['created_files'].append(str(path)); _journal(folder, receipt, state)
        state['interpreter_identity'] = _write_new(path, content[INTERPRETER], 0o550, READER_GID)
        _journal(folder, receipt, state)
        actual, installed_identity = _binary(path, mode=0o550, group=READER_GID)
        if installed_identity != state['interpreter_identity'] or actual != content[INTERPRETER]:
            _fail('EXPORT_INSTALLED_CHANGED')
        for name in (*SCRIPTS, *COORDINATORS.values()):
            path = script_dir / name
            state['created_files'].append(str(path)); _journal(folder, receipt, state)
            _write_new(path, content[name], 0o644)
        for output in OUTPUTS.values():
            if not output.exists():
                state['created_directories'].append(str(output)); _journal(folder, receipt, state)
                output.mkdir(mode=0o750); os.chown(output, uid, READER_GID);os.chmod(output,0o750);_fsync_directory(output.parent)
        for name in units:
            path = UNITS / name
            state['created_files'].append(str(path)); _journal(folder, receipt, state)
            _write_new(path, content[name], 0o644)
        _command(command, ['systemd-analyze', 'verify', *[str(UNITS / name) for name in sorted(units)]])
        _command(command, ['systemctl', 'daemon-reload'])
        for kind in KINDS:
            _command(command, ['systemctl', 'start', f'naver-{kind}-export.service'])
        verified = verify(receipt, command=command, require_timers=False)
        for kind in KINDS:
            _command(command, ['systemctl', 'enable', '--now', f'naver-{kind}-export.timer'])
        state.update(state='installed', timers_enabled=True, sources=verified['sources'])
        _journal(folder, receipt, state)
        return {**verified, 'state': 'installed', 'timers_enabled': True}
    except BaseException:
        # Keep journal and exact created paths for explicit paired release rollback.
        state['state'] = 'failed'; _journal(folder, receipt, state)
        raise


def verify(receipt, *, command, require_timers=True, now=None):
    plan, folder, content = _prepared(receipt)
    if _source_identity(plan) != receipt['source_identity'] or _identity(plan) != receipt['runtime_identity']:
        _fail('EXPORT_SOURCE_CHANGED')
    state = json.loads(_regular(folder / 'installed.json', mode=0o600))
    for name, body in content.items():
        if name == COMPANION:
            continue
        path = INSTALL / plan['ops_commit'] / name if name in (*SCRIPTS, *COORDINATORS.values(), INTERPRETER) else UNITS / name
        if name == INTERPRETER:
            actual, identity = _binary(path, mode=0o550, group=READER_GID)
            if identity != state.get('interpreter_identity') or actual != body:
                _fail('EXPORT_INSTALLED_CHANGED')
        elif _regular(path, mode=0o644) != body:
            _fail('EXPORT_INSTALLED_CHANGED')
    for kind in KINDS:
        for unit in (f'naver-{kind}-export.service', f'naver-{kind}-export-reader.service'):
            result = _command(command, ['systemctl', 'show', unit,
                                       '--property=Result', '--property=ExecMainStatus'])
            if isinstance(result, bytes): result = result.decode('ascii')
            if set(str(result).splitlines()) != {'Result=success', 'ExecMainStatus=0'}:
                _fail('EXPORT_RUN_NOT_VERIFIED')
        if require_timers:
            _command(command, ['systemctl', 'is-enabled', f'naver-{kind}-export.timer'])
            _command(command, ['systemctl', 'is-active', f'naver-{kind}-export.timer'])
    # Pass user explicitly into summary; no ambient source/env lookup.
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.utcoffset() is None:
        _fail('EXPORT_TIME')
    sources = {kind: _bundle_summary_for_user(kind, now, plan['exporter_user']) for kind in KINDS}
    return {'version': 1, 'operation_id': receipt['operation_id'], 'state': 'verified',
            'sources': sources, 'timers_enabled': bool(require_timers),
            'engine_verified': False, 'source_writes': True, 'database_writes': False,
            'coordination_files_may_change': True, 'network_calls': 0}


def _bundle_summary_for_user(kind, now, user):
    # Kept call-local: an installer may inspect two independent releases.
    path = OUTPUTS[kind] / 'bundle.json'
    uid=pwd.getpwnam(user).pw_uid
    if _directory(OUTPUTS[kind],owner=uid,mode=0o750).st_gid!=READER_GID:
        _fail('EXPORT_DIRECTORY_POLICY')
    body = _regular(path, maximum=MAX_BUNDLE, owner=uid, mode=0o640,group=READER_GID)
    try:
        value = json.loads(body)
        if (not isinstance(value, dict) or set(value) != {'schema_version', 'complete', 'exported_at', 'stores'} or
                type(value['schema_version']) is not int or value['schema_version'] != 1 or
                value['complete'] is not True or not isinstance(value['stores'], list) or len(value['stores']) > 10000):
            _fail('EXPORT_BUNDLE_INVALID')
        at = datetime.fromisoformat(value['exported_at'])
        if at.utcoffset() is None or not -300 <= (now-at).total_seconds() <= 30*3600:
            _fail('EXPORT_BUNDLE_STALE')
        field = 'products' if kind == 'product' else 'cohorts'
        if any(not isinstance(row, dict) or not isinstance(row.get(field), list) for row in value['stores']):
            _fail('EXPORT_BUNDLE_INVALID')
        return {'status': 'ok', 'stores': len(value['stores']),
                field: sum(len(row[field]) for row in value['stores']),
                'bytes': len(body), 'exported_at': at.isoformat(), 'sha256': _sha(body)}
    except (ValueError, TypeError, KeyError, OverflowError):
        _fail('EXPORT_BUNDLE_INVALID')


def _rollback_state(receipt):
    if os.geteuid() != ROOT_UID:
        _fail('EXPORT_ROOT_REQUIRED')
    plan, folder, content = _prepared(receipt)
    state = json.loads(_regular(folder / 'installed.json', mode=0o600))
    allowed = {str(INSTALL / plan['ops_commit'] / name): content[name] for name in (*SCRIPTS, *COORDINATORS.values(), INTERPRETER)}
    allowed.update({str(UNITS / name): body for name, body in content.items() if name.endswith(('.service', '.timer'))})
    if (state.get('operation_id') != receipt['operation_id'] or not isinstance(state.get('created_files'), list) or
            len(state['created_files']) != len(set(state['created_files'])) or any(path not in allowed for path in state['created_files'])):
        _fail('EXPORT_JOURNAL')
    # Never delete unknown drift. Complete this preflight before stopping anything.
    for name in state['created_files']:
        path = Path(name)
        if path.exists() or path.is_symlink():
            if path.name == INTERPRETER:
                actual, identity = _binary(path, mode=0o550, group=READER_GID)
                if identity != state.get('interpreter_identity') or actual != allowed[name]:
                    _fail('EXPORT_ROLLBACK_DRIFT')
            elif _regular(path, mode=0o644) != allowed[name]:
                _fail('EXPORT_ROLLBACK_DRIFT')
    return plan, folder, state


def validate_rollback(receipt):
    """Read-only exact-artifact preflight; never stop services or remove files."""
    _rollback_state(receipt)


def rollback(receipt, *, command):
    """Stop only these jobs and remove exact installed units/scripts; keep bundles."""
    plan, folder, state = _rollback_state(receipt)
    for kind in KINDS:
        if str(UNITS / f'naver-{kind}-export.timer') in state['created_files'] and (UNITS / f'naver-{kind}-export.timer').exists():
            _command(command, ['systemctl', 'disable', '--now', f'naver-{kind}-export.timer'])
        if str(UNITS / f'naver-{kind}-export.service') in state['created_files'] and (UNITS / f'naver-{kind}-export.service').exists():
            _command(command, ['systemctl', 'stop', f'naver-{kind}-export.service'])
        if str(UNITS / f'naver-{kind}-export-reader.service') in state['created_files'] and (UNITS / f'naver-{kind}-export-reader.service').exists():
            _command(command, ['systemctl', 'stop', f'naver-{kind}-export-reader.service'])
    for name in reversed(state['created_files']):
        Path(name).unlink(missing_ok=True)
    script_dir = INSTALL / plan['ops_commit']
    if str(script_dir) in state.get('created_directories', ()) and script_dir.exists():
        script_dir.rmdir()
    if any(Path(name).parent == UNITS for name in state['created_files']):
        _command(command, ['systemctl', 'daemon-reload'])
    state['state'] = 'rolled_back'; state['timers_enabled'] = False
    _journal(folder, receipt, state)
    return {'version': 1, 'operation_id': receipt['operation_id'], 'state': 'rolled_back',
            'source_untouched': False, 'database_writes': False,
            'coordination_files_may_change': True, 'export_bundles_preserved': True}
