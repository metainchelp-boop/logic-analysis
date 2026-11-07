"""Synthetic filesystem/evidence and local pipes only; no server or actual key."""
import base64
import contextlib
import copy
import datetime
import fcntl
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
import unittest
from unittest import mock

DIRECTORY = Path(__file__).resolve().parents[1]
PATH = DIRECTORY / 'naver_archive_refetch_receiver.py'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


subject = load('refetch_receiver_tested', PATH)
legacy = load('refetch_legacy_tested', DIRECTORY / 'naver_archive_receiver_control.py')
LEGACY_SOURCE = (DIRECTORY / 'naver_archive_receiver_control.py').read_bytes()
MODULE_SOURCE = PATH.read_bytes()
PRIMARY = b'SYNTHETIC_PRIMARY_AUTHORIZATION_NEVER_RETURNED\n'
CIPHER = b'SYNTHETIC_ENCRYPTED_BYTES\0' * 4096
NOW = datetime.datetime(2026, 11, 7, 9, 0, tzinfo=datetime.timezone.utc)
SSHD = (b'authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2\n'
        b'pubkeyauthentication yes\nforcecommand none\npermitrootlogin prohibit-password\n')


def key(byte):
    return 'ssh-ed25519 ' + base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes([byte]) * 32).decode()


def rename(parent, source, target):
    try:
        os.stat(target, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        os.rename(source, target, src_dir_fd=parent, dst_dir_fd=parent)
        return
    raise legacy.Refused('secondary_exists')


class RefetchReceiverTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='naver-refetch-receiver-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.base.chmod(0o700)
        for path in ('root', 'root/.ssh', 'var', 'var/backups', 'var/backups/metainc-app-retirement',
                     subject.DATA_DIR.lstrip('/')):
            self.path('/' + path).mkdir(mode=0o700)
        self.write(subject.PRIMARY, PRIMARY)
        self.write(subject.CIPHER_PATH, CIPHER)
        self.write(subject.LOCK_PATH, b'')
        self.owner = os.getuid(), os.getgid()
        self.files = legacy.Files(str(self.base), *self.owner, rename)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch.object(subject, 'L', legacy))
        self.patches.enter_context(mock.patch.object(subject, 'LEGACY_SOURCE', LEGACY_SOURCE))
        self.patches.enter_context(mock.patch.object(subject, 'MODULE_SOURCE', MODULE_SOURCE))
        self.checks = []
        self.request = dict(action='install', fetch_public_key=key(12), fetch_ip='198.51.100.2',
                            cipher_bytes=len(CIPHER), cipher_sha256=subject.digest(CIPHER))
        self.plan = dict(version=1, session=subject.DATA_SESSION, groups=[{}], total_bytes=len(CIPHER))
        self.proof('plan', self.plan)
        self.sent = dict(status='sent_unverified', session=subject.DATA_SESSION,
                         plan_sha256=self.request['plan_sha256'], bytes=len(CIPHER), sha256=subject.digest(CIPHER))
        self.proof('sent', self.sent)
        self.installed = legacy.empty_result('install')
        self.installed.update(status='installed', error=None, expires_at='20261107080150Z',
            source_ip='192.0.2.1', fetch_ip='198.51.100.2', send_key_sha256=subject.digest(key(11).encode()),
            fetch_key_sha256=subject.digest(key(12).encode()), primary=self.files.read(subject.PRIMARY, 65536)[1],
            primary_unchanged=True, secondary=self.meta(100), secondary_published=True, pending=self.meta(100),
            tool_directory=self.meta(101, directory=True), data_directory=self.meta(102, directory=True),
            receiver=self.meta(103, sha=legacy.RECEIVER_SHA256))
        legacy.validate_result(self.installed, owner=self.owner)
        self.revoked = dict(self.installed, action='revoke', status='revoked')
        self.proof('install', self.installed)
        self.proof('revoke', self.revoked)

    def path(self, value):
        return self.base / value.lstrip('/')

    def write(self, path, raw):
        p = self.path(path)
        p.write_bytes(raw)
        p.chmod(0o600)

    def meta(self, inode, directory=False, sha='a' * 64):
        value = dict(device=1, inode=inode, uid=self.owner[0], gid=self.owner[1],
                     mode=0o700 if directory else 0o600, links=2 if directory else 1, bytes=100)
        if not directory:
            value['sha256'] = sha
        return value

    def proof(self, name, value, raw=None):
        raw = subject.canonical(value) if raw is None else raw
        self.request[name + '_b64'] = base64.b64encode(raw).decode()
        self.request[name + '_sha256'] = subject.digest(raw)

    def check_sshd(self, ip):
        self.checks.append(ip)
        legacy.validate_sshd(SSHD)

    def run_request(self, request=None, **kwargs):
        result = subject.perform(self.request if request is None else request, files=self.files,
                                 check_sshd=kwargs.pop('check_sshd', self.check_sshd), now=NOW, **kwargs)
        self.assertEqual(subject.validate_result(result, owner=self.owner), result)
        raw = subject.canonical(result)
        self.assertLessEqual(len(raw), subject.MAX_RESULT)
        for value in (PRIMARY, CIPHER, key(11).encode(), key(12).encode(), b'restrict,from=', b'Traceback'):
            self.assertNotIn(value, raw)
        return result

    def snapshot(self):
        return {str(p.relative_to(self.base)): (subject.identity(p.stat()), p.read_bytes())
                for p in self.base.rglob('*') if p.is_file()}

    def protected(self):
        return {p: (subject.identity(self.path(p).stat()), self.path(p).read_bytes())
                for p in (subject.PRIMARY, subject.CIPHER_PATH, subject.LOCK_PATH)}

    def fetch(self, config, output=None, **kwargs):
        output = io.BytesIO() if output is None else output
        result = subject.fetch(config, output, files=self.files, now=kwargs.pop('now', NOW), **kwargs)
        self.assertEqual(result, {'bytes': len(CIPHER), 'sha256': subject.digest(CIPHER)})
        return output

    def test_install_read_only_fetch_and_exact_revoke_preserve_original_bytes_and_inodes(self):
        protected = self.protected()
        result = self.run_request()
        self.assertEqual(result['status'], 'installed')
        self.assertEqual(self.checks, ['198.51.100.2'])
        self.assertEqual(result['config']['issued_at'], '20261107090000Z')
        self.assertEqual(result['config']['start_before'], '20261107093000Z')
        self.assertEqual(result['config']['expires_at'], '20261107150000Z')
        self.assertEqual(self.files.read(subject.SECONDARY, 4096)[0], subject.authorization(result['config'], key(12)))
        self.assertEqual(len(self.path(subject.SECONDARY).read_bytes().splitlines()), 1)
        self.assertEqual(self.fetch(result['config']).getvalue(), CIPHER)
        for path, expected in ((subject.TOOL, MODULE_SOURCE), (subject.LEGACY_PATH, LEGACY_SOURCE),
                               (subject.CONFIG_PATH, subject.canonical(result['config']))):
            self.assertEqual(self.path(path).read_bytes(), expected)
            self.assertEqual(stat.S_IMODE(self.path(path).stat().st_mode), 0o600)
        revoked = self.run_request({'action': 'revoke', 'installed': result})
        self.assertEqual(revoked['status'], 'revoked')
        self.assertFalse(self.path(subject.SECONDARY).exists())
        self.assertEqual(self.run_request({'action': 'revoke', 'installed': result})['status'], 'already_absent')
        self.assertTrue(self.path(subject.TOOL).exists())
        self.assertEqual(self.protected(), protected)

    def test_closed_request_keys_key_ip_and_raw_hash_fail_before_writes(self):
        before = self.snapshot()
        variants = [dict(extra=True), dict(fetch_public_key=key(11)), dict(fetch_public_key=key(12) + ' comment'),
            dict(fetch_ip='198.51.100.2/32'), dict(fetch_ip='198.051.100.2'), dict(fetch_ip='::1'),
            dict(cipher_bytes=True), dict(cipher_sha256='x' * 64), dict(plan_sha256='0' * 64),
            dict(sent_sha256='0' * 64), dict(install_sha256='0' * 64), dict(revoke_sha256='0' * 64),
            dict(plan_b64='not-base64')]
        for change in variants:
            with self.subTest(change=list(change)):
                self.assertEqual(self.run_request(dict(self.request, **change))['status'], 'failed')
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.checks, [])

    def test_plan_canonical_closed_envelope_and_sent_binding_are_required(self):
        original = copy.deepcopy(self.request)
        variants = [('plan', dict(self.plan, unexpected=True), None),
            ('plan', self.plan, subject.canonical(self.plan) + b'\n'),
            ('plan', None, b'{"version":1,"version":1}'),
            ('sent', dict(self.sent, plan_sha256='0' * 64), None),
            ('sent', dict(self.sent, bytes=len(CIPHER) + 1), None),
            ('sent', dict(self.sent, status='verified'), None),
            ('sent', self.sent, subject.canonical(self.sent) + b'\n')]
        before = self.snapshot()
        for name, value, raw in variants:
            with self.subTest(name=name, value=value):
                self.request = copy.deepcopy(original)
                self.proof(name, value, raw)
                self.assertEqual(self.run_request()['status'], 'failed')
                self.assertEqual(self.snapshot(), before)

    def test_old_revocation_must_match_every_preserved_install_field(self):
        before = self.snapshot()
        for changed in (dict(fetch_ip='198.51.100.4'), dict(primary_unchanged=False),
                        dict(primary=dict(self.revoked['primary'], inode=123)),
                        dict(secondary=dict(self.revoked['secondary'], sha256='0' * 64)),
                        dict(status='failed', error='operation_failed')):
            with self.subTest(changed=changed):
                self.proof('revoke', dict(self.revoked, **changed))
                self.assertEqual(self.run_request()['status'], 'failed')
                self.assertEqual(self.snapshot(), before)

    def test_old_already_absent_proof_is_allowed_but_actual_secondary_must_be_absent(self):
        self.proof('revoke', dict(self.revoked, status='already_absent'))
        self.write(subject.SECONDARY, b'FOREIGN')
        before = self.snapshot()
        self.assertEqual(self.run_request()['error'], 'secondary_exists')
        self.assertEqual(self.snapshot(), before)
        self.path(subject.SECONDARY).unlink()
        self.assertEqual(self.run_request()['status'], 'installed')

    def test_foreign_secondary_old_pending_and_new_pending_are_preserved(self):
        for path in (subject.SECONDARY, subject.OLD_PENDING, subject.PENDING):
            with self.subTest(path=path):
                self.write(path, b'FOREIGN')
                before = self.snapshot()
                self.assertEqual(self.run_request()['error'], 'secondary_exists')
                self.assertEqual(self.snapshot(), before)
                self.path(path).unlink()

    def test_primary_must_match_previous_receipt_before_any_write(self):
        self.write(subject.PRIMARY, b'CHANGED_PRIMARY')
        before = self.snapshot()
        self.assertEqual(self.run_request()['error'], 'primary_changed')
        self.assertEqual(self.snapshot(), before)

    def test_unsafe_effective_sshd_refused_before_tool_creation(self):
        def check(ip):
            legacy.validate_sshd(SSHD.replace(b'forcecommand none', b'forcecommand something'))
        before = self.snapshot()
        self.assertEqual(self.run_request(check_sshd=check)['error'], 'sshd_secondary_unavailable')
        self.assertEqual(self.snapshot(), before)

    def test_missing_existing_lock_is_not_created(self):
        self.path(subject.LOCK_PATH).unlink()
        before = self.snapshot()
        self.assertEqual(self.run_request()['status'], 'failed')
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.path(subject.LOCK_PATH).exists())

    def test_busy_lock_nonblocking_refusal(self):
        with self.path(subject.LOCK_PATH).open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = self.snapshot()
            self.assertEqual(self.run_request()['error'], 'busy')
            self.assertEqual(self.snapshot(), before)

    def test_existing_partial_is_never_read_moved_or_removed(self):
        self.write(subject.PARTIAL_PATH, b'INCOMPLETE_OLD_CIPHER')
        before = self.snapshot()
        self.assertEqual(self.run_request()['error'], 'partial_exists')
        self.assertEqual(self.snapshot(), before)

    def test_cipher_or_lock_symlink_hardlink_permissions_refused(self):
        for name in (subject.CIPHER_PATH, subject.LOCK_PATH):
            p = self.path(name)
            p.chmod(0o644)
            self.assertEqual(self.run_request()['status'], 'failed')
            p.chmod(0o600)
            linked = p.with_name(p.name + '.link')
            os.link(p, linked)
            self.assertEqual(self.run_request()['status'], 'failed')
            linked.unlink()
            p.rename(linked)
            p.symlink_to(linked)
            self.assertEqual(self.run_request()['status'], 'failed')
            p.unlink()
            linked.rename(p)
        self.assertFalse(self.path(subject.ROOT).exists())

    def test_full_cipher_hash_and_length_must_match_original_sent(self):
        for raw in (CIPHER[:-1], b'X' + CIPHER[1:]):
            self.write(subject.CIPHER_PATH, raw)
            before = self.snapshot()
            self.assertEqual(self.run_request()['error'], 'cipher_mismatch')
            self.assertEqual(self.snapshot(), before)

    def test_existing_tool_directory_cannot_refresh_or_reinstall_lease(self):
        result = self.run_request()
        self.run_request({'action': 'revoke', 'installed': result})
        before = self.snapshot()
        self.assertEqual(self.run_request()['error'], 'directory_exists')
        self.assertEqual(self.snapshot(), before)

    def test_primary_replacement_after_pending_refuses_publication(self):
        actual = self.files.write
        def write(path, raw):
            result = actual(path, raw)
            if path == subject.PENDING:
                p = self.path(subject.PRIMARY)
                p.rename(p.with_name('original-primary'))
                self.write(subject.PRIMARY, PRIMARY)
            return result
        with mock.patch.object(self.files, 'write', side_effect=write):
            result = self.run_request()
        self.assertEqual(result['error'], 'primary_changed')
        self.assertFalse(result['primary_unchanged'])
        self.assertFalse(result['secondary_published'])
        self.assertIsNotNone(result['pending'])
        self.assertFalse(self.path(subject.SECONDARY).exists())

    def test_failed_pending_write_retains_partial_metadata_and_tools(self):
        actual = os.write
        calls = 0
        def write(fd, raw):
            nonlocal calls
            if self.path(subject.PENDING).exists():
                calls += 1
                if calls == 1:
                    return actual(fd, raw[:11])
                raise OSError('PRIVATE_DIAGNOSTIC_MUST_NOT_LEAK')
            return actual(fd, raw)
        with mock.patch.object(os, 'write', side_effect=write):
            result = self.run_request()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['pending']['bytes'], 11)
        self.assertFalse(result['secondary_published'])
        self.assertTrue(self.path(subject.TOOL).exists())
        self.assertNotIn('PRIVATE_DIAGNOSTIC', json.dumps(result))

    def test_rename_failure_retains_pending_without_secondary(self):
        self.files.rename = mock.Mock(side_effect=legacy.Refused('atomic_publish_failed'))
        result = self.run_request()
        self.assertEqual(result['error'], 'atomic_publish_failed')
        self.assertFalse(result['secondary_published'])
        self.assertTrue(self.path(subject.PENDING).exists())
        self.assertFalse(self.path(subject.SECONDARY).exists())

    def test_post_publish_fsync_failure_has_usable_exact_revoke_receipt(self):
        actual = os.fsync
        def fsync(fd):
            if self.path(subject.SECONDARY).exists():
                raise OSError('SYNTHETIC_DURABILITY_FAILURE')
            return actual(fd)
        before = self.protected()
        with mock.patch.object(os, 'fsync', side_effect=fsync):
            result = self.run_request()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['secondary_published'])
        self.assertEqual(result['secondary'], self.files.read(subject.SECONDARY, 4096)[1])
        self.assertEqual(self.run_request({'action': 'revoke', 'installed': result})['status'], 'revoked')
        self.assertEqual(self.protected(), before)

    def test_rename_success_then_exception_recovers_exact_revocation_evidence(self):
        def fail(parent, source, target):
            rename(parent, source, target)
            raise OSError('AFTER_RENAME')
        self.files.rename = fail
        result = self.run_request()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['secondary_published'])
        self.assertEqual(self.run_request({'action': 'revoke', 'installed': result})['status'], 'revoked')

    def test_exact_revoke_refuses_replaced_secondary_even_same_content(self):
        result = self.run_request()
        p = self.path(subject.SECONDARY)
        raw = p.read_bytes()
        p.rename(p.with_name('original-secondary'))
        self.write(subject.SECONDARY, raw)
        self.assertEqual(self.run_request({'action': 'revoke', 'installed': result})['error'], 'secondary_mismatch')
        self.assertEqual(p.read_bytes(), raw)

    def test_revoke_checks_fixed_command_envelope_even_with_forged_metadata(self):
        result = self.run_request()
        raw = self.path(subject.SECONDARY).read_bytes().replace(subject.COMMAND.encode(), b'/bin/sh')
        self.write(subject.SECONDARY, raw)
        result['secondary'] = result['pending'] = self.files.read(subject.SECONDARY, 4096)[1]
        revoked = self.run_request({'action': 'revoke', 'installed': result})
        self.assertEqual(revoked['error'], 'authorization_refused')
        self.assertEqual(self.path(subject.SECONDARY).read_bytes(), raw)

    def test_config_constants_paths_and_time_envelope_are_closed(self):
        config = self.run_request()['config']
        variants = [dict(extra=True), dict(cipher_path='/tmp/foreign'), dict(server_timeout=14401),
            dict(client_timeout=16201), dict(legacy_sha256='0' * 64), dict(expires_at='20261107160000Z'),
            dict(start_before='20261107093100Z'), dict(fetch_ip='198.51.100.2/32'),
            dict(lock_identity=dict(config['lock_identity'], bytes=1))]
        for changed in variants:
            with self.subTest(changed=changed), self.assertRaises(subject.Refused):
                subject.validate_config(dict(config, **changed), owner=self.owner)

    def test_config_and_result_validators_are_pure(self):
        result = self.run_request()
        with mock.patch.object(os, 'open', side_effect=AssertionError('unexpected syscall')):
            self.assertEqual(subject.validate_config(result['config'], owner=self.owner), result['config'])
            self.assertEqual(subject.validate_result(result, owner=self.owner), result)

    def test_fetch_must_start_within_lease_window_no_bytes_on_refusal(self):
        config = self.run_request()['config']
        for now in (NOW - datetime.timedelta(seconds=1), NOW + datetime.timedelta(seconds=1801),
                    NOW + datetime.timedelta(seconds=21600)):
            output = io.BytesIO()
            with self.subTest(now=now), self.assertRaisesRegex(subject.Refused, 'start_expired'):
                self.fetch(config, output, now=now)
            self.assertEqual(output.getvalue(), b'')
        self.assertEqual(self.fetch(config, now=NOW + datetime.timedelta(seconds=1800)).getvalue(), CIPHER)

    def test_fetch_replaced_or_truncated_cipher_outputs_nothing(self):
        config = self.run_request()['config']
        self.write(subject.CIPHER_PATH, CIPHER[:-1])
        output = io.BytesIO()
        with self.assertRaisesRegex(subject.Refused, 'cipher_changed'):
            self.fetch(config, output)
        self.assertEqual(output.getvalue(), b'')

    def test_fetch_hash_mismatch_even_same_identity_claim_outputs_nothing(self):
        config = self.run_request()['config']
        self.write(subject.CIPHER_PATH, b'X' + CIPHER[1:])
        config['cipher']['identity'] = subject.identity(self.path(subject.CIPHER_PATH).stat())
        output = io.BytesIO()
        with self.assertRaisesRegex(subject.Refused, 'cipher_mismatch'):
            self.fetch(config, output)
        self.assertEqual(output.getvalue(), b'')

    def test_fetch_replaced_lock_or_directory_binding_is_refused(self):
        config = self.run_request()['config']
        p = self.path(subject.LOCK_PATH)
        p.rename(p.with_name('old-lock'))
        self.write(subject.LOCK_PATH, b'')
        output = io.BytesIO()
        with self.assertRaisesRegex(subject.Refused, 'cipher_changed'):
            self.fetch(config, output)
        self.assertEqual(output.getvalue(), b'')

    def test_fetch_short_writes_are_completed(self):
        class Short(io.BytesIO):
            def write(self, raw):
                return super().write(raw[:73])
        output = self.fetch(self.run_request()['config'], Short())
        self.assertEqual(output.getvalue(), CIPHER)

    def test_fetch_zero_write_and_deadline_refuse_success_and_release_lock(self):
        config = self.run_request()['config']
        class Zero(io.BytesIO):
            def write(self, raw):
                return 0
        with self.assertRaisesRegex(subject.Refused, 'stream_failed'):
            self.fetch(config, Zero())
        with self.assertRaisesRegex(subject.Refused, 'deadline_exceeded'):
            self.fetch(config, deadline=time.monotonic() - 1)
        self.assertEqual(self.fetch(config).getvalue(), CIPHER)

    def test_fetch_changed_cipher_during_output_never_returns_success(self):
        config = self.run_request()['config']
        owner = self
        class Changed(io.BytesIO):
            def write(self, raw):
                count = super().write(raw)
                owner.write(subject.CIPHER_PATH, b'X' + CIPHER[1:])
                return count
        with self.assertRaisesRegex(subject.Refused, 'cipher_changed'):
            self.fetch(config, Changed())

    def test_fetch_flush_failure_never_returns_success(self):
        class BrokenFlush(io.BytesIO):
            def flush(self):
                raise BrokenPipeError('SYNTHETIC_OUTPUT_FAILURE')
        with self.assertRaises(BrokenPipeError):
            self.fetch(self.run_request()['config'], BrokenFlush())

    def test_runtime_arbitrary_command_or_argument_never_emits_stdout(self):
        for command, argv in ((subject.FETCH_COMMAND, ['refetch.py', 'receive']),
                              ('receive-' + subject.LEASE_ID, ['refetch.py'])):
            output = io.BytesIO()
            with mock.patch.object(subject.os, 'geteuid', return_value=0), \
                 mock.patch.object(subject.sys, 'platform', 'linux'), \
                 mock.patch.object(subject.sys, 'argv', argv), \
                 mock.patch.dict(subject.os.environ, {'SSH_ORIGINAL_COMMAND': command}), \
                 mock.patch.object(subject.sys, 'stdout', type('Out', (), {'buffer': output})()), \
                 mock.patch.object(subject, 'emit_error') as errors:
                self.assertEqual(subject.main_fetch(), 2)
            self.assertEqual(output.getvalue(), b'')
            errors.assert_called_once_with('command_refused')

    def test_runtime_actual_alarm_interrupts_blocked_pipe_and_returns_nonzero(self):
        # The child uses a synthetic stream seam but the real main_fetch timer,
        # blocking os.write and process exit. Parent deliberately does not drain.
        program = r'''
import importlib.util, os, sys
from unittest import mock
p=sys.argv[1]
s=importlib.util.spec_from_file_location('server',p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class F:
 def read(self,*a): return b'{}',None
 def directory(self,*a):
  import contextlib
  return contextlib.nullcontext()
class L:
 Files=F
def stream(config,output,**k):
 while True: output.write(b'Z'*65536)
m.SERVER_TIMEOUT=.2
m.legacy=lambda:L
m.module_source=lambda:b'public'
m.validate_config=lambda x:dict(module_sha256=m.digest(b'public'))
canonical=m.canonical
m.canonical=lambda x:b'{}' if 'module_sha256' in x else canonical(x)
m.fetch=stream
os.environ['SSH_ORIGINAL_COMMAND']=m.FETCH_COMMAND
sys.argv=['refetch.py']
with mock.patch.object(m.os,'geteuid',return_value=0),mock.patch.object(m.sys,'platform','linux'):
 sys.exit(m.main_fetch())
'''
        proc = subprocess.Popen([sys.executable, '-I', '-B', '-c', program, str(PATH)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(proc.wait(timeout=5), 2)
            output, error = proc.communicate(timeout=2)
            self.assertTrue(output and set(output) == {ord('Z')})
            self.assertEqual(json.loads(error)['error'], 'deadline_exceeded')
            self.assertLess(len(error), 512)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate()

    def test_runtime_broken_pipe_error_has_safe_stderr_only(self):
        program = r'''
import importlib.util,os,sys
from unittest import mock
s=importlib.util.spec_from_file_location('server',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
m.SERVER_TIMEOUT=1
m.legacy=lambda:(_ for _ in ()).throw(BrokenPipeError('PRIVATE_RAW_ERROR'))
os.environ['SSH_ORIGINAL_COMMAND']=m.FETCH_COMMAND
sys.argv=['refetch.py']
with mock.patch.object(m.os,'geteuid',return_value=0),mock.patch.object(m.sys,'platform','linux'):
 sys.exit(m.main_fetch())
'''
        proc = subprocess.run([sys.executable, '-I', '-B', '-c', program, str(PATH)], capture_output=True, timeout=5)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, b'')
        self.assertNotIn(b'PRIVATE_RAW_ERROR', proc.stderr)
        self.assertEqual(json.loads(proc.stderr)['error'], 'operation_failed')

    def test_legacy_source_pin_is_exact(self):
        self.assertEqual(subject.digest(LEGACY_SOURCE), subject.LEGACY_SHA256)
        with mock.patch.object(subject, 'LEGACY_SOURCE', LEGACY_SOURCE + b'\n'):
            with self.assertRaisesRegex(subject.Refused, 'asset_refused'):
                subject.legacy()


if __name__ == '__main__':
    unittest.main()
