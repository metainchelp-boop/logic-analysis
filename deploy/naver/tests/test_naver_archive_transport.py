"""Synthetic pipes and ciphertext only; never invokes real GPG, SSH, or keys."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / 'naver_archive_transport.py'
SPEC = importlib.util.spec_from_file_location('naver_transport', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)

CANARY = 'SYNTHETIC_PLAINTEXT_NOT_FOR_RECEIPTS'
PAYLOAD = (CANARY.encode() + b'\0') * 17003


def child(code):
    return [sys.executable, '-I', '-B', '-c', code]


SOURCE = child('import os; os.write(1, (' + repr(CANARY.encode() + b'\0') + ')*17003)')
PASSTHROUGH = child('import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data[::-1])')
REMOTE = child('import sys,hashlib,json; data=sys.stdin.buffer.read(); '
               'print(json.dumps({"status":"received_unverified","bytes":len(data),'
               '"sha256":hashlib.sha256(data).hexdigest()}))')


class TransportTests(unittest.TestCase):
    def refuse(self, code, fn, *args, **kwargs):
        with self.assertRaises(subject.Refused) as caught:
            fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY, str(caught.exception))

    def test_send_streams_bounded_cipher_and_matching_remote_receipt(self):
        result = subject.stream_send(SOURCE, PASSTHROUGH, REMOTE, timeout=5)
        self.assertEqual(result, {'bytes': len(PAYLOAD),
                                 'sha256': hashlib.sha256(PAYLOAD[::-1]).hexdigest()})
        self.assertNotIn(CANARY, json.dumps(result))

    def test_producer_exit_failure_rejects_matching_cipher_receipt(self):
        source = child('import os; os.write(1,b"partial"); raise SystemExit(7)')
        self.refuse('pipeline_failed', subject.stream_send, source, PASSTHROUGH, REMOTE, timeout=5)

    def test_encryptor_exit_failure_rejects_matching_cipher_receipt(self):
        gpg = child('import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write(b"partial"); raise SystemExit(7)')
        self.refuse('pipeline_failed', subject.stream_send, SOURCE, gpg, REMOTE, timeout=5)

    def test_ssh_nonzero_rejects_matching_receipt(self):
        remote = child(REMOTE[-1] + '; raise SystemExit(8)')
        self.refuse('pipeline_failed', subject.stream_send, SOURCE, PASSTHROUGH, remote, timeout=5)

    def test_ssh_early_exit_cleans_up_pipeline(self):
        started = time.monotonic()
        with self.assertRaises(subject.Refused):
            subject.stream_send(SOURCE, PASSTHROUGH, child('pass'), timeout=2)
        self.assertLess(time.monotonic() - started, 4)

    def test_cipher_limit_aborts_before_acknowledgement(self):
        self.refuse('cipher_limit', subject.stream_send, SOURCE, PASSTHROUGH, REMOTE,
                    timeout=5, max_cipher=100)

    def test_wrong_receipt_hash_rejected(self):
        remote = child('import sys,json; d=sys.stdin.buffer.read(); '
                       'print(json.dumps({"status":"received_unverified","bytes":len(d),"sha256":"0"*64}))')
        self.refuse('receipt_invalid', subject.stream_send, SOURCE, PASSTHROUGH, remote, timeout=5)

    def test_duplicate_receipt_fields_rejected(self):
        remote = child('import sys; sys.stdin.buffer.read(); print(\'{"status":"received_unverified","bytes":1,"bytes":2,"sha256":"a"}\')')
        self.refuse('receipt_invalid', subject.stream_send, SOURCE, PASSTHROUGH, remote, timeout=5)

    def test_stderr_is_bounded_and_not_returned(self):
        source = child('import sys; sys.stderr.write("' + CANARY + '"*10000)')
        self.refuse('output_limit', subject.stream_send, source, PASSTHROUGH, REMOTE, timeout=5)

    def test_empty_cipher_never_succeeds(self):
        self.refuse('pipeline_failed', subject.stream_send, child('pass'), PASSTHROUGH, REMOTE, timeout=5)

    def test_deadline_terminates_children_including_held_pipe(self):
        source = child('import os,time; pid=os.fork(); time.sleep(60) if pid == 0 else None')
        started = time.monotonic()
        self.refuse('deadline_exceeded', subject.stream_send, source, PASSTHROUGH, REMOTE, timeout=.2)
        self.assertLess(time.monotonic() - started, 4)

    def test_spawn_failure_reaps_previously_started_producer(self):
        real = subject.subprocess.Popen
        children = []
        def fail_second(*args, **kwargs):
            if children:
                raise OSError('synthetic spawn failure')
            process = real(*args, **kwargs)
            children.append(process)
            return process
        with mock.patch.object(subject.subprocess, 'Popen', side_effect=fail_second):
            with self.assertRaises(OSError):
                subject.stream_send(child('import time; time.sleep(60)'), PASSTHROUGH, REMOTE, timeout=5)
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].returncode)
        self.assertTrue(children[0].stdout.closed)
        self.assertTrue(children[0].stderr.closed)

    def test_command_limits_and_discards_stderr(self):
        self.assertEqual(subject.command(child('print("safe")')), b'safe\n')
        self.refuse('output_limit', subject.command, child('print("x"*100)'), limit=3)
        self.refuse('command_failed', subject.command,
                    child('import sys; sys.stderr.write("' + CANARY + '"); raise SystemExit(4)'))

    def test_new_fixed_ssh_commands_and_host_validation(self):
        for action in (subject.RECEIVE, subject.FETCH):
            argv = subject.ssh_args('/key', '/knownhosts', action)
            self.assertEqual(argv[-2:], ['root@139.162.109.181', action])
            for value in ('BatchMode=yes', 'StrictHostKeyChecking=yes', 'ForwardAgent=no',
                          'GlobalKnownHostsFile=/dev/null', 'ControlPath=none', 'UpdateHostKeys=no'):
                self.assertIn(value, argv)
            self.assertEqual(argv[1:4], ['-F', '/dev/null', '-T'])
        self.refuse('internal_failure', subject.ssh_args, '/key', '/hosts', 'receive-data-snapshot-20261102-v1')
        quoted = subject.ssh_args('/key', '/secure/a space/hosts', subject.FETCH)
        self.assertIn('UserKnownHostsFile="/secure/a space/hosts"', quoted)
        self.refuse('unsafe_path', subject.ssh_args, '/key', '/hosts\nother', subject.FETCH)


class FilesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(os.path.realpath(temp.name))
        self.files = subject.Files(str(self.root), os.geteuid())
        (self.root / 'secure').mkdir(mode=0o700)
        self.payload = b'SYNTHETIC_CIPHERTEXT' * 1000
        self.receipt = {'status': 'sent_unverified', 'session': subject.SESSION,
                        'plan_sha256': 'a' * 64, 'bytes': len(self.payload),
                        'sha256': hashlib.sha256(self.payload).hexdigest()}

    def fetch(self, payload=None, **kwargs):
        code = 'import os; os.write(1,' + repr(self.payload if payload is None else payload) + ')'
        return subject.stream_fetch(child(code), self.receipt, '/secure/cipher.gpg', self.files, timeout=5, **kwargs)

    def test_fetch_same_fd_verification_and_exclusive_publication(self):
        result = self.fetch()
        self.assertEqual(result['status'], 'fetched_unverified')
        self.assertEqual((self.root / 'secure/cipher.gpg').read_bytes(), self.payload)
        self.assertEqual((self.root / 'secure/cipher.gpg').stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / 'secure/cipher.gpg.partial').exists())
        with self.assertRaises(subject.Refused) as caught:
            self.fetch()
        self.assertEqual(caught.exception.code, 'file_exists')

    def test_fetch_truncation_keeps_partial_no_final(self):
        with self.assertRaises(subject.Refused) as caught:
            self.fetch(self.payload[:100])
        self.assertEqual(caught.exception.code, 'cipher_mismatch')
        self.assertEqual((self.root / 'secure/cipher.gpg.partial').read_bytes(), self.payload[:100])
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())

    def test_fetch_oversize_keeps_partial_no_final(self):
        with self.assertRaises(subject.Refused) as caught:
            self.fetch(self.payload + b'extra')
        self.assertEqual(caught.exception.code, 'cipher_limit')
        self.assertTrue((self.root / 'secure/cipher.gpg.partial').exists())
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())

    def test_fetch_matching_cipher_but_ssh_failure_is_not_success(self):
        argv = child('import os; os.write(1,' + repr(self.payload) + '); raise SystemExit(3)')
        with self.assertRaises(subject.Refused) as caught:
            subject.stream_fetch(argv, self.receipt, '/secure/cipher.gpg', self.files, timeout=5)
        self.assertEqual(caught.exception.code, 'pipeline_failed')
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())
        self.assertEqual((self.root / 'secure/cipher.gpg.partial').read_bytes(), self.payload)

    def test_fetch_existing_partial_refused_not_overwritten(self):
        partial = self.root / 'secure/cipher.gpg.partial'
        partial.write_bytes(b'previous evidence')
        with self.assertRaises(FileExistsError):
            self.fetch()
        self.assertEqual(partial.read_bytes(), b'previous evidence')

    def test_fetch_path_swap_during_same_fd_rehash_refuses_publication(self):
        real_lseek = subject.os.lseek
        partial = self.root / 'secure/cipher.gpg.partial'
        def swap(fd, offset, whence):
            result = real_lseek(fd, offset, whence)
            partial.rename(partial.with_name('retained-original.partial'))
            partial.write_bytes(self.payload)
            partial.chmod(0o600)
            return result
        with mock.patch.object(subject.os, 'lseek', side_effect=swap):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'path_changed')
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())

    def test_fetch_capacity_checks_before_output_creation(self):
        small = types.SimpleNamespace(f_bavail=10, f_frsize=1)
        with mock.patch.object(subject.os, 'fstatvfs', return_value=small):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'space_insufficient')
        self.assertEqual(list((self.root / 'secure').iterdir()), [])

    def test_fetch_midstream_disk_pressure_keeps_evidence(self):
        ample = types.SimpleNamespace(f_bavail=10 ** 12, f_frsize=1)
        small = types.SimpleNamespace(f_bavail=10, f_frsize=1)
        with mock.patch.object(subject.os, 'fstatvfs', side_effect=[ample, small]):
            with self.assertRaises(subject.Refused) as caught:
                self.fetch()
        self.assertEqual(caught.exception.code, 'space_insufficient')
        self.assertTrue((self.root / 'secure/cipher.gpg.partial').exists())
        self.assertFalse((self.root / 'secure/cipher.gpg').exists())

    def test_symlink_parent_and_output_refused(self):
        (self.root / 'link').symlink_to(self.root / 'secure', target_is_directory=True)
        with self.assertRaises(subject.Refused):
            subject.stream_fetch(child('pass'), self.receipt, '/link/cipher', self.files, timeout=5)
        (self.root / 'secure/cipher.gpg').symlink_to(self.root / 'target')
        with self.assertRaises(subject.Refused) as caught:
            self.fetch()
        self.assertEqual(caught.exception.code, 'file_exists')

    def test_file_security_and_identity_revalidation(self):
        path = self.root / 'secure/plan.json'
        path.write_bytes(b'{}')
        path.chmod(0o600)
        self.assertEqual(self.files.read('/secure/plan.json', 100, 0o600), b'{}')
        with self.assertRaises(subject.Refused) as caught:
            with self.files.opened('/secure/plan.json', 0o600):
                path.rename(path.with_name('old.json'))
                path.write_bytes(b'{}')
                path.chmod(0o600)
        self.assertEqual(caught.exception.code, 'path_changed')
        path.chmod(0o644)
        with self.assertRaises(subject.Refused):
            self.files.read('/secure/plan.json', 100, 0o600)

    def test_one_shot_session_directory_cannot_be_reused(self):
        self.files.mkdir('/secure/new-session')
        self.files.create('/secure/new-session/attempt.json', b'{}')
        with self.assertRaises(subject.Refused) as caught:
            self.files.mkdir('/secure/new-session')
        self.assertEqual(caught.exception.code, 'session_exists')

    def test_receipt_rejects_bool_size_extra_field_and_wrong_session(self):
        for change in ({'bytes': True}, {'extra': True}, {'session': 'data-snapshot-20261102-v1'},
                       {'sha256': 'invalid'}, {'status': 'verified'}):
            with self.assertRaises(subject.Refused):
                subject.validate_sent({**self.receipt, **change})

    def test_pinned_public_assets_accepted_changed_asset_refused(self):
        folder = self.root / 'secure/assets'
        folder.mkdir()
        for name in ('recovery-public.asc', 'server-b-known-hosts'):
            (folder / name).write_bytes((PATH.parent / 'preservation' / name).read_bytes())
        subject.assets(self.files, '/secure/assets')
        (folder / 'server-b-known-hosts').write_bytes(b'untrusted host')
        with self.assertRaises(subject.Refused) as caught:
            subject.assets(self.files, '/secure/assets')
        self.assertEqual(caught.exception.code, 'asset_invalid')


class SendInterfaceTests(unittest.TestCase):
    def setUp(self):
        FilesTests.setUp(self)
        self.base = str(PATH.parent)
        source_dir = self.root / self.base.lstrip('/')
        source_dir.mkdir(parents=True)
        (source_dir / 'preservation').mkdir()
        for name in ('recovery-public.asc', 'server-b-known-hosts'):
            (source_dir / 'preservation' / name).write_bytes((PATH.parent / 'preservation' / name).read_bytes())
        (source_dir / 'naver_archive_source.py').write_bytes(b'# Synthetic source fixture')
        (self.root / 'usr/bin').mkdir(parents=True)
        for name in ('gpg', 'ssh'):
            (self.root / 'usr/bin' / name).write_bytes(b'# Synthetic dependency fixture')
        self.files.create('/secure/plan.json', b'{"version":1}')
        self.files.create('/secure/new-transport-key', CANARY.encode())
        self.args = types.SimpleNamespace(plan='/secure/plan.json',
            plan_sha256=hashlib.sha256(b'{"version":1}').hexdigest(),
            transport_key='/secure/new-transport-key', session_dir='/secure/session')

    def command(self, argv, **kwargs):
        self.assertEqual(argv[0], '/usr/bin/gpg')
        self.assertIn('--no-options', argv)
        self.assertIn('--no-autostart', argv)
        if '--list-keys' in argv:
            return ('pub:-:255:22:x:0:0:::::c:\nfpr:::::::::' + subject.RECIPIENT + ':\n').encode()
        self.assertIn('--import', argv)
        return b''

    def test_send_cli_uses_public_assets_and_fixed_source_interface(self):
        result = {'bytes': 111, 'sha256': 'c' * 64}
        with mock.patch.object(subject.os, 'geteuid', return_value=0), \
                mock.patch.object(subject, 'command', side_effect=self.command), \
                mock.patch.object(subject, 'stream_send', return_value=result) as sending, \
                mock.patch.object(self.files, 'read', wraps=self.files.read) as reading:
            receipt = subject.send(self.args, self.files)
        self.assertEqual(receipt, {'status': 'sent_unverified', 'session': subject.SESSION,
            'plan_sha256': self.args.plan_sha256, **result})
        source, gpg, ssh = sending.call_args.args
        self.assertEqual(source[1:], ['-I', '-B', self.base + '/naver_archive_source.py',
            'stream', '--plan', self.args.plan, '--plan-sha256', self.args.plan_sha256])
        self.assertIn('AES256', gpg)
        self.assertIn('none', gpg)
        self.assertEqual(ssh[-1], subject.RECEIVE)
        self.assertNotIn(self.args.transport_key, [call.args[0] for call in reading.call_args_list])
        saved = (self.root / 'secure/session/sent.json').read_bytes()
        self.assertEqual(saved, subject.canonical(receipt))
        self.assertNotIn(CANARY.encode(), saved)

    def test_failed_send_leaves_one_shot_attempt_and_refuses_retry(self):
        with mock.patch.object(subject.os, 'geteuid', return_value=0), \
                mock.patch.object(subject, 'command', side_effect=self.command), \
                mock.patch.object(subject, 'stream_send', side_effect=subject.Refused('pipeline_failed')):
            with self.assertRaises(subject.Refused) as caught:
                subject.send(self.args, self.files)
            self.assertEqual(caught.exception.code, 'pipeline_failed')
            self.assertTrue((self.root / 'secure/session/attempt.json').is_file())
            self.assertFalse((self.root / 'secure/session/sent.json').exists())
            with self.assertRaises(subject.Refused) as caught:
                subject.send(self.args, self.files)
            self.assertEqual(caught.exception.code, 'session_exists')

    def test_plan_hash_mismatch_refused_before_any_send_or_session_write(self):
        self.args.plan_sha256 = 'f' * 64
        with mock.patch.object(subject.os, 'geteuid', return_value=0):
            with self.assertRaises(subject.Refused) as caught:
                subject.send(self.args, self.files)
        self.assertEqual(caught.exception.code, 'plan_invalid')
        self.assertFalse((self.root / 'secure/session').exists())


if __name__ == '__main__':
    unittest.main()
