"""실제 공개 WSGI·Store의 catalog 연결 회귀. 외부 송신/운영 쓰기는 없다."""
import io
import json
from pathlib import Path
import runpy
import socket
import sqlite3
import unittest
from datetime import timedelta
from unittest.mock import patch

from naver_engine.tests import test_morning as TM, test_account_catalog as TC, test_alerts as TA
from naver_engine import erp_read as E, links as L, naver_read as N, session as SE
from naver_engine import store as S, web as WEB
from naver_engine.credentials import Secret
from app.naver_auto import matching as M


ROOT = Path(__file__).resolve().parents[2]
make_fixture = runpy.run_path(str(ROOT / "tools/naver-store-selection-benchmark.py"))["make_fixture"]


class CatalogLinksTest(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        fixture = make_fixture(accounts=1, managed=1, campaigns=0)
        self.store, self.clock = fixture.store, fixture.clock
        self.addCleanup(self.store.close)
        now = self.clock.now()
        for decision in self.store.link_decisions()[0]:
            self.store.revoke_decision(decision.decision_id, 0, now, "합성 미확정 사례")
        self.ids = [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))]
        self.company_name = "합성전산상호"
        self.save_catalog([TC.company(11, "진행중", company_name=self.company_name)])
        self.store.record_prospects(E.StageSnapshot({12: TM.srow(12, name="별도합성업체")}, now, {}, ()))
        self.pair()
        self.signer = SE.TokenSigner(Secret("t" * 40))
        self.before_write = lambda: None
        def write(fn):
            self.before_write()
            return fn(self.store)
        def open_read():
            connection = sqlite3.connect(":memory:", isolation_level=None)
            self.store._conn.backup(connection)
            return S.Store(connection, ":memory:", None, writer=False, clock=self.clock.now)
        self.app = WEB.App(open_read=open_read, write=write, signer=self.signer,
            profiles=None, clock=self.clock.now, owner_verification=True, verified_linking=True)

    def save_catalog(self, rows=None, ids=None):
        current = self.store.account_catalog()
        self.store.record_account_catalog({"generated_at": self.clock.now().isoformat(),
            "total": len(rows if rows is not None else current["items"]), "complete": True,
            "items": rows if rows is not None else current["items"]},
            self.ids if ids is None else ids, self.clock.now())

    def pair(self):
        result = L.pair_links(TM.FakeErp(self.ids), self.store, self.clock.now())
        self.assertEqual(result.outcome, S.SYNC_ACCEPTED)

    def call(self, method, path, actor=0, body=None, narrowed=False):
        data = b"" if body is None else json.dumps(body).encode()
        status = []
        output = self.app({"REQUEST_METHOD": method, "PATH_INFO": WEB.PREFIX + path.partition("?")[0],
            "QUERY_STRING": path.partition("?")[2], "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(data)),
            "HTTP_AUTHORIZATION": "Bearer " + self.signer.issue(actor, self.clock.now(), narrowed=narrowed),
            "wsgi.input": io.BytesIO(data)}, lambda value, headers: status.append(int(value.split()[0])))
        return status[0], json.loads(b"".join(output))

    def pending(self, actor=0, narrowed=False, selection="all"):
        status, data = self.call("GET", "/links/pending?selection=" + selection, actor, narrowed=narrowed)
        self.assertEqual(status, 200, data)
        return data

    def confirm(self, rows, actor=0, proof="8000000", narrowed=False, selection="all"):
        body = {"refs": [r["ref"] for r in rows]}
        if selection != "all":
            body["selection"] = selection
        if proof is not None:
            body["ad_account_no"] = proof
        return self.call("POST", "/links/confirm", actor, body, narrowed=narrowed)

    def test_catalog_only_company_is_in_both_public_surfaces(self):
        status, inventory = self.call("GET", "/accounts")
        self.assertEqual(status, 200)
        coverage = inventory["managed_coverage"]
        self.assertEqual((coverage["total"], coverage["matched"], coverage["missing"]), (1, 0, 1))
        self.assertIn("name-different", coverage["items"][0]["codes"])
        pending = self.pending()
        self.assertEqual([r["possibility_id"] for r in pending["rows"]], [11])
        self.assertEqual(pending["source"], "catalog")
        row = pending["rows"][0]
        self.assertEqual((row["code"], row["can_confirm"], row["can_reject"]),
                         ("name-different", True, False))
        self.assertFalse(row["detail_available"])

    def test_owner_confirms_catalog_only_pair_without_inserting_legacy_prospect(self):
        rows = self.pending(100)["rows"]
        self.assertEqual([r["possibility_id"] for r in rows], [11])
        self.assertEqual(self.pending(101)["rows"], [])
        before = (self.store.prospects(), self.store.last_pairing())
        self.assertEqual(self.confirm(rows, 100), (200, {"decided": 1, "decision": "confirmed"}))
        self.assertEqual(before, (self.store.prospects(), self.store.last_pairing()))
        decisions = self.store.current_decisions()
        self.assertEqual([(d.possibility_id, d.customer_id, d.decided_by) for d in decisions], [(11, TM.A, 100)])
        self.assertFalse(any(r["can_confirm"] for r in self.pending(100)["rows"]))

    def test_different_name_needs_single_exact_ad_account_number(self):
        rows = self.pending()["rows"]
        before = self.store.link_decisions()
        for proof in (None, "1", str(TM.A), True, 8000000, "08000000", "8000000 "):
            with self.subTest(proof=proof):
                self.assertEqual(self.confirm(rows, proof=proof)[0], 409)
                self.assertEqual(before, self.store.link_decisions())
        self.assertEqual(self.confirm(rows)[0], 200)

    def test_actor_and_narrowed_scope_cannot_reuse_another_ref(self):
        rows = self.pending()["rows"]
        before = self.store.link_decisions()
        for actor, narrowed in ((100, False), (101, False), (0, True)):
            with self.subTest(actor=actor, narrowed=narrowed):
                self.assertIn(self.confirm(rows, actor, narrowed=narrowed)[0], (403, 404))
                self.assertEqual(before, self.store.link_decisions())
        self.assertEqual(self.confirm(self.pending(100)["rows"], 100)[0], 200)

    def test_pair_key_is_stable_but_is_not_a_confirmation_token(self):
        row = self.pending()["rows"][0]
        self.assertEqual(row["pair_key"], self.pending(100)["rows"][0]["pair_key"])
        self.assertNotEqual(row["ref"], self.pending(100)["rows"][0]["ref"])
        before = self.store.link_decisions()
        self.assertEqual(self.confirm([{**row, "ref": row["pair_key"]}])[0], 404)
        self.assertEqual(before, self.store.link_decisions())

    def test_same_catalog_timestamp_but_changed_content_invalidates_ref(self):
        for change in ("name", "id", "stage", "hidden"):
            with self.subTest(change=change):
                rows = self.pending()["rows"]
                self.assertTrue(rows)
                before = self.store.link_decisions()
                item = TC.company(11, "진행중", company_name=self.company_name)
                ids = self.ids
                if change == "name":
                    item["company_name"] += "변경"
                elif change == "id":
                    ids = [E.NaverIdRow(11, M.VENDOR_NAVER, None, "8000000")]
                elif change == "stage":
                    item["stage"] = "사후관리"
                else:
                    item["stage_hidden"] = True
                self.save_catalog([item], ids)
                self.assertIn(self.confirm(rows)[0], (404, 409))
                self.assertEqual(before, self.store.link_decisions())
                self.save_catalog([TC.company(11, "진행중", company_name=self.company_name)])

    def test_changed_accounts_invalidates_ref_but_keeps_display_pair_key(self):
        row = self.pending()["rows"][0]
        before = self.store.link_decisions()
        self.clock.advance(1)
        self.store.record_accounts(N.ChildAccounts({TM.A: {"customerId": TM.A,
            "adAccountNo": 8000000, "adAccountName": "새합성별칭"}}, {1: 1}, ()), self.clock.now())
        self.assertEqual(self.confirm([row])[0], 404)
        self.assertEqual(before, self.store.link_decisions())
        self.assertNotEqual(row["ref"], self.pending()["rows"][0]["ref"])
        self.assertEqual(row["pair_key"], self.pending()["rows"][0]["pair_key"])

    def test_owner_changed_in_write_queue_refuses_old_scope(self):
        rows = self.pending(100)["rows"]
        before = self.store.link_decisions()
        def change_owner():
            self.clock.advance(1)
            self.store.record_org(TA.org_body(self.clock.now(), owners=[TA.owner(11, 101)]), self.clock.now())
            self.before_write = lambda: None
        self.before_write = change_owner
        self.assertIn(self.confirm(rows, 100)[0], (403, 404))
        self.assertEqual(before, self.store.link_decisions())
        self.assertEqual(self.pending(100)["rows"], [])
        self.assertTrue(self.pending(101)["rows"])

    def test_transaction_guard_refuses_change_after_request_validation(self):
        rows = self.pending()["rows"]
        before = self.store.link_decisions()
        record = self.store.record_decisions
        def racing_record(*args, **kwargs):
            self.save_catalog([TC.company(11, "진행중", company_name="검사후변경")])
            return record(*args, **kwargs)
        with patch.object(self.store, "record_decisions", side_effect=racing_record):
            self.assertEqual(self.confirm(rows)[0], 409)
        self.assertEqual(before, self.store.link_decisions())
        self.assertFalse(self.store._conn.in_transaction)

    def test_catalog_failed_or_stale_never_falls_back_to_legacy(self):
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_prospects(E.StageSnapshot({11: TM.srow(11, name=self.company_name),
            12: TM.srow(12, name="다른합성")}, now, {}, ()))
        self.pair()
        rows = self.pending()["rows"]
        before = self.store.link_decisions()
        self.store.record_account_catalog_failure(now, "CATALOG_FAILED")
        failed = self.pending()
        self.assertEqual(failed["source"], "catalog")
        self.assertEqual(failed["source_state"], "failed")
        self.assertFalse(any(r["can_confirm"] for r in failed["rows"]))
        self.assertIn(self.confirm(rows)[0], (404, 409))
        self.save_catalog()
        rows = self.pending()["rows"]
        self.clock.advance(2 * 60 * 60 + 1)
        self.assertEqual(self.pending()["source_state"], "stale")
        self.assertIn(self.confirm(rows)[0], (404, 409))
        self.assertEqual(before, self.store.link_decisions())

    def test_accounts_failed_snapshot_blocks_confirm_and_org_expiry_blocks_write(self):
        rows = self.pending()["rows"]
        before = self.store.link_decisions()
        self.store.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ["NETWORK"], self.clock.now())
        self.assertEqual(self.pending()["source_state"], "accounts-unavailable")
        self.assertIn(self.confirm(rows)[0], (404, 409))
        self.clock.advance(27 * 60 * 60)
        self.assertEqual(self.confirm(rows)[0], 409)
        self.assertEqual(before, self.store.link_decisions())

    def test_selected_owner_limits_list_and_source_bound_confirmation(self):
        self.assertEqual(self.pending(selection="person:101")["rows"], [])
        rows = self.pending(selection="person:100")["rows"]
        before = self.store.link_decisions()
        self.assertEqual(self.confirm(rows)[0], 404)
        self.assertEqual(before, self.store.link_decisions())
        self.assertEqual(self.confirm(rows, selection="person:100")[0], 200)
        self.assertEqual(self.call("GET", "/links/pending?selection=person:101", 100)[0], 404)

    def test_conflicting_ids_from_hidden_or_outside_catalog_still_block_confirmation(self):
        original = TC.company(11, "진행중", company_name=self.company_name)
        for extra in ([], [TC.company(12, "진행중", company_name="범위밖상호")],
                      [TC.company(12, "진행중", company_name="숨김상호", stage_hidden=True)]):
            with self.subTest(extra=extra):
                self.save_catalog([original] + extra, self.ids + [E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.A))])
                rows = self.pending(100)["rows"]
                self.assertTrue(rows)
                self.assertTrue(all(r["possibility_id"] == 11 for r in rows))
                self.assertFalse(any(r["can_confirm"] for r in rows))
                self.assertFalse(any(r["account_name"] for r in rows))
                before = self.store.link_decisions()
                self.assertEqual(self.confirm(rows[:1], 100)[0], 409)
                self.assertEqual(before, self.store.link_decisions())

    def test_name_only_candidate_is_visible_but_not_confirmable(self):
        account_name = self.store.accounts()[0]["account_name"]
        self.save_catalog([TC.company(11, "진행중", company_name=account_name)], [])
        row = self.pending(100)["rows"][0]
        self.assertEqual((row["state"], row["can_confirm"]), ("candidate", False))
        before = self.store.link_decisions()
        self.assertEqual(self.confirm([row], 100)[0], 409)
        self.assertEqual(before, self.store.link_decisions())

    def test_old_end_date_and_unreadable_contract_still_block(self):
        for end, unreadable in ((self.clock.now().date() - timedelta(days=15), False), (None, True)):
            with self.subTest(end=end, unreadable=unreadable):
                self.clock.advance(1)
                self.store.record_prospects(E.StageSnapshot({
                    11: TM.srow(11, name=self.company_name, end=end, unreadable=unreadable),
                    12: TM.srow(12, name="별도합성업체")}, self.clock.now(), {}, ()))
                rows = self.pending()["rows"]
                self.assertTrue(rows)
                self.assertFalse(any(r["can_confirm"] for r in rows))
                before = self.store.link_decisions()
                self.assertEqual(self.confirm(rows)[0], 409)
                self.assertEqual(before, self.store.link_decisions())

    def test_new_decision_invalidates_ref_and_confirmed_history_is_preserved(self):
        rows = self.pending(100)["rows"]
        self.store.record_decision(11, TM.A, "confirmed", 0, self.clock.now())
        before = self.store.link_decisions()
        self.assertEqual(self.confirm(rows, 100)[0], 404)
        self.assertEqual(before, self.store.link_decisions())
        decisions = self.pending(100)["decisions"]
        self.assertEqual([(d["possibility_id"], d["decision"]) for d in decisions], [(11, "confirmed")])
        self.assertEqual(self.pending(101)["decisions"], [])

    def test_wrong_batch_member_never_partially_confirms(self):
        row = self.pending()["rows"][0]
        before = self.store.link_decisions()
        self.assertEqual(self.confirm([row, {"ref": "catalog:invalid"}])[0], 404)
        self.assertEqual(before, self.store.link_decisions())

    def test_source_guard_executes_inside_the_sql_write_transaction(self):
        rows = self.pending()["rows"]
        record = self.store.record_decisions
        guarded = []
        def checked_record(*args, **kwargs):
            guard = kwargs["guard"]
            def check():
                guarded.append(self.store._conn.in_transaction)
                return guard()
            kwargs["guard"] = check
            return record(*args, **kwargs)
        with patch.object(self.store, "record_decisions", side_effect=checked_record):
            self.assertEqual(self.confirm(rows)[0], 200)
        self.assertEqual(guarded, [True])

    def test_first_catalog_failure_does_not_use_legacy_fallback(self):
        # Simulate an installation before its first accepted catalog; no product guard is patched.
        with self.store._tx() as connection:
            connection.execute("DELETE FROM naver_auto_meta WHERE key IN ('account_catalog', 'account_catalog_status')")
        self.assertNotIn("source", self.pending())
        self.store.record_account_catalog_failure(self.clock.now(), "CATALOG_FAILED")
        data = self.pending()
        self.assertEqual((data["source"], data["source_state"], data["rows"]), ("catalog", "failed", []))

    def test_old_legacy_ref_is_not_accepted_after_catalog_becomes_available(self):
        self.clock.advance(1)
        self.store.record_prospects(E.StageSnapshot({11: TM.srow(11, name=self.company_name),
            12: TM.srow(12, name="별도합성업체")}, self.clock.now(), {}, ()))
        self.pair()
        with self.store._tx() as connection:
            connection.execute("DELETE FROM naver_auto_meta WHERE key IN ('account_catalog', 'account_catalog_status')")
        legacy_rows = self.pending()["rows"]
        self.assertTrue(legacy_rows)
        before = self.store.link_decisions()
        self.save_catalog([TC.company(11, "진행중", company_name=self.company_name)])
        self.assertEqual(self.confirm(legacy_rows)[0], 404)
        self.assertEqual(before, self.store.link_decisions())


if __name__ == "__main__":
    unittest.main()
