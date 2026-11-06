"""Synthetic namespaces and SSH configuration only; no servers or actual keys."""
import base64
import contextlib
import copy
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import types
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('naver_archive_receiver_control_tested',
    Path(__file__).resolve().parents[1] / 'naver_archive_receiver_control.py')
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
RECEIVER = b'# PUBLIC_SYNTHETIC_RECEIVER_FOR_FILESYSTEM_TESTS\n'
PRIMARY = b'SYNTHETIC_EXISTING_PRIMARY_AUTHORIZATION\n'
NOW = datetime.datetime(2026, 11, 6, 8, 30, tzinfo=datetime.timezone.utc)
SSHD = (b'authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2\n'
        b'pubkeyauthentication yes\nforcecommand none\npermitrootlogin prohibit-password\n')


def key(byte):
    wire = b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes([byte]) * 32
    return 'ssh-ed25519 ' + base64.b64encode(wire).decode('ascii')


def synthetic_rename(parent, source, target):
    # Deterministic single-process seam on macOS. Linux syscall is tested below.
    try:
        os.stat(target, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        os.rename(source, target, src_dir_fd=parent, dst_dir_fd=parent)
        return
    raise subject.Refused('secondary_exists')


class ReceiverControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='naver-receiver-control-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.base.chmod(0o700)
        for path in ('root', 'root/.ssh', 'var', 'var/backups', 'var/backups/metainc-app-retirement'):
            self.path('/' + path).mkdir(mode=0o700)
        self.path(subject.PRIMARY).write_bytes(PRIMARY)
        self.path(subject.PRIMARY).chmod(0o600)
        self.files = subject.Files(str(self.base), os.getuid(), os.getgid(), synthetic_rename)
        self.owner = os.getuid(), os.getgid()
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(mock.patch.object(subject, 'RECEIVER_SHA256', subject.digest(RECEIVER)))
        self.space = types.SimpleNamespace(f_bavail=16 * 1024 ** 3, f_frsize=1)
        self.patches.enter_context(mock.patch.object(subject.os, 'fstatvfs', return_value=self.space))
        self.checks = []
        self.request = dict(action='install', send_public_key=key(11), fetch_public_key=key(12),
            source_ip='192.0.2.1', fetch_ip='198.51.100.2', receiver_b64=base64.b64encode(RECEIVER).decode('ascii'))

    def path(self, value):
        return self.base / value.lstrip('/')

    def check_sshd(self, ip):
        self.checks.append(ip)
        subject.validate_sshd(SSHD)

    def run_request(self, request=None, **kwargs):
        result = subject.perform(self.request if request is None else request, files=self.files,
                                 check_sshd=kwargs.pop('check_sshd', self.check_sshd), now=NOW, **kwargs)
        self.assertEqual(subject.validate_result(result, owner=self.owner), result)
        self.assertLessEqual(len(subject.canonical(result)), subject.MAX_RESULT)
        public = subject.canonical(result)
        for secret in (PRIMARY, RECEIVER, key(11).encode(), key(12).encode(), b'restrict,from=', b'Traceback'):
            self.assertNotIn(secret, public)
        return result

    def snapshot(self):
        return {str(p.relative_to(self.base)): (stat.S_IMODE(p.lstat().st_mode), p.read_bytes())
                for p in self.base.rglob('*') if p.is_file()}

    def test_install_two_distinct_keys_expiry_fixed_command_and_exact_revoke(self):
        initial_primary = self.files.read(subject.PRIMARY, 65536)[1]
        installed = self.run_request()
        self.assertEqual(installed['status'], 'installed')
        self.assertEqual(self.checks, ['192.0.2.1', '198.51.100.2'])
        self.assertEqual(installed['expires_at'], '20261106113000Z')
        self.assertTrue(installed['primary_unchanged'])
        self.assertTrue(installed['secondary_published'])
        self.assertFalse(self.path(subject.PENDING).exists())
        self.assertEqual(self.files.read(subject.PRIMARY, 65536)[1], initial_primary)
        raw, metadata = self.files.read(subject.SECONDARY, 4096)
        self.assertEqual(raw, subject.authorization(self.request, installed['expires_at']))
        self.assertEqual(metadata, installed['secondary'])
        self.assertEqual(len(raw.splitlines()), 2)
        self.assertEqual(self.path(subject.TOOL).read_bytes(), RECEIVER)
        self.assertEqual(stat.S_IMODE(self.path(subject.DATA_DIR).stat().st_mode), 0o700)
        keep = self.path(subject.DATA_DIR) / 'archives.gpg'
        keep.write_bytes(b'SYNTHETIC_CIPHERTEXT')
        keep.chmod(0o600)
        revoked = self.run_request({'action': 'revoke', 'installed': installed})
        self.assertEqual(revoked['status'], 'revoked')
        self.assertFalse(self.path(subject.SECONDARY).exists())
        self.assertEqual(keep.read_bytes(), b'SYNTHETIC_CIPHERTEXT')
        self.assertEqual(self.path(subject.TOOL).read_bytes(), RECEIVER)
        self.assertEqual(self.files.read(subject.PRIMARY, 65536)[1], initial_primary)
        self.assertEqual(self.run_request({'action': 'revoke', 'installed': installed})['status'], 'already_absent')
        self.assertEqual(self.checks, ['192.0.2.1', '198.51.100.2'])

    def test_invalid_request_assets_rejected_before_any_write(self):
        changes = [dict(extra='unexpected'), dict(receiver_b64=base64.b64encode(b'wrong').decode()),
            dict(receiver_b64='not base64!'), dict(send_public_key=key(12)),
            dict(send_public_key=key(11) + ' comment'), dict(fetch_public_key='ssh-rsa whatever'),
            dict(source_ip='192.0.2.1/32'), dict(source_ip='192.000.2.1'),
            dict(fetch_ip='::1'), dict(fetch_ip='198.51.100.2\n')]
        before = self.snapshot()
        for change in changes:
            with self.subTest(change=list(change)):
                request = dict(self.request, **change)
                self.assertEqual(self.run_request(request)['status'], 'failed')
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.path(subject.ROOT).exists())
                self.assertFalse(self.path(subject.DATA_DIR).exists())
        self.assertEqual(self.checks, [])

    def test_second_ip_effective_sshd_refusal_prevents_all_writes(self):
        def check(ip):
            self.checks.append(ip)
            if ip == self.request['fetch_ip']:
                raise subject.Refused('sshd_secondary_unavailable')
        result = self.run_request(check_sshd=check)
        self.assertEqual(result['error'], 'sshd_secondary_unavailable')
        self.assertEqual(self.checks, [self.request['source_ip'], self.request['fetch_ip']])
        self.assertFalse(self.path(subject.ROOT).exists())
        self.assertFalse(self.path(subject.DATA_DIR).exists())
        self.assertEqual(self.path(subject.PRIMARY).read_bytes(), PRIMARY)

    def test_insufficient_space_before_any_write(self):
        self.space.f_bavail = subject.MIN_FREE - 1
        result = self.run_request()
        self.assertEqual(result['error'], 'space_insufficient')
        self.assertFalse(self.path(subject.ROOT).exists())
        self.assertFalse(self.path(subject.DATA_DIR).exists())

    def test_foreign_secondary_or_pending_is_never_overwritten(self):
        for name in (subject.SECONDARY, subject.PENDING):
            with self.subTest(path=name):
                p = self.path(name)
                p.write_bytes(b'FOREIGN_AUTHORIZATION')
                p.chmod(0o600)
                before = self.snapshot()
                self.assertEqual(self.run_request()['error'], 'secondary_exists')
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.path(subject.ROOT).exists())
                p.unlink()

    def test_existing_data_session_never_reused(self):
        self.path(subject.DATA_DIR).mkdir(mode=0o700)
        self.assertEqual(self.run_request()['error'], 'directory_exists')
        self.assertFalse(self.path(subject.ROOT).exists())

    def test_symlink_shared_parent_permissions_and_primary_hardlink_refused(self):
        folder = self.path(subject.DATA_ROOT)
        folder.chmod(0o755)
        self.assertEqual(self.run_request()['error'], 'unsafe_directory')
        folder.chmod(0o700)
        moved = folder.with_name('moved')
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.run_request()['error'], 'unsafe_directory')
        folder.unlink()
        moved.rename(folder)
        os.link(self.path(subject.PRIMARY), self.path('/root/.ssh/primary-link'))
        self.assertEqual(self.run_request()['error'], 'unsafe_file')
        self.assertFalse(self.path(subject.ROOT).exists())

    def test_primary_replacement_after_pending_blocks_publication(self):
        original = self.files.write
        def replaced(path, raw):
            result = original(path, raw)
            if path == subject.PENDING:
                p = self.path(subject.PRIMARY)
                p.rename(p.with_name('original-primary'))
                p.write_bytes(PRIMARY)
                p.chmod(0o600)
            return result
        with mock.patch.object(self.files, 'write', side_effect=replaced):
            result = self.run_request()
        self.assertEqual(result['error'], 'primary_changed')
        self.assertFalse(result['primary_unchanged'])
        self.assertFalse(result['secondary_published'])
        self.assertIsNotNone(result['pending'])
        self.assertTrue(self.path(subject.PENDING).exists())
        self.assertFalse(self.path(subject.SECONDARY).exists())

    def test_partial_pending_write_is_retained_and_reported(self):
        original = os.write
        count = 0
        def fail_second_write(fd, raw):
            nonlocal count
            if self.path(subject.PENDING).exists():
                count += 1
                if count == 1:
                    return original(fd, raw[:9])
                raise OSError('SYNTHETIC_PRIVATE_ERROR')
            return original(fd, raw)
        with mock.patch.object(subject.os, 'write', side_effect=fail_second_write):
            result = self.run_request()
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['secondary_published'])
        self.assertEqual(result['pending']['bytes'], 9)
        self.assertEqual(result['pending']['sha256'], subject.digest(self.path(subject.PENDING).read_bytes()))
        self.assertTrue(result['primary_unchanged'])
        self.assertIsNotNone(result['receiver'])

    def test_publish_failure_retains_pending_and_never_cleans_tools(self):
        self.files.rename = mock.Mock(side_effect=subject.Refused('atomic_publish_unavailable'))
        result = self.run_request()
        self.assertEqual(result['error'], 'atomic_publish_unavailable')
        self.assertFalse(result['secondary_published'])
        self.assertTrue(self.path(subject.PENDING).exists())
        self.assertTrue(self.path(subject.TOOL).exists())
        self.assertTrue(self.path(subject.DATA_DIR).exists())
        self.assertFalse(self.path(subject.SECONDARY).exists())

    def test_publish_conflict_keeps_foreign_secondary(self):
        def conflicted(parent, source, target):
            p = self.path(subject.SECONDARY)
            p.write_bytes(b'FOREIGN')
            p.chmod(0o600)
            synthetic_rename(parent, source, target)
        self.files.rename = conflicted
        result = self.run_request()
        self.assertEqual(result['error'], 'secondary_exists')
        self.assertFalse(result['secondary_published'])
        self.assertTrue(self.path(subject.PENDING).exists())
        self.assertEqual(self.path(subject.SECONDARY).read_bytes(), b'FOREIGN')

    def test_post_publish_fsync_failure_retains_exact_revocation_proof(self):
        original = os.fsync
        def failed_after_publish(fd):
            if self.path(subject.SECONDARY).exists():
                raise OSError('SYNTHETIC_DURABILITY_FAILURE')
            return original(fd)
        with mock.patch.object(subject.os, 'fsync', side_effect=failed_after_publish):
            result = self.run_request()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(result['secondary_published'])
        self.assertEqual(result['secondary'], self.files.read(subject.SECONDARY, 4096)[1])
        self.assertEqual(self.run_request({'action': 'revoke', 'installed': result})['status'], 'revoked')

    def test_partial_directory_creation_failure_preserves_observed_identity(self):
        original = self.files.mkdir
        def failed(path, existing=False):
            result = original(path, existing)
            if path == subject.DATA_DIR:
                raise OSError('synthetic failure after mkdir')
            return result
        with mock.patch.object(self.files, 'mkdir', side_effect=failed):
            result = self.run_request()
        self.assertEqual(result['status'], 'failed')
        self.assertIsNotNone(result['tool_directory'])
        self.assertIsNotNone(result['data_directory'])
        self.assertIsNone(result['receiver'])
        self.assertFalse(result['secondary_published'])

    def test_revoke_rejects_changed_secondary_without_deleting_it(self):
        installed = self.run_request()
        p = self.path(subject.SECONDARY)
        p.write_bytes(b'FOREIGN')
        result = self.run_request({'action': 'revoke', 'installed': installed})
        self.assertEqual(result['error'], 'secondary_mismatch')
        self.assertEqual(p.read_bytes(), b'FOREIGN')
        self.assertTrue(result['primary_unchanged'])

    def test_forged_receipt_hash_cannot_authorize_foreign_command_envelope(self):
        installed = self.run_request()
        p = self.path(subject.SECONDARY)
        p.write_bytes(p.read_bytes().replace(subject.COMMAND.encode(), b'/bin/sh'))
        forged = copy.deepcopy(installed)
        forged['secondary'] = self.files.read(subject.SECONDARY, 4096)[1]
        forged['pending'] = forged['secondary']
        result = self.run_request({'action': 'revoke', 'installed': forged})
        self.assertEqual(result['error'], 'authorization_refused')
        self.assertTrue(p.exists())

    def test_revoke_unlink_error_preserves_secondary_and_primary(self):
        installed = self.run_request()
        before = self.snapshot()
        with mock.patch.object(subject.os, 'unlink', side_effect=OSError('SYNTHETIC_PRIVATE_ERROR')):
            result = self.run_request({'action': 'revoke', 'installed': installed})
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(result['primary_unchanged'])

    def test_revoke_fsync_failure_is_failed_but_absent_retry_is_safe(self):
        installed = self.run_request()
        original = os.fsync
        def failed_after_unlink(fd):
            if not self.path(subject.SECONDARY).exists():
                raise OSError('synthetic revoke durability failure')
            return original(fd)
        with mock.patch.object(subject.os, 'fsync', side_effect=failed_after_unlink):
            result = self.run_request({'action': 'revoke', 'installed': installed})
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(self.path(subject.SECONDARY).exists())
        self.assertTrue(result['primary_unchanged'])
        self.assertEqual(self.run_request({'action': 'revoke', 'installed': installed})['status'], 'already_absent')

    def test_primary_change_after_publish_is_failed_and_preserves_revoke_evidence(self):
        original = self.files.publish
        def published_then_primary_changed(expected, result):
            original(expected, result)
            self.path(subject.PRIMARY).write_bytes(b'EXTERNAL_PRIMARY_CHANGE')
        with mock.patch.object(self.files, 'publish', side_effect=published_then_primary_changed):
            installed = self.run_request()
        self.assertEqual(installed['error'], 'primary_changed')
        self.assertFalse(installed['primary_unchanged'])
        self.assertTrue(installed['secondary_published'])
        result = self.run_request({'action': 'revoke', 'installed': installed})
        self.assertEqual(result['status'], 'revoked')
        self.assertEqual(self.path(subject.PRIMARY).read_bytes(), b'EXTERNAL_PRIMARY_CHANGE')
        self.assertTrue(result['primary_unchanged'])

    def test_cli_requires_linux_root_before_reading_request(self):
        for platform, uid, error in (('darwin', 0, 'platform_refused'), ('linux', 501, 'root_required')):
            output = io.StringIO()
            incoming = types.SimpleNamespace(buffer=mock.Mock(side_effect=AssertionError('must not read')))
            with mock.patch.object(subject.sys, 'platform', platform), \
                    mock.patch.object(subject.os, 'geteuid', return_value=uid), \
                    mock.patch.object(subject.sys, 'stdin', incoming), \
                    mock.patch.object(subject.sys, 'stdout', output):
                self.assertEqual(subject.main(), 2)
            self.assertEqual(json.loads(output.getvalue())['error'], error)
            incoming.buffer.read.assert_not_called()

    def test_expired_install_never_refreshes_and_can_be_revoked(self):
        installed = self.run_request()
        before = self.snapshot()
        later = NOW + datetime.timedelta(days=3)
        result = subject.perform(self.request, files=self.files, check_sshd=self.check_sshd, now=later)
        self.assertEqual(result['error'], 'secondary_exists')
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.run_request({'action': 'revoke', 'installed': installed})['status'], 'revoked')

    def test_result_closed_schema_and_proof_validation_reject_tampering(self):
        installed = self.run_request()
        changes = [dict(extra=1), dict(version=True), dict(session='foreign'),
            dict(receiver_sha256='0'*64), dict(status='installed', error='operation_failed'),
            dict(primary_unchanged=False), dict(secondary_published=False), dict(expires_at='20261399000000Z'),
            dict(source_ip='192.0.2.1/32'), dict(send_key_sha256=installed['fetch_key_sha256'])]
        for change in changes:
            with self.subTest(change=list(change)), self.assertRaises(subject.Refused):
                subject.validate_result(dict(installed, **change), owner=self.owner)
        bad = copy.deepcopy(installed)
        bad['secondary']['links'] = 2
        with self.assertRaises(subject.Refused):
            subject.validate_result(bad, owner=self.owner)
        for request in ({'action': 'revoke', 'installed': installed, 'extra': 1},
                        {'action': 'revoke', 'installed': subject.empty_result('install')}):
            self.assertEqual(self.run_request(request)['status'], 'failed')
            self.assertTrue(self.path(subject.SECONDARY).exists())

    def test_sshd_closed_effective_settings_parser(self):
        subject.validate_sshd(SSHD)
        for raw in (SSHD.replace(b'pubkeyauthentication yes', b'pubkeyauthentication no'),
                    SSHD.replace(b'forcecommand none', b'forcecommand /bin/sh'),
                    SSHD.replace(b'permitrootlogin prohibit-password', b'permitrootlogin no'),
                    SSHD.replace(b'.ssh/authorized_keys .ssh/authorized_keys2', b'.ssh/authorized_keys'),
                    SSHD + b'forcecommand none\n'):
            with self.assertRaises(subject.Refused):
                subject.validate_sshd(raw)

    def test_duplicate_json_and_nonfinite_numbers_refused(self):
        for raw in (b'{"action":"install","action":"revoke"}', b'{"x":NaN}'):
            with self.assertRaises(subject.Refused):
                subject.strict_json(raw)

    def test_invalid_cli_input_emits_only_closed_safe_failure(self):
        for raw in (b'PRIVATE_INPUT_NOT_JSON', b'x' * (subject.MAX_REQUEST + 1)):
            output = io.StringIO()
            incoming = types.SimpleNamespace(buffer=io.BytesIO(raw))
            with mock.patch.object(subject.sys, 'argv', ['controller.py']), \
                    mock.patch.object(subject.sys, 'platform', 'linux'), \
                    mock.patch.object(subject.sys, 'stdin', incoming), \
                    mock.patch.object(subject.sys, 'stdout', output), \
                    mock.patch.object(subject.os, 'geteuid', return_value=0):
                self.assertEqual(subject.main(), 2)
            result = json.loads(output.getvalue())
            subject.validate_result(result)
            self.assertEqual(result['error'], 'request_refused')
            self.assertNotIn('PRIVATE_INPUT', output.getvalue())
            self.assertEqual(self.snapshot(), {'root/.ssh/authorized_keys': (0o600, PRIMARY)})

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux renameat2 syscall')
    def test_linux_real_rename_noreplace_preserves_existing_target(self):
        parent = os.open(self.path(subject.SSH_DIR), subject.FLAGS)
        try:
            for name, raw in (('source', b'SOURCE'), ('target', b'TARGET')):
                self.path(subject.SSH_DIR + '/' + name).write_bytes(raw)
            with self.assertRaisesRegex(subject.Refused, 'secondary_exists'):
                subject.rename_noreplace(parent, 'source', 'target')
            self.assertEqual(self.path(subject.SSH_DIR + '/target').read_bytes(), b'TARGET')
            subject.rename_noreplace(parent, 'source', 'new-target')
            self.assertEqual(self.path(subject.SSH_DIR + '/new-target').read_bytes(), b'SOURCE')
            self.assertFalse(self.path(subject.SSH_DIR + '/source').exists())
        finally:
            os.close(parent)


if __name__ == '__main__':
    unittest.main()
