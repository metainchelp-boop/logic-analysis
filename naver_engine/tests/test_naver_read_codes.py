"""읽기 관문의 고정 진단 코드 — 응답 원문 없이 기존 예외 문구를 보존한다."""
import unittest
from datetime import date

from naver_engine import naver_read as R
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_naver_read import NOW, check_handle, creds


class DiagnosticCodeTest(unittest.TestCase):
    def test_budget_error_default_and_allowlist_preserve_message(self):
        for supplied, expected in (
            (None, "REQUEST_BUDGET"),
            ("REQUEST_DEADLINE", "REQUEST_DEADLINE"),
            ("REQUEST_CALL_CAP", "REQUEST_CALL_CAP"),
            ("RATE", "RATE"),
            ("raw-response-or-secret", "REQUEST_BUDGET"),
            ([], "REQUEST_BUDGET"),
        ):
            with self.subTest(code=supplied):
                error = R.RunAbort("기존 중단 문구", **({} if supplied is None else {"code": supplied}))
                self.assertEqual(error.code, expected)
                self.assertEqual(str(error), "기존 중단 문구")
                self.assertEqual(error.args, ("기존 중단 문구",))

    def test_shape_error_default_and_allowlist_preserve_message(self):
        for supplied, expected in (
            (None, "STATS_SHAPE_UNKNOWN"),
            ("STATS_NUMERIC_INVALID", "STATS_NUMERIC_INVALID"),
            ("STATS_ROW_ID_INVALID", "STATS_ROW_ID_INVALID"),
            ("STATS_DATE_INVALID", "STATS_DATE_INVALID"),
            ("raw-response-or-secret", "STATS_SHAPE_UNKNOWN"),
            ([], "STATS_SHAPE_UNKNOWN"),
        ):
            with self.subTest(code=supplied):
                error = R.StatsShapeUnknown("기존 오류 문구", **({} if supplied is None else {"code": supplied}))
                self.assertEqual(error.code, expected)
                self.assertEqual(str(error), "기존 오류 문구")
                self.assertEqual(error.args, ("기존 오류 문구",))

    def test_invalid_numeric_response_has_fixed_code_without_raw_value(self):
        day = date(2026, 10, 2)
        for value in (True, "raw-response-or-secret", [], {}, float("nan"), float("inf")):
            for parser in (
                lambda: R.parse_stats({"data": [{"id": "cmp-a", "salesAmt": value}]},
                                      ["cmp-a"], ("salesAmt",), day),
                lambda: R.parse_daily({"data": [{"dateStart": str(day), "salesAmt": value}]},
                                      "cmp-a", ("salesAmt",), day, day),
            ):
                with self.subTest(value=value), self.assertRaises(R.StatsShapeUnknown) as caught:
                    parser()
                self.assertEqual(caught.exception.code, "STATS_NUMERIC_INVALID")
                self.assertEqual(str(caught.exception), "숫자가 아닌 지표(salesAmt)")
                self.assertNotIn("raw-response-or-secret", repr(caught.exception))

    def test_invalid_row_identity_has_fixed_code_without_raw_id(self):
        for rows, message in (
            ([None], "줄에 번호(id)가 없음"),
            ([{}], "줄에 번호(id)가 없음"),
            ([{"id": 123}], "줄에 번호(id)가 없음"),
            ([{"id": "raw-customer-or-secret"}], "요청하지 않은 번호의 줄"),
            ([{"id": "cmp-a"}, {"id": "cmp-a"}], "같은 번호의 줄이 두 번"),
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(R.StatsShapeUnknown) as caught:
                    R.parse_stats({"data": rows}, ["cmp-a"], ("salesAmt",), date(2026, 10, 2))
                self.assertEqual(caught.exception.code, "STATS_ROW_ID_INVALID")
                self.assertEqual(str(caught.exception), message)
                self.assertNotIn("raw-customer-or-secret", repr(caught.exception))

    def test_invalid_daily_dates_have_fixed_code_without_raw_date(self):
        day = date(2026, 10, 2)
        for rows, message in (
            ([{}], "하루 줄에 날짜가 없음"),
            ([{"dateStart": "raw-response-or-secret"}], "하루 줄에 날짜가 없음"),
            ([{"dateStart": "2026-99-99"}], "요청하지 않은 날짜의 줄"),
            ([{"dateStart": "2026-10-01"}], "요청하지 않은 날짜의 줄"),
            ([{"dateStart": str(day)}, {"dateStart": str(day)}], "같은 날짜의 줄이 두 번"),
            ([{"dateStart": str(day), "dateEnd": "raw-response-or-secret"}], "하루 줄이 하루가 아님"),
        ):
            with self.subTest(rows=rows):
                with self.assertRaises(R.StatsShapeUnknown) as caught:
                    R.parse_daily({"data": rows}, "cmp-a", ("salesAmt",), day, day)
                self.assertEqual(caught.exception.code, "STATS_DATE_INVALID")
                self.assertEqual(str(caught.exception), message)
                self.assertNotIn("raw-response-or-secret", repr(caught.exception))

    def test_reader_propagates_fixed_parser_codes_from_get_responses(self):
        day = NOW.date()
        for daily, body, code in (
            (False, {"raw-response-or-secret": []}, "STATS_SHAPE_UNKNOWN"),
            (False, {"data": [{"id": "cmp-a", "salesAmt": "raw-response-or-secret"}]}, "STATS_NUMERIC_INVALID"),
            (False, {"data": [{"id": "raw-response-or-secret"}]}, "STATS_ROW_ID_INVALID"),
            (True, {"data": [{"dateStart": "raw-response-or-secret"}]}, "STATS_DATE_INVALID"),
        ):
            with self.subTest(code=code):
                transport = FakeNaver()
                transport.script("/stats", (200, body))
                reader = R.NaverReader(creds(), transport=transport, clock=FakeClock(NOW))
                with self.assertRaises(R.StatsShapeUnknown) as caught:
                    if daily:
                        reader.get_stats_daily(check_handle(), "cmp-a", day, day)
                    else:
                        reader.get_stats_summary(check_handle(), ["cmp-a"], day, day)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn("raw-response-or-secret", repr(caught.exception))
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(transport.calls[0].method, "GET")


class RequestAbortCodeTest(unittest.TestCase):
    def test_repeated_rate_pause_has_fixed_code_and_preserves_pause_policy(self):
        class NoJitter:
            def uniform(self, low, high):
                return 0.0

        transport, clock = FakeNaver(), FakeClock(NOW)
        reader = R.NaverReader(creds(), transport=transport, clock=clock, rng=NoJitter())
        for _ in range(10):
            transport.script("/ncc/campaigns", (429, {"code": 1016}), (200, []))
        with self.assertRaises(R.RunAbort) as caught:
            for _ in range(10):
                reader.get_campaigns(check_handle())
        self.assertEqual(caught.exception.code, "RATE")
        self.assertEqual(str(caught.exception), "rate-paused-twice")
        self.assertTrue(reader.rate_limited)
        self.assertEqual(clock.sleeps.count(R.RATE_PAUSE), 1)
        self.assertEqual(reader.pauses, 2)
        self.assertEqual(len(transport.calls), 19)

    def test_deadlines_have_fixed_code_before_expired_or_pacing_request(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                transport, clock = FakeNaver(), FakeClock(NOW)
                transport.route(r"/ncc/campaigns", lambda call: (200, []))
                reader = R.NaverReader(creds(), transport=transport, clock=clock)
                with reader.bounded_requests(max_calls=10, max_seconds=0.1):
                    reader.get_campaigns(check_handle())
                    if expired:
                        clock.advance(0.1)
                    with self.assertRaises(R.RunAbort) as caught:
                        reader.get_campaigns(check_handle())
                self.assertEqual(caught.exception.code, "REQUEST_DEADLINE")
                self.assertEqual(str(caught.exception), "bounded-deadline")
                self.assertEqual(len(transport.calls), 1)
                self.assertEqual(clock.sleeps, [])

    def test_call_caps_have_fixed_code_and_do_not_send_another_request(self):
        for bounded in (False, True):
            with self.subTest(bounded=bounded):
                transport = FakeNaver()
                transport.route(r"/ncc/campaigns", lambda call: (200, []))
                reader = R.NaverReader(creds(), transport=transport, clock=FakeClock(NOW),
                                       max_calls=10 if bounded else 1)
                with reader.bounded_requests(max_calls=1 if bounded else 10, max_seconds=10):
                    reader.get_campaigns(check_handle())
                    with self.assertRaises(R.RunAbort) as caught:
                        reader.get_campaigns(check_handle())
                self.assertEqual(caught.exception.code, "REQUEST_CALL_CAP")
                self.assertEqual(str(caught.exception), "bounded-call-cap" if bounded else "call-cap")
                self.assertEqual(len(transport.calls), 1)


if __name__ == "__main__":
    unittest.main()
