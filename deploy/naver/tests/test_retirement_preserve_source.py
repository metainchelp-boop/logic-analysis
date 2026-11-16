"""Synthetic files/processes plus public-only GPG; no production or private key reads."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / 'retirement_preserve_source.py'
SPEC = importlib.util.spec_from_file_location('preserve_source', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = 'PRIVATE_SYNTHETIC_CONTENT_CANARY'
PUBLIC = 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + b'x' * 32).decode()


class SourceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.temp.name))
        self.files = subject.Files(str(self.root), os.getuid())
        for path in ('/root', '/tmp', '/var/lib/docker/tmp', '/usr/bin', '/proc/123', '/assets'):
            self.local(path).mkdir(parents=True, exist_ok=True)
        for path in subject.BINARIES.values():
            self.local(path).write_text('synthetic executable placeholder')
            self.local(path).chmod(0o755)
        for name in (subject.PUBLIC_ASSET, subject.HOSTS_ASSET):
            self.local('/assets/' + name).write_bytes((PATH.parent / 'preservation' / name).read_bytes())
        fields = ['S'] + ['0'] * 18 + ['1000'] + ['0'] * 8
        self.local('/proc/123/stat').write_text('123 (dockerd) ' + ' '.join(fields))
        self.local('/proc/123/comm').write_text('dockerd\n')
        self.local('/proc/123/environ').write_bytes(('UNRELATED=' + CANARY + '\0').encode())
        self.frees = {'/tmp': subject.MIN_FREE + 1, '/var/lib/docker': subject.MIN_FREE + 1}
        self.files.free = lambda path: self.frees[path]
        self.calls, self.transfers = [], []
        self.image_size = 103807861
        self.source = subject.Preservation(self.files, '/assets', self.command, self.transfer)

    def tearDown(self):
        self.temp.cleanup()

    def local(self, path):
        return self.root / path.lstrip('/')

    def command(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == subject.BINARIES['systemctl']:
            return b'123\n'
        if argv[0] == subject.BINARIES['docker']:
            if 'info' in argv:
                return b'{"root":"/var/lib/docker","driver":"overlay2"}'
            if 'version' in argv:
                return b'{"client":"28.0.1","server":"28.0.1"}'
            if 'inspect' in argv:
                return json.dumps({'id': subject.IMAGE, 'size': self.image_size}).encode()
        if argv[0] == subject.BINARIES['gpg']:
            if '--list-keys' in argv:
                return ('pub:-:255:22:x:0:0:::::c:\nfpr:::::::::' + subject.RECIPIENT + ':\n').encode()
            if '--import' in argv:
                return b''
        if argv[0] == subject.BINARIES['keygen']:
            self.local(subject.DIRECTORY + '/' + subject.KEY).write_text(CANARY)
            self.local(subject.DIRECTORY + '/' + subject.KEY).chmod(0o600)
            self.local(subject.DIRECTORY + '/' + subject.KEY + '.pub').write_text(PUBLIC + '\n')
            return b''
        raise AssertionError('Unexpected synthetic command')

    def transfer(self, docker, gpg, ssh, **kwargs):
        self.transfers.append((docker, gpg, ssh))
        return {'bytes': 257, 'sha256': 'a' * 64, 'process_rc': {'docker': 0, 'gpg': 0, 'ssh': 0}}

    def check(self, phase):
        result = self.source.perform(phase)
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertFalse(result['backup_verified'])
        return result

    def refuse(self, phase, code):
        with self.assertRaises(subject.Refused) as caught:
            self.source.perform(phase)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY, str(caught.exception))

    def test_prepare_send_cleanup_lifecycle_retains_receipts_and_originals(self):
        before = self.local('/proc/123/environ').read_bytes()
        prepared = self.check('prepare')
        self.assertEqual(prepared['status'], 'prepared')
        self.assertEqual(prepared['ssh_public_key'], PUBLIC)
        self.assertEqual(self.local(subject.DIRECTORY).stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.local(subject.DIRECTORY + '/' + subject.KEY).stat().st_mode & 0o777, 0o600)
        sent = self.check('send')
        self.assertEqual(sent['status'], 'transferred_unverified')
        self.assertTrue(self.files.exists(subject.KEY))
        self.assertEqual(self.files.json('transfer-receipt.json')['sha256'], 'a' * 64)
        self.assertEqual(self.check('cleanup')['status'], 'transport_key_removed')
        self.assertFalse(self.files.exists(subject.KEY))
        self.assertFalse(self.files.exists(subject.KEY + '.pub'))
        self.assertTrue(self.files.exists('prepared.json'))
        self.assertTrue(self.files.exists('transfer-receipt.json'))
        self.assertEqual(self.check('cleanup')['status'], 'already_closed')
        self.assertEqual(self.local('/proc/123/environ').read_bytes(), before)
        self.refuse('send', 'session_closed')
        self.refuse('prepare', 'session_exists')

    def test_prepare_refuses_existing_session_without_overwrite(self):
        self.check('prepare')
        before = self.files.json('prepared.json')
        self.refuse('prepare', 'session_exists')
        self.assertEqual(self.files.json('prepared.json'), before)

    def test_source_only_passes_fixed_image_recipient_ssh_identity_and_command(self):
        self.check('prepare')
        self.check('send')
        docker, gpg, ssh = self.transfers[0]
        self.assertEqual(docker[-2:], ['save', subject.IMAGE])
        self.assertIn('--no-options', gpg)
        self.assertIn('--no-autostart', gpg)
        self.assertEqual(gpg[-3:], ['--recipient', subject.RECIPIENT, '--encrypt'])
        for option in ('StrictHostKeyChecking=yes', 'IdentitiesOnly=yes', 'ForwardAgent=no',
                       'GlobalKnownHostsFile=/dev/null', 'UpdateHostKeys=no', 'ControlMaster=no',
                       'ControlPath=none', 'PasswordAuthentication=no', 'KbdInteractiveAuthentication=no'):
            self.assertIn(option, ssh)
        self.assertEqual(ssh[-2:], ['root@139.162.109.181', 'receive-ad-image-20261102-v1'])
        self.assertNotIn(CANARY, ' '.join(ssh))

    def test_source_private_transport_key_is_never_read_by_python(self):
        real_read = self.files.read

        def public_only(path, *args, **kwargs):
            self.assertNotEqual(path, subject.DIRECTORY + '/' + subject.KEY)
            return real_read(path, *args, **kwargs)

        self.files.read = public_only
        self.check('prepare')
        self.check('send')
        self.check('cleanup')

    def test_low_space_fails_before_key_generation_and_supports_cleanup(self):
        self.frees['/tmp'] = subject.MIN_FREE - 1
        self.refuse('prepare', 'space_insufficient')
        self.assertFalse(self.files.exists(subject.KEY))
        self.assertEqual(self.files.json('failure-receipt.json')['status'], 'failed')
        self.check('cleanup')

    def test_image_size_cap_refuses_before_generation(self):
        self.image_size = subject.MAX_IMAGE + 1
        self.refuse('prepare', 'image_invalid')
        self.assertFalse(any(call[0] == subject.BINARIES['keygen'] for call in self.calls))

    def test_custom_daemon_temp_settings_and_duplicates_are_rejected(self):
        for value in (b'DOCKER_TMPDIR=/outside\0', b'TMPDIR=/outside\0',
                      b'DOCKER_TMPDIR=/tmp\0DOCKER_TMPDIR=/tmp\0', b'TMPDIR=\0'):
            self.local('/proc/123/environ').write_bytes(value)
            with self.assertRaises(subject.Refused) as caught:
                self.source.preflight()
            self.assertEqual(caught.exception.code, 'daemon_unverified')

    def test_allowed_daemon_temp_settings_do_not_change_output(self):
        self.local('/proc/123/environ').write_bytes(b'DOCKER_TMPDIR=/var/lib/docker/tmp\0TMPDIR=/tmp\0')
        self.assertEqual(self.source.preflight(), self.image_size)

    def test_daemon_starttime_change_and_wrong_process_are_rejected(self):
        real_read = self.files.read
        reads = 0

        def changed(path, *args, **kwargs):
            nonlocal reads
            data = real_read(path, *args, **kwargs)
            if path == '/proc/123/stat':
                reads += 1
                if reads == 2:
                    return data.replace(b'1000', b'1001')
            return data

        self.files.read = changed
        with self.assertRaises(subject.Refused) as caught:
            self.source.preflight()
        self.assertEqual(caught.exception.code, 'daemon_unverified')
        self.files.read = real_read
        self.local('/proc/123/comm').write_text(CANARY)
        with self.assertRaises(subject.Refused):
            self.source.preflight()

    def test_daemon_dynamic_cpu_fields_do_not_false_positive_on_reuse_guard(self):
        first = b'123 (dockerd) ' + b' '.join([b'S'] + [b'0'] * 18 + [b'1000', b'1'])
        second = b'123 (dockerd) ' + b' '.join([b'S'] + [b'3'] * 18 + [b'1000', b'9'])
        self.assertEqual(subject.process_start(first, b'123'), subject.process_start(second, b'123'))

    def test_asset_mutation_is_refused_before_transport_key(self):
        self.local('/assets/' + subject.PUBLIC_ASSET).write_text(CANARY)
        self.refuse('prepare', 'asset_invalid')
        self.assertFalse(self.files.exists(subject.KEY))

    def test_recipient_mismatch_is_refused(self):
        real_run = self.command

        def bad(argv, **kwargs):
            value = real_run(argv, **kwargs)
            return value.replace(subject.RECIPIENT.encode(), b'0' * 40) if '--list-keys' in argv else value

        self.source.run = bad
        self.refuse('prepare', 'recipient_invalid')

    def test_successful_send_cannot_be_repeated(self):
        self.check('prepare')
        self.check('send')
        self.refuse('send', 'attempt_exists')
        self.assertEqual(len(self.transfers), 1)

    def test_failed_pipeline_retains_key_until_explicit_cleanup(self):
        self.check('prepare')
        self.source.transfer = mock.Mock(side_effect=subject.Refused('pipeline_failed'))
        self.refuse('send', 'pipeline_failed')
        self.assertTrue(self.files.exists(subject.KEY))
        self.assertFalse(self.files.exists('transfer-receipt.json'))
        self.check('cleanup')
        self.assertFalse(self.files.exists(subject.KEY))
        self.assertTrue(self.files.exists('failure-receipt.json'))

    def test_unreaped_pipeline_has_no_terminal_receipt_and_cannot_cleanup(self):
        self.check('prepare')
        self.source.transfer = mock.Mock(side_effect=subject.Unfinished())
        self.refuse('send', 'attempt_not_terminal')
        self.assertFalse(self.files.exists('failure-receipt.json'))
        self.refuse('send', 'attempt_exists')
        self.assertFalse(self.files.exists('failure-receipt.json'))
        self.refuse('cleanup', 'attempt_not_terminal')
        self.assertTrue(self.files.exists(subject.KEY))

    def test_incomplete_prepare_cannot_be_silently_cleaned(self):
        self.files.mkdir(subject.BASE)
        self.files.mkdir(subject.DIRECTORY)
        with self.files.lock(create=True):
            self.files.record('prepare-attempt.json', {'session': subject.SESSION, 'phase': 'prepare'})
        self.refuse('cleanup', 'attempt_not_terminal')

    def test_lock_contention_prevents_second_phase(self):
        self.check('prepare')
        with self.files.lock():
            self.refuse('cleanup', 'lock_busy')
        self.assertTrue(self.files.exists(subject.KEY))

    def test_relaxed_session_permissions_are_rejected(self):
        self.check('prepare')
        self.local(subject.DIRECTORY).chmod(0o755)
        self.refuse('cleanup', 'unsafe_path')

    def test_symlink_session_or_asset_is_refused(self):
        self.local('/assets/' + subject.PUBLIC_ASSET).unlink()
        self.local('/assets/' + subject.PUBLIC_ASSET).symlink_to(self.local('/proc/123/environ'))
        self.refuse('prepare', 'unsafe_path')

    def test_existing_receipt_cannot_be_overwritten(self):
        self.check('prepare')
        before = self.files.json('prepared.json')
        with self.assertRaises(subject.Refused) as caught:
            self.files.record('prepared.json', {'raw': CANARY})
        self.assertEqual(caught.exception.code, 'file_exists')
        self.assertEqual(self.files.json('prepared.json'), before)

    def test_phase_deadline_includes_preflight_before_pipeline(self):
        self.check('prepare')
        now = [1000]
        real_run = self.command
        observed = []

        def slow(argv, **kwargs):
            self.assertLessEqual(kwargs['timeout'], 20)
            now[0] += 2
            return real_run(argv, **kwargs)

        def transferred(docker, gpg, ssh, **kwargs):
            observed.append(kwargs['timeout'])
            return self.transfer(docker, gpg, ssh)

        self.source.runner, self.source.transfer = slow, transferred
        with mock.patch.object(subject.time, 'monotonic', side_effect=lambda: now[0]):
            self.check('send')
        self.assertEqual(observed, [subject.DEADLINE - 10])

    def test_expired_preflight_never_starts_pipeline(self):
        self.check('prepare')
        now = [1000]
        real_run = self.command

        def expired(argv, **kwargs):
            now[0] += subject.DEADLINE + 1
            return real_run(argv, **kwargs)

        self.source.runner = expired
        with mock.patch.object(subject.time, 'monotonic', side_effect=lambda: now[0]):
            self.refuse('send', 'deadline_exceeded')
        self.assertFalse(self.transfers)

    def test_parent_replacement_is_detected_after_descriptor_operation(self):
        with self.assertRaises(subject.Refused) as caught:
            with self.files.directory('/assets'):
                self.local('/assets').rename(self.local('/old-assets'))
                self.local('/assets').mkdir()
        self.assertEqual(caught.exception.code, 'path_changed')

    def test_parent_symlink_and_group_write_are_rejected(self):
        self.local('/assets').rename(self.local('/old-assets'))
        self.local('/assets').symlink_to(self.local('/old-assets'), target_is_directory=True)
        with self.assertRaises(subject.Refused):
            with self.files.directory('/assets'):
                self.fail('Symlink parent was traversed')
        self.local('/assets').unlink()
        self.local('/old-assets').rename(self.local('/assets'))
        self.local('/assets').chmod(0o770)
        with self.assertRaises(subject.Refused):
            with self.files.directory('/assets'):
                self.fail('Writable parent was traversed')


def python(code):
    return [sys.executable, '-I', '-B', '-c', code]


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.data = (CANARY * 20000).encode()
        self.producer = python('import sys; sys.stdout.buffer.write(' + repr(CANARY.encode()) + '*20000)')
        # Reversible synthetic byte transform, not a cryptographic implementation.
        self.encryptor = python('import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(bytes(x^91 for x in d))')
        self.receiver = python('import sys,json,hashlib; d=sys.stdin.buffer.read(); print(json.dumps({"status":"received_unverified","bytes":len(d),"sha256":hashlib.sha256(d).hexdigest()}))')

    def invoke(self, producer=None, encryptor=None, receiver=None, **kwargs):
        return subject.stream_image(producer or self.producer, encryptor or self.encryptor,
                                    receiver or self.receiver, **kwargs)

    def test_cipher_backpressure_hash_size_all_three_codes_match(self):
        result = self.invoke()
        cipher = bytes(x ^ 91 for x in self.data)
        self.assertEqual(result, {'bytes': len(cipher), 'sha256': hashlib.sha256(cipher).hexdigest(),
                                 'process_rc': {'docker': 0, 'gpg': 0, 'ssh': 0}})

    def test_partial_transport_writes_are_not_lost(self):
        producer = python('import sys; sys.stdout.buffer.write(b"x"*4096)')
        real_write = os.write
        with mock.patch.object(subject.os, 'write', side_effect=lambda fd, data: real_write(fd, data[:17])):
            result = self.invoke(producer=producer)
        self.assertEqual(result['bytes'], 4096)
        self.assertEqual(result['sha256'], hashlib.sha256(bytes([ord('x') ^ 91]) * 4096).hexdigest())

    def test_each_failed_process_prevents_success_even_when_receipt_matches(self):
        choices = [dict(producer=python('import sys;sys.stdout.buffer.write(b"x"*10);sys.exit(7)')),
                   dict(encryptor=python('import sys;sys.stdin.buffer.read();sys.stdout.buffer.write(b"cipher");sys.exit(8)')),
                   dict(receiver=python('import sys;sys.stdin.buffer.read();sys.exit(9)'))]
        for override in choices:
            with self.assertRaises(subject.Refused) as caught:
                self.invoke(**override)
            self.assertIn(caught.exception.code, ('pipeline_failed', 'pipe_failed'))

    def test_wrong_or_extra_receipt_data_is_rejected(self):
        for obj in ({'status': 'received_unverified', 'bytes': 4, 'sha256': 'f' * 64},
                    {'status': 'verified', 'bytes': 4, 'sha256': 'f' * 64}, {'raw': CANARY}):
            receiver = python('import sys;sys.stdin.buffer.read();print(' + repr(json.dumps(obj)) + ')')
            with self.assertRaises(subject.Refused) as caught:
                self.invoke(receiver=receiver)
            self.assertEqual(caught.exception.code, 'receipt_invalid')

    def test_receipt_stdout_cap_is_enforced(self):
        receiver = python('import sys;sys.stdin.buffer.read();print("x"*1100)')
        with self.assertRaises(subject.Refused) as caught:
            self.invoke(receiver=receiver)
        self.assertEqual(caught.exception.code, 'receipt_invalid')

    def test_duplicate_or_multiline_receipts_are_rejected(self):
        for data in (b'{"bytes":1,"bytes":2}', b'{\n"bytes":1\n}', b'{}\n{}\n'):
            with self.assertRaises(subject.Refused) as caught:
                subject.strict_json(data)
            self.assertEqual(caught.exception.code, 'receipt_invalid')
        self.assertEqual(subject.strict_json(b'{"bytes":1}\n'), {'bytes': 1})

    def test_cipher_limit_kills_pipeline(self):
        with self.assertRaises(subject.Refused) as caught:
            self.invoke(max_cipher=8)
        self.assertEqual(caught.exception.code, 'cipher_limit')

    def test_stderr_is_bounded_and_not_returned(self):
        producer = python('import sys;sys.stderr.write(' + repr(CANARY) + '*4000);sys.stdout.write("x")')
        with self.assertRaises(subject.Refused) as caught:
            self.invoke(producer=producer)
        self.assertEqual(caught.exception.code, 'command_limit')
        self.assertNotIn(CANARY, str(caught.exception))

    def test_timeout_reaps_children(self):
        producer = python('import time;time.sleep(20)')
        started = time.monotonic()
        with self.assertRaises(subject.Refused) as caught:
            self.invoke(producer=producer, timeout=.1)
        self.assertEqual(caught.exception.code, 'deadline_exceeded')
        self.assertLess(time.monotonic() - started, 4)

    def test_early_ssh_exit_does_not_hang_on_backpressure(self):
        with self.assertRaises(subject.Refused) as caught:
            self.invoke(receiver=python('raise SystemExit(7)'), timeout=2)
        self.assertIn(caught.exception.code, ('pipe_failed', 'pipeline_failed'))

    def test_command_bounds_and_nonzero_exit(self):
        for code, limit, expected in [('print("x"*20)', 10, 'command_limit'),
                                     ('raise SystemExit(4)', 10, 'command_failed'),
                                     ('import time;time.sleep(20)', 10, 'deadline_exceeded')]:
            with self.assertRaises(subject.Refused) as caught:
                subject.command(python(code), limit=limit, timeout=.1)
            self.assertEqual(caught.exception.code, expected)


class PublicGpgTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('gpg'), 'Public-only GPG integration requires gpg on PATH')
    def test_pinned_public_asset_import_and_encrypt_without_private_key_or_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'gpg'
            home.mkdir(mode=0o700)
            argv = [shutil.which('gpg'), '--no-options', '--homedir', str(home), '--batch', '--no-tty',
                    '--no-autostart', '--no-auto-key-retrieve', '--auto-key-locate', 'clear']
            imported = subprocess.run(argv + ['--import', str(PATH.parent / 'preservation' / subject.PUBLIC_ASSET)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual(imported.returncode, 0)
            encrypted = subprocess.run(argv + ['--trust-model', 'always', '--compress-algo', 'none',
                '--cipher-algo', 'AES256', '--recipient', subject.RECIPIENT, '--encrypt'],
                input=b'synthetic-public-only', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual(encrypted.returncode, 0)
            self.assertGreater(len(encrypted.stdout), 32)
            self.assertNotIn(b'synthetic-public-only', encrypted.stdout)
            secret_dir = home / 'private-keys-v1.d'
            self.assertFalse(secret_dir.exists() and any(secret_dir.iterdir()))


class EntrypointTest(unittest.TestCase):
    def test_no_path_argument_and_nonroot_are_rejected_without_phase_execution(self):
        for argv, uid, error in (['helper', '--path', CANARY], 0, 'invalid_phase'), \
                (['helper', 'send'], 501, 'root_required'):
            stream = io.StringIO()
            with mock.patch.object(subject.sys, 'argv', argv), mock.patch.object(subject.os, 'geteuid', return_value=uid), \
                    mock.patch.object(subject, 'Preservation') as constructor, contextlib.redirect_stdout(stream):
                rc = subject.main()
            self.assertEqual(rc, 2)
            constructor.assert_not_called()
            self.assertEqual(json.loads(stream.getvalue())['error'], error)
            self.assertNotIn(CANARY, stream.getvalue())


if __name__ == '__main__':
    unittest.main()
