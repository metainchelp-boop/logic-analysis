"""Private, append-only paired-operation journal; no systemd or database IO.

Host integration must supply its fixed root, UID 0 and the compiled exact plan.
The configurable directory/UID permit isolated filesystem qualification only.
Events are linked atomically without overwriting. Interrupted temporary files
are retained as evidence, bounded and never interpreted as completed actions.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid
import transition as T

MAX_FILE = 32768
MAX_EVENTS = 256
MAX_ORPHANS = 16


def identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value: T.fail('JOURNAL_JSON')
        value[key] = item
    return value


def decode(raw):
    try:
        value = json.loads(raw, object_pairs_hook=unique,
            parse_constant=lambda _: T.fail('JOURNAL_JSON'))
        if T.canonical(value) != raw: T.fail('JOURNAL_JSON')
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        T.fail('JOURNAL_JSON')


class Ledger:
    def __init__(self, root, plan, *, owner=0):
        self.root = Path(root)
        self.plan = json.loads(T.canonical(plan))
        self.plan_hash = T.sha(T.canonical(plan))
        T.operation(plan['apply_id']); T.operation(plan['rollback_id'])
        self.folder = self.root / plan['apply_id']
        self.owner = owner
        self._fd = None

    def _dir(self, path):
        if not path.is_absolute() or path.resolve() != path:
            T.fail('JOURNAL_PATH')
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner
                or stat.S_IMODE(info.st_mode) != 0o700):
            T.fail('JOURNAL_DIRECTORY')
        return identity(info)

    def _file(self, path, *, links=(1,)):
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != self.owner
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink not in links
                or not 0 <= before.st_size <= MAX_FILE):
            T.fail('JOURNAL_FILE')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if identity(os.fstat(fd)) != identity(before): T.fail('JOURNAL_CHANGED')
            raw = b''
            while len(raw) <= MAX_FILE:
                chunk = os.read(fd, min(4096, MAX_FILE + 1 - len(raw)))
                if not chunk: break
                raw += chunk
            if (len(raw) > MAX_FILE or identity(os.fstat(fd)) != identity(before)
                    or identity(path.lstat()) != identity(before)):
                T.fail('JOURNAL_CHANGED')
            return raw, before
        finally:
            os.close(fd)

    def _sync(self, directory):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)

    @contextmanager
    def lock(self):
        if self._fd is not None: T.fail('JOURNAL_BUSY')
        self._dir(self.root)
        path = self.root / 'transition.lock'
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.fchmod(fd, 0o600); os.fsync(fd); self._sync(self.root)
        except FileExistsError:
            self._file(path)
            fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (identity(info) != identity(path.lstat()) or not stat.S_ISREG(info.st_mode)
                    or info.st_uid != self.owner or stat.S_IMODE(info.st_mode) != 0o600
                    or info.st_nlink != 1 or info.st_size != 0):
                T.fail('JOURNAL_LOCK')
            try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: T.fail('JOURNAL_BUSY')
            self._fd = fd
            self._lock_identity = identity(info)
            self._root_identity = self._dir(self.root)[:2]
            yield
        finally:
            self._fd = None
            os.close(fd)

    def _held(self):
        if self._fd is None: T.fail('JOURNAL_LOCK_REQUIRED')
        if (self._dir(self.root)[:2] != self._root_identity or
                identity(os.fstat(self._fd)) != self._lock_identity or
                identity((self.root / 'transition.lock').lstat()) != self._lock_identity):
            T.fail('JOURNAL_CHANGED')

    def _atomic_new(self, path, raw):
        self._held()
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_FILE:
            T.fail('JOURNAL_SIZE')
        temporary = path.parent / ('.pending-' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0: T.fail('JOURNAL_WRITE')
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        # Atomic no-clobber commit; crash after link leaves an exact second link.
        os.link(temporary, path, follow_symlinks=False)
        self._sync(path.parent)
        temporary.unlink()
        self._sync(path.parent)

    def _inventory(self):
        self._dir(self.folder)
        entries = list(self.folder.iterdir())
        if len(entries) > MAX_EVENTS + MAX_ORPHANS + 1:
            T.fail('JOURNAL_SIZE')
        pending = []
        for path in entries:
            if re.fullmatch(r'\.pending-[0-9a-f]{32}', path.name):
                _, info = self._file(path, links=(1, 2))
                pending.append((path, info))
            elif path.name != 'plan.json' and not re.fullmatch(r'[0-9]{6}\.json', path.name):
                T.fail('JOURNAL_INVENTORY')
        if len(pending) > MAX_ORPHANS: T.fail('JOURNAL_SIZE')
        return entries, pending

    def _committed(self, path, pending):
        raw, info = self._file(path, links=(1, 2))
        peers = [p for p, st in pending if (st.st_dev, st.st_ino) == (info.st_dev, info.st_ino)]
        if (info.st_nlink == 2 and len(peers) != 1) or (info.st_nlink == 1 and peers):
            T.fail('JOURNAL_LINK')
        return decode(raw)

    def _reservation_value(self):
        return dict(plan_sha256=self.plan_hash, apply_id=self.plan['apply_id'],
                    rollback_id=self.plan['rollback_id'])

    def _reservations(self, folder):
        self._dir(folder)
        entries = list(folder.iterdir())
        if len(entries) > MAX_EVENTS + MAX_ORPHANS: T.fail('JOURNAL_SIZE')
        pending, paths = [], []
        for path in entries:
            if re.fullmatch(r'\.pending-[0-9a-f]{32}', path.name):
                _, info = self._file(path, links=(1, 2)); pending.append((path, info))
            elif re.fullmatch(r'[0-9a-f]{32}\.json', path.name): paths.append(path)
            else: T.fail('JOURNAL_INVENTORY')
        if len(pending) > MAX_ORPHANS or len(paths) > MAX_EVENTS: T.fail('JOURNAL_SIZE')
        records, used = [], set()
        for path in paths:
            value = self._committed(path, pending)
            if type(value) is not dict or set(value) != {'plan_sha256', 'apply_id', 'rollback_id'}:
                T.fail('JOURNAL_BINDING')
            T.digest(value['plan_sha256'])
            apply_id, rollback_id = T.operation(value['apply_id']), T.operation(value['rollback_id'])
            if apply_id == rollback_id or path.name != apply_id + '.json' or used & {apply_id, rollback_id}:
                T.fail('JOURNAL_BINDING')
            used.update((apply_id, rollback_id)); records.append(value)
        return records, used

    def _reserve_ids(self):
        folder = self.root / 'identities'
        if not folder.exists() and not folder.is_symlink():
            folder.mkdir(mode=0o700); folder.chmod(0o700); self._sync(self.root)
        records, used = self._reservations(folder)
        if used & {self.plan['apply_id'], self.plan['rollback_id']}:
            T.fail('JOURNAL_OPERATION_RESERVED')
        if len(records) >= MAX_EVENTS: T.fail('JOURNAL_SIZE')
        # Both IDs are committed atomically in one immutable pair record. A
        # crash before/after this link leaves neither/both reserved, never one.
        path = folder / (self.plan['apply_id'] + '.json')
        self._atomic_new(path, T.canonical(self._reservation_value()))

    def _verify_ids(self):
        records, _ = self._reservations(self.root / 'identities')
        if sum(T.same(value, self._reservation_value()) for value in records) != 1:
            T.fail('JOURNAL_BINDING')

    def read(self, plan_hash):
        self._held()
        if plan_hash != self.plan_hash: T.fail('JOURNAL_BINDING')
        try: self.folder.lstat()
        except FileNotFoundError: return []
        entries, pending = self._inventory()
        value = self._committed(self.folder / 'plan.json', pending)
        if not T.same(value, self.plan) or T.sha(T.canonical(value)) != self.plan_hash:
            T.fail('JOURNAL_BINDING')
        event_paths = sorted(p for p in entries if re.fullmatch(r'[0-9]{6}\.json', p.name))
        if not event_paths: T.fail('JOURNAL_INITIAL_INCOMPLETE')
        self._verify_ids()
        events, previous = [], plan_hash
        for index, path in enumerate(event_paths, 1):
            if path.name != '%06d.json' % index: T.fail('JOURNAL_SEQUENCE')
            value = self._committed(path, pending)
            if type(value) is not dict or set(value) != {'sequence', 'previous', 'event', 'sha256'}:
                T.fail('JOURNAL_EVENT')
            payload = {k: value[k] for k in ('sequence', 'previous', 'event')}
            if (type(value['sequence']) is not int or value['sequence'] != index
                    or value['previous'] != previous or T.sha(T.canonical(payload)) != value['sha256']):
                T.fail('JOURNAL_CHAIN')
            events.append(value['event']); previous = value['sha256']
        if events: T.validate_history(events, self.plan)
        self._tail = previous
        return events

    def append(self, plan_hash, event):
        self._held()
        if plan_hash != self.plan_hash: T.fail('JOURNAL_BINDING')
        created = False
        if not self.folder.exists() and not self.folder.is_symlink():
            self._reserve_ids()
            self.folder.mkdir(mode=0o700); os.chmod(self.folder, 0o700); self._sync(self.root)
            self._atomic_new(self.folder / 'plan.json', T.canonical(self.plan))
            created = True
        if created:
            events, self._tail = [], plan_hash
        else:
            events = self.read(plan_hash)
        T.validate_history(events + [event], self.plan)
        if len(events) >= MAX_EVENTS: T.fail('JOURNAL_SIZE')
        payload = dict(sequence=len(events) + 1, previous=self._tail, event=event)
        value = dict(payload, sha256=T.sha(T.canonical(payload)))
        self._atomic_new(self.folder / ('%06d.json' % (len(events) + 1)), T.canonical(value))
