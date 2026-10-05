"""Code-only deployment sequencing; no operating DB or service is used."""
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared


class CodeOnlyTest(unittest.TestCase):
    def scenario(self, failure=None, mode='apply'):
        return shared.ContractTest().scenario(failure, mode, code_only=True)

    def test_unreviewed_release_refuses_before_any_host_action(self):
        code = shared.load('naver_preview_code_upgrade')
        policy = shared.load('naver_preview_code_only')
        for name in ('prepare', 'apply'):
            with self.subTest(name=name):
                adapters = [Mock() for _ in range(4)]
                with self.assertRaisesRegex(ValueError, '^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                    getattr(policy, name)({}, *adapters, code)
                for adapter in adapters:
                    self.assertEqual(adapter.mock_calls, [])

    def test_success_changes_only_code_without_database_access_or_source_warmup(self):
        result, commands, writes, _, state = self.scenario()
        self.assertIsInstance(result, dict, str(result))
        self.assertTrue(result['ok'])
        self.assertEqual(state, {'engine': 'b'*40, 'relay': 'b'*40})
        self.assertEqual(result['database_policy'], 'preserve-in-place')
        self.assertFalse(result['database_opened_by_controller'])
        self.assertFalse(result['database_snapshot_verified'])
        self.assertFalse(result['source_warmup_performed'])
        self.assertFalse(result['rollback_requires_matching_database'])
        self.assertNotIn('database_schema', result)
        self.assertNotIn('source_status', result)
        self.assertFalse(any('exec' in args or 'run' in args for args in commands))
        self.assertFalse(any(p.name == 'bootstrap-request.json' or p.parent.name == 'secrets'
                             for p, _ in writes))

    def test_prepare_builds_without_stopping_services_or_opening_any_database(self):
        with patch.object(shared.sqlite3, 'connect', side_effect=AssertionError('DB access forbidden')):
            result, commands, _, restored, state = self.scenario(mode='prepare')
        self.assertIsInstance(result, dict, str(result))
        self.assertFalse(result['services_started'])
        self.assertTrue(restored)
        self.assertEqual(set(state.values()), {shared.load('naver_preview_code_upgrade').OLD_COMMIT})
        self.assertEqual(sum(args[:2] == ['docker', 'build'] for args in commands), 2)
        self.assertFalse(any(args[:2] in (['/usr/bin/systemctl', 'stop'], ['/usr/bin/systemctl', 'start'])
                             for args in commands))

    def test_partial_failures_restore_only_old_code_and_keep_existing_guards(self):
        for failure in ('recreate', 'start', 'stop', 'probe'):
            with self.subTest(failure=failure), patch.object(
                    shared.sqlite3, 'connect', side_effect=AssertionError('DB access forbidden')):
                result, commands, _, restored, state = self.scenario(failure)
                self.assertEqual(str(result), 'CODE_ONLY_FAILED_ROLLED_BACK')
                self.assertTrue(restored)
                self.assertEqual(set(state.values()), {shared.load('naver_preview_code_upgrade').OLD_COMMIT})
                self.assertNotIn('PRIVATE_ERROR_SENTINEL', str(result))
                self.assertTrue(result.failure_details['failed_stage'].startswith('code_'))
                self.assertFalse(any('exec' in args or 'run' in args for args in commands))

    def test_unproved_stop_or_failed_rollback_does_not_restart_old_services(self):
        for failure in ('stop_writer_running', 'rollback_writer_running', 'rollback_recreate'):
            with self.subTest(failure=failure):
                result, commands, _, _, _ = self.scenario(failure)
                self.assertEqual(str(result), 'CODE_ROLLBACK_FAILED')
                self.assertEqual(commands[-2:], [
                    ['/usr/bin/systemctl', 'stop', 'metainc-naver-relay.service'],
                    ['/usr/bin/systemctl', 'stop', 'metainc-naver-engine.service']])

    def test_schema_infrastructure_or_unapproved_scope_is_rejected_before_stop(self):
        for failure in ('image', 'unit', 'manifest', 'schema', 'infrastructure', 'override',
                        'bootstrap_pending', 'old_source', 'unapproved_code', 'unapproved_new'):
            with self.subTest(failure=failure):
                result, commands, writes, _, _ = self.scenario(failure)
                self.assertIsInstance(result, Exception)
                self.assertEqual(writes, [])
                self.assertFalse(any(args[:2] == ['/usr/bin/systemctl', 'stop'] for args in commands))

    def test_review_is_bound_to_each_release_pin_and_cannot_be_set_by_input(self):
        code = shared.load('naver_preview_code_upgrade')
        policy = shared.load('naver_preview_code_only')
        pins = (code.OLD_COMMIT, code.TARGET_COMMIT, code.OLD_SOURCE_SHA256, code.TARGET_SOURCE_SHA256,
                code.STORE_SHA256['old'], code.STORE_SHA256['target'], code.EXPECTED_BASELINE)
        for index in range(len(pins)):
            changed = list(pins)
            changed[index] = '0'*len(pins[index])
            with self.subTest(index=index), patch.object(policy, 'REVIEWED_TRANSITION', tuple(changed)):
                adapters = [Mock() for _ in range(4)]
                with self.assertRaisesRegex(ValueError, '^CODE_ONLY_RELEASE_NOT_REVIEWED$'):
                    policy.apply({'REVIEWED_TRANSITION': pins}, *adapters, code)
                self.assertTrue(all(not adapter.mock_calls for adapter in adapters))

    def test_changed_bootstrap_refuses_old_code_restart_without_repairing_data(self):
        result, commands, _, _, _ = self.scenario('bootstrap_changed')
        self.assertEqual(str(result), 'CODE_ROLLBACK_FAILED')
        # Initial target recreations are allowed; rollback must not recreate the old writer.
        self.assertEqual(sum('--force-recreate' in args for args in commands), 2)
        self.assertEqual(result.failure_details['rollback_stage'], 'code_rollback')
        self.assertEqual(result.failure_details['rollback_operation'], 'rollback_state')

    def test_host_or_source_drift_before_rollback_refuses_old_code_restart(self):
        for failure, expected in (('rollback_host_changed', 'CODE_POST_STATE'),
                                  ('rollback_source_changed', 'CODE_STORE_CHANGED')):
            with self.subTest(failure=failure):
                result, commands, _, _, _ = self.scenario(failure)
                self.assertEqual(str(result), 'CODE_ROLLBACK_FAILED')
                self.assertEqual(sum('--force-recreate' in args for args in commands), 2)
                self.assertEqual(result.failure_details['rollback_error_code'], expected)
                self.assertEqual(commands[-2:], [
                    ['/usr/bin/systemctl', 'stop', 'metainc-naver-relay.service'],
                    ['/usr/bin/systemctl', 'stop', 'metainc-naver-engine.service']])

    def test_failure_reporting_never_exposes_untrusted_error_text(self):
        policy = shared.load('naver_preview_code_only')
        code = shared.load('naver_preview_code_upgrade')
        for label in ('CODE_ONLY_RELEASE_NOT_REVIEWED', 'CODE_ONLY_FAILED_ROLLED_BACK'):
            self.assertEqual(policy.failure_report(ValueError(label), code)['error_code'], label)
        self.assertEqual(policy.failure_report(RuntimeError('PRIVATE_ERROR_SENTINEL'), code)['error_code'],
                         'UNRECOGNIZED')

    def test_current_workflow_cannot_activate_the_unreviewed_path(self):
        workflow = (shared.Path(__file__).parents[2]/'.github/workflows/debug-rank.yml').read_text()
        self.assertNotIn('naver_preview_code_only', workflow)
        self.assertIn("'preview-code-upgrade':('naver_preview_code_upgrade','apply')", workflow)


if __name__ == '__main__':
    unittest.main()
