"""실제 목록/성과 요청에서 사용하지 않는 구형 판정 원천을 읽지 않는다."""
import json
import sqlite3
import unittest
from unittest.mock import patch

from naver_engine import erp_read as E, naver_read as N, store as S, views as W
from naver_engine.tests import test_accounts_match_reuse as TM, test_alerts as TA
from naver_engine.tests import test_morning as MORNING


UNUSED_TABLES = frozenset({"naver_auto_pairing_run", "naver_auto_pairing_row",
                          "naver_auto_issue", "naver_auto_account_day"})


class InventoryContextTest(unittest.TestCase):
    def setUp(self):
        self.fixture = TM.AccountsMatchReuseTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store, self.clock = self.fixture.store, self.fixture.clock
        self.full_load = W.load

    def legacy(self, path, actor=0, narrowed=False):
        # 수정 전 loader를 같은 요청/Store/시각/권한에서 실행한다.
        with patch.object(W, "load_inventory", side_effect=self.full_load, create=True):
            return self.fixture.call(path, actor, narrowed=narrowed)

    def assert_legacy_parity(self):
        for actor, narrowed in ((0, False), (100, False), (101, False), (0, True)):
            for path in ("/accounts", "/accounts?mapping=matched", "/accounts?view=lost",
                         "/accounts?workflow=진행중", "/accounts?selection=person:100",
                         "/accounts?selection=person:101", "/accounts?selection=team:11",
                         "/dashboard", "/dashboard?selection=me",
                         "/dashboard?selection=person:100", "/dashboard?selection=team:11"):
                with self.subTest(actor=actor, narrowed=narrowed, path=path):
                    expected = self.legacy(path, actor, narrowed)
                    self.assertEqual(self.fixture.call(path, actor, narrowed=narrowed), expected)

    def forbid_unused_sql(self):
        original = self.fixture.app._open_read
        reads, refused = [], []
        def open_read():
            store = original()
            def authorize(operation, table, column, database, trigger):
                if operation == sqlite3.SQLITE_READ:
                    reads.append(table)
                    if table in UNUSED_TABLES:
                        refused.append(table)
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            store._conn.set_authorizer(authorize)
            return store
        return patch.object(self.fixture.app, "_open_read", side_effect=open_read), reads, refused

    def test_real_accounts_and_dashboard_never_read_unused_tables(self):
        guard, reads, refused = self.forbid_unused_sql()
        with guard:
            for path in ("/accounts", "/dashboard"):
                for actor in (0, 100, 101):
                    with self.subTest(path=path, actor=actor):
                        status, body = self.fixture.call(path, actor)
                        self.assertEqual(status, 200, body)
        self.assertFalse(refused)
        self.assertTrue({"naver_auto_account", "naver_auto_meta", "naver_auto_org",
                         "naver_auto_link_decision", "naver_auto_prospect"}.issubset(reads))

    def heavy_unused_sources(self, count=1200):
        conn, now = self.store._conn, self.clock.now()
        at, today = now.isoformat(), str(now.date())
        cur = conn.execute("""INSERT INTO naver_auto_pairing_run
            (at,outcome,codes,accounts_read_at,stages_as_of,decisions_hash,counts)
            VALUES(?,'accepted','[]',?,?,NULL,'{}')""", (at, at, at))
        run_id = cur.lastrowid
        conn.executemany("""INSERT INTO naver_auto_pairing_row
            (pairing_id,possibility_id,customer_id,state,code)
            VALUES(?,?,NULL,'missing','not-linked')""",
            ((run_id, 900000+n) for n in range(count)))
        facts = json.dumps({"synthetic": "x"*4096})
        conn.executemany("""INSERT INTO naver_auto_issue
            (possibility_id,code,target,customer_id,rule,severity,state,first_seen_on,last_seen_on,updated_at,facts)
            VALUES(?,'synthetic','synthetic',?,'synthetic','info','new',?,?,?,?)""",
            ((900000+n, 900000+n, today, today, at, facts) for n in range(count)))
        conn.executemany("""INSERT INTO naver_auto_account_day
            (customer_id,day,status,possibility_id,rules_not_run,rules_run,run_id,checked_at)
            VALUES(?,?,'ok',?,'[]','[]',1,?)""", ((900000+n, today, 900000+n, at) for n in range(count)))

    def test_heavy_legacy_sources_do_not_change_business_bytes_or_get_read(self):
        before = {path: self.fixture.call(path) for path in ("/accounts", "/dashboard")}
        self.heavy_unused_sources()
        for path, expected in before.items():
            self.assertEqual(self.legacy(path), expected)
        guard, _, refused = self.forbid_unused_sql()
        with guard:
            for path, expected in before.items():
                got = self.fixture.call(path)
                self.assertEqual(got, expected)
                self.assertEqual(json.dumps(got, ensure_ascii=False, sort_keys=True).encode(),
                                 json.dumps(expected, ensure_ascii=False, sort_keys=True).encode())
        self.assertFalse(refused)

    def test_all_existing_scope_filter_and_narrowed_business_results_equal_full_loader(self):
        self.assert_legacy_parity()

    def test_current_owner_hidden_unknown_and_stale_org_keep_full_loader_rules(self):
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 101), TA.owner(12, 101),
                                                     TA.owner(13, 100), TA.owner(14, 101)]), now)
        self.assertEqual(self.fixture.call("/accounts", 100)[1]["rows"], [])
        self.assert_legacy_parity()
        catalog = self.store.account_catalog()
        for flags in ({"stage_hidden": True}, {"stage_known": False}):
            items = [{**row, **flags} if row["possibility_id"] == 11 else row for row in catalog["items"]]
            self.store.record_account_catalog({"generated_at": now.isoformat(), "total": len(items),
                "complete": True, "items": items}, self.fixture.ids, now)
            self.assertEqual(len(self.fixture.call("/accounts", 101)[1]["rows"]), 1)
            self.assert_legacy_parity()
        self.clock.advance(60*60*31)
        self.assert_legacy_parity()

    def test_present_prospect_detail_flag_and_absent_accounts_keep_full_loader_results(self):
        now = self.clock.now()
        self.store.record_prospects(E.StageSnapshot({11: MORNING.srow(11, name="합성업체")}, now, {}, ()))
        matched = self.fixture.call("/accounts")[1]["rows"]
        self.assertTrue(next(row for row in matched if row["possibility_id"] == 11)["detail_available"])
        self.assert_legacy_parity()
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_prospects(E.StageSnapshot({12: MORNING.srow(12, name="별도합성업체")}, now, {}, ()))
        matched = self.fixture.call("/accounts")[1]["rows"]
        self.assertFalse(next(row for row in matched if row["possibility_id"] == 11)["detail_available"])
        self.assert_legacy_parity()
        accounts = self.store.accounts()
        current = {r["customer_id"]: {"customerId": r["customer_id"], "adAccountNo": r["ad_account_no"],
            "adAccountName": r["account_name"]} for r in accounts[1:]}
        self.store.record_accounts(N.ChildAccounts(current, {1: len(current)}, ()), now)
        self.assert_legacy_parity()

    def test_active_holding_expired_and_refunded_contract_policy_bytes_stay_equal(self):
        before = self.store.link_decisions()
        catalog = self.store.account_catalog()
        for stage, workflow in (("진행중", "진행중"), ("홀딩중", "홀딩중"),
                                ("계약 만료", "계약만료"), ("환불 완료", "환불완료")):
            with self.subTest(stage=stage):
                self.clock.advance(1)
                now = self.clock.now()
                items = [{**row, "stage": stage} if row["possibility_id"] == 11 else row
                         for row in catalog["items"]]
                self.store.record_account_catalog({"generated_at": now.isoformat(), "total": len(items),
                    "complete": True, "items": items}, self.fixture.ids, now)
                for path in ("/accounts", "/dashboard"):
                    for actor in (0, 100, 101):
                        self.assertEqual(self.fixture.call(path, actor), self.legacy(path, actor))
                rows = self.fixture.call("/accounts")[1]["rows"]
                self.assertEqual(next(r for r in rows if r["possibility_id"] == 11)["workflow"], workflow)
                self.assertEqual(self.store.link_decisions(), before)

    def test_view_sync_same_cursor_and_business_payload_keep_rebuilding_current_scope(self):
        for path in ("/accounts", "/dashboard"):
            first = self.fixture.call(path+"?view_sync=1")[1]
            query = path+"?view_sync=1&view_cursor="+first["cursor"]
            legacy = self.legacy(query)[1]
            actual = self.fixture.call(query)[1]
            legacy.pop("_request_timing", None)
            actual.pop("_request_timing", None)
            self.assertEqual(actual, legacy)
            self.assertEqual(actual["mode"], "unchanged")
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 101), TA.owner(12, 101)]), now)
        self.assertEqual(self.fixture.call("/accounts", 100)[1]["rows"], [])

    def test_other_surfaces_keep_full_context_loader(self):
        with patch.object(W, "load", wraps=self.full_load) as full:
            self.assertEqual(self.fixture.call("/board")[0], 200)
            self.assertEqual(full.call_count, 1)


if __name__ == "__main__":
    unittest.main()
