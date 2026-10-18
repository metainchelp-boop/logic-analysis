"""No-clobber publication and inode-bound removal of diagnostic-only files.

All directories must be provisioned and checked by the host entrypoint before
preparing this set. Preparation writes private staging files only; no service or
database call exists here. A complete immutable ownership receipt is durable
before the first public hard link. Interrupted publication/removal is resumable
only through the paired transaction, never by replacing an unexpected path.
"""
import os
from pathlib import Path
import stat
import transition as T
from systemd_boundary import MASK_ROOT
from journal import decode

MAX_RECORD = 32768


def inode(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid]


def stable(info):
    return inode(info) + [info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


class Publication:
    def __init__(self, root, plan, files, *, sources, owner=0, group=0):
        self.plan_hash = T.validate_plan(plan, files, sources=sources)
        self.root = Path(root)
        self.owner, self.group = owner, group
        self.expected = {path: dict(kind='file', sha256=T.sha(body)) for path, body in files.items()}
        self.expected.update({MASK_ROOT + '/' + name: dict(kind='mask', sha256=None)
                              for name in plan['original_units']})
        self.files = dict(files)
        self.stage_roots = {str(Path(path).parent): Path(path).parent /
            ('.naver-diag-' + plan['apply_id']) for path in self.expected}

    def _directory(self, path, *, private=False):
        path = Path(path)
        if not path.is_absolute() or path.resolve() != path: T.fail('OWNED_DIRECTORY')
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner
                or info.st_gid != self.group or stat.S_IMODE(info.st_mode) & 0o022
                or (private and stat.S_IMODE(info.st_mode) != 0o700)):
            T.fail('OWNED_DIRECTORY')
        return inode(info)

    def _sync(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(fd)
        finally: os.close(fd)

    def _write(self, path, body, mode):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
        try:
            os.fchmod(fd, mode)
            if os.fstat(fd).st_gid != self.group: T.fail('OWNED_GROUP')
            view = memoryview(body)
            while view:
                count = os.write(fd, view)
                if count <= 0: T.fail('OWNED_WRITE')
                view = view[count:]
            os.fsync(fd)
        finally: os.close(fd)

    def _regular(self, path, *, mode, maximum, links=(1,)):
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != self.owner
                or before.st_gid != self.group or stat.S_IMODE(before.st_mode) != mode
                or before.st_nlink not in links or not 0 < before.st_size <= maximum):
            T.fail('OWNED_FILE')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if stable(os.fstat(fd)) != stable(before): T.fail('OWNED_CHANGED')
            result = b''
            while len(result) <= maximum:
                part = os.read(fd, min(4096, maximum + 1 - len(result)))
                if not part: break
                result += part
            if (len(result) != before.st_size or len(result) > maximum
                    or stable(os.fstat(fd)) != stable(before) or stable(path.lstat()) != stable(before)):
                T.fail('OWNED_CHANGED')
            return result, before
        finally: os.close(fd)

    def prepare(self):
        """Must finish before the controller may stop an original timer.

        A pre-receipt crash leaves private staging only and cannot be retried in
        place. Cross-filesystem publication is rejected before service mutation.
        """
        root_identity = self._directory(self.root, private=True)
        if list(self.root.iterdir()): T.fail('OWNED_PREPARATION_EXISTS')
        parents, stages, entries = {}, {}, {}
        for target in sorted(self.expected):
            path = Path(target)
            parents[str(path.parent)] = self._directory(path.parent)
            if path.exists() or path.is_symlink(): T.fail('OWNED_TARGET_EXISTS')
            stage_root = self.stage_roots[str(path.parent)]
            stages[str(stage_root)] = self._directory(stage_root, private=True)
            if list(stage_root.iterdir()): T.fail('OWNED_PREPARATION_EXISTS')
            if parents[str(path.parent)][0] != stages[str(stage_root)][0]:
                T.fail('OWNED_CROSS_FILESYSTEM')
        for index, (target, expected) in enumerate(sorted(self.expected.items())):
            stage = self.stage_roots[str(Path(target).parent)] / ('item-%02d' % index)
            if expected['kind'] == 'file':
                self._write(stage, self.files[target], 0o644)
            else:
                os.symlink('/dev/null', stage)
            info = stage.lstat()
            if info.st_uid != self.owner or info.st_gid != self.group or info.st_nlink != 1:
                T.fail('OWNED_STAGE')
            entries[target] = dict(expected, stage=str(stage), inode=inode(info))
        for stage_root in self.stage_roots.values(): self._sync(stage_root)
        self._sync(self.root)
        receipt = dict(version=1, plan_sha256=self.plan_hash, root_inode=root_identity,
                       parents=parents, stages=stages, entries=entries)
        body = T.canonical(receipt)
        if len(body) > MAX_RECORD: T.fail('OWNED_RECORD_LIMIT')
        pending = self.root / 'ownership.pending'
        self._write(pending, body, 0o600)
        os.link(pending, self.root / 'ownership.json', follow_symlinks=False)
        self._sync(self.root)
        pending.unlink(); self._sync(self.root)
        self.validate()
        return T.sha(body)

    def _receipt(self):
        current_root = self._directory(self.root, private=True)
        # A crash immediately after the no-clobber commit may leave the second
        # private ownership link. It is evidence, not an extra operation.
        path = self.root / 'ownership.json'
        raw, info = self._regular(path, mode=0o600, maximum=MAX_RECORD, links=(1, 2))
        pending = self.root / 'ownership.pending'
        if info.st_nlink == 2:
            other, other_info = self._regular(pending, mode=0o600, maximum=MAX_RECORD, links=(2,))
            if other != raw or inode(other_info) != inode(info): T.fail('OWNED_RECORD_LINK')
        elif pending.exists() or pending.is_symlink(): T.fail('OWNED_RECORD_LINK')
        receipt = decode(raw)
        if (type(receipt) is not dict or set(receipt) != {'version', 'plan_sha256', 'root_inode', 'parents', 'stages', 'entries'}
                or type(receipt['version']) is not int or receipt['version'] != 1
                or receipt['plan_sha256'] != self.plan_hash
                or not T.same(receipt['root_inode'], current_root)
                or type(receipt['entries']) is not dict or set(receipt['entries']) != set(self.expected)
                or type(receipt['parents']) is not dict
                or set(receipt['parents']) != {str(Path(p).parent) for p in self.expected}
                or type(receipt['stages']) is not dict
                or set(receipt['stages']) != {str(p) for p in self.stage_roots.values()}):
            T.fail('OWNED_RECORD')
        expected_names = {'ownership.json'}
        if info.st_nlink == 2: expected_names.add('ownership.pending')
        for index, target in enumerate(sorted(self.expected)):
            item = receipt['entries'][target]
            name = str(self.stage_roots[str(Path(target).parent)] / ('item-%02d' % index))
            if (type(item) is not dict or set(item) != {'kind', 'sha256', 'stage', 'inode'}
                    or item['stage'] != name or item['kind'] != self.expected[target]['kind']
                    or item['sha256'] != self.expected[target]['sha256']
                    or type(item['inode']) is not list or len(item['inode']) != 5
                    or any(type(v) is not int for v in item['inode'])):
                T.fail('OWNED_RECORD')
        if {p.name for p in self.root.iterdir()} != expected_names: T.fail('OWNED_INVENTORY')
        for root in self.stage_roots.values():
            if not T.same(self._directory(root, private=True), receipt['stages'][str(root)]):
                T.fail('OWNED_STAGE_DIRECTORY_CHANGED')
            expected = {Path(item['stage']).name for item in receipt['entries'].values()
                        if Path(item['stage']).parent == root}
            if {p.name for p in root.iterdir()} != expected: T.fail('OWNED_INVENTORY')
        return receipt

    def validate(self):
        receipt = self._receipt()
        for parent, expected in receipt['parents'].items():
            if not T.same(self._directory(parent), expected): T.fail('OWNED_PARENT_CHANGED')
        for target, item in receipt['entries'].items():
            stage = Path(item['stage'])
            info = stage.lstat()
            if not T.same(inode(info), item['inode']): T.fail('OWNED_STAGE_CHANGED')
            if item['kind'] == 'file':
                body, info = self._regular(stage, mode=0o644, maximum=262144, links=(1, 2))
                if T.sha(body) != item['sha256']: T.fail('OWNED_STAGE_CHANGED')
            elif (not stat.S_ISLNK(info.st_mode) or os.readlink(stage) != '/dev/null'
                    or info.st_nlink not in (1, 2)):
                T.fail('OWNED_MASK_CHANGED')
            path = Path(target)
            try: public = path.lstat()
            except FileNotFoundError:
                if info.st_nlink != 1: T.fail('OWNED_LINK')
            else:
                if not T.same(inode(public), item['inode']) or public.st_nlink != 2 or info.st_nlink != 2:
                    T.fail('OWNED_TARGET_CHANGED')
        return receipt

    def publish(self, kind):
        if kind not in ('file', 'mask'): T.fail('OWNED_KIND')
        receipt = self.validate()
        # Recovery after ownership link but before its original directory fsync
        # must make that ownership name durable before any public side effect.
        self._sync(self.root)
        for target, item in receipt['entries'].items():
            if item['kind'] != kind: continue
            path = Path(target)
            # Publication is not restartable through apply. Existing links are
            # accepted here solely for an already validated exact inode, which
            # permits bounded filesystem qualification of interrupted effects.
            if not path.exists() and not path.is_symlink():
                os.link(item['stage'], path, follow_symlinks=False)
                self._sync(path.parent)
            self.validate()

    def remove(self, kind):
        if kind not in ('file', 'mask'): T.fail('OWNED_KIND')
        receipt = self.validate()  # Validate the entire set before first unlink.
        for target, item in receipt['entries'].items():
            if item['kind'] != kind: continue
            path = Path(target)
            if path.exists() or path.is_symlink():
                # Recheck immediately before unlink; no hash-only ownership.
                if not T.same(inode(path.lstat()), item['inode']): T.fail('OWNED_TARGET_CHANGED')
                path.unlink(); self._sync(path.parent)
            self.validate()
