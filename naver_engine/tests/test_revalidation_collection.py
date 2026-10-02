"""출근 수집/정정 대조의 합성 경계. 네트워크·운영 DB를 사용하지 않는다."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import sqlite3
import unittest

from naver_engine import management as M, performance_reads as P, store as S
from naver_engine.tests.test_managed_storage import _ManagedBoundary
from naver_engine.tests.test_morning import A


class CollectionSQLBoundary(_ManagedBoundary):
    """메모리 SQL 계약만 시험한다. 파일 Store/Writer 잠금 통합의 대체가 아니다."""
    def __init__(self, now):
        super().__init__(now)
        self._conn = sqlite3.connect(":memory:", isolation_level=None)
        for sql in S._SCHEMA:
            self._conn.execute(sql)
        for table, columns in S._REVISION_COLUMNS.items():
            for name, definition in columns:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @contextmanager
    def _tx(self):
        self._conn.execute("BEGIN")
        try:
            yield self._conn
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

    def daily_performance(self, *args, **kwargs):
        return S.ManagedStorage.daily_performance(self, *args, **kwargs)

    def performance_progress(self, job):
        return S.ManagedStorage.performance_progress(self, job)

    def advance(self, delta):
        self.now += delta
        self.catalog["generated_at"] = self.now.isoformat()

    def job(self, day=None):
        day = day or self.now.date()-timedelta(days=1)
        kind = "daily" if day == self.now.date()-timedelta(days=1) else "recent"
        start = day if kind == "daily" else self.now.date()-timedelta(days=3)
        return self._performance_job(A, kind, self.now.date(), start, day,
            self.states[A], self.now, self.catalog["generated_at"])

    def success(self, job, spend=100, *, source=None, conversion=1):
        self.begin_performance_check(job, self.now)
        source = source or self.now
        days = [str(date.fromisoformat(job["period_start"])+timedelta(days=n))
            for n in range((date.fromisoformat(job["period_end"])-date.fromisoformat(job["period_start"])).days+1)]
        progress = dict(customer_id=A, period_start=job["period_start"], period_end=job["period_end"],
            generation=job["generation"], campaign_ids=["cmp-1"], fingerprint=P.fingerprint(["cmp-1"]),
            next_index=1, cycles=[source.isoformat()], conversion_evidence=True,
            day_totals={day: dict(impCnt=10, clkCnt=1, salesAmt=spend, ccnt=conversion, convAmt=conversion)
                        for day in days})
        self.record_performance_progress(job, self.now, progress)
        return self.record_performance_check(job, self.now, dict(status="ok", campaign_fingerprint=progress["fingerprint"],
            daily_rows=[dict(customer_id=A,day=day,basic_complete=True,conversion_complete=conversion is not None,
                imp=10,clk=1,spend=spend,conversions=conversion,conversion_value=conversion,
                checked_at=self.now.isoformat(),source_at=source.isoformat()) for day in days]))


class RevalidationScheduleTest(unittest.TestCase):
    def test_midnight_waits_until_one_minute_and_ten_is_not_a_stop(self):
        day = date(2026, 10, 5)
        for hour, minute, expected in ((0, 0, False), (0, 1, True), (10, 0, True), (23, 59, True)):
            now = datetime.combine(day, datetime.min.time(), tzinfo=S.KST).replace(hour=hour, minute=minute)
            self.assertEqual(bool(_ManagedBoundary(now).performance_work(now)), expected)

    def test_daily_recent_weekly_and_monthly_ranges_cross_calendar_boundaries(self):
        monday = M.revalidation_periods(date(2026, 11, 2), managed=True)
        self.assertIn(("recent", date(2026, 11, 2), date(2026, 10, 30), date(2026, 11, 1)), monday)
        self.assertIn(("report_weekly", date(2026, 11, 2), date(2026, 10, 26), date(2026, 11, 1)), monday)
        leap = M.revalidation_periods(date(2024, 3, 3), managed=True)
        self.assertIn(("report_monthly", date(2024, 3, 3), date(2024, 2, 1), date(2024, 2, 29)), leap)
        self.assertIn(("reconcile", date(2024, 3, 3), date(2024, 2, 1), date(2024, 3, 2)), leap)
        self.assertFalse(M.revalidation_periods(date(2026, 10, 5), managed=False, prior_managed=True))


class RevalidationStorageBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.st = CollectionSQLBoundary(datetime(2026, 10, 5, 10, tzinfo=S.KST))
        self.addCleanup(self.st._conn.close)

    def test_source_wait_is_bounded_without_spending_four_error_attempts(self):
        job = self.st.job()
        for expected in (15, 30, 60, 60, 60, 60):
            job.update(snapshot_at=self.st.now, catalog_at=self.st.catalog["generated_at"])
            self.st.begin_performance_check(job, self.st.now)
            self.assertEqual(self.st.record_performance_check(job, self.st.now,
                {"status": "source_wait", "error_code": "SOURCE_AGGREGATING"}), "source_wait")
            saved = self.st._conn.execute("SELECT attempts,next_try_at FROM naver_auto_performance_job").fetchone()
            self.assertEqual(saved[0], 0)
            self.assertEqual(datetime.fromisoformat(saved[1])-self.st.now, timedelta(minutes=expected))
            self.st.advance(timedelta(minutes=expected))
        self.assertTrue(self.st.performance_work(self.st.now))

    def test_material_decrease_and_zero_make_revisions_but_same_success_does_not(self):
        job = self.st.job()
        self.st.success(job)
        day = date.fromisoformat(job["period_end"])
        for spend, revision in ((50, 2), (0, 3), (0, 3)):
            self.st.advance(timedelta(hours=1))
            self.st.performance_manual_request(A, 100, self.st.now)
            manual = next(j for j in self.st.performance_work(self.st.now) if j["kind"] == "manual")
            self.st.success(manual, spend)
            saved = self.st.daily_performance([A], day, day)[0]
            self.assertEqual((saved["spend"], saved["source_revision"]), (spend, revision))
            self.assertEqual(saved["checked_at"], S._kst_text(self.st.now, "시험"))
        self.assertEqual(self.st._conn.execute("SELECT COUNT(*) FROM naver_auto_daily_revision").fetchone()[0], 2)
        self.assertEqual(self.st._conn.execute("SELECT COUNT(*) FROM naver_auto_report_dirty WHERE pending=1").fetchone()[0], 2)

    def test_older_source_and_generation_cannot_overwrite_verified_success(self):
        job = self.st.job()
        self.st.success(job)
        day = date.fromisoformat(job["period_end"])
        old = self.st.daily_performance([A], day, day)[0]
        self.st.advance(timedelta(hours=1))
        self.st.performance_manual_request(A, 100, self.st.now)
        manual = next(j for j in self.st.performance_work(self.st.now) if j["kind"] == "manual")
        self.st.success(manual, 0, source=datetime.fromisoformat(old["source_at"])-timedelta(seconds=1))
        self.assertEqual(self.st.daily_performance([A], day, day)[0], old)

    def test_midnight_carry_keeps_fixed_days_and_new_generation_has_no_checkpoint(self):
        first = self.st.job()
        self.st.begin_performance_check(first, self.st.now)
        self.st.record_performance_check(first, self.st.now, {"status":"partial", "error_code":"REQUEST_BUDGET"})
        self.st.advance(timedelta(days=1))
        jobs = self.st.performance_work(self.st.now)
        carried = next(j for j in jobs if j["job_key"] == first["job_key"])
        self.assertEqual((carried["period_start"], carried["generation"]), (first["period_start"], first["generation"]))
        self.assertTrue(self.st.performance_account_valid(carried, self.st.now))
        fresh = next(j for j in jobs if j["cycle_day"] == str(self.st.now.date()))
        self.assertNotEqual(fresh["generation"], first["generation"])
        self.assertIsNone(self.st.performance_progress(fresh))

    def test_manual_period_requires_known_historical_owner_and_maximum_31_closed_days(self):
        job = self.st.job()
        self.st.success(job)
        day = date.fromisoformat(job["period_end"])
        for start, end, pid in ((day-timedelta(days=31),day,11), (day,self.st.now.date(),11),
                                (day-timedelta(days=1),day,11), (day,day,12)):
            with self.assertRaises(Exception):
                self.st.performance_manual_request(A,100,self.st.now,start=start,end=end,possibility_id=pid)
        self.assertEqual(self.st.performance_manual_request(A,100,self.st.now,
            start=day,end=day,possibility_id=11)["status"], "accepted")
        manual = next(j for j in self.st.performance_work(self.st.now) if j["kind"] == "manual_period")
        self.assertTrue(self.st.performance_account_valid(manual, self.st.now))

    def test_dated_revalidation_projects_its_own_period_without_relabeling_daily(self):
        daily = self.st.job()
        self.st.success(daily)
        day = date.fromisoformat(daily["period_end"])
        daily_at = self.st.performance_checks(self.st.now)[A]["checked_at"]
        self.st.advance(timedelta(hours=1))
        self.st._conn.execute("UPDATE naver_auto_report_dirty SET pending=0")
        self.st.performance_manual_request(A,100,self.st.now,start=day,end=day,possibility_id=11)
        self.assertEqual(self.st._conn.execute("SELECT COUNT(*) FROM naver_auto_report_dirty WHERE pending=1").fetchone()[0], 2)
        queued = self.st.performance_checks(self.st.now)[A]["revalidation"]
        self.assertEqual((queued["status"], queued["checked_at"], queued["kind"]), ("pending",None,"manual_period"))
        manual = next(j for j in self.st.performance_work(self.st.now) if j["kind"] == "manual_period")
        self.st.success(manual, 50)
        check = self.st.performance_checks(self.st.now)[A]
        self.assertEqual((check["period_start"], check["period_end"], check["checked_at"]),
                         (daily["period_start"], daily["period_end"], daily_at))
        self.assertEqual((check["revalidation"]["kind"],check["revalidation"]["status"]), ("manual_period","ok"))
        self.assertEqual(check["revalidation"]["period_start"], str(day))
        self.assertEqual(check["source_rechecked_at"], S._kst_text(self.st.now, "시험"))
        self.assertEqual(check["spend"], 50)

    def test_undated_manual_request_keeps_its_original_period_and_manual_kind(self):
        self.st.success(self.st.job())
        self.st.advance(timedelta(hours=1))
        self.st.performance_manual_request(A,100,self.st.now)
        saved = self.st._conn.execute("SELECT period_start,period_end,request_kind FROM naver_auto_manual_read").fetchone()
        self.assertEqual(saved, ("2026-10-04","2026-10-04","manual"))
        self.st.advance(timedelta(days=1))
        manual = next(job for job in self.st.performance_work(self.st.now) if job["kind"] == "manual")
        self.assertEqual((manual["period_start"], manual["period_end"]), saved[:2])

    def test_manual_structure_job_uses_request_generation_and_dated_stats_does_not_trigger_structure(self):
        self.st.success(self.st.job())
        self.st.advance(timedelta(hours=1))
        self.st.performance_manual_request(A,100,self.st.now)
        job = next(job for job in self.st.structure_work(self.st.now) if job["kind"] == "manual")
        self.assertEqual(job["generation"], job["requested_at"])
        self.assertTrue(self.st.structure_account_valid(job,self.st.now))
        self.st.begin_structure_check(job,self.st.now)
        self.st.record_structure_check(job,self.st.now,{"status":"retry","error_code":"READ_RETRY"})
        self.assertEqual(self.st.structure_checks([A],self.st.now)[A]["status"],"retry")
        manual = next(job for job in self.st.performance_work(self.st.now) if job["kind"] == "manual")
        self.st.success(manual)
        self.st.advance(timedelta(hours=1))
        day = date(2026,10,4)
        self.st.performance_manual_request(A,100,self.st.now,start=day,end=day,possibility_id=11)
        self.assertTrue(all(job["kind"] not in ("manual","manual_period") for job in self.st.structure_work(self.st.now)))


if __name__ == "__main__":
    unittest.main()
