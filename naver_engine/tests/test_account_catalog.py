"""전체 전산 목록 계약: 부분 응답을 미등록으로 오해하지 않는다. 외부 호출 없음."""
import json
import unittest
from datetime import timedelta

from naver_engine import erp_read as E
from naver_engine.credentials import Secret
from naver_engine.tests.fake_naver import FakeClock
from naver_engine.tests.test_erp_read import NOW, MARK_KEY, FakeErp
from naver_engine.tests import test_morning as TM
from naver_engine.tests import test_alerts as TA
from app.naver_auto import matching as M, scope as SC
from naver_engine import views as W


def catalog(*rows):
    return {"generated_at": NOW.isoformat(), "total": len(rows), "complete": True, "items": list(rows)}


def company(pid=11, stage="환불 완료", **kw):
    return {"possibility_id": pid, "company_name": "가상상점", "stage": stage,
            "stage_hidden": False, "stage_known": True, **kw}


class CatalogReadTest(unittest.TestCase):
    def read(self, body):
        fake = FakeErp()
        fake.override[("/api/ad-sync/naver-account-catalog", None)] = (
            200, json.dumps({"status": 200, "result": body}).encode())
        return E.ErpReader(Secret(MARK_KEY), fake, FakeClock(NOW)).read_account_catalog()

    def test_refunded_and_hidden_and_unknown_are_preserved(self):
        out = self.read(catalog(company(), company(12, "계약 만료"),
                                company(13, "기타", stage_hidden=True),
                                company(14, None, stage_known=False)))
        self.assertEqual([r["possibility_id"] for r in out["items"]], [11, 12, 13, 14])
        self.assertEqual(out["items"][0]["stage"], "환불 완료")
        self.assertFalse(out["items"][3]["stage_known"])

    def test_partial_duplicate_and_stale_never_accepted(self):
        for body in (catalog(company(), company()), {**catalog(company()), "complete": False},
                     {**catalog(company()), "total": 2}, {**catalog(company()), "total": True},
                     {**catalog(company()), "generated_at": (NOW-timedelta(days=4)).isoformat()},
                     {**catalog(company()), "generated_at": (NOW+timedelta(hours=1)).isoformat()},
                     catalog(company(stage_hidden="false"))):
            with self.subTest(body=body), self.assertRaises(E.ErpIncomplete):
                self.read(body)

    def test_extra_fields_never_retained(self):
        out = self.read(catalog(company(phone="private", api_key="secret")))
        self.assertNotIn("private", str(out))
        self.assertNotIn("secret", str(out))

    def test_nullable_company_name_does_not_drop_company_or_catalog(self):
        out = self.read(catalog(company(company_name=None)))
        self.assertEqual(out["items"][0]["possibility_id"], 11)
        self.assertIsNone(out["items"][0]["company_name"])


class InventoryViewTest(TM.Base):
    def setUp(self):
        super().setUp()
        self.names_before = dict(TM.NAMES)
        TM.NAMES.update({TM.A: "가상에이상점", TM.B: "가상비상점", TM.C_: "가상씨상점"})
        self.addCleanup(lambda: (TM.NAMES.clear(), TM.NAMES.update(self.names_before)))
        self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
        self.st.record_accounts(TM.kids(TM.A, TM.B, TM.C_), self.fc.now())

    def save(self, items, ids=()):
        body = {"generated_at": self.fc.now().isoformat(), "total": len(items),
                "complete": True, "items": items}
        self.st.record_account_catalog(body, ids, self.fc.now())

    def board(self, idx=0, **kw):
        from naver_engine import inventory
        ctx = W.load(self.st, self.fc.now())
        return inventory.board(ctx, self.st, SC.scope_of(ctx.org, idx), **kw)

    def test_all_accounts_include_expired_refunded_and_no_erp(self):
        self.save([company(11, "계약 만료", company_name=TM.NAMES[TM.A]),
                   company(12, "환불 완료", company_name=TM.NAMES[TM.B])],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)),
                   E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))])
        result = self.board()
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["counts"]["matched"], 2)
        self.assertEqual(result["counts"]["no_erp_record"], 1)
        self.assertEqual({r["workflow"] for r in result["rows"]}, {"계약만료", "환불완료", "미분류"})
        self.assertEqual(len(self.board(workflow="환불완료")["rows"]), 1)

    def test_employee_sees_own_matched_only(self):
        self.save([company(11, company_name=TM.NAMES[TM.A]), company(12, company_name=TM.NAMES[TM.B])],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)), E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))])
        result = self.board(100)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["rows"][0]["possibility_id"], 11)
        with self.assertRaises(SC.ScopeError):
            self.board(100, selection="person:101")

    def test_catalog_missing_stale_or_failed_does_not_claim_unregistered(self):
        self.assertEqual(self.board()["counts"]["no_erp_record"], 0)
        self.save([company(11)])
        self.st.record_account_catalog_failure(self.fc.now(), "CATALOG_FAILED")
        self.assertEqual(self.board()["counts"]["no_erp_record"], 0)
        self.assertEqual(self.board()["catalog_status"], "failed")

    def test_duplicate_name_is_unclassified_not_auto_linked(self):
        self.save([company(11, company_name=TM.NAMES[TM.A]), company(12, company_name=TM.NAMES[TM.A])])
        row = next(r for r in self.board()["rows"] if r["ad_account_no"] == str(8_000_000 + TM.A % 1_000_000))
        self.assertEqual(row["mapping"], "unclassified")
        self.assertIsNone(row["possibility_id"])

    def test_failed_atomic_refresh_preserves_last_catalog(self):
        self.save([company(11)])
        before = self.st.account_catalog()
        with self.assertRaises(E.ErpIncomplete):
            self.st.record_account_catalog({**catalog(company()), "total": 2}, [], self.fc.now())
        self.assertEqual(self.st.account_catalog(), before)

    def test_all_name_candidates_remain_unclassified_beyond_display_cap(self):
        ids = tuple(range(100001, 100007))
        TM.NAMES.update({cid: "동일한가상상점" for cid in ids})
        self.fc.advance(1)
        self.st.record_accounts(TM.kids(*ids), self.fc.now())
        self.save([company(11, company_name="동일한가상상점")])
        result = self.board()
        self.assertEqual(result["total"], 6)
        self.assertEqual(result["counts"], {"matched": 0, "no_erp_record": 0, "unclassified": 6})

    def test_extra_name_candidate_of_already_matched_company_is_not_unregistered(self):
        TM.NAMES[TM.B] = TM.NAMES[TM.A]
        self.fc.advance(1)
        self.st.record_accounts(TM.kids(TM.A, TM.B, TM.C_), self.fc.now())
        self.save([company(11, company_name=TM.NAMES[TM.A])], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        rows = {r["ad_account_no"]: r for r in self.board()["rows"]}
        self.assertEqual(rows[str(8_000_000 + TM.A % 1_000_000)]["mapping"], "matched")
        self.assertEqual(rows[str(8_000_000 + TM.B % 1_000_000)]["mapping"], "unclassified")

    def test_latest_account_failure_invalidates_classification_and_employee_visibility(self):
        from naver_engine import store as S
        self.save([company(11, company_name=TM.NAMES[TM.A])], [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A))])
        self.st.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ("KEY_REJECTED",), self.fc.now())
        result = self.board()
        self.assertFalse(result["accounts_current"])
        self.assertEqual(result["counts"], {"matched": 0, "no_erp_record": 0, "unclassified": 3})
        self.assertEqual(self.board(100)["total"], 0)


class InventoryApiTest(InventoryViewTest):
    def test_api_roster_and_counts_and_employee_boundary(self):
        from naver_engine.tests.test_web import WebBase
        from naver_engine import web as WEB, session as SE, store as S
        self.save([company(11, company_name=TM.NAMES[TM.A]), company(12, company_name=TM.NAMES[TM.B])],
                  [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)), E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))])
        self.signer = SE.TokenSigner(Secret("z"*40))
        self.app = WEB.App(open_read=lambda: S.open_reader(self.path), write=lambda f: f(self.st),
                           signer=self.signer, profiles=None, clock=self.fc.now, owner_verification=True)
        self.call = WebBase.call.__get__(self)
        status, data, _, _ = self.call("GET", "/accounts", self.signer.issue(100, self.fc.now()))
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 1)
        status, data, _, _ = self.call("GET", "/me", self.signer.issue(0, self.fc.now()))
        self.assertEqual(status, 200)
        self.assertEqual(data["teams"], [])
        people = {p["idx"]: p for p in data["people"]}
        self.assertEqual(people[100]["account_count"], 1)
        self.assertEqual(people[101]["account_count"], 1)
        status, _, _, _ = self.call("GET", "/accounts", self.signer.issue(100, self.fc.now()), query="selection=person:101")
        self.assertEqual(status, 404)


from naver_engine.tests.test_web import WebBase


class HiddenLegacyBoundaryTest(WebBase):
    def test_hidden_catalog_blocks_all_employee_legacy_read_paths(self):
        self.assertEqual(self.get("/clients/11", 100)[0], 200)
        rows = [company(pid, company_name=TM.shop(pid), stage_hidden=(pid == 11)) for pid in (11, 12, 13, 14)]
        body = {"generated_at": self.fc.now().isoformat(), "total": len(rows), "complete": True, "items": rows}
        self.st.record_account_catalog(body, (), self.fc.now())
        self.assertEqual(self.get("/clients/11", 100)[0], 404)
        status, board = self.get("/board", 100, query="attention=0")
        self.assertEqual(status, 200)
        self.assertNotIn(11, {r["possibility_id"] for r in board["rows"]})
        self.assertEqual(self.get("/clients/11", 0)[0], 200)


if __name__ == "__main__":
    unittest.main()
