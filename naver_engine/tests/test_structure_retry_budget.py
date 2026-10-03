"""구조 수집의 중단 사유와 재시도 정책. 실제 Store/메모리 SQL과 합성 HTTP만 쓴다."""
from pathlib import Path
import runpy
import socket
import unittest
from unittest.mock import patch

from naver_engine import naver_read as N, structure_reads as R
from naver_engine.tests.test_morning import A, creds


make_fixture = runpy.run_path(str(Path(__file__).resolve().parents[2] /
    "tools/naver-store-selection-benchmark.py"))["make_fixture"]


class StructureRetryBudgetTests(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)

    def fixture(self):
        fixture = make_fixture(accounts=1, managed=1, campaigns=0)
        self.addCleanup(fixture.store.close)
        fixture.http.route(r"/ncc/channels", lambda call: (200, []))
        return fixture

    def run_structure(self, fixture, **kwargs):
        fixture.reader = N.NaverReader(creds(), transport=fixture.http, clock=fixture.clock)
        outcome = R.run_structure(fixture.reader, fixture.store, fixture.clock.now, **kwargs)
        return outcome, fixture.store.structure_checks([A], fixture.clock.now())[A]

    def test_deadline_during_server_retry_preserves_actual_failure(self):
        fixture = self.fixture()
        fixture.http.tick = lambda call: fixture.clock.advance(1.5)
        fixture.http.script("/ncc/campaigns", *((503, {"message": "비공개응답"}),) * 4)

        outcome, row = self.run_structure(fixture)

        self.assertEqual(outcome.counts, {"retry": 1})
        self.assertEqual(row["error_code"], "SERVER")
        self.assertEqual(fixture.reader.calls, 3)
        self.assertEqual(fixture.clock.sleeps, [1.0, 2.0])
        self.assertNotIn("비공개응답", str(row))

    def test_pure_budget_stops_remain_retryable_after_more_than_four_rounds(self):
        for code, limits in (("REQUEST_DEADLINE", {"max_seconds": 1}),
                             ("REQUEST_CALL_CAP", {"per_account_calls": 1})):
            with self.subTest(code=code):
                fixture = self.fixture()
                if code == "REQUEST_DEADLINE":
                    fixture.http.tick = lambda call: fixture.clock.advance(2)
                for _ in range(6):
                    outcome, row = self.run_structure(fixture, **limits)
                    self.assertEqual(outcome.counts, {"retry": 1})
                    self.assertEqual((row["status"], row["error_code"]), ("retry", code))
                    self.assertEqual(fixture.reader.calls, 1)
                    fixture.clock.advance(120)
                    self.assertEqual(len(fixture.store.structure_work(fixture.clock.now())), 1)

    def test_real_failures_at_call_cap_still_stop_after_four_failures(self):
        for reply, code in (((503, {"message": "비공개응답"}), "SERVER"),
                            (TimeoutError("비공개응답"), "NETWORK"),
                            ((429, {"code": 1016}), "RATE")):
            with self.subTest(code=code):
                fixture = self.fixture()
                for attempt in range(4):
                    fixture.http.script("/ncc/campaigns", reply)
                    outcome, row = self.run_structure(fixture, per_account_calls=1)
                    expected = "limited" if attempt == 3 else "retry"
                    self.assertEqual(outcome.counts, {expected: 1})
                    self.assertEqual((row["status"], row["error_code"]), (expected, code))
                    self.assertEqual(fixture.reader.calls, 1)
                    self.assertNotIn("비공개응답", str(row))
                    if attempt < 3:
                        fixture.clock.advance((2, 5, 15)[attempt] * 60)
                self.assertEqual(fixture.store.structure_work(fixture.clock.now()), [])

    def test_budget_stop_keeps_prior_real_failures_without_spending_another(self):
        fixture = self.fixture()
        for delay in (2, 5):
            fixture.http.script("/ncc/campaigns", (503, {}))
            self.assertEqual(self.run_structure(fixture, per_account_calls=1)[0].counts, {"retry": 1})
            fixture.clock.advance(delay * 60)

        outcome, row = self.run_structure(fixture, per_account_calls=1)
        self.assertEqual((outcome.counts, row["error_code"]), ({"retry": 1}, "REQUEST_CALL_CAP"))
        fixture.clock.advance(5 * 60)
        fixture.http.script("/ncc/campaigns", (503, {}))
        self.assertEqual(self.run_structure(fixture, per_account_calls=1)[0].counts, {"retry": 1})
        fixture.clock.advance(15 * 60)
        fixture.http.script("/ncc/campaigns", (503, {}))
        outcome, row = self.run_structure(fixture, per_account_calls=1)
        self.assertEqual((outcome.counts, row["error_code"]), ({"limited": 1}, "SERVER"))

    def test_legacy_budget_code_remains_a_failure_and_does_not_reopen_limited_work(self):
        fixture = self.fixture()
        job = fixture.store.structure_work(fixture.clock.now())[0]
        for attempt in range(4):
            fixture.store.begin_structure_check(job, fixture.clock.now())
            expected = "limited" if attempt == 3 else "retry"
            self.assertEqual(fixture.store.record_structure_check(job, fixture.clock.now(),
                {"status": "retry", "error_code": "REQUEST_BUDGET"}), expected)
            if attempt < 3:
                fixture.clock.advance((2, 5, 15)[attempt] * 60)
        fixture.clock.advance(30 * 60)
        row = fixture.store.structure_checks([A], fixture.clock.now())[A]
        self.assertEqual((row["status"], row["error_code"]), ("limited", "REQUEST_BUDGET"))
        self.assertEqual(fixture.store.structure_work(fixture.clock.now()), [])

    def test_rate_keeps_precedence_over_later_server_abort(self):
        fixture = self.fixture()
        fixture.http.tick = lambda call: fixture.clock.advance(1)
        fixture.http.script("/ncc/campaigns", (429, {"code": 1016}), *((503, {}),) * 3)

        outcome, row = self.run_structure(fixture)

        self.assertEqual((outcome.code, outcome.counts, row["error_code"]), ("BUDGET", {"retry": 1}, "RATE"))
        self.assertTrue(fixture.reader.rate_limited)
        self.assertEqual(fixture.reader.calls, 4)


if __name__ == "__main__":
    unittest.main()
