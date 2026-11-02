"""Execute workflow trust/asset/cleanup boundaries with synthetic local files only."""
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_content_preflight_workflow import block, steps

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/naver-image-preservation.yml'
CANARY = 'PRIVATE_SYNTHETIC_VALUE_CANARY'
ASSETS = ('retirement_preserve_source.py', 'recovery-public.asc', 'server-b-known-hosts')
PYTHON = shutil.which('python3')


class RetirementPreservationWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()
        cls.parts = steps(cls.source)
        cls.guard = block(cls.parts[0], 'run')
        cls.invoke = block(next(p for p in cls.parts if 'out=$(timeout' in p), 'script')
        cls.cleanup = block(cls.parts[-1], 'script')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.incoming = self.base / 'incoming'
        self.incoming.mkdir(mode=0o700)
        self.fakebin = self.base / 'bin'
        self.fakebin.mkdir()
        self.env = dict(PATH=str(self.fakebin) + os.pathsep + os.environ.get('PATH', ''),
                        ACTOR='metainchelp-boop', TRIGGERING_ACTOR='metainchelp-boop',
                        REF='refs/heads/main', HOST_FINGERPRINT='SHA256:' + 'c' * 43,
                        NRP_RUN='1234-1', NRP_PHASE='prepare',
                        TEST_INCOMING=str(self.incoming), TEST_UID='0')
        self.program('id', "import os\nprint(os.environ['TEST_UID'])\n")
        self.program('stat', """import os, stat, sys
s = os.lstat(sys.argv[-1])
fields = {'%u': os.environ['TEST_UID'], '%a': format(stat.S_IMODE(s.st_mode), 'o'), '%h': str(s.st_nlink)}
print(':'.join(fields[p] for p in sys.argv[2].split(':')))
""")
        self.program('sha256sum', "import hashlib, pathlib, sys\np = pathlib.Path(sys.argv[1])\nprint(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p))\n")
        self.program('timeout', "import os, sys\nos.execvp(sys.argv[4], sys.argv[4:])\n")
        self.set_report(self.report())
        for name in ASSETS[1:]:
            path = self.incoming / name
            path.write_text('SYNTHETIC_PUBLIC_ASSET\n')
            path.chmod(0o600)
        self.hash_assets()

    def program(self, name, code):
        path = self.fakebin / name
        path.write_text('#!' + PYTHON + '\n' + code)
        path.chmod(0o700)

    def set_helper(self, code):
        path = self.incoming / ASSETS[0]
        path.write_text(code)
        path.chmod(0o600)

    def report(self):
        return dict(phase='prepare', status='prepared', session='ad-image-20261102-v1',
                    error=None, ssh_public_key=None, image_size_bytes=103807861,
                    bytes=None, sha256=None, process_rc=None, backup_verified=False)

    def set_report(self, payload, rc=0):
        self.set_helper('import sys\nprint(' + repr(json.dumps(payload)) + ')\nsys.exit(' + str(rc) + ')\n')

    def hash_assets(self):
        for name, field in zip(ASSETS, ('NRP_HELPER_SHA', 'NRP_PUBLIC_SHA', 'NRP_HOSTS_SHA')):
            self.env[field] = hashlib.sha256((self.incoming / name).read_bytes()).hexdigest()

    def run_shell(self, script, **values):
        script = script.replace('"/tmp/metainc-image-preservation-$NRP_RUN"', '"$TEST_INCOMING"')
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', script],
                              env=dict(self.env, **values), capture_output=True,
                              text=True, timeout=5)

    def assert_refused(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(CANARY, result.stdout + result.stderr)

    def test_owner_main_pin_and_each_phase_pass(self):
        for phase in ('prepare', 'send', 'cleanup'):
            result = self.run_shell(self.guard, NRP_PHASE=phase)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, '')

    def test_initial_and_rerun_actor_each_fail_closed(self):
        for field in ('ACTOR', 'TRIGGERING_ACTOR'):
            for value in ('', CANARY, 'metainchelp-boop\n' + CANARY):
                self.assert_refused(self.run_shell(self.guard, **{field: value}))

    def test_non_main_malformed_pin_and_unlisted_phase_are_refused(self):
        for field, values in {
            'REF': ('', 'refs/tags/main', 'refs/heads/main\n' + CANARY),
            'HOST_FINGERPRINT': ('', CANARY, 'SHA256:' + 'c' * 42, 'SHA256:' + 'c' * 43 + '\n' + CANARY),
            'NRP_PHASE': ('', 'delete', 'send\n' + CANARY, 'send;echo ' + CANARY),
        }.items():
            for value in values:
                self.assert_refused(self.run_shell(self.guard, **{field: value}))

    def test_only_manual_phase_choice_and_serial_non_cancelling_group(self):
        header = self.source.split('\npermissions:', 1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):', header, re.MULTILINE), ['workflow_dispatch'])
        self.assertEqual(re.findall(r'^      ([a-z_]+):', header, re.MULTILINE), ['phase'])
        self.assertIn('type: choice', header)
        self.assertIn('options: [prepare, send, cleanup]', header)
        self.assertIn('contents: read', self.source)
        self.assertNotIn('contents: write', self.source)
        self.assertIn('group: naver-image-preservation\n  cancel-in-progress: false', self.source)
        self.assertNotIn('group: deploy-logic-analysis', self.source)

    def test_preservation_tests_before_transport_and_pinned_actions(self):
        checked = next(i for i, p in enumerate(self.parts) if "unittest discover -s deploy/naver/tests -p 'test_retirement_*.py' -v" in p)
        remote = [i for i, p in enumerate(self.parts) if 'uses: appleboy/' in p]
        self.assertEqual(len(remote), 4)
        self.assertTrue(all(i > checked > 0 for i in remote))
        self.assertIn('persist-credentials: false', self.source)
        for version in re.findall(r'uses: [^@\s]+@(\S+)', self.source):
            self.assertRegex(version, r'^[0-9a-f]{40}$')
        for i in remote:
            self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}', self.parts[i])
        self.assertNotIn('allenvs:', self.source)
        self.assertNotIn('debug: true', self.source)

    def test_transfer_contains_exactly_three_public_assets(self):
        part = next(p for p in self.parts if 'uses: appleboy/scp-action@' in p)
        source = re.search(r'^          source: (.+)$', part, re.MULTILINE)[1]
        self.assertEqual(source.split(','), ['preservation-ship/' + name for name in ASSETS])
        self.assertIn('strip_components: 1', part)
        self.assertIn('overwrite: false', part)
        ship = next(p for p in self.parts if 'mkdir preservation-ship' in p)
        self.assertLess(ship.index('chmod 600'), ship.index('sudo chown 0:0'))
        for name in ('NRP_HELPER_SHA=', 'NRP_PUBLIC_SHA=', 'NRP_HOSTS_SHA='):
            self.assertLess(ship.index(name), ship.index('sudo chown 0:0'))
        self.assertNotRegex(self.source, r'docker\s+(stop|rm|exec|build|run)|rm\s+-rf|rsync|sqlite3|/root/|\.env')
        self.assertNotIn('upload-artifact', self.source)

    def test_runner_finishes_permission_changes_and_hashes_before_ownership_transfer(self):
        # Simulate root ownership making files unreadable to the ordinary runner.
        # No sudo/root access is used by this synthetic test.
        self.program('sudo', """import pathlib, sys
if sys.argv[1:3] != ['chown', '0:0']:
    raise SystemExit(1)
for name in sys.argv[3:]:
    pathlib.Path(name).chmod(0)
""")
        target = self.base / 'deploy/naver'
        (target / 'preservation').mkdir(parents=True)
        for name in ASSETS:
            source = target / name if name.endswith('.py') else target / 'preservation' / name
            source.write_text('SYNTHETIC_PUBLIC_ASSET\n')
        ship = block(next(p for p in self.parts if 'mkdir preservation-ship' in p), 'run')
        env_file = self.base / 'github-env'
        result = subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', ship],
                                env=dict(self.env, GITHUB_ENV=str(env_file),
                                         GITHUB_RUN_ID='1234', GITHUB_RUN_ATTEMPT='1'),
                                cwd=self.base, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout + result.stderr, '')
        values = dict(line.split('=', 1) for line in env_file.read_text().splitlines())
        expected = hashlib.sha256(b'SYNTHETIC_PUBLIC_ASSET\n').hexdigest()
        for field in ('NRP_HELPER_SHA', 'NRP_PUBLIC_SHA', 'NRP_HOSTS_SHA'):
            self.assertEqual(values[field], expected)
        self.assertEqual(values['NRP_RUN'], '1234-1')

    def test_matching_assets_execute_exact_phase_with_metadata_output(self):
        result = self.run_shell(self.invoke)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        prefix, payload = result.stdout.strip().split('=', 1)
        self.assertEqual(prefix, 'RETIREMENT_PRESERVATION')
        self.assertEqual(json.loads(payload)['phase'], 'prepare')

    def test_each_tampered_asset_prevents_helper_execution(self):
        self.set_helper('print(' + repr(CANARY) + ')\n')
        self.hash_assets()
        for name in ASSETS:
            with self.subTest(asset=name):
                path = self.incoming / name
                before = path.read_bytes()
                path.write_bytes(before + b'# tampered\n')
                self.assert_refused(self.run_shell(self.invoke))
                path.write_bytes(before)

    def test_untrusted_run_digest_phase_owner_and_mode_prevent_execution(self):
        self.set_helper('print(' + repr(CANARY) + ')\n')
        self.hash_assets()
        for field, value in (('NRP_RUN', '1234-1\n' + CANARY), ('NRP_HELPER_SHA', 'f' * 64 + '\n'),
                             ('NRP_PHASE', CANARY), ('TEST_UID', '1000')):
            self.assert_refused(self.run_shell(self.invoke, **{field: value}))
        (self.incoming / ASSETS[1]).chmod(0o644)
        self.assert_refused(self.run_shell(self.invoke))

    def test_linked_asset_is_rejected(self):
        target = self.base / 'outside-public'
        target.write_text(CANARY)
        path = self.incoming / ASSETS[1]
        path.unlink()
        path.symlink_to(target)
        self.assert_refused(self.run_shell(self.invoke))
        self.assert_refused(self.run_shell(self.cleanup))
        self.assertEqual(target.read_text(), CANARY)

    def test_failed_helper_stdout_and_stderr_are_not_published(self):
        self.set_helper("import sys\nprint(" + repr(CANARY) + ")\nprint(" + repr(CANARY) + ", file=sys.stderr)\nsys.exit(1)\n")
        self.hash_assets()
        self.assert_refused(self.run_shell(self.invoke))

    def test_success_exit_does_not_publish_unvalidated_output(self):
        for output in (CANARY, CANARY + '\n{}', json.dumps({'unexpected': CANARY}), 'x' * 4097):
            self.set_helper('print(' + repr(output) + ')\n')
            self.hash_assets()
            result = self.run_shell(self.invoke)
            self.assert_refused(result)
            self.assertIn('RETIREMENT_PRESERVATION_OUTPUT_REFUSED', result.stdout)

    def test_output_shape_and_value_types_fail_closed(self):
        for key, value in (('session', CANARY), ('phase', 'send'), ('status', CANARY),
                           ('error', CANARY), ('ssh_public_key', CANARY), ('bytes', CANARY),
                           ('sha256', CANARY), ('image_size_bytes', True),
                           ('process_rc', {'docker': CANARY}), ('backup_verified', True)):
            payload = self.report()
            payload[key] = value
            self.set_report(payload)
            self.hash_assets()
            self.assert_refused(self.run_shell(self.invoke))

    def test_failure_report_is_public_metadata_and_keeps_failure_exit(self):
        payload = self.report()
        payload.update(status='failed', error='source_refused')
        self.set_report(payload, rc=2)
        self.hash_assets()
        result = self.run_shell(self.invoke)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout.split('=', 1)[1]), payload)
        self.assertEqual(result.stderr, '')

    def test_cleanup_only_removes_public_assets_and_empty_directory(self):
        result = self.run_shell(self.cleanup)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.incoming.exists())
        cleanup_step = self.parts[-1]
        self.assertIn("if: always() && steps.prepare_remote.outcome == 'success'", cleanup_step)
        self.assertNotIn('"$helper"', cleanup_step)
        self.assertNotIn('ad-image-20261102-v1', cleanup_step)
        self.assertNotIn('rm -r', cleanup_step)

    def test_cleanup_unknown_entry_is_preserved_and_reported_incomplete(self):
        unexpected = self.incoming / 'unrelated'
        unexpected.write_text(CANARY)
        result = self.run_shell(self.cleanup)
        self.assert_refused(result)
        self.assertIn('RETIREMENT_PRESERVATION_CLEANUP_INCOMPLETE', result.stdout)
        self.assertEqual(unexpected.read_text(), CANARY)

    def test_helper_temporary_directory_must_be_exclusive_private_and_owned(self):
        prepare = next(p for p in self.parts if 'id: prepare_remote' in p)
        self.assertIn('umask 077', prepare)
        self.assertIn('[ ! -L /tmp ]', prepare)
        self.assertIn('mkdir "/tmp/metainc-image-preservation-$NRP_RUN"', prepare)
        self.assertNotIn('mkdir -p', prepare)
        self.incoming.chmod(0o755)
        self.assert_refused(self.run_shell(self.invoke))
        self.assert_refused(self.run_shell(self.cleanup))

    def test_every_embedded_shell_block_parses(self):
        for part in self.parts:
            for key in ('run', 'script'):
                if re.search(r'^ +' + key + r': \|$', part, re.MULTILINE):
                    result = subprocess.run(['/bin/bash', '-n'], input=block(part, key),
                                            text=True, capture_output=True, timeout=3)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_preservation_changes_never_trigger_app_deploy_and_ci_covers_workflow(self):
        deploy = (ROOT / '.github/workflows/deploy.yml').read_text()
        ignored = re.findall(r"^      - '([^']+)'", deploy, re.MULTILINE)
        paths = ['.github/workflows/deploy.yml', '.github/workflows/naver-tools-check.yml',
                 '.github/workflows/naver-image-preservation.yml',
                 'deploy/naver/retirement_preserve_source.py', 'deploy/naver/retirement_receive.py',
                 'deploy/naver/preservation/recovery-public.asc',
                 'deploy/naver/preservation/server-b-known-hosts',
                 'deploy/naver/tests/test_retirement_preservation_workflow.py']
        for path in paths:
            self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in ignored), path)
        checks = (ROOT / '.github/workflows/naver-tools-check.yml').read_text().split('\n  push:', 1)[0]
        self.assertIn("'.github/workflows/naver-image-preservation.yml'", checks)
        self.assertIn("'deploy/naver/**'", checks)


if __name__ == '__main__':
    unittest.main()
