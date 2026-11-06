"""Synthetic subprocesses only: no recovery key, real GPG or production files."""
import base64
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / 'naver_archive_recover.py'
SPEC = importlib.util.spec_from_file_location('archive_recover_test', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = 'SYNTHETIC_PRIVATE_VALUE_NOT_FOR_REPORTS'
PLAINTEXT = b'synthetic framed bundle bytes'
CIPHER = b'synthetic opaque ciphertext'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def good_status():
    return ('[GNUPG:] ENC_TO ' + 'A' * 16 + ' 18 0\n'
        '[GNUPG:] DECRYPTION_KEY ' + 'B' * 40 + ' ' + subject.RECIPIENT + ' u\n'
        '[GNUPG:] DECRYPTION_INFO 2 9 0\n'
        '[GNUPG:] DECRYPTION_OKAY\n'
        '[GNUPG:] GOODMDC\n'
        '[GNUPG:] END_DECRYPTION\n').encode()


class RecoveryFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(os.path.realpath(self.temp.name))
        self.root.chmod(0o700)
        self.home = self.root / 'gnupg'
        self.home.mkdir(mode=0o700)
        self.plan = {'version': 1, 'session': subject.SESSION, 'synthetic_fixture': True}
        self.rows = [{'path': 'interrupted/fixture/snapshot.sqlite.gz',
                      'size': 12, 'sha256': digest(b'fixture-file')}]
        self.common = types.SimpleNamespace(canonical=canonical, digest=digest,
            validate_plan=self.validate_plan, verify_bundle=self.verify_bundle,
            file_rows=lambda plan: self.rows)
        self.args = types.SimpleNamespace(plan=str(self.root / 'plan.json'),
            plan_sha256=digest(canonical(self.plan)), transfer_receipt=str(self.root / 'transfer.json'),
            cipher=str(self.root / 'cipher.gpg'), gnupg_home=str(self.home),
            output=str(self.root / 'recovery.json'))
        self.transfer = {'status': 'sent_unverified', 'session': subject.SESSION,
            'plan_sha256': self.args.plan_sha256, 'bytes': len(CIPHER), 'sha256': digest(CIPHER)}
        self.write(self.args.plan, canonical(self.plan))
        self.write(self.args.transfer_receipt, canonical(self.transfer))
        self.write(self.args.cipher, CIPHER)
        self.binary = self.root / 'fake-gpg'
        self.fake()

    def write(self, path, data):
        Path(path).write_bytes(data)
        Path(path).chmod(0o600)

    def validate_plan(self, plan):
        if plan != self.plan:
            raise ValueError()

    def verify_bundle(self, stream, plan):
        data = bytearray()
        while True:
            part = stream.read(7)
            if not part:
                break
            data.extend(part)
        if bytes(data) != PLAINTEXT:
            raise ValueError(CANARY)
        return {'files': self.rows}

    def fake(self, plaintext=PLAINTEXT, status=None, code=0, before='', after=''):
        status = good_status() if status is None else status
        # All injected snippets below are fixed synthetic test code, never CLI input.
        script = ('#!' + sys.executable + '\n'
            'import base64, json, os, signal, sys, time\n'
            'status_fd = int(sys.argv[sys.argv.index("--status-fd") + 1])\n'
            'received = sys.stdin.buffer.read()\n'
            'assert received == ' + repr(CIPHER) + '\n'
            + before + '\n'
            'data = base64.b64decode(' + repr(base64.b64encode(status)) + ')\n'
            'while data:\n'
            '    count = os.write(status_fd, data[:4096])\n'
            '    data = data[count:]\n'
            'sys.stdout.buffer.write(base64.b64decode(' + repr(base64.b64encode(plaintext)) + '))\n'
            'sys.stdout.buffer.flush()\n'
            + after + '\n'
            'raise SystemExit(' + str(code) + ')\n')
        self.binary.write_text(script)
        self.binary.chmod(0o700)

    def verify(self, **kwargs):
        return subject.verify(self.args, common=self.common, binary=str(self.binary), **kwargs)

    def real_bundle(self):
        self.common = subject.common_module()
        raw = b'synthetic snapshot bytes, never a real database' * 256
        packed = gzip.compress(raw, compresslevel=1, mtime=0)
        metadata = {'source': self.common.INTERRUPTED_SOURCE, 'sha256': digest(raw),
                    'bytes': len(raw), 'gzip_bytes': len(packed), 'gzip_level': 1}
        payloads = {'snapshot.sqlite.json': canonical(metadata), 'snapshot.sqlite.gz': packed,
                    'packed.zip.broken': b'PK\x03\x04synthetic interrupted ZIP'}
        ident = {'device': 1, 'inode': 2, 'mode': 0o100600, 'uid': 0, 'gid': 0,
                 'size': 0, 'links': 1, 'mtime_ns': 1, 'ctime_ns': 1, 'allocated_bytes': 4096}
        rows = [{'name': name, 'size': len(payloads[name]), 'sha256': digest(payloads[name]),
                 'identity': {**ident, 'size': len(payloads[name])}}
                for name in self.common.names_for('interrupted', payloads)]
        self.plan = {'version': 1, 'session': subject.SESSION, 'groups': [{
            'kind': 'interrupted', 'name': self.common.INTERRUPTED,
            'identity': {**ident, 'mode': 0o40700}, 'files': rows}],
            'total_bytes': sum(map(len, payloads.values()))}
        self.args.plan_sha256 = digest(canonical(self.plan))
        self.transfer['plan_sha256'] = self.args.plan_sha256
        self.write(self.args.plan, canonical(self.plan))
        self.write(self.args.transfer_receipt, canonical(self.transfer))
        bundle = self.common.header(self.plan) + b''.join(payloads[row['name']] for row in rows)
        return bundle, payloads

    def refuse(self, code, **kwargs):
        with self.assertRaises(subject.Refused) as caught:
            self.verify(**kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY, str(caught.exception))
        self.assertFalse(Path(self.args.output).exists())

    def test_authenticated_roundtrip_receipt_matches_exact_plan_and_cipher(self):
        before = set(self.root.iterdir())
        receipt = self.verify()
        self.assertEqual(receipt, {'version': 1, 'status': 'recovery_verified',
            'session': subject.SESSION, 'plan_sha256': self.args.plan_sha256,
            'cipher': {'bytes': len(CIPHER), 'sha256': digest(CIPHER)},
            'files': self.rows, 'verification': 'gpg-authenticated-and-inner-gzip-v1'})
        output = Path(self.args.output)
        self.assertEqual(json.loads(output.read_bytes()), receipt)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(set(self.root.iterdir()) - before, {output})
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertNotIn(PLAINTEXT, output.read_bytes())

    def test_gpg_normal_pinentry_and_dedicated_status_fd_without_password_args(self):
        real = subject.subprocess.Popen
        with mock.patch.object(subject.subprocess, 'Popen', wraps=real) as start:
            self.verify()
        args, kwargs = start.call_args
        argv = args[0]
        self.assertEqual(argv[1:3], ['--no-options', '--homedir'])
        self.assertEqual(argv[argv.index('--pinentry-mode') + 1], 'ask')
        self.assertEqual(argv[argv.index('--homedir') + 1], str(self.home))
        self.assertNotIn('--batch', argv)
        self.assertFalse(any('passphrase' in word for word in argv))
        self.assertTrue(kwargs['start_new_session'])
        self.assertFalse(kwargs.get('shell', False))
        self.assertEqual(kwargs['stderr'], subject.subprocess.DEVNULL)
        self.assertEqual(kwargs['pass_fds'], (int(argv[argv.index('--status-fd') + 1]),))

    def test_cipher_tampering_refused_before_gpg(self):
        self.write(self.args.cipher, b'tampered')
        with mock.patch.object(subject.subprocess, 'Popen') as start:
            self.refuse('cipher_mismatch')
        start.assert_not_called()

    def test_wrong_plan_digest_refused_before_gpg(self):
        self.args.plan_sha256 = '0' * 64
        with mock.patch.object(subject.subprocess, 'Popen') as start:
            self.refuse('plan_mismatch')
        start.assert_not_called()

    def test_plan_schema_rejected(self):
        self.write(self.args.plan, b'{}')
        self.refuse('plan_invalid')

    def test_transfer_schema_plan_and_session_are_closed(self):
        variants = [{**self.transfer, 'extra': True}, {**self.transfer, 'session': 'other'},
            {**self.transfer, 'plan_sha256': 'f' * 64}, {**self.transfer, 'bytes': True},
            {**self.transfer, 'status': 'received_unverified'},
            {**self.transfer, 'bytes': subject.MAX_CIPHER + 1}]
        for value in variants:
            with self.subTest(value=value):
                self.write(self.args.transfer_receipt, canonical(value))
                self.refuse('receipt_invalid')

    def test_duplicate_json_keys_and_excessive_nesting_rejected(self):
        for data in (b'{"status":1,"status":2}', b'[' * 30 + b'0' + b']' * 30, b'NaN'):
            with self.subTest(data=data):
                self.write(self.args.transfer_receipt, data)
                self.refuse('input_invalid')

    def test_missing_mdc_and_decryption_okay_rejected_even_on_exit_zero(self):
        for removed in (b'[GNUPG:] GOODMDC\n', b'[GNUPG:] DECRYPTION_OKAY\n'):
            with self.subTest(removed=removed):
                self.fake(status=good_status().replace(removed, b''))
                self.refuse('gpg_unauthenticated')

    def test_bad_status_and_repeated_authenticated_message_rejected(self):
        for extra in (b'[GNUPG:] BADMDC\n', b'[GNUPG:] FAILURE decrypt 1\n',
                      b'[GNUPG:] GOODMDC\n', b'[GNUPG:] DECRYPTION_OKAY\n'):
            with self.subTest(extra=extra):
                self.fake(status=good_status() + extra)
                self.refuse('gpg_unauthenticated')

    def test_primary_key_must_match_pinned_recipient(self):
        self.fake(status=good_status().replace(subject.RECIPIENT.encode(), b'C' * 40))
        self.refuse('recipient_mismatch')

    def test_invalid_status_is_not_echoed(self):
        for value in (CANARY.encode() + b'\n', good_status().rstrip(b'\n'),
                      b'[GNUPG:] \x00SECRET\n', b''):
            with self.subTest(value=value):
                self.fake(status=value)
                self.refuse('gpg_status_invalid')

    def test_nonzero_gpg_exit_rejected_despite_complete_status_and_plaintext(self):
        self.fake(code=2)
        self.refuse('gpg_failed')

    def test_corrupt_truncated_and_trailing_plaintext_never_publish_receipt(self):
        for payload in (PLAINTEXT[:-1], b'wrong', PLAINTEXT + b'extra'):
            with self.subTest(payload=payload):
                self.fake(plaintext=payload)
                self.refuse('bundle_invalid')

    def test_verifier_cannot_skip_trailing_plaintext(self):
        def incomplete(stream, plan):
            stream.read(1)
            return {'files': self.rows}
        self.common.verify_bundle = incomplete
        self.refuse('bundle_invalid')

    def test_verifier_cannot_change_receipt_file_inventory(self):
        original = self.common.verify_bundle
        self.common.verify_bundle = lambda stream, plan: (original(stream, plan) and {'files': []})
        self.refuse('bundle_invalid')

    def test_bounded_status_pipe_is_drained_before_stdout_without_deadlock(self):
        prefix = b'[GNUPG:] KEY_CONSIDERED ' + b'A' * 40 + b' 0\n'
        self.fake(status=prefix * 500 + good_status())
        self.verify(timeout=3)

    def test_oversized_status_refused_without_deadlock(self):
        self.fake(status=b'[GNUPG:] KEY_CONSIDERED A 0\n' * 4000)
        self.refuse('gpg_status_invalid', timeout=3)

    def test_hanging_decrypt_has_deadline_and_process_is_killed(self):
        pidfile = self.root / 'fake.pid'
        self.fake(before='open(' + repr(str(pidfile)) + ', "w").write(str(os.getpid()))\ntime.sleep(30)')
        start = time.monotonic()
        self.refuse('deadline_exceeded', timeout=1.5)
        self.assertLess(time.monotonic() - start, 4)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pidfile.read_text()), 0)

    def test_stdout_eof_while_process_keeps_status_open_has_deadline(self):
        self.fake(after='os.close(1)\ntime.sleep(30)')
        self.refuse('deadline_exceeded', timeout=0.3)

    def test_input_symlink_hardlink_and_group_read_refused(self):
        original = Path(self.args.cipher)
        target = self.root / 'cipher-original'
        original.rename(target)
        original.symlink_to(target)
        self.refuse('input_invalid')
        original.unlink()
        os.link(target, original)
        self.refuse('input_invalid')
        original.unlink()
        target.rename(original)
        original.chmod(0o640)
        self.refuse('input_invalid')

    def test_directory_symlink_and_writable_parent_refused(self):
        alias = self.root / 'home-link'
        alias.symlink_to(self.home, target_is_directory=True)
        self.args.gnupg_home = str(alias)
        self.refuse('unsafe_path')
        self.args.gnupg_home = str(self.home)
        self.root.chmod(0o777)
        try:
            self.refuse('unsafe_path')
        finally:
            self.root.chmod(0o700)

    def test_gnupg_home_and_output_parent_must_be_private(self):
        self.home.chmod(0o755)
        self.refuse('unsafe_path')
        self.home.chmod(0o700)
        self.root.chmod(0o755)
        try:
            self.refuse('unsafe_path')
        finally:
            self.root.chmod(0o700)

    def test_existing_output_never_overwritten_or_decrypt_started(self):
        self.write(self.args.output, b'existing artifact')
        with mock.patch.object(subject.subprocess, 'Popen') as start:
            with self.assertRaises(subject.Refused) as caught:
                self.verify()
        self.assertEqual(caught.exception.code, 'output_exists')
        self.assertEqual(Path(self.args.output).read_bytes(), b'existing artifact')
        start.assert_not_called()

    def test_cipher_mutation_during_decryption_blocks_receipt(self):
        self.fake(after='open(' + repr(self.args.cipher) + ', "wb").write(b"tampered")')
        self.refuse('path_changed')

    def test_cipher_path_replacement_blocks_receipt_even_if_bytes_match(self):
        replacement = self.root / 'replacement'
        self.write(replacement, CIPHER)
        self.fake(after='os.replace(' + repr(str(replacement)) + ', ' + repr(self.args.cipher) + ')')
        self.refuse('path_changed')

    def test_transfer_modified_during_decryption_blocks_receipt(self):
        self.fake(after='open(' + repr(self.args.transfer_receipt) + ', "wb").write(b"{}")')
        self.refuse('path_changed')

    def test_replaced_input_parent_directory_blocks_receipt_before_publication(self):
        folder = self.root / 'inputs'
        folder.mkdir(mode=0o700)
        for field in ('plan', 'transfer_receipt', 'cipher'):
            old = Path(getattr(self.args, field))
            new = folder / old.name
            old.rename(new)
            setattr(self.args, field, str(new))
        moved = self.root / 'inputs-old'
        self.fake(after='os.rename(' + repr(str(folder)) + ', ' + repr(str(moved)) + ')\n'
            'os.mkdir(' + repr(str(folder)) + ', 0o700)')
        self.refuse('path_changed')

    def test_sigterm_routes_through_cleanup_and_restores_original_handler(self):
        previous = signal.getsignal(signal.SIGTERM)
        output = io.StringIO()
        def interrupted(args):
            os.kill(os.getpid(), signal.SIGTERM)
        with mock.patch.object(subject, 'verify', side_effect=interrupted), \
                mock.patch.object(sys, 'stdout', output):
            result = subject.main(['--plan', CANARY, '--plan-sha256', CANARY,
                '--transfer-receipt', CANARY, '--cipher', CANARY,
                '--gnupg-home', CANARY, '--output', CANARY])
        self.assertEqual(result, 2)
        self.assertEqual(json.loads(output.getvalue())['error'], 'interrupted')
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_main_errors_are_fixed_codes_without_paths_or_input_content(self):
        output = io.StringIO()
        with mock.patch.object(subject, 'verify', side_effect=RuntimeError(CANARY)), \
                mock.patch.object(sys, 'stdout', output):
            result = subject.main(['--plan', CANARY, '--plan-sha256', CANARY,
                '--transfer-receipt', CANARY, '--cipher', CANARY,
                '--gnupg-home', CANARY, '--output', CANARY])
        self.assertEqual(result, 2)
        self.assertNotIn(CANARY, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['error'], 'internal_failure')

    def test_parser_errors_do_not_echo_input(self):
        output = io.StringIO()
        with mock.patch.object(sys, 'stdout', output):
            self.assertEqual(subject.main(['--unknown', CANARY]), 2)
        self.assertNotIn(CANARY, output.getvalue())

    def test_binary_lookup_ignores_path_and_checks_fixed_executable(self):
        with mock.patch.object(subject, 'GPG_CANDIDATES', (str(self.binary),)), \
                mock.patch.dict(os.environ, {'PATH': str(self.root / 'hostile')}):
            self.assertEqual(subject.gpg_binary(), str(self.binary))
        self.binary.chmod(0o777)
        with mock.patch.object(subject, 'GPG_CANDIDATES', (str(self.binary),)):
            with self.assertRaises(subject.Refused) as caught:
                subject.gpg_binary()
        self.assertEqual(caught.exception.code, 'gpg_unavailable')

    def test_real_bundle_isolated_restore_is_exact_and_all_files_private(self):
        bundle, payloads = self.real_bundle()
        self.fake(plaintext=bundle)
        self.args.restore_dir = str(self.root / 'restored')
        result = self.verify()
        folder = Path(self.args.restore_dir) / 'interrupted' / self.common.INTERRUPTED
        self.assertEqual({path.name for path in folder.iterdir()}, set(payloads))
        for name, expected in payloads.items():
            self.assertEqual((folder / name).read_bytes(), expected)
            self.assertEqual(stat.S_IMODE((folder / name).stat().st_mode), 0o600)
        self.assertEqual(result['files'], self.common.file_rows(self.plan))
        self.assertEqual(stat.S_IMODE(Path(self.args.restore_dir).stat().st_mode), 0o700)

    def test_restore_directory_not_created_when_first_authentication_fails(self):
        bundle, unused = self.real_bundle()
        self.fake(plaintext=bundle, status=good_status().replace(b'[GNUPG:] GOODMDC\n', b''))
        self.args.restore_dir = str(self.root / 'restored')
        self.refuse('gpg_unauthenticated')
        self.assertFalse(Path(self.args.restore_dir).exists())

    def test_second_pass_failure_retains_isolated_candidate_without_receipt(self):
        bundle, unused = self.real_bundle()
        self.fake(plaintext=bundle)
        self.args.restore_dir = str(self.root / 'restored')
        original = self.common.restore_bundle
        def fails_auth(stream, plan, outputroot):
            result = original(stream, plan, outputroot)
            # Models a second-pass GPG integrity error after data was emitted.
            stream.status.extend(b'[GNUPG:] BADMDC\n')
            return result
        self.common.restore_bundle = fails_auth
        self.refuse('gpg_unauthenticated')
        self.assertTrue(Path(self.args.restore_dir).is_dir())
        self.assertTrue(any(Path(self.args.restore_dir).rglob('snapshot.sqlite.gz')))

    def test_restore_requires_full_capacity_before_creating_directory(self):
        bundle, unused = self.real_bundle()
        self.fake(plaintext=bundle)
        self.args.restore_dir = str(self.root / 'restored')
        capacity = types.SimpleNamespace(f_bavail=0, f_frsize=4096)
        with mock.patch.object(subject.os, 'fstatvfs', return_value=capacity):
            self.refuse('restore_space')
        self.assertFalse(Path(self.args.restore_dir).exists())

    def test_existing_restore_directory_never_reused(self):
        bundle, unused = self.real_bundle()
        self.fake(plaintext=bundle)
        self.args.restore_dir = str(self.root / 'restored')
        Path(self.args.restore_dir).mkdir(mode=0o700)
        sentinel = Path(self.args.restore_dir) / 'existing'
        sentinel.write_bytes(b'keep me')
        self.refuse('output_exists')
        self.assertEqual(sentinel.read_bytes(), b'keep me')

    def test_actual_ephemeral_gpg_authenticates_restores_and_rejects_corruption(self):
        try:
            binary = subject.gpg_binary()
        except subject.Refused:
            self.skipTest('GPG is not installed in the fixed executable locations')
        bundle, payloads = self.real_bundle()
        base = [binary, '--no-options', '--homedir', str(self.home), '--batch']
        gpgconf = str(Path(binary).with_name('gpgconf'))
        if Path(gpgconf).is_file():
            self.addCleanup(lambda: subprocess.run([gpgconf, '--homedir', str(self.home),
                '--kill', 'gpg-agent'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=10, check=False))
        created = subprocess.run(base + ['--pinentry-mode', 'loopback', '--passphrase', '',
            '--quick-generate-key', 'Synthetic Recovery Test <fixture@example.invalid>',
            'rsa2048', 'encrypt', '1d'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=45, check=False)
        self.assertEqual(created.returncode, 0, 'Ephemeral synthetic GPG key creation failed')
        listing = subprocess.run(base + ['--with-colons', '--list-keys'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True)
        recipient = next(line.split(':')[9] for line in listing.stdout.decode().splitlines()
                         if line.startswith('fpr:'))
        encrypted = subprocess.run(base + ['--compress-algo', 'none', '--cipher-algo', 'AES256',
            '--trust-model', 'always', '--recipient', recipient, '--output', '-', '--encrypt'],
            input=bundle, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
        self.assertEqual(encrypted.returncode, 0, 'Synthetic GPG encryption failed')
        self.binary = Path(binary)
        self.write(self.args.cipher, encrypted.stdout)
        self.transfer.update(bytes=len(encrypted.stdout), sha256=digest(encrypted.stdout))
        self.write(self.args.transfer_receipt, canonical(self.transfer))
        self.args.restore_dir = str(self.root / 'restored')
        with mock.patch.object(subject, 'RECIPIENT', recipient):
            receipt = self.verify(timeout=30)
            self.assertEqual(receipt['status'], 'recovery_verified')
            folder = Path(self.args.restore_dir) / 'interrupted' / self.common.INTERRUPTED
            for name, expected in payloads.items():
                self.assertEqual((folder / name).read_bytes(), expected)
            # Bind the mutated ciphertext's new outer hash to ensure this tests
            # GPG/MDC or strict inner verification, not only the preflight hash.
            broken = bytearray(encrypted.stdout)
            broken[-8] ^= 1
            self.write(self.args.cipher, bytes(broken))
            self.transfer.update(bytes=len(broken), sha256=digest(broken))
            self.write(self.args.transfer_receipt, canonical(self.transfer))
            self.args.output = str(self.root / 'corrupt-recovery.json')
            self.args.restore_dir = str(self.root / 'corrupt-restored')
            with self.assertRaises(subject.Refused) as caught:
                self.verify(timeout=30)
            self.assertIn(caught.exception.code, ('gpg_failed', 'gpg_unauthenticated', 'bundle_invalid'))
            self.assertFalse(Path(self.args.output).exists())
            self.assertFalse(Path(self.args.restore_dir).exists())


if __name__ == '__main__':
    unittest.main()
