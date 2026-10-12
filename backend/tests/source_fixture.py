"""Authenticated test-only source4d fixture, independent of checkout and Git.

All names and tar headers are checked before any member contents are read.
Only a new private temporary directory is populated, with canonical file modes.
"""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import types
import zlib

HERE = Path(__file__).resolve().parent
ASSETS = HERE / 'fixtures'
SOURCE = '4d5802360c1ba23aa801b1145ca8483db3edd35f'
CANONICAL_SHA = 'b1ce7e10044552e9d50427ba15f1e201836d88747fd0d16476a917cf72dab5c8'
ARCHIVE_SHA = '1db45b8e54e562bd83c12b4cf53c791426ea45fccd85162bfb0e5f27179873fe'
RAW_SHA = '574ae4183d89b2059104f788ed75524507cf5cacd7c653dc4518ebd54e37c43d'
ARCHIVE_BYTES, RAW_BYTES, FILE_COUNT = 2131064, 5519360, 163
MAX_CANONICAL, MAX_ARCHIVE, MAX_RAW, MAX_FILE = 65536, 3*1024*1024, 6*1024*1024, 3*1024*1024
FROZEN = {
    'reader.py': (56883, '799c04ca239cf11d17776fc3a6e2cd291b642e475415a8c3cbe3cd9b4e954def'),
    'fixtures.py': (16216, 'a842b5fdc76cf93e0980fe4efc10339f0347c7e6101e53cde173d4e031672836'),
    'test_reader.py': (22802, 'afa6daa8efc87b8780152d81dcede5ed49bbc3df9535d9dc0045118c1db5efce'),
    'history-fixed-0528-v1/freeze.receipt.json': (721, '90ac772f8a9ed27deb3b9924542bbd1b92e68222e237f2d36bea5dc4a3463a6a'),
    'history-fixed-0528-v1/reader.py': (55667, 'de6ff5b9a8bad4306293ae62c8498fe11bbec36f751f7cf3a05b0f580a4fb6a9'),
    'history-fixed-0528-v1/fixtures.py': (16215, '61a0e2f91e865b2ba825e3cacc754ff68dd87997cf724c15e13f4f1476185135'),
    'history-fixed-0528-v1/test_reader.py': (21075, 'b015514a1701ba0ac8fc19181ddad7c547fa5d63f4d6f899c6c986e2a5f233cd'),
}


def refuse(condition):
    if not condition:
        raise ValueError('D3_FIXTURE_REFUSED')


def digest(body):
    return hashlib.sha256(body).hexdigest()


def checked_file(path, limit):
    """Bound reads before allocation and never follow a symlink asset."""
    path = Path(path)
    refuse(path.is_absolute() and path.resolve(strict=True) == path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        refuse(stat.S_ISREG(info.st_mode) and 0 <= info.st_size <= limit)
        body = stream.read(limit + 1)
    refuse(len(body) <= limit and len(body) == info.st_size)
    return body


def strict_json(body):
    def pairs(values):
        out = {}
        for key, value in values:
            refuse(key not in out)
            out[key] = value
        return out
    def nonfinite(_):
        raise ValueError('D3_FIXTURE_REFUSED')
    try:
        return json.loads(body, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, RecursionError, TypeError, json.JSONDecodeError):
        raise ValueError('D3_FIXTURE_REFUSED') from None


def allowed_name(name):
    refuse(type(name) is str and 0 < len(name) <= 240 and '\\' not in name and '\x00' not in name)
    p = PurePosixPath(name)
    refuse(not p.is_absolute() and str(p) == name and all(part not in ('', '.', '..') for part in p.parts))
    refuse(not any(part.casefold() in ('.git', 'store 2.py', 'handover.md')
        or part.casefold().startswith('.env') for part in p.parts))
    return p


def validate_bundle(canonical_raw, packed):
    """Authenticate, bound, then header-check the whole archive before bodies."""
    refuse(type(canonical_raw) is bytes and len(canonical_raw) <= MAX_CANONICAL
        and digest(canonical_raw) == CANONICAL_SHA)
    canonical = strict_json(canonical_raw)
    keys = {'source_commit', 'files', 'file_count', 'raw_bytes', 'raw_sha256',
        'gzip_bytes', 'gzip_sha256', 'profile_sha256'}
    refuse(type(canonical) is dict and set(canonical) == keys and canonical['source_commit'] == SOURCE
        and type(canonical['file_count']) is int and canonical['file_count'] == FILE_COUNT
        and type(canonical['files']) is dict and len(canonical['files']) == FILE_COUNT
        and type(canonical['raw_bytes']) is int and canonical['raw_bytes'] == RAW_BYTES <= MAX_RAW
        and type(canonical['gzip_bytes']) is int and canonical['gzip_bytes'] == ARCHIVE_BYTES <= MAX_ARCHIVE
        and canonical['gzip_sha256'] == ARCHIVE_SHA and canonical['raw_sha256'] == RAW_SHA
        and type(canonical['profile_sha256']) is str
        and re.fullmatch('[0-9a-f]{64}', canonical['profile_sha256']) is not None)
    parents = set()
    for name, row in canonical['files'].items():
        p = allowed_name(name)
        refuse(type(row) is dict and set(row) == {'mode', 'bytes', 'sha256'}
            and type(row['mode']) is int and row['mode'] in (0o644, 0o755)
            and type(row['bytes']) is int and 0 <= row['bytes'] <= MAX_FILE
            and type(row['sha256']) is str and re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None)
        parents.update(str(parent) for parent in p.parents if str(parent) != '.')
    refuse(sum(row['bytes'] for row in canonical['files'].values()) <= MAX_RAW)
    refuse(type(packed) is bytes and len(packed) == ARCHIVE_BYTES <= MAX_ARCHIVE and digest(packed) == ARCHIVE_SHA)
    try:
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = inflater.decompress(packed, MAX_RAW + 1)
        refuse(len(raw) == RAW_BYTES and inflater.eof and not inflater.unused_data
            and not inflater.unconsumed_tail and digest(raw) == RAW_SHA)
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
            refuse(archive.pax_headers == {'comment': SOURCE})
            members, seen, files, directories = [], set(), set(), set()
            for member in archive:
                refuse(len(members) < FILE_COUNT + len(parents))
                allowed_name(member.name)
                refuse(member.name not in seen and member.pax_headers == {'comment': SOURCE}
                    and not member.linkname and not member.sparse)
                seen.add(member.name)
                if member.isdir():
                    refuse(member.name in parents and member.mode == 0o775 and member.size == 0)
                    directories.add(member.name)
                else:
                    refuse(member.isfile() and member.name in canonical['files'])
                    row = canonical['files'][member.name]
                    # The authenticated Git archive adds group-write (020).
                    # Temporary files are written with the canonical modes below.
                    refuse(member.mode == (row['mode'] | 0o020) and member.size == row['bytes'])
                    files.add(member.name)
                members.append(member)
            refuse(files == set(canonical['files']) and directories == parents
                and len(members) == FILE_COUNT + len(parents) and not any(raw[archive.offset:]))
            bodies = {}
            for member in members:
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                refuse(stream is not None)
                with stream:
                    body = stream.read(MAX_FILE + 1)
                row = canonical['files'][member.name]
                refuse(len(body) == row['bytes'] and digest(body) == row['sha256'])
                bodies[member.name] = body
    except (tarfile.TarError, zlib.error, OSError, OverflowError):
        raise ValueError('D3_FIXTURE_REFUSED') from None
    return canonical, bodies


def read_bundle():
    canonical = checked_file(ASSETS / 'canonical-source.json', MAX_CANONICAL)
    packed = checked_file(ASSETS / 'source-4d.tar.gz', MAX_ARCHIVE)
    return validate_bundle(canonical, packed)


def extract_source(destination):
    """Populate only a new directory after all authentication succeeds."""
    canonical, bodies = read_bundle()
    destination = Path(destination)
    refuse(destination.is_absolute() and destination.parent.resolve(strict=True) == destination.parent
        and not destination.exists() and not destination.is_symlink())
    destination.mkdir(mode=0o700)
    try:
        for name in sorted(bodies):
            target = destination / name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(bodies[name])
                os.fchmod(stream.fileno(), canonical['files'][name]['mode'])
    except BaseException:
        shutil.rmtree(destination)
        raise
    return destination


def frozen_bytes():
    result = {}
    for name, (size, pin) in FROZEN.items():
        body = checked_file(ASSETS / 'frozen-reader' / name, max(size, 1))
        refuse(len(body) == size and digest(body) == pin)
        result[name] = body
    return result


def frozen_module(name, body, path):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(body, str(path), 'exec'), module.__dict__)
    return module
