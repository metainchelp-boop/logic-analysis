#!/usr/bin/env python3
"""Check capsule structure on stdin; never extract, parse, hash, or print key bodies.

The caller must also require GPG's exit code 0. This is not a key-validity or
application-restore test. Normal structural failures still drain to EOF for MDC.
"""
import json
import resource
import signal
import sys
import tarfile
import time

MEMBERS = frozenset(('ad-dashboard/secret.key', 'autobid/.env'))
MAX_ARCHIVE = 80 * 1024
MAX_SOURCE = 64 * 1024
TIMEOUT_SECONDS = 300
BLOCK = 4096
ZERO = b'\0' * 512


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
        if self.count > MAX_ARCHIVE:
            raise VerifyError('archive_size_limit')
        size = min(size, BLOCK, MAX_ARCHIVE + 1 - self.count)
        data = self.stream.read(size)
        if not isinstance(data, bytes) or len(data) > size:
            raise VerifyError('stream_failed')
        self.count += len(data)
        if self.count > MAX_ARCHIVE:
            raise VerifyError('archive_size_limit')
        if not data:
            self.eof = True
        return data

    def exact(self, size):
        # Used only for 512-byte headers and their smaller padding, never a body.
        result = bytearray()
        while len(result) < size:
            data = self.read(size - len(result))
            if not data:
                raise VerifyError('archive_truncated')
            result.extend(data)
        return bytes(result)

    def discard(self, size):
        while size:
            data = self.read(size)
            if not data:
                raise VerifyError('archive_truncated')
            size -= len(data)

    def drain(self, padding=False):
        while True:
            data = self.read(BLOCK)
            if not data:
                return
            if padding and any(data):
                raise VerifyError('trailing_data')


def read_archive(reader):
    seen, source_bytes = set(), 0
    while True:
        block = reader.exact(512)
        if block == ZERO:
            if reader.exact(512) != ZERO:
                raise VerifyError('end_marker_invalid')
            reader.drain(padding=True)
            if reader.count % 512:
                raise VerifyError('padding_invalid')
            if seen != MEMBERS:
                raise VerifyError('members_missing')
            return len(seen), source_bytes
        if block[257:265] != b'ustar\00000':
            raise VerifyError('unsupported_format')
        if block[156:157] not in (tarfile.REGTYPE, tarfile.AREGTYPE):
            raise VerifyError('member_type_refused')
        try:
            member = tarfile.TarInfo.frombuf(block, 'utf-8', 'strict')
        except (tarfile.HeaderError, ValueError, UnicodeError):
            raise VerifyError('header_invalid') from None
        if member.name not in MEMBERS:
            raise VerifyError('member_name_refused')
        if member.name in seen:
            raise VerifyError('member_duplicate')
        # Require the exact USTAR header produced by the source helper. This
        # rejects prefix aliases, hidden link fields, base-256 numbers and junk
        # after NUL fields without exposing any caller-controlled metadata.
        canonical = tarfile.TarInfo(member.name)
        canonical.size, canonical.mode = member.size, 0o600
        canonical.uid = canonical.gid = canonical.mtime = 0
        canonical.uname = canonical.gname = ''
        if not 0 < member.size <= MAX_SOURCE or source_bytes + member.size > MAX_SOURCE:
            raise VerifyError('source_size_limit')
        try:
            expected = canonical.tobuf(format=tarfile.USTAR_FORMAT)
        except (ValueError, OverflowError):
            raise VerifyError('header_invalid') from None
        if block != expected:
            raise VerifyError('header_invalid')
        reader.discard(member.size)
        if any(reader.exact(-member.size % 512)):
            raise VerifyError('padding_invalid')
        seen.add(member.name)
        source_bytes += member.size


def result(error, count=0, source_bytes=0, archive_bytes=0):
    return {'status': 'failed' if error else 'capsule_structure_verified',
            'error': error, 'member_count': count if error is None else 0,
            'source_bytes': source_bytes if error is None else 0,
            'archive_bytes': archive_bytes}


def verify_stream(stream):
    reader, error, count, source_bytes = Reader(stream), None, 0, 0
    try:
        count, source_bytes = read_archive(reader)
    except VerifyError as exc:
        error = exc.code
    except DeadlineExpired:
        error = 'deadline_exceeded'
    except Exception:
        error = 'verification_failed'
    # Limits/deadline stop consumption. They can never be marked successful.
    if error not in ('archive_size_limit', 'deadline_exceeded'):
        try:
            reader.drain()
        except VerifyError as exc:
            error = exc.code
        except DeadlineExpired:
            error = 'deadline_exceeded'
        except Exception:
            error = 'stream_failed'
    return result(error, count, source_bytes, reader.count)


def expired(signum, frame):
    raise DeadlineExpired()


def main():
    if len(sys.argv) != 1:
        answer = result('arguments_refused')
    else:
        previous = signal.signal(signal.SIGALRM, expired)
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            signal.setitimer(signal.ITIMER_REAL, TIMEOUT_SECONDS)
            answer = verify_stream(sys.stdin.buffer)
        except Exception:
            answer = result('verification_failed')
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
    try:
        sys.stdout.write(json.dumps(answer, sort_keys=True, separators=(',', ':')) + '\n')
        sys.stdout.flush()
    except Exception:
        return 2
    return 0 if answer['status'] == 'capsule_structure_verified' else 2


if __name__ == '__main__':
    sys.exit(main())
