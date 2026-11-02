#!/usr/bin/env python3
"""Receive one opaque ciphertext. A receipt never means a verified backup."""
import contextlib
import fcntl
import hashlib
import json
import os
import signal
import stat
import sys
import types

DESTINATION = 'image.gpg.pending'
PARTIAL = 'image.gpg.partial'
LOCK = '.receive.lock'
OWNER_UID, OWNER_GID = 0, 0
BLOCK_BYTES = 64 * 1024
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


PROFILE_SHA256 = 'f776e4a27ab2e66a3a34ae8c0122aadc763ae3e6145e58040e68484d699ebcd5'
PROFILE_FILE = 'retirement_image_profiles.py'
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


def load_profiles():
    """Load only hash-bound bytes from the fixed sibling, including under python -I."""
    parent = os.open(os.path.dirname(os.path.abspath(__file__)), DIR_FLAGS)
    try:
        fd = os.open(PROFILE_FILE, READ_FLAGS, dir_fd=parent)
        try:
            before = os.fstat(fd)
            expected = (before.st_dev, before.st_ino, before.st_mode, before.st_uid,
                        before.st_gid, before.st_nlink, before.st_size,
                        before.st_mtime_ns, before.st_ctime_ns)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or
                    before.st_uid not in (0, os.geteuid()) or before.st_mode & 0o022 or
                    not 0 < before.st_size <= 32768):
                raise ValueError('profile_module_refused')
            data = bytearray()
            while True:
                block = os.read(fd, min(8192, 32769 - len(data)))
                if not block:
                    break
                data.extend(block)
                if len(data) > 32768:
                    raise ValueError('profile_module_refused')
            for after in (os.fstat(fd), os.stat(PROFILE_FILE, dir_fd=parent, follow_symlinks=False)):
                actual = (after.st_dev, after.st_ino, after.st_mode, after.st_uid,
                          after.st_gid, after.st_nlink, after.st_size,
                          after.st_mtime_ns, after.st_ctime_ns)
                if actual != expected:
                    raise ValueError('profile_module_refused')
            if hashlib.sha256(data).hexdigest() != PROFILE_SHA256:
                raise ValueError('profile_module_refused')
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    module = types.ModuleType('_retirement_fixed_image_profiles_' + PROFILE_SHA256)
    module.__file__ = os.path.join(os.path.dirname(os.path.abspath(__file__)), PROFILE_FILE)
    # dataclasses resolves this name while decorating; execute the exact checked bytes.
    prior = sys.modules.get(module.__name__)
    sys.modules[module.__name__] = module
    try:
        exec(compile(bytes(data), module.__file__, 'exec'), module.__dict__)
    except BaseException:
        if prior is None:
            sys.modules.pop(module.__name__, None)
        else:
            sys.modules[module.__name__] = prior
        raise
    return module



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
def namespace(root, profile):
    """The production root is always /. Tests pass only a synthetic root fd."""
    with contextlib.ExitStack() as stack:
        before = os.fstat(root)
        if not directory_ok(before):
            raise ReceiverError('namespace_unsafe')
        root_identity, chain, parent = identity(before), [], root
        for index, name in enumerate(('var', 'backups', 'metainc-app-retirement', profile.session)):
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


def receive_into(stream, root, state, profile):
    with namespace(root, profile) as (folder, validate), exclusive_lock(folder):
        validate()
        if optional_stat(folder, DESTINATION) is not None:
            raise ReceiverError('destination_exists')
        if optional_stat(folder, PARTIAL) is not None:
            raise ReceiverError('partial_exists')
        available = os.fstatvfs(folder)
        if available.f_bavail * available.f_frsize < profile.receiver_min_free_bytes:
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
                block = stream.read(min(BLOCK_BYTES, profile.max_cipher_bytes + 1 - state['bytes']))
                if not block:
                    break
                if not isinstance(block, bytes) or state['bytes'] + len(block) > profile.max_cipher_bytes:
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
                block = os.read(fd, min(BLOCK_BYTES, profile.max_cipher_bytes + 1 - count))
                if not block:
                    break
                count += len(block)
                if count > profile.max_cipher_bytes:
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


def receive(stream, state, profile):
    root = os.open('/', DIRECTORY_FLAGS)
    try:
        return receive_into(stream, root, state, profile)
    finally:
        os.close(root)


def expired(signum, frame):
    raise DeadlineExpired()


def main():
    state = {'bytes': 0}
    answer = receipt('command_refused')
    profile = None
    try:
        if len(sys.argv) == 2:
            profile = load_profiles().lookup(sys.argv[1])
    except Exception:
        pass
    if profile is None:
        answer = receipt('profile_refused')
    elif os.geteuid() != 0:
        answer = receipt('root_required')
    elif os.environ.get('SSH_ORIGINAL_COMMAND') == profile.command:
        previous = None
        try:
            previous = signal.signal(signal.SIGALRM, expired)
            os.umask(0o077)
            signal.setitimer(signal.ITIMER_REAL, profile.receiver_timeout_seconds)
            answer = receive(sys.stdin.buffer, state, profile)
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
