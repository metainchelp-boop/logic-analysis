"""계정 보고서의 공개 WSGI 계약. 실제 메모리 Store, 외부 송신·읽기 중 쓰기 금지."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import socket
import sqlite3
import unittest
from unittest.mock import patch

from naver_engine.tests import test_web as TW, test_alerts as TA, test_account_catalog as TC
from naver_engine.tests.test_catalog_links import make_fixture
from naver_engine import store as S, reporting as R


class ReportAccountsWebTest(unittest.TestCase):
    call = TW.WebBase.call

    def setUp(self):
        for method in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, method, side_effect=AssertionError("외부 송신 금지"))
            guard.start()
            self.addCleanup(guard.stop)
        self.fixture = make_fixture(accounts=2, managed=2, campaigns=0)
        self.store, self.clock = self.fixture.store, self.fixture.clock
        self.addCleanup(self.store.close)
        self.signer = TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET))
        self.clock.advance(1)
        now = self.clock.now()
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11, 100), TA.owner(12, 101), TA.owner(13, 100)]), now)
        catalog = self.store.account_catalog()
        self.store.record_account_catalog({"generated_at": now.isoformat(), "total": 3, "complete": True,
            "items": [*catalog["items"], TC.company(13, "진행중", company_name="미연결 합성 업체")]},
            [TW.E.NaverIdRow(row["possibility_id"], row["vendor"], row["customer_id_raw"], row["ad_account_no_raw"])
             for row in catalog["ids"]], now)

        def open_read():
            conn = sqlite3.connect(":memory:", isolation_level=None)
            self.store._conn.backup(conn)
            return S.Store(conn, ":memory:", None, writer=False, clock=self.clock.now)

        def forbidden(*args, **kwargs):
            self.fail("보고서 GET은 쓰기 또는 수집을 시작할 수 없습니다")

        self.app = TW.WEB.App(open_read=open_read, write=forbidden, signer=self.signer,
            profiles=forbidden, clock=self.clock.now, owner_verification=True, verified_linking=True,
            request_collection=forbidden, collection_status=forbidden)

    def get(self, path="/reports/accounts", query="kind=weekly&anchor=2026-09-21", actor=100):
        return self.call("GET", path, self.signer.issue(actor, self.clock.now()), query=query)

    def test_current_owned_account_without_report_remains_visible_and_unlinked_count_is_scoped(self):
        status, body, _, raw = self.get()
        self.assertEqual(status, 200, body)
        self.assertEqual((body["total"], body["unlinked_companies"], body["page_size"]), (1, 1, 20))
        row = body["rows"][0]
        self.assertEqual((row["possibility_id"], row["status"], row["report_id"]), (11, "not_generated", None))
        self.assertEqual(row["account_key"], hashlib.sha256(str(TW.A).encode()).hexdigest())
        self.assertEqual(row["ad_account_no"], "8000000")
        self.assertNotIn(str(TW.A).encode(), raw)
        self.assertEqual(self.get(actor=101)[1]["unlinked_companies"], 0)
        self.assertEqual(self.get(actor=0)[1]["total"], 2)

    def test_view_sync_is_scoped_and_unchanged_only_for_identical_query_and_owner(self):
        query = "kind=weekly&anchor=2026-09-21&view_sync=1"
        status, first, _, _ = self.get(query=query)
        self.assertEqual(status, 200, first)
        self.assertEqual(first["mode"], "full")
        again = self.get(query=query+"&view_cursor="+first["cursor"])[1]
        self.assertEqual(again["mode"], "unchanged")
        other = self.get(query=query+"&view_cursor="+first["cursor"], actor=101)[1]
        self.assertEqual(other["mode"], "full")
        self.assertEqual([row["possibility_id"] for row in other["data"]["rows"]], [12])

    def seed_report(self, report_id=1, pid=11, cid=TW.A, *, spend=100, version=2, anchor="2026-09-21"):
        period = R.period("weekly", date.fromisoformat(anchor))
        days = [{"customer_id": cid, "day": str(period.start+timedelta(days=n)),
                 "basic_complete": True, "conversion_complete": True, "imp": 100, "clk": 10,
                 "spend": spend, "conversions": 1, "conversion_value": 500,
                 "checked_at": self.clock.now().isoformat()} for n in range(7)]
        payload = R.aggregate(period, [cid], days, self.clock.now())
        payload["revision_no"] = report_id
        if version == 2:
            detail = {**deepcopy(payload), "format_version": 2,
                      "details": {"status": "available", "daily": [], "briefing": [],
                                  "_private": {"marker": "PRIVATE-NESTED"},
                                  "customer_id": "PRIVATE-ID"}, "validation": {"status": "complete"}}
            payload.update(format_version=2, details=deepcopy(detail["details"]),
                           validation={"status": "pending"},
                           _expected_customers=[cid], _account_reports={str(cid): detail})
        self.store._conn.execute("""INSERT INTO naver_auto_report_snapshot
            (report_id,possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
            VALUES(?,?,?,?,?,?,?,?)""", (report_id, pid, period.key, payload["revision_fingerprint"],
             self.clock.now().isoformat(), payload["status"], payload["review_status"], json.dumps(payload)))
        return payload

    def test_exact_period_latest_account_snapshot_and_read_only_detail(self):
        self.seed_report(1, spend=100)
        self.seed_report(2, spend=200)
        self.seed_report(3, spend=900, anchor="2026-09-14")
        status, body, _, _ = self.get()
        self.assertEqual(status, 200, body)
        row = body["rows"][0]
        self.assertEqual((row["report_id"], row["revision_no"], row["status"]), (2, 2, "ready"))
        status, detail, _, raw = self.get("/reports/detail", "report_id=1&account_key="+row["account_key"])
        self.assertEqual(status, 200, detail)
        self.assertEqual((detail["report_id"], detail["payload"]["totals"]["spend"]), (1, 700))
        self.assertEqual(detail["scope"]["kind"], "account")
        self.assertEqual(detail["scope"]["ad_account_no"], "8000000")
        self.assertNotIn(b"PRIVATE-NESTED", raw)
        self.assertNotIn(b"PRIVATE-ID", raw)
        self.assertNotIn(str(TW.A).encode(), raw)

    def test_account_revalidation_is_not_the_whole_company_revalidation(self):
        self.seed_report()
        key = hashlib.sha256(str(TW.A).encode()).hexdigest()
        account = self.get("/reports/detail", "report_id=1&account_key="+key)[1]
        company = self.get("/reports/detail", "report_id=1&account_key=company")[1]
        self.assertEqual(account["validation"]["status"], "complete")
        self.assertEqual(company["validation"]["status"], "pending")

    def test_account_payload_cannot_claim_a_different_period_from_its_saved_company_report(self):
        payload = self.seed_report()
        payload["_account_reports"][str(TW.A)]["period_key"] = "weekly:2026-09-14:2026-09-20"
        self.store._conn.execute("UPDATE naver_auto_report_snapshot SET payload_json=? WHERE report_id=1", (json.dumps(payload),))
        key = hashlib.sha256(str(TW.A).encode()).hexdigest()
        self.assertEqual(self.get("/reports/detail", "report_id=1&account_key="+key)[:2], (404, TW.WEB.NOT_VISIBLE))

    def test_detail_check_time_does_not_replace_the_frozen_report_generation_time(self):
        payload = self.seed_report()
        self.clock.advance(30)
        status, detail, _, _ = self.get("/reports/detail", "report_id=1&account_key=company")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["checked_at"], self.clock.now().isoformat())
        self.assertEqual(detail["generated_at"], payload["generated_at"])
        self.assertNotEqual(detail["checked_at"], detail["generated_at"])

    def test_other_owner_unknown_report_and_unrelated_account_have_identical_not_found(self):
        self.seed_report()
        other = hashlib.sha256(str(TW.B).encode()).hexdigest()
        key = hashlib.sha256(str(TW.A).encode()).hexdigest()
        for query, actor in (("report_id=1&account_key="+key, 101),
                             ("report_id=999&account_key="+key, 100),
                             ("report_id=1&account_key="+other, 100),
                             ("report_id=1&account_key="+key+"&possibility_id=12", 100),
                             ("report_id=1&account_key="+key+"&period_key=weekly:2026-09-14:2026-09-20", 100)):
            with self.subTest(query=query, actor=actor):
                self.assertEqual(self.get("/reports/detail", query, actor)[:2], (404, TW.WEB.NOT_VISIBLE))

    def test_moved_account_never_grants_new_company_owner_the_previous_company_report(self):
        self.seed_report()
        key = hashlib.sha256(str(TW.A).encode()).hexdigest()
        self.store.record_decision(12, TW.A, "confirmed", 0, self.clock.now())
        query = "report_id=1&account_key="+key
        self.assertEqual(self.get("/reports/detail", query, 101)[:2], (404, TW.WEB.NOT_VISIBLE))
        status, old, _, _ = self.get("/reports/detail", query)
        self.assertEqual(status, 200, old)
        self.assertEqual(old["payload"]["totals"]["spend"], 700)
        self.assertIsNone(old["scope"]["ad_account_no"])
        self.assertIsNone(old["scope"]["account_name"])
        current = self.get(actor=101)[1]
        self.assertTrue(all(row["report_id"] is None for row in current["rows"]))

    def test_newly_added_account_does_not_borrow_a_company_snapshot_without_that_account(self):
        self.seed_report()
        self.store.record_decision(11, TW.A+1, "confirmed", 0, self.clock.now())
        rows = self.get()[1]["rows"]
        self.assertEqual(len(rows), 2)
        added = next(row for row in rows if row["ad_account_no"] == "8000001")
        self.assertEqual((added["status"], added["report_id"]), ("not_generated", None))

    def test_owner_change_and_retirement_are_checked_again_before_detail_download(self):
        self.seed_report()
        query = "report_id=1&account_key=company"
        self.assertEqual(self.get("/reports/detail", query)[0], 200)
        self.clock.advance(1)
        body = TA.org_body(self.clock.now(), owners=[TA.owner(11, 101), TA.owner(12, 101)])
        self.store.record_org(body, self.clock.now())
        self.assertEqual(self.get("/reports/detail", query)[:2], (404, TW.WEB.NOT_VISIBLE))
        self.assertEqual(self.get("/reports/detail", query, 101)[0], 200)
        self.clock.advance(1)
        body["generated_at"] = self.clock.now().isoformat()
        for employee in body["employees"]:
            if employee["idx"] == 101:
                employee["status"] = "RESIGNED"
        self.store.record_org(body, self.clock.now())
        self.assertEqual(self.get("/reports/detail", query, 101)[0], 401)

    def test_legacy_account_has_no_company_numbers_and_company_aggregate_is_preserved(self):
        source = self.seed_report(version=1)
        key = self.get()[1]["rows"][0]["account_key"]
        status, account, _, _ = self.get("/reports/detail", "report_id=1&account_key="+key)
        self.assertEqual(status, 200, account)
        self.assertEqual(account["payload"]["details"]["status"], "legacy_unavailable")
        self.assertTrue(all(value is None for value in account["payload"]["totals"].values()))
        status, company, _, _ = self.get("/reports/detail", "report_id=1&account_key=company")
        self.assertEqual(status, 200, company)
        self.assertEqual(company["payload"]["totals"], source["totals"])
        self.assertEqual(company["scope"]["kind"], "company")
        self.assertEqual(self.get("/reports", "")[1]["rows"][0]["payload"]["totals"], source["totals"])

    def test_search_matches_beyond_first_page_and_does_not_count_other_staff(self):
        self.clock.advance(1)
        now = self.clock.now()
        children = {TW.A+n: {"customerId": TW.A+n, "adAccountNo": 8000000+n, "adAccountName": f"광고계정{n:02d}"}
                    for n in range(25)}
        self.store.record_accounts(TW.TM.N.ChildAccounts(children, {1: 25}, ()), now)
        items = [TC.company(11+n, "진행중", company_name=f"업체{n:02d}") for n in range(25)]
        self.store.record_account_catalog({"generated_at": now.isoformat(), "complete": True, "total": 25, "items": items},
            [TW.E.NaverIdRow(11+n, TW.M.VENDOR_NAVER, str(TW.A+n)) for n in range(25)], now)
        self.store.record_org(TA.org_body(now, owners=[TA.owner(11+n, 101 if n == 24 else 100) for n in range(25)]), now)
        for n in range(2, 25):
            self.store.record_decision(11+n, TW.A+n, "confirmed", 0, now)
        first = self.get(actor=0)[1]
        self.assertEqual((first["total"], len(first["rows"]), first["next_page"]), (25, 20, 1))
        last = self.get(query="kind=weekly&anchor=2026-09-21&page=1", actor=0)[1]
        self.assertEqual(len(last["rows"]), 5)
        found = self.get(query="kind=weekly&anchor=2026-09-21&q=8000024", actor=0)[1]
        self.assertEqual((found["total"], found["rows"][0]["ad_account_no"]), (1, "8000024"))
        hidden = self.get(query="kind=weekly&anchor=2026-09-21&q=8000024")[1]
        self.assertEqual((hidden["total"], hidden["rows"]), (0, []))

    def test_strict_queries_current_stage_and_source_fail_closed(self):
        for query in ("kind=daily", "anchor=2026-02-30", "anchor=20260921", "q="+"a"*201,
                      "page=-1", "page=01", "page=1", "possibility_id=0", "extra=x", "page=0&page=0"):
            self.assertEqual(self.get(query=query)[:2], (400, {"error": "bad-query"}), query)
        for query in ("report_id=1", "report_id=0&account_key=company", "report_id=1&account_key=raw-id",
                      "report_id=1&account_key=company&extra=x"):
            self.assertEqual(self.get("/reports/detail", query)[:2], (400, {"error": "bad-query"}), query)
        for pid in (12, 999):
            self.assertEqual(self.get(query=f"possibility_id={pid}")[:2], (404, TW.WEB.NOT_VISIBLE))
        self.seed_report()
        self.clock.advance(1)
        catalog = self.store.account_catalog()
        for row in catalog["items"]:
            if row["possibility_id"] == 11:
                row["stage"] = "계약만료"
        self.store.record_account_catalog({"generated_at": self.clock.now().isoformat(), "total": 3,
            "complete": True, "items": catalog["items"]},
            [TW.E.NaverIdRow(row["possibility_id"], row["vendor"], row["customer_id_raw"], row["ad_account_no_raw"])
             for row in catalog["ids"]], self.clock.now())
        self.assertEqual(self.get()[1]["total"], 0)
        self.assertEqual(self.get("/reports/detail", "report_id=1&account_key=company")[:2], (404, TW.WEB.NOT_VISIBLE))
        self.store.record_account_catalog_failure(self.clock.now(), "FAILED")
        self.assertEqual(self.get()[0], 503)

    def test_default_and_monthly_period_respect_kst_due_time(self):
        now = self.clock.now()
        expected = R.period("weekly", now.date()-timedelta(days=7))
        if expected.due_at > now:
            expected = R.period("weekly", expected.start-timedelta(days=1))
        self.assertEqual(self.get(query="")[1]["period"], expected.as_dict())
        month = self.get(query="kind=monthly&anchor=2026-09-17")[1]["period"]
        self.assertEqual((month["start"], month["end"], month["due_at"]),
                         ("2026-09-01", "2026-09-30", "2026-10-03T10:00:00+09:00"))


if __name__ == "__main__":
    unittest.main()
