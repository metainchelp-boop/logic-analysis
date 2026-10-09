"""불변 보고서판에서만 계산하는 공개 성과 지표의 행동 계약."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import unittest

from naver_engine import reporting as R
from naver_engine import report_enrichment as E


NOW = datetime(2026, 10, 5, 10, tzinfo=R.KST)
WEEK = R.period("weekly", date(2026, 9, 28))


def rows(target=WEEK, customers=(101,), **values):
    result = []
    for cid in customers:
        for offset in range(target.as_dict()["days"]):
            result.append({"customer_id": cid, "day": str(target.start+timedelta(days=offset)),
                           "basic_complete": True, "conversion_complete": True,
                           "imp": 100, "clk": 10, "spend": 1000, "conversions": 2,
                           "conversion_value": 4000, "checked_at": NOW.isoformat(), **values})
    return result


def snapshot(current=None, previous=None, customers=(101,), previous_customers=(101,), target=WEEK):
    return R.snapshot(target, customers, rows(target, customers) if current is None else current, NOW,
                      previous_customers=previous_customers,
                      previous_rows=rows(R.previous_period(target), previous_customers) if previous is None else previous)


def metrics(report):
    return {item["key"]: item for item in E.enrich(report)["metrics"]}


def old_snapshot(value):
    if isinstance(value, dict):
        return {key: old_snapshot(item) for key, item in value.items()
                if key not in ("roas_clicks", "roas_conversions")}
    if isinstance(value, list):
        return [old_snapshot(item) for item in value]
    return value


class ReportEnrichmentTests(unittest.TestCase):
    def test_complete_snapshot_exposes_seventeen_metrics_without_changing_saved_values(self):
        report = snapshot()
        original = deepcopy(report)
        result = E.enrich(report)
        self.assertEqual(report, original)
        values = {item["key"]: item for item in result["metrics"]}
        self.assertEqual(len(values), 17)
        for key, expected in {"spend": 7000, "conversion_value": 28000, "conversions": 14,
                              "roas": 400, "cpa": 500, "cvr": 20, "impressions": 700,
                              "clicks": 70, "ctr": 10, "cpc": 100, "cpm": 10000,
                              "value_per_conversion": 2000, "spend_per_day": 1000,
                              "clicks_per_day": 10, "impressions_per_day": 100,
                              "conversions_per_day": 2, "value_per_day": 4000}.items():
            self.assertEqual(values[key]["current"], expected, key)
            self.assertEqual(values[key]["absolute"], 0, key)
            self.assertEqual(values[key]["status"], "ready", key)
        self.assertEqual(result["quality"]["expected_account_days"], 7)
        self.assertEqual(result["quality"]["paired"]["percent"], 100)
        json.dumps(result, allow_nan=False)

    def test_partial_new_snapshot_keeps_efficiency_on_the_same_account_days(self):
        current = rows(customers=(101, 202))
        current[0].update(conversion_complete=False, conversion_value=900000, conversions=999)
        current[-1].update(basic_complete=False, spend=800000, clk=10000)
        report = snapshot(current=current, customers=(101, 202), previous_customers=(101, 202))
        values = metrics(report)
        self.assertEqual(report["ratios"]["roas_clicks"], 120)
        self.assertEqual(report["ratios"]["roas_conversions"], 24)
        self.assertEqual(values["cpa"]["current"], 500)
        self.assertEqual(values["cvr"]["current"], 20)
        self.assertEqual(values["value_per_conversion"]["current"], 2000)
        self.assertEqual(values["cpa"]["scope"]["account_days"], 12)
        self.assertEqual(values["cpa"]["value_status"], "partial")
        self.assertEqual(values["cpa"]["status"], "insufficient_data")
        self.assertIsNone(values["spend_per_day"]["current"])
        self.assertEqual(E.enrich(report)["quality"]["missing_account_days"], 2)

    def test_old_partial_snapshot_recovers_paired_values_only_from_its_own_complete_account_days(self):
        current = rows(customers=(101, 202))
        current[0].update(conversion_complete=False, conversions=None, conversion_value=None)
        current[-1].update(basic_complete=False, spend=999999, clk=99999)
        report = old_snapshot(snapshot(current=current, customers=(101, 202), previous_customers=(101, 202)))
        original = deepcopy(report)
        self.assertEqual(metrics(report)["value_per_conversion"]["current"], 2000)
        self.assertEqual(metrics(report["_account_reports"]["101"])["cvr"]["current"], 20)
        self.assertEqual(report, original)
        public_partial = R.public_payload(report)
        self.assertIsNone(metrics(public_partial)["value_per_conversion"]["current"])
        self.assertEqual(metrics(public_partial)["value_per_conversion"]["value_status"], "legacy_unavailable")
        report["_account_reports"]["101"]["period_key"] = "different_saved_period"
        self.assertIsNone(metrics(report)["value_per_conversion"]["current"])

    def test_zero_missing_relative_percent_and_percentage_points_are_different_states(self):
        current, prior = rows(), rows(R.previous_period(WEEK))
        for item in current:
            item.update(clk=20, conversions=0, conversion_value=0)
        for item in prior:
            item.update(spend=0)
        report = snapshot(current=current, previous=prior)
        values = metrics(report)
        self.assertEqual(values["ctr"]["absolute"], 10)
        self.assertEqual(values["ctr"]["percent"], 100)
        self.assertTrue(values["ctr"]["percentage_points"])
        self.assertEqual(values["spend"]["absolute"], 7000)
        self.assertIsNone(values["spend"]["percent"])
        self.assertEqual(values["spend"]["status"], "zero_denominator")
        self.assertEqual(values["conversions"]["current"], 0)
        self.assertEqual(values["conversions"]["absolute"], -14)
        self.assertIsNone(values["cpa"]["current"])
        self.assertEqual(values["cpa"]["value_status"], "zero_denominator")
        empty = metrics(snapshot(current=[], previous=[], previous_customers=()))
        self.assertIsNone(empty["conversions"]["current"])
        self.assertEqual(empty["conversions"]["status"], "no_previous")
        json.dumps(E.enrich(report), allow_nan=False)

    def test_month_length_and_scope_changes_are_explained_without_unsupported_cause_claims(self):
        target = R.period("monthly", date(2026, 3, 15))
        report = snapshot(target=target)
        result = E.enrich(report)
        values = {item["key"]: item for item in result["metrics"]}
        self.assertEqual(values["spend"]["absolute"], 3000)
        self.assertEqual(values["spend_per_day"]["absolute"], 0)
        self.assertTrue(any("31일" in text and "28일" in text for text in result["period_caveats"]))
        self.assertTrue(result["feedback"]["facts"])
        self.assertTrue(all(item["evidence"]["period_key"] == report["period_key"]
                            for item in result["feedback"]["facts"]))
        changed = E.enrich(snapshot(customers=(101, 202)))
        self.assertTrue(all(item["status"] == "scope_changed" and item["absolute"] is None
                            for item in changed["metrics"]))
        self.assertTrue(any("범위" in item["text"] for item in changed["feedback"]["actions"]))
        for hypothesis in changed["feedback"]["hypotheses"]:
            self.assertTrue(hypothesis["alternative"])
            self.assertTrue(hypothesis["required_evidence"])
            self.assertTrue(hypothesis["verification"])

    def test_account_contribution_uses_same_saved_period_and_complete_group_denominators(self):
        report = snapshot(customers=(101, 202), previous_customers=(101, 202))
        account = report["_account_reports"]["101"]
        original = deepcopy(report)
        contribution = E.contribution(report, account)
        self.assertEqual(contribution["shares"]["spend"], 50)
        self.assertEqual(contribution["shares"]["conversions"], 50)
        self.assertEqual(contribution["metrics"][0]["current"], 7000)
        self.assertEqual(report, original)
        foreign = snapshot(customers=(303,), previous_customers=(303,))["_account_reports"]["303"]
        self.assertTrue(all(value is None for value in E.contribution(report, foreign)["shares"].values()))
        incomplete = rows(customers=(101, 202))
        incomplete[-1].update(conversion_complete=False)
        partial = snapshot(current=incomplete, customers=(101, 202), previous_customers=(101, 202))
        contribution = E.contribution(partial, partial["_account_reports"]["101"])
        self.assertEqual(contribution["shares"]["spend"], 50)
        self.assertIsNone(contribution["shares"]["conversions"])
        self.assertIsNone(contribution["shares"]["conversion_value"])
        json.dumps(contribution, allow_nan=False)
        self.assertNotIn("_expected_customers", json.dumps(contribution))

    def test_not_due_period_and_conversion_gap_do_not_gain_comparison_from_numeric_totals(self):
        early = NOW-timedelta(hours=1)
        current, prior = rows(), rows(R.previous_period(WEEK))
        for item in current+prior:
            item["checked_at"] = early.isoformat()
        open_report = R.snapshot(WEEK, (101,), current, early,
                                 previous_customers=(101,), previous_rows=prior)
        self.assertTrue(open_report["coverage"]["basic_complete"])
        self.assertTrue(all(item["absolute"] is None for item in E.enrich(open_report)["metrics"]))
        current = rows()
        current[-1].update(conversion_complete=False, conversions=None, conversion_value=None)
        values = metrics(snapshot(current=current))
        self.assertEqual(values["spend"]["status"], "ready")
        self.assertEqual(values["conversions"]["status"], "insufficient_data")
        self.assertEqual(values["cvr"]["status"], "insufficient_data")
        self.assertIsNone(values["conversions_per_day"]["current"])

    def test_quality_keeps_total_missing_count_separate_from_truncated_reason_sample(self):
        report = snapshot(current=[], customers=tuple(range(101, 122)), previous_customers=())
        report.update(missing=report["missing"][:100], missing_count=147, missing_truncated=True)
        quality = E.enrich(report)["quality"]
        self.assertEqual(quality["expected_account_days"], 147)
        self.assertEqual(quality["missing_account_days"], 147)
        self.assertEqual(quality["missing_count"], 147)
        self.assertEqual(quality["missing_reasons"]["day_missing"], 100)
        self.assertFalse(quality["missing_reasons_complete"])
        self.assertEqual(quality["missing_reasons_observed_count"], 100)
        self.assertEqual(quality["validation_status"], "unknown")

    def test_new_snapshot_briefing_names_conversion_value_without_claiming_payment_revenue(self):
        report = snapshot()
        briefing = " ".join(report["details"]["briefing"])
        self.assertIn("광고 전환가치", briefing)
        self.assertIn("실제 주문·결제 매출과 별도", briefing)
        self.assertNotIn("전환매출", briefing)

    def test_extreme_ratio_is_not_infinite_or_mislabeled_as_an_unretained_old_metric(self):
        current = rows(conversions=1e-320)
        report = snapshot(current=current)
        values = metrics(report)
        self.assertIsNone(values["value_per_conversion"]["current"])
        self.assertEqual(values["value_per_conversion"]["value_status"], "unavailable")
        json.dumps(E.enrich(report), allow_nan=False)


if __name__ == "__main__":
    unittest.main()
