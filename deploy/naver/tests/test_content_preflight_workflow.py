"""Exercise the shipped Bash guard and static transport boundaries without any server."""
import fnmatch
from pathlib import Path
import re
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / '.github/workflows/naver-content-preflight.yml'
CANARY = 'PRIVATE_CUSTOMER_CANARY'


def steps(source):
    return [part for part in re.split(r'(?=^      - )', source, flags=re.MULTILINE)
            if part.startswith('      - ')]


def block(source, key):
    """Read the literal indented shell block, without third-party YAML or execution."""
    match = re.search(r'^( +)' + re.escape(key) + r': \|\n', source, re.MULTILINE)
    if match is None:
        raise AssertionError('Expected literal shell block')
    indentation = len(match[1])
    lines = []
    for line in source[match.end():].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= indentation:
            break
        lines.append(line)
    return textwrap.dedent('\n'.join(lines)) + '\n'


class ContentPreflightWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = WORKFLOW.read_text()
        cls.parts = steps(cls.source)
        cls.guard = block(cls.parts[0], 'run')

    def probe(self, **overrides):
        values = dict(ACTOR='metainchelp-boop', TRIGGERING_ACTOR='metainchelp-boop',
                      REF='refs/heads/main', TARGET_ID='a' * 64,
                      TARGET_IMAGE='sha256:' + 'b' * 64, TARGET_PID='100',
                      HOST_FINGERPRINT='SHA256:' + 'c' * 43)
        values.update(overrides)
        # No inherited BASH_ENV, shell options or external service credentials.
        return subprocess.run(['/bin/bash', '--noprofile', '--norc', '-c', self.guard],
                              env=values, capture_output=True, text=True, timeout=3)

    def rejected(self, **overrides):
        result = self.probe(**overrides)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(CANARY, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')

    def test_pinned_owner_main_target_and_host_key_pass(self):
        result = self.probe()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout + result.stderr, '')

    def test_each_owner_check_and_both_false_fail_independently(self):
        for override in ({'ACTOR': CANARY}, {'TRIGGERING_ACTOR': CANARY},
                         {'ACTOR': CANARY, 'TRIGGERING_ACTOR': CANARY}, {'ACTOR': ''}):
            with self.subTest(override=list(override)):
                self.rejected(**override)

    def test_non_main_ref_is_rejected(self):
        self.rejected(REF='refs/heads/' + CANARY)

    def test_invalid_container_id_is_rejected_without_echoing_input(self):
        for value in ('', 'a' * 63, 'A' * 64, 'a' * 64 + '\n' + CANARY, '../' + CANARY):
            self.rejected(TARGET_ID=value)

    def test_invalid_image_is_rejected_without_echoing_input(self):
        for value in ('', 'sha256:' + 'b' * 63, 'sha256:' + 'b' * 64 + '\n' + CANARY, CANARY):
            self.rejected(TARGET_IMAGE=value)

    def test_pid_format_and_range_are_checked_before_transport(self):
        for value in ('', '0', '-1', '01', '4294967296', '100\n' + CANARY, '1; echo ' + CANARY):
            self.rejected(TARGET_PID=value)
        self.assertEqual(self.probe(TARGET_PID='4294967295').returncode, 0)

    def test_missing_or_invalid_host_key_is_fail_closed(self):
        for value in ('', CANARY, 'SHA256:' + 'c' * 42, 'SHA256:' + 'c' * 43 + '\n' + CANARY):
            self.rejected(HOST_FINGERPRINT=value)

    def test_only_manual_readonly_entrypoint_and_guard_precedes_network(self):
        header = self.source.split('\npermissions:', 1)[0]
        self.assertEqual(re.findall(r'^  ([a-z_]+):', header, re.MULTILINE), ['workflow_dispatch'])
        self.assertIn('contents: read', self.source.split('\nconcurrency:', 1)[0])
        self.assertNotIn('contents: write', self.source)
        self.assertIn('group: deploy-logic-analysis\n  cancel-in-progress: false', self.source)
        self.assertIn('HOST_FINGERPRINT: ${{ secrets.VPS_HOST_FINGERPRINT }}', self.parts[0])
        tests = next(i for i, part in enumerate(self.parts) if 'unittest discover' in part)
        network = [i for i, part in enumerate(self.parts) if 'uses: appleboy/' in part]
        self.assertTrue(network)
        self.assertTrue(all(i > tests > 0 for i in network))
        self.assertIn('persist-credentials: false', self.source)
        self.assertTrue(all(re.fullmatch('[0-9a-f]{40}', version) for version in
                            re.findall(r'uses: [^@\s]+@(\S+)', self.source)))

    def test_every_ssh_and_scp_connection_pins_the_same_required_host_key(self):
        remote = [part for part in self.parts if 'uses: appleboy/' in part]
        self.assertEqual(len(remote), 4)
        for part in remote:
            self.assertIn('fingerprint: ${{ secrets.VPS_HOST_FINGERPRINT }}', part)
            self.assertRegex(part, r'command_timeout: (30|45)s')
        self.assertNotIn('allenvs:', self.source)
        self.assertNotIn('debug: true', self.source)

    def test_single_helper_exclusive_directory_hash_and_timeout_boundaries(self):
        prep = next(part for part in self.parts if 'id: prepare_remote' in part)
        self.assertIn('[ "$(id -u)" = 0 ]', prep)
        self.assertIn('umask 077', prep)
        self.assertIn('mkdir "/tmp/metainc-content-preflight-$NSP_RUN"', prep)
        self.assertNotIn('mkdir -p', prep)
        transfer = next(part for part in self.parts if 'uses: appleboy/scp-action@' in part)
        self.assertIn('source: preflight-ship/content_runtime_preflight.py', transfer)
        self.assertIn('strip_components: 1', transfer)
        self.assertIn('overwrite: false', transfer)
        execute = next(part for part in self.parts if 'CONTENT_RUNTIME_PREFLIGHT=' in part)
        self.assertIn('[ "$(stat -c \'%u:%a\' "$incoming")" = 0:700 ]', execute)
        self.assertIn('[ ! -L "$incoming" ]', execute)
        self.assertIn('[ ! -L "$helper" ]', execute)
        self.assertIn('[ "$(sha256sum "$helper" | cut -d\' \' -f1)" = "$NSP_SHA" ]', execute)
        self.assertIn('timeout -k 1s 20s python3 -I -B "$helper"', execute)
        self.assertIn('2>/dev/null) || rc=$?', execute)
        self.assertIn('case "$rc" in 0|2)', execute)
        self.assertLess(execute.index('trap '), execute.index('sha256sum "$helper"'))
        self.assertNotRegex(self.source, r'docker\s+(stop|rm|exec|build|run)|rm\s+-rf|rsync|sqlite3')

    def test_cleanup_is_ownership_scoped_and_runs_after_transfer_failure(self):
        cleanup = self.parts[-1]
        self.assertIn("if: always() && steps.prepare_remote.outcome == 'success'", cleanup)
        self.assertIn('[ ! -L "$incoming" ]', cleanup)
        self.assertIn('[ "$(stat -c \'%u:%a\' "$incoming")" = 0:700 ]', cleanup)
        self.assertIn('[ ! -L "$helper" ]', cleanup)
        self.assertIn('[ "$(stat -c \'%u\' "$helper")" = 0 ]', cleanup)
        self.assertIn('rm -f -- "$helper" 2>/dev/null', cleanup)
        self.assertIn('rmdir -- "$incoming" 2>/dev/null', cleanup)
        self.assertNotIn('rm -r', cleanup)

    def test_all_embedded_shell_blocks_have_valid_bash_syntax(self):
        for part in self.parts:
            for key in ('run', 'script'):
                if re.search(r'^ +' + key + r': \|$', part, re.MULTILINE):
                    result = subprocess.run(['/bin/bash', '-n'], input=block(part, key),
                                            text=True, capture_output=True, timeout=3)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_new_paths_are_excluded_from_app_deployment_and_pr_checks_include_workflow(self):
        deploy = (ROOT / '.github/workflows/deploy.yml').read_text()
        ignored = re.findall(r"^      - '([^']+)'", deploy, re.MULTILINE)
        paths = ['.github/workflows/deploy.yml', '.github/workflows/naver-tools-check.yml',
                 '.github/workflows/naver-content-preflight.yml', 'deploy/naver/CONTENT_PREFLIGHT.md',
                 'deploy/naver/content_runtime_preflight.py',
                 'deploy/naver/tests/test_content_runtime_preflight.py',
                 'deploy/naver/tests/test_content_preflight_workflow.py']
        for path in paths:
            self.assertTrue(any(fnmatch.fnmatchcase(path, pattern) for pattern in ignored), path)
        checks = (ROOT / '.github/workflows/naver-tools-check.yml').read_text().split('\n  push:', 1)[0]
        self.assertIn("'.github/workflows/naver-content-preflight.yml'", checks)
        self.assertIn("'deploy/naver/**'", checks)


if __name__ == '__main__':
    unittest.main()
