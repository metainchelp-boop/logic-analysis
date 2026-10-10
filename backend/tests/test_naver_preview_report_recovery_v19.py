"""V19 fixed reader; only synthetic SQLite, frozen predicates and mocked host."""
import ast
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_report_recovery as previous

TOOLS = Path(__file__).parents[1]/'tools'
MODULE = 'naver_preview_report_recovery_v19'
BASE_FIXTURE = previous.fixture


def load_predicates():
    spec = importlib.util.spec_from_file_location('frozen_reporting',Path(__file__).parent/'fixtures/v19-reporting-predicates.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured():
    module = shared.load(MODULE)
    module.SOURCE,module.ARCHIVE,module.STORE = 'b'*40,'d'*64,'e'*64
    module.R = load_predicates()
    return module


def fixture():
    connection, decisions = BASE_FIXTURE()
    for name in ('imp','clk','spend','conversions','conversion_value'):
        connection.execute('ALTER TABLE naver_auto_daily_performance ADD COLUMN '+name+' REAL')
    connection.execute('UPDATE naver_auto_daily_performance SET imp=100,clk=10,spend=987654321,conversions=2,conversion_value=123456789')
    return connection,decisions


class V19ProjectionTest(unittest.TestCase):
    def setUp(self):
        self.module = configured()
        self.connection,self.decisions = fixture()
        self.addCleanup(self.connection.close)

    def collect(self):
        return self.module.collect(SimpleNamespace(_conn=self.connection),self.decisions,previous.NOW,
            previous.MATCHING,time.monotonic()+20)

    def result(self):
        return dict(ok=True,mode='report-recovery-diagnostics-v19',source_commit=self.module.SOURCE,
            reader_mode='sqlite-mode-ro-query-only-authorizer',mutations=0,
            existing_app_baseline_unchanged=True,collection_completion_verified=False,diagnostics=self.collect())

    def test_valid_coverage_and_frozen_monthly_counts_have_separate_scopes(self):
        value = self.collect()
        self.module.validate_result(value)
        counts = value['monthly_valid_coverage']
        self.assertEqual(counts['current_companies'],3)
        self.assertEqual(counts['current_linked_accounts'],3)
        self.assertEqual(counts['raw_basic_valid_account_days'],55)
        self.assertEqual(counts['raw_conversion_valid_account_days'],26)
        self.assertEqual(counts['raw_basic_days_distribution'],[
            {'account_days':0,'companies':1},{'account_days':26,'companies':1},{'account_days':29,'companies':1}])
        self.assertEqual(counts['latest_snapshot_companies'],1)
        self.assertEqual(counts['latest_expected_account_days'],30)
        self.assertEqual(counts['latest_basic_complete_account_days'],26)
        self.assertTrue(counts['comparison_is_counts_only'])
        self.assertTrue(value['population']['stored_report_population_is_separate'])
        self.assertNotIn('987654321',json.dumps(value))
        self.assertNotIn('123456789',json.dumps(value))
        self.assertNotIn('PRIVATE',json.dumps(value))
        self.assertLess(len(json.dumps(value).encode()),self.module.MAX_OUTPUT)

    def test_adopted_raw_changes_count_drift_without_rewriting_snapshot_or_claiming_completion(self):
        before = self.connection.execute('SELECT payload_json FROM naver_auto_report_snapshot').fetchall()
        self.connection.execute('UPDATE naver_auto_daily_performance SET possibility_id=74789 WHERE customer_id=2488728 AND possibility_id IS NULL')
        value = self.collect()
        self.assertEqual(value['monthly_valid_coverage']['raw_basic_count_different_from_latest_companies'],1)
        sample = value['sample_valid_coverage'][0]
        self.assertEqual(sample['raw_basic_valid_account_days'],29)
        self.assertEqual(sample['latest_basic_complete_account_days'],26)
        self.assertEqual(self.connection.execute('SELECT payload_json FROM naver_auto_report_snapshot').fetchall(),before)
        self.assertTrue(value['coverage_is_stored_flags_not_completion_proof'])

    def test_invalid_number_or_future_collection_is_unverified_despite_stored_flag(self):
        self.connection.execute("UPDATE naver_auto_daily_performance SET imp=-1 WHERE customer_id=1073478 AND day='2026-09-01'")
        self.connection.execute("UPDATE naver_auto_daily_performance SET checked_at='2027-01-01T12:00:00+09:00' WHERE customer_id=1073478 AND day='2026-09-02'")
        value = self.collect()
        self.assertEqual(value['monthly_valid_coverage']['raw_basic_valid_account_days'],53)
        self.assertEqual(len(value['samples'][1]['accounts'][0]['dates']['basic_current_pid']),29)
        with patch.object(self.module.R,'_collected',wraps=self.module.R._collected) as collected, \
             patch.object(self.module.R,'_number',wraps=self.module.R._number) as numeric:
            self.collect()
        self.assertEqual(collected.call_count,55)
        self.assertGreater(numeric.call_count,0)

    def test_fixed_backfill_jobs_are_current_owner_only_and_latest_status_is_not_completion_proof(self):
        jobs = [
            ('ok',2488728,74789,'2026-09-27','ok','2026-10-09T12:00:00+09:00'),
            ('new',2488728,74789,'2026-09-27','reading','2026-10-10T12:00:00+09:00'),
            ('retry',1073478,82569,'2026-09-28','retry','2026-10-10T13:00:00+09:00'),
            ('other',2488728,123,'2026-09-27','ok',previous.AT),
            ('wide',1073478,82569,'2026-09-26','ok',previous.AT)]
        for key,cid,pid,start,status,at in jobs:
            self.connection.execute('INSERT INTO naver_auto_performance_job VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (key,cid,pid,'backfill','2026-10-10',start,'2026-09-30',status,at,at if status=='ok' else None,at,at,0,None))
        value = self.collect()
        self.module.validate_result(value)
        backfill = value['backfill_jobs']
        self.assertEqual(backfill['jobs'],3)
        self.assertEqual(backfill['current_accounts_with_jobs'],2)
        self.assertEqual(backfill['current_accounts_without_jobs'],1)
        self.assertEqual(backfill['statuses']['ok'],1)
        self.assertEqual(backfill['latest_account_statuses']['ok'],0)
        self.assertEqual(backfill['latest_account_statuses']['reading'],1)
        self.assertEqual(backfill['latest_account_statuses']['retry'],1)
        self.assertTrue(backfill['ok_jobs_are_not_full_recovery_proof'])

    def test_closed_typed_new_evidence_refuses_field_scope_count_and_time_forgeries(self):
        result = self.result()
        self.module.validate_operation_result(result)
        changes = (
            lambda out:out.update(ok=1),
            lambda out:out['diagnostics']['monthly_valid_coverage'].update(company_name='PRIVATE'),
            lambda out:out['diagnostics']['monthly_valid_coverage'].update(raw_owned_rows=False),
            lambda out:out['diagnostics']['monthly_valid_coverage'].update(current_companies=569),
            lambda out:out['diagnostics']['monthly_valid_coverage'].update(comparison_is_counts_only=1),
            lambda out:out['diagnostics']['monthly_valid_coverage']['raw_basic_days_distribution'][0].update(companies=9),
            lambda out:out['diagnostics']['sample_valid_coverage'][0].update(possibility_id=999),
            lambda out:out['diagnostics']['sample_valid_coverage'][0].update(latest_expected_account_days=None),
            lambda out:out['diagnostics']['backfill_jobs'].update(kind='report_monthly'),
            lambda out:out['diagnostics']['backfill_jobs'].update(period_start_min='2026-09-01'),
            lambda out:out['diagnostics']['backfill_jobs']['statuses'].update(ok=1),
            lambda out:out['diagnostics']['backfill_jobs']['checked_at'].update(first='complete'),
            lambda out:out['diagnostics']['backfill_jobs'].update(ok_jobs_are_not_full_recovery_proof=1))
        for change in changes:
            mutated = copy.deepcopy(result)
            change(mutated)
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.module.validate_operation_result(mutated)


class V19ReaderGateTest(unittest.TestCase):
    def test_pending_and_each_wrong_pin_refuse_before_any_host_database_or_process(self):
        module = shared.load(MODULE)
        self.assertEqual(module.SOURCE,'00701771c0583477357010e9ac731263770f1da5')
        self.assertEqual(module.ARCHIVE,'5c77d0197fb088600e11234660f3bf3013c03eafd8e3b756b8be7b91f34fc0e3')
        self.assertEqual(module.STORE,'aa39afff20c48225d70e80a899234c68b862aeaa53fae43c2e0769346f3b6d62')
        module.SOURCE = module.ARCHIVE = module.STORE = None
        package = dict(baseline=module.BASELINE,source_commit=module.SOURCE,source_tar_gz_sha256=module.ARCHIVE,
            period='2026-09',scope='current-managed-linked')
        for operation in ('run','validate_operation_result'):
            host,release = Mock(),Mock()
            with self.subTest(operation=operation),self.assertRaisesRegex(ValueError,'RECOVERY_TARGET_NOT_PINNED'):
                getattr(module,operation)(package,host,release) if operation=='run' else module.validate_operation_result({})
            self.assertFalse(host.mock_calls or release.mock_calls)
        module = configured()
        package.update(source_commit=module.SOURCE,source_tar_gz_sha256=module.ARCHIVE)
        for change in ({'source_commit':'a'*40},{'source_tar_gz_sha256':'a'*64},{'period':'2026-10'},
                       {'scope':'all'},{'sql':'SELECT 1'},{'path':'/other'}):
            host,release = Mock(),Mock()
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'RECOVERY_PACKAGE_'):
                module.run(dict(package,**change),host,release)
            self.assertFalse(host.mock_calls or release.mock_calls)

    def test_script_preserves_reader_security_and_imports_actual_reporting_predicates(self):
        module = configured()
        program = module.script()
        ast.parse(program)
        self.assertIn(b'reporting as R',program)
        self.assertIn(b'R._collected(row, row[\'day\'], now)',program)
        self.assertIn(b'R._number(row[key])',program)
        self.assertIn(b'writer=False',program)
        self.assertIn(b'connection.total_changes!=0',program)
        self.assertLess(program.index(b'RECOVERY_STORE_PIN'),program.index(b'connection=connect_reader'))
        old = shared.load('naver_preview_report_recovery')
        self.assertTrue(module.PROJECTION_SOURCE.startswith(old.PROJECTION_SOURCE))
        self.assertEqual(module.MAX_ACCOUNTS,old.MAX_ACCOUNTS)
        self.assertEqual(module.MAX_TARGETS,old.MAX_TARGETS)
        self.assertEqual(module.MAX_ROWS,old.MAX_ROWS)
        self.assertEqual(module.MAX_OUTPUT,old.MAX_OUTPUT)

    def test_controller_postflight_and_safe_output_gate_survive_enrichment(self):
        module = configured()
        with patch.object(previous,'M',module),patch.object(previous,'fixture',side_effect=fixture):
            result,release,host,inspections = previous.ControllerTest().scenario()
        module.validate_operation_result(result)
        self.assertEqual(inspections,2)
        self.assertEqual(host.baseline.call_count,2)
        self.assertFalse(result['collection_completion_verified'])

    def test_new_explicit_transport_roundtrip_keeps_existing_wire_limits(self):
        module = shared.load(MODULE)
        encode,decode,_ = shared.ContractTest().workflow_transport()
        bundle = dict(operation='preview-report-recovery-v19',function='run',
            package=dict(baseline=module.BASELINE,source_commit=module.SOURCE,source_tar_gz_sha256=module.ARCHIVE,period='2026-09',scope='current-managed-linked'),
            source=(TOOLS/(MODULE+'.py')).read_text(),release_source=(TOOLS/'naver_preview_release.py').read_text(),
            host_source=(TOOLS/'naver_erp_tunnel_service_install.py').read_text())
        wire = encode(bundle)
        self.assertEqual(decode(wire),bundle)
        self.assertLessEqual(len(wire),65536)
        self.assertLessEqual(len(json.dumps(bundle).encode()),196608)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
            decode(encode(dict(bundle,function='apply')))


if __name__ == '__main__':
    unittest.main()
