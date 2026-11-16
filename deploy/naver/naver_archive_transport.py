#!/usr/bin/env python3
"""One-shot NAVER archive encryption/send and exclusive ciphertext retrieval.

No recovery private key is loaded here. A send receipt proves ciphertext transport,
not decryption, restore, or permission to remove any source file.
"""
import argparse
import base64
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import struct
import subprocess
import sys
import time

SESSION = 'naver-archives-20261106-v1'
RECEIVE = 'receive-' + SESSION
FETCH = 'fetch-' + SESSION
DESTINATION = 'root@139.162.109.181'
RECIPIENT = '78076C3BC580EB5AC684EDE8BE5DAF3D1B780CA5'
PUBLIC_HASH = '1c680db160149e83e04983c6f74a5c696c473fa9d921e956b14a7c908fd667a3'
HOSTS_HASH = '263a7fd1c7fe50257fec9223c4cb2015d4e4ff575c0f8c7d362225c589204675'
HOST_FINGERPRINT = 'j9NJSZdOiJNqeSzDFbu6FVlhMJFGb4B6byavrDoG+bg'
MAX_CIPHER = 12 * 1024 ** 3
MAX_PLAN = 256 * 1024
MAX_RECEIPT = 4096
MAX_STDERR = 65536
DEADLINE = 3600
BLOCK = 65536
WIRE_MAGIC = b'NAVER-ARCHIVE-CIPHER-FRAMES-V1\n'
FRAME_BYTES = 65536
RESERVE = 512 * 1024 ** 2
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C', 'LC_ALL': 'C'}
HEX = re.compile(r'[0-9a-f]{64}\Z')
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
ERRORS = frozenset(('unsafe_path', 'path_changed', 'root_required', 'receipt_invalid',
    'plan_invalid', 'asset_invalid', 'recipient_invalid', 'dependency_failed',
    'session_exists', 'file_exists', 'deadline_exceeded', 'output_limit',
    'pipeline_failed', 'pipe_failed', 'cipher_limit', 'cipher_mismatch',
    'command_failed', 'space_insufficient', 'interrupted', 'cleanup_failed', 'internal_failure'))


class Refused(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'internal_failure'
        super().__init__(self.code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, TypeError):
        raise Refused('receipt_invalid') from None


def identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def dir_identity(value):
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


class Files:
    """Owner/root overrides are test seams, never CLI inputs."""
    def __init__(self, root='/', owner=None):
        self.root = root
        self.owner = os.geteuid() if owner is None else owner

    @contextlib.contextmanager
    def directory(self, path):
        if (not isinstance(path, str) or not path.startswith('/') or
                any(ord(char) < 32 or ord(char) == 127 for char in path) or any(
                part in ('.', '..') for part in path.split('/'))):
            raise Refused('unsafe_path')
        with contextlib.ExitStack() as stack:
            fd = os.open(self.root, DIR_FLAGS)
            stack.callback(os.close, fd)
            chain = []
            for name in filter(None, path.split('/')):
                before = os.stat(name, dir_fd=fd, follow_symlinks=False)
                sticky_tmp = name == 'tmp' and not chain and bool(before.st_mode & stat.S_ISVTX)
                if (not stat.S_ISDIR(before.st_mode) or before.st_uid not in (0, self.owner)
                        or (before.st_mode & 0o022 and not sticky_tmp)):
                    raise Refused('unsafe_path')
                child = os.open(name, DIR_FLAGS, dir_fd=fd)
                stack.callback(os.close, child)
                expected = dir_identity(before)
                if dir_identity(os.fstat(child)) != expected:
                    raise Refused('path_changed')
                chain.append((fd, name, child, expected))
                fd = child
            yield fd
            for parent, name, child, expected in chain:
                if (dir_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected
                        or dir_identity(os.fstat(child)) != expected):
                    raise Refused('path_changed')

    @contextlib.contextmanager
    def parent(self, path):
        if (not isinstance(path, str) or '/' not in path or
                any(ord(char) < 32 or ord(char) == 127 for char in path)):
            raise Refused('unsafe_path')
        parent, name = path.rsplit('/', 1)
        if not name or name in ('.', '..'):
            raise Refused('unsafe_path')
        with self.directory(parent or '/') as fd:
            yield fd, name

    @contextlib.contextmanager
    def opened(self, path, mode=None):
        with self.parent(path) as (parent, name):
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid not in (0, self.owner)
                    or before.st_nlink != 1 or before.st_mode & 0o022
                    or (mode is not None and (before.st_uid != self.owner
                        or stat.S_IMODE(before.st_mode) != mode))):
                raise Refused('unsafe_path')
            fd = os.open(name, READ_FLAGS, dir_fd=parent)
            try:
                expected = identity(before)
                if identity(os.fstat(fd)) != expected:
                    raise Refused('path_changed')
                yield fd
                if (identity(os.fstat(fd)) != expected or
                        identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected):
                    raise Refused('path_changed')
            finally:
                os.close(fd)

    def read(self, path, limit, mode=None):
        with self.opened(path, mode) as fd:
            if os.fstat(fd).st_size > limit:
                raise Refused('output_limit')
            result = bytearray()
            while True:
                data = os.read(fd, min(BLOCK, limit + 1 - len(result)))
                if not data:
                    return bytes(result)
                result.extend(data)
                if len(result) > limit:
                    raise Refused('output_limit')

    def create(self, path, data):
        with self.parent(path) as (parent, name):
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent)
            try:
                os.fchmod(fd, 0o600)
                write_all(fd, data)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)

    def mkdir(self, path):
        with self.parent(path) as (parent, name):
            try:
                os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError:
                raise Refused('session_exists') from None
            os.fsync(parent)


def write_all(fd, data):
    view = memoryview(data)
    while view:
        amount = os.write(fd, view)
        if amount <= 0:
            raise Refused('pipe_failed')
        view = view[amount:]


def validate_sent(receipt):
    if (not isinstance(receipt, dict) or set(receipt) !=
            {'status', 'session', 'plan_sha256', 'bytes', 'sha256'} or
            receipt['status'] != 'sent_unverified' or receipt['session'] != SESSION or
            type(receipt['bytes']) is not int or not 0 < receipt['bytes'] <= MAX_CIPHER or
            any(not isinstance(receipt[key], str) or not HEX.fullmatch(receipt[key])
                for key in ('plan_sha256', 'sha256'))):
        raise Refused('receipt_invalid')
    return receipt


def spawn(argv, processes, **kwargs):
    numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    pending = []
    previous = {number: signal.signal(number, lambda number, frame: pending.append(number))
                for number in numbers}
    try:
        process = subprocess.Popen(argv, env=ENV, shell=False, start_new_session=True, **kwargs)
        processes.append(process)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
    if pending:
        raise Refused('interrupted')
    return process


def close_processes(processes):
    # Always address groups: a child can exit while its descendants hold a pipe.
    numbers = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = {number: signal.signal(number, signal.SIG_IGN) for number in numbers}
    uncertain = False
    try:
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except OSError:
                # macOS can report EPERM for a just-exited process group.
                # Retry at SIGKILL below, then require a successful reap. The
                # child can be between exit and waitable state at this point.
                pass
        end = time.monotonic() + .25
        for process in processes:
            try:
                process.wait(timeout=max(.01, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                pass
        for process in processes:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                uncertain = True
        if uncertain:
            raise Refused('cleanup_failed')
    finally:
        for process in processes:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        for number, handler in previous.items():
            signal.signal(number, handler)


def remaining(end):
    value = end - time.monotonic()
    if value <= 0:
        raise Refused('deadline_exceeded')
    return value


def command(argv, timeout=30, limit=16384):
    processes = []
    end, output, errors = time.monotonic() + timeout, bytearray(), 0
    try:
        process = spawn(argv, processes, stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with selectors.DefaultSelector() as selector:
            for stream, label in ((process.stdout, 'out'), (process.stderr, 'err')):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, label)
            while selector.get_map():
                for key, _ in selector.select(min(remaining(end), .2)):
                    try:
                        data = os.read(key.fd, BLOCK)
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(key.fileobj)
                    elif key.data == 'out':
                        output.extend(data)
                        if len(output) > limit:
                            raise Refused('output_limit')
                    else:
                        errors += len(data)
                        if errors > MAX_STDERR:
                            raise Refused('output_limit')
        if process.wait(timeout=remaining(end)) != 0:
            raise Refused('command_failed')
        return bytes(output)
    except subprocess.TimeoutExpired:
        raise Refused('deadline_exceeded') from None
    finally:
        close_processes(processes)


def stream_send(source, gpg, ssh, timeout=DEADLINE, max_cipher=MAX_CIPHER):
    """Frame ciphertext; commit only after both upstream exits and stderr EOFs."""
    processes = []
    end = time.monotonic() + timeout
    try:
        producer = spawn(source, processes, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        encryptor = spawn(gpg, processes, stdin=producer.stdout,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        producer.stdout.close()
        remote = spawn(ssh, processes, stdin=subprocess.PIPE,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        digest, count, errors, receipt = hashlib.sha256(), 0, 0, bytearray()
        pending, fragment = bytearray(WIRE_MAGIC), bytearray()
        eof, cipher_registered, writable, terminal = False, True, True, False
        stderr_done = set()
        with selectors.DefaultSelector() as selector:
            for index, process in enumerate(processes):
                os.set_blocking(process.stderr.fileno(), False)
                selector.register(process.stderr, selectors.EVENT_READ, ('stderr', index))
            for stream in (encryptor.stdout, remote.stdout, remote.stdin):
                os.set_blocking(stream.fileno(), False)
            selector.register(encryptor.stdout, selectors.EVENT_READ, ('cipher', None))
            selector.register(remote.stdout, selectors.EVENT_READ, ('receipt', None))
            selector.register(remote.stdin, selectors.EVENT_WRITE, ('send', None))

            def enable_send():
                nonlocal writable
                if pending and not writable:
                    selector.register(remote.stdin, selectors.EVENT_WRITE, ('send', None))
                    writable = True

            while selector.get_map():
                for key, _ in selector.select(min(remaining(end), .2)):
                    label, index = key.data
                    if label == 'send':
                        try:
                            sent = os.write(key.fd, pending)
                        except BlockingIOError:
                            continue
                        except BrokenPipeError:
                            raise Refused('pipe_failed') from None
                        if sent <= 0:
                            raise Refused('pipe_failed')
                        del pending[:sent]
                        if not pending:
                            selector.unregister(remote.stdin)
                            writable = False
                            if terminal:
                                remote.stdin.close()
                        if not eof and not cipher_registered and len(pending) < 4 * BLOCK:
                            selector.register(encryptor.stdout, selectors.EVENT_READ, ('cipher', None))
                            cipher_registered = True
                        continue
                    try:
                        data = os.read(key.fd, BLOCK)
                    except BlockingIOError:
                        continue
                    if not data:
                        selector.unregister(key.fileobj)
                        if label == 'cipher':
                            eof, cipher_registered = True, False
                            if fragment:
                                pending.extend(struct.pack('>I', len(fragment)))
                                pending.extend(fragment)
                                fragment.clear()
                                enable_send()
                        elif label == 'stderr':
                            stderr_done.add(index)
                    elif label == 'stderr':
                        errors += len(data)
                        if errors > MAX_STDERR:
                            raise Refused('output_limit')
                    elif label == 'receipt':
                        receipt.extend(data)
                        if len(receipt) > MAX_RECEIPT:
                            raise Refused('receipt_invalid')
                    else:
                        count += len(data)
                        if count > max_cipher:
                            raise Refused('cipher_limit')
                        digest.update(data)
                        fragment.extend(data)
                        while len(fragment) >= FRAME_BYTES:
                            pending.extend(struct.pack('>I', FRAME_BYTES))
                            pending.extend(fragment[:FRAME_BYTES])
                            del fragment[:FRAME_BYTES]
                        enable_send()
                        if len(pending) >= 4 * BLOCK:
                            selector.unregister(encryptor.stdout)
                            cipher_registered = False
                upstream = (producer.poll(), encryptor.poll())
                if any(code is not None and code != 0 for code in upstream):
                    raise Refused('pipeline_failed')
                if not terminal and remote.poll() is not None:
                    raise Refused('pipeline_failed')
                if not terminal and eof and {0, 1}.issubset(stderr_done) and upstream == (0, 0):
                    if not count:
                        raise Refused('pipeline_failed')
                    # This is the sole commit signal. An interrupted pipeline
                    # closes without it, even when GPG encrypted a valid prefix.
                    pending.extend(struct.pack('>IQ', 0, count))
                    pending.extend(digest.digest())
                    terminal = True
                    enable_send()
        if (any(process.wait(timeout=remaining(end)) != 0 for process in processes)
                or not terminal or not eof or pending or fragment or count == 0):
            raise Refused('pipeline_failed')
        result = strict_json(receipt)
        if (not isinstance(result, dict) or set(result) != {'status', 'bytes', 'sha256'}
                or result['status'] != 'received_unverified' or type(result['bytes']) is not int
                or result['bytes'] != count or result['sha256'] != digest.hexdigest()):
            raise Refused('receipt_invalid')
        return {'bytes': count, 'sha256': digest.hexdigest()}
    except subprocess.TimeoutExpired:
        raise Refused('deadline_exceeded') from None
    finally:
        close_processes(processes)


def stream_fetch(ssh, receipt, output, files=None, timeout=DEADLINE):
    """Failures retain the partial or published final. Never overwrite either."""
    files = files or Files()
    validate_sent(receipt)
    processes = []
    end = time.monotonic() + timeout
    with files.parent(output) as (parent, name):
        partial = name + '.partial'
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise Refused('file_exists')
        space = os.fstatvfs(parent)
        if space.f_bavail * space.f_frsize < receipt['bytes'] + RESERVE:
            raise Refused('space_insufficient')
        fd = os.open(partial, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        try:
            os.fchmod(fd, 0o600)
            original = os.fstat(fd)
            os.fsync(parent)
            digest, count, errors = hashlib.sha256(), 0, 0
            process = spawn(ssh, processes, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with selectors.DefaultSelector() as selector:
                for stream, label in ((process.stdout, 'cipher'), (process.stderr, 'stderr')):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, label)
                while selector.get_map():
                    for key, _ in selector.select(min(remaining(end), .2)):
                        try:
                            data = os.read(key.fd, BLOCK)
                        except BlockingIOError:
                            continue
                        if not data:
                            selector.unregister(key.fileobj)
                        elif key.data == 'stderr':
                            errors += len(data)
                            if errors > MAX_STDERR:
                                raise Refused('output_limit')
                        else:
                            if count + len(data) > receipt['bytes']:
                                raise Refused('cipher_limit')
                            space = os.fstatvfs(parent)
                            if space.f_bavail * space.f_frsize < len(data) + RESERVE:
                                raise Refused('space_insufficient')
                            write_all(fd, data)
                            digest.update(data)
                            count += len(data)
            if process.wait(timeout=remaining(end)) != 0:
                raise Refused('pipeline_failed')
            if count != receipt['bytes'] or digest.hexdigest() != receipt['sha256']:
                raise Refused('cipher_mismatch')
            os.fsync(fd)
            expected = os.fstat(fd)
            if (dir_identity(expected) != dir_identity(original) or expected.st_nlink != 1
                    or expected.st_size != count or stat.S_IMODE(expected.st_mode) != 0o600
                    or identity(os.stat(partial, dir_fd=parent, follow_symlinks=False)) != identity(expected)):
                raise Refused('path_changed')
            os.lseek(fd, 0, os.SEEK_SET)
            reread, size = hashlib.sha256(), 0
            while True:
                remaining(end)
                data = os.read(fd, BLOCK)
                if not data:
                    break
                reread.update(data)
                size += len(data)
                if size > receipt['bytes']:
                    raise Refused('cipher_limit')
            if size != count or reread.hexdigest() != receipt['sha256']:
                raise Refused('cipher_mismatch')
            if (identity(os.fstat(fd)) != identity(expected) or
                    identity(os.stat(partial, dir_fd=parent, follow_symlinks=False)) != identity(expected)):
                raise Refused('path_changed')
            os.link(partial, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
            os.fsync(parent)
            # Linking changes ctime/nlink; every name and the pinned fd must
            # still refer to the same private ciphertext immediately before unlink.
            def publication_identity(info):
                return (dir_identity(info), info.st_size, info.st_mtime_ns)
            publication = publication_identity(expected)
            def recheck_publication():
                published = os.fstat(fd)
                if (publication_identity(published) != publication or published.st_nlink != 2
                        or not stat.S_ISREG(published.st_mode)
                        or stat.S_IMODE(published.st_mode) != 0o600):
                    raise Refused('path_changed')
                for info in (os.stat(name, dir_fd=parent, follow_symlinks=False),
                             os.stat(partial, dir_fd=parent, follow_symlinks=False),
                             os.fstat(fd)):
                    if identity(info) != identity(published):
                        raise Refused('path_changed')
            try:
                recheck_publication()
            except OSError:
                raise Refused('path_changed') from None
            os.unlink(partial, dir_fd=parent)
            os.fsync(parent)
            return {'status': 'fetched_unverified', 'session': SESSION,
                    'plan_sha256': receipt['plan_sha256'], 'bytes': count, 'sha256': digest.hexdigest()}
        except subprocess.TimeoutExpired:
            raise Refused('deadline_exceeded') from None
        finally:
            try:
                close_processes(processes)
            finally:
                os.close(fd)


def assets(files, directory):
    public = files.read(directory + '/recovery-public.asc', 16384)
    hosts = files.read(directory + '/server-b-known-hosts', 1024)
    if hashlib.sha256(public).hexdigest() != PUBLIC_HASH or hashlib.sha256(hosts).hexdigest() != HOSTS_HASH:
        raise Refused('asset_invalid')
    try:
        fields = hosts.decode('ascii').strip().split()
        if fields[:2] != ['139.162.109.181', 'ssh-ed25519'] or len(fields) != 3:
            raise ValueError()
        fingerprint = base64.b64encode(hashlib.sha256(base64.b64decode(fields[2], validate=True)).digest())
        if fingerprint.decode().rstrip('=') != HOST_FINGERPRINT:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise Refused('asset_invalid') from None
    return public, hosts


def ssh_args(key, hosts, action):
    if action not in (RECEIVE, FETCH):
        raise Refused('internal_failure')
    if any(ord(char) < 32 or ord(char) == 127 for char in hosts):
        raise Refused('unsafe_path')
    hosts_option = '"' + hosts.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-i', key,
        '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'PreferredAuthentications=publickey', '-o', 'PasswordAuthentication=no',
        '-o', 'KbdInteractiveAuthentication=no', '-o', 'UserKnownHostsFile=' + hosts_option,
        '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no',
        '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'ForwardAgent=no',
        '-o', 'ClearAllForwardings=yes', '-o', 'ControlMaster=no', '-o', 'ControlPath=none',
        '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
        DESTINATION, action]


def gpg_args(home, *extra):
    return ['/usr/bin/gpg', '--no-options', '--homedir', home, '--batch', '--no-tty',
        '--no-autostart', '--no-auto-key-retrieve', '--auto-key-locate', 'clear', *extra]


def send(args, files=None):
    if os.geteuid() != 0:
        raise Refused('root_required')
    files = files or Files()
    if not HEX.fullmatch(args.plan_sha256):
        raise Refused('plan_invalid')
    raw = files.read(args.plan, MAX_PLAN, 0o600)
    try:
        plan = strict_json(raw)
    except Refused:
        raise Refused('plan_invalid') from None
    if hashlib.sha256(raw).hexdigest() != args.plan_sha256 or canonical(plan) != raw:
        raise Refused('plan_invalid')
    base = str(Path(__file__).resolve().parent)
    public, hosts = assets(files, base + '/preservation')
    with files.opened(args.transport_key, 0o600), files.opened(args.plan, 0o600):
        with files.opened(base + '/naver_archive_source.py'), files.opened('/usr/bin/gpg'), files.opened('/usr/bin/ssh'):
            files.mkdir(args.session_dir)
            files.create(args.session_dir + '/attempt.json', canonical({
                'session': SESSION, 'plan_sha256': args.plan_sha256, 'status': 'started'}))
            files.create(args.session_dir + '/recovery-public.asc', public)
            files.create(args.session_dir + '/server-b-known-hosts', hosts)
            home = args.session_dir + '/gpg'
            files.mkdir(home)
            command(gpg_args(home, '--import', args.session_dir + '/recovery-public.asc'))
            listing = command(gpg_args(home, '--with-colons', '--fingerprint', '--list-keys'))
            try:
                lines = listing.decode('ascii').splitlines()
                public_keys = [line for line in lines if line.startswith('pub:')]
                fingerprints = [line.split(':')[9] for line in lines
                    if line.startswith('fpr:') and len(line.split(':')) > 9]
                if (len(public_keys) != 1 or not fingerprints or fingerprints[0] != RECIPIENT
                        or any(line.startswith(('sec:', 'ssb:')) for line in lines)):
                    raise ValueError()
            except (UnicodeError, ValueError):
                raise Refused('recipient_invalid') from None
            result = stream_send([sys.executable, '-I', '-B', base + '/naver_archive_source.py',
                'stream', '--plan', args.plan, '--plan-sha256', args.plan_sha256],
                gpg_args(home, '--trust-model', 'always', '--compress-algo', 'none',
                    '--cipher-algo', 'AES256', '--recipient', RECIPIENT, '--encrypt'),
                ssh_args(args.transport_key, args.session_dir + '/server-b-known-hosts', RECEIVE))
            receipt = {'status': 'sent_unverified', 'session': SESSION,
                       'plan_sha256': args.plan_sha256, **result}
            files.create(args.session_dir + '/sent.json', canonical(receipt))
            return receipt


def fetch(args, files=None):
    files = files or Files()
    if not HEX.fullmatch(args.receipt_sha256):
        raise Refused('receipt_invalid')
    raw = files.read(args.sent_receipt, MAX_RECEIPT, 0o600)
    if hashlib.sha256(raw).hexdigest() != args.receipt_sha256:
        raise Refused('receipt_invalid')
    receipt = validate_sent(strict_json(raw))
    base = str(Path(__file__).resolve().parent)
    assets(files, base + '/preservation')
    hosts = base + '/preservation/server-b-known-hosts'
    with files.opened(args.transport_key, 0o600), files.opened(hosts), files.opened('/usr/bin/ssh'):
        return stream_fetch(ssh_args(args.transport_key, hosts, FETCH), receipt, args.output, files)


def interrupted(number, frame):
    raise Refused('interrupted')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    sending = modes.add_parser('send')
    sending.add_argument('--plan', required=True)
    sending.add_argument('--plan-sha256', required=True)
    sending.add_argument('--transport-key', required=True,
                         help='Explicit new session SSH transport key; never a recovery key')
    sending.add_argument('--session-dir', required=True,
                         help='New absolute directory; retained to prevent blind retries')
    fetching = modes.add_parser('fetch')
    fetching.add_argument('--sent-receipt', required=True)
    fetching.add_argument('--receipt-sha256', required=True)
    fetching.add_argument('--transport-key', required=True)
    fetching.add_argument('--output', required=True, help='New absolute ciphertext path')
    args = parser.parse_args(argv)
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    os.umask(0o077)
    try:
        result = send(args) if args.mode == 'send' else fetch(args)
    except BaseException as error:
        code = error.code if isinstance(error, Refused) else 'internal_failure'
        result = {'status': 'failed', 'session': SESSION, 'error': code}
        print(json.dumps(result, sort_keys=True), flush=True)
        return 2
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
