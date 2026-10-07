"""목록/직원 수의 순수 매칭 재사용. 실제 WSGI·메모리 Store, 외부 연결·쓰기는 없다."""
import io
import json
import socket
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.naver_auto import matching as M, scope as SC
from naver_engine import erp_read as E, inventory as I, management_store as MS, naver_read as N
from naver_engine import session as SE, store as S, views as W, web as WEB
from naver_engine.credentials import Secret
from naver_engine.tests import test_account_catalog as TC, test_alerts as TA
from naver_engine.tests.test_catalog_links import make_fixture
from naver_engine.tests.test_inventory_name_index import scene


def direct_matching(store, accounts, decisions, catalog, evidence, *, candidate_counts=None):
    return I._matching(SimpleNamespace(accounts=accounts, live_decisions=decisions), catalog,
                       auto_evidence=evidence, candidate_counts=candidate_counts)


class AccountsMatchReuseTest(unittest.TestCase):
    def setUp(self):
        for name in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, name, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        fixture = make_fixture(accounts=6, managed=2, campaigns=0)
        self.store, self.clock = fixture.store, fixture.clock
        self.addCleanup(self.store.close)
        self.clock.advance(1)
        now = self.clock.now()
        accounts = self.store.accounts()
        catalog = self.store.account_catalog()
        items = catalog["items"] + [TC.company(13, "진행중", company_name=accounts[2]["account_name"]),
                                    TC.company(14, "진행중", company_name=accounts[3]["account_name"][:8])]
        self.ids = [E.NaverIdRow(r["possibility_id"], r["vendor"], r["customer_id_raw"],
                               ad_account_no_raw=r["ad_account_no_raw"]) for r in catalog["ids"]]
        self.store.record_account_catalog({"generated_at": now.isoformat(), "total": len(items),
            "complete": True, "items": items}, self.ids, now)
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 100), TA.owner(12, 101),
                                                      TA.owner(13, 100), TA.owner(14, 101)]), now)
        self.signer = SE.TokenSigner(Secret("synthetic-list-match-key-" * 3))
        def open_read():
            conn = sqlite3.connect(":memory:", isolation_level=None)
            self.store._conn.backup(conn)
            return S.Store(conn, ":memory:", None, writer=False, clock=self.clock.now)
        def no_write(_):
            raise AssertionError("목록/직원 수 GET 쓰기 금지")
        self.app = WEB.App(open_read=open_read, write=no_write, signer=self.signer, profiles=None,
            clock=self.clock.now, owner_verification=True, verified_linking=True)

    def call(self, path, actor=0, *, narrowed=False):
        status = []
        body = self.app({"REQUEST_METHOD": "GET", "PATH_INFO": WEB.PREFIX + path.partition("?")[0],
            "QUERY_STRING": path.partition("?")[2], "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(),
            "HTTP_AUTHORIZATION": "Bearer " + self.signer.issue(actor, self.clock.now(), narrowed=narrowed)},
            lambda value, headers: status.append(int(value.split()[0])))
        return status[0], json.loads(b"".join(body))

    def test_accounts_compute_same_matching_once_per_request(self):
        with patch.object(I, "_matching", wraps=I._matching) as matching:
            status, result = self.call("/accounts")
        self.assertEqual(status, 200)
        self.assertEqual(len(result["rows"]), 6)
        self.assertTrue(result["matching_ready"])
        self.assertEqual(matching.call_count, 1, "동일 입력의 목록/관리 판정 매칭이 중복됩니다")

    def test_me_compute_same_matching_once_per_request(self):
        with patch.object(I, "_matching", wraps=I._matching) as matching:
            status, result = self.call("/me")
        self.assertEqual(status, 200)
        self.assertTrue(result["inventory_enabled"])
        self.assertEqual(matching.call_count, 1, "직원별 계정 수에서도 같은 매칭이 중복됩니다")

    def board(self, actor=0):
        ctx = W.load(self.store, self.clock.now())
        return I.board(ctx, self.store, SC.scope_of(ctx.org, actor))

    def test_public_output_equals_uncached_matching_for_each_scope_and_filter(self):
        for actor, narrowed in ((0, False), (100, False), (101, False), (0, True)):
            for path in ("/accounts", "/accounts?mapping=matched", "/accounts?view=lost", "/me"):
                with self.subTest(actor=actor, narrowed=narrowed, path=path):
                    with patch.object(MS, "matching_result", side_effect=direct_matching):
                        expected = self.call(path, actor, narrowed=narrowed)
                    self.assertEqual(self.call(path, actor, narrowed=narrowed), expected)
        for actor, pid in ((100, 11), (101, 12)):
            self.assertEqual({r["possibility_id"] for r in self.call("/accounts", actor)[1]["rows"]}, {pid})
            people = self.call("/me", actor)[1]["people"]
            self.assertEqual([(p["idx"], p["account_count"]) for p in people], [(actor, 1)])

    def test_new_request_reader_does_not_reuse_the_previous_reader(self):
        with patch.object(I, "_matching", wraps=I._matching) as matching:
            self.assertEqual(self.call("/accounts")[0], 200)
            self.assertEqual(matching.call_count, 1)
            self.assertEqual(self.call("/me")[0], 200)
            self.assertEqual(matching.call_count, 2)

    def test_management_then_board_and_board_then_management_keep_the_same_output(self):
        for first in ("management", "board"):
            with self.subTest(first=first):
                if hasattr(self.store, "_management_match_memo"):
                    del self.store._management_match_memo
                with patch.object(I, "_matching", wraps=I._matching) as matching:
                    if first == "management":
                        policies = MS.snapshot(self.store, self.clock.now())
                        got = self.board()
                    else:
                        got = self.board()
                        policies = MS.snapshot(self.store, self.clock.now())
                    self.assertEqual(matching.call_count, 1)
                with patch.object(MS, "matching_result", side_effect=direct_matching):
                    self.assertEqual(got, self.board())
                    self.assertEqual(policies, MS.snapshot(self.store, self.clock.now()))
                candidates = {r["possibility_id"]: r["candidate_count"] for r in got["managed_coverage"]["items"]}
                self.assertEqual((candidates[13], candidates[14]), (1, 1))

    def test_changed_decision_in_same_store_recomputes_and_matches_uncached(self):
        with patch.object(I, "_matching", wraps=I._matching) as matching:
            original = self.board()
            self.assertEqual(matching.call_count, 1)
            self.clock.advance(1)
            self.store.record_decision(11, self.store.accounts()[0]["customer_id"], "rejected", 0, self.clock.now())
            changed = self.board()
            self.assertEqual(matching.call_count, 2)
        self.assertNotEqual(changed, original)
        with patch.object(MS, "matching_result", side_effect=direct_matching):
            self.assertEqual(changed, self.board())

    def test_owner_stage_and_freshness_are_rechecked_when_pure_matching_is_reused(self):
        with patch.object(I, "_matching", wraps=I._matching) as matching:
            self.assertEqual(len(self.board(100)["rows"]), 1)
            self.clock.advance(1)
            now = self.clock.now()
            self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 101), TA.owner(12, 101),
                                                          TA.owner(13, 100), TA.owner(14, 101)]), now)
            self.assertEqual(self.board(100)["rows"], [])
            self.assertEqual(len(self.board(101)["rows"]), 2)
            catalog = self.store.account_catalog()
            items = [{**r, "stage_hidden": True} if r["possibility_id"] == 11 else r for r in catalog["items"]]
            self.store.record_account_catalog({"generated_at": now.isoformat(), "total": len(items),
                "complete": True, "items": items}, self.ids, now)
            self.assertEqual({r["possibility_id"] for r in self.board(101)["rows"]}, {12})
            self.assertEqual(matching.call_count, 1)
            self.store.record_account_catalog_failure(now, "CATALOG_FAILED")
            stale = self.board()
            self.assertFalse(stale["matching_ready"])
            self.assertTrue(all(not r["management"]["can_manage"] and not r["management"]["can_collect"]
                                for r in stale["rows"]))
        with patch.object(MS, "matching_result", side_effect=direct_matching):
            self.assertEqual(stale, self.board())

    def test_candidate_metadata_is_complete_and_cannot_be_mutated_by_callers(self):
        ctx, catalog = scene(["합성후보"], ["합성후보상점" + str(n) for n in range(8)])
        store = SimpleNamespace()
        with patch.object(I, "_matching", wraps=I._matching) as matching:
            # 관리 판정이 먼저 기억한 경우에도 목록의 전체 후보 수가 있어야 한다.
            pure = MS._matched(store, ctx.accounts, [], catalog, {})
            counts = {}
            result, possible = MS.matching_result(store, ctx.accounts, [], catalog, {}, candidate_counts=counts)
            self.assertIs(result, pure)
            self.assertEqual(len(result.candidates), M.CANDIDATE_MAX)
            self.assertEqual(counts, {1: 8})
            self.assertEqual(len(possible), 8)
            counts.clear()
            possible.clear()
            result2, possible2 = MS.matching_result(store, ctx.accounts, [], catalog, {}, candidate_counts=counts)
            self.assertIs(result2, result)
            self.assertEqual(counts, {1: 8})
            self.assertEqual(len(possible2), 8)
            self.assertEqual(matching.call_count, 1)

    def test_lost_account_uses_separate_matching_and_keeps_staff_scope(self):
        accounts = self.store.accounts()[1:]
        for hours in (1, 24):
            self.clock.advance(hours * 3600)
            now = self.clock.now()
            self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 100), TA.owner(12, 101)]), now)
            self.store.record_accounts(N.ChildAccounts({r["customer_id"]: {
                "customerId": r["customer_id"], "adAccountNo": r["ad_account_no"],
                "adAccountName": r["account_name"]} for r in accounts}, {1: len(accounts)}, ()), now)
            catalog = self.store.account_catalog()
            self.store.record_account_catalog({"generated_at": now.isoformat(), "total": len(catalog["items"]),
                "complete": True, "items": catalog["items"]}, self.ids, now)
        with patch.object(I, "_matching", wraps=I._matching) as matching:
            got = self.call("/accounts?view=lost", 100)
            self.assertEqual(matching.call_count, 2)
            self.assertEqual(sum(c.kwargs.get("include_absent", False) for c in matching.call_args_list), 1)
        self.assertEqual(got[0], 200)
        self.assertEqual([r["possibility_id"] for r in got[1]["rows"]], [11])
        self.assertEqual(self.call("/accounts?view=lost", 101)[1]["rows"], [])
        with patch.object(MS, "matching_result", side_effect=direct_matching):
            self.assertEqual(got, self.call("/accounts?view=lost", 100))
