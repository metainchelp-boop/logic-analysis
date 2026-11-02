"""Synthetic state, fake binaries and fake ciphertext. No real key, GPG, Docker or SSH."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / 'retirement_data_source.py'
SPEC = importlib.util.spec_from_file_location('data_source', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
DIRECTORY = subject.BASE + '/' + subject.SESSION
CANARY = 'PRIVATE_SYNTHETIC_CONTENT_CANARY'
PUBLIC = 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + b'x' * 32).decode()


class SourceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(os.path.realpath(self.temp.name))
        self.files = subject.Files(str(self.root), os.getuid())
        for path in ('/root', '/tmp', '/usr/bin', '/assets'):
            self.local(path).mkdir(parents=True, exist_ok=True)
        for path in subject.BINARIES.values():
            self.local(path).write_text('synthetic executable placeholder')
            self.local(path).chmod(0o755)
        for name in (subject.PUBLIC_ASSET, subject.HOSTS_ASSET):
            self.local('/assets/' + name).write_bytes((PATH.parent / 'preservation' / name).read_bytes())
        self.files.free = lambda path: 64 * 1024 ** 2 + 1
        self.calls, self.transfers = [], []
        self.paused = {'ad': False, 'content': False}
        self.policy = {'request': {'ad': {'id': 'a' * 64, 'pid': 101}, 'content': {'id': 'b' * 64, 'pid': 201}},
                       'files': [{'sha256': 'd' * 64}]}
        self.restart, self.control_files = 'no', self.policy['files']
        self.control = types.SimpleNamespace(collect=self.controls)
        self.modules = {'archive': object(), 'preflight': object(), 'control': self.control}
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(subject, 'load_modules', return_value=self.modules))
        self.stack.enter_context(mock.patch.object(subject, 'CONTROL_POLICY', self.policy))
        self.stack.enter_context(mock.patch.object(subject, 'OPERATOR_EVIDENCE_SHA256', 'c' * 64))
        journal = self.local('/root/.metainc-retirement-control/' + subject.SESSION + '/fence-complete.json')
        journal.parent.mkdir(parents=True)
        journal.write_bytes(b'SYNTHETIC_COMPLETED_FENCE')
        journal.chmod(0o600)
        self.restart_evidence = {'sha256': hashlib.sha256(journal.read_bytes()).hexdigest(),
                                'operator_evidence_sha256': 'c' * 64, 'control_policy_sha256': 'd' * 64}
        self.stack.enter_context(mock.patch.object(subject, 'RESTART_EVIDENCE', self.restart_evidence))
        self.stack.enter_context(mock.patch.dict(os.environ, {'RETIREMENT_RUN': '123-1',
            'RETIREMENT_OPERATOR_EVIDENCE_SHA256': 'c' * 64}))
        self.source = subject.Preservation(self.files, '/assets', self.command, self.transfer)

    def local(self, path):
        return self.root / path.lstrip('/')

    def controls(self, request, **kwargs):
        return {'status': 'observed', 'error': None, 'files': self.control_files,
            'containers': [{'alias': alias, 'pid': request[alias]['pid'], 'paused': self.paused[alias],
                            'restart_policy': self.restart, 'maximum_retry_count': 0} for alias in ('ad', 'content')]}

    def command(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[0] == subject.BINARIES['gpg']:
            if '--list-keys' in argv:
                return ('pub:-:255:22:x:0:0:::::c:\nfpr:::::::::' + subject.RECIPIENT + ':\n').encode()
            if '--import' in argv:
                return b''
        if argv[0] == subject.BINARIES['keygen']:
            self.local(DIRECTORY + '/' + subject.KEY).write_text(CANARY)
            self.local(DIRECTORY + '/' + subject.KEY).chmod(0o600)
            self.local(DIRECTORY + '/' + subject.KEY + '.pub').write_text(PUBLIC + '\n')
            return b''
        if argv[0] == subject.BINARIES['docker'] and argv[-2] == 'pause':
            alias = 'ad' if argv[-1] == 'a' * 64 else 'content'
            self.paused[alias] = True
            self.assertTrue(self.files.exists('attempt.json'))
            return argv[-1].encode() + b'\n'
        raise AssertionError('Unexpected synthetic command')

    def transfer(self, archive, preflight, request, gpg, ssh, **kwargs):
        self.transfers.append((request, gpg, ssh))
        self.assertTrue(all(self.paused.values()))
        self.assertEqual(kwargs['restart_evidence'], self.restart_evidence)
        return {'bytes': 257, 'sha256': 'a' * 64, 'process_rc': {'archive': 0, 'gpg': 0, 'ssh': 0},
                'source_bytes': 351, 'archive_bytes': 4096, 'object_count': 7}

    def test_unreviewed_or_changed_fence_journal_stops_before_any_pause(self):
        self.check('prepare')
        with mock.patch.object(subject, 'RESTART_EVIDENCE', None):
            self.refuse('send', 'policy_unresolved')
        with mock.patch.object(subject, 'RESTART_EVIDENCE', {**self.restart_evidence, 'sha256': 'f' * 64}):
            self.refuse('send', 'controls_changed')
        self.assertFalse(any(self.paused.values()))
        self.assertFalse(self.files.exists('attempt.json'))

    def check(self, phase):
        result = self.source.perform(phase)
        self.assertNotIn(CANARY, json.dumps(result))
        self.assertFalse(result['backup_verified'])
        self.assertEqual(len(result), 15)
        return result

    def refuse(self, phase, code):
        with self.assertRaises(subject.Refused) as caught:
            self.source.perform(phase)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn(CANARY, str(caught.exception))

    def test_lifecycle_keeps_paused_apps_and_only_removes_transport_key(self):
        prepared = self.check('prepare')
        self.assertEqual(prepared['ssh_public_key'], PUBLIC)
        self.assertIsNone(prepared['operator_evidence_sha256'])
        self.assertFalse(any(self.paused.values()))
        sent = self.check('send')
        self.assertEqual(sent['status'], 'transferred_unverified')
        self.assertEqual(sent['paused'], {'ad': 'paused', 'content': 'paused'})
        self.assertEqual(sent['operator_evidence_sha256'], 'c' * 64)
        self.assertEqual(self.check('cleanup')['status'], 'transport_key_removed')
        self.assertEqual(self.check('cleanup')['status'], 'already_closed')
        self.assertTrue(all(self.paused.values()))
        self.assertTrue(self.files.exists('transfer-receipt.json'))
        self.assertFalse(self.files.exists(subject.KEY))
        self.refuse('send', 'session_closed')

    def test_unresolved_policy_and_operator_evidence_stop_before_pause(self):
        self.check('prepare')
        with mock.patch.object(subject, 'CONTROL_POLICY', None): self.refuse('send', 'policy_unresolved')
        with mock.patch.object(subject, 'OPERATOR_EVIDENCE_SHA256', '0' * 64): self.refuse('send', 'operator_evidence_refused')
        self.assertFalse(any(self.paused.values())); self.assertFalse(self.transfers)
        self.assertFalse(self.files.exists('attempt.json'))

    def test_changed_restart_nginx_or_pid_stops_before_pause(self):
        self.check('prepare')
        self.restart = 'always'; self.refuse('send', 'controls_changed'); self.restart = 'no'
        self.control_files = []; self.refuse('send', 'controls_changed')
        self.assertFalse(any(self.paused.values())); self.assertFalse(self.transfers)

    def test_second_pause_failure_leaves_first_paused_and_no_automatic_resume(self):
        self.check('prepare'); original = self.command
        def fail(argv, **kw):
            if argv[-2:] == ['pause', 'b' * 64]: raise subject.Refused('command_failed')
            return original(argv, **kw)
        self.source.runner = fail
        self.refuse('send', 'command_failed')
        self.assertEqual(self.paused, {'ad': True, 'content': False})
        self.assertEqual(self.source.report['paused'], {'ad': 'paused', 'content': 'pause_requested'})
        self.assertTrue(self.files.exists('failure-receipt.json'))
        self.check('cleanup'); self.assertTrue(self.paused['ad'])
        self.assertFalse(self.transfers)

    def test_final_control_change_rejects_even_complete_cipher(self):
        self.check('prepare'); original = self.transfer
        def changed(*args, **kwargs):
            value = original(*args, **kwargs); self.control_files = []; return value
        self.source.transfer = changed
        self.refuse('send', 'controls_changed')
        self.assertFalse(self.files.exists('transfer-receipt.json'))
        self.assertTrue(self.files.exists('failure-receipt.json'))
        self.assertTrue(all(self.paused.values()))

    def test_only_exact_pause_commands_and_strict_encryption_transport(self):
        self.check('prepare'); self.check('send')
        commands = [row for row in self.calls if row[0] == subject.BINARIES['docker']]
        self.assertEqual([row[-2:] for row in commands], [['pause', 'a' * 64], ['pause', 'b' * 64]])
        _, gpg, ssh = self.transfers[0]
        for flag in ('--no-options', '--no-autostart', '--no-auto-key-retrieve', '--encrypt'):
            self.assertIn(flag, gpg)
        self.assertEqual(gpg[gpg.index('--recipient') + 1], subject.RECIPIENT)
        for flag in ('StrictHostKeyChecking=yes', 'IdentitiesOnly=yes', 'ForwardAgent=no', 'ClearAllForwardings=yes'):
            self.assertIn(flag, ssh)
        self.assertEqual(ssh[-2:], ['root@139.162.109.181', subject.COMMAND])
        self.assertNotIn('unpause', PATH.read_text())
        self.assertNotIn("docker('stop'", PATH.read_text())

    def test_unsafe_run_and_no_module_pins_cannot_create_session(self):
        with mock.patch.dict(os.environ, {'RETIREMENT_RUN': CANARY}): self.refuse('prepare', 'operator_evidence_refused')
        with mock.patch.object(subject, 'load_modules', side_effect=subject.Refused('module_refused')):
            self.refuse('prepare', 'module_refused')
        self.assertFalse(self.local(DIRECTORY).exists())

    def test_low_metadata_space_stops_before_key_and_can_close_failed_prepare(self):
        self.files.free = lambda path: 64 * 1024 ** 2 - 1
        self.refuse('prepare', 'space_insufficient')
        self.assertFalse(self.files.exists(subject.KEY))
        self.assertTrue(self.files.exists('failure-receipt.json'))
        self.assertEqual(self.check('cleanup')['status'], 'transport_key_removed')
        self.assertFalse(any(self.paused.values()))

    def test_prepare_refuses_existing_session_without_overwrite(self):
        self.check('prepare')
        before = self.files.json('prepared.json')
        self.refuse('prepare', 'session_exists')
        self.assertEqual(self.files.json('prepared.json'), before)


    def test_source_private_transport_key_is_never_read_by_python(self):
        real_read = self.files.read

        def public_only(path, *args, **kwargs):
            self.assertNotEqual(path, DIRECTORY + '/' + subject.KEY)
            return real_read(path, *args, **kwargs)

        self.files.read = public_only
        self.check('prepare')
        self.check('send')
        self.check('cleanup')


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
        self.files.mkdir(DIRECTORY)
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
        self.local(DIRECTORY).chmod(0o755)
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


    def test_global_lock_symlink_hardlink_and_mode_are_refused(self):
        self.check('prepare')
        lock = self.local(subject.BASE + '/remaining-images.lock')
        lock.rename(lock.with_name('old-lock'))
        lock.symlink_to(lock.with_name('old-lock'))
        with self.assertRaises(OSError):
            with self.files.export_lock():
                self.fail('Symlink lock acquired')
        lock.unlink()
        os.link(lock.with_name('old-lock'), lock)
        with self.assertRaises(subject.Refused):
            with self.files.export_lock():
                self.fail('Hardlink lock acquired')
        lock.with_name('old-lock').unlink()
        lock.chmod(0o640)
        with self.assertRaises(subject.Refused):
            with self.files.export_lock():
                self.fail('Nonprivate lock acquired')


    def test_global_lock_replacement_while_held_is_refused(self):
        self.check('prepare')
        lock = self.local(subject.BASE + '/remaining-images.lock')
        with self.assertRaises(subject.Refused) as caught:
            with self.files.export_lock():
                lock.rename(lock.with_name('old-lock'))
                lock.write_text('')
                lock.chmod(0o600)
        self.assertEqual(caught.exception.code, 'path_changed')



def python(code):
    return [sys.executable, '-I', '-B', '-c', code]


class FakeArchive:
    def __init__(self, body=None, fail=False, delay=0, bad_proof=False, proof_override=None):
        self.body = ((CANARY * 20000).encode() + b"x" * ((-len(CANARY * 20000)) % 512)) if body is None else body
        self.fail, self.delay, self.bad_proof = fail, delay, bad_proof
        self.proof_override = proof_override or {}

    def archive_snapshot(self, preflight, request, fd, **kwargs):
        time.sleep(self.delay)
        print(CANARY)  # Child standard output must be /dev/null.
        pending = memoryview(self.body)
        while pending:
            count = os.write(fd, pending[:65536]); pending = pending[count:]
        if self.fail: raise ValueError(CANARY)
        proof = {'status': 'archive_stream_complete', 'session': subject.SESSION,
            'archive_bytes': len(self.body), 'source_bytes': len(self.body) // 2,
            'object_count': 7, 'application_restore_verified': False}
        if self.bad_proof: proof['status'] = CANARY
        proof.update(self.proof_override)
        return proof


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.data = FakeArchive().body
        self.producer = FakeArchive()
        self.encryptor = python('import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(bytes(x^91 for x in d))')
        self.receiver = python('import sys,json,hashlib; d=sys.stdin.buffer.read(); print(json.dumps({"status":"received_unverified","bytes":len(d),"sha256":hashlib.sha256(d).hexdigest()}))')

    def invoke(self, producer=None, encryptor=None, receiver=None, **kwargs):
        return subject.stream_archive(producer or self.producer, types.SimpleNamespace(Docker=lambda end, runner: None), {}, encryptor or self.encryptor,
                                      receiver or self.receiver, **kwargs)

    def test_cipher_backpressure_hash_and_all_three_rc_plus_archive_proof(self):
        result = self.invoke()
        cipher = bytes(x ^ 91 for x in self.data)
        self.assertEqual(result, {'bytes': len(cipher), 'sha256': hashlib.sha256(cipher).hexdigest(),
            'process_rc': {'archive': 0, 'gpg': 0, 'ssh': 0}, 'source_bytes': len(self.data) // 2,
            'archive_bytes': len(self.data), 'object_count': 7})

    def test_partial_writes_in_plaintext_control_and_cipher_pipes_are_complete(self):
        real_write = os.write
        with mock.patch.object(subject.os, 'write', side_effect=lambda fd, data: real_write(fd, data[:17])):
            result = self.invoke(producer=FakeArchive(b'x' * 4096))
        self.assertEqual(result['bytes'], 4096)
        self.assertEqual(result['sha256'], hashlib.sha256(bytes([ord('x') ^ 91]) * 4096).hexdigest())

    def test_each_process_failure_and_invalid_control_proof_prevent_success(self):
        choices = [dict(producer=FakeArchive(fail=True)), dict(producer=FakeArchive(bad_proof=True)),
            dict(encryptor=python('import sys;sys.stdin.buffer.read();sys.stdout.buffer.write(b"cipher");sys.exit(8)')),
            dict(receiver=python('import sys;sys.stdin.buffer.read();sys.exit(9)'))]
        for override in choices:
            with self.subTest(case=list(override)), self.assertRaises(subject.Refused) as caught:
                self.invoke(**override)
            self.assertIn(caught.exception.code, ('pipeline_failed', 'pipe_failed', 'archive_failed'))
            self.assertNotIn(CANARY, str(caught.exception))

    def test_zero_counts_and_inconsistent_archive_proof_are_refused(self):
        for update in ({'source_bytes': 0}, {'object_count': 0}, {'archive_bytes': 1025},
                       {'archive_bytes': 1024, 'source_bytes': 1025}):
            with self.subTest(update=update), self.assertRaises(subject.Refused) as caught:
                self.invoke(producer=FakeArchive(body=b'x' * 4096, proof_override=update))
            self.assertEqual(caught.exception.code, 'archive_failed')

    def test_timeout_reaps_archive_and_all_other_children_and_closes_control(self):
        processes = []; original = subject.start_archive
        def capture(*args):
            value = original(*args); processes.append(value); return value
        with mock.patch.object(subject, 'start_archive', capture), self.assertRaises(subject.Refused) as caught:
            self.invoke(producer=FakeArchive(delay=20), timeout=.1)
        self.assertEqual(caught.exception.code, 'deadline_exceeded')
        self.assertIsNotNone(processes[0].poll())
        self.assertTrue(processes[0].control.closed)
        self.assertTrue(processes[0].stdout.closed)

    def test_encryptor_stderr_is_bounded_without_secret_output(self):
        with self.assertRaises(subject.Refused) as caught:
            self.invoke(encryptor=python('import sys;sys.stderr.write(' + repr(CANARY) + '*4000)'))
        self.assertEqual(caught.exception.code, 'command_limit')
        self.assertNotIn(CANARY, str(caught.exception))

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



class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve(); self.root.joinpath('assets').mkdir()
        self.files = subject.Files(str(self.root), os.getuid())
        bodies = {'archive': b"SESSION='data-snapshot-20261102-v1'\nMAX_ARCHIVE=2283523072\nMAX_BYTES=2147483648\n",
                  'preflight': b'CHECKED=True\n', 'control': b'CHECKED=True\n'}
        self.pins = {}
        for alias, body in bodies.items():
            name = 'retirement_data_' + alias + '.py'
            target = self.root / 'assets' / name; target.write_bytes(body); target.chmod(0o600)
            self.pins[alias] = (name, hashlib.sha256(body).hexdigest())

    def load(self):
        with mock.patch.object(subject, 'MODULES', self.pins):
            return subject.load_modules('/assets', self.files)

    def test_same_checked_bytes_are_compiled_without_sys_path_imports(self):
        loaded = self.load()
        self.assertTrue(loaded['preflight'].CHECKED)
        self.assertEqual(loaded['archive'].MAX_ARCHIVE, subject.MAX_ARCHIVE)

    def test_changed_bytes_links_wrong_mode_and_placeholder_never_execute(self):
        target = self.root / 'assets' / self.pins['preflight'][0]
        original = target.read_bytes()
        for scenario in ('bytes', 'symlink', 'hardlink', 'mode', 'placeholder'):
            if scenario == 'bytes': target.write_bytes(b'raise RuntimeError("SHOULD_NOT_EXECUTE")')
            elif scenario == 'symlink':
                target.unlink(); target.symlink_to(self.root / 'assets' / self.pins['control'][0])
            elif scenario == 'hardlink': os.link(target, self.root / 'extra')
            elif scenario == 'mode': target.chmod(0o666)
            else: self.pins['preflight'] = (target.name, '0' * 64)
            with self.subTest(case=scenario), self.assertRaises(subject.Refused): self.load()
            if scenario == 'hardlink': self.root.joinpath('extra').unlink()
            if target.is_symlink(): target.unlink()
            target.write_bytes(original); target.chmod(0o600)

    def test_loaded_archive_wrong_bounds_are_refused(self):
        name, _ = self.pins['archive']; target = self.root / 'assets' / name
        body = target.read_bytes().replace(b'2283523072', b'9999999999'); target.write_bytes(body)
        self.pins['archive'] = (name, hashlib.sha256(body).hexdigest())
        with self.assertRaises(subject.Refused) as caught: self.load()
        self.assertEqual(caught.exception.code, 'module_refused')


class EntrypointTest(unittest.TestCase):
    def test_cli_has_only_phase_no_paths_or_ids_and_no_private_errors(self):
        for args, uid, code in ((['source', 'prepare', '/etc/shadow'], 0, 'invalid_phase'),
                               (['source', 'send'], 104729, 'root_required')):
            output = io.StringIO()
            with mock.patch.object(sys, 'argv', args), mock.patch.object(os, 'geteuid', return_value=uid), \
                    mock.patch.object(subject, 'Preservation') as construct, contextlib.redirect_stdout(output):
                self.assertEqual(subject.main(), 2)
            construct.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())['error'], code)

class SpawnSignalTest(unittest.TestCase):
    def test_registration_precedes_every_deferred_signal_and_restores_handlers(self):
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            before={sig:signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP)}
            owned=[]; child=object()
            def factory(previous,pending):
                signal.getsignal(number)(number,None)
                return child
            with self.subTest(signal=number), self.assertRaises(subject.Refused) as caught:
                subject.spawn_registered(factory,owned)
            self.assertEqual(caught.exception.code,'interrupted')
            self.assertEqual(owned,[child])
            self.assertEqual({sig:signal.getsignal(sig) for sig in before},before)

    def test_command_signal_after_spawn_reaps_the_registered_child(self):
        original=subprocess.Popen; children=[]
        def spawn(*args,**kwargs):
            child=original(*args,**kwargs);children.append(child)
            signal.getsignal(signal.SIGINT)(signal.SIGINT,None)
            return child
        with mock.patch.object(subject.subprocess,'Popen',side_effect=spawn), self.assertRaises(subject.Refused) as caught:
            subject.command(python('import time;time.sleep(20)'))
        self.assertEqual(caught.exception.code,'interrupted')
        self.assertIsNotNone(children[0].poll())
        self.assertTrue(children[0].stdout.closed and children[0].stderr.closed)

    def test_fork_encryptor_and_ssh_spawn_return_signals_are_all_reaped(self):
        for at in ('fork','gpg','ssh'):
            fixture=PipelineTest();fixture.setUp()
            real_fork=subject.start_archive;real_popen=subprocess.Popen;children=[];count=[0]
            def fork(*args):
                child=real_fork(*args);children.append(child)
                if at=='fork':signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
                return child
            def popen(*args,**kwargs):
                child=real_popen(*args,**kwargs);children.append(child);count[0]+=1
                if (at=='gpg' and count[0]==1) or (at=='ssh' and count[0]==2):
                    signal.getsignal(signal.SIGHUP)(signal.SIGHUP,None)
                return child
            with self.subTest(at=at), mock.patch.object(subject,'start_archive',side_effect=fork), \
                    mock.patch.object(subject.subprocess,'Popen',side_effect=popen), self.assertRaises(subject.Refused) as caught:
                fixture.invoke()
            self.assertEqual(caught.exception.code,'interrupted')
            for child in children:
                self.assertIsNotNone(child.poll())
                for name in ('stdin','stdout','stderr','control'):
                    stream=getattr(child,name,None)
                    if stream is not None:self.assertTrue(stream.closed)

    def test_fork_child_restores_original_signal_handlers(self):
        class HandlerArchive(FakeArchive):
            def archive_snapshot(self,*args,**kwargs):
                for number in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
                    if signal.getsignal(number) is not subject.interrupted:raise ValueError('defer inherited')
                return super().archive_snapshot(*args,**kwargs)
        old=subject.replace_handlers(subject.interrupted)
        try:
            fixture=PipelineTest();fixture.setUp()
            self.assertEqual(fixture.invoke(producer=HandlerArchive())['process_rc']['archive'],0)
        finally:subject.restore_handlers(old)
