"""Authenticated payload framing keeps the existing source/secret policy."""
import base64
import gzip
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('payload_release', Path(__file__).parents[1]/'tools/naver_preview_release.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
MAGIC = b'NAVER-PREVIEW-PAYLOAD-GZIP-1\n'


class PayloadCodecTest(unittest.TestCase):
    def payload(self):
        source = b'synthetic-source'
        files = [dict(path=str(M.SECRET_ROOT/name), mode=0o600, uid=owner[0], gid=owner[1], content='synthetic')
                 for name, owner in M.SECRET_OWNERS.items()]
        return source, dict(schema=1, purpose='naver-owner-verification-runtime', source_commit='a'*40,
                            source_tar_gz_b64=base64.b64encode(source).decode(), files=files)

    def test_old_and_compressed_payload_keep_source_and_all_secret_checks(self):
        source, payload = self.payload()
        raw = json.dumps(payload).encode()
        for wire in (raw, MAGIC+gzip.compress(raw, mtime=0)):
            self.assertEqual(M.decode_payload(wire, 'a'*40, M.sha(source)), (source, payload['files']))

    def test_truncated_corrupt_trailing_and_multiple_gzip_streams_are_refused(self):
        source, payload = self.payload()
        compressed = gzip.compress(json.dumps(payload).encode(), mtime=0)
        for body in (compressed[:-1], compressed[:10], b'not-gzip', compressed+b'trailing',
                     compressed+compressed, compressed[:-5]+b'xxxxx'):
            with self.subTest(size=len(body)), self.assertRaisesRegex(ValueError, '^PAYLOAD_COMPRESSION$'):
                M.decode_payload(MAGIC+body, 'a'*40, M.sha(source))

    def test_limits_apply_before_parsing_and_decompression_cannot_expand_unbounded(self):
        for body, reason in ((b'', 'PLAINTEXT_SIZE'), (b'x'*(3*1024*1024+1), 'PLAINTEXT_SIZE'),
                (MAGIC+b'x'*(2*1024*1024-4096-len(MAGIC)), 'PAYLOAD_WIRE_SIZE'),
                (MAGIC+gzip.compress(b'x'*(3*1024*1024+1)), 'PAYLOAD_COMPRESSION')):
            with self.assertRaisesRegex(ValueError, '^'+reason+'$'):
                M.decode_payload(body, 'a'*40, 'b'*64)

    def test_duplicate_fields_unknown_encoding_and_malformed_json_are_refused(self):
        source, payload = self.payload()
        raw = json.dumps(payload).encode()
        duplicate = b'{"schema":1,'+raw[1:]
        for body in (duplicate, MAGIC+gzip.compress(duplicate), b'NAVER-PREVIEW-PAYLOAD-GZIP-2\n'+raw,
                     MAGIC+gzip.compress(b'\xff'), MAGIC+gzip.compress(b'{')):
            with self.assertRaisesRegex(ValueError, '^PAYLOAD_JSON$'):
                M.decode_payload(body, 'a'*40, M.sha(source))

    def test_compression_does_not_bypass_commit_digest_secret_path_or_owner_policy(self):
        source, original = self.payload()
        changes = (
            lambda p: p.update(source_commit='b'*40),
            lambda p: p.update(source_tar_gz_b64=base64.b64encode(b'changed').decode()),
            lambda p: p['files'][0].update(path='/tmp/unapproved.env'),
            lambda p: p['files'][0].update(mode=0o644),
            lambda p: p['files'][0].update(uid=10001),
            lambda p: p['files'][0].update(content='x'*32769),
            lambda p: p.update(unexpected=True),
        )
        for change in changes:
            payload = json.loads(json.dumps(original))
            change(payload)
            with self.assertRaises(ValueError):
                M.decode_payload(MAGIC+gzip.compress(json.dumps(payload).encode()), 'a'*40, M.sha(source))


if __name__ == '__main__':
    unittest.main()
