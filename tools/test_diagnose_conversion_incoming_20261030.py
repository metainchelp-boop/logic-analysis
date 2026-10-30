import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

import diagnose_conversion_incoming_20261030 as diagnostic

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'execute', 'prepare', 'apply', 'rollback', 'trusted_dir', 'current_state', 'mkdir', 'makedirs', 'chmod',
             'chown', 'open', 'write', 'write_bytes', 'write_text', 'write_new', 'unlink', 'remove', 'rmdir', 'rename',
             'replace', 'run', 'command', 'system', 'popen', 'Popen', 'check_output', 'download', 'urlopen', 'lstat'}
ALLOWED_CALLS = {'alarm', 'b64decode', 'sha256', 'hexdigest', 'ModuleType', 'exec', 'decode', 'clear', 'update', 'modules',
                 'validate_package', 'geteuid', 'NativeHost', 'baseline', 'dumps', 'print', 'len', 'type', 'ValueError'}
HARNESS = r'''
import builtins, json, os, sys
probe = sys.stdin.read(); fake = os.environ.pop('FAKE_HOST_BASELINE'); hits = []
def trip(name):
    def refuse(*args, **kwargs):
        hits.append(name); sys.stderr.write('TRIPWIRE:' + name + '\n'); raise AssertionError('TRIPWIRE')
    return refuse
for name in ('mkdir', 'makedirs', 'chmod', 'chown', 'unlink', 'remove', 'rmdir', 'rename', 'replace', 'system'):
    setattr(os, name, trip('os.' + name))
real_open = builtins.open
def guarded_open(file, mode='r', *args, **kwargs):
    if any(flag in mode for flag in 'wax+'):trip('open-write')()
    return real_open(file, mode, *args, **kwargs)
builtins.open = guarded_open
real_exec = builtins.exec
def watched_exec(code, scope=None, local=None):
    real_exec(code, scope, local)
    if isinstance(scope, dict) and {'modules', 'execute', 'decode', 'TRANSPORT_RAW_SHA256'} <= set(scope):
        scope['execute'] = trip('transport.execute'); real_modules = scope['modules']
        def modules(value):
            loaded = real_modules(value)
            for name in ('prepare', 'apply', 'rollback', 'current_state'):setattr(loaded['patch'], name, trip('patch.' + name))
            loaded['release'].trusted_dir = trip('release.trusted_dir'); loaded['release'].write_new = trip('release.write_new')
            loaded['host'].NativeHost = lambda: type('ReadOnlyHost', (), {'baseline': lambda self: fake})()
            return loaded
        scope['modules'] = modules
gates = dict(vars(builtins)); gates['exec'] = watched_exec
real_exec(compile(probe, 'readonly-probe', 'exec'), {'__builtins__': gates, '__name__': 'probe'})
sys.stderr.write('HITS:' + json.dumps(hits) + '\n')
'''


def probe_body():
    return diagnostic.SCRIPT.split("<<'PYCODE'\n", 1)[1].rsplit('PYCODE\n', 1)[0]


class ReadonlyProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wire, cls.boot = diagnostic.build(ROOT)

    def run_probe(self, wire, boot, fake):
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'P22_WIRE': wire, 'P22_BOOT': boot, 'FAKE_HOST_BASELINE': fake}
        result = subprocess.run([sys.executable, '-I', '-B', '-c', HARNESS], input=probe_body(), text=True,
                                capture_output=True, env=env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertNotIn('TRIPWIRE', result.stderr)
        self.assertIn('HITS:[]', result.stderr)
        lines = [l for l in result.stdout.splitlines() if l.startswith('NAVER_CONVERSION_INCOMING_DIAGNOSTIC=')]
        self.assertEqual(len(lines), 1)
        return json.loads(lines[0].split('=', 1)[1])

    def test_probe_calls_only_the_readonly_allowlist(self):
        tree = ast.parse(probe_body())
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertEqual(calls, ALLOWED_CALLS)
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertFalse(names & FORBIDDEN)
        self.assertNotIn('import subprocess', probe_body()); self.assertNotIn('pathlib', probe_body())

    def test_probe_end_to_end_reaches_only_baseline_and_reports_minimal_fields(self):
        for fake, equal in ((diagnostic.CURRENT_BASELINE, True), ('0' * 64, False), (diagnostic.HISTORICAL_BASELINE, False)):
            with self.subTest(fake=fake):
                out = self.run_probe(self.wire, self.boot, fake)
                self.assertEqual(out, {'stage': 'complete', 'root_user': os.geteuid() == 0, 'actual_baseline_sha256': fake,
                                       'current_expected_sha256': diagnostic.CURRENT_BASELINE, 'equal': equal})

    def test_probe_refuses_foreign_transport_or_request_before_host_access(self):
        raw = (ROOT / diagnostic.NS / 'backend/tools/naver_report_progress_transport.py').read_bytes()
        import base64
        tampered = base64.b64encode(raw + b'\n# changed\n').decode()
        self.assertEqual(self.run_probe(self.wire, tampered, diagnostic.CURRENT_BASELINE),
                         {'stage': 'transport', 'error_code': 'COMPLETION_TRANSPORT_SOURCE'})
        out = self.run_probe(self.wire[:-1] + ('0' if self.wire[-1] != '0' else '1'), self.boot, diagnostic.CURRENT_BASELINE)
        self.assertEqual((out['stage'], out['error_code']), ('decode', 'PATCH_ENCODING'))
        for field, value in (('run_id', '40335961943'), ('ciphertext_sha256', 'd' * 64)):
            with self.subTest(field=field), mock.patch.object(diagnostic, 'package', lambda f=field, v=value: {**PACKAGE, f: v}):
                wire, boot = diagnostic.build(ROOT)
                self.assertEqual(self.run_probe(wire, boot, diagnostic.CURRENT_BASELINE), {'stage': 'package', 'error_code': 'PATCH_PACKAGE'})

    def test_real_total_ssh_size_and_minimal_script(self):
        script = len(diagnostic.SCRIPT.encode()); total = diagnostic.ssh_size(self.wire, self.boot)
        exports = "export P22_WIRE='" + self.wire + "'; export P22_BOOT='" + self.boot + "';\n"
        self.assertEqual(total, len((exports + diagnostic.SCRIPT).encode()))
        self.assertLessEqual(script, 2200)
        self.assertLess(total, 131072)
        self.assertEqual((len(self.wire) <= 102400, len(self.boot) <= 32768), (True, True))

    def test_request_is_the_failed_prepare_on_the_current_baseline(self):
        self.assertEqual(diagnostic.package(), PACKAGE)
        self.assertNotIn('download_url', PACKAGE); self.assertNotIn('artifact_sha256', PACKAGE)
        self.assertNotIn(diagnostic.HISTORICAL_BASELINE, json.dumps(PACKAGE))
        source = (ROOT / 'tools/diagnose_conversion_incoming_20261030.py').read_text()
        for word in ('urlopen', 'download(', 'requests', 'runtime-secrets'):
            self.assertNotIn(word, source)

    def test_pins_match_unchanged_base_payload(self):
        for name, digest in diagnostic.PINS.items():
            self.assertEqual(hashlib.sha256((ROOT / diagnostic.NS / name).read_bytes()).hexdigest(), digest, name)
        with mock.patch.dict(diagnostic.PINS, {'bundle.py': '0' * 64}), self.assertRaises(ValueError):
            diagnostic.build(ROOT)

    def test_foreign_context_and_retry_refused(self):
        head = 'a' * 40
        env = dict(GITHUB_REPOSITORY='metainchelp-boop/logic-analysis', GITHUB_REF=diagnostic.REF, GITHUB_EVENT_NAME='push',
                   GITHUB_RUN_ATTEMPT='1', GITHUB_ACTOR='metainchelp-boop', GITHUB_SHA=head)
        event = dict(after=head, ref=diagnostic.REF, forced=False, deleted=False,
                     repository=dict(full_name=env['GITHUB_REPOSITORY'], private=False))
        diagnostic.context(env, event, head)
        for key, value in [('GITHUB_RUN_ATTEMPT', '2'), ('GITHUB_REF', 'refs/heads/codex/naver-conversion-incoming-diagnostic-20261026'),
                           ('GITHUB_ACTOR', 'foreign'), ('GITHUB_SHA', 'b' * 40), ('GITHUB_EVENT_NAME', 'workflow_dispatch')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                diagnostic.context(dict(env, **{key: value}), event, head)
        for key, value in [('forced', True), ('deleted', True), ('after', 'b' * 40)]:
            with self.subTest(event=key), self.assertRaises(ValueError):
                diagnostic.context(env, dict(event, **{key: value}), head)

    def test_workflow_runs_exact_probe_on_new_branch_only(self):
        workflow = (ROOT / diagnostic.WORKFLOW).read_text()
        script = workflow.split('          script: |\n', 1)[1]
        self.assertEqual(script, ''.join('            ' + line if line.strip() else line for line in diagnostic.SCRIPT.splitlines(True)))
        self.assertIn('    branches: [' + diagnostic.BRANCH + ']\n', workflow)
        self.assertIn("github.ref == '" + diagnostic.REF + "' && github.run_attempt == 1", workflow)
        self.assertIn("github.actor == 'metainchelp-boop'", workflow)
        self.assertIn('      group: deploy-logic-analysis\n      cancel-in-progress: false\n', workflow)
        self.assertEqual(workflow.count('uses: appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262'), 1)
        for word in ('scp-action', 'workflow_dispatch', 'pull_request', '20261026'):
            self.assertNotIn(word, workflow)

    def test_exact_base_plus_four_added_files_and_normal_checker_untouched(self):
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        cwd = os.getcwd(); os.chdir(ROOT)
        try:
            diagnostic.source_boundary(head)
        finally:
            os.chdir(cwd)
        spec = importlib.util.spec_from_file_location('gate', ROOT / 'tools/check_conversion_executor.py')
        gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
        # The release gate is not widened: on this diagnostic head it refuses the four extra files.
        with self.assertRaisesRegex(ValueError, '^RELEASE_CHANGE_SET$'):
            gate.verify(ROOT)


PACKAGE = {'baseline': '1a107fb029873d44ccfc09b1001c5d85b3dd5e871c008adeadb516e12b72e3cd',
           'source_commit': 'abceeb737548ada081072df95279d19981b561f7',
           'ciphertext_sha256': '53b9fd97ccf1baf5923af959fd8b7e315df04c51b4440ce12de91a029ad32027',
           'source_tar_gz_sha256': '50681cb0a30db4f421d8555d859b8a050ca5e07e6f5b6f5662ca527c036ef703',
           'run_id': '41023987057', 'operation': 'code-prepare'}

if __name__ == '__main__':
    unittest.main()
