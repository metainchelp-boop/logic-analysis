"""계정별 보고서의 고정된 숫자와 공개 자료 계약."""
from copy import deepcopy
from datetime import date, timedelta
import json
import unittest

from naver_engine import reporting as R
from naver_engine.tests.test_reporting import NOW, WEEK, daily_rows
from naver_engine.tests.test_report_revisions import ReportAdapter


class ReportDetailTests(unittest.TestCase):
    def test_two_accounts_have_separate_fixed_daily_totals_and_weighted_ratios(self):
        rows = daily_rows(customers=(101, 202))
        for row in rows[7:]:
            row.update(imp=300, clk=90, spend=3000, conversions=9, conversion_value=6000)
        report = R.snapshot(WEEK, (101, 202), rows, NOW)
        self.assertEqual(report["format_version"], 2)
        self.assertEqual(report["totals"]["spend"], 28000)
        self.assertEqual(report["ratios"]["ctr"], 25)
        self.assertEqual(report["ratios"]["cvr"], 10)
        self.assertEqual(report["ratios"]["cpa"], 400)
        self.assertEqual(report["_account_reports"]["101"]["totals"]["spend"], 7000)
        self.assertEqual(report["_account_reports"]["202"]["totals"]["spend"], 21000)
        self.assertEqual(len(report["details"]["daily"]), 7)
        self.assertEqual(report["details"]["daily"][0]["totals"]["spend"], 4000)
        self.assertEqual(report["details"]["daily"][0]["status"], "ready")
        public = R.public_payload(report)
        self.assertNotIn("_account_reports", public)
        self.assertNotIn("customer_id", json.dumps(public))

    def test_previous_period_compares_complete_groups_and_percentage_points(self):
        prior = R.period("weekly", WEEK.start-timedelta(days=1))
        rows, older = daily_rows(), daily_rows(prior)
        for row in older:
            row.update(clk=5, spend=500, conversions=None, conversion_value=None, conversion_complete=False)
        report = R.snapshot(WEEK, (101,), rows, NOW, previous_customers=(101,), previous_rows=older)
        comparison = report["details"]["comparison"]
        self.assertEqual(comparison["period"], prior.as_dict())
        self.assertEqual(comparison["basic_status"], "ready")
        self.assertEqual(comparison["conversion_status"], "insufficient_data")
        self.assertEqual(comparison["changes"]["spend"],
                         {"absolute": 3500, "percent": 100.0, "unit": "currency", "status": "ready"})
        self.assertEqual(comparison["changes"]["ctr"],
                         {"absolute": 5.0, "percent": None, "unit": "percentage_points", "status": "ready"})
        self.assertIsNone(comparison["changes"]["roas"]["absolute"])
        self.assertEqual(len(comparison["daily"]), 7)
        self.assertEqual(len(report["details"]["briefing"]), 3)
        self.assertEqual(report["details"]["management_records"], [])
        self.assertEqual(report["details"]["next_actions"], [])

    def test_missing_previous_scope_is_unknown_not_a_confirmed_scope_change(self):
        report = R.snapshot(WEEK, (101,), daily_rows(), NOW)
        self.assertEqual(report["details"]["comparison"]["status"], "insufficient_data")
        rows = daily_rows()
        rows[0].update(basic_complete=False)
        report = R.snapshot(WEEK, (101,), rows, NOW)
        self.assertIn("확정하지", report["details"]["briefing"][2])

    def test_missing_days_real_zero_and_zero_comparison_denominator_stay_distinct(self):
        rows = daily_rows()
        rows.pop()
        for key in R.OUTPUT_FIELDS:
            rows[0][key] = 0
        prior = R.previous_period(WEEK)
        older = daily_rows(prior)
        report = R.snapshot(WEEK, (101,), rows, NOW, previous_customers=(101,), previous_rows=older)
        first, last = report["details"]["daily"][0], report["details"]["daily"][-1]
        self.assertEqual(first["totals"]["spend"], 0)
        self.assertIsNone(first["ratios"]["ctr"])
        self.assertEqual(first["status"], "ready")
        self.assertIsNone(last["totals"]["spend"])
        self.assertEqual(last["status"], "collecting")
        self.assertEqual(report["details"]["comparison"]["changes"]["spend"]["status"], "insufficient_data")
        for row in older:
            row["spend"] = 0
        complete = R.snapshot(WEEK, (101,), daily_rows(), NOW, previous_customers=(101,), previous_rows=older)
        change = complete["details"]["comparison"]["changes"]["spend"]
        self.assertEqual(change["absolute"], 7000)
        self.assertIsNone(change["percent"])
        self.assertEqual(change["status"], "zero_denominator")

    def test_company_scope_change_does_not_block_same_account_comparison(self):
        prior = R.previous_period(WEEK)
        report = R.snapshot(WEEK, (202, 101), daily_rows(customers=(101, 202)), NOW,
                            previous_customers=(101,), previous_rows=daily_rows(prior))
        comparison = report["details"]["comparison"]
        self.assertEqual(comparison["status"], "scope_changed")
        self.assertTrue(all(item["absolute"] is None for item in comparison["changes"].values()))
        self.assertEqual(report["_account_reports"]["101"]["details"]["comparison"]["status"], "ready")
        self.assertEqual(report["_account_reports"]["202"]["details"]["comparison"]["status"], "insufficient_data")

    def test_monthly_comparison_uses_complete_calendar_months_and_nested_private_fields_are_removed(self):
        period = R.period("monthly", date(2026, 9, 15))
        previous = R.previous_period(period)
        report = R.snapshot(period, (101,), daily_rows(period), NOW,
                            previous_customers=(101,), previous_rows=daily_rows(previous))
        self.assertEqual(previous.start, date(2026, 8, 1))
        self.assertEqual(len(report["details"]["daily"]), 30)
        self.assertEqual(len(report["details"]["comparison"]["daily"]), 31)
        self.assertEqual(report["details"]["comparison"]["status"], "ready")
        report["details"]["daily"][0]["_private_source"] = {"customer_id": 123456789}
        original = deepcopy(report)
        public = R.public_payload(report)
        self.assertEqual(report, original)
        text = json.dumps(public)
        for value in ("_private_source", "customer_id", "_source_manifest", "_expected_customers", "_account_reports"):
            self.assertNotIn(value, text)

    def test_comparison_daily_correction_changes_version_even_when_period_totals_match(self):
        prior = R.previous_period(WEEK)
        older = daily_rows(prior)
        first = R.snapshot(WEEK, (101,), daily_rows(), NOW, previous_customers=(101,), previous_rows=older)
        older[0]["spend"], older[1]["spend"] = 500, 1500
        changed = R.snapshot(WEEK, (101,), daily_rows(), NOW, previous_customers=(101,), previous_rows=older)
        self.assertEqual(first["details"]["comparison"]["totals"], changed["details"]["comparison"]["totals"])
        self.assertNotEqual(first["revision_fingerprint"], changed["revision_fingerprint"])

    def test_restored_values_have_new_source_revision_but_time_only_rechecks_keep_fingerprint(self):
        rows = daily_rows()
        for row in rows:
            row["source_revision"] = 1
        first = R.snapshot(WEEK, (101,), rows, NOW)
        rows[0].update(spend=2000, source_revision=2)
        changed = R.snapshot(WEEK, (101,), rows, NOW)
        rows[0].update(spend=1000, source_revision=3)
        restored = R.snapshot(WEEK, (101,), rows, NOW)
        self.assertEqual(restored["totals"], first["totals"])
        self.assertEqual(restored["details"]["daily"], first["details"]["daily"])
        self.assertEqual(len({report["revision_fingerprint"] for report in (first, changed, restored)}), 3)
        self.assertEqual(restored["_source_manifest"][0]["source_revision"], 3)
        later = NOW+timedelta(hours=1)
        for row in rows:
            row.update(checked_at=later.isoformat(), source_at=later.isoformat(), source_generation=later.isoformat())
        rechecked = R.snapshot(WEEK, (101,), rows, later)
        self.assertEqual(rechecked["revision_fingerprint"], restored["revision_fingerprint"])

    def test_extreme_small_comparison_denominator_never_creates_infinite_json_numbers(self):
        prior = R.previous_period(WEEK)
        older = daily_rows(prior)
        for row in older:
            row["spend"] = 1e-320
        report = R.snapshot(WEEK, (101,), daily_rows(), NOW, previous_customers=(101,), previous_rows=older)
        json.dumps(R.public_payload(report), allow_nan=False)
        self.assertIsNone(report["details"]["comparison"]["changes"]["spend"]["percent"])

    def test_briefing_uses_whole_won_display_without_changing_precise_totals(self):
        prior = R.previous_period(WEEK)
        rows, older = daily_rows(), daily_rows(prior)
        rows[0]["spend"] = 1000.75
        older[0]["spend"] = 2000.25
        report = R.snapshot(WEEK, (101,), rows, NOW, previous_customers=(101,), previous_rows=older)
        briefing = report["details"]["briefing"]
        self.assertIn("광고비 7,000원", briefing[0])
        self.assertIn("-999원", briefing[1])
        self.assertNotIn(".00원", " ".join(briefing))
        self.assertEqual(report["totals"]["spend"], 7000.75)
        self.assertEqual(report["details"]["comparison"]["changes"]["spend"]["absolute"], -999.5)


class StoredReportDetailTests(unittest.TestCase):
    def setUp(self):
        self.store = ReportAdapter()
        self.addCleanup(self.store._conn.close)

    def test_exact_snapshot_read_keeps_saved_validation_and_does_not_write(self):
        self.store.seed(WEEK.start, WEEK.end)
        self.store.generate_reports(self.store.now)
        row = next(item for item in self.store.report_snapshots() if item["period_key"] == WEEK.key)
        before = self.store._conn.total_changes
        original = self.store.report_snapshot_detail(row["report_id"])
        self.assertEqual(self.store._conn.total_changes, before)
        self.store.now += timedelta(minutes=1)
        self.store.recheck(WEEK.start, WEEK.end)
        changed = self.store.report_snapshot_detail(row["report_id"])
        self.assertEqual(changed, original)
        self.assertIsNone(self.store.report_snapshot_detail(99999))

    def test_generated_snapshot_freezes_accounts_comparison_and_source_revision(self):
        prior = R.previous_period(WEEK)
        self.store.groups[202] = 11
        for cid, amount in ((101, 1000), (202, 3000)):
            self.store.seed(prior.start, WEEK.end, cid=cid, spend=amount)
        self.store.generate_reports(self.store.now)
        row = next(item for item in self.store.report_snapshots() if item["period_key"] == WEEK.key)
        original = self.store.report_snapshot_detail(row["report_id"])
        payload = original["payload"]
        self.assertEqual(payload["format_version"], 2)
        self.assertEqual(payload["_expected_customers"], [101, 202])
        self.assertEqual(payload["_account_reports"]["202"]["totals"]["spend"], 21000)
        self.assertEqual(payload["details"]["comparison"]["totals"]["spend"], 28000)
        reference = payload["details"]["comparison"]["reference"]
        self.assertEqual(self.store.report_snapshot_detail(reference["report_id"])["period_key"], prior.key)
        self.store.now += timedelta(minutes=1)
        self.store.seed(prior.start, prior.start, cid=101, spend=8000)
        self.store.generate_reports(self.store.now)
        self.assertEqual(self.store.report_snapshot_detail(row["report_id"]), original)

    def test_one_complete_account_does_not_inherit_another_accounts_validation_gap(self):
        self.store.groups[202] = 11
        self.store.seed(WEEK.start, WEEK.end)
        self.store.generate_reports(self.store.now)
        row = next(item for item in self.store.report_snapshots() if item["period_key"] == WEEK.key)
        payload = self.store.report_snapshot_detail(row["report_id"])["payload"]
        self.assertNotEqual(payload["validation"]["status"], "complete")
        self.assertEqual(payload["_account_reports"]["101"]["validation"]["status"], "complete")
        self.assertNotEqual(payload["_account_reports"]["202"]["validation"]["status"], "complete")

    def test_account_move_keeps_daily_values_and_comparison_with_historical_company(self):
        prior = R.previous_period(WEEK)
        self.store.groups = {101: 11, 202: 11}
        self.store.seed(prior.start, WEEK.end)
        self.store.seed(prior.start, WEEK.end, cid=202, spend=3000)
        self.store.generate_reports(self.store.now)
        old = next(item for item in self.store.report_snapshots() if item["period_key"] == WEEK.key)
        self.store.groups[101] = 12
        self.store.now += timedelta(minutes=1)
        self.store.seed(prior.start, prior.start, spend=2000)
        self.store.generate_reports(self.store.now)
        historical = next(item for item in self.store.report_snapshots()
                          if item["possibility_id"] == 11 and item["period_key"] == WEEK.key)
        new_owner = next(item for item in self.store.report_snapshots()
                         if item["possibility_id"] == 12 and item["period_key"] == WEEK.key)
        account = self.store.report_snapshot_detail(historical["report_id"])["payload"]["_account_reports"]["101"]
        self.assertEqual(account["totals"]["spend"], 7000)
        self.assertEqual(account["details"]["comparison"]["totals"]["spend"], 8000)
        self.assertIsNone(new_owner["payload"]["totals"]["spend"])
        self.assertIsNone(new_owner["payload"]["details"]["comparison"]["totals"]["spend"])
        self.assertEqual(self.store.report_snapshot_detail(old["report_id"])["payload"]["totals"]["spend"], 28000)

    def test_previous_source_correction_revises_dependent_period_without_rewriting_old_copy(self):
        prior = R.previous_period(WEEK)
        self.store.seed(prior.start, WEEK.end)
        self.store.generate_reports(self.store.now)
        first = next(item for item in self.store.report_snapshots() if item["period_key"] == WEEK.key)
        old = self.store.report_snapshot_detail(first["report_id"])
        self.store.now += timedelta(minutes=1)
        self.store.seed(prior.start, prior.start, spend=8000)
        self.store.generate_reports(self.store.now)
        second = next(item for item in self.store.report_snapshots() if item["period_key"] == WEEK.key)
        self.assertGreater(second["report_id"], first["report_id"])
        self.assertEqual(second["payload"]["totals"], first["payload"]["totals"])
        self.assertEqual(second["payload"]["details"]["comparison"]["totals"]["spend"], 14000)
        self.assertTrue(second["change_summary"]["comparison_changed"])
        self.assertEqual(self.store.report_snapshot_detail(first["report_id"]), old)

    def test_old_legacy_snapshot_is_preserved_and_reconstruction_gets_a_new_version(self):
        period = R.period("monthly", date(2025, 2, 1))
        self.store.seed(period.start, period.end)
        rows = self.store.daily_performance([101], period.start, period.end, possibility_id=11)
        legacy = R.aggregate(period, (101,), rows, self.store.now)
        legacy["revision_no"] = 1
        raw = json.dumps(legacy)
        cursor = self.store._conn.execute("""INSERT INTO naver_auto_report_snapshot
            (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
            VALUES(11,?,?,?,?,?,?)""", (period.key, legacy["revision_fingerprint"], self.store.now.isoformat(),
                legacy["status"], legacy["review_status"], raw))
        old_id = cursor.lastrowid
        self.store._conn.execute("UPDATE naver_auto_report_dirty SET pending=0")
        old = self.store.report_snapshot_detail(old_id)
        self.assertEqual(old["payload"]["details"]["status"], "legacy_unavailable")
        self.assertEqual(old["payload"]["details"]["daily"], [])
        self.store.generate_reports(self.store.now)
        current = next(item for item in self.store.report_snapshots() if item["period_key"] == period.key)
        self.assertEqual(current["payload"]["format_version"], 2)
        self.assertEqual(current["payload"]["details"]["status"], "reconstructed")
        self.assertEqual(current["revision_no"], 2)
        self.assertNotEqual(current["revision_fingerprint"], legacy["revision_fingerprint"])
        self.assertEqual(self.store.report_snapshot_detail(old_id), old)
        self.assertEqual(self.store._conn.execute("SELECT payload_json FROM naver_auto_report_snapshot WHERE report_id=?",
                                                (old_id,)).fetchone()[0], raw)

    def test_legacy_without_retained_source_is_not_replaced_by_a_fictitious_reconstruction(self):
        legacy = R.aggregate(WEEK, (101,), daily_rows(), self.store.now)
        raw = json.dumps(legacy)
        cursor = self.store._conn.execute("""INSERT INTO naver_auto_report_snapshot
            (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
            VALUES(11,?,?,?,?,?,?)""", (WEEK.key, legacy["revision_fingerprint"], self.store.now.isoformat(),
                legacy["status"], legacy["review_status"], raw))
        old_id = cursor.lastrowid
        self.store.generate_reports(self.store.now)
        current = next(item for item in self.store.report_snapshots() if item["period_key"] == WEEK.key)
        self.assertEqual(current["report_id"], old_id)
        self.assertEqual(current["payload"]["details"]["status"], "legacy_unavailable")
        self.assertEqual(current["payload"]["totals"]["spend"], 7000)


if __name__ == "__main__":
    unittest.main()
