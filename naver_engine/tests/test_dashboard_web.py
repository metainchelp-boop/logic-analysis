"""월간 대시보드 읽기 경로의 인증·범위·부작용 경계. 운영 자료/외부 호출 없음."""
from datetime import timedelta
import json
import socket
import unittest
from unittest.mock import patch

from naver_engine.tests import test_web as TW
from naver_engine.tests.test_account_catalog import company


class DashboardRequestGateTest(unittest.TestCase):
    call = TW.WebBase.call

    def make_app(self, *, verification=False):
        def forbidden(*args, **kwargs):
            self.fail("인증 없는 대시보드는 저장소·전산·수집을 호출할 수 없습니다")

        self.app = TW.WEB.App(
            open_read=forbidden, write=forbidden,
            signer=TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET)),
            profiles=forbidden, clock=lambda: TW.T0,
            owner_verification=verification, request_collection=forbidden)

    def test_dashboard_requires_authentication_before_opening_store(self):
        self.make_app()
        self.assertEqual(self.call("GET", "/dashboard")[:2],
                         (401, {"error": "token-missing"}))

    def test_read_only_dashboard_get_reaches_the_existing_authentication_gate(self):
        self.make_app(verification=True)
        self.assertEqual(self.call("GET", "/dashboard")[:2],
                         (401, {"error": "token-missing"}))

    def test_forged_token_is_refused_without_opening_store(self):
        self.make_app(verification=True)
        signer = TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET))
        parts = signer.issue(0, TW.T0).split(".")
        parts[2] = ("a" if parts[2][0] != "a" else "b") + parts[2][1:]
        self.assertEqual(self.call("GET", "/dashboard", ".".join(parts))[0], 401)

    def test_duplicate_query_is_rejected_before_store_access(self):
        self.make_app(verification=True)
        for query in ("selection=all&selection=me", "selection=all&%73election=me"):
            with self.subTest(query=query):
                self.assertEqual(self.call("GET", "/dashboard", query=query)[:2],
                                 (400, {"error": "bad-query"}))

    def test_dashboard_post_cannot_trigger_collection_or_write(self):
        self.make_app(verification=True)
        self.assertEqual(self.call("POST", "/dashboard", body={"collect": True})[:2],
                         (403, {"error": "verification-read-only"}))


class DashboardWebTest(TW.WebBase):
    """기존 실제 SQLite WebBase를 사용한다. 저장 잠금 실패는 건너뛰거나 우회하지 않는다."""

    def make_app(self, **kwargs):
        return super().make_app(owner_verification=True, **kwargs)

    def setUp(self):
        super().setUp()
        rows = [company(11, company_name=TW.TM.NAMES[TW.A]),
                company(12, company_name=TW.TM.NAMES[TW.B])]
        self.st.record_account_catalog(
            {"generated_at": self.fc.now().isoformat(), "total": len(rows),
             "complete": True, "items": rows},
            [TW.E.NaverIdRow(11, TW.M.VENDOR_NAVER, str(TW.A)),
             TW.E.NaverIdRow(12, TW.M.VENDOR_NAVER, str(TW.B))], self.fc.now())
        self.balance(TW.A, 11111)
        self.balance(TW.B, 22222)

    def balance(self, customer_id, amount):
        now = self.fc.now()
        snapshot = self.st.inventory_snapshot(now)
        self.st.begin_inventory_check(customer_id, snapshot, now)
        self.st.record_inventory_check(customer_id, snapshot, now,
                                       {"status": "partial", "bizmoney": amount})

    def dashboard(self, idx=0, query="", **kwargs):
        status, result = self.get("/dashboard", idx, query=query, **kwargs)
        self.assertEqual(status, 200, result)
        for key in ("period", "accounts", "coverage", "totals"):
            self.assertIn(key, result)
        return result

    def test_owner_read_only_dashboard_is_available_for_current_scope(self):
        status, result, headers, _ = self.call("GET", "/dashboard", self.token(0))
        self.assertEqual(status, 200, result)
        self.assertEqual(result["accounts"]["total"], 4)
        self.assertEqual(result["period"]["timezone"], "Asia/Seoul")
        self.assertIn("no-store", headers.get("Cache-Control", ""))

    def test_staff_all_me_and_own_person_never_expand_beyond_own_account(self):
        answers = [self.dashboard(100, query=query)
                   for query in ("", "selection=all", "selection=me", "selection=person%3A100")]
        for result in answers:
            self.assertEqual(result["accounts"]["total"], 1)
        for key in ("period", "accounts", "coverage", "totals"):
            self.assertTrue(all(result[key] == answers[0][key] for result in answers))
        owner_selected = self.dashboard(0, query="selection=person%3A100")
        for key in ("period", "accounts", "coverage", "totals"):
            self.assertEqual(answers[0][key], owner_selected[key], key)
        self.assertEqual(self.dashboard(1)["accounts"]["total"], 0)

    def test_other_people_and_nonexistent_people_are_indistinguishable(self):
        results = [self.get("/dashboard", 100, query=query)
                   for query in ("selection=person:101", "selection=person:99999",
                                 "selection=team:11", "selection=team:99999")]
        self.assertTrue(all(result[0] == 404 for result in results))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.get("/dashboard", 100, query="selection=unassigned")[0], 400)

    def test_unknown_and_malformed_queries_are_rejected(self):
        for query in ("unknown=1", "as=0", "selection=all&collect=1", "selection=%ZZ",
                      "selection=all&selection=me", "selection=all&%73election=me"):
            with self.subTest(query=query):
                self.assertEqual(self.get("/dashboard", 100, query=query)[0], 400)

    def test_resigned_user_is_refused_on_next_request_with_same_token(self):
        token = self.token(100)
        self.assertEqual(self.call("GET", "/dashboard", token)[0], 200)
        self.resign(100)
        self.assertEqual(self.call("GET", "/dashboard", token)[:2],
                         (401, {"error": "no-scope"}))

    def test_stale_org_refuses_staff_and_preserves_owner_recovery_view(self):
        self.at(self.fc.now() + timedelta(hours=30))
        for idx in (1, 100, 101):
            with self.subTest(idx=idx):
                self.assertEqual(self.get("/dashboard", idx), (503, {"error": "org-stale"}))
        self.assertEqual(self.get("/dashboard", 0)[0], 200)

    def monthly(self, customer_id, spend):
        from naver_engine import monthly_reads as MR
        now = self.fc.now()
        start, end = MR.window(now.date())
        snapshot = self.st.inventory_snapshot(now)
        campaign_ids = [f"cmp-{customer_id}-1"]
        fingerprint = MR.fingerprint(campaign_ids)
        batch = {"impCnt": 100, "clkCnt": 10, "salesAmt": spend, "convAmt": 3000}
        progress = {"customer_id": customer_id, "period_start": start.isoformat(),
                    "period_end": end.isoformat(), "campaign_ids": campaign_ids,
                    "fingerprint": fingerprint, "next_index": 1, "batches": [batch],
                    "cycles": [now.isoformat()], "zero_rows": {}}
        self.st.begin_monthly_check(customer_id, snapshot, now)
        self.st.record_monthly_progress(customer_id, snapshot, now, progress)
        self.st.record_monthly_check(customer_id, snapshot, now,
                                     {"status": "ok", "imp": 100, "clk": 10, "spend": spend,
                                      "conversion_value": 3000, "campaign_count": 1,
                                      "enabled_campaigns": 1, "campaign_fingerprint": fingerprint})

    def test_out_of_scope_monthly_statistics_do_not_change_staff_answer(self):
        self.monthly(TW.A, 1000)
        before = self.dashboard(100)
        owner_before = self.dashboard(0)
        self.monthly(TW.B, 987654321)
        self.assertEqual(self.dashboard(100), before)
        self.assertNotEqual(self.dashboard(0), owner_before)

    def test_dashboard_read_does_not_collect_write_or_call_external_network(self):
        def forbidden(*args, **kwargs):
            self.fail("대시보드 조회는 수집·네트워크·업무 쓰기를 시작할 수 없습니다")

        self.app = TW.WEB.App(
            open_read=lambda: TW.S.open_reader(self.path), write=forbidden,
            signer=self.signer, profiles=forbidden, clock=self.fc.now,
            owner_verification=True, request_collection=forbidden, collection_status=forbidden)
        before = (self.st.inventory_checks_on(self.fc.now().date()),
                  self.st.account_day_checks_on(self.fc.now().date()), self.st.issues(),
                  self.st.link_decisions(), self.st.thresholds(), self.st.access_log())
        calls = (len(self.naver.calls), len(self.erp.calls))
        with patch.object(socket.socket, "connect", side_effect=forbidden), \
             patch.object(socket, "create_connection", side_effect=forbidden):
            self.dashboard(0)
            self.dashboard(100)
        after = (self.st.inventory_checks_on(self.fc.now().date()),
                 self.st.account_day_checks_on(self.fc.now().date()), self.st.issues(),
                 self.st.link_decisions(), self.st.thresholds(), self.st.access_log())
        self.assertEqual(after, before)
        self.assertEqual((len(self.naver.calls), len(self.erp.calls)), calls)

    def test_accounts_never_exposes_internal_customer_ids_after_dashboard_read(self):
        def assert_no_customer_key(value):
            if isinstance(value, dict):
                self.assertNotIn("customer_id", value)
                self.assertNotIn("customerId", value)
                for child in value.values():
                    assert_no_customer_key(child)
            elif isinstance(value, list):
                for child in value:
                    assert_no_customer_key(child)

        for idx in (0, 100, 101):
            with self.subTest(idx=idx):
                self.dashboard(idx)
                status, accounts = self.get("/accounts", idx)
                self.assertEqual(status, 200)
                assert_no_customer_key(accounts)
                encoded = json.dumps(accounts, ensure_ascii=False)
                for customer_id in (TW.A, TW.B, TW.C_, TW.D):
                    self.assertNotIn(str(customer_id), encoded)


if __name__ == "__main__":
    unittest.main()
