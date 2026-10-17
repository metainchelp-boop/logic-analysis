"""V26 aggregate recovery profile: synthetic SQLite and mocked transport only."""
import ast
import copy
import hashlib
import io
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_naver_preview_code_upgrade as shared
import test_naver_preview_report_recovery as controller
import test_naver_preview_report_recovery_v19 as previous

TOOLS = Path(__file__).parents[1]/'tools'
MODULE = 'naver_preview_conversion_recovery_v26'
AT = '2026-10-10T12:00:00+09:00'
FINGERPRINT = 'f'*64


def configured():
    module = shared.load(MODULE)
    module.R = previous.load_predicates()
    module.EXPECTED_ACCOUNTS, module.EXPECTED_COMPANIES, module.EXPECTED_TARGETS = 3, 2, 2
    return module


def package(module):
    return dict(baseline=module.BASELINE, source_commit=module.SOURCE, source_tar_gz_sha256=module.ARCHIVE,
        store_sha256=module.STORE, schema_version=11, expected_accounts=module.EXPECTED_ACCOUNTS,
        expected_companies=module.EXPECTED_COMPANIES, expected_targets=module.EXPECTED_TARGETS,
        period='2026-09', scope='current-managed-linked')


def fixture(module):
    connection = sqlite3.connect(':memory:', isolation_level=None)
    connection.executescript('''
        CREATE TABLE naver_auto_daily_performance(customer_id INTEGER,possibility_id INTEGER,day TEXT,
            basic_complete INTEGER,conversion_complete INTEGER,imp REAL,clk REAL,spend REAL,
            conversions REAL,conversion_value REAL,checked_at TEXT,source_at TEXT,
            campaign_fingerprint TEXT,source_generation TEXT,PRIMARY KEY(customer_id,day));
        CREATE TABLE naver_auto_performance_job(job_key TEXT,customer_id INTEGER,possibility_id INTEGER,
            period_start TEXT,period_end TEXT,status TEXT,error_code TEXT,checked_at TEXT,generation TEXT,
            progress_json TEXT,campaigns_json TEXT);
        CREATE TABLE naver_auto_inventory_check(customer_id INTEGER,status TEXT,checked_at TEXT,campaigns_json TEXT);
        CREATE TABLE naver_auto_manual_read(customer_id INTEGER PRIMARY KEY,possibility_id INTEGER,
            requested_at TEXT,consumed_at TEXT,period_start TEXT,period_end TEXT);
    ''')
    decisions = {cid:dict(possibility_id=pid, matched=True,
        decision=SimpleNamespace(cadence='daily', attributable=True)) for cid,pid in ((101,74789),(102,82569),(103,82569))}
    for cid,pid in ((101,74789),(102,82569),(103,82569)):
        for offset in range(30):
            day = str(module.date(2026,9,1)+module.timedelta(days=offset))
            connection.execute('INSERT INTO naver_auto_daily_performance VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (cid,None if cid==103 else pid,day,1,0,100,10,987654321,None if cid!=101 else 0,
                 None if cid!=101 else 0,AT,AT,FINGERPRINT,AT))
        progress = dict(campaign_ids=[] if cid==102 else ['PRIVATE_CAMPAIGN'],next_index=0 if cid==102 else 1,
            conversion_evidence=False,fingerprint=FINGERPRINT,private='PRIVATE_CHECKPOINT')
        connection.execute('INSERT INTO naver_auto_performance_job VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (str(cid),cid,pid,'2026-09-01','2026-09-30','ok',None,AT,AT,json.dumps(progress),
             '[]' if cid==102 else '[{"name":"PRIVATE_CAMPAIGN"}]'))
    # Latest inventory is deliberately different from the September source-progress count.
    connection.execute('INSERT INTO naver_auto_inventory_check VALUES(?,?,?,?)',
        (102,'ok','2026-10-11T12:00:00+09:00','[{"name":"PRIVATE_NEW"},{"name":"PRIVATE_OTHER"}]'))
    return connection,decisions


class RecoveryProjectionTest(unittest.TestCase):
    def setUp(self):
        self.module = configured()
        self.connection,self.decisions = fixture(self.module)
        self.addCleanup(self.connection.close)
        self.store = SimpleNamespace(_conn=self.connection,_performance_attribution_start=lambda cid,pid:None)
        self.now = self.module.datetime(2026,10,11,18,tzinfo=self.module.KST)

    def collect(self, deadline=None):
        return self.module.collect(self.store,self.decisions,self.now,FINGERPRINT,
            time.monotonic()+20 if deadline is None else deadline)

    def test_numeric_response_null_and_attribution_are_separate_aggregate_only(self):
        value = self.collect()
        self.module.validate_result(value)
        self.assertEqual(value['accounts']['numeric_zero'],1)
        self.assertEqual(value['target_accounts']['conversion_missing_or_null'],1)
        self.assertEqual(value['target_accounts']['owner_null'],1)
        self.assertEqual(value['target_source_progress_account_days']['no_campaigns'],30)
        self.assertEqual(value['target_source_progress_account_days']['no_matching_progress'],30)
        self.assertEqual(value['target_latest_campaign_inventory']['campaign_count_buckets']['multiple'],1)
        self.assertEqual(value['target_latest_campaign_inventory']['statuses_by_campaign_count_bucket']['multiple']['ok'],1)
        self.assertEqual(value['target_latest_campaign_inventory']['checked_at']['last'],'2026-10-11T12:00:00+09:00')
        self.assertEqual(value['target_monthly_manual_preconditions']['history_preconditions_met'],1)
        self.assertEqual(value['target_monthly_manual_preconditions']['owner_or_attribution_gap'],1)
        encoded=json.dumps(value)
        for private in ('PRIVATE','74789','82569','987654321','customer_id','possibility_id','campaign_ids','progress_json'):
            self.assertNotIn(private,encoded)
        self.assertTrue(all(value['limits'].values()))
        self.assertLess(len(encoded.encode()),self.module.MAX_OUTPUT)

    def test_row_missing_owner_other_invalid_basic_and_source_gap_do_not_become_conversion_zero(self):
        cases = (("DELETE FROM naver_auto_daily_performance WHERE customer_id=102 AND day='2026-09-01'",'row_missing'),
            ("UPDATE naver_auto_daily_performance SET possibility_id=999 WHERE customer_id=102",'owner_other'),
            ("UPDATE naver_auto_daily_performance SET imp=-1 WHERE customer_id=102",'basic_incomplete'),
            ("UPDATE naver_auto_daily_performance SET source_generation='2026-10-02T12:00:00+09:00' WHERE customer_id=102",'source_unverified'),
            ("UPDATE naver_auto_daily_performance SET conversions=-1,conversion_value=0 WHERE customer_id=102",'conversion_invalid'))
        for sql,kind in cases:
            with self.subTest(kind=kind):
                self.connection.execute('BEGIN');self.connection.execute(sql)
                value=self.collect();self.module.validate_result(value)
                self.assertEqual(value['target_accounts'][kind],1)
                self.connection.execute('ROLLBACK')

    def test_new_generation_and_failed_or_queued_recheck_block_current_source(self):
        for sql in ("UPDATE naver_auto_performance_job SET generation='2026-10-11T12:00:00+09:00' WHERE customer_id=102",
                    "UPDATE naver_auto_performance_job SET status='retry',error_code='PRIVATE_ERROR' WHERE customer_id=102",
                    "INSERT INTO naver_auto_manual_read VALUES(102,82569,'2026-10-11T12:00:00+09:00',NULL,'2026-09-01','2026-09-30')"):
            with self.subTest(sql=sql):
                self.connection.execute('BEGIN');self.connection.execute(sql)
                value=self.collect();self.module.validate_result(value)
                self.assertEqual(value['target_accounts']['source_unverified'],1)
                self.assertNotIn('PRIVATE_ERROR',json.dumps(value))
                self.connection.execute('ROLLBACK')

    def test_progress_fingerprint_and_generation_must_match_actual_daily_source(self):
        for field,value in (('fingerprint','a'*64),('conversion_evidence',1),('campaign_ids',{})):
            self.connection.execute('BEGIN')
            progress=dict(campaign_ids=[],next_index=0,conversion_evidence=False,fingerprint=FINGERPRINT)
            progress[field]=value
            self.connection.execute('UPDATE naver_auto_performance_job SET progress_json=? WHERE customer_id=102',(json.dumps(progress),))
            actual=self.collect()['target_source_progress_account_days']
            self.assertEqual(actual['no_matching_progress' if field=='fingerprint' else 'invalid_metadata'],30 if field!='fingerprint' else 60)
            self.connection.execute('ROLLBACK')

    def test_manual_history_gap_boundary_pending_overlap_and_recent_request_guards(self):
        self.store._performance_attribution_start=lambda cid,pid:'2026-09-02'
        self.assertEqual(self.collect()['target_monthly_manual_preconditions']['owner_or_attribution_gap'],2)
        self.store._performance_attribution_start=lambda cid,pid:None
        for sql,kind in (("DELETE FROM naver_auto_daily_performance WHERE customer_id=102 AND day='2026-09-01'",'history_missing'),
            ("UPDATE naver_auto_performance_job SET status='source_wait' WHERE customer_id=102",'collection_in_progress'),
            ("INSERT INTO naver_auto_manual_read VALUES(102,82569,'2026-10-11T17:30:00+09:00','2026-10-11T17:31:00+09:00','2026-09-01','2026-09-30')",'request_pending_or_recent')):
            self.connection.execute('BEGIN');self.connection.execute(sql)
            self.assertEqual(self.collect()['target_monthly_manual_preconditions'][kind],1)
            self.connection.execute('ROLLBACK')

    def test_nullable_legacy_manual_periods_and_old_owner_requests_do_not_corrupt_source_scope(self):
        for start,end in ((None,None),('2026-09-01','2026-09-30')):
            self.connection.execute('BEGIN')
            self.connection.execute('INSERT INTO naver_auto_manual_read VALUES(?,?,?,?,?,?)',
                (102,999,'2026-10-01T12:00:00+09:00',None,start,end))
            value=self.collect();self.module.validate_result(value)
            self.assertEqual(value['target_accounts']['conversion_missing_or_null'],1)
            self.assertEqual(value['target_monthly_manual_preconditions']['history_preconditions_met'],1)
            self.connection.execute('ROLLBACK')
        self.connection.execute('INSERT INTO naver_auto_manual_read VALUES(?,?,?,?,?,?)',
            (102,82569,'2026-10-01T12:00:00+09:00',None,None,None))
        value=self.collect();self.module.validate_result(value)
        self.assertEqual(value['target_monthly_manual_preconditions']['request_pending_or_recent'],1)

    def test_newest_null_inventory_is_unknown_instead_of_reusing_older_zero_success(self):
        self.connection.execute('INSERT INTO naver_auto_inventory_check VALUES(?,?,?,?)',
            (102,'reading','2026-10-11T13:00:00+09:00',None))
        value=self.collect();self.module.validate_result(value)
        inventory=value['target_latest_campaign_inventory']
        self.assertEqual(inventory['campaign_count_buckets']['invalid_or_missing'],1)
        self.assertEqual(inventory['campaign_count_buckets']['zero'],0)
        self.assertEqual(inventory['statuses']['reading'],1)
        self.assertEqual(inventory['checked_at']['last'],'2026-10-11T13:00:00+09:00')

    def test_wrong_type_checkpoint_projection_never_fetches_raw_objects_or_oversize_text(self):
        captured=[]
        original=self.module.rows
        def observe(*args):
            value=original(*args)
            if value and 'progress_safe' in value[0]:captured.extend(value)
            return value
        for field in ('next_index','conversion_evidence','fingerprint'):
            progress=dict(campaign_ids=[],next_index=0,conversion_evidence=False,fingerprint=FINGERPRINT)
            progress[field]={'PRIVATE': 'x'*200000}
            self.connection.execute('UPDATE naver_auto_performance_job SET progress_json=? WHERE customer_id=102',(json.dumps(progress),))
            captured.clear()
            with patch.object(self.module,'rows',side_effect=observe):value=self.collect()
            self.module.validate_result(value)
            projected=[row for row in captured if row['customer_id']==102][0]
            self.assertIsNone(projected[{'next_index':'next_index','conversion_evidence':'evidence','fingerprint':'fingerprint'}[field]])
            self.assertLess(len(json.dumps(projected)),1000)

    def test_invalid_inventory_is_unknown_and_unsuccessful_zero_is_labeled_without_setup_claim(self):
        for raw in ('{invalid','{}','x'*1048577):
            self.connection.execute('UPDATE naver_auto_inventory_check SET campaigns_json=?',(raw,))
            value=self.collect();self.module.validate_result(value)
            self.assertEqual(value['target_latest_campaign_inventory']['campaign_count_buckets']['invalid_or_missing'],1)
        self.connection.execute("UPDATE naver_auto_inventory_check SET campaigns_json='[]',status='retry'")
        value=self.collect();self.module.validate_result(value)
        self.assertEqual(value['target_latest_campaign_inventory']['campaign_count_buckets']['zero'],1)
        self.assertEqual(value['target_latest_campaign_inventory']['statuses']['retry'],1)
        self.assertTrue(value['limits']['zero_inventory_non_ok_status_is_not_setup_proof'])

    def test_population_target_deadline_and_row_caps_fail_closed(self):
        with self.assertRaisesRegex(ValueError,'CONVERSION_DEADLINE'):
            self.collect(0)
        for field,value,code in (('EXPECTED_ACCOUNTS',4,'CONVERSION_POPULATION_CHANGED'),
            ('EXPECTED_TARGETS',1,'CONVERSION_TARGET_POPULATION_CHANGED'),('MAX_ROWS',89,'CONVERSION_ROW_LIMIT'),
            ('MAX_JOBS',0,'CONVERSION_ROW_LIMIT')):
            with patch.object(self.module,field,value),self.assertRaisesRegex(ValueError,code):
                self.collect()

    def test_closed_output_counts_types_enums_and_no_extra_payload(self):
        good=self.collect();self.module.validate_result(good)
        for keys,value in ((['population','accounts'],True),(['target_accounts','owner_null'],2),
            (['target_latest_period_jobs','errors','PRIVATE'],0),(['mutations'],False),
            (['limits','tracking_installation_not_determined'],1),(['private'],'PRIVATE')):
            altered=copy.deepcopy(good);current=altered
            for key in keys[:-1]:current=current[key]
            current[keys[-1]]=value
            with self.subTest(keys=keys),self.assertRaises(ValueError):
                self.module.validate_result(altered)


class RecoveryOperationTest(unittest.TestCase):
    def test_fixed_v26_pins_and_package_refuse_old_profile_and_custom_query_before_host(self):
        module=shared.load(MODULE);module.validate_package(package(module))
        old=shared.load('naver_preview_conversion_diagnostics')
        self.assertNotEqual(module.SOURCE,old.SOURCE)
        self.assertEqual(module.SOURCE,'737a65952f2ddbc05a235cf2b139a4a11f4e7673')
        self.assertEqual((module.EXPECTED_ACCOUNTS,module.EXPECTED_COMPANIES,module.EXPECTED_TARGETS),(569,568,23))
        for key,value in (('source_commit',old.SOURCE),('store_sha256','a'*64),('schema_version',10),
            ('expected_accounts',568),('expected_accounts',569.0),('expected_targets',22),('period','2026-10'),('sql','SELECT 1')):
            altered=package(module);altered[key]=value
            host,release=Mock(),Mock()
            with self.subTest(key=key),self.assertRaises(ValueError):module.run(altered,host,release)
            self.assertFalse(host.mock_calls or release.mock_calls)

    def test_ro_query_only_authorizer_and_store_schema_script_precede_database(self):
        module=shared.load(MODULE)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'engine.db'
            with sqlite3.connect(path) as connection:connection.execute('CREATE TABLE safe(value)')
            before=path.read_bytes();reader=module.connect_reader(path)
            try:
                self.assertEqual(reader.execute('PRAGMA query_only').fetchone(),(1,))
                for sql in ('INSERT INTO safe VALUES(1)','CREATE TABLE bad(x)','ATTACH DATABASE ":memory:" AS bad',
                    'PRAGMA query_only=OFF','SELECT load_extension("x")','PRAGMA wal_checkpoint'):
                    with self.subTest(sql=sql),self.assertRaises(sqlite3.DatabaseError):reader.execute(sql)
                self.assertEqual(reader.total_changes,0)
            finally:reader.close()
            self.assertEqual(path.read_bytes(),before)
        source=module.script().decode();ast.parse(source)
        self.assertLess(source.index('CONVERSION_STORE_PIN'),source.index('connection=connect_reader'))
        for expected in ('os.geteuid()!=10001','writer=False','time.monotonic()+20',"!=('11',)",
            "connection.execute('BEGIN')","connection.execute('ROLLBACK')",'connection.total_changes!=0',
            'signal.setitimer(signal.ITIMER_REAL,20)'):
            self.assertIn(expected,source)
        for forbidden in ('SELECT progress_json','SELECT campaigns_json','SELECT payload_json','run_performance',
                          'performance_manual_request','credentials','store 2.py'):
            self.assertNotIn(forbidden,source)

    def test_container_timer_interrupts_python_snapshot_work_without_waiting_for_sql(self):
        module=shared.load(MODULE)
        tree=ast.parse(module.script().decode())
        body=next(node for node in tree.body if isinstance(node,ast.Try)).body
        deadline_class=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='ReadDeadline')
        handler=next(node for node in body if isinstance(node,ast.FunctionDef) and node.name=='expire')
        namespace={}
        exec(compile(ast.Module(body=[deadline_class,handler],type_ignores=[]),'<reader-timer>','exec'),namespace)
        old_handler=signal.signal(signal.SIGALRM,namespace['expire'])
        old_timer=signal.setitimer(signal.ITIMER_REAL,0.02)
        try:
            started=time.monotonic()
            with self.assertRaisesRegex(namespace['ReadDeadline'],'CONVERSION_DEADLINE'):
                try:
                    while time.monotonic()-started<1:
                        pass
                except Exception:
                    self.fail('ordinary snapshot error handling swallowed the deadline')
            self.assertLess(time.monotonic()-started,0.5)
        finally:
            signal.setitimer(signal.ITIMER_REAL,0)
            signal.signal(signal.SIGALRM,old_handler)
            signal.setitimer(signal.ITIMER_REAL,*old_timer)

    def test_early_identity_failure_is_sanitized_before_environment_or_database_access(self):
        module=shared.load(MODULE)
        stream=io.StringIO()
        with patch.object(module.os,'geteuid',return_value=0),patch('sys.stdout',stream), \
             patch.object(module.os.environ,'clear',side_effect=AssertionError('must fail before environment clear')):
            exec(compile(module.script(),'<synthetic-identity-refusal>','exec'),{})
        self.assertEqual(json.loads(stream.getvalue()),{'failure':'CONVERSION_IDENTITY'})

    def test_controller_preflight_postflight_bounded_result_and_error_sanitization(self):
        module=configured()
        def make_fixture():return fixture(module)
        # This adapter supplies only the read-only attribution predicate needed by this profile.
        original_collect=module.collect
        def collect(store,*args):
            store._performance_attribution_start=lambda cid,pid:None
            return original_collect(store,*args)
        with patch.object(controller,'M',module),patch.object(controller,'fixture',side_effect=make_fixture), \
             patch.object(controller,'NOW',module.datetime(2026,10,11,18,tzinfo=module.KST)), \
             patch.object(controller,'package',side_effect=lambda:package(module)),patch.object(module,'collect',side_effect=collect):
            result,release,host,inspections=controller.ControllerTest().scenario()
            module.validate_operation_result(result)
            self.assertEqual((inspections,host.baseline.call_count),(2,2))
            self.assertFalse(result['collection_completion_verified'])
            for failure,code in (('receipt','SOURCE_NOT_READY'),('mount','PREVIEW_DATA_MOUNT'),
                ('image','PREPARED_IMAGE_CHANGED'),('restart','POST_BASELINE'),('command','CONVERSION_READER_FAILED'),
                ('output','CONVERSION_OUTPUT_FIELDS'),('size','CONVERSION_OUTPUT_LIMIT'),('reader','CONVERSION_READ_FAILED')):
                with self.subTest(failure=failure):
                    result,*_=controller.ControllerTest().scenario(failure)
                    self.assertEqual(result,code)
                    self.assertNotIn('PRIVATE',result)

    def test_workflow_separate_dispatch_codec_caps_and_v19_unchanged(self):
        module=shared.load(MODULE)
        encode,decode,_=shared.ContractTest().workflow_transport()
        bundle=dict(operation='preview-conversion-recovery-v26',function='run',package=package(module),
            source=(TOOLS/(MODULE+'.py')).read_text(),release_source=(TOOLS/'naver_preview_release.py').read_text(),
            host_source=(TOOLS/'naver_erp_tunnel_service_install.py').read_text())
        wire=encode(bundle);self.assertEqual(decode(wire),bundle)
        self.assertLessEqual(len(wire),73728);self.assertLessEqual(len(json.dumps(bundle).encode()),229376)
        with self.assertRaisesRegex(ValueError,'CODE_OPS_OPERATION'):decode(encode(dict(bundle,function='apply')))
        workflow=(TOOLS.parents[1]/'.github/workflows/debug-rank.yml').read_text()
        for text in ("'preview-conversion-diagnostics':('naver_preview_conversion_diagnostics','run')",
            "'preview-conversion-recovery-v26':('naver_preview_conversion_recovery_v26','run')",
            "inputs.ad_prepare == 'preview-conversion-recovery-v26'",'naver_preview_conversion_recovery_v26.validate_package(package)',
            "github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'"):
            self.assertIn(text,workflow)
        old=(TOOLS/'naver_preview_conversion_diagnostics.py').read_bytes()
        pinned=subprocess.check_output(['git','show','HEAD:backend/tools/naver_preview_conversion_diagnostics.py'],cwd=TOOLS)
        self.assertEqual(hashlib.sha256(old).digest(),hashlib.sha256(pinned).digest())


if __name__=='__main__':unittest.main()
