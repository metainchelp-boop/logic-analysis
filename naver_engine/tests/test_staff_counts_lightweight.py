"""첫 화면 직원 수 조회는 성과/구조 이력을 읽지 않고 현재 권한과 매칭만 센다."""
from collections import Counter
from contextlib import ExitStack
import unittest
from unittest.mock import patch

from app.naver_auto import scope as SC
from naver_engine import inventory as I, naver_read as N, store as S, views as W
from naver_engine.tests import test_alerts as TA
from naver_engine.tests import test_accounts_match_reuse as TM


class StaffCountsLightweightTest(unittest.TestCase):
    def setUp(self):
        self.fixture = TM.AccountsMatchReuseTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.clock = self.fixture.store, self.fixture.clock

    def counts(self, actor=0, *, narrowed=False):
        ctx = W.load(self.store, self.clock.now())
        scope = SC.narrowed_scope_of(ctx.org, actor) if narrowed else SC.scope_of(ctx.org, actor)
        return I.staff_counts(ctx, self.store, scope)

    def assert_matches_list(self):
        for actor in (0, 100, 101):
            ctx = W.load(self.store, self.clock.now())
            scope = SC.scope_of(ctx.org, actor)
            matched = Counter(r["possibility_id"] for r in I.board(ctx, self.store, scope)["rows"]
                              if r["mapping"] == "matched")
            owns = {pid: SC.ownership_for_client(ctx.org, pid, pid, SC.MATCH_PID) for pid in matched}
            expected = {idx: sum(matched[pid] for pid in SC.clients_in(ctx.org,
                SC.narrowed_scope_of(ctx.org, idx), owns)) for idx in scope.people
                if ctx.org.people[idx].active and ctx.org.people[idx].is_management}
            self.assertEqual(self.counts(actor), expected)

    def test_real_me_does_not_load_account_detail_histories(self):
        with ExitStack() as stack:
            for method in ("inventory_checks_on", "structure_reason_summaries", "performance_checks",
                           "latest_inventory_successes", "account_times"):
                stack.enter_context(patch.object(S.Store, method,
                    side_effect=AssertionError("직원 수 조회가 계정 상세 이력을 읽었습니다: " + method)))
            for actor, expected in ((100, [(100, 1)]), (101, [(101, 1)])):
                status, result = self.fixture.call("/me", actor)
                self.assertEqual(status, 200)
                self.assertEqual([(r["idx"], r["account_count"]) for r in result["people"]], expected)

    def test_count_parity_current_hidden_failed_source_and_owner_change(self):
        self.assert_matches_list()
        self.assertEqual(self.counts(100), {100: 1})
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 101), TA.owner(12, 101)]), now)
        self.assertEqual(self.counts(100), {100: 0})
        self.assertEqual(self.counts(101), {101: 2})
        self.assert_matches_list()
        catalog = self.store.account_catalog()
        items = [{**r, "stage_hidden": True} if r["possibility_id"] == 11 else r for r in catalog["items"]]
        self.store.record_account_catalog({"generated_at": now.isoformat(), "complete": True,
            "total": len(items), "items": items}, self.fixture.ids, now)
        self.assertEqual(self.counts(101), {101: 1})
        self.assert_matches_list()
        self.store.record_account_catalog_failure(now, "CATALOG_FAILED")
        self.assertEqual(self.counts(101), {101: 0})
        self.assert_matches_list()

    def test_stale_account_source_and_rejected_match_do_not_count(self):
        cid = self.store.accounts()[0]["customer_id"]
        self.store.record_decision(11, cid, "rejected", 0, self.clock.now())
        self.assertEqual(self.counts(100), {100: 0})
        self.assert_matches_list()
        self.store.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ("KEY_REJECTED",), self.clock.now())
        self.assertEqual(self.counts(101), {101: 0})
        self.assert_matches_list()

    def test_multiple_confirmed_accounts_count_individually(self):
        account = self.store.accounts()[4]
        self.store.record_decision(11, account["customer_id"], "confirmed", 0, self.clock.now())
        self.assertEqual(self.counts(100), {100: 2})
        self.assert_matches_list()

    def test_absent_account_is_not_counted_even_with_previous_confirmation(self):
        accounts = self.store.accounts()
        absent = accounts[0]["customer_id"]
        now = self.clock.now()
        current = {row["customer_id"]: {"customerId": row["customer_id"],
            "adAccountNo": row["ad_account_no"], "adAccountName": row["account_name"]}
            for row in accounts if row["customer_id"] != absent}
        self.store.record_accounts(N.ChildAccounts(current, {1: len(current)}, ()), now)
        self.assertEqual(next(row["present"] for row in self.store.accounts()
                              if row["customer_id"] == absent), 0)
        self.assertEqual(self.counts(100), {100: 0})
        self.assertEqual(self.counts(101), {101: 1})
        self.assert_matches_list()

    def test_unknown_stage_is_excluded_but_expired_and_refunded_stages_still_count(self):
        catalog = self.store.account_catalog()
        now = self.clock.now()
        for unknown in (False, True):
            items = [{**row, "stage": "계약만료", "stage_known": not unknown}
                     if row["possibility_id"] == 11 else
                     {**row, "stage": "환불완료"} if row["possibility_id"] == 12 else row
                     for row in catalog["items"]]
            self.store.record_account_catalog({"generated_at": now.isoformat(), "complete": True,
                "total": len(items), "items": items}, self.fixture.ids, now)
            self.assertEqual(self.counts(100), {100: 0 if unknown else 1})
            self.assertEqual(self.counts(101), {101: 1})
            self.assert_matches_list()

    def test_stale_catalog_counts_zero_without_using_the_last_accepted_matches(self):
        self.clock.advance(I.CATALOG_INTERVAL.total_seconds() * 2 + 1)
        self.assertEqual(I.catalog_status(self.store, self.clock.now())[1], "stale")
        self.assertIsNotNone(self.store.inventory_snapshot(self.clock.now()))
        self.assertEqual(self.counts(100), {100: 0})
        self.assertEqual(self.counts(101), {101: 0})
        self.assert_matches_list()

    def test_main_sub_previous_and_unassigned_owners_keep_existing_scope_rules(self):
        self.clock.advance(1)
        now = self.clock.now()
        previous = {**TA.owner(12, None, 101), "owner_source": "prev", "prev_manage_owner_idx": 100}
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 100, 101), previous]), now)
        self.assertEqual(self.counts(100), {100: 2})
        self.assertEqual(self.counts(101), {101: 2})
        self.assert_matches_list()
        for actor in (100, 101):
            status, result = self.fixture.call("/me", actor)
            self.assertEqual(status, 200)
            self.assertEqual([(row["idx"], row["account_count"]) for row in result["people"]], [(actor, 2)])
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 100, 100), TA.owner(12, None)]), now)
        self.assertEqual(self.counts(100), {100: 1})
        self.assertEqual(self.counts(101), {101: 0})
        self.assert_matches_list()

    def test_narrowed_sessions_keep_staff_boundary_and_ceo_counts(self):
        for actor in (0, 100, 101):
            with self.subTest(actor=actor):
                self.assertEqual(self.counts(actor, narrowed=True), self.counts(actor))
                regular_status, regular = self.fixture.call("/me", actor)
                narrow_status, narrowed = self.fixture.call("/me", actor, narrowed=True)
                self.assertEqual((regular_status, narrow_status), (200, 200))
                self.assertEqual(narrowed["people"], regular["people"])
                if actor != 0:
                    self.assertEqual([row["idx"] for row in narrowed["people"]], [actor])

    def test_nonmanagement_and_resigned_owners_do_not_enter_roster_or_get_access(self):
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, extra_people=(
            TA.emp(102, "합성영업", 11, management=False),
            TA.emp(103, "합성퇴사", 11, status="RESIGNED")),
            owners=[TA.owner(11, 102), TA.owner(12, 103)]), now)
        self.assertEqual(self.counts(), {0: 2, 1: 0, 100: 0, 101: 0})
        self.assert_matches_list()
        status, result = self.fixture.call("/me", 0)
        self.assertEqual(status, 200)
        self.assertEqual({row["idx"] for row in result["people"]}, {0, 1, 100, 101})
        self.assertEqual(self.fixture.call("/me", 102)[0], 401)
        self.assertEqual(self.fixture.call("/me", 103)[0], 401)
