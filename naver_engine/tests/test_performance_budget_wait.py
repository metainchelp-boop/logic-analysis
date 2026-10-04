"""실제 Store/메모리 SQL에서 내부 한도 대기와 실제 실패 예산을 구분한다."""
from pathlib import Path
from datetime import timedelta
import runpy
import socket
import unittest
from unittest.mock import patch

from naver_engine import naver_read as N, store as S
from naver_engine.tests.test_morning import creds


make_fixture = runpy.run_path(str(Path(__file__).resolve().parents[2] /
    "tools/naver-store-selection-benchmark.py"))["make_fixture"]


class PerformanceBudgetWaitTest(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        self.fixture = make_fixture(1, 1)
        self.store, self.clock = self.fixture.store, self.fixture.clock
        self.addCleanup(self.store.close)
        self.job = self.store.performance_work(self.clock.now(), 1)[0]

    def record(self, code, *, status="retry"):
        self.store.begin_performance_check(self.job, self.clock.now())
        result = self.store.record_performance_check(self.job, self.clock.now(),
            {"status": status, "error_code": code})
        current = self.store.performance_checks(self.clock.now())[self.job["customer_id"]]
        self.assertEqual((current["status"], current["error_code"]), (result, code))
        return result

    def test_pure_internal_limits_resume_immediately_without_spending_failure_attempts(self):
        for code in ("REQUEST_DEADLINE", "REQUEST_CALL_CAP") * 3:
            self.assertEqual(self.record(code), "retry")
            self.assertIn(self.job["job_key"],
                [row["job_key"] for row in self.store.performance_work(self.clock.now())])

    def test_transient_limited_probes_hourly_without_erasing_attempts(self):
        for delay in (2, 5, 15):
            self.assertEqual(self.record("NETWORK"), "retry")
            self.clock.advance(delay*60)
        self.assertEqual(self.record("NETWORK"), "limited")
        self.clock.advance(3599)
        self.assertNotIn(self.job["job_key"], [r["job_key"] for r in self.store.performance_work(self.clock.now())])
        self.clock.advance(1)
        self.assertIn(self.job["job_key"], [r["job_key"] for r in self.store.performance_work(self.clock.now())])
        self.assertEqual(self.record("SERVER"), "limited")
        row = self.store._conn.execute("SELECT attempts FROM naver_auto_performance_job WHERE job_key=?", (self.job["job_key"],)).fetchone()
        self.assertEqual(row[0], 5)

    def test_internal_yield_does_not_clear_three_real_failures_or_renew_elapsed_backoff(self):
        for code, delay in (("SERVER", 2), ("NETWORK", 5), ("RATE", 15)):
            self.assertEqual(self.record(code), "retry")
            self.clock.advance(delay * 60)
            self.assertEqual(self.record("REQUEST_DEADLINE"), "retry")
            self.assertIn(self.job["job_key"], [r["job_key"] for r in self.store.performance_work(self.clock.now())])
        self.assertEqual(self.record("SERVER"), "limited")
        self.clock.advance(1800)
        with self.assertRaises(S.StoreRefused):
            self.store.begin_performance_check(self.job, self.clock.now())
        self.assertNotIn(self.job["job_key"],
            [row["job_key"] for row in self.store.performance_work(self.clock.now())])

    def test_legacy_ambiguous_budget_is_not_exempted(self):
        for index, delay in enumerate((2, 5, 15, 30)):
            self.assertEqual(self.record("REQUEST_BUDGET"), "limited" if index == 3 else "retry")
            self.clock.advance(delay * 60)
        self.assertNotIn(self.job["job_key"], [r["job_key"] for r in self.store.performance_work(self.clock.now())])
        self.clock.advance(1800)
        self.assertIn(self.job["job_key"], [r["job_key"] for r in self.store.performance_work(self.clock.now())])
        self.assertEqual(self.record("REQUEST_DEADLINE"), "limited")
        row = self.store._conn.execute("SELECT attempts,next_try_at FROM naver_auto_performance_job WHERE job_key=?", (self.job["job_key"],)).fetchone()
        self.assertEqual(row[0], 4)
        self.assertEqual(row[1], S._kst_text(self.clock.now()+timedelta(hours=1), "대기"))

    def test_auth_and_invalid_checkpoints_are_not_automatically_reopened(self):
        for code,status in (("KEY_REJECTED","reauth_required"),("UNEXPECTED","limited")):
            with self.subTest(code=code):
                fixture = make_fixture(1,1)
                self.addCleanup(fixture.store.close)
                job = fixture.store.performance_work(fixture.clock.now(),1)[0]
                fixture.store.begin_performance_check(job, fixture.clock.now())
                fixture.store.record_performance_check(job, fixture.clock.now(), {"status":status,"error_code":code})
                fixture.clock.advance(3600)
                self.assertNotIn(job["job_key"], [r["job_key"] for r in fixture.store.performance_work(fixture.clock.now())])

    def test_account_guard_selection_only_checks_bounded_lane_candidates(self):
        fixture = make_fixture(100,100)
        self.addCleanup(fixture.store.close)
        with patch.object(fixture.store,"_collection_account_ready",wraps=fixture.store._collection_account_ready) as guard:
            jobs = fixture.store.performance_work(fixture.clock.now(),24)
        self.assertEqual(len(jobs),24)
        self.assertLessEqual(guard.call_count,48)

    def test_already_limited_internal_deadline_probes_only_after_one_hour(self):
        self.assertEqual(self.record("REQUEST_DEADLINE", status="limited"), "limited")
        self.clock.advance(1800)
        with self.assertRaises(S.StoreRefused):
            self.store.begin_performance_check(self.job, self.clock.now())
        self.assertNotIn(self.job["job_key"],
            [row["job_key"] for row in self.store.performance_work(self.clock.now())])
        self.clock.advance(1800)
        self.assertIn(self.job["job_key"], [r["job_key"] for r in self.store.performance_work(self.clock.now())])

    def test_reader_call_cap_waits_then_real_server_failure_still_stops_on_fourth(self):
        fixture = self.fixture
        for _ in range(5):
            self.assertEqual(fixture.run(limit=1, per_account_calls=1).counts, {"retry": 1})
            state = self.store.performance_checks(self.clock.now())[self.job["customer_id"]]
            self.assertEqual(state["error_code"], "REQUEST_CALL_CAP")
            self.clock.advance(120)
        for index, delay in enumerate((2, 5, 15, 30)):
            fixture.http.script("/ncc/campaigns", (503, {}))
            expected = "limited" if index == 3 else "retry"
            self.assertEqual(fixture.run(limit=1, per_account_calls=1).counts, {expected: 1})
            state = self.store.performance_checks(self.clock.now())[self.job["customer_id"]]
            self.assertEqual((state["status"], state["error_code"]), (expected, "SERVER"))
            self.clock.advance(delay * 60)
        self.assertTrue(all(call.method == "GET" for call in fixture.http.calls))

    def test_reader_pure_deadline_can_resume_after_five_waits(self):
        fixture = self.fixture
        fixture.http.tick = lambda call: self.clock.advance(10)
        for _ in range(5):
            self.assertEqual(fixture.run(limit=1).counts, {"retry": 1})
            state = self.store.performance_checks(self.clock.now())[self.job["customer_id"]]
            self.assertEqual(state["error_code"], "REQUEST_DEADLINE")
            self.assertIsNone(state["spend"])
            self.clock.advance(120)
        self.assertEqual(len(fixture.http.calls), 10)
        fixture.http.tick = None
        self.assertEqual(fixture.run(limit=1).counts, {"ok": 1})
        state = self.store.performance_checks(self.clock.now())[self.job["customer_id"]]
        self.assertEqual((state["status"], state["spend"]), ("ok", 25000))

    def test_checkpoint_waits_keep_verified_campaigns_and_resume_to_exact_totals(self):
        fixture = make_fixture(1, 1, campaigns=601)
        self.addCleanup(fixture.store.close)
        store, clock = fixture.store, fixture.clock
        job = store.performance_work(clock.now(), 1)[0]
        self.assertEqual(fixture.run(limit=1).counts, {"partial": 1})
        progress = store.performance_progress(job)
        self.assertEqual(progress["next_index"], 600)
        for _ in range(5):
            fixture.reader = N.NaverReader(creds(), transport=fixture.http, clock=clock)
            self.assertEqual(fixture.run(limit=1, per_account_calls=1).counts, {"retry": 1})
            self.assertEqual(store.performance_progress(job), progress)
            clock.advance(120)
        fixture.reader = N.NaverReader(creds(), transport=fixture.http, clock=clock)
        self.assertEqual(fixture.run(limit=1).counts, {"ok": 1})
        current = store.performance_checks(clock.now())[job["customer_id"]]
        self.assertEqual((current["status"], current["error_code"], current["spend"]), ("ok", None, 601000))
        ids = [cid for call in fixture.stats_calls for cid in call.query.get("ids", call.query.get("id", []))]
        self.assertEqual(len(ids), 601)
        self.assertEqual(len(set(ids)), 601)


if __name__ == "__main__":
    unittest.main()
