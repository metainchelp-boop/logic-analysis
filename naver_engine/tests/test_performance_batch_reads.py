"""실제 GET 관문 + 합성 HTTP로 전일 묶음 수집의 호출량과 정합성을 검증한다."""
from copy import deepcopy
from datetime import date, timedelta
import json
import socket
import unittest
from unittest.mock import patch

from naver_engine import naver_read as N, performance_reads as P
from naver_engine.tests.fake_naver import FakeClock, FakeNaver, cycle_str
from naver_engine.tests.test_performance_reads import MemoryPerformance, NOW
from naver_engine.tests.test_morning import A, creds


class BatchFixture:
    def __init__(self, count=6):
        self.clock, self.http = FakeClock(NOW), FakeNaver()
        self.store = MemoryPerformance(self.clock)
        self.store.jobs[0].update(kind="daily", cycle_day="2026-10-05",
                                  period_start="2026-10-04", period_end="2026-10-04")
        self.campaigns = [{"nccCampaignId": f"cmp-{A}-{i:04d}", "customerId": A,
                           "status": "ELIGIBLE", "userLock": False, "delFlag": False} for i in range(count)]
        self.omitted, self.rows, self.daily_rows = set(), {}, {}
        self.cycle = NOW
        self.http.route(r"/ncc/campaigns", lambda call: (200, deepcopy(self.campaigns)))
        self.http.route(r"/billing/bizmoney", lambda call: (200, {
            "customerId": int(call.customer), "bizmoney": 1000, "budgetLock": False, "refundLock": False}))
        self.http.route(r"/stats", self.stats)
        self.reader = N.NaverReader(creds(), transport=self.http, clock=self.clock)

    def stats(self, call):
        metrics = {"impCnt": 100, "clkCnt": 10, "salesAmt": 1000, "ccnt": 1, "convAmt": 2000}
        if "ids" in call.query:
            rows = [dict(id=cid, **self.rows.get(cid, metrics)) for cid in call.query["ids"] if cid not in self.omitted]
        else:
            cid = call.query["id"][0]
            span = json.loads(call.query["timeRange"][0])
            start, end = date.fromisoformat(span["since"]), date.fromisoformat(span["until"])
            rows = self.daily_rows.get(cid, [dict(dateStart=(start+timedelta(days=n)).isoformat(),
                **self.rows.get(cid, metrics)) for n in range((end-start).days+1)])
        return 200, {"cycleBaseTm": cycle_str(self.cycle) if self.cycle else None, "data": deepcopy(rows)}

    def run(self, **kwargs):
        return P.run_performance(self.reader, self.store, self.clock.now, **kwargs)

    @property
    def result(self):
        return self.store.results["weekly-test"]

    @property
    def stats_calls(self):
        return [call for call in self.http.calls if call.path == "/stats"]


class PerformanceBatchTests(unittest.TestCase):
    def setUp(self):
        network = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        network.start()
        self.addCleanup(network.stop)

    def test_six_and_25_campaigns_finish_in_four_calls_with_exact_totals(self):
        for count in (6, 25, 100):
            with self.subTest(count=count):
                f = BatchFixture(count)
                self.assertEqual(f.run().counts, {"ok": 1})
                self.assertEqual(f.reader.calls, 4)
                self.assertEqual(len(f.stats_calls), 1)
                self.assertEqual(len(f.stats_calls[0].query["ids"]), count)
                self.assertNotIn("timeIncrement", f.stats_calls[0].query)
                row = f.result["daily_rows"][0]
                self.assertEqual((row["imp"], row["spend"], row["conversion_value"]), (100*count, 1000*count, 2000*count))
                self.assertTrue(row["conversion_complete"])
                self.assertTrue(all(c.method == "GET" and c.sig_ok and c.api_key_ok for c in f.http.calls))

    def test_only_omitted_campaign_gets_daily_confirmation_and_never_assumed_zero(self):
        f = BatchFixture()
        missing = f.campaigns[2]["nccCampaignId"]
        f.omitted.add(missing)
        f.rows[missing] = dict.fromkeys(P.FIELDS, 0)
        self.assertEqual(f.run().counts, {"ok": 1})
        self.assertEqual(f.reader.calls, 5)
        self.assertEqual([c.query["id"][0] for c in f.stats_calls if "id" in c.query], [missing])
        self.assertEqual(f.result["daily_rows"][0]["spend"], 5000)
        self.assertFalse(f.result["daily_rows"][0]["conversion_complete"])
        f = BatchFixture()
        missing = f.campaigns[2]["nccCampaignId"]
        f.omitted.add(missing)
        f.daily_rows[missing] = []
        self.assertEqual(f.run().counts, {"source_wait": 1})
        self.assertNotIn("daily_rows", f.result)
        self.assertEqual(f.store.progress["weekly-test"]["next_index"], 2)

    def test_many_ids_chunk_at_100_and_resume_without_rereading_verified_ids(self):
        f = BatchFixture(601)
        self.assertEqual(f.run().counts, {"partial": 1})
        self.assertEqual(f.reader.calls, 8)
        self.assertEqual(f.store.progress["weekly-test"]["next_index"], 600)
        f.reader = N.NaverReader(creds(), transport=f.http, clock=f.clock)
        self.assertEqual(f.run().counts, {"ok": 1})
        ids = [cid for c in f.stats_calls for cid in c.query.get("ids", c.query.get("id", []))]
        self.assertEqual(len(ids), 601)
        self.assertEqual(len(set(ids)), 601)
        self.assertTrue(all(len(c.query.get("ids", [])) <= 100 for c in f.stats_calls))
        self.assertEqual(f.result["daily_rows"][0]["spend"], 601000)

    def test_batch_boundary_and_missing_middle_resume_in_new_reader(self):
        f = BatchFixture(101)
        self.assertEqual(f.run().counts, {"ok": 1})
        self.assertEqual(f.reader.calls, 5)
        self.assertEqual([len(c.query.get("ids", c.query.get("id"))) for c in f.stats_calls], [100, 1])
        f = BatchFixture(25)
        f.omitted = {row["nccCampaignId"] for index, row in enumerate(f.campaigns) if index % 3 == 1}
        self.assertEqual(f.run().counts, {"partial": 1})
        saved_index = f.store.progress["weekly-test"]["next_index"]
        self.assertEqual(saved_index, 16)
        before = len(f.stats_calls)
        f.reader = N.NaverReader(creds(), transport=f.http, clock=f.clock)
        self.assertEqual(f.run().counts, {"ok": 1})
        retried = {cid for c in f.stats_calls[before:] for cid in c.query.get("ids", c.query.get("id"))}
        self.assertFalse(retried.intersection(row["nccCampaignId"] for row in f.campaigns[:saved_index]))
        self.assertEqual(f.result["daily_rows"][0]["spend"], 25000)

    def test_multi_day_period_remains_true_daily_data(self):
        f = BatchFixture(3)
        f.store.jobs[0].update(period_start="2026-10-02", kind="weekly")
        self.assertEqual(f.run().counts, {"ok": 1})
        self.assertEqual(len(f.result["daily_rows"]), 3)
        self.assertTrue(all(c.query.get("timeIncrement") == ["1"] and "ids" not in c.query for c in f.stats_calls))

    def test_unknown_conversion_is_not_fabricated_even_when_basics_complete(self):
        f = BatchFixture()
        f.rows[f.campaigns[0]["nccCampaignId"]] = dict(impCnt=100, clkCnt=10, salesAmt=1000, ccnt=None, convAmt=None)
        self.assertEqual(f.run().counts, {"ok": 1})
        row = f.result["daily_rows"][0]
        self.assertEqual(row["spend"], 6000)
        self.assertIsNone(row["conversions"])
        self.assertIsNone(row["conversion_value"])
        self.assertFalse(row["conversion_complete"])

    def test_invalid_metric_has_distinct_reason_and_no_published_totals(self):
        for value, code in ((None, "STATS_METRIC_MISSING"), (-1, "STATS_METRIC_INVALID"),
                            ("비공개응답", "STATS_NUMERIC_INVALID")):
            with self.subTest(value_type=type(value).__name__):
                f = BatchFixture()
                f.rows[f.campaigns[0]["nccCampaignId"]] = dict(impCnt=100, clkCnt=10, salesAmt=value, ccnt=1, convAmt=2000)
                self.assertEqual(f.run().counts, {"retry": 1})
                self.assertEqual(f.result["error_code"], code)
                self.assertNotIn("daily_rows", f.result)
                self.assertNotIn("비공개응답", str(f.result))

    def test_stale_future_missing_cycle_and_old_generation_cannot_publish(self):
        for mode, status, code in (("stale", "source_wait", "SOURCE_AGGREGATING"),
                                   ("future", "retry", "STATS_CYCLE_FUTURE"),
                                   ("missing", "retry", "STATS_CYCLE_INVALID"),
                                   ("old_generation", "source_wait", "SOURCE_AGGREGATING")):
            with self.subTest(mode=mode):
                f = BatchFixture()
                if mode == "stale":
                    f.cycle = NOW-timedelta(days=2)
                elif mode == "future":
                    f.cycle = NOW+timedelta(minutes=1)
                elif mode == "missing":
                    f.cycle = None
                else:
                    f.store.jobs[0].update(generation=NOW.isoformat(), period_start="2026-10-02", period_end="2026-10-02")
                    f.cycle = NOW-timedelta(days=1)
                self.assertEqual(f.run().counts, {status: 1})
                self.assertEqual(f.result["error_code"], code)
                self.assertNotIn("daily_rows", f.result)

    def test_changed_campaigns_and_permissions_never_publish_batch(self):
        f = BatchFixture()
        f.http.script("/ncc/campaigns", (200, f.campaigns), (200, []))
        self.assertEqual(f.run().counts, {"retry": 1})
        self.assertEqual(f.result["error_code"], "CAMPAIGNS_CHANGED")
        self.assertNotIn("daily_rows", f.result)
        f = BatchFixture()
        f.http.tick = lambda call: setattr(f.store, "valid", False) if call.path == "/stats" else None
        self.assertEqual(f.run().code, "SOURCE_CHANGED")
        self.assertEqual(f.store.results, {})


if __name__ == "__main__":
    unittest.main()
