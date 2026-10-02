"""저장된 일별 자료만으로 만드는 닫힌 기간 보고서의 행동 계약."""
import unittest
import json
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone

from naver_engine import reporting as R


NOW = datetime(2026, 10, 5, 10, tzinfo=R.KST)
WEEK = R.period("weekly", date(2026, 9, 28))


def daily_rows(report_period=WEEK, customers=(101,)):
    rows = []
    for cid in customers:
        for offset in range((report_period.end-report_period.start).days+1):
            rows.append({"customer_id": cid, "day": (report_period.start+timedelta(days=offset)).isoformat(),
                         "basic_complete": True, "conversion_complete": True,
                         "imp": 100, "clk": 10, "spend": 1000, "conversions": 1,
                         "conversion_value": 2000, "checked_at": NOW.isoformat(),
                         "source_at": None})
    return rows


class ReportingTests(unittest.TestCase):
    def test_revision_metadata_distinguishes_absent_previous_from_real_zero_metrics(self):
        rows = daily_rows()
        for row in rows:
            row.update({key: 0 for key in R.OUTPUT_FIELDS})
        report = R.aggregate(WEEK, (101,), rows, NOW)
        initial = R.revision_metadata(None, report)
        same = R.revision_metadata(report, report, 1)
        self.assertTrue(all(value is None for value in initial["metric_deltas"].values()))
        self.assertTrue(all(value == 0 for value in same["metric_deltas"].values()))
        self.assertFalse(initial["completeness_changed"])
        self.assertFalse(same["completeness_changed"])

    def test_revision_summary_retains_same_total_daily_movement(self):
        rows = daily_rows()
        first = R.aggregate(WEEK, (101,), rows, NOW)
        rows[0]["spend"], rows[1]["spend"] = 500, 1500
        corrected = R.aggregate(WEEK, (101,), rows, NOW)
        summary = R.revision_metadata(first, corrected, 7)
        self.assertEqual(summary["previous_report_id"], 7)
        self.assertEqual(summary["metric_deltas"]["spend"], 0)
        self.assertEqual(summary["changed_days"], ["2026-09-28", "2026-09-29"])
        self.assertIn("spend", summary["changed_metrics"])
        self.assertFalse(summary["completeness_changed"])

    def test_period_anchor_is_a_day_inside_the_reported_period(self):
        weekly = R.period("weekly", date(2025, 1, 1))
        self.assertEqual((weekly.start, weekly.end), (date(2024, 12, 30), date(2025, 1, 5)))
        self.assertEqual(weekly.due_at, datetime(2025, 1, 6, 10, tzinfo=R.KST))
        self.assertEqual(weekly.key, "weekly:2024-12-30:2025-01-05")
        monthly = R.period("monthly", date(2024, 2, 20))
        self.assertEqual((monthly.start, monthly.end), (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(monthly.due_at, datetime(2024, 3, 3, 10, tzinfo=R.KST))

    def test_due_periods_catch_up_after_downtime_with_kst_cutoff_and_bounded_work(self):
        since = date(2026, 9, 1)
        just_before = datetime(2026, 10, 3, 0, 59, 59, tzinfo=timezone.utc)
        before = R.due_periods(just_before, since)
        self.assertNotIn("monthly:2026-09-01:2026-09-30", [p.key for p in before])
        due = R.due_periods(just_before+timedelta(seconds=1), since)
        self.assertIn("monthly:2026-09-01:2026-09-30", [p.key for p in due])
        resumed = R.due_periods(datetime(2026, 10, 7, 16, tzinfo=R.KST), since)
        self.assertIn("weekly:2026-09-28:2026-10-04", [p.key for p in resumed])
        self.assertEqual([p.key for p in resumed], [p.key for p in R.due_periods(
            datetime(2026, 10, 8, 16, tzinfo=R.KST), since)])
        self.assertEqual(len(R.due_periods(just_before, date(2000, 1, 1), limit=3)), 3)
        self.assertEqual(R.due_periods(just_before, date(2027, 1, 1)), ())
        with self.assertRaises(R.ReportInvalid):
            R.due_periods(datetime(2026, 10, 3, 10), since)

    def test_complete_daily_accounts_create_numeric_weekly_report_and_weighted_ratios(self):
        rows = daily_rows(customers=(101, 202))
        for row in rows[7:]:
            row.update(spend=3000, conversion_value=0, conversions=0)
        report = R.aggregate(WEEK, (101, 202), rows, NOW)
        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["ready"])
        self.assertEqual(report["review_status"], "not_required")
        self.assertEqual(report["totals"], {"impressions": 1400, "clicks": 140, "spend": 28000,
                                            "conversions": 7, "conversion_value": 14000})
        self.assertEqual(report["ratios"]["roas"], 50)
        self.assertEqual(report["ratios"]["roas_spend"], 28000)
        self.assertEqual(report["coverage"]["expected_account_days"], 14)
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["generated_at"], NOW.isoformat())
        self.assertEqual(report["period_key"], WEEK.key)

    def test_missing_account_days_and_conversion_evidence_are_not_zero(self):
        rows = daily_rows(customers=(101, 202))
        rows.pop()  # 두 번째 계정의 일요일 전체가 없음
        rows[0].update(conversion_complete=False, conversion_value=None, conversions=None)
        rows[1].update(basic_complete=False, imp=999999)  # 일부 캠페인 합계를 전체처럼 쓰지 않음
        report = R.aggregate(WEEK, (101, 202), rows, NOW)
        self.assertFalse(report["ready"])
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["coverage"]["basic_complete_account_days"], 12)
        self.assertEqual(report["coverage"]["conversion_complete_account_days"], 12)
        self.assertEqual(report["totals"]["impressions"], 1200)
        self.assertEqual(report["ratios"]["roas_account_days"], 11)
        self.assertEqual(report["ratios"]["roas_spend"], 11000)
        self.assertEqual(report["ratios"]["roas_conversion_value"], 22000)
        self.assertEqual(report["ratios"]["roas"], 200)
        missing_day = next(item for item in report["missing"] if item["day"] == "2026-10-04")
        self.assertEqual(missing_day["account_index"], 2)
        self.assertEqual(missing_day["reason"], "day_missing")
        self.assertEqual(missing_day["metrics"], ["imp", "clk", "spend", "conversions", "conversion_value"])
        empty = R.aggregate(WEEK, (101,), [], NOW)
        self.assertEqual(empty["status"], "collecting")
        self.assertIsNone(empty["totals"]["spend"])
        self.assertIsNone(empty["totals"]["conversion_value"])
        self.assertIsNone(empty["ratios"]["roas"])
        self.assertFalse(R.aggregate(WEEK, (), [], NOW)["ready"])

    def test_daily_source_requires_closed_day_and_aware_nonfuture_collection_time(self):
        for checked_at, source_at in ((None, None), ("2026-10-05T10:00:00", None),
                                      ((NOW+timedelta(seconds=1)).isoformat(), None),
                                      ("2026-09-28T23:59:59+09:00", None),
                                      (NOW.isoformat(), "not-a-source-time"),
                                      (NOW.isoformat(), (NOW+timedelta(seconds=1)).isoformat())):
            with self.subTest(checked_at=checked_at, source_at=source_at):
                rows = daily_rows()
                rows[0].update(checked_at=checked_at, source_at=source_at)
                report = R.aggregate(WEEK, (101,), rows, NOW)
                self.assertFalse(report["ready"])
                self.assertEqual(report["coverage"]["basic_complete_account_days"], 6)
                self.assertEqual(report["missing"][0]["reason"], "source_unverified")
        rows = daily_rows()
        rows[0]["checked_at"] = "2026-09-29T00:00:00+09:00"
        report = R.aggregate(WEEK, (101,), rows, NOW)
        self.assertTrue(report["ready"])
        self.assertEqual(report["coverage"]["oldest_collected_at"], "2026-09-29T00:00:00+09:00")

    def test_report_requires_review_by_kind_and_never_becomes_ready_before_due_time(self):
        rows = daily_rows()
        self.assertEqual(R.aggregate(WEEK, (101,), rows, NOW, has_open_issues=True)["review_status"],
                         "needs_staff_review")
        month = R.period("monthly", date(2026, 9, 15))
        report = R.aggregate(month, (101,), daily_rows(month), NOW)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["review_status"], "needs_staff_review")
        rows.pop()
        self.assertNotEqual(R.aggregate(WEEK, (101,), rows, NOW)["status"], "ready")
        before = NOW-timedelta(hours=1)
        rows = daily_rows()
        for row in rows:
            row["checked_at"] = before.isoformat()
        report = R.aggregate(WEEK, (101,), rows, before)
        self.assertFalse(report["ready"])
        self.assertIn("not_due", report["blocked_reasons"])
        self.assertIn("no_confirmed_accounts", R.aggregate(WEEK, (), [], NOW)["blocked_reasons"])

    def test_duplicate_or_ambiguous_inputs_fail_closed_and_invalid_numbers_stay_missing(self):
        rows = daily_rows()
        for customers, source in (((101, 101), rows), ((True,), []), (("private-account",), []),
                                   ((101,), rows+[rows[0]]), ((101,), [{"customer_id": 101, "day": "private-date"}])):
            with self.subTest(customers=customers):
                with self.assertRaises(R.ReportInvalid) as caught:
                    R.aggregate(WEEK, customers, source, NOW)
                self.assertNotIn("private-", str(caught.exception))
        malformed_period = R.ReportPeriod("monthly", WEEK.start, WEEK.end, WEEK.due_at)
        with self.assertRaises(R.ReportInvalid):
            R.aggregate(malformed_period, (101,), rows, NOW)
        for value in (None, True, -1, float("nan"), float("inf"), R.MAX_NUMBER+1, "1000"):
            with self.subTest(value=value):
                source = daily_rows()
                source[0]["spend"] = value
                report = R.aggregate(WEEK, (101,), source, NOW)
                self.assertFalse(report["ready"])
                self.assertEqual(report["totals"]["spend"], 6000)
                self.assertEqual(report["missing"][0]["metrics"], ["spend"])

    def test_revision_is_stable_on_retry_but_changes_for_corrected_days_and_never_exposes_raw_identity(self):
        rows = daily_rows(customers=(987654321,))
        for row in rows:
            row.update(stage_key="환불", advertiser_name="비공개업체", api_key="비공개키")
        original = deepcopy(rows)
        report = R.aggregate(WEEK, (987654321,), rows, NOW)
        self.assertEqual(rows, original)
        self.assertTrue(report["ready"])  # 지금 단계가 과거 귀속 실적을 삭제하지 않음
        later = NOW+timedelta(hours=1)
        for row in rows:
            row["checked_at"] = later.isoformat()
        retried = R.aggregate(WEEK, (987654321,), list(reversed(rows)), later)
        self.assertEqual(report["revision_fingerprint"], retried["revision_fingerprint"])
        rows[0]["spend"] += 100
        rows[1]["spend"] -= 100  # 총합이 같아도 일별 정정 이력은 달라져야 함
        revised = R.aggregate(WEEK, (987654321,), rows, later)
        self.assertNotEqual(report["revision_fingerprint"], revised["revision_fingerprint"])
        outside = daily_rows(customers=(111222333,))
        outside[0]["checked_at"] = "비공개오류"
        ignored = R.aggregate(WEEK, (987654321,), original+outside, NOW)
        self.assertEqual(report["revision_fingerprint"], ignored["revision_fingerprint"])
        for private in ("customer_id", "987654321", "111222333", "비공개", "환불", "api_key"):
            self.assertNotIn(private, json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
