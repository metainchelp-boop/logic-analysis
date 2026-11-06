"""Plan/stream/clean only fixed historical archives, never live backup files.

Cleanup trusts an operator-installed root-only recovery receipt and its separately
reviewed SHA. The receipt is not a signature or proof against a malicious root.
"""
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path
import signal
import stat
import sys

_spec = importlib.util.spec_from_file_location('naver_archive_common', Path(__file__).with_name('naver_archive_common.py'))
c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c)

OWNER_UID, OWNER_GID = 0, 0
PARENT = ('var', 'backups', 'metainc')
COLD_PARENT = 'naver-cold-archives'
JOURNAL = 'naver-archives-20261106-v1.cleanup.jsonl'
FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
CONFIRM = 'REMOVE_ONLY_RECOVERY_VERIFIED_NAVER_ARCHIVES_20261106'
TIMEOUT = 3600


def identity(info):
    return c.cold.identity(info)


def dir_id(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def check_dir(info, private=False):
    c.need(stat.S_ISDIR(info.st_mode) and info.st_uid == OWNER_UID and info.st_gid == OWNER_GID
           and not info.st_mode & 0o022 and (not private or stat.S_IMODE(info.st_mode) == 0o700),
           'unsafe_directory')


@contextlib.contextmanager
def namespace(root, exclusive=False):
    with contextlib.ExitStack() as stack:
        chain, parent = [], root
        check_dir(os.fstat(root))
        for name in PARENT:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            # Existing deploy tooling restricts individual backup directories,
            # not the shared metainc ancestor. Never require chmod on that parent.
            check_dir(before)
            child = os.open(name, FLAGS, dir_fd=parent)
            stack.callback(os.close, child)
            c.need(dir_id(before) == dir_id(os.fstat(child)), 'namespace_changed')
            chain.append((parent, name, child, dir_id(before)))
            parent = child
        try:
            fcntl.flock(parent, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise c.Refused('busy') from None
        def validate():
            for p, n, fd, expected in chain:
                c.need(dir_id(os.stat(n, dir_fd=p, follow_symlinks=False)) == expected == dir_id(os.fstat(fd)),
                       'namespace_changed')
        validate()
        yield parent, validate


def optional_stat(parent, name):
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


class Sources:
    """Pin fixed directories and every exact file before any byte work."""
    def __init__(self, parent, validate):
        self.parent, self.validate, self.stack = parent, validate, contextlib.ExitStack()
        self.groups, self.files, self.links = [], {}, []

    def folder(self, parent, name, private=True):
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        check_dir(before, private)
        fd = os.open(name, FLAGS, dir_fd=parent)
        self.stack.callback(os.close, fd)
        c.need(dir_id(before) == dir_id(os.fstat(fd)), 'namespace_changed')
        self.links.append((parent, name, fd, dir_id(before)))
        return fd

    def __enter__(self):
        try:
            parents = []
            if optional_stat(self.parent, COLD_PARENT) is not None:
                cold_parent = self.folder(self.parent, COLD_PARENT)
                names = os.listdir(cold_parent)
                c.need(set(names).issubset(c.COLD), 'unknown_cold_directory')
                parents.extend(('cold', name, cold_parent) for name in sorted(names))
            if optional_stat(self.parent, c.INTERRUPTED) is not None:
                parents.append(('interrupted', c.INTERRUPTED, self.parent))
            c.need(parents, 'no_archives')
            for kind, name, parent in parents:
                folder = self.folder(parent, name)
                files = []
                for filename in c.names_for(kind, os.listdir(folder)):
                    fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=folder)
                    self.stack.callback(os.close, fd)
                    info = os.fstat(fd)
                    broken = kind == 'interrupted' and filename == 'packed.zip.broken'
                    c.need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                           and info.st_dev == os.fstat(folder).st_dev
                           and info.st_uid in ((OWNER_UID, 10001) if broken else (OWNER_UID,))
                           and info.st_gid in ((OWNER_GID, 10001) if broken else (OWNER_GID,))
                           and stat.S_IMODE(info.st_mode) in ((0o600, 0o640, 0o644) if broken else (0o600,)),
                           'unsafe_file')
                    meta = identity(info)
                    c.need(info.st_size <= (65536 if filename.endswith('.json') else c.MAX_TOTAL), 'size_limit')
                    row = dict(name=filename, size=info.st_size, sha256=self.hash_fd(fd, meta), identity=meta)
                    files.append(row)
                    self.files[(kind, name, filename)] = (folder, fd, meta)
                self.groups.append(dict(kind=kind, name=name, identity=identity(os.fstat(folder)), files=files))
            self.plan = c.validate_plan(dict(version=1, session=c.SESSION, groups=self.groups,
                                            total_bytes=sum(f['size'] for g in self.groups for f in g['files'])))
            self.recheck()
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        self.stack.close()

    @staticmethod
    def hash_fd(fd, expected):
        os.lseek(fd, 0, os.SEEK_SET)
        h, count = hashlib.sha256(), 0
        while True:
            block = os.read(fd, min(c.CHUNK, expected['size'] - count + 1))
            if not block:
                break
            count += len(block)
            c.need(count <= expected['size'], 'source_changed')
            h.update(block)
        c.need(count == expected['size'] and identity(os.fstat(fd)) == expected, 'source_changed')
        return h.hexdigest()

    def recheck(self, removed=()):
        self.validate()
        for parent, name, fd, expected in self.links:
            c.need(dir_id(os.stat(name, dir_fd=parent, follow_symlinks=False)) == expected == dir_id(os.fstat(fd)),
                   'namespace_changed')
        removed = set(removed)
        for key, (folder, fd, expected) in self.files.items():
            if '/'.join(key) in removed:
                continue
            c.need(identity(os.fstat(fd)) == expected == identity(os.stat(key[2], dir_fd=folder, follow_symlinks=False)),
                   'source_changed')
        for group in self.groups:
            folder = self.files[(group['kind'], group['name'], group['files'][0]['name'])][0]
            expected_names = {f['name'] for f in group['files']
                              if '/'.join((group['kind'], group['name'], f['name'])) not in removed}
            c.need(set(os.listdir(folder)) == expected_names, 'source_members_changed')

    def blocks(self):
        yield c.header(self.plan)
        for group in self.groups:
            for row in group['files']:
                _, fd, expected = self.files[(group['kind'], group['name'], row['name'])]
                os.lseek(fd, 0, os.SEEK_SET)
                h, count = hashlib.sha256(), 0
                while count < row['size']:
                    block = os.read(fd, min(c.CHUNK, row['size'] - count))
                    c.need(block, 'source_truncated')
                    count += len(block)
                    h.update(block)
                    yield block
                c.need(os.read(fd, 1) == b'' and h.hexdigest() == row['sha256']
                       and identity(os.fstat(fd)) == expected, 'source_changed')
        self.recheck()


class BlockReader:
    def __init__(self, blocks):
        self.blocks, self.pending = iter(blocks), b''

    def read(self, size):
        c.need(0 <= size <= c.MAX_PLAN + c.CHUNK)
        while len(self.pending) < size:
            try:
                self.pending += next(self.blocks)
            except StopIteration:
                break
        result, self.pending = self.pending[:size], self.pending[size:]
        return result


def read_evidence(path, expected_sha, plan=False):
    c.need(c.hash_ok(expected_sha) and os.path.isabs(path), 'evidence_path')
    parts = Path(path).parts
    with contextlib.ExitStack() as stack:
        parent = os.open('/', FLAGS)
        stack.callback(os.close, parent)
        for name in parts[1:-1]:
            parent = os.open(name, FLAGS, dir_fd=parent)
            stack.callback(os.close, parent)
            check_dir(os.fstat(parent))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        stack.callback(os.close, fd)
        info = os.fstat(fd)
        c.need(stat.S_ISREG(info.st_mode) and info.st_uid == OWNER_UID and info.st_gid == OWNER_GID
               and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1 and info.st_size <= c.MAX_PLAN,
               'unsafe_evidence')
        raw = os.read(fd, c.MAX_PLAN + 1)
        c.need(len(raw) == info.st_size and c.digest(raw) == expected_sha
               and identity(os.fstat(fd)) == identity(info), 'evidence_hash')
    value = c.strict_json(raw)
    if plan:
        c.validate_plan(value)
        c.need(c.canonical(value) == raw, 'noncanonical_plan')
    return value


def validate_recovery(receipt, plan):
    keys = {'version', 'status', 'session', 'plan_sha256', 'cipher', 'files', 'verification'}
    c.need(type(receipt) is dict and set(receipt) == keys, 'recovery_receipt')
    c.need(type(receipt['version']) is int and receipt['version'] == 1
           and receipt['status'] == 'recovery_verified' and receipt['session'] == c.SESSION
           and receipt['plan_sha256'] == c.digest(c.canonical(plan))
           and receipt['verification'] == 'gpg-authenticated-and-inner-gzip-v1'
           and receipt['files'] == c.file_rows(plan), 'recovery_receipt')
    cipher = receipt['cipher']
    c.need(type(cipher) is dict and set(cipher) == {'bytes', 'sha256'}
           and c.number(cipher['bytes'], 12 * 1024 ** 3) and cipher['bytes'] > 0
           and c.hash_ok(cipher['sha256']), 'recovery_receipt')


def cleanup(parent, sources, receipt, recovery_sha, state):
    validate_recovery(receipt, sources.plan)
    # No writes before every source's compressed AND raw bytes have been verified.
    c.verify_bundle(BlockReader(sources.blocks()), sources.plan)
    sources.recheck()
    fd = os.open(JOURNAL, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600, dir_fd=parent)
    try:
        state.update(status='cleanup_started', plan_sha256=c.digest(c.canonical(sources.plan)),
                     recovery_receipt_sha256=recovery_sha, removed_files=[], pending=None)
        def persist():
            # Keep earlier durable records even if a later append is interrupted.
            # A final incomplete line is evidence for review, never success.
            data = c.canonical(state) + b'\n'
            while data:
                n = os.write(fd, data)
                c.need(n > 0, 'journal_write')
                data = data[n:]
            os.fsync(fd)
            os.fsync(parent)
        persist()
        # The wire plan stays manifest-first for bounded streaming verification.
        # Cleanup removes every group's payloads before any metadata, so an
        # interrupted payload removal retains all manifests for manual recovery.
        for manifests in (False, True):
            for group in sources.groups:
                for row in group['files']:
                    if row['name'].endswith('.json') != manifests:
                        continue
                    key = (group['kind'], group['name'], row['name'])
                    path = '/'.join(key)
                    folder, source_fd, expected = sources.files[key]
                    sources.recheck(state['removed_files'])
                    c.need(sources.hash_fd(source_fd, expected) == row['sha256'], 'source_changed')
                    state['pending'] = path
                    persist()
                    sources.recheck(state['removed_files'])
                    os.unlink(row['name'], dir_fd=folder)
                    os.fsync(folder)
                    state['removed_files'].append(path)
                    state['pending'] = None
                    persist()
        state['status'] = 'cleaned'
        persist()
    finally:
        os.close(fd)


def expired(*_):
    raise TimeoutError()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='mode', required=True)
    sub.add_parser('plan')
    for mode in ('stream', 'cleanup'):
        p = sub.add_parser(mode)
        p.add_argument('--plan', required=True)
        p.add_argument('--plan-sha256', required=True)
        if mode == 'cleanup':
            p.add_argument('--recovery-receipt', required=True)
            p.add_argument('--recovery-sha256', required=True)
            p.add_argument('--confirm', required=True, choices=(CONFIRM,))
    args = parser.parse_args(argv)
    state = {'status': 'refused', 'removed_files': [], 'pending': None}
    root = None
    try:
        c.need(os.geteuid() == 0, 'root_required')
        os.umask(0o077)
        signal.signal(signal.SIGALRM, expired)
        signal.alarm(TIMEOUT)
        plan = read_evidence(args.plan, args.plan_sha256, True) if args.mode != 'plan' else None
        receipt = read_evidence(args.recovery_receipt, args.recovery_sha256) if args.mode == 'cleanup' else None
        root = os.open('/', FLAGS)
        with namespace(root, args.mode == 'cleanup') as (parent, validate), Sources(parent, validate) as sources:
            if plan is not None:
                c.need(sources.plan == plan, 'plan_changed')
            if args.mode == 'cleanup':
                cleanup(parent, sources, receipt, args.recovery_sha256, state)
            else:
                c.verify_bundle(BlockReader(sources.blocks()), sources.plan)
                sources.recheck()
                if args.mode == 'plan':
                    sys.stdout.buffer.write(c.canonical(sources.plan))
                else:
                    for block in sources.blocks():
                        sys.stdout.buffer.write(block)
                sys.stdout.buffer.flush()
        if args.mode == 'cleanup':
            print(c.canonical(state).decode('ascii'))
        return 0
    except Exception as error:
        state['status'] = 'hold'
        state['reason'] = str(error) if isinstance(error, c.Refused) else type(error).__name__
        print(c.canonical(state).decode('ascii'), file=sys.stderr)
        return 2
    finally:
        signal.alarm(0)
        if root is not None:
            os.close(root)


if __name__ == '__main__':
    sys.exit(main())
