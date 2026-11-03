"""Fixed read-only backup observation: RAM health and directory metadata only."""
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
import time

SCOPE = 'naver-backup-status-v2'
BACKUP_ROOT = '/var/backups/metainc/naver-engine'
SOCKET_PATH = '/run/metainc/naver-engine/engine.sock'
LOCK_PATH = '/var/lib/metainc/naver-deploy/lock'
ENGINE_UID = 10001
MAX_ENTRIES = 4096
MAX_BUILDING_DIRECTORIES = 16
MAX_BODY = 65536
METADATA_SECONDS = 10
HEALTH_SECONDS = 3
DOCKER = ('/usr/bin/docker', '--host=unix:///var/run/docker.sock')
ID = re.compile(r'[0-9a-f]{64}\Z')
IMAGE = re.compile(r'sha256:[0-9a-f]{64}\Z')
NAME = re.compile(r'naver-([0-9]{8}T[0-9]{6}Z)-[0-9a-f]{32}\.(zip|cms)\Z')
BUILDING = re.compile(r'\.building-[a-z0-9_]{8}\Z')
ROOT_BUCKETS = ('archive_regular', 'building_directory', 'other_regular',
                'other_directory', 'symlink', 'special')
CHILD_BUCKETS = ('snapshot_regular', 'packed_regular', 'encrypted_regular',
                 'other_regular', 'directory', 'symlink', 'special')
VIOLATIONS = ('name', 'extension', 'type', 'owner', 'mode', 'links', 'size', 'date')
CODES = frozenset(('NEVER', 'IN_PROGRESS', 'LOCAL_FAILED', 'ENCRYPTION_FAILED', 'READY',
                  'LOCAL_READY', 'UPLOAD_FAILED', 'OFFSITE_OK', 'RETENTION_FAILED'))
REASONS = frozenset(('OK', 'MISSING', 'UNAVAILABLE', 'INVALID', 'TIME_LIMIT', 'ENTRY_LIMIT',
                     'UNEXPECTED_ENTRY', 'BUILDING_LIMIT', 'CHANGED', 'MOUNT_REFUSED', 'PROTECTED_CHANGED',
                     'LOCKED', 'PATH_REFUSED', 'NOT_ROOT', 'INPUT_REFUSED', 'INTERNAL_ERROR'))
SNAP_FORMAT = ('{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},'
               '"pid":{{json .State.Pid}},"started":{{json .State.StartedAt}},'
               '"restarts":{{json .RestartCount}}}')
MOUNT_FORMAT = ('{"id":{{json .Id}},"user":{{json .Config.User}},'
                '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
                '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
                '"mounts":{{json .Mounts}}}')


class Refused(Exception):
    pass


class DeadlineExpired(Exception):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def strict_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise Refused('INVALID')
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def timestamp(value):
    if value is None:
        return None
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})', value):
        raise Refused('INVALID')
    # Python 3.10 only parses 3/6 fractional digits. Validate a microsecond
    # copy while retaining every original digit for snapshot identity checks.
    parse_value = re.sub(r'\.([0-9]+)',
                        lambda match: '.' + match[1][:6].ljust(6, '0'), value)
    parsed = dt.datetime.fromisoformat(parse_value.replace('Z', '+00:00'))
    if parsed.utcoffset() is None:
        raise Refused('INVALID')
    return value


def empty_health(reason):
    return dict(status='unavailable', reason=reason, http_status=None,
                backup=None, last_tick=None)


def project_health(raw, http_status):
    if type(raw) is not bytes or len(raw) > MAX_BODY or http_status not in (200, 503):
        raise Refused('INVALID')
    try:
        body = strict_json(raw)
        if type(body) is not dict:
            raise Refused('INVALID')
        tick = timestamp(body.get('last_tick'))
        if 'backup' not in body:
            value = empty_health('MISSING')
            value.update(http_status=http_status, last_tick=tick)
            return value
        backup = body['backup']
        if type(backup) is not dict or set(backup) != {'code', 'last_attempt_at', 'last_offsite_at'}:
            raise Refused('INVALID')
        if type(backup['code']) is not str or backup['code'] not in CODES:
            raise Refused('INVALID')
        output = dict(code=backup['code'], last_attempt_at=timestamp(backup['last_attempt_at']),
                      last_offsite_at=timestamp(backup['last_offsite_at']))
        return dict(status='observed', reason='OK', http_status=http_status, backup=output, last_tick=tick)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Refused('INVALID') from None


@contextlib.contextmanager
def deadline(seconds):
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        raise Refused('UNAVAILABLE')
    def expired(*args):
        raise DeadlineExpired()
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@contextlib.contextmanager
def directory(path):
    # Walk every component without following symlinks, including trusted parents.
    if not path.startswith('/') or any(p in ('', '.', '..') for p in path.split('/')[1:]):
        raise Refused('PATH_REFUSED')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.split('/')[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_blocks)


def http_payload(raw):
    # Bound the complete HTTP response, including headers, before any JSON parse.
    if len(raw) > MAX_BODY or b'\r\n\r\n' not in raw:
        raise Refused('INVALID')
    head, body = raw.split(b'\r\n\r\n', 1)
    lines = head.split(b'\r\n')
    match = re.fullmatch(rb'HTTP/1\.[01] (200|503) [^\r\n]{1,64}', lines[0])
    if match is None or len(lines) > 33:
        raise Refused('INVALID')
    headers = {}
    for line in lines[1:]:
        if b':' not in line:
            raise Refused('INVALID')
        name, value = line.split(b':', 1)
        name = name.lower()
        if not re.fullmatch(rb'[a-z][a-z0-9-]{0,63}', name) or name in headers:
            raise Refused('INVALID')
        headers[name] = value.strip()
    length = headers.get(b'content-length', b'')
    if b'transfer-encoding' in headers or not re.fullmatch(rb'[0-9]{1,6}', length) or int(length) != len(body):
        raise Refused('INVALID')
    return body, int(match[1])


def read_health():
    connection = None
    try:
        with deadline(HEALTH_SECONDS), directory(os.path.dirname(SOCKET_PATH)) as parent:
            before = os.stat('engine.sock', dir_fd=parent, follow_symlinks=False)
            if not stat.S_ISSOCK(before.st_mode) or before.st_uid != ENGINE_UID or before.st_mode & 0o002:
                raise Refused('PATH_REFUSED')
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection = sock
            sock.settimeout(HEALTH_SECONDS)
            sock.connect(SOCKET_PATH)
            sock.sendall(b'GET /_engine/health HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n')
            raw = bytearray()
            while len(raw) <= MAX_BODY:
                block = sock.recv(min(4096, MAX_BODY + 1 - len(raw)))
                if not block:
                    break
                raw.extend(block)
            body, status = http_payload(bytes(raw))
            if identity(before) != identity(os.stat('engine.sock', dir_fd=parent, follow_symlinks=False)):
                raise Refused('CHANGED')
            return project_health(body, status)
    except DeadlineExpired:
        return empty_health('TIME_LIMIT')
    except Refused as error:
        return empty_health(str(error))
    except socket.timeout:
        return empty_health('TIME_LIMIT')
    except OSError:
        return empty_health('UNAVAILABLE')
    finally:
        if connection is not None:
            connection.close()


def empty_metadata(reason):
    return dict(status='incomplete', reason=reason, root_entries=None, child_entries=None,
                root_buckets=None, child_buckets=None, archive_violations=None,
                building_directories_scanned=None, unscanned_directory_count=None,
                unscanned_subtree_bytes=None, duplicate_inode_count=None,
                building_oldest_mtime_utc=None, building_newest_mtime_utc=None)


def empty_folder(reason, metadata=None):
    return dict(status='incomplete', reason=reason, file_count=None, logical_bytes=None,
                allocated_bytes=None, oldest_filename_kst_day=None, newest_filename_kst_day=None,
                metadata=empty_metadata(reason) if metadata is None else metadata)


class MetadataBudget:
    """One work bound for both folders and their immediate building children."""
    def __init__(self, monotonic=time.monotonic):
        self.monotonic = monotonic
        self.started = monotonic()
        self.entries = 0
        self.buildings = 0

    def check(self):
        if self.monotonic() - self.started >= METADATA_SECONDS:
            raise Refused('TIME_LIMIT')

    def entry(self):
        self.check()
        if self.entries >= MAX_ENTRIES:
            raise Refused('ENTRY_LIMIT')
        self.entries += 1

    def building(self):
        self.check()
        if self.buildings >= MAX_BUILDING_DIRECTORIES:
            raise Refused('BUILDING_LIMIT')
        self.buildings += 1


def bucket_rows(names):
    return {name: dict(entries=0, regular_logical_bytes=0, inode_allocated_bytes=0)
            for name in names}


def entry_bucket(name, info, *, child=False):
    if stat.S_ISREG(info.st_mode):
        if child:
            return {'snapshot.sqlite': 'snapshot_regular', 'packed.zip': 'packed_regular',
                    'encrypted.cms': 'encrypted_regular'}.get(name, 'other_regular')
        return 'archive_regular' if NAME.fullmatch(name) else 'other_regular'
    if stat.S_ISDIR(info.st_mode):
        return 'directory' if child else ('building_directory' if BUILDING.fullmatch(name) else 'other_directory')
    return 'symlink' if stat.S_ISLNK(info.st_mode) else 'special'


def summarize_folder(folder, extension, *, monotonic=time.monotonic, budget=None):
    budget = MetadataBudget(monotonic) if budget is None else budget
    try:
        with directory(BACKUP_ROOT) as parent, contextlib.ExitStack() as opened:
            info = os.fstat(parent)
            if info.st_uid != ENGINE_UID or stat.S_IMODE(info.st_mode) != 0o700:
                raise Refused('PATH_REFUSED')
            fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            opened.callback(os.close, fd)
            before = os.fstat(fd)
            if before.st_uid != ENGINE_UID or stat.S_IMODE(before.st_mode) != 0o700:
                raise Refused('PATH_REFUSED')
            metadata = dict(status='observed', reason='OK', root_entries=0, child_entries=0,
                root_buckets=bucket_rows(ROOT_BUCKETS), child_buckets=bucket_rows(CHILD_BUCKETS),
                archive_violations=dict.fromkeys(VIOLATIONS, 0), building_directories_scanned=0,
                unscanned_directory_count=0, unscanned_subtree_bytes=0, duplicate_inode_count=0,
                building_oldest_mtime_utc=None, building_newest_mtime_utc=None)
            seen, checks, buildings, archives = set(), [], [], []
            building_descriptors = []
            building_mtimes = []
            archive_reason = None

            def rows(directory_fd):
                names = []
                with os.scandir(directory_fd) as entries:
                    for entry in entries:
                        budget.entry()
                        names.append(entry.name)
                return sorted(names)

            def observe(name, directory_fd, *, child=False):
                budget.check()
                item = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                checks.append((directory_fd, name, identity(item)))
                if not 0 <= item.st_size < 2 ** 63 or not 0 <= item.st_blocks * 512 < 2 ** 63:
                    raise Refused('INVALID' if child else 'UNEXPECTED_ENTRY')
                kind = entry_bucket(name, item, child=child)
                bucket = metadata['child_buckets' if child else 'root_buckets'][kind]
                metadata['child_entries' if child else 'root_entries'] += 1
                bucket['entries'] += 1
                inode = (item.st_dev, item.st_ino)
                if inode in seen:
                    metadata['duplicate_inode_count'] += 1
                else:
                    seen.add(inode)
                    bucket['inode_allocated_bytes'] += item.st_blocks * 512
                    if stat.S_ISREG(item.st_mode):
                        bucket['regular_logical_bytes'] += item.st_size
                return item

            # Deterministic first-inode attribution: sorted root entries, then
            # sorted immediate children of sorted eligible building directories.
            for name in rows(fd):
                item = observe(name, fd)
                match = NAME.fullmatch(name)
                violations = dict(name=match is None, extension=match is not None and match[2] != extension,
                    type=not stat.S_ISREG(item.st_mode), owner=item.st_uid != ENGINE_UID,
                    mode=stat.S_IMODE(item.st_mode) != 0o600, links=item.st_nlink != 1,
                    size=not 0 <= item.st_size < 2 ** 63 or not 0 <= item.st_blocks * 512 < 2 ** 63,
                    date=False)
                day = None
                if match is not None:
                    try:
                        instant = dt.datetime.strptime(match[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc)
                        day = instant.astimezone(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
                    except ValueError:
                        violations['date'] = True
                for key, failed in violations.items():
                    metadata['archive_violations'][key] += int(failed)
                if any(violations.values()):
                    # Keep the original archive-only eligibility and null totals.
                    if archive_reason is None:
                        archive_reason = ('UNAVAILABLE' if match is not None and match[2] == extension
                                          and violations['date'] else 'UNEXPECTED_ENTRY')
                else:
                    archives.append((day, item.st_size, item.st_blocks * 512))
                if stat.S_ISDIR(item.st_mode):
                    if BUILDING.fullmatch(name):
                        seconds, nanos = divmod(item.st_mtime_ns, 10 ** 9)
                        building_mtimes.append(dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
                                               + dt.timedelta(microseconds=nanos // 1000))
                    if BUILDING.fullmatch(name) and item.st_uid == ENGINE_UID and stat.S_IMODE(item.st_mode) == 0o700:
                        buildings.append((name, identity(item)))
                    else:
                        metadata['unscanned_directory_count'] += 1

            for name, expected in buildings:
                budget.building()
                child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                opened.callback(os.close, child_fd)
                if identity(os.fstat(child_fd)) != expected:
                    raise Refused('CHANGED')
                building_descriptors.append((child_fd, name, expected))
                metadata['building_directories_scanned'] += 1
                for child_name in rows(child_fd):
                    child = observe(child_name, child_fd, child=True)
                    if stat.S_ISDIR(child.st_mode):
                        metadata['unscanned_directory_count'] += 1
                # The final root-entry recheck also checks the directory identity;
                # fstat binds it to the opened descriptor rather than only a name.
                if identity(os.fstat(child_fd)) != expected:
                    raise Refused('CHANGED')
            for directory_fd, name, expected in checks:
                budget.check()
                if identity(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) != expected:
                    raise Refused('CHANGED')
            for child_fd, name, expected in building_descriptors:
                budget.check()
                if (identity(os.fstat(child_fd)) != expected or
                        identity(os.stat(name, dir_fd=fd, follow_symlinks=False)) != expected):
                    raise Refused('CHANGED')
            budget.check()
            if (identity(before) != identity(os.fstat(fd)) or
                    identity(before) != identity(os.stat(folder, dir_fd=parent, follow_symlinks=False)) or
                    identity(info) != identity(os.fstat(parent))):
                raise Refused('CHANGED')
            if any(sum(row[key] for buckets in (metadata['root_buckets'], metadata['child_buckets'])
                       for row in buckets.values()) >= 2 ** 63
                   for key in ('regular_logical_bytes', 'inode_allocated_bytes')):
                raise Refused('INVALID')
            metadata['unscanned_subtree_bytes'] = None if metadata['unscanned_directory_count'] else 0
            if building_mtimes:
                metadata['building_oldest_mtime_utc'] = min(building_mtimes).isoformat()
                metadata['building_newest_mtime_utc'] = max(building_mtimes).isoformat()
            if archive_reason is not None:
                return empty_folder(archive_reason, metadata)
            sizes, allocated = sum(x[1] for x in archives), sum(x[2] for x in archives)
            if max(sizes, allocated) >= 2 ** 63:
                raise Refused('INVALID')
            days = [x[0] for x in archives]
            return dict(status='observed', reason='OK', file_count=len(archives), logical_bytes=sizes,
                        allocated_bytes=allocated, oldest_filename_kst_day=min(days) if days else None,
                        newest_filename_kst_day=max(days) if days else None, metadata=metadata)
    except FileNotFoundError:
        return empty_folder('MISSING')
    except Refused as error:
        return empty_folder(str(error))
    except (OSError, ValueError, OverflowError):
        return empty_folder('UNAVAILABLE')


def run(command):
    return subprocess.run(command, capture_output=True, timeout=30,
        env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': '/root', 'LANG': 'C.UTF-8', 'DOCKER_CONFIG': '/var/empty'})


def docker_read(args, runner):
    value = runner((*DOCKER, *args))
    if value.returncode or len(value.stdout) > 1048576:
        raise Refused('UNAVAILABLE')
    return value.stdout.decode('utf-8').splitlines()


def snapshot(runner):
    try:
        ids = docker_read(('ps', '-aq', '--no-trunc'), runner)
        if len(ids) != 5 or len(set(ids)) != 5 or any(not ID.fullmatch(x) for x in ids):
            raise Refused('INVALID')
        rows = [strict_json(x) for x in docker_read(('inspect', '--type=container', '--format', SNAP_FORMAT, *sorted(ids)), runner)]
        if len(rows) != 5 or any(type(r) is not dict or set(r) != {'id', 'image', 'running', 'pid', 'started', 'restarts'} for r in rows):
            raise Refused('INVALID')
        if {r['id'] for r in rows} != set(ids):
            raise Refused('INVALID')
        for r in rows:
            if (type(r['image']) is not str or not IMAGE.fullmatch(r['image']) or type(r['running']) is not bool or
                    any(type(r[k]) is not int or not 0 <= r[k] <= 2 ** 31 for k in ('pid', 'restarts'))):
                raise Refused('INVALID')
            timestamp(r['started'])
        images = sorted(set(docker_read(('image', 'ls', '-aq', '--no-trunc'), runner)))
        if not images or len(images) > 4096 or any(not IMAGE.fullmatch(x) for x in images) or not {r['image'] for r in rows}.issubset(images):
            raise Refused('INVALID')
        return dict(containers=sorted(rows, key=lambda r: r['id']), images=images)
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise Refused('INVALID') from None


def verify_mounts(protected, runner):
    ids = docker_read(('ps', '-aq', '--no-trunc', '--filter', 'label=com.docker.compose.project=naver-engine',
                       '--filter', 'label=com.docker.compose.service=naver-engine'), runner)
    if len(ids) != 1 or ids[0] not in {r['id'] for r in protected['containers']}:
        raise Refused('MOUNT_REFUSED')
    # Only the engine's bind metadata is read; other apps' mounts are not queried.
    rows = [strict_json(x) for x in docker_read(('inspect', '--type=container', '--format', MOUNT_FORMAT, ids[0]), runner)]
    if len(rows) != 1 or type(rows[0]) is not dict or set(rows[0]) != {'id', 'user', 'project', 'service', 'mounts'}:
        raise Refused('MOUNT_REFUSED')
    engine = rows[0]
    if (engine['id'] != ids[0] or engine['project'] != 'naver-engine' or
            engine['service'] != 'naver-engine' or engine['user'] != '10001:10001'):
        raise Refused('MOUNT_REFUSED')
    if not next(r['running'] for r in protected['containers'] if r['id'] == engine['id']):
        raise Refused('MOUNT_REFUSED')
    mounts = engine['mounts']
    if type(mounts) is not list or len(mounts) > 32 or any(type(m) is not dict for m in mounts):
        raise Refused('MOUNT_REFUSED')
    for source, destination in ((BACKUP_ROOT, '/var/backups/naver-engine'),
                                (os.path.dirname(SOCKET_PATH), '/run/naver-engine')):
        found = [m for m in mounts if m.get('Destination') == destination]
        if len(found) != 1 or found[0].get('Source') != source or found[0].get('Type') != 'bind' or found[0].get('RW') is not True:
            raise Refused('MOUNT_REFUSED')


def receipt():
    return dict(version=2, scope=SCOPE, status='unavailable', reason='INTERNAL_ERROR',
                observed_at=None, health=empty_health('UNAVAILABLE'), local=empty_folder('UNAVAILABLE'),
                outgoing=empty_folder('UNAVAILABLE'), protected_unchanged=None,
                containers=None, images=None, database_opened=False, file_contents_read=False,
                external_network_used=False, operating_files_changed=False)


def execute(runner=run):
    value = receipt()
    try:
        before = snapshot(runner)
        verify_mounts(before, runner)
        value.update(observed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                     containers=len(before['containers']), images=len(before['images']))
        value['health'] = read_health()
        try:
            with deadline(METADATA_SECONDS):
                budget = MetadataBudget()
                value['local'] = summarize_folder('local', 'zip', budget=budget)
                value['outgoing'] = summarize_folder('outgoing', 'cms', budget=budget)
        except DeadlineExpired:
            for key in ('local', 'outgoing'):
                if value[key]['status'] != 'observed':
                    value[key] = empty_folder('TIME_LIMIT')
        value['protected_unchanged'] = snapshot(runner) == before
        if not value['protected_unchanged']:
            raise Refused('PROTECTED_CHANGED')
        complete = all(value[k]['status'] == 'observed' for k in ('health', 'local', 'outgoing'))
        value.update(status='observed' if complete else 'partial', reason='OK')
    except Refused as error:
        value.update(status='unavailable', reason=str(error))
    except Exception:
        value.update(status='unavailable', reason='INTERNAL_ERROR')
    return validate_report(value)


def validate_metadata(value):
    if (type(value) is not dict or set(value) != set(empty_metadata('OK')) or
            value['status'] not in ('observed', 'incomplete') or value['reason'] not in REASONS):
        raise Refused('INVALID')
    if value['status'] == 'incomplete':
        if value['reason'] == 'OK' or any(value[k] is not None for k in value if k not in ('status', 'reason')):
            raise Refused('INVALID')
        return value
    if value['reason'] != 'OK':
        raise Refused('INVALID')
    numeric = ('root_entries', 'child_entries', 'building_directories_scanned',
               'unscanned_directory_count', 'duplicate_inode_count')
    if any(type(value[k]) is not int or not 0 <= value[k] <= MAX_ENTRIES for k in numeric):
        raise Refused('INVALID')
    total = value['root_entries'] + value['child_entries']
    if total > MAX_ENTRIES or value['building_directories_scanned'] > MAX_BUILDING_DIRECTORIES:
        raise Refused('INVALID')
    for key, names, count_key in (('root_buckets', ROOT_BUCKETS, 'root_entries'),
                                  ('child_buckets', CHILD_BUCKETS, 'child_entries')):
        buckets = value[key]
        if type(buckets) is not dict or set(buckets) != set(names):
            raise Refused('INVALID')
        for name, row in buckets.items():
            if (type(row) is not dict or set(row) != {'entries', 'regular_logical_bytes', 'inode_allocated_bytes'} or
                    any(type(n) is not int or not 0 <= n < 2 ** 63 for n in row.values()) or
                    row['entries'] > MAX_ENTRIES or
                    (not name.endswith('_regular') and row['regular_logical_bytes'] != 0) or
                    (row['entries'] == 0 and (row['regular_logical_bytes'] or row['inode_allocated_bytes']))):
                raise Refused('INVALID')
        if (sum(row['entries'] for row in buckets.values()) != value[count_key] or
                any(sum(row[k] for row in buckets.values()) >= 2 ** 63
                    for k in ('regular_logical_bytes', 'inode_allocated_bytes'))):
            raise Refused('INVALID')
    violations = value['archive_violations']
    if any(sum(row[k] for buckets in (value['root_buckets'], value['child_buckets'])
               for row in buckets.values()) >= 2 ** 63
           for k in ('regular_logical_bytes', 'inode_allocated_bytes')):
        raise Refused('INVALID')
    if (type(violations) is not dict or set(violations) != set(VIOLATIONS) or
            any(type(n) is not int or not 0 <= n <= value['root_entries'] for n in violations.values())):
        raise Refused('INVALID')
    root = value['root_buckets']
    building_count = root['building_directory']['entries']
    scanned = value['building_directories_scanned']
    unscanned = building_count - scanned + root['other_directory']['entries'] + value['child_buckets']['directory']['entries']
    if (scanned > building_count or value['unscanned_directory_count'] != unscanned or
            (not scanned and value['child_entries']) or value['duplicate_inode_count'] > total):
        raise Refused('INVALID')
    if (unscanned and value['unscanned_subtree_bytes'] is not None) or (not unscanned and (type(value['unscanned_subtree_bytes']) is not int or value['unscanned_subtree_bytes'] != 0)):
        raise Refused('INVALID')
    times = [value['building_oldest_mtime_utc'], value['building_newest_mtime_utc']]
    if building_count:
        for item in times:
            if timestamp(item) is None or not item.endswith('+00:00'):
                raise Refused('INVALID')
        if dt.datetime.fromisoformat(times[0]) > dt.datetime.fromisoformat(times[1]):
            raise Refused('INVALID')
    elif times != [None, None]:
        raise Refused('INVALID')
    return value


def validate_report(v):
    if type(v) is not dict or set(v) != set(receipt()) or type(v['version']) is not int or v['version'] != 2 or v['scope'] != SCOPE or v['status'] not in ('observed', 'partial', 'unavailable') or v['reason'] not in REASONS:
        raise Refused('INVALID')
    timestamp(v['observed_at'])
    for k in ('database_opened', 'file_contents_read', 'external_network_used', 'operating_files_changed'):
        if v[k] is not False:
            raise Refused('INVALID')
    if v['protected_unchanged'] is not None and type(v['protected_unchanged']) is not bool:
        raise Refused('INVALID')
    for k in ('containers', 'images'):
        if v[k] is not None and (type(v[k]) is not int or not 0 <= v[k] <= 4096):
            raise Refused('INVALID')
    h = v['health']
    if type(h) is not dict or set(h) != set(empty_health('OK')) or h['status'] not in ('observed', 'unavailable') or h['reason'] not in REASONS or (h['http_status'] is not None and (type(h['http_status']) is not int or h['http_status'] not in (200, 503))):
        raise Refused('INVALID')
    timestamp(h['last_tick'])
    if h['status'] == 'observed':
        if h['reason'] != 'OK' or h['http_status'] is None or project_health(json.dumps({'backup':h['backup'],'last_tick':h['last_tick']}).encode(), h['http_status']) != h:
            raise Refused('INVALID')
    elif h['backup'] is not None or h['reason'] == 'OK':
        raise Refused('INVALID')
    for key in ('local', 'outgoing'):
        row = v[key]
        if type(row) is not dict or set(row) != set(empty_folder('OK')) or row['status'] not in ('observed', 'incomplete') or row['reason'] not in REASONS:
            raise Refused('INVALID')
        metadata = validate_metadata(row['metadata'])
        fields = ('file_count', 'logical_bytes', 'allocated_bytes')
        if row['status'] == 'observed':
            if row['reason'] != 'OK' or any(type(row[k]) is not int or not 0 <= row[k] < 2 ** 63 for k in fields) or row['file_count'] > MAX_ENTRIES:
                raise Refused('INVALID')
            for k in ('oldest_filename_kst_day', 'newest_filename_kst_day'):
                day = row[k]
                if row['file_count']:
                    if type(day) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', day) or dt.date.fromisoformat(day).isoformat() != day:
                        raise Refused('INVALID')
                elif day is not None or row['logical_bytes'] != 0 or row['allocated_bytes'] != 0:
                    raise Refused('INVALID')
            if row['file_count'] and row['oldest_filename_kst_day'] > row['newest_filename_kst_day']:
                raise Refused('INVALID')
            if (metadata['status'] != 'observed' or metadata['root_entries'] != row['file_count'] or
                    metadata['root_buckets']['archive_regular']['entries'] != row['file_count'] or
                    any(metadata['archive_violations'].values()) or metadata['child_entries']):
                raise Refused('INVALID')
            archive = metadata['root_buckets']['archive_regular']
            if row['logical_bytes'] != archive['regular_logical_bytes'] or row['allocated_bytes'] != archive['inode_allocated_bytes']:
                raise Refused('INVALID')
        elif row['reason'] == 'OK' or any(row[k] is not None for k in (*fields, 'oldest_filename_kst_day', 'newest_filename_kst_day')):
            raise Refused('INVALID')
        elif metadata['status'] == 'observed' and (row['reason'] not in ('UNEXPECTED_ENTRY', 'UNAVAILABLE') or not any(metadata['archive_violations'].values())):
            raise Refused('INVALID')
    known_metadata = [v[k]['metadata'] for k in ('local', 'outgoing') if v[k]['metadata']['status'] == 'observed']
    if (sum(m['root_entries'] + m['child_entries'] for m in known_metadata) > MAX_ENTRIES or
            sum(m['building_directories_scanned'] for m in known_metadata) > MAX_BUILDING_DIRECTORIES):
        raise Refused('INVALID')
    if v['status'] == 'unavailable' and v['reason'] == 'OK':
        raise Refused('INVALID')
    if v['status'] in ('observed', 'partial') and (v['reason'] != 'OK' or v['protected_unchanged'] is not True or v['observed_at'] is None or v['containers'] != 5 or not v['images']):
        raise Refused('INVALID')
    if v['status'] == 'observed' and any(v[k]['status'] != 'observed' for k in ('health','local','outgoing')):
        raise Refused('INVALID')
    if v['status'] == 'partial' and all(v[k]['status'] == 'observed' for k in ('health','local','outgoing')):
        raise Refused('INVALID')
    return v


@contextlib.contextmanager
def deployment_lock():
    with directory(os.path.dirname(LOCK_PATH)) as parent:
        parent_info = os.fstat(parent)
        if parent_info.st_uid != 0 or parent_info.st_mode & 0o022:
            raise Refused('PATH_REFUSED')
        fd = os.open(os.path.basename(LOCK_PATH), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            s = os.fstat(fd)
            if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_nlink != 1 or s.st_mode & 0o022:
                raise Refused('PATH_REFUSED')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('LOCKED') from None
            yield
        finally:
            os.close(fd)


def main(args=None):
    args = sys.argv[1:] if args is None else args
    value = receipt()
    try:
        if args:
            raise Refused('INPUT_REFUSED')
        if os.geteuid() != 0:
            raise Refused('NOT_ROOT')
        with deployment_lock():
            value = execute()
    except Refused as error:
        value.update(reason=str(error))
    except Exception:
        value.update(reason='INTERNAL_ERROR')
    print(canonical(validate_report(value)))
    return 0 if value['status'] in ('observed', 'partial') else 2


if __name__ == '__main__':
    raise SystemExit(main())
