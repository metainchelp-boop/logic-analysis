"""Preserve two fixed NAVER backup sources before reclaiming either original.

No SQLite, service mutation, caller paths, key access or automatic retry.
The existing cold helper is loaded unchanged from one hash-bound sibling.
"""
import contextlib
import datetime as dt
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import threading
import time
import types
import zlib

COLD_SHA = 'b18e2ae1d704d93de752eb3d81a4480991f6d25568f2c6b19bd9a4aae5be85c7'


def load_cold():
    path = Path(__file__).with_name('cold_backup_archive.py')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        raw = os.read(fd, 131073)
        after = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                len(raw) > 131072 or hashlib.sha256(raw).hexdigest() != COLD_SHA or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('HELPER_REFUSED')
    finally:
        os.close(fd)
    module = types.ModuleType('bundle_cold_archive')
    module.__file__ = str(path)
    exec(compile(raw, str(path), 'exec'), module.__dict__)
    return module


A = load_cold()
Refused = A.Refused
SCOPE = 'naver-fixed-backup-bundle-gzip6-v1'
CONFIRM = 'PRESERVE_FIXED_NAVER_BACKUP_BUNDLE_LOSSLESSLY'
DEPLOYMENT_SCOPE = '54fc-cold-backup-lossless-gzip6-v1'
BACKUP_ROOT = '/var/backups/metainc/naver-engine'
ARCHIVE_NAME = '54fc-and-20261021-regular-snapshot-gzip6-v1'
ENGINE_UID = 10001
ENGINE_GID = 10001
ENGINE_IMAGE = 'sha256:93f185106b073b0bf9e848fafd4f2953bc679c33ce9fca0166740474c9d2ae92'
SOURCE_PINS = {
    'naver_engine/backup.py': 'd783dea45821e22be8ac1ea6a677bc1fc8929523c21ebfcd4b00e0e11416913d',
    'naver_engine/store.py': '775941ce72278db29ad1c8def8aad78335d5447b88f542461292c4c271da482f',
    'naver_runtime/__main__.py': '313a15d1bfad8bb819e54f76282c3efb2f77808ffed40787e837ebb4629b2356',
}
BUILDING = re.compile(r'\.building-[a-z0-9_]{8}\Z')
ZIP = re.compile(r'naver-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.zip\Z')
CANDIDATE_BYTES = 2475552768
CANDIDATE_MTIME_US = 1792594892360859
MAX_PLAN = 8192
MAX_ENTRIES = 4096
MAX_PROCESSES = 4096
MAX_TABLE_FDS = 4096
MAX_FDS = 131072
MAX_MAPS = 262144
MAX_LATE = 64
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def limit_caps():
    return dict(task_population=MAX_PROCESSES, task_generations=MAX_PROCESSES,
                fd_table=MAX_TABLE_FDS, fd_total=MAX_FDS, maps_bytes=MAX_MAPS,
                late_generations=MAX_LATE, stat_bytes=4096, fdinfo_bytes=4096)


def validate_limit_diagnostic(value):
    if (type(value) is not dict or set(value) != {'kind', 'cap', 'observed_lower_bound'} or
            type(value['kind']) is not str):
        raise Refused('ARCHIVE_REFUSED')
    kind, cap, observed = (value[k] for k in ('kind', 'cap', 'observed_lower_bound'))
    if kind in ('malformed_fd_table', 'malformed_maps'):
        if cap is not None or observed is not None:
            raise Refused('ARCHIVE_REFUSED')
    elif (kind not in limit_caps() or type(cap) is not int or cap != limit_caps()[kind] or
            type(observed) is not int or not cap < observed < 2 ** 63):
        raise Refused('ARCHIVE_REFUSED')
    return value


class LimitRefused(Refused):
    def __init__(self, kind, cap, observed_lower_bound):
        super().__init__('PROC_LIMIT')
        self.diagnostic = dict(kind=kind, cap=cap, observed_lower_bound=observed_lower_bound)


PROC_PHASES = frozenset(('unknown', 'visibility', 'population', 'task_list',
    'identity_stat', 'identity_pid_namespace', 'identity_mount_namespace',
    'process_presence', 'task_presence', 'fd_list', 'fd_metadata', 'observer_flags',
    'maps', 'cwd', 'root', 'identity_parse', 'maps_parse', 'namespace_mismatch',
    'population_stat_missing_present', 'population_pidns_missing_present',
    'population_mntns_missing_present', 'population_identity_missing_present',
    'population_pidns_missing_present_zombie_at_identity_read',
    'population_mntns_missing_present_zombie_at_identity_read',
    'population_tasks_missing_present', 'fd_missing_listed', 'fd_missing_listed_self', 'cwd_missing_with_refs',
    'root_missing_with_refs', 'same_generation_metadata_missing', 'task_identity_missing_present'))
PROC_ERRNOS = frozenset(('ENOENT', 'ESRCH', 'EACCES', 'EPERM', 'EIO', 'OTHER_OS',
                        'INVALID_VALUE', 'INVALID_ENCODING'))


def errno_bucket(error):
    if isinstance(error, OSError):
        for name in ('ENOENT', 'ESRCH', 'EACCES', 'EPERM', 'EIO'):
            if error.errno == getattr(errno, name):
                return name
        return 'OTHER_OS'
    if isinstance(error, UnicodeError):
        return 'INVALID_ENCODING'
    if isinstance(error, ValueError):
        return 'INVALID_VALUE'
    return None


def proc_observation(phase, operation, *args, **kwargs):
    # Bind only the current syscall/parse exception, never ambient last-error
    # state. Rethrow the same object so existing ENOENT recovery stays intact.
    try:
        return operation(*args, **kwargs)
    except (OSError, ValueError, UnicodeError) as error:
        error._naver_proc_fault = dict(phase=phase, errno_bucket=errno_bucket(error))
        raise


def validate_proc_diagnostic(value):
    if (type(value) is not dict or set(value) != {'phase', 'errno_bucket'} or
            type(value['phase']) is not str or value['phase'] not in PROC_PHASES or
            (value['errno_bucket'] is not None and
             (type(value['errno_bucket']) is not str or value['errno_bucket'] not in PROC_ERRNOS))):
        raise Refused('ARCHIVE_REFUSED')
    return value


def proc_fault(error):
    value = getattr(error, '_naver_proc_fault', None)
    if value is None:
        value = dict(phase='unknown', errno_bucket=errno_bucket(error))
    return dict(validate_proc_diagnostic(value))


class ProcUnavailable(Refused):
    def __init__(self, phase=None, error=None):
        super().__init__('PROC_UNAVAILABLE')
        value = proc_fault(error)
        if phase is not None:
            value['phase'] = phase
        self.proc_diagnostic = validate_proc_diagnostic(value)


def codec():
    return dict(level=6, mtime=0, zlib=zlib.ZLIB_RUNTIME_VERSION,
                python='.'.join(str(x) for x in sys.version_info[:3]))


def hash_object(value):
    return A.digest(A.canonical(value).encode())


def validate_plan(plan):
    keys = {'version', 'scope', 'codec', 'source_identity_sha256', 'producer_sha256',
            'protected_sha256', 'files'}
    if (type(plan) is not dict or set(plan) != keys or type(plan['version']) is not int or
            plan['version'] != 1 or plan['scope'] != SCOPE or
            type(plan['codec']) is not dict or set(plan['codec']) != {'level', 'mtime', 'zlib', 'python'} or
            type(plan['codec']['level']) is not int or plan['codec']['level'] != 6 or
            type(plan['codec']['mtime']) is not int or plan['codec']['mtime'] != 0 or
            any(type(plan['codec'][k]) is not str or not re.fullmatch(r'[0-9A-Za-z.+-]{1,32}', plan['codec'][k])
                for k in ('zlib', 'python'))):
        raise Refused('INPUT_REFUSED')
    for key in ('source_identity_sha256', 'producer_sha256', 'protected_sha256'):
        if type(plan[key]) is not str or not A.SHA.fullmatch(plan[key]):
            raise Refused('INPUT_REFUSED')
    if type(plan['files']) is not dict or set(plan['files']) != {'deployment', 'snapshot'}:
        raise Refused('INPUT_REFUSED')
    for row in plan['files'].values():
        if type(row) is not dict or set(row) != {'size', 'sha256', 'gzip_size', 'gzip_sha256'}:
            raise Refused('INPUT_REFUSED')
        if (type(row['size']) is not int or not 0 < row['size'] <= A.MAX_SOURCE or
                type(row['gzip_size']) is not int or not 0 < row['gzip_size'] <= A.MAX_ARCHIVE or
                any(type(row[k]) is not str or not A.SHA.fullmatch(row[k]) for k in ('sha256', 'gzip_sha256'))):
            raise Refused('INPUT_REFUSED')
    if sum(row['size'] for row in plan['files'].values()) > A.MAX_SOURCE:
        raise Refused('INPUT_REFUSED')
    return plan


def parse_plan(raw, expected):
    if (type(raw) is not str or not 0 < len(raw.encode()) <= MAX_PLAN or
            type(expected) is not str or not A.SHA.fullmatch(expected)):
        raise Refused('INPUT_REFUSED')
    plan = validate_plan(A.strict_json(raw))
    if hash_object(plan) != expected:
        raise Refused('PLAN_MISMATCH')
    return plan


@contextlib.contextmanager
def private_child(parent, name, uid, gid):
    fd = os.open(name, DIR_FLAGS, dir_fd=parent)
    try:
        meta = A.identity(os.fstat(fd))
        if meta['uid'] != uid or meta['gid'] != gid or meta['mode'] != 0o700:
            raise Refused('PATH_REFUSED')
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def regular_root():
    # Engine-owned private leaf; root-controlled ancestors retain old checks.
    with A.directory(str(Path(BACKUP_ROOT).parent)) as parent:
        with private_child(parent, Path(BACKUP_ROOT).name, ENGINE_UID, ENGINE_GID) as root:
            yield root


def entry_metadata(parent):
    names = os.listdir(parent)
    if len(names) > MAX_ENTRIES:
        raise Refused('ENTRY_LIMIT')
    return {name: A.identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) for name in sorted(names)}


@contextlib.contextmanager
def snapshot_source():
    with regular_root() as root, private_child(root, 'local', ENGINE_UID, ENGINE_GID) as local:
        entries = entry_metadata(local)
        names = [name for name in entries if BUILDING.fullmatch(name)]
        protected = [name for name in entries if ZIP.fullmatch(name)]
        if len(names) != 1 or len(protected) != 3 or set(names + protected) != set(entries):
            raise Refused('SOURCE_REFUSED')
        for name in protected:
            meta = entries[name]
            if (not stat.S_ISREG(os.stat(name, dir_fd=local, follow_symlinks=False).st_mode) or
                    meta['uid'] != ENGINE_UID or meta['gid'] != ENGINE_GID or
                    meta['mode'] != 0o600 or meta['links'] != 1):
                raise Refused('SOURCE_REFUSED')
        name = names[0]
        with private_child(local, name, ENGINE_UID, ENGINE_GID) as folder:
            meta = A.identity(os.fstat(folder))
            if (meta['mtime_ns'] // 1000 != CANDIDATE_MTIME_US or
                    set(os.listdir(folder)) != {'snapshot.sqlite'}):
                raise Refused('SOURCE_REFUSED')
            fd = os.open('snapshot.sqlite', READ_FLAGS, dir_fd=folder)
            value = None
            try:
                info = os.fstat(fd)
                file_meta = A.identity(info)
                if (not stat.S_ISREG(info.st_mode) or file_meta['links'] != 1 or
                        file_meta['uid'] != ENGINE_UID or file_meta['gid'] != ENGINE_GID or
                        file_meta['mode'] != 0o600 or file_meta['size'] != CANDIDATE_BYTES or
                        file_meta['allocated_bytes'] != CANDIDATE_BYTES or info.st_dev != meta['device']):
                    raise Refused('SOURCE_REFUSED')
                value = dict(root=root, local=local, fd=folder, handle=fd, name=name,
                             entries=entries, folder=meta, file=file_meta,
                             local_identity=A.identity(os.fstat(local)))
                verify_snapshot_source(value)
                yield value
            finally:
                if value is None or value['handle'] is not None:
                    os.close(fd)


def verify_snapshot_source(src):
    A.same(src['local'], src['local_identity'])
    A.same(src['fd'], src['folder'])
    A.same(src['handle'], src['file'])
    if (entry_metadata(src['local']) != src['entries'] or
            A.identity(os.stat(src['name'], dir_fd=src['local'], follow_symlinks=False)) != src['folder'] or
            set(os.listdir(src['fd'])) != {'snapshot.sqlite'} or
            A.identity(os.stat('snapshot.sqlite', dir_fd=src['fd'], follow_symlinks=False)) != src['file']):
        raise Refused('SOURCE_CHANGED')


class Proc:
    """Bounded kernel metadata access; never read a descriptor's file contents."""
    def __init__(self, root='/proc'):
        self.root = Path(root)

    def path(self, pid, tid, name):
        return self.root / str(pid) / 'task' / str(tid) / name

    @staticmethod
    def path_present(path, phase='process_presence'):
        try:
            proc_observation(phase, os.stat, path, follow_symlinks=False)
            return True
        except (FileNotFoundError, ProcessLookupError):
            return False

    def read(self, pid, tid, name, limit):
        phase = 'identity_stat' if name == 'stat' else 'maps' if name == 'maps' else 'observer_flags'
        fd = proc_observation(phase, os.open, self.path(pid, tid, name), READ_FLAGS)
        try:
            raw = proc_observation(phase, os.read, fd, limit + 1)
            if len(raw) > limit:
                kind = 'maps_bytes' if name == 'maps' else 'stat_bytes' if name == 'stat' else 'fdinfo_bytes'
                raise LimitRefused(kind, limit, len(raw))
            return raw
        finally:
            proc_observation(phase, os.close, fd)

    def identity(self, pid, tid):
        raw = self.read(pid, tid, 'stat', 4096)
        end = raw.rfind(b')')
        fields = raw[end + 1:].split()
        if end < 0 or raw[:raw.find(b'(')].strip() != str(tid).encode() or len(fields) < 20:
            raise Refused('PROC_INVALID')
        try:
            a = proc_observation('identity_pid_namespace', os.stat, self.path(pid, tid, 'ns/pid'))
            b = proc_observation('identity_mount_namespace', os.stat, self.path(pid, tid, 'ns/mnt'))
        except (FileNotFoundError, ProcessLookupError) as error:
            # Existing stat bytes only; this is not a non-use/skip condition.
            error._naver_proc_zombie_at_identity_read = fields[0] == b'Z'
            raise
        return (proc_observation('identity_parse', int, fields[19]),
                proc_observation('identity_parse', int, fields[1]), a.st_dev, a.st_ino, b.st_dev, b.st_ino)

    def population(self, budget):
        out = {}
        for name in proc_observation('population', os.listdir, self.root):
            budget.check()
            if not name.isascii() or not name.isdigit():
                continue
            pid = int(name)
            try:
                for item in proc_observation('task_list', os.listdir, self.root / name / 'task'):
                    budget.check()
                    if not item.isascii() or not item.isdigit():
                        raise Refused('PROC_INVALID')
                    tid = int(item)
                    try:
                        out[(pid, tid)] = self.identity(pid, tid)
                    except (FileNotFoundError, ProcessLookupError) as error:
                        if self.present(pid, tid):
                            phase = {'identity_stat': 'population_stat_missing_present',
                                     'identity_pid_namespace': 'population_pidns_missing_present',
                                     'identity_mount_namespace': 'population_mntns_missing_present'}.get(
                                         proc_fault(error)['phase'], 'population_identity_missing_present')
                            if getattr(error, '_naver_proc_zombie_at_identity_read', False) is True:
                                phase = {'population_pidns_missing_present':
                                    'population_pidns_missing_present_zombie_at_identity_read',
                                    'population_mntns_missing_present':
                                    'population_mntns_missing_present_zombie_at_identity_read'}.get(phase, phase)
                            raise ProcUnavailable(phase, error) from None
                        continue
                    if len(out) > MAX_PROCESSES:
                        raise LimitRefused('task_population', MAX_PROCESSES, len(out))
            except (FileNotFoundError, ProcessLookupError) as error:
                if self.path_present(self.root / name):
                    raise ProcUnavailable('population_tasks_missing_present', error) from None
                continue
        return out

    def present(self, pid, tid):
        return self.path_present(self.root / str(pid) / 'task' / str(tid), phase='task_presence')

    def fds(self, pid, tid):
        names = proc_observation('fd_list', os.listdir, self.path(pid, tid, 'fd'))
        if len(names) > MAX_TABLE_FDS:
            raise LimitRefused('fd_table', MAX_TABLE_FDS, len(names))
        if any(not re.fullmatch(r'[0-9]{1,10}', n) for n in names):
            raise LimitRefused('malformed_fd_table', None, None)
        return set(int(name) for name in names)

    def fd_metadata(self, pid, tid, number):
        info = proc_observation('fd_metadata', os.stat, self.path(pid, tid, 'fd/' + str(number)))
        return A.identity(info)

    def fd_flags(self, pid, tid, number):
        raw = self.read(pid, tid, 'fdinfo/' + str(number), 4096)
        flags = re.findall(rb'^flags:\s*([0-7]+)\s*$', raw, re.M)
        if len(flags) != 1:
            raise Refused('PROC_INVALID')
        return proc_observation('observer_flags', int, flags[0], 8)

    def fd(self, pid, tid, number):
        return self.fd_metadata(pid, tid, number), self.fd_flags(pid, tid, number)

    def maps(self, pid, tid):
        return self.read(pid, tid, 'maps', MAX_MAPS)

    def link(self, pid, tid, name):
        info = proc_observation(name, os.stat, self.path(pid, tid, name))
        return info.st_dev, info.st_ino

    def visible(self):
        # Invoked by the fixed host-root SSH workflow, outside containers.
        a = proc_observation('visibility', os.stat, self.root / 'self/ns/pid')
        b = proc_observation('visibility', os.stat, self.root / '1/ns/pid')
        if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
            raise ProcUnavailable('namespace_mismatch')


def mapped_identities(raw):
    out = set()
    if type(raw) is not bytes:
        raise LimitRefused('malformed_maps', None, None)
    if len(raw) > MAX_MAPS:
        raise LimitRefused('maps_bytes', MAX_MAPS, len(raw))
    for line in raw.splitlines():
        parts = line.split(None, 5)
        if (len(parts) < 5 or not re.fullmatch(rb'[r-][w-][x-][sp]', parts[1]) or
                not re.fullmatch(rb'[0-9a-f]+-[0-9a-f]+', parts[0]) or
                not re.fullmatch(rb'[0-9a-f]+', parts[2]) or
                not re.fullmatch(rb'[0-9a-f]+:[0-9a-f]+', parts[3]) or not parts[4].isdigit()):
            raise Refused('PROC_INVALID')
        major, minor = (int(p, 16) for p in parts[3].split(b':'))
        inode = int(parts[4])
        if inode:
            out.add((os.makedev(major, minor), inode))
    return out


def scan_references(targets, budget, *, observer_fds=(), proc=None):
    """Return finite observation counts, or refuse any observed use/unknown.

    observer_fds rows are (pid, tid, process_identity, number, file_identity,
    flags). They are constructed only for the helper's pinned read handles.
    """
    proc = proc or Proc()
    targets = frozenset(targets)
    exceptions = {(p, t, tuple(g), n): (m, f) for p, t, g, n, m, f in observer_fds}
    result = dict(process_generations=0, fd_observations=0, map_observations=0,
                  late_generations=0, exited_generations=0, reference_count=0,
                  passes=2)
    seen = set()

    def observe(person, before):
        pid, tid = person
        generation = (pid, tid, before)
        budget.check()
        seen.add(generation)
        if len(seen) > MAX_PROCESSES:
            raise LimitRefused('task_generations', MAX_PROCESSES, len(seen))
        try:
            if proc.identity(pid, tid) != before:
                raise Refused('PROC_CHANGED')
            first = proc.fds(pid, tid)

            def descriptor(number):
                budget.check()
                result['fd_observations'] += 1
                if result['fd_observations'] > MAX_FDS:
                    raise LimitRefused('fd_total', MAX_FDS, result['fd_observations'])
                try:
                    metadata = proc.fd_metadata(pid, tid, number)
                except (FileNotFoundError, ProcessLookupError) as error:
                    if number in proc.fds(pid, tid):
                        current_pid = os.getpid()
                        # listdir can list its own temporary FD, close it, then
                        # reuse its number on the confirming listing. Only the
                        # current task's table can be checked with direct fstat.
                        # A known source pin is never eligible, even if closed.
                        if (error.errno in (errno.ENOENT, errno.ESRCH) and
                                (pid, tid, before, number) not in exceptions and
                                pid == current_pid and tid == threading.get_native_id()):
                            try:
                                os.fstat(number)
                            except OSError as closed:
                                if closed.errno == errno.EBADF:
                                    return
                        phase = 'fd_missing_listed_self' if pid == current_pid else 'fd_missing_listed'
                        raise ProcUnavailable(phase, error) from None
                    return
                key = (metadata['device'], metadata['inode'])
                if key not in targets:
                    return
                expected = exceptions.get((pid, tid, before, number))
                if expected is None or expected[0] != metadata:
                    raise Refused('SOURCE_IN_USE')
                # Access mode cannot excuse a source reference. The original
                # flags/recheck path gets no closed-current-task exception.
                try:
                    flags = proc.fd_flags(pid, tid, number)
                except (FileNotFoundError, ProcessLookupError) as error:
                    if number in proc.fds(pid, tid):
                        phase = 'fd_missing_listed_self' if pid == os.getpid() else 'fd_missing_listed'
                        raise ProcUnavailable(phase, error) from None
                    return
                if expected != (metadata, flags):
                    raise Refused('SOURCE_IN_USE')
                if proc.fd(pid, tid, number) != (metadata, flags):
                    raise Refused('PROC_CHANGED')

            for number in sorted(first):
                descriptor(number)
            second = proc.fds(pid, tid)
            for number in sorted(second - first):
                descriptor(number)
            if proc.fds(pid, tid) - second:
                raise Refused('PROC_CHANGED')
            for _ in range(2):
                budget.check()
                refs = proc_observation('maps_parse', mapped_identities, proc.maps(pid, tid))
                result['map_observations'] += len(refs)
                if targets & refs:
                    raise Refused('SOURCE_IN_USE')
            for name in ('cwd', 'root'):
                try:
                    if proc.link(pid, tid, name) in targets:
                        raise Refused('SOURCE_IN_USE')
                except (FileNotFoundError, ProcessLookupError) as error:
                    # Kernel tasks can have no userspace root/cwd. A living
                    # userspace task with FDs/maps cannot use that exception.
                    if second or refs:
                        phase = 'cwd_missing_with_refs' if name == 'cwd' else 'root_missing_with_refs'
                        raise ProcUnavailable(phase, error) from None
            if proc.identity(pid, tid) != before:
                raise Refused('PROC_CHANGED')
        except (FileNotFoundError, ProcessLookupError) as error:
            try:
                after = proc.identity(pid, tid)
            except (FileNotFoundError, ProcessLookupError):
                after = None
            if after is not None:
                if after == before:
                    raise ProcUnavailable('same_generation_metadata_missing', error) from None
                raise Refused('PROC_CHANGED') from None
            if proc.present(pid, tid):
                raise ProcUnavailable('task_identity_missing_present', error) from None
            result['exited_generations'] += 1

    try:
        proc.visible()
        for _ in range(2):
            population = proc.population(budget)
            for person, generation in sorted(population.items()):
                observe(person, generation)
        last = proc.population(budget)
        tail = [(person, generation) for person, generation in last.items()
                if (*person, generation) not in seen]
        if len(tail) > MAX_LATE:
            raise LimitRefused('late_generations', MAX_LATE, len(tail))
        result['late_generations'] = len(tail)
        for person, generation in tail:
            observe(person, generation)
        if any((*person, generation) not in seen for person, generation in proc.population(budget).items()):
            raise Refused('PROC_CHANGED')
    except (OSError, ValueError, UnicodeError) as error:
        raise ProcUnavailable(error=error) from None
    budget.check()
    result['process_generations'] = len(seen)
    return result


def timestamp_ns(raw):
    match = re.fullmatch(r'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(?:\.([0-9]{1,9}))?(Z|[+-][0-9]{2}:[0-9]{2})', raw)
    if match is None:
        raise Refused('PRODUCER_REFUSED')
    value = dt.datetime.fromisoformat(match[1] + match[3].replace('Z', '+00:00'))
    return int(value.timestamp()) * 10 ** 9 + int((match[2] or '').ljust(9, '0'))


@contextlib.contextmanager
def beneath(root, components):
    fd = os.dup(root)
    try:
        for component in components:
            child = os.open(component, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def producer_state(protected, candidate, budget, runner=A.run, proc=None):
    proc = proc or Proc()
    engines = [row for row in protected['containers'] if row['image'] == ENGINE_IMAGE]
    if len(engines) != 1 or not engines[0]['running'] or not engines[0]['pid']:
        raise Refused('PRODUCER_REFUSED')
    engine = engines[0]
    pid = engine['pid']
    before = proc.identity(pid, pid)
    if timestamp_ns(engine['started']) <= max(candidate['folder'][k] for k in ('mtime_ns', 'ctime_ns')) or \
            timestamp_ns(engine['started']) <= max(candidate['file'][k] for k in ('mtime_ns', 'ctime_ns')):
        raise Refused('PRODUCER_REFUSED')
    fmt = ('{"id":{{json .Id}},"user":{{json .Config.User}},'
           '"readonly":{{json .HostConfig.ReadonlyRootfs}},'
           '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
           '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
           '"mounts":{{json .Mounts}}}')
    budget.check()
    result = runner((*A.DOCKER, 'inspect', '--type=container', '--format', fmt, engine['id']))
    if result.returncode or len(result.stdout) > 65536:
        raise Refused('PRODUCER_REFUSED')
    row = A.strict_json(result.stdout)
    if (type(row) is not dict or set(row) != {'id', 'user', 'readonly', 'project', 'service', 'mounts'} or
            row['id'] != engine['id'] or row['user'] != '10001:10001' or row['readonly'] is not True or
            row['project'] != 'naver-engine' or row['service'] != 'naver-engine' or
            type(row['mounts']) is not list or len(row['mounts']) > 32 or
            any(type(v) is not dict for v in row['mounts'])):
        raise Refused('PRODUCER_REFUSED')
    mounts = [v for v in row['mounts'] if v.get('Destination') == '/var/backups/naver-engine']
    if (len(mounts) != 1 or mounts[0].get('Source') != BACKUP_ROOT or
            mounts[0].get('Type') != 'bind' or mounts[0].get('RW') is not True):
        raise Refused('PRODUCER_REFUSED')
    # The sole intentional symlink follow is the kernel process-root handle.
    root = os.open(proc.root / str(pid) / 'root', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        with beneath(root, ('var', 'backups', 'naver-engine')) as mounted:
            x, y = os.fstat(mounted), os.fstat(candidate['root'])
            if (x.st_dev, x.st_ino) != (y.st_dev, y.st_ino):
                raise Refused('PRODUCER_REFUSED')
        with beneath(root, ('opt', 'naver-engine')) as code:
            for relative, expected in SOURCE_PINS.items():
                budget.check()
                parts = relative.split('/')
                with beneath(code, parts[:-1]) as parent:
                    fd = os.open(parts[-1], READ_FLAGS, dir_fd=parent)
                    try:
                        meta = A.identity(os.fstat(fd))
                        if not stat.S_ISREG(os.fstat(fd).st_mode) or meta['size'] > 1048576:
                            raise Refused('PRODUCER_REFUSED')
                        raw = A.read_small(fd, 1048576)
                        if A.digest(raw) != expected:
                            raise Refused('PRODUCER_REFUSED')
                        A.same(fd, meta)
                    finally:
                        os.close(fd)
    finally:
        os.close(root)
    if proc.identity(pid, pid) != before:
        raise Refused('PRODUCER_CHANGED')
    return dict(engine=engine, generation=before, source_pins=SOURCE_PINS,
                backup_mount_identity=[x.st_dev, x.st_ino])


def source_identity(deployment, snapshot):
    # Random directory basename is hashed, never emitted even in the plan.
    return hash_object(dict(deployment_folder=deployment['folder'],
                            deployment_manifest=deployment['identities']['manifest.json'],
                            deployment_files=deployment['identities'],
                            snapshot_folder=snapshot['folder'], snapshot_file=snapshot['file'],
                            local_identity=snapshot['local_identity'],
                            local_entries_sha256=hash_object(snapshot['entries'])))


def source_rows(deployment, snapshot):
    if set(deployment['handles']) != {'engine.db', 'manifest.json'}:
        raise Refused('SOURCE_REFUSED')
    if deployment['folder']['device'] != snapshot['folder']['device']:
        raise Refused('SOURCE_REFUSED')
    return {'deployment': deployment['handles']['engine.db'], 'snapshot': snapshot['handle']}


def rehash(fd, budget):
    os.lseek(fd, 0, os.SEEK_SET)
    result, size = hashlib.sha256(), 0
    while True:
        budget.check()
        chunk = os.read(fd, A.CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > A.MAX_SOURCE:
            raise Refused('SOURCE_REFUSED')
        result.update(chunk)
    return size, result.hexdigest()


def observe_sources(deployment, snapshot, budget, proc=None):
    proc = proc or Proc()
    source_rows(deployment, snapshot)
    fds = [deployment['fd'], snapshot['fd'], *deployment['handles'].values(), snapshot['handle']]
    pid = os.getpid()
    generation = proc.identity(pid, pid)
    exceptions = []
    targets = set()
    for fd in fds:
        metadata, flags = proc.fd(pid, pid, fd)
        if metadata != A.identity(os.fstat(fd)) or flags & os.O_ACCMODE != os.O_RDONLY:
            raise Refused('PROC_INVALID')
        targets.add((metadata['device'], metadata['inode']))
        exceptions.append((pid, pid, generation, fd, metadata, flags))
    return scan_references(targets, budget, observer_fds=exceptions, proc=proc)


def make_plan(deployment, snapshot, protected, producer, budget):
    rows = {key: A.compress(fd, budget, A.Sink(budget), level=6)
            for key, fd in source_rows(deployment, snapshot).items()}
    # The deployment backup has a pre-existing manifest, unlike the interrupted
    # regular snapshot. Its historical integrity assertion is retained.
    expected = deployment['manifest']['engine.db']
    if any(rows['deployment'][key] != expected[key] for key in ('size', 'sha256')):
        raise Refused('HASH_MISMATCH')
    return validate_plan(dict(version=1, scope=SCOPE, codec=codec(),
        source_identity_sha256=source_identity(deployment, snapshot),
        producer_sha256=hash_object(producer), protected_sha256=hash_object(protected), files=rows))


def check_plan_sources(plan, deployment, snapshot, protected, producer, budget):
    validate_plan(plan)
    if (plan['codec'] != codec() or plan['source_identity_sha256'] != source_identity(deployment, snapshot) or
            plan['producer_sha256'] != hash_object(producer) or
            plan['protected_sha256'] != hash_object(protected)):
        raise Refused('PLAN_MISMATCH')
    for key, fd in source_rows(deployment, snapshot).items():
        if rehash(fd, budget) != (plan['files'][key]['size'], plan['files'][key]['sha256']):
            raise Refused('HASH_MISMATCH')
    original = deployment['manifest']['engine.db']
    if any(plan['files']['deployment'][key] != original[key] for key in ('size', 'sha256')):
        raise Refused('HASH_MISMATCH')


def deployment_archive_plan(src, measured, protected):
    profile = src['profile']
    return A.validate_archive_plan(dict(version=1, scope=profile.scope,
        backup=profile.backup, archive=profile.archive, gzip=codec(),
        source_folder=src['folder'], source_manifest=src['identities']['manifest.json'],
        source_manifest_sha256=A.digest(src['raw']),
        files={'engine.db': dict(measured, source=src['identities']['engine.db'])},
        protected=protected, reserve_bytes=A.RESERVE,
        minimum_free_after_bytes=A.MIN_FREE_AFTER, overhead_bytes=A.OVERHEAD), DEPLOYMENT_SCOPE)


def snapshot_archive_plan(src, measured):
    return dict(version=1, scope=SCOPE, kind='interrupted-snapshot-bytes',
                codec=codec(), source_folder=src['folder'], source_file=src['file'],
                file=measured)


def validate_snapshot_archive(plan):
    keys = {'version', 'scope', 'kind', 'codec', 'source_folder', 'source_file', 'file'}
    if (type(plan) is not dict or set(plan) != keys or type(plan['version']) is not int or
            plan['version'] != 1 or plan['scope'] != SCOPE or
            plan['kind'] != 'interrupted-snapshot-bytes' or type(plan['codec']) is not dict or
            set(plan['codec']) != {'level', 'mtime', 'zlib', 'python'} or
            type(plan['codec']['level']) is not int or plan['codec']['level'] != 6 or
            type(plan['codec']['mtime']) is not int or plan['codec']['mtime'] != 0 or
            any(type(plan['codec'][k]) is not str or not re.fullmatch(r'[0-9A-Za-z.+-]{1,32}', plan['codec'][k])
                for k in ('zlib', 'python'))):
        raise Refused('ARCHIVE_REFUSED')
    metadata_keys = {'device', 'inode', 'mode', 'uid', 'gid', 'size', 'links',
                     'mtime_ns', 'ctime_ns', 'allocated_bytes'}
    for key, mode in (('source_folder', 0o700), ('source_file', 0o600)):
        row = plan[key]
        if (type(row) is not dict or set(row) != metadata_keys or
                any(type(v) is not int or not 0 <= v < 2 ** 63 for v in row.values()) or
                row['uid'] != ENGINE_UID or row['gid'] != ENGINE_GID or row['mode'] != mode or
                row['size'] > A.MAX_SOURCE or row['allocated_bytes'] > A.MAX_SOURCE + A.OVERHEAD):
            raise Refused('ARCHIVE_REFUSED')
    row = plan['file']
    if (type(row) is not dict or set(row) != {'size', 'sha256', 'gzip_size', 'gzip_sha256'} or
            type(row['size']) is not int or row['size'] != plan['source_file']['size'] or
            row['size'] != CANDIDATE_BYTES or plan['source_file']['links'] != 1 or
            type(row['gzip_size']) is not int or not 0 < row['gzip_size'] <= A.MAX_ARCHIVE or
            any(type(row[k]) is not str or not A.SHA.fullmatch(row[k]) for k in ('sha256', 'gzip_sha256'))):
        raise Refused('ARCHIVE_REFUSED')
    return plan


def verify_snapshot_archive(folder, plan, budget, published):
    validate_snapshot_archive(plan)
    marker = 'archive-manifest.json' if published else '.manifest.pending'
    if set(os.listdir(folder)) != {'snapshot.sqlite.gz', marker}:
        raise Refused('ARCHIVE_VERIFY_FAILED')
    A.verify_gzip(folder, 'snapshot.sqlite', plan['file'], budget)
    fd = A.open_file(folder, marker, True)
    try:
        if A.read_small(fd) != A.canonical(plan).encode():
            raise Refused('ARCHIVE_VERIFY_FAILED')
    finally:
        os.close(fd)


def bundle_absent():
    A.archive_absent(DEPLOYMENT_SCOPE)
    with A.directory(A.ARCHIVE_PARENT, True) as parent:
        if A.exists(parent, ARCHIVE_NAME):
            raise Refused('ARCHIVE_EXISTS')


@contextlib.contextmanager
def new_bundle(device):
    with A.directory(A.ARCHIVE_PARENT, True) as parent:
        if os.fstat(parent).st_dev != device:
            raise Refused('PATH_REFUSED')
        if A.exists(parent, ARCHIVE_NAME):
            raise Refused('ARCHIVE_EXISTS')
        os.mkdir(ARCHIVE_NAME, 0o700, dir_fd=parent)
        os.fsync(parent)
        root = os.open(ARCHIVE_NAME, DIR_FLAGS, dir_fd=parent)
        children = {}
        try:
            for name in ('deployment', 'snapshot'):
                os.mkdir(name, 0o700, dir_fd=root)
                children[name] = os.open(name, DIR_FLAGS, dir_fd=root)
            os.fsync(root)
            yield root, children
        finally:
            for fd in children.values():
                os.close(fd)
            os.close(root)


def stage_bundle(root, children, deployment, snapshot, protected, plan, budget, free):
    files = source_rows(deployment, snapshot)
    for key, name in (('deployment', 'engine.db'), ('snapshot', 'snapshot.sqlite')):
        expected = plan['files'][key]
        fd = A.create_file(children[key], name + '.gz')
        try:
            measured = A.compress(files[key], budget,
                A.Sink(budget, fd=fd, free=free, maximum=expected['gzip_size']), level=6)
        finally:
            os.close(fd)
        if measured != expected:
            raise Refused('HASH_MISMATCH')
    A.verify_source(deployment)
    verify_snapshot_source(snapshot)
    dplan = deployment_archive_plan(deployment, plan['files']['deployment'], protected)
    splan = validate_snapshot_archive(snapshot_archive_plan(snapshot, plan['files']['snapshot']))
    A.write_bytes(children['deployment'], 'source-manifest.json', deployment['raw'], budget)
    for key, value in (('deployment', dplan), ('snapshot', splan)):
        A.write_bytes(children[key], '.manifest.pending', A.canonical(value).encode(), budget)
        os.fsync(children[key])
    A.verify_archive(children['deployment'], dplan, deployment['raw'], budget, False)
    verify_snapshot_archive(children['snapshot'], splan, budget, False)
    # Either complete child can be independently restored after a later failure.
    A.publish(children['deployment'])
    A.publish(children['snapshot'])
    manifest = dict(version=1, scope=SCOPE, plan=plan, plan_sha256=hash_object(plan),
                    deployment_archive_sha256=hash_object(dplan), snapshot_archive_sha256=hash_object(splan))
    A.write_bytes(root, '.manifest.pending', A.canonical(manifest).encode(), budget)
    os.fsync(root)
    A.publish(root)
    for folder, expected in ((children['deployment'], dplan), (children['snapshot'], splan), (root, manifest)):
        fd = A.open_file(folder, 'archive-manifest.json', True)
        try:
            if A.read_small(fd) != A.canonical(expected).encode():
                raise Refused('ARCHIVE_VERIFY_FAILED')
        finally:
            os.close(fd)
    return manifest


def restore_snapshot_isolated(archive_path, target_parent, target_name, archive_sha256):
    if (not re.fullmatch(r'restore-check-[0-9a-f]{16}', target_name) or
            type(archive_sha256) is not str or not A.SHA.fullmatch(archive_sha256) or
            target_parent.startswith(('/var/lib/', '/var/backups/', '/srv/', '/opt/'))):
        raise Refused('INPUT_REFUSED')
    budget = A.Budget()
    with A.directory(archive_path, True) as archive, A.directory(target_parent, True) as parent:
        fd = A.open_file(archive, 'archive-manifest.json', True)
        try:
            raw = A.read_small(fd)
        finally:
            os.close(fd)
        if A.digest(raw) != archive_sha256:
            raise Refused('ARCHIVE_REFUSED')
        plan = validate_snapshot_archive(A.strict_json(raw))
        verify_snapshot_archive(archive, plan, budget, True)
        os.mkdir(target_name, 0o700, dir_fd=parent)
        target = os.open(target_name, DIR_FLAGS, dir_fd=parent)
        try:
            output = A.create_file(target, 'snapshot.sqlite')
            try:
                A.verify_gzip(archive, 'snapshot.sqlite', plan['file'], budget, output)
                meta = plan['source_file']
                os.fchown(output, meta['uid'], meta['gid'])
                os.fchmod(output, meta['mode'])
                os.utime(output, ns=(meta['mtime_ns'], meta['mtime_ns']))
                os.fsync(output)
            finally:
                os.close(output)
            meta = plan['source_folder']
            os.fchown(target, meta['uid'], meta['gid'])
            os.fchmod(target, meta['mode'])
            os.utime(target, ns=(meta['mtime_ns'], meta['mtime_ns']))
            os.fsync(target)
            os.fsync(parent)
        finally:
            os.close(target)


REASONS = A.REASONS | frozenset(('ENTRY_LIMIT', 'PROC_LIMIT', 'PROC_INVALID',
    'PROC_CHANGED', 'PROC_UNAVAILABLE', 'SOURCE_IN_USE', 'PRODUCER_REFUSED', 'PRODUCER_CHANGED',
    'METADATA_READY'))
NUMBERS = ('source_bytes', 'source_allocated_bytes', 'compressed_bytes', 'archive_budget_bytes',
           'free_before_bytes', 'projected_free_bytes', 'free_after_bytes', 'removed_files',
           'containers', 'images', 'reference_checks')
FLAGS = ('capacity_ok', 'archive_started', 'archive_published', 'archive_verified',
         'cleanup_started', 'cleanup_complete', 'protected_unchanged')
HASHES = ('plan_sha256', 'archive_manifest_sha256', 'protected_sha256')


def receipt(mode):
    return dict(version=3, scope=SCOPE, mode=mode if mode in ('diagnose', 'plan', 'apply') else 'invalid',
                status='refused', reason='INTERNAL_ERROR', plan=None, limit_diagnostic=None, proc_diagnostic=None,
                **{key: None for key in NUMBERS + HASHES}, **{key: False for key in FLAGS},
                database_opened=False, services_changed=False, external_network_used=False)


def validate_report(value):
    if type(value) is dict and value.get('mode') == 'finalize':
        return validate_finalize_report(value)
    if type(value) is dict and value.get('mode') == 'inspect':
        return validate_inspect_report(value)
    if (type(value) is not dict or set(value) != set(receipt('plan')) or
            type(value['version']) is not int or value['version'] != 3 or value['scope'] != SCOPE or
            value['mode'] not in ('diagnose', 'plan', 'apply', 'invalid') or
            value['status'] not in ('observed', 'planned', 'applied', 'refused') or value['reason'] not in REASONS):
        raise Refused('ARCHIVE_REFUSED')
    for key in NUMBERS:
        if value[key] is not None and (type(value[key]) is not int or not 0 <= value[key] < 2 ** 63):
            raise Refused('ARCHIVE_REFUSED')
    for key in FLAGS + ('database_opened', 'services_changed', 'external_network_used'):
        if type(value[key]) is not bool:
            raise Refused('ARCHIVE_REFUSED')
    for key in HASHES:
        if value[key] is not None and (type(value[key]) is not str or not A.SHA.fullmatch(value[key])):
            raise Refused('ARCHIVE_REFUSED')
    if any(value[k] for k in ('database_opened', 'services_changed', 'external_network_used')):
        raise Refused('ARCHIVE_REFUSED')
    if value['proc_diagnostic'] is not None:
        validate_proc_diagnostic(value['proc_diagnostic'])
        if value['reason'] != 'PROC_UNAVAILABLE' or value['status'] != 'refused':
            raise Refused('ARCHIVE_REFUSED')
    if value['limit_diagnostic'] is not None:
        validate_limit_diagnostic(value['limit_diagnostic'])
        if value['reason'] != 'PROC_LIMIT' or value['status'] != 'refused':
            raise Refused('ARCHIVE_REFUSED')
    if value['plan'] is not None:
        validate_plan(value['plan'])
        if value['plan_sha256'] != hash_object(value['plan']):
            raise Refused('ARCHIVE_REFUSED')
    if value['archive_verified'] and not value['archive_published']:
        raise Refused('ARCHIVE_REFUSED')
    if value['cleanup_started'] and not value['archive_verified']:
        raise Refused('ARCHIVE_REFUSED')
    if value['mode'] == 'diagnose' and (value['plan'] is not None or
            any(value[k] is not None for k in ('plan_sha256', 'archive_manifest_sha256',
                'source_bytes', 'source_allocated_bytes', 'compressed_bytes', 'archive_budget_bytes',
                'projected_free_bytes', 'removed_files')) or
            any(value[k] for k in FLAGS if k != 'protected_unchanged')):
        raise Refused('ARCHIVE_REFUSED')
    if value['status'] == 'observed' and (value['mode'] != 'diagnose' or
            value['reason'] != 'METADATA_READY' or value['reference_checks'] != 1 or
            not value['protected_unchanged']):
        raise Refused('ARCHIVE_REFUSED')
    if value['status'] == 'planned' and (value['mode'] != 'plan' or value['reason'] != 'PLAN_READY' or
            value['plan'] is None or value['archive_started'] or not value['protected_unchanged'] or
            value['reference_checks'] != 2):
        raise Refused('ARCHIVE_REFUSED')
    if value['status'] == 'applied' and (value['mode'] != 'apply' or value['reason'] != 'ARCHIVED' or
            not all(value[key] for key in FLAGS) or value['removed_files'] != 3 or
            value['reference_checks'] != 3 or value['free_after_bytes'] < A.MIN_FREE_AFTER):
        raise Refused('ARCHIVE_REFUSED')
    return value


def remove_snapshot(src, result, budget):
    budget.check()
    verify_snapshot_source(src)
    os.unlink('snapshot.sqlite', dir_fd=src['fd'])
    result['removed_files'] += 1
    os.close(src['handle'])
    src['handle'] = None
    os.fsync(src['fd'])
    current = os.stat(src['name'], dir_fd=src['local'], follow_symlinks=False)
    if (current.st_dev, current.st_ino) != (src['folder']['device'], src['folder']['inode']) or os.listdir(src['fd']):
        raise Refused('SOURCE_CHANGED')
    os.rmdir(src['name'], dir_fd=src['local'])
    os.fsync(src['local'])


def execute(mode, plan_sha='', confirm='', plan_json='', *, runner=A.run, free=None,
            budget=None, producer_probe=None, reference_probe=None):
    result = receipt(mode)
    budget = budget or A.Budget()
    producer_probe = producer_probe or producer_state
    reference_probe = reference_probe or observe_sources
    try:
        if mode in ('diagnose', 'plan'):
            if plan_sha or confirm or plan_json:
                raise Refused('INPUT_REFUSED')
            plan = None
        elif mode == 'apply':
            if confirm != CONFIRM:
                raise Refused('INPUT_REFUSED')
            plan = parse_plan(plan_json, plan_sha)
            if plan['codec'] != codec():
                raise Refused('PLAN_MISMATCH')
        else:
            raise Refused('INPUT_REFUSED')
        budget.check()
        protected = A.snapshot(runner)
        result.update(protected_sha256=hash_object(protected), containers=len(protected['containers']),
                      images=len(protected['images']), reference_checks=0)
        bundle_absent()
        with A.source(DEPLOYMENT_SCOPE) as deployment, snapshot_source() as snapshot:
            source_rows(deployment, snapshot)
            free = free or (lambda: A.free_bytes(deployment['parent']))
            result['free_before_bytes'] = free()
            producer = producer_probe(protected, snapshot, budget, runner)

            def references():
                reference_probe(deployment, snapshot, budget)
                result['reference_checks'] += 1

            def unchanged():
                budget.check()
                A.verify_source(deployment)
                verify_snapshot_source(snapshot)
                result['protected_unchanged'] = A.snapshot(runner) == protected
                if not result['protected_unchanged']:
                    raise Refused('PROTECTED_CHANGED')
                if producer_probe(protected, snapshot, budget, runner) != producer:
                    raise Refused('PRODUCER_CHANGED')

            references()
            if mode == 'diagnose':
                # Metadata and source-code identity only. Do not read/hash the
                # backup payloads, measure gzip, create archives or unlink.
                unchanged()
                result.update(status='observed', reason='METADATA_READY', free_after_bytes=free())
                return validate_report(result)
            if mode == 'plan':
                plan = make_plan(deployment, snapshot, protected, producer, budget)
            else:
                check_plan_sources(plan, deployment, snapshot, protected, producer, budget)
            result.update(plan=plan, plan_sha256=hash_object(plan))
            unchanged()
            references()
            allocated = deployment['identities']['engine.db']['allocated_bytes'] + snapshot['file']['allocated_bytes']
            compressed = sum(row['gzip_size'] for row in plan['files'].values())
            archive_budget = compressed + 2 * A.OVERHEAD
            current_free = free()
            projection = max(0, current_free + allocated - archive_budget)
            capacity = current_free >= archive_budget + A.RESERVE and projection >= A.MIN_FREE_AFTER
            result.update(source_bytes=sum(row['size'] for row in plan['files'].values()),
                          source_allocated_bytes=allocated, compressed_bytes=compressed,
                          archive_budget_bytes=archive_budget, projected_free_bytes=projection,
                          capacity_ok=capacity)
            if mode == 'plan':
                result.update(status='planned', reason='PLAN_READY', free_after_bytes=free())
                return validate_report(result)
            if not capacity:
                raise Refused('SPACE_REFUSED')
            # Both original files remain until both child archives and the root
            # marker are durable and complete. The inherited single profiles
            # never change their per-source floor or execution path.
            with new_bundle(deployment['folder']['device']) as (root, children):
                result['archive_started'] = True
                manifest = stage_bundle(root, children, deployment, snapshot, protected, plan, budget, free)
                result.update(archive_published=True, archive_verified=True,
                              archive_manifest_sha256=hash_object(manifest))
                unchanged()
                references()
                unchanged()
                if free() + allocated < A.MIN_FREE_AFTER:
                    raise Refused('SPACE_REFUSED')
                budget.check()
                result.update(cleanup_started=True, removed_files=0)
                child_result = {}
                try:
                    A.remove_source(deployment, child_result, budget)
                finally:
                    result['removed_files'] += child_result.get('removed_files', 0)
                remove_snapshot(snapshot, result, budget)
                result['cleanup_complete'] = True
                result['protected_unchanged'] = A.snapshot(runner) == protected
                result['free_after_bytes'] = free()
                if not result['protected_unchanged']:
                    raise Refused('PROTECTED_CHANGED')
                if result['free_after_bytes'] < A.MIN_FREE_AFTER:
                    result['capacity_ok'] = False
                    raise Refused('SPACE_REFUSED')
                result.update(status='applied', reason='ARCHIVED')
    except Refused as error:
        result['reason'] = str(error) if str(error) in REASONS else 'INTERNAL_ERROR'
        if isinstance(error, LimitRefused):
            result['limit_diagnostic'] = error.diagnostic
        if isinstance(error, ProcUnavailable):
            result['proc_diagnostic'] = error.proc_diagnostic
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    return validate_report(result)


@contextlib.contextmanager
def hard_deadline():
    if signal.getitimer(signal.ITIMER_REAL)[0]:
        raise Refused('TIME_LIMIT')
    def expired(*args):
        raise Refused('TIME_LIMIT')
    old = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, A.TIME_BUDGET)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


# Separate pending-only completion path; legacy modes and cold helper stay unchanged.
FINALIZE_CONFIRM = 'FINALIZE_VERIFIED_FIXED_NAVER_BACKUP_BUNDLE'


def finalize_receipt():
    value = receipt('apply')
    value.pop('archive_started')
    value.update(version=1, mode='finalize', archive_reused=False, payload_verified=False,
                 publication_started=False, published_markers=0, gzip_created=False,
                 gzip_rewritten=False)
    return value


def validate_finalize_report(value):
    if (type(value) is not dict or set(value) != set(finalize_receipt()) or
            type(value['version']) is not int or value['version'] != 1 or
            value['mode'] != 'finalize' or value['status'] not in ('refused', 'applied') or
            any(type(value[k]) is not bool for k in ('archive_reused', 'payload_verified',
                'publication_started', 'gzip_created', 'gzip_rewritten')) or
            value['gzip_created'] or value['gzip_rewritten'] or
            type(value['published_markers']) is not int or not 0 <= value['published_markers'] <= 3 or
            (value['payload_verified'] and not value['archive_reused']) or
            (value['publication_started'] and not value['payload_verified']) or
            (value['published_markers'] and not value['publication_started']) or
            value['archive_published'] != (value['published_markers'] == 3) or
            (value['archive_verified'] and not value['payload_verified'])):
        raise Refused('ARCHIVE_REFUSED')
    legacy = {k: v for k, v in value.items() if k in receipt('apply')}
    legacy.update(version=3, mode='apply', archive_started=value['publication_started'])
    validate_report(legacy)
    return value


def verify_pinned_gzip(fd, expected, budget):
    """Cold verifier's bounded algorithm on the caller's retained read-only FD."""
    pinned = A.identity(os.fstat(fd))
    if pinned['size'] != expected['gzip_size']:
        raise Refused('ARCHIVE_VERIFY_FAILED')
    os.lseek(fd, 0, os.SEEK_SET)
    compressed_hash, raw_hash = hashlib.sha256(), hashlib.sha256()
    total = 0
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        while True:
            budget.check()
            chunk = os.read(fd, A.CHUNK)
            if not chunk:
                break
            compressed_hash.update(chunk)
            while chunk:
                budget.check()
                data = decoder.decompress(chunk, A.CHUNK)
                chunk = decoder.unconsumed_tail
                total += len(data)
                if total > expected['size'] or decoder.unused_data:
                    raise Refused('ARCHIVE_VERIFY_FAILED')
                raw_hash.update(data)
        if (not decoder.eof or total != expected['size'] or
                raw_hash.hexdigest() != expected['sha256'] or
                compressed_hash.hexdigest() != expected['gzip_sha256']):
            raise Refused('ARCHIVE_VERIFY_FAILED')
        A.same(fd, pinned)
    except (zlib.error, OSError):
        raise Refused('ARCHIVE_VERIFY_FAILED') from None


def verify_pinned_compressed(fd, expected, budget):
    """Rebind the earlier full roundtrip to current compressed bytes before cleanup."""
    pinned = A.identity(os.fstat(fd))
    if pinned['size'] != expected['gzip_size']:
        raise Refused('ARCHIVE_VERIFY_FAILED')
    os.lseek(fd, 0, os.SEEK_SET)
    digest, size = hashlib.sha256(), 0
    while True:
        budget.check()
        chunk = os.read(fd, A.CHUNK)
        if not chunk:
            break
        size += len(chunk)
        if size > expected['gzip_size']:
            raise Refused('ARCHIVE_VERIFY_FAILED')
        digest.update(chunk)
    if size != expected['gzip_size'] or digest.hexdigest() != expected['gzip_sha256']:
        raise Refused('ARCHIVE_VERIFY_FAILED')
    A.same(fd, pinned)


class PendingBundle:
    """Retain the actual verified descriptors and permit only our publication transitions."""
    layout = {'bundle': {'deployment', 'snapshot'},
              'deployment': {'engine.db.gz', 'source-manifest.json', '.manifest.pending'},
              'snapshot': {'snapshot.sqlite.gz', '.manifest.pending'}}

    def __init__(self, stack, parent, device, budget):
        self.parent, self.budget = parent, budget
        self.parent_meta = A.identity(os.fstat(parent))
        self.dirs, self.files, self.published = {}, {}, set()
        self.marker_bytes = {}
        self.root_written = False
        self.stack = stack
        self.open_dir(parent, ARCHIVE_NAME, 'bundle', device)
        for key in ('deployment', 'snapshot'):
            self.open_dir(self.dirs['bundle'][0], key, key, device)
        for folder in ('deployment', 'snapshot'):
            for name in sorted(self.layout[folder]):
                self.open_file(folder, name)
        all_meta = [x[3] for x in self.dirs.values()] + [x[1] for x in self.files.values()]
        if len({(v['device'], v['inode']) for v in all_meta}) != len(all_meta):
            raise Refused('ARCHIVE_REFUSED')
        self.check()

    def names(self, fd):
        names = set()
        with os.scandir(fd) as iterator:
            for entry in iterator:
                self.budget.check()
                if len(names) >= 8:
                    raise Refused('ARCHIVE_REFUSED')
                names.add(entry.name)
        return names

    def open_dir(self, parent, name, key, device):
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != A.ROOT_UID or
                info.st_gid != A.ROOT_GID or stat.S_IMODE(info.st_mode) != 0o700 or info.st_dev != device):
            raise Refused('ARCHIVE_REFUSED')
        fd = os.open(name, DIR_FLAGS, dir_fd=parent)
        self.stack.callback(os.close, fd)
        meta = A.identity(info)
        A.same(fd, meta)
        self.dirs[key] = (fd, parent, name, meta)
        if self.names(fd) != self.layout[key]:
            raise Refused('ARCHIVE_REFUSED')

    def open_file(self, folder, name):
        parent = self.dirs[folder][0]
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != A.ROOT_UID or
                info.st_gid != A.ROOT_GID or stat.S_IMODE(info.st_mode) != 0o600 or
                info.st_nlink != 1 or info.st_dev != self.parent_meta['device']):
            raise Refused('ARCHIVE_REFUSED')
        meta = A.identity(info)
        if not 0 <= meta['size'] <= (A.MAX_ARCHIVE if name.endswith('.gz') else 65536):
            raise Refused('ARCHIVE_REFUSED')
        fd = os.open(name, READ_FLAGS, dir_fd=parent)
        self.stack.callback(os.close, fd)
        A.same(fd, meta)
        self.files[(folder, name)] = (fd, meta)

    def read(self, folder, name):
        fd, _ = self.files[(folder, name)]
        os.lseek(fd, 0, os.SEEK_SET)
        return A.read_small(fd)

    @staticmethod
    def equal_metadata(actual, expected, mutable=()):
        return all(actual[k] == value for k, value in expected.items() if k not in mutable)

    def check(self):
        self.budget.check()
        # File checks precede closing directory names and bindings, as in inspect.
        for (folder, name), (fd, meta) in self.files.items():
            published = name == '.manifest.pending' and folder in self.published
            current_name = 'archive-manifest.json' if published else name
            current = A.identity(os.fstat(fd))
            if (current != meta or
                    A.identity(os.stat(current_name, dir_fd=self.dirs[folder][0], follow_symlinks=False)) != current):
                raise Refused('SOURCE_CHANGED')
        for folder, (fd, parent, name, meta) in self.dirs.items():
            expected = set(self.layout[folder])
            if folder == 'bundle' and self.root_written:
                expected.add('.manifest.pending')
            if folder in self.published:
                expected.remove('.manifest.pending')
                expected.add('archive-manifest.json')
            current = A.identity(os.fstat(fd))
            if (self.names(fd) != expected or current != meta or
                    A.identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != current):
                raise Refused('SOURCE_CHANGED')
        A.same(self.parent, self.parent_meta)

    def verify(self, deployment, snapshot, protected, plan):
        dplan = deployment_archive_plan(deployment, plan['files']['deployment'], protected)
        splan = validate_snapshot_archive(snapshot_archive_plan(snapshot, plan['files']['snapshot']))
        if (self.read('deployment', 'source-manifest.json') != deployment['raw'] or
                self.read('deployment', '.manifest.pending') != A.canonical(dplan).encode() or
                self.read('snapshot', '.manifest.pending') != A.canonical(splan).encode()):
            raise Refused('ARCHIVE_VERIFY_FAILED')
        self.marker_bytes = {'deployment': A.canonical(dplan).encode(), 'snapshot': A.canonical(splan).encode()}
        self.gzip_expectations = plan['files']
        self.check()
        for folder, name in (('deployment', 'engine.db.gz'), ('snapshot', 'snapshot.sqlite.gz')):
            verify_pinned_gzip(self.files[(folder, name)][0], plan['files'][folder], self.budget)
            self.check()
        return dict(version=1, scope=SCOPE, plan=plan, plan_sha256=hash_object(plan),
                    deployment_archive_sha256=hash_object(dplan), snapshot_archive_sha256=hash_object(splan))

    def directory_transition(self, folder, *, added_root_marker=False):
        # Only immediately after our known write/link/unlink, never on a later check.
        fd, parent, name, before = self.dirs[folder]
        expected = set(self.layout[folder])
        if folder == 'bundle' and self.root_written:
            expected.add('.manifest.pending')
        if folder in self.published:
            expected.remove('.manifest.pending')
            expected.add('archive-manifest.json')
        after = A.identity(os.fstat(fd))
        # A new regular entry changes directory nlink on APFS, but not ext4.
        allowed_links = (before['links'], before['links'] + 1) if added_root_marker and folder == 'bundle' else (before['links'],)
        if (self.names(fd) != expected or after['links'] not in allowed_links or
                not self.equal_metadata(after, before, ('size', 'allocated_bytes', 'mtime_ns', 'ctime_ns', 'links')) or
                A.identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != after):
            raise Refused('SOURCE_CHANGED')
        self.dirs[folder] = (fd, parent, name, after)

    def marker_transition(self, folder):
        fd, before = self.files[(folder, '.manifest.pending')]
        after = A.identity(os.fstat(fd))
        if (not self.equal_metadata(after, before, ('ctime_ns',)) or
                A.identity(os.stat('archive-manifest.json', dir_fd=self.dirs[folder][0], follow_symlinks=False)) != after or
                self.read(folder, '.manifest.pending') != self.marker_bytes[folder]):
            raise Refused('SOURCE_CHANGED')
        A.same(fd, after)
        self.files[(folder, '.manifest.pending')] = (fd, after)
        self.published.add(folder)
        self.directory_transition(folder)

    def check_final_contents(self, source_manifest):
        # Timestamp resolution alone cannot bind the earlier verification to current bytes.
        for folder, name in (('deployment', 'engine.db.gz'), ('snapshot', 'snapshot.sqlite.gz')):
            verify_pinned_compressed(self.files[(folder, name)][0], self.gzip_expectations[folder], self.budget)
        for folder, expected in self.marker_bytes.items():
            self.budget.check()
            if self.read(folder, '.manifest.pending') != expected:
                raise Refused('ARCHIVE_VERIFY_FAILED')
        if self.read('deployment', 'source-manifest.json') != source_manifest:
            raise Refused('ARCHIVE_VERIFY_FAILED')
        self.check()

    def publish(self, manifest, result, free):
        self.check()
        for fd, _ in self.files.values():
            self.budget.check()
            os.fsync(fd)
        for folder in ('deployment', 'snapshot'):
            os.fsync(self.dirs[folder][0])
        self.check()
        for folder in ('deployment', 'snapshot'):
            self.budget.check()
            if free() < A.RESERVE:
                raise Refused('SPACE_REFUSED')
            self.check()
            result['publication_started'] = True
            A.publish(self.dirs[folder][0])
            self.marker_transition(folder)
            result['published_markers'] += 1
            self.check()
        raw = A.canonical(manifest).encode()
        if len(raw) > 65536 or free() < A.RESERVE + len(raw):
            raise Refused('SPACE_REFUSED')
        fd = A.create_file(self.dirs['bundle'][0], '.manifest.pending')
        try:
            sink = A.Sink(self.budget, fd=fd, free=free, maximum=65536)
            sink.write(raw)
            sink.flush()
            created_identity = A.identity(os.fstat(fd))
        finally:
            os.close(fd)
        self.root_written = True
        self.open_file('bundle', '.manifest.pending')
        if self.files[('bundle', '.manifest.pending')][1] != created_identity:
            raise Refused('SOURCE_CHANGED')
        if self.read('bundle', '.manifest.pending') != raw:
            raise Refused('ARCHIVE_VERIFY_FAILED')
        self.marker_bytes['bundle'] = raw
        os.fsync(self.dirs['bundle'][0])
        self.directory_transition('bundle', added_root_marker=True)
        self.check()
        self.budget.check()
        if free() < A.RESERVE:
            raise Refused('SPACE_REFUSED')
        A.publish(self.dirs['bundle'][0])
        self.marker_transition('bundle')
        result.update(published_markers=3, archive_published=True)
        self.check()
        if self.read('bundle', '.manifest.pending') != raw:
            raise Refused('ARCHIVE_VERIFY_FAILED')
        # The original held child marker contents also remain immutable across link/unlink.
        for folder, key in (('deployment', 'deployment_archive_sha256'), ('snapshot', 'snapshot_archive_sha256')):
            if A.digest(self.read(folder, '.manifest.pending')) != manifest[key]:
                raise Refused('ARCHIVE_VERIFY_FAILED')
        self.check()


def finalize_execute(plan_sha, confirm, plan_json, *, runner=A.run, free=None,
                     budget=None, producer_probe=None, reference_probe=None):
    result = finalize_receipt()
    budget = budget or A.Budget()
    producer_probe = producer_probe or producer_state
    reference_probe = reference_probe or observe_sources
    try:
        if confirm != FINALIZE_CONFIRM:
            raise Refused('INPUT_REFUSED')
        plan = parse_plan(plan_json, plan_sha)
        if plan['codec'] != codec():
            raise Refused('PLAN_MISMATCH')
        result.update(plan=plan, plan_sha256=plan_sha)
        budget.check()
        protected = A.snapshot(runner)
        result.update(protected_sha256=hash_object(protected), containers=len(protected['containers']),
                      images=len(protected['images']), reference_checks=0)
        A.archive_absent(DEPLOYMENT_SCOPE)
        with A.source(DEPLOYMENT_SCOPE) as deployment, snapshot_source() as snapshot, \
                A.directory(A.ARCHIVE_PARENT, True) as parent, contextlib.ExitStack() as stack:
            source_rows(deployment, snapshot)
            if os.fstat(parent).st_dev != deployment['folder']['device']:
                raise Refused('PATH_REFUSED')
            archive = PendingBundle(stack, parent, deployment['folder']['device'], budget)
            result['archive_reused'] = True
            free = free or (lambda: A.free_bytes(deployment['parent']))
            result['free_before_bytes'] = free()
            producer = producer_probe(protected, snapshot, budget, runner)

            def references():
                reference_probe(deployment, snapshot, budget)
                result['reference_checks'] += 1

            def unchanged():
                budget.check()
                A.verify_source(deployment)
                verify_snapshot_source(snapshot)
                result['protected_unchanged'] = A.snapshot(runner) == protected
                if not result['protected_unchanged']:
                    raise Refused('PROTECTED_CHANGED')
                if producer_probe(protected, snapshot, budget, runner) != producer:
                    raise Refused('PRODUCER_CHANGED')

            references()
            check_plan_sources(plan, deployment, snapshot, protected, producer, budget)
            unchanged()
            references()
            allocated = deployment['identities']['engine.db']['allocated_bytes'] + snapshot['file']['allocated_bytes']
            overhead = 2 * A.OVERHEAD
            current_free = free()
            projection = max(0, current_free + allocated - overhead)
            capacity = current_free >= A.RESERVE + overhead and projection >= A.MIN_FREE_AFTER
            result.update(source_bytes=sum(row['size'] for row in plan['files'].values()),
                          source_allocated_bytes=allocated, compressed_bytes=sum(row['gzip_size'] for row in plan['files'].values()),
                          archive_budget_bytes=overhead, projected_free_bytes=projection, capacity_ok=capacity)
            if not capacity:
                raise Refused('SPACE_REFUSED')
            manifest = archive.verify(deployment, snapshot, protected, plan)
            result['payload_verified'] = True
            unchanged()
            archive.publish(manifest, result, free)
            result.update(archive_verified=True, archive_manifest_sha256=hash_object(manifest))
            unchanged()
            references()
            unchanged()
            archive.check_final_contents(deployment['raw'])
            if free() + allocated < A.MIN_FREE_AFTER:
                raise Refused('SPACE_REFUSED')
            budget.check()
            result.update(cleanup_started=True, removed_files=0)
            child_result = {}
            try:
                A.remove_source(deployment, child_result, budget)
            finally:
                result['removed_files'] += child_result.get('removed_files', 0)
            remove_snapshot(snapshot, result, budget)
            result['cleanup_complete'] = True
            result['protected_unchanged'] = A.snapshot(runner) == protected
            result['free_after_bytes'] = free()
            if not result['protected_unchanged']:
                raise Refused('PROTECTED_CHANGED')
            if result['free_after_bytes'] < A.MIN_FREE_AFTER:
                result['capacity_ok'] = False
                raise Refused('SPACE_REFUSED')
            result.update(status='applied', reason='ARCHIVED')
    except Refused as error:
        result['reason'] = str(error) if str(error) in REASONS else 'INTERNAL_ERROR'
        if isinstance(error, LimitRefused):
            result['limit_diagnostic'] = error.diagnostic
        if isinstance(error, ProcUnavailable):
            result['proc_diagnostic'] = error.proc_diagnostic
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    return validate_finalize_report(result)


def finalize_main(args):
    result = finalize_receipt()
    try:
        if len(args) != 4 or args[0] != 'finalize':
            raise Refused('INPUT_REFUSED')
        if os.geteuid() != A.ROOT_UID:
            raise Refused('NOT_ROOT')
        os.umask(0o077)
        os.nice(19)
        with hard_deadline(), A.deployment_lock():
            result = finalize_execute(args[1], args[2], args[3])
    except Refused as error:
        result['reason'] = str(error) if str(error) in REASONS else 'INTERNAL_ERROR'
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    print(A.canonical(validate_finalize_report(result)))
    return 0 if result['status'] == 'applied' else 2


# Separate metadata-only contract. Existing preservation receipts stay version 3.
INSPECT_LAYOUT = {
    'bundle': ('.manifest.pending', 'archive-manifest.json'),
    'deployment': ('engine.db.gz', 'source-manifest.json', '.manifest.pending', 'archive-manifest.json'),
    'snapshot': ('snapshot.sqlite.gz', '.manifest.pending', 'archive-manifest.json'),
}
INSPECT_SLOTS = {
    folder + ':' + name: (folder, name)
    for folder, names in INSPECT_LAYOUT.items() for name in names
}
INSPECT_REASONS = frozenset(('METADATA_READY', 'INPUT_REFUSED', 'PLAN_MISMATCH',
    'NOT_ROOT', 'LOCKED', 'PATH_REFUSED', 'SOURCE_CHANGED', 'ENTRY_LIMIT',
    'MANIFEST_LIMIT', 'SNAPSHOT_REFUSED', 'DOCKER_READ_FAILED', 'PROTECTED_CHANGED',
    'TIME_LIMIT', 'INTERNAL_ERROR'))
INSPECT_FALSE = ('payload_read', 'payload_verified', 'archive_mutated',
                 'source_mutated', 'database_opened', 'services_changed', 'external_network_used')


def inspect_file_receipt():
    return dict(present=None, size=None, allocated_bytes=None, identity_sha256=None,
                manifest_sha256=None, manifest_shape_valid=None,
                manifest_plan_bound=None, payload_size_relation=None)


def inspect_receipt():
    return dict(version=1, scope=SCOPE, mode='inspect', status='refused',
        reason='INTERNAL_ERROR', plan_sha256=None, protected_sha256=None,
        protected_matches_plan=None, protected_unchanged=False,
        free_before_bytes=None, free_after_bytes=None, total_allocated_bytes=None,
        directories={k: dict(present=None, identity_sha256=None) for k in INSPECT_LAYOUT},
        files={k: inspect_file_receipt() for k in INSPECT_SLOTS},
        marker_pairs={k: 'unknown' for k in INSPECT_LAYOUT},
        bundle_child_hashes_match=None, deployment_source_manifest_matches=None,
        **{k: False for k in INSPECT_FALSE})


def validate_inspect_report(value):
    expected = inspect_receipt()
    if (type(value) is not dict or set(value) != set(expected) or
            type(value['version']) is not int or value['version'] != 1 or
            value['scope'] != SCOPE or value['mode'] != 'inspect' or
            value['status'] not in ('observed', 'refused') or value['reason'] not in INSPECT_REASONS):
        raise Refused('ARCHIVE_REFUSED')
    def maybe_bool(v):
        return v is None or type(v) is bool
    def maybe_number(v):
        return v is None or (type(v) is int and 0 <= v < 2 ** 63)
    def maybe_hash(v):
        return v is None or (type(v) is str and A.SHA.fullmatch(v))
    if (any(value[k] is not False for k in INSPECT_FALSE) or
            type(value['protected_unchanged']) is not bool or
            not all(maybe_bool(value[k]) for k in ('protected_matches_plan', 'bundle_child_hashes_match', 'deployment_source_manifest_matches')) or
            not all(maybe_hash(value[k]) for k in ('plan_sha256', 'protected_sha256')) or
            not all(maybe_number(value[k]) for k in ('free_before_bytes', 'free_after_bytes', 'total_allocated_bytes'))):
        raise Refused('ARCHIVE_REFUSED')
    for key in ('directories', 'marker_pairs', 'files'):
        if type(value[key]) is not dict or set(value[key]) != set(expected[key]):
            raise Refused('ARCHIVE_REFUSED')
    for row in value['directories'].values():
        if (type(row) is not dict or set(row) != {'present', 'identity_sha256'} or
                not maybe_bool(row['present']) or not maybe_hash(row['identity_sha256']) or
                (row['present'] is True) != (row['identity_sha256'] is not None)):
            raise Refused('ARCHIVE_REFUSED')
    for slot, row in value['files'].items():
        if (type(row) is not dict or set(row) != set(inspect_file_receipt()) or
                not all(maybe_bool(row[k]) for k in ('present', 'manifest_shape_valid', 'manifest_plan_bound')) or
                not all(maybe_number(row[k]) for k in ('size', 'allocated_bytes')) or
                not all(maybe_hash(row[k]) for k in ('identity_sha256', 'manifest_sha256')) or
                row['payload_size_relation'] not in (None, 'short', 'equal', 'long') or
                (row['present'] is True) != (row['identity_sha256'] is not None) or
                (row['present'] is True and (row['size'] is None or row['allocated_bytes'] is None)) or
                (row['present'] is not True and any(v is not None for k, v in row.items() if k != 'present')) or
                (row['manifest_plan_bound'] is True and row['manifest_shape_valid'] is not True)):
            raise Refused('ARCHIVE_REFUSED')
        if row['present'] is True:
            is_payload = INSPECT_SLOTS[slot][1].endswith('.gz')
            if (is_payload and (any(row[k] is not None for k in
                    ('manifest_sha256', 'manifest_shape_valid', 'manifest_plan_bound')) or
                    row['payload_size_relation'] is None)) or (not is_payload and
                    (row['payload_size_relation'] is not None or (value['status'] == 'observed' and
                    any(row[k] is None for k in ('manifest_sha256', 'manifest_shape_valid', 'manifest_plan_bound'))))):
                raise Refused('ARCHIVE_REFUSED')
    if any(v not in ('unknown', 'absent', 'pending', 'published', 'link_window', 'conflict')
           for v in value['marker_pairs'].values()):
        raise Refused('ARCHIVE_REFUSED')
    if value['status'] == 'observed' and (value['reason'] != 'METADATA_READY' or
            not value['protected_unchanged'] or value['plan_sha256'] is None or
            value['protected_sha256'] is None or value['protected_matches_plan'] is None or
            value['free_before_bytes'] is None or value['free_after_bytes'] is None or value['total_allocated_bytes'] is None or
            any(row['present'] is None for row in value['directories'].values()) or
            any(row['present'] is None for row in value['files'].values()) or
            'unknown' in value['marker_pairs'].values()):
        raise Refused('ARCHIVE_REFUSED')
    return value


@contextlib.contextmanager
def inspection_lock():
    # An inspection never creates even a missing lock file.
    with A.directory(A.LOCK_PARENT) as parent:
        fd = os.open('lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != A.ROOT_UID or
                    info.st_nlink != 1 or info.st_mode & 0o022):
                raise Refused('PATH_REFUSED')
            try:
                A.fcntl.flock(fd, A.fcntl.LOCK_EX | A.fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused('LOCKED') from None
            yield
        finally:
            os.close(fd)


def inspect_manifest(value, folder, name, plan):
    """Return a schema/claim association only, never a payload verification."""
    if name == 'source-manifest.json':
        if type(value) is not dict or set(value) != {'engine.db'}:
            raise ValueError('shape')
        row = value['engine.db']
        if (type(row) is not dict or set(row) != {'size', 'sha256'} or
                type(row['size']) is not int or not 0 <= row['size'] <= A.MAX_SOURCE or
                type(row['sha256']) is not str or not A.SHA.fullmatch(row['sha256'])):
            raise ValueError('shape')
        return row == {k: plan['files']['deployment'][k] for k in ('size', 'sha256')}
    if folder == 'deployment':
        A.validate_archive_plan(value, DEPLOYMENT_SCOPE)
        if set(value['files']) != {'engine.db'}:
            raise ValueError('shape')
        row = {k: v for k, v in value['files']['engine.db'].items() if k != 'source'}
        return (row == plan['files']['deployment'] and value['gzip'] == plan['codec'] and
                hash_object(value['protected']) == plan['protected_sha256'])
    if folder == 'snapshot':
        validate_snapshot_archive(value)
        return value['file'] == plan['files']['snapshot'] and value['codec'] == plan['codec']
    keys = {'version', 'scope', 'plan', 'plan_sha256', 'deployment_archive_sha256', 'snapshot_archive_sha256'}
    if (type(value) is not dict or set(value) != keys or type(value['version']) is not int or
            value['version'] != 1 or value['scope'] != SCOPE or
            any(type(value[k]) is not str or not A.SHA.fullmatch(value[k]) for k in
                ('plan_sha256', 'deployment_archive_sha256', 'snapshot_archive_sha256'))):
        raise ValueError('shape')
    validate_plan(value['plan'])
    if hash_object(value['plan']) != value['plan_sha256']:
        raise ValueError('shape')
    return value['plan'] == plan and value['plan_sha256'] == hash_object(plan)


def inspect_execute(plan_sha, plan_json, *, runner=A.run, free=None, budget=None):
    result = inspect_receipt()
    budget = budget or A.Budget()
    try:
        try:
            plan = parse_plan(plan_json, plan_sha)
        except Refused as error:
            raise Refused('PLAN_MISMATCH' if str(error) == 'PLAN_MISMATCH' else 'INPUT_REFUSED') from None
        result['plan_sha256'] = plan_sha
        budget.check()
        protected = A.snapshot(runner)
        result['protected_sha256'] = hash_object(protected)
        result['protected_matches_plan'] = hash_object(protected) == plan['protected_sha256']
        with A.directory(A.ARCHIVE_PARENT, True) as parent, contextlib.ExitStack() as stack:
            parent_meta = A.identity(os.fstat(parent))
            free = free or (lambda: A.free_bytes(parent))
            result['free_before_bytes'] = free()
            fds, dirs, entries, metadata, groups, seen = {}, {}, {}, {}, {}, set()
            def names(fd, folder):
                allowed = set(INSPECT_LAYOUT[folder]) | ({'deployment', 'snapshot'} if folder == 'bundle' else set())
                out = set()
                with os.scandir(fd) as iterator:
                    for entry in iterator:
                        budget.check()
                        seen.add((folder, entry.name))
                        if len(seen) > 16 or len(out) >= 16:
                            raise Refused('ENTRY_LIMIT')
                        if entry.name not in allowed:
                            raise Refused('PATH_REFUSED')
                        out.add(entry.name)
                return out
            def directory_at(container, name, folder):
                try:
                    info = os.stat(name, dir_fd=container, follow_symlinks=False)
                except FileNotFoundError:
                    result['directories'][folder]['present'] = False
                    return
                if (not stat.S_ISDIR(info.st_mode) or info.st_uid != A.ROOT_UID or
                        info.st_gid != A.ROOT_GID or stat.S_IMODE(info.st_mode) != 0o700):
                    raise Refused('PATH_REFUSED')
                fd = os.open(name, DIR_FLAGS, dir_fd=container)
                stack.callback(os.close, fd)
                expected = A.identity(info)
                A.same(fd, expected)
                if expected['device'] != parent_meta['device']:
                    raise Refused('PATH_REFUSED')
                fds[folder], dirs[folder] = fd, (container, name, expected)
                result['directories'][folder].update(present=True, identity_sha256=hash_object(expected))
                entries[folder] = names(fd, folder)
            directory_at(parent, ARCHIVE_NAME, 'bundle')
            if 'bundle' in fds:
                for folder in ('deployment', 'snapshot'):
                    directory_at(fds['bundle'], folder, folder)
            else:
                for folder in ('deployment', 'snapshot'):
                    result['directories'][folder]['present'] = False
            if len({(row[2]['device'], row[2]['inode']) for row in dirs.values()}) != len(dirs):
                raise Refused('PATH_REFUSED')
            for slot, (folder, name) in INSPECT_SLOTS.items():
                budget.check()
                row = result['files'][slot]
                if name not in entries.get(folder, set()):
                    row['present'] = False
                    continue
                info = os.stat(name, dir_fd=fds[folder], follow_symlinks=False)
                value = A.identity(info)
                if (not stat.S_ISREG(info.st_mode) or value['uid'] != A.ROOT_UID or
                        value['gid'] != A.ROOT_GID or value['mode'] != 0o600 or
                        value['links'] not in (1, 2) or value['device'] != parent_meta['device'] or
                        not 0 <= value['size'] <= A.MAX_ARCHIVE or
                        not 0 <= value['allocated_bytes'] < 2 ** 63):
                    raise Refused('PATH_REFUSED')
                metadata[slot] = value
                groups.setdefault((value['device'], value['inode']), []).append(slot)
                row.update(present=True, size=value['size'], allocated_bytes=value['allocated_bytes'],
                           identity_sha256=hash_object(value))
                if name.endswith('.gz'):
                    expected = plan['files'][folder]['gzip_size']
                    row['payload_size_relation'] = 'short' if value['size'] < expected else 'long' if value['size'] > expected else 'equal'
            for slots in groups.values():
                value = metadata[slots[0]]
                if len(slots) == 1 and value['links'] == 1:
                    continue
                pairs = {INSPECT_SLOTS[k] for k in slots}
                folder = INSPECT_SLOTS[slots[0]][0]
                if (value['links'] != 2 or pairs != {(folder, '.manifest.pending'), (folder, 'archive-manifest.json')} or
                        any(metadata[k] != value for k in slots)):
                    raise Refused('PATH_REFUSED')
            parsed, cached, read_bytes = {}, {}, 0
            for slot, value in metadata.items():
                folder, name = INSPECT_SLOTS[slot]
                if name.endswith('.gz'):
                    continue
                budget.check()
                inode = value['device'], value['inode']
                if value['size'] > 65536:
                    raise Refused('MANIFEST_LIMIT')
                if inode not in cached:
                    fd = os.open(name, READ_FLAGS, dir_fd=fds[folder])
                    try:
                        A.same(fd, value)
                        data = os.read(fd, 65537)
                        if len(data) > 65536:
                            raise Refused('MANIFEST_LIMIT')
                        A.same(fd, value)
                    finally:
                        os.close(fd)
                    read_bytes += len(data)
                    if read_bytes > 7 * 65536:
                        raise Refused('MANIFEST_LIMIT')
                    cached[inode] = data
                data = cached[inode]
                row = result['files'][slot]
                row['manifest_sha256'] = A.digest(data)
                try:
                    doc = A.strict_json(data)
                    bound = inspect_manifest(doc, folder, name, plan)
                    row.update(manifest_shape_valid=True, manifest_plan_bound=bound)
                    parsed[slot] = doc
                except (Refused, ValueError, TypeError, KeyError, OverflowError):
                    row.update(manifest_shape_valid=False, manifest_plan_bound=False)
            for folder in INSPECT_LAYOUT:
                a, b = folder + ':.manifest.pending', folder + ':archive-manifest.json'
                if a in metadata and b in metadata:
                    state = 'link_window' if metadata[a] == metadata[b] else 'conflict'
                else:
                    state = 'pending' if a in metadata else 'published' if b in metadata else 'absent'
                result['marker_pairs'][folder] = state
            root_doc = parsed.get('bundle:archive-manifest.json') or parsed.get('bundle:.manifest.pending')
            children = {k: 'archive-manifest.json' if k + ':archive-manifest.json' in parsed else '.manifest.pending'
                        for k in ('deployment', 'snapshot')}
            if root_doc is not None and all(k + ':' + n in parsed for k, n in children.items()):
                result['bundle_child_hashes_match'] = all(root_doc[k + '_archive_sha256'] ==
                    hash_object(parsed[k + ':' + n]) for k, n in children.items())
            ddoc = parsed.get('deployment:archive-manifest.json') or parsed.get('deployment:.manifest.pending')
            copied = result['files']['deployment:source-manifest.json']
            if ddoc is not None and copied['manifest_sha256'] is not None:
                result['deployment_source_manifest_matches'] = ddoc['source_manifest_sha256'] == copied['manifest_sha256']
            # Recheck files before closing each directory over entries and its parent binding.
            for slot, value in metadata.items():
                folder, name = INSPECT_SLOTS[slot]
                if A.identity(os.stat(name, dir_fd=fds[folder], follow_symlinks=False)) != value:
                    raise Refused('SOURCE_CHANGED')
            for folder, (container, name, value) in dirs.items():
                if names(fds[folder], folder) != entries[folder]:
                    raise Refused('SOURCE_CHANGED')
                A.same(fds[folder], value)
                if A.identity(os.stat(name, dir_fd=container, follow_symlinks=False)) != value:
                    raise Refused('SOURCE_CHANGED')
            A.same(parent, parent_meta)
            result['total_allocated_bytes'] = sum(v[2]['allocated_bytes'] for v in dirs.values()) + sum(metadata[v[0]]['allocated_bytes'] for v in groups.values())
            budget.check()
            result['protected_unchanged'] = A.snapshot(runner) == protected
            if not result['protected_unchanged']:
                raise Refused('PROTECTED_CHANGED')
            result['free_after_bytes'] = free()
            result.update(status='observed', reason='METADATA_READY')
    except Refused as error:
        result['reason'] = str(error) if str(error) in INSPECT_REASONS else 'INTERNAL_ERROR'
    except OSError:
        result['reason'] = 'PATH_REFUSED'
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    return validate_inspect_report(result)


def inspect_main(args):
    result = inspect_receipt()
    try:
        if len(args) != 4 or args[0] != 'inspect' or args[2]:
            raise Refused('INPUT_REFUSED')
        if os.geteuid() != A.ROOT_UID:
            raise Refused('NOT_ROOT')
        with hard_deadline(), inspection_lock():
            result = inspect_execute(args[1], args[3])
    except Refused as error:
        result['reason'] = str(error) if str(error) in INSPECT_REASONS else 'INTERNAL_ERROR'
    except OSError:
        result['reason'] = 'PATH_REFUSED'
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    print(A.canonical(validate_inspect_report(result)))
    return 0 if result['status'] == 'observed' else 2


def main(args):
    if args and args[0] == 'finalize':
        return finalize_main(args)
    if args and args[0] == 'inspect':
        return inspect_main(args)
    result = receipt(args[0] if args else 'invalid')
    try:
        if len(args) != 4:
            raise Refused('INPUT_REFUSED')
        if os.geteuid() != A.ROOT_UID:
            raise Refused('NOT_ROOT')
        os.umask(0o077)
        os.nice(19)
        with hard_deadline(), A.deployment_lock():
            result = execute(*args)
    except Refused as error:
        result['reason'] = str(error) if str(error) in REASONS else 'INTERNAL_ERROR'
    except Exception:
        result['reason'] = 'INTERNAL_ERROR'
    print(A.canonical(validate_report(result)))
    return 0 if result['status'] in ('observed', 'planned', 'applied') else 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
