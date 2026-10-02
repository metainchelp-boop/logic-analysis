"""저장된 광고 사유의 계정별 페이지: 실제 WSGI/토큰/읽기 Store 경계.

SQLite 파일 잠금을 지원하는 Linux CI에서 실행한다. 잠금 구현을 대체하지 않으며,
수집에는 합성 전송만 사용하고 화면 요청 중에는 네이버 호출 자체를 거절한다.
"""
import socket
import sys
import unittest
from unittest.mock import patch

from naver_engine.tests import test_web as TW
from naver_engine import erp_read as E, structure_reads as R, web as WEB
from naver_engine.tests import test_account_catalog as TC, test_alerts as TA, test_morning as TM
from naver_engine.tests.fake_naver import FakeNaver
from app.naver_auto import matching as M


PRIVATE_MARKER = "PRIVATE-CHANNEL-PHONE-01000000000"


@unittest.skipUnless(sys.platform.startswith("linux"), "실제 Store 파일 잠금은 Linux CI에서 검증")
class ReasonPageWebTest(TW.WebBase):
    def setUp(self):
        guard = patch.object(socket.socket, "connect", side_effect=AssertionError("외부 송신 금지"))
        guard.start()
        self.addCleanup(guard.stop)
        super().setUp()

    def world(self):
        # WebBase의 토큰/WSGI/읽기 연결을 쓰되 구 아침 점검 자료는 만들지 않는다.
        TM.NAMES.update({TM.A: "가상에이상점", TM.B: "가상비상점"})
        self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
        self.st.record_accounts(TM.kids(TM.A, TM.B), self.fc.now())
        self.save_catalog()
        # 기존 Ads의 선행 라우트가 구조 응답을 가로채지 않도록 독립 전송을 쓴다.
        self.naver = FakeNaver()
        self.naver.route(r"/ncc/campaigns", self.campaigns)
        self.naver.route(r"/ncc/channels", self.channels)
        self.naver.route(r"/ncc/(adgroups|ad-extensions)", lambda call: (200, []))
        result = R.run_structure(self.reader(), self.st, self.fc.now, max_calls=12)
        self.assertEqual(result.counts, {"ok": 2}, result)
        self.source_calls = len(self.naver.calls)
        # 화면 조회는 저장 자료만 읽어야 한다. 합성 전송 호출도 실패시킨다.
        no_reads = patch.object(self.naver, "send", side_effect=AssertionError("화면의 네이버 재조회 금지"))
        no_reads.start()
        self.addCleanup(no_reads.stop)

    def save_catalog(self, stage="진행중", extra=()):
        now = self.fc.now()
        pairs = ((11, TM.A), (12, TM.B)) + tuple(extra)
        rows = [TC.company(pid, stage, company_name=TM.NAMES[cid])
                for pid, cid in pairs]
        self.st.record_account_catalog(
            {"generated_at": now.isoformat(), "total": len(rows), "complete": True, "items": rows},
            [E.NaverIdRow(pid, M.VENDOR_NAVER, str(cid)) for pid, cid in pairs], now)

    @staticmethod
    def prefix(call):
        return "own" if int(call.customer) == TM.A else "other"

    def campaigns(self, call):
        return 200, [{"customerId": int(call.customer), "nccCampaignId": self.prefix(call)+"-campaign",
                      "status": "PAUSED", "statusReason": "CAMPAIGN_PAUSED", "name": PRIVATE_MARKER}]

    def channels(self, call):
        return 200, [{"customerId": int(call.customer),
                      "nccBusinessChannelId": f"{self.prefix(call)}-channel-{n:02}",
                      "status": "PAUSED", "statusReason": "BUSINESS_CHANNEL_DISAPPROVED",
                      "businessInfo": PRIVATE_MARKER, "url": "https://private.invalid/"+PRIVATE_MARKER}
                     for n in range(51)]

    @staticmethod
    def ad_no(cid):
        return str(8_000_000 + cid % 1_000_000)

    def reasons(self, viewer=100, cid=TM.A, page=0, selection="all"):
        return self.get("/accounts/reasons", viewer,
                        query=f"ad_account_no={self.ad_no(cid)}&page={page}&selection={selection}")

    def add_unobserved_account(self, *, extra=()):
        self.fc.advance(1)
        TM.NAMES[TM.C_] = "가상씨상점"
        self.st.record_accounts(TM.kids(TM.A, TM.B, TM.C_), self.fc.now())
        self.save_catalog(extra=extra)

    def test_complete_pages_are_bounded_stable_and_do_not_requery_naver(self):
        status, first = self.reasons()
        self.assertEqual(status, 200, first)
        self.assertEqual(set(first), {"items", "total", "page", "page_size", "next_page", "checked_at", "status"})
        self.assertEqual((first["total"], first["page"], first["page_size"], first["next_page"]), (52, 0, 50, 1))
        self.assertEqual(len(first["items"]), 50)
        self.assertEqual(first["status"], "ok")
        self.assertIsNotNone(first["checked_at"])
        status, last = self.reasons(page=1)
        self.assertEqual(status, 200, last)
        self.assertEqual((last["total"], last["page"], last["page_size"], last["next_page"]), (52, 1, 50, None))
        self.assertEqual(len(last["items"]), 2)
        self.assertEqual((last["status"], last["checked_at"]), (first["status"], first["checked_at"]))
        items = first["items"] + last["items"]
        self.assertEqual(len({(row["entity"], row["entity_id"]) for row in items}), 52)
        self.assertTrue(all(row["entity_id"].startswith("own-") for row in items))
        self.assertEqual(self.reasons(), (200, first))
        self.assertEqual(self.reasons(viewer=0), (200, first))
        self.assertEqual(len(self.naver.calls), self.source_calls)
        for marker in (PRIVATE_MARKER, str(TM.A), str(TM.B), "customerId", "customer_id", "other-channel"):
            self.assertNotIn(marker, str(items))
        channel = next(row for row in items if row["entity"] == "business_channel")
        self.assertEqual(channel["reason"]["code"], "BUSINESS_CHANNEL_DISAPPROVED")
        self.assertEqual(channel["reason"]["code_state"], "known")

    def test_outside_scope_and_nonexistent_account_have_identical_responses(self):
        outside = self.reasons(cid=TM.B)
        missing = self.get("/accounts/reasons", 100, query="ad_account_no=9999999&page=0&selection=all")
        self.assertEqual(outside, (404, WEB.NOT_VISIBLE))
        self.assertEqual(missing, outside)
        self.assertEqual(self.reasons(viewer=101, cid=TM.B)[0], 200)
        self.assertEqual(self.reasons(viewer=0, cid=TM.A, selection="person:101"), outside)

    def test_account_list_contains_only_reason_summary_not_full_pages(self):
        status, board = self.get("/accounts", 0, query="selection=all")
        self.assertEqual(status, 200, board)
        self.assertEqual(len(board["rows"]), 2)
        for row in board["rows"]:
            self.assertNotIn("ad_reasons", row)
            self.assertEqual(row["ad_reason_count"], 52)
        self.assertEqual(row["structure_status"], "ok")
        self.assertIsNotNone(row["structure_checked_at"])
        self.assertNotIn("own-channel-", str(board))
        self.assertNotIn("other-channel-", str(board))
        self.assertEqual(len(self.naver.calls), self.source_calls)

    def test_fresh_mapped_account_without_observation_is_empty_pending(self):
        self.add_unobserved_account(extra=((13, TM.C_),))
        self.assertEqual(self.reasons(viewer=0, cid=TM.C_), (200, {
            "items": [], "total": 0, "page": 0, "page_size": 50, "next_page": None,
            "checked_at": None, "status": "pending"}))

    def test_only_ceo_can_read_current_unmatched_account_without_observation(self):
        self.add_unobserved_account()
        self.assertEqual(self.reasons(viewer=0, cid=TM.C_), (200, {
            "items": [], "total": 0, "page": 0, "page_size": 50, "next_page": None,
            "checked_at": None, "status": "pending"}))
        self.assertEqual(self.reasons(viewer=100, cid=TM.C_), (404, WEB.NOT_VISIBLE))

    def test_ambiguous_claim_is_hidden_even_from_ceo(self):
        self.add_unobserved_account(extra=((13, TM.C_), (14, TM.C_)))
        self.assertEqual(self.reasons(viewer=0, cid=TM.C_), (404, WEB.NOT_VISIBLE))
        self.assertEqual(self.reasons(viewer=100, cid=TM.C_), (404, WEB.NOT_VISIBLE))

    def test_verification_read_only_mode_allows_the_detail_get(self):
        self.app = self.make_app(owner_verification=True)
        self.assertEqual(self.reasons()[0], 200)

    def test_bad_and_out_of_range_pages_are_rejected_without_source_values(self):
        ad_no = self.ad_no(TM.A)
        bad_queries = ["", "page=0", "ad_account_no=0&page=0", "ad_account_no=x&page=0",
                       f"ad_account_no={ad_no}&page=0&extra=1", f"ad_account_no={ad_no}&page=0&page=1",
                       f"ad_account_no={ad_no}&ad_account_no={ad_no}&page=0"]
        bad_queries += [f"ad_account_no={ad_no}&page={page}" for page in
                        ("", "-1", "01", "1.0", "true", "1000000", "2", "999999", "%ZZ")]
        for query in bad_queries:
            with self.subTest(query=query):
                self.assertEqual(self.get("/accounts/reasons", 100, query=query), (400, {"error": "bad-query"}))

    def test_failed_catalog_does_not_expose_previously_collected_reasons(self):
        self.st.record_account_catalog_failure(self.fc.now(), "CATALOG_FAILED")
        self.assertEqual(self.reasons(), (409, {"error": "source-stale"}))

    def test_expired_catalog_does_not_expose_previously_collected_reasons(self):
        self.fc.advance(2*3600+1)
        self.assertEqual(self.reasons(), (409, {"error": "source-stale"}))

    def test_expired_account_snapshot_is_not_repaired_by_fresh_catalog_and_org(self):
        self.fc.advance(31*3600)
        self.st.record_org(TA.org_body(self.fc.now()), self.fc.now())
        self.save_catalog()
        self.assertEqual(self.reasons(), (409, {"error": "source-stale"}))

    def test_stale_org_is_rejected_at_the_existing_viewer_boundary(self):
        self.fc.advance(27*3600)
        self.st.record_accounts(TM.kids(TM.A, TM.B), self.fc.now())
        self.save_catalog()
        self.assertEqual(self.reasons(), (503, {"error": "org-stale"}))

    def test_stage_change_does_not_relabel_old_reasons_as_current(self):
        self.fc.advance(1)
        self.save_catalog(stage="사후 관리")
        self.st.synchronize_management(self.fc.now())
        self.assertEqual(self.reasons(), (409, {"error": "source-stale"}))

    def test_removed_account_is_indistinguishable_from_nonexistent(self):
        self.fc.advance(1)
        self.st.record_accounts(TM.kids(TM.B), self.fc.now())
        self.assertEqual(self.reasons(), (404, WEB.NOT_VISIBLE))

    def test_existing_session_is_rejected_after_employee_resigns(self):
        token = self.token(100)
        self.fc.advance(1)
        body = TA.org_body(self.fc.now())
        for employee in body["employees"]:
            if employee["idx"] == 100:
                employee["status"] = "RESIGNED"
        self.st.record_org(body, self.fc.now())
        status, response, _headers, _payload = self.call(
            "GET", "/accounts/reasons", token,
            query=f"ad_account_no={self.ad_no(TM.A)}&page=0&selection=all")
        self.assertEqual((status, response), (401, {"error": "no-scope"}))
