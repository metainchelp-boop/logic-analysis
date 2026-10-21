"""Fixed diagnostic directories and an immutable, private preparation receipt.

No service, database, original installation or original output is changed.
Preparation is not restartable: a claimed apply-ID directory always rejects a
second prepare. load() restores a completed context for paired recovery only.
The caller still owns current_guard semantics and Publication.prepare/validate.
"""
import os
from pathlib import Path
import pwd
import stat
import types
import transition as T
import journal as J
from publication import inode, stable
from systemd_boundary import MASK_ROOT

CONTROL = Path('/var/lib/metainc/naver-market-diagnostic-control')
ROOT_UID, ROOT_GID = 0, 0
TRUST_ANCHOR = Path('/')
MAX_RECORD, MAX_GUARD = 32768, 4096


def _sync(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def _directory(path, uid, gid, mode=None):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path: T.fail('PROVISION_PATH')
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) & 0o022
            or (mode is not None and stat.S_IMODE(info.st_mode) != mode)):
        T.fail('PROVISION_DIRECTORY')
    return inode(info)


def _ancestors(path):
    path = Path(path)
    if TRUST_ANCHOR != path and TRUST_ANCHOR not in path.parents:
        T.fail('PROVISION_PATH')
    for parent in (path, *path.parents):
        _directory(parent, ROOT_UID, ROOT_GID)
        if parent == TRUST_ANCHOR: break


def _new_directory(path, uid, gid, mode):
    path.mkdir(mode=0o700)  # Exclusive claim; never chmod/chown an existing path.
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if inode(os.fstat(fd)) != inode(before): T.fail('PROVISION_CHANGED')
        if (before.st_uid, before.st_gid) != (uid, gid): os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
        os.fsync(fd)
        identity = inode(os.fstat(fd))
        if identity != _directory(path, uid, gid, mode): T.fail('PROVISION_CHANGED')
    finally: os.close(fd)
    _sync(path.parent)
    return identity


def _shared(path, mode):
    _ancestors(path.parent)
    try: path.lstat()
    except FileNotFoundError:
        try: _new_directory(path, ROOT_UID, ROOT_GID, mode)
        except FileExistsError: pass  # A peer may create only this fixed shared directory.
    return _directory(path, ROOT_UID, ROOT_GID, mode)


def _runtime_owner(runtime_uid, reader_gid):
    if (type(runtime_uid) is not int or not 0 < runtime_uid < 2**32
            or type(reader_gid) is not int or reader_gid != 10001
            or pwd.getpwnam(T.PROFILE['exporter_user']).pw_uid != runtime_uid):
        T.fail('PROVISION_RUNTIME')
    return runtime_uid, reader_gid


def _guard(value):
    if type(value) is not dict: T.fail('PROVISION_GUARD')
    try:
        raw = T.canonical(value)
        if len(raw) > MAX_GUARD: T.fail('PROVISION_GUARD')
        decoded = J.decode(raw)
        if not T.same(value, decoded): T.fail('PROVISION_GUARD')
    except (TypeError, ValueError, RecursionError):
        T.fail('PROVISION_GUARD')
    return decoded


def _layout(plan, files, runtime_uid):
    uid, gid = _runtime_owner(runtime_uid, plan['reader_gid'])
    operation = CONTROL / 'preparations' / plan['apply_id']
    code, output = Path(plan['code_root']), Path(plan['output_root'])
    if code != Path(T.INSTALL) / plan['apply_id'] or output != Path(T.OUTPUT) / plan['apply_id']:
        T.fail('PROVISION_PLAN')
    targets = set(files) | {MASK_ROOT + '/' + name for name in plan['original_units']}
    stages = {Path(target).parent / ('.naver-diag-' + plan['apply_id']) for target in targets}
    shared = {CONTROL: 0o700, CONTROL / 'ledger': 0o700,
              CONTROL / 'preparations': 0o700, Path(T.INSTALL): 0o755,
              Path(T.OUTPUT): 0o755, Path(MASK_ROOT): 0o755}
    private = {operation: (ROOT_UID, ROOT_GID, 0o700),
               operation / 'ownership': (ROOT_UID, ROOT_GID, 0o700),
               code: (ROOT_UID, ROOT_GID, 0o755), output: (uid, gid, 0o750)}
    private.update({path: (ROOT_UID, ROOT_GID, 0o700) for path in stages})
    return operation, shared, private, targets, uid, gid


def _absent(path):
    try: path.lstat()
    except FileNotFoundError: return
    T.fail('PROVISION_EXISTS')


def _write(path, body):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid, info.st_nlink) != (ROOT_UID, ROOT_GID, 1):
            T.fail('PROVISION_RECEIPT')
        view = memoryview(body)
        while view:
            count = os.write(fd, view)
            if count <= 0: T.fail('PROVISION_WRITE')
            view = view[count:]
        os.fsync(fd)
    finally: os.close(fd)


def _read(path):
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != ROOT_UID or before.st_gid != ROOT_GID
            or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink not in (1, 2)
            or not 0 < before.st_size <= MAX_RECORD): T.fail('PROVISION_RECEIPT')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if stable(os.fstat(fd)) != stable(before): T.fail('PROVISION_CHANGED')
        raw = b''
        while len(raw) <= MAX_RECORD:
            part = os.read(fd, min(4096, MAX_RECORD + 1 - len(raw)))
            if not part: break
            raw += part
        if (len(raw) != before.st_size or len(raw) > MAX_RECORD
                or stable(os.fstat(fd)) != stable(before) or stable(path.lstat()) != stable(before)):
            T.fail('PROVISION_CHANGED')
        return raw, before
    finally: os.close(fd)


def prepare(plan, files, *, sources, runtime_uid, guard_proof):
    """Provision once before Publication.prepare and before any timer action."""
    plan_hash = T.validate_plan(plan, files, sources=sources)
    guard = _guard(guard_proof)
    if os.geteuid() != ROOT_UID: T.fail('PROVISION_ROOT')
    operation, shared, private, targets, uid, gid = _layout(plan, files, runtime_uid)
    _ancestors(Path(T.UNIT_ROOT))
    # Validate every existing shared directory and every new/public destination
    # before claiming this operation. Existing shared contents are never edited.
    for path, mode in shared.items():
        if path.exists() or path.is_symlink(): _directory(path, ROOT_UID, ROOT_GID, mode)
    for path in set(private) | {Path(x) for x in targets}: _absent(path)
    for path, mode in shared.items(): _shared(path, mode)
    identities = {str(path): _directory(path, ROOT_UID, ROOT_GID, mode)
                  for path, mode in shared.items()}
    identities[str(Path(T.UNIT_ROOT))] = _directory(Path(T.UNIT_ROOT), ROOT_UID, ROOT_GID)
    # This exclusive directory is the non-replayable preparation claim.
    identities[str(operation)] = _new_directory(operation, *private[operation])
    for path, spec in private.items():
        if path != operation: identities[str(path)] = _new_directory(path, *spec)
    receipt = dict(version=1, plan_sha256=plan_hash, apply_id=plan['apply_id'],
                   rollback_id=plan['rollback_id'], runtime_uid=uid, runtime_gid=gid,
                   guard_proof=guard, directories=identities)
    body = T.canonical(receipt)
    if len(body) > MAX_RECORD: T.fail('PROVISION_RECEIPT_LIMIT')
    pending = operation / 'prepared.pending'
    _write(pending, body)
    os.link(pending, operation / 'prepared.json', follow_symlinks=False)
    _sync(operation)
    pending.unlink(); _sync(operation)
    return load(plan, files, sources=sources, runtime_uid=runtime_uid)


def load(plan, files, *, sources, runtime_uid):
    """Verify and fsync a completed private receipt, without creating any path.

    A returned context does not authorize applying again. Controller/Ledger own
    apply history and paired rollback; current_guard validates restored proof.
    """
    plan_hash = T.validate_plan(plan, files, sources=sources)
    if os.geteuid() != ROOT_UID: T.fail('PROVISION_ROOT')
    operation, shared, private, _, uid, gid = _layout(plan, files, runtime_uid)
    expected = {**{p: (ROOT_UID, ROOT_GID, m) for p, m in shared.items()},
                Path(T.UNIT_ROOT): (ROOT_UID, ROOT_GID, None), **private}
    identities = {}
    for path, spec in expected.items():
        _ancestors(path.parent)
        identities[str(path)] = _directory(path, *spec)
    raw, info = _read(operation / 'prepared.json')
    names = {'prepared.json', 'ownership'}
    pending = operation / 'prepared.pending'
    if info.st_nlink == 2:
        other, peer = _read(pending)
        if raw != other or inode(peer) != inode(info): T.fail('PROVISION_RECEIPT_LINK')
        names.add('prepared.pending')
    elif pending.exists() or pending.is_symlink(): T.fail('PROVISION_RECEIPT_LINK')
    if {p.name for p in operation.iterdir()} != names: T.fail('PROVISION_INVENTORY')
    receipt = J.decode(raw)
    if (type(receipt) is not dict or set(receipt) != {'version', 'plan_sha256', 'apply_id',
            'rollback_id', 'runtime_uid', 'runtime_gid', 'guard_proof', 'directories'}):
        T.fail('PROVISION_RECEIPT')
    guard = _guard(receipt['guard_proof'])
    expected_receipt = dict(version=1, plan_sha256=plan_hash, apply_id=plan['apply_id'],
        rollback_id=plan['rollback_id'], runtime_uid=uid, runtime_gid=gid,
        guard_proof=guard, directories=identities)
    if not T.same(receipt, expected_receipt): T.fail('PROVISION_CHANGED')
    _sync(operation)  # A visible link from interrupted commit becomes durable first.
    return types.SimpleNamespace(prepared_sha256=T.sha(raw), guard_proof=guard,
        ledger_root=CONTROL / 'ledger', ownership_root=operation / 'ownership',
        output_identity=identities[plan['output_root']], operation_root=operation,
        receipt=receipt)
