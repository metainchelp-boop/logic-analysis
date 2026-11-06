"""Pinned Mac operator for one new B receiver session; no private key transport."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import selectors
import shlex
import signal
import stat
import subprocess
import sys
import time
import base64

SESSION = 'naver-archives-20261106-v1'
CONTROLLER_SHA256 = 'f058ae0585643b461fcaf5cdba7c43a48cebbfff9b43e15f7726231a0c92bebc'
RECEIVER_SHA256 = '68ced288ad852e88cf177a0ffa0c775f781129d75a8307dd0e387466931219c9'
KNOWN_HOSTS_SHA256 = '263a7fd1c7fe50257fec9223c4cb2015d4e4ff575c0f8c7d362225c589204675'
SERVER = 'root@139.162.109.181'
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LANG': 'C', 'LC_ALL': 'C'}
MAX_RESULT = 16384
MAX_IO = 131072
ERRORS = frozenset(('path_refused', 'path_changed', 'file_refused', 'bundle_refused',
                    'input_refused', 'output_exists', 'remote_unknown', 'deadline_exceeded',
                    'output_limit', 'receipt_refused', 'operation_failed'))


class Refused(Exception):
    pass


def identity(s):
    return s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_gid


def content_identity(s):
    return identity(s) + (s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_nlink)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise Refused('receipt_refused')
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise Refused('receipt_refused') from None


class LocalFiles:
    """No symlink ancestors; actual user's private work directory, never /tmp aliases."""
    @contextlib.contextmanager
    def parent(self, path):
        path = Path(path)
        if not path.is_absolute() or '..' in path.parts or path.name in ('', '.', '..'):
            raise Refused('path_refused')
        with contextlib.ExitStack() as stack:
            parent = os.open('/', FLAGS)
            stack.callback(os.close, parent)
            chain = []
            for name in path.parts[1:-1]:
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if (not stat.S_ISDIR(before.st_mode) or before.st_uid not in (0, os.getuid())
                        or before.st_mode & 0o022):
                    raise Refused('path_refused')
                child = os.open(name, FLAGS, dir_fd=parent)
                stack.callback(os.close, child)
                if identity(before) != identity(os.fstat(child)):
                    raise Refused('path_changed')
                chain.append((parent, name, child, identity(before)))
                parent = child
            yield parent, path.name
            for folder, name, fd, expected in chain:
                if (identity(os.stat(name, dir_fd=folder, follow_symlinks=False)) != expected
                        or identity(os.fstat(fd)) != expected):
                    raise Refused('path_changed')

    def read(self, path, limit, private=False, metadata_only=False):
        with self.parent(path) as (parent, name):
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if private and before.st_uid != os.getuid():
                raise Refused('file_refused')
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid not in (0, os.getuid()) or before.st_mode & 0o022
                    or before.st_size > limit or before.st_size < 1
                    or (private and stat.S_IMODE(before.st_mode) != 0o600)):
                raise Refused('file_refused')
            if metadata_only:
                return content_identity(before)
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
            try:
                if content_identity(os.fstat(fd)) != content_identity(before):
                    raise Refused('path_changed')
                result = bytearray()
                while True:
                    block = os.read(fd, min(8192, limit + 1 - len(result)))
                    if not block:
                        break
                    result.extend(block)
                    if len(result) > limit:
                        raise Refused('file_refused')
                if (content_identity(os.fstat(fd)) != content_identity(before)
                        or content_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != content_identity(before)):
                    raise Refused('path_changed')
                return bytes(result)
            finally:
                os.close(fd)

    @contextlib.contextmanager
    def output(self, path):
        with self.parent(path) as (parent, name):
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise Refused('path_refused')
            try:
                fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=parent)
            except FileExistsError:
                raise Refused('output_exists') from None
            try:
                original = identity(os.fstat(fd))
                os.fsync(parent)

                def save(value):
                    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                    if len(raw) > MAX_RESULT:
                        raise Refused('output_limit')
                    current = os.fstat(fd)
                    linked = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if (identity(current) != original or identity(linked) != original
                            or current.st_nlink != 1 or linked.st_nlink != 1 or current.st_size != 0):
                        raise Refused('path_changed')
                    remaining = memoryview(raw)
                    while remaining:
                        written = os.write(fd, remaining)
                        if written <= 0:
                            raise Refused('operation_failed')
                        remaining = remaining[written:]
                    os.fsync(fd)
                    if (content_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
                            != content_identity(os.fstat(fd))):
                        raise Refused('path_changed')
                    os.fsync(parent)
                    return digest(raw)

                yield save
            finally:
                # Keep the reserved/partial output on failure: never automatically rerun.
                os.close(fd)


def bundle(files, directory):
    controller = files.read(directory / 'naver_archive_receiver_control.py', 131072)
    receiver = files.read(directory / 'naver_archive_receiver.py', 65536)
    known = directory / 'preservation/server-b-known-hosts'
    if (digest(controller) != CONTROLLER_SHA256 or digest(receiver) != RECEIVER_SHA256
            or digest(files.read(known, 1024)) != KNOWN_HOSTS_SHA256):
        raise Refused('bundle_refused')
    namespace = {'__name__': 'pinned_receiver_control'}
    exec(compile(controller, '<pinned-public-controller>', 'exec'), namespace)
    if namespace.get('RECEIVER_SHA256') != RECEIVER_SHA256 or namespace.get('SESSION') != SESSION:
        raise Refused('bundle_refused')
    return controller, receiver, known, namespace


def ssh_command(admin_key, known, controller):
    if any(char in str(known) for char in ('"', '\\', '\n', '\r', '\0')):
        raise Refused('path_refused')
    remote = '/usr/bin/python3 -I -B -c ' + shlex.quote(controller.decode('utf-8'))
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-i', str(admin_key),
            '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile="' + str(known) + '"', '-o', 'GlobalKnownHostsFile=/dev/null',
            '-o', 'IdentityAgent=none',
            '-o', 'HostKeyAlgorithms=ssh-ed25519', '-o', 'UpdateHostKeys=no',
            '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no', '-o', 'ClearAllForwardings=yes',
            '-o', 'ProxyCommand=none', '-o', 'ProxyJump=none', '-o', 'ControlMaster=no',
            '-o', 'ControlPath=none', '-o', 'ConnectTimeout=10', '-o', 'ServerAliveInterval=15',
            '-o', 'ServerAliveCountMax=2', '-o', 'LogLevel=ERROR', SERVER, remote]


def exchange(argv, request, timeout=90):
    payload = json.dumps(request, separators=(',', ':')).encode()
    if len(payload) > MAX_IO:
        raise Refused('input_refused')
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=ENV, cwd='/', start_new_session=True)
    end, sent, size, output = time.monotonic() + timeout, 0, 0, bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            for pipe, events, label in ((process.stdin, selectors.EVENT_WRITE, 'send'),
                                        (process.stdout, selectors.EVENT_READ, 'out'),
                                        (process.stderr, selectors.EVENT_READ, 'err')):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, events, label)
            while selector.get_map():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    raise Refused('deadline_exceeded')
                for key, _ in selector.select(min(remaining, .2)):
                    if key.data == 'send':
                        try:
                            count = os.write(key.fd, payload[sent:])
                        except BlockingIOError:
                            continue
                        if count <= 0:
                            raise Refused('remote_unknown')
                        sent += count
                        if sent == len(payload):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                    else:
                        try:
                            block = os.read(key.fd, 8192)
                        except BlockingIOError:
                            continue
                        if not block:
                            selector.unregister(key.fileobj)
                            continue
                        size += len(block)
                        if size > MAX_IO:
                            raise Refused('output_limit')
                        if key.data == 'out':
                            output.extend(block)
                            if len(output) > MAX_RESULT:
                                raise Refused('output_limit')
        rc = process.wait(timeout=max(.01, end - time.monotonic()))
        if rc not in (0, 2):
            raise Refused('remote_unknown')
        return rc, strict_json(output)
    except (OSError, subprocess.TimeoutExpired):
        raise Refused('remote_unknown') from None
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            if process.poll() is None:
                # A group may already be gone or inaccessible on macOS. Still
                # stop/reap our direct SSH child and always close local pipes.
                process.kill()
                process.wait(timeout=2)
        finally:
            for pipe in (process.stdin, process.stdout, process.stderr):
                if not pipe.closed:
                    pipe.close()


def run(args, files=None, remote=exchange, directory=None):
    files = files or LocalFiles()
    directory = directory or Path(__file__).absolute().parent
    controller, receiver, known, ns = bundle(files, directory)
    admin_identity = files.read(args.admin_key, 32768, private=True, metadata_only=True)
    if args.action == 'install':
        def key(path):
            parts = files.read(path, 1024).decode('ascii').strip().split()
            if len(parts) not in (2, 3):
                raise Refused('input_refused')
            return ' '.join(parts[:2])
        request = dict(action='install', send_public_key=key(args.send_public_key),
                       fetch_public_key=key(args.fetch_public_key), source_ip=args.source_ip,
                       fetch_ip=args.fetch_ip, receiver_b64=base64.b64encode(receiver).decode())
    else:
        raw = files.read(args.installed, MAX_RESULT, private=True)
        if digest(raw) != args.receipt_sha256:
            raise Refused('receipt_refused')
        installed = strict_json(raw)
        ns['validate_result'](installed)
        request = dict(action='revoke', installed=installed)
    ns['validate_request'](request)
    with files.output(args.output) as save:
        rc, result = remote(ssh_command(args.admin_key, known, controller), request)
        ns['validate_result'](result)
        if result['action'] != args.action or result['session'] != SESSION:
            raise Refused('receipt_refused')
        if (rc == 0) != (result['status'] in ('installed', 'revoked', 'already_absent')):
            raise Refused('receipt_refused')
        if args.action == 'install':
            for name in ('source_ip', 'fetch_ip'):
                if result[name] is not None and result[name] != request[name]:
                    raise Refused('receipt_refused')
            for field, name in (('send_key_sha256', 'send_public_key'), ('fetch_key_sha256', 'fetch_public_key')):
                if result[field] is not None and result[field] != digest(request[name].encode('ascii')):
                    raise Refused('receipt_refused')
        elif result['secondary_published']:
            for field in ('expires_at', 'source_ip', 'fetch_ip', 'send_key_sha256', 'fetch_key_sha256',
                          'secondary', 'pending', 'receiver', 'tool_directory', 'data_directory'):
                if result[field] != installed[field]:
                    raise Refused('receipt_refused')
        receipt_sha = save(result)
        if files.read(args.admin_key, 32768, private=True, metadata_only=True) != admin_identity:
            raise Refused('path_changed')
    return {'status': result['status'], 'error': result['error'], 'session': SESSION,
            'receipt_sha256': receipt_sha, 'primary_unchanged': result['primary_unchanged']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    for action in ('install', 'revoke'):
        command = commands.add_parser(action)
        command.add_argument('--admin-key', type=Path, required=True)
        command.add_argument('--output', type=Path, required=True)
        if action == 'install':
            command.add_argument('--send-public-key', type=Path, required=True)
            command.add_argument('--fetch-public-key', type=Path, required=True)
            command.add_argument('--source-ip', required=True)
            command.add_argument('--fetch-ip', required=True)
        else:
            command.add_argument('--installed', type=Path, required=True)
            command.add_argument('--receipt-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except Exception as error:
        code = str(error) if isinstance(error, Refused) and str(error) in ERRORS else 'operation_failed'
        result = {'status': 'HOLD', 'error': code, 'session': SESSION, 'retry_authorized': False}
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['status'] in ('installed', 'revoked', 'already_absent') else 2


if __name__ == '__main__':
    sys.exit(main())
