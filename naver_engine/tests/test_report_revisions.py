"""보고서 SQL 어댑터 시험. 실제 Store WAL/파일 잠금 통합 검증과 구분한다."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
import sqlite3
from types import SimpleNamespace
import unittest

from naver_engine import reporting as R, store as S
from naver_engine.tests import test_alerts as TA, test_account_catalog as TC
from app.naver_auto import scope as SC


class ReportAdapter(S.ManagedStorage):
    def __init__(self):
        self.now = datetime(2026, 10, 5, 10, tzinfo=S.KST)
        self._conn = sqlite3.connect(":memory:", isolation_level=None)
        for sql in S._SCHEMA:
            self._conn.execute(sql)
        self.groups = {101: 11}
        self.cadence = "daily"
        self.fail_period = None

    def _need_writer(self):
        pass

    def _now(self):
        return self.now

    def _not_future(self, now, what):
        if now > self.now:
            raise S.StoreRefused("미래 시각")

    @contextmanager
    def _tx(self):
        self._conn.execute("BEGIN")
        try:
            adapter = self
            class Transaction:
                def execute(self, sql, args=()):
                    if "INSERT INTO naver_auto_report_snapshot" in sql and adapter.fail_period == args[1]:
                        raise sqlite3.OperationalError("합성 저장 실패")
                    return adapter._conn.execute(sql, args)
            yield Transaction()
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def synchronize_management(self, now):
        return {cid: {"possibility_id": pid, "decision": SimpleNamespace(cadence=self.cadence)}
                for cid, pid in self.groups.items()}

    def current_decisions(self):
        return [SimpleNamespace(customer_id=cid, possibility_id=pid, decision="confirmed")
                for cid, pid in self.groups.items()]

    def issues(self, open_only=False):
        return []

    def org_current(self):
        return {"body": TA.org_body(self.now), "generated_at": self.now}

    def account_catalog(self):
        return {"generated_at": self.now.isoformat(), "complete": True, "total": 2,
                "items": [TC.company(11), TC.company(12)]}

    def account_catalog_status(self):
        return {"state": "accepted"}

    def seed(self, start, end, cid=101, pid=11, spend=1000):
        for offset in range((end-start).days+1):
            day = start+timedelta(days=offset)
            self._conn.execute("""INSERT INTO naver_auto_daily_performance
                (customer_id,day,possibility_id,matching_fingerprint,basic_complete,conversion_complete,
                 conversion_attempts,imp,clk,spend,conversions,conversion_value,checked_at,campaign_fingerprint)
                VALUES(?,?,?,'matching',1,1,0,100,10,?,1,2000,?,'campaign')
                ON CONFLICT(customer_id,day) DO UPDATE SET spend=excluded.spend,checked_at=excluded.checked_at""",
                (cid, day.isoformat(), pid, spend, self.now.isoformat()))
            for kind in ("weekly", "monthly"):
                self._conn.execute("""INSERT INTO naver_auto_report_dirty
                    (possibility_id,period_key,updated_at,pending) VALUES(?,?,?,1)
                    ON CONFLICT(possibility_id,period_key) DO UPDATE SET updated_at=excluded.updated_at,pending=1""",
                    (pid, R.period(kind, day).key, self.now.isoformat()))

    def recheck(self, start, end, status="reading"):
        at = self.now.isoformat()
        self._conn.execute("""INSERT INTO naver_auto_performance_job
            (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,stage_revision,
             possibility_id,matching_fingerprint,status,checked_at,next_try_at,attempts)
            VALUES('recheck',101,'manual_period',?,?,?,?,?,'revision',11,'matching',?,?,?,0)
            ON CONFLICT(job_key) DO UPDATE SET status=excluded.status,checked_at=excluded.checked_at""",
            (self.now.date().isoformat(), start.isoformat(), end.isoformat(), at, at, status, at, at))
        self._conn.execute("UPDATE naver_auto_report_dirty SET pending=1,updated_at=?", (at,))


class ReportRevisionTests(unittest.TestCase):
    def setUp(self):
        self.st = ReportAdapter()
        self.addCleanup(self.st._conn.close)

    def report(self, key, pid=11):
        return next(row for row in self.st.report_snapshots()
                    if row["period_key"] == key and row["possibility_id"] == pid)

    def test_old_period_dirty_revision_is_not_limited_to_previous_month(self):
        old = R.period("monthly", date(2025, 2, 3))
        self.st.seed(old.start, old.end)
        self.st.generate_reports(self.st.now)
        first = self.report(old.key)
        self.st.now += timedelta(hours=1)
        self.st.seed(old.start, old.start, spend=0)
        self.st.generate_reports(self.st.now)
        second = self.report(old.key)
        self.assertEqual(second["revision_no"], first["revision_no"]+1)
        self.assertEqual(second["payload"]["totals"]["spend"], 27000)
        self.assertEqual(second["change_summary"]["metric_deltas"]["spend"], -1000)

    def test_unchanged_success_advances_validation_without_new_revision(self):
        month = R.period("monthly", date(2026, 9, 3))
        self.st.seed(month.start, month.end)
        self.st.generate_reports(self.st.now)
        first = self.report(month.key)
        self.st.now += timedelta(hours=1)
        self.st.seed(month.start, month.end)
        self.st.generate_reports(self.st.now)
        second = self.report(month.key)
        self.assertEqual(second["report_id"], first["report_id"])
        self.assertGreater(second["validation"]["last_checked_at"], first["validation"]["last_checked_at"])
        self.assertEqual(second["validation"]["status"], "complete")
        self.assertNotIn("_day_fingerprints", second["payload"])

    def test_affected_week_and_month_publish_atomically_and_retry_drains_dirty(self):
        month = R.period("monthly", date(2026, 8, 3))
        week = R.period("weekly", date(2026, 8, 17))
        self.st.seed(month.start, month.end)
        self.st.generate_reports(self.st.now)
        old_month, old_week = self.report(month.key), self.report(week.key)
        self.st.now += timedelta(hours=1)
        self.st.seed(week.start, week.start, spend=2000)
        self.st.fail_period = week.key
        with self.assertRaises(sqlite3.OperationalError):
            self.st.generate_reports(self.st.now)
        self.assertEqual(self.report(month.key)["report_id"], old_month["report_id"])
        self.assertEqual(self.report(week.key)["report_id"], old_week["report_id"])
        self.assertEqual(self.report(month.key)["validation"]["status"], "updating")
        self.st.fail_period = None
        self.st.generate_reports(self.st.now)
        new_month, new_week = self.report(month.key), self.report(week.key)
        self.assertGreater(new_month["report_id"], old_month["report_id"])
        self.assertGreater(new_week["report_id"], old_week["report_id"])
        self.assertEqual(new_month["validation"]["source_snapshot_fingerprint"],
                         new_week["validation"]["source_snapshot_fingerprint"])
        self.assertEqual(self.st.generate_reports(self.st.now)["generated"], 0)

    def test_history_is_owner_scoped_paginated_and_never_revives_old_approval(self):
        month = R.period("monthly", date(2026, 9, 3))
        self.st.seed(month.start, month.end)
        self.st.generate_reports(self.st.now)
        first = self.report(month.key)
        self.st.record_report_review(first["report_id"], 100, self.st.now, "approved", "원천 확인")
        for amount in (2000, 1000):
            self.st.now += timedelta(hours=1)
            self.st.seed(month.start, month.start, spend=amount)
            self.st.generate_reports(self.st.now)
        latest = self.report(month.key)
        self.assertEqual(latest["revision_fingerprint"], first["revision_fingerprint"])
        self.assertIsNone(latest["review"])
        with self.assertRaises(S.StoreRefused):
            self.st.record_report_review(first["report_id"], 100, self.st.now, "approved", "옛 판")
        with self.assertRaises(SC.ScopeError):
            self.st.report_history(11, 101, self.st.now, period_key=month.key)
        page = self.st.report_history(11, 100, self.st.now, period_key=month.key, limit=2)
        self.assertEqual([r["revision_no"] for r in page["items"]], [3, 2])
        tail = self.st.report_history(11, 100, self.st.now, period_key=month.key,
                                      before_report_id=page["next_before_report_id"], limit=2)
        self.assertEqual(tail["items"][0]["review_status"], "approved")
        self.assertIsNone(tail["next_before_report_id"])
        self.assertNotIn("_day_fingerprints", tail["items"][0]["payload"])

    def test_pending_and_failed_recheck_block_approval_and_keep_last_success(self):
        month = R.period("monthly", date(2026, 9, 3))
        self.st.seed(month.start, month.end)
        self.st.generate_reports(self.st.now)
        first = self.report(month.key)
        checked = first["validation"]["last_checked_at"]
        self.st.now += timedelta(hours=1)
        for status in ("reading", "retry"):
            self.st.recheck(month.start, month.end, status)
            current = self.report(month.key)
            self.assertIn(current["validation"]["status"], ("pending", "failed"))
            self.assertEqual(current["validation"]["last_checked_at"], checked)
            with self.assertRaises(S.StoreRefused):
                self.st.record_report_review(first["report_id"], 100, self.st.now, "approved", "대조 중")
            self.st.generate_reports(self.st.now)
            self.assertEqual(self.report(month.key)["report_id"], first["report_id"])
            self.assertEqual(self.report(month.key)["validation"]["last_checked_at"], checked)

    def test_current_rematch_does_not_move_old_daily_values_or_expected_accounts(self):
        month = R.period("monthly", date(2026, 9, 3))
        self.st.seed(month.start, month.end)
        self.st.generate_reports(self.st.now)
        first = self.report(month.key)
        self.st.groups = {101: 12}
        self.st.now += timedelta(hours=1)
        self.st.seed(month.start, month.start, spend=500)
        self.st.generate_reports(self.st.now)
        old = self.report(month.key)
        new = self.report(month.key, pid=12)
        self.assertEqual(old["payload"]["totals"]["spend"], 29500)
        self.assertGreater(old["report_id"], first["report_id"])
        self.assertIsNone(new["payload"]["totals"]["spend"])

    def test_bounded_advertiser_batch_preserves_unprocessed_dirty_for_next_run(self):
        day = date(2025, 8, 6)
        self.st.groups = {}
        for index in range(21):
            self.st.seed(day, day, cid=101+index, pid=11+index)
        first = self.st.generate_reports(self.st.now)
        self.assertEqual(first["advertisers"], 20)
        self.assertEqual(len({row["possibility_id"] for row in self.st.report_snapshots()}), 20)
        self.assertEqual(self.st.generate_reports(self.st.now)["advertisers"], 1)
        self.assertEqual(len({row["possibility_id"] for row in self.st.report_snapshots()}), 21)

    def test_unmanaged_monthly_report_reuses_last_sunday_without_weekday_recheck(self):
        month = R.period("monthly", date(2026, 1, 3))
        self.st.cadence = "weekly"
        self.st.now = datetime(2026, 2, 1, 10, tzinfo=S.KST)
        self.st.seed(month.start, month.end)
        self.st.now = datetime(2026, 2, 3, 10, tzinfo=S.KST)
        self.st.generate_reports(self.st.now)
        report = self.report(month.key)
        self.assertEqual(report["validation"]["status"], "complete")
        self.assertEqual(report["validation"]["last_checked_at"], "2026-02-01T10:00:00+09:00")
        self.assertNotIn("_required_after", report["validation"])
        self.st.record_report_review(report["report_id"], 100, self.st.now, "approved", "일요일 대조 확인")


if __name__ == "__main__":
    unittest.main()
