"""V14 post-success inverse with synthetic adapters; no DB, server or network."""
import unittest
from unittest.mock import patch

import test_naver_preview_code_rollback as previous


class V14RollbackTest(unittest.TestCase):
    fixture = previous.PostSuccessRollbackTest.fixture

    def run_fixture(self, fixture):
        with patch.object(fixture['code'], 'db_snapshot', side_effect=AssertionError('DB snapshot forbidden')), \
             patch.object(fixture['code'], 'restore_db', side_effect=AssertionError('DB restore forbidden')), \
             patch.object(fixture['code'], 'warm_sources', side_effect=AssertionError('warmup forbidden')), \
             patch.object(fixture['code'], 'verify_database_schema', side_effect=AssertionError('DB schema forbidden')):
            return previous.PostSuccessRollbackTest.run_fixture(self, fixture)

    def test_v14_success_checks_exact_inverse_and_keeps_database_and_history(self):
        fixture = self.fixture(code_module='naver_preview_code_upgrade_v14')
        self.assertTrue(all((fixture['new']/name).exists() and not (fixture['old']/name).exists()
                            for name in fixture['code'].ADDED_SOURCE_PATHS))
        with patch.object(fixture['code'], 'compatible_inverse_source', wraps=fixture['code'].compatible_inverse_source) as inverse:
            result = self.run_fixture(fixture)
        self.assertTrue(result['ok'])
        self.assertGreaterEqual(inverse.call_count, 2)
        self.assertFalse(result['database_opened_by_controller'])
        self.assertFalse(result['source_warmup_performed'])
        self.assertEqual(result['database_policy'], 'preserve-in-place')
        for path, body in fixture['historical_bytes'].items():
            self.assertEqual(path.read_bytes(), body)

    def test_v14_extra_or_missing_module_refuses_before_service_control(self):
        for mutation in ('extra', 'missing', 'old_added'):
            fixture = self.fixture(code_module='naver_preview_code_upgrade_v14')
            if mutation == 'extra':
                (fixture['new']/'naver_engine/unreviewed.py').write_bytes(b'unapproved')
            elif mutation == 'missing':
                (fixture['new']/'naver_engine/report_notes.py').unlink()
            else:
                (fixture['old']/'naver_engine/report_notes.py').write_bytes(b'not a new module')
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'CODE_SCOPE_CHANGED'):
                self.run_fixture(fixture)
            self.assertEqual(fixture['commands'], [])
            self.assertEqual(fixture['writes'], [])

    def test_v14_writer_failure_stops_both_without_database_restore(self):
        fixture = self.fixture('writer', code_module='naver_preview_code_upgrade_v14')
        with self.assertRaisesRegex(RuntimeError, '^CODE_POST_ROLLBACK_FAILED$'):
            self.run_fixture(fixture)
        self.assertTrue(all(fixture['active'][unit] == 'inactive' for unit in fixture['lifecycle'].UNITS))
        for path, body in fixture['historical_bytes'].items():
            self.assertEqual(path.read_bytes(), body)


if __name__ == '__main__':
    unittest.main()
