import copy
import importlib.util
import json
from pathlib import Path, PurePosixPath
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('gate', HERE / 'check_conversion_executor.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


class ExecutorBoundaryTests(unittest.TestCase):
    def receipt(self):
        root = HERE.parent / g.NS
        return json.loads((root / 'qualification.json').read_bytes()), json.loads((root / 'release-policy.json').read_bytes())

    def test_real_receipt_and_wrong_run_or_failed_qualification(self):
        receipt, policy = self.receipt()
        g.qualification(receipt, policy)
        changes = [('head', 'a' * 40), ('run_id', '123456789'), ('private', False),
                   ('attempt', True), ('base_files', True), ('deployment_ready', True),
                   ('repository', g.REPO), ('status', 'failure')]
        for name, value in changes:
            with self.subTest(name=name), self.assertRaises(ValueError):
                g.qualification({**receipt, name: value}, policy)
        for name in ('run_conclusion', 'job_conclusion', 'spec_review', 'standards_review'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                g.qualification(receipt, {**policy, name: 'failure'})

    def test_missing_changed_failed_or_extra_skipped_check_rejected(self):
        receipt, policy = self.receipt()
        for name, value in [('skipped', 3), ('errors', 1), ('failures', 1),
                            ('command_sha256', 'a' * 64), ('passed', True),
                            ('expected_skipped_replays', [])]:
            changed = copy.deepcopy(receipt)
            changed['checks'][0][name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                g.qualification(changed, policy)
        with self.assertRaises(ValueError):
            g.qualification({**receipt, 'checks': receipt['checks'][:1]}, policy)

    def test_deployment_requires_exact_release_and_first_manual_attempt(self):
        env = {'GITHUB_REPOSITORY': g.REPO, 'GITHUB_REF': 'refs/heads/' + g.RELEASE,
               'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_RUN_ATTEMPT': '1',
               'GITHUB_SHA': 'b' * 40, 'GITHUB_RUN_ID': '12345678901'}
        event = {'repository': {'full_name': g.REPO}, 'inputs': {
            'ad_prepare': 'preview-report-progress-prepare', 'ad_expected_baseline': '{}'}}
        g.deploy_context(env, event)
        for name, value in [('GITHUB_REPOSITORY', g.PRIVATE_REPO), ('GITHUB_REF', 'refs/heads/main'),
                            ('GITHUB_EVENT_NAME', 'push'), ('GITHUB_RUN_ATTEMPT', '2'),
                            ('GITHUB_SHA', 'bad'), ('GITHUB_RUN_ID', '../123456')]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                g.deploy_context({**env, name: value}, event)
        for inputs in [{**event['inputs'], 'unrelated': 'on'}, {**event['inputs'], 'ad_prepare': 'off'}]:
            with self.assertRaises(ValueError):
                g.deploy_context(env, {**event, 'inputs': inputs})

    def test_original_server_steps_and_transfer_target_preserved(self):
        original = (HERE.parent / g.NS / g.WORKFLOW).read_text()
        wrapper = g.expected_workflow(original)
        tail = original[original.index('      - name: Incoming\n'):]
        shifted = tail.replace('          source: preview-payload/runtime-secrets.cms\n',
                               f'          source: {g.NS}/preview-payload/runtime-secrets.cms\n')
        shifted = shifted.replace('          strip_components: 1\n', '          strip_components: 3\n')
        self.assertEqual(wrapper[wrapper.index('      - name: Incoming\n'):], shifted)
        self.assertEqual(PurePosixPath(g.NS + '/preview-payload/runtime-secrets.cms').parts[3:], ('runtime-secrets.cms',))
        self.assertEqual(wrapper.count('uses: appleboy/ssh-action@'), 2)
        self.assertEqual(wrapper.count('uses: appleboy/scp-action@'), 1)
        self.assertIn('group: deploy-logic-analysis\n      cancel-in-progress: false', wrapper)
        self.assertNotIn('secrets: inherit', wrapper)
        self.assertNotIn('pull_request_target:', wrapper)

    def test_qualified_python_and_public_tools_match_metadata(self):
        receipt, _ = self.receipt()
        root = HERE.parent / g.NS
        self.assertEqual(g.sha((root / 'bundle.py').read_bytes()), receipt['bundle_python_sha256'])
        self.assertEqual(len(receipt['public_files']), 12)
        for name, row in receipt['public_files'].items():
            self.assertNotIn('/fixtures/', name)
            self.assertNotEqual(Path(name).name, 'store.py')
            raw = (root / name).read_bytes()
            self.assertEqual({'bytes': len(raw), 'sha256': g.sha(raw)}, row)

    def test_duplicate_json_symlink_escape_and_size_rejected(self):
        with self.assertRaises(ValueError):
            json.loads('{"status":"pass","status":"fail"}', object_pairs_hook=g.unique)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            (root / 'file').write_bytes(b'abc')
            (root / 'link').symlink_to(root / 'file')
            for name, cap in [('link', 3), ('file', 2), ('missing', 3)]:
                with self.subTest(name=name), self.assertRaises(ValueError):
                    g.read(root, name, cap)


if __name__ == '__main__':
    unittest.main()
