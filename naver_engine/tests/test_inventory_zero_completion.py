"""원천 무활동 보완: 실제 수집·읽기 관문 + 가짜 HTTP·메모리 저장 경계.

SQLite/파일 잠금을 우회하지 않는다. 저장·큐·재시작 통합 보장은 기존 저장소 시험이 맡는다.
"""
from copy import deepcopy
from datetime import timedelta
import unittest

from naver_engine import handles as H, inventory_reads as I, naver_read as N, store as S
from naver_engine.tests.fake_naver import FakeClock, FakeNaver, cycle_str
from naver_engine.tests.test_morning import A, Ads, T0, YDAY, creds, steady


class MemoryInventory:
    """이 시험에서만 사용하는 저장 경계. 실제 SQLite 저장소의 대체 검증은 아니다."""

    def __init__(self, now):
        self.snapshot = now
        self.valid = True
        self.progress = {}
        self.results = {}

    def inventory_snapshot(self, now):
        return self.snapshot

    def inventory_work(self, now, limit):
        return [A][:limit]

    def inventory_account_valid(self, cid, snapshot, now):
        return self.valid and cid == A and snapshot == self.snapshot and now >= snapshot

    def begin_inventory_check(self, cid, snapshot, now):
        if not self.inventory_account_valid(cid, snapshot, now):
            raise S.StoreRefused("시험 원천 변경")

    def inventory_progress(self, cid, today):
        progress = deepcopy(self.progress.get(cid))
        if progress is not None:
            I.validate_progress(progress, cid, today)
        return progress

    def record_inventory_progress(self, cid, snapshot, now, progress):
        self.begin_inventory_check(cid, snapshot, now)
        self.progress[cid] = deepcopy(progress)

    def record_inventory_check(self, cid, snapshot, now, values):
        self.begin_inventory_check(cid, snapshot, now)
        self.results[cid] = deepcopy(values)
        return values["status"]


class InventoryZeroCompletionTest(unittest.TestCase):
    def setUp(self):
        self.fc = FakeClock(T0)
        self.naver = FakeNaver()
        self.ads = Ads(self.naver)
        self.st = MemoryInventory(T0)
        self.reader = N.NaverReader(creds(), transport=self.naver, clock=self.fc)

    def run_inventory(self, **kwargs):
        return I.run_inventory(self.reader, self.st, self.fc.now, **kwargs)

    def test_missing_summary_is_completed_only_by_fresh_daily_zero(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
        outcome = self.run_inventory()
        self.assertEqual(outcome.counts, {"ok": 1})
        row = self.st.results[A]
        self.assertEqual((row["yday_imp"], row["yday_clk"], row["yday_spend"]), (0, 0, 0))
        self.assertEqual(len(self.naver.calls), 5)

    def test_only_missing_campaigns_need_daily_proof(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, steady()),
                         (2, "PAUSED", True, steady(0, 0, 0, 0))], biz=10)
        outcome = self.run_inventory()
        self.assertEqual(outcome.counts, {"ok": 1})
        self.assertEqual(self.st.results[A]["yday_spend"], 20000)
        daily = [call.query["id"][0] for call in self.naver.calls if "timeIncrement" in call.query]
        self.assertEqual(daily, [f"cmp-{A}-2"])

    def test_many_missing_zero_campaigns_complete_across_bounded_rounds(self):
        self.ads.add(A, [(n, "ELIGIBLE", False, steady(0, 0, 0, 0)) for n in range(12)], biz=10)
        for expected in ({"partial": 1}, {"partial": 1}, {"ok": 1}):
            before = self.reader.calls
            self.assertEqual(self.run_inventory().counts, expected)
            self.assertLessEqual(self.reader.calls - before, 8)
        self.assertEqual(self.st.results[A]["yday_spend"], 0)
        daily = [call.query["id"][0] for call in self.naver.calls if "timeIncrement" in call.query]
        self.assertEqual(len(daily), 12)
        self.assertEqual(len(set(daily)), 12)

    def test_missing_or_delayed_daily_evidence_is_not_zero(self):
        zero = {"dateStart": YDAY.isoformat(), **dict.fromkeys(I.FIELDS, 0)}
        variants = (
            ([], cycle_str(T0)),
            ([zero], None),
            ([zero], cycle_str(T0 - timedelta(days=1))),
            ([zero], cycle_str(T0 + timedelta(hours=1))),
            ([dict(zero, salesAmt=None)], cycle_str(T0)),
            ([dict(zero, impCnt=1)], cycle_str(T0)),
            ([dict(zero, clkCnt=1)], cycle_str(T0)),
            ([dict(zero, salesAmt=1)], cycle_str(T0)),
        )
        for data, cycle in variants:
            with self.subTest(data=data, cycle=cycle):
                self.setUp()
                self.ads.add(A, [(1, "PAUSED", True, steady(0, 0, 0, 0))], biz=10)
                self.naver.script("/stats", (200, {"data": [], "cycleBaseTm": cycle_str(T0)}),
                                  (200, {"data": data, "cycleBaseTm": cycle}))
                self.assertEqual(self.run_inventory().counts, {"retry": 1})
                row = self.st.results[A]
                self.assertEqual(row["error_code"], "STATS_INCOMPLETE")
                self.assertNotIn("yday_spend", row)
                self.assertEqual(self.st.progress[A]["next_index"], 0)
                self.assertEqual(len(self.naver.calls), 4)

    def test_invalid_daily_shape_is_not_zero(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
        self.naver.script("/stats", (200, {"data": [], "cycleBaseTm": cycle_str(T0)}),
                          (200, {"data": [{"dateStart": YDAY.isoformat(), "impCnt": True,
                                          "clkCnt": 0, "salesAmt": 0}], "cycleBaseTm": cycle_str(T0)}))
        self.assertEqual(self.run_inventory().counts, {"retry": 1})
        self.assertEqual(self.st.results[A]["error_code"], "STATS_SHAPE")
        self.assertNotIn("yday_spend", self.st.results[A])

    def test_incomplete_summary_is_not_overridden_by_daily_proof(self):
        for data, cycle in (([], None), ([], cycle_str(T0 - timedelta(days=1))),
                            ([{"id": f"cmp-{A}-1", "impCnt": None, "clkCnt": 0, "salesAmt": 0}],
                             cycle_str(T0))):
            with self.subTest(data=data, cycle=cycle):
                self.setUp()
                self.ads.add(A, [(1, "ELIGIBLE", False, steady(0, 0, 0, 0)),
                                 (2, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
                self.naver.script("/stats", (200, {"data": data, "cycleBaseTm": cycle}))
                self.assertEqual(self.run_inventory().counts, {"retry": 1})
                self.assertEqual(self.st.results[A]["error_code"], "STATS_INCOMPLETE")
                self.assertEqual(len(self.naver.calls), 3)

    def test_current_nonzero_summary_supersedes_cached_zero(self):
        self.ads.add(A, [(n, "ELIGIBLE", False, steady(0, 0, 0, 0)) for n in range(6)], biz=10)
        self.assertEqual(self.run_inventory().counts, {"partial": 1})
        cached = self.st.progress[A]["zero_ids"][0]
        self.ads.acc[A]["series"][cached] = steady(9, 2, 17, 0)
        self.assertEqual(self.run_inventory().counts, {"ok": 1})
        row = self.st.results[A]
        self.assertEqual((row["yday_imp"], row["yday_clk"], row["yday_spend"]), (9, 2, 17))

    def test_campaign_list_change_discards_cached_zero_proofs(self):
        self.ads.add(A, [(n, "ELIGIBLE", False, steady(0, 0, 0, 0)) for n in range(6)], biz=10)
        self.assertEqual(self.run_inventory().counts, {"partial": 1})
        self.ads.add(A, [(99, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
        before = self.reader.calls
        self.assertEqual(self.run_inventory().counts, {"ok": 1})
        self.assertEqual(self.reader.calls - before, 5)
        self.assertEqual(self.st.progress[A]["zero_ids"], [f"cmp-{A}-99"])

    def test_cached_zero_does_not_override_a_later_stale_summary(self):
        self.ads.add(A, [(n, "ELIGIBLE", False, steady(0, 0, 0, 0)) for n in range(6)], biz=10)
        self.assertEqual(self.run_inventory().counts, {"partial": 1})
        before = deepcopy(self.st.progress[A])
        self.ads.cycle = T0 - timedelta(days=1)
        self.assertEqual(self.run_inventory().counts, {"retry": 1})
        self.assertEqual(self.st.results[A]["error_code"], "STATS_INCOMPLETE")
        self.assertNotIn("yday_spend", self.st.results[A])
        self.assertEqual(self.st.progress[A], before)

    def test_existing_complete_summary_needs_no_zero_cache_or_daily_proof(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())], biz=10)
        self.assertEqual(self.run_inventory().counts, {"ok": 1})
        self.assertEqual(len(self.naver.calls), 4)
        self.assertNotIn("zero_ids", self.st.progress[A])
        self.assertEqual(I.validate_progress(self.st.progress[A], A, T0.date()),
                         dict(impCnt=1000, clkCnt=50, salesAmt=20000))

    def test_malformed_cached_proofs_are_rejected_before_http(self):
        self.ads.add(A, [(n, "ELIGIBLE", False, steady(0, 0, 0, 0)) for n in range(6)], biz=10)
        self.run_inventory()
        baseline = deepcopy(self.st.progress[A])
        zero_ids = baseline["zero_ids"]
        for bad in (None, "not-a-list", [None], [zero_ids[0], zero_ids[0]],
                    list(reversed(zero_ids)), ["cmp-foreign"]):
            with self.subTest(bad=bad):
                self.st.progress[A] = dict(deepcopy(baseline), zero_ids=bad)
                before = self.reader.calls
                self.assertEqual(self.run_inventory().counts, {"limited": 1})
                self.assertEqual(self.st.results[A]["error_code"], "CHECKPOINT_INVALID")
                self.assertEqual(self.reader.calls, before)
        for changes in ({"customer_id": A + 1}, {"day": YDAY.isoformat()}, {"fingerprint": "wrong"}):
            with self.subTest(changes=changes), self.assertRaises(I.CheckpointInvalid):
                I.validate_progress(dict(baseline, **changes), A, T0.date())

    def test_every_daily_retry_revalidates_inventory_handle(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
        self.naver.script("/stats", (200, {"data": [], "cycleBaseTm": cycle_str(T0)}),
                          (500, {"code": 500}))
        def revoke_on_daily(call):
            if "timeIncrement" in call.query:
                self.st.valid = False
        self.naver.tick = revoke_on_daily
        self.assertEqual(self.run_inventory().code, "SOURCE_CHANGED")
        self.assertEqual(len(self.naver.calls), 4)
        self.assertEqual(self.st.results, {})
        self.assertNotIn("zero_ids", self.st.progress[A])

    def test_source_change_or_clock_rollback_during_proof_is_not_saved(self):
        for change in (lambda: setattr(self.st, "snapshot", self.fc.now() + timedelta(seconds=1)),
                       lambda: self.fc.advance(-3600)):
            with self.subTest(change=change):
                self.setUp()
                self.ads.add(A, [(1, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
                def change_on_daily(call):
                    if "timeIncrement" in call.query:
                        change()
                self.naver.tick = change_on_daily
                self.assertEqual(self.run_inventory().code, "SOURCE_CHANGED")
                self.assertEqual(len(self.naver.calls), 4)
                self.assertEqual(self.st.results, {})
                self.assertNotIn("zero_ids", self.st.progress[A])

    def test_daily_response_after_deadline_does_not_become_zero_proof(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, steady(0, 0, 0, 0))], biz=10)
        def late_daily(call):
            if "timeIncrement" in call.query:
                self.fc.advance(11)
        self.naver.tick = late_daily
        self.assertEqual(self.run_inventory().counts, {"retry": 1})
        self.assertEqual(self.st.results[A]["error_code"], "REQUEST_BUDGET")
        self.assertNotIn("zero_ids", self.st.progress[A])
        self.assertNotIn("yday_spend", self.st.results[A])

    def test_daily_proofs_obey_account_and_run_call_caps(self):
        for limits in ({"per_account_calls": 4}, {"max_calls": 4}):
            with self.subTest(limits=limits):
                self.setUp()
                self.ads.add(A, [(n, "ELIGIBLE", False, steady(0, 0, 0, 0)) for n in range(6)], biz=10)
                self.assertEqual(self.run_inventory(**limits).counts, {"partial": 1})
                self.assertEqual(len(self.naver.calls), 4)
                self.assertEqual(len(self.st.progress[A]["zero_ids"]), 1)
                self.assertNotIn("yday_spend", self.st.results[A])

    def test_forged_or_stale_inventory_handle_cannot_request_daily_stats(self):
        handle = H.issue_inventory_handle(customer_id=A, snapshot_at=T0, now=T0,
                                          validate=self.st.inventory_account_valid)
        object.__setattr__(handle, "customer_id", A + 1)
        with self.assertRaises(H.HandleInvalid):
            self.reader.get_stats_daily(handle, f"cmp-{A}-1", YDAY, YDAY, fields=I.FIELDS)
        handle = H.issue_inventory_handle(customer_id=A, snapshot_at=T0, now=T0,
                                          validate=self.st.inventory_account_valid)
        self.fc.advance(31 * 3600)
        with self.assertRaises((H.HandleInvalid, H.NotEligible)):
            self.reader.confirm_no_activity(handle, [f"cmp-{A}-1"], YDAY, YDAY, fields=I.FIELDS)
        self.assertEqual(self.naver.calls, [])


if __name__ == "__main__":
    unittest.main()
