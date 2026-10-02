"""월간 원천: 실제 읽기 관문과 합성 HTTP. 운영 송신·SQLite 잠금 우회 없음."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import socket
import unittest
from unittest.mock import patch

from naver_engine import monthly_reads as M, store as S, naver_read as N
from naver_engine.tests.fake_naver import FakeClock, FakeNaver, cycle_str
from naver_engine.tests.test_morning import A, creds

NOW = datetime(2026, 10, 15, 9, tzinfo=S.KST)


class MemoryMonthly:
    def __init__(self, clock):
        self.clock, self.valid = clock, True
        self.snapshot = clock.now()
        self.progress, self.results = {}, {}

    def inventory_snapshot(self, now):
        return self.snapshot if self.valid else None

    def inventory_account_valid(self, cid, snapshot, now):
        return self.valid and cid == A and snapshot == self.snapshot

    def monthly_work(self, now, limit, **kwargs):
        return [A][:limit]

    def begin_monthly_check(self, cid, snapshot, now):
        if not self.inventory_account_valid(cid, snapshot, now):
            raise S.StoreRefused("시험 원천 변경")

    def monthly_progress(self, cid, start, end):
        value = deepcopy(self.progress.get((cid, start, end)))
        if value is not None:
            M.validate_progress(value, cid, start, end)
        return value

    def record_monthly_progress(self, cid, snapshot, now, source):
        self.begin_monthly_check(cid, snapshot, now)
        start, end = M.window(now.astimezone(S.KST).date())
        M.validate_progress(source, cid, start, end)
        self.progress[cid, start, end] = deepcopy(source)

    def record_monthly_check(self, cid, snapshot, now, values):
        self.begin_monthly_check(cid, snapshot, now)
        self.results[cid] = deepcopy(values)
        return values["status"]


class MonthlyReadsTest(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.clock, self.http = FakeClock(NOW), FakeNaver()
        self.store = MemoryMonthly(self.clock)
        self.reader = N.NaverReader(creds(), transport=self.http, clock=self.clock)
        self.campaigns = [{"nccCampaignId": f"cmp-{A}-1", "customerId": A,
                           "status": "ELIGIBLE", "userLock": False, "delFlag": False}]
        self.http.route(r"/ncc/campaigns", lambda call: (200, deepcopy(self.campaigns)))

    def summary(self, conversion=None):
        self.http.route(r"/stats", lambda call: (200, {"cycleBaseTm": cycle_str(NOW), "data": [
            {"id": self.campaigns[0]["nccCampaignId"], "impCnt": 140, "clkCnt": 14,
             "salesAmt": 1400, "convAmt": conversion}]}))

    def test_month_to_yesterday_requests_revenue_but_missing_revenue_keeps_core_metrics(self):
        self.summary()
        result = M.run_monthly(self.reader, self.store, self.clock.now)
        self.assertEqual(result.counts, {"ok": 1})
        row = self.store.results[A]
        self.assertEqual((row["imp"], row["clk"], row["spend"], row["conversion_value"]), (140, 14, 1400, None))
        stat = next(c for c in self.http.calls if c.path == "/stats")
        self.assertEqual(json.loads(stat.query["fields"][0]), ["impCnt", "clkCnt", "salesAmt", "convAmt"])
        self.assertEqual(json.loads(stat.query["timeRange"][0]), {"since": "2026-10-01", "until": "2026-10-14"})
        self.assertEqual((row["campaign_count"], row["enabled_campaigns"]), (1, 1))

    def test_missing_summary_needs_every_month_day_zero_and_does_not_invent_revenue(self):
        start, end = M.window(NOW.date())
        daily = [{"dateStart": (start + timedelta(days=n)).isoformat(), "impCnt": 0, "clkCnt": 0,
                  "salesAmt": 0, "convAmt": None} for n in range((end-start).days + 1)]
        self.http.route(r"/stats", lambda call: (200, {"cycleBaseTm": cycle_str(NOW),
            "data": daily if "timeIncrement" in call.query else []}))
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        self.assertEqual(self.store.results[A]["spend"], 0)
        self.assertIsNone(self.store.results[A]["conversion_value"])

    def test_first_of_month_is_empty_not_previous_month_or_zero(self):
        self.clock.advance((NOW.replace(day=1)-NOW).total_seconds())
        result = M.run_monthly(self.reader, self.store, self.clock.now)
        self.assertEqual(result.code, "EMPTY_PERIOD")
        self.assertEqual(self.http.calls, [])

    def test_explicit_revenue_zero_and_positive_are_preserved_without_tracking_claim(self):
        for value in (0, 2800, 28.5):
            with self.subTest(value=value):
                self.setUp()
                self.summary(value)
                self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"ok": 1})
                self.assertEqual(self.store.results[A]["conversion_value"], value)

    def test_unknown_campaign_state_does_not_mean_inactive(self):
        self.summary()
        del self.campaigns[0]["userLock"]
        M.run_monthly(self.reader, self.store, self.clock.now)
        self.assertIsNone(self.store.results[A]["campaign_count"])
        self.assertIsNone(self.store.results[A]["enabled_campaigns"])

    def test_unrecognized_provider_status_is_unknown_not_inactive(self):
        self.summary()
        self.campaigns[0]["status"] = "NEW_PROVIDER_STATE"
        M.run_monthly(self.reader, self.store, self.clock.now)
        self.assertIsNone(self.store.results[A]["campaign_count"])
        self.assertIsNone(self.store.results[A]["enabled_campaigns"])

    def test_oversized_checkpoint_integer_fails_closed_without_overflow(self):
        self.summary()
        M.run_monthly(self.reader, self.store, self.clock.now)
        start, end = M.window(NOW.date())
        self.store.progress[A, start, end]["batches"][0]["impCnt"] = 10 ** 400
        before = self.reader.calls
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"limited": 1})
        self.assertEqual(self.reader.calls, before)

    def test_empty_campaigns_have_zero_basic_metrics_but_unknown_conversion(self):
        self.campaigns = []
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        row = self.store.results[A]
        self.assertEqual((row["imp"], row["clk"], row["spend"], row["campaign_count"]), (0, 0, 0, 0))
        self.assertIsNone(row["conversion_value"])
        self.assertEqual(len(self.http.calls), 2)

    def test_missing_basic_metric_is_not_replaced_with_zero(self):
        self.http.route(r"/stats", lambda call: (200, {"cycleBaseTm": cycle_str(NOW), "data": [
            {"id": self.campaigns[0]["nccCampaignId"], "impCnt": None, "clkCnt": 0, "salesAmt": 0}]}))
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"retry": 1})
        self.assertNotIn("spend", self.store.results[A])

    def test_stale_cycle_and_missing_day_do_not_prove_zero(self):
        for cycle, days in ((None, []), (cycle_str(NOW-timedelta(days=1)), []), (cycle_str(NOW), [])):
            with self.subTest(cycle=cycle):
                self.setUp()
                self.http.route(r"/stats", lambda call: (200, {"cycleBaseTm": cycle, "data": days}))
                self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"retry": 1})
                self.assertNotIn("spend", self.store.results[A])

    def test_changed_campaign_list_does_not_publish_partial_totals(self):
        self.summary(2800)
        self.http.script("/ncc/campaigns", (200, deepcopy(self.campaigns)), (200, []))
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"retry": 1})
        self.assertNotIn("spend", self.store.results[A])

    def test_tampered_checkpoint_is_rejected_before_any_http(self):
        self.summary()
        M.run_monthly(self.reader, self.store, self.clock.now)
        start, end = M.window(NOW.date())
        self.store.progress[A, start, end]["fingerprint"] = "forged"
        before = len(self.http.calls)
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"limited": 1})
        self.assertEqual(len(self.http.calls), before)

    def test_budget_is_real_http_budget_and_partial_never_publishes_totals(self):
        self.summary()
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now, max_calls=2).counts, {"partial": 1})
        self.assertEqual(len(self.http.calls), 2)
        self.assertNotIn("spend", self.store.results[A])
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        self.assertEqual(self.store.results[A]["spend"], 1400)

    def test_many_zero_proofs_resume_without_duplicate_daily_calls(self):
        self.campaigns = [dict(self.campaigns[0], nccCampaignId=f"cmp-{A}-{i}") for i in range(12)]
        start, end = M.window(NOW.date())
        daily = [{"dateStart": (start+timedelta(days=n)).isoformat(), **dict.fromkeys(M.FIELDS, 0)}
                 for n in range((end-start).days+1)]
        self.http.route(r"/stats", lambda call: (200, {"cycleBaseTm": cycle_str(NOW),
            "data": daily if "timeIncrement" in call.query else []}))
        for expected in ("partial", "partial", "ok"):
            before = self.reader.calls
            self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).counts, {expected: 1})
            self.assertLessEqual(self.reader.calls-before, 8)
        requests = [c.query["id"][0] for c in self.http.calls if "timeIncrement" in c.query]
        self.assertEqual(len(requests), len(set(requests)))
        self.assertEqual(len(requests), 12)

    def test_current_authority_is_checked_again_before_each_request(self):
        self.summary()
        self.http.tick = lambda call: setattr(self.store, "valid", False)
        self.assertEqual(M.run_monthly(self.reader, self.store, self.clock.now).code, "SOURCE_CHANGED")
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(self.store.results, {})


if __name__ == "__main__":
    unittest.main()
