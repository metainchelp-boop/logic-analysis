"""시간 창/3회 상한에 잘렸던 자동 이슈 점검의 연속 실행. 외부 HTTP 없음."""
from datetime import timedelta
import sqlite3
import socket
from unittest.mock import patch
from naver_engine import morning as M, store as S
from naver_engine.tests.test_morning import Base, A, B, T0, Ads, FakeClock, FakeNaver
from naver_engine.tests import test_alerts as TA, test_account_catalog as TC, test_morning as TM
from naver_runtime.scheduler import _ManagedMorningStore
from naver_engine import erp_read as E
from app.naver_auto import matching as Match


class ContinuousMorningTests(Base):
    def setUp(self):
        guard = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        guard.start()
        self.addCleanup(guard.stop)
        self.fc = FakeClock(T0)
        connection = sqlite3.connect(":memory:", isolation_level=None)
        for statement in S._SCHEMA:
            connection.execute(statement)
        for table, columns in S._REVISION_COLUMNS.items():
            for name, definition in columns:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        self.st = S.Store(connection, ":memory:", None, writer=True, clock=self.fc.now)
        self.naver = FakeNaver()
        self.ads = Ads(self.naver)

    def tearDown(self):
        self.st.close()

    def scene(self, **kwargs):
        result = super().scene(**kwargs)
        self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
        self.st.record_account_catalog({"generated_at": self.fc.now().isoformat(), "total": 2, "complete": True,
            "items": [TC.company(11, "진행중", company_name=TM.shop(11)), TC.company(12, "진행중", company_name=TM.shop(12))]},
            [E.NaverIdRow(11, Match.VENDOR_NAVER, str(A)), E.NaverIdRow(12, Match.VENDOR_NAVER, str(B))], self.fc.now())
        return result

    def monitored(self):
        return _ManagedMorningStore(self.st, self.fc.now())

    def test_after_eight_and_three_runs_remaining_account_is_checked_once(self):
        self.standard_ads()
        self.scene()
        for _ in range(3):
            rid = self.st.begin_run(self.fc.now().date(), self.fc.now())
            self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        self.fc.advance(90*60)
        self.assertTrue(M.continuous_due(self.monitored(), self.fc.now()))
        result = M.run_continuous(self.reader(), self.monitored(), self.fc.now)
        self.assertEqual(result.outcome, M.OUT_DONE)
        self.assertIsNotNone(self.st.account_day(A, T0.date()))
        self.assertIsNotNone(self.st.account_day(B, T0.date()))
        self.assertFalse(M.continuous_due(self.monitored(), self.fc.now()))

    def test_internal_yield_keeps_completed_account_and_continues_remaining(self):
        self.standard_ads()
        self.scene()
        reader = self.reader()
        with reader.bounded_requests(max_calls=4, max_seconds=30):
            result = M.run_continuous(reader, self.monitored(), self.fc.now)
        self.assertIn("BUDGET_YIELD", result.codes)
        self.assertNotIn(M.CODE_RUN_ABORT, result.codes)
        self.assertFalse(result.alert)
        self.assertTrue(M.continuous_due(self.monitored(), self.fc.now()))
        result = M.run_continuous(self.reader(), self.monitored(), self.fc.now)
        self.assertEqual(result.outcome, M.OUT_DONE)

    def test_monitoring_does_not_use_legacy_end_plus_fourteen_days(self):
        self.standard_ads()
        self.scene(ends={11:T0.date()-timedelta(days=60)})
        result = M.run_continuous(self.reader(), self.monitored(), self.fc.now)
        self.assertEqual(result.outcome, M.OUT_DONE)
        self.assertEqual(self.st.account_day(A, T0.date())["status"], "ok")

    def test_current_sources_allow_continuation_before_legacy_six_thirty_start(self):
        self.standard_ads()
        self.scene(t=T0.replace(hour=0,minute=10))
        self.assertTrue(M.continuous_due(self.monitored(), self.fc.now()))
        self.assertEqual(M.run_continuous(self.reader(), self.monitored(), self.fc.now).outcome, M.OUT_DONE)
        self.assertIsNotNone(self.st.account_day(A, T0.date()))

    def test_current_delegation_protects_issue_omitted_by_legacy_end_filter(self):
        self.standard_ads()
        self.ads.acc[A]["biz"] = 0
        self.scene(ends={11:T0.date()-timedelta(days=60)})
        M.run_continuous(self.reader(), self.monitored(), self.fc.now)
        opened = [row for row in self.st.issues(open_only=True) if row["customer_id"] == A]
        self.assertTrue(opened)
        self.st._conn.execute("DELETE FROM naver_auto_link_memory WHERE customer_id=?", (A,))
        rid = self.st.begin_run(T0.date(), self.fc.now())
        pairing = self.st.last_pairing(S.SYNC_ACCEPTED)["pairing_id"]
        closed = self.st.close_unlinked_issues(rid, pairing, self.fc.now(), account_monitoring=True)
        self.assertEqual(closed.closed_issues, 0)
        self.assertEqual([r["issue_id"] for r in self.st.issues(open_only=True) if r["customer_id"] == A],
                         [r["issue_id"] for r in opened])

    def test_large_account_budget_yield_resumes_without_publishing_incomplete_account(self):
        self.standard_ads()
        self.ads.add(A, [(n,"ELIGIBLE",False,TM.steady()) for n in range(1,30)])
        self.scene()
        for attempt in range(2):
            reader = self.reader()
            with reader.bounded_requests(max_calls=24,max_seconds=30):
                result = M.run_continuous(reader, self.monitored(), self.fc.now)
            if attempt == 0:
                self.assertIn("BUDGET_YIELD", result.codes)
                self.assertIsNone(self.st.account_day(A,T0.date()))
            self.assertLessEqual(reader.calls,24)
        day = self.st.account_day(A,T0.date())
        self.assertIsNotNone(day)
        self.assertEqual(day["status"], "ok")
        self.assertEqual(day["yday_spend"], 29 * 20000)
        daily = [value for kind,value in self.ads.stats_calls if kind == "daily"]
        self.assertEqual(len(daily), len(set(daily)))
