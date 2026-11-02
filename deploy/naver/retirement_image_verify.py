#!/usr/bin/env python3
"""Verify a decrypted Docker-save stream; never extract it or execute an image."""
import hashlib
import json
import re
import signal
import sys
import tarfile
import time
from dataclasses import dataclass

EXPECTED_IMAGE = 'sha256:959001525d45612e0c5cc1045291c7b6caefa768c14d37cc1070c26584cb8922'
MAX_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_METADATA_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 600
BLOCK = 64 * 1024


class VerifyError(Exception):
    def __init__(self, code):
        self.code = code


class DeadlineExpired(BaseException):
    pass


class Reader:
    def __init__(self, stream):
        self.stream, self.count, self.eof = stream, 0, False
        self.deadline = time.monotonic() + TIMEOUT_SECONDS

    def read(self, size):
        if time.monotonic() > self.deadline:
            raise VerifyError('deadline_exceeded')
        if self.eof:
            return b''
        if self.count > MAX_BYTES:
            raise VerifyError('archive_size_limit')
        size = min(size, BLOCK, MAX_BYTES + 1 - self.count)
        data = self.stream.read(size)
        if not isinstance(data, bytes) or len(data) > size:
            raise VerifyError('stream_failed')
        self.count += len(data)
        if self.count > MAX_BYTES:
            raise VerifyError('archive_size_limit')
        if not data:
            self.eof = True
        return data

    def exact(self, size):
        data = bytearray()
        while len(data) < size:
            part = self.read(size - len(data))
            if not part:
                raise VerifyError('archive_truncated')
            data.extend(part)
        return bytes(data)

    def drain(self, padding=False):
        while True:
            data = self.read(BLOCK)
            if not data:
                return
            if padding and any(data):
                raise VerifyError('trailing_data')


@dataclass(frozen=True)
class Entry:
    regular: bool
    size: int
    digest: str
    first: bytes
    last: bytes


def compressed(data):
    return data.startswith((b'\x1f\x8b', b'BZh', b'\xfd7zXZ\x00', b'\x28\xb5\x2f\xfd'))


def path_name(value, directory=False):
    if (not isinstance(value, str) or len(value) > 4096 or value.startswith('/')
            or '\\' in value or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise VerifyError('unsafe_member_path')
    while value.startswith('./'):
        value = value[2:]
    if directory:
        value = value.rstrip('/')
        if value in ('', '.'):
            return ''
    if not value or any(part in ('', '.', '..') for part in value.split('/')):
        raise VerifyError('unsafe_member_path')
    return value


def json_object(data, error):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError()
            obj[key] = value
        return obj
    try:
        return json.loads(data, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError):
        raise VerifyError(error) from None


def pax_fields(data):
    fields, offset = {}, 0
    allowed = {'path', 'size', 'mtime', 'atime', 'ctime', 'uid', 'gid', 'uname', 'gname', 'comment'}
    while offset < len(data):
        space = data.find(b' ', offset, offset + 24)
        if space == -1 or not data[offset:space].isdigit():
            raise VerifyError('unsupported_tar_format')
        length = int(data[offset:space])
        end = offset + length
        if length <= space - offset + 2 or end > len(data) or data[end - 1:end] != b'\n':
            raise VerifyError('unsupported_tar_format')
        try:
            key, value = data[space + 1:end - 1].decode('utf-8').split('=', 1)
        except (UnicodeError, ValueError):
            raise VerifyError('unsupported_tar_format') from None
        if key not in allowed or key in fields:
            raise VerifyError('unsupported_tar_format')
        fields[key] = value
        offset = end
    return fields


def read_archive(reader):
    """Read outer tar headers only. File payloads are hashed, never extracted."""
    entries, documents, pending, count = {}, {}, None, 0
    image_hex = EXPECTED_IMAGE.removeprefix('sha256:')
    config_names = {image_hex + '.json', 'blobs/sha256/' + image_hex}
    while True:
        prefix = reader.exact(8)
        if compressed(prefix):
            raise VerifyError('unsupported_compression')
        header = prefix + reader.exact(504)
        if header == bytes(512):
            if pending is not None or reader.exact(512) != bytes(512):
                raise VerifyError('unsupported_tar_format')
            reader.drain(padding=True)
            return entries, documents, config_names
        count += 1
        if count > MAX_ENTRIES:
            raise VerifyError('entry_limit')
        try:
            info = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
        except (tarfile.HeaderError, UnicodeError, ValueError):
            raise VerifyError('unsupported_tar_format') from None
        if info.type not in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.XHDTYPE):
            raise VerifyError('unsupported_tar_format')
        if info.size < 0:
            raise VerifyError('unsupported_tar_format')
        if info.type == tarfile.XHDTYPE:
            path_name(info.name)
            if pending is not None or info.size > MAX_METADATA_BYTES:
                raise VerifyError('metadata_size_limit')
            pending = pax_fields(reader.exact(info.size))
            reader.exact((-info.size) % 512)
            continue
        if pending is not None:
            info.name = pending.get('path', info.name)
            if 'size' in pending:
                if re.fullmatch(r'[0-9]{1,12}', pending['size']) is None:
                    raise VerifyError('unsupported_tar_format')
                info.size = int(pending['size'])
            pending = None
        name = path_name(info.name, info.isdir())
        if name in entries:
            raise VerifyError('duplicate_member')
        if info.size > MAX_BYTES:
            raise VerifyError('archive_size_limit')
        if info.isdir() and info.size:
            raise VerifyError('unsupported_tar_format')
        capture = name == 'manifest.json' or name in config_names
        if capture and info.size > MAX_METADATA_BYTES:
            raise VerifyError('metadata_size_limit')
        digest, first, last, document = hashlib.sha256(), b'', b'', bytearray()
        left = info.size
        while left:
            part = reader.exact(min(BLOCK, left))
            digest.update(part)
            first = (first + part)[:512] if len(first) < 512 else first
            last = (last + part)[-1024:]
            if capture:
                document.extend(part)
            left -= len(part)
        reader.exact((-info.size) % 512)
        entries[name] = Entry(not info.isdir(), info.size, digest.hexdigest(), first, last)
        if capture:
            documents[name] = bytes(document)


def validate_archive(entries, documents, config_names):
    manifest_entry = entries.get('manifest.json')
    if manifest_entry is None or not manifest_entry.regular:
        raise VerifyError('manifest_missing')
    manifest = json_object(documents['manifest.json'], 'manifest_invalid')
    if (not isinstance(manifest, list) or len(manifest) != 1
            or not isinstance(manifest[0], dict)):
        raise VerifyError('manifest_invalid')
    item = manifest[0]
    if not {'Config', 'Layers'} <= set(item) or set(item) - {'Config', 'Layers', 'RepoTags', 'LayerSources'}:
        raise VerifyError('manifest_invalid')
    config_name = path_name(item['Config'])
    if config_name not in config_names:
        raise VerifyError('image_mismatch')
    config_entry = entries.get(config_name)
    if config_entry is None or not config_entry.regular:
        raise VerifyError('config_missing')
    if 'sha256:' + config_entry.digest != EXPECTED_IMAGE:
        raise VerifyError('config_digest_mismatch')
    config = json_object(documents[config_name], 'config_invalid')
    rootfs = config.get('rootfs') if isinstance(config, dict) else None
    if not isinstance(rootfs, dict) or rootfs.get('type') != 'layers':
        raise VerifyError('config_invalid')
    layers, diff_ids = item['Layers'], rootfs.get('diff_ids')
    if (not isinstance(layers, list) or not 1 <= len(layers) <= MAX_ENTRIES
            or not isinstance(diff_ids, list) or len(layers) != len(diff_ids)):
        raise VerifyError('layer_list_invalid')
    for name, diff_id in zip(layers, diff_ids):
        name = path_name(name)
        if not isinstance(diff_id, str) or re.fullmatch(r'sha256:[0-9a-f]{64}', diff_id) is None:
            raise VerifyError('layer_list_invalid')
        entry = entries.get(name)
        if entry is None or not entry.regular:
            raise VerifyError('layer_missing')
        if compressed(entry.first):
            raise VerifyError('unsupported_compression')
        if entry.size < 1024 or entry.size % 512 or entry.last != bytes(1024):
            raise VerifyError('unsupported_layer_format')
        if entry.first != bytes(512):
            try:
                tarfile.TarInfo.frombuf(entry.first, 'utf-8', 'strict')
            except (tarfile.HeaderError, UnicodeError, ValueError):
                raise VerifyError('unsupported_layer_format') from None
        if 'sha256:' + entry.digest != diff_id:
            raise VerifyError('layer_digest_mismatch')
    return len(layers), config_entry.digest


def verify_stream(stream):
    reader, error, layers, config_digest = Reader(stream), None, 0, None
    try:
        entries, documents, config_names = read_archive(reader)
        layers, config_digest = validate_archive(entries, documents, config_names)
    except VerifyError as exc:
        error = exc.code
    except DeadlineExpired:
        error = 'deadline_exceeded'
    except Exception:
        error = 'verification_failed'
    # On ordinary structural errors still consume EOF so the parent can check GPG MDC.
    # Size/deadline failures stop consumption; they can never produce success.
    if error not in ('archive_size_limit', 'deadline_exceeded'):
        try:
            reader.drain()
        except VerifyError as exc:
            error = exc.code
        except DeadlineExpired:
            error = 'deadline_exceeded'
        except Exception:
            error = 'stream_failed'
    return {'status': 'archive_structure_verified' if error is None else 'failed',
            'error': error, 'image_id': EXPECTED_IMAGE,
            'layer_count': layers if error is None else 0, 'archive_bytes': reader.count,
            'config_digest': config_digest if error is None else None}


def expired(signum, frame):
    raise DeadlineExpired()


def main():
    if len(sys.argv) != 1:
        answer = {'status': 'failed', 'error': 'arguments_refused', 'image_id': EXPECTED_IMAGE,
                  'layer_count': 0, 'archive_bytes': 0, 'config_digest': None}
    else:
        previous = signal.signal(signal.SIGALRM, expired)
        try:
            signal.setitimer(signal.ITIMER_REAL, TIMEOUT_SECONDS)
            answer = verify_stream(sys.stdin.buffer)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    try:
        sys.stdout.write(json.dumps(answer, sort_keys=True, separators=(',', ':')) + '\n')
        sys.stdout.flush()
    except Exception:
        return 2
    return 0 if answer['status'] == 'archive_structure_verified' else 2


if __name__ == '__main__':
    sys.exit(main())
