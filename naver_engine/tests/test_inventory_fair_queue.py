"""계정 원천 대기열: 날짜가 바뀌어도 시도 순서는 보존하고 숫자는 섞지 않는다."""
from datetime import timedelta
import hashlib
import json

from naver_engine import inventory_reads as I, store as S
from naver_engine.tests.fake_naver import campaign
from naver_engine.tests.test_morning import Base, kids, steady


class InventoryFairQueueTest(Base):
    def accounts(self, ids):
        self.st.record_accounts(kids(*ids), self.fc.now())
        for cid in ids:
            self.ads.add(cid, [], biz=cid)

    def outcome(self, cid, status):
        now = self.fc.now()
        snapshot = self.st.inventory_snapshot(now)
        self.st.begin_inventory_check(cid, snapshot, now)
        return self.st.record_inventory_check(cid, snapshot, now, {"status": status, "bizmoney": cid})

    def test_daily_capacity_continues_tail_across_midnight_and_restarts(self):
        ids = list(range(1_000_001, 1_000_008))
        self.at(self.fc.now().replace(hour=23, minute=58))
        self.accounts(ids)
        expected = (ids[:3], ids[3:6], [ids[6], *ids[:2]], ids[2:5], [ids[5], *ids[:2]])
        previous_day = None
        for selected in expected:
            today = self.fc.now().date()
            self.assertEqual(self.st.inventory_checks_on(today), {})
            self.assertEqual(self.st.inventory_work(self.fc.now()), selected)
            self.assertEqual(I.run_inventory(self.reader(), self.st, self.fc.now, limit=3).counts, {"ok": 3})
            rows = self.st.inventory_checks_on(today)
            self.assertEqual(set(rows), set(selected))
            if previous_day is not None:
                self.assertEqual(self.st.inventory_checks_on(previous_day), previous_rows)
            previous_day, previous_rows = today, rows
            self.st.close()
            self.st = S.open_writer(self.path, clock=self.fc.now)
            self.at((self.fc.now() + timedelta(days=1)).replace(hour=0, minute=1))
            self.st.record_accounts(kids(*ids), self.fc.now())

    def test_due_partial_and_retry_take_a_turn_after_finite_untouched_tail(self):
        ids = list(range(1_000_001, 1_000_008))
        self.accounts(ids)
        self.outcome(ids[0], "partial")
        self.fc.advance(1)
        self.outcome(ids[1], "retry")
        self.fc.advance(121)
        self.assertEqual(self.st.inventory_work(self.fc.now()), ids[2:5])
        I.run_inventory(self.reader(), self.st, self.fc.now, limit=3)
        self.fc.advance(1)
        self.assertEqual(self.st.inventory_work(self.fc.now()), [*ids[5:], ids[0]])
        I.run_inventory(self.reader(), self.st, self.fc.now, limit=3)
        self.fc.advance(1)
        self.assertEqual(self.st.inventory_work(self.fc.now()), [ids[1]])
        I.run_inventory(self.reader(), self.st, self.fc.now, limit=3)
        self.assertEqual({r["status"] for r in self.st.inventory_checks_on(self.fc.now().date()).values()}, {"ok"})

    def test_older_due_continuation_precedes_account_attempted_late_yesterday(self):
        low, high = 1_000_001, 1_000_002
        self.accounts([low, high])
        self.outcome(high, "partial")
        self.fc.advance(60)
        self.outcome(low, "partial")
        self.fc.advance(24 * 3600)
        self.st.record_accounts(kids(low, high), self.fc.now())
        self.assertEqual(self.st.inventory_work(self.fc.now()), [high, low])
        self.outcome(high, "partial")
        self.fc.advance(1)
        self.assertEqual(self.st.inventory_work(self.fc.now()), [low, high])

    def test_new_account_is_eligible_before_previously_attempted_accounts(self):
        low, high = 1_000_001, 1_000_002
        self.accounts([low])
        I.run_inventory(self.reader(), self.st, self.fc.now, limit=1)
        self.fc.advance(24 * 3600)
        self.accounts([low, high])
        self.assertEqual(self.st.inventory_work(self.fc.now()), [high, low])

    def test_retry_backoff_four_attempt_limit_and_reauth_stay_excluded_today(self):
        retry, reauth, partial = 1_000_001, 1_000_002, 1_000_003
        self.accounts([retry, reauth, partial])
        self.outcome(reauth, "reauth_required")
        self.outcome(partial, "partial")
        for attempt, delay in enumerate((120, 300, 900, 1800), start=1):
            self.assertEqual(self.outcome(retry, "retry"), "limited" if attempt == 4 else "retry")
            self.assertEqual(self.st.inventory_work(self.fc.now()), [partial])
            with self.assertRaises(S.StoreRefused):
                self.st.begin_inventory_check(retry, self.st.inventory_snapshot(self.fc.now()), self.fc.now())
            self.fc.advance(delay)
            self.assertEqual(set(self.st.inventory_work(self.fc.now())),
                             {partial} if attempt == 4 else {partial, retry})
        self.assertEqual(self.st.inventory_checks_on(self.fc.now().date())[retry]["error_code"], "RETRY_EXHAUSTED")

    def test_old_day_partial_checkpoint_is_neither_resumed_nor_published_today(self):
        cid = 1_000_001
        self.at(self.fc.now().replace(hour=23, minute=58))
        self.accounts([cid])
        self.ads.add(cid, [(n, "ELIGIBLE", False, steady()) for n in range(601)], biz=10)
        old_day = self.fc.now().date()
        self.assertEqual(I.run_inventory(self.reader(), self.st, self.fc.now, limit=1).counts, {"partial": 1})
        old_progress = self.st.inventory_progress(cid, old_day)
        self.assertGreater(old_progress["next_index"], 0)
        old_rows = self.st.inventory_checks_on(old_day)
        self.fc.advance(180)
        self.at(self.fc.now().replace(hour=6, minute=1))
        self.ads.cycle = self.fc.now().replace(hour=5, minute=0)
        today = self.fc.now().date()
        self.assertNotEqual(today, old_day)
        self.assertIsNone(self.st.inventory_progress(cid, today))
        self.assertEqual(self.st.inventory_checks_on(today), {})
        self.ads.add(cid, [(n, "ELIGIBLE", False, steady(3, 1, 7, 1)) for n in range(601)], biz=20)
        self.assertEqual(I.run_inventory(self.reader(), self.st, self.fc.now, limit=1).counts, {"partial": 1})
        row = self.st.inventory_checks_on(today)[cid]
        self.assertIsNone(row["yday_spend"])
        new_progress = self.st.inventory_progress(cid, today)
        self.assertEqual(new_progress["next_index"], old_progress["next_index"])
        self.assertEqual(I.validate_progress(new_progress, cid, today)["salesAmt"], new_progress["next_index"] * 7)
        self.assertEqual(self.st.inventory_progress(cid, old_day), old_progress)
        self.assertEqual(self.st.inventory_checks_on(old_day), old_rows)

    def test_new_verified_zero_checkpoint_resets_failure_budget_without_advancing_batch(self):
        cid = 1_000_001
        self.accounts([cid])
        self.outcome(cid, "retry")
        self.fc.advance(120)
        ids = sorted(campaign(cid, n)["nccCampaignId"] for n in range(2))
        source = dict(customer_id=cid, day=self.fc.now().date().isoformat(), campaign_ids=ids,
                      fingerprint=hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest(),
                      next_index=0, batches=[])
        snapshot = self.st.inventory_snapshot(self.fc.now())
        self.st.begin_inventory_check(cid, snapshot, self.fc.now())
        self.st.record_inventory_progress(cid, snapshot, self.fc.now(), source)
        self.st.record_inventory_check(cid, snapshot, self.fc.now(), {"status": "retry"})
        self.fc.advance(300)
        self.st.begin_inventory_check(cid, snapshot, self.fc.now())
        source["zero_ids"] = ids[:1]
        self.st.record_inventory_progress(cid, snapshot, self.fc.now(), source)
        self.st.record_inventory_check(cid, snapshot, self.fc.now(), {"status": "retry"})
        self.fc.advance(120)
        self.assertEqual(self.st.inventory_work(self.fc.now()), [cid])
        self.assertEqual(self.st.inventory_progress(cid, self.fc.now().date())["next_index"], 0)
        # 같은 증거를 다시 적는 것만으로는 실패 횟수를 초기화하지 않는다.
        self.st.begin_inventory_check(cid, snapshot, self.fc.now())
        self.st.record_inventory_progress(cid, snapshot, self.fc.now(), source)
        self.st.record_inventory_check(cid, snapshot, self.fc.now(), {"status": "retry"})
        self.fc.advance(120)
        self.assertEqual(self.st.inventory_work(self.fc.now()), [])
        self.fc.advance(180)
        self.assertEqual(self.st.inventory_work(self.fc.now()), [cid])

    def test_candidate_limit_is_bounded_at_twenty_four_and_default_stays_three(self):
        ids = list(range(1_000_001, 1_000_031))
        self.accounts(ids)
        self.assertEqual(self.st.inventory_work(self.fc.now()), ids[:3])
        self.assertEqual(self.st.inventory_work(self.fc.now(), limit=24), ids[:24])
        for invalid in (0, 25, True, 1.5, None):
            with self.subTest(limit=invalid), self.assertRaises(S.StoreRefused):
                self.st.inventory_work(self.fc.now(), limit=invalid)

    def test_stale_or_unaccepted_list_never_returns_candidates(self):
        ids = list(range(1_000_001, 1_000_008))
        self.accounts(ids)
        self.fc.advance(31 * 3600)
        self.assertEqual(self.st.inventory_work(self.fc.now(), limit=24), [])
        self.st.record_accounts(kids(*ids), self.fc.now())
        self.fc.advance(1)
        self.st.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ("INCOMPLETE_LIST",), self.fc.now())
        self.assertEqual(self.st.inventory_work(self.fc.now(), limit=24), [])

    def test_account_missing_from_latest_accepted_list_is_not_a_candidate(self):
        ids = list(range(1_000_001, 1_000_011))
        self.accounts(ids)
        self.fc.advance(1)
        self.st.record_accounts(kids(*ids[1:]), self.fc.now())
        self.assertEqual(self.st.inventory_work(self.fc.now(), limit=24), ids[1:])
