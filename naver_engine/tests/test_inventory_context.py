"""실제 목록/성과 요청에서 사용하지 않는 구형 판정 원천을 읽지 않는다."""
import json
import sqlite3
import unittest
from dataclasses import replace
from unittest.mock import patch

from app.naver_auto import org_snapshot as O, scope as SC
from naver_engine import erp_read as E, inventory as I, naver_read as N, store as S, sync as Y, views as W, web as WEB
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
        if path.partition("?")[0] == "/me":
            routes = tuple(replace(route, handler=self.legacy_me) if route.pattern.fullmatch("/me") else route
                           for route in WEB.ROUTES)
            with patch.object(WEB, "ROUTES", routes):
                return self.fixture.call(path, actor, narrowed=narrowed)
        # 구형 reference는 계측 adapter를 거치지 않고 원래 Reader로 full loader를 실행한다.
        with patch.object(W, "load_inventory", side_effect=self.full_load, create=True), \
                patch.object(WEB, "_TimedReadStore", side_effect=lambda store, timings: store):
            return self.fixture.call(path, actor, narrowed=narrowed)

    def legacy_me(self, app, req, viewer, now):
        # source277의 기존 /me 조립. 신선도 Store 읽기도 원래 Ctx에서 한 번만 수행한다.
        ctx = viewer.ctx(now)
        out = W.me(ctx, viewer.scope)
        counts = I.staff_counts(ctx, viewer.store, viewer.scope)
        for person in out["people"]:
            person["account_count"] = counts.get(person["idx"], 0)
        out["inventory_enabled"] = True
        out["bell_unread"] = W.bell(viewer.store, viewer.idx, now)["unread"]
        if app._owner_verification:
            out["owner_verification"] = True
        if app._owner_actions:
            out["owner_actions"] = True
        out["verified_linking"] = app._verified_linking and viewer.scope.kind in (SC.ALL, SC.MINE)
        return 200, out

    def assert_legacy_parity(self):
        for actor, narrowed in ((0, False), (100, False), (101, False), (0, True)):
            for path in ("/me", "/me?as=100", "/accounts", "/accounts?mapping=matched", "/accounts?view=lost",
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

    def test_real_me_never_reads_unused_legacy_tables(self):
        expected = {actor: self.fixture.call("/me", actor) for actor in (0, 100, 101)}
        guard, reads, refused = self.forbid_unused_sql()
        with guard:
            for actor, before in expected.items():
                with self.subTest(actor=actor):
                    self.assertEqual(before[0], 200)
                    self.assertEqual(self.fixture.call("/me", actor), before)
        self.assertFalse(refused)
        self.assertTrue({"naver_auto_org", "naver_auto_account", "naver_auto_meta",
                         "naver_auto_link_decision"}.issubset(reads))

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
        before = {path: self.fixture.call(path) for path in ("/accounts", "/dashboard", "/me")}
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

    def test_me_roster_flags_and_personal_bell_keep_full_legacy_payload(self):
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 100), TA.owner(12, 101),
            TA.owner(13, 100), TA.owner(14, 101)], extra_people=(TA.emp(102, "합성영업", 11, management=False),
            TA.emp(103, "합성퇴사", 11, status="RESIGNED"))), now)
        self.store.record_alert(S.ALERT_DIGEST, now.date(), "compose", "digest", (), "/naver/issues",
            [{"emp_idx": who, "severity": "NORMAL", "params": {"red": 1, "yellow": 2}}
             for who in (0, 100)], now)
        for verification, actions, linking in ((False, False, False), (True, False, True), (True, True, True)):
            with patch.object(self.fixture.app, "_owner_verification", verification), \
                    patch.object(self.fixture.app, "_owner_actions", actions), \
                    patch.object(self.fixture.app, "_verified_linking", linking):
                for actor, narrowed in ((0, False), (100, False), (101, False), (0, True)):
                    with self.subTest(actor=actor, narrowed=narrowed, verification=verification,
                                      actions=actions, linking=linking):
                        before = self.legacy("/me", actor, narrowed)
                        actual = self.fixture.call("/me", actor, narrowed=narrowed)
                        self.assertEqual(actual, before)
                        self.assertEqual(actual[0], 200)
                        body = actual[1]
                        self.assertEqual(body["bell_unread"], int(actor in (0, 100)))
                        self.assertNotIn(102, {person["idx"] for person in body["people"]})
                        self.assertNotIn(103, {person["idx"] for person in body["people"]})
                        self.assertEqual(json.dumps(actual, ensure_ascii=False, sort_keys=True).encode(),
                                         json.dumps(before, ensure_ascii=False, sort_keys=True).encode())

    def test_me_preserves_store_freshness_failures_and_missing_source_display(self):
        original = self.fixture.app._open_read
        def faulty_reader(mode, failing_at, persistent=False):
            def open_read():
                store = original()
                current, last_sync, calls = store.org_current, store.last_sync, 0
                def org_current():
                    nonlocal calls
                    calls += 1
                    if calls < failing_at or (calls > failing_at and not persistent):
                        return current()  # 권한 검증·뒤의 bell 읽기는 정상. 표시용 읽기만 실패한다.
                    if mode == "read-error":
                        raise S.StoreError("synthetic")
                    if mode == "corrupt-body":
                        return {**current(), "body": {}}
                    def missing_history(*args):
                        store.last_sync = last_sync  # 표시용 신선도 읽기 한 번에만 주입한다.
                        if mode == "missing-never":
                            return None
                        if mode == "missing-accepted":
                            return {"outcome": S.SYNC_ACCEPTED}
                        raise S.StoreError("synthetic")
                    store.last_sync = missing_history
                    return None
                store.org_current = org_current
                return store
            return open_read
        for mode in ("read-error", "corrupt-body", "missing-never", "missing-accepted", "missing-history-error"):
            for actor, narrowed in ((0, False), (100, False), (101, False), (0, True)):
                failing_at = 2 if actor == 0 else 3  # 대표는 좁힌 토큰이어도 기존 SC.ALL이다.
                with patch.object(self.fixture.app, "_open_read", side_effect=faulty_reader(mode, failing_at)):
                    with self.subTest(mode=mode, actor=actor, narrowed=narrowed):
                        before = self.legacy("/me", actor, narrowed)
                        actual = self.fixture.call("/me", actor, narrowed=narrowed)
                        self.assertEqual(actual, before)
                        self.assertEqual(actual[0], 200)
                        self.assertEqual(actual[1]["org_freshness"],
                                         O.FRESH_NONE if mode == "missing-never" else O.FRESH_STALE)
        # 조직 읽기가 계속 실패하면 bell의 필수 읽기도 거절한다. 기존503을 유지한다.
        for actor, narrowed in ((0, False), (100, False), (0, True)):
            failing_at = 2 if actor == 0 else 3
            with patch.object(self.fixture.app, "_open_read", side_effect=faulty_reader("read-error", failing_at, True)):
                self.assertEqual(self.fixture.call("/me", actor, narrowed=narrowed),
                                 self.legacy("/me", actor, narrowed))
                self.assertEqual(self.fixture.call("/me", actor, narrowed=narrowed),
                                 (503, {"error": "org-unavailable"}))

    def test_me_freshness_rule_is_request_local_and_other_lean_routes_do_not_read_it(self):
        with patch.object(Y, "org_freshness", wraps=Y.org_freshness) as freshness:
            for path in ("/accounts", "/dashboard"):
                self.assertEqual(self.fixture.call(path)[0], 200)
            self.assertEqual(freshness.call_count, 0)
            for actor in (0, 100, 101):
                before = freshness.call_count
                self.assertEqual(self.fixture.call("/me", actor)[0], 200)
                # 직원은 기존 viewer 권한 신선도 검사1회 + me 표시1회. 대표는 표시1회.
                self.assertEqual(freshness.call_count-before, 1 if actor == 0 else 2)
        ctx = self.full_load(self.store, self.clock.now())
        scope = SC.scope_of(ctx.org, 0)
        self.assertEqual(W.me(ctx, scope), W.me(ctx, scope, freshness=ctx.freshness))

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
                for path in ("/accounts", "/dashboard", "/me"):
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
        self.assertEqual(self.fixture.call("/me?view_sync=1"), (400, {"error": "bad-query"}))

    def test_other_surfaces_keep_full_context_loader(self):
        with patch.object(W, "load", wraps=self.full_load) as full:
            self.assertEqual(self.fixture.call("/board")[0], 200)
            self.assertEqual(full.call_count, 1)


if __name__ == "__main__":
    unittest.main()
