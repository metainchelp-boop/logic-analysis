"""Private synthetic files and subprocesses only; no SSH or administrator keys."""
import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / 'naver_archive_receiver_operator.py'
SPEC = importlib.util.spec_from_file_location('receiver_operator_tested', PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
CANARY = b'SYNTHETIC_ADMIN_KEY_BYTES_MUST_NEVER_BE_READ_OR_SENT'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def key(byte):
    raw = b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes([byte]) * 32
    return 'ssh-ed25519 ' + base64.b64encode(raw).decode()


def child(code):
    return [sys.executable, '-I', '-B', '-c', code]


class OperatorFixture(unittest.TestCase):
    def setUp(self):
        # A real private ancestor chain works on Linux too; /tmp is intentionally
        # rejected by LocalFiles and must not be patched into acceptance.
        tmp = tempfile.TemporaryDirectory(prefix='.operator-fixture-', dir=Path(__file__).parent)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.root.chmod(0o700)
        self.directory = self.root / 'bundle'
        self.directory.mkdir(mode=0o700)
        (self.directory / 'preservation').mkdir(mode=0o700)
        self.controller = PATH.with_name('naver_archive_receiver_control.py').read_bytes()
        self.receiver = PATH.with_name('naver_archive_receiver.py').read_bytes()
        self.known = b'192.0.2.200 ssh-ed25519 SYNTHETIC_PINNED_HOST_PUBLIC_KEY\n'
        for name, raw in (('naver_archive_receiver_control.py', self.controller),
                          ('naver_archive_receiver.py', self.receiver),
                          ('preservation/server-b-known-hosts', self.known)):
            self.write(self.directory / name, raw, 0o644)
        self.ns = {'__name__': 'synthetic_pinned_controller'}
        exec(compile(self.controller, '<synthetic-public-controller>', 'exec'), self.ns)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        for name, raw in (('CONTROLLER_SHA256', self.controller), ('RECEIVER_SHA256', self.receiver),
                          ('KNOWN_HOSTS_SHA256', self.known)):
            self.patches.enter_context(mock.patch.object(subject, name, subject.digest(raw)))
        self.args = types.SimpleNamespace(action='install', admin_key=self.root / 'admin-key',
            output=self.root / 'receipt.json', send_public_key=self.root / 'send.pub',
            fetch_public_key=self.root / 'fetch.pub', source_ip='192.0.2.1', fetch_ip='198.51.100.2')
        self.write(self.args.admin_key, CANARY)
        self.write(self.args.send_public_key, (key(11) + ' send-fixture\n').encode(), 0o644)
        self.write(self.args.fetch_public_key, (key(12) + ' fetch-fixture\n').encode(), 0o644)
        self.result = self.installed()
        self.calls = []

    def write(self, path, raw, mode=0o600):
        path.write_bytes(raw)
        path.chmod(mode)

    def installed(self):
        def row(inode, directory=False, sha='a' * 64):
            result = dict(device=1, inode=inode, uid=0, gid=0,
                          mode=0o700 if directory else 0o600, links=1, bytes=100)
            if not directory:
                result['sha256'] = sha
            return result
        answer = self.ns['empty_result']('install')
        answer.update(status='installed', error=None, expires_at='20261106113000Z',
            source_ip=self.args.source_ip, fetch_ip=self.args.fetch_ip,
            send_key_sha256=subject.digest(key(11).encode()), fetch_key_sha256=subject.digest(key(12).encode()),
            primary=row(1), primary_unchanged=True, secondary=row(2), secondary_published=True,
            pending=row(2), tool_directory=row(3, True), data_directory=row(4, True),
            receiver=row(5, sha=subject.digest(self.receiver)))
        return self.ns['validate_result'](answer)

    def remote(self, argv, request):
        self.calls.append((argv, request))
        return (2 if self.result['status'] == 'failed' else 0), copy.deepcopy(self.result)

    def run_operator(self, **kwargs):
        return subject.run(self.args, remote=kwargs.pop('remote', self.remote), directory=self.directory, **kwargs)

    def revoke(self):
        self.args.action = 'revoke'
        self.args.installed = self.root / 'installed.json'
        self.write(self.args.installed, canonical(self.result))
        self.args.receipt_sha256 = subject.digest(canonical(self.result))
        self.result = dict(self.result, action='revoke', status='revoked')

    def test_install_uses_pinned_bundle_closed_request_and_bound_private_receipt(self):
        result = self.run_operator()
        self.assertEqual(result['status'], 'installed')
        argv, request = self.calls[0]
        self.assertEqual(self.ns['validate_request'](request), self.receiver)
        self.assertEqual(request['send_public_key'], key(11))
        self.assertEqual(request['fetch_public_key'], key(12))
        self.assertEqual(base64.b64decode(request['receiver_b64']), self.receiver)
        self.assertNotIn(CANARY.decode(), json.dumps(request))
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)
        self.assertEqual(result['receipt_sha256'], subject.digest(self.args.output.read_bytes()))
        self.assertEqual(stat.S_IMODE(self.args.output.stat().st_mode), 0o600)
        self.assertEqual(self.args.admin_key.read_bytes(), CANARY)
        self.assertEqual(argv[-2], subject.SERVER)

    def test_admin_key_is_only_statted_never_opened_or_read(self):
        actual_open = subject.os.open
        def opened(path, *args, **kwargs):
            self.assertNotEqual(path, self.args.admin_key.name)
            self.assertNotEqual(path, self.args.admin_key)
            return actual_open(path, *args, **kwargs)
        with mock.patch.object(subject.os, 'open', side_effect=opened):
            self.run_operator()
        self.assertNotIn(CANARY.decode(), json.dumps(self.calls))

    def test_each_bundle_hash_mismatch_refuses_before_remote_or_output(self):
        for name in ('CONTROLLER_SHA256', 'RECEIVER_SHA256', 'KNOWN_HOSTS_SHA256'):
            with self.subTest(name=name), mock.patch.object(subject, name, '0' * 64):
                with self.assertRaisesRegex(subject.Refused, 'bundle_refused'):
                    self.run_operator()
                self.assertEqual(self.calls, [])
                self.assertFalse(self.args.output.exists())

    def test_controller_receiver_constant_mismatch_blocks_execution(self):
        altered = self.controller.replace(subject.digest(self.receiver).encode(), b'0' * 64)
        self.write(self.directory / 'naver_archive_receiver_control.py', altered, 0o644)
        with mock.patch.object(subject, 'CONTROLLER_SHA256', subject.digest(altered)):
            with self.assertRaisesRegex(subject.Refused, 'bundle_refused'):
                self.run_operator()
        self.assertEqual(self.calls, [])

    def test_bad_public_key_ip_and_reused_key_refuse_before_remote(self):
        original = self.args.send_public_key.read_bytes()
        for change in ('bad-key', 'same-key', 'bad-ip'):
            with self.subTest(change=change):
                if change == 'bad-key':
                    self.write(self.args.send_public_key, b'not-a-key\n')
                elif change == 'same-key':
                    self.write(self.args.send_public_key, key(12).encode())
                else:
                    self.write(self.args.send_public_key, original)
                    self.args.source_ip = '192.0.2.1; arbitrary-command'
                with self.assertRaises(Exception):
                    self.run_operator()
                self.assertEqual(self.calls, [])
                self.assertFalse(self.args.output.exists())

    def test_output_exists_blocks_remote_and_preserves_contents(self):
        self.write(self.args.output, b'previous-attempt-evidence')
        with self.assertRaisesRegex(subject.Refused, 'output_exists'):
            self.run_operator()
        self.assertEqual(self.args.output.read_bytes(), b'previous-attempt-evidence')
        self.assertEqual(self.calls, [])

    def test_output_is_reserved_before_remote_and_kept_after_exchange_failure(self):
        def failed(argv, request):
            self.assertTrue(self.args.output.exists())
            self.assertEqual(self.args.output.read_bytes(), b'')
            raise subject.Refused('remote_unknown')
        with self.assertRaisesRegex(subject.Refused, 'remote_unknown'):
            self.run_operator(remote=failed)
        self.assertTrue(self.args.output.exists())
        self.assertEqual(self.args.output.read_bytes(), b'')

    def test_valid_failed_receipt_is_saved_with_status_not_success(self):
        self.result = self.ns['empty_result']('install')
        self.result['error'] = 'space_insufficient'
        result = self.run_operator()
        self.assertEqual((result['status'], result['error']), ('failed', 'space_insufficient'))
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)

    def test_failed_published_install_keeps_exact_revocation_proof(self):
        self.result.update(status='failed', error='write_verify_failed')
        result = self.run_operator()
        self.assertEqual(result['status'], 'failed')
        saved = json.loads(self.args.output.read_bytes())
        self.assertTrue(saved['secondary_published'])
        self.assertEqual(self.ns['validate_request']({'action': 'revoke', 'installed': saved}), None)

    def test_failed_install_with_mismatched_populated_binding_is_refused(self):
        self.result.update(status='failed', error='write_verify_failed', source_ip='192.0.2.99')
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_operator()
        self.assertEqual(self.args.output.read_bytes(), b'')

    def test_receipt_unknown_fields_and_wrong_action_never_publish(self):
        for wrong in (dict(self.result, unexpected='forbidden'), dict(self.result, action='revoke', status='revoked')):
            with self.subTest(extra='unexpected' in wrong):
                with self.assertRaises(Exception):
                    self.run_operator(remote=lambda argv, request: (0, wrong))
                self.assertEqual(self.args.output.read_bytes(), b'')
                self.args.output.unlink()

    def test_install_receipt_binding_mismatch_retains_empty_output(self):
        for field, wrong in (('source_ip', '192.0.2.3'), ('fetch_ip', '198.51.100.4'),
                             ('send_key_sha256', 'c' * 64), ('fetch_key_sha256', 'd' * 64)):
            with self.subTest(field=field):
                self.result = dict(self.installed(), **{field: wrong})
                with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
                    self.run_operator()
                self.assertEqual(self.args.output.read_bytes(), b'')
                self.args.output.unlink()

    def test_remote_rc_disagrees_with_success_receipt_is_refused(self):
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_operator(remote=lambda argv, request: (2, self.result))
        self.assertEqual(self.args.output.read_bytes(), b'')

    def test_admin_key_metadata_change_after_remote_preserves_valid_revoke_evidence(self):
        def changed(argv, request):
            self.write(self.args.admin_key, b'SYNTHETIC_CHANGED_KEY')
            return 0, self.result
        with self.assertRaisesRegex(subject.Refused, 'path_changed'):
            self.run_operator(remote=changed)
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)

    def test_output_name_replacement_preserves_both_files(self):
        detached = self.root / 'detached-output'
        def changed(argv, request):
            self.args.output.rename(detached)
            self.write(self.args.output, b'replacement-must-remain')
            return 0, self.result
        with self.assertRaisesRegex(subject.Refused, 'path_changed'):
            self.run_operator(remote=changed)
        self.assertEqual(self.args.output.read_bytes(), b'replacement-must-remain')
        self.assertEqual(detached.read_bytes(), b'')

    def test_revoke_requires_installed_raw_hash_and_valid_install_proof(self):
        self.revoke()
        self.args.receipt_sha256 = '0' * 64
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_operator()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.args.output.exists())

    def test_revoke_exact_proof_and_result_are_bound(self):
        self.revoke()
        expected = json.loads(self.args.installed.read_bytes())
        result = self.run_operator()
        self.assertEqual(result['status'], 'revoked')
        self.assertEqual(self.calls[0][1], {'action': 'revoke', 'installed': expected})

    def test_stale_revoke_receipt_cannot_claim_other_installed_authorization(self):
        self.revoke()
        self.result['secondary'] = dict(self.result['secondary'], sha256='d' * 64)
        self.result['pending'] = dict(self.result['secondary'])
        self.ns['validate_result'](self.result)
        with self.assertRaisesRegex(subject.Refused, 'receipt_refused'):
            self.run_operator()
        self.assertEqual(self.args.output.read_bytes(), b'')

    def test_private_admin_permissions_and_symlink_are_refused(self):
        self.args.admin_key.chmod(0o644)
        with self.assertRaisesRegex(subject.Refused, 'file_refused'):
            self.run_operator()
        self.args.admin_key.chmod(0o600)
        real = self.root / 'actual-key'
        self.args.admin_key.rename(real)
        self.args.admin_key.symlink_to(real)
        with self.assertRaisesRegex(subject.Refused, 'file_refused'):
            self.run_operator()
        self.assertEqual(self.calls, [])

    def test_untrusted_public_asset_hardlink_or_writable_mode_is_refused(self):
        self.args.send_public_key.chmod(0o666)
        with self.assertRaisesRegex(subject.Refused, 'file_refused'):
            self.run_operator()
        self.args.send_public_key.chmod(0o644)
        os.link(self.args.send_public_key, self.root / 'alias.pub')
        with self.assertRaisesRegex(subject.Refused, 'file_refused'):
            self.run_operator()
        self.assertEqual(self.calls, [])

    def test_output_directory_must_be_private(self):
        self.root.chmod(0o755)
        with self.assertRaisesRegex(subject.Refused, 'path_refused'):
            self.run_operator()
        self.assertFalse(self.args.output.exists())

    def test_input_path_replacement_while_reading_is_refused(self):
        files = subject.LocalFiles()
        original_read = os.read
        target = self.args.send_public_key
        changed = False
        def swapped(fd, size):
            nonlocal changed
            data = original_read(fd, size)
            if not changed and data:
                changed = True
                target.rename(self.root / 'old-public-key')
                self.write(target, key(12).encode())
            return data
        with mock.patch.object(subject.os, 'read', side_effect=swapped):
            with self.assertRaisesRegex(subject.Refused, 'path_changed'):
                files.read(target, 1024)

    def test_output_short_writes_complete_and_zero_progress_preserves_empty(self):
        actual_write = subject.os.write
        def short(fd, raw):
            return actual_write(fd, raw[:7])
        with mock.patch.object(subject.os, 'write', side_effect=short):
            self.run_operator()
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)
        self.args.output.unlink()
        with mock.patch.object(subject.os, 'write', return_value=0):
            with self.assertRaisesRegex(subject.Refused, 'operation_failed'):
                self.run_operator()
        self.assertEqual(self.args.output.read_bytes(), b'')

    def test_output_fsync_failure_retains_written_evidence(self):
        actual_sync = subject.os.fsync
        def failed(fd):
            info = os.fstat(fd)
            if stat.S_ISREG(info.st_mode) and info.st_size > 0:
                raise OSError('synthetic fsync failure')
            return actual_sync(fd)
        with mock.patch.object(subject.os, 'fsync', side_effect=failed):
            with self.assertRaises(OSError):
                self.run_operator()
        self.assertEqual(json.loads(self.args.output.read_bytes()), self.result)

    def test_read_relative_symlink_ancestor_and_traversal_are_refused(self):
        files = subject.LocalFiles()
        alias = self.root / 'alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        for path in (Path('relative'), self.root / '..' / 'ignored', alias / 'naver_archive_receiver.py'):
            with self.subTest(path=str(path)), self.assertRaises(subject.Refused):
                files.read(path, 65536)

    def test_changed_output_parent_is_refused_and_original_receipt_preserved(self):
        folder = self.root / 'out'
        folder.mkdir(mode=0o700)
        self.args.output = folder / 'receipt.json'
        detached = self.root / 'detached-folder'
        def changed(argv, request):
            folder.rename(detached)
            folder.mkdir(mode=0o700)
            return 0, self.result
        with self.assertRaisesRegex(subject.Refused, 'path_changed'):
            self.run_operator(remote=changed)
        self.assertFalse(self.args.output.exists())
        self.assertTrue((detached / 'receipt.json').exists())


class ExchangeTest(unittest.TestCase):
    def assert_refused(self, code, argv, request=None, **kwargs):
        with self.assertRaisesRegex(subject.Refused, '^' + code + '$'):
            subject.exchange(argv, {} if request is None else request, **kwargs)

    def test_exchange_closed_json_zero_and_failed_rc(self):
        for rc in (0, 2):
            code, result = subject.exchange(child('import sys,json; d=json.load(sys.stdin); '
                'print(json.dumps({"status":"fixture","count":len(d)})); raise SystemExit(' + str(rc) + ')'), {'action': 'install'}, timeout=2)
            self.assertEqual((code, result), (rc, {'status': 'fixture', 'count': 1}))

    def test_exchange_unknown_return_code_and_malformed_json_are_refused(self):
        self.assert_refused('remote_unknown', child('import sys; sys.stdin.read(); print("{}"); raise SystemExit(255)'), timeout=2)
        for output in ('not json', '{"x":1,"x":2}'):
            self.assert_refused('receipt_refused', child('import sys; sys.stdin.read(); print(' + repr(output) + ')'), timeout=2)

    def test_input_limit_checked_before_process_spawn(self):
        with mock.patch.object(subject.subprocess, 'Popen') as popen:
            self.assert_refused('input_refused', ['never-run'], {'data': 'x' * subject.MAX_IO})
        popen.assert_not_called()

    def test_stdout_and_combined_output_are_bounded_without_exposing_payload(self):
        self.assert_refused('output_limit', child('import sys; sys.stdin.read(); sys.stdout.write("x"*20000)'), timeout=2)
        self.assert_refused('output_limit', child('import sys; sys.stdin.read(); '
            'sys.stdout.write("x"*10000); sys.stdout.flush(); sys.stderr.write("x"*125000)'), timeout=2)

    def test_absolute_deadline_terminates_hanging_child(self):
        self.assert_refused('deadline_exceeded', child('import time; time.sleep(60)'), timeout=.05)

    def test_deadline_cleans_group_even_when_direct_child_already_exited(self):
        real_popen = subprocess.Popen
        children = []
        def started(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            children.append(process)
            return process
        code = 'import os,time; p=os.fork()\nif p == 0: time.sleep(60)\nelse: os._exit(0)'
        actual_kill = os.killpg
        try:
            with mock.patch.object(subject.subprocess, 'Popen', side_effect=started), \
                    mock.patch.object(subject.os, 'killpg', wraps=actual_kill) as groups:
                self.assert_refused('deadline_exceeded', child(code), timeout=.1)
            self.assertEqual(children[0].returncode, 0)
            groups.assert_any_call(children[0].pid, signal.SIGKILL)
        finally:
            for process in children:
                try:
                    actual_kill(process.pid, signal.SIGKILL)
                except OSError:
                    # macOS may report EPERM for an already reaped process group.
                    pass
                process.wait(timeout=2)

    def test_cleanup_permission_error_after_exit_does_not_mask_result_or_leak_pipes(self):
        actual_popen = subprocess.Popen
        processes = []
        def started(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            processes.append(process)
            return process
        try:
            with mock.patch.object(subject.subprocess, 'Popen', side_effect=started), \
                    mock.patch.object(subject.os, 'killpg', side_effect=PermissionError('synthetic exited group')):
                code, result = subject.exchange(child('import sys; sys.stdin.read(); print("{}")'), {}, timeout=2)
            self.assertEqual((code, result), (0, {}))
            self.assertTrue(all(pipe.closed for pipe in (processes[0].stdin, processes[0].stdout, processes[0].stderr)))
        finally:
            # A failing implementation must not contaminate later strict-stderr tests.
            for process in processes:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    pipe.close()

    def test_ssh_argv_has_fixed_destination_no_shell_or_user_config(self):
        argv = subject.ssh_command(Path('/private/admin-key'), Path('/private/known-hosts'), b'print("synthetic")')
        self.assertEqual(argv[:4], ['/usr/bin/ssh', '-F', '/dev/null', '-T'])
        self.assertEqual(argv[-2], subject.SERVER)
        self.assertIn('StrictHostKeyChecking=yes', argv)
        self.assertIn('IdentitiesOnly=yes', argv)
        self.assertIn('ProxyCommand=none', argv)
        self.assertIn('ProxyJump=none', argv)
        self.assertIn('GlobalKnownHostsFile=/dev/null', argv)
        remote = shlex.split(argv[-1])
        self.assertEqual(remote[:4], ['/usr/bin/python3', '-I', '-B', '-c'])
        self.assertEqual(remote[4], 'print("synthetic")')

    def test_ssh_known_hosts_path_with_space_is_one_config_value(self):
        path = Path('/private/operator work/known-hosts')
        argv = subject.ssh_command(Path('/private/admin-key'), path, b'pass')
        option = next(v for v in argv if v.startswith('UserKnownHostsFile='))
        self.assertEqual(shlex.split(option.split('=', 1)[1]), [str(path)])

    def test_known_hosts_config_metacharacters_are_refused(self):
        for character in ('"', '\\', '\n', '\r', '\0'):
            with self.subTest(character=repr(character)):
                with self.assertRaisesRegex(subject.Refused, 'path_refused'):
                    subject.ssh_command(Path('/private/admin-key'), Path('/private/a' + character + 'b'), b'pass')

    def test_main_failure_is_fixed_hold_without_exception_or_paths(self):
        output = io.StringIO()
        with mock.patch.object(subject, 'run', side_effect=OSError(CANARY.decode())), contextlib.redirect_stdout(output):
            code = subject.main(['revoke', '--admin-key', '/synthetic', '--output', '/synthetic-out',
                                 '--installed', '/synthetic-receipt', '--receipt-sha256', '0' * 64])
        self.assertEqual(code, 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result, {'status': 'HOLD', 'error': 'operation_failed',
            'session': subject.SESSION, 'retry_authorized': False})
        self.assertNotIn(CANARY.decode(), output.getvalue())


if __name__ == '__main__':
    unittest.main()
