"""실제 읽기 관문·판정·SQLite를 잇는 지속 상세점검 회귀. HTTP는 합성 전용."""
from datetime import timedelta
import sqlite3
import socket
import sys
import unittest
from unittest.mock import patch

from naver_engine import morning as M, store as S
from naver_engine import erp_read as E, morning_progress as CP
from app.naver_auto import matching as Match
from naver_engine.tests import test_morning as TM
from naver_engine.tests import test_morning_continuous as MC


class MorningProgressTests(MC.ContinuousMorningTests):

    def seed(self, count=29):
        self.standard_ads()
        self.ads.add(TM.A, [(n,"ELIGIBLE",False,TM.steady()) for n in range(1,count+1)])
        self.scene()

    def tick(self, calls=24):
        reader = self.reader()
        with reader.bounded_requests(max_calls=calls,max_seconds=30):
            result = M.run_continuous(reader, self.monitored(), self.fc.now)
        self.assertLessEqual(reader.calls,calls)
        return result

    def saved(self):
        return self.st.morning_progress(TM.A,11,self.fc.now().date(),self.fc.now())

    def test_campaign_auth_failure_invalidates_prior_budget_progress(self):
        self.seed(3)
        self.tick(4)
        self.assertIsNotNone(self.saved())
        self.ads.fail[(TM.A,"camps")] = (403,{"code":1002})
        self.tick()
        self.assertIsNone(self.saved())
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["status"],"key_rejected")

    def test_restart_resumes_real_persisted_chunks_and_never_repeats_verified_daily(self):
        self.seed()
        self.tick()
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))
        reopened = sqlite3.connect(":memory:",isolation_level=None)
        self.st._conn.backup(reopened)  # OS 파일 잠금은 Linux 별도 시험, 여기서는 새 SQLite 연결에서 재개.
        self.st.close()
        self.st = S.Store(reopened,":memory:",None,writer=True,clock=self.fc.now)
        self.tick()
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["yday_spend"],580000)
        daily = [v for k,v in self.ads.stats_calls if k == "daily"]
        self.assertEqual(len(daily),len(set(daily)))
        self.assertIsNone(self.saved())

    def test_final_verification_budget_yield_preserves_all_chunks(self):
        self.seed(2)
        self.tick(5)  # 캠페인/비즈머니/합계/일별2개 다음 최종 목록 전에 중단.
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))
        before = list(self.ads.stats_calls)
        self.tick(3)  # 다음 회차에는 목록/비즈머니/최종 목록만 필요.
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["status"],"ok")
        self.assertEqual(self.ads.stats_calls,before)

    def test_timestamp_refresh_and_campaign_reorder_keep_semantically_identical_progress(self):
        self.seed(3)
        self.tick(4)
        generation = self.saved()["generation"]
        self.fc.advance(1)
        catalog = self.st.account_catalog()
        self.st.record_account_catalog({"generated_at": self.fc.now().isoformat(), "total":2,
            "complete":True,"items":catalog["items"]},
            [E.NaverIdRow(11,Match.VENDOR_NAVER,str(TM.A)),E.NaverIdRow(12,Match.VENDOR_NAVER,str(TM.B))],self.fc.now())
        self.st.record_accounts(TM.kids(TM.A,TM.B),self.fc.now())
        self.ads.acc[TM.A]["campaigns"].reverse()
        self.assertEqual(self.saved()["generation"],generation)
        self.tick(5)
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["yday_spend"],60000)
        calls = [v for k,v in self.ads.stats_calls if k == "daily"]
        self.assertEqual(len(calls),len(set(calls)))

    def test_same_campaign_ids_but_changed_verdict_input_invalidates_cached_zero(self):
        self.seed(2)
        self.ads.acc[TM.A]["campaigns"][0]["userLock"] = True
        first = self.ads.acc[TM.A]["campaigns"][0]["nccCampaignId"]
        self.ads.acc[TM.A]["series"][first] = TM.quiet
        self.tick(3)
        self.ads.acc[TM.A]["campaigns"][0]["userLock"] = False
        self.ads.acc[TM.A]["series"][first] = TM.steady()
        self.tick()
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["yday_spend"],40000)
        self.assertEqual(len([v for k,v in self.ads.stats_calls if k == "summary"]),3)  # A 두 번+B 한 번

    def test_current_pid_change_cannot_publish_previous_company_progress(self):
        self.seed(3)
        self.tick(4)
        old = self.saved()["generation"]
        self.st.record_decision(12,TM.A,"confirmed",0,self.fc.now())
        self.assertIsNone(self.st.morning_progress(TM.A,12,self.fc.now().date(),self.fc.now()))
        self.tick()
        row = self.st.account_day(TM.A,TM.TODAY)
        self.assertEqual((row["possibility_id"],row["yday_spend"]),(12,60000))
        first = f"cmp-{TM.A}-1"
        self.assertEqual([v for k,v in self.ads.stats_calls if k == "daily"].count(first),2)
        head = self.st._conn.execute("SELECT generation FROM naver_auto_morning_progress WHERE customer_id=?",(TM.A,)).fetchone()
        self.assertGreater(head[0],old)

    def test_next_day_uses_new_window_without_accumulating_day_rows(self):
        from naver_engine.tests import test_alerts as TA
        self.seed(3)
        self.tick(4)
        self.fc.advance(24*60*60)
        self.ads.cycle += timedelta(days=1)
        self.st.record_org(TA.org_body(self.fc.now()),self.fc.now())
        catalog = self.st.account_catalog()
        self.st.record_account_catalog({"generated_at":self.fc.now().isoformat(),"total":2,
            "complete":True,"items":catalog["items"]},
            [E.NaverIdRow(11,Match.VENDOR_NAVER,str(TM.A)),E.NaverIdRow(12,Match.VENDOR_NAVER,str(TM.B))],self.fc.now())
        self.st.record_accounts(TM.kids(TM.A,TM.B),self.fc.now())
        self.tick()
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))
        self.assertEqual(self.st.account_day(TM.A,self.fc.now().date())["yday_spend"],60000)
        self.assertEqual(self.st._conn.execute("SELECT COUNT(*) FROM naver_auto_morning_progress WHERE customer_id=?",(TM.A,)).fetchone()[0],1)

    def test_data_late_consumes_complete_checkpoint_and_next_attempt_reads_fresh_stats(self):
        self.seed(2)
        self.ads.cycle -= timedelta(days=1)
        self.tick()
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["status"],"data_late")
        self.assertIsNone(self.saved())
        before = len(self.ads.stats_calls)
        self.ads.cycle += timedelta(days=1)
        self.tick()
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["status"],"ok")
        self.assertGreater(len(self.ads.stats_calls),before)

    def test_summary_batches_resume_before_any_daily_responses(self):
        self.seed(201)
        self.ads.acc[TM.A]["series"] = {k:TM.quiet for k in self.ads.acc[TM.A]["series"]}
        for row in self.ads.acc[TM.A]["campaigns"]:
            row["userLock"] = True
        self.tick(3)
        self.tick(3)
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))
        self.tick(4)
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["yday_spend"],0)
        batches = [v for k,v in self.ads.stats_calls if k == "summary"]
        self.assertEqual([len(v) for v in batches],[100,100,1])
        self.assertEqual(len({i for batch in batches for i in batch}),201)

    def test_empty_campaigns_require_final_confirmation_even_across_budget_boundary(self):
        self.seed(0)
        self.tick(2)
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))
        self.tick(3)
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["yday_spend"],0)
        self.assertEqual(self.ads.stats_calls,[])

    def test_final_same_id_status_change_never_publishes_partial_account(self):
        self.seed(2)
        seen = []
        def change(call):
            if call.path == "/ncc/campaigns" and int(call.customer) == TM.A:
                seen.append(call)
                if len(seen) == 2:
                    self.ads.acc[TM.A]["campaigns"][0]["sharedBudgetLock"] = True
        self.naver.tick = change
        result = self.tick()
        self.assertIn(M.CODE_HANDLE_INVALID,result.codes)
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))
        self.assertIsNone(self.saved())

    def test_actual_rate_failure_discards_progress_and_keeps_failed_run_backoff(self):
        self.seed(3)
        self.tick(4)
        self.ads.fail[(TM.A,"stats")] = (429,{"code":1014})
        result = self.tick(4)
        self.assertIn(M.CODE_RUN_ABORT,result.codes)
        self.assertIsNone(self.saved())
        self.assertFalse(M.continuous_due(self.monitored(),self.fc.now()))
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))

    def test_bizmoney_auth_then_budget_cut_does_not_preserve_old_progress(self):
        self.seed(3)
        self.tick(4)
        self.ads.fail[(TM.A,"biz")] = (403,{"code":1002})
        self.tick(2)
        self.assertIsNone(self.saved())

    def test_completed_checkpoint_survives_ledger_transaction_failure(self):
        self.seed(2)
        self.st._conn.set_authorizer(lambda action,a,b,c,d:
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and a == "naver_auto_account_day" else sqlite3.SQLITE_OK)
        with self.assertRaises(S.StoreError):
            self.tick()
        self.st._conn.set_authorizer(S._authorizer(S.PHASE_RUN))
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))
        self.assertIsNotNone(self.saved())
        count = len([v for k,v in self.ads.stats_calls if k == "daily"])
        self.fc.advance(20*60)
        self.tick(3)
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["yday_spend"],40000)
        self.assertEqual(len([v for k,v in self.ads.stats_calls if k == "daily"]),count)

    def test_checkpoint_consumption_failure_rolls_back_entire_account_ledger(self):
        self.seed(2)
        self.tick(5)
        self.st._conn.set_authorizer(lambda action,a,b,c,d:
            sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_UPDATE and a == "naver_auto_morning_progress" and b == "status"
            else sqlite3.SQLITE_OK)
        with self.assertRaises(S.StoreError):
            self.tick(3)
        self.st._conn.set_authorizer(S._authorizer(S.PHASE_RUN))
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY))
        self.assertIsNotNone(self.saved())

    def test_payload_limit_is_account_partial_and_hourly_bounded_without_http_loop(self):
        self.seed(3)
        with patch.object(CP,"MAX_BYTES",100):
            result = self.tick()
        self.assertIn("CHECKPOINT_TOO_LARGE",result.codes)
        row = self.st.account_day(TM.A,TM.TODAY)
        self.assertEqual(row["status"],"partial")
        self.assertIsNone(row["yday_spend"])
        self.assertTrue(all(reason == "checkpoint-too-large" for _,reason in row["rules_not_run"]))
        count = len(self.naver.calls)
        self.tick()
        self.assertEqual(len(self.naver.calls),count)
        self.fc.advance(60*60)
        self.tick()
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["status"],"ok")

    def test_corrupt_payload_is_not_used_as_zero_or_complete(self):
        self.seed(3)
        self.tick(4)
        self.st._conn.execute("UPDATE naver_auto_morning_chunk SET body='{}' WHERE customer_id=?",(TM.A,))
        result = self.tick()
        self.assertIn("CHECKPOINT_INVALID",result.codes)
        self.assertIsNone(self.saved())
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["status"],"partial")
        self.assertIsNone(self.st.account_day(TM.A,TM.TODAY)["yday_spend"])
        self.tick()
        self.assertEqual(self.st.account_day(TM.A,TM.TODAY)["status"],"ok")


class ProgressMigrationTests(unittest.TestCase):
    def test_additive_migration_preserves_old_rows_version_and_read_only_contract(self):
        connection = sqlite3.connect(":memory:",isolation_level=None)
        for sql in S._SCHEMA:
            if "naver_auto_morning_" not in sql:
                connection.execute(sql)
        connection.execute("INSERT INTO naver_auto_meta VALUES ('schema_version',?)",(str(S.SCHEMA_VERSION),))
        store = S.Store(connection,":memory:",None,writer=True,clock=lambda:TM.T0)
        self.addCleanup(store.close)
        store.record_accounts(TM.kids(TM.A),TM.T0)
        before = store.accounts()
        store._migrate()
        store._migrate()
        self.assertEqual(store.accounts(),before)
        self.assertEqual(store.meta("schema_version"),"11")
        with self.assertRaises(sqlite3.DatabaseError):
            connection.execute("DELETE FROM naver_auto_morning_progress")
        reader_connection = sqlite3.connect(":memory:",isolation_level=None)
        connection.backup(reader_connection)
        reader_connection.set_authorizer(S._authorizer(S.PHASE_READ))
        reader = S.Store(reader_connection,":memory:",None,writer=False,clock=lambda:TM.T0)
        self.addCleanup(reader.close)
        self.assertEqual(reader.accounts(),before)  # 구판 명시열 조회에 영향 없는 추가 표만 사용.
        self.assertEqual(reader.meta("schema_version"),"11")
        with self.assertRaises(S.StoreRefused):
            reader.finish_morning_progress(TM.A,1,TM.T0)

    @unittest.skipUnless(sys.platform == "linux","실제 inode 잠금/WAL 재시작은 Linux에서 검증")
    def test_linux_file_restart_keeps_progress_without_relaxing_single_writer_lock(self):
        fixture = MorningProgressTests()
        with patch.object(socket.socket,"connect",side_effect=AssertionError("외부 송신 금지")):
            TM.Base.setUp(fixture)
            try:
                fixture.seed()
                fixture.tick()
                path = fixture.path
                fixture.st.close()
                fixture.st = S.open_writer(path,clock=fixture.fc.now)
                with self.assertRaises(S.StoreBusy):
                    S.open_writer(path,clock=fixture.fc.now)
                fixture.tick()
                with S.open_reader(path) as reader:
                    self.assertEqual(reader.account_day(TM.A,TM.TODAY)["yday_spend"],580000)
                    self.assertEqual(reader.meta("schema_version"),"11")
                daily = [v for k,v in fixture.ads.stats_calls if k == "daily"]
                self.assertEqual(len(daily),len(set(daily)))
            finally:
                TM.Base.tearDown(fixture)
