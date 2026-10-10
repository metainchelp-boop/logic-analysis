"""V9 post-success rollback with synthetic adapters and no operating DB.

Commit/archive pins are the reviewed 96 -> 798 values. Only Store bytes and their
in-memory review hash are synthetic; no container, service or network is used.
"""
import json
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_code_rollback as previous


OLD = '7985925dcc4ed9d75c28ae43a456964cdc78c63f'
TARGET = 'bd08fd07281ae5448bffb3de3d7c405887bfecd9'
OLD_ARCHIVE = '47632d4d3403c24dd4988b80c1a0ada25cc155fc6048a7f2413fb72d84ea73ff'
TARGET_ARCHIVE = '6b1618ab9dd47eca6030d1092bdbce1d451d30ce8fdf103e448a96f3ac9da3f1'
STORE = 'f33f8ca29633ae6cda46fd721d9cbf3bdf63969ac69059434a1a159562778862'
HOST = '5463ca7b23575f668062e842f551170937239e625fb5a6104655c031c7e31d76'
PATHS = frozenset({'compose.naver-engine.yml', 'naver_engine/inventory.py', 'naver_engine/management_store.py'})
TRANSITION = (OLD, TARGET, OLD_ARCHIVE, TARGET_ARCHIVE, STORE, STORE, HOST, PATHS)


class V9PostSuccessRollbackTest(unittest.TestCase):
    fixture = previous.PostSuccessRollbackTest.fixture

    def v9_fixture(self, fault=None):
        return self.fixture(fault, code_module='naver_preview_code_upgrade_v9')

    def run_fixture(self, f):
        # Tripwires cover inherited DB/snapshot/warmup entry points as well as
        # sqlite3.connect in the shared runner. All service adapters are mocks.
        with patch.object(f['code'], 'db_snapshot', side_effect=AssertionError('DB snapshot forbidden')), \
                patch.object(f['code'], 'restore_db', side_effect=AssertionError('DB restore forbidden')), \
                patch.object(f['code'], 'warm_sources', side_effect=AssertionError('warmup forbidden')), \
                patch.object(f['code'], 'verify_database_schema', side_effect=AssertionError('DB schema forbidden')), \
                patch.object(f['code'], 'database_contract', side_effect=AssertionError('DB contract forbidden')):
            return previous.PostSuccessRollbackTest.run_fixture(self, f)

    def assert_untouched(self, f):
        self.assertEqual(f['commands'], [])
        self.assertEqual(f['writes'], [])
        f['upgrade'].replace_unit.assert_not_called()
        for path, body in f['historical_bytes'].items():
            self.assertEqual(path.read_bytes(), body)

    def test_production_v9_exact_reverse_transition_is_reviewed_without_repins(self):
        helper = shared.load('naver_preview_code_rollback')
        policy = shared.load('naver_preview_code_only')
        code = shared.load('naver_preview_code_upgrade_v9')
        self.assertEqual(helper.transition(code), TRANSITION)
        self.assertIn(TRANSITION, helper.REVIEWED_ROLLBACKS)
        self.assertEqual(policy.REVIEWED_TRANSITION_V9, TRANSITION[:-1])
        self.assertEqual(policy.code_module_name(TARGET), 'naver_preview_code_upgrade_v9')
        helper.require_review(policy, code)
        self.assertEqual(code.TEST_PATHS, frozenset())

    def test_v9_success_returns_to_original798_images_units_and_preserves_all_receipts(self):
        f = self.v9_fixture()
        self.assertEqual((f['code'].OLD_COMMIT, f['code'].TARGET_COMMIT), (OLD, TARGET))
        self.assertEqual((f['code'].OLD_SOURCE_SHA256, f['code'].TARGET_SOURCE_SHA256),
                         (OLD_ARCHIVE, TARGET_ARCHIVE))
        self.assertEqual(f['code'].EXPECTED_BASELINE, HOST)
        self.assertEqual(f['code'].CODE_PATHS, PATHS)
        self.assertEqual(f['old'].name, 'naver-' + OLD)
        self.assertEqual(f['new'].name, 'naver-' + TARGET)
        self.assertEqual(f['saved']['source_commit'], OLD)
        self.assertEqual(f['saved']['target_commit'], TARGET)
        self.assertEqual(f['saved']['images'], {'engine': 'sha256:' + '1' * 64,
                                              'relay': 'sha256:' + '2' * 64})
        result = self.run_fixture(f)
        self.assertTrue(result['ok'])
        self.assertEqual(result['source_commit'], OLD)
        self.assertEqual(result['previous_commit'], TARGET)
        self.assertEqual(result['apply_operation_id'], '9' * 32)
        self.assertEqual(result['operation_id'], '8' * 32)
        self.assertEqual(set(f['state'].values()), {OLD})
        self.assertEqual(result['database_policy'], 'preserve-in-place')
        for field in ('database_opened_by_controller', 'source_warmup_performed', 'nginx_changed'):
            self.assertIs(result[field], False)
        self.assertEqual(len(f['writes']), 2)
        attempt_path, attempt_raw = f['writes'][0]
        result_path, result_raw = f['writes'][1]
        self.assertEqual(attempt_path.name, 'code-post-rollback-' + '8' * 32 + '.json')
        self.assertEqual(result_path.name, 'code-post-rollback-' + '8' * 32 + '.result.json')
        self.assertEqual(json.loads(attempt_raw), dict(source_commit=TARGET, target_commit=OLD,
            apply_operation_id='9' * 32, operation_id='8' * 32, database_policy='preserve-in-place'))
        self.assertEqual(json.loads(result_raw), result)
        for path, body in f['historical_bytes'].items():
            self.assertEqual(path.read_bytes(), body)
        for path, body in f['old_files'].items():
            self.assertEqual(path.read_bytes(), body)
        for call in f['upgrade'].replace_unit.call_args_list:
            path, expected_new, original_old, request_id, release = call.args
            self.assertIn(TARGET.encode(), expected_new)
            self.assertIn(OLD.encode(), original_old)
            self.assertEqual(original_old, f['old_files'][path])
            self.assertEqual(request_id, '8' * 32)
            self.assertIs(release, f['release'])
        recreates = [args for args in f['commands'] if '--force-recreate' in args]
        self.assertEqual(len(recreates), 2)
        self.assertTrue(all(str(f['old']) in args and '--no-start' in args and '--no-build' in args
                            for args in recreates))
        self.assertFalse(any(any(word in args for word in ('build', 'pull', 'exec', 'run'))
                             or 'nginx' in ' '.join(args) for args in f['commands']))
        self.assertEqual(f['commands'][:2], [['/usr/bin/systemctl', 'stop', unit]
                         for unit in reversed(f['lifecycle'].UNITS)])
        self.assertEqual([args[2] for args in f['commands'] if args[:2] == ['/usr/bin/systemctl', 'start']],
                         list(f['lifecycle'].UNITS))
        self.assertEqual([event[0] for event in f['events'] if event[0] in ('stopped', 'recreate')],
                         ['stopped', 'stopped', 'recreate', 'recreate'])

    def test_v9_pin_scope_and_store_mutations_refuse_before_any_adapter(self):
        for mutation in ('old', 'target', 'old_archive', 'target_archive', 'store_old',
                         'store_target', 'paths_extra', 'paths_missing', 'test_paths', 'host_pin'):
            f = self.v9_fixture()
            if mutation == 'old': f['code'].OLD_COMMIT = '0' * 40
            if mutation == 'target': f['code'].TARGET_COMMIT = '0' * 40
            if mutation == 'old_archive': f['code'].OLD_SOURCE_SHA256 = '0' * 64
            if mutation == 'target_archive': f['code'].TARGET_SOURCE_SHA256 = '0' * 64
            if mutation == 'store_old': f['code'].STORE_SHA256['old'] = '0' * 64
            if mutation == 'store_target': f['code'].STORE_SHA256['target'] = '0' * 64
            if mutation == 'paths_extra': f['code'].CODE_PATHS |= {'naver_runtime/writer.py'}
            if mutation == 'paths_missing': f['code'].CODE_PATHS -= {'naver_engine/inventory.py'}
            if mutation == 'test_paths': f['code'].TEST_PATHS = frozenset({'backend/tests/extra.py'})
            if mutation == 'host_pin': f['code'].EXPECTED_BASELINE = '0' * 64
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'NOT_REVIEWED'):
                self.run_fixture(f)
            f['host'].baseline.assert_not_called()
            f['upgrade'].manifest.assert_not_called()
            self.assert_untouched(f)

    def test_v9_request_and_apply_identity_tampering_refuse_before_host(self):
        for mutation in ('extra', 'same_id', 'apply_id_path', 'new_id_bad', 'forward_operation',
                         'target', 'archive', 'baseline'):
            f = self.v9_fixture()
            if mutation == 'extra': f['package']['force'] = True
            if mutation == 'same_id': f['package']['operation_id'] = f['package']['apply_operation_id']
            if mutation == 'apply_id_path': f['package']['apply_operation_id'] = '../other-apply'
            if mutation == 'new_id_bad': f['package']['operation_id'] = '8' * 31
            if mutation == 'forward_operation': f['package']['release']['operation'] = 'upgrade-prepare'
            if mutation == 'target': f['package']['release']['source_commit'] = OLD
            if mutation == 'archive': f['package']['release']['source_tar_gz_sha256'] = OLD_ARCHIVE
            if mutation == 'baseline': f['package']['release']['baseline'] = '0' * 64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.run_fixture(f)
            f['host'].baseline.assert_not_called()
            self.assert_untouched(f)

    def test_v9_recovery_and_started_receipt_tampering_refuse_before_stop(self):
        for mutation in ('old_image', 'old_unit', 'old_source', 'target_source', 'recovery_db',
                         'extra_recovery', 'apply_binding', 'started_source', 'started_previous',
                         'started_stage', 'started_ok', 'started_db', 'started_warmup'):
            f = self.v9_fixture()
            if mutation == 'old_image': f['saved']['images']['engine'] = 'sha256:' + '3' * 64
            if mutation == 'old_unit': f['saved']['units'][next(iter(f['saved']['units']))] = TARGET
            if mutation == 'old_source': f['saved']['source_commit'] = '49c42d645b90732071d0c61b8f9aaf7660e8b765'
            if mutation == 'target_source': f['saved']['target_commit'] = OLD
            if mutation == 'recovery_db': f['saved']['database_policy'] = 'replace'
            if mutation == 'extra_recovery': f['saved']['force'] = True
            if mutation == 'apply_binding': f['started']['operation_id'] = '7' * 32
            if mutation == 'started_source': f['started']['source_commit'] = OLD
            if mutation == 'started_previous': f['started']['previous_commit'] = TARGET
            if mutation == 'started_stage': f['started']['stage'] = 'prepared'
            if mutation == 'started_ok': f['started']['ok'] = False
            if mutation == 'started_db': f['started']['database_opened_by_controller'] = True
            if mutation == 'started_warmup': f['started']['source_warmup_performed'] = True
            f['saved_path'].write_text(json.dumps(f['saved']))
            f['started_path'].write_text(json.dumps(f['started']))
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'CODE_ROLLBACK_(RECOVERY|STARTED)'):
                self.run_fixture(f)
            self.assertEqual(f['commands'], [])
            self.assertEqual(f['writes'], [])

    def test_v9_other_apply_uuid_cannot_reuse_matching_recovery_data(self):
        f = self.v9_fixture()
        other_id = '7' * 32
        other_recovery = f['saved_path'].with_name('code-upgrade-' + other_id + '.json')
        other_recovery.write_bytes(f['saved_path'].read_bytes())
        f['package']['apply_operation_id'] = other_id
        with self.assertRaisesRegex(ValueError, '^CODE_ROLLBACK_STARTED$'):
            self.run_fixture(f)
        self.assert_untouched(f)

    def test_v9_existing_attempt_or_result_never_replaces_historical_or_operation_receipts(self):
        for suffix in ('.json', '.result.json'):
            f = self.v9_fixture()
            path = f['release'].ROOT / 'receipts' / ('code-post-rollback-' + '8' * 32 + suffix)
            marker = b'previous attempt must remain untouched'
            path.write_bytes(marker)
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, '^CODE_ROLLBACK_ALREADY_ATTEMPTED$'):
                self.run_fixture(f)
            self.assertEqual(path.read_bytes(), marker)
            self.assert_untouched(f)

    def test_v9_exclusive_create_race_refuses_before_stop_without_overwriting_receipts(self):
        f = self.v9_fixture()
        writer = f['release'].write_new.side_effect
        marker = b'existing operation from another process'
        def raced_create(path, body, **kwargs):
            path.write_bytes(marker)
            return writer(path, body, **kwargs)
        f['release'].write_new.side_effect = raced_create
        with self.assertRaises(FileExistsError):
            self.run_fixture(f)
        path = f['release'].ROOT / 'receipts' / ('code-post-rollback-' + '8' * 32 + '.json')
        self.assertEqual(path.read_bytes(), marker)
        self.assertEqual(f['commands'], [])
        f['upgrade'].replace_unit.assert_not_called()
        for historical, body in f['historical_bytes'].items():
            self.assertEqual(historical.read_bytes(), body)

    def test_v9_source_units_host_and_image_drift_refuse_before_stop(self):
        for mutation in ('store', 'infrastructure', 'unit', 'host', 'image'):
            f = self.v9_fixture('image' if mutation == 'image' else None)
            if mutation == 'store': (f['new'] / 'naver_engine/store.py').write_bytes(b'drift')
            if mutation == 'infrastructure': (f['new'] / 'Dockerfile.naver-engine').write_bytes(b'drift')
            if mutation == 'unit': (f['lifecycle'].UNIT_DIR / f['lifecycle'].UNITS[0]).write_bytes(b'drift')
            if mutation == 'host': f['host'].baseline.return_value = '0' * 64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.run_fixture(f)
            self.assert_untouched(f)

    def test_v9_failure_isolates_both_writers_and_preserves_original_history(self):
        for fault in ('writer', 'recreate', 'start', 'bootstrap', 'source_after_stop',
                      'probe_old', 'write_result'):
            f = self.v9_fixture(fault)
            with self.subTest(fault=fault), self.assertRaisesRegex(RuntimeError, '^CODE_POST_ROLLBACK_FAILED$') as raised:
                self.run_fixture(f)
            self.assertNotIn('PRIVATE', json.dumps(raised.exception.failure_details))
            self.assertEqual(f['commands'][-2:], [['/usr/bin/systemctl', 'stop', unit]
                             for unit in reversed(f['lifecycle'].UNITS)])
            self.assertTrue(all(f['active'][unit] == 'inactive' for unit in f['lifecycle'].UNITS))
            for path, body in f['historical_bytes'].items():
                self.assertEqual(path.read_bytes(), body)
            if fault in ('writer', 'bootstrap', 'source_after_stop'):
                self.assertFalse(any('--force-recreate' in args for args in f['commands']))

    def test_v9_stop_failure_and_untrusted_exception_are_reported_without_private_details(self):
        for fault in ('stop_error', 'unknown_kind'):
            f = self.v9_fixture(fault)
            with self.subTest(fault=fault), self.assertRaisesRegex(RuntimeError, '^CODE_POST_ROLLBACK_FAILED$') as raised:
                self.run_fixture(f)
            self.assertNotIn('PRIVATE', json.dumps(raised.exception.failure_details))
            if fault == 'stop_error':
                self.assertIs(raised.exception.failure_details['isolated_stop_verified'], False)
                self.assertFalse(any('--force-recreate' in args or args[:2] == ['/usr/bin/systemctl', 'start']
                                     for args in f['commands']))
            else:
                self.assertEqual(raised.exception.failure_details['failed_error_kind'], 'UNRECOGNIZED')


if __name__ == '__main__':
    unittest.main()
