"""보고서 SQL 어댑터 시험. 실제 Store WAL/파일 잠금 통합 검증과 구분한다."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from naver_engine import reporting as R, store as S
from naver_engine.tests import test_alerts as TA, test_account_catalog as TC
from app.naver_auto import scope as SC


class ReportAdapter(S.ManagedStorage):
    def __init__(self):
        self.now = datetime(2026, 10, 5, 10, tzinfo=S.KST)
        self._conn = sqlite3.connect(":memory:", isolation_level=None)
        for sql in S._SCHEMA:
            self._conn.execute(sql)
        for table, columns in S._REVISION_COLUMNS.items():
            for name, definition in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        self.groups = {101: 11}
        self.cadence = "daily"
        self.stage = "진행중"
        self.attributable = True
        self.human_confirmed = True
        self.open_issue_pids = set()
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
        return {cid: {"possibility_id": pid, "stage": self.stage,
                      "decision": SimpleNamespace(cadence=self.cadence, attributable=self.attributable)}
                for cid, pid in self.groups.items()}

    def current_decisions(self):
        if not self.human_confirmed:
            return []
        return [SimpleNamespace(customer_id=cid, possibility_id=pid, decision="confirmed")
                for cid, pid in self.groups.items()]

    def issues(self, open_only=False):
        return [{"possibility_id": pid} for pid in self.open_issue_pids]

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
                 conversion_attempts,imp,clk,spend,conversions,conversion_value,checked_at,campaign_fingerprint,
                 source_at,source_generation)
                VALUES(?,?,?,'matching',1,1,0,100,10,?,1,2000,?,'campaign',?,?)
                ON CONFLICT(customer_id,day) DO UPDATE SET spend=excluded.spend,checked_at=excluded.checked_at,
                source_at=excluded.source_at,source_generation=excluded.source_generation""",
                (cid, day.isoformat(), pid, spend, self.now.isoformat(), self.now.isoformat(),
                 self.now.replace(hour=0, minute=1, second=0, microsecond=0).isoformat()))
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

    def test_nonmanaged_accounts_keep_daily_records_without_creating_reports(self):
        week = R.period("weekly", date(2026, 9, 28))
        self.st.cadence, self.st.stage = "weekly", "계약 만료"
        self.st.seed(week.start, week.end)
        records = self.st.daily_performance([101], week.start, week.end)
        self.assertEqual(self.st.generate_reports(self.st.now)["generated"], 0)
        self.assertEqual(self.st.report_snapshots(), [])
        self.assertEqual(self.st.daily_performance([101], week.start, week.end), records)

    def test_unique_id_automatic_link_gets_report_without_inventing_human_confirmation(self):
        week = R.period("weekly", date(2026, 9, 28))
        self.st.human_confirmed = False
        self.st.seed(week.start, week.end)
        self.st.generate_reports(self.st.now)
        self.assertEqual(self.report(week.key)["payload"]["totals"]["spend"], 7000)
        self.assertEqual(self.st.current_decisions(), [])

    def test_unattributable_source_does_not_create_company_report(self):
        week = R.period("weekly", date(2026, 9, 28))
        self.st.attributable = False
        self.st.seed(week.start, week.end)
        self.assertEqual(self.st.generate_reports(self.st.now)["generated"], 0)
        self.assertEqual(self.st.report_snapshots(), [])

    def test_new_current_account_cannot_leave_existing_report_falsely_complete(self):
        week = R.period("weekly", date(2026, 9, 28))
        self.st.seed(week.start, week.end)
        self.st.generate_reports(self.st.now)
        self.assertEqual(self.report(week.key)["validation"]["status"], "complete")
        self.st.groups[102] = 11
        self.st.generate_reports(self.st.now)
        current = self.report(week.key)
        self.assertNotEqual(current["validation"]["status"], "complete")
        self.assertEqual(current["validation"]["pending_account_days"], 7)
        expected = self.st._conn.execute("""SELECT expected_customers_json FROM naver_auto_report_validation
            WHERE possibility_id=11 AND period_key=?""", (week.key,)).fetchone()[0]
        self.assertEqual(json.loads(expected), [101, 102])

    def test_account_moved_to_company_after_period_does_not_rewrite_prior_report_scope(self):
        week = R.period("weekly", date(2026, 9, 28))
        self.st.seed(week.start, week.end)
        self.st.generate_reports(self.st.now)
        first = self.report(week.key)
        self.st.groups[102] = 11
        self.st._conn.execute("UPDATE naver_auto_report_dirty SET pending=1")
        with patch.object(self.st, "_performance_attribution_start", side_effect=lambda cid, pid:
                          "2026-10-05" if cid == 102 else None):
            self.st.generate_reports(self.st.now)
        self.assertEqual(self.report(week.key)["report_id"], first["report_id"])
        self.assertEqual(self.report(week.key)["validation"]["status"], "complete")

    def test_leaving_managed_stage_preserves_prior_report_and_resumes_after_return(self):
        week = R.period("weekly", date(2026, 9, 28))
        self.st.seed(week.start, week.end)
        self.st.generate_reports(self.st.now)
        first = self.report(week.key)
        self.st.cadence, self.st.stage = "weekly", "환불 완료"
        self.st.now += timedelta(hours=1)
        self.st.seed(week.start, week.start, spend=500)
        self.assertEqual(self.st.generate_reports(self.st.now)["generated"], 0)
        self.assertEqual(self.report(week.key)["report_id"], first["report_id"])
        self.assertEqual(self.st.daily_performance([101], week.start, week.start)[0]["spend"], 500)
        self.st.cadence, self.st.stage = "daily", "재계약 진행중"
        self.st.generate_reports(self.st.now)
        self.assertGreater(self.report(week.key)["report_id"], first["report_id"])

    def test_manual_daily_inclusion_does_not_make_nonmanaged_company_a_report_target(self):
        self.st.cadence, self.st.stage = "daily", "홀딩중"
        self.st.seed(date(2026, 9, 28), date(2026, 10, 4))
        self.assertEqual(self.st.generate_reports(self.st.now)["generated"], 0)
        self.assertEqual(self.st.report_snapshots(), [])

    def test_issue_only_changes_requeue_weekly_review_policy_without_new_source(self):
        week = R.period("weekly", date(2026, 9, 28))
        self.st.seed(week.start, week.end)
        self.st.generate_reports(self.st.now)
        first = self.report(week.key)
        self.st.record_report_review(first["report_id"], 100, self.st.now, "approved", "초판 확인")
        self.st.open_issue_pids.add(11)
        self.st.now += timedelta(minutes=1)
        self.st.generate_reports(self.st.now)
        changed = self.report(week.key)
        self.assertGreater(changed["report_id"], first["report_id"])
        self.assertEqual(changed["review_status"], "needs_staff_review")
        self.assertIsNone(changed["review"])
        self.assertEqual(changed["payload"]["totals"], first["payload"]["totals"])
        self.assertEqual(self.st.generate_reports(self.st.now)["generated"], 0)
        self.st.open_issue_pids.clear()
        self.st.now += timedelta(minutes=1)
        self.st.generate_reports(self.st.now)
        cleared = self.report(week.key)
        self.assertGreater(cleared["report_id"], changed["report_id"])
        self.assertEqual(cleared["review_status"], "not_required")
        self.assertIsNone(cleared["review"])

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

    def test_accepted_manual_recheck_blocks_approval_before_worker_starts(self):
        month = R.period("monthly", date(2026, 9, 3))
        self.st.seed(month.start, month.end)
        self.st.generate_reports(self.st.now)
        first = self.report(month.key)
        self.st.now += timedelta(hours=1)
        with patch("naver_engine.management_store.require_action", return_value={"possibility_id": 11}), \
                patch.object(self.st, "_performance_history_valid", return_value=True):
            self.st.performance_manual_request(101, 100, self.st.now, start=month.start, end=month.end, possibility_id=11)
        for generate in (False, True):
            if generate:
                self.st.generate_reports(self.st.now)
            current = self.report(month.key)
            self.assertEqual(current["report_id"], first["report_id"])
            self.assertEqual(current["validation"]["status"], "pending")
            self.assertEqual(current["validation"]["pending_account_days"], 30)
            self.assertEqual(current["validation"]["last_checked_at"], first["validation"]["last_checked_at"])
            # 아직 시도하지 않은 요청을 성공/실패 시도 시각으로 꾸미지 않는다.
            self.assertEqual(current["validation"]["last_attempt_at"], first["validation"]["last_attempt_at"])
            with self.assertRaises(S.StoreRefused):
                self.st.record_report_review(first["report_id"], 100, self.st.now, "approved", "재확인 접수 대기")

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
        # 더는 실관리 연결이 없는 이전 업체의 보고서는 보존만 한다. 원천 정정도 새 업체로 옮기지 않는다.
        self.assertEqual(old["payload"]["totals"]["spend"], 30000)
        self.assertEqual(old["report_id"], first["report_id"])
        self.assertEqual(self.st.daily_performance([101], month.start, month.start, possibility_id=11)[0]["spend"], 500)
        self.assertIsNone(new["payload"]["totals"]["spend"])

    def test_bounded_advertiser_batch_preserves_unprocessed_dirty_for_next_run(self):
        day = date(2025, 8, 6)
        self.st.groups = {101+index: 11+index for index in range(21)}
        for index in range(21):
            self.st.seed(day, day, cid=101+index, pid=11+index)
        first = self.st.generate_reports(self.st.now)
        self.assertEqual(first["advertisers"], 20)
        self.assertEqual(len({row["possibility_id"] for row in self.st.report_snapshots()}), 20)
        self.assertEqual(self.st.generate_reports(self.st.now)["advertisers"], 1)
        self.assertEqual(len({row["possibility_id"] for row in self.st.report_snapshots()}), 21)

    def test_late_old_generation_cannot_complete_new_report_validation(self):
        month = R.period("monthly", date(2026, 9, 3))
        self.st.now = datetime(2026, 10, 3, 10, tzinfo=S.KST)
        self.st.seed(month.start, month.end)
        self.st._conn.execute("UPDATE naver_auto_daily_performance SET source_generation=?,source_at=?",
                              ("2026-10-02T00:01:00+09:00", "2026-10-03T09:00:00+09:00"))
        self.st.generate_reports(self.st.now)
        first = self.report(month.key)
        self.assertEqual(first["validation"]["status"], "pending")
        self.assertEqual(first["validation"]["pending_account_days"], 30)
        self.assertIsNone(first["validation"]["last_checked_at"])
        with self.assertRaises(S.StoreRefused):
            self.st.record_report_review(first["report_id"], 100, self.st.now, "approved", "옛 세대 늦은 완료")
        # 같은 날 네이버 cycleBaseTm은 세대 시작 시각보다 이를 수 있다. 날짜 하한만 적용한다.
        self.st._conn.execute("UPDATE naver_auto_daily_performance SET source_generation=?,source_at=?",
                              ("2026-10-03T00:01:00+09:00", "2026-10-03T00:00:00+09:00"))
        self.st._conn.execute("UPDATE naver_auto_report_dirty SET pending=1")
        self.st.generate_reports(self.st.now)
        current = self.report(month.key)
        self.assertEqual(current["report_id"], first["report_id"])
        self.assertEqual(current["validation"]["status"], "complete")

    def test_legacy_or_older_cycle_proof_is_not_assumed_revalidated(self):
        month = R.period("monthly", date(2026, 9, 3))
        self.st.now = datetime(2026, 10, 3, 10, tzinfo=S.KST)
        self.st.seed(month.start, month.end)
        for generation, source in (("", "2026-10-03T09:00:00+09:00"),
                                   ("2026-10-03T00:01:00+09:00", None),
                                   ("2026-10-03T00:01:00+09:00", "2026-10-02T23:00:00+09:00"),
                                   ("2026-10-03T00:01:00", "2026-10-03T09:00:00+09:00")):
            with self.subTest(generation=generation, source=source):
                self.st._conn.execute("UPDATE naver_auto_daily_performance SET source_generation=?,source_at=?",
                                      (generation, source))
                self.st._conn.execute("UPDATE naver_auto_report_dirty SET pending=1")
                self.st.generate_reports(self.st.now)
                report = self.report(month.key)
                self.assertEqual(report["validation"]["status"], "pending")
                self.assertIsNone(report["validation"]["last_checked_at"])

    def test_unmanaged_monthly_source_stays_available_without_report(self):
        month = R.period("monthly", date(2026, 1, 3))
        self.st.cadence = "weekly"
        self.st.stage = "계약 만료"
        self.st.now = datetime(2026, 2, 1, 10, tzinfo=S.KST)
        self.st.seed(month.start, month.end)
        self.st.now = datetime(2026, 2, 3, 10, tzinfo=S.KST)
        self.assertEqual(self.st.generate_reports(self.st.now)["generated"], 0)
        self.assertEqual(self.st.report_snapshots(), [])
        rows = self.st.daily_performance([101], month.start, month.end)
        self.assertEqual(len(rows), 31)
        self.assertTrue(all(row["checked_at"] == "2026-02-01T10:00:00+09:00" for row in rows))


if __name__ == "__main__":
    unittest.main()
