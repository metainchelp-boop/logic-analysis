#!/usr/bin/env python3
"""Opaque image encryption; no app volume/DB access or app state changes."""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

SESSION = 'ad-image-20261102-v1'
BASE = '/root/.metainc-retirement-transfer'
DIRECTORY = BASE + '/' + SESSION
IMAGE = 'sha256:959001525d45612e0c5cc1045291c7b6caefa768c14d37cc1070c26584cb8922'
RECIPIENT = '78076C3BC580EB5AC684EDE8BE5DAF3D1B780CA5'
PUBLIC_HASH = '1c680db160149e83e04983c6f74a5c696c473fa9d921e956b14a7c908fd667a3'
HOSTS_HASH = '263a7fd1c7fe50257fec9223c4cb2015d4e4ff575c0f8c7d362225c589204675'
HOST_FINGERPRINT = 'j9NJSZdOiJNqeSzDFbu6FVlhMJFGb4B6byavrDoG+bg'
MAX_IMAGE = 256 * 1024 * 1024
MAX_CIPHER = 512 * 1024 * 1024
MIN_FREE = 3 * 1024 * 1024 * 1024
MAX_STDERR = 65536
MAX_RECEIPT = 1024
DEADLINE = 900
BINARIES = {'docker': '/usr/bin/docker', 'gpg': '/usr/bin/gpg', 'ssh': '/usr/bin/ssh',
            'keygen': '/usr/bin/ssh-keygen', 'systemctl': '/usr/bin/systemctl'}
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
KEY = 'source-transport-key'
PUBLIC_ASSET = 'recovery-public.asc'
HOSTS_ASSET = 'server-b-known-hosts'
HEX = re.compile(r'[0-9a-f]{64}\Z')
ERRORS = frozenset(('invalid_phase', 'root_required', 'unsafe_path', 'path_changed',
    'session_exists', 'session_missing', 'file_exists', 'file_missing', 'file_too_large',
    'lock_busy', 'dependency_failed', 'command_failed', 'command_limit', 'deadline_exceeded',
    'asset_invalid', 'recipient_invalid', 'image_invalid', 'space_insufficient',
    'daemon_unverified', 'public_key_invalid', 'not_prepared', 'attempt_exists',
    'session_closed', 'receipt_invalid', 'pipeline_failed', 'cipher_limit',
    'pipe_failed', 'attempt_not_terminal', 'interrupted', 'internal_failure'))


class Refused(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'internal_failure'


class Unfinished(Refused):
    def __init__(self):
        super().__init__('attempt_not_terminal')


def output(phase):
    return {'phase': phase, 'status': 'failed', 'session': SESSION, 'error': None,
            'ssh_public_key': None, 'image_size_bytes': None, 'bytes': None,
            'sha256': None, 'process_rc': None, 'backup_verified': False}


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


class Files:
    """Alternate root/owner are synthetic-fixture seams, never CLI inputs."""
    def __init__(self, root='/', owner=0):
        self.root, self.owner = root, owner

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
        with self.directory(DIRECTORY) as fd:
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
        with self.directory(DIRECTORY) as parent:
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
        return strict_json(self.read(DIRECTORY + '/' + name, 4096, 0o600))

    @contextlib.contextmanager
    def lock(self, create=False):
        with self.directory(DIRECTORY) as parent:
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
        with self.directory(DIRECTORY) as parent:
            before = self.metadata(DIRECTORY + '/' + name)
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
        with self.directory(DIRECTORY) as parent:
            try:
                before = self.metadata(DIRECTORY + '/' + name, 0o600)
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


def terminate(processes):
    previous = {sig: signal.signal(sig, signal.SIG_IGN) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for process in processes:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        end = time.monotonic() + 2
        for process in processes:
            try:
                process.wait(timeout=max(.01, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
    except Exception:
        raise Unfinished()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def close_streams(processes):
    for process in processes:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()


def command(argv, limit=4096, timeout=20):
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=ENV, shell=False, start_new_session=True)
    try:
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
        terminate([process])
        close_streams([process])


def stream_image(docker, gpg, ssh, max_cipher=MAX_CIPHER, timeout=DEADLINE):
    """Only encrypted gpg stdout enters Python; docker plaintext goes straight to gpg."""
    processes = []
    end = time.monotonic() + timeout
    try:
        producer = subprocess.Popen(docker, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=ENV, shell=False, start_new_session=True)
        processes.append(producer)
        encryptor = subprocess.Popen(gpg, stdin=producer.stdout, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=ENV, shell=False, start_new_session=True)
        processes.append(encryptor)
        producer.stdout.close()
        transport = subprocess.Popen(ssh, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=ENV, shell=False, start_new_session=True)
        processes.append(transport)
        digest, size, errors, receipt = hashlib.sha256(), 0, 0, bytearray()
        pending, eof, cipher_registered, writable = bytearray(), False, True, False
        with selectors.DefaultSelector() as selector:
            for process in processes:
                os.set_blocking(process.stderr.fileno(), False)
                selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
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
                 for name, process in zip(('docker', 'gpg', 'ssh'), processes)}
        if any(code != 0 for code in codes.values()) or not eof or pending or size == 0:
            raise Refused('pipeline_failed')
        remote = strict_json(receipt)
        if (not isinstance(remote, dict) or set(remote) != {'status', 'bytes', 'sha256'} or
                remote['status'] != 'received_unverified' or type(remote['bytes']) is not int or
                remote['bytes'] != size or remote['sha256'] != digest.hexdigest()):
            raise Refused('receipt_invalid')
        return {'bytes': size, 'sha256': digest.hexdigest(), 'process_rc': codes}
    except subprocess.TimeoutExpired:
        raise Refused('deadline_exceeded')
    finally:
        terminate(processes)
        close_streams(processes)


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


def process_start(data, pid):
    try:
        head, tail = data.rsplit(b') ', 1)
        fields = tail.split()
        if head != pid + b' (dockerd' or len(fields) < 20 or not fields[19].isdigit():
            raise ValueError()
        return int(fields[19])
    except (ValueError, IndexError):
        raise Refused('daemon_unverified')


class Preservation:
    def __init__(self, files=None, asset_dir=None, run=command, transfer=stream_image):
        self.files = files or Files()
        self.asset_dir = asset_dir or os.path.dirname(os.path.abspath(__file__))
        self.runner, self.transfer = run, transfer
        self.end = None

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
                '--config', DIRECTORY + '/docker-config', *args]

    def gpg(self, *args):
        return [BINARIES['gpg'], '--no-options', '--homedir', DIRECTORY + '/gpg',
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
        if (hashlib.sha256(key).hexdigest() != PUBLIC_HASH or
                hashlib.sha256(hosts).hexdigest() != HOSTS_HASH or
                not key.startswith(b'-----BEGIN PGP PUBLIC KEY BLOCK-----')):
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

    def preflight(self):
        self.dependencies()
        try:
            info = json.loads(self.run(self.docker('info', '--format', '{"root":{{json .DockerRootDir}},"driver":{{json .Driver}}}')))
            version = json.loads(self.run(self.docker('version', '--format', '{"client":{{json .Client.Version}},"server":{{json .Server.Version}}}')))
            image = json.loads(self.run(self.docker('image', 'inspect', '--format', '{"id":{{json .Id}},"size":{{json .Size}}}', IMAGE)))
            if (set(info) != {'root', 'driver'} or info['root'] != '/var/lib/docker' or
                    info['driver'] not in ('overlay2', 'overlayfs') or set(version) != {'client', 'server'} or
                    not all(isinstance(x, str) and re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,2}[a-zA-Z0-9+._-]*', x) for x in version.values())):
                raise Refused('daemon_unverified')
            if set(image) != {'id', 'size'} or image['id'] != IMAGE or type(image['size']) is not int or not 0 < image['size'] <= MAX_IMAGE:
                raise Refused('image_invalid')
        except (ValueError, TypeError, UnicodeError):
            raise Refused('daemon_unverified')
        pid = self.run([BINARIES['systemctl'], 'show', 'docker.service', '--property=MainPID', '--value'], limit=32).strip()
        if not re.fullmatch(rb'[1-9][0-9]{0,9}', pid):
            raise Refused('daemon_unverified')
        proc = '/proc/' + pid.decode()
        start = process_start(self.files.read(proc + '/stat', 4096), pid)
        if self.files.read(proc + '/comm', 64).strip() != b'dockerd':
            raise Refused('daemon_unverified')
        # Bounded daemon environment is inspected only in memory for these two settings.
        # No unrelated environment value is decoded, stored, or emitted.
        environment = self.files.read(proc + '/environ', 65536).split(b'\0')
        for prefix in (b'DOCKER_TMPDIR=', b'TMPDIR='):
            settings = [item[len(prefix):] for item in environment if item.startswith(prefix)]
            if len(settings) > 1 or (settings and settings[0] not in (b'/tmp', b'/var/lib/docker/tmp')):
                raise Refused('daemon_unverified')
        del environment
        if process_start(self.files.read(proc + '/stat', 4096), pid) != start or self.files.read(proc + '/comm', 64).strip() != b'dockerd':
            raise Refused('daemon_unverified')
        if any(self.files.free(path) < MIN_FREE for path in ('/var/lib/docker', '/tmp')):
            raise Refused('space_insufficient')
        # Default tmp must exist on the already checked Docker filesystem.
        with self.files.directory('/var/lib/docker') as root:
            with self.files.directory('/var/lib/docker/tmp') as temp:
                if os.fstat(root).st_dev != os.fstat(temp).st_dev:
                    raise Refused('daemon_unverified')
        return image['size']

    def perform(self, phase):
        self.end = time.monotonic() + DEADLINE
        report = output(phase)
        files = self.files
        if phase == 'prepare':
            files.mkdir(BASE, existing=True)
            files.mkdir(DIRECTORY)
        with files.lock(create=phase == 'prepare'):
            if files.exists('cleanup-receipt.json'):
                if phase == 'cleanup':
                    closed = files.json('cleanup-receipt.json')
                    if (closed.get('session') != SESSION or closed.get('phase') != 'cleanup' or
                            closed.get('status') != 'transport_key_removed' or
                            files.exists(KEY) or files.exists(KEY + '.pub')):
                        raise Refused('receipt_invalid')
                    report['status'] = 'already_closed'
                    return report
                raise Refused('session_closed')
            record_failure = False
            try:
                if phase == 'prepare':
                    files.record('prepare-attempt.json', {'session': SESSION, 'phase': 'prepare'})
                    record_failure = True
                    files.mkdir(DIRECTORY + '/gpg')
                    files.mkdir(DIRECTORY + '/docker-config')
                    size = self.preflight()
                    key, hosts = self.assets(self.asset_dir)
                    files.write(PUBLIC_ASSET, key)
                    files.write(HOSTS_ASSET, hosts)
                    self.run(self.gpg('--import', DIRECTORY + '/' + PUBLIC_ASSET))
                    self.recipient()
                    if files.exists(KEY) or files.exists(KEY + '.pub'):
                        raise Refused('file_exists')
                    self.run([BINARIES['keygen'], '-q', '-t', 'ed25519', '-N', '', '-C', '', '-f', DIRECTORY + '/' + KEY])
                    files.chmod_key(KEY + '.pub')
                    files.metadata(DIRECTORY + '/' + KEY, 0o600)  # No private key read.
                    key_public = public_key(files.read(DIRECTORY + '/' + KEY + '.pub', 256, 0o600))
                    report.update(status='prepared', image_size_bytes=size, ssh_public_key=key_public)
                    files.record('prepared.json', report)
                elif phase == 'send':
                    if not files.exists('prepared.json'):
                        raise Refused('not_prepared')
                    if files.exists('attempt.json') or files.exists('failure-receipt.json'):
                        raise Refused('attempt_exists')
                    record_failure = True
                    prepared = files.json('prepared.json')
                    if prepared.get('session') != SESSION or prepared.get('status') != 'prepared':
                        raise Refused('not_prepared')
                    size = self.preflight()
                    self.assets(DIRECTORY)
                    self.recipient()
                    files.metadata(DIRECTORY + '/' + KEY, 0o600)
                    if public_key(files.read(DIRECTORY + '/' + KEY + '.pub', 256, 0o600)) != prepared.get('ssh_public_key'):
                        raise Refused('public_key_invalid')
                    files.record('attempt.json', {'session': SESSION, 'phase': 'send'})
                    ssh = [BINARIES['ssh'], '-F', '/dev/null', '-T', '-i', DIRECTORY + '/' + KEY,
                        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                        '-o', 'PreferredAuthentications=publickey', '-o', 'PasswordAuthentication=no',
                        '-o', 'KbdInteractiveAuthentication=no',
                        '-o', 'UserKnownHostsFile=' + DIRECTORY + '/' + HOSTS_ASSET,
                        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no',
                        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ForwardAgent=no',
                        '-o', 'ClearAllForwardings=yes', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
                        '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                        'root@139.162.109.181', 'receive-ad-image-20261102-v1']
                    transferred = self.transfer(self.docker('save', IMAGE), self.gpg('--trust-model', 'always',
                        '--compress-algo', 'none', '--cipher-algo', 'AES256', '--recipient', RECIPIENT, '--encrypt'),
                        ssh, timeout=self.remaining())
                    report.update(status='transferred_unverified', image_size_bytes=size, **transferred)
                    files.record('transfer-receipt.json', report)
                else:
                    if files.exists('prepare-attempt.json') and not any(files.exists(name) for name in
                            ('prepared.json', 'failure-receipt.json')):
                        raise Refused('attempt_not_terminal')
                    if files.exists('attempt.json') and not any(files.exists(name) for name in
                            ('transfer-receipt.json', 'failure-receipt.json')):
                        raise Refused('attempt_not_terminal')
                    for name in ('transfer-receipt.json', 'failure-receipt.json'):
                        if files.exists(name):
                            saved = files.json(name)
                            if saved.get('session') != SESSION or saved.get('phase') not in ('prepare', 'send'):
                                raise Refused('receipt_invalid')
                    files.remove_key(KEY)
                    files.remove_key(KEY + '.pub')
                    report['status'] = 'transport_key_removed'
                    files.record('cleanup-receipt.json', report)
                return report
            except Exception as error:
                report['status'] = 'failed'
                report['error'] = error.code if isinstance(error, Refused) else 'internal_failure'
                # Pipeline finally has reaped every child before a terminal failure receipt.
                if (record_failure and phase in ('prepare', 'send') and not isinstance(error, Unfinished) and
                        not files.exists('failure-receipt.json')):
                    files.record('failure-receipt.json', report)
                raise Refused(report['error'])


def interrupted(signum, frame):
    raise Refused('interrupted')


def main():
    phase = sys.argv[1] if len(sys.argv) == 2 and sys.argv[1] in ('prepare', 'send', 'cleanup') else 'prepare'
    report = output(phase)
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ('prepare', 'send', 'cleanup'):
            raise Refused('invalid_phase')
        if os.geteuid() != 0:
            raise Refused('root_required')
        os.umask(0o077)
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        report = Preservation().perform(phase)
    except Exception as error:
        report['error'] = error.code if isinstance(error, Refused) else 'internal_failure'
    payload = json.dumps(report, separators=(',', ':'))
    if len(payload) > 4096:
        report = output(phase)
        report['error'] = 'internal_failure'
        payload = json.dumps(report, separators=(',', ':'))
    print(payload)
    return 0 if report['status'] != 'failed' else 2


if __name__ == '__main__':
    sys.exit(main())
