#!/usr/bin/env python3
"""Bounded metadata-only observations; never a proof that a container may stop."""
import argparse
import contextlib
import dataclasses
import datetime
import errno
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import time

MAX_PIDS = 64
MAX_FDS = 4096
MAX_PROC_BYTES = 65536
MAX_FDINFO_BYTES = 4096
MAX_COMMAND_BYTES = 65536
MAX_REPORT_BYTES = 65536
TIME_BUDGET = 10
DATABASES = ('studio_clients.db', 'studio_copy_library.db', 'studio_references.db',
             'studio_feedback.db', 'studio_share.db', 'studio_support.db', 'auth.db', 'categories.db')
DATA_DATABASES = ('auth.db', 'clients.db', 'categories.db', 'copy_library.db', 'references.db',
                  'feedback.db', 'share.db', 'usage.db', 'support.db')
SIDECARS = ('', '-wal', '-shm', '-journal')
CANDIDATES = tuple('/tmp/' + name + suffix for name in DATABASES for suffix in SIDECARS)
KNOWN_FD_PATHS = frozenset(CANDIDATES) | frozenset('/app/data/' + name + suffix
                       for name in DATA_DATABASES for suffix in SIDECARS)
COMM_ALLOWLIST = frozenset(('python', 'python3', 'gunicorn', 'sh', 'bash', 'tini'))
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
INSPECT_TEMPLATE = ('{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},"running":{{json .State.Running}},'
                    '"pid":{{json .State.Pid}},"mounts":[{{range $i,$m := .Mounts}}{{if $i}},{{end}}'
                    '{"type":{{json $m.Type}},"destination":{{json $m.Destination}}}{{end}}]}')


class ObservationError(Exception):
    def __init__(self, code):
        self.code = code


class DeadlineExpired(BaseException):
    """Bypass per-file error handling; a deadline must terminate collection."""


def failure(error):
    if isinstance(error, ObservationError):
        return error.code
    if isinstance(error, FileNotFoundError):
        return 'absent_or_process_exited'
    if isinstance(error, PermissionError):
        return 'permission_denied'
    return 'symlink_or_non_directory_refused' if isinstance(error, OSError) and error.errno in {
        errno.ELOOP, errno.ENOTDIR} else 'metadata_failed'


@dataclasses.dataclass
class CommandResult:
    status: str
    stdout: str = ''


def run_command(argv, timeout):
    """Bound combined streams; raw stderr/exception messages never leave this function."""
    process = None
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=False, start_new_session=True)
        end = time.monotonic() + timeout
        count, chunks = 0, []
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise ObservationError('command_timeout')
                for key, _ in selector.select(remaining):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    count += len(chunk)
                    if count > MAX_COMMAND_BYTES:
                        raise ObservationError('command_output_limit')
                    if key.data:
                        chunks.append(chunk)
        code = process.wait(timeout=max(0.001, end - time.monotonic()))
        return CommandResult('ok' if code == 0 else 'command_failed', b''.join(chunks).decode('utf-8', 'strict') if code == 0 else '')
    except Exception as error:
        return CommandResult(error.code if isinstance(error, ObservationError) else 'command_unavailable_or_failed')
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            process.stdout.close()
            process.stderr.close()


def child_directory(parent, name, stack):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise ObservationError('symlink_or_non_directory_refused')
    fd = os.open(name, DIRECTORY_FLAGS, dir_fd=parent)
    stack.callback(os.close, fd)
    after = os.fstat(fd)
    if (before.st_dev, before.st_ino, before.st_mode) != (after.st_dev, after.st_ino, after.st_mode):
        raise ObservationError('changed_during_query')
    return fd


def bounded_read(parent, name, limit):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ObservationError('proc_file_type_refused')
        chunks, size = [], 0
        while True:
            block = os.read(fd, min(8192, limit + 1 - size))
            if not block:
                return b''.join(chunks).decode('utf-8', 'strict')
            chunks.append(block)
            size += len(block)
            if size > limit:
                raise ObservationError('proc_output_limit')
    finally:
        os.close(fd)


class Proc:
    """Only the Linux /proc root, ns links and fd links are explicit kernel exceptions."""
    def __init__(self, proc_root='/proc'):
        self.proc_root = proc_root  # Non-default values are synthetic-test fixtures only.

    @contextlib.contextmanager
    def process(self, pid):
        if type(pid) is not int or not 0 < pid <= 4294967295:
            raise ObservationError('pid_refused')
        with contextlib.ExitStack() as stack:
            base = os.open(self.proc_root, DIRECTORY_FLAGS)
            stack.callback(os.close, base)
            yield child_directory(base, str(pid), stack)

    def identity(self, pid):
        with self.process(pid) as process:
            raw = bounded_read(process, 'stat', MAX_PROC_BYTES)
            close = raw.rfind(')')
            if close < 0 or raw.split('(', 1)[0].strip() != str(pid):
                raise ObservationError('proc_stat_invalid')
            fields = raw[close + 1:].split()
            if len(fields) < 20 or not fields[1].isdigit() or not fields[19].isdigit():
                raise ObservationError('proc_stat_invalid')
            with contextlib.ExitStack() as stack:
                ns = child_directory(process, 'ns', stack)
                pid_ns, mount_ns = os.stat('pid', dir_fd=ns), os.stat('mnt', dir_fd=ns)
            return {'start_ticks': int(fields[19]), 'ppid': int(fields[1]),
                    'pid_namespace': (pid_ns.st_dev, pid_ns.st_ino),
                    'mount_namespace': (mount_ns.st_dev, mount_ns.st_ino)}

    def candidates(self, pid):
        rows = []
        with self.process(pid) as process, contextlib.ExitStack() as stack:
            # Deliberately follow only this kernel link; all inner components remain no-follow.
            root = os.open('root', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=process)
            stack.callback(os.close, root)
            for index, path in enumerate(CANDIDATES, 1):
                row = {'alias': 'candidate-' + str(index)}
                try:
                    with contextlib.ExitStack() as path_stack:
                        directory = child_directory(root, 'tmp', path_stack)
                        info = os.stat(path.rsplit('/', 1)[1], dir_fd=directory, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode):
                        raise ObservationError('non_regular_or_symlink_refused')
                    row.update(status='ok', device=info.st_dev, inode=info.st_ino,
                               size_bytes=info.st_size, mtime_ns=info.st_mtime_ns,
                               mode=oct(stat.S_IMODE(info.st_mode)), uid=info.st_uid, gid=info.st_gid,
                               links=info.st_nlink)
                except Exception as error:
                    row['status'] = failure(error)
                rows.append(row)
        return rows

    def mountinfo(self, pid):
        with self.process(pid) as process:
            return bounded_read(process, 'mountinfo', MAX_PROC_BYTES)

    def fd_counts(self, pid, known_inodes, deadline, max_fds=MAX_FDS):
        out = dict(status='ok', observed_fds=0, known_db_fds=0, known_db_writable=0,
                   known_db_deleted=0, unclassified_regular_writable=0,
                   unclassified_regular_deleted=0, unclassified_deleted_writable=0, failed_fds=0)
        with self.process(pid) as process, contextlib.ExitStack() as stack:
            descriptors = child_directory(process, 'fd', stack)
            infos = child_directory(process, 'fdinfo', stack)
            with os.scandir(descriptors) as entries:
                for entry in entries:
                    if time.monotonic() >= deadline or out['observed_fds'] >= max_fds:
                        out['status'] = 'limit_incomplete'
                        break
                    if not re.fullmatch(r'[0-9]{1,10}', entry.name):
                        out['status'] = 'invalid_fd_entry'
                        continue
                    out['observed_fds'] += 1
                    try:
                        # Only kernel fd links may be followed, for stat/readlink metadata alone.
                        info = os.stat(entry.name, dir_fd=descriptors)
                        if not stat.S_ISREG(info.st_mode):
                            continue
                        target = os.readlink(entry.name, dir_fd=descriptors)
                        if len(target) > 4096:
                            raise ObservationError('fd_target_limit')
                        raw = bounded_read(infos, entry.name, MAX_FDINFO_BYTES)
                        flags = re.findall(r'^flags:\s*([0-7]{1,12})\s*$', raw, re.MULTILINE)
                        if len(flags) != 1:
                            raise ObservationError('fd_flags_unconfirmed')
                        access = int(flags[0], 8) & os.O_ACCMODE
                        if access not in (os.O_RDONLY, os.O_WRONLY, os.O_RDWR):
                            raise ObservationError('fd_flags_unconfirmed')
                        writable = access in (os.O_WRONLY, os.O_RDWR)
                        deleted = target.endswith(' (deleted)')
                        normalized = target[:-10] if deleted else target
                        after = os.stat(entry.name, dir_fd=descriptors)
                        if (info.st_dev, info.st_ino, info.st_mode) != (after.st_dev, after.st_ino, after.st_mode):
                            raise ObservationError('fd_changed_during_query')
                        known = normalized in KNOWN_FD_PATHS or (info.st_dev, info.st_ino) in known_inodes
                        if known:
                            out['known_db_fds'] += 1
                            out['known_db_writable'] += int(writable)
                            out['known_db_deleted'] += int(deleted)
                        else:
                            out['unclassified_regular_writable'] += int(writable)
                            out['unclassified_regular_deleted'] += int(deleted)
                            out['unclassified_deleted_writable'] += int(deleted and writable)
                    except Exception:
                        out['failed_fds'] += 1
                        out['status'] = 'partial'
        if out['known_db_deleted'] or out['unclassified_regular_writable'] or out['unclassified_regular_deleted']:
            out['status'] = 'unresolved_open_files'
        return out


def mount_summary(raw, declared):
    """Longest mountpoint for /tmp and every fixed candidate, including nested mounts."""
    mounts = []
    try:
        for line in raw.splitlines():
            fields, filesystem = line.split(' - ', 1)
            fields = fields.split()
            if len(fields) < 6:
                raise ValueError()
            point = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[4])
            if not point.startswith('/') or '\\' in point or '\x00' in point:
                raise ValueError()
            mounts.append((point.rstrip('/') or '/', filesystem.split()[0]))
        if not any(point == '/' for point, _ in mounts):
            raise ValueError()
        out = []
        for index, path in enumerate(('/tmp',) + CANDIDATES):
            covers = lambda point: point == '/' or path == point or path.startswith(point + '/')
            point, fs = max((m for m in mounts if covers(m[0])), key=lambda m: len(m[0]))
            declarations = [(m['destination'], m['type']) for m in declared if covers(m['destination'])]
            declared_type = max(declarations, key=lambda m: len(m[0]))[1] if declarations else None
            out.append({'alias': 'tmp' if index == 0 else 'candidate-' + str(index),
                        'memory_backed': True if fs in {'tmpfs', 'ramfs'} else None,
                        'declared_bind': declared_type == 'bind' if declared_type is not None else None,
                        'effective_filesystem': fs if fs in {'tmpfs', 'ramfs', 'overlay', 'ext4', 'xfs'} else 'other',
                        'persistence_after_stop': 'unverified'})
        return {'status': 'ok', 'paths': out}
    except Exception:
        return {'status': 'unknown', 'paths': []}


class Preflight:
    def __init__(self, runner=run_command, proc=None, time_budget=TIME_BUDGET):
        self.runner, self.proc = runner, proc or Proc()
        self.deadline = time.monotonic() + min(time_budget, TIME_BUDGET)

    def command(self, argv):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise ObservationError('time_limit')
        result = self.runner(argv, min(remaining, TIME_BUDGET))
        if result.status != 'ok':
            raise ObservationError(result.status if result.status in {
                'command_failed', 'command_timeout', 'command_output_limit', 'command_unavailable_or_failed'} else 'command_failed')
        if len(result.stdout.encode('utf-8')) > MAX_COMMAND_BYTES:
            raise ObservationError('command_output_limit')
        return result.stdout

    def inspect(self, container, image, pid):
        raw = json.loads(self.command(['docker', 'inspect', '--format', INSPECT_TEMPLATE, container]))
        if (not isinstance(raw, dict) or raw.get('name') != '/content-studio'
                or type(raw.get('pid')) is not int or raw.get('running') is not True
                or (raw.get('id'), raw.get('image'), raw.get('pid')) != (container, image, pid)):
            raise ObservationError('container_identity_unconfirmed')
        mounts = raw.get('mounts')
        if not isinstance(mounts, list) or len(mounts) > 128 or any(
                not isinstance(m, dict) or m.get('type') not in {'bind', 'volume', 'tmpfs'}
                or not isinstance(m.get('destination'), str) or not m['destination'].startswith('/')
                or any(part in {'.', '..'} for part in m['destination'].split('/'))
                or '\x00' in m['destination'] or '\\' in m['destination'] for m in mounts):
            raise ObservationError('mounts_unconfirmed')
        return sorted(({'type': m['type'], 'destination': m['destination']} for m in mounts), key=lambda m: (m['destination'], m['type']))

    def workers(self, container, init_pid):
        lines = self.command(['docker', 'top', container, '-eo', 'pid,ppid,comm']).splitlines()
        if not lines or lines[0].split()[:2] != ['PID', 'PPID']:
            raise ObservationError('top_unconfirmed')
        workers, seen = [], set()
        for line in lines[1:]:
            fields = line.split(None, 2)
            if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
                raise ObservationError('top_unconfirmed')
            pid, ppid = int(fields[0]), int(fields[1])
            if not 0 < pid <= 4294967295 or ppid > 4294967295 or pid in seen:
                raise ObservationError('top_unconfirmed')
            seen.add(pid)
            workers.append((pid, ppid, fields[2] if fields[2] in COMM_ALLOWLIST else 'other'))
        if init_pid not in seen:
            raise ObservationError('init_missing_from_top')
        return sorted(workers)

    def collect(self, container, image, init_pid):
        report = {'read_only': True, 'status': 'incomplete',
                  'collected_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'effective_database_paths': 'unknown_environment_overrides_not_read',
                  'writer_absence': 'unverified_even_if_observed_counts_are_zero',
                  'stop_safety': 'not_determined', 'candidate_files': [], 'processes': []}
        try:
            if not re.fullmatch(r'[0-9a-f]{64}', container or '') or not re.fullmatch(r'sha256:[0-9a-f]{64}', image or ''):
                raise ObservationError('request_refused')
            if type(init_pid) is not int or not 0 < init_pid <= 4294967295:
                raise ObservationError('request_refused')
            declared = self.inspect(container, image, init_pid)
            initial = self.proc.identity(init_pid)
            workers = self.workers(container, init_pid)
            report['worker_limit_exceeded'] = len(workers) > MAX_PIDS
            report['reported_pid_count'] = len(workers)
            report['candidate_files'] = self.proc.candidates(init_pid)
            report['tmp_mounts'] = mount_summary(self.proc.mountinfo(init_pid), declared)
            known = {(row['device'], row['inode']) for row in report['candidate_files'] if row['status'] == 'ok'}
            partial = report['worker_limit_exceeded'] or report['tmp_mounts']['status'] != 'ok' or any(
                row['status'] not in {'ok', 'absent_or_process_exited'} for row in report['candidate_files'])
            for pid, ppid, comm in workers[:MAX_PIDS]:
                row = {'pid': pid, 'ppid': ppid, 'executable_basename': comm}
                try:
                    if time.monotonic() >= self.deadline:
                        raise ObservationError('time_limit')
                    before = self.proc.identity(pid)
                    if any(before[key] != initial[key] for key in ('pid_namespace', 'mount_namespace')) or before['ppid'] != ppid:
                        raise ObservationError('worker_identity_unconfirmed')
                    counts = self.proc.fd_counts(pid, known, self.deadline)
                    if self.proc.identity(pid) != before:
                        raise ObservationError('process_identity_changed')
                    row.update(status=counts['status'], start_ticks=before['start_ticks'],
                               pid_namespace=list(before['pid_namespace']), mount_namespace=list(before['mount_namespace']), fd=counts)
                except Exception as error:
                    row['status'] = failure(error)
                partial |= row['status'] != 'ok'
                report['processes'].append(row)
            if (self.proc.identity(init_pid) != initial or self.inspect(container, image, init_pid) != declared
                    or self.workers(container, init_pid) != workers):
                raise ObservationError('container_or_init_changed')
            report['status'] = 'incomplete' if partial else 'bounded_observations_complete'
        except Exception as error:
            report.update(status='incomplete', error=failure(error), candidate_files=[], processes=[])
            report.pop('tmp_mounts', None)
        return report


def main():
    class PrivateParser(argparse.ArgumentParser):
        def error(self, message):
            self.exit(2, 'request_refused\n')  # argparse's default echoes arbitrary rejected values.
    parser = PrivateParser(description='Explicitly pinned content container metadata preflight; no app/DB reads.')
    parser.add_argument('--container-id', required=True)
    parser.add_argument('--expected-image', required=True)
    parser.add_argument('--expected-init-pid', type=int, required=True)
    args = parser.parse_args()
    def timeout(*_):
        raise DeadlineExpired()
    previous = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, TIME_BUDGET)
    try:
        result = Preflight().collect(args.container_id, args.expected_image, args.expected_init_pid)
    except DeadlineExpired:
        result = {'read_only': True, 'status': 'incomplete', 'error': 'time_limit',
                  'effective_database_paths': 'unknown_environment_overrides_not_read',
                  'writer_absence': 'unverified_even_if_observed_counts_are_zero', 'stop_safety': 'not_determined'}
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    encoded = json.dumps(result, separators=(',', ':'), ensure_ascii=True)
    if len(encoded.encode('ascii')) > MAX_REPORT_BYTES:
        result = {'read_only': True, 'status': 'incomplete', 'error': 'report_output_limit',
                  'effective_database_paths': 'unknown_environment_overrides_not_read',
                  'writer_absence': 'unverified_even_if_observed_counts_are_zero', 'stop_safety': 'not_determined'}
        encoded = json.dumps(result)
    print(encoded)
    return 0 if result['status'] == 'bounded_observations_complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
