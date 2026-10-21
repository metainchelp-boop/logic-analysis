"""Code patch SSH byte pressure and isolation from the historical paired release."""
import ast
import hashlib
from pathlib import Path
import unittest


WORKFLOW = Path(__file__).resolve().parents[2] / '.github/workflows/debug-rank.yml'
HISTORICAL_SHA = '9275078894a8897c602a774a1d95c0298e0b8de445a254b79ff13b2c17103fbe'


def section(text, name):
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line == '  ' + name + ':\n']
    if len(starts) != 1:
        raise ValueError('PATCH_WORKFLOW_SECTION')
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith('  ') and not lines[i].startswith('   ')
                and lines[i].strip().endswith(':')), len(lines))
    return ''.join(lines[start:end])


def pressure_functions():
    workflow = WORKFLOW.read_text()
    part = section(workflow, 'completion-postcompletion-patch')
    first = part.index('          def patch_ssh_scripts(')
    last = part.index('          P.require_pins()', first)
    source = ''.join(line[10:] if line.startswith('          ') else line
                     for line in part[first:last].splitlines(keepends=True))
    tree = ast.parse(source)
    assert [node.name for node in tree.body] == ['patch_ssh_scripts', 'require_patch_ssh_pressure']
    scope = {}
    exec(compile(tree, '<actual-patch-workflow-pressure>', 'exec'), scope)
    return workflow, scope['patch_ssh_scripts'], scope['require_patch_ssh_pressure']


class CompletionPatchWorkflowTests(unittest.TestCase):
    def test_historical_paired_release_job_is_byte_identical(self):
        workflow = WORKFLOW.read_text()
        original = '\n' + section(workflow, 'completion-release').rstrip('\n') + '\n'
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), HISTORICAL_SHA)

    def test_actual_two_scripts_include_both_quoted_exports_and_strict_utf8_limit(self):
        workflow, scripts, require = pressure_functions()
        wire, transport = 'patch-xz-v1:AA==', 'AA=='
        exports = "export COMPLETION_PATCH_B64='" + wire + "'; export COMPLETION_PATCH_TRANSPORT_B64='" + transport + "';\n"
        self.assertEqual(require(wire, transport, workflow),
                         [len((exports + body).encode()) for body in scripts(workflow)])
        self.assertEqual(len(scripts(workflow)), 2)
        self.assertIn('incoming=True', scripts(workflow)[0])
        self.assertIn('transport.execute(bundle)', scripts(workflow)[1])
        bounded = wire + 'A' * (131071 - max(require(wire, transport, workflow)))
        self.assertEqual(max(require(bounded, transport, workflow)), 131071)
        with self.assertRaisesRegex(ValueError, 'COMPLETION_SSH_SIZE'):
            require(bounded + 'A', transport, workflow)
        for unsafe in ("'", '\n', '\x00', '가'):
            with self.subTest(unsafe=repr(unsafe)), self.assertRaisesRegex(ValueError, 'COMPLETION_SSH_ENV'):
                require(wire + unsafe, transport, workflow)

    def test_unknown_ssh_shape_refuses_and_scripts_do_not_load_paired_controller(self):
        workflow, scripts, require = pressure_functions()
        before, marker, tail = workflow.partition('\n  completion-postcompletion-patch:\n')
        changed = before + marker + tail.replace('          script: |\n', '          script: >\n', 1)
        with self.assertRaisesRegex(ValueError, 'COMPLETION_SSH_WORKFLOW'):
            require('patch-xz-v1:AA==', 'AA==', changed)
        for body in scripts(workflow):
            self.assertNotIn("bundle['sources']['controller']", body)
        self.assertIn("bundle['sources']['patch']", scripts(workflow)[1])
        part = section(workflow, 'completion-postcompletion-patch')
        self.assertIn("github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'", part)
        self.assertIn("all(v=='off' for v in inputs.values())", part)
        self.assertIn('persist-credentials: false', part)
        self.assertNotIn('INPUTS_JSON:', part)
        self.assertIn("pathlib.Path(os.environ['GITHUB_EVENT_PATH']).read_text()", part)


if __name__ == '__main__':
    unittest.main()
