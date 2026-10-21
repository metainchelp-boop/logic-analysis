"""D3 초안의 source4d 실제 Store 합성 회귀. 운영 호출·운영 DB 없음."""
import copy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

import reader as D
import fixtures as F

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'source-4d-fixture'


class IOTrap:
    def __fspath__(self):
        raise AssertionError('PENDING_PIN_TOUCHED_PATH')


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = D.load_modules(ROOT)

    def fixture(self,scenario='nojob',mutate=None):
        st, modules, now = F.seed(self.modules,scenario)
        self.addCleanup(st.close)
        c = st._conn
        c.set_authorizer(None)
        if mutate:
            mutate(st,c,modules,now)
        c.execute('PRAGMA query_only=ON')
        c.set_authorizer(D.readonly_authorizer)
        c.execute('BEGIN')
        self.addCleanup(lambda: c.execute('ROLLBACK') if c.in_transaction else None)
        return st,modules,now

    def collect(self,scenario='nojob',mutate=None):
        st,m,now = self.fixture(scenario,mutate)
        before = st._conn.total_changes
        with patch.object(st,'synchronize_management',side_effect=AssertionError('FORBIDDEN_SELECTOR')), \
             patch.object(st,'inspection_work',side_effect=AssertionError('FORBIDDEN_SELECTOR')), \
             patch.object(st,'performance_work',side_effect=AssertionError('FORBIDDEN_SELECTOR')), \
             patch.object(st,'performance_manual_request',side_effect=AssertionError('FORBIDDEN_WRITER')), \
             patch.object(st,'_tx',side_effect=AssertionError('FORBIDDEN_WRITER')), \
             patch.object(socket.socket,'connect',side_effect=AssertionError('FORBIDDEN_NETWORK')), \
             patch.object(socket.socket,'connect_ex',side_effect=AssertionError('FORBIDDEN_NETWORK')):
            result = D.collect(st,now,m)
        self.assertEqual(st._conn.total_changes,before)
        return D.validate_result(result)

    def unknown(self,mutate):
        result = self.collect(mutate=mutate)
        self.assertEqual(result['authorization'],'UNKNOWN')
        self.assertTrue(all(result[k] is None for k in ('identity','inspection','manual','same_pid_performance')))

    def job_mutation(self,change):
        def mutation(st,c,m,now):
            key,raw = c.execute("SELECT key,value FROM naver_auto_meta WHERE key LIKE 'learning-job:%'").fetchone()
            job = json.loads(raw)
            change(job)
            c.execute('UPDATE naver_auto_meta SET value=? WHERE key=?',(json.dumps(job),key))
        return mutation

    def reservation_mutation(self,change):
        def mutation(st,c,m,now):
            key,raw = c.execute("SELECT key,value FROM naver_auto_meta WHERE key LIKE 'learning-call:%'").fetchone()
            reservation = json.loads(raw)
            change(reservation)
            c.execute('UPDATE naver_auto_meta SET value=? WHERE key=?',(json.dumps(reservation),key))
        return mutation

    def payload_mutation(self,change):
        def mutation(st,c,m,now):
            rid,raw = c.execute('SELECT report_id,payload_json FROM naver_auto_report_snapshot WHERE period_key=? ORDER BY report_id DESC LIMIT 1',(D.PERIOD_KEY,)).fetchone()
            value = json.loads(raw)
            change(value)
            c.execute('UPDATE naver_auto_report_snapshot SET payload_json=? WHERE report_id=?',(json.dumps(value),rid))
        return mutation

    def test_pending_pins_fail_before_any_caller_or_path_io(self):
        with patch.object(D,'load_modules',side_effect=AssertionError('IMPORT_BEFORE_PIN')),patch.object(D,'connect_reader',side_effect=AssertionError('DB_BEFORE_PIN')):
            with self.assertRaisesRegex(ValueError,'D3_EXECUTION_PINS_PENDING'):
                D.read_database(IOTrap(),IOTrap())

    def test_all_execution_slots_remain_pending(self):
        self.assertEqual(len(D.EXECUTION_PINS),5)
        self.assertTrue(all(x is None for x in D.EXECUTION_PINS.values()))

    def test_exact_163_source_and_no_forbidden_path(self):
        self.assertEqual(D.verify_source(ROOT),ROOT)
        self.assertEqual(len(D.SOURCE_FILES),163)
        self.assertTrue(all(Path(k).name not in ('store 2.py','HANDOVER.md') and not Path(k).name.startswith('.env') for k in D.SOURCE_FILES))

    def test_source_byte_or_mode_mutant_rejected_before_import(self):
        files = copy.deepcopy(D.SOURCE_FILES)
        first = next(iter(files))
        files[first]['sha256'] = '0'*64
        with patch.object(D,'SOURCE_FILES',files),self.assertRaisesRegex(ValueError,'D3_SOURCE_PIN'):
            D.verify_source(ROOT)

    def test_real_generate_four_revisions_and_observed_reservation_pass(self):
        result = self.collect()
        self.assertEqual(result['authorization'],'OBSERVED_EVENT_OWNER_CURRENTLY_AUTHORIZED')
        self.assertEqual(result['inspection']['ui_branch'],'NO_OBSERVATION')
        self.assertEqual(result['identity']['pid'],D.PID)
        self.assertTrue(result['identity']['canonical_ad_account_namespace_resolved'])

    def test_event_expired_now_but_valid_terminal_then_remains_readable(self):
        self.assertLess(F.EXPIRES,F.NOW)
        self.assertEqual(self.collect()['authorization'],'OBSERVED_EVENT_OWNER_CURRENTLY_AUTHORIZED')

    def test_report_generated_extra_period_fields_are_preserved(self):
        st,m,now = self.fixture()
        raw = st._conn.execute('SELECT payload_json FROM naver_auto_report_snapshot WHERE period_key=? ORDER BY report_id DESC LIMIT 1',(D.PERIOD_KEY,)).fetchone()[0]
        period = json.loads(raw)['period']
        self.assertTrue({'days','timezone','due_at'} <= set(period))
        self.assertTrue(D.event_owner(st,now,time.monotonic()+20,m,F.CID,m['MS'].snapshot(st,now)[F.CID]))

    def test_customer_id_different_from_ad_account_no_real_fixture(self):
        self.assertNotEqual(F.CID,D.ADNO)
        result = self.collect()
        self.assertEqual(result['authorization'],'OBSERVED_EVENT_OWNER_CURRENTLY_AUTHORIZED')

    def test_namespace_decoy_does_not_replace_exact_ad_account(self):
        def mutate(st,c,m,now):
            original = c.execute('SELECT * FROM naver_auto_account WHERE customer_id=?',(F.CID,))
            columns = [d[0] for d in original.description]
            values = list(original.fetchone())
            values[columns.index('customer_id')] = D.ADNO
            values[columns.index('ad_account_no')] = D.ADNO+99
            c.execute('INSERT INTO naver_auto_account('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',values)
        result = self.collect(mutate=mutate)
        self.assertEqual(result['authorization'],'OBSERVED_EVENT_OWNER_CURRENTLY_AUTHORIZED')

    def test_duplicate_present_ad_account_refuses_scope(self):
        def mutate(st,c,m,now):
            original = c.execute('SELECT * FROM naver_auto_account WHERE customer_id=?',(F.CID,))
            columns = [d[0] for d in original.description]
            values = list(original.fetchone())
            values[columns.index('customer_id')] = F.CID+1
            c.execute('INSERT INTO naver_auto_account('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',values)
        self.unknown(mutate)

    def test_absent_selected_account_refuses_scope(self):
        self.unknown(lambda st,c,m,now:c.execute('UPDATE naver_auto_account SET present=0 WHERE customer_id=?',(F.CID,)))

    def test_dirty_report_does_not_borrow_prior_revision(self):
        self.unknown(lambda st,c,m,now:c.execute('UPDATE naver_auto_report_dirty SET pending=1 WHERE possibility_id=? AND period_key=?',(D.PID,D.PERIOD_KEY)))

    def test_numeric_revision_changed_refuses_fixed_event(self):
        self.unknown(self.payload_mutation(lambda v:v.update(revision_no=5)))

    def test_account_numeric_revision_changed_refuses_fixed_event(self):
        self.unknown(self.payload_mutation(lambda v:v['_account_reports'][str(F.CID)].update(revision_no=5)))

    def test_current_strategy_head_prevents_alternate_event_fallback(self):
        def mutate(st,c,m,now):
            rid = c.execute('SELECT report_id FROM naver_auto_report_snapshot WHERE period_key=? ORDER BY report_id DESC LIMIT 1',(D.PERIOD_KEY,)).fetchone()[0]
            c.execute('INSERT INTO naver_auto_meta(key,value) VALUES(?,?)',('report-strategy-head:'+str(rid)+':'+m['RV'].account_key(F.CID),'{}'))
        self.unknown(mutate)

    def test_other_period_refuses_current_report(self):
        self.unknown(self.payload_mutation(lambda v:v['period'].update(start='2026-10-06')))

    def test_event_outside_fixed_minute_does_not_expand_window(self):
        self.unknown(self.reservation_mutation(lambda v:v.update(at='2026-10-13T07:11:00+09:00')))

    def test_event_expired_before_terminal_refuses(self):
        self.unknown(self.job_mutation(lambda v:v.update(expires_at='2026-10-13T07:10:40+09:00')))

    def test_job_not_terminal_refuses(self):
        self.unknown(self.job_mutation(lambda v:v.update(state='running',diagnostic=None)))

    def test_reservation_actor_mismatch_refuses(self):
        self.unknown(self.reservation_mutation(lambda v:v.update(actor=F.ACTOR+1)))

    def test_reservation_bool_actor_cannot_equal_int_actor(self):
        self.unknown(self.reservation_mutation(lambda v:v.update(actor=True)))

    def test_binding_origin_other_than_manual_async_refuses(self):
        self.unknown(lambda st,c,m,now:c.execute("UPDATE naver_auto_provider_binding SET origin='scheduled'"))

    def test_binding_missing_refuses_without_disclosing_uuid(self):
        self.unknown(lambda st,c,m,now:c.execute("UPDATE naver_auto_provider_binding SET job_id=?",('c'*32,)))

    def test_binding_proof_mismatch_refuses(self):
        self.unknown(lambda st,c,m,now:c.execute('UPDATE naver_auto_provider_binding SET proof_hash=?',('f'*64,)))

    def test_current_authority_revoked_refuses_past_event(self):
        def mutate(st,c,m,now):
            raw = c.execute("SELECT value FROM naver_auto_meta WHERE key='org_snapshot'").fetchone()
            # Actual record_org updates the current organization through its public validation boundary.
            st.writer = True
            organization = F._organization(now)
            organization['owners'][0]['manage_emp_idx'] = 1
            st.record_org(organization,now)
            st.writer = False
        self.unknown(mutate)

    def test_ambiguous_manual_event_does_not_choose_an_actor(self):
        def mutate(st,c,m,now):
            key,raw = c.execute("SELECT key,value FROM naver_auto_meta WHERE key LIKE 'learning-job:%'").fetchone()
            job = json.loads(raw);job.update(actor=F.ACTOR+1,job_id='c'*32)
            identity = m['J'].identity(job['actor'],job['narrowed'],job['report_id'],job['account_key'],job['revision_fingerprint'],job['expected_version'])
            c.execute('INSERT INTO naver_auto_meta(key,value) VALUES(?,?)',(m['J'].PREFIX+identity,json.dumps(job)))
            raw = c.execute("SELECT value FROM naver_auto_meta WHERE key=?",('learning-call:'+F.JOB_ID,)).fetchone()[0]
            reserved = json.loads(raw);reserved['actor']=job['actor']
            c.execute('INSERT INTO naver_auto_meta(key,value) VALUES(?,?)',('learning-call:'+job['job_id'],json.dumps(reserved)))
            c.execute('INSERT INTO naver_auto_provider_binding SELECT ?,?,?,possibility_id,account_key,report_id,origin,created_at,reserved_microusd,proof_hash FROM naver_auto_provider_binding WHERE job_id=?',('d'*32,job['job_id'],job['actor'],F.JOB_ID))
        self.unknown(mutate)

    def test_meta_row_payload_is_bounded_before_store_parser(self):
        def mutate(st,c,m,now):
            c.execute('INSERT INTO naver_auto_meta(key,value) VALUES(?,?)',('synthetic-oversized','x'*(16*1024*1024+1)))
        with self.assertRaisesRegex(ValueError,'D3_READ_BOUND'):
            self.collect(mutate=mutate)

    def test_progress_body_is_bounded_in_sql_before_decode(self):
        def mutate(st,c,m,now):
            c.execute('UPDATE naver_auto_inspection_job SET progress_json=?',('x'*(D.MAX_BODY+1),))
        with self.assertRaisesRegex(ValueError,'D3_READ_BOUND'):
            self.collect('ok',mutate)

    def test_corrupt_checkpoint_cannot_borrow_previous_success(self):
        def mutate(st,c,m,now):
            c.execute('UPDATE naver_auto_inspection_job SET progress_hash=?',('0'*64,))
        result = self.collect('ok',mutate)
        self.assertEqual(result['inspection']['ui_branch'],'CURRENT_ROW_INVALID')
        self.assertFalse(result['inspection']['current_valid'])

    def test_performance_overlap_groups_same_pid_period_only_all_supported_kinds(self):
        def mutate(st,c,m,now):
            policy = m['MS'].snapshot(st,now)[F.CID]
            period = m['P'].period_for('daily',now)
            catalog = st.account_catalog()
            base = st._performance_job(F.CID,'daily',period.cycle_day,period.since,period.until,policy,st.inventory_snapshot(now),catalog['generated_at'],matching_fingerprint=st.decision_fingerprint())
            base['snapshot_at'] = m['S']._kst_text(base['snapshot_at'],'synthetic')
            columns = list(base)+['possibility_id','status','checked_at','next_try_at','attempts','error_code']
            for index,(kind,status,pid,until) in enumerate((('daily','retry',D.PID,'2026-10-12'),('backfill','partial',D.PID,'2026-10-12'),('manual','ok',D.PID,'2026-10-12'),('manual_period','source_wait',D.PID+1,'2026-10-12'),('weekly','reading',D.PID,'2026-09-30'))):
                values = dict(base,job_key='synthetic-performance-'+str(index),kind=kind,possibility_id=pid,status=status,checked_at=m['S']._kst_text(now-F.timedelta(hours=2),'synthetic'),next_try_at=m['S']._kst_text(now-F.timedelta(minutes=1),'synthetic'),attempts=0,error_code='NETWORK',period_end=until)
                c.execute('INSERT INTO naver_auto_performance_job('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[values[k] for k in columns])
        result = self.collect(mutate=mutate)['same_pid_performance']
        self.assertEqual(result['overlap_count'],2)
        self.assertEqual({g['kind'] for g in result['closed_groups']},{'daily','backfill'})
        self.assertTrue(all(g['retry_due'] for g in result['closed_groups']))

    def test_manual_period_registration_is_not_setup_manual_selection(self):
        def mutate(st,c,m,now):
            c.execute("UPDATE naver_auto_manual_read SET request_kind='manual_period'")
        result = self.collect('manual_pending',mutate)
        self.assertEqual(result['manual']['request_kind'],'manual_period')
        self.assertTrue(result['manual']['actor_pid_valid'])
        self.assertEqual(result['inspection']['ui_branch'],'CURRENT_COMPLETE')

    def test_full_uri_reader_uses_single_snapshot_and_no_mutation_on_synthetic_db(self):
        st,m,now = F.seed(self.modules,'partial')
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp).resolve()/'synthetic.db'
                disk = sqlite3.connect(path);st._conn.backup(disk);disk.close()
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                pins = {k:'0'*64 for k in D.PIN_FIELDS};pins['canonical_receipt']=D.CANONICAL_SHA256
                # In-memory synthetic authorization of the entry harness only;
                # actual deployment slots in the source remain None.
                transactions = []
                connect = D.connect_reader
                def capture(path):
                    connection = connect(path)
                    connection.set_trace_callback(lambda sql:transactions.append(sql) if sql in ('BEGIN','ROLLBACK') else None)
                    return connection
                with patch.object(D,'EXECUTION_PINS',pins),patch.object(D,'connect_reader',side_effect=capture),patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK')):
                    result = D.read_database(path,ROOT,now=now)
                self.assertEqual(transactions,['BEGIN','ROLLBACK'])
                self.assertEqual(result['inspection']['ui_branch'],'CURRENT_PARTIAL')
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
                self.assertTrue(all(v is None for v in D.EXECUTION_PINS.values()))
        finally:
            st.close()

    def test_fixed_0710_window_and_original_0528_snapshot_are_separate(self):
        self.assertEqual(D.EVENT_FROM.isoformat(),'2026-10-13T07:10:00+09:00')
        self.assertEqual(D.EVENT_UNTIL.isoformat(),'2026-10-13T07:11:00+09:00')
        self.assertTrue(D.EVENT_FROM <= F.EVENT < D.EVENT_UNTIL)
        old = json.loads((HERE/'history-fixed-0528-v1'/'freeze.receipt.json').read_text())
        self.assertEqual(old['event_window'],['2026-10-13T05:28:00+09:00','2026-10-13T05:29:00+09:00'])
        for name,pin in old['files'].items():
            raw = (HERE/'history-fixed-0528-v1'/name).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),pin['sha256'])

    def test_closed_output_rejects_false_complete_and_half_counts(self):
        v = self.collect('ok')
        v['inspection']['progress_shape_valid'] = False
        with self.assertRaisesRegex(ValueError,'D3_OUTPUT_SHAPE'):D.validate_result(v)
        v = self.collect()
        v['inspection']['next_index'] = 0
        with self.assertRaisesRegex(ValueError,'D3_OUTPUT_SHAPE'):D.validate_result(v)

    def test_duplicate_or_nonfinite_json_refuses_without_content(self):
        for raw in ('{"same":1,"same":2}','{"numeric":NaN}'):
            with self.assertRaisesRegex(ValueError,'D3_SHAPE'):D.private_json(raw,1024)

    def test_real_setup_scenarios_match_store_and_ui_branch(self):
        expected = {'nojob':'NO_OBSERVATION','ok':'CURRENT_COMPLETE','empty_ok':'CURRENT_COMPLETE',
            'missing_metrics':'CURRENT_COMPLETE','reading':'CURRENT_PARTIAL','partial':'CURRENT_PARTIAL',
            'retry':'CURRENT_PARTIAL','manual_pending':'MANUAL_PENDING','consumed':'MANUAL_PENDING',
            'manual_ok':'CURRENT_COMPLETE','expired_manual':'CURRENT_COMPLETE','stale':'CURRENT_ROW_INVALID',
            'stale_catalog':'CURRENT_ROW_INVALID','stale_snapshot':'CURRENT_ROW_INVALID'}
        for scenario,branch in expected.items():
            with self.subTest(scenario=scenario):
                result = self.collect(scenario)
                self.assertEqual(result['authorization'],'OBSERVED_EVENT_OWNER_CURRENTLY_AUTHORIZED')
                self.assertEqual(result['inspection']['ui_branch'],branch)
                self.assertIs(result['inspection']['ui_setup_branch_agreement'],True)

    def test_consumed_manual_is_current_selection_not_registration_reuse(self):
        result = self.collect('consumed')
        self.assertTrue(result['manual']['consumed'])
        self.assertTrue(result['manual']['actor_pid_valid'])
        self.assertEqual(result['inspection']['ui_branch'],'MANUAL_PENDING')
        self.assertTrue(result['manual']['one_hour_wait'])

    def test_yesterday_manual_not_revived(self):
        result = self.collect('expired_manual')
        self.assertFalse(result['manual']['requested_today'])
        self.assertTrue(result['manual']['actor_pid_valid'])
        self.assertEqual(result['inspection']['ui_branch'],'CURRENT_COMPLETE')

    def test_partial_never_promoted_to_complete(self):
        self.assertEqual(self.collect('partial')['inspection']['ui_branch'],'CURRENT_PARTIAL')
        with patch.object(D,'expected_setup',side_effect=lambda branch,row:dict(D.actual_setup(None),present=True,status='ok',stale=False,complete=True)):
            with self.assertRaisesRegex(ValueError,'D3_UI_BRANCH_MISMATCH'):
                self.collect('partial')

    def test_single_snapshot_required(self):
        st,m,now = self.fixture()
        st._conn.execute('ROLLBACK')
        with self.assertRaisesRegex(ValueError,'D3_READER_MODE'):
            D.collect(st,now,m)

    def test_writer_store_is_refused_before_read(self):
        st,m,now = self.fixture()
        st.writer = True
        with self.assertRaisesRegex(ValueError,'D3_READER_MODE'):
            D.collect(st,now,m)
        st.writer = False

    def test_projection_never_contains_raw_identity_or_model(self):
        encoded = json.dumps(self.collect('ok'),ensure_ascii=False)
        forbidden = (str(F.CID),str(F.ACTOR),'account_key','"actor":','proof','trace','revision_fingerprint',
                     F.JOB_ID,F.TRACE_ID,'합성 상품','합성 소재','cmp-synthetic','kwd-synthetic')
        for token in forbidden:
            self.assertNotIn(token,encoded)

    def test_closed_output_rejects_unknown_extra_field_and_free_text(self):
        valid = self.collect()
        for mutation in (lambda v:v.update(raw='secret'),lambda v:v['inspection'].update(error_code='secret'),lambda v:v['identity'].update(stage='secret')):
            v = copy.deepcopy(valid);mutation(v)
            with self.assertRaises(ValueError):
                D.validate_result(v)

    def test_sql_authorizer_blocks_every_mutation_attach_and_arbitrary_function(self):
        st,m,now = self.fixture()
        c = st._conn
        c.create_function('invented_secret_function',0,lambda:'secret')
        for statement in ("UPDATE naver_auto_meta SET value='x'",'CREATE TABLE x(y)','DROP TABLE naver_auto_meta',
                          "ATTACH DATABASE ':memory:' AS other","SELECT load_extension('no')",
                          'SELECT invented_secret_function()', 'PRAGMA query_only=OFF','SAVEPOINT x','COMMIT'):
            with self.subTest(statement=statement),self.assertRaises(sqlite3.Error):
                c.execute(statement)
        self.assertEqual(c.execute('PRAGMA query_only').fetchone(),(1,))

    def test_disk_database_ro_uri_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve()/'invented.db'
            c = sqlite3.connect(path);c.execute('CREATE TABLE synthetic(v)');c.commit();c.close()
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            c = D.connect_reader(path)
            try:
                c.execute('BEGIN');self.assertEqual(c.execute('SELECT count(*) FROM synthetic').fetchone(),(0,))
                with self.assertRaises(sqlite3.Error):c.execute('INSERT INTO synthetic VALUES(1)')
                c.execute('ROLLBACK')
            finally:c.close()
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
            alias = Path(tmp).resolve()/'alias.db';alias.symlink_to(path)
            with self.assertRaisesRegex(ValueError,'D3_DATABASE_PATH'):D.connect_reader(alias)


if __name__ == '__main__':
    unittest.main()
