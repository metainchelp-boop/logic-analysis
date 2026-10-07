"""실제 읽기 관문의 상세 점검 중단 원인을 고정 로그로만 보존한다. 외부 HTTP 없음."""
from contextlib import contextmanager
import unittest
from unittest.mock import patch

from naver_engine import morning as M, naver_read as N
from naver_engine.tests import test_morning as TM
from naver_engine.tests import test_morning_continuous as MC
from naver_runtime.scheduler import Scheduler


LOGGER = "naver_engine.morning"


@contextmanager
def scene():
    fixture = MC.ContinuousMorningTests(methodName="test_internal_yield_keeps_completed_account_and_continues_remaining")
    fixture.setUp()
    try:
        fixture.standard_ads()
        fixture.scene()
        yield fixture
    finally:
        fixture.tearDown()
        fixture.doCleanups()


class MorningAbortDiagnosticsTests(unittest.TestCase):
    def run_bounded(self, fixture, *, calls=24, seconds=30):
        reader = fixture.reader()
        with reader.bounded_requests(max_calls=calls, max_seconds=seconds):
            outcome = M.run_continuous(reader, fixture.monitored(), fixture.fc.now)
        self.assertLessEqual(reader.calls, calls)
        self.assertTrue(all(call.method == "GET" and not call.has_body for call in fixture.naver.calls))
        return reader, outcome

    def test_real_retry_deadline_logs_distinct_safe_cause_and_keeps_failure_backoff(self):
        for cause, reply, latency in (("SERVER", (503, {"message": "PRIVATE_BODY"}), 8.5),
                                      ("NETWORK", TimeoutError("PRIVATE_EXCEPTION"), 8.5),
                                      ("RATE", (429, {"code": 1016}), 7)):
            with self.subTest(cause=cause), scene() as fixture:
                fixture.naver.tick = lambda call: fixture.fc.advance(latency)
                fixture.naver.script("/ncc/campaigns", *((reply,) * 10))
                started = fixture.fc.now()
                with self.assertLogs(LOGGER, level="WARNING") as logs:
                    reader, outcome = self.run_bounded(fixture)
                elapsed_ms = int((fixture.fc.now() - started).total_seconds() * 1000)
                expected = [f"WARNING:{LOGGER}:morning_abort code=REQUEST_DEADLINE "
                    f"cause={cause} calls=3 elapsed_ms={elapsed_ms}"]
                if cause == "NETWORK":
                    expected.append(f"WARNING:{LOGGER}:morning_network_failure kind=TIMEOUT phase=TRANSPORT "
                        "step=CAMPAIGNS request_elapsed_ms=8500 remaining_ms=1500")
                self.assertEqual(logs.output, expected)
                self.assertEqual(reader.calls, 3)
                self.assertEqual(reader.rate_limited, cause == "RATE")
                self.assertEqual((outcome.outcome, outcome.codes), (M.OUT_FAILED, (M.CODE_RUN_ABORT,)))
                self.assertEqual(Scheduler._runtime_problem("morning", outcome), ("error", "RUNTIME_ERROR"))
                self.assertEqual(fixture.st.runs_on(TM.TODAY)[-1]["error_kind"], M.CODE_RUN_ABORT)
                self.assertIsNone(fixture.st.account_day(TM.A, TM.TODAY))
                self.assertFalse(M.continuous_due(fixture.monitored(), fixture.fc.now()))
                fixture.fc.advance(M.RETRY_AFTER.total_seconds() - 1)
                self.assertFalse(M.continuous_due(fixture.monitored(), fixture.fc.now()))
                fixture.fc.advance(1)
                self.assertTrue(M.continuous_due(fixture.monitored(), fixture.fc.now()))
                for private in ("PRIVATE_BODY", "PRIVATE_EXCEPTION", str(TM.A), TM.MARK_API_KEY, TM.MARK_SECRET):
                    self.assertNotIn(private, "\n".join(logs.output))

    def test_pure_budget_yield_is_not_an_abort_warning_and_keeps_progress(self):
        for calls, seconds in ((4, 30), (24, 0.5)):
            with self.subTest(calls=calls, seconds=seconds), scene() as fixture:
                with self.assertNoLogs(LOGGER, level="WARNING"):
                    reader, outcome = self.run_bounded(fixture, calls=calls, seconds=seconds)
                self.assertIn("BUDGET_YIELD", outcome.codes)
                self.assertEqual(outcome.outcome, M.OUT_DONE)
                self.assertIsNone(fixture.st.runs_on(TM.TODAY)[-1]["error_kind"])
                self.assertTrue(M.continuous_due(fixture.monitored(), fixture.fc.now()))
                with self.assertNoLogs(LOGGER, level="WARNING"):
                    self.run_bounded(fixture)
                self.assertEqual(fixture.st.account_day(TM.A, TM.TODAY)["status"], "ok")

    def test_successful_retry_does_not_label_the_next_pure_budget_as_server_failure(self):
        with scene() as fixture:
            fixture.naver.script("/ncc/campaigns", (503, {}))
            with self.assertNoLogs(LOGGER, level="WARNING"):
                reader, outcome = self.run_bounded(fixture, calls=2)
            self.assertEqual(reader.calls, 2)
            self.assertEqual((outcome.outcome, outcome.codes), (M.OUT_DONE, ("BUDGET_YIELD",)))

    def test_successful_network_retry_does_not_label_a_later_budget_yield(self):
        with scene() as fixture:
            fixture.naver.script("/ncc/campaigns", TimeoutError("PRIVATE"))
            with self.assertNoLogs(LOGGER, level="WARNING"):
                reader, outcome = self.run_bounded(fixture, calls=2)
            self.assertEqual(reader.calls, 2)
            self.assertEqual((outcome.outcome, outcome.codes), (M.OUT_DONE, ("BUDGET_YIELD",)))

    def test_wrapped_transport_diagnostic_keeps_its_stage_and_timing(self):
        with scene() as fixture:
            fixture.naver.tick = lambda call: fixture.fc.advance(8.5 if call.path == "/billing/bizmoney" else 0)
            error = N.TransportNetworkError(N.NetworkDiagnostic("DNS", "OPEN", elapsed_ms=50, remaining_ms=150))
            fixture.naver.script("/billing/bizmoney", *((error,) * 10))
            with self.assertLogs(LOGGER, level="WARNING") as logs:
                _, outcome = self.run_bounded(fixture)
            self.assertEqual(logs.output[-1], f"WARNING:{LOGGER}:morning_network_failure kind=DNS phase=OPEN "
                "step=BIZMONEY request_elapsed_ms=50 remaining_ms=150")
            self.assertEqual(outcome.outcome, M.OUT_FAILED)

    def test_mutated_network_diagnostic_is_sanitized_again_before_logging(self):
        bad_values = [None, "PRIVATE", {}, N.NetworkDiagnostic("PRIVATE", "PRIVATE", "PRIVATE", "PRIVATE", True),
                      N.NetworkDiagnostic("TIMEOUT", "BODY", "STATS", -1, 9_999_999)]
        for value in bad_values:
            with self.subTest(value_type=type(value).__name__), scene() as fixture:
                error = N.RunAbort("PRIVATE", code="REQUEST_DEADLINE", cause_code="NETWORK")
                error.network_diagnostic = value
                with patch.object(M, "read_account", side_effect=error), self.assertLogs(LOGGER, level="WARNING") as logs:
                    _, outcome = self.run_bounded(fixture)
                self.assertNotIn("PRIVATE", "\n".join(logs.output))
                self.assertEqual(outcome.outcome, M.OUT_FAILED)
                expected = ("kind=TIMEOUT phase=BODY step=STATS request_elapsed_ms=0 remaining_ms=3600000"
                    if value == bad_values[-1] else
                    "kind=UNRECOGNIZED phase=UNRECOGNIZED step=UNRECOGNIZED request_elapsed_ms=0 remaining_ms=0")
                self.assertEqual(logs.output[-1], f"WARNING:{LOGGER}:morning_network_failure {expected}")

    def test_legacy_call_cap_logs_none_cause_and_remains_a_failed_run(self):
        with scene() as fixture:
            reader = fixture.reader(max_calls=1)
            with self.assertLogs(LOGGER, level="WARNING") as logs:
                outcome = M.run_morning(reader, fixture.st, fixture.fc.now)
            self.assertEqual(logs.output, [f"WARNING:{LOGGER}:morning_abort code=REQUEST_CALL_CAP "
                "cause=NONE calls=1 elapsed_ms=0"])
            self.assertEqual((outcome.outcome, outcome.codes), (M.OUT_FAILED, (M.CODE_RUN_ABORT,)))

    def test_unrecognized_mutated_exception_fields_never_escape_into_logs(self):
        for value in ("PRIVATE_EXCEPTION", {}, []):
            with self.subTest(value_type=type(value).__name__), scene() as fixture:
                error = N.RunAbort("PRIVATE_EXCEPTION")
                error.code = value
                error.cause_code = value
                with patch.object(M, "read_account", side_effect=error), self.assertLogs(LOGGER, level="WARNING") as logs:
                    reader, outcome = self.run_bounded(fixture)
                self.assertEqual(logs.output, [f"WARNING:{LOGGER}:morning_abort code=UNRECOGNIZED "
                    "cause=UNRECOGNIZED calls=0 elapsed_ms=0"])
                self.assertEqual(outcome.outcome, M.OUT_FAILED)

    def test_later_account_abort_preserves_completed_account_and_total_call_count(self):
        with scene() as fixture:
            fixture.ads.fail[(TM.B, "camps")] = (503, {})
            fixture.naver.tick = lambda call: fixture.fc.advance(8.5 if int(call.customer) == TM.B else 0)
            started = fixture.fc.now()
            with self.assertLogs(LOGGER, level="WARNING") as logs:
                reader, outcome = self.run_bounded(fixture)
            elapsed_ms = int((fixture.fc.now() - started).total_seconds() * 1000)
            self.assertEqual(logs.output, [f"WARNING:{LOGGER}:morning_abort code=REQUEST_DEADLINE "
                f"cause=SERVER calls={reader.calls} elapsed_ms={elapsed_ms}"])
            self.assertEqual(fixture.st.account_day(TM.A, TM.TODAY)["status"], "ok")
            self.assertIsNone(fixture.st.account_day(TM.B, TM.TODAY))
            run = fixture.st.runs_on(TM.TODAY)[-1]
            self.assertEqual((run["accounts_ok"], run["accounts_total"], run["error_kind"]), (1, 2, M.CODE_RUN_ABORT))
            self.assertEqual(outcome.outcome, M.OUT_FAILED)


if __name__ == "__main__":
    unittest.main()
