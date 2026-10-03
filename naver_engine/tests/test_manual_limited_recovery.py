"""기존 '지금 조회'의 중단 작업 재조회 경계. 운영 재개 승인이나 자동 복구 정책은 아니다.

원래 작업을 다시 여는 것이 아니라 별도 수동 작업을 만들며, 새 작업 안의 실제 오류
예산만 시험한다. 과거 작업의 실제 실패 횟수가 새 작업으로 승계된다는 보장은 아니다.
"""
from pathlib import Path
import runpy
import socket
import unittest
from unittest.mock import patch

from naver_engine import naver_read as N, store as S
from naver_engine.tests.test_morning import creds


make_fixture = runpy.run_path(str(Path(__file__).resolve().parents[2] /
    "tools/naver-store-selection-benchmark.py"))["make_fixture"]


class ManualLimitedRecoveryTest(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        self.fixture = make_fixture(1, 1)
        self.store, self.clock = self.fixture.store, self.fixture.clock
        self.addCleanup(self.store.close)
        self.original = self.store.performance_work(self.clock.now(), 1)[0]
        self.customer_id = self.original["customer_id"]

    def request_after_internal_stop(self):
        self.store.begin_performance_check(self.original, self.clock.now())
        self.assertEqual(self.store.record_performance_check(self.original, self.clock.now(),
            {"status": "limited", "error_code": "REQUEST_DEADLINE"}), "limited")
        self.clock.advance(30 * 60)
        self.assertEqual(self.store.performance_work(self.clock.now()), [])
        with self.assertRaises(S.StoreRefused):
            self.store.begin_performance_check(self.original, self.clock.now())
        request = self.store.performance_manual_request(self.customer_id, 100, self.clock.now())
        self.assertEqual(request["status"], "accepted")
        jobs = self.store.performance_work(self.clock.now())
        self.assertEqual([job["kind"] for job in jobs], ["manual"])
        self.assertNotEqual(jobs[0]["job_key"], self.original["job_key"])
        return jobs[0]

    def run_manual(self, **kwargs):
        self.fixture.reader = N.NaverReader(creds(), transport=self.fixture.http, clock=self.clock)
        result = self.fixture.run(limit=1, **kwargs)
        return result, self.store.performance_checks(self.clock.now())[self.customer_id]

    def test_manual_success_restores_current_view_without_reopening_original_daily_job(self):
        manual = self.request_after_internal_stop()
        self.assertEqual((manual["period_start"], manual["period_end"]),
                         (self.original["period_start"], self.original["period_end"]))

        result, current = self.run_manual()

        self.assertEqual(result.counts, {"ok": 1})
        self.assertEqual((current["status"], current["error_code"], current["stale"], current["spend"]),
                         ("ok", None, False, 25000))
        with self.assertRaises(S.StoreRefused):
            self.store.begin_performance_check(self.original, self.clock.now())
        self.assertNotIn(self.original["job_key"],
                         [job["job_key"] for job in self.store.performance_work(self.clock.now())])
        self.assertTrue(all(call.method == "GET" for call in self.fixture.http.calls))

    def test_new_manual_job_stops_after_four_actual_rate_failures(self):
        manual = self.request_after_internal_stop()
        for attempt, delay in enumerate((2, 5, 15, 30)):
            self.fixture.http.script("/ncc/campaigns", (429, {"code": 1016}))

            result, current = self.run_manual(per_account_calls=1)

            expected = "limited" if attempt == 3 else "retry"
            self.assertEqual(result.counts, {expected: 1})
            self.assertEqual((current["status"], current["error_code"]), (expected, "RATE"))
            self.assertTrue(self.fixture.reader.rate_limited)
            self.clock.advance(delay * 60)
        self.assertEqual(len(self.fixture.http.calls), 4)
        self.assertEqual(self.store.performance_work(self.clock.now()), [])
        for job in (manual, self.original):
            with self.assertRaises(S.StoreRefused):
                self.store.begin_performance_check(job, self.clock.now())

    def test_new_manual_job_does_not_automatically_retry_rejected_credentials(self):
        manual = self.request_after_internal_stop()
        self.fixture.http.script("/ncc/campaigns", (403, {"code": 403}))

        result, current = self.run_manual()

        self.assertEqual(result.counts, {"reauth_required": 1})
        self.assertEqual((current["status"], current["error_code"]), ("reauth_required", "KEY_REJECTED"))
        calls = len(self.fixture.http.calls)
        self.clock.advance(30 * 60)
        self.assertEqual(self.store.performance_work(self.clock.now()), [])
        self.assertEqual(self.run_manual()[0].counts, {})
        self.assertEqual(len(self.fixture.http.calls), calls)
        with self.assertRaises(S.StoreRefused):
            self.store.begin_performance_check(manual, self.clock.now())


if __name__ == "__main__":
    unittest.main()
