#!/usr/bin/env python3
"""One reviewed frozen continuation. Old evidence is immutable; only ciphertext leaves.

The original apps stay paused. There is no retry/reset or state-changing Docker command.
"""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import resource
import selectors
import signal
import stat
import subprocess
import sys
import time
import types

BASE = '/root/.metainc-retirement-transfer'
RECIPIENT = '78076C3BC580EB5AC684EDE8BE5DAF3D1B780CA5'
PUBLIC_HASH = '1c680db160149e83e04983c6f74a5c696c473fa9d921e956b14a7c908fd667a3'
HOSTS_HASH = '263a7fd1c7fe50257fec9223c4cb2015d4e4ff575c0f8c7d362225c589204675'
HOST_FINGERPRINT = 'j9NJSZdOiJNqeSzDFbu6FVlhMJFGb4B6byavrDoG+bg'
MAX_CIPHER = 2300300288
MAX_STDERR = 65536
MAX_RECEIPT = 1024
DEADLINE = 2400
BINARIES = {'docker': '/usr/bin/docker', 'gpg': '/usr/bin/gpg', 'ssh': '/usr/bin/ssh',
            'keygen': '/usr/bin/ssh-keygen'}
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
KEY = 'source-transport-key'
PUBLIC_ASSET = 'recovery-public.asc'
HOSTS_ASSET = 'server-b-known-hosts'
HEX = re.compile(r'[0-9a-f]{64}\Z')
SESSION = 'data-snapshot-continuation-20261102-v1'
SNAPSHOT_SESSION = 'data-snapshot-20261102-v1'
COMMAND = 'receive-data-snapshot-continuation-20261102-v1'
OLD_DIRECTORY = BASE + '/' + SNAPSHOT_SESSION
FAILED_RUN = '41412005422-1'
CLEANUP_RUN = '41412844116-1'
FAILED_SHA256 = '7df76d66ee23ecf1dd27acff5b1c42099ad546199f348f75dc17e1bfc22d0a9f'
FAILED_BYTES = 410
MAX_ARCHIVE = 2283523072
MAX_SOURCE = 2 * 1024 ** 3
MAX_OBJECTS = 100080
# Root pins exact reviewed artifacts before execution. All-zero pins refuse loading.
MODULES = {
    'preflight': ('retirement_data_preflight.py', '562582ebf91b82c84f6a728bd2fd2afd9a7cc59d8346deb40b110c20578fec8c'),
    'archive': ('retirement_data_archive.py', 'd1e61d7a51e1ec955625ef03ce312cf5299630718615479bd20d09a0630ad269'),
    'control': ('retirement_control_preflight.py', '16483b62c97d6780e8a7b04ffde9a445aa8b14f75b8f2a29ca6285036238dcb0'),
}
CONTROL_POLICY = {'request': {'ad': {'id': '6f37ec7da0dea75b4630fd177ff0f51ae0087e6b310d68df5a6e6803c015890f', 'pid': 1679637}, 'content': {'id': '740ea62adf12d41571a1297ea4bb623ca62177f1c4def4d2c290f7b5ee07c9b5', 'pid': 1669091}}, 'files': [{'aliases': ['ad'], 'enabled_paths': ['/etc/nginx/sites-enabled/ad.metainc.co.kr'], 'locations': [{'end': 745, 'modifier': '', 'path': '/', 'sha256': '375cef8b18bbe4ee9d11c3fcdbddd36e330512ca224de8c17ec0346201b7e967', 'start': 422}], 'matching_servers': 1, 'metadata': {'bytes': 4700, 'device': 64769, 'gid': 0, 'inode': 917201, 'links': 1, 'mode': 420, 'uid': 0}, 'protected_bytes_sha256': '4878a9972995b66863aa5b9ac8134fb7bab0bef3a99fbd263d5d421fde5ce990', 'protected_locations': [{'end': 1992, 'modifier': '=', 'path': '/naver', 'sha256': 'c29741ab74b50d2179157602480e5db9c5099192455f73844c6109341eff97f9', 'start': 1221}, {'end': 2770, 'modifier': '^~', 'path': '/naver/', 'sha256': 'da371418392851ab2f0a8f2d6c5c74d5034b3a3f1ad424fb0fb2f6a5a480f8b3', 'start': 1997}, {'end': 3555, 'modifier': '=', 'path': '/api/naver-auto', 'sha256': '779f650946aeaa333da7c8ba6fdc779d1c548fc65298142af9e872c5137afa5d', 'start': 2775}, {'end': 4342, 'modifier': '^~', 'path': '/api/naver-auto/', 'sha256': '07fcc86d58e48eebd268210f1416e259597b1923204a9d53eae39c123f65d819', 'start': 3560}], 'resolved_path': '/etc/nginx/sites-available/ad.metainc.co.kr', 'sha256': 'f48e0a389974d3b070f9c132d65bf9a776f289541ac5def778936496cd11a89c'}, {'aliases': ['logic'], 'enabled_paths': ['/etc/nginx/sites-enabled/logic-analysis'], 'locations': [{'end': 1464, 'modifier': '=', 'path': '/autobid', 'sha256': 'aead532583115a336d5786a7c37370f64937addf9f9e2e094d1c6e5d7d41ef6a', 'start': 1419}, {'end': 1730, 'modifier': '', 'path': '/autobid/', 'sha256': 'c5df16221f8339254fdbc56827dc8d060be14ed614a89ee8da2dc3eff75b648e', 'start': 1469}, {'end': 3036, 'modifier': '', 'path': '/studio/', 'sha256': '83ed22a01d892d593f7b99fb6dd4a8cd6da8e94c5c170e15b85f2c21c549f407', 'start': 2370}, {'end': 3096, 'modifier': '=', 'path': '/studio', 'sha256': '37f35efee5a022d8da4eba70d180903e258e62c87b1cb0e10ba9e34c09cad45f', 'start': 3041}], 'matching_servers': 1, 'metadata': {'bytes': 3099, 'device': 64769, 'gid': 0, 'inode': 917065, 'links': 1, 'mode': 420, 'uid': 0}, 'protected_bytes_sha256': '892890bfb2ed64ac46ca8f5ca941454e254f2b2e9b82b7de1439c7f36fcb9c93', 'protected_locations': [], 'resolved_path': '/etc/nginx/sites-enabled/logic-analysis', 'sha256': 'a8c1a4f6e2c2012aacdf73ba04dd0082ad8c0eeb5685b43e345d838e2b1e3aea'}, {'aliases': ['studio'], 'enabled_paths': ['/etc/nginx/sites-enabled/studio.metainc.co.kr.conf'], 'locations': [{'end': 891, 'modifier': '', 'path': '/', 'sha256': '3fba238fa0f3633f14fc74d726331aa3e292e582e936fbab854b0cb87bb1558b', 'start': 235}], 'matching_servers': 1, 'metadata': {'bytes': 894, 'device': 64769, 'gid': 0, 'inode': 947735, 'links': 1, 'mode': 420, 'uid': 0}, 'protected_bytes_sha256': '1d93ca0b112f10f5cbcf992a1023cf7e850c3b0293a63477087cd39a326002c4', 'protected_locations': [], 'resolved_path': '/etc/nginx/sites-available/studio.metainc.co.kr.conf', 'sha256': '4db230394a0609739da7516084e3a2b7960cc8a8056914d1d804c5a12f4ecf22'}]}
OPERATOR_EVIDENCE_SHA256 = '9069e12e55d6c2a3b9ade3ef95b451d3ed6aac084a5e32319948b59a556455ba'
# Set only after the completed fence journal has been independently reviewed.
RESTART_EVIDENCE = {'sha256': '49176980546cbbf81adfd9597e598ebadfe1e7970356c21bac25ad3180c1ddbd', 'operator_evidence_sha256': '9069e12e55d6c2a3b9ade3ef95b451d3ed6aac084a5e32319948b59a556455ba', 'control_policy_sha256': '7d37230c3c52038d2182506804301b1e090eca2f68cbd146438983b73ebf5dca'}
ERRORS = frozenset(('invalid_phase', 'root_required', 'unsafe_path', 'path_changed',
    'session_exists', 'session_missing', 'file_exists', 'file_missing', 'file_too_large',
    'lock_busy', 'dependency_failed', 'command_failed', 'command_limit', 'deadline_exceeded',
    'asset_invalid', 'recipient_invalid', 'image_invalid', 'space_insufficient',
    'daemon_unverified', 'public_key_invalid', 'not_prepared', 'attempt_exists',
    'session_closed', 'receipt_invalid', 'pipeline_failed', 'cipher_limit',
    'pipe_failed', 'attempt_not_terminal', 'interrupted', 'internal_failure',
    'module_refused', 'policy_unresolved', 'controls_changed', 'operator_evidence_refused', 'archive_failed', 'old_attempt_refused', 'old_transport_not_closed'))


# Static reviewed archive failure labels only; private exception messages never cross the pipe.
PRODUCER_CODES = frozenset(('archive_incomplete', 'archive_size_limit', 'archive_timeout', 'async_io_uncovered', 'cgroup_tasks_changed', 'cgroup_unconfirmed', 'configuration_changed', 'configuration_limit', 'configuration_missing', 'configuration_unconfirmed', 'content_changed', 'coverage_incomplete', 'data_size_limit', 'deleted_changed', 'deleted_limit', 'deleted_uncovered', 'direct_io_uncovered', 'directory_changed', 'encrypted_pipe_failed', 'encrypted_pipe_required', 'entry_limit', 'fd_limit', 'file_changed', 'filesystem_boundary', 'final_guard_changed', 'freeze_changed', 'link_or_special_uncovered', 'manifest_size_limit', 'mapping_changed', 'mapping_unpinned', 'name_uncovered', 'nested_cgroup_uncovered', 'not_frozen', 'preflight_contract_refused', 'privilege_or_platform_refused', 'process_changed', 'regular_file_uncovered', 'request_refused', 'restart_evidence_unconfirmed', 'thread_set_unconfirmed', 'tree_changed'))
PRODUCER_COMMAND_CODES = frozenset(('command_failed', 'command_limit', 'deadline_exceeded', 'interrupted'))
PRODUCER_CODES = PRODUCER_CODES | PRODUCER_COMMAND_CODES
ERRORS = ERRORS | frozenset('producer_' + code for code in PRODUCER_CODES)


class Refused(Exception):
    def __init__(self, code, process_rc=None):
        self.code = code if code in ERRORS else 'internal_failure'
        self.process_rc = process_rc


class Unfinished(Refused):
    def __init__(self):
        super().__init__('attempt_not_terminal')


def output(phase):
    return {'phase': phase, 'status': 'failed', 'session': SESSION, 'error': None,
            'ssh_public_key': None, 'bytes': None, 'sha256': None, 'process_rc': None,
            'backup_verified': False, 'source_bytes': None, 'archive_bytes': None,
            'object_count': None, 'paused': {'ad': 'not_observed', 'content': 'not_observed'},
            'operator_evidence_sha256': None, 'run': None}


def identity(value):
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        if len(data.splitlines()) != 1:
            raise ValueError()
        return json.loads(data, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise Refused('receipt_invalid')


def exact_json(actual, expected):
    # Preserve JSON types: bool and int compare equal in Python but not in evidence.
    return json.dumps(actual, sort_keys=True, separators=(',', ':'), allow_nan=False) == json.dumps(
        expected, sort_keys=True, separators=(',', ':'), allow_nan=False)


class Files:
    """Alternate root/owner are synthetic-fixture seams, never CLI inputs."""
    def __init__(self, root='/', owner=0):
        self.root, self.owner = root, owner
        self.path = BASE + '/' + SESSION

    @contextlib.contextmanager
    def directory(self, path):
        if not path.startswith('/') or '..' in path.split('/'):
            raise Refused('unsafe_path')
        with contextlib.ExitStack() as stack:
            fd = os.open(self.root, DIR_FLAGS)
            stack.callback(os.close, fd)
            chain = []
            for name in filter(None, path.split('/')):
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                allowed_tmp = not chain and name == 'tmp' and bool(before.st_mode & stat.S_ISVTX)
                if (not stat.S_ISDIR(before.st_mode) or before.st_uid != self.owner or
                        (before.st_mode & 0o022 and not allowed_tmp)):
                    raise Refused('unsafe_path')
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                stack.callback(os.close, child)
                if identity(before) != identity(os.fstat(child)):
                    raise Refused('path_changed')
                chain.append((fd, name, child, identity(before)))
                fd = child
            yield fd
            for parent, name, child, expected in chain:
                if (identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected or
                        identity(os.fstat(child)) != expected):
                    raise Refused('path_changed')

    @contextlib.contextmanager
    def parent(self, path):
        parent, name = path.rsplit('/', 1)
        if not name or name in ('.', '..'):
            raise Refused('unsafe_path')
        with self.directory(parent or '/') as fd:
            yield fd, name

    def mkdir(self, path, existing=False):
        with self.parent(path) as (fd, name):
            try:
                os.mkdir(name, mode=0o700, dir_fd=fd)
            except FileExistsError:
                if not existing:
                    raise Refused('session_exists')
            value = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode) or value.st_uid != self.owner or stat.S_IMODE(value.st_mode) != 0o700:
                raise Refused('unsafe_path')

    def metadata(self, path, mode=None):
        with self.parent(path) as (fd, name):
            value = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (not stat.S_ISREG(value.st_mode) or value.st_uid != self.owner or value.st_nlink != 1 or
                    value.st_mode & 0o022 or (mode is not None and stat.S_IMODE(value.st_mode) != mode)):
                raise Refused('unsafe_path')
            return value

    def exists(self, name):
        with self.directory(self.path) as fd:
            try:
                os.stat(name, dir_fd=fd, follow_symlinks=False)
                return True
            except FileNotFoundError:
                return False

    def read(self, path, limit, mode=None):
        with self.parent(path) as (parent, name):
            before = self.metadata(path, mode)
            fd = os.open(name, READ_FLAGS, dir_fd=parent)
            try:
                if identity(os.fstat(fd)) != identity(before):
                    raise Refused('path_changed')
                data = b''
                while True:
                    chunk = os.read(fd, min(8192, limit + 1 - len(data)))
                    data += chunk
                    if len(data) > limit:
                        raise Refused('file_too_large')
                    if not chunk:
                        break
                after = os.fstat(fd)
                linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (identity(after) != identity(before) or identity(linked) != identity(before) or
                        (after.st_size, after.st_mtime_ns, after.st_ctime_ns) !=
                        (before.st_size, before.st_mtime_ns, before.st_ctime_ns)):
                    raise Refused('path_changed')
                return data
            finally:
                os.close(fd)

    def write(self, name, data):
        with self.directory(self.path) as parent:
            try:
                fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
            except FileExistsError:
                raise Refused('file_exists')
            try:
                view = memoryview(data)
                while view:
                    count = os.write(fd, view)
                    if count <= 0:
                        raise Refused('internal_failure')
                    view = view[count:]
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)

    def record(self, name, data):
        self.write(name, json.dumps(data, separators=(',', ':')).encode())

    def json(self, name):
        return strict_json(self.read(self.path + '/' + name, 4096, 0o600))

    @contextlib.contextmanager
    def lock(self, create=False):
        with self.directory(self.path) as parent:
            if stat.S_IMODE(os.fstat(parent).st_mode) != 0o700:
                raise Refused('unsafe_path')
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            fd = os.open('phase.lock', flags, 0o600, dir_fd=parent)
            try:
                value = os.fstat(fd)
                if (not stat.S_ISREG(value.st_mode) or value.st_uid != self.owner or
                        value.st_nlink != 1 or stat.S_IMODE(value.st_mode) != 0o600):
                    raise Refused('unsafe_path')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Refused('lock_busy')
                yield
            finally:
                os.close(fd)

    def chmod_key(self, name):
        # Only a just-generated public transport key may start at 0644.
        with self.directory(self.path) as parent:
            before = self.metadata(self.path + '/' + name)
            fd = os.open(name, READ_FLAGS, dir_fd=parent)
            try:
                if identity(os.fstat(fd)) != identity(before):
                    raise Refused('path_changed')
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)

    def remove_key(self, name):
        if name not in (KEY, KEY + '.pub'):
            raise Refused('unsafe_path')
        with self.directory(self.path) as parent:
            try:
                before = self.metadata(self.path + '/' + name, 0o600)
            except FileNotFoundError:
                return
            if identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != identity(before):
                raise Refused('path_changed')
            os.unlink(name, dir_fd=parent)
            os.fsync(parent)

    def free(self, path):
        with self.directory(path) as fd:
            value = os.fstatvfs(fd)
            return value.f_bavail * value.f_frsize

    def filesystem(self, path):
        with self.directory(path) as fd:
            value, metadata = os.fstatvfs(fd), os.fstat(fd)
            available = value.f_bavail * value.f_frsize
            if not 0 <= available < 2**63 or not 0 <= metadata.st_dev < 2**63:
                raise Refused('daemon_unverified')
            return {'device': metadata.st_dev, 'available_bytes': available}

    @contextlib.contextmanager
    def export_lock(self):
        """The same fixed lock also excludes simultaneous remaining-image operations."""
        with self.directory(BASE) as folder:
            if stat.S_IMODE(os.fstat(folder).st_mode) != 0o700:
                raise Refused('unsafe_path')
            name = 'remaining-images.lock'
            try:
                before = os.stat(name, dir_fd=folder, follow_symlinks=False)
            except FileNotFoundError:
                before = None
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if before is None:
                flags |= os.O_CREAT | os.O_EXCL
            fd = os.open(name, flags, 0o600, dir_fd=folder)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner or
                        info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or
                        (before is not None and identity(before) != identity(info))):
                    raise Refused('unsafe_path')
                expected = identity(info)
                if identity(os.stat(name, dir_fd=folder, follow_symlinks=False)) != expected:
                    raise Refused('path_changed')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Refused('lock_busy')
                yield
                linked = os.stat(name, dir_fd=folder, follow_symlinks=False)
                if identity(linked) != expected or linked.st_nlink != 1:
                    raise Refused('path_changed')
            finally:
                os.close(fd)


def replace_handlers(handler):
    numbers = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, numbers)
    try:
        return {number: signal.signal(number, handler) for number in numbers}
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def restore_handlers(previous):
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, tuple(previous))
    try:
        for number, handler in previous.items():
            signal.signal(number, handler)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, mask)


def terminate(processes):
    previous = replace_handlers(signal.SIG_IGN)
    uncertain = False
    try:
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except OSError:
                    # macOS can return EPERM when the just-exited group disappeared.
                    # Do not abandon the other children; only tolerate a reaped PID.
                    if process.poll() is None:
                        uncertain = True
        end = time.monotonic() + 2
        for process in processes:
            try:
                process.wait(timeout=max(.01, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    if process.poll() is None:
                        uncertain = True
                try:
                    process.wait(timeout=2)
                except Exception:
                    uncertain = True
            except Exception:
                uncertain = True
        if uncertain:
            raise Unfinished()
    finally:
        restore_handlers(previous)


def close_streams(processes):
    for process in processes:
        for stream in (process.stdin, process.stdout, process.stderr, getattr(process, "control", None)):
            if stream is not None and not stream.closed:
                stream.close()


def spawn_registered(factory, processes):
    """Defer handled signals until a newly created child is owned by cleanup."""
    pending = []
    def deferred(number, frame):
        pending.append(number)
    previous = replace_handlers(deferred)
    try:
        process = factory(previous, pending)
        processes.append(process)
    finally:
        restore_handlers(previous)
    if pending:
        raise Refused('interrupted')
    return process


def command(argv, limit=4096, timeout=20):
    processes = []
    try:
        process = spawn_registered(lambda previous, pending: subprocess.Popen(argv,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=ENV, shell=False, start_new_session=True), processes)
        out, errors = bytearray(), 0
        end = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, True)
            selector.register(process.stderr, selectors.EVENT_READ, False)
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise Refused('deadline_exceeded')
                for key, _ in selector.select(min(remaining, .2)):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data:
                        out.extend(chunk)
                        if len(out) > limit:
                            raise Refused('command_limit')
                    else:
                        errors += len(chunk)
                        if errors > MAX_STDERR:
                            raise Refused('command_limit')
        if process.wait(timeout=max(.01, end - time.monotonic())) != 0:
            raise Refused('command_failed')
        return bytes(out)
    except subprocess.TimeoutExpired:
        raise Refused('deadline_exceeded')
    finally:
        try:
            terminate(processes)
        finally:
            close_streams(processes)


def stream_archive(archive, preflight, request, gpg, ssh, max_cipher=MAX_CIPHER, timeout=DEADLINE, restart_evidence=None):
    """Only ciphertext enters the parent. Forked producer uses a dedicated inherited pipe."""
    processes = []
    failure = None
    end = time.monotonic() + timeout
    try:
        producer = spawn_registered(lambda previous, pending: start_archive(
            archive, preflight, request, previous, pending, restart_evidence), processes)
        encryptor = spawn_registered(lambda previous, pending: subprocess.Popen(gpg,
            stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=ENV, shell=False, start_new_session=True), processes)
        producer.stdout.close()
        transport = spawn_registered(lambda previous, pending: subprocess.Popen(ssh,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=ENV, shell=False, start_new_session=True), processes)
        digest, size, errors, receipt = hashlib.sha256(), 0, 0, bytearray()
        pending, eof, cipher_registered, writable = bytearray(), False, True, False
        summary = bytearray()
        with selectors.DefaultSelector() as selector:
            for process in processes:
                if process.stderr is not None:
                    os.set_blocking(process.stderr.fileno(), False)
                    selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            os.set_blocking(producer.control.fileno(), False)
            selector.register(producer.control, selectors.EVENT_READ, 'summary')
            os.set_blocking(encryptor.stdout.fileno(), False)
            os.set_blocking(transport.stdout.fileno(), False)
            os.set_blocking(transport.stdin.fileno(), False)
            selector.register(encryptor.stdout, selectors.EVENT_READ, 'cipher')
            selector.register(transport.stdout, selectors.EVENT_READ, 'receipt')
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise Refused('deadline_exceeded')
                for key, _ in selector.select(min(remaining, .2)):
                    if key.data == 'send':
                        try:
                            sent = os.write(key.fd, pending)
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            raise Refused('pipe_failed')
                        if sent <= 0:
                            raise Refused('pipe_failed')
                        del pending[:sent]
                        if not pending:
                            selector.unregister(transport.stdin)
                            writable = False
                            if eof:
                                transport.stdin.close()
                        if not eof and not cipher_registered and len(pending) < 262144:
                            selector.register(encryptor.stdout, selectors.EVENT_READ, 'cipher')
                            cipher_registered = True
                        continue
                    try:
                        chunk = os.read(key.fd, 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        if key.data == 'cipher':
                            eof, cipher_registered = True, False
                            if not pending:
                                transport.stdin.close()
                        continue
                    if key.data == 'stderr':
                        errors += len(chunk)
                        if errors > MAX_STDERR:
                            raise Refused('command_limit')
                    elif key.data == 'summary':
                        summary.extend(chunk)
                        if len(summary) > 1024:
                            raise Refused('archive_failed')
                    elif key.data == 'receipt':
                        receipt.extend(chunk)
                        if len(receipt) > MAX_RECEIPT:
                            raise Refused('receipt_invalid')
                    else:
                        size += len(chunk)
                        if size > max_cipher:
                            raise Refused('cipher_limit')
                        digest.update(chunk)
                        pending.extend(chunk)
                        if not writable:
                            selector.register(transport.stdin, selectors.EVENT_WRITE, 'send')
                            writable = True
                        if len(pending) >= 262144:
                            selector.unregister(encryptor.stdout)
                            cipher_registered = False
        codes = {name: process.wait(timeout=max(.01, end - time.monotonic()))
                 for name, process in zip(('archive', 'gpg', 'ssh'), processes)}
        if codes['archive'] != 0:
            try:
                failed = strict_json(summary)
            except Refused:
                failed = None
            if (isinstance(failed, dict) and set(failed) == {'status', 'session', 'error'} and
                    failed['status'] == 'failed' and failed['session'] == SNAPSHOT_SESSION):
                if failed['error'] == 'attempt_not_terminal':
                    raise Unfinished()
                if isinstance(failed['error'], str) and failed['error'] in PRODUCER_CODES:
                    raise Refused('producer_' + failed['error'])
        if any(code != 0 for code in codes.values()) or not eof or pending or size == 0:
            raise Refused('pipeline_failed')
        remote = strict_json(receipt)
        if (not isinstance(remote, dict) or set(remote) != {'status', 'bytes', 'sha256'} or
                remote['status'] != 'received_unverified' or type(remote['bytes']) is not int or
                remote['bytes'] != size or remote['sha256'] != digest.hexdigest()):
            raise Refused('receipt_invalid')
        proof = strict_json(summary)
        if (not isinstance(proof, dict) or set(proof) != {'status', 'session', 'archive_bytes', 'object_count', 'source_bytes', 'application_restore_verified'} or
                proof['status'] != 'archive_stream_complete' or proof['session'] != SNAPSHOT_SESSION or proof['application_restore_verified'] is not False or
                any(type(proof[key]) is not int or not 0 < proof[key] <= limit for key, limit in
                    (('archive_bytes', MAX_ARCHIVE), ('source_bytes', MAX_SOURCE), ('object_count', MAX_OBJECTS))) or
                proof['archive_bytes'] < 1024 or proof['archive_bytes'] % 512 or proof['archive_bytes'] < proof['source_bytes']):
            raise Refused('archive_failed')
        return {'bytes': size, 'sha256': digest.hexdigest(), 'process_rc': codes,
                **{key: proof[key] for key in ('archive_bytes', 'source_bytes', 'object_count')}}
    except subprocess.TimeoutExpired:
        failure = Refused('deadline_exceeded')
    except BaseException as error:
        failure = error
    finally:
        try:
            terminate(processes)
        except BaseException as error:
            failure = error
        finally:
            close_streams(processes)
        if failure is not None:
            codes = {name: None for name in ('archive', 'gpg', 'ssh')}
            for name, process in zip(codes, processes):
                code = process.returncode
                if type(code) is int and -255 <= code <= 255:
                    codes[name] = code
            if not isinstance(failure, Refused):
                failure = Refused('internal_failure')
            failure.process_rc = codes
            raise failure from None


def public_key(data):
    try:
        parts = data.decode('ascii').strip().split()
        if len(parts) != 2 or parts[0] != 'ssh-ed25519':
            raise ValueError()
        raw = base64.b64decode(parts[1], validate=True)
        if len(raw) != 51 or raw[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
            raise ValueError()
        return ' '.join(parts)
    except (ValueError, UnicodeError):
        raise Refused('public_key_invalid')



def load_modules(directory, files):
    """Compile only bytes read once from fixed files and matched to reviewed pins."""
    result = {}
    for alias, (name, digest) in MODULES.items():
        if not HEX.fullmatch(digest) or digest == '0' * 64:
            raise Refused('module_refused')
        body = files.read(directory + '/' + name, 262144, 0o600)
        if hashlib.sha256(body).hexdigest() != digest:
            raise Refused('module_refused')
        module = types.ModuleType('_retirement_data_' + alias + '_' + digest)
        module.__file__ = directory + '/' + name
        exec(compile(body, module.__file__, 'exec'), module.__dict__)
        result[alias] = module
    if (result['archive'].SESSION != SNAPSHOT_SESSION or result['archive'].MAX_ARCHIVE != MAX_ARCHIVE or
            result['archive'].MAX_BYTES != MAX_SOURCE):
        raise Refused('module_refused')
    return result


class ArchiveProcess:
    """Minimal wait/reap adapter; child inherits immutable checked module snapshots."""
    def __init__(self, pid, plain, control):
        self.pid, self.returncode = pid, None
        self.stdin, self.stderr = None, None
        self.stdout, self.control = os.fdopen(plain, 'rb', buffering=0), os.fdopen(control, 'rb', buffering=0)

    def poll(self):
        if self.returncode is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.returncode = os.waitstatus_to_exitcode(status)
        return self.returncode

    def wait(self, timeout=None):
        end = time.monotonic() + timeout if timeout is not None else float('inf')
        while self.poll() is None:
            if time.monotonic() >= end:
                raise subprocess.TimeoutExpired('archive', timeout)
            time.sleep(.01)
        return self.returncode


def start_archive(archive, preflight, request, prior_handlers=None, pending_signals=None, restart_evidence=None):
    read, write = os.pipe()
    control_read, control_write = os.pipe()
    try:
        pid = os.fork()
    except BaseException:
        for fd in (read, write, control_read, control_write):
            os.close(fd)
        raise
    if pid == 0:
        code = 2
        child_cleanup_uncertain = False
        producer_command_failure = None
        try:
            # The fork inherited the parent's temporary defer handler. Restore
            # real handlers and honor any deferred interruption in the child too.
            restore_handlers(prior_handlers or {})
            if pending_signals:
                raise Refused('interrupted')
            os.setsid()
            os.close(read); os.close(control_read)
            null = os.open('/dev/null', os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(null, fd)
            if null > 2:
                os.close(null)
            # Retain inherited phase/global locks: an orphan worker prevents cleanup.
            end = time.monotonic() + 1800
            def docker_run(args):
                nonlocal child_cleanup_uncertain, producer_command_failure
                try:
                    return command([BINARIES['docker'], '--host', 'unix:///var/run/docker.sock',
                        '--config', BASE + '/' + SESSION + '/docker-config', *args],
                        limit=131072, timeout=min(20, max(.01, end - time.monotonic())))
                except Unfinished:
                    # Archive wrappers may replace this exception. Keep its terminal
                    # safety meaning independently until the control message is sent.
                    child_cleanup_uncertain = True
                    raise
                except Refused as error:
                    if error.code in PRODUCER_COMMAND_CODES:
                        producer_command_failure = error.code
                    raise
            docker = preflight.Docker(end, runner=docker_run)
            proof = archive.archive_snapshot(preflight, request, write, docker=docker, restart_evidence=restart_evidence)
            if child_cleanup_uncertain:
                raise Unfinished()
            if producer_command_failure is not None:
                raise Refused(producer_command_failure)
            raw = json.dumps(proof, separators=(',', ':')).encode('ascii')
            if len(raw) > 1024:
                raise ValueError()
            pending = memoryview(raw)
            while pending:
                count = os.write(control_write, pending)
                if count <= 0:
                    raise ValueError()
                pending = pending[count:]
            code = 0
        except BaseException as error:
            reason = ('attempt_not_terminal' if child_cleanup_uncertain or isinstance(error, Unfinished)
                      else producer_command_failure or getattr(error, 'code', None))
            if reason != 'attempt_not_terminal' and (not isinstance(reason, str) or reason not in PRODUCER_CODES):
                reason = 'archive_incomplete'
            failure = {'status': 'failed', 'session': SNAPSHOT_SESSION, 'error': reason}
            try:
                pending = memoryview(json.dumps(failure, separators=(',', ':')).encode('ascii'))
                while pending:
                    count = os.write(control_write, pending)
                    if count <= 0:
                        break
                    pending = pending[count:]
            except BaseException:
                pass  # Never render a private exception or traceback.
        finally:
            for descriptor in (write, control_write):
                try:
                    os.close(descriptor)
                except BaseException:
                    code = 2
            os._exit(code)
    os.close(write); os.close(control_write)
    return ArchiveProcess(pid, read, control_read)


class Preservation:
    def __init__(self, files=None, asset_dir=None, run=command, transfer=stream_archive):
        self.path = BASE + '/' + SESSION
        self.files = files or Files()
        self.report = output('prepare')
        self.asset_dir = asset_dir or os.path.dirname(os.path.abspath(__file__))
        self.runner, self.transfer = run, transfer
        self.end, self.modules = None, None

    def remaining(self):
        remaining = DEADLINE if self.end is None else self.end - time.monotonic()
        if remaining <= 0:
            raise Refused('deadline_exceeded')
        return remaining

    def run(self, argv, **kwargs):
        kwargs['timeout'] = min(kwargs.get('timeout', 20), self.remaining())
        return self.runner(argv, **kwargs)

    def docker(self, *args):
        return [BINARIES['docker'], '--host', 'unix:///var/run/docker.sock',
                '--config', OLD_DIRECTORY + '/docker-config', *args]

    def gpg(self, *args):
        return [BINARIES['gpg'], '--no-options', '--homedir', self.path + '/gpg',
                '--batch', '--no-tty', '--no-autostart', '--no-auto-key-retrieve',
                '--auto-key-locate', 'clear', *args]

    def dependencies(self):
        for path in BINARIES.values():
            value = self.files.metadata(path)
            if not value.st_mode & 0o111:
                raise Refused('dependency_failed')

    def assets(self, source):
        key = self.files.read(source + '/' + PUBLIC_ASSET, 16384)
        hosts = self.files.read(source + '/' + HOSTS_ASSET, 1024)
        if hashlib.sha256(key).hexdigest() != PUBLIC_HASH or hashlib.sha256(hosts).hexdigest() != HOSTS_HASH:
            raise Refused('asset_invalid')
        try:
            parts = hosts.decode('ascii').strip().split()
            if len(parts) != 3 or parts[:2] != ['139.162.109.181', 'ssh-ed25519']:
                raise ValueError()
            raw = base64.b64decode(parts[2], validate=True)
            if base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=') != HOST_FINGERPRINT:
                raise ValueError()
        except (ValueError, UnicodeError):
            raise Refused('asset_invalid')
        return key, hosts

    def recipient(self):
        lines = self.run(self.gpg('--with-colons', '--fingerprint', '--list-keys'), limit=16384).decode('ascii').splitlines()
        pubs = [line.split(':') for line in lines if line.startswith('pub:')]
        fprs = [line.split(':')[9] for line in lines if line.startswith('fpr:') and len(line.split(':')) > 9]
        if len(pubs) != 1 or not fprs or fprs[0] != RECIPIENT or any(line.startswith(('sec:', 'ssb:')) for line in lines):
            raise Refused('recipient_invalid')

    def controls(self, paused):
        policy = CONTROL_POLICY
        if (not isinstance(policy, dict) or set(policy) != {'request', 'files'} or
                not isinstance(policy['request'], dict) or set(policy['request']) != {'ad', 'content'} or
                not isinstance(policy['files'], list) or not 1 <= len(policy['files']) <= 3):
            raise Refused('policy_unresolved')
        for selection in policy['request'].values():
            if (not isinstance(selection, dict) or set(selection) != {'id', 'pid'} or
                    not isinstance(selection['id'], str) or not HEX.fullmatch(selection['id']) or
                    type(selection['pid']) is not int or not 0 < selection['pid'] < 2**32):
                raise Refused('policy_unresolved')
        template = ('{"id":{{json .Id}},"image":{{json .Image}},"name":{{json .Name}},"pid":{{json .State.Pid}},'
                    '"running":{{json .State.Running}},"paused":{{json .State.Paused}},'
                    '"restarting":{{json .State.Restarting}},"restart":{{json .HostConfig.RestartPolicy}}}')
        adapter = types.SimpleNamespace(inspect=lambda alias, selection: strict_json(
            self.run(self.docker('inspect', '--format', template, selection['id']), limit=16384)))
        current = self.modules['control'].collect(policy['request'], docker=adapter)
        if (current.get('status') != 'observed' or current.get('error') is not None or
                current.get('files') != policy['files'] or
                not isinstance(current.get('containers'), list) or len(current['containers']) != 2):
            raise Refused('controls_changed')
        seen = set()
        for row in current['containers']:
            alias = row.get('alias')
            if (alias not in ('ad', 'content') or alias in seen or
                    row.get('pid') != policy['request'][alias]['pid'] or row.get('paused') is not paused or
                    row.get('restart_policy') != 'no' or row.get('maximum_retry_count') != 0):
                raise Refused('controls_changed')
            seen.add(alias)
        return policy['request']

    def operator(self):
        supplied = os.environ.get('RETIREMENT_OPERATOR_EVIDENCE_SHA256', '')
        if (OPERATOR_EVIDENCE_SHA256 == '0' * 64 or not HEX.fullmatch(OPERATOR_EVIDENCE_SHA256) or
                supplied != OPERATOR_EVIDENCE_SHA256):
            raise Refused('operator_evidence_refused')
        self.report['operator_evidence_sha256'] = supplied

    def restart_evidence(self):
        evidence = RESTART_EVIDENCE
        if (not isinstance(evidence, dict) or set(evidence) !=
                {'sha256', 'operator_evidence_sha256', 'control_policy_sha256'} or
                any(not isinstance(value, str) or not HEX.fullmatch(value) or value == '0' * 64
                    for value in evidence.values()) or evidence['operator_evidence_sha256'] != OPERATOR_EVIDENCE_SHA256):
            raise Refused('policy_unresolved')
        body = self.files.read('/root/.metainc-retirement-control/' + SNAPSHOT_SESSION + '/fence-complete.json', 8192, 0o600)
        if hashlib.sha256(body).hexdigest() != evidence['sha256']:
            raise Refused('controls_changed')
        return dict(evidence)

    def old_attempt(self):
        """Read exact predecessor evidence; never modify its directory or files."""
        with self.files.directory(OLD_DIRECTORY) as folder:
            if stat.S_IMODE(os.fstat(folder).st_mode) != 0o700:
                raise Refused('old_attempt_refused')
            body = self.files.read(OLD_DIRECTORY + '/failure-receipt.json', 4096, 0o600)
            expected = output('send')
            expected.update(session=SNAPSHOT_SESSION, error='pipeline_failed', run=FAILED_RUN,
                paused={'ad': 'paused', 'content': 'paused'}, operator_evidence_sha256=OPERATOR_EVIDENCE_SHA256)
            if (len(body) != FAILED_BYTES or hashlib.sha256(body).hexdigest() != FAILED_SHA256 or
                    not exact_json(strict_json(body), expected)):
                raise Refused('old_attempt_refused')
            attempt = strict_json(self.files.read(OLD_DIRECTORY + '/attempt.json', 4096, 0o600))
            if not exact_json(attempt, {'session': SNAPSHOT_SESSION, 'phase': 'send', 'run': FAILED_RUN,
                           'operator_evidence_sha256': OPERATOR_EVIDENCE_SHA256}):
                raise Refused('old_attempt_refused')
            closed = output('cleanup')
            closed.update(session=SNAPSHOT_SESSION, status='transport_key_removed', run=CLEANUP_RUN)
            if not exact_json(strict_json(self.files.read(OLD_DIRECTORY + '/cleanup-receipt.json', 4096, 0o600)), closed):
                raise Refused('old_transport_not_closed')
            for name in (KEY, KEY + '.pub', 'transfer-receipt.json'):
                try:
                    os.stat(name, dir_fd=folder, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise Refused('old_transport_not_closed')
            with self.files.directory(OLD_DIRECTORY + '/docker-config') as config:
                if stat.S_IMODE(os.fstat(config).st_mode) != 0o700 or os.listdir(config):
                    raise Refused('old_attempt_refused')

    def continuation_guard(self):
        """Before effects: completed old attempt, original fence and all tasks frozen.

        Only Snapshot's frozen/original_restart metadata seams are used here;
        no inventory, app file content, mapping pin or archive write is performed.
        """
        self.operator()
        self.old_attempt()
        request = self.controls(True)
        evidence = self.restart_evidence()
        preflight, archive = self.modules['preflight'], self.modules['archive']
        docker = preflight.Docker(self.end, runner=lambda args: self.run(self.docker(*args), limit=131072))
        snapshot = None
        try:
            snapshot = archive.Snapshot(preflight, request, docker=docker,
                                        end=self.end, restart_evidence=evidence)
            frozen = snapshot.frozen()
            snapshot.original_restart()
            if snapshot.frozen() != frozen:
                raise Refused('producer_freeze_changed')
        except Refused:
            raise
        except BaseException as error:
            code = getattr(error, 'code', None)
            if isinstance(code, str) and code in PRODUCER_CODES:
                raise Refused('producer_' + code) from None
            raise Refused('archive_failed') from None
        finally:
            if snapshot is not None:
                snapshot.stack.close()
        self.old_attempt()
        self.report['paused'] = {'ad': 'paused', 'content': 'paused'}
        return request, evidence

    def ssh(self):
        return [BINARIES['ssh'], '-F', '/dev/null', '-T', '-i', self.path + '/' + KEY,
            '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'PreferredAuthentications=publickey', '-o', 'PasswordAuthentication=no',
            '-o', 'KbdInteractiveAuthentication=no', '-o', 'UserKnownHostsFile=' + self.path + '/' + HOSTS_ASSET,
            '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no', '-o', 'HostKeyAlgorithms=ssh-ed25519',
            '-o', 'ForwardAgent=no', '-o', 'ClearAllForwardings=yes', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
            '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
            'root@139.162.109.181', COMMAND]

    def perform(self, phase):
        if phase not in ('prepare', 'send', 'cleanup'):
            raise Refused('invalid_phase')
        self.end = time.monotonic() + DEADLINE
        self.report = output(phase)
        run = os.environ.get('RETIREMENT_RUN', '')
        if re.fullmatch(r'[1-9][0-9]{0,19}-[1-9][0-9]{0,5}', run) is None:
            raise Refused('operator_evidence_refused')
        self.report['run'] = run
        # Cleanup never imports mutable helper dependencies and remains possible after a failed attempt.
        if phase != 'cleanup':
            self.modules = load_modules(self.asset_dir, self.files)
        with self.files.export_lock():
            if phase == 'prepare':
                self.continuation_guard()
                self.files.mkdir(self.path)
            with self.files.lock(create=phase == 'prepare'):
                return self.perform_locked(phase)

    def perform_locked(self, phase):
        report, files = self.report, self.files
        if files.exists('cleanup-receipt.json'):
            saved = files.json('cleanup-receipt.json')
            if (phase != 'cleanup' or saved.get('session') != SESSION or saved.get('status') != 'transport_key_removed' or
                    files.exists(KEY) or files.exists(KEY + '.pub')):
                raise Refused('session_closed')
            report['status'] = 'already_closed'
            return report
        record_failure = False
        try:
            if phase == 'prepare':
                files.record('prepare-attempt.json', {'session': SESSION, 'phase': phase})
                record_failure = True
                files.mkdir(self.path + '/gpg'); files.mkdir(self.path + '/docker-config')
                self.dependencies()
                if files.free(self.path) < 64 * 1024 ** 2:
                    raise Refused('space_insufficient')
                key, hosts = self.assets(self.asset_dir)
                files.write(PUBLIC_ASSET, key); files.write(HOSTS_ASSET, hosts)
                self.run(self.gpg('--import', self.path + '/' + PUBLIC_ASSET))
                self.recipient()
                if files.exists(KEY) or files.exists(KEY + '.pub'):
                    raise Refused('file_exists')
                self.run([BINARIES['keygen'], '-q', '-t', 'ed25519', '-N', '', '-C', '', '-f', self.path + '/' + KEY])
                files.chmod_key(KEY + '.pub'); files.metadata(self.path + '/' + KEY, 0o600)
                self.continuation_guard()
                report.update(status='prepared', ssh_public_key=public_key(files.read(self.path + '/' + KEY + '.pub', 256, 0o600)))
                files.record('prepared.json', report)
            elif phase == 'send':
                if not files.exists('prepared.json'):
                    raise Refused('not_prepared')
                if files.exists('attempt.json') or files.exists('failure-receipt.json'):
                    raise Refused('attempt_exists')
                prepared = files.json('prepared.json')
                if prepared.get('session') != SESSION or prepared.get('status') != 'prepared':
                    raise Refused('not_prepared')
                request, restart_evidence = self.continuation_guard()
                self.dependencies(); self.assets(self.path); self.recipient()
                files.metadata(self.path + '/' + KEY, 0o600)
                if public_key(files.read(self.path + '/' + KEY + '.pub', 256, 0o600)) != prepared.get('ssh_public_key'):
                    raise Refused('public_key_invalid')
                # New one-shot attempt only after all frozen predecessor guards pass.
                files.record('attempt.json', {'session': SESSION, 'phase': phase, 'run': report['run'],
                    'operator_evidence_sha256': report['operator_evidence_sha256']})
                record_failure = True
                transferred = self.transfer(self.modules['archive'], self.modules['preflight'], request,
                    self.gpg('--trust-model', 'always', '--compress-algo', 'none', '--cipher-algo', 'AES256',
                             '--recipient', RECIPIENT, '--encrypt'), self.ssh(), timeout=self.remaining(),
                    restart_evidence=restart_evidence)
                report['process_rc'] = transferred['process_rc']
                self.continuation_guard()
                report.update(status='transferred_unverified', **transferred)
                files.record('transfer-receipt.json', report)
            else:
                if files.exists('prepare-attempt.json') and not any(files.exists(name) for name in ('prepared.json', 'failure-receipt.json')):
                    raise Refused('attempt_not_terminal')
                if files.exists('attempt.json') and not any(files.exists(name) for name in ('transfer-receipt.json', 'failure-receipt.json')):
                    raise Refused('attempt_not_terminal')
                for name in ('transfer-receipt.json', 'failure-receipt.json'):
                    if files.exists(name):
                        value = files.json(name)
                        if value.get('session') != SESSION or value.get('phase') not in ('prepare', 'send'):
                            raise Refused('receipt_invalid')
                files.remove_key(KEY); files.remove_key(KEY + '.pub')
                report['status'] = 'transport_key_removed'
                files.record('cleanup-receipt.json', report)
            return report
        except BaseException as error:
            report.update(status='failed', error=error.code if isinstance(error, Refused) else 'internal_failure')
            if isinstance(error, Refused) and error.process_rc is not None:
                report['process_rc'] = error.process_rc
            if record_failure and not isinstance(error, Unfinished) and not files.exists('failure-receipt.json'):
                files.record('failure-receipt.json', report)
            raise Refused(report['error']) from None


def interrupted(signum, frame):
    raise Refused('interrupted')


def main():
    phase = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ('prepare', 'send', 'cleanup') else 'prepare'
    report, source = output(phase), None
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ('prepare', 'send', 'cleanup'):
            raise Refused('invalid_phase')
        if os.geteuid() != 0 or sys.platform != 'linux':
            raise Refused('root_required')
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0)); os.umask(0o077)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, interrupted)
        source = Preservation()
        report = source.perform(phase)
    except BaseException as error:
        if source is not None:
            report = source.report
        report.update(status='failed', error=error.code if isinstance(error, Refused) else 'internal_failure')
    payload = json.dumps(report, separators=(',', ':'))
    if len(payload) > 4096:
        report = output(phase); report['error'] = 'internal_failure'
        payload = json.dumps(report, separators=(',', ':'))
    print(payload)
    return 0 if report['status'] != 'failed' else 2


if __name__ == '__main__':
    sys.exit(main())
