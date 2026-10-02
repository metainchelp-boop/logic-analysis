"""실관리 누락 대조. 저장소 경계만 합성하고 공개 board의 실제 매칭·권한을 확인한다."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pathlib
import sys
import unittest

BACKEND = pathlib.Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from naver_engine import inventory as I
from naver_engine.tests.test_account_catalog import company
from naver_engine.tests import test_alerts as TA
from app.naver_auto import matching as M, scope as SC, org_snapshot as O

AT = datetime(2026, 10, 2, 10, tzinfo=timezone(timedelta(hours=9)))
A, B, C = 1234567, 2345678, 3456789


def credential(pid, cid=None, ad_no=None):
    return dict(possibility_id=pid, vendor=M.VENDOR_NAVER, customer_id_raw=cid, ad_account_no_raw=ad_no)


class CatalogStore:
    def __init__(self):
        self.catalog = None
        self.state = "accepted"
        self.current = True

    def account_catalog(self):
        return self.catalog

    def account_catalog_status(self):
        return {"state": self.state, "at": AT.isoformat()}

    def accounts_read_at(self):
        return AT

    def inventory_snapshot(self, _now):
        return AT if self.current else None

    def inventory_checks_on(self, _day):
        return {}

    def account_times(self):
        return {}


class ManagedCoverageTest(unittest.TestCase):
    def setUp(self):
        self.store = CatalogStore()
        self.ctx = SimpleNamespace(now=AT, today=AT.date(), org=O.parse_org_snapshot(TA.org_body(AT)),
            accounts={cid: {"present": 1, "ad_account_no": cid+10000000, "account_name": name}
                      for cid, name in ((A, "가상에이상점"), (B, "가상비상점"), (C, "가상씨상점"))},
            live_decisions=[], prospects={})

    def save(self, items, ids=()):
        self.store.catalog = dict(generated_at=AT.isoformat(), items=items, ids=ids)

    def board(self, idx=0, **kw):
        return I.board(self.ctx, self.store, SC.scope_of(self.ctx.org, idx), **kw)

    def test_active_erp_company_without_any_account_remains_in_denominator(self):
        self.save([company(11, "진행중", company_name="가상에이상점"),
                   company(12, "전략 관리", company_name="미연결가상업체"),
                   company(13, "환불중", company_name="비관리업체")],
                  [credential(11, str(A))])
        original = self.board()
        coverage = original["managed_coverage"]
        self.assertEqual((coverage["ready"], coverage["total"], coverage["matched"], coverage["missing"]),
                         (True, 2, 1, 1))
        rows = {r["possibility_id"]: r for r in coverage["items"]}
        self.assertEqual(rows[11]["state"], "matched")
        self.assertEqual(rows[12]["state"], "id_missing")
        self.assertEqual(rows[12]["codes"], ["ID_MISSING", "NO_CANDIDATE"])
        self.assertEqual(original["total"], 3)  # 기존 계정 분모는 그대로다.
        self.assertEqual(self.board(mapping="matched")["managed_coverage"], coverage)

    def test_all_name_candidates_are_counted_before_five_item_display_cap(self):
        self.ctx.accounts = {1234500+i: {"present": 1, "ad_account_no": 9000000+i,
                                        "account_name": "동일가상상점"} for i in range(7)}
        self.save([company(11, "진행중", company_name="동일가상상점")])
        item = self.board(100)["managed_coverage"]["items"][0]
        self.assertEqual(item["state"], "multiple_candidates")
        self.assertEqual(item["candidate_count"], 7)
        self.assertEqual(item["codes"], ["ID_MISSING", "MULTIPLE_CANDIDATES"])
        self.assertEqual(item["matched_account_count"], 0)
        self.assertNotIn("900000", str(item))
        self.assertNotIn("123450", str(item))

    def test_exact_blocked_codes_distinguish_bad_identifier_conflict_and_absent_transfer(self):
        cases = [
            (credential(11, "not-a-number"), "identifier_invalid", M.B_FORMAT),
            (credential(11, "123"), "identifier_invalid", M.B_LENGTH),
            (credential(11, None, "bad"), "identifier_invalid", M.B_AD_FORMAT),
            (credential(11, str(A), str(B+10000000)), "identifier_conflict", M.B_IDENTIFIER_CONFLICT),
            (credential(11, "9999999"), "transfer_unconfirmed", M.B_NOT_LINKED),
            (credential(11, None, "99999999"), "transfer_unconfirmed", M.B_AD_NOT_LINKED),
            (credential(11, str(A)), "candidate_pending", M.B_NAME_DIFFERENT),
        ]
        for cred, state, reason in cases:
            with self.subTest(reason=reason):
                self.save([company(11, "진행중", company_name="서로다른상호")], [cred])
                row = self.board(100)["managed_coverage"]["items"][0]
                self.assertEqual(row["state"], state)
                self.assertIn(reason, row["codes"])
                self.assertEqual(row["matched_account_count"], 0)

    def test_stale_or_failed_sources_never_revive_a_past_confirmation_as_current(self):
        self.save([company(11, "진행중", company_name="가상에이상점")])
        self.ctx.live_decisions = [M.HumanDecision(11, A)]
        self.assertEqual(self.board()["managed_coverage"]["matched"], 1)
        for fail in ("accounts", "catalog_failed", "catalog_stale", "catalog_missing"):
            with self.subTest(fail=fail):
                self.store.current = fail != "accounts"
                self.store.state = "failed" if fail == "catalog_failed" else "accepted"
                self.save([company(11, "진행중", company_name="가상에이상점")])
                if fail == "catalog_stale":
                    self.store.catalog["generated_at"] = (AT-timedelta(hours=3)).isoformat()
                if fail == "catalog_missing":
                    self.store.catalog = None
                coverage = self.board(100)["managed_coverage"]
                self.assertFalse(coverage["ready"])
                self.assertEqual((coverage["total"], coverage["matched"], coverage["missing"]), (None, None, None))
                for item in coverage["items"]:
                    self.assertEqual(item["state"], "source_unavailable")
                    self.assertEqual(item["codes"], ["SOURCE_UNAVAILABLE"])
                    self.assertIsNone(item["matched_account_count"])
                    self.assertIsNone(item["candidate_count"])

    def test_employee_and_leader_see_only_assigned_companies_and_never_other_candidate_details(self):
        self.save([company(11, "진행중", company_name="가상에이상점"),
                   company(12, "전략관리", company_name="다른담당비공개상호"),
                   company(13, "재계약진행중", company_name="담당미정상호"),
                   company(14, "사후관리", company_name="내담당두번째상호")],
                  [credential(11, str(A)), credential(12, str(A))])
        mine = self.board(100)["managed_coverage"]
        self.assertEqual({r["possibility_id"] for r in mine["items"]}, {11, 14})
        self.assertEqual(mine["items"][0]["state"], "identifier_conflict")
        self.assertIn(M.B_CLAIMED_BY_SEVERAL, mine["items"][0]["codes"])
        self.assertNotIn("다른담당비공개상호", str(mine))
        self.assertNotIn(str(A), str(mine))
        self.assertEqual(self.board(1)["managed_coverage"]["total"], 0)  # 팀장도 본인 담당만.
        self.assertEqual(self.board()["managed_coverage"]["total"], 4)
        self.assertEqual(self.board(selection="person:100")["managed_coverage"], mine)
        with self.assertRaises(SC.ScopeError):
            self.board(100, selection="person:101")
        for fields in ({"status": "INACTIVE"}, {"is_management": False}, {"is_deleted": True}):
            body = TA.org_body(AT)
            next(p for p in body["employees"] if p["idx"] == 100).update(fields)
            self.ctx.org = O.parse_org_snapshot(body)
            self.assertEqual(self.board(100)["managed_coverage"]["items"], [])

    def test_unknown_hidden_and_nonmanagement_stages_do_not_become_daily_managed(self):
        self.save([company(11, "진행중", stage_hidden=True), company(12, "진행중", stage_known=False),
                   company(13, "홀딩중"), company(14, "사후관리")])
        self.assertEqual([r["possibility_id"] for r in self.board()["managed_coverage"]["items"]], [14])

    def test_confirmed_elsewhere_and_rejected_names_are_not_free_candidates(self):
        self.ctx.accounts[B]["account_name"] = self.ctx.accounts[A]["account_name"]
        self.save([company(11, "진행중", company_name="가상에이상점"),
                   company(12, "진행중", company_name="다른담당비공개상호")], [credential(11, str(A))])
        self.ctx.live_decisions = [M.HumanDecision(12, A), M.HumanDecision(11, B, M.DECISION_REJECTED)]
        item = self.board(100)["managed_coverage"]["items"][0]
        self.assertEqual(item["state"], "identifier_conflict")
        self.assertIn(M.B_CONFIRMED_ELSEWHERE, item["codes"])
        self.assertEqual(item["candidate_count"], 0)
        self.assertNotIn("다른담당비공개상호", str(item))

    def test_one_matched_account_does_not_hide_another_missing_confirmed_account(self):
        self.save([company(11, "진행중", company_name="가상에이상점")])
        self.ctx.live_decisions = [M.HumanDecision(11, A), M.HumanDecision(11, 9999999)]
        coverage = self.board(100)["managed_coverage"]
        self.assertEqual((coverage["matched"], coverage["missing"]), (0, 1))
        item = coverage["items"][0]
        self.assertEqual((item["state"], item["matched_account_count"]), ("transfer_unconfirmed", 1))
        self.assertIn("CONFIRMED_ACCOUNT_NOT_LISTED", item["codes"])

    def test_old_organization_alone_invalidates_current_managed_coverage(self):
        self.save([company(11, "진행중", company_name="가상에이상점")], [credential(11, str(A))])
        self.ctx.org = O.parse_org_snapshot(TA.org_body(AT-timedelta(days=2)))
        coverage = self.board()["managed_coverage"]
        self.assertFalse(coverage["ready"])
        self.assertIsNone(coverage["matched"])
        self.assertEqual(coverage["items"][0]["state"], "source_unavailable")
