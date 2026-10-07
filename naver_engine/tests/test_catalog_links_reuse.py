"""짝 확인의 홀더 색인/순수 매칭 재사용. 합성 Store, 실제 WSGI, 외부 연결 금지."""
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.naver_auto import scope as SC
from naver_engine import catalog_links as CL, inventory as I, management_store as MS, views as W
from naver_engine.tests import test_catalog_links as TCL


class CatalogLinksReuseTest(unittest.TestCase):
    def setUp(self):
        self.case = TCL.CatalogLinksTest(methodName="runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def load(self, actor=0):
        case = self.case
        org = W.load_org(case.store)
        return CL.load(case.store, case.clock.now(), org, SC.scope_of(org, actor))

    def test_holder_index_equals_full_scan_with_all_claim_sources(self):
        context = self.load()
        ctx = context.ctx
        cid = next(iter(ctx.accounts))
        confirmed = SimpleNamespace(customer_id=cid, possibility_id=91, decision="confirmed")
        rejected = SimpleNamespace(customer_id=cid, possibility_id=92, decision="rejected")
        lost = SimpleNamespace(customer_id=cid, possibility_id=93, decision="confirmed")
        ctx = replace(ctx, live_decisions=(confirmed, rejected), lost_decisions=(lost,),
                      rows_by_pid={11: ({"customer_id": cid},),
                                   94: ({"customer_id": cid}, {"customer_id": cid}),
                                   95: ({"customer_id": None},),
                                   96: ({"customer_id": cid + 1},)},
                      name_owners={I.M.loose_name(ctx.accounts[cid]["account_name"]): frozenset({11, 97})})
        index = CL._holder_index(ctx)
        context = replace(context, ctx=ctx, holder_ids=index)
        for pid in (11, 91, 92, 93, 94, 95, 96, 97, 999):
            for customer in (None, cid, cid + 1, cid + 2):
                with self.subTest(pid=pid, customer=customer):
                    self.assertEqual(CL._holders(context, pid, customer), W.link_holders(ctx, pid, customer))
        self.assertEqual(CL._holders(context, 11, cid), frozenset({91, 93, 94, 97}))

    def test_pending_uses_one_index_without_row_by_row_full_scans(self):
        self.case.explicit_name_collision("합성원본상점", "합성원본상점")
        for actor in (0, 100, 101):
            context = self.load(actor)
            expected = CL.pending(context)
            with patch.object(W, "link_holders", side_effect=AssertionError("행마다 전체 홀더 순회 금지")):
                self.assertEqual(CL.pending(context), expected)

    def test_management_and_catalog_linking_share_the_same_pure_match(self):
        case = self.case
        with patch.object(I, "_matching", wraps=I._matching) as matching:
            MS.snapshot(case.store, case.clock.now())
            context = self.load()
            CL.pending(context)
            self.assertEqual(matching.call_count, 1)
        with patch.object(MS, "matching_result", side_effect=lambda store, accounts, decisions, catalog,
                          evidence, **kwargs: I._matching(SimpleNamespace(accounts=accounts,
                              live_decisions=decisions), catalog, auto_evidence=evidence, **kwargs)):
            self.assertEqual(CL.pending(context), CL.pending(self.load()))

    def test_cached_match_rechecks_source_freshness_and_latest_confirmations(self):
        case = self.case
        rows = case.explicit_name_collision("합성원본상점", "합성원본상점")
        cached = self.load()
        self.assertTrue(CL.pending(cached)["rows"][0]["can_confirm"])
        case.store.record_decision(12, next(iter(cached.ctx.accounts)), "confirmed", 0, case.clock.now())
        changed = self.load()
        self.assertNotEqual(cached.source_key, changed.source_key)
        self.assertFalse(any(row["can_confirm"] for row in CL.pending(changed)["rows"]))
        self.assertEqual(case.confirm(rows)[0], 404)
        case.clock.advance(3 * 3600)
        stale = self.load()
        self.assertEqual(stale.source_state, "stale")
        self.assertFalse(any(row["can_confirm"] for row in CL.pending(stale)["rows"]))

    def test_transaction_rechecks_changed_decision_after_match_is_cached(self):
        case = self.case
        rows = case.explicit_name_collision("합성원본상점", "합성원본상점")
        self.load()
        record = case.store.record_decisions
        cid = case.store.accounts()[0]["customer_id"]
        def racing_record(*args, **kwargs):
            case.store.record_decision(12, cid, "confirmed", 0, case.clock.now())
            return record(*args, **kwargs)
        with patch.object(case.store, "record_decisions", side_effect=racing_record):
            self.assertEqual(case.confirm(rows)[0], 409)
        self.assertEqual([(d.possibility_id, d.customer_id) for d in case.store.current_decisions()], [(12, cid)])
        self.assertFalse(case.store._conn.in_transaction)


if __name__ == "__main__":
    unittest.main()
