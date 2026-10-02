"""독립 검토용 집계 조합 시험. 공개 aggregate 경로, 합성 원천, 외부 호출 없음."""
from datetime import datetime, timedelta, timezone
from itertools import product
import unittest

from naver_engine import dashboard

NOW = datetime(2026, 10, 3, 10, tzinfo=timezone(timedelta(hours=9)))


class IndependentDashboardAggregateTest(unittest.TestCase):
    def test_complete_population_company_denominators_and_conversion_unknown_matrix(self):
        rows = [{"customer_id": cid, "possibility_id": pid, "mapping": "matched",
                 "collection": {"status": "pending"}}
                for cid, pid in ((1, 11), (2, 11), (3, 12))]
        amounts = {1: 100, 2: 200, 3: 300}
        for states in product(("ok", "partial", "missing"), repeat=3):
            for conversion in (None, 0, 1000):
                with self.subTest(states=states, conversion=conversion):
                    checks = {cid: {"period_start": "2026-10-01", "period_end": "2026-10-02",
                                    "status": status, "checked_at": NOW.isoformat(),
                                    "imp": amounts[cid], "clk": cid, "spend": amounts[cid],
                                    "conversion_value": conversion}
                              for cid, status in enumerate(states, start=1) if status != "missing"}
                    out = dashboard.aggregate(rows, checks, NOW, ready=True)
                    complete = {cid for cid, status in enumerate(states, start=1) if status == "ok"}
                    sum_spend = sum(amounts[cid] for cid in complete) if complete else None
                    complete_companies = [group for group in ({1, 2}, {3}) if group <= complete]
                    average_spend = (sum(amounts[cid] for group in complete_companies for cid in group)
                                     / len(complete_companies) / 2) if complete_companies else None
                    self.assertEqual(out["coverage"]["complete_accounts"], len(complete))
                    self.assertEqual(out["totals"]["spend"], sum_spend)
                    self.assertEqual(out["advertisers"]["complete"], len(complete_companies))
                    self.assertEqual(out["averages"]["advertiser_daily_spend"], average_spend)
                    if conversion and complete:
                        self.assertEqual(out["ratios"]["roas_accounts"], len(complete))
                        self.assertEqual(out["ratios"]["roas_spend"], sum_spend)
                        self.assertAlmostEqual(out["ratios"]["roas"],
                                               conversion * len(complete) / sum_spend * 100)
                    else:
                        self.assertEqual(out["ratios"]["roas_accounts"], 0)
                        self.assertIsNone(out["ratios"]["roas"])


if __name__ == "__main__":
    unittest.main()
