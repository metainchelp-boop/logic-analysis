"""Execute owner/ref/host guards; inspect transport boundaries without a server."""
import fnmatch
from pathlib import Path
import re
import subprocess
import unittest

from test_content_preflight_workflow import block, steps

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/naver-autobid-key-preflight.yml'
CANARY = 'PRIVATE_SYNTHETIC_KEY_CANARY'


class AutobidKeyWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()
        cls.parts = steps(cls.source)
        cls.guard = block(cls.parts[0], 'run')

    def probe(self, **overrides):
        values = dict(ACTOR='metainchelp-boop', TRIGGERING_ACTOR='metainchelp-boop',
                      REF='refs/heads/main', HOST_FINGERPRINT='SHA256:' + 'c' * 43)
        values.update(overrides)
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', self.guard],
                              env=values, capture_output=True, text=True, timeout=3)

    def refused(self, **values):
        result = self.probe(**values)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(CANARY, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')

    def test_exact_owner_main_and_host_pin_pass(self):
        result = self.probe()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout + result.stderr, '')

    def test_initial_actor_is_checked_independently(self):
        for actor in ('', CANARY, 'metainchelp-boop\n' + CANARY):
            self.refused(ACTOR=actor)

    def test_rerun_actor_is_checked_independently_and_both_fail(self):
        self.refused(TRIGGERING_ACTOR=CANARY)
        self.refused(TRIGGERING_ACTOR='')
        self.refused(ACTOR=CANARY, TRIGGERING_ACTOR=CANARY)

    def test_non_main_or_missing_ref_fails(self):
        for ref in ('', 'refs/heads/' + CANARY, 'refs/tags/main', 'refs/heads/main\n' + CANARY):
            self.refused(REF=ref)

    def test_missing_malformed_or_multiline_host_pin_fails(self):
        for pin in ('', CANARY, 'SHA256:' + 'c' * 42, 'SHA256:' + 'c' * 43 + '\n' + CANARY):
            self.refused(HOST_FINGERPRINT=pin)

    def test_no_path_inputs_or_automatic_entrypoint_and_readonly_token(self):
        header = self.source.split('\npermissions:', 1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):', header, re.MULTILINE), ['workflow_dispatch'])
        self.assertNotIn('inputs:', self.source)
        self.assertNotIn('${{ inputs.', self.source)
        self.assertIn('contents: read', self.source)
        self.assertNotIn('contents: write', self.source)
        self.assertIn('group: naver-autobid-key-preflight\n  cancel-in-progress: false', self.source)
        self.assertNotIn('group: deploy-logic-analysis', self.source)

    def test_checks_precede_network_and_action_versions_are_pinned(self):
        tests = next(i for i, part in enumerate(self.parts) if 'unittest discover' in part)
        remote = [i for i, part in enumerate(self.parts) if 'uses: appleboy/' in part]
        self.assertEqual(len(remote), 4)
        self.assertTrue(all(i > tests > 0 for i in remote))
        self.assertIn('persist-credentials: false', self.source)
        versions = re.findall(r'uses: [^@\s]+@(\S+)', self.source)
        self.assertTrue(versions)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{40}', version) for version in versions))

    def test_all_transport_connections_pin_same_required_host_key(self):
        self.assertIn('HOST_FINGERPRINT: ${{ secrets.VPS_HOST_FINGERPRINT }}', self.parts[0])
        for part in self.parts:
            if 'uses: appleboy/' in part:
                self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}', part)
                self.assertRegex(part, r'command_timeout: (30|45)s')
        self.assertNotIn('allenvs:', self.source)
        self.assertNotIn('debug: true', self.source)

    def test_only_public_helper_is_shipped_and_hash_checked(self):
        ship = next(part for part in self.parts if 'mkdir preflight-ship' in part)
        self.assertIn('cp deploy/naver/autobid_key_metadata.py preflight-ship/', ship)
        self.assertIn('sudo chown 0:0 preflight-ship/autobid_key_metadata.py', ship)
        self.assertLess(ship.index('sudo chown 0:0'), ship.index('NSP_SHA='))
        transfer = next(part for part in self.parts if 'uses: appleboy/scp-action@' in part)
        self.assertIn('source: preflight-ship/autobid_key_metadata.py', transfer)
        self.assertIn('strip_components: 1', transfer)
        self.assertIn('overwrite: false', transfer)
        run = next(part for part in self.parts if 'AUTOBID_KEY_METADATA=' in part)
        self.assertIn('[ "$(sha256sum "$helper" | cut -d\' \' -f1)" = "$NSP_SHA" ]', run)
        self.assertIn('timeout -k 1s 20s python3 -I -B "$helper" 2>/dev/null', run)
        self.assertIn('envs: NSP_RUN,NSP_SHA', run)
        self.assertIn('case "$rc" in 0|2)', run)
        self.assertNotIn('"$helper" --', run)
        self.assertNotRegex(self.source, r'docker\s+(stop|rm|exec|build|run)|rm\s+-rf|rsync|sqlite3|/root/|\.env')

    def test_exclusive_private_directory_and_scoped_cleanup(self):
        prep = next(part for part in self.parts if 'id: prepare_remote' in part)
        self.assertIn('[ "$(id -u)" = 0 ]', prep)
        self.assertIn('[ ! -L /tmp ]', prep)
        self.assertIn('umask 077', prep)
        self.assertIn('mkdir "/tmp/metainc-autobid-key-preflight-$NSP_RUN"', prep)
        self.assertNotIn('mkdir -p', prep)
        run = next(part for part in self.parts if 'AUTOBID_KEY_METADATA=' in part)
        self.assertIn('[ ! -L "$incoming" ]', run)
        self.assertIn('[ "$(stat -c \'%u:%a\' "$incoming")" = 0:700 ]', run)
        self.assertIn('[ ! -L "$helper" ]', run)
        self.assertIn('[ "$(stat -c \'%u\' "$helper")" = 0 ]', run)
        cleanup = self.parts[-1]
        self.assertIn("if: always() && steps.prepare_remote.outcome == 'success'", cleanup)
        for part in (run, cleanup):
            self.assertIn('rm -f -- "$helper" 2>/dev/null', part)
            self.assertIn('rmdir -- "$incoming" 2>/dev/null', part)
            self.assertNotIn('rm -r', part)
        self.assertIn('[ ! -L "$helper" ]', cleanup)
        self.assertIn('[ "$(stat -c \'%u\' "$helper")" = 0 ]', cleanup)
        self.assertIn('AUTOBID_KEY_PREFLIGHT_CLEANUP_INCOMPLETE', cleanup)

    def test_every_embedded_shell_block_parses_in_bash(self):
        for part in self.parts:
            for key in ('run', 'script'):
                if re.search(r'^ +' + key + r': \|$', part, re.MULTILINE):
                    result = subprocess.run(['/bin/bash', '-n'], input=block(part, key),
                                            text=True, capture_output=True, timeout=3)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_changed_paths_are_excluded_from_deployment_and_pr_ci_covers_workflow(self):
        deploy = (ROOT / '.github/workflows/deploy.yml').read_text()
        ignored = re.findall(r"^      - '([^']+)'", deploy, re.MULTILINE)
        paths = ['.github/workflows/deploy.yml', '.github/workflows/naver-tools-check.yml',
                 '.github/workflows/naver-autobid-key-preflight.yml',
                 'deploy/naver/autobid_key_metadata.py', 'deploy/naver/AUTOBID_KEY_PREFLIGHT.md',
                 'deploy/naver/tests/test_autobid_key_metadata.py',
                 'deploy/naver/tests/test_autobid_key_preflight_workflow.py',
                 'docs/superpowers/specs/2026-11-02-autobid-key-location-design.md']
        for path in paths:
            self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in ignored), path)
        checks = (ROOT / '.github/workflows/naver-tools-check.yml').read_text().split('\n  push:', 1)[0]
        self.assertIn("'.github/workflows/naver-autobid-key-preflight.yml'", checks)
        self.assertIn("'deploy/naver/**'", checks)


if __name__ == '__main__':
    unittest.main()
