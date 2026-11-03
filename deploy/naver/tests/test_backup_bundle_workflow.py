import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_cold_backup_archive_workflow import blocks
import test_backup_bundle as T

B = T.B

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/naver-backup-bundle.yml'
CANARY = 'PRIVATE_SYNTHETIC_BUNDLE_CANARY'


class BundleWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()
        cls.blocks = blocks(cls.text)
        cls.guard = cls.blocks[0]
        cls.prepare = next(s for s in cls.blocks if 'INPUT_JSON' in s)
        cls.input_code = cls.prepare.split("<<'PYCODE'\n", 1)[1].split('\nPYCODE', 1)[0]
        cls.invoke = next(s for s in cls.blocks if 'out=$(python3' in s)
        cls.validator = cls.invoke.split("python3 -I -B -c '\n", 1)[1].split("\n' \"$helper\"", 1)[0]

    def gate(self, **updates):
        env = dict(PATH=os.environ.get('PATH', ''), ACTOR='metainchelp-boop',
                   TRIGGERING_ACTOR='metainchelp-boop', REF='refs/heads/main', ATTEMPT='1',
                   HOST_FINGERPRINT='SHA256:' + 'a' * 43)
        env.update(updates)
        return subprocess.run(['/bin/bash', '-c', self.guard], env=env, capture_output=True, timeout=3)

    def test_owner_main_host_first_attempt_concurrency_and_no_automatic_dispatch(self):
        self.assertEqual(self.gate().returncode, 0)
        for key, values in dict(ACTOR=[CANARY], TRIGGERING_ACTOR=[CANARY], REF=['refs/heads/other'],
                                ATTEMPT=['2'], HOST_FINGERPRINT=['', CANARY]).items():
            for value in values:
                result = self.gate(**{key: value})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(CANARY.encode(), result.stdout + result.stderr)
        self.assertIn('group: deploy-logic-analysis\n  cancel-in-progress: false', self.text)
        self.assertIn('contents: read', self.text)
        self.assertIn('options: [diagnose, plan, apply]', self.text)
        self.assertNotRegex(self.text, r'contents: write|workflow_run|schedule:|pull_request:')
        for action in re.findall(r'uses: ([^\n]+)', self.text):
            self.assertRegex(action, r'@[0-9a-f]{40}\Z')

    def test_closed_plan_input_rejects_paths_hash_mismatch_and_does_not_log_values(self):
        plan = T.ClosedPlanTests().plan()
        for mode, raw, digest, confirm, accepted in (
                ('plan', '', '', '', True),
                ('diagnose', '', '', '', True),
                ('apply', B.A.canonical(plan), B.hash_object(plan), B.CONFIRM, True),
                ('apply', B.A.canonical(plan), '0' * 64, B.CONFIRM, False),
                ('plan', CANARY, '', '', False),
                ('diagnose', CANARY, '', '', False),
                ('diagnose', '', '0' * 64, '', False),
                ('diagnose', '', '', B.CONFIRM, False),
                ('apply', json.dumps(dict(plan, path=CANARY)), '0' * 64, B.CONFIRM, False),
                ('apply', 'x' * 8193, '0' * 64, B.CONFIRM, False)):
            with self.subTest(mode=mode, accepted=accepted), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'environment'
                env = dict(os.environ, INPUT_MODE=mode, INPUT_JSON=raw, INPUT_PLAN=digest,
                           INPUT_CONFIRM=confirm, GITHUB_ENV=str(output))
                result = subprocess.run([sys.executable, '-I', '-B', '-c', self.input_code],
                    env=env, cwd=ROOT, capture_output=True, timeout=5)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                self.assertNotIn(CANARY.encode(), result.stdout + result.stderr)
                self.assertEqual(result.stdout, b'')
                if accepted:
                    self.assertRegex(output.read_text(), r'\ANBB_PLAN_B64=[A-Za-z0-9+/=]*\n\Z')

    def validate(self, raw, rc='2', good_hash=True):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for name in ('backup_bundle.py', 'cold_backup_archive.py'):
                (directory / name).write_bytes((ROOT / 'deploy/naver' / name).read_bytes())
            helper = directory / 'backup_bundle.py'
            digest = hashlib.sha256(helper.read_bytes()).hexdigest() if good_hash else '0' * 64
            original = os.fstat
            def normalized(fd):
                s = original(fd)
                values = {k: getattr(s, k) for k in ('st_mode', 'st_nlink', 'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
                return SimpleNamespace(st_uid=0, **values)
            with patch.object(sys, 'argv', ['-c', str(helper), digest, rc]), \
                    patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(raw))), \
                    patch.object(os, 'fstat', side_effect=normalized), contextlib.redirect_stdout(io.StringIO()) as output:
                try:
                    exec(compile(self.validator, 'workflow-validator', 'exec'), {})
                    accepted = True
                except Exception:
                    accepted = False
            self.assertEqual(output.getvalue(), '')
            return accepted

    def test_exact_closed_output_and_source_hash_gate_before_public_result(self):
        raw = B.A.canonical(B.receipt('plan')).encode()
        self.assertTrue(self.validate(raw))
        self.assertFalse(self.validate(raw, rc='0'))
        self.assertFalse(self.validate(raw, good_hash=False))
        for value in (raw + b'\n', CANARY.encode(), b'', b'x' * 16385,
                      B.A.canonical(dict(B.receipt('plan'), extra=CANARY)).encode()):
            self.assertFalse(self.validate(value))
        observed = dict(B.receipt('diagnose'), status='observed', reason='METADATA_READY',
                        reference_checks=1, protected_unchanged=True)
        self.assertTrue(self.validate(B.A.canonical(observed).encode(), rc='0'))
        self.assertFalse(self.validate(B.A.canonical(observed).encode(), rc='2'))
        refused = dict(B.receipt('diagnose'), reason='PROC_LIMIT', limit_diagnostic=dict(
                       kind='maps_bytes', cap=B.MAX_MAPS, observed_lower_bound=B.MAX_MAPS + 1))
        self.assertTrue(self.validate(B.A.canonical(refused).encode()))
        for invalid in (dict(observed, compressed_bytes=1), dict(observed, archive_started=True),
                        dict(refused, version=1), dict(refused, limit_diagnostic=dict(
                            refused['limit_diagnostic'], path=CANARY)),
                        dict(refused, limit_diagnostic=dict(kind=CANARY, cap=1, observed_lower_bound=2))):
            self.assertFalse(self.validate(B.A.canonical(invalid).encode(),
                                          rc='0' if invalid['status'] == 'observed' else '2'))
        self.assertLess(self.invoke.index('ns["validate_report"](value)'), self.invoke.index("printf 'NAVER_BACKUP_BUNDLE_RESULT="))
        self.assertEqual(self.invoke.count("printf 'NAVER_BACKUP_BUNDLE_RESULT="), 1)

    def test_shipping_cleanup_and_deployment_exclusion_are_fixed(self):
        self.assertIn('source: backup-bundle-ship/backup_bundle.py,backup-bundle-ship/cold_backup_archive.py', self.text)
        self.assertIn('overwrite: false', self.text)
        self.assertIn('persist-credentials: false', self.text)
        self.assertEqual(self.text.count('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}'), 4)
        self.assertNotRegex(self.text, r'upload-artifact|docker\s+(run|exec|stop|rm|prune)|rsync|sqlite3|\.env(?:\W|$)|rm\s+-rf')
        self.assertNotIn('/var/backups', self.text)
        self.assertIn('rm -f -- "$incoming/backup_bundle.py" "$incoming/cold_backup_archive.py"', self.blocks[-1])
        self.assertIn('0:700', self.blocks[-1])
        self.assertIn('command_timeout: 21m', self.text)
        deploy = (ROOT / '.github/workflows/deploy.yml').read_text().split('workflow_dispatch:', 1)[0]
        self.assertIn("      - '.github/workflows/naver-backup-bundle.yml'", deploy)
        tests = (ROOT / '.github/workflows/naver-tools-check.yml').read_text()
        self.assertIn("'.github/workflows/naver-backup-bundle.yml'", tests.split('  push:', 1)[0])

    def test_all_shell_blocks_parse(self):
        for script in self.blocks:
            result = subprocess.run(['/bin/bash', '-n'], input=script, text=True, capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
