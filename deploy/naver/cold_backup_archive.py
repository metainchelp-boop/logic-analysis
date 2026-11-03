"""Losslessly archive one of four fixed, already-cold deployment backups.

This does not open SQLite, inspect live database files, stop containers, or prune
images. The original byte manifest is retained verbatim. Publication means an
exclusive, fsynced archive manifest in a private archive directory; original
files are removed only after that publication and a complete decompression
verification. Interrupted partial archives are retained for operator review.
There is deliberately no production restore command or automatic retry.
"""
import contextlib
from collections import namedtuple
from types import MappingProxyType
import fcntl
import gzip
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
import zlib

BACKUP_PARENT = '/var/backups/metainc/naver-deploy-db'
ARCHIVE_PARENT = '/var/backups/metainc/naver-cold-archives'
BACKUP_NAME = '20261102T170022Z-c44a66393340'
ARCHIVE_NAME = BACKUP_NAME + '-v1'
LOCK_PARENT = '/var/lib/metainc/naver-deploy'
CONFIRM = 'ARCHIVE_C44_COLD_BACKUP_LOSSLESSLY'
SCOPE = 'c44-cold-backup-lossless-v1'
Profile = namedtuple('Profile', 'scope backup archive confirm gzip_level', defaults=(1,))
PROFILES = MappingProxyType({
    SCOPE: Profile(SCOPE, BACKUP_NAME, ARCHIVE_NAME, CONFIRM),
    'a377-cold-backup-lossless-v1': Profile(
        'a377-cold-backup-lossless-v1', '20261102T185748Z-a3770876f746',
        '20261102T185748Z-a3770876f746-v1', 'ARCHIVE_A377_COLD_BACKUP_LOSSLESSLY'),
    'bb151-cold-backup-lossless-v1': Profile(
        'bb151-cold-backup-lossless-v1', '20261102T205647Z-bb151c2a483a',
        '20261102T205647Z-bb151c2a483a-v1', 'ARCHIVE_BB151_COLD_BACKUP_LOSSLESSLY'),
    'd633-cold-backup-lossless-v1': Profile(
        'd633-cold-backup-lossless-v1', '20261102T230515Z-d633ff4450bb',
        '20261102T230515Z-d633ff4450bb-v1', 'ARCHIVE_D633_COLD_BACKUP_LOSSLESSLY'),
    'd633-cold-backup-lossless-gzip6-v1': Profile(
        'd633-cold-backup-lossless-gzip6-v1', '20261102T230515Z-d633ff4450bb',
        '20261102T230515Z-d633ff4450bb-gzip6-v1', 'ARCHIVE_D633_COLD_BACKUP_GZIP6_LOSSLESSLY', 6),
})
ROOT_UID = 0
ROOT_GID = 0
FILES = frozenset(('engine.db', 'engine.db-wal', 'engine.db-shm', 'engine.db-journal'))
SHA = re.compile(r'[0-9a-f]{64}\Z')
DOCKER = ('/usr/bin/docker', '--host=unix:///var/run/docker.sock')
INSPECT_FORMAT = ('{"id":{{json .Id}},"image":{{json .Image}},'
                  '"running":{{json .State.Running}},"pid":{{json .State.Pid}},'
                  '"started":{{json .State.StartedAt}},"restarts":{{json .RestartCount}}}')
CHUNK = 1024 * 1024
MAX_SOURCE = 16 * 1024 ** 3
MAX_ARCHIVE = 4 * 1024 ** 3
RESERVE = 512 * 1024 ** 2
MIN_FREE_AFTER = 5 * 1024 ** 3
OVERHEAD = 1024 * 1024
TIME_BUDGET = 600
REASONS = frozenset(('PLAN_READY', 'ARCHIVED', 'INPUT_REFUSED', 'NOT_ROOT',
    'LOCKED', 'PATH_REFUSED', 'SOURCE_REFUSED', 'SOURCE_CHANGED', 'HASH_MISMATCH',
    'SNAPSHOT_REFUSED', 'DOCKER_READ_FAILED', 'PLAN_MISMATCH', 'SPACE_REFUSED',
    'ARCHIVE_EXISTS', 'ARCHIVE_REFUSED', 'ARCHIVE_VERIFY_FAILED', 'TIME_LIMIT',
    'PROTECTED_CHANGED', 'INTERNAL_ERROR'))
NUMBERS = ('source_files', 'source_bytes', 'source_allocated_bytes',
           'compressed_bytes', 'archive_budget_bytes', 'free_before_bytes',
           'projected_free_bytes', 'free_after_bytes', 'removed_files',
           'containers', 'images')
BOOLEANS = ('capacity_ok', 'archive_started', 'archive_published',
            'archive_verified', 'cleanup_started', 'cleanup_complete',
            'protected_unchanged')
HASHES = ('plan_sha256', 'source_manifest_sha256', 'archive_manifest_sha256',
          'protected_sha256')


class Refused(Exception):
    pass


def profile_for(scope=SCOPE):
    if type(scope) is not str or scope not in PROFILES:
        raise Refused('INPUT_REFUSED')
    return PROFILES[scope]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def receipt(mode, scope=SCOPE):
    return dict(version=1, scope=profile_for(scope).scope, mode=mode if mode in ('plan', 'apply') else 'invalid',
                status='refused', reason='INTERNAL_ERROR',
                **{key: None for key in NUMBERS + HASHES},
                **{key: False for key in BOOLEANS},
                database_opened=False, services_changed=False)


def validate_report(value, expected_scope=None):
    if type(value) is not dict or set(value) != set(receipt('plan')):
        raise Refused('ARCHIVE_REFUSED')
    if (type(value['version']) is not int or value['version'] != 1 or
            type(value['scope']) is not str or value['scope'] not in PROFILES or
            value['mode'] not in ('plan', 'apply', 'invalid') or
            value['status'] not in ('planned', 'applied', 'refused') or
            value['reason'] not in REASONS):
        raise Refused('ARCHIVE_REFUSED')
    if expected_scope is not None and value['scope'] != profile_for(expected_scope).scope:
        raise Refused('ARCHIVE_REFUSED')
    for key in NUMBERS:
        if value[key] is not None and (type(value[key]) is not int or not 0 <= value[key] < 2 ** 63):
            raise Refused('ARCHIVE_REFUSED')
    for key in HASHES:
        if value[key] is not None and (type(value[key]) is not str or not SHA.fullmatch(value[key])):
            raise Refused('ARCHIVE_REFUSED')
    for key in BOOLEANS + ('database_opened', 'services_changed'):
        if type(value[key]) is not bool:
            raise Refused('ARCHIVE_REFUSED')
    if value['database_opened'] or value['services_changed']:
        raise Refused('ARCHIVE_REFUSED')
    if value['archive_verified'] and not value['archive_published']:
        raise Refused('ARCHIVE_REFUSED')
    if value['cleanup_started'] and not value['archive_verified']:
        raise Refused('ARCHIVE_REFUSED')
    if value['status'] == 'planned' and (value['mode'] != 'plan' or value['reason'] != 'PLAN_READY' or
            not value['plan_sha256'] or value['archive_started'] or not value['protected_unchanged']):
        raise Refused('ARCHIVE_REFUSED')
    if value['status'] == 'applied' and (value['mode'] != 'apply' or value['reason'] != 'ARCHIVED' or
            not all(value[k] for k in BOOLEANS) or value['removed_files'] != value['source_files'] + 1):
        raise Refused('ARCHIVE_REFUSED')
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refused('SOURCE_REFUSED')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        raise Refused('SOURCE_REFUSED') from None


def identity(info):
    return dict(device=info.st_dev, inode=info.st_ino, mode=stat.S_IMODE(info.st_mode),
                uid=info.st_uid, gid=info.st_gid, size=info.st_size, links=info.st_nlink,
                mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
                allocated_bytes=info.st_blocks * 512)


def same(fd, expected):
    if identity(os.fstat(fd)) != expected:
        raise Refused('SOURCE_CHANGED')


def check_dir(fd, private=False):
    info = os.fstat(fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, ROOT_UID) or
            info.st_mode & 0o022 or (private and stat.S_IMODE(info.st_mode) != 0o700)):
        raise Refused('PATH_REFUSED')


@contextlib.contextmanager
def directory(path, private=False):
    """Pin every absolute ancestor without following symlinks."""
    if not path.startswith('/') or any(x in ('', '.', '..') for x in path.split('/')[1:]):
        raise Refused('PATH_REFUSED')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        try:
            for part in path.split('/')[1:]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = child
                check_dir(fd)
            check_dir(fd, private)
        except OSError:
            raise Refused('PATH_REFUSED') from None
        yield fd
    finally:
        os.close(fd)


def open_file(parent, name, manifest=False):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                info.st_uid not in (ROOT_UID, 10001) or stat.S_IMODE(info.st_mode) not in (0o600, 0o640, 0o644) or
                (manifest and (info.st_uid != ROOT_UID or stat.S_IMODE(info.st_mode) != 0o600))):
            raise Refused('SOURCE_REFUSED')
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_small(fd, maximum=65536):
    data = os.read(fd, maximum + 1)
    if len(data) > maximum:
        raise Refused('SOURCE_REFUSED')
    return data


class Budget:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.end = clock() + TIME_BUDGET

    def check(self):
        if self.clock() > self.end:
            raise Refused('TIME_LIMIT')


class Sink:
    def __init__(self, budget, fd=None, free=None, maximum=MAX_ARCHIVE):
        self.size = 0
        self.hash = hashlib.sha256()
        self.budget, self.fd, self.free, self.maximum = budget, fd, free, maximum

    def write(self, data):
        self.budget.check()
        self.size += len(data)
        if self.size > self.maximum or (self.free is not None and self.free() < RESERVE + len(data)):
            raise Refused('SPACE_REFUSED')
        self.hash.update(data)
        if self.fd is not None:
            view = memoryview(data)
            while view:
                count = os.write(self.fd, view)
                if count <= 0:
                    raise Refused('ARCHIVE_REFUSED')
                view = view[count:]
        return len(data)

    def flush(self):
        if self.fd is not None:
            os.fsync(self.fd)


def compress(fd, budget, sink, *, level=1):
    os.lseek(fd, 0, os.SEEK_SET)
    raw_hash, raw_size = hashlib.sha256(), 0
    with gzip.GzipFile(filename='', mode='wb', fileobj=sink, compresslevel=level, mtime=0) as output:
        while True:
            budget.check()
            chunk = os.read(fd, CHUNK)
            if not chunk:
                break
            raw_size += len(chunk)
            if raw_size > MAX_SOURCE:
                raise Refused('SOURCE_REFUSED')
            raw_hash.update(chunk)
            output.write(chunk)
    sink.flush()
    return dict(size=raw_size, sha256=raw_hash.hexdigest(),
                gzip_size=sink.size, gzip_sha256=sink.hash.hexdigest())


def run(command):
    return subprocess.run(command, capture_output=True, timeout=30,
        env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root',
             'LANG': 'C.UTF-8', 'DOCKER_CONFIG': '/var/empty'})


def snapshot(runner=run):
    def read(args):
        result = runner((*DOCKER, *args))
        if result.returncode or len(result.stdout) > 1048576:
            raise Refused('DOCKER_READ_FAILED')
        return result.stdout.decode('utf-8').splitlines()
    try:
        ids = read(('ps', '-aq', '--no-trunc'))
        if len(ids) != 5 or len(set(ids)) != 5 or any(not SHA.fullmatch(v) for v in ids):
            raise Refused('SNAPSHOT_REFUSED')
        rows = read(('inspect', '--type=container', '--format', INSPECT_FORMAT, *sorted(ids)))
        containers = [strict_json(v) for v in rows]
        if len(containers) != 5:
            raise Refused('SNAPSHOT_REFUSED')
        for row in containers:
            if (type(row) is not dict or set(row) != {'id', 'image', 'running', 'pid', 'started', 'restarts'} or
                    row['id'] not in ids or not isinstance(row['image'], str) or
                    not re.fullmatch(r'sha256:[0-9a-f]{64}', row['image']) or
                    type(row['running']) is not bool or
                    any(type(row[k]) is not int or not 0 <= row[k] <= 2 ** 31 for k in ('pid', 'restarts')) or
                    type(row['started']) is not str or not re.fullmatch(r'[0-9]{4}-[0-9TZ:.+-]{10,40}', row['started'])):
                raise Refused('SNAPSHOT_REFUSED')
        if set(row['id'] for row in containers) != set(ids):
            raise Refused('SNAPSHOT_REFUSED')
        images = sorted(set(read(('image', 'ls', '-aq', '--no-trunc'))))
        if not images or len(images) > 4096 or any(not re.fullmatch(r'sha256:[0-9a-f]{64}', v) for v in images):
            raise Refused('SNAPSHOT_REFUSED')
        if not set(row['image'] for row in containers).issubset(images):
            raise Refused('SNAPSHOT_REFUSED')
        return dict(containers=sorted(containers, key=lambda row: row['id']), images=images)
    except Refused:
        raise
    except Exception:
        raise Refused('SNAPSHOT_REFUSED') from None


@contextlib.contextmanager
def source(scope=SCOPE):
    profile = profile_for(scope)
    with directory(BACKUP_PARENT) as parent:
        fd = os.open(profile.backup, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        handles = {}
        try:
            check_dir(fd, True)
            folder = identity(os.fstat(fd))
            if folder['device'] != os.fstat(parent).st_dev:
                raise Refused('SOURCE_REFUSED')
            manifest_fd = open_file(fd, 'manifest.json', True)
            handles['manifest.json'] = manifest_fd
            manifest_identity = identity(os.fstat(manifest_fd))
            raw = read_small(manifest_fd)
            manifest = strict_json(raw)
            if (type(manifest) is not dict or not manifest or 'engine.db' not in manifest or
                    not set(manifest).issubset(FILES) or set(os.listdir(fd)) != set(manifest) | {'manifest.json'}):
                raise Refused('SOURCE_REFUSED')
            identities = {'manifest.json': manifest_identity}
            for name, entry in sorted(manifest.items()):
                if (type(entry) is not dict or set(entry) != {'size', 'sha256'} or
                        type(entry['size']) is not int or not 0 <= entry['size'] <= MAX_SOURCE or
                        type(entry['sha256']) is not str or not SHA.fullmatch(entry['sha256'])):
                    raise Refused('SOURCE_REFUSED')
                handles[name] = open_file(fd, name)
                identities[name] = identity(os.fstat(handles[name]))
                if identities[name]['size'] != entry['size'] or identities[name]['device'] != folder['device']:
                    raise Refused('SOURCE_REFUSED')
            if sum(row['size'] for row in identities.values()) > MAX_SOURCE:
                raise Refused('SOURCE_REFUSED')
            yield dict(parent=parent, fd=fd, handles=handles, identities=identities, profile=profile,
                       folder=folder, raw=raw, manifest=manifest)
        finally:
            for handle in handles.values():
                os.close(handle)
            os.close(fd)


def verify_source(src):
    same(src['fd'], src['folder'])
    current = os.stat(src['profile'].backup, dir_fd=src['parent'], follow_symlinks=False)
    if identity(current) != src['folder'] or set(os.listdir(src['fd'])) != set(src['handles']):
        raise Refused('SOURCE_CHANGED')
    for name, fd in src['handles'].items():
        same(fd, src['identities'][name])
        if identity(os.stat(name, dir_fd=src['fd'], follow_symlinks=False)) != src['identities'][name]:
            raise Refused('SOURCE_CHANGED')


def measure(src, budget, protected):
    rows = {}
    profile = src['profile']
    for name in sorted(src['manifest']):
        row = compress(src['handles'][name], budget, Sink(budget), level=profile.gzip_level)
        if {key: row[key] for key in ('size', 'sha256')} != src['manifest'][name]:
            raise Refused('HASH_MISMATCH')
        rows[name] = dict(row, source=src['identities'][name])
    verify_source(src)
    return validate_archive_plan(dict(version=1, scope=profile.scope, backup=profile.backup, archive=profile.archive,
                gzip=dict(level=profile.gzip_level, mtime=0, zlib=zlib.ZLIB_RUNTIME_VERSION, python=sys.version.split()[0]),
                source_folder=src['folder'], source_manifest=src['identities']['manifest.json'],
                source_manifest_sha256=digest(src['raw']), files=rows, protected=protected,
                reserve_bytes=RESERVE, minimum_free_after_bytes=MIN_FREE_AFTER,
                overhead_bytes=OVERHEAD), expected_scope=profile.scope)


def free_bytes(fd):
    info = os.fstatvfs(fd)
    return info.f_bavail * info.f_frsize


def exists(parent, name):
    try:
        os.stat(name, dir_fd=parent, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def archive_absent(scope=SCOPE):
    profile = profile_for(scope)
    with directory('/'.join(ARCHIVE_PARENT.split('/')[:-1])) as parent:
        name = ARCHIVE_PARENT.split('/')[-1]
        if exists(parent, name):
            with directory(ARCHIVE_PARENT, True) as archive_parent:
                if any(exists(archive_parent, candidate.archive) for candidate in PROFILES.values()
                       if candidate.backup == profile.backup):
                    raise Refused('ARCHIVE_EXISTS')


@contextlib.contextmanager
def new_archive(source_device, scope=SCOPE):
    """An incomplete private directory is retained on error; never overwrite it."""
    profile = profile_for(scope)
    with directory('/'.join(ARCHIVE_PARENT.split('/')[:-1])) as parent:
        name = ARCHIVE_PARENT.split('/')[-1]
        if not exists(parent, name):
            os.mkdir(name, 0o700, dir_fd=parent)
            os.fsync(parent)
        with directory(ARCHIVE_PARENT, True) as archive_parent:
            if os.fstat(archive_parent).st_dev != source_device:
                raise Refused('PATH_REFUSED')
            if any(exists(archive_parent, candidate.archive) for candidate in PROFILES.values()
                   if candidate.backup == profile.backup):
                raise Refused('ARCHIVE_EXISTS')
            os.mkdir(profile.archive, 0o700, dir_fd=archive_parent)
            os.fsync(archive_parent)
            fd = os.open(profile.archive, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=archive_parent)
            try:
                check_dir(fd, True)
                yield fd
            finally:
                os.close(fd)


def create_file(parent, name):
    return os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)


def write_bytes(parent, name, data, budget):
    fd = create_file(parent, name)
    try:
        sink = Sink(budget, fd=fd, maximum=65536)
        sink.write(data)
        sink.flush()
    finally:
        os.close(fd)


def verify_gzip(parent, name, expected, budget, output_fd=None):
    fd = open_file(parent, name + '.gz', True)
    try:
        pinned = identity(os.fstat(fd))
        if pinned['size'] != expected['gzip_size']:
            raise Refused('ARCHIVE_VERIFY_FAILED')
        compressed_hash, raw_hash = hashlib.sha256(), hashlib.sha256()
        total = 0
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        while True:
            budget.check()
            chunk = os.read(fd, CHUNK)
            if not chunk:
                break
            compressed_hash.update(chunk)
            while chunk:
                data = decoder.decompress(chunk, CHUNK)
                chunk = decoder.unconsumed_tail
                total += len(data)
                if total > expected['size'] or decoder.unused_data:
                    raise Refused('ARCHIVE_VERIFY_FAILED')
                raw_hash.update(data)
                if output_fd is not None:
                    view = memoryview(data)
                    while view:
                        count = os.write(output_fd, view)
                        if count <= 0:
                            raise Refused('ARCHIVE_VERIFY_FAILED')
                        view = view[count:]
        if (not decoder.eof or total != expected['size'] or
                raw_hash.hexdigest() != expected['sha256'] or
                compressed_hash.hexdigest() != expected['gzip_sha256']):
            raise Refused('ARCHIVE_VERIFY_FAILED')
        same(fd, pinned)
    except (zlib.error, OSError):
        raise Refused('ARCHIVE_VERIFY_FAILED') from None
    finally:
        os.close(fd)


def verify_archive(fd, plan, raw, budget, published):
    expected_names = {name + '.gz' for name in plan['files']} | {'source-manifest.json', 'archive-manifest.json' if published else '.manifest.pending'}
    if set(os.listdir(fd)) != expected_names:
        raise Refused('ARCHIVE_VERIFY_FAILED')
    for name, expected in plan['files'].items():
        verify_gzip(fd, name, expected, budget)
    for name, expected in (('source-manifest.json', raw),
                           ('archive-manifest.json' if published else '.manifest.pending', canonical(plan).encode())):
        handle = open_file(fd, name, True)
        try:
            if read_small(handle) != expected:
                raise Refused('ARCHIVE_VERIFY_FAILED')
        finally:
            os.close(handle)


def publish(fd):
    """Exclusive manifest link is the atomic commit marker, then fsync it.

    All files are durable before this link. A crash before publication leaves
    the source intact; a crash after publication always leaves a full archive.
    """
    os.link('.manifest.pending', 'archive-manifest.json', src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
    os.unlink('.manifest.pending', dir_fd=fd)
    os.fsync(fd)


def remove_source(src, result, budget):
    verify_source(src)
    result['cleanup_started'] = True
    result['removed_files'] = 0
    for name in sorted(src['handles']):
        budget.check()
        same(src['handles'][name], src['identities'][name])
        if identity(os.stat(name, dir_fd=src['fd'], follow_symlinks=False)) != src['identities'][name]:
            raise Refused('SOURCE_CHANGED')
        os.unlink(name, dir_fd=src['fd'])
        result['removed_files'] += 1
        # Unlink alone retains all blocks while our verification fd is open.
        # Close it before reporting free space, and avoid a second close later.
        os.close(src['handles'].pop(name))
    os.fsync(src['fd'])
    info = os.stat(src['profile'].backup, dir_fd=src['parent'], follow_symlinks=False)
    if (info.st_dev, info.st_ino) != (src['folder']['device'], src['folder']['inode']) or os.listdir(src['fd']):
        raise Refused('SOURCE_CHANGED')
    os.rmdir(src['profile'].backup, dir_fd=src['parent'])
    os.fsync(src['parent'])
    result['cleanup_complete'] = True


def execute(mode, plan_sha='', confirm='', runner=run, free=None, budget=None, scope=SCOPE):
    result = receipt(mode)
    budget = budget or Budget()
    try:
        profile = profile_for(scope)
        result['scope'] = profile.scope
        if mode == 'plan':
            if plan_sha or confirm:
                raise Refused('INPUT_REFUSED')
        elif mode == 'apply':
            if type(plan_sha) is not str or not SHA.fullmatch(plan_sha) or confirm != profile.confirm:
                raise Refused('INPUT_REFUSED')
        else:
            raise Refused('INPUT_REFUSED')
        protected = snapshot(runner)
        result.update(protected_sha256=digest(canonical(protected).encode()),
                      containers=len(protected['containers']), images=len(protected['images']))
        archive_absent(profile.scope)
        with source(profile.scope) as src:
            free = free or (lambda: free_bytes(src['parent']))
            result['free_before_bytes'] = free()
            plan = measure(src, budget, protected)
            total = sum(row['size'] for row in plan['files'].values())
            allocated = sum(row['allocated_bytes'] for row in src['identities'].values())
            compressed = sum(row['gzip_size'] for row in plan['files'].values())
            archive_budget = compressed + OVERHEAD
            projection = max(0, free() + allocated - archive_budget)
            capacity = free() >= archive_budget + RESERVE and projection >= MIN_FREE_AFTER
            result.update(plan_sha256=digest(canonical(plan).encode()),
                          source_manifest_sha256=digest(src['raw']), source_files=len(plan['files']),
                          source_bytes=total, source_allocated_bytes=allocated, compressed_bytes=compressed,
                          archive_budget_bytes=archive_budget, projected_free_bytes=projection, capacity_ok=capacity)
            result['protected_unchanged'] = snapshot(runner) == protected
            if not result['protected_unchanged']:
                raise Refused('PROTECTED_CHANGED')
            if mode == 'plan':
                result.update(status='planned', reason='PLAN_READY', free_after_bytes=free())
                return validate_report(result)
            if plan_sha != result['plan_sha256']:
                raise Refused('PLAN_MISMATCH')
            if not capacity:
                raise Refused('SPACE_REFUSED')
            with new_archive(src['folder']['device'], profile.scope) as archive:
                result['archive_started'] = True
                for name, expected in plan['files'].items():
                    handle = create_file(archive, name + '.gz')
                    try:
                        actual = compress(src['handles'][name], budget,
                            Sink(budget, fd=handle, free=free, maximum=expected['gzip_size']),
                            level=profile.gzip_level)
                    finally:
                        os.close(handle)
                    if actual != {key: expected[key] for key in ('size', 'sha256', 'gzip_size', 'gzip_sha256')}:
                        raise Refused('HASH_MISMATCH')
                verify_source(src)
                write_bytes(archive, 'source-manifest.json', src['raw'], budget)
                write_bytes(archive, '.manifest.pending', canonical(plan).encode(), budget)
                os.fsync(archive)
                verify_archive(archive, plan, src['raw'], budget, False)
                result['protected_unchanged'] = snapshot(runner) == protected
                if not result['protected_unchanged']:
                    raise Refused('PROTECTED_CHANGED')
                verify_source(src)
                if free() + allocated < MIN_FREE_AFTER:
                    raise Refused('SPACE_REFUSED')
                publish(archive)
                result.update(archive_published=True, archive_manifest_sha256=digest(canonical(plan).encode()))
                # Publication changes only a directory entry; bytes were already
                # fully decompressed and compared. Recheck the committed manifest.
                manifest_fd = open_file(archive, 'archive-manifest.json', True)
                try:
                    if read_small(manifest_fd) != canonical(plan).encode():
                        raise Refused('ARCHIVE_VERIFY_FAILED')
                finally:
                    os.close(manifest_fd)
                result['archive_verified'] = True
                remove_source(src, result, budget)
                result['protected_unchanged'] = snapshot(runner) == protected
                result['free_after_bytes'] = free()
                if not result['protected_unchanged']:
                    raise Refused('PROTECTED_CHANGED')
                if result['free_after_bytes'] < MIN_FREE_AFTER:
                    result['capacity_ok'] = False
                    raise Refused('SPACE_REFUSED')
                result.update(status='applied', reason='ARCHIVED')
    except Refused as exc:
        result['reason'] = str(exc) if str(exc) in REASONS else 'INTERNAL_ERROR'
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    return validate_report(result)


def validate_archive_plan(plan, expected_scope=None):
    if type(plan) is not dict or type(plan.get('scope')) is not str or plan['scope'] not in PROFILES:
        raise Refused('ARCHIVE_REFUSED')
    profile = profile_for(plan['scope'])
    if expected_scope is not None and profile.scope != profile_for(expected_scope).scope:
        raise Refused('ARCHIVE_REFUSED')
    expected = {'version', 'scope', 'backup', 'archive', 'gzip', 'source_folder',
                'source_manifest', 'source_manifest_sha256', 'files', 'protected',
                'reserve_bytes', 'minimum_free_after_bytes', 'overhead_bytes'}
    if (type(plan) is not dict or set(plan) != expected or type(plan['version']) is not int or
            plan['version'] != 1 or plan['backup'] != profile.backup or
            plan['archive'] != profile.archive or type(plan['files']) is not dict or
            'engine.db' not in plan['files'] or not set(plan['files']).issubset(FILES) or
            type(plan['source_manifest_sha256']) is not str or not SHA.fullmatch(plan['source_manifest_sha256'])):
        raise Refused('ARCHIVE_REFUSED')
    for name, expected_value in (('reserve_bytes', RESERVE), ('minimum_free_after_bytes', MIN_FREE_AFTER),
                                 ('overhead_bytes', OVERHEAD)):
        if type(plan[name]) is not int or plan[name] != expected_value:
            raise Refused('ARCHIVE_REFUSED')
    gz = plan['gzip']
    if (type(gz) is not dict or set(gz) != {'level', 'mtime', 'zlib', 'python'} or
            type(gz['level']) is not int or gz['level'] != profile.gzip_level or type(gz['mtime']) is not int or gz['mtime'] != 0 or
            any(type(gz[k]) is not str or not re.fullmatch(r'[0-9A-Za-z.+-]{1,32}', gz[k]) for k in ('zlib', 'python'))):
        raise Refused('ARCHIVE_REFUSED')

    def metadata(row, kind):
        keys = {'device', 'inode', 'mode', 'uid', 'gid', 'size', 'links', 'mtime_ns', 'ctime_ns', 'allocated_bytes'}
        if (type(row) is not dict or set(row) != keys or
                any(type(v) is not int or not 0 <= v < 2 ** 63 for v in row.values()) or
                row['uid'] not in (ROOT_UID, 10001) or row['gid'] not in (ROOT_GID, 10001) or
                row['size'] > MAX_SOURCE or row['allocated_bytes'] > MAX_SOURCE + OVERHEAD or
                row['mode'] not in ((0o700,) if kind == 'folder' else (0o600,) if kind == 'manifest' else (0o600, 0o640, 0o644)) or
                (kind != 'folder' and row['links'] != 1) or
                (kind in ('folder', 'manifest') and (row['uid'] != ROOT_UID or row['gid'] != ROOT_GID))):
            raise Refused('ARCHIVE_REFUSED')

    metadata(plan['source_folder'], 'folder')
    metadata(plan['source_manifest'], 'manifest')
    if plan['source_manifest']['size'] > 65536:
        raise Refused('ARCHIVE_REFUSED')
    for row in plan['files'].values():
        if (type(row) is not dict or set(row) != {'size', 'sha256', 'gzip_size', 'gzip_sha256', 'source'} or
                type(row['size']) is not int or not 0 <= row['size'] <= MAX_SOURCE or
                type(row['gzip_size']) is not int or not 0 < row['gzip_size'] <= MAX_ARCHIVE or
                any(type(row[k]) is not str or not SHA.fullmatch(row[k]) for k in ('sha256', 'gzip_sha256'))):
            raise Refused('ARCHIVE_REFUSED')
        metadata(row['source'], 'file')
        if row['source']['size'] != row['size']:
            raise Refused('ARCHIVE_REFUSED')
    if sum(row['size'] for row in plan['files'].values()) > MAX_SOURCE:
        raise Refused('ARCHIVE_REFUSED')
    return plan


def restore_isolated(archive_path, target_parent, target_name, archive_sha256, scope=SCOPE):
    """Local recovery exercise only, never reachable from the production CLI.

    The caller provides an existing private isolated parent; only a newly
    created restore-check-* child is accepted. No existing file is overwritten.
    Original manifest bytes, ownership, modes and mtime are restored after the
    full gzip byte comparison. No database library is used.
    """
    profile = profile_for(scope)
    if (not re.fullmatch(r'restore-check-[0-9a-f]{16}', target_name) or
            type(archive_sha256) is not str or not SHA.fullmatch(archive_sha256)):
        raise Refused('INPUT_REFUSED')
    if target_parent.startswith(('/var/lib/', '/var/backups/', '/srv/', '/opt/')):
        raise Refused('PATH_REFUSED')
    budget = Budget()
    with directory(archive_path, True) as archive, directory(target_parent, True) as parent:
        handle = open_file(archive, 'archive-manifest.json', True)
        try:
            manifest_bytes = read_small(handle)
        finally:
            os.close(handle)
        if digest(manifest_bytes) != archive_sha256:
            raise Refused('ARCHIVE_REFUSED')
        plan = validate_archive_plan(strict_json(manifest_bytes), expected_scope=profile.scope)
        handle = open_file(archive, 'source-manifest.json', True)
        try:
            raw = read_small(handle)
        finally:
            os.close(handle)
        if digest(raw) != plan.get('source_manifest_sha256'):
            raise Refused('ARCHIVE_REFUSED')
        original = strict_json(raw)
        if original != {name: {key: row[key] for key in ('size', 'sha256')} for name, row in plan['files'].items()}:
            raise Refused('ARCHIVE_REFUSED')
        verify_archive(archive, plan, raw, budget, True)
        os.mkdir(target_name, 0o700, dir_fd=parent)
        target = os.open(target_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        try:
            for name, row in plan['files'].items():
                output = create_file(target, name)
                try:
                    verify_gzip(archive, name, row, budget, output)
                    metadata = row['source']
                    os.fchown(output, metadata['uid'], metadata['gid'])
                    os.fchmod(output, metadata['mode'])
                    os.utime(output, ns=(metadata['mtime_ns'], metadata['mtime_ns']))
                    os.fsync(output)
                finally:
                    os.close(output)
            write_bytes(target, 'manifest.json', raw, budget)
            manifest_fd = open_file(target, 'manifest.json', True)
            try:
                meta = plan['source_manifest']
                os.fchown(manifest_fd, meta['uid'], meta['gid'])
                os.fchmod(manifest_fd, meta['mode'])
                os.utime(manifest_fd, ns=(meta['mtime_ns'], meta['mtime_ns']))
                os.fsync(manifest_fd)
            finally:
                os.close(manifest_fd)
            meta = plan['source_folder']
            os.fchown(target, meta['uid'], meta['gid'])
            os.fchmod(target, meta['mode'])
            os.utime(target, ns=(meta['mtime_ns'], meta['mtime_ns']))
            os.fsync(target)
            os.fsync(parent)
        finally:
            os.close(target)


@contextlib.contextmanager
def deployment_lock():
    with directory(LOCK_PARENT) as parent:
        fd = os.open('lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_nlink != 1 or info.st_mode & 0o022:
                raise Refused('PATH_REFUSED')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('LOCKED') from None
            yield
        finally:
            os.close(fd)


def main(args):
    mode = args[0] if args else 'invalid'
    result = receipt(mode)
    try:
        if len(args) not in (3, 4):
            raise Refused('INPUT_REFUSED')
        profile = profile_for(args[3] if len(args) == 4 else SCOPE)
        result['scope'] = profile.scope
        if os.geteuid() != ROOT_UID:
            raise Refused('NOT_ROOT')
        os.umask(0o077)
        os.nice(19)
        with deployment_lock():
            result = execute(*args[:3], scope=profile.scope)
    except Refused as exc:
        result['reason'] = str(exc) if str(exc) in REASONS else 'INTERNAL_ERROR'
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    print(canonical(validate_report(result)))
    return 0 if result['status'] in ('planned', 'applied') else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
