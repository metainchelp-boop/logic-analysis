"""사유 목록은 요약만, 상세는 권한이 확인된 계정의 고정 크기 페이지로 읽는다."""
from datetime import timedelta
import json
from types import SimpleNamespace
import unittest

from app.naver_auto import org_snapshot as O, scope as SC
from naver_engine import inventory as I, store as S
from naver_engine.tests.test_managed_storage import _ManagedBoundary, _Rows
from naver_engine.tests import test_morning as TM


class ReasonStore(_ManagedBoundary):
    def __init__(self, now):
        super().__init__(now)
        self.reasons = [{"entity": "ad", "entity_id": f"ad-{n}", "checked_at": now.isoformat(),
                         "status": {"code": "UNRECOGNIZED", "meaning": "해석 미확인"},
                         "reason": {"code": "AD_PAUSED", "meaning": "소재 사용자 중지"},
                         "parents": [{"entity": "campaign", "entity_id": "cmp-1",
                                      "status": {"code": "ELIGIBLE"}, "reason": {"code": None}}]}
                        for n in range(51)]
        self.structure = {"row_id": 1, "customer_id": TM.A, "job_key": "structure:daily:test",
                          "cycle_day": now.date().isoformat(), "stage_revision": "revision-1", "status": "ok",
                          "checked_at": now.isoformat(), "error_code": None}

    def execute(self, sql, args=()):
        if "json_each" in sql:
            return _Rows([{"value": json.dumps(item)} for item in self.reasons[args[1]:args[1]+50]])
        if "json_array_length" in sql:
            return _Rows([] if self.structure is None else [{**self.structure, "customer_id": cid,
                          "reason_count": len(self.reasons)} for cid in args if cid in self.states])
        return super().execute(sql, args)

    def accounts_read_at(self):
        return self.now

    def inventory_checks_on(self, day):
        return {}

    def performance_checks(self, now):
        return {}

    def latest_inventory_successes(self):
        return {}

    def account_times(self):
        return {}

    def structure_checks(self, *args):
        raise AssertionError("목록은 전체 사유를 읽지 않아야 합니다")

    def observed_campaign_reasons(self, *args):
        raise AssertionError("목록은 이전 캠페인 전체를 읽지 않아야 합니다")

    def context(self):
        return SimpleNamespace(now=self.now, today=self.now.date(), org=O.parse_org_snapshot(self.org_current()["body"]),
                               accounts={row["customer_id"]: row for row in self.accounts()},
                               live_decisions=self.current_decisions(), prospects={})


class ReasonPageTest(unittest.TestCase):
    def setUp(self):
        self.st = ReasonStore(TM.T0)

    def test_store_pages_keep_raw_reason_and_parent_without_full_array_in_summary(self):
        summary = self.st.structure_reason_summaries([TM.A], TM.T0)[TM.A]
        self.assertEqual(summary["reason_count"], 51)
        self.assertNotIn("reasons", summary)
        first = self.st.structure_reason_page(TM.A, TM.T0)
        second = self.st.structure_reason_page(TM.A, TM.T0, page=1)
        self.assertEqual((first["page_size"], len(first["items"]), first["next_page"]), (50, 50, 1))
        self.assertEqual((second["total"], len(second["items"]), second["next_page"]), (51, 1, None))
        self.assertEqual(first["items"]+second["items"], self.st.reasons)

    def test_board_contains_only_count_status_time_and_never_reads_full_reasons(self):
        ctx = self.st.context()
        rows = I.board(ctx, self.st, SC.scope_of(ctx.org, 100))["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ad_reason_count"], 51)
        self.assertEqual(rows[0]["structure_status"], "ok")
        self.assertEqual(rows[0]["structure_checked_at"], TM.T0.isoformat())
        self.assertNotIn("ad_reasons", rows[0])

    def test_inventory_detail_uses_current_owner_scope_and_rejects_other_or_missing_equally(self):
        ctx = self.st.context()
        number = str(ctx.accounts[TM.A]["ad_account_no"])
        result = I.reason_page(ctx, self.st, SC.scope_of(ctx.org, 100), number)
        self.assertEqual((result["total"], len(result["items"])), (51, 50))
        for actor, account in ((101, number), (100, "999999999")):
            with self.subTest(actor=actor, account=account), self.assertRaises(SC.ClientNotVisible):
                I.reason_page(ctx, self.st, SC.scope_of(ctx.org, actor), account)

    def test_single_account_detail_does_not_scan_other_account_reason_arrays(self):
        class DetailOnlyStore(ReasonStore):
            def structure_reason_summaries(self, *args):
                raise AssertionError("단일 상세는 전체 계정의 사유 요약을 읽지 않습니다")
        store = DetailOnlyStore(TM.T0)
        ctx = store.context()
        result = I.reason_page(ctx, store, SC.scope_of(ctx.org, 100), str(ctx.accounts[TM.A]["ad_account_no"]))
        self.assertEqual(len(result["items"]), 50)

    def test_fresh_unobserved_structure_is_pending_but_changed_or_stale_source_is_rejected(self):
        self.st.structure = None
        self.assertEqual(self.st.structure_reason_page(TM.A, TM.T0),
                         {"items": [], "total": 0, "page": 0, "page_size": 50,
                          "next_page": None, "checked_at": None, "status": "pending"})
        self.st = ReasonStore(TM.T0)
        self.st.catalog["items"][0]["stage"] = "사후관리"
        with self.assertRaisesRegex(S.StoreRefused, "SOURCE_STALE"):
            self.st.structure_reason_page(TM.A, TM.T0)
        self.assertEqual(self.st.structure_reason_summaries([TM.A], TM.T0)[TM.A]["reason_count"], 0)
        self.st = ReasonStore(TM.T0)
        self.st.catalog_state = "failed"
        ctx = self.st.context()
        with self.assertRaisesRegex(S.StoreRefused, "SOURCE_STALE"):
            I.reason_page(ctx, self.st, SC.scope_of(ctx.org, 100), str(ctx.accounts[TM.A]["ad_account_no"]))

    def test_ceo_can_read_unmatched_and_ambiguous_raw_accounts_but_staff_cannot(self):
        self.st.structure = None
        self.st.catalog.update(total=0, items=[], ids=[])
        self.st.states[TM.A].update(possibility_id=None, stage_key=None)
        ctx = self.st.context()
        number = str(ctx.accounts[TM.A]["ad_account_no"])
        self.assertEqual(I.reason_page(ctx, self.st, SC.scope_of(ctx.org, 0), number)["status"], "pending")
        with self.assertRaises(SC.ClientNotVisible):
            I.reason_page(ctx, self.st, SC.scope_of(ctx.org, 100), number)
        self.st = ReasonStore(TM.T0)
        self.st.catalog["items"].append({**self.st.catalog["items"][0], "possibility_id": 12})
        self.st.catalog["ids"].append({**self.st.catalog["ids"][0], "possibility_id": 12})
        self.st.catalog["total"] = 2
        self.st.structure = None
        self.st.states[TM.A].update(possibility_id=None, stage_key=None)
        ctx = self.st.context()
        self.assertEqual(I.reason_page(ctx, self.st, SC.scope_of(ctx.org, 0), number)["status"], "pending")
        with self.assertRaises(SC.ClientNotVisible):
            I.reason_page(ctx, self.st, SC.scope_of(ctx.org, 100), number)
        with self.assertRaises(SC.ClientNotVisible):
            I.reason_page(ctx, self.st, SC.scope_of(ctx.org, 0), number, selection="person:100")

    def test_page_bounds_do_not_enable_arbitrary_large_or_negative_reads(self):
        for page in (-1, True, "1", 2, 200, 10**20):
            with self.subTest(page=page), self.assertRaisesRegex(S.StoreRefused, "BAD_PAGE"):
                self.st.structure_reason_page(TM.A, TM.T0, page)

    def test_1793_accounts_with_ten_thousand_reasons_each_stay_below_relay_limit(self):
        class LargeStore(ReasonStore):
            def performance_checks(self, now):
                at = now.isoformat()
                return {cid: dict(cadence="daily", policy_reason="MANAGED_STAGE", stage_revision="a"*64,
                                 excluded=False, status="ok", checked_at=at, error_code=None,
                                 last_success_at=at, period_start="2026-09-28", period_end="2026-09-28",
                                 stale=False, attribution_changed=False, bizmoney=12000000, bizmoney_at=at,
                                 previous_bizmoney=10000000, previous_bizmoney_at=at, bizmoney_change=2000000,
                                 spend=50000, imp=10000, clk=100, activity_observed=True)
                        for cid in self.states}
        self.st = LargeStore(TM.T0)
        sample = self.st.states[TM.A]
        self.st.states = {cid: {**sample, "stage_revision": "a"*64} for cid in range(TM.A, TM.A+1793)}
        self.st.structure["stage_revision"] = "a"*64
        self.st.catalog["ids"] = [{**self.st.catalog["ids"][0], "customer_id_raw": str(cid)} for cid in self.st.states]
        self.st.reasons = self.st.reasons[:1]*10000
        ctx = self.st.context()
        result = I.board(ctx, self.st, SC.scope_of(ctx.org, 0))
        self.assertEqual(len(result["rows"]), 1793)
        self.assertTrue(all(row["ad_reason_count"] == 10000 and "ad_reasons" not in row for row in result["rows"]))
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
        self.assertLess(len(payload), 4*1024*1024)


if __name__ == "__main__":
    unittest.main()
