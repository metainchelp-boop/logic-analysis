import copy
import importlib.util
import json
from pathlib import Path, PurePosixPath
import tempfile
import unittest
import unittest.mock

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

    def test_actual_run_pressure_packages_preserve_reserved_ids_without_urls(self):
        source = dict(baseline='a' * 64, source_commit='b' * 40,
                      source_tar_gz_sha256='c' * 64, ciphertext_sha256='d' * 64,
                      download_url='https://example.invalid/private', artifact_sha256='e' * 64)
        event = {'inputs': {'ad_prepare': 'preview-report-progress-prepare',
                            'ad_expected_baseline': json.dumps(source)}}
        rows = g.operation_packages({'GITHUB_RUN_ID': '40335961943'}, event)
        self.assertEqual([x[0] for x in rows], ['prepare', 'apply', 'rollback'])
        self.assertEqual(rows[0][1]['run_id'], '40335961943')
        self.assertEqual(rows[1][1]['operation_id'], g.APPLY_ID)
        self.assertEqual(rows[2][1]['apply_operation_id'], g.APPLY_ID)
        self.assertEqual(rows[2][1]['operation_id'], g.ROLLBACK_ID)
        self.assertNotIn('download_url', rows[0][1])
        self.assertNotIn('artifact_sha256', rows[0][1])
        for name, package in rows[1:]:
            inputs = {'ad_prepare': 'preview-report-progress-' + name,
                      'ad_expected_baseline': json.dumps(package)}
            self.assertEqual(g.operation_packages({'GITHUB_RUN_ID': '99999999999'}, {'inputs': inputs}), rows)
            for changed in (dict(package, operation_id='f' * 32), dict(package, unexpected=True)):
                with self.assertRaises(ValueError):
                    g.operation_packages({}, {'inputs': {**inputs, 'ad_expected_baseline': json.dumps(changed)}})
        for invalid in ('../40335961943', '', True, '12345'):
            with self.assertRaises(ValueError):g.operation_packages({'GITHUB_RUN_ID': invalid}, event)

    def test_baseline_transition_receipt_fields_cannot_be_weakened(self):
        receipt, policy = self.receipt()
        for field, value in [('passed', True), ('tests', 6), ('skipped', 1),
                             ('current_baseline', receipt['transition']['historical_baseline']),
                             ('manifest_sha256', '0' * 64)]:
            changed = copy.deepcopy(receipt); changed['transition'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):g.qualification(changed, policy)
        changed = copy.deepcopy(receipt); changed['transition']['extra'] = True
        with self.assertRaises(ValueError):g.qualification(changed, policy)

    def test_pressure_gate_precedes_download_and_all_server_steps(self):
        workflow = (HERE.parent / g.WORKFLOW).read_text()
        order = [workflow.index(x) for x in ('name: Verify exact qualified release before building wire',
                                            'name: Bundle', 'name: Incoming', 'name: Transfer', 'name: Patch')]
        self.assertEqual(order, sorted(order))
        source = (HERE / 'check_conversion_executor.py').read_text()
        self.assertLess(source.index('receipt = verify(ROOT)'), source.index('pressure(ROOT, os.environ, event)'))
        self.assertLess(source.index('deploy_context(os.environ, event)'), source.index('pressure(ROOT, os.environ, event)'))

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


class PoolFirstBoundaryTests(unittest.TestCase):
    """New pool-first release: exact private identity, proof, IDs and public digests."""

    def receipt(self):
        root = HERE.parent / g.NS
        return json.loads((root / 'qualification.json').read_bytes()), json.loads((root / 'release-policy.json').read_bytes())

    def refused(self, receipt, policy):
        with self.assertRaises(ValueError):
            g.qualification(receipt, policy)

    def test_wrong_or_previous_ref_scope_head_tree_and_run_refused(self):
        receipt, policy = self.receipt()
        g.qualification(receipt, policy)
        self.assertEqual((receipt['ref'], receipt['qualification_scope']), (g.PRIVATE_REF, g.QUALIFICATION_SCOPE))
        for name, value in [('ref', 'refs/heads/codex/naver-conversion-baseline-transition-20261026'),
                            ('ref', 'refs/heads/main'), ('ref', g.PRIVATE_REF + 'x'),
                            ('qualification_scope', 'baseline_transition_bundle_checks_private_only'),
                            ('qualification_scope', 'unchanged_bundle_checks_private_only'),
                            ('report_progress_job_sha256', '2fbaa5d3087483f4c1b6e362329b7539ae14e7aad9caa9b4d319f5217fa2f857'),
                            ('bundle_python_sha256', '8d75bd0583897db0d66780e8bc8e1c06fc65b7de60837fadf08b7ee2ff5aedea'),
                            ('base_manifest_sha256', '0' * 64), ('private_fixtures', 8)]:
            with self.subTest(name=name, value=value):
                self.refused({**receipt, name: value}, policy)
        # Even a self-consistent policy cannot move the pinned private head, tree or run.
        for name, value in [('head', '49275594f9c9344afd403b32f129756194423e1b'), ('tree', '565025160b2519e9e7c31596dbf01af266248d5e'),
                            ('run_id', '40344629727')]:
            with self.subTest(binding=name):
                self.refused({**receipt, name: value}, {**policy, 'private_' + name: value})
                self.refused(receipt, {**policy, 'private_' + name: value})

    def test_receipt_and_policy_field_sets_are_exact(self):
        receipt, policy = self.receipt()
        for key in ('pool_first', 'transition', 'public_files'):
            changed = dict(receipt); changed.pop(key)
            with self.subTest(missing=key):
                self.refused(changed, policy)
        self.refused({**receipt, 'extra': True}, policy)
        for key in ('private_artifact_id', 'private_job_id', 'trust_boundary'):
            changed = dict(policy); changed.pop(key)
            with self.subTest(policy_missing=key):
                self.refused(receipt, changed)
        for name, value in [('extra', 1), ('private_artifact_sha256', 'x'), ('private_job_id', '1'),
                            ('private_fixture_bodies_exported', 1), ('secret_values_copied', 1), ('schema', 'other')]:
            with self.subTest(policy=name):
                self.refused(receipt, {**policy, name: value})

    def test_missing_or_tampered_pool_first_fields_refused(self):
        receipt, policy = self.receipt()
        self.assertEqual(receipt['pool_first'], g.POOL_FIRST)
        for key in g.POOL_FIRST:
            changed = copy.deepcopy(receipt); changed['pool_first'].pop(key)
            with self.subTest(missing=key):
                self.refused(changed, policy)
        for key, value in [('base', '0' * 40), ('manifest_sha256', 'f04d341fc6b84c24634739104cb7195e28f7751a099ac2fdc1ef2e6139975512'),
                           ('command_sha256', '0' * 64), ('old_commit', '89a924f2416f0450f38854b531bdf8778558dca6'),
                           ('target_commit', 'c44a66393340314796851f4dd524dad523bd5415'), ('private_fixtures_added', 0),
                           ('private_fixtures_added', True), ('reserved_apply_operation_id', 'd43ebab98f5941f08146490e48e71aab'),
                           ('reserved_rollback_operation_id', 'cb95f18a925e4637a8c5c7ac7b4583d0')]:
            changed = copy.deepcopy(receipt); changed['pool_first'][key] = value
            with self.subTest(key=key, value=value):
                self.refused(changed, policy)
        changed = copy.deepcopy(receipt); changed['pool_first']['extra'] = 0
        self.refused(changed, policy)

    def test_wrong_counts_or_skips_in_any_suite_refused(self):
        receipt, policy = self.receipt()
        for suite in ('pool_first', 'transition'):
            tests = receipt[suite]['tests']
            for key, value in [('tests', tests - 1), ('tests', tests + 1), ('passed', tests - 1), ('skipped', 1),
                               ('failures', 1), ('errors', 1), ('tests', float(tests)), ('passed', True)]:
                changed = copy.deepcopy(receipt); changed[suite][key] = value
                with self.subTest(suite=suite, key=key, value=value):
                    self.refused(changed, policy)
        self.assertEqual((receipt['transition']['tests'], receipt['pool_first']['tests']), (7, 20))
        for index, key, value in [(0, 'skipped', 3), (0, 'skipped_cases', 2), (1, 'skipped', 1), (1, 'passed', 108)]:
            changed = copy.deepcopy(receipt); changed['checks'][index][key] = value
            with self.subTest(check=index, key=key):
                self.refused(changed, policy)

    def test_old_reserved_operation_ids_refused(self):
        self.assertEqual((g.APPLY_ID, g.ROLLBACK_ID), ('01330a7419d0494d8bfb74ec1fcb7e28', 'ba912f5af5d34a6985d9415013f90486'))
        release = dict(operation='code-prepare', baseline='a' * 64, source_commit='b' * 40,
                       source_tar_gz_sha256='c' * 64, ciphertext_sha256='d' * 64, run_id='41017595072')
        old_apply, old_rollback = 'd43ebab98f5941f08146490e48e71aab', 'cb95f18a925e4637a8c5c7ac7b4583d0'
        cases = [('apply', {'release': release, 'operation_id': old_apply}),
                 ('rollback', {'release': release, 'apply_operation_id': old_apply, 'operation_id': g.ROLLBACK_ID}),
                 ('rollback', {'release': release, 'apply_operation_id': g.APPLY_ID, 'operation_id': old_rollback}),
                 ('rollback', {'release': release, 'apply_operation_id': old_apply, 'operation_id': old_rollback})]
        for name, package in cases:
            inputs = {'ad_prepare': 'preview-report-progress-' + name, 'ad_expected_baseline': json.dumps(package)}
            with self.subTest(name=name, package=package), self.assertRaisesRegex(ValueError, 'RESERVED_'):
                g.operation_packages({}, {'inputs': inputs})
        with unittest.mock.patch.object(g, 'APPLY_ID', old_apply), self.assertRaisesRegex(ValueError, 'RESERVED_IDENTITY'):
            g.pool_first_identity(HERE.parent)

    def test_tampered_public_file_hashes_refused(self):
        receipt, policy = self.receipt()
        root = HERE.parent / g.NS
        for name, row in g.PUBLIC_FILES.items():
            raw = (root / name).read_bytes()
            self.assertEqual({'bytes': len(raw), 'sha256': g.sha(raw)}, row, name)
        for name in ('backend/tools/naver_report_progress_patch.py', 'backend/tools/naver_report_progress_transport.py',
                     'backend/tools/naver_preview_completion_release.py'):
            for field, value in (('sha256', '0' * 64), ('bytes', 1)):
                changed = copy.deepcopy(receipt); changed['public_files'][name][field] = value
                with self.subTest(name=name, field=field):
                    self.refused(changed, policy)
        changed = copy.deepcopy(receipt); changed['public_files'].pop('backend/tools/naver_report_progress_patch.py')
        self.refused(changed, policy)
        manifest = json.loads((root / 'public-files.json').read_bytes())
        for name, row in receipt['public_files'].items():
            self.assertEqual(manifest[g.NS + '/' + name], row)

    def test_added_fixture_identity_matches_the_qualified_controller(self):
        g.pool_first_identity(HERE.parent)
        self.assertEqual(len(g.POOL_FIRST_FIXTURES), g.POOL_FIRST['private_fixtures_added'])
        for name, value in [('fixtures/c44a66393340314796851f4dd524dad523bd5415/naver_runtime/report_output_schema.py', (420, 10231, '0' * 64)),
                            ('fixtures/abceeb737548ada081072df95279d19981b561f7/naver_runtime/report_output_schema.py', (420, 10447, '109b76c3ec0af340491842657a0902dd1aa05112dde089499b2bbfc4981a56fd'))]:
            with self.subTest(name=name), unittest.mock.patch.dict(g.POOL_FIRST_FIXTURES, {name: value}), self.assertRaises(ValueError):
                g.pool_first_identity(HERE.parent)


if __name__ == '__main__':
    unittest.main()
