"""Synthetic original files and process faults only; no production key access."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock
from types import SimpleNamespace

PATH = Path(__file__).resolve().parents[1] / 'retirement_key_capsule_source.py'
SPEC = importlib.util.spec_from_file_location('capsule_source', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = b'SYNTHETIC_PRIVATE_KEY_CANARY'
PUBLIC = 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + b'x' * 32).decode()


class SourceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.temp.name))
        self.files = subject.Files(str(self.root), os.getuid())
        for directory in ('/root', '/usr/bin', '/assets'):
            self.local(directory).mkdir(parents=True, exist_ok=True)
        for path in subject.BINARIES.values():
            self.local(path).write_text('synthetic executable')
            self.local(path).chmod(0o755)
        for name in (subject.PUBLIC_ASSET, subject.HOSTS_ASSET):
            self.local('/assets/' + name).write_bytes((PATH.parent / 'preservation' / name).read_bytes())
        self.bodies = [CANARY + b'\0\xff\n', b'NOT_PARSED=' + CANARY + b'\n# arbitrary bytes\xff\0']
        for (path, _), body in zip(subject.ORIGINALS, self.bodies):
            self.local(path).parent.mkdir(parents=True, exist_ok=True)
            self.local(path).write_bytes(body)
            self.local(path).chmod(0o600)
        self.files.free = lambda path: subject.MIN_FREE + 1
        self.calls, self.transfers, self.plain_refs = [], [], []
        self.source = subject.Capsule(self.files, '/assets', self.command, self.transfer)

    def tearDown(self):
        self.temp.cleanup()

    def local(self, path):
        return self.root / path.lstrip('/')

    def command(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == subject.BINARIES['gpg']:
            if '--list-keys' in argv:
                return ('pub:-:255:22:x:0:0:::::c:\nfpr:::::::::' + subject.RECIPIENT + ':\n').encode()
            if '--import' in argv:
                return b''
        if argv[0] == subject.BINARIES['keygen']:
            self.local(subject.DIRECTORY + '/' + subject.KEY).write_bytes(CANARY)
            self.local(subject.DIRECTORY + '/' + subject.KEY).chmod(0o600)
            self.local(subject.DIRECTORY + '/' + subject.KEY + '.pub').write_text(PUBLIC + '\n')
            return b''
        raise AssertionError('Unexpected synthetic command')

    def transfer(self, plain, gpg, ssh, **kwargs):
        self.plain_refs.append(plain)
        self.transfers.append((bytes(plain), gpg, ssh, kwargs))
        return {'bytes': 257, 'sha256': 'a' * 64, 'process_rc': {'gpg': 0, 'ssh': 0}}

    def check(self, phase):
        result = self.source.perform(phase)
        self.assertNotIn(CANARY.decode(), json.dumps(result))
        self.assertFalse(result['backup_verified'])
        return result

    def refuse(self, phase, code):
        with self.assertRaises(subject.Refused) as caught:
            self.source.perform(phase)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY.decode(), str(caught.exception))

    def assert_tar(self, data):
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as tar:
            members = tar.getmembers()
            self.assertEqual([item.name for item in members], [alias for _, alias in subject.ORIGINALS])
            for member, body in zip(members, self.bodies):
                self.assertTrue(member.isfile())
                self.assertEqual((member.mode, member.uid, member.gid, member.mtime), (0o600, 0, 0, 0))
                self.assertEqual(tar.extractfile(member).read(), body)

    def test_archive_preserves_exact_arbitrary_bytes_and_fixed_two_members(self):
        data, size = subject.source_archive(self.files)
        self.assert_tar(data)
        self.assertEqual(size, sum(map(len, self.bodies)))
        self.assertLessEqual(len(data), subject.MAX_ARCHIVE)

    def test_prepare_never_opens_original_bodies(self):
        original_open = os.open
        def guarded(path, *args, **kwargs):
            self.assertNotIn(path, ('secret.key', '.env'))
            return original_open(path, *args, **kwargs)
        with mock.patch.object(subject.os, 'open', side_effect=guarded):
            result = self.check('prepare')
        self.assertEqual(result['source_size_bytes'], sum(map(len, self.bodies)))
        self.assertEqual(result['ssh_public_key'], PUBLIC)
        self.assertFalse(self.transfers)

    def test_lifecycle_wipes_owned_archive_retains_receipts_and_originals(self):
        self.check('prepare')
        sent = self.check('send')
        self.assertEqual(sent['status'], 'transferred_unverified')
        self.assertEqual(sent['source_size_bytes'], sum(map(len, self.bodies)))
        self.assert_tar(self.transfers[0][0])
        self.assertEqual(set(self.plain_refs[0]), {0})
        self.assertTrue(self.files.exists(subject.KEY))
        self.assertEqual(self.check('cleanup')['status'], 'transport_key_removed')
        self.assertFalse(self.files.exists(subject.KEY))
        self.assertFalse(self.files.exists(subject.KEY + '.pub'))
        self.assertTrue(self.files.exists('transfer-receipt.json'))
        self.assertEqual(self.check('cleanup')['status'], 'already_closed')
        self.refuse('send', 'session_closed')
        self.refuse('prepare', 'session_exists')
        for (path, _), body in zip(subject.ORIGINALS, self.bodies):
            self.assertEqual(self.local(path).read_bytes(), body)
        names = {path.name for path in self.local(subject.DIRECTORY).rglob('*')}
        self.assertFalse({'secret.key', '.env', 'keys.tar'} & names)

    def test_both_original_descriptors_open_before_first_body_read(self):
        original_open, original_read = os.open, os.read
        originals = set()
        def opened(path, *args, **kwargs):
            fd = original_open(path, *args, **kwargs)
            if path in ('secret.key', '.env'):
                originals.add(fd)
            return fd
        def read(fd, count):
            if fd in originals:
                self.assertEqual(len(originals), 2)
            return original_read(fd, count)
        with mock.patch.object(subject.os, 'open', side_effect=opened), mock.patch.object(subject.os, 'read', side_effect=read):
            subject.source_archive(self.files)

    def test_combined_limit_checked_before_any_body_read(self):
        for path, _ in subject.ORIGINALS:
            self.local(path).write_bytes(b'x' * (subject.MAX_SOURCE // 2 + 1))
        with mock.patch.object(subject.os, 'read', side_effect=AssertionError('Body must not be read')):
            with self.assertRaises(subject.Refused) as caught:
                subject.source_archive(self.files)
        self.assertEqual(caught.exception.code, 'source_invalid')

    def test_exact_combined_limit_succeeds(self):
        for path, _ in subject.ORIGINALS:
            self.local(path).write_bytes(b'x' * (subject.MAX_SOURCE // 2))
        data, size = subject.source_archive(self.files)
        self.assertEqual(size, subject.MAX_SOURCE)
        self.assertLessEqual(len(data), subject.MAX_ARCHIVE)

    def test_empty_original_is_rejected(self):
        self.local(subject.ORIGINALS[0][0]).write_bytes(b'')
        self.refuse('prepare', 'source_invalid')

    def test_symlink_leaf_is_never_followed(self):
        first, second = [self.local(item[0]) for item in subject.ORIGINALS]
        first.unlink()
        first.symlink_to(second)
        self.refuse('prepare', 'unsafe_path')

    def test_hardlinked_leaf_is_rejected(self):
        os.link(self.local(subject.ORIGINALS[0][0]), self.local('/second-link'))
        self.refuse('prepare', 'unsafe_path')

    def test_fifo_leaf_is_rejected_without_open(self):
        first = self.local(subject.ORIGINALS[0][0])
        first.unlink()
        os.mkfifo(first)
        self.refuse('prepare', 'unsafe_path')

    def test_group_writable_leaf_is_rejected(self):
        self.local(subject.ORIGINALS[0][0]).chmod(0o620)
        self.refuse('prepare', 'unsafe_path')

    def test_wrong_owner_is_rejected(self):
        self.files.owner = os.getuid() + 1
        self.refuse('prepare', 'unsafe_path')

    def test_symlink_and_writable_parent_are_rejected(self):
        parent = self.local(subject.ORIGINALS[0][0]).parent
        old = parent.with_name('old-data')
        parent.rename(old)
        parent.symlink_to(old, target_is_directory=True)
        with self.assertRaises(subject.Refused):
            subject.source_archive(self.files)
        parent.unlink()
        old.rename(parent)
        parent.chmod(0o770)
        with self.assertRaises(subject.Refused):
            subject.source_archive(self.files)

    def mutate_during_read(self, mutation):
        original_read, done = os.read, [False]
        def read(fd, count):
            block = original_read(fd, count)
            if block and not done[0]:
                done[0] = True
                mutation()
            return block
        with mock.patch.object(subject.os, 'read', side_effect=read):
            with self.assertRaises(subject.Refused) as caught:
                subject.source_archive(self.files)
        self.assertIn(caught.exception.code, ('source_changed', 'path_changed'))

    def test_same_size_content_mutation_is_rejected(self):
        first = self.local(subject.ORIGINALS[0][0])
        self.mutate_during_read(lambda: first.write_bytes(b'x' * len(self.bodies[0])))

    def test_first_original_replacement_after_read_is_rejected(self):
        first = self.local(subject.ORIGINALS[0][0])
        def replace():
            first.rename(first.with_name('old-key'))
            first.write_bytes(self.bodies[0])
        self.mutate_during_read(replace)

    def test_parent_replacement_after_open_is_rejected(self):
        parent = self.local(subject.ORIGINALS[0][0]).parent
        def replace():
            parent.rename(parent.with_name('old-data'))
            parent.mkdir()
        self.mutate_during_read(replace)

    def test_parent_ctime_change_even_with_same_inode_is_rejected(self):
        parent = self.local(subject.ORIGINALS[0][0]).parent
        self.mutate_during_read(lambda: (parent / 'synthetic-new-entry').write_bytes(b'x'))

    def test_permission_change_after_open_is_rejected(self):
        first = self.local(subject.ORIGINALS[0][0])
        self.mutate_during_read(lambda: first.chmod(0o644))

    def test_original_body_growth_is_rejected(self):
        first = self.local(subject.ORIGINALS[0][0])
        self.mutate_during_read(lambda: first.write_bytes(self.bodies[0] + b'x'))

    def test_transport_arguments_are_fixed_and_do_not_contain_plaintext(self):
        self.check('prepare')
        self.check('send')
        _, gpg, ssh, _ = self.transfers[0]
        self.assertEqual(gpg[-3:], ['--recipient', subject.RECIPIENT, '--encrypt'])
        self.assertIn('--no-autostart', gpg)
        self.assertEqual(ssh[-2:], ['root@139.162.109.181', 'receive-key-capsule-20261102-v1'])
        for option in ('StrictHostKeyChecking=yes', 'IdentitiesOnly=yes', 'ForwardAgent=no',
                       'GlobalKnownHostsFile=/dev/null', 'UpdateHostKeys=no', 'ControlPath=none'):
            self.assertIn(option, ssh)
        self.assertNotIn(CANARY.decode(), repr(self.calls) + repr((gpg, ssh)))
        self.assertFalse(any('docker' in str(call) for call in self.calls))

    def test_low_space_fails_before_keygen(self):
        self.files.free = lambda path: subject.MIN_FREE - 1
        self.refuse('prepare', 'space_insufficient')
        self.assertFalse(self.files.exists(subject.KEY))
        self.check('cleanup')

    def test_failed_send_wipes_plaintext_and_preserves_key_until_cleanup(self):
        self.check('prepare')
        def failed(plain, *args, **kwargs):
            self.plain_refs.append(plain)
            raise subject.Refused('pipeline_failed')
        self.source.transfer = failed
        self.refuse('send', 'pipeline_failed')
        self.assertEqual(set(self.plain_refs[0]), {0})
        self.assertTrue(self.files.exists(subject.KEY))
        self.assertTrue(self.files.exists('failure-receipt.json'))
        self.check('cleanup')

    def test_unreaped_attempt_cannot_be_retried_or_promoted_to_terminal(self):
        self.check('prepare')
        self.source.transfer = mock.Mock(side_effect=subject.Unfinished())
        self.refuse('send', 'attempt_not_terminal')
        self.refuse('send', 'attempt_exists')
        self.assertFalse(self.files.exists('failure-receipt.json'))
        self.refuse('cleanup', 'attempt_not_terminal')
        self.assertTrue(self.files.exists(subject.KEY))

    def test_completed_send_cannot_repeat(self):
        self.check('prepare')
        self.check('send')
        self.refuse('send', 'attempt_exists')
        self.assertEqual(len(self.transfers), 1)

    def test_concurrent_phase_lock_and_session_permissions(self):
        self.check('prepare')
        with self.files.lock():
            self.refuse('cleanup', 'lock_busy')
        self.local(subject.DIRECTORY).chmod(0o755)
        self.refuse('cleanup', 'unsafe_path')

    def test_public_asset_mutation_refuses_before_original_body_read(self):
        self.local('/assets/' + subject.PUBLIC_ASSET).write_bytes(CANARY)
        self.refuse('prepare', 'asset_invalid')
        self.assertFalse(self.files.exists(subject.KEY))

    def test_total_phase_budget_is_passed_to_transfer(self):
        self.check('prepare')
        now, original_run = [1000], self.command
        def run(argv, **kwargs):
            now[0] += 5
            return original_run(argv, **kwargs)
        self.source.runner = run
        with mock.patch.object(subject.time, 'monotonic', side_effect=lambda: now[0]):
            self.check('send')
        self.assertEqual(self.transfers[0][3]['timeout'], subject.DEADLINE - 5)


def python(code):
    return [sys.executable, '-I', '-B', '-c', code]


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.plain = bytearray(CANARY * 2500)
        self.encryptor = python('import sys;d=sys.stdin.buffer.read();sys.stdout.buffer.write(bytes(x^91 for x in d))')
        self.receiver = python('import sys,json,hashlib;d=sys.stdin.buffer.read();print(json.dumps({"status":"received_unverified","bytes":len(d),"sha256":hashlib.sha256(d).hexdigest()}))')

    def run_pipe(self, gpg=None, ssh=None, **kwargs):
        return subject.stream_capsule(self.plain, gpg or self.encryptor, ssh or self.receiver, **kwargs)

    def test_encrypted_bytes_hash_and_two_exit_codes_match(self):
        result = self.run_pipe()
        cipher = bytes(x ^ 91 for x in self.plain)
        self.assertEqual(result, {'bytes': len(cipher), 'sha256': hashlib.sha256(cipher).hexdigest(),
                                 'process_rc': {'gpg': 0, 'ssh': 0}})

    def test_both_plaintext_and_ciphertext_partial_writes_are_complete(self):
        self.plain = bytearray(CANARY * 20)
        original_write = os.write
        with mock.patch.object(subject.os, 'write', side_effect=lambda fd, data: original_write(fd, data[:17])):
            result = self.run_pipe()
        self.assertEqual(result['sha256'], hashlib.sha256(bytes(x ^ 91 for x in self.plain)).hexdigest())

    def test_gpg_or_ssh_nonzero_never_reports_transfer_success(self):
        for overrides in ({'gpg': python('import sys;sys.stdin.buffer.read();sys.stdout.write("cipher");sys.exit(7)')},
                          {'ssh': python('import sys;sys.stdin.buffer.read();sys.exit(8)')}):
            with self.assertRaises(subject.Refused) as caught:
                self.run_pipe(**overrides)
            self.assertIn(caught.exception.code, ('pipeline_failed', 'pipe_failed'))

    def test_early_gpg_or_ssh_exit_fails_without_hanging(self):
        for overrides in ({'gpg': python('raise SystemExit(7)')}, {'ssh': python('raise SystemExit(8)')}):
            processes, popen = [], subprocess.Popen
            def spawn(*args, **kwargs):
                process = popen(*args, **kwargs)
                processes.append(process)
                return process
            with mock.patch.object(subject.subprocess, 'Popen', side_effect=spawn):
                with self.assertRaises(subject.Refused) as caught:
                    self.run_pipe(**overrides, timeout=2)
            self.assertIn(caught.exception.code, ('pipeline_failed', 'pipe_failed', 'attempt_not_terminal'))
            self.assertTrue(all(process.poll() is not None for process in processes))
            self.assertTrue(all(stream.closed for process in processes
                                for stream in (process.stdin, process.stdout, process.stderr)))

    def test_cipher_size_limit(self):
        with self.assertRaises(subject.Refused) as caught:
            self.run_pipe(max_cipher=8)
        self.assertEqual(caught.exception.code, 'cipher_limit')

    def test_stderr_limit_and_canary_not_exposed(self):
        gpg = python('import sys;sys.stderr.write(' + repr(CANARY.decode()) + '*4000);sys.stdin.buffer.read()')
        with self.assertRaises(subject.Refused) as caught:
            self.run_pipe(gpg=gpg)
        self.assertEqual(caught.exception.code, 'command_limit')
        self.assertNotIn(CANARY.decode(), str(caught.exception))

    def test_deadline_reaps_processes(self):
        start = time.monotonic()
        with self.assertRaises(subject.Refused) as caught:
            self.run_pipe(gpg=python('import time;time.sleep(20)'), timeout=.1)
        self.assertEqual(caught.exception.code, 'deadline_exceeded')
        self.assertLess(time.monotonic() - start, 4)

    def test_bad_or_duplicate_receipt_is_refused(self):
        for raw in ('{"bytes":1,"bytes":2}', '{"status":"verified"}', '{}\n{}', 'x' * 1100):
            ssh = python('import sys;sys.stdin.buffer.read();print(' + repr(raw) + ')')
            with self.assertRaises(subject.Refused) as caught:
                self.run_pipe(ssh=ssh)
            self.assertEqual(caught.exception.code, 'receipt_invalid')

    def test_failed_second_spawn_reaps_first_child(self):
        processes, popen = [], subprocess.Popen
        def spawn(*args, **kwargs):
            if processes:
                raise OSError(CANARY.decode())
            process = popen(*args, **kwargs)
            processes.append(process)
            return process
        with mock.patch.object(subject.subprocess, 'Popen', side_effect=spawn):
            with self.assertRaises((OSError, subject.Refused)):
                self.run_pipe()
        self.assertTrue(all(process.poll() is not None for process in processes))
        self.assertTrue(all(stream.closed for process in processes
                            for stream in (process.stdin, process.stdout, process.stderr)))


class PolicyTests(unittest.TestCase):
    def test_observed_owner_exception_is_exact_source_parent_only(self):
        info = SimpleNamespace(st_uid=501, st_gid=50, st_mode=stat.S_IFDIR | 0o755)
        self.assertTrue(subject.parent_allowed(info, '/root/ad-dashboard-deploy', 0, True))
        self.assertFalse(subject.parent_allowed(info, '/root/ad-dashboard-deploy', 0, False))
        for path in ('/root', '/root/content-studio-deploy', subject.DIRECTORY, '/tmp',
                     '/root/ad-dashboard-deploy/data'):
            self.assertFalse(subject.parent_allowed(info, path, 0, True))
        for name, bad in (('st_uid', 502), ('st_gid', 51), ('st_mode', stat.S_IFDIR | 0o775)):
            modified = SimpleNamespace(**vars(info))
            setattr(modified, name, bad)
            self.assertFalse(subject.parent_allowed(modified, '/root/ad-dashboard-deploy', 0, True))

    def test_original_parent_does_not_accept_arbitrary_paths(self):
        with self.assertRaises(subject.Refused):
            with subject.Files().original_parent('/root/arbitrary'):
                self.fail('Arbitrary original path accepted')

    def test_termination_error_still_waits_for_all_children(self):
        first, second = mock.Mock(), mock.Mock()
        first.pid, second.pid = 12345, 23456
        first.poll.return_value = None
        second.poll.return_value = None
        with mock.patch.object(subject.os, 'killpg', side_effect=PermissionError()):
            with self.assertRaises(subject.Unfinished):
                subject.terminate([first, second])
        first.wait.assert_called()
        second.wait.assert_called()

    def test_already_reaped_group_permission_race_is_not_active_writer(self):
        process = mock.Mock()
        process.pid, process.poll.side_effect = 12345, [None, 0]
        with mock.patch.object(subject.os, 'killpg', side_effect=PermissionError()):
            subject.terminate([process])
        process.wait.assert_called()

    @unittest.skipUnless(shutil.which('gpg'), 'Public-only GPG integration needs gpg')
    def test_actual_public_only_gpg_to_synthetic_receiver(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'gpg'
            home.mkdir(mode=0o700)
            argv = [shutil.which('gpg'), '--no-options', '--homedir', str(home), '--batch', '--no-tty',
                    '--no-autostart', '--no-auto-key-retrieve', '--auto-key-locate', 'clear']
            imported = subprocess.run(argv + ['--import', str(PATH.parent / 'preservation' / subject.PUBLIC_ASSET)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            self.assertEqual(imported.returncode, 0)
            receiver = python('import sys,json,hashlib;d=sys.stdin.buffer.read();print(json.dumps({"status":"received_unverified","bytes":len(d),"sha256":hashlib.sha256(d).hexdigest()}))')
            result = subject.stream_capsule(bytearray(CANARY), argv + ['--trust-model', 'always',
                '--compress-algo', 'none', '--cipher-algo', 'AES256', '--recipient', subject.RECIPIENT, '--encrypt'], receiver)
            self.assertEqual(result['process_rc'], {'gpg': 0, 'ssh': 0})
            self.assertGreater(result['bytes'], len(CANARY))
            secret = home / 'private-keys-v1.d'
            self.assertFalse(secret.exists() and any(secret.iterdir()))


class EntrypointTests(unittest.TestCase):
    def test_only_phase_input_and_root_are_accepted(self):
        for argv, uid, error in ((['helper', 'send', '/arbitrary'], 0, 'invalid_phase'),
                                (['helper', 'send'], 501, 'root_required')):
            stream = io.StringIO()
            with mock.patch.object(subject.sys, 'argv', argv), mock.patch.object(subject.os, 'geteuid', return_value=uid), \
                    mock.patch.object(subject, 'Capsule') as constructor, contextlib.redirect_stdout(stream):
                code = subject.main()
            self.assertEqual(code, 2)
            constructor.assert_not_called()
            self.assertEqual(json.loads(stream.getvalue())['error'], error)

    def test_core_dumps_disabled_before_capsule_execution(self):
        stream, events = io.StringIO(), []
        def limits(*args):
            events.append('core_disabled')
        instance = mock.Mock()
        def perform(phase):
            self.assertEqual(events, ['core_disabled'])
            result = subject.output(phase)
            result['status'] = 'transport_key_removed'
            return result
        instance.perform = perform
        with mock.patch.object(subject.sys, 'argv', ['helper', 'cleanup']), \
                mock.patch.object(subject.os, 'geteuid', return_value=0), \
                mock.patch.object(subject.os, 'umask'), mock.patch.object(subject.signal, 'signal'), \
                mock.patch.object(subject.resource, 'setrlimit', side_effect=limits), \
                mock.patch.object(subject, 'Capsule', return_value=instance), contextlib.redirect_stdout(stream):
            self.assertEqual(subject.main(), 0)
        self.assertEqual(json.loads(stream.getvalue())['backup_verified'], False)


if __name__ == '__main__':
    unittest.main()
