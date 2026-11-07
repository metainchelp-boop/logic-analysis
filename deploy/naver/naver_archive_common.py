"""Fixed historical NAVER archives: bounded wire format and byte verification.

The bundle is MAGIC, uint64 big-endian canonical-plan length, plan JSON, then
the listed files in order. No archive paths are ever extracted by this module.
It is deliberately independent of SQLite, Docker and daily-backup state.
"""
import hashlib
import importlib.util
import json
import contextlib
import os
from pathlib import Path
import re
import stat
import struct
import zlib

SESSION = 'naver-archives-20261106-v1'
MAGIC = b'NAVER-ARCHIVE-V1\n'
CHUNK = 1024 * 1024
MAX_PLAN = 256 * 1024
MAX_TOTAL = 11 * 1024 ** 3
MAX_RAW = 16 * 1024 ** 3
SHA = re.compile(r'[0-9a-f]{64}\Z')
INTERRUPTED = 'naver-engine-interrupted-20261106'
BUNDLE = '54fc-and-20261021-regular-snapshot-gzip6-v1'
BUNDLE_KINDS = ('bundle', 'bundle-deployment', 'bundle-snapshot')
BUNDLE_FILES = {
    'bundle': ('archive-manifest.json',),
    'bundle-deployment': ('archive-manifest.json', 'source-manifest.json', 'engine.db.gz'),
    'bundle-snapshot': ('archive-manifest.json', 'snapshot.sqlite.gz'),
}
INTERRUPTED_SOURCE = 'interrupted nightly backup 2026-11-06 00:35 KST (not a daily backup, not in state.json)'
ID_KEYS = {'device', 'inode', 'mode', 'uid', 'gid', 'size', 'links',
           'mtime_ns', 'ctime_ns', 'allocated_bytes'}


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cold = sibling('cold_backup_archive')
COLD = {p.archive: p.scope for p in cold.PROFILES.values()}


class Refused(Exception):
    """Only fixed error identifiers belong in caller output."""


def need(condition, code='invalid_evidence'):
    if not condition:
        raise Refused(code)


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('ascii')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'duplicate_key')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused('invalid_json')))
    except (ValueError, UnicodeError, RecursionError):
        raise Refused('invalid_json') from None


def number(value, maximum=2 ** 63 - 1):
    return type(value) is int and 0 <= value <= maximum


def hash_ok(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def metadata(value):
    need(type(value) is dict and set(value) == ID_KEYS)
    need(all(number(v) for v in value.values()))


def names_for(kind, names):
    """Manifests precede payloads, so gzip checking needs bounded memory only."""
    if kind in BUNDLE_KINDS:
        expected = BUNDLE_FILES[kind]
        need(set(names) == set(expected), 'unexpected_files')
        return list(expected)
    if kind == 'interrupted':
        expected = ['snapshot.sqlite.json', 'snapshot.sqlite.gz', 'packed.zip.broken']
        need(set(names) == set(expected), 'unexpected_files')
        return expected
    need(kind == 'cold', 'unexpected_kind')
    base = {'archive-manifest.json', 'source-manifest.json', 'engine.db.gz'}
    allowed = base | {n + '.gz' for n in cold.FILES}
    need(base.issubset(names) and set(names).issubset(allowed), 'unexpected_files')
    return ['archive-manifest.json', 'source-manifest.json'] + sorted(set(names) - base | {'engine.db.gz'})


def path_for(kind, name, filename):
    """Map only fixed group/member names to the isolated recovery namespace."""
    if kind in BUNDLE_KINDS:
        need(name == BUNDLE and filename in BUNDLE_FILES[kind], 'unexpected_path')
        middle = '' if kind == 'bundle' else kind[len('bundle-'):] + '/'
        return 'bundle/' + name + '/' + middle + filename
    if kind == 'cold':
        allowed = {'archive-manifest.json', 'source-manifest.json'} | {n + '.gz' for n in cold.FILES}
        need(name in COLD and filename in allowed, 'unexpected_path')
    else:
        need(kind == 'interrupted' and name == INTERRUPTED and filename in
             ('snapshot.sqlite.json', 'snapshot.sqlite.gz', 'packed.zip.broken'), 'unexpected_path')
    return kind + '/' + name + '/' + filename


def bundle_helper():
    # Cold/interrupted-only recovery keeps its original dependency boundary.
    return sibling('backup_bundle')


def validate_plan(plan):
    need(type(plan) is dict and set(plan) == {'version', 'session', 'groups', 'total_bytes'})
    need(type(plan['version']) is int and plan['version'] == 1 and plan['session'] == SESSION)
    need(type(plan['groups']) is list and 1 <= len(plan['groups']) <= len(COLD) + 4)
    keys, total = [], 0
    for group in plan['groups']:
        need(type(group) is dict and set(group) == {'kind', 'name', 'identity', 'files'})
        kind, name = group['kind'], group['name']
        need(type(kind) is str and type(name) is str)
        need((kind == 'cold' and name in COLD) or (kind == 'interrupted' and name == INTERRUPTED)
             or (kind in BUNDLE_KINDS and name == BUNDLE))
        metadata(group['identity'])
        files = group['files']
        minimum = len(BUNDLE_FILES[kind]) if kind in BUNDLE_KINDS else 3
        maximum = minimum if kind in BUNDLE_KINDS else 6
        need(type(files) is list and minimum <= len(files) <= maximum)
        names = []
        for row in files:
            need(type(row) is dict and set(row) == {'name', 'size', 'sha256', 'identity'})
            need(type(row['name']) is str and number(row['size'], MAX_TOTAL) and hash_ok(row['sha256']))
            metadata(row['identity'])
            need(row['identity']['size'] == row['size'] and row['identity']['links'] == 1)
            if row['name'].endswith('.json'):
                need(row['size'] <= 65536)
            names.append(row['name'])
            total += row['size']
        need(len(set(names)) == len(names) and names == names_for(kind, names), 'file_order')
        keys.append((kind, name))
    need(keys == sorted(set(keys)), 'group_order')
    bundle_kinds = {kind for kind, _ in keys if kind in BUNDLE_KINDS}
    need(not bundle_kinds or bundle_kinds == set(BUNDLE_KINDS), 'incomplete_bundle_groups')
    need(number(plan['total_bytes'], MAX_TOTAL) and plan['total_bytes'] == total)
    need(len(canonical(plan)) <= MAX_PLAN)
    return plan


def file_rows(plan):
    return [{'path': path_for(g['kind'], g['name'], f['name']),
             'size': f['size'], 'sha256': f['sha256']}
            for g in plan['groups'] for f in g['files']]


def header(plan):
    data = canonical(validate_plan(plan))
    return MAGIC + struct.pack('>Q', len(data)) + data


def exact(stream, size):
    chunks = []
    while size:
        data = stream.read(min(size, CHUNK))
        need(isinstance(data, bytes) and 0 < len(data) <= size, 'truncated_bundle')
        chunks.append(data)
        size -= len(data)
    return b''.join(chunks)


class GzipCheck:
    def __init__(self, raw_size, raw_sha):
        need(number(raw_size, MAX_RAW) and hash_ok(raw_sha), 'invalid_gzip_manifest')
        self.expected, self.sha = raw_size, raw_sha
        self.size, self.digest = 0, hashlib.sha256()
        self.decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)

    def write(self, data):
        try:
            while data:
                out = self.decoder.decompress(data, min(CHUNK, self.expected - self.size + 1))
                self.size += len(out)
                need(self.size <= self.expected, 'gzip_size')
                self.digest.update(out)
                need(not self.decoder.unused_data, 'gzip_trailing_data')
                data = self.decoder.unconsumed_tail
        except zlib.error:
            raise Refused('gzip_invalid') from None

    def finish(self):
        need(self.decoder.eof and not self.decoder.unused_data and not self.decoder.unconsumed_tail,
             'gzip_incomplete')
        need(self.size == self.expected and self.digest.hexdigest() == self.sha, 'gzip_hash')


def verify_bundle(stream, expected_plan):
    validate_plan(expected_plan)
    need(exact(stream, len(MAGIC)) == MAGIC, 'bundle_magic')
    length = struct.unpack('>Q', exact(stream, 8))[0]
    need(0 < length <= MAX_PLAN, 'plan_size')
    need(exact(stream, length) == canonical(expected_plan), 'plan_mismatch')
    helper, root_archive = None, None
    if any(group['kind'] in BUNDLE_KINDS for group in expected_plan['groups']):
        try:
            helper = bundle_helper()
        except Exception:
            raise Refused('bundle_helper') from None
    for group in expected_plan['groups']:
        kind = group['kind']
        manifests, archive = {}, None
        for row in group['files']:
            name, remaining, digestor = row['name'], row['size'], hashlib.sha256()
            check, captured = None, bytearray()
            if name.endswith('.gz'):
                if kind in ('cold', 'bundle-deployment'):
                    need(archive is not None and name[:-3] in archive['files'], 'gzip_member')
                    inner = archive['files'][name[:-3]]
                    need(row['size'] == inner['gzip_size'] and row['sha256'] == inner['gzip_sha256'])
                    check = GzipCheck(inner['size'], inner['sha256'])
                elif kind == 'bundle-snapshot':
                    need(archive is not None and name == 'snapshot.sqlite.gz', 'gzip_member')
                    inner = archive['file']
                    need(row['size'] == inner['gzip_size'] and row['sha256'] == inner['gzip_sha256'])
                    check = GzipCheck(inner['size'], inner['sha256'])
                else:
                    inner = manifests['snapshot.sqlite.json']
                    need(row['size'] == inner['gzip_bytes'])
                    check = GzipCheck(inner['bytes'], inner['sha256'])
            while remaining:
                data = exact(stream, min(CHUNK, remaining))
                remaining -= len(data)
                digestor.update(data)
                if name.endswith('.json'):
                    captured.extend(data)
                if check:
                    check.write(data)
            need(digestor.hexdigest() == row['sha256'], 'file_hash')
            if check:
                check.finish()
            if name.endswith('.json'):
                value = strict_json(captured)
                manifests[name] = value
                if name == 'archive-manifest.json':
                    if kind in BUNDLE_KINDS:
                        try:
                            if kind == 'bundle':
                                need(type(value) is dict and 'plan' in value, 'bundle_manifest')
                                need(helper.inspect_manifest(value, 'bundle', name, value['plan']),
                                     'bundle_manifest')
                                root_archive = value
                            else:
                                need(root_archive is not None, 'bundle_manifest')
                                child = kind[len('bundle-'):]
                                need(helper.inspect_manifest(value, child, name, root_archive['plan']),
                                     'bundle_manifest')
                                need(digest(canonical(value)) == root_archive[child + '_archive_sha256'],
                                     'bundle_manifest')
                        except Exception:
                            raise Refused('bundle_manifest') from None
                        archive = value
                        continue
                    try:
                        archive = cold.validate_archive_plan(value, COLD[group['name']])
                    except Exception:
                        raise Refused('cold_manifest') from None
                    need(set(f['name'] for f in group['files']) ==
                         {'archive-manifest.json', 'source-manifest.json'} | {n + '.gz' for n in archive['files']})
                elif name == 'source-manifest.json':
                    need(digest(captured) == archive['source_manifest_sha256'], 'source_manifest_hash')
                    need(value == {n: {k: r[k] for k in ('size', 'sha256')} for n, r in archive['files'].items()},
                         'source_manifest')
                    if kind == 'bundle-deployment':
                        try:
                            need(helper.inspect_manifest(value, 'deployment', name, root_archive['plan']),
                                 'bundle_manifest')
                        except Exception:
                            raise Refused('bundle_manifest') from None
                elif name == 'snapshot.sqlite.json':
                    need(type(value) is dict and set(value) ==
                         {'source', 'sha256', 'bytes', 'gzip_bytes', 'gzip_level'}, 'interrupted_manifest')
                    need(value['source'] == INTERRUPTED_SOURCE and type(value['gzip_level']) is int
                         and value['gzip_level'] == 1 and number(value['gzip_bytes'], MAX_TOTAL))
                    need(number(value['bytes'], MAX_RAW) and hash_ok(value['sha256']))
    need(stream.read(1) == b'', 'bundle_trailing_data')
    return {'files': file_rows(expected_plan)}


def restore_bundle(stream, expected_plan, outputroot):
    """Reconstruct compressed archival files in a NEW private isolated directory.

    Caller must still authenticate the decrypting process and check its exit.
    Failure leaves a recovery candidate for inspection, never deletes it.
    No gzip content is extracted to disk and no database is opened.
    """
    validate_plan(expected_plan)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    with contextlib.ExitStack() as stack:
        root = os.open(outputroot, flags)
        stack.callback(os.close, root)
        info = os.fstat(root)
        need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
             and stat.S_IMODE(info.st_mode) == 0o700 and not os.listdir(root), 'restore_directory')
        directories, files, links = {'': root}, [], []
        for row in file_rows(expected_plan):
            parts = row['path'].split('/')
            filename = parts[-1]
            for index, name in enumerate(parts[:-1]):
                path, parent_path = '/'.join(parts[:index + 1]), '/'.join(parts[:index])
                if path not in directories:
                    parent = directories[parent_path]
                    os.mkdir(name, 0o700, dir_fd=parent)
                    fd = os.open(name, flags, dir_fd=parent)
                    stack.callback(os.close, fd)
                    directories[path] = fd
                    links.append((parent, name, fd, os.fstat(fd).st_ino))
            parent = directories['/'.join(parts[:-1])]
            fd = os.open(filename, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                         0o600, dir_fd=parent)
            stack.callback(os.close, fd)
            files.append((fd, row))
            links.append((parent, filename, fd, os.fstat(fd).st_ino))

        class CopyReader:
            skip, index, written = len(header(expected_plan)), 0, 0

            def read(self, size):
                data = stream.read(size)
                if not isinstance(data, bytes):
                    return data  # verifier rejects it without writing
                pending = memoryview(data)
                cut = min(self.skip, len(pending))
                self.skip -= cut
                pending = pending[cut:]
                while pending:
                    while self.index < len(files) and self.written == files[self.index][1]['size']:
                        self.index += 1
                        self.written = 0
                    need(self.index < len(files), 'bundle_trailing_data')
                    fd, row = files[self.index]
                    piece = pending[:row['size'] - self.written]
                    free = os.fstatvfs(fd)
                    need(free.f_bavail * free.f_frsize >= len(piece) + 512 * 1024 ** 2,
                         'restore_space')
                    n = os.write(fd, piece)
                    need(n > 0, 'restore_write')
                    self.written += n
                    pending = pending[n:]
                return data

        result = verify_bundle(CopyReader(), expected_plan)
        for fd, row in files:
            os.fsync(fd)
            before = cold.identity(os.fstat(fd))
            need(before['size'] == row['size'] and before['links'] == 1
                 and before['mode'] == 0o600 and before['uid'] == os.geteuid(), 'restore_size')
            os.lseek(fd, 0, os.SEEK_SET)
            h, size = hashlib.sha256(), 0
            while True:
                data = os.read(fd, min(CHUNK, row['size'] - size + 1))
                if not data:
                    break
                size += len(data)
                need(size <= row['size'], 'restore_size')
                h.update(data)
            need(size == row['size'] and h.hexdigest() == row['sha256']
                 and cold.identity(os.fstat(fd)) == before, 'restore_hash')
        for parent, name, fd, inode in links:
            current, opened = os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(fd)
            need(current.st_ino == opened.st_ino == inode and current.st_dev == opened.st_dev
                 and not stat.S_ISLNK(current.st_mode), 'restore_changed')
            os.fsync(fd)
        for fd in reversed(list(directories.values())):
            os.fsync(fd)
        return result
