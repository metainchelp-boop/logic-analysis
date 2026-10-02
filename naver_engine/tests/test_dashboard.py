"""월간 저장 원천의 공개 집계 계약. 가상 자료만 사용하며 외부 연결 없음."""
import unittest
from datetime import datetime, timezone, timedelta

from naver_engine import dashboard as D

NOW = datetime(2026, 10, 3, 10, tzinfo=timezone(timedelta(hours=9)))


def account(cid, pid=11, mapping="matched", **collection):
    return {"customer_id": cid, "possibility_id": pid, "mapping": mapping,
            "collection": {"status": "pending", **collection}}


def monthly(imp=100, clk=10, spend=1000, conv=3000, **kw):
    return {"period_start": "2026-10-01", "period_end": "2026-10-02", "status": "ok",
            "checked_at": NOW.isoformat(), "imp": imp, "clk": clk, "spend": spend,
            "conversion_value": conv, "campaign_count": 1, "enabled_campaigns": 1, **kw}


class DashboardAggregateTest(unittest.TestCase):
    def test_month_to_yesterday_and_empty_scope_are_explicit(self):
        out = D.aggregate([], {}, NOW, ready=True)
        self.assertEqual(out["period"], {"start": "2026-10-01", "end": "2026-10-02",
                                          "days": 2, "timezone": "Asia/Seoul"})
        self.assertEqual(out["accounts"]["total"], 0)
        self.assertEqual(out["totals"]["spend"], 0)
        self.assertIsNone(out["ratios"]["roas"])

    def test_period_sums_and_company_average_do_not_count_accounts_as_companies(self):
        rows = [account(1), account(2), account(3, None, "no_erp_record")]
        out = D.aggregate(rows, {1: monthly(), 2: monthly(), 3: monthly()}, NOW, ready=True)
        self.assertEqual(out["totals"], {"impressions": 300, "clicks": 30,
                                         "spend": 3000, "conversion_value": 9000})
        self.assertEqual(out["advertisers"], {"total": 1, "complete": 1, "unknown": 0})
        self.assertEqual(out["averages"], {"advertiser_impressions": 200,
            "advertiser_clicks": 20, "advertiser_daily_spend": 1000, "daily_spend": 1500})
        self.assertEqual(out["ratios"]["roas"], 300)
        self.assertEqual(out["ratios"]["ctr"], 10)
        self.assertEqual(out["ratios"]["cpc"], 100)

    def test_missing_account_is_not_zero_and_incomplete_company_is_not_average_denominator(self):
        out = D.aggregate([account(1), account(2), account(3, 12)],
                          {1: monthly(), 3: monthly(spend=600)}, NOW, ready=True)
        self.assertEqual(out["totals"]["spend"], 1600)
        self.assertEqual(out["coverage"]["complete_accounts"], 2)
        self.assertEqual(out["coverage"]["pending_accounts"], 1)
        self.assertEqual(out["advertisers"], {"total": 2, "complete": 1, "unknown": 1})
        self.assertEqual(out["averages"]["advertiser_daily_spend"], 300)

    def test_roas_excludes_unknown_tracking_cost_and_uses_same_cohort(self):
        out = D.aggregate([account(1), account(2), account(3)],
                          {1: monthly(), 2: monthly(conv=None), 3: monthly(conv=0)}, NOW, ready=True)
        self.assertEqual(out["totals"]["spend"], 3000)
        self.assertEqual(out["ratios"]["roas"], 300)
        self.assertEqual(out["ratios"]["roas_spend"], 1000)
        self.assertEqual(out["ratios"]["roas_accounts"], 1)
        self.assertIsNone(D.aggregate([account(1)], {1: monthly(conv=0)}, NOW, ready=True)["ratios"]["roas"])

    def test_first_day_never_uses_previous_month_or_divides_by_zero(self):
        out = D.aggregate([account(1)], {1: monthly()}, NOW.replace(day=1), ready=True)
        self.assertEqual(out["period"]["days"], 0)
        self.assertEqual(out["period"]["end"], "2026-09-30")
        self.assertIsNone(out["totals"]["spend"])
        self.assertIsNone(out["averages"]["daily_spend"])

    def test_utc_clock_uses_korean_calendar(self):
        out = D.aggregate([], {}, datetime(2026, 9, 30, 16, tzinfo=timezone.utc), ready=True)
        self.assertEqual(out["period"]["start"], "2026-10-01")
        self.assertEqual(out["period"]["days"], 0)

    def test_failed_sources_wrong_period_and_stale_or_future_checks_are_unknown(self):
        for values, ready in ((monthly(), False),
                              (monthly(period_end="2026-10-01"), True),
                              (monthly(checked_at=(NOW-timedelta(days=1)).isoformat()), True),
                              (monthly(checked_at=(NOW+timedelta(seconds=1)).isoformat()), True),
                              (monthly(checked_at=NOW.replace(tzinfo=None).isoformat()), True),
                              (monthly(status="partial"), True)):
            with self.subTest(values=values, ready=ready):
                out = D.aggregate([account(1)], {1: values}, NOW, ready=ready)
                self.assertIsNone(out["totals"]["spend"])
                self.assertEqual(out["coverage"]["complete_accounts"], 0)

    def test_zero_spend_alone_does_not_mean_no_delivery(self):
        rows = [account(1, status="ok", yday_imp=20, yday_clk=0, yday_spend=0),
                account(2, status="ok", yday_imp=0, yday_clk=0, yday_spend=0),
                account(3, status="partial", yday_imp=0, yday_clk=0, yday_spend=0)]
        out = D.aggregate(rows, {1: monthly(enabled_campaigns=0), 2: monthly()}, NOW, ready=True)
        self.assertEqual(out["delivery"], {"active": 1, "inactive": 1, "unknown": 1})
        self.assertEqual(out["configuration"], {"enabled": 1, "disabled": 1, "unknown": 1})

    def test_out_of_scope_stored_metrics_and_ids_never_escape(self):
        out = D.aggregate([account(1)], {1: monthly(), 987654321: monthly(spend=999999)}, NOW, ready=True)
        self.assertEqual(out["totals"]["spend"], 1000)
        self.assertNotIn("customer_id", str(out))
        self.assertNotIn("987654321", str(out))

    def test_invalid_numbers_and_overflow_never_become_trusted_totals(self):
        for value in (True, -1, float("nan"), float("inf"), 10 ** 1000):
            with self.subTest(value=value):
                out = D.aggregate([account(1)], {1: monthly(spend=value)}, NOW, ready=True)
                self.assertIsNone(out["totals"]["spend"])
        out = D.aggregate([account(1), account(2)],
                          {1: monthly(spend=D.MAX_NUMBER), 2: monthly(spend=1)}, NOW, ready=True)
        self.assertIsNone(out["totals"]["spend"])
