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

SCRIPT = Path(__file__).resolve().parents[1] / 'retirement_images_verify.py'
SPEC = importlib.util.spec_from_file_location('retirement_images_verify', SCRIPT)
subject = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = subject
SPEC.loader.exec_module(subject)
CANARY = b'PRIVATE_SYNTHETIC_APP_CONTENT_NEVER_PRINT'


from test_retirement_image_verify import archive, fixture, oci_fixture, EOFStream
from dataclasses import replace


class RetirementImagesVerifyTest(unittest.TestCase):
    def setUp(self):
        self.members, self.image = fixture()
        self.profile = subject.load_profiles().lookup('autobid-web')

    @contextlib.contextmanager
    def override(self, **values):
        previous = self.profile
        self.profile = replace(self.profile, **values)
        try:
            yield
        finally:
            self.profile = previous

    def check(self, payload=None, members=None, expected=None, error=None, drain=True):
        payload = archive(self.members if members is None else members) if payload is None else payload
        stream = EOFStream(payload)
        result = subject.verify_stream(stream, replace(self.profile, image_id=expected or self.image))
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
        result = subject.verify_stream(stream, replace(self.profile, image_id=self.image))
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
        with self.override(max_archive_bytes=1024):
            result, stream = self.check(error='archive_size_limit', drain=False)
        self.assertLessEqual(result['archive_bytes'], 1025)
        self.assertFalse(stream.eof_observed)
        payload = archive(self.members)
        with self.override(max_archive_bytes=len(payload) - 1):
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
                    mock.patch.object(subject.sys, 'argv', ['validator', 'autobid-web']), \
                    mock.patch.object(subject.sys, 'stdin', types.SimpleNamespace(buffer=stream)), \
                    mock.patch.object(subject, 'load_profiles', return_value=types.SimpleNamespace(lookup=lambda name: replace(self.profile, verify_timeout_seconds=0.05))), \
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
        result = subject.verify_stream(Broken(), self.profile)
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
        with mock.patch.object(subject.sys, 'argv', ['validator', 'autobid-web']), \
                mock.patch.object(subject.sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(archive(self.members)))), \
                mock.patch.object(subject, 'load_profiles', return_value=types.SimpleNamespace(lookup=lambda name: replace(self.profile, image_id=self.image))), contextlib.redirect_stdout(output):
            code = subject.main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'archive_structure_verified')
        self.assertNotIn(CANARY.decode(), output.getvalue())
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), CANARY.decode()],
                                input=b'', capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['error'], 'profile_refused')
        self.assertEqual(result.stderr, b'')
        self.assertNotIn(CANARY, result.stdout)


class OCIImageVerifyTest(unittest.TestCase):
    override = RetirementImagesVerifyTest.override
    check = RetirementImagesVerifyTest.check
    replace_manifest = RetirementImagesVerifyTest.replace_manifest

    def setUp(self):
        self.members, self.image = oci_fixture()
        self.profile = subject.load_profiles().lookup('autobid-web')

    def test_oci_manifest_digest_binds_config_and_ordered_layers(self):
        result, _ = self.check()
        self.assertNotEqual(result['config_digest'], self.image.split(':')[1])
        self.assertEqual(result['layer_count'], 2)

    def test_oci_single_runtime_index_and_nested_index_are_supported(self):
        for depth in (1, 2):
            members, expected = oci_fixture(index_depth=depth, attested=True)
            self.check(members=members, expected=expected)

    def test_oci_gzip_layers_validate_raw_digest_and_uncompressed_diff_ids(self):
        members, expected = oci_fixture(index_depth=1, gzip_layers=True, attested=True)
        self.check(members=members, expected=expected)
        self.check(members=list(reversed(members)), expected=expected)

    def test_oci_gzip_stream_output_can_exceed_one_chunk(self):
        plain = archive([('large.bin', b'x' * (subject.BLOCK * 3), tarfile.REGTYPE)])
        members, expected = oci_fixture(gzip_layers=True, plain_layers=[plain])
        self.check(members=members, expected=expected)

    def test_oci_corrupt_root_config_or_layer_digest_is_rejected(self):
        manifest = json.loads(next(body for name, body, _ in self.members if name == 'manifest.json'))[0]
        names = ['blobs/sha256/' + self.image.split(':')[1], manifest['Config'], manifest['Layers'][0]]
        for changed in names:
            members = [(name, body + b' ' if name == changed else body, kind) for name, body, kind in self.members]
            self.check(members=members, error='oci_descriptor_mismatch')

    def test_oci_descriptor_size_must_match_actual_raw_blob(self):
        members, expected = oci_fixture(descriptor_size_delta=1)
        self.check(members=members, expected=expected, error='oci_descriptor_mismatch')

    def test_oci_compatibility_config_or_layer_order_cannot_select_other_content(self):
        original = json.loads(next(body for name, body, _ in self.members if name == 'manifest.json'))
        for field in ('Config', 'Layers'):
            value = json.loads(json.dumps(original))
            if field == 'Config':
                value[0][field] = value[0]['Layers'][0]
            else:
                value[0][field].reverse()
            self.check(members=self.replace_manifest(value), error='oci_compatibility_mismatch')

    def test_oci_config_diff_id_is_checked_even_with_valid_manifest_descriptors(self):
        for compressed_layers in (False, True):
            members, expected = oci_fixture(gzip_layers=compressed_layers, bad_diff_id=True)
            self.check(members=members, expected=expected, error='layer_digest_mismatch')

    def test_oci_missing_referenced_blob_and_wrong_index_anchor_fail(self):
        manifest = json.loads(next(body for name, body, _ in self.members if name == 'manifest.json'))[0]
        members = [record for record in self.members if record[0] != manifest['Config']]
        self.check(members=members, error='oci_blob_missing')
        members = [(name, body.replace(self.image.encode(), ('sha256:' + 'b' * 64).encode())
                    if name == 'index.json' else body, kind) for name, body, kind in self.members]
        self.check(members=members, error='image_mismatch')

    def test_oci_multiple_runtime_platforms_are_unsupported(self):
        members, expected = oci_fixture(index_depth=1, extra_platform=True)
        self.check(members=members, expected=expected, error='unsupported_multi_platform')

    def test_oci_attestation_cannot_substitute_for_a_runtime_image(self):
        members, expected = oci_fixture(config_changes={'os': 'unknown', 'architecture': 'unknown'})
        self.check(members=members, expected=expected, error='oci_runtime_invalid')
        members, expected = oci_fixture(index_depth=1, config_changes={'architecture': 'arm64'})
        self.check(members=members, expected=expected, error='oci_platform_mismatch')

    def test_oci_index_depth_metadata_count_and_total_are_bounded(self):
        members, expected = oci_fixture(index_depth=2)
        with mock.patch.object(subject, 'MAX_INDEX_DEPTH', 1):
            self.check(members=members, expected=expected, error='oci_index_depth_limit')
        with mock.patch.object(subject, 'MAX_METADATA_CANDIDATES', 1):
            self.check(error='metadata_total_limit')
        with mock.patch.object(subject, 'MAX_METADATA_TOTAL', 32):
            self.check(error='metadata_total_limit')

    def test_oci_json_nesting_is_bounded(self):
        deep = None
        for _ in range(subject.MAX_JSON_DEPTH + 1):
            deep = [deep]
        members, expected = oci_fixture(config_changes={'ignored': deep})
        self.check(members=members, expected=expected, error='config_invalid')

    def test_oci_gzip_crc_truncation_and_concatenation_fail_closed(self):
        cases = [(lambda p: p[:-1], 'invalid_gzip_layer'),
                 (lambda p: p[:-8] + bytes([p[-8] ^ 1]) + p[-7:], 'invalid_gzip_layer'),
                 (lambda p: p + b'junk', 'unsupported_gzip_stream'),
                 (lambda p: p + p, 'unsupported_gzip_stream')]
        for transform, error in cases:
            members, expected = oci_fixture(gzip_layers=True, gzip_transform=transform)
            self.check(members=members, expected=expected, error=error)

    def test_oci_inflated_total_and_unsupported_codec_are_explicit(self):
        members, expected = oci_fixture(gzip_layers=True)
        with self.override(max_expanded_bytes=1024):
            self.check(members=members, expected=expected, error='expanded_size_limit')
        members, expected = oci_fixture(layer_media='application/vnd.oci.image.layer.v1.tar+zstd')
        self.check(members=members, expected=expected, error='unsupported_compression')

    def test_main_disables_core_dumps_before_reading_opaque_input(self):
        events, output = [], io.StringIO()
        def limits(*args):
            self.assertEqual(args, (subject.resource.RLIMIT_CORE, (0, 0)))
            events.append('core_disabled')
        def verify(stream, profile):
            self.assertEqual(events, ['core_disabled'])
            return {'status': 'failed', 'error': 'fixture'}
        with mock.patch.object(subject.sys, 'argv', ['validator', 'autobid-web']), \
                mock.patch.object(subject.resource, 'setrlimit', side_effect=limits), \
                mock.patch.object(subject, 'verify_stream', side_effect=verify), \
                contextlib.redirect_stdout(output):
            self.assertEqual(subject.main(), 2)


class ImageProfileIsolationTest(unittest.TestCase):
    def test_selected_profile_identity_is_reported_and_other_image_refused(self):
        members, image = fixture()
        profiles = subject.load_profiles()
        for name in profiles.ORDER:
            profile = profiles.lookup(name)
            result = subject.verify_stream(io.BytesIO(archive(members)), profile)
            self.assertEqual((result['status'], result['error'], result['image_id']),
                             ('failed', 'image_mismatch', profile.image_id))
        with self.assertRaises(ValueError):
            profiles.lookup('ad-image')

    def test_profiles_have_independent_size_deadline_and_identity_in_one_process(self):
        members, image = fixture()
        original = subject.load_profiles().lookup('autobid-web')
        accepted = replace(original, image_id=image)
        small = replace(accepted, max_archive_bytes=1024)
        for profile, error in ((accepted, None), (small, 'archive_size_limit'), (accepted, None), (original, 'image_mismatch')):
            result = subject.verify_stream(io.BytesIO(archive(members)), profile)
            self.assertEqual(result['error'], error)
        self.assertEqual(original.max_archive_bytes, 536870912)

    def test_content_packed_size_does_not_bound_cumulative_layer_expansion(self):
        layers=[archive([('synthetic-a',b'A'*131072,tarfile.REGTYPE)]),
                archive([('synthetic-b',b'B'*196608,tarfile.REGTYPE)])]
        members,image=oci_fixture(gzip_layers=True,plain_layers=layers)
        packed=sum(len(body) for name,body,_ in members if name.startswith('blobs/'))
        payload=archive(members);expanded=sum(map(len,layers))
        self.assertLess(packed,len(payload));self.assertLess(len(payload),expanded)
        original=subject.load_profiles().lookup('content-studio')
        profile=replace(original,image_id=image,expected_size_bytes=packed,max_expanded_bytes=expanded)
        # Exact expanded budget accepts both real gzip layers, with no archive
        # bytes double-charged; one fewer byte fails but still drains GPG EOF.
        for limit,error in ((expanded-1,'expanded_size_limit'),(expanded,None)):
            stream=EOFStream(payload)
            result=subject.verify_stream(stream,replace(profile,max_expanded_bytes=limit))
            self.assertEqual(result['error'],error)
            self.assertEqual(result['archive_bytes'],len(payload))
            self.assertTrue(stream.eof_observed)
            self.assertLessEqual(stream.largest_request,subject.BLOCK)
        # A larger inflate budget cannot weaken the separate outer archive cap.
        result=subject.verify_stream(EOFStream(payload),replace(profile,max_archive_bytes=len(payload)-1))
        self.assertEqual(result['error'],'archive_size_limit')

    def test_content_real_eight_gib_counter_boundary_stays_fail_closed(self):
        profile=subject.load_profiles().lookup('content-studio')
        self.assertEqual(profile.max_expanded_bytes,8*1024**3)
        plain=archive([('synthetic',b'A'*131072,tarfile.REGTYPE)])
        packed=gzip.compress(plain,mtime=0)
        for excess in (0,1):
            reader=subject.Reader(EOFStream(b''),profile)
            budget={'bytes':profile.max_expanded_bytes-len(plain)+excess}
            inflater=subject.GzipDigest(budget,reader)
            if excess:
                with self.assertRaisesRegex(subject.VerifyError,'expanded_size_limit'):
                    inflater.feed(packed)
            else:
                inflater.feed(packed);entry,error=inflater.finish()
                self.assertIsNone(error);self.assertEqual(entry.size,len(plain))
                self.assertEqual(entry.digest,hashlib.sha256(plain).hexdigest())
                self.assertEqual(budget['bytes'],profile.max_expanded_bytes)
                self.assertLessEqual(len(entry.first),512);self.assertLessEqual(len(entry.last),1024)

    def test_content_larger_budget_still_rejects_identity_descriptor_and_diff_id_faults(self):
        profile=subject.load_profiles().lookup('content-studio')
        cases=[({},'sha256:'+'f'*64,'image_mismatch'),
               ({'descriptor_size_delta':1},None,'oci_descriptor_mismatch'),
               ({'bad_diff_id':True},None,'layer_digest_mismatch')]
        for options,wrong_image,error in cases:
            members,image=oci_fixture(gzip_layers=True,**options)
            result=subject.verify_stream(EOFStream(archive(members)),replace(profile,image_id=wrong_image or image))
            self.assertEqual(result['error'],error)
            self.assertEqual(result['status'],'failed')
            self.assertIsNone(result['config_digest'])

    def test_library_verification_needs_no_files_or_profile_loader(self):
        members, image = fixture()
        profile = replace(subject.load_profiles().lookup('autobid-engine'), image_id=image)
        with mock.patch.object(subject, 'load_profiles', side_effect=AssertionError('unexpected loader')), \
                mock.patch.object(subject.os, 'open', side_effect=AssertionError('unexpected file')):
            result = subject.verify_stream(io.BytesIO(archive(members)), profile)
        self.assertEqual(result['status'], 'archive_structure_verified')

    def test_isolated_cli_loads_pinned_profile_and_binds_public_result(self):
        members, _ = fixture()
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), 'autobid-web'],
                                input=archive(members), capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 2)
        answer = json.loads(result.stdout)
        self.assertEqual(answer['error'], 'image_mismatch')
        self.assertEqual(answer['image_id'], subject.load_profiles().lookup('autobid-web').image_id)
        self.assertEqual(result.stderr, b'')
        self.assertNotIn(CANARY, result.stdout)

    def test_unknown_or_missing_cli_profile_never_reads_stdin(self):
        class RefuseRead:
            def read(self, count):
                raise AssertionError('stdin must stay unread')
        for args in ([], ['ad-image'], ['autobid-web', '--id', CANARY.decode()]):
            output = io.StringIO()
            with mock.patch.object(subject.sys, 'argv', ['verify'] + args), \
                    mock.patch.object(subject.sys, 'stdin', types.SimpleNamespace(buffer=RefuseRead())), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(subject.main(), 2)
            self.assertEqual(json.loads(output.getvalue())['error'], 'profile_refused')
            self.assertNotIn(CANARY.decode(), output.getvalue())


if __name__ == '__main__':
    unittest.main()
