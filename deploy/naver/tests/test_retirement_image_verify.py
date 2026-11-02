"""Synthetic Docker-save streams only; no Docker, live image, GPG, or network."""
import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import types
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'retirement_image_verify.py'
SPEC = importlib.util.spec_from_file_location('retirement_image_verify', SCRIPT)
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)
CANARY = b'PRIVATE_SYNTHETIC_APP_CONTENT_NEVER_PRINT'


def archive(members, fmt=tarfile.USTAR_FORMAT):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=fmt) as bundle:
        for name, body, kind in members:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(body) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                entry.linkname = 'outside'
            bundle.addfile(entry, io.BytesIO(body) if entry.size else None)
    return output.getvalue()


def fixture(blobs=False, manifest_first=False, layer_payloads=None):
    if layer_payloads is None:
        layer_payloads = [archive([('private.txt', CANARY, tarfile.REGTYPE)]),
                          archive([('app.txt', b'SYNTHETIC_SECOND_LAYER', tarfile.REGTYPE)])]
    digests = [hashlib.sha256(value).hexdigest() for value in layer_payloads]
    config = json.dumps({'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + d for d in digests]},
                         'config': {'Env': ['SECRET=' + CANARY.decode()]}}).encode()
    image = hashlib.sha256(config).hexdigest()
    config_name = 'blobs/sha256/' + image if blobs else image + '.json'
    layer_names = [('blobs/sha256/' + digest) if blobs else (digest + '/layer.tar')
                   for digest in digests]
    manifest = json.dumps([{'Config': config_name, 'RepoTags': None, 'Layers': layer_names}]).encode()
    members = [(name, value, tarfile.REGTYPE) for name, value in zip(layer_names, layer_payloads)]
    members.append((config_name, config, tarfile.REGTYPE))
    record = ('manifest.json', manifest, tarfile.REGTYPE)
    members.insert(0, record) if manifest_first else members.append(record)
    return members, 'sha256:' + image


class EOFStream(io.BytesIO):
    def __init__(self, payload):
        super().__init__(payload)
        self.eof_observed = False
        self.largest_request = 0

    def read(self, size=-1):
        self.largest_request = max(self.largest_request, size)
        result = super().read(size)
        if not result:
            self.eof_observed = True
        return result


class RetirementImageVerifyTest(unittest.TestCase):
    def setUp(self):
        self.members, self.image = fixture()

    def check(self, payload=None, members=None, expected=None, error=None, drain=True):
        payload = archive(self.members if members is None else members) if payload is None else payload
        stream = EOFStream(payload)
        with mock.patch.object(subject, 'EXPECTED_IMAGE', expected or self.image):
            result = subject.verify_stream(stream)
        self.assertEqual(set(result), {'status', 'error', 'image_id', 'layer_count', 'archive_bytes', 'config_digest'})
        public = json.dumps(result)
        for private in (CANARY.decode(), 'private.txt', 'manifest.json', 'Traceback'):
            self.assertNotIn(private, public)
        self.assertLess(stream.largest_request, subject.BLOCK + 1)
        self.assertEqual(result['error'], error, result)
        self.assertEqual(result['status'], 'archive_structure_verified' if error is None else 'failed')
        if drain:
            self.assertTrue(stream.eof_observed)
            self.assertEqual(result['archive_bytes'], len(payload))
        if error is not None:
            self.assertIsNone(result['config_digest'])
            self.assertEqual(result['layer_count'], 0)
        return result, stream

    def replace_manifest(self, value):
        return [(name, json.dumps(value).encode() if name == 'manifest.json' else body, kind)
                for name, body, kind in self.members]

    def test_config_and_layers_before_manifest_are_verified_after_complete_eof(self):
        result, _ = self.check()
        self.assertEqual(result['layer_count'], 2)
        self.assertEqual(result['config_digest'], self.image.split(':')[1])

    def test_manifest_first_is_also_supported(self):
        members, expected = fixture(manifest_first=True)
        self.check(members=members, expected=expected)

    def test_canonical_blob_paths_with_uncompressed_layers_are_supported(self):
        members, expected = fixture(blobs=True)
        self.check(members=members, expected=expected)

    def test_short_reads_are_reassembled_without_unbounded_read(self):
        class ShortReader(EOFStream):
            def read(self, size=-1):
                return super().read(min(size, 13))
        stream = ShortReader(archive(self.members))
        with mock.patch.object(subject, 'EXPECTED_IMAGE', self.image):
            result = subject.verify_stream(stream)
        self.assertEqual(result['status'], 'archive_structure_verified')
        self.assertTrue(stream.eof_observed)

    def test_config_body_hash_must_match_fixed_image(self):
        members = [(name, body.replace(b'SECRET=', b'OTHER=') if name.endswith('.json') and name != 'manifest.json' else body, kind)
                   for name, body, kind in self.members]
        self.check(members=members, error='config_digest_mismatch')

    def test_unexpected_image_fails(self):
        self.check(expected='sha256:' + '1' * 64, error='image_mismatch')

    def test_layer_body_hash_must_match_ordered_config_diff_id(self):
        members = [(name, body.replace(CANARY, b'X' * len(CANARY)) if name.endswith('/layer.tar') else body, kind)
                   for name, body, kind in self.members]
        self.check(members=members, error='layer_digest_mismatch')

    def test_layer_order_must_match_config(self):
        manifest = json.loads(self.members[-1][1])
        manifest[0]['Layers'].reverse()
        self.check(members=self.replace_manifest(manifest), error='layer_digest_mismatch')

    def test_truncated_layer_payload_is_not_accepted(self):
        payload = archive(self.members)
        self.check(payload=payload[:600], error='archive_truncated')

    def test_missing_manifest_config_and_layer_are_distinct_failures(self):
        for index, error in ((-1, 'manifest_missing'), (-2, 'config_missing'), (0, 'layer_missing')):
            members = list(self.members)
            members.pop(index)
            self.check(members=members, error=error)

    def test_manifest_requires_exactly_one_image_and_known_structure(self):
        value = json.loads(self.members[-1][1])
        for malformed in ({}, [], value * 2, [dict(value[0], Unexpected=CANARY.decode())], [{}]):
            self.check(members=self.replace_manifest(malformed), error='manifest_invalid')

    def test_duplicate_json_keys_are_rejected(self):
        body = b'[{"Config":"x","Config":"y","Layers":[]}]'
        members = self.members[:-1] + [('manifest.json', body, tarfile.REGTYPE)]
        self.check(members=members, error='manifest_invalid')

    def test_invalid_layer_list_fails(self):
        value = json.loads(self.members[-1][1])
        for layers in ('not-a-list', [], value[0]['Layers'][:1]):
            value[0]['Layers'] = layers
            self.check(members=self.replace_manifest(value), error='layer_list_invalid')

    def test_member_and_reference_traversal_are_rejected(self):
        for unsafe in ('../private', '/private', 'a/../private', 'a\\private'):
            self.check(members=[(unsafe, CANARY, tarfile.REGTYPE)] + self.members,
                       error='unsafe_member_path')
            value = json.loads(self.members[-1][1])
            value[0]['Layers'][0] = unsafe
            self.check(members=self.replace_manifest(value), error='unsafe_member_path')

    def test_links_and_special_files_are_not_followed_or_extracted(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE):
            members = [(self.members[0][0], b'', kind)] + self.members[1:]
            self.check(members=members, error='unsupported_tar_format')

    def test_directory_cannot_substitute_for_referenced_layer(self):
        members = [(self.members[0][0], b'', tarfile.DIRTYPE)] + self.members[1:]
        self.check(members=members, error='layer_missing')

    def test_duplicate_member_is_ambiguous_and_rejected(self):
        self.check(members=self.members + [self.members[0]], error='duplicate_member')

    def test_outer_compression_is_explicitly_unsupported(self):
        self.check(payload=gzip.compress(archive(self.members)), error='unsupported_compression')

    def test_compressed_layer_is_explicitly_unsupported(self):
        members, expected = fixture(layer_payloads=[gzip.compress(self.members[0][1])])
        self.check(members=members, expected=expected, error='unsupported_compression')

    def test_layer_must_have_uncompressed_tar_framing(self):
        members, expected = fixture(layer_payloads=[CANARY])
        self.check(members=members, expected=expected, error='unsupported_layer_format')

    def test_nonzero_trailing_data_is_rejected_and_fully_drained(self):
        self.check(payload=archive(self.members) + CANARY, error='trailing_data')

    def test_two_end_headers_are_required(self):
        payload = archive(self.members)
        used = sum(512 + ((len(body) + 511) // 512 * 512) for _, body, _ in self.members)
        self.check(payload=payload[:used + 512], error='archive_truncated')

    def test_byte_limit_stops_without_claiming_eof_or_success(self):
        with mock.patch.object(subject, 'MAX_BYTES', 1024):
            result, stream = self.check(error='archive_size_limit', drain=False)
        self.assertLessEqual(result['archive_bytes'], 1025)
        self.assertFalse(stream.eof_observed)
        payload = archive(self.members)
        with mock.patch.object(subject, 'MAX_BYTES', len(payload) - 1):
            result, stream = self.check(payload=payload, error='archive_size_limit', drain=False)
        self.assertEqual(result['archive_bytes'], len(payload))
        self.assertFalse(stream.eof_observed)

    def test_entry_and_metadata_limits_fail_closed_but_finish_input(self):
        with mock.patch.object(subject, 'MAX_ENTRIES', 2):
            self.check(error='entry_limit')
        with mock.patch.object(subject, 'MAX_METADATA_BYTES', 32):
            self.check(error='metadata_size_limit')

    def test_deadline_failure_never_claims_complete_input(self):
        with mock.patch.object(subject.time, 'monotonic', side_effect=[0, 601]):
            result, stream = self.check(error='deadline_exceeded', drain=False)
        self.assertFalse(stream.eof_observed)
        self.assertEqual(result['archive_bytes'], 0)

    def test_cli_deadline_interrupts_a_blocked_stdin_read(self):
        read_fd, write_fd = os.pipe()
        output = io.StringIO()
        try:
            with os.fdopen(read_fd, 'rb') as stream, \
                    mock.patch.object(subject.sys, 'argv', ['validator']), \
                    mock.patch.object(subject.sys, 'stdin', types.SimpleNamespace(buffer=stream)), \
                    mock.patch.object(subject, 'TIMEOUT_SECONDS', 0.05), \
                    contextlib.redirect_stdout(output):
                code = subject.main()
        finally:
            os.close(write_fd)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())['error'], 'deadline_exceeded')

    def test_stdin_read_exception_never_exposes_exception_text(self):
        class Broken:
            def read(self, size):
                raise OSError(CANARY.decode())
        result = subject.verify_stream(Broken())
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn(CANARY.decode(), json.dumps(result))

    def test_pax_path_override_is_checked(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as bundle:
            info = tarfile.TarInfo('safe')
            info.pax_headers = {'path': '../' + CANARY.decode()}
            bundle.addfile(info)
        self.check(payload=output.getvalue(), error='unsafe_member_path')

    def test_bounded_pax_metadata_is_supported(self):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w', format=tarfile.PAX_FORMAT) as bundle:
            for name, body, _ in self.members:
                info = tarfile.TarInfo(name)
                info.size = len(body)
                info.pax_headers = {'mtime': '1.5'}
                bundle.addfile(info, io.BytesIO(body))
        self.check(payload=output.getvalue())

    def test_header_checksum_failure_is_not_accepted(self):
        payload = bytearray(archive(self.members))
        payload[0] ^= 1
        self.check(payload=bytes(payload), error='unsupported_tar_format')

    def test_main_is_zero_argument_and_reports_only_public_json(self):
        output = io.StringIO()
        with mock.patch.object(subject.sys, 'argv', ['validator']), \
                mock.patch.object(subject.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(archive(self.members)))), \
                mock.patch.object(subject, 'EXPECTED_IMAGE', self.image), contextlib.redirect_stdout(output):
            code = subject.main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'archive_structure_verified')
        self.assertNotIn(CANARY.decode(), output.getvalue())
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), CANARY.decode()],
                                input=b'', capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error'], 'arguments_refused')
        self.assertEqual(result.stderr, b'')
        self.assertNotIn(CANARY, result.stdout)


if __name__ == '__main__':
    unittest.main()
