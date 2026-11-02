"""Exercise workflow trust and output gates using synthetic local files only."""
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


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/naver-cold-backup-archive.yml'
CANARY = 'PRIVATE_SYNTHETIC_CANARY'
CONFIRM = 'ARCHIVE_C44_COLD_BACKUP_LOSSLESSLY'
SCOPE = 'c44-cold-backup-lossless-v1'
A377_SCOPE = 'a377-cold-backup-lossless-v1'
A377_CONFIRM = 'ARCHIVE_A377_COLD_BACKUP_LOSSLESSLY'


def blocks(source):
    lines = source.splitlines()
    result = []
    for index, line in enumerate(lines):
        if not re.fullmatch(r'\s+(run|script): \|', line):
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for part in lines[index + 1:]:
            if part.strip() and len(part) - len(part.lstrip()) <= indent:
                break
            body.append(part[indent + 2:])
        result.append('\n'.join(body))
    return result


class ColdBackupArchiveWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()
        cls.blocks = blocks(cls.source)
        cls.guard = cls.blocks[0]
        cls.ship = next(x for x in cls.blocks if 'mkdir -m 755 cold-backup-ship' in x)
        cls.invoke = next(x for x in cls.blocks if 'out=$(python3' in x)
        cls.cleanup = cls.blocks[-1]
        cls.validator = cls.invoke.split("python3 -I -B -c '\n", 1)[1].split("\n' \"$helper\"", 1)[0]

    def gate(self, **values):
        env = dict(PATH=os.environ.get('PATH', ''), ACTOR='metainchelp-boop',
                   TRIGGERING_ACTOR='metainchelp-boop', REF='refs/heads/main', ATTEMPT='1',
                   HOST_FINGERPRINT='SHA256:' + 'c' * 43, SCOPE=SCOPE, MODE='plan', PLAN_SHA='', CONFIRM='')
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', self.guard],
                              env=dict(env, **values), capture_output=True, text=True, timeout=3)

    def assert_refused(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_manual_only_read_permission_and_shared_non_cancelling_group(self):
        header = self.source.split('\npermissions:', 1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):', header, re.M), ['workflow_dispatch'])
        self.assertEqual(re.findall(r'^      ([a-z_0-9]+):', header, re.M),
                         ['scope', 'mode', 'plan_sha256', 'confirm'])
        self.assertIn('options: [c44-cold-backup-lossless-v1, a377-cold-backup-lossless-v1]', header)
        self.assertIn('default: c44-cold-backup-lossless-v1', header)
        self.assertIn('options: [plan, apply]', header)
        self.assertIn('default: plan', header)
        self.assertIn('permissions:\n  contents: read', self.source)
        self.assertIn('group: deploy-logic-analysis\n  cancel-in-progress: false', self.source)
        self.assertNotIn('contents: write', self.source)

    def test_plan_and_explicit_hash_bound_apply_pass_gate(self):
        for values in ({}, dict(MODE='apply', PLAN_SHA='a' * 64, CONFIRM=CONFIRM),
                       dict(SCOPE=A377_SCOPE),
                       dict(SCOPE=A377_SCOPE, MODE='apply', PLAN_SHA='a' * 64, CONFIRM=A377_CONFIRM)):
            result = self.gate(**values)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, '')

    def test_actor_ref_attempt_and_host_pin_fail_closed(self):
        invalid = {
            'SCOPE': ('', CANARY, '../cold', SCOPE + '\n' + CANARY),
            'ACTOR': ('', CANARY, 'metainchelp-boop\n' + CANARY),
            'TRIGGERING_ACTOR': ('', CANARY),
            'REF': ('refs/heads/other', 'refs/tags/main', 'refs/heads/main\n' + CANARY),
            'ATTEMPT': ('2', '', '1\n' + CANARY),
            'HOST_FINGERPRINT': ('', CANARY, 'SHA256:' + 'a' * 42,
                                 'SHA256:' + 'a' * 43 + '\n' + CANARY),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_refused(self.gate(**{field: value}))

    def test_plan_rejects_apply_credentials_and_unlisted_mode(self):
        for values in (dict(PLAN_SHA='a' * 64), dict(CONFIRM=CONFIRM),
                       dict(MODE='restore'), dict(MODE='apply;echo ' + CANARY)):
            self.assert_refused(self.gate(**values))

    def test_apply_rejects_missing_malformed_or_injected_confirmation(self):
        base = dict(MODE='apply', PLAN_SHA='a' * 64, CONFIRM=CONFIRM)
        for field, values in {
            'PLAN_SHA': ('', 'A' * 64, 'a' * 63, 'a' * 64 + '\n' + CANARY,
                         '$(echo ' + CANARY + ')'),
            'CONFIRM': ('', CONFIRM + '\n' + CANARY, '$(echo ' + CANARY + ')'),
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assert_refused(self.gate(**dict(base, **{field: value})))

    def test_synthetic_tests_run_before_any_transport_and_actions_are_pinned(self):
        self.assertIn("-p 'test_cold_backup_archive*.py' -v", self.source)
        self.assertLess(self.source.index('unittest discover'), self.source.index('uses: appleboy/'))
        versions = re.findall(r'uses: [^@\s]+@(\S+)', self.source)
        self.assertEqual(len(versions), 6)
        self.assertTrue(all(re.fullmatch(r'[0-9a-f]{40}', value) for value in versions))
        self.assertEqual(self.source.count('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}'), 4)
        self.assertIn('persist-credentials: false', self.source)
        self.assertNotIn('allenvs:', self.source)
        self.assertNotIn('debug: true', self.source)

    def test_only_single_public_helper_transferred_and_no_operating_artifacts(self):
        self.assertEqual(re.findall(r'^          source: (.+)$', self.source, re.M),
                         ['cold-backup-ship/cold_backup_archive.py'])
        self.assertIn('strip_components: 1', self.source)
        self.assertIn('overwrite: false', self.source)
        self.assertNotRegex(self.source, r'upload-artifact|docker\s+(run|exec|stop|rm|prune)|rsync|sqlite3|\.env')
        self.assertNotIn('secrets.NAVER_PRODUCT', self.source)
        for line in self.invoke.splitlines():
            self.assertNotIn('${{', line)

    def test_public_staging_is_readable_for_scp_other_uid(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            helper = base / 'deploy/naver/cold_backup_archive.py'
            helper.parent.mkdir(parents=True)
            helper.write_text('SYNTHETIC_PUBLIC_HELPER\n')
            bindir = base / 'bin'
            bindir.mkdir()
            sudo = bindir / 'sudo'
            sudo.write_text('#!/bin/sh\n[ "$#" = 3 ] || exit 1\n'
                            'case "$1:$2" in chown:0:0) exit 0;; '
                            'chmod:644) exec chmod "$2" "$3";; *) exit 1;; esac\n')
            sudo.chmod(0o700)
            sha = bindir / 'sha256sum'
            sha.write_text('#!' + sys.executable + '\nimport hashlib,pathlib,sys\np=pathlib.Path(sys.argv[1])\nprint(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+str(p))\n')
            sha.chmod(0o700)
            envfile = base / 'github-env'
            result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', self.ship],
                cwd=base, env=dict(PATH=str(bindir) + os.pathsep + os.environ.get('PATH', ''),
                                  GITHUB_ENV=str(envfile), GITHUB_RUN_ID='1234', GITHUB_RUN_ATTEMPT='1'),
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            target = base / 'cold-backup-ship/cold_backup_archive.py'
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            self.assertEqual(target.parent.stat().st_mode & 0o777, 0o755)
            self.assertEqual(target.read_bytes(), helper.read_bytes())
            self.assertEqual(dict(line.split('=', 1) for line in envfile.read_text().splitlines()),
                {'NCA_SHA': hashlib.sha256(helper.read_bytes()).hexdigest(), 'NCA_RUN': '1234-1'})
            archive = subprocess.run(['tar', '-cf', '-', 'cold-backup-ship/cold_backup_archive.py'],
                                     cwd=base, capture_output=True, timeout=5)
            self.assertEqual(archive.returncode, 0)
            self.assertGreater(len(archive.stdout), 0)

    def test_remote_file_identity_and_hash_checked_before_execute(self):
        invoke = self.invoke
        execute = invoke.index('out=$(python3')
        for guard in ('[ ! -L "$incoming" ]', '[ ! -L "$helper" ]',
                      '"$(stat -c \'%u:%a\' "$incoming")" = 0:700',
                      '"$(stat -c \'%u:%h:%a\' "$helper")" = 0:1:644',
                      '"$(sha256sum "$helper" | cut -d\' \' -f1)" = "$NCA_SHA"'):
            self.assertLess(invoke.index(guard), execute)
        self.assertIn('"$helper" "$NCA_MODE" "$NCA_PLAN" "$NCA_CONFIRM" "$NCA_SCOPE" 2>/dev/null', invoke)
        self.assertIn('command_timeout: 21m', self.source)

    def test_cleanup_targets_only_this_helper_and_empty_temporary_directory(self):
        self.assertNotRegex(self.source, r'rm\s+-rf')
        self.assertIn('rm -f -- "$helper"', self.cleanup)
        self.assertIn('rmdir -- "$incoming"', self.cleanup)
        self.assertIn('0:1:644', self.cleanup)
        self.assertIn('0:700', self.cleanup)
        self.assertIn('always() && steps.prepare_remote.outcome == \'success\'', self.source)
        self.assertNotIn('/var/backups', self.source)
        self.assertNotIn('/var/lib/docker', self.source)

    def validate_output(self, raw, rc='0', *, hash_match=True, same_file=True, scope=SCOPE, helper_source=None):
        # The real extracted validator runs against a synthetic helper. UID is the
        # only normalized stat value so the fixture also runs on a non-root Mac.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'helper.py'
            path.write_text('def validate_report(v,expected_scope=None):\n'
                            '    assert type(v) is dict and set(v)=={"status","scope"}\n'
                            '    assert v["scope"]==expected_scope\n'
                            '    assert v["status"] in ("planned","applied","refused")\n')
            if helper_source is not None:
                path.write_text(helper_source)
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if hash_match else '0' * 64
            real_fstat = os.fstat
            calls = 0

            def normalized_stat(fd):
                nonlocal calls
                calls += 1
                actual = real_fstat(fd)
                fields = {name: getattr(actual, name) for name in
                          ('st_mode', 'st_nlink', 'st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')}
                if not same_file and calls > 1:
                    fields['st_mtime_ns'] += 1
                return SimpleNamespace(st_uid=0, **fields)

            stdout = io.StringIO()
            with patch.object(sys, 'argv', ['-c', str(path), digest, rc, scope]), \
                    patch.object(sys, 'stdin', SimpleNamespace(buffer=io.BytesIO(raw))), \
                    patch.object(os, 'fstat', side_effect=normalized_stat), \
                    contextlib.redirect_stdout(stdout):
                try:
                    exec(compile(self.validator, '<workflow-validator>', 'exec'), {})
                    accepted = True
                except Exception:
                    accepted = False
            self.assertEqual(stdout.getvalue(), '')
            return accepted

    def test_only_closed_receipt_and_exit_status_pairs_accepted(self):
        for status, rc in (('planned', '0'), ('applied', '0'), ('refused', '2')):
            self.assertTrue(self.validate_output(json.dumps({'status': status, 'scope': SCOPE}).encode(), rc))
        for status, rc in (('planned', '2'), ('applied', '2'), ('refused', '0'), ('planned', '1')):
            self.assertFalse(self.validate_output(json.dumps({'status': status, 'scope': SCOPE}).encode(), rc))

    def test_raw_unknown_extra_multiline_and_oversize_output_refused_without_echo(self):
        for raw in (CANARY.encode(), b'', b'{"status":"planned","extra":"' + CANARY.encode() + b'"}',
                    b'{"status":"' + CANARY.encode() + b'"}', b'{"status":"planned"}\n',
                    b' ' * 32769 + b'{"status":"planned"}'):
            self.assertFalse(self.validate_output(raw))

    def test_changed_helper_hash_or_identity_refuses_output(self):
        raw = json.dumps({'status': 'planned', 'scope': SCOPE}).encode()
        self.assertFalse(self.validate_output(raw, hash_match=False))
        self.assertFalse(self.validate_output(raw, same_file=False))

    def test_validation_precedes_only_receipt_publication(self):
        self.assertLess(self.invoke.index('ns["validate_report"](value,expected_scope=scope)'),
                        self.invoke.index("printf 'NAVER_COLD_BACKUP_ARCHIVE_RESULT="))
        self.assertIn('O_NOFOLLOW', self.validator)
        self.assertIn('st_nlink==1', self.validator)
        self.assertIn('hashlib.sha256(code).hexdigest()==expected', self.validator)
        self.assertEqual(self.invoke.count('printf \'NAVER_COLD_BACKUP_ARCHIVE_RESULT='), 1)


    def test_confirmation_is_bound_to_selected_scope(self):
        self.assert_refused(self.gate(SCOPE=A377_SCOPE, MODE='apply', PLAN_SHA='a' * 64, CONFIRM=CONFIRM))
        self.assert_refused(self.gate(SCOPE=SCOPE, MODE='apply', PLAN_SHA='a' * 64, CONFIRM=A377_CONFIRM))

    def test_selected_scope_reaches_remote_helper_and_receipt_validator(self):
        self.assertIn('NCA_SCOPE: ${{ inputs.scope }}', self.source)
        self.assertIn('envs: NCA_RUN,NCA_SHA,NCA_MODE,NCA_PLAN,NCA_CONFIRM,NCA_SCOPE', self.source)
        self.assertIn('"$rc" "$NCA_SCOPE" 2>/dev/null', self.invoke)
        for scope in (SCOPE, A377_SCOPE):
            raw = json.dumps({'status': 'planned', 'scope': scope}).encode()
            self.assertTrue(self.validate_output(raw, scope=scope))
            other = A377_SCOPE if scope == SCOPE else SCOPE
            self.assertFalse(self.validate_output(raw, scope=other))

    def test_actual_public_helper_loads_and_enforces_scope_in_workflow_validator(self):
        source = (ROOT / 'deploy/naver/cold_backup_archive.py').read_text()
        ns = {'__name__': 'workflow_helper_fixture'}
        exec(compile(source, '<public-helper-fixture>', 'exec'), ns)
        for scope in (SCOPE, A377_SCOPE):
            raw = json.dumps(ns['receipt']('plan', scope)).encode()
            self.assertTrue(self.validate_output(raw, '2', scope=scope, helper_source=source))
            other = A377_SCOPE if scope == SCOPE else SCOPE
            self.assertFalse(self.validate_output(raw, '2', scope=other, helper_source=source))

    def test_every_embedded_shell_block_parses(self):
        self.assertEqual(len(self.blocks), 5)
        for script in self.blocks:
            result = subprocess.run(['/bin/bash', '-n'], input=script,
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
