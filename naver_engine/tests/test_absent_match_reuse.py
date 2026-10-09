"""부재 계정 순수 매칭 1개만 재사용. 실제 matcher/board, 합성 객체만; DB/네트워크 없음."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, astuple
from datetime import datetime, timedelta, timezone
import socket
import sqlite3
import sys
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.naver_auto import matching as M, org_snapshot as O, scope as SC
from naver_engine import inventory as I, management_store as MS, store as S, views as W
from naver_engine.tests import test_alerts as TA

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone(timedelta(hours=9)))


def direct(accounts, decisions, catalog):
    return I._matching(SimpleNamespace(accounts=accounts, live_decisions=decisions), catalog, include_absent=True)


def cached(accounts, decisions, catalog):
    # Before the fix this exercises exactly the existing _lost_rows computation (RED).
    fn = getattr(MS, "absent_matching_result", direct)
    return fn(accounts, decisions, catalog)


class ReadAdapter:
    def __init__(self):
        self.accounts_value = {100001: {"customer_id": 100001, "present": 1, "ad_account_no": 9001, "account_name": "가상현재가"},
            100002: {"customer_id": 100002, "present": 1, "ad_account_no": 9002, "account_name": "가상현재나"},
            100003: {"customer_id": 100003, "present": 0, "ad_account_no": 9003, "account_name": "가상부재가"},
            100004: {"customer_id": 100004, "present": 0, "ad_account_no": 9004, "account_name": "가상부재나"}}
        self.decisions = [SimpleNamespace(possibility_id=14, customer_id=100004, decision=M.DECISION_CONFIRMED)]
        self.catalog = {"generated_at": NOW.isoformat(), "items": [
            {"possibility_id": pid, "company_name": name, "stage": stage, "stage_hidden": False, "stage_known": True}
            for pid, name, stage in ((11, "가상현재가", "진행중"), (12, "가상현재나", "진행중"),
                                    (13, "가상부재가", "계약만료"), (14, "가상부재나", "홀딩중"))],
            "ids": [{"possibility_id": pid, "vendor": M.VENDOR_NAVER, "customer_id_raw": str(cid),
                     "ad_account_no_raw": None} for pid, cid in ((11, 100001), (12, 100002), (13, 100003))]}
        self.org_body = TA.org_body(NOW, owners=[TA.owner(11, 100), TA.owner(12, 101), TA.owner(13, 100), TA.owner(14, 101)])
        self.catalog_state = "accepted"
        self.time_rows = {cid: {"present": 0, "absent_days": 2, "absent_since": NOW-timedelta(days=2),
                               "absent_last_at": NOW} for cid in (100003, 100004)}
    def account_catalog(self): return deepcopy(self.catalog)
    def account_catalog_status(self): return {"state": self.catalog_state, "at": NOW.isoformat()}
    def accounts_read_at(self): return NOW
    def inventory_snapshot(self, now): return NOW
    def automatic_link_evidence(self): return {(13, 100003): "b"*64}  # _lost_rows historically ignores auto evidence.
    def inventory_checks_on(self, today): return {}
    def performance_checks(self, now):
        return {cid: {"cadence": "daily", "stage_revision": "synthetic-current"} for cid in (100001, 100002)}
    def latest_inventory_successes(self): return {}
    def account_times(self): return deepcopy(self.time_rows)
    def board(self, actor=0, *, narrowed=False, now=NOW, **kw):
        org = O.parse_org_snapshot(self.org_body)
        ctx = W.InventoryCtx(now, now.date(), org, {}, deepcopy(self.accounts_value), tuple(deepcopy(self.decisions)))
        scope = SC.narrowed_scope_of(org, actor) if narrowed else SC.scope_of(org, actor)
        return I.board(ctx, self, scope, **kw)
    def inputs(self): return deepcopy(self.accounts_value), deepcopy(self.decisions), deepcopy(self.catalog)


class AbsentMatchingReuseTest(unittest.TestCase):
    def setUp(self):
        for obj, name in ((socket.socket, "connect"), (socket.socket, "connect_ex"),
                          (sqlite3, "connect"), (S, "open_reader"), (S, "open_writer")):
            guard = patch.object(obj, name, side_effect=AssertionError("DB/네트워크 금지"))
            guard.start(); self.addCleanup(guard.stop)
        self.store = ReadAdapter()
        self.addCleanup(lambda: setattr(MS, "_MATCH_MEMO", None))
        if hasattr(MS, "_ABSENT_MATCH_MEMO"):
            MS._ABSENT_MATCH_MEMO = None
            self.addCleanup(lambda: setattr(MS, "_ABSENT_MATCH_MEMO", None))
        MS._MATCH_MEMO = None

    def test_warm_board_does_not_recompute_absent_matching(self):
        with patch.object(I, "_matching", wraps=I._matching) as spy:
            first = self.store.board()
            cold = spy.call_count
            self.assertEqual(first["summary"]["lost_count"], 2)
            self.assertEqual(cold, 2)  # separate current and include-absent inputs
            self.assertEqual(self.store.board(), first)
            self.assertEqual(spy.call_count, cold, "부재 매칭을 매 요청 다시 계산합니다")

    def test_every_public_scope_filter_equals_direct_matching(self):
        for actor, narrowed in ((0, False), (100, False), (101, False), (0, True)):
            for kwargs in ({}, {"view": "lost"}, {"mapping": "matched"}, {"workflow": "계약만료", "view": "lost"},
                           {"selection": "me"}, {"selection": "person:100"} if actor == 0 and not narrowed else {}):
                with self.subTest(actor=actor, narrowed=narrowed, kwargs=kwargs):
                    expected = self.store.board(actor, narrowed=narrowed, **kwargs)
                    with patch.object(MS, "absent_matching_result", side_effect=direct):
                        self.assertEqual(self.store.board(actor, narrowed=narrowed, **kwargs), expected)
        self.assertEqual({r["possibility_id"] for r in self.store.board(100, view="lost")["rows"]}, {13})
        self.assertEqual(self.store.board(100, narrowed=True, view="lost")["rows"], self.store.board(100, view="lost")["rows"])

    def test_all_matcher_inputs_invalidate_and_equal_direct(self):
        def changed_accounts(a, d, c): a[100003]["account_name"] = "새합성상호"
        def changed_ad_number(a, d, c): a[100003]["ad_account_no"] = 9013
        def changed_present(a, d, c): a[100003]["present"] = 1
        def added_account(a, d, c): a[100005] = {"customer_id":100005,"present":0,"ad_account_no":9005,"account_name":"새합성계정"}
        def removed_account(a, d, c): del a[100003]
        def changed_account_order(a, d, c): a[100001] = a.pop(100001)
        def changed_decision_pid(a, d, c): d[0].possibility_id = 13
        def changed_decision_cid(a, d, c): d[0].customer_id = 100003
        def changed_decision_kind(a, d, c): d[0].decision = M.DECISION_REJECTED
        def added_decision(a, d, c): d.append(SimpleNamespace(possibility_id=13,customer_id=100003,decision=M.DECISION_CONFIRMED))
        def changed_decision_order(a, d, c): d.insert(0,SimpleNamespace(possibility_id=13,customer_id=100003,decision=M.DECISION_CONFIRMED))
        def changed_item_pid(a, d, c): c["items"][2]["possibility_id"] = 15
        def changed_item_name(a, d, c): c["items"][2]["company_name"] = "새합성업체"
        def changed_item_order(a, d, c): c["items"].reverse()
        def changed_id_pid(a, d, c): c["ids"][2]["possibility_id"] = 14
        def changed_id_vendor(a, d, c): c["ids"][2]["vendor"] = "other"
        def changed_id_customer(a, d, c): c["ids"][2]["customer_id_raw"] = "100004"
        def changed_id_ad_number(a, d, c): c["ids"][2]["ad_account_no_raw"] = "9003"
        def changed_id_order(a, d, c): c["ids"].reverse()
        for change in (changed_accounts,changed_ad_number,changed_present,added_account,removed_account,changed_account_order,
                       changed_decision_pid,changed_decision_cid,changed_decision_kind,added_decision,changed_decision_order,
                       changed_item_pid,changed_item_name,changed_item_order,changed_id_pid,changed_id_vendor,
                       changed_id_customer,changed_id_ad_number,changed_id_order):
            with self.subTest(change=change.__name__), patch.object(I, "_matching", wraps=I._matching) as spy:
                cached(*self.store.inputs())
                values = self.store.inputs(); change(*values)
                got = cached(*values)
                self.assertEqual(spy.call_count, 2)
                self.assertEqual((astuple(got[0]),got[1]),(astuple(direct(*values)[0]),direct(*values)[1]))

    def test_current_and_absent_memos_remain_separate(self):
        a,d,c = self.store.inputs()
        with patch.object(I, "_matching", wraps=I._matching) as spy:
            current = MS.matching_result(SimpleNamespace(),a,d,c,{})
            lost = cached(a,d,c)
            self.assertEqual(spy.call_count,2)
            self.assertEqual(MS.matching_result(SimpleNamespace(),a,d,c,{}),current)
            self.assertEqual(cached(a,d,c),lost)
            self.assertEqual(spy.call_count,2)
            self.assertNotEqual(astuple(current[0]),astuple(lost[0]))

    def test_mutable_possible_set_cannot_change_remembered_result(self):
        a,d,c = self.store.inputs(); c["ids"] = []
        with patch.object(I,"_matching",wraps=I._matching) as spy:
            result,possible = cached(a,d,c); expected=set(possible); possible.clear()
            again,possible2=cached(a,d,c)
            self.assertIs(again,result); self.assertEqual(possible2,expected)
            self.assertEqual(spy.call_count,1)
        with self.assertRaises(FrozenInstanceError): result.pairs=()

    def test_one_entry_replaces_previous_input(self):
        a,d,c = self.store.inputs(); second=deepcopy(c); second["items"][2]["company_name"]="다른합성상호"
        with patch.object(I,"_matching",wraps=I._matching) as spy:
            cached(a,d,c); cached(a,d,second); cached(a,d,c)
            self.assertEqual(spy.call_count,3)

    def test_actual_string_size_limit_falls_back_without_retaining_oversize(self):
        a,d,c = self.store.inputs()
        with patch.object(MS,"_ABSENT_MATCH_KEY_BYTES",1), patch.object(I,"_matching",wraps=I._matching) as spy:
            expected=direct(a,d,c)
            self.assertEqual(cached(a,d,c),expected); self.assertEqual(cached(a,d,c),expected)
            self.assertEqual(spy.call_count,3)
            self.assertIsNone(MS._ABSENT_MATCH_MEMO)

    def test_unicode_key_over_four_mib_uses_direct_result_and_retains_only_prior_small_entry(self):
        a,d,c = self.store.inputs()
        with patch.object(I,"_matching",wraps=I._matching) as spy:
            cached(a,d,c)
            small=MS._ABSENT_MATCH_MEMO
            self.assertLessEqual(sys.getsizeof(small[0]),4*1024*1024)
            c["items"].append({"possibility_id":15,"company_name":"합"*(2*1024*1024)})
            expected=direct(a,d,c)
            self.assertEqual(cached(a,d,c),expected)
            self.assertEqual(cached(a,d,c),expected)
            self.assertEqual(spy.call_count,4)
            self.assertIs(MS._ABSENT_MATCH_MEMO,small)

    def test_equal_but_wrong_type_and_errors_are_not_remembered(self):
        a,d,c = self.store.inputs(); cached(a,d,c); c["items"][2]["possibility_id"]=13.0
        with patch.object(I,"_matching",wraps=I._matching) as spy:
            for _ in range(2):
                with self.assertRaises(M.BadInput): cached(a,d,c)
            self.assertEqual(spy.call_count,2)

    def test_unkeyable_input_preserves_original_exception(self):
        a,d,c=self.store.inputs(); del a[100003]["present"]
        for fn in (direct,cached):
            with self.assertRaises(KeyError): fn(a,d,c)

    def test_replaced_functions_are_not_bypassed(self):
        a,d,c=self.store.inputs(); cached(a,d,c)
        for module,name in ((I,"_matching"),(M,"match"),(M,"loose_name")):
            with self.subTest(function=name), patch.object(module,name,wraps=getattr(module,name)) as spy:
                self.assertEqual(cached(a,d,c),direct(a,d,c)); self.assertGreater(spy.call_count,0)

    def test_absent_matching_keeps_original_none_auto_evidence(self):
        with patch.object(I,"_matching",wraps=I._matching) as spy:
            self.store.board(view="lost")
            lost=[call for call in spy.call_args_list if call.kwargs.get("include_absent")]
            self.assertEqual(len(lost),1)
            self.assertIsNone(lost[0].kwargs.get("auto_evidence"))

    def test_owner_sub_stage_hidden_and_freshness_revalidate_each_board(self):
        with patch.object(I,"_matching",wraps=I._matching) as spy:
            self.assertEqual({r["possibility_id"] for r in self.store.board(100,view="lost")["rows"]},{13})
            # Same org timestamp: ownership must change immediately while pure matching stays warm.
            self.store.org_body["owners"][2]=TA.owner(13,101,sub=100)
            self.assertEqual({r["possibility_id"] for r in self.store.board(101,view="lost")["rows"]},{13,14})
            self.store.org_body["owners"][2]=TA.owner(13,101)
            self.assertEqual(self.store.board(100,view="lost")["rows"],[])
            self.store.catalog["items"][2]["stage"]="환불완료"
            row=next(r for r in self.store.board(101,view="lost")["rows"] if r["possibility_id"]==13)
            self.assertEqual(row["workflow"],"환불완료")
            self.store.catalog["items"][2]["stage_hidden"]=True
            self.assertEqual({r["possibility_id"] for r in self.store.board(101,view="lost")["rows"]},{14})
            self.assertEqual(spy.call_count,2)
            stale=self.store.board(now=NOW+timedelta(days=4))
            self.assertFalse(stale["matching_ready"]); self.assertIsNone(stale["summary"]["lost_count"])
            self.assertTrue(all(not r["management"]["can_collect"] and not r["management"]["can_manage"] for r in stale["rows"]))

    def test_absence_threshold_is_recomputed_after_warm_matching(self):
        first=self.store.board(view="lost"); self.assertEqual(len(first["rows"]),2)
        self.store.time_rows[100003]["absent_days"]=1
        self.assertEqual({r["possibility_id"] for r in self.store.board(view="lost")["rows"]},{14})
        self.store.time_rows[100004]["absent_days"]=1
        with patch.object(I,"_matching",wraps=I._matching) as spy:
            self.assertEqual(self.store.board(view="lost")["rows"],[])
            self.assertEqual(spy.call_count,1)  # current matching only; no eligible absent computation

    def test_previous_owner_and_resigned_person_change_visibility_without_recomputing(self):
        with patch.object(I,"_matching",wraps=I._matching) as spy:
            self.store.board(100,view="lost")
            owner=TA.owner(13,None)
            owner.update(owner_source="prev",prev_manage_owner_idx=100)
            self.store.org_body["owners"][2]=owner
            row=self.store.board(100,view="lost")["rows"][0]
            self.assertEqual((row["possibility_id"],row["workflow"],row["owner"]["state"]),(13,"계약만료","prev"))
            next(p for p in self.store.org_body["employees"] if p["idx"]==100)["is_deleted"]=True
            self.assertEqual(self.store.board(100,view="lost")["rows"],[])
            self.assertEqual(self.store.board(100)["rows"],[])
            self.assertEqual(spy.call_count,2)

    def test_invalid_absent_account_still_marks_lost_summary_unavailable(self):
        self.store.board(); self.store.accounts_value[100003]["ad_account_no"]=9001
        out=self.store.board(view="lost")
        self.assertIsNone(out["summary"]["lost_count"])
        self.assertTrue(out["matching_ready"]); self.assertEqual(out["rows"],[])

    def test_concurrent_different_inputs_do_not_cross_results(self):
        a,d,c=self.store.inputs(); other=deepcopy(c); other["items"][2]["company_name"]="다른합성상호"
        original=I._matching; started,release=Event(),Event()
        def controlled(ctx,catalog,**kwargs):
            if catalog["items"][2]["company_name"]==c["items"][2]["company_name"]:
                started.set(); self.assertTrue(release.wait(5))
            return original(ctx,catalog,**kwargs)
        with patch.object(I,"_matching",side_effect=controlled):
            with ThreadPoolExecutor(max_workers=2) as workers:
                first=workers.submit(cached,a,d,c)
                try:
                    self.assertTrue(started.wait(5)); second=workers.submit(cached,a,d,other).result(5)
                finally: release.set()
                first=first.result(5)
        self.assertEqual(first,original(SimpleNamespace(accounts=a,live_decisions=d),c,include_absent=True))
        self.assertEqual(second,original(SimpleNamespace(accounts=a,live_decisions=d),other,include_absent=True))
        self.assertEqual(cached(a,d,other),second)


if __name__ == "__main__": unittest.main()
