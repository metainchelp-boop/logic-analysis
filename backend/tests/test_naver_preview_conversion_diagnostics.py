"""Synthetic conversion classification and narrow read-only operation contract."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import textwrap
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_report_recovery_v19 as previous
import test_naver_preview_report_recovery as controller

TOOLS = Path(__file__).parents[1]/'tools'
MODULE = 'naver_preview_conversion_diagnostics'
AT = '2026-10-10T12:00:00+09:00'
FINGERPRINT = 'f'*64


def configured():
    module = shared.load(MODULE)
    module.R = previous.load_predicates()
    module.EXPECTED_ACCOUNTS, module.EXPECTED_COMPANIES = 3, 2
    return module


def package(module):
    return dict(baseline=module.BASELINE,source_commit=module.SOURCE,source_tar_gz_sha256=module.ARCHIVE,
                period='2026-09',scope='current-managed-linked')


def fixture(module):
    connection = sqlite3.connect(':memory:',isolation_level=None)
    connection.executescript('''
        CREATE TABLE naver_auto_daily_performance(customer_id INTEGER,possibility_id INTEGER,day TEXT,
            conversion_complete INTEGER,conversions REAL,conversion_value REAL,checked_at TEXT,source_at TEXT,
            campaign_fingerprint TEXT,source_generation TEXT,PRIMARY KEY(customer_id,day));
        CREATE TABLE naver_auto_performance_job(job_key TEXT,customer_id INTEGER,possibility_id INTEGER,
            kind TEXT,period_start TEXT,period_end TEXT,status TEXT,error_code TEXT,checked_at TEXT,
            last_success_at TEXT,next_try_at TEXT,generation TEXT,progress_json TEXT);
    ''')
    decisions = {cid:dict(possibility_id=pid,matched=True,decision=SimpleNamespace(cadence='daily',attributable=True))
        for cid,pid in ((101,74789),(102,82569),(103,82569))}
    for cid,pid in ((101,74789),(102,82569),(103,82569)):
        for offset in range(30):
            day = str(module.date(2026,9,1)+module.timedelta(days=offset))
            connection.execute('INSERT INTO naver_auto_daily_performance VALUES(?,?,?,?,?,?,?,?,?,?)',
                (cid,pid,day,int(cid==101),None if cid==103 else 0,None if cid==103 else 0,AT,AT,FINGERPRINT,AT))
    progress = dict(campaign_ids=['PRIVATE_CAMPAIGN'],next_index=1,conversion_evidence=False,fingerprint=FINGERPRINT,
                    private='PRIVATE_RAW_VALUE')
    connection.execute('INSERT INTO naver_auto_performance_job VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
        ('job',102,82569,'report_monthly','2026-09-01','2026-09-30','ok',None,AT,AT,AT,AT,json.dumps(progress)))
    return connection,decisions


class ConversionProjectionTest(unittest.TestCase):
    def setUp(self):
        self.module = configured()
        self.connection,self.decisions = fixture(self.module)
        self.addCleanup(self.connection.close)
        self.now = self.module.datetime(2026,10,10,18,tzinfo=self.module.KST)

    def collect(self, deadline=None):
        return self.module.collect(SimpleNamespace(_conn=self.connection),self.decisions,self.now,FINGERPRINT,
                                   time.monotonic()+20 if deadline is None else deadline)

    def result(self):
        return dict(ok=True,mode='conversion-diagnostics-v19',source_commit=self.module.SOURCE,
            reader_mode='sqlite-mode-ro-query-only-authorizer',mutations=0,
            existing_app_baseline_unchanged=True,collection_completion_verified=False,diagnostics=self.collect())

    def test_zero_complete_zero_unconfirmed_and_null_are_separate_without_values_or_identifiers(self):
        value = self.collect()
        self.module.validate_result(value)
        self.assertEqual(value['account_days']['complete_zero'],30)
        self.assertEqual(value['account_days']['present_flagfalse_zero'],30)
        self.assertEqual(value['account_days']['field_missing_or_null'],30)
        self.assertEqual(value['accounts']['complete_zero'],1)
        self.assertEqual(value['accounts']['present_flagfalse_zero'],1)
        self.assertEqual(value['accounts']['field_missing_or_null'],1)
        self.assertEqual(value['source_campaign_coverage']['present_flagfalse_account_days']['all_campaigns_evidence_false'],30)
        self.assertEqual(value['source_campaign_coverage']['campaign_count_account_days']['one'],30)
        text = json.dumps(value)
        for private in ('PRIVATE', '74789', '82569', 'customer_id', 'possibility_id', 'campaign_ids', 'progress_json'):
            self.assertNotIn(private,text)
        self.assertTrue(all(value['limits'].values()))
        self.assertLess(len(text.encode()),self.module.MAX_OUTPUT)

    def test_positive_present_false_does_not_become_complete_and_partial_zero_is_account_classified(self):
        self.connection.execute('UPDATE naver_auto_daily_performance SET conversions=1,conversion_value=123456789 WHERE customer_id=102 AND day=?',('2026-09-02',))
        self.connection.execute('UPDATE naver_auto_daily_performance SET conversion_complete=1 WHERE customer_id=102 AND day=?',('2026-09-03',))
        value = self.collect()
        self.module.validate_result(value)
        self.assertEqual(value['account_days']['present_flagfalse_positive'],1)
        self.assertEqual(value['account_days']['present_flagfalse_zero'],28)
        self.assertEqual(value['accounts']['present_flagfalse_positive'],1)
        self.assertNotIn('123456789',json.dumps(value))

    def test_exact_reporting_predicates_preserve_invalid_future_and_owner_gaps(self):
        self.connection.execute('DELETE FROM naver_auto_daily_performance WHERE customer_id=101 AND day=?',('2026-09-01',))
        self.connection.execute('UPDATE naver_auto_daily_performance SET possibility_id=999 WHERE customer_id=101 AND day=?',('2026-09-02',))
        self.connection.execute('UPDATE naver_auto_daily_performance SET checked_at=? WHERE customer_id=101 AND day=?',('2027-01-01T12:00:00+09:00','2026-09-03'))
        self.connection.execute('UPDATE naver_auto_daily_performance SET conversions=-1 WHERE customer_id=101 AND day=?',('2026-09-04',))
        with patch.object(self.module.R,'_collected',wraps=self.module.R._collected) as collected, \
             patch.object(self.module.R,'_number',wraps=self.module.R._number) as numeric:
            value = self.collect()
        self.module.validate_result(value)
        for kind in ('row_missing','owner_mismatch','source_unverified','field_invalid'):
            self.assertEqual(value['account_days'][kind],1)
        self.assertEqual(value['accounts']['source_gap'],1)
        self.assertGreaterEqual(collected.call_count,87)
        self.assertGreater(numeric.call_count,0)

    def test_invalid_numeric_boolean_nonfinite_and_missing_precedence(self):
        for raw in (True,-1,float('inf'),float('nan'),'0'):
            self.assertEqual(self.module.field_kind(raw),'invalid')
        self.assertEqual(self.module.field_kind(None),'missing_or_null')
        row = dict(possibility_id=1,day='2026-09-01',checked_at=AT,source_at=AT,
                   conversion_complete=1,conversions=None,conversion_value=-1)
        self.assertEqual(self.module.day_kind(row,1,self.now),'field_missing_or_null')

    def test_campaign_partial_empty_invalid_and_wrong_generation_are_not_complete_evidence(self):
        for update,expected in ((dict(next_index=0),'partial_campaigns'),
                (dict(campaign_ids=[],next_index=0),'no_campaigns'),
                (dict(campaign_ids={}), 'invalid_metadata'),
                (dict(conversion_evidence=1),'invalid_metadata'),
                (dict(conversion_evidence=True),'all_campaigns_evidence_true')):
            progress = dict(campaign_ids=['PRIVATE'],next_index=1,conversion_evidence=False,fingerprint=FINGERPRINT)
            progress.update(update)
            self.connection.execute('UPDATE naver_auto_performance_job SET progress_json=?',(json.dumps(progress),))
            value = self.collect()
            self.module.validate_result(value)
            self.assertEqual(value['source_campaign_coverage']['account_days'][expected],30)
        self.connection.execute('UPDATE naver_auto_performance_job SET generation=?',('2026-10-09T12:00:00+09:00',))
        self.assertEqual(self.collect()['source_campaign_coverage']['account_days']['no_matching_progress'],90)

    def test_missing_and_malformed_progress_is_unknown_not_setup_failure(self):
        for raw in (None,'{invalid','x'*1048577):
            self.connection.execute('UPDATE naver_auto_performance_job SET progress_json=?',(raw,))
            value = self.collect()
            self.module.validate_result(value)
            self.assertEqual(value['source_campaign_coverage']['account_days']['no_matching_progress'],90)
            self.assertTrue(value['limits']['tracking_installation_not_determined'])

    def test_current_population_account_and_company_counts_are_exact(self):
        for change in ('account','company','cadence'):
            before = copy.deepcopy(self.decisions)
            if change == 'account':
                self.decisions.pop(103)
            elif change == 'company':
                self.decisions[103]['possibility_id'] = 123
            else:
                self.decisions[103]['decision'].cadence = 'monthly'
            with self.assertRaisesRegex(ValueError,'CONVERSION_POPULATION_CHANGED'):
                self.collect()
            self.decisions = before

    def test_timeout_and_total_row_caps_fail_closed_without_writes(self):
        with self.assertRaisesRegex(ValueError,'CONVERSION_DEADLINE'):
            self.collect(time.monotonic()-1)
        with patch.object(self.module,'MAX_ROWS',89):
            with self.assertRaisesRegex(ValueError,'CONVERSION_ROW_LIMIT'):
                self.collect()
        with patch.object(self.module,'MAX_JOBS',0):
            with self.assertRaisesRegex(ValueError,'CONVERSION_ROW_LIMIT'):
                self.collect()
        self.assertEqual(self.connection.total_changes,91)

    def test_closed_field_types_counts_enums_and_timestamps_reject_forgery(self):
        value = self.result()
        self.module.validate_operation_result(value)
        cases = [(['ok'],1),(['mutations'],False),(['existing_app_baseline_unchanged'],1),
            (['collection_completion_verified'],0),(['diagnostics','mutations'],False),
            (['diagnostics','observed_at'],'complete'),(['diagnostics','period'],'2026-09-01'),
            (['diagnostics','population','accounts'],True),
            (['diagnostics','account_days','complete_zero'],31),
            (['diagnostics','jobs','checked_at','first'],'complete'),
            (['diagnostics','limits','tracking_installation_not_determined'],1),
            (['diagnostics','source_campaign_coverage','matching_metadata_account_days'],31)]
        for keys,replacement in cases:
            altered = copy.deepcopy(value)
            current = altered
            for key in keys[:-1]:
                current = current[key]
            current[keys[-1]] = replacement
            with self.subTest(keys=keys),self.assertRaises(ValueError):
                self.module.validate_operation_result(altered)
        altered = copy.deepcopy(value)
        altered['diagnostics']['account_days']['PRIVATE'] = 0
        with self.assertRaises(ValueError):
            self.module.validate_operation_result(altered)


class ConversionOperationTest(unittest.TestCase):
    def test_closed_exact_package_rejects_scope_source_archive_and_extra_selectors(self):
        module = shared.load(MODULE)
        module.validate_package(package(module))
        for key,value in (('source_commit','a'*40),('source_tar_gz_sha256','a'*64),('baseline','a'*64),
                ('period','2026-10'),('scope','all'),('customer_id',123)):
            altered = package(module); altered[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                module.validate_package(altered)
            host,release=Mock(),Mock()
            with self.assertRaises(ValueError):
                module.run(altered,host,release)
            self.assertFalse(host.mock_calls or release.mock_calls)

    def test_reader_is_ro_query_only_authorized_consistent_and_nonmutating(self):
        module = shared.load(MODULE)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve()/'engine.db'
            writer = sqlite3.connect(path); writer.execute('CREATE TABLE safe(value INTEGER)');writer.commit();writer.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            connection = module.connect_reader(path)
            try:
                connection.execute('BEGIN')
                self.assertEqual(connection.execute('PRAGMA query_only').fetchone(),(1,))
                for sql in ('INSERT INTO safe VALUES(1)','CREATE TABLE unsafe(value)','ATTACH DATABASE ":memory:" AS extra',
                        'PRAGMA query_only=OFF','SELECT load_extension("x")','DELETE FROM safe'):
                    with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):
                        connection.execute(sql)
                self.assertEqual(connection.total_changes,0)
                connection.execute('ROLLBACK')
            finally:
                connection.close()
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)

    def test_script_store_pin_precedes_db_schema_is_fixed_and_no_collector_or_json_payload_selected(self):
        module = shared.load(MODULE)
        source = module.script().decode()
        ast.parse(source)
        self.assertLess(source.index('CONVERSION_STORE_PIN'),source.index('connection=connect_reader'))
        self.assertIn("!=('11',)",source)
        self.assertIn('writer=False',source)
        self.assertIn('time.monotonic()+20',source)
        self.assertIn("connection.execute('BEGIN')",source)
        self.assertIn("connection.execute('ROLLBACK')",source)
        for forbidden in ('SELECT progress_json','SELECT payload_json','run_performance','request_performance_period',
                          'daily_revision','campaigns_json','bizmoney','credentials','store 2.py'):
            self.assertNotIn(forbidden,source)

    def test_controller_preflight_postflight_and_bounded_output_fail_closed(self):
        module = configured()
        with patch.object(controller,'M',module),patch.object(controller,'fixture',side_effect=lambda:fixture(module)):
            result,release,host,inspections = controller.ControllerTest().scenario()
            module.validate_operation_result(result)
            self.assertEqual(inspections,2)
            self.assertEqual(host.baseline.call_count,2)
            for failure,code in (('receipt','SOURCE_NOT_READY'),('mount','PREVIEW_DATA_MOUNT'),
                    ('image','PREPARED_IMAGE_CHANGED'),('restart','POST_BASELINE'),
                    ('command','CONVERSION_READER_FAILED'),('output','CONVERSION_OUTPUT_FIELDS'),
                    ('size','CONVERSION_OUTPUT_LIMIT'),('reader','CONVERSION_READ_FAILED')):
                with self.subTest(failure=failure):
                    result,release,host,inspections = controller.ControllerTest().scenario(failure)
                    self.assertEqual(result,code)
                    if failure in ('command','output','size','reader','restart'):
                        self.assertEqual(inspections,2)
                    self.assertNotIn('PRIVATE',result)

    def test_exact_workflow_wiring_and_unexpanded_wire_caps_round_trip(self):
        module = shared.load(MODULE)
        workflow = (TOOLS.parents[1]/'.github/workflows/debug-rank.yml').read_text()
        blocks = []
        lines = workflow.splitlines()
        for index,line in enumerate(lines):
            if "python3 - <<'PY'" in line or "/usr/bin/python3 -I -B - <<'PY'" in line:
                body=[]
                for candidate in lines[index+1:]:
                    if candidate.strip()=='PY': break
                    body.append(candidate[10:] if candidate.startswith('          ') else candidate[12:])
                blocks.append('\n'.join(body))
        encode,decode = None,None
        for block in blocks:
            tree=ast.parse(textwrap.dedent(block))
            definitions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('encode_ops','decode_ops')]
            if definitions:
                namespace={}
                exec('import base64,gzip,json,zlib',namespace)
                exec(compile(ast.Module(body=definitions,type_ignores=[]),'<workflow-codec>','exec'),namespace)
                encode=namespace.get('encode_ops',encode);decode=namespace.get('decode_ops',decode)
        bundle=dict(operation='preview-conversion-diagnostics',function='run',package=package(module),
            source=(TOOLS/(MODULE+'.py')).read_text(),release_source=(TOOLS/'naver_preview_release.py').read_text(),
            host_source=(TOOLS/'naver_erp_tunnel_service_install.py').read_text())
        wire=encode(bundle)
        self.assertEqual(decode(wire),bundle)
        self.assertLessEqual(len(wire),73728)
        self.assertLessEqual(len(json.dumps(bundle).encode()),229376)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):
            decode(encode(dict(bundle,function='apply')))
        for required in ("'preview-conversion-diagnostics':('naver_preview_conversion_diagnostics','run')",
                "inputs.ad_prepare == 'preview-conversion-diagnostics'",'naver_preview_conversion_diagnostics.validate_package(package)',
                "github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'"):
            self.assertIn(required,workflow)
        for codec in (encode,decode):
            self.assertIn(229376,codec.__code__.co_consts)
            self.assertIn(73728,codec.__code__.co_consts)


if __name__ == '__main__':
    unittest.main()
