"""현재 재대조 표시와 불변 수치판을 함께 검증한다. 합성 메모리 DB, 외부 호출 없음."""
from datetime import date, timedelta
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from naver_engine import reporting as R, report_views as RV, store as S
from naver_engine.tests.test_report_revisions import ReportAdapter


class ReportRefreshTests(unittest.TestCase):
    def setUp(self):
        self.store = ReportAdapter()
        self.addCleanup(self.store._conn.close)
        self.ctx = SimpleNamespace(now=self.store.now, org=None,
            accounts={101: {"account_name": "합성 계정", "ad_account_no": 8000000},
                      202: {"account_name": "다른 합성 계정", "ad_account_no": 8000001}})
        for target, name, value in ((RV, "_context", ({11: {"company_name": "합성 업체", "stage": "진행중"}}, {101: 11, 202: 11})),
                                    (RV.W, "_owner", {"name": "합성 담당"}),
                                    (RV.SC, "allowed_actions", frozenset())):
            guard = patch.object(target, name, return_value=value)
            guard.start()
            self.addCleanup(guard.stop)

    def detail(self, rid, cid=101):
        self.ctx.now = self.store.now
        return RV.detail(self.ctx, self.store, None, {11: None},
            {"report_id": str(rid), "account_key": "company" if cid is None else RV.account_key(cid)})

    def latest(self, period):
        return self.store.report_latest_ids(period.key, [11])[11]

    def test_same_values_advance_account_and_company_refresh_without_new_numeric_revision(self):
        for kind in ("weekly", "monthly"):
            with self.subTest(kind=kind):
                period = R.period(kind, date(2026, 9, 28))
                self.store.seed(period.start, period.end)
                self.store.generate_reports(self.store.now)
                rid = self.latest(period)
                saved = self.store.report_snapshot_detail(rid)
                first = self.detail(rid)
                self.store.now += timedelta(hours=1)
                self.store.seed(period.start, period.end)
                self.store.generate_reports(self.store.now)
                before = self.store._conn.total_changes
                for cid in (101, None):
                    current = self.detail(rid, cid)
                    self.assertEqual(current["validation"]["last_checked_at"], self.store.now.isoformat())
                    self.assertEqual(current["refresh"]["source_collected_at"], self.store.now.isoformat())
                    self.assertEqual(current["refresh"]["scope"], "current")
                    self.assertEqual(current["generated_at"], saved["generated_at"])
                self.assertEqual(self.store._conn.total_changes, before)
                self.assertEqual(self.latest(period), rid)
                self.assertEqual(self.store.report_snapshot_detail(rid), saved)
                self.assertEqual(self.detail(rid)["payload"], first["payload"])

    def test_list_uses_the_same_latest_account_state_with_batched_source_reads(self):
        period = R.period("weekly", date(2026, 9, 28))
        self.store.seed(period.start, period.end)
        self.store.generate_reports(self.store.now)
        self.store.now += timedelta(hours=1)
        self.store.seed(period.start, period.end)
        self.store.generate_reports(self.store.now)
        self.ctx.now = self.store.now
        statements, before = [], self.store._conn.total_changes
        self.store._conn.set_trace_callback(statements.append)
        try:
            body = RV.accounts(self.ctx, self.store, None, {11: None}, {"kind": "weekly", "anchor": "2026-09-28"})
        finally:
            self.store._conn.set_trace_callback(None)
        row = next(row for row in body["rows"] if row["account_key"] == RV.account_key(101))
        self.assertEqual(row["refresh"]["last_success_at"], self.store.now.isoformat())
        self.assertEqual(row["refresh"]["source_collected_at"], self.store.now.isoformat())
        self.assertEqual(row["collection_status"], "complete")
        self.assertEqual(self.store._conn.total_changes, before)
        self.assertEqual(sum("FROM naver_auto_daily_performance" in sql for sql in statements), 1)
        self.assertEqual(sum("FROM naver_auto_performance_job" in sql for sql in statements), 1)

    def test_legacy_validation_100_reports_have_constant_batched_query_count(self):
        period = R.period("weekly", date(2026, 9, 28))
        ids = []
        for offset in range(100):
            pid, cid, rid = 1000+offset, 2000+offset, 3000+offset
            self.store.seed(period.start, period.end, cid=cid, pid=pid)
            self.store._conn.execute("""INSERT INTO naver_auto_report_snapshot
                (report_id,possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
                VALUES(?,?,?,'synthetic',?,'ready','not_required','{}')""", (rid,pid,period.key,self.store.now.isoformat()))
            self.store._conn.execute("""INSERT INTO naver_auto_report_validation
                (possibility_id,period_key,expected_customers_json,payload_json) VALUES(?,?,?,?)""",
                (pid,period.key,json.dumps([cid]),json.dumps({"status":"complete","last_checked_at":self.store.now.isoformat()})))
            ids.append(rid)
        before, statements = self.store._conn.total_changes, []
        self.store._conn.set_trace_callback(statements.append)
        try:
            states = self.store.report_refresh_states_batch(ids)
        finally:
            self.store._conn.set_trace_callback(None)
        self.assertEqual(len(states),100)
        self.assertTrue(all(state["company"]["source_collected_at"] == self.store.now.isoformat() for state in states.values()))
        self.assertEqual(sum("FROM naver_auto_daily_performance" in sql for sql in statements),1)
        self.assertEqual(sum("FROM naver_auto_performance_job" in sql for sql in statements),1)
        self.assertEqual(sum("FROM naver_auto_manual_read" in sql for sql in statements),1)
        self.assertLessEqual(len(statements),7)
        self.assertEqual(self.store._conn.total_changes,before)
        for invalid in ([True], [0], ["1"], list(range(1,102))):
            with self.subTest(invalid=invalid), self.assertRaises(S.StoreRefused):
                self.store.report_refresh_states_batch(invalid)

    def test_historical_revision_keeps_saved_validation_after_new_revision(self):
        period = R.period("weekly", date(2026, 9, 28))
        self.store.seed(period.start, period.end)
        self.store.generate_reports(self.store.now)
        rid = self.latest(period)
        first = self.detail(rid)
        self.store.now += timedelta(hours=1)
        self.store.seed(period.start, period.end, spend=2000)
        self.store.generate_reports(self.store.now)
        self.assertNotEqual(self.latest(period), rid)
        historical = self.detail(rid)
        self.assertEqual(historical["validation"], first["validation"])
        self.assertEqual(historical["payload"], first["payload"])
        self.assertEqual(historical["refresh"]["scope"], "saved")
        self.assertIsNotNone(first["refresh"]["source_collected_at"])
        self.assertEqual(historical["refresh"]["source_collected_at"], first["refresh"]["source_collected_at"])

    def test_latest_refresh_is_scoped_per_account_and_keeps_prior_success_on_failed_recheck(self):
        period = R.period("weekly", date(2026, 9, 28))
        self.store.groups[202] = 11
        for cid in (101, 202):
            self.store.seed(period.start, period.end, cid=cid)
        self.store.generate_reports(self.store.now)
        rid = self.latest(period)
        self.store.now += timedelta(hours=1)
        self.store.seed(period.start, period.end, cid=101)
        self.store.generate_reports(self.store.now)
        checked = self.detail(rid)["validation"]["last_checked_at"]
        self.assertEqual(checked, self.store.now.isoformat())
        self.assertLess(self.detail(rid, 202)["validation"]["last_checked_at"], checked)
        self.store.now += timedelta(hours=1)
        self.store.recheck(period.start, period.end, status="retry")
        before = self.store._conn.total_changes
        current = self.detail(rid)
        self.assertEqual(current["validation"]["status"], "failed")
        self.assertEqual(current["validation"]["last_checked_at"], checked)
        self.assertEqual(current["refresh"]["source_collected_at"], checked)
        self.assertEqual(self.store._conn.total_changes, before)

    def test_malformed_naive_and_future_times_remain_unknown_without_page_failure(self):
        period = R.period("weekly", date(2026, 9, 28))
        self.store.seed(period.start, period.end)
        self.store.generate_reports(self.store.now)
        rid = self.latest(period)
        self.store.recheck(period.start, period.end, status="retry")
        invalid_times = ("not-a-time", "2026-10-05T11:00:00", (self.store.now+timedelta(days=1)).isoformat())
        for invalid in invalid_times:
            with self.subTest(time=invalid):
                self.store._conn.execute("UPDATE naver_auto_performance_job SET checked_at=?", (invalid,))
                self.store._conn.execute("UPDATE naver_auto_daily_performance SET checked_at=?", (invalid,))
                report = self.detail(rid)
                self.assertEqual(report["validation"]["status"], "pending")
                self.assertIsNone(report["refresh"]["source_collected_at"])
                self.assertIsNone(report["refresh"]["last_attempt_at"])
                self.assertNotEqual(report["refresh"]["last_success_at"], invalid)

    def test_unknown_source_is_not_replaced_with_request_time(self):
        period = R.period("weekly", date(2026, 9, 28))
        self.store.seed(period.start, period.end)
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET source_at=NULL")
        self.store.generate_reports(self.store.now)
        report = self.detail(self.latest(period))
        self.assertIsNone(report["refresh"]["source_collected_at"])
        self.assertIsNone(report["validation"]["last_checked_at"])

    def test_conversion_only_gap_is_distinct_from_missing_basic_data(self):
        period = R.period("weekly", date(2026, 9, 28))
        self.store.seed(period.start, period.end)
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET conversion_complete=0,conversions=NULL,conversion_value=NULL")
        self.store.generate_reports(self.store.now)
        rid = self.latest(period)
        report = self.detail(rid)
        self.assertEqual(report["collection_status"], "conversion_unconfirmed")
        self.assertEqual(report["payload"]["coverage"]["basic_complete_account_days"], 7)
        self.assertIsNone(report["payload"]["totals"]["conversions"])
        self.store.now += timedelta(hours=1)
        self.store._conn.execute("DELETE FROM naver_auto_daily_performance WHERE day=?", (str(period.start),))
        self.store._conn.execute("UPDATE naver_auto_report_dirty SET pending=1")
        self.store.generate_reports(self.store.now)
        self.assertEqual(self.detail(self.latest(period))["collection_status"], "basic_incomplete")

    def test_numeric_zero_response_is_separate_from_saved_conversion_evidence_and_historical_editions(self):
        period = R.period("weekly", date(2026, 9, 28))
        self.store.seed(period.start, period.end)
        self.store._conn.execute("UPDATE naver_auto_daily_performance SET conversion_complete=0,conversions=0,conversion_value=0")
        self.store.generate_reports(self.store.now)
        rid = self.latest(period)
        saved = self.store.report_snapshot_detail(rid)
        before, statements = self.store._conn.total_changes, []
        self.store._conn.set_trace_callback(statements.append)
        try:
            report = self.detail(rid)
            body = RV.accounts(self.ctx, self.store, None, {11: None}, {"kind":"weekly", "anchor":"2026-09-28"})
        finally:
            self.store._conn.set_trace_callback(None)
        response = report["refresh"]["conversion_response"]
        self.assertEqual(response["status"], "complete")
        self.assertEqual(response["received_account_days"], 7)
        self.assertEqual(response["zero_account_days"], 7)
        self.assertEqual(report["validation"]["status"], "pending")
        self.assertEqual(report["collection_status"], "conversion_unconfirmed")
        self.assertIsNone(report["payload"]["totals"]["conversions"])
        row = next(row for row in body["rows"] if row["account_key"] == RV.account_key(101))
        self.assertEqual(row["refresh"]["conversion_response"], response)
        self.assertEqual(self.store._conn.total_changes, before)
        self.assertEqual(self.store.report_snapshot_detail(rid), saved)
        self.store.now += timedelta(hours=1)
        self.store.seed(period.start, period.end, spend=2000)
        self.store.generate_reports(self.store.now)
        historical = self.detail(rid)
        self.assertEqual(historical["refresh"]["scope"], "saved")
        self.assertNotIn("conversion_response", historical["refresh"])
        self.assertEqual(historical["payload"], report["payload"])


if __name__ == "__main__":
    unittest.main()
