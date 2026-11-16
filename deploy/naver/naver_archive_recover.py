#!/usr/bin/env python3
"""Authenticate a retrieved NAVER archive; optionally restore into isolation.

The output is a local verification record, not a signature or deletion authority.
Only GPG accesses the selected key home. Passphrases use its normal pinentry.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

SESSION = 'naver-archives-20261106-v1'
RECIPIENT = '78076C3BC580EB5AC684EDE8BE5DAF3D1B780CA5'
MAX_CIPHER = 12 * 1024 ** 3
MAX_JSON = 1024 * 1024
MAX_STATUS = 64 * 1024
BLOCK = 64 * 1024
TIMEOUT = 3600
RESTORE_RESERVE = 512 * 1024 ** 2
HEX = re.compile(r'[0-9a-f]{64}\Z')
FINGERPRINT = re.compile(r'(?:[0-9A-F]{40}|[0-9A-F]{64})\Z')
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
GPG_CANDIDATES = ('/opt/homebrew/bin/gpg', '/usr/local/bin/gpg', '/usr/bin/gpg')
BAD_STATUS = frozenset(('BADMDC', 'ERRMDC', 'DECRYPTION_FAILED', 'FAILURE',
    'ERROR', 'NODATA', 'NO_SECKEY', 'MISSING_PASSPHRASE', 'BAD_PASSPHRASE',
    'UNEXPECTED'))
ERRORS = frozenset(('unsafe_path', 'path_changed', 'input_invalid', 'plan_invalid',
    'plan_mismatch', 'receipt_invalid', 'cipher_mismatch', 'cipher_limit',
    'output_exists', 'output_failed', 'gpg_unavailable', 'gpg_failed',
    'gpg_status_invalid', 'gpg_unauthenticated', 'recipient_mismatch',
    'bundle_invalid', 'restore_space', 'deadline_exceeded', 'interrupted', 'internal_failure'))


class Refused(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'internal_failure'
        super().__init__(self.code)


def common_module():
    spec = importlib.util.spec_from_file_location('_naver_archive_recover_common',
        Path(__file__).with_name('naver_archive_common.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise Refused('deadline_exceeded')


def identity(value, content=False):
    result = (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid)
    if content:
        result += (value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    return result


def path_parts(path):
    if not isinstance(path, str) or not path.startswith('/') or '\x00' in path:
        raise Refused('unsafe_path')
    parts = path.split('/')[1:]
    if any(part in ('', '.', '..') for part in parts):
        raise Refused('unsafe_path')
    return parts


@contextlib.contextmanager
def directory(path, private=False):
    """Pin every component; a private leaf must belong to the invoking user."""
    parts = path_parts(path)
    with contextlib.ExitStack() as stack:
        fd = os.open('/', DIR_FLAGS)
        stack.callback(os.close, fd)
        chain = []
        for name in parts:
            before = os.stat(name, dir_fd=fd, follow_symlinks=False)
            sticky_root = before.st_uid == 0 and bool(before.st_mode & stat.S_ISVTX)
            if (not stat.S_ISDIR(before.st_mode) or before.st_uid not in (0, os.geteuid())
                    or (before.st_mode & 0o022 and not sticky_root)):
                raise Refused('unsafe_path')
            child = os.open(name, DIR_FLAGS, dir_fd=fd)
            stack.callback(os.close, child)
            expected = identity(before)
            if identity(os.fstat(child)) != expected:
                raise Refused('path_changed')
            chain.append((fd, name, child, expected))
            fd = child
        leaf = os.fstat(fd)
        if private and (leaf.st_uid != os.geteuid() or stat.S_IMODE(leaf.st_mode) != 0o700):
            raise Refused('unsafe_path')
        yield fd
        for parent, name, child, expected in chain:
            if (identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected
                    or identity(os.fstat(child)) != expected):
                raise Refused('path_changed')


class PinnedFile:
    def __init__(self, parent, parent_path, name, limit):
        self.parent, self.parent_path, self.name = parent, parent_path, name
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid not in (0, os.geteuid())
                or before.st_nlink != 1 or before.st_mode & 0o077
                or before.st_size > limit or before.st_size < 0):
            raise Refused('input_invalid')
        self.fd = os.open(name, READ_FLAGS, dir_fd=parent)
        self.expected = identity(before, True)
        try:
            self.check()
        except BaseException:
            os.close(self.fd)
            raise

    def check(self):
        if (identity(os.fstat(self.fd), True) != self.expected
                or identity(os.stat(self.name, dir_fd=self.parent,
                                    follow_symlinks=False), True) != self.expected):
            raise Refused('path_changed')

    def check_namespace(self):
        check_directory_path(self.parent_path, self.parent)
        self.check()

    def read(self, limit, deadline):
        os.lseek(self.fd, 0, os.SEEK_SET)
        data = bytearray()
        while True:
            check_deadline(deadline)
            part = os.read(self.fd, min(BLOCK, limit + 1 - len(data)))
            data.extend(part)
            if len(data) > limit:
                raise Refused('input_invalid')
            if not part:
                self.check()
                return bytes(data)

    def hashed(self, deadline):
        os.lseek(self.fd, 0, os.SEEK_SET)
        sha, size = hashlib.sha256(), 0
        while True:
            check_deadline(deadline)
            part = os.read(self.fd, BLOCK)
            if not part:
                break
            size += len(part)
            if size > MAX_CIPHER:
                raise Refused('cipher_limit')
            sha.update(part)
        self.check()
        return {'bytes': size, 'sha256': sha.hexdigest()}


@contextlib.contextmanager
def input_file(path, limit):
    parts = path_parts(path)
    parent_path = '/' + '/'.join(parts[:-1])
    with directory(parent_path) as parent:
        file = PinnedFile(parent, parent_path, parts[-1], limit)
        try:
            yield file
        finally:
            os.close(file.fd)


def check_directory_path(path, pinned, private=False):
    with directory(path, private=private) as current:
        if identity(os.fstat(current)) != identity(os.fstat(pinned)):
            raise Refused('path_changed')


def strict_json(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    try:
        value = json.loads(data, object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        pending, count = [(value, 0)], 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if depth > 24 or count > 16384:
                raise ValueError()
            if isinstance(item, dict):
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise Refused('input_invalid') from None


def transfer_cipher(receipt, plan_sha256):
    if (not isinstance(receipt, dict)
            or set(receipt) != {'status', 'session', 'plan_sha256', 'bytes', 'sha256'}
            or receipt['status'] != 'sent_unverified' or receipt['session'] != SESSION
            or receipt['plan_sha256'] != plan_sha256
            or type(receipt['bytes']) is not int or not 0 < receipt['bytes'] <= MAX_CIPHER
            or not isinstance(receipt['sha256'], str) or not HEX.fullmatch(receipt['sha256'])):
        raise Refused('receipt_invalid')
    return {'bytes': receipt['bytes'], 'sha256': receipt['sha256']}


def validate_status(data):
    """GPG's authenticated MDC success and primary decryption key are required."""
    if not data or len(data) > MAX_STATUS or not data.endswith(b'\n'):
        raise Refused('gpg_status_invalid')
    statuses = []
    for raw in data.splitlines():
        if not raw.startswith(b'[GNUPG:] ') or len(raw) > 4096:
            raise Refused('gpg_status_invalid')
        try:
            line = raw[9:].decode('ascii').split()
        except UnicodeError:
            raise Refused('gpg_status_invalid') from None
        if not line or not re.fullmatch(r'[A-Z_]+', line[0]):
            raise Refused('gpg_status_invalid')
        if line[0] in BAD_STATUS:
            raise Refused('gpg_unauthenticated')
        statuses.append(line)
    keys = [line for line in statuses if line[0] == 'DECRYPTION_KEY']
    if (len(keys) != 1 or len(keys[0]) != 4 or not FINGERPRINT.fullmatch(keys[0][1])
            or keys[0][2] != RECIPIENT):
        raise Refused('recipient_mismatch')
    for token in ('DECRYPTION_OKAY', 'GOODMDC'):
        found = [line for line in statuses if line[0] == token]
        if found != [[token]]:
            raise Refused('gpg_unauthenticated')


class DecryptedStream:
    """Read bounded plaintext directly while draining the separate status pipe."""
    def __init__(self, process, status_fd, deadline):
        self.process, self.deadline = process, deadline
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout.fileno(), selectors.EVENT_READ, 'stdout')
        self.selector.register(status_fd, selectors.EVENT_READ, 'status')
        self.status, self.stdout_eof = bytearray(), False

    def close(self):
        self.selector.close()

    def events(self):
        check_deadline(self.deadline)
        return self.selector.select(min(1, max(0, self.deadline - time.monotonic())))

    def status_part(self, fd):
        data = os.read(fd, BLOCK)
        if not data:
            self.selector.unregister(fd)
            return
        self.status.extend(data)
        if len(self.status) > MAX_STATUS:
            raise Refused('gpg_status_invalid')

    def read(self, size):
        if type(size) is not int or size < 0:
            raise Refused('bundle_invalid')
        check_deadline(self.deadline)
        if not size or self.stdout_eof:
            return b''
        while True:
            for key, unused in self.events():
                if key.data == 'status':
                    self.status_part(key.fd)
                else:
                    data = os.read(key.fd, min(size, BLOCK))
                    if not data:
                        self.selector.unregister(key.fd)
                        self.stdout_eof = True
                    return data

    def finish(self):
        if not self.stdout_eof and self.read(1):
            raise Refused('bundle_invalid')
        while self.selector.get_map():
            for key, unused in self.events():
                self.status_part(key.fd)
        check_deadline(self.deadline)
        try:
            code = self.process.wait(timeout=max(0.001, self.deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise Refused('deadline_exceeded') from None
        if code != 0:
            raise Refused('gpg_failed')
        validate_status(bytes(self.status))


def gpg_binary():
    for candidate in GPG_CANDIDATES:
        if not os.path.exists(candidate):
            continue
        resolved = os.path.realpath(candidate)
        # Installed executables use the platform's package-manager trust. For
        # example Homebrew's Cellar is commonly admin-group writable. Never
        # search PATH or apply that exception to data or key-home directories.
        value = os.stat(resolved, follow_symlinks=False)
        if (not stat.S_ISREG(value.st_mode) or value.st_uid not in (0, os.geteuid())
                or value.st_mode & 0o022 or not value.st_mode & 0o111):
            raise Refused('gpg_unavailable')
        return resolved
    raise Refused('gpg_unavailable')


def decrypt(cipher, home, plan, common, deadline, binary=None, restore_dir=None):
    read_fd, write_fd = os.pipe()
    process, stream = None, None
    succeeded = False
    try:
        os.lseek(cipher.fd, 0, os.SEEK_SET)
        argv = [binary or gpg_binary(), '--no-options', '--homedir', home,
                '--no-tty', '--no-auto-key-retrieve', '--no-auto-key-import',
                '--no-auto-check-trustdb', '--pinentry-mode', 'ask',
                '--status-fd', str(write_fd), '--output', '-', '--decrypt']
        env = {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin',
               'LANG': 'C', 'LC_ALL': 'C'}
        for name in ('GPG_TTY', 'DISPLAY', 'TERM'):
            if name in os.environ:
                env[name] = os.environ[name]
        process = subprocess.Popen(argv, stdin=cipher.fd, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, pass_fds=(write_fd,), start_new_session=True,
            bufsize=0, env=env)
        os.close(write_fd)
        write_fd = None
        stream = DecryptedStream(process, read_fd, deadline)
        try:
            if restore_dir is None:
                verified = common.verify_bundle(stream, plan)
            else:
                verified = common.restore_bundle(stream, plan, restore_dir)
        except Refused:
            raise
        except Exception:
            raise Refused('bundle_invalid') from None
        stream.finish()
        succeeded = True
        return verified
    finally:
        if process is not None:
            if not succeeded:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    # A group may disappear between EOF and cleanup (EPERM on
                    # some macOS versions). Always attempt direct kill/reaping.
                    try:
                        process.kill()
                    except OSError:
                        pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
        if stream is not None:
            stream.close()
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)


def write_receipt(parent, name, data):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(name, flags, 0o600, dir_fd=parent)
    except FileExistsError:
        raise Refused('output_exists') from None
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise Refused('output_failed')
            view = view[written:]
        os.fsync(fd)
        os.fsync(parent)
    except OSError:
        raise Refused('output_failed') from None
    finally:
        os.close(fd)


def verify(args, *, common=None, binary=None, timeout=TIMEOUT):
    common = common or common_module()
    deadline = time.monotonic() + timeout
    if not isinstance(args.plan_sha256, str) or not HEX.fullmatch(args.plan_sha256):
        raise Refused('plan_mismatch')
    output_parts = path_parts(args.output)
    output_parent_path = '/' + '/'.join(output_parts[:-1])
    with contextlib.ExitStack() as stack:
        plan_file = stack.enter_context(input_file(args.plan, MAX_JSON))
        transfer_file = stack.enter_context(input_file(args.transfer_receipt, MAX_JSON))
        cipher = stack.enter_context(input_file(args.cipher, MAX_CIPHER))
        home = stack.enter_context(directory(args.gnupg_home, private=True))
        output = stack.enter_context(directory(output_parent_path, private=True))
        try:
            os.stat(output_parts[-1], dir_fd=output, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise Refused('output_exists')
        plan = strict_json(plan_file.read(MAX_JSON, deadline))
        try:
            common.validate_plan(plan)
        except Exception:
            raise Refused('plan_invalid') from None
        if common.digest(common.canonical(plan)) != args.plan_sha256:
            raise Refused('plan_mismatch')
        expected = transfer_cipher(strict_json(transfer_file.read(MAX_JSON, deadline)), args.plan_sha256)
        if cipher.hashed(deadline) != expected:
            raise Refused('cipher_mismatch')
        verified = decrypt(cipher, args.gnupg_home, plan, common, deadline, binary)
        if cipher.hashed(deadline) != expected:
            raise Refused('cipher_mismatch')
        expected_files = common.file_rows(plan)
        if verified != {'files': expected_files}:
            raise Refused('bundle_invalid')
        restore_path = getattr(args, 'restore_dir', None)
        if restore_path is not None:
            restore_parts = path_parts(restore_path)
            restore_parent = stack.enter_context(directory(
                '/' + '/'.join(restore_parts[:-1]), private=True))
            capacity = os.fstatvfs(restore_parent)
            if capacity.f_bavail * capacity.f_frsize < plan['total_bytes'] + RESTORE_RESERVE:
                raise Refused('restore_space')
            try:
                os.mkdir(restore_parts[-1], 0o700, dir_fd=restore_parent)
            except FileExistsError:
                raise Refused('output_exists') from None
            os.fsync(restore_parent)
            # No automatic cleanup: even incomplete second-pass output remains
            # an isolated, unverified candidate until this command succeeds.
            restore_fd = stack.enter_context(directory(restore_path, private=True))
            restored = decrypt(cipher, args.gnupg_home, plan, common, deadline,
                               binary, restore_path)
            if restored != {'files': expected_files}:
                raise Refused('bundle_invalid')
            if cipher.hashed(deadline) != expected:
                raise Refused('cipher_mismatch')
            check_directory_path(restore_path, restore_fd, private=True)
        plan_file.check_namespace()
        transfer_file.check_namespace()
        cipher.check_namespace()
        check_directory_path(args.gnupg_home, home, private=True)
        check_directory_path(output_parent_path, output, private=True)
        check_deadline(deadline)
        receipt = {'version': 1, 'status': 'recovery_verified', 'session': SESSION,
            'plan_sha256': args.plan_sha256, 'cipher': expected, 'files': expected_files,
            'verification': 'gpg-authenticated-and-inner-gzip-v1'}
        write_receipt(output, output_parts[-1], common.canonical(receipt) + b'\n')
        return receipt


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('input_invalid')


def main(argv=None):
    parser = Parser(description=__doc__)
    for name in ('plan', 'plan-sha256', 'transfer-receipt', 'cipher', 'gnupg-home', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--restore-dir', help='Create a new isolated 0700 directory only after authentication')
    previous = signal.getsignal(signal.SIGTERM)
    def terminate(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, terminate)
    try:
        result = verify(parser.parse_args(argv))
        print(json.dumps({'status': result['status'], 'session': SESSION,
                          'plan_sha256': result['plan_sha256']}, sort_keys=True))
        return 0
    except KeyboardInterrupt:
        code = 'interrupted'
    except Refused as exc:
        code = exc.code
    except Exception:
        code = 'internal_failure'
    finally:
        signal.signal(signal.SIGTERM, previous)
    print(json.dumps({'status': 'refused', 'session': SESSION, 'error': code}, sort_keys=True))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
