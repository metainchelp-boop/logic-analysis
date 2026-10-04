"""재시도 중 예산 종료에도 같은 요청의 실제 실패 원인만 보존한다."""
import socket
import unittest
from unittest.mock import patch

from naver_engine import handles as H, naver_read as N
from naver_engine.tests.test_morning import creds
from naver_engine.tests.test_performance_batch_reads import BatchFixture


class NoJitter:
    def uniform(self, low, high):
        return 0.0


class PerformanceRetryCauseTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        network.start()
        self.addCleanup(network.stop)

    def handle(self, fixture):
        job = fixture.store.jobs[0]
        return H.issue_inventory_handle(customer_id=job["customer_id"],
            snapshot_at=job["snapshot_at"], now=fixture.clock.now(),
            validate=lambda cid, snapshot, at: fixture.store.performance_account_valid(job, at))

    def test_deadline_after_retries_preserves_cause_without_extra_calls(self):
        for reply, expected in (((503, {"message": "비공개응답"}), "SERVER"),
                                (TimeoutError("비공개응답"), "NETWORK")):
            with self.subTest(cause=expected):
                fixture = BatchFixture(6)
                fixture.http.tick = lambda call: fixture.clock.advance(1.5)
                fixture.http.script("/ncc/campaigns", *((reply,) * 4))
                started = fixture.clock.monotonic()

                self.assertEqual(fixture.run(max_seconds=10).counts, {"retry": 1})

                self.assertEqual(fixture.result["error_code"], expected)
                self.assertEqual(fixture.reader.calls, 3)
                self.assertEqual(len(fixture.http.calls), 3)
                self.assertEqual(fixture.clock.sleeps, [1.0, 2.0])
                self.assertEqual(fixture.clock.monotonic() - started, 7.5)
                self.assertNotIn("daily_rows", fixture.result)
                self.assertNotIn("비공개응답", str(fixture.result))

    def test_reader_abort_keeps_budget_code_and_message_with_retry_cause(self):
        for max_calls, max_seconds, expected, message, calls, sleeps, elapsed in (
                (8, 10, "REQUEST_DEADLINE", "bounded-deadline", 3, [1.0, 2.0], 7.5),
                (1, 10, "REQUEST_CALL_CAP", "bounded-call-cap", 1, [1.0], 2.5),
                (8, 1, "REQUEST_DEADLINE", "bounded-deadline", 1, [], 1.5)):
            with self.subTest(code=expected, seconds=max_seconds):
                fixture = BatchFixture()
                fixture.http.tick = lambda call: fixture.clock.advance(1.5)
                fixture.http.script("/ncc/campaigns", *((503, {}),) * 4)
                started = fixture.clock.monotonic()

                with fixture.reader.bounded_requests(max_calls=max_calls, max_seconds=max_seconds):
                    with self.assertRaises(N.RunAbort) as caught:
                        fixture.reader.get_campaigns(self.handle(fixture))

                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(caught.exception.cause_code, "SERVER")
                self.assertEqual(str(caught.exception), message)
                self.assertEqual(caught.exception.args, (message,))
                self.assertEqual(fixture.reader.calls, calls)
                self.assertEqual(len(fixture.http.calls), calls)
                self.assertEqual(fixture.clock.sleeps, sleeps)
                self.assertEqual(fixture.clock.monotonic() - started, elapsed)

    def test_mixed_retries_preserve_last_cause_in_same_request(self):
        fixture = BatchFixture()
        fixture.http.tick = lambda call: fixture.clock.advance(1.5)
        fixture.http.script("/ncc/campaigns", (503, {}), TimeoutError(), (503, {}), TimeoutError())
        with fixture.reader.bounded_requests(max_calls=8, max_seconds=10):
            with self.assertRaises(N.RunAbort) as caught:
                fixture.reader.get_campaigns(self.handle(fixture))
        self.assertEqual(caught.exception.code, "REQUEST_DEADLINE")
        self.assertEqual(caught.exception.cause_code, "NETWORK")
        self.assertEqual(fixture.reader.calls, 4)
        self.assertEqual(fixture.clock.sleeps, [1.0, 1.0, 2.0])

    def test_successful_retry_does_not_carry_cause_to_next_request(self):
        for max_calls, max_seconds, expected in ((2, 10, "REQUEST_CALL_CAP"),
                                                  (8, 1.25, "REQUEST_DEADLINE")):
            with self.subTest(code=expected):
                fixture = BatchFixture()
                fixture.http.script("/ncc/campaigns", (503, {}))
                handle = self.handle(fixture)
                with fixture.reader.bounded_requests(max_calls=max_calls, max_seconds=max_seconds):
                    self.assertEqual(len(fixture.reader.get_campaigns(handle)), 6)
                    with self.assertRaises(N.RunAbort) as caught:
                        fixture.reader.get_campaigns(handle)
                self.assertEqual(caught.exception.code, expected)
                self.assertIsNone(caught.exception.cause_code)
                self.assertEqual(fixture.reader.calls, 2)
                self.assertEqual(fixture.clock.sleeps, [1.0])

    def test_new_request_does_not_carry_cause_from_previous_failed_request(self):
        fixture = BatchFixture()
        fixture.http.script("/ncc/campaigns", (503, {}))
        handle = self.handle(fixture)
        with fixture.reader.bounded_requests(max_calls=8, max_seconds=0.5):
            with self.assertRaises(N.RunAbort) as caught:
                fixture.reader.get_campaigns(handle)
            self.assertEqual(caught.exception.cause_code, "SERVER")
            fixture.clock.advance(0.5)
            with self.assertRaises(N.RunAbort) as later:
                fixture.reader.get_campaigns(handle)
        self.assertEqual(later.exception.code, "REQUEST_DEADLINE")
        self.assertIsNone(later.exception.cause_code)
        self.assertEqual(fixture.reader.calls, 1)
        self.assertEqual(fixture.clock.sleeps, [])

    def test_rate_keeps_existing_precedence_over_later_server_retry_cause(self):
        fixture = BatchFixture()
        fixture.reader = N.NaverReader(creds(), transport=fixture.http,
                                      clock=fixture.clock, rng=NoJitter())
        fixture.http.tick = lambda call: fixture.clock.advance(1)
        fixture.http.script("/ncc/campaigns", (429, {"code": 1016}), *((503, {}),) * 3)

        outcome = fixture.run(max_seconds=10)

        self.assertEqual(outcome.code, "BUDGET")
        self.assertEqual(outcome.counts, {"retry": 1})
        self.assertEqual(fixture.result["error_code"], "RATE")
        self.assertTrue(fixture.reader.rate_limited)
        self.assertEqual(fixture.reader.calls, 4)
        self.assertEqual(fixture.clock.sleeps, [2.0, 1.0, 2.0])

    def test_retry_cause_accepts_only_fixed_safe_codes(self):
        for supplied in ("SERVER", "NETWORK", "RATE", None, "비공개응답", "REQUEST_DEADLINE", 123, {}, []):
            with self.subTest(cause=supplied):
                error = N.RunAbort("기존 중단 문구", code="REQUEST_CALL_CAP", cause_code=supplied)
                expected = supplied if type(supplied) is str and supplied in {"SERVER", "NETWORK", "RATE"} else None
                self.assertEqual(error.cause_code, expected)
                self.assertEqual(error.code, "REQUEST_CALL_CAP")
                self.assertEqual(str(error), "기존 중단 문구")
                self.assertEqual(error.args, ("기존 중단 문구",))
                self.assertNotIn("비공개응답", repr(error))


if __name__ == "__main__":
    unittest.main()
