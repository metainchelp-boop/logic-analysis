"""실제 Store·합성 GET의 원천 귀속과 보고서 갱신 전달. 운영 자료·외부 송신 없음."""
from datetime import date, timedelta
from pathlib import Path
import json
import runpy
import socket
import unittest
from unittest.mock import patch

from naver_engine import management as M, naver_read as N, performance_reads as P, reporting as R, store as S
from naver_engine.tests.test_morning import creds
from naver_engine.tests.test_report_revisions import ReportAdapter
from naver_runtime.scheduler import run_report_cycle


make_fixture = runpy.run_path(str(Path(__file__).resolve().parents[2] /
    "tools/naver-store-selection-benchmark.py"))["make_fixture"]


class PerformanceReportDirtyTest(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        self.fixture = make_fixture(1, 1, campaigns=1)
        self.store, self.clock = self.fixture.store, self.fixture.clock
        self.addCleanup(self.store.close)
        self.clock.advance(3600)  # 닫힌 주간 보고서의 생성 시각 이후
        self.store.now = self.clock.now()
        self.customer_id = self.store.accounts()[0]["customer_id"]
        self.month = R.period("monthly", date(2026, 9, 1))
        self.week = R.period("weekly", date(2026, 9, 28))
        ReportAdapter.seed(self.store, self.month.start, self.month.end,
                           cid=self.customer_id, pid=11)
        self.store._conn.execute("""UPDATE naver_auto_daily_performance SET possibility_id=NULL
            WHERE customer_id=? AND day>='2026-09-27'""", (self.customer_id,))

    def report(self, period):
        row = self.store._conn.execute("""SELECT report_id,payload_json FROM naver_auto_report_snapshot
            WHERE possibility_id=11 AND period_key=? ORDER BY report_id DESC LIMIT 1""",
            (period.key,)).fetchone()
        return row[0], json.loads(row[1])

    def dirty(self):
        return self.store._conn.execute("""SELECT pending FROM naver_auto_report_dirty
            WHERE possibility_id=11 AND period_key=?""", (self.month.key,)).fetchone()[0]

    def collect_week(self, *, newer_source=True, unknown_conversion=False):
        self.clock.advance(60)
        if newer_source:
            self.fixture.cycle = self.clock.now()
        if unknown_conversion:
            self.fixture.rows[self.fixture.campaigns[0]["nccCampaignId"]] = dict(
                impCnt=100, clkCnt=10, salesAmt=1000, ccnt=None, convAmt=None)
        decisions = self.store.synchronize_management(self.clock.now())
        job = self.store._performance_job(self.customer_id, "report_weekly", self.clock.now().date(),
            self.week.start, self.week.end, decisions[self.customer_id],
            self.store.inventory_snapshot(self.clock.now()), self.store.account_catalog()["generated_at"])
        self.assertTrue(self.store.performance_account_valid(job, self.clock.now()))
        reader = N.NaverReader(creds(), transport=self.fixture.http, clock=self.clock)
        # 후보만 고정한다. 권한·귀속·실제 저장·일별 GET은 모두 제품 코드를 거친다.
        with patch.object(self.store, "performance_work", return_value=[job]):
            result = P.run_performance(reader, self.store, self.clock.now, limit=1)
        self.assertEqual(result.counts, {"ok": 1})
        self.assertTrue(all(call.method == "GET" for call in self.fixture.http.calls))

    def completed_collection_jobs(self):
        """지난 성공 회차만 합성한다. 이후 보충 후보·GET·저장은 실제 공개 경로를 실행한다."""
        today = self.clock.now().date()
        decisions = self.store.synchronize_management(self.clock.now())
        kinds = [("daily", today, today-timedelta(days=1), today-timedelta(days=1)),
                 *M.revalidation_periods(today, managed=True)]
        for kind, cycle, start, end in kinds:
            job = self.store._performance_job(self.customer_id, kind, cycle, start, end,
                decisions[self.customer_id], self.store.inventory_snapshot(self.clock.now()),
                self.store.account_catalog()["generated_at"])
            self.store.begin_performance_check(job, self.clock.now())
            self.store._conn.execute("UPDATE naver_auto_performance_job SET status='ok' WHERE job_key=?",
                                     (job["job_key"],))
        ReportAdapter.seed(self.store, today.replace(day=1), today-timedelta(days=1),
                           cid=self.customer_id, pid=11)

    def test_complete_raw_repairs_stale_month_without_source_requests(self):
        run_report_cycle(self.store, self.clock.now())
        old_id, old = self.report(self.month)
        self.store._conn.execute("""UPDATE naver_auto_daily_performance SET possibility_id=11
            WHERE customer_id=? AND day>='2026-09-27'""", (self.customer_id,))
        self.assertEqual(self.dirty(), 0)
        run_report_cycle(self.store, self.clock.now())
        new_id, month = self.report(self.month)
        self.assertGreater(new_id, old_id)
        self.assertEqual(month["coverage"]["basic_complete_account_days"], 30)
        self.assertEqual(month["coverage"]["conversion_complete_account_days"], 30)
        frozen = self.store._conn.execute("SELECT payload_json FROM naver_auto_report_snapshot WHERE report_id=?",
                                          (old_id,)).fetchone()[0]
        self.assertEqual(json.loads(frozen), old)
        self.assertEqual(self.fixture.http.calls, [])

    def test_previous_month_null_gap_is_collected_then_report_becomes_30(self):
        run_report_cycle(self.store, self.clock.now())
        self.store._conn.execute("""UPDATE naver_auto_daily_performance SET possibility_id=11
            WHERE customer_id=? AND day>='2026-09-28'""", (self.customer_id,))
        self.assertEqual(len(self.store.daily_performance([self.customer_id], self.month.start,
                         self.month.end, possibility_id=11)), 29)
        self.completed_collection_jobs()
        self.clock.advance(60)
        self.fixture.cycle = self.clock.now()
        self.fixture.rows[self.fixture.campaigns[0]["nccCampaignId"]] = dict(
            impCnt=100, clkCnt=10, salesAmt=1000, ccnt=None, convAmt=None)
        jobs = self.store.performance_work(self.clock.now())
        self.assertEqual([(job["kind"], job["period_start"], job["period_end"]) for job in jobs],
                         [("backfill", "2026-09-27", "2026-09-30")])
        self.assertEqual(jobs[0]["cycle_day"], "2026-10-05")
        self.assertTrue(self.store.performance_account_valid(jobs[0], self.clock.now()))
        reader = N.NaverReader(creds(), transport=self.fixture.http, clock=self.clock)
        result = P.run_performance(reader, self.store, self.clock.now, limit=1)
        self.assertEqual(result.counts, {"ok": 1})
        self.assertEqual(reader.calls, 4)
        self.assertTrue(all(call.method == "GET" for call in self.fixture.http.calls))
        run_report_cycle(self.store, self.clock.now())
        month = self.report(self.month)[1]
        self.assertEqual(month["coverage"]["basic_complete_account_days"], 30)
        self.assertEqual(month["coverage"]["conversion_complete_account_days"], 26)
        self.assertFalse(month["coverage"]["conversion_complete"])
        for row in self.store.daily_performance([self.customer_id], date(2026, 9, 27), self.month.end):
            self.assertEqual(row["possibility_id"], 11)
            self.assertIsNone(row["conversions"])
            self.assertIsNone(row["conversion_value"])

    def test_previous_month_backfill_requires_daily_success_and_ignores_protected_gaps(self):
        self.completed_collection_jobs()
        self.store._conn.execute("""UPDATE naver_auto_performance_job SET status='retry',error_code='NETWORK'
            WHERE kind='daily'""")
        self.assertFalse(any(job["kind"] == "backfill" and job["period_end"] == "2026-09-30"
                             for job in self.store.performance_work(self.clock.now())))
        self.store._conn.execute("UPDATE naver_auto_performance_job SET status='ok' WHERE kind='daily'")
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET possibility_id=12 WHERE day<'2026-10-01'")
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET possibility_id=NULL WHERE day='2026-09-02'")
        with patch.object(self.store, "_performance_attribution_start", return_value="2026-09-21"):
            self.assertFalse(any(job["kind"] == "backfill" and job["period_end"] == "2026-09-30"
                                 for job in self.store.performance_work(self.clock.now())))

    def test_previous_backfill_keeps_other_owner_inside_the_requested_interval(self):
        self.store._conn.execute("""UPDATE naver_auto_daily_performance SET possibility_id=11
            WHERE day>='2026-09-29'""")
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET possibility_id=12 WHERE day='2026-09-28'")
        protected = self.store.daily_performance([self.customer_id], date(2026, 9, 28), date(2026, 9, 28))
        self.completed_collection_jobs()
        self.clock.advance(60)
        self.fixture.cycle = self.clock.now()
        reader = N.NaverReader(creds(), transport=self.fixture.http, clock=self.clock)
        self.assertEqual(P.run_performance(reader, self.store, self.clock.now, limit=1).counts, {"ok": 1})
        self.assertEqual(self.store.daily_performance([self.customer_id], date(2026, 9, 28), date(2026, 9, 28)), protected)
        run_report_cycle(self.store, self.clock.now())
        self.assertEqual(self.report(self.month)[1]["coverage"]["basic_complete_account_days"], 29)

    def test_previous_month_validator_refuses_older_or_cross_month_ranges(self):
        self.completed_collection_jobs()
        decisions = self.store.synchronize_management(self.clock.now())
        for start, end, valid in ((date(2026, 9, 1), date(2026, 9, 30), True),
                                  (date(2026, 8, 31), date(2026, 9, 30), False),
                                  (date(2026, 8, 1), date(2026, 8, 31), False)):
            job = self.store._performance_job(self.customer_id, "backfill", self.clock.now().date(),
                start, end, decisions[self.customer_id], self.store.inventory_snapshot(self.clock.now()),
                self.store.account_catalog()["generated_at"])
            self.assertEqual(self.store.performance_account_valid(job, self.clock.now()), valid)

    def test_future_or_invalid_metrics_do_not_claim_report_completeness(self):
        run_report_cycle(self.store, self.clock.now())
        old_id, _ = self.report(self.month)
        self.store._conn.execute("""UPDATE naver_auto_daily_performance SET possibility_id=11,checked_at=?
            WHERE day>='2026-09-27'""", ((self.clock.now()+timedelta(hours=1)).isoformat(),))
        run_report_cycle(self.store, self.clock.now())
        self.assertEqual(self.report(self.month)[0], old_id)
        self.store._conn.execute("""UPDATE naver_auto_daily_performance SET checked_at=?,imp=NULL,
            conversions=NULL,conversion_value=NULL WHERE day>='2026-09-27'""", (self.clock.now().isoformat(),))
        run_report_cycle(self.store, self.clock.now())
        self.assertEqual(self.report(self.month)[0], old_id)
        self.assertEqual(self.dirty(), 0)

    def test_adopted_rows_requeue_month_and_week_without_fabricating_conversion(self):
        run_report_cycle(self.store, self.clock.now())
        old_id, old = self.report(self.month)
        self.assertEqual(old["coverage"]["basic_complete_account_days"], 26)
        self.collect_week(unknown_conversion=True)
        self.assertEqual(len(self.store.daily_performance([self.customer_id], self.month.start,
                         self.month.end, possibility_id=11)), 29)
        self.assertEqual(self.dirty(), 1)
        run_report_cycle(self.store, self.clock.now())
        new_id, month = self.report(self.month)
        self.assertGreater(new_id, old_id)
        self.assertEqual(month["coverage"]["basic_complete_account_days"], 29)
        self.assertEqual(self.report(self.week)[1]["coverage"]["basic_complete_account_days"], 7)
        for row in self.store.daily_performance([self.customer_id], self.week.start, self.week.end):
            self.assertFalse(row["conversion_complete"])
            self.assertIsNone(row["conversions"])
            self.assertIsNone(row["conversion_value"])

    def test_other_owner_rows_are_preserved_and_not_claimed_by_current_report(self):
        self.store._conn.execute("""UPDATE naver_auto_daily_performance SET possibility_id=12
            WHERE customer_id=? AND day BETWEEN '2026-09-28' AND '2026-09-30'""", (self.customer_id,))
        before = self.store.daily_performance([self.customer_id], date(2026, 9, 28), date(2026, 9, 30))
        run_report_cycle(self.store, self.clock.now())
        self.collect_week()
        self.assertEqual(self.store.daily_performance([self.customer_id], date(2026, 9, 28),
                         date(2026, 9, 30)), before)
        self.assertEqual(self.dirty(), 0)
        run_report_cycle(self.store, self.clock.now())
        self.assertEqual(self.report(self.month)[1]["coverage"]["basic_complete_account_days"], 26)
        self.assertEqual(self.report(self.week)[1]["coverage"]["basic_complete_account_days"], 4)

    def test_older_source_does_not_adopt_or_overwrite_existing_rows(self):
        before = self.store.daily_performance([self.customer_id], date(2026, 9, 27), date(2026, 9, 30))
        run_report_cycle(self.store, self.clock.now())
        self.collect_week(newer_source=False)
        self.assertEqual(self.store.daily_performance([self.customer_id], date(2026, 9, 27),
                         date(2026, 9, 30)), before)
        self.assertEqual(self.dirty(), 0)
        run_report_cycle(self.store, self.clock.now())
        self.assertEqual(self.report(self.month)[1]["coverage"]["basic_complete_account_days"], 26)
        self.assertEqual(self.report(self.week)[1]["coverage"]["basic_complete_account_days"], 4)


class ReportRecoveryReadBudgetTest(unittest.TestCase):
    def test_reconciliation_keeps_an_already_pending_company_in_its_existing_queue_position(self):
        store = ReportAdapter()
        self.addCleanup(store._conn.close)
        store.seed(date(2026, 9, 1), date(2026, 9, 30))
        run_report_cycle(store, store.now)
        store._conn.execute("""UPDATE naver_auto_daily_performance SET conversion_complete=0,
            conversions=NULL,conversion_value=NULL WHERE day='2026-09-27'""")
        key = R.period("monthly", date(2026, 9, 1)).key
        before = (store.now-timedelta(hours=1)).isoformat()
        store._conn.execute("UPDATE naver_auto_report_dirty SET pending=1,updated_at=? WHERE period_key=?", (before, key))
        S._report_plan(store, store.now)
        self.assertEqual(store._conn.execute("SELECT updated_at FROM naver_auto_report_dirty WHERE period_key=?", (key,)).fetchone()[0], before)

    def test_100_companies_use_one_previous_month_raw_read_and_cached_snapshot_counts(self):
        store = ReportAdapter()
        self.addCleanup(store._conn.close)
        store.groups = {101+n: 11+n for n in range(100)}
        for cid, pid in store.groups.items():
            store.seed(date(2026, 9, 1), date(2026, 9, 30), cid=cid, pid=pid)
        for _ in range(5):
            run_report_cycle(store, store.now)
        S._report_plan(store, store.now)  # 마지막 조각의 새 판 사실까지 기억한다.
        statements = []
        store._conn.set_trace_callback(statements.append)
        try:
            S._report_plan(store, store.now)
        finally:
            store._conn.set_trace_callback(None)
        raw = [sql for sql in statements if "FROM naver_auto_daily_performance" in sql]
        self.assertEqual(len(raw), 1)
        self.assertIn("day BETWEEN '2026-09-01' AND '2026-09-30'", raw[0])
        self.assertFalse(any("json_extract" in sql or "payload_json" in sql for sql in statements))
        self.assertLessEqual(len(store._report_coverage_cache), len(store._report_fact_cache))

if __name__ == "__main__":
    unittest.main()
