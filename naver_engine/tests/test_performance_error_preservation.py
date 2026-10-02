"""성과 수집 실패 사유의 저장/조회 계약. 메모리 SQL만 사용한다."""
from datetime import datetime, timedelta
import unittest

from naver_engine import store as S
from naver_engine.tests.test_morning import A
from naver_engine.tests.test_revalidation_collection import CollectionSQLBoundary


class PerformanceErrorPreservationTest(unittest.TestCase):
    def setUp(self):
        self.st = CollectionSQLBoundary(datetime(2026, 10, 5, 10, tzinfo=S.KST))
        self.addCleanup(self.st._conn.close)

    def retry(self, job, code):
        job.update(snapshot_at=self.st.now, catalog_at=self.st.catalog["generated_at"])
        self.st.begin_performance_check(job, self.st.now)
        return self.st.record_performance_check(job, self.st.now,
            {"status": "retry", "error_code": code})

    def test_four_retries_keep_last_actual_cause_and_stop_automatic_work(self):
        job = self.st.job()
        for index, code in enumerate(("NETWORK", "STATS_METRIC_MISSING", "STATS_DATE_INCOMPLETE", "STATS_CYCLE_INVALID")):
            expected_status = "limited" if index == 3 else "retry"
            self.assertEqual(self.retry(job, code), expected_status)
            current = self.st.performance_checks(self.st.now)[A]
            self.assertEqual((current["status"], current["error_code"]), (expected_status, code))
            self.st.advance(timedelta(minutes=(2, 5, 15, 30)[index]))
        self.assertNotIn(job["job_key"], [row["job_key"] for row in self.st.performance_work(self.st.now)])
        self.assertEqual(S.SCHEMA_VERSION, 11)

    def test_only_fixed_safe_failure_codes_can_be_persisted(self):
        job = self.st.job()
        self.st.begin_performance_check(job, self.st.now)
        for code in ("ACCOUNT_PRIVATE_123", "server said secret", "https://private.invalid", "", 123, {}, []):
            with self.subTest(code=code), self.assertRaises(S.StoreRefused):
                self.st.record_performance_check(job, self.st.now,
                    {"status": "retry", "error_code": code})
        self.assertIsNone(self.st.performance_checks(self.st.now)[A]["error_code"])

    def test_reader_and_collector_diagnostic_codes_survive_storage(self):
        codes = ("STATS_SHAPE_UNKNOWN", "STATS_NUMERIC_INVALID", "STATS_ROW_ID_INVALID", "STATS_DATE_INVALID",
            "STATS_PERIOD_OPEN", "STATS_METRIC_MISSING", "STATS_METRIC_INVALID", "STATS_DATE_INCOMPLETE",
            "STATS_CYCLE_INVALID", "STATS_CYCLE_FUTURE", "STATS_CAMPAIGNS_INVALID", "REQUEST_DEADLINE",
            "REQUEST_CALL_CAP", "RATE", "SERVER", "BAD_REQUEST", "NOT_FOUND", "NETWORK", "BAD_RESPONSE",
            "MISMATCH", "OTHER", "KEY_REJECTED", "STATS_INCOMPLETE", "STATS_SHAPE", "RETRY_EXHAUSTED")
        for code in codes:
            with self.subTest(code=code):
                store = CollectionSQLBoundary(self.st.now)
                try:
                    job = store.job()
                    store.begin_performance_check(job, store.now)
                    store.record_performance_check(job, store.now, {"status": "retry", "error_code": code})
                    self.assertEqual(store.performance_checks(store.now)[A]["error_code"], code)
                finally:
                    store._conn.close()

    def test_failure_after_success_keeps_verified_values_and_recovery_clears_current_error(self):
        job = self.st.job()
        self.st.success(job, spend=700, conversion=None)
        before = self.st.performance_checks(self.st.now)[A]
        self.st.advance(timedelta(hours=2))
        for index in range(4):
            self.retry(job, "STATS_NUMERIC_INVALID")
            self.st.advance(timedelta(minutes=(2, 5, 15, 30)[index]))
        failed = self.st.performance_checks(self.st.now)[A]
        self.assertEqual((failed["status"], failed["error_code"]), ("limited", "STATS_NUMERIC_INVALID"))
        self.assertEqual((failed["spend"], failed["last_success_at"]), (700, before["last_success_at"]))

        self.st.performance_manual_request(A, 100, self.st.now)
        manual = next(row for row in self.st.performance_work(self.st.now) if row["kind"] == "manual")
        self.st.success(manual, spend=800)
        recovered = self.st.performance_checks(self.st.now)[A]
        self.assertEqual((recovered["status"], recovered["error_code"], recovered["spend"]), ("ok", None, 800))
        self.st.advance(timedelta(hours=1))
        self.st.performance_manual_request(A, 100, self.st.now)
        next_manual = next(row for row in self.st.performance_work(self.st.now) if row["kind"] == "manual")
        self.retry(next_manual, "STATS_DATE_INVALID")
        later = self.st.performance_checks(self.st.now)[A]
        self.assertEqual((later["status"], later["error_code"], later["spend"]), ("retry", "STATS_DATE_INVALID", 800))
        self.assertEqual(later["last_success_at"], recovered["last_success_at"])


if __name__ == "__main__":
    unittest.main()
