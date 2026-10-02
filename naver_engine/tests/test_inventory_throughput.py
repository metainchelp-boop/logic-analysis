"""실제 읽기 관문/가짜 HTTP로 회차 예산 활용을 비교한다. 운영 처리량 시험이 아니다."""
from copy import deepcopy
import unittest

from naver_engine import inventory_reads as I, naver_read as N
from naver_engine.tests.fake_naver import FakeClock, FakeNaver
from naver_engine.tests.test_morning import A, Ads, T0, creds, steady
from naver_engine.tests.test_inventory_zero_completion import MemoryInventory


class QueueBoundary(MemoryInventory):
    """한 회차의 후보 목록만 제공한다. 공정 큐/SQLite 검증은 저장소 시험에 있다."""
    def __init__(self, now, ids):
        super().__init__(now)
        self.ids = ids
        self.started = []

    def inventory_work(self, now, limit):
        return self.ids[:limit]

    def inventory_account_valid(self, cid, snapshot, now):
        return self.valid and cid in self.ids and snapshot == self.snapshot and now >= snapshot

    def begin_inventory_check(self, cid, snapshot, now):
        super().begin_inventory_check(cid, snapshot, now)
        self.started.append(cid)

    def record_inventory_progress(self, cid, snapshot, now, progress):
        if not self.inventory_account_valid(cid, snapshot, now):
            raise AssertionError("검증되지 않은 시험 원천")
        self.progress[cid] = deepcopy(progress)

    def record_inventory_check(self, cid, snapshot, now, values):
        if not self.inventory_account_valid(cid, snapshot, now):
            raise AssertionError("검증되지 않은 시험 원천")
        self.results[cid] = deepcopy(values)
        return values["status"]


class InventoryThroughputTest(unittest.TestCase):
    def scene(self, *, active=False, count=12):
        clock, transport = FakeClock(T0), FakeNaver()
        ads = Ads(transport)
        store = QueueBoundary(T0, list(range(A, A + count)))
        for cid in store.ids:
            campaigns = [(1, "ELIGIBLE", False, steady())] if active else []
            ads.add(cid, campaigns, biz=10)
        reader = N.NaverReader(creds(), transport=transport, clock=clock)
        return clock, transport, store, reader

    def test_empty_accounts_use_same_24_request_budget_instead_of_stopping_at_three(self):
        old_clock, old_http, old_store, old_reader = self.scene()
        old = I.run_inventory(old_reader, old_store, old_clock.now, limit=3)
        clock, http, store, reader = self.scene()
        new = I.run_inventory(reader, store, clock.now)
        self.assertEqual((old.counts, len(old_http.calls)), ({"ok": 3}, 9))
        self.assertEqual((new.counts, len(http.calls)), ({"ok": 8}, 24))
        self.assertEqual(len(store.started), 8)

    def test_active_accounts_double_completed_accounts_without_changing_http_cap(self):
        old_clock, old_http, old_store, old_reader = self.scene(active=True)
        old = I.run_inventory(old_reader, old_store, old_clock.now, limit=3)
        clock, http, store, reader = self.scene(active=True)
        new = I.run_inventory(reader, store, clock.now)
        self.assertEqual((old.counts, len(old_http.calls)), ({"ok": 3}, 12))
        self.assertEqual((new.counts, len(http.calls)), ({"ok": 6}, 24))
        self.assertTrue(all(row["yday_spend"] == 20000 for row in store.results.values()))

    def test_less_than_minimum_remaining_budget_does_not_start_another_account(self):
        clock, http, store, reader = self.scene()
        outcome = I.run_inventory(reader, store, clock.now, max_calls=11)
        self.assertEqual((outcome.code, outcome.counts, len(http.calls)), ("BUDGET", {"ok": 3}, 9))
        self.assertEqual(store.started, store.ids[:3])

    def test_pacing_read_only_and_per_account_bounds_remain_in_force(self):
        clock, http, store, reader = self.scene(active=True)
        sent_at = []
        http.tick = lambda call: sent_at.append(clock.monotonic())
        I.run_inventory(reader, store, clock.now)
        self.assertEqual(len(sent_at), 24)
        self.assertTrue(all(b - a >= 1 / N.CALLS_PER_SEC - 1e-9 for a, b in zip(sent_at, sent_at[1:])))
        self.assertTrue(all(call.method == "GET" and not call.has_body for call in http.calls))
        self.assertTrue(all(sum(call.customer == str(cid) for call in http.calls) <= 8 for cid in store.started))

    def test_retries_are_charged_to_the_same_budget_and_do_not_publish_unknowns(self):
        clock, http, store, reader = self.scene()
        http.script("/ncc/campaigns", *[(500, {"code": 500})] * 40)
        outcome = I.run_inventory(reader, store, clock.now)
        self.assertLessEqual(len(http.calls), 24)
        self.assertLessEqual((clock.now() - T0).total_seconds(), 30)
        self.assertNotIn("ok", outcome.counts)
        self.assertTrue(all(row.get("yday_spend") is None for row in store.results.values()))

    def test_candidate_cap_cannot_be_expanded_or_boolean(self):
        clock, http, store, reader = self.scene()
        for limit in (0, 25, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                I.run_inventory(reader, store, clock.now, limit=limit)
        self.assertEqual(http.calls, [])


if __name__ == "__main__":
    unittest.main()
