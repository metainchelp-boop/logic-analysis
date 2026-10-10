"""합성 ERP/SQLite WSGI 검증. 외부 송신과 GET 중 쓰기는 기본 fixture에서 금지한다."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import unittest

from app.naver_auto import org_snapshot as O, scope as SC
from naver_engine import sales_views as SV, store as S
from naver_engine.tests import test_alerts as TA, test_web as TW, test_account_catalog as TC
from naver_engine.tests import test_report_accounts_web as Fixtures


class SalesReadWebTest(unittest.TestCase):
    call = TW.WebBase.call
    def seed_report(self, report_id=1, pid=11, cid=TW.A, **kwargs):
        payload = Fixtures.ReportAccountsWebTest.seed_report(self, report_id, pid, cid, **kwargs)
        payload["_account_reports"][str(cid)]["_expected_customers"] = [cid]
        self.store._conn.execute("UPDATE naver_auto_report_snapshot SET payload_json=? WHERE report_id=?",
                                 (json.dumps(payload), report_id))
        return payload

    def setUp(self):
        Fixtures.ReportAccountsWebTest.setUp(self)
        self.clock.advance(1)
        self.org = TA.org_body(self.clock.now(), extra_people=[
            {**TA.emp(200, "합성 영업가", 11, management=False), "is_sales": True, "naver_sales_view": True},
            {**TA.emp(201, "합성 영업나", 11, management=False), "is_sales": True, "naver_sales_view": True}])
        self.org["sales_contracts"] = [{"possibility_id": pid, "seller_emp_idx": seller}
            for pid, seller in ((11, 200), (12, 201), (13, 200))]
        self.store.record_org(self.org, self.clock.now())

    def get(self, path="/sales/clients", query="kind=weekly&anchor=2026-09-21", actor=200):
        return self.call("GET", path, self.signer.issue(actor, self.clock.now()), query=query)

    def update_org(self, fn):
        self.clock.advance(1)
        fn(self.org)
        self.org["generated_at"] = self.clock.now().isoformat()
        self.store.record_org(self.org, self.clock.now())

    def test_actual_seller_only_including_pending_company_and_no_management_projection(self):
        status, body, _, raw = self.get()
        self.assertEqual(status, 200, body)
        self.assertEqual([r["possibility_id"] for r in body["items"]], [11, 13])
        pending = body["items"][1]
        self.assertEqual((pending["connection_status"], pending["accounts"]), ("pending", []))
        self.assertEqual(body["items"][0]["accounts"][0]["metrics"]["cost"], None)
        self.assertEqual(body["page_size"], 100)
        self.assertNotIn(str(TW.A).encode(), raw)
        self.assertNotIn(b'"owner"', raw)
        self.assertEqual([r["possibility_id"] for r in self.get(actor=201)[1]["items"]], [12])
        me = self.get("/me", query="")[1]
        self.assertEqual(set(me), {"idx", "name", "scope", "sales_read_only", "source_as_of", "narrowed", "verified_linking"})

    def test_other_direct_ids_search_and_account_scope_do_not_leak(self):
        self.assertEqual(self.get("/sales/detail", "pid=12")[0], 404)
        self.assertEqual(self.get(query="q=8000001")[1]["total"], 0)
        self.assertEqual(self.get("/sales/report", "pid=12&account_key="+SV.RV.account_key(TW.B))[0], 404)
        self.assertEqual(self.get("/sales/report", "pid=11&account_key=company")[0], 400)
        self.assertEqual(self.get(query="selection=all")[0], 400)
        self.assertEqual(self.get(query="view_sync=1")[0], 400)

    def test_existing_read_routes_and_all_business_writes_are_closed(self):
        for path in ("/board", "/accounts", "/accounts/reasons", "/dashboard", "/clients/11",
                     "/reports", "/reports/accounts", "/reports/detail", "/reports/history",
                     "/links/pending", "/ended", "/unlinked", "/bell", "/settings", "/health", "/collection/status",
                     "/automation", "/reports/strategy"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, query="")[0], 403)
        for route in TW.WEB.ROUTES:
            if route.method != "POST" or route.pattern.pattern in ("/session", "/session/refresh"):
                continue
            path = route.pattern.pattern
            import re
            path = re.sub(r"\(\?P<\w+>[^)]+\)", "1", path)
            with self.subTest(path=path):
                self.assertIn(self.call("POST", path, self.signer.issue(200, self.clock.now()), body={})[0], (403, 404))

    def test_scope_functions_cannot_grant_management_actions_even_if_owner_overlaps(self):
        self.update_org(lambda org: org["owners"].append(TA.owner(999, 200)))
        org = O.parse_org_snapshot(self.store.org_current()["body"])
        scope = SC.scope_of(org, 200)
        own = SC.Ownership(client_id=999, main=200, match=SC.MATCH_PID, source="manage")
        self.assertEqual(scope.kind, SC.SALES_READ)
        self.assertFalse(SC.can_see(org, scope, own))
        self.assertFalse(SC.allowed_actions(org, scope, own))

    def test_permission_resignation_seller_removal_missing_source_and_stale_all_close(self):
        token = self.signer.issue(200, self.clock.now())
        self.update_org(lambda org: org["employees"][-2].update(naver_sales_view=False))
        self.assertEqual(self.call("GET", "/sales/clients", token)[0], 401)
        self.update_org(lambda org: org["employees"][-2].update(naver_sales_view=True, status="RESIGNED"))
        self.assertEqual(self.get()[0], 401)
        self.update_org(lambda org: org["employees"][-2].update(status="ACTIVE"))
        self.update_org(lambda org: org.update(sales_contracts=[]))
        self.assertEqual(self.get()[1]["total"], 0)
        self.update_org(lambda org: org.pop("sales_contracts"))
        self.assertEqual(self.get()[0], 503)

    def test_org_failure_or_two_hour_expiry_denies_previous_scope(self):
        self.store.record_sync_event(S.SYNC_ORG, S.SYNC_FAILED, ["TEST"], self.clock.now())
        self.assertEqual(self.get()[0], 503)

    def test_two_hour_expiry_denies(self):
        self.clock.advance(7201)
        self.assertEqual(self.get()[0], 503)

    def test_stage_exact_in_progress_only(self):
        catalog = self.store.account_catalog()
        self.clock.advance(1)
        catalog["items"][0]["stage"] = "계약만료"
        self.store.record_account_catalog({"generated_at": self.clock.now().isoformat(), "total": 3,
            "complete": True, "items": catalog["items"]},
            [TW.E.NaverIdRow(r["possibility_id"], r["vendor"], r["customer_id_raw"], r["ad_account_no_raw"])
             for r in catalog["ids"]], self.clock.now())
        self.assertEqual([r["possibility_id"] for r in self.get()[1]["items"]], [13])
        self.assertEqual(self.get("/sales/detail", "pid=11")[0], 404)

    def test_metrics_are_per_account_and_only_approved_exact_notes_can_be_read(self):
        payload = self.seed_report()
        key = SV.RV.account_key(TW.A)
        query = "pid=11&account_key="+key+"&kind=weekly&anchor=2026-09-21"
        account = self.get()[1]["items"][0]["accounts"][0]
        self.assertEqual(account["metrics"]["cost"], 700)
        self.assertEqual(self.get("/sales/report", query)[0], 404)
        saved = self.store.record_report_notes(1, key, payload["revision_fingerprint"], 100,
            self.clock.now(), expected_version=0, action="save", document={
                "shared_comment": "승인 공유 피드백", "next_plan": "다음 주 소재 비교",
                "internal_note": "INTERNAL-PRIVATE", "client_feedback": "FEEDBACK-PRIVATE"})
        self.assertEqual(self.get("/sales/report", query)[0], 404)
        self.store.record_report_notes(1, key, payload["revision_fingerprint"], 100,
            self.clock.now(), expected_version=saved["version"], action="approve")
        status, report, _, raw = self.get("/sales/report", query)
        self.assertEqual(status, 200, report)
        self.assertEqual(report["comment"]["shared_comment"], "승인 공유 피드백")
        self.assertNotIn(b"PRIVATE", raw)
        self.assertNotIn(b'"author"', raw)
        self.seed_report(2, spend=200)
        self.assertEqual(self.get("/sales/report", query)[0], 404)

    def test_old_schema_and_string_permission_default_closed(self):
        self.update_org(lambda org: org["employees"][-2].update(naver_sales_view="true"))
        self.assertEqual(self.get()[0], 401)
        legacy = deepcopy(self.org)
        legacy.pop("sales_contracts")
        for person in legacy["employees"]:
            person.pop("is_sales", None)
            person.pop("naver_sales_view", None)
        parsed = O.parse_org_snapshot(legacy)
        self.assertEqual(SC.scope_of(parsed, 200).kind, SC.NONE)
        self.assertEqual(SC.scope_of(parsed, 100).kind, SC.MINE)

    def test_rematched_account_cannot_read_previous_company_report(self):
        self.seed_report()
        key = SV.RV.account_key(TW.A)
        self.store.record_decision(12, TW.A, "confirmed", 0, self.clock.now())
        query = "pid=11&account_key="+key+"&kind=weekly&anchor=2026-09-21"
        self.assertEqual(self.get("/sales/report", query)[0], 404)
        query = "pid=12&account_key="+key+"&kind=weekly&anchor=2026-09-21"
        self.assertEqual(self.get("/sales/report", query, actor=201)[0], 404)

    def test_shared_notes_on_another_account_do_not_approve_selected_account(self):
        payload = self.seed_report()
        key = SV.RV.account_key(TW.A)
        self.store.record_report_notes(1, "company", payload["revision_fingerprint"], 100,
            self.clock.now(), expected_version=0, action="save", document={"shared_comment": "회사 합산 승인"})
        self.store.record_report_notes(1, "company", payload["revision_fingerprint"], 100,
            self.clock.now(), expected_version=1, action="approve")
        self.assertEqual(self.get("/sales/report", "pid=11&account_key="+key+"&kind=weekly&anchor=2026-09-21")[0], 404)


if __name__ == "__main__":
    unittest.main()
