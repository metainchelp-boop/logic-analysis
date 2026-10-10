"""현재 원천 응답의 조회 전용 분류. 저장판/전환 산정 근거와 숫자 0을 구분한다."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import unittest

from naver_engine import report_refresh as RF, reporting as R
from naver_engine.tests.test_report_revisions import ReportAdapter


class ConversionResponseTests(unittest.TestCase):
    def setUp(self):
        self.period = R.period("weekly", date(2026, 9, 28))
        self.now = datetime(2026, 10, 5, 10, tzinfo=R.KST)

    def rows(self, cid=101, **changes):
        stamp = self.now.isoformat()
        return [{"customer_id": cid, "day": str(self.period.start+timedelta(days=offset)),
                 "basic_complete": True, "conversion_complete": False,
                 "imp": 10, "clk": 1, "spend": 20, "conversions": 0, "conversion_value": 0,
                 "checked_at": stamp, "source_at": stamp, "source_generation": stamp, **changes}
                for offset in range((self.period.end-self.period.start).days+1)]

    def state(self, rows, **changes):
        args = {"period": self.period, "expected": [101], "rows": rows, "jobs": [], "queued": [],
                "prior": {}, "required_after": {}, "dirty": False, "now": self.now}
        args.update(changes)
        return RF.scope_state(**args)

    def assert_partition(self, response):
        counts = ("expected", "received", "zero", "positive", "missing_or_null", "source_unverified", "basic_incomplete")
        self.assertEqual(set(response), {"status", *(key+"_account_days" for key in counts)})
        for key in counts:
            self.assertIs(type(response[key+"_account_days"]), int)
            self.assertGreaterEqual(response[key+"_account_days"], 0)
        self.assertEqual(response["received_account_days"], response["zero_account_days"]+response["positive_account_days"])
        self.assertEqual(response["expected_account_days"], sum(response[key+"_account_days"]
            for key in ("received", "missing_or_null", "source_unverified", "basic_incomplete")))
        json.dumps(response, allow_nan=False)

    def test_zero_response_is_available_without_claiming_conversion_evidence(self):
        rows = self.rows()
        before = deepcopy(rows)
        state = self.state(rows)
        response = state["conversion_response"]
        self.assertEqual(response["status"], "complete")
        self.assertEqual(response["zero_account_days"], 7)
        self.assertEqual(state["validation"]["status"], "pending")
        self.assertIsNone(state["validation"]["last_checked_at"])
        self.assertEqual(rows, before)
        self.assert_partition(response)

    def test_positive_response_does_not_change_strict_validation(self):
        state = self.state(self.rows(conversions=1, conversion_value=0))
        self.assertEqual(state["conversion_response"]["positive_account_days"], 7)
        self.assertEqual(state["conversion_response"]["status"], "complete")
        self.assertEqual(state["validation"]["pending_account_days"], 7)
        strict = self.state(self.rows(conversion_complete=True))
        self.assertEqual(strict["conversion_response"]["zero_account_days"], 7)
        self.assertEqual(strict["validation"]["status"], "complete")

    def test_monthly_zero_responses_remain_available_without_strict_conversion_evidence(self):
        self.period = R.period("monthly", date(2026, 9, 28))
        state = self.state(self.rows())
        self.assertEqual(state["conversion_response"]["expected_account_days"], 30)
        self.assertEqual(state["conversion_response"]["zero_account_days"], 30)
        self.assertEqual(state["conversion_response"]["status"], "complete")
        self.assertEqual(state["validation"]["pending_account_days"], 30)

    def test_null_invalid_and_boolean_numbers_are_not_zero_responses(self):
        for key in R.CONVERSION_FIELDS:
            for value in (None, True, False, "0", -1, float("nan"), float("inf"), R.MAX_NUMBER+1):
                with self.subTest(key=key, value=value):
                    response = self.state(self.rows(**{key: value}))["conversion_response"]
                    self.assertEqual(response["status"], "unavailable")
                    self.assertEqual(response["missing_or_null_account_days"], 7)
                    self.assert_partition(response)

    def test_partial_response_counts_have_disjoint_reasons(self):
        rows = self.rows()
        rows[0]["conversions"] = None
        rows[1]["conversion_value"] = None
        rows[2]["source_at"] = None
        rows[3]["basic_complete"] = False
        rows[4]["spend"] = True
        rows[5]["conversion_value"] = 5
        response = self.state(rows)["conversion_response"]
        self.assertEqual(response, {"status": "partial", "expected_account_days": 7,
            "received_account_days": 2, "zero_account_days": 1, "positive_account_days": 1,
            "missing_or_null_account_days": 2, "source_unverified_account_days": 1,
            "basic_incomplete_account_days": 2})
        self.assert_partition(response)

    def test_missing_rows_and_empty_scope_are_unavailable(self):
        response = self.state([])["conversion_response"]
        self.assertEqual(response["basic_incomplete_account_days"], 7)
        self.assertEqual(response["status"], "unavailable")
        empty = self.state(self.rows(), expected=[])["conversion_response"]
        self.assertEqual(empty["expected_account_days"], 0)
        self.assertEqual(empty["status"], "unavailable")
        self.assert_partition(empty)

    def test_source_time_and_required_generation_must_be_verified(self):
        invalid = (None, "bad-time", "2026-10-05T10:00:00", (self.now+timedelta(hours=1)).isoformat())
        for key in ("checked_at", "source_at", "source_generation"):
            for value in invalid:
                with self.subTest(key=key, value=value):
                    response = self.state(self.rows(**{key: value}))["conversion_response"]
                    self.assertEqual(response["source_unverified_account_days"], 7)
                    self.assertEqual(response["status"], "unavailable")
        before_base = self.period.due_at.replace(hour=0, minute=0).isoformat()
        self.assertEqual(self.state(self.rows(source_generation=before_base))["conversion_response"]["source_unverified_account_days"], 7)
        later = (self.now+timedelta(minutes=1)).isoformat()
        self.assertEqual(self.state(self.rows(), required_after={"101": later})["conversion_response"]["source_unverified_account_days"], 7)
        same_day = self.period.end.isoformat()+"T23:00:00+09:00"
        rows = self.rows()
        rows[-1].update(checked_at=same_day, source_at=same_day, source_generation=same_day)
        required = {"101": self.period.end.isoformat()+"T00:01:00+09:00"}
        self.assertEqual(self.state(rows, required_after=required)["conversion_response"]["source_unverified_account_days"], 1)

    def test_newer_invalid_failed_or_queued_work_blocks_stale_response_completion(self):
        later = self.now+timedelta(minutes=1)
        job = {"customer_id": 101, "period_start": str(self.period.start), "period_end": str(self.period.end),
               "status": "ok", "checked_at": later.isoformat(), "generation": later.isoformat()}
        for changes in ({}, {"checked_at": "bad-time"}, {"checked_at": "2026-10-05T10:01:00"},
                        {"checked_at": (later+timedelta(hours=1)).isoformat()},
                        {"status": "reading", "generation": self.now.isoformat()},
                        {"status": "retry", "generation": self.now.isoformat()}):
            with self.subTest(job=changes):
                state = self.state(self.rows(), jobs=[{**job, **changes}], now=later)
                self.assertEqual(state["conversion_response"]["source_unverified_account_days"], 7)
        request = {"customer_id": 101, "period_start": str(self.period.start), "period_end": str(self.period.start)}
        queued = self.state(self.rows(), queued=[request])["conversion_response"]
        self.assertEqual(queued["received_account_days"], 6)
        self.assertEqual(queued["source_unverified_account_days"], 1)

    def test_older_failure_other_scope_and_dirty_do_not_discard_current_responses(self):
        older = (self.now-timedelta(minutes=1)).isoformat()
        job = {"customer_id": 101, "period_start": str(self.period.start), "period_end": str(self.period.end),
               "status": "retry", "checked_at": older, "generation": older}
        request = {"customer_id": 202, "period_start": str(self.period.start), "period_end": str(self.period.end)}
        state = self.state(self.rows(conversion_complete=True), jobs=[job], queued=[request], dirty=True)
        self.assertEqual(state["conversion_response"]["status"], "complete")
        self.assertEqual(state["validation"]["status"], "updating")

    def test_unverified_latest_job_generation_blocks_response_without_changing_strict_validation(self):
        job = {"customer_id": 101, "period_start": str(self.period.start), "period_end": str(self.period.end),
               "status": "ok", "checked_at": self.now.isoformat()}
        for generation in (None, "bad-time", "2026-10-05T10:00:00"):
            with self.subTest(generation=generation):
                state = self.state(self.rows(conversion_complete=True), jobs=[{**job, "generation": generation}])
                self.assertEqual(state["conversion_response"]["status"], "unavailable")
                self.assertEqual(state["conversion_response"]["source_unverified_account_days"], 7)
                self.assertEqual(state["validation"]["status"], "complete")

    def test_period_and_account_scope_do_not_leak_extra_rows(self):
        rows = self.rows()+self.rows(cid=202, conversions=1)+self.rows(cid=303, conversions=1)
        rows.append({**rows[0], "day": str(self.period.start-timedelta(days=1)), "conversions": 2})
        company = self.state(rows, expected=[101, 202])["conversion_response"]
        account = self.state(rows, expected=[101])["conversion_response"]
        self.assertEqual(company["expected_account_days"], 14)
        self.assertEqual(company["zero_account_days"], 7)
        self.assertEqual(company["positive_account_days"], 7)
        self.assertEqual(account["expected_account_days"], 7)
        self.assertEqual(account["positive_account_days"], 0)
        self.assert_partition(company)
        self.assert_partition(account)


class ConversionResponseStorageTests(unittest.TestCase):
    def test_null_or_other_company_source_is_not_projected_into_current_company(self):
        store = ReportAdapter()
        self.addCleanup(store._conn.close)
        period = R.period("weekly", date(2026, 9, 28))
        store.seed(period.start, period.end)
        store.generate_reports(store.now)
        rid = store.report_latest_ids(period.key, [11])[11]
        saved = deepcopy(store.report_snapshot_detail(rid))
        for owner in (None, 12):
            with self.subTest(owner=owner):
                store._conn.execute("UPDATE naver_auto_daily_performance SET possibility_id=?", (owner,))
                before = store._conn.total_changes
                state = store.report_refresh_states_batch([rid])[rid]["company"]
                self.assertEqual(state["conversion_response"]["status"], "unavailable")
                self.assertEqual(state["conversion_response"]["basic_incomplete_account_days"], 7)
                self.assertEqual(store._conn.total_changes, before)
                self.assertEqual(store.report_snapshot_detail(rid), saved)

    def test_projection_is_current_only_and_does_not_write_or_change_saved_numbers(self):
        store = ReportAdapter()
        self.addCleanup(store._conn.close)
        period = R.period("weekly", date(2026, 9, 28))
        store.seed(period.start, period.end)
        store._conn.execute("UPDATE naver_auto_daily_performance SET conversion_complete=0,conversions=0,conversion_value=0")
        store.generate_reports(store.now)
        rid = store.report_latest_ids(period.key, [11])[11]
        saved = deepcopy(store.report_snapshot_detail(rid))
        before, statements = store._conn.total_changes, []
        store._conn.set_trace_callback(statements.append)
        try:
            states = store.report_refresh_states_batch([rid])
        finally:
            store._conn.set_trace_callback(None)
        self.assertEqual(states[rid]["company"]["conversion_response"]["zero_account_days"], 7)
        self.assertEqual(states[rid]["accounts"]["101"]["conversion_response"]["status"], "complete")
        self.assertEqual(states[rid]["company"]["validation"]["status"], "pending")
        self.assertEqual(store._conn.total_changes, before)
        self.assertEqual(store.report_snapshot_detail(rid), saved)
        self.assertIsNone(saved["payload"]["totals"]["conversions"])
        self.assertNotIn("conversion_response", json.dumps(saved))
        self.assertEqual(sum("FROM naver_auto_daily_performance" in sql for sql in statements), 1)
        self.assertLessEqual(len(statements), 7)
        store.now += timedelta(hours=1)
        store.seed(period.start, period.end, spend=2000)
        store.generate_reports(store.now)
        self.assertNotEqual(store.report_latest_ids(period.key, [11])[11], rid)
        self.assertEqual(store.report_refresh_states_batch([rid]), {})
        self.assertEqual(store.report_snapshot_detail(rid), saved)


if __name__ == "__main__":
    unittest.main()
