#!/usr/bin/env python3
"""Preserve exactly two opaque key files; no parsing, plaintext output, or app changes."""
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import resource
import tarfile
import selectors
import signal
import stat
import subprocess
import sys
import time

SESSION = 'key-capsule-20261102-v1'
BASE = '/root/.metainc-retirement-transfer'
DIRECTORY = BASE + '/' + SESSION
ORIGINALS = (('/root/ad-dashboard-deploy/data/secret.key', 'ad-dashboard/secret.key'),
             ('/root/content-studio-deploy/autobid/.env', 'autobid/.env'))
RECIPIENT = '78076C3BC580EB5AC684EDE8BE5DAF3D1B780CA5'
PUBLIC_HASH = '1c680db160149e83e04983c6f74a5c696c473fa9d921e956b14a7c908fd667a3'
HOSTS_HASH = '263a7fd1c7fe50257fec9223c4cb2015d4e4ff575c0f8c7d362225c589204675'
HOST_FINGERPRINT = 'j9NJSZdOiJNqeSzDFbu6FVlhMJFGb4B6byavrDoG+bg'
MAX_SOURCE = 64 * 1024
MAX_ARCHIVE = 80 * 1024
MAX_CIPHER = 1024 * 1024
MIN_FREE = 16 * 1024 * 1024
MAX_STDERR = 65536
MAX_RECEIPT = 1024
DEADLINE = 300
BINARIES = {'gpg': '/usr/bin/gpg', 'ssh': '/usr/bin/ssh', 'keygen': '/usr/bin/ssh-keygen'}
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
KEY = 'source-transport-key'
PUBLIC_ASSET = 'recovery-public.asc'
HOSTS_ASSET = 'server-b-known-hosts'
ERRORS = frozenset(('invalid_phase', 'root_required', 'unsafe_path', 'path_changed',
    'session_exists', 'session_missing', 'file_exists', 'file_missing', 'file_too_large',
    'lock_busy', 'dependency_failed', 'command_failed', 'command_limit', 'deadline_exceeded',
    'asset_invalid', 'recipient_invalid', 'source_invalid', 'space_insufficient',
    'source_changed', 'public_key_invalid', 'not_prepared', 'attempt_exists',
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
            'ssh_public_key': None, 'source_size_bytes': None, 'bytes': None,
            'sha256': None, 'process_rc': None, 'backup_verified': False}


def identity(value):
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


def parent_allowed(value, path, owner, original):
    observed_source_parent = (original and path == '/root/ad-dashboard-deploy' and
        value.st_uid == 501 and value.st_gid == 50 and stat.S_IMODE(value.st_mode) == 0o755)
    sticky_tmp = not original and path == '/tmp' and bool(value.st_mode & stat.S_ISVTX)
    return (stat.S_ISDIR(value.st_mode) and (value.st_uid == owner or observed_source_parent) and
            (not value.st_mode & 0o022 or sticky_tmp))


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
    def directory(self, path, original=False):
        if not path.startswith('/') or '..' in path.split('/'):
            raise Refused('unsafe_path')
        with contextlib.ExitStack() as stack:
            fd = os.open(self.root, DIR_FLAGS)
            stack.callback(os.close, fd)
            chain, current = [], ''
            for name in filter(None, path.split('/')):
                current += '/' + name
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if not parent_allowed(before, current, self.owner, original):
                    raise Refused('unsafe_path')
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                stack.callback(os.close, child)
                if identity(before) != identity(os.fstat(child)):
                    raise Refused('path_changed')
                chain.append((fd, name, child, identity(before), before.st_ctime_ns))
                fd = child
            yield fd
            for parent, name, child, expected, ctime in chain:
                linked, opened = os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(child)
                if (identity(linked) != expected or identity(opened) != expected or
                        (original and (linked.st_ctime_ns != ctime or opened.st_ctime_ns != ctime))):
                    raise Refused('path_changed')

    @contextlib.contextmanager
    def parent(self, path):
        parent, name = path.rsplit('/', 1)
        if not name or name in ('.', '..'):
            raise Refused('unsafe_path')
        with self.directory(parent or '/') as fd:
            yield fd, name

    @contextlib.contextmanager
    def original_parent(self, path):
        if path not in {item[0] for item in ORIGINALS}:
            raise Refused('unsafe_path')
        parent, name = path.rsplit('/', 1)
        with self.directory(parent, original=True) as fd:
            yield fd, name

    def original_metadata(self, path):
        with self.original_parent(path) as (fd, name):
            value = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if (not stat.S_ISREG(value.st_mode) or value.st_uid != self.owner or
                    value.st_nlink != 1 or value.st_mode & 0o022):
                raise Refused('unsafe_path')
            return value

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
        try:
            terminate([process])
        finally:
            close_streams([process])



def source_identity(value):
    return (*identity(value), value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def source_size(files):
    sizes = [files.original_metadata(path).st_size for path, _ in ORIGINALS]
    if any(size <= 0 for size in sizes) or sum(sizes) > MAX_SOURCE:
        raise Refused('source_invalid')
    return sum(sizes)


def wipe(data):
    data[:] = b'\0' * len(data)


def source_archive(files):
    """The only original-body reader: two pinned fds, bounded memory, fixed tar names."""
    blocks, archive, total = [], bytearray(), 0
    try:
        with contextlib.ExitStack() as stack:
            opened = []
            for path, alias in ORIGINALS:
                parent, name = stack.enter_context(files.original_parent(path))
                before = files.original_metadata(path)
                if not 0 < before.st_size <= MAX_SOURCE:
                    raise Refused('source_invalid')
                fd = os.open(name, READ_FLAGS, dir_fd=parent)
                stack.callback(os.close, fd)
                if source_identity(os.fstat(fd)) != source_identity(before):
                    raise Refused('source_changed')
                opened.append((parent, name, fd, before, alias))
            if sum(item[3].st_size for item in opened) > MAX_SOURCE:
                raise Refused('source_invalid')
            for parent, name, fd, before, alias in opened:
                data = bytearray()
                blocks.append(data)
                while True:
                    block = os.read(fd, min(8192, MAX_SOURCE + 1 - total))
                    if not block:
                        break
                    data.extend(block)
                    total += len(block)
                    if total > MAX_SOURCE:
                        raise Refused('source_invalid')
                if len(data) != before.st_size:
                    raise Refused('source_changed')
                header = tarfile.TarInfo(alias)
                header.size, header.mode = len(data), 0o600
                header.uid = header.gid = header.mtime = 0
                header.uname = header.gname = ''
                archive.extend(header.tobuf(format=tarfile.USTAR_FORMAT))
                archive.extend(data)
                archive.extend(b'\0' * (-len(data) % 512))
            # Recheck BOTH originals after the complete read, before any encryption/send.
            for parent, name, fd, before, _ in opened:
                if (source_identity(os.fstat(fd)) != source_identity(before) or
                        source_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != source_identity(before)):
                    raise Refused('source_changed')
        # All pinned parent edges have now passed their post-operation identity checks.
        archive.extend(b'\0' * 1024)
        archive.extend(b'\0' * (-len(archive) % 10240))
        if not 0 < total <= MAX_SOURCE or len(archive) > MAX_ARCHIVE:
            raise Refused('source_invalid')
        return archive, total
    except BaseException:
        wipe(archive)
        raise
    finally:
        for data in blocks:
            wipe(data)


def stream_capsule(plain, gpg, ssh, max_cipher=MAX_CIPHER, timeout=DEADLINE):
    """Plaintext is sent only to GPG stdin; only ciphertext is hashed/forwarded."""
    if not isinstance(plain, bytearray) or not 0 < len(plain) <= MAX_ARCHIVE:
        raise Refused('source_invalid')
    processes, end = [], time.monotonic() + timeout
    try:
        encryptor = subprocess.Popen(gpg, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=ENV, shell=False, start_new_session=True)
        processes.append(encryptor)
        transport = subprocess.Popen(ssh, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=ENV, shell=False, start_new_session=True)
        processes.append(transport)
        digest, size, errors, receipt = hashlib.sha256(), 0, 0, bytearray()
        pending, offset, eof, cipher_registered, writable = bytearray(), 0, False, True, False
        with selectors.DefaultSelector() as selector:
            for process in processes:
                for stream in (process.stdin, process.stdout, process.stderr):
                    os.set_blocking(stream.fileno(), False)
                selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            selector.register(encryptor.stdin, selectors.EVENT_WRITE, 'plain')
            selector.register(encryptor.stdout, selectors.EVENT_READ, 'cipher')
            selector.register(transport.stdout, selectors.EVENT_READ, 'receipt')
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise Refused('deadline_exceeded')
                for key, _ in selector.select(min(remaining, .2)):
                    if key.data in ('plain', 'send'):
                        data = memoryview(plain)[offset:offset + 65536] if key.data == 'plain' else memoryview(pending)
                        try:
                            sent = os.write(key.fd, data)
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            raise Refused('pipe_failed')
                        finally:
                            data.release()
                        if sent <= 0:
                            raise Refused('pipe_failed')
                        if key.data == 'plain':
                            offset += sent
                            if offset == len(plain):
                                selector.unregister(encryptor.stdin)
                                encryptor.stdin.close()
                        else:
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
                 for name, process in zip(('gpg', 'ssh'), processes)}
        if any(code != 0 for code in codes.values()) or offset != len(plain) or not eof or pending or size == 0:
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
        try:
            terminate(processes)
        finally:
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


class Capsule:
    def __init__(self, files=None, asset_dir=None, run=command, transfer=stream_capsule):
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
        size = source_size(self.files)
        if self.files.free(DIRECTORY) < MIN_FREE:
            raise Refused('space_insufficient')
        return size

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
                    report.update(status='prepared', source_size_bytes=size, ssh_public_key=key_public)
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
                        'root@139.162.109.181', 'receive-key-capsule-20261102-v1']
                    archive, size = source_archive(files)
                    try:
                        transferred = self.transfer(archive, self.gpg('--trust-model', 'always',
                            '--compress-algo', 'none', '--cipher-algo', 'AES256', '--recipient', RECIPIENT, '--encrypt'),
                            ssh, timeout=self.remaining())
                    finally:
                        wipe(archive)
                    report.update(status='transferred_unverified', source_size_bytes=size, **transferred)
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
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.umask(0o077)
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        report = Capsule().perform(phase)
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
