#!/usr/bin/env python3
"""Verify a decrypted Docker-save stream; never extract it or execute an image."""
import hashlib
import json
import os
import stat
import types
import re
import resource
import signal
import sys
import tarfile
import time
import zlib
from dataclasses import dataclass

MAX_ENTRIES = 4096
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_METADATA_TOTAL = 16 * 1024 * 1024
MAX_METADATA_CANDIDATES = 256
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 65536
MAX_INDEX_DEPTH = 8
BLOCK = 64 * 1024
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
BLOB = re.compile(r'blobs/sha256/[0-9a-f]{64}')
MANIFEST_TYPES = {'application/vnd.oci.image.manifest.v1+json',
                  'application/vnd.docker.distribution.manifest.v2+json'}
INDEX_TYPES = {'application/vnd.oci.image.index.v1+json',
               'application/vnd.docker.distribution.manifest.list.v2+json'}
CONFIG_TYPES = {'application/vnd.oci.image.config.v1+json',
                'application/vnd.docker.container.image.v1+json'}
TAR_TYPES = {'application/vnd.oci.image.layer.v1.tar',
             'application/vnd.docker.image.rootfs.diff.tar'}
GZIP_TYPES = {'application/vnd.oci.image.layer.v1.tar+gzip',
              'application/vnd.docker.image.rootfs.diff.tar.gzip'}


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



class VerifyError(Exception):
    def __init__(self, code):
        self.code = code


class DeadlineExpired(BaseException):
    pass


class Reader:
    def __init__(self, stream, profile):
        self.stream, self.count, self.eof = stream, 0, False
        self.profile = profile
        self.deadline = time.monotonic() + profile.verify_timeout_seconds

    def read(self, size):
        if time.monotonic() > self.deadline:
            raise VerifyError('deadline_exceeded')
        if self.eof:
            return b''
        if self.count > self.profile.max_archive_bytes:
            raise VerifyError('archive_size_limit')
        size = min(size, BLOCK, self.profile.max_archive_bytes + 1 - self.count)
        data = self.stream.read(size)
        if not isinstance(data, bytes) or len(data) > size:
            raise VerifyError('stream_failed')
        self.count += len(data)
        if self.count > self.profile.max_archive_bytes:
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
    inflated: object = None
    gzip_error: str = None


class GzipDigest:
    """Single gzip member, bounded output chunks, CRC/trailer and EOF required."""
    def __init__(self, budget, reader):
        self.decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self.budget, self.reader = budget, reader
        self.digest, self.size, self.first, self.last = hashlib.sha256(), 0, b'', b''
        self.error = None

    def feed(self, data):
        if self.error:
            return
        if self.decoder.eof and data:
            self.error = 'unsupported_gzip_stream'
            return
        try:
            while True:
                if time.monotonic() > self.reader.deadline:
                    raise VerifyError('deadline_exceeded')
                output = self.decoder.decompress(data, BLOCK)
                self.size += len(output)
                self.budget['bytes'] += len(output)
                if self.budget['bytes'] > self.reader.profile.max_expanded_bytes:
                    raise VerifyError('expanded_size_limit')
                self.digest.update(output)
                self.first = (self.first + output)[:512] if len(self.first) < 512 else self.first
                self.last = (self.last + output)[-1024:]
                if self.decoder.unused_data:
                    self.error = 'unsupported_gzip_stream'
                    return
                data = self.decoder.unconsumed_tail
                if not data and len(output) < BLOCK:
                    return
        except zlib.error:
            self.error = 'invalid_gzip_layer'

    def finish(self):
        if not self.error and not self.decoder.eof:
            self.error = 'invalid_gzip_layer'
        return Entry(True, self.size, self.digest.hexdigest(), self.first, self.last), self.error


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
        result = json.loads(data, object_pairs_hook=unique,
                            parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
        pending, nodes = [(result, 0)], 0
        while pending:
            value, depth = pending.pop()
            nodes += 1
            if depth > MAX_JSON_DEPTH or nodes > MAX_JSON_NODES:
                raise ValueError()
            if isinstance(value, dict):
                pending.extend((v, depth + 1) for v in value.values())
            elif isinstance(value, list):
                pending.extend((v, depth + 1) for v in value)
        return result
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
    metadata_total, candidates, expanded = 0, 0, {'bytes': 0}
    image_hex = reader.profile.image_id.removeprefix('sha256:')
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
        if info.size > reader.profile.max_archive_bytes:
            raise VerifyError('archive_size_limit')
        if info.isdir() and info.size:
            raise VerifyError('unsupported_tar_format')
        required = name in {'manifest.json', 'index.json', 'oci-layout'} or name in config_names
        if required and info.size > MAX_METADATA_BYTES:
            raise VerifyError('metadata_size_limit')
        capture = not info.isdir() and (required or (BLOB.fullmatch(name) and info.size <= MAX_METADATA_BYTES))
        if capture:
            metadata_total += info.size
            candidates += 1
            if metadata_total > MAX_METADATA_TOTAL or candidates > MAX_METADATA_CANDIDATES:
                raise VerifyError('metadata_total_limit')
        digest, first, last, document = hashlib.sha256(), b'', b'', bytearray()
        inflater = None
        left = info.size
        while left:
            part = reader.exact(min(BLOCK, left))
            if left == info.size and BLOB.fullmatch(name) and part.startswith(b'\x1f\x8b'):
                inflater = GzipDigest(expanded, reader)
            if inflater is not None:
                inflater.feed(part)
            digest.update(part)
            first = (first + part)[:512] if len(first) < 512 else first
            last = (last + part)[-1024:]
            if capture:
                document.extend(part)
            left -= len(part)
        reader.exact((-info.size) % 512)
        inflated, gzip_error = inflater.finish() if inflater is not None else (None, None)
        entries[name] = Entry(not info.isdir(), info.size, digest.hexdigest(), first, last, inflated, gzip_error)
        if capture:
            documents[name] = bytes(document)


def checked_descriptor(value, entries, types, profile):
    if (not isinstance(value, dict) or value.get('mediaType') not in types or
            not isinstance(value.get('digest'), str) or DIGEST.fullmatch(value['digest']) is None or
            type(value.get('size')) is not int or not 0 <= value['size'] <= profile.max_archive_bytes):
        raise VerifyError('oci_descriptor_invalid')
    name = 'blobs/sha256/' + value['digest'].split(':')[1]
    entry = entries.get(name)
    if entry is None or not entry.regular:
        raise VerifyError('oci_blob_missing')
    if entry.size != value['size'] or 'sha256:' + entry.digest != value['digest']:
        raise VerifyError('oci_descriptor_mismatch')
    return name, entry


def oci_document(name, documents):
    if name not in documents:
        raise VerifyError('metadata_size_limit')
    document = json_object(documents[name], 'oci_document_invalid')
    if not isinstance(document, dict) or type(document.get('schemaVersion')) is not int or document['schemaVersion'] != 2:
        raise VerifyError('oci_document_invalid')
    return document


def attestation(value):
    if not isinstance(value, dict):
        return False
    annotations, platform = value.get('annotations'), value.get('platform')
    return (isinstance(annotations, dict) and isinstance(platform, dict) and
            annotations.get('vnd.docker.reference.type') == 'attestation-manifest' and
            platform.get('os') == platform.get('architecture') == 'unknown')


def oci_identity(entries, documents, item, profile):
    """Expected raw target digest -> one runtime manifest -> exact compatibility map."""
    for name in ('oci-layout', 'index.json'):
        if name not in entries or not entries[name].regular or name not in documents:
            raise VerifyError('oci_layout_missing')
    layout = json_object(documents['oci-layout'], 'oci_layout_invalid')
    if not isinstance(layout, dict) or layout.get('imageLayoutVersion') != '1.0.0':
        raise VerifyError('oci_layout_invalid')
    index = oci_document('index.json', documents)
    targets = index.get('manifests')
    if not isinstance(targets, list) or len(targets) != 1:
        raise VerifyError('unsupported_multi_platform')
    descriptor = targets[0]
    if not isinstance(descriptor, dict) or descriptor.get('digest') != profile.image_id:
        raise VerifyError('image_mismatch')
    visited, platform = set(), None
    for depth in range(MAX_INDEX_DEPTH + 1):
        name, _ = checked_descriptor(descriptor, entries, MANIFEST_TYPES | INDEX_TYPES, profile)
        if name in visited:
            raise VerifyError('oci_index_cycle')
        visited.add(name)
        document = oci_document(name, documents)
        if document.get('mediaType', descriptor['mediaType']) != descriptor['mediaType']:
            raise VerifyError('oci_descriptor_invalid')
        if descriptor.get('platform') is not None:
            platform = descriptor['platform']
        if descriptor['mediaType'] in MANIFEST_TYPES:
            break
        if depth == MAX_INDEX_DEPTH:
            raise VerifyError('oci_index_depth_limit')
        children = document.get('manifests')
        if not isinstance(children, list) or not 1 <= len(children) <= MAX_METADATA_CANDIDATES:
            raise VerifyError('oci_document_invalid')
        runtime = [child for child in children if not attestation(child)]
        if len(runtime) != 1:
            raise VerifyError('unsupported_multi_platform')
        descriptor = runtime[0]
    config_name, _ = checked_descriptor(document.get('config'), entries, CONFIG_TYPES, profile)
    if path_name(item['Config']) != config_name:
        raise VerifyError('oci_compatibility_mismatch')
    layers = document.get('layers')
    if (not isinstance(layers, list) or not 1 <= len(layers) <= MAX_ENTRIES or
            not isinstance(item['Layers'], list) or len(item['Layers']) != len(layers)):
        raise VerifyError('layer_list_invalid')
    media_types = []
    for descriptor, compatibility_name in zip(layers, item['Layers']):
        if isinstance(descriptor, dict) and descriptor.get('mediaType') not in TAR_TYPES | GZIP_TYPES:
            raise VerifyError('unsupported_compression')
        layer_name, _ = checked_descriptor(descriptor, entries, TAR_TYPES | GZIP_TYPES, profile)
        if path_name(compatibility_name) != layer_name:
            raise VerifyError('oci_compatibility_mismatch')
        media_types.append(descriptor['mediaType'])
    return config_name, media_types, platform


def validate_archive(entries, documents, config_names, profile):
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
    media_types, platform = None, None
    if config_name not in config_names:
        # No fallback to an arbitrary config: the fixed target blob must exist.
        if 'blobs/sha256/' + profile.image_id.split(':')[1] not in entries:
            raise VerifyError('image_mismatch')
        config_name, media_types, platform = oci_identity(entries, documents, item, profile)
    config_entry = entries.get(config_name)
    if config_entry is None or not config_entry.regular:
        raise VerifyError('config_missing')
    if media_types is None and 'sha256:' + config_entry.digest != profile.image_id:
        raise VerifyError('config_digest_mismatch')
    if config_name not in documents:
        raise VerifyError('metadata_size_limit')
    config = json_object(documents[config_name], 'config_invalid')
    rootfs = config.get('rootfs') if isinstance(config, dict) else None
    if not isinstance(rootfs, dict) or rootfs.get('type') != 'layers':
        raise VerifyError('config_invalid')
    if media_types is not None:
        if any(not isinstance(config.get(k), str) or config[k] in ('', 'unknown') for k in ('os', 'architecture')):
            raise VerifyError('oci_runtime_invalid')
        if platform is not None and (not isinstance(platform, dict) or
                any(platform.get(k) != config[k] for k in ('os', 'architecture'))):
            raise VerifyError('oci_platform_mismatch')
    layers, diff_ids = item['Layers'], rootfs.get('diff_ids')
    if (not isinstance(layers, list) or not 1 <= len(layers) <= MAX_ENTRIES
            or not isinstance(diff_ids, list) or len(layers) != len(diff_ids)):
        raise VerifyError('layer_list_invalid')
    for position, (name, diff_id) in enumerate(zip(layers, diff_ids)):
        name = path_name(name)
        if not isinstance(diff_id, str) or re.fullmatch(r'sha256:[0-9a-f]{64}', diff_id) is None:
            raise VerifyError('layer_list_invalid')
        entry = entries.get(name)
        if entry is None or not entry.regular:
            raise VerifyError('layer_missing')
        if media_types is not None and media_types[position] in GZIP_TYPES:
            if entry.inflated is None:
                raise VerifyError('invalid_gzip_layer')
            if entry.gzip_error:
                raise VerifyError(entry.gzip_error)
            entry = entry.inflated
        elif compressed(entry.first):
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


def verify_stream(stream, profile):
    reader, error, layers, config_digest = Reader(stream, profile), None, 0, None
    try:
        entries, documents, config_names = read_archive(reader)
        layers, config_digest = validate_archive(entries, documents, config_names, profile)
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
            'error': error, 'image_id': profile.image_id,
            'layer_count': layers if error is None else 0, 'archive_bytes': reader.count,
            'config_digest': config_digest if error is None else None}


def expired(signum, frame):
    raise DeadlineExpired()


def main():
    answer = {'status': 'failed', 'error': 'profile_refused', 'image_id': None,
              'layer_count': 0, 'archive_bytes': 0, 'config_digest': None}
    profile = None
    try:
        if len(sys.argv) == 2:
            profile = load_profiles().lookup(sys.argv[1])
    except Exception:
        pass
    if profile is not None:
        previous = signal.signal(signal.SIGALRM, expired)
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            signal.setitimer(signal.ITIMER_REAL, profile.verify_timeout_seconds)
            answer = verify_stream(sys.stdin.buffer, profile)
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
