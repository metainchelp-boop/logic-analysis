"""Dispatch/encryption boundary tests; never contact a real Docker host."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('host_probe', ROOT / 'collector_host_probe.py')
host = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(host)


class HostBackupBoundaryTests(unittest.TestCase):
    def test_backup_requires_exact_approval_before_any_command(self):
        with patch.object(host, 'command') as command:
            for value in (None, '', 'approved', 'approved-backup-only-20260921-op2'):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'BACKUP_APPROVAL_REQUIRED'):
                    host.collect({'operation': 'backup_verify', 'approval': value})
            command.assert_not_called()

    def test_unknown_operation_never_falls_back_to_diagnostics(self):
        with patch.object(host, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'INVALID_OPERATION'):
                host.collect({'operation': 'deploy'})
            command.assert_not_called()

    def test_backup_command_is_fixed_and_only_metadata_is_returned(self):
        result = subprocess.CompletedProcess([], 0, json.dumps({'passed': True, 'sha256': 'abc'}).encode(),
                                             b'PRIVATE_STDERR_MUST_NOT_APPEAR')
        with patch.object(host, 'command', return_value=result) as command:
            report = host.collect({'operation': 'backup_verify', 'approval': 'approved-backup-only-20260921-op1',
                                   'backupScript': '# reviewed probe', 'jobDir': '/not-used',
                                   'source': '/not-used', 'command': 'not-used'})
        command.assert_called_once_with(
            ['docker', 'exec', '-i', '-e', 'PYTHONDONTWRITEBYTECODE=1', 'logic-analysis', 'python3', '-',
             '--job-dir', '/app/data/backups/collector-validation-20260921-op1'],
            b'# reviewed probe', timeout=220)
        self.assertEqual(report['mode'], 'APPROVED_NEW_BACKUP_AND_ISOLATED_RESTORE_ONLY')
        self.assertEqual(report['commandExitCode'], 0)
        self.assertTrue(report['backup']['passed'])
        self.assertNotIn('PRIVATE', json.dumps(report))

    def test_failure_is_not_promoted_to_success(self):
        result = subprocess.CompletedProcess([], 1, b'{"passed":false,"error":"PREFLIGHT_FAILED"}', b'private')
        with patch.object(host, 'command', return_value=result):
            report = host.backup_collect({'approval': 'approved-backup-only-20260921-op1', 'backupScript': ''})
        self.assertFalse(report['backup']['passed'])
        self.assertEqual(report['commandExitCode'], 1)

    def test_existing_verification_requires_exact_approval_and_phase(self):
        with patch.object(host, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'BACKUP_APPROVAL_REQUIRED'):
                host.collect({'operation': 'backup_verify_existing'})
            with self.assertRaisesRegex(ValueError, 'INVALID_VERIFICATION_PHASE'):
                host.collect({'operation': 'backup_verify_existing',
                              'approval': 'approved-backup-only-20260921-op1',
                              'verificationPhase': '../source'})
            command.assert_not_called()

    def test_existing_verification_has_no_new_copy_or_arbitrary_path_argument(self):
        for phase in ('digests', 'restored_metadata'):
            result = subprocess.CompletedProcess([], 0, b'{"passed":true}', b'private')
            with self.subTest(phase=phase), patch.object(host, 'command', return_value=result) as command:
                report = host.collect({'operation': 'backup_verify_existing',
                    'approval': 'approved-backup-only-20260921-op1', 'verificationPhase': phase,
                    'backupVerificationScript': '# read-only verifier', 'path': '/ignored'})
                command.assert_called_once_with(
                    ['docker', 'exec', '-i', '-e', 'PYTHONDONTWRITEBYTECODE=1', 'logic-analysis',
                     'python3', '-', '--phase', phase], b'# read-only verifier', timeout=220)
                self.assertEqual(report['mode'], 'READ_ONLY_EXISTING_BACKUP_VERIFICATION')
                self.assertTrue(report['verification']['passed'])
                self.assertEqual(report['commandExitCode'], 0)

    def test_invalid_child_result_is_rejected(self):
        for stdout in (b'private-not-json', b'[]', b'{"passed":"true"}', b'{}'):
            with self.subTest(stdout=stdout), patch.object(host, 'command', return_value=
                    subprocess.CompletedProcess([], 0, stdout, b'private')):
                with self.assertRaises((ValueError, json.JSONDecodeError)):
                    host.backup_collect({'approval': 'approved-backup-only-20260921-op1', 'backupScript': ''})

    def test_encryption_is_preflighted_before_collect(self):
        with patch.object(host, 'collect') as collect, patch.object(host, 'command', return_value=
                subprocess.CompletedProcess([], 1, b'', b'private')):
            with self.assertRaisesRegex(RuntimeError, 'ENCRYPTION_UNAVAILABLE'):
                host.encrypted_main({'certificate': 'synthetic certificate'})
            collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
