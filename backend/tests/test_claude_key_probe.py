"""Synthetic-only checks for a two-boolean, isolated existing-key probe."""
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch


WORKFLOW = Path(__file__).parents[2] / '.github/workflows/debug-rank.yml'
SOURCE = WORKFLOW.read_text()
NAMES = ('ANTHROPIC_API_KEY', 'CLAUDE_API_KEY')
SENTINEL = 'SYNTHETIC_SECRET_MUST_NEVER_APPEAR'


def heredoc(marker):
    start = SOURCE.index("<<'" + marker + "'")
    rest = SOURCE[start:].splitlines()[1:]
    lines = []
    for line in rest:
        if line.strip() == marker:
            return textwrap.dedent('\n'.join(lines)) + '\n'
        lines.append(line)
    raise AssertionError('Missing heredoc terminator')


def jobs():
    body = SOURCE.split('\njobs:\n', 1)[1]
    matches = list(re.finditer(r'^  ([a-z][a-z-]+):$', body, re.M))
    return {match.group(1): body[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(body)]
            for index, match in enumerate(matches)}


def defaults():
    return dict(claude_key_probe=True, ad_prepare='off', ad_expected_baseline='', collector='off',
                rank_link='off', capacity='off', structure='off', expired='off', queue='off',
                urlshape='off', use_branch_code='off')


def run_script(script, environment=None, completed=None, error=None):
    stdout, stderr = io.StringIO(), io.StringIO()
    result = completed or subprocess.CompletedProcess([], 0, b'{"ANTHROPIC_API_KEY":true,"CLAUDE_API_KEY":false}')
    with patch.dict(os.environ, environment or {}, clear=True), \
            patch('subprocess.run', return_value=result, side_effect=error) as call, \
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = 0
        try:
            exec(compile(script, '<synthetic-probe>', 'exec'), {})
        except SystemExit as exc:
            status = exc.code
    return status, stdout.getvalue(), stderr.getvalue(), call


class KeyProbeTest(unittest.TestCase):
    def test_valid_booleans_and_exact_read_only_docker_command(self):
        status, output, errors, call = run_script(heredoc('CLAUDE_KEY_PROBE'))
        self.assertEqual((status, errors), (0, ''))
        self.assertEqual(json.loads(output), {NAMES[0]: True, NAMES[1]: False})
        args, kwargs = call.call_args
        self.assertEqual(args[0][:-1], ['/usr/bin/docker', 'exec', 'logic-analysis', 'python', '-I', '-S', '-B', '-c'])
        self.assertEqual(kwargs, dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, timeout=10, check=False,
                                     env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C'}))
        program = args[0][-1]
        for environment, expected in (({}, [False, False]), ({NAMES[0]: ''}, [False, False]),
                                      ({NAMES[0]: SENTINEL}, [True, False]),
                                      ({name: SENTINEL for name in NAMES}, [True, True])):
            with self.subTest(environment_names=list(environment)):
                child = io.StringIO()
                with patch.dict(os.environ, environment, clear=True), contextlib.redirect_stdout(child):
                    exec(compile(program, '<synthetic-container>', 'exec'), {})
                actual = child.getvalue()
                self.assertNotIn(SENTINEL, actual)
                self.assertEqual(json.loads(actual), dict(zip(NAMES, expected)))

    def test_every_invalid_or_secret_bearing_output_is_sanitized(self):
        bodies = [b'', b'not json', SENTINEL.encode(),
                  json.dumps({NAMES[0]: SENTINEL, NAMES[1]: False}).encode(),
                  b'{"ANTHROPIC_API_KEY":1,"CLAUDE_API_KEY":false}',
                  b'{"ANTHROPIC_API_KEY":null,"CLAUDE_API_KEY":false}',
                  b'{"ANTHROPIC_API_KEY":{},"CLAUDE_API_KEY":false}',
                  b'{"ANTHROPIC_API_KEY":true}',
                  b'{"ANTHROPIC_API_KEY":true,"CLAUDE_API_KEY":false,"extra":false}',
                  b'{"ANTHROPIC_API_KEY":true,"ANTHROPIC_API_KEY":false,"CLAUDE_API_KEY":false}',
                  b'[true,false]', b'\xff', b' ' * 257,
                  b'{"ANTHROPIC_API_KEY":true,"CLAUDE_API_KEY":false}\n' + SENTINEL.encode(),
                  'unexpected decoded string']
        for body in bodies:
            with self.subTest(body_type=type(body).__name__):
                completed = subprocess.CompletedProcess([], 0, body, SENTINEL.encode())
                status, output, errors, _ = run_script(heredoc('CLAUDE_KEY_PROBE'), completed=completed)
                self.assertEqual((status, output, errors), (1, 'CLAUDE_KEY_PROBE_FAILED\n', ''))

    def test_command_failure_timeout_and_exception_never_print_details(self):
        failures = [dict(completed=subprocess.CompletedProcess([], 1, SENTINEL.encode(), SENTINEL.encode())),
                    dict(error=subprocess.TimeoutExpired(SENTINEL, 10, output=SENTINEL, stderr=SENTINEL)),
                    dict(error=OSError(SENTINEL)), dict(error=RuntimeError(SENTINEL))]
        for failure in failures:
            with self.subTest(kind=next(iter(failure))):
                status, output, errors, _ = run_script(heredoc('CLAUDE_KEY_PROBE'), **failure)
                self.assertEqual((status, output, errors), (1, 'CLAUDE_KEY_PROBE_FAILED\n', ''))

    def test_probe_imports_only_stdlib_and_has_one_subprocess(self):
        tree = ast.parse(heredoc('CLAUDE_KEY_PROBE'))
        imports = [name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names]
        self.assertEqual(imports, ['json', 'subprocess', 'sys'])
        self.assertEqual(sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
                             isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess' and
                             node.func.attr == 'run' for node in ast.walk(tree)), 1)
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and
                             node.func.id in ('open', 'eval', '__import__') for node in ast.walk(tree)))


class WorkflowIsolationTest(unittest.TestCase):
    def test_boolean_defaults_disabled_and_pinned_ssh_serialized(self):
        self.assertRegex(SOURCE, r'claude_key_probe:\n        description: [^\n]+\n        type: boolean\n        required: false\n        default: false')
        probe = jobs()['claude-key-probe']
        self.assertIn('group: deploy-logic-analysis\n      cancel-in-progress: false', probe)
        self.assertIn('uses: appleboy/ssh-action@029f5b4aeeeb58fdfe1410a5d17f967dacf36262', probe)
        self.assertIn('uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262', probe)
        self.assertIn('persist-credentials: false', probe)
        for name in ('VPS_HOST', 'VPS_USER', 'VPS_SSH_KEY'):
            self.assertIn('${{ secrets.' + name + ' }}', probe)
        self.assertNotIn('${{ secrets.ANTHROPIC_API_KEY', probe)
        self.assertNotIn('${{ secrets.CLAUDE_API_KEY', probe)
        self.assertEqual(probe.count('uses: appleboy/ssh-action@'), 1)

    def test_all_nine_existing_jobs_are_disabled_before_probe_inputs(self):
        blocks = jobs()
        self.assertEqual(set(blocks), {'claude-key-probe', 'preview-ops', 'preview-start', 'preview-prepare',
                                     'preview-envelope', 'tunnel-native', 'ad-deploy-prepare',
                                     'ad-tunnel-install', 'diagnose', 'learning-center-static'})
        for name, block in blocks.items():
            condition = re.search(r'^    if: (.+)$', block, re.M).group(1)
            if name != 'claude-key-probe':
                self.assertTrue(condition.startswith('${{ !inputs.claude_key_probe && ('), name)
            for mode in ('off', 'inspect', 'prepare', 'preview-code-only-upgrade', 'tunnel-install',
                         'learning-center-static-install'):
                for ref in ('refs/heads/codex/naver-claude-key-probe-20261011',
                            'refs/heads/codex/ad-deploy-prep-20261001', 'refs/heads/master'):
                    for event in ('workflow_dispatch', 'push'):
                        values = defaults()
                        values['ad_prepare'] = mode
                        expression = condition.removeprefix('${{').removesuffix('}}').strip()
                        expression = expression.replace('&&', ' and ').replace('||', ' or ')
                        expression = re.sub(r'!(?!=)', 'not ', expression)
                        active = eval(expression, {'__builtins__': {}, 'true': True, 'false': False},
                                      {'inputs': SimpleNamespace(**values),
                                       'github': SimpleNamespace(event_name=event, ref=ref)})
                        expected = name == 'claude-key-probe' and event == 'workflow_dispatch' and ref.endswith('/codex/naver-claude-key-probe-20261011')
                        self.assertEqual(bool(active), expected, (name, mode, ref, event))

    def test_probe_inputs_accept_only_true_and_all_other_modes_off(self):
        script = heredoc('CLAUDE_PROBE_INPUT')
        omitted_empty_optional = defaults()
        omitted_empty_optional.pop('ad_expected_baseline')
        # GitHub omits an optional default:'' field from toJSON(inputs).
        for values in (defaults(), omitted_empty_optional):
            status, output, errors, call = run_script(script, {'INPUTS_JSON': json.dumps(values)})
            self.assertEqual((status, output, errors), (0, '', ''))
            call.assert_not_called()
        bad = [{}, [], dict(defaults(), claude_key_probe=False), dict(defaults(), claude_key_probe='true'),
               dict(defaults(), claude_key_probe=1), dict(defaults(), ad_expected_baseline='unexpected'),
               dict(defaults(), extra='off')]
        bad.extend(dict(defaults(), **{name: 'on'}) for name in defaults() if name not in ('claude_key_probe', 'ad_expected_baseline'))
        for values in bad:
            with self.subTest(fields=list(values) if isinstance(values, dict) else 'not-dict'):
                status, output, errors, call = run_script(script, {'INPUTS_JSON': json.dumps(values)})
                self.assertEqual((status, output, errors), (1, 'CLAUDE_KEY_PROBE_INPUT_REJECTED\n', ''))
                call.assert_not_called()

    def test_existing_input_validators_remove_false_without_weakening_other_inputs(self):
        # Five multiline parsers, one tunnel parser and two inline parsers.
        self.assertEqual(SOURCE.count("assert inputs.pop('claude_key_probe', False) is False"), 6)
        self.assertEqual(SOURCE.count('assert d.pop("claude_key_probe", False) is False'), 1)
        self.assertEqual(SOURCE.count('assert values.pop("claude_key_probe", False) is False'), 1)
        for variable in ('inputs', 'd', 'values'):
            script = "assert " + variable + ".pop('claude_key_probe', False) is False"
            for present in (False, True):
                values = {'collector': 'on'}
                if present:
                    values['claude_key_probe'] = False
                exec(script, {}, {variable: values})
                self.assertEqual(values, {'collector': 'on'})
            with self.assertRaises(AssertionError):
                exec(script, {}, {variable: {'claude_key_probe': True}})


if __name__ == '__main__':
    unittest.main()
