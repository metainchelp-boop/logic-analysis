"""Synthetic opaque bytes only; no secret keys, app imports, extraction, or network."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import types
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / 'retirement_key_capsule_verify.py'
SPEC = importlib.util.spec_from_file_location('key_capsule_verify', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = b'PRIVATE_SYNTHETIC_VALUE_NOT_A_REAL_KEY'
NAMES = ('ad-dashboard/secret.key', 'autobid/.env')


def member(name, body=CANARY, **metadata):
    info = tarfile.TarInfo(name)
    info.size, info.mode = len(body), 0o600
    for key, value in metadata.items():
        setattr(info, key, value)
    return info.tobuf(format=tarfile.USTAR_FORMAT) + body + b'\0' * (-len(body) % 512)


def archive(parts=None, padded=True):
    parts = [member(name) for name in NAMES] if parts is None else parts
    data = b''.join(parts) + b'\0' * 1024
    return data + b'\0' * (-len(data) % 10240) if padded else data


class CapsuleVerifyTests(unittest.TestCase):
    def verify(self, data, error=None):
        stream = io.BytesIO(data)
        answer = subject.verify_stream(stream)
        self.assertEqual(set(answer), {'status', 'error', 'member_count', 'source_bytes', 'archive_bytes'})
        self.assertEqual(answer['error'], error)
        self.assertEqual(answer['status'], 'failed' if error else 'capsule_structure_verified')
        public = json.dumps(answer)
        for secret in (CANARY.decode(), *NAMES, 'sha256', 'Traceback'):
            self.assertNotIn(secret, public)
        if error:
            self.assertEqual((answer['member_count'], answer['source_bytes']), (0, 0))
        if error != 'archive_size_limit':
            self.assertEqual(stream.tell(), len(data), 'ordinary failures must drain to EOF')
        return answer

    def test_exact_two_opaque_members_pass_without_key_validation(self):
        data = archive([member(NAMES[0], b'\0\xffnot-fernet\n'),
                        member(NAMES[1], CANARY + b'\nNOT_ENV_SYNTAX\xff')])
        answer = self.verify(data)
        self.assertEqual(answer['member_count'], 2)
        self.assertEqual(answer['archive_bytes'], len(data))
        self.assertEqual(answer['source_bytes'], 13 + len(CANARY) + 16)

    def test_reverse_member_order_is_valid(self):
        self.verify(archive([member(name) for name in reversed(NAMES)]))

    def test_exact_combined_source_limit_is_accepted(self):
        answer = self.verify(archive([member(NAMES[0], b'a' * 65535), member(NAMES[1], b'b')]))
        self.assertEqual(answer['source_bytes'], 65536)

    def test_source_limit_empty_and_oversized_members_are_rejected(self):
        for first, second in ((b'', b'b'), (b'a' * 65536, b'b'), (b'a' * 65537, b'b')):
            self.verify(archive([member(NAMES[0], first), member(NAMES[1], second)]), 'source_size_limit')

    def test_exact_archive_limit_with_zero_padding_is_accepted(self):
        data = archive()
        self.verify(data + b'\0' * (subject.MAX_ARCHIVE - len(data)))

    def test_archive_limit_stops_after_one_overflow_probe(self):
        data = archive() + b'\0' * subject.MAX_ARCHIVE
        answer = self.verify(data, 'archive_size_limit')
        self.assertEqual(answer['archive_bytes'], subject.MAX_ARCHIVE + 1)

    def test_wrong_traversal_absolute_and_alias_names_are_refused(self):
        for name in ('../secret', '/root/secret', './ad-dashboard/secret.key',
                     'ad-dashboard/../secret.key', 'ad-dashboard//secret.key',
                     'ad-dashboard\\secret.key', CANARY.decode()):
            self.verify(archive([member(name), member(NAMES[1])]), 'member_name_refused')

    def test_duplicate_or_third_member_is_refused(self):
        self.verify(archive([member(NAMES[0]), member(NAMES[0])]), 'member_duplicate')
        self.verify(archive([member(NAMES[0]), member(NAMES[1]), member(NAMES[0])]), 'member_duplicate')

    def test_missing_members_are_refused(self):
        for parts in ([], [member(NAMES[0])], [member(NAMES[1])]):
            self.verify(archive(parts), 'members_missing')

    def test_links_directories_special_and_extension_records_are_refused(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.DIRTYPE, tarfile.FIFOTYPE,
                     tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.XHDTYPE, tarfile.XGLTYPE,
                     tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_SPARSE):
            self.verify(archive([member(NAMES[0], type=kind), member(NAMES[1])]), 'member_type_refused')

    def test_checksum_mutation_is_refused_and_drained(self):
        data = bytearray(archive())
        data[0] ^= 1
        self.verify(bytes(data), 'header_invalid')

    def test_noncanonical_metadata_and_hidden_link_are_refused(self):
        for metadata in ({'mode': 0o644}, {'uid': 123}, {'gid': 123}, {'mtime': 1},
                         {'uname': CANARY.decode()}, {'linkname': CANARY.decode()}):
            self.verify(archive([member(NAMES[0], **metadata), member(NAMES[1])]), 'header_invalid')

    def test_gnu_old_tar_and_compression_are_unsupported(self):
        for magic in (b'ustar  \0', b'\0' * 8):
            data = bytearray(archive())
            data[257:265] = magic
            self.verify(bytes(data), 'unsupported_format')
        for prefix in (b'\x1f\x8b', b'BZh', b'\xfd7zXZ\x00', b'\x28\xb5\x2f\xfd'):
            self.verify(prefix + b'\0' * 1024, 'unsupported_format')

    def test_nonzero_member_padding_is_refused(self):
        data = bytearray(archive())
        data[512 + len(CANARY)] = 1
        self.verify(bytes(data), 'padding_invalid')

    def test_nonzero_trailer_and_unaligned_zero_padding_are_refused(self):
        self.verify(archive() + CANARY, 'trailing_data')
        self.verify(archive() + b'\0', 'padding_invalid')

    def test_two_zero_end_blocks_are_required(self):
        body = member(NAMES[0]) + member(NAMES[1])
        self.verify(body + b'\0' * 512, 'archive_truncated')
        self.verify(body + b'\0' * 512 + b'x' * 512, 'end_marker_invalid')

    def test_truncated_header_body_padding_and_end_are_refused(self):
        data = archive(padded=False)
        for length in (0, 511, 512 + len(CANARY) - 1, 1023, 2048, len(data) - 1):
            self.verify(data[:length], 'archive_truncated')

    def test_small_reads_work_without_assuming_pipe_chunk_size(self):
        class Short(io.BytesIO):
            def read(self, size):
                return super().read(min(size, 7))
        data = archive()
        answer = subject.verify_stream(Short(data))
        self.assertEqual((answer['status'], answer['archive_bytes']), ('capsule_structure_verified', len(data)))

    def test_stream_exception_is_sanitized(self):
        class Broken(io.BytesIO):
            def read(self, size):
                raise OSError(CANARY.decode())
        answer = subject.verify_stream(Broken())
        self.assertEqual(answer['error'], 'stream_failed')
        self.assertNotIn(CANARY.decode(), json.dumps(answer))

    def test_no_extraction_file_write_or_tarfile_open(self):
        with mock.patch('builtins.open', side_effect=AssertionError(CANARY)), \
                mock.patch.object(subject.tarfile, 'open', side_effect=AssertionError(CANARY)):
            self.verify(archive())

    def test_production_source_archive_contract_with_synthetic_originals(self):
        spec = importlib.util.spec_from_file_location('capsule_source_contract',
            PATH.with_name('retirement_key_capsule_source.py'))
        source = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(source)
        with tempfile.TemporaryDirectory() as directory:
            for path, _ in source.ORIGINALS:
                target = Path(directory) / path.lstrip('/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(CANARY)
                target.chmod(0o600)
            opaque, total = source.source_archive(source.Files(root=directory, owner=os.getuid()))
            try:
                answer = self.verify(bytes(opaque))
                self.assertEqual(answer['source_bytes'], total)
            finally:
                source.wipe(opaque)

    def test_cli_emits_only_public_counts_and_refuses_arguments(self):
        data = archive()
        for arguments, expected in (([], 0), (['--path', CANARY.decode()], 2)):
            process = subprocess.run([sys.executable, '-I', '-B', str(PATH), *arguments],
                                     input=data, capture_output=True, timeout=5)
            self.assertEqual(process.returncode, expected)
            self.assertEqual(process.stderr, b'')
            self.assertLess(len(process.stdout), 512)
            self.assertNotIn(CANARY, process.stdout)
            answer = json.loads(process.stdout)
            self.assertEqual(answer['status'], 'failed' if expected else 'capsule_structure_verified')

    def test_absolute_deadline_interrupts_blocking_stdin(self):
        read_fd, write_fd = os.pipe()
        began = time.monotonic()
        try:
            with os.fdopen(read_fd, 'rb') as stream, \
                    mock.patch.object(subject.sys, 'argv', ['validator']), \
                    mock.patch.object(subject.sys, 'stdin', types.SimpleNamespace(buffer=stream)), \
                    mock.patch.object(subject, 'TIMEOUT_SECONDS', .02), \
                    mock.patch.object(subject.resource, 'setrlimit'), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(subject.main(), 2)
            self.assertLess(time.monotonic() - began, 1)
            self.assertEqual(json.loads(output.getvalue())['error'], 'deadline_exceeded')
        finally:
            os.close(write_fd)


if __name__ == '__main__':
    unittest.main()
