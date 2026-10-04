"""현재 계정 관제 정책. 합성 원천 + 실제 메모리 Store, 네트워크·파일 잠금 우회 없음."""
from datetime import timedelta
import socket
import sqlite3
import unittest
from unittest.mock import patch

from app.naver_auto import matching as M, scope as SC
from naver_engine import erp_read as E, inventory as I, management_store as MS, naver_read as N, store as S, views as W
from naver_engine.tests import test_account_catalog as TC, test_alerts as TA, test_morning as TM
from naver_engine.tests.test_catalog_links import make_fixture


class MonitoringIdentityPolicyTest(unittest.TestCase):
    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        self.fixture = make_fixture(accounts=5, managed=1, campaigns=0)
        self.st, self.clock = self.fixture.store, self.fixture.clock
        self.addCleanup(self.st.close)
        self.accounts = self.st.accounts()
        self.company = self.st.account_catalog()["items"][0]

    def refresh(self, items, ids, *, seconds=1):
        self.clock.advance(seconds)
        now = self.clock.now()
        self.st.record_org(TA.org_body(now, owners=[TA.owner(pid, 100) for pid in range(11, 17)]), now)
        children = {row["customer_id"]: {"customerId": row["customer_id"],
                    "adAccountNo": row["ad_account_no"], "adAccountName": row["account_name"]}
                    for row in self.accounts}
        self.st.record_accounts(N.ChildAccounts(children, {1: len(children)}, ()), now)
        self.st.record_account_catalog({"generated_at": now.isoformat(), "total": len(items),
            "complete": True, "items": items}, ids, now)

    def board(self, actor=0):
        ctx = W.load(self.st, self.clock.now())
        return I.board(ctx, self.st, SC.scope_of(ctx.org, actor), _include_customer_ids=True)

    def test_every_uncertain_or_unregistered_current_account_is_weekly_without_staff_exposure(self):
        for decision in self.st.current_decisions():
            self.st.revoke_decision(decision.decision_id, 0, self.clock.now(), "합성 미확정 사례")
        a, b, c, d, _ = self.accounts
        items = [TC.company(11, "진행중", company_name=a["account_name"], stage_hidden=True),
                 TC.company(12, None, company_name=b["account_name"], stage_known=False),
                 TC.company(13, "진행중", company_name=c["account_name"]),
                 TC.company(14, "진행중", company_name=c["account_name"]),
                 TC.company(15, "진행중", company_name=d["account_name"])]
        ids = [E.NaverIdRow(pid, M.VENDOR_NAVER, str(row["customer_id"]))
               for pid, row in ((11, a), (12, b), (13, c), (14, c))]
        seconds = ((6-self.clock.now().weekday()) % 7) * 86400 + 1
        self.refresh(items, ids, seconds=seconds)
        self.st.synchronize_management(self.clock.now())
        result = self.board()
        self.assertEqual(result["counts"], {"matched": 0, "no_erp_record": 1, "unclassified": 4})
        for row in result["rows"]:
            self.assertEqual(row["management"]["cadence"], "weekly")
            self.assertTrue(row["management"]["can_collect"])
            self.assertFalse(row["management"]["can_manage"])
            self.assertIsNone(row["possibility_id"])
            self.assertIsNone(row["company_name"])
            self.assertIsNone(row["owner"])
        jobs = self.st.performance_work(self.clock.now(), 24)
        self.assertEqual({job["customer_id"] for job in jobs}, {row["customer_id"] for row in self.accounts})
        self.assertTrue(all(job["kind"] == "weekly" for job in jobs))
        self.assertTrue(all(row["possibility_id"] is None for row in self.st.management_states().values()))
        self.assertTrue(all(self.st.performance_account_valid(job, self.clock.now()) for job in jobs))
        self.assertEqual(self.board(100)["rows"], [])
        self.assertEqual(self.board(101)["rows"], [])

    def test_confirmed_link_and_performance_history_survive_name_time_and_stage_changes(self):
        self.assertEqual(self.fixture.run(limit=1).counts, {"ok": 1})
        now = self.clock.now()
        history = self.st.daily_performance([TM.A], now.date()-timedelta(days=7), now.date())
        self.assertTrue(history)
        decisions = self.st.link_decisions()
        before = self.st.management_states()[TM.A]["stage_revision"]
        original_ids = [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))]
        self.refresh([{**self.company, "company_name": "변경된 전산 상호"}], original_ids)
        row = self.st.synchronize_management(self.clock.now())[TM.A]
        self.assertEqual(row["stage_revision"], before)
        self.assertEqual(row["decision"].cadence, "daily")
        for stage, cadence in (("계약 대기", "weekly"), ("사후 관리", "daily")):
            self.refresh([{**self.company, "company_name": "다시 바뀐 전산 상호", "stage": stage}], original_ids)
            row = self.st.synchronize_management(self.clock.now())[TM.A]
            self.assertEqual(row["possibility_id"], 11)
            self.assertEqual(row["decision"].cadence, cadence)
            self.assertEqual(self.st.link_decisions(), decisions)
            self.assertEqual(self.st.daily_performance([TM.A], now.date()-timedelta(days=7), now.date()), history)
        ctx = W.load(self.st, self.clock.now())
        pairs, _ = I._matching(ctx, self.st.account_catalog())
        self.assertEqual([(pair.possibility_id, pair.customer_id, pair.link) for pair in pairs.pairs],
                         [(11, TM.A, "confirmed")])

    def test_unique_number_auto_keeps_provenance_and_does_not_create_human_confirmation(self):
        for decision in self.st.current_decisions():
            self.st.revoke_decision(decision.decision_id, 0, self.clock.now(), "합성 자동 연결 사례")
        decisions = self.st.link_decisions()
        self.st.synchronize_management(self.clock.now())
        first = MS.snapshot(self.st, self.clock.now())[TM.A]
        self.refresh([self.company], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        second = self.st.synchronize_management(self.clock.now())[TM.A]
        self.assertEqual(first["decision"], second["decision"])
        self.assertEqual(first["stage_revision"], second["stage_revision"])
        self.assertEqual(second["decision"].cadence, "daily")
        self.assertEqual(self.st.link_decisions(), decisions)
        ctx = W.load(self.st, self.clock.now())
        result, _ = I._matching(ctx, self.st.account_catalog())
        self.assertEqual([(pair.customer_id, pair.link) for pair in result.pairs], [(TM.A, "auto")])

    def test_legacy_manual_overrides_remain_in_history_but_no_longer_control_cadence(self):
        row = self.st.synchronize_management(self.clock.now())[TM.A]
        state = self.st.record_management_override(TM.A, row["stage_revision"], False, 100,
                                                  self.clock.now(), "과거 제외 이력 합성")
        self.assertEqual(state["excluded_revision"], row["stage_revision"])
        self.assertEqual(MS.snapshot(self.st, self.clock.now())[TM.A]["decision"].cadence, "daily")
        self.refresh([{**self.company, "stage": "계약 대기"}], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        row = self.st.synchronize_management(self.clock.now())[TM.A]
        state = self.st.record_management_override(TM.A, row["stage_revision"], True, 100,
                                                  self.clock.now(), "과거 포함 이력 합성")
        self.assertEqual(state["included_revision"], row["stage_revision"])
        self.assertEqual(MS.snapshot(self.st, self.clock.now())[TM.A]["decision"].cadence, "weekly")
        actions = [row[0] for row in self.st._conn.execute(
            "SELECT action FROM naver_auto_management_event WHERE customer_id=? ORDER BY event_id", (TM.A,))]
        self.assertEqual(actions, ["stage_sync", "exclude", "stage_sync", "include"])

    def test_auto_identity_survives_name_change_without_human_confirmation(self):
        for decision in self.st.current_decisions():
            self.st.revoke_decision(decision.decision_id, 0, self.clock.now(), "합성 자동 연결")
        decisions = self.st.link_decisions()
        before = self.st.synchronize_management(self.clock.now())[TM.A]
        self.assertEqual(self.fixture.run(limit=1).counts, {"ok": 1})
        now = self.clock.now()
        history = self.st.daily_performance([TM.A], now.date()-timedelta(days=7), now.date())
        self.assertTrue(history)
        self.refresh([{**self.company, "company_name": "전혀 달라진 상호"}],
                     [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        after = self.st.synchronize_management(self.clock.now())[TM.A]
        self.assertEqual(after["possibility_id"], 11)
        self.assertEqual(after["stage_revision"], before["stage_revision"])
        self.assertEqual(after["decision"].cadence, "daily")
        self.assertEqual(self.st.link_decisions(), decisions)
        self.assertEqual(self.st.daily_performance([TM.A], now.date()-timedelta(days=7), now.date()), history)
        pair = I._matching(W.load(self.st, self.clock.now()), self.st.account_catalog(),
                           auto_evidence=self.st.automatic_link_evidence())[0].pairs[0]
        self.assertEqual((pair.link, pair.name_relation), ("auto", "different"))
        self.assertEqual(self.board(100)["counts"]["matched"], 1)

    def start_auto(self):
        for decision in self.st.current_decisions():
            self.st.revoke_decision(decision.decision_id, 0, self.clock.now(), "합성 자동 연결")
        self.st.synchronize_management(self.clock.now())
        self.assertIn((11, TM.A), self.st.automatic_link_evidence())

    def assert_invalidated(self):
        row = self.st.synchronize_management(self.clock.now())[TM.A]
        self.assertIsNone(row["possibility_id"])
        self.assertNotIn((11, TM.A), self.st.automatic_link_evidence())
        self.assertIn((11, TM.A), self.st.matched_before("auto"))
        return row

    def test_auto_evidence_invalidated_on_number_change_does_not_resurrect_after_revert(self):
        self.start_auto()
        original = self.accounts[0]["ad_account_no"]
        self.accounts[0]["ad_account_no"] += 100
        renamed = [{**self.company, "company_name": "전혀 달라진 상호"}]
        ids = [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))]
        self.refresh(renamed, ids)
        self.assert_invalidated()
        self.accounts[0]["ad_account_no"] = original
        self.refresh(renamed, ids)
        self.assert_invalidated()

    def test_auto_evidence_invalidated_on_removed_identifier_or_duplicate(self):
        self.start_auto()
        self.refresh([{**self.company, "company_name": "전혀 달라진 상호"}], [])
        self.assert_invalidated()
        self.refresh([self.company], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        self.st.synchronize_management(self.clock.now())
        self.assertIn((11, TM.A), self.st.automatic_link_evidence())  # 현재 strict 매칭이면 새로 증명 가능
        self.refresh([self.company, TC.company(12, "진행중", company_name="별도업체")],
                     [E.NaverIdRow(pid, M.VENDOR_NAVER, str(TM.A)) for pid in (11, 12)])
        self.assert_invalidated()

    def test_auto_evidence_invalidated_on_explicit_rejection(self):
        self.start_auto()
        self.st.record_decision(11, TM.A, "rejected", 100, self.clock.now())
        self.assert_invalidated()
        self.assertEqual(len(self.st.current_decisions()), 1)

    def test_authority_loss_clears_evidence_not_history(self):
        self.start_auto()
        self.accounts = self.accounts[1:]
        self.refresh([self.company], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        self.assertEqual(self.assert_invalidated()["decision"].cadence, "blocked")

    def test_source_failure_does_not_clear_evidence_and_reopened_reader_can_use_it(self):
        self.start_auto()
        evidence = self.st.automatic_link_evidence()
        self.clock.advance(86400)
        self.assertEqual(self.st.synchronize_management(self.clock.now())[TM.A]["decision"].cadence, "blocked")
        self.assertEqual(self.st.automatic_link_evidence(), evidence)
        self.refresh([{**self.company, "company_name": "전혀 달라진 상호"}],
                     [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        connection = sqlite3.connect(":memory:", isolation_level=None)
        self.st._conn.backup(connection)
        reader = S.Store(connection, ":memory:", None, writer=False, clock=self.clock.now)
        self.addCleanup(reader.close)
        self.assertEqual(reader.automatic_link_evidence(), evidence)
        self.assertEqual(MS.snapshot(reader, self.clock.now())[TM.A]["decision"].cadence, "daily")

    def test_legacy_null_auto_history_is_not_numeric_evidence(self):
        for decision in self.st.current_decisions():
            self.st.revoke_decision(decision.decision_id, 0, self.clock.now(), "합성 자동 연결")
        at = self.clock.now().isoformat()
        with self.st._tx() as conn:
            conn.execute("""INSERT INTO naver_auto_link_memory
                (possibility_id,customer_id,link,first_matched_at,last_matched_at)
                VALUES (?,?,'auto',?,?)""", (11, TM.A, at, at))
        self.refresh([{**self.company, "company_name": "이미 달라져 있던 상호"}],
                     [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        self.assert_invalidated()

    def test_stage_hidden_does_not_delete_auto_evidence_or_grant_staff_access(self):
        self.start_auto()
        evidence = self.st.automatic_link_evidence()
        ids = [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))]
        self.refresh([{**self.company, "company_name": "전혀 달라진 상호", "stage_hidden": True}], ids)
        row = self.st.synchronize_management(self.clock.now())[TM.A]
        self.assertEqual(row["decision"].cadence, "weekly")
        self.assertIsNone(row["possibility_id"])
        self.assertEqual(self.st.automatic_link_evidence(), evidence)
        self.assertEqual(self.board(100)["rows"], [])
        self.refresh([{**self.company, "company_name": "전혀 달라진 상호", "stage": "계약대기"}], ids)
        self.assertEqual(self.st.synchronize_management(self.clock.now())[TM.A]["decision"].cadence, "weekly")
        self.refresh([{**self.company, "company_name": "전혀 달라진 상호"}], ids)
        self.assertEqual(self.st.synchronize_management(self.clock.now())[TM.A]["decision"].cadence, "daily")


if __name__ == "__main__":
    unittest.main()
