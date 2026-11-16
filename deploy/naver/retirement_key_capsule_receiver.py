#!/usr/bin/env python3
"""Receive one original-key capsule ciphertext; never parse plaintext. A receipt never means a verified backup."""
import contextlib
import fcntl
import hashlib
import json
import os
import signal
import stat
import sys

PARENTS = ('var', 'backups', 'metainc-app-retirement', 'key-capsule-20261102-v1')
COMMAND = 'receive-key-capsule-20261102-v1'
DESTINATION = 'keys.gpg.pending'
PARTIAL = 'keys.gpg.partial'
LOCK = '.receive.lock'
OWNER_UID, OWNER_GID = 0, 0
MAX_BYTES = 1024 * 1024
MIN_FREE_BYTES = 16 * 1024 * 1024
TIMEOUT_SECONDS = 300
BLOCK_BYTES = 64 * 1024
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


class ReceiverError(Exception):
    def __init__(self, code):
        self.code = code


class DeadlineExpired(BaseException):
    """Do not let normal I/O error handling swallow the absolute deadline."""


def receipt(status, count=0, digest=None):
    return {'status': status, 'bytes': count, 'sha256': digest}


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def optional_stat(parent, name):
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def directory_ok(info, private=False):
    return (stat.S_ISDIR(info.st_mode) and info.st_uid == OWNER_UID
            and info.st_gid == OWNER_GID and not info.st_mode & 0o022
            and (not private or stat.S_IMODE(info.st_mode) == 0o700))


def file_ok(info, links=1):
    return (stat.S_ISREG(info.st_mode) and info.st_uid == OWNER_UID
            and info.st_gid == OWNER_GID and info.st_nlink == links
            and stat.S_IMODE(info.st_mode) == 0o600)


def validate_chain(root, root_identity, chain):
    if identity(os.fstat(root)) != root_identity:
        raise ReceiverError('namespace_changed')
    for parent, name, child, expected in chain:
        if (identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != expected
                or identity(os.fstat(child)) != expected):
            raise ReceiverError('namespace_changed')


@contextlib.contextmanager
def namespace(root):
    """The production root is always /. Tests pass only a synthetic root fd."""
    with contextlib.ExitStack() as stack:
        before = os.fstat(root)
        if not directory_ok(before):
            raise ReceiverError('namespace_unsafe')
        root_identity, chain, parent = identity(before), [], root
        for index, name in enumerate(PARENTS):
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not directory_ok(before, private=index >= 2):
                raise ReceiverError('namespace_unsafe')
            child = os.open(name, DIRECTORY_FLAGS, dir_fd=parent)
            stack.callback(os.close, child)
            expected = identity(before)
            if identity(os.fstat(child)) != expected:
                raise ReceiverError('namespace_changed')
            chain.append((parent, name, child, expected))
            parent = child
        validate = lambda: validate_chain(root, root_identity, chain)
        validate()
        yield parent, validate


@contextlib.contextmanager
def exclusive_lock(folder):
    before = optional_stat(folder, LOCK)
    if before is not None and not file_ok(before):
        raise ReceiverError('lock_unsafe')
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    if before is None:
        flags |= os.O_CREAT | os.O_EXCL
    fd = os.open(LOCK, flags, 0o600, dir_fd=folder)
    try:
        actual = os.fstat(fd)
        if not file_ok(actual) or (before is not None and identity(before) != identity(actual)):
            raise ReceiverError('lock_unsafe')
        linked = os.stat(LOCK, dir_fd=folder, follow_symlinks=False)
        if identity(linked) != identity(actual) or not file_ok(linked):
            raise ReceiverError('lock_unsafe')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReceiverError('busy') from None
        yield
    finally:
        os.close(fd)


def validate_partial(folder, fd, expected, links=1, name=PARTIAL):
    actual = os.fstat(fd)
    linked = os.stat(name, dir_fd=folder, follow_symlinks=False)
    if (identity(actual) != expected or identity(linked) != expected
            or not file_ok(actual, links) or not file_ok(linked, links)):
        raise ReceiverError('partial_changed')


def receive_into(stream, root, state):
    with namespace(root) as (folder, validate), exclusive_lock(folder):
        validate()
        if optional_stat(folder, DESTINATION) is not None:
            raise ReceiverError('destination_exists')
        if optional_stat(folder, PARTIAL) is not None:
            raise ReceiverError('partial_exists')
        available = os.fstatvfs(folder)
        if available.f_bavail * available.f_frsize < MIN_FREE_BYTES:
            raise ReceiverError('insufficient_space')
        validate()
        fd = os.open(PARTIAL, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o600, dir_fd=folder)
        try:
            expected = identity(os.fstat(fd))
            validate_partial(folder, fd, expected)
            os.fsync(folder)  # Persist the partial name, including on later failure.
            digest = hashlib.sha256()
            while True:
                block = stream.read(min(BLOCK_BYTES, MAX_BYTES + 1 - state['bytes']))
                if not block:
                    break
                if not isinstance(block, bytes) or state['bytes'] + len(block) > MAX_BYTES:
                    raise ReceiverError('size_limit')
                validate()
                validate_partial(folder, fd, expected)
                free = os.fstatvfs(folder)
                if free.f_bavail * free.f_frsize < len(block):
                    raise ReceiverError('insufficient_space')
                pending = memoryview(block)
                while pending:
                    written = os.write(fd, pending)
                    if written <= 0:
                        raise ReceiverError('write_failed')
                    state['bytes'] += written
                    digest.update(pending[:written])
                    pending = pending[written:]
            if not state['bytes']:
                raise ReceiverError('empty_stream')
            os.fsync(fd)
            validate()
            validate_partial(folder, fd, expected)
            if os.fstat(fd).st_size != state['bytes']:
                raise ReceiverError('reread_mismatch')
            os.lseek(fd, 0, os.SEEK_SET)
            reread, count = hashlib.sha256(), 0
            while True:
                block = os.read(fd, min(BLOCK_BYTES, MAX_BYTES + 1 - count))
                if not block:
                    break
                count += len(block)
                if count > MAX_BYTES:
                    raise ReceiverError('reread_mismatch')
                reread.update(block)
            if count != state['bytes'] or reread.digest() != digest.digest():
                raise ReceiverError('reread_mismatch')
            validate()
            validate_partial(folder, fd, expected)
            # link is atomic and refuses an existing destination. No rename overwrite.
            try:
                os.link(PARTIAL, DESTINATION, src_dir_fd=folder, dst_dir_fd=folder,
                        follow_symlinks=False)
            except FileExistsError:
                raise ReceiverError('destination_exists') from None
            validate_partial(folder, fd, expected, links=2, name=DESTINATION)
            os.fsync(folder)
            validate()
            validate_partial(folder, fd, expected, links=2)
            os.unlink(PARTIAL, dir_fd=folder)
            os.fsync(folder)
            validate()
            validate_partial(folder, fd, expected, name=DESTINATION)
            return receipt('received_unverified', count, reread.hexdigest())
        finally:
            # Failed or interrupted partials are deliberately never deleted here.
            os.close(fd)


def receive(stream, state):
    root = os.open('/', DIRECTORY_FLAGS)
    try:
        return receive_into(stream, root, state)
    finally:
        os.close(root)


def expired(signum, frame):
    raise DeadlineExpired()


def main():
    state = {'bytes': 0}
    answer = receipt('command_refused')
    if len(sys.argv) != 1:
        answer = receipt('arguments_refused')
    elif os.geteuid() != 0:
        answer = receipt('root_required')
    elif os.environ.get('SSH_ORIGINAL_COMMAND') == COMMAND:
        previous = None
        try:
            previous = signal.signal(signal.SIGALRM, expired)
            os.umask(0o077)
            signal.setitimer(signal.ITIMER_REAL, TIMEOUT_SECONDS)
            answer = receive(sys.stdin.buffer, state)
        except DeadlineExpired:
            answer = receipt('deadline_exceeded', state['bytes'])
        except ReceiverError as error:
            answer = receipt(error.code, state['bytes'])
        except Exception:
            answer = receipt('receive_failed', state['bytes'])
        finally:
            if previous is not None:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)
    payload = json.dumps(answer, separators=(',', ':'))
    if len(payload.encode('ascii')) > 1024:
        payload = json.dumps(receipt('receipt_limit'))
        answer = receipt('receipt_limit')
    try:
        sys.stdout.write(payload + '\n')
        sys.stdout.flush()
    except Exception:
        return 2
    return 0 if answer['status'] == 'received_unverified' else 2


if __name__ == '__main__':
    sys.exit(main())
