"""일별 성과 수집: 실제 GET 관문, 합성 HTTP, 메모리 저장소만 사용한다."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import socket
import unittest
from unittest.mock import patch

from naver_engine import performance_reads as P, naver_read as N, store as S
from naver_engine.tests.fake_naver import FakeClock, FakeNaver, cycle_str
from naver_engine.tests.test_morning import A, B, creds


NOW = datetime(2026, 10, 5, 9, tzinfo=S.KST)


class MemoryPerformance:
    def __init__(self, clock):
        self.clock, self.valid = clock, True
        self.jobs = [{"customer_id": A, "kind": "weekly", "cycle_day": "2026-10-04",
                      "period_start": "2026-09-27", "period_end": "2026-10-03",
                      "snapshot_at": clock.now(), "job_key": "weekly-test"}]
        self.progress, self.results = {}, {}

    def performance_work(self, now, limit):
        return deepcopy(self.jobs[:limit])

    def inventory_snapshot(self, now):
        return self.clock.now() if self.valid else None

    def performance_account_valid(self, job, now):
        return self.valid and job in self.jobs

    def begin_performance_check(self, job, now):
        if not self.performance_account_valid(job, now):
            raise S.StoreRefused("시험 권한 변경")

    def performance_progress(self, job):
        return deepcopy(self.progress.get(job["job_key"]))

    def record_performance_progress(self, job, now, progress):
        self.begin_performance_check(job, now)
        self.progress[job["job_key"]] = deepcopy(progress)

    def record_performance_check(self, job, now, values):
        self.begin_performance_check(job, now)
        self.results[job["job_key"]] = deepcopy(values)
        return values["status"]


class PerformanceReadsTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.clock, self.http = FakeClock(NOW), FakeNaver()
        self.store = MemoryPerformance(self.clock)
        self.reader = N.NaverReader(creds(), transport=self.http, clock=self.clock)
        self.campaigns = [{"nccCampaignId": f"cmp-{A}-1", "customerId": A, "status": "ELIGIBLE",
                           "userLock": False, "delFlag": False}]
        self.http.route(r"/ncc/campaigns", lambda call: (200, deepcopy(self.campaigns)))
        self.http.route(r"/billing/bizmoney", lambda call: (200, {"customerId": int(call.customer),
                        "bizmoney": 1000.5, "budgetLock": False, "refundLock": False}))
        self.days, self.cycle = {}, NOW
        self.http.route(r"/stats", self.stats)

    def stats(self, call):
        span = json.loads(call.query["timeRange"][0])
        start, end = date.fromisoformat(span["since"]), date.fromisoformat(span["until"])
        rows = [{"dateStart": (start+timedelta(days=n)).isoformat(), "impCnt": 100, "clkCnt": 10,
                 "salesAmt": 1000, "ccnt": 1, "convAmt": 2000} for n in range((end-start).days+1)]
        return 200, {"cycleBaseTm": cycle_str(self.cycle) if self.cycle else None,
                     "data": deepcopy(self.days.get(call.query["id"][0], rows))}

    def rows(self, *, imp=100, conversions=1, value=2000):
        job = self.store.jobs[0]
        start, end = date.fromisoformat(job["period_start"]), date.fromisoformat(job["period_end"])
        return [{"dateStart": (start+timedelta(days=n)).isoformat(), "impCnt": imp, "clkCnt": 10,
                 "salesAmt": 1000, "ccnt": conversions, "convAmt": value} for n in range((end-start).days+1)]

    def test_weekly_job_reads_every_closed_day_and_preserves_conversion_and_balance_time(self):
        result = P.run_performance(self.reader, self.store, self.clock.now)
        self.assertEqual(result.counts, {"ok": 1})
        out = self.store.results["weekly-test"]
        self.assertEqual(len(out["daily_rows"]), 7)
        self.assertEqual(out["daily_rows"][0], {
            "customer_id": A, "day": "2026-09-27", "basic_complete": True, "conversion_complete": True,
            "imp": 100, "clk": 10, "spend": 1000, "conversions": 1, "conversion_value": 2000,
            "checked_at": self.clock.now().isoformat(), "source_at": NOW.isoformat()})
        self.assertEqual(out["bizmoney"], 1000.5)
        self.assertGreater(datetime.fromisoformat(out["bizmoney_at"]), NOW)
        self.assertLess(datetime.fromisoformat(out["bizmoney_at"]), self.clock.now())
        stats = [call for call in self.http.calls if call.path == "/stats"]
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0].query["timeIncrement"], ["1"])
        self.assertEqual(json.loads(stats[0].query["fields"][0]), ["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"])
        self.assertEqual(len(self.http.calls), 4)

    def test_missing_dates_metrics_stale_and_future_sources_never_become_zero_success(self):
        for mode in ("missing_day", "missing_metric", "stale", "unknown_cycle", "future"):
            with self.subTest(mode=mode):
                self.store.progress.clear()
                rows = self.rows()
                if mode == "missing_day":
                    rows.pop()
                if mode == "missing_metric":
                    rows[0]["salesAmt"] = None
                self.cycle = NOW if mode not in ("stale", "unknown_cycle", "future") else {
                    "stale": NOW-timedelta(days=2), "unknown_cycle": None,
                    "future": NOW+timedelta(minutes=1)}[mode]
                self.days[self.campaigns[0]["nccCampaignId"]] = rows
                result = P.run_performance(self.reader, self.store, self.clock.now)
                self.assertEqual(result.counts, {"source_wait" if mode in ("missing_day", "stale") else "retry": 1})
                self.assertNotIn("daily_rows", self.store.results["weekly-test"])
                self.assertEqual(self.store.progress["weekly-test"]["next_index"], 0)

    def test_conversion_unknown_and_explicit_zero_preserve_basic_metrics_without_tracking_claim(self):
        for conversions, value, tracking, complete in ((None, None, False, False), (0, 0, False, False),
                                                       (0, 0, True, True), (0, 2000.5, False, True)):
            with self.subTest(conversions=conversions, value=value, tracking=tracking):
                self.store.progress.clear()
                self.store.jobs[0]["conversion_tracking_confirmed"] = tracking
                self.days[self.campaigns[0]["nccCampaignId"]] = self.rows(conversions=conversions, value=value)
                self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"ok": 1})
                row = self.store.results["weekly-test"]["daily_rows"][0]
                self.assertTrue(row["basic_complete"])
                self.assertEqual((row["conversions"], row["conversion_value"]), (conversions, value))
                self.assertEqual(row["conversion_complete"], complete)

    def test_many_campaigns_resume_with_no_repeated_daily_calls_and_real_account_cap(self):
        self.campaigns = [dict(self.campaigns[0], nccCampaignId=f"cmp-{A}-{i}") for i in range(12)]
        for expected in ("partial", "partial", "ok"):
            before = self.reader.calls
            result = P.run_performance(self.reader, self.store, self.clock.now)
            self.assertEqual(result.counts, {expected: 1})
            self.assertLessEqual(self.reader.calls-before, 8)
            if expected != "ok":
                self.assertNotIn("daily_rows", self.store.results["weekly-test"])
        requests = [call.query["id"][0] for call in self.http.calls if call.path == "/stats"]
        self.assertEqual(len(requests), len(set(requests)))
        self.assertEqual(len(requests), 12)
        self.assertEqual(self.store.results["weekly-test"]["daily_rows"][0]["spend"], 12000)
        self.assertEqual(self.store.progress["weekly-test"]["next_index"], 12)

    def test_failed_campaign_resumes_without_repeating_prior_verified_campaign(self):
        self.campaigns = [dict(self.campaigns[0], nccCampaignId=f"cmp-{A}-{i}") for i in range(3)]
        self.days[f"cmp-{A}-1"] = []
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"source_wait": 1})
        self.assertEqual(self.store.progress["weekly-test"]["next_index"], 1)
        self.days.clear()
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        requests = [call.query["id"][0] for call in self.http.calls if call.path == "/stats"]
        self.assertEqual(requests.count(f"cmp-{A}-0"), 1)
        self.assertEqual(requests.count(f"cmp-{A}-1"), 2)
        self.assertEqual(self.store.results["weekly-test"]["daily_rows"][0]["imp"], 300)

    def test_calendar_job_range_includes_month_end_leap_day_and_single_yesterday(self):
        for start, end, days in (("2024-02-01", "2024-02-29", 29), ("2025-12-01", "2025-12-31", 31),
                                 ("2026-10-04", "2026-10-04", 1)):
            with self.subTest(start=start, end=end):
                self.store.progress.clear()
                self.store.jobs[0].update(period_start=start, period_end=end, kind="backfill")
                self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"ok": 1})
                rows = self.store.results["weekly-test"]["daily_rows"]
                self.assertEqual((len(rows), rows[0]["day"], rows[-1]["day"]), (days, start, end))

    def test_empty_campaigns_have_zero_basics_but_no_conversion_tracking_evidence(self):
        self.campaigns = []
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        row = self.store.results["weekly-test"]["daily_rows"][0]
        self.assertEqual((row["imp"], row["clk"], row["spend"]), (0, 0, 0))
        self.assertTrue(row["basic_complete"])
        self.assertIsNone(row["conversions"])
        self.assertIsNone(row["conversion_value"])
        self.assertFalse(row["conversion_complete"])
        self.assertEqual(len(self.http.calls), 3)

    def test_changed_final_campaign_list_never_publishes_partial_totals(self):
        self.http.script("/ncc/campaigns", (200, deepcopy(self.campaigns)), (200, []))
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"retry": 1})
        self.assertEqual(self.store.results["weekly-test"]["error_code"], "CAMPAIGNS_CHANGED")
        self.assertNotIn("daily_rows", self.store.results["weekly-test"])

    def test_invalid_initial_source_is_not_ready_without_any_call(self):
        self.store.valid = False
        self.assertEqual(P.run_performance(self.reader,self.store,self.clock.now).code,"NOT_READY")
        self.assertEqual(self.http.calls,[])
        self.assertEqual(self.store.results,{})

    def test_authority_recheck_and_429_stop_before_starting_another_account(self):
        self.http.tick = lambda call: setattr(self.store, "valid", False)
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).code, "SOURCE_CHANGED")
        self.assertEqual(len(self.http.calls), 1)
        self.assertEqual(self.store.results, {})
        self.http.tick = None
        self.store.valid = True
        self.store.jobs.append(dict(self.store.jobs[0], customer_id=B, job_key="other-account"))
        self.http.script("/ncc/campaigns", (429, {"code": 1016}))
        before = len(self.http.calls)
        result = P.run_performance(self.reader, self.store, self.clock.now, max_seconds=1)
        self.assertEqual(result.code, "BUDGET")
        self.assertEqual(len(self.http.calls)-before, 1)
        self.assertNotIn("other-account", self.store.results)
        before = len(self.http.calls)
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).code, "BUDGET")
        self.assertEqual(len(self.http.calls), before)

    def test_transport_deadline_and_global_24_call_budget_are_enforced(self):
        self.http.tick = lambda call: self.clock.advance(2)
        result = P.run_performance(self.reader, self.store, self.clock.now, max_seconds=1)
        self.assertEqual(result.counts, {"retry": 1})
        self.assertEqual(len(self.http.calls), 1)
        self.assertNotIn("daily_rows", self.store.results["weekly-test"])
        self.http.tick = None
        self.store.jobs = [dict(self.store.jobs[0], job_key=f"job-{n}", customer_id=A+n) for n in range(10)]
        self.http.routes[0] = (self.http.routes[0][0], lambda call:
            (200, [dict(self.campaigns[0], customerId=int(call.customer))]))
        before = self.reader.calls
        result = P.run_performance(self.reader, self.store, self.clock.now)
        self.assertEqual(result.code, "BUDGET")
        self.assertEqual(result.counts, {"ok": 6})
        self.assertEqual(self.reader.calls-before, 24)

    def test_tampered_checkpoint_is_rejected_before_any_http_or_private_error_text(self):
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        good = deepcopy(self.store.progress["weekly-test"])
        variants = []
        for key, value in (("fingerprint", "비공개위조"), ("customer_id", B), ("next_index", True),
                           ("cycles", [(NOW+timedelta(days=1)).isoformat()]), ("conversion_evidence", "비공개위조")):
            source = deepcopy(good)
            source[key] = value
            variants.append(source)
        source = deepcopy(good)
        source["day_totals"]["2026-09-27"]["salesAmt"] = 10 ** 400
        variants.append(source)
        source = deepcopy(good)
        del source["day_totals"]["2026-09-27"]
        variants.append(source)
        for source in variants:
            with self.subTest(source_key=list(source)):
                self.store.progress["weekly-test"] = source
                before = self.reader.calls
                result = P.run_performance(self.reader, self.store, self.clock.now)
                self.assertEqual(result.counts, {"limited": 1})
                self.assertEqual(self.reader.calls, before)
                self.assertEqual(self.store.results["weekly-test"]["error_code"], "CHECKPOINT_INVALID")
                self.assertNotIn("비공개", str(self.store.results["weekly-test"]))

    def test_unstarted_checkpoint_cannot_contain_unattributed_nonzero_totals(self):
        P.run_performance(self.reader, self.store, self.clock.now)
        source = deepcopy(self.store.progress["weekly-test"])
        source.update(next_index=0, cycles=[])
        with self.assertRaises(P.CheckpointInvalid):
            P.validate_progress(source, self.store.jobs[0])

    def test_two_campaign_conversion_denominator_stays_unknown_if_one_tracking_source_is_unknown(self):
        self.campaigns.append(dict(self.campaigns[0], nccCampaignId=f"cmp-{A}-2"))
        self.days[f"cmp-{A}-2"] = self.rows(conversions=0, value=0)
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        row = self.store.results["weekly-test"]["daily_rows"][0]
        self.assertEqual((row["spend"], row["conversion_value"]), (2000, 2000))
        self.assertFalse(row["conversion_complete"])

    def test_new_generation_really_reads_stats_and_rejects_an_old_generation_checkpoint(self):
        job = self.store.jobs[0]
        job["generation"] = "2026-10-04T00:01:00+09:00"
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        original = deepcopy(self.store.progress[job["job_key"]])
        job.update(job_key="weekly-new", generation="2026-10-05T00:01:00+09:00")
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"ok": 1})
        self.assertEqual(len([call for call in self.http.calls if call.path == "/stats"]), 2)
        self.store.progress[job["job_key"]] = original
        before = self.reader.calls
        self.assertEqual(P.run_performance(self.reader, self.store, self.clock.now).counts, {"limited": 1})
        self.assertEqual(self.reader.calls, before)

    def test_historical_period_cannot_claim_revalidation_from_a_pre_generation_cycle(self):
        self.store.jobs[0].update(kind="manual_period", generation="2026-10-05T08:00:00+09:00")
        self.cycle = NOW-timedelta(days=1)
        result = P.run_performance(self.reader,self.store,self.clock.now)
        self.assertEqual(result.counts, {"source_wait":1})
        self.assertNotIn("daily_rows", self.store.results["weekly-test"])


if __name__ == "__main__":
    unittest.main()
