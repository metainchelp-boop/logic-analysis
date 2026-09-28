"""네이버 읽기 관문(S4) 시험 — 가짜 네이버로 끝까지 · 네트워크 0 · 비밀값 0.

돌리는 법(저장소 맨 위에서):  python3 -m unittest -v naver_engine.tests.test_naver_read

지키는 것(설계 v1.8 「첫 조각 S4」):
  GET 만 · 정해진 호스트·경로만 · 넘겨주기 안 따라감 · 날 번호 거절(손잡이만) · 남길 칸만 ·
  모르는 통계 모양은 0 이 아님 · 빠진 줄은 모름 · 자료 기준 시각 · 하위 계정 목록은 전부 아니면 버림 ·
  응답 고객 번호 대조 · 속도 제한·다시 보내기 · 호출 수 상한 · 비밀값·개인정보가 로그·오류에 0.
"""
from __future__ import annotations

import http.server
import io
import json
import logging
import pickle
import random
import socket
import threading
import traceback
import unittest
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from naver_engine import handles as H
from naver_engine import naver_read as R
from naver_engine.credentials import (CredentialsMissing, ManagerCredentials, Secret, customer_tail,
                                      load_manager_credentials)
from naver_engine.tests.fake_naver import (AGENCY_ID, MARK_API_KEY, MARK_BIZINFO, MARK_MGR_NAVERID, MARK_NEWFIELD,
                                           MARK_OWNER, MARK_SECRET, MARK_TRACK, Agency, FakeClock, FakeNaver,
                                           campaign, cycle_str, page_of)

NOW = datetime(2026, 9, 29, 6, 40, tzinfo=H.KST)
YDAY = NOW.date() - timedelta(days=1)
ACC = 3000001
MARKS = (MARK_API_KEY, MARK_SECRET, MARK_OWNER, MARK_MGR_NAVERID, MARK_TRACK, MARK_BIZINFO, MARK_NEWFIELD, str(ACC),
         str(AGENCY_ID))


def creds() -> ManagerCredentials:
    return ManagerCredentials(AGENCY_ID, Secret(MARK_API_KEY), Secret(MARK_SECRET))


def check_handle(cid=ACC, stage="진행중", pid=501, link=H.LINK_CONFIRMED, end=None, now=NOW, age_h=1):
    return H.issue_check_handle(customer_id=cid, possibility_id=pid, link_state=link, stage=stage,
                                stage_as_of=now - timedelta(hours=age_h), latest_end_date=end, now=now)


def preview_handle(cid=ACC, pid=501, by=112, now=NOW, cand=77):
    return H.issue_preview_handle(customer_id=cid, possibility_id=pid, candidate_id=cand, stage="진행중",
                                  stage_as_of=now - timedelta(hours=1), latest_end_date=None, now=now, requested_by=by)


class _Collect(logging.Handler):
    """로그를 **형식을 갖춰**(오류 추적 exc_info · stack_info 포함) 모은다 — 추적에 키가 섞이는 것까지 본다."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


class Base(unittest.TestCase):
    def setUp(self):
        self.naver = FakeNaver()
        self.clock = FakeClock(NOW)
        self.reader = R.NaverReader(creds(), transport=self.naver, clock=self.clock, rng=random.Random(7))
        self.logs = _Collect()
        lg = logging.getLogger("naver_engine")
        lg.addHandler(self.logs)
        lg.setLevel(logging.DEBUG)
        self.errors = []

    def tearDown(self):
        logging.getLogger("naver_engine").removeHandler(self.logs)
        # 로그·오류 문구 어디에도 비밀값·개인정보·전체 고객 번호가 없다
        text = "\n".join(self.logs.lines + self.errors)
        for m in MARKS:
            self.assertNotIn(m, text, f"로그·오류에 표지 값이 나왔다: {m[:6]}…")
        # 가짜 네이버가 받은 요청은 전부 GET · 정해진 호스트 · 본문 없음 · 키·서명 맞음
        for c in self.naver.calls:
            self.assertEqual(c.method, "GET")
            self.assertEqual((c.scheme, c.host), ("https", "api.searchad.naver.com"), "호스트는 글자 그대로 고정")
            self.assertFalse(c.has_body)
            self.assertTrue(c.api_key_ok and c.sig_ok, "키·서명이 틀렸다")

    def expect(self, exc, fn, *a, **kw):
        with self.assertRaises(exc) as cm:
            fn(*a, **kw)
        # 문구만이 아니라 원인 사슬(__cause__ · __context__)까지 포함한 추적 전체를 본다
        self.errors.append("".join(traceback.format_exception(cm.exception)))
        return cm.exception


# ── 1. GET 만 · 호스트·경로 ─────────────────────────────────────────
class GateTest(Base):
    def test_non_get_refused_before_request(self):
        for m in ("POST", "PUT", "DELETE", "PATCH", "get", "HEAD", ""):
            self.expect(R.WriteForbidden, self.reader._gate, m, "/ncc/campaigns", None, ACC)
        self.assertEqual(self.naver.calls, [], "거절한 요청이 나가면 안 된다")
        self.assertEqual(self.reader.calls, 0)

    def test_allowed_methods_is_exactly_get(self):
        self.assertEqual(R._ALLOWED_METHODS, frozenset({"GET"}))

    def test_built_request_rechecked_before_send(self):
        # 요청 만드는 코드가 바뀌어 방식이 GET 이 아니게 되거나 본문이 붙어도, 보내기 전에 한 번 더 막는다
        real = urllib.request.Request
        for kind in ("method", "body"):
            class Bad(real):
                def get_method(self, _k=kind):
                    return "POST" if _k == "method" else super().get_method()

                @property
                def data(self, _k=kind):
                    return b"x" if _k == "body" else None

                @data.setter
                def data(self, v):
                    pass
            urllib.request.Request = Bad
            try:
                self.expect(R.WriteForbidden, self.reader._gate, "GET", "/ncc/campaigns", None, ACC)
            finally:
                urllib.request.Request = real
        self.assertEqual(self.naver.calls, [])

    def test_host_is_pinned(self):
        self.assertEqual((R.BASE_HOST, R.BASE_URL), ("api.searchad.naver.com", "https://api.searchad.naver.com"))
        old = R.BASE_URL
        for other in ("https://api.searchad.naver.com.evil.example", "http://api.searchad.naver.com",
                      "https://evil.example"):
            R.BASE_URL = other
            try:
                self.expect(R.PathForbidden, self.reader._gate, "GET", "/ncc/campaigns", None, ACC)
            finally:
                R.BASE_URL = old
        self.assertEqual(self.naver.calls, [], "만든 뒤 호스트 검사가 막아야 한다")

    def test_path_not_allowed(self):
        for p in ("/ncc/keywords", "/ncc/adgroups", "/ncc/campaigns/abc", "/manager-accounts/x/child-ad-accounts",
                  "/billing/bizmoney/histories/charge", "//evil.example/stats", "/stats/../ncc/keywords"):
            self.expect(R.PathForbidden, self.reader._gate, "GET", p, None, ACC)
        self.assertEqual(self.naver.calls, [])

    def test_signature_excludes_query_and_customer_header(self):
        Agency(self.naver)
        mh = self.reader.manager_handle()
        self.reader.list_manager_accounts(mh)
        c = self.naver.calls[0]
        self.assertEqual(c.path, "/manager-accounts")
        self.assertEqual(c.query["size"], ["1000"])
        self.assertEqual(c.customer, str(AGENCY_ID))
        self.assertTrue(c.sig_ok)

    def test_account_calls_use_account_customer(self):
        self.naver.route(r"/ncc/campaigns", lambda c: (200, [campaign(ACC, 1)]))
        self.reader.get_campaigns(check_handle())
        self.assertEqual(self.naver.calls[0].customer, str(ACC))

    def test_redirect_is_not_followed(self):
        hits = {"n": 0}

        class Target(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits["n"] += 1
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        target = http.server.HTTPServer(("127.0.0.1", 0), Target)
        tport = target.server_address[1]

        code = {"v": 302}

        class Redir(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(code["v"])
                self.send_header("Location", f"http://127.0.0.1:{tport}/steal")
                self.end_headers()

            def log_message(self, *a):
                pass

        redir = http.server.HTTPServer(("127.0.0.1", 0), Redir)
        for s in (target, redir):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{redir.server_address[1]}/x",
                                         headers={"X-API-KEY": "k"}, method="GET")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), R._NoRedirect())
            t = R.UrllibTransport()
            t._opener = opener  # 시험용: 이 컴퓨터의 프록시 설정을 거치지 않게만 바꾼다(넘겨주기 거절은 그대로)
            for c in (301, 302, 303, 307, 308):
                code["v"] = c
                req = urllib.request.Request(f"http://127.0.0.1:{redir.server_address[1]}/x",
                                             headers={"X-API-KEY": "k"}, method="GET")
                status, _ = t.send(req, 5)
                self.assertEqual(status, c)
                self.assertEqual(hits["n"], 0, f"{c} 넘겨주기를 따라가면 키 머리글이 다른 곳으로 간다")
        finally:
            for s in (target, redir):
                s.shutdown()
                s.server_close()

    def test_default_transport_refuses_redirect_handler(self):
        handlers = [type(h) for h in R.UrllibTransport()._opener.handlers]
        self.assertIn(R._NoRedirect, handlers)
        self.assertNotIn(urllib.request.HTTPRedirectHandler, handlers)

    def test_default_transport_ignores_env_proxy_and_verifies(self):
        import os
        import ssl
        old = {k: os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy")}
        os.environ["HTTPS_PROXY"] = os.environ["https_proxy"] = "http://proxy.invalid:3128"
        try:
            t = R.UrllibTransport()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        proxies = [h for h in t._opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
        # 빈 ProxyHandler 를 넘기면 기본 프록시 처리기(환경변수를 읽는 것)가 끼지 않는다
        self.assertEqual([p.proxies for p in proxies if p.proxies], [], "환경변수 프록시를 따르면 키가 다른 서버를 거친다")
        https = [h for h in t._opener.handlers if isinstance(h, urllib.request.HTTPSHandler)]
        self.assertEqual(len(https), 1)
        ctx = https[0]._context
        self.assertEqual((ctx.verify_mode, ctx.check_hostname), (ssl.CERT_REQUIRED, True))

    def test_unexpected_transport_error_is_masked(self):
        def boom(call):
            raise ValueError(f"Invalid header value {MARK_API_KEY}")
        self.naver.tick = boom
        e = self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle())
        self.assertEqual((e.kind, e.detail), (R.KIND_OTHER, "ValueError"))
        self.assertIsNone(e.__cause__)
        self.assertTrue(e.__suppress_context__)


# ── 2. 손잡이 — 날 번호 거절 ────────────────────────────────────────
class HandleTest(Base):
    def test_raw_numbers_refused(self):
        for raw in (ACC, str(ACC), {"customer_id": ACC}, None, AGENCY_ID):
            self.expect(H.HandleInvalid, self.reader.get_campaigns, raw)
            self.expect(H.HandleInvalid, self.reader.get_bizmoney, raw)
            self.expect(H.HandleInvalid, self.reader.list_manager_accounts, raw)
        self.assertEqual(self.naver.calls, [])

    def test_forged_handle_refused(self):
        h = check_handle()
        fake = H.AccountHandle(ACC + 1, h.possibility_id, h.purpose, h.issued_on, None, None, h.issued_at, h.nonce,
                               h._tag)
        self.expect(H.HandleInvalid, self.reader.get_campaigns, fake)
        self.assertEqual(self.naver.calls, [])

    def test_every_handle_field_is_signed(self):
        """서명을 그대로 두고 칸 하나만 바꾼 가짜 손잡이는 모두 거절(목적 · 날짜 · 가망 · 요청자 · 후보 · 시각 · 번호)."""
        y = NOW.date() - timedelta(days=1)
        ck = check_handle()
        pv = preview_handle(by=7101)
        variants = [
            (ck, dict(customer_id=ACC + 1)), (ck, dict(possibility_id=502)), (ck, dict(purpose=H.PURPOSE_PREVIEW)),
            (ck, dict(issued_on=y)), (ck, dict(requested_by=5)), (ck, dict(issued_at=ck.issued_at - timedelta(days=1))),
            (ck, dict(nonce="x")), (ck, dict(candidate_id=9)),
            (pv, dict(purpose=H.PURPOSE_CHECK)), (pv, dict(requested_by=0)), (pv, dict(candidate_id=78)),
            (pv, dict(nonce="0" * 24)), (pv, dict(possibility_id=999)),
        ]
        for h, change in variants:
            f = dict(customer_id=h.customer_id, possibility_id=h.possibility_id, purpose=h.purpose,
                     issued_on=h.issued_on, requested_by=h.requested_by, candidate_id=h.candidate_id,
                     issued_at=h.issued_at, nonce=h.nonce)
            f.update(change)
            fake = H.AccountHandle(f["customer_id"], f["possibility_id"], f["purpose"], f["issued_on"],
                                   f["requested_by"], f["candidate_id"], f["issued_at"], f["nonce"], h._tag)
            with self.assertRaises(H.HandleInvalid, msg=str(change)):
                H.require_account(fake, NOW, (H.PURPOSE_CHECK, H.PURPOSE_PREVIEW))

    def test_manager_handle_checks(self):
        y = H.issue_manager_handle(AGENCY_ID, NOW - timedelta(days=1))
        self.expect(H.HandleInvalid, self.reader.list_manager_accounts, y)
        fake = H.ManagerHandle(AGENCY_ID, NOW.date(), "not-a-signature")
        self.expect(H.HandleInvalid, self.reader.list_manager_accounts, fake)
        self.assertEqual(self.naver.calls, [])

    def test_handle_is_immutable_and_not_picklable(self):
        h = check_handle()
        with self.assertRaises(AttributeError):
            h.customer_id = ACC + 1
        with self.assertRaises(TypeError):
            pickle.dumps(h)

    def test_yesterdays_handle_refused(self):
        h = check_handle(now=NOW - timedelta(days=1))
        self.expect(H.HandleInvalid, self.reader.get_campaigns, h)
        self.assertEqual(self.naver.calls, [])

    def test_purpose(self):
        pv = preview_handle()
        self.expect(H.HandleInvalid, self.reader.get_bizmoney, pv)
        self.expect(H.HandleInvalid, self.reader.get_stats_summary, pv, ["a"], YDAY, YDAY)
        self.expect(H.HandleInvalid, self.reader.get_channels, check_handle())
        self.assertEqual(self.naver.calls, [])

    def test_manager_and_account_handles_do_not_mix(self):
        self.expect(H.HandleInvalid, self.reader.get_campaigns, self.reader.manager_handle())
        self.expect(H.HandleInvalid, self.reader.list_manager_accounts, check_handle())
        other = H.issue_manager_handle(AGENCY_ID + 1, NOW)
        self.expect(H.HandleInvalid, self.reader.list_manager_accounts, other)
        self.assertEqual(self.naver.calls, [])


class EligibilityTest(unittest.TestCase):
    def test_link_states(self):
        for link in (H.LINK_CONFIRMED, H.LINK_AUTO):
            self.assertEqual(check_handle(link=link).customer_id, ACC)
        for link in ("name", "candidate", "rejected", "", None, "CONFIRMED"):
            with self.assertRaises(H.NotEligible):
                check_handle(link=link)

    def test_stage_spelling_both_ways(self):
        for stage in ("사후 관리", "사후관리", "재계약 진행중", "재계약진행중", "전략 관리", " 진행중 ", "환불중", "홀딩중"):
            self.assertEqual(check_handle(stage=stage).customer_id, ACC)
        for stage in ("가망", "계약 대기", "", None, 3):
            with self.assertRaises(H.NotEligible):
                check_handle(stage=stage)

    def test_ended_contract_14_days(self):
        today = NOW.date()
        self.assertTrue(check_handle(stage="계약 만료", end=today - timedelta(days=14)))
        with self.assertRaises(H.NotEligible) as cm:
            check_handle(stage="계약 만료", end=today - timedelta(days=15))
        self.assertEqual(cm.exception.reason, "ended-over-14-days")
        with self.assertRaises(H.NotEligible) as cm:
            check_handle(stage="계약만료", end=None)
        self.assertEqual(cm.exception.reason, "ended-end-date-unknown")
        with self.assertRaises(H.NotEligible):  # 날짜가 아닌 값
            check_handle(stage="계약만료", end="2026-09-20")

    def test_14_days_applies_to_every_stage(self):
        """전산 단계가 늦게 바뀌는 곳(계약은 끝났는데 진행중) — 종료일이 적혀 있으면 어느 단계든 14일 규칙."""
        today = NOW.date()
        for stage in ("진행중", "환불중", "재계약 진행중", "홀딩중", "사후 관리"):
            self.assertTrue(check_handle(stage=stage, end=today - timedelta(days=14)))
            self.assertTrue(check_handle(stage=stage, end=today + timedelta(days=90)))
            with self.assertRaises(H.NotEligible, msg=stage) as cm:
                check_handle(stage=stage, end=today - timedelta(days=60))
            self.assertEqual(cm.exception.reason, "ended-over-14-days")
        self.assertTrue(check_handle(stage="진행중", end=None), "종료일을 모르면 진행 단계는 단계를 믿는다")

    def test_preview_also_obeys_14_days(self):
        with self.assertRaises(H.NotEligible):
            H.issue_preview_handle(customer_id=ACC, possibility_id=5, candidate_id=9, stage="계약만료",
                                   stage_as_of=NOW - timedelta(hours=1), latest_end_date=NOW.date() - timedelta(days=30),
                                   now=NOW, requested_by=112)

    def test_stale_stage_refused(self):
        self.assertTrue(check_handle(age_h=71))
        with self.assertRaises(H.NotEligible) as cm:
            check_handle(age_h=73)
        self.assertEqual(cm.exception.reason, "stage-stale")
        with self.assertRaises(H.NotEligible):
            H.issue_check_handle(customer_id=ACC, possibility_id=5, link_state="auto", stage="진행중",
                                 stage_as_of=datetime(2026, 9, 29, 6, 0), latest_end_date=None, now=NOW)
        # 미래 시각으로 찍힌 단계 자료는 낡을 수가 없다 — 받지 않는다(5분 여유)
        self.assertTrue(check_handle(age_h=-4 / 60))
        for ahead_h in (6 / 60, 24 * 30):
            with self.assertRaises(H.NotEligible) as cm:
                check_handle(age_h=-ahead_h)
            self.assertEqual(cm.exception.reason, "stage-time-in-future")

    def test_ids(self):
        for bad in (True, False, 0, -1, "12a", "", "1 2", 10 ** 15, 1.5):
            with self.assertRaises(H.NotEligible):
                check_handle(cid=bad)
        self.assertEqual(check_handle(cid=" 3000001 ").customer_id, ACC)
        for bad in (0, -3, True, "5", None):
            with self.assertRaises(H.NotEligible):
                check_handle(pid=bad)

    def test_ceo_zero_can_request_preview(self):
        self.assertEqual(preview_handle(by=0).requested_by, 0)  # 대표 = 0번(0 을 「없음」으로 읽지 않는다)
        for bad in (-1, None, True, "0"):
            with self.assertRaises(H.NotEligible):
                preview_handle(by=bad)

    def test_preview_limits(self):
        """미리보기 손잡이 — 10분 · 3번 · 한 사람 하루 300개 · 후보 번호 필수(1,784곳 일괄 읽기를 막는다)."""
        naver, clock = FakeNaver(), FakeClock(NOW)
        naver.route(r"/ncc/campaigns", lambda c: (200, [campaign(ACC, 1)]))
        reader = R.NaverReader(creds(), transport=naver, clock=clock)
        h = preview_handle(by=7001)
        for _ in range(H.PREVIEW_MAX_USES):
            reader.get_campaigns(h)
        with self.assertRaises(H.HandleInvalid):
            reader.get_campaigns(h)
        h2 = preview_handle(by=7001)
        clock.advance(11 * 60)
        with self.assertRaises(H.HandleInvalid):
            reader.get_campaigns(h2)
        self.assertEqual(len(naver.calls), H.PREVIEW_MAX_USES)
        for bad in (0, -1, None, True, "77"):
            with self.assertRaises(H.NotEligible):
                preview_handle(by=7002, cand=bad)
        for _ in range(H.PREVIEW_DAILY_CAP - 2):
            preview_handle(by=7001)
        with self.assertRaises(H.NotEligible) as cm:
            preview_handle(by=7001)
        self.assertEqual(cm.exception.reason, "preview-daily-cap")
        self.assertTrue(preview_handle(by=7003), "다른 사람은 따로 센다")

    def test_forged_candidate_refused(self):
        h = preview_handle(by=7004)
        fake = H.AccountHandle(h.customer_id, h.possibility_id, h.purpose, h.issued_on, h.requested_by,
                               h.candidate_id + 1, h.issued_at, h.nonce, h._tag)
        with self.assertRaises(H.HandleInvalid):
            H.require_account(fake, NOW, (H.PURPOSE_PREVIEW,))

    def test_naive_now_refused(self):
        with self.assertRaises(ValueError):
            H.issue_manager_handle(AGENCY_ID, datetime(2026, 9, 29, 6, 0))


# ── 3. 남길 칸만 · 하위 계정 목록 전부 아니면 버림 ───────────────────
class ChildListTest(Base):
    def test_all_children_complete(self):
        ag = Agency(self.naver)
        res = self.reader.list_all_children(self.reader.manager_handle())
        self.assertEqual(len(res.accounts), 2345 + 90 + 339)
        self.assertEqual(res.per_manager, {101: 2345, 102: 90, 103: 339})
        self.assertEqual(sum(1 for c in self.naver.calls if "child-ad-accounts" in c.path), 3 + 1 + 1)
        pages = [c.query["page"][0] for c in self.naver.calls if c.path == "/manager-accounts/101/child-ad-accounts"]
        self.assertEqual(pages, ["0", "1", "2"])
        blob = json.dumps([res.accounts, res.managers], ensure_ascii=False)
        for m in (MARK_OWNER, MARK_MGR_NAVERID, MARK_NEWFIELD):
            self.assertNotIn(m, blob, "남길 칸 목록에 없는 칸이 새어 나왔다")
        one = res.accounts[3000000]
        self.assertEqual(set(one), set(("customerId", "adAccountNo", "adAccountName", "accountRole")))
        self.assertEqual(set(res.managers[0]), {"managerAccountNo", "name", "childAdAccountCount", "deleted", "disabled"})
        self.assertIn("ownerNaverId", ag.children[101][0], "원본(가짜 네이버)에는 있었다 — 빠진 것은 관문 덕이다")

    def test_one_manager_fails_whole_list_dropped(self):
        Agency(self.naver)
        for _ in range(4):
            self.naver.script("/manager-accounts/103/child-ad-accounts", (500, {"code": 500}))
        e = self.expect(R.NaverApiError, self.reader.list_all_children, self.reader.manager_handle())
        self.assertEqual(e.kind, R.KIND_SERVER)

    def test_short_list_is_incomplete(self):
        ag = Agency(self.naver)
        self.naver.route(r"/manager-accounts/102/child-ad-accounts",
                         lambda c: page_of(ag.children[102][:80], c, total=90))
        self.naver.routes.insert(0, self.naver.routes.pop())  # 위 경로가 먼저 걸리게
        self.expect(R.IncompleteList, self.reader.list_all_children, self.reader.manager_handle())

    def test_missing_total_is_incomplete(self):
        self.naver.route(r"/manager-accounts", lambda c: (200, {"content": []}))
        self.expect(R.IncompleteList, self.reader.list_manager_accounts, self.reader.manager_handle())

    def test_bare_list_is_incomplete(self):
        self.naver.route(r"/manager-accounts", lambda c: (200, [{"managerAccountNo": 1}]))
        self.expect(R.IncompleteList, self.reader.list_manager_accounts, self.reader.manager_handle())

    def test_total_changes_mid_way(self):
        ag = Agency(self.naver)
        state = {"n": 0}

        def moving(c):
            state["n"] += 1
            return page_of(ag.children[101], c, total=2345 + state["n"])
        self.naver.routes.insert(0, (__import__("re").compile(r"/manager-accounts/101/child-ad-accounts"), moving))
        self.expect(R.IncompleteList, self.reader.list_child_accounts, self.reader.manager_handle(), 101)

    def test_repeated_rows_are_incomplete(self):
        """1부터 세는 쪽 번호(0·1쪽이 같은 줄) · 쪽 사이 순서가 바뀐 경우 — 합계는 맞아도 버린다."""
        rows = [{"customerId": 5000000 + i} for i in range(2000)]

        def one_based(c):
            page = max(int(c.query["page"][0]), 1) - 1
            return 200, {"content": rows[page * 1000:(page + 1) * 1000], "totalElements": 2000, "last": False}
        self.naver.route(r"/manager-accounts/101/child-ad-accounts", one_based)
        self.expect(R.IncompleteList, self.reader.list_child_accounts, self.reader.manager_handle(), 101)

    def test_page_number_mismatch(self):
        rows = [{"customerId": 5000000 + i} for i in range(1500)]

        def wrong_number(c):
            r = page_of(rows, c)
            r[1]["number"] = int(c.query["page"][0]) + 1
            return r
        self.naver.route(r"/manager-accounts/101/child-ad-accounts", wrong_number)
        self.expect(R.IncompleteList, self.reader.list_child_accounts, self.reader.manager_handle(), 101)

    def test_manager_says_children_but_list_empty(self):
        ag = Agency(self.naver, sizes=(3, 2))
        ag.managers[1]["managerAccount"]["childAdAccountCount"] = 40
        ag.children[102] = []
        self.expect(R.IncompleteList, self.reader.list_all_children, self.reader.manager_handle())

    def test_null_child_count_is_fine(self):
        ag = Agency(self.naver, sizes=(3, 2))
        for m in ag.managers:
            m["managerAccount"]["childAdAccountCount"] = None  # 실측 모양
        self.assertEqual(len(self.reader.list_all_children(self.reader.manager_handle()).accounts), 5)

    def test_non_200_success_refused(self):
        Agency(self.naver)
        self.naver.script("/manager-accounts", (206, {"content": [], "totalElements": 0}))
        e = self.expect(R.NaverApiError, self.reader.list_manager_accounts, self.reader.manager_handle())
        self.assertEqual(e.kind, R.KIND_BAD_RESPONSE)

    def test_zero_managers(self):
        self.naver.route(r"/manager-accounts", lambda c: page_of([], c))
        self.expect(R.IncompleteList, self.reader.list_all_children, self.reader.manager_handle())

    def test_page_cap(self):
        self.naver.route(r"/manager-accounts/101/child-ad-accounts",
                         lambda c: (200, {"content": [{"customerId": 1 + int(c.query["page"][0])}],
                                          "totalElements": 10 ** 6, "last": False}))
        self.expect(R.IncompleteList, self.reader.list_child_accounts, self.reader.manager_handle(), 101)
        self.assertEqual(len(self.naver.calls), R.MAX_PAGES)

    def test_row_without_customer_id(self):
        self.naver.route(r"/manager-accounts/101/child-ad-accounts",
                         lambda c: page_of([{"customerId": None, "ownerNaverId": MARK_OWNER}], c))
        self.expect(R.IncompleteList, self.reader.list_child_accounts, self.reader.manager_handle(), 101)

    def test_bad_manager_number(self):
        for bad in (0, -1, True, "101"):
            self.expect(ValueError, self.reader.list_child_accounts, self.reader.manager_handle(), bad)
        self.assertEqual(self.naver.calls, [])


# ── 4. 광고주 계정 읽기 — 남길 칸 · 고객 번호 대조 ──────────────────
class AccountReadTest(Base):
    def test_campaigns_kept_fields_only(self):
        self.naver.route(r"/ncc/campaigns", lambda c: (200, [campaign(ACC, 1), campaign(ACC, 2)]))
        out = self.reader.get_campaigns(check_handle())
        self.assertEqual([c["nccCampaignId"] for c in out], [f"cmp-{ACC}-1", f"cmp-{ACC}-2"])
        blob = json.dumps(out, ensure_ascii=False)
        self.assertNotIn(MARK_TRACK, blob)
        self.assertNotIn(MARK_NEWFIELD, blob)

    def test_campaign_from_other_customer_refused(self):
        self.naver.route(r"/ncc/campaigns", lambda c: (200, [campaign(ACC, 1), campaign(ACC, 2, customer=ACC + 9)]))
        e = self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle())
        self.assertEqual(e.kind, R.KIND_MISMATCH)

    def test_campaign_without_customer_refused(self):
        row = campaign(ACC, 1)
        del row["customerId"]
        self.naver.route(r"/ncc/campaigns", lambda c: (200, [row]))
        self.assertEqual(self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle()).kind, R.KIND_MISMATCH)

    def test_campaigns_not_a_list(self):
        self.naver.route(r"/ncc/campaigns", lambda c: (200, {"data": []}))
        self.assertEqual(self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle()).kind, R.KIND_BAD_RESPONSE)

    def test_empty_campaigns_is_empty(self):
        self.naver.route(r"/ncc/campaigns", lambda c: (200, []))
        self.assertEqual(self.reader.get_campaigns(check_handle()), [])

    def test_preview_can_read_campaigns(self):
        self.naver.route(r"/ncc/campaigns", lambda c: (200, [campaign(ACC, 1)]))
        self.assertEqual(len(self.reader.get_campaigns(preview_handle())), 1)

    def test_bizmoney(self):
        self.naver.route(r"/billing/bizmoney",
                         lambda c: (200, {"customerId": ACC, "bizmoney": 123456, "budgetLock": False,
                                          "refundLock": False, "newPersonalField": MARK_NEWFIELD}))
        out = self.reader.get_bizmoney(check_handle())
        self.assertEqual(out, {"customerId": ACC, "bizmoney": 123456, "budgetLock": False, "refundLock": False})

    def test_bizmoney_decimal(self):
        # 실측(2026-09-28): 잔액이 원 아래 소수까지 온다 — 첫 조각은 정수만 받아 첫날 전부 실패할 뻔했다
        self.naver.script("/billing/bizmoney", (200, {"customerId": ACC, "bizmoney": 123456.78, "budgetLock": False,
                                                      "refundLock": False}),
                          (200, {"customerId": ACC, "bizmoney": 0, "budgetLock": True, "refundLock": False}))
        self.assertEqual(self.reader.get_bizmoney(check_handle())["bizmoney"], 123456.78)
        self.assertEqual(self.reader.get_bizmoney(check_handle())["bizmoney"], 0)
        self.naver.script("/billing/bizmoney", (200, b'{"customerId": 3000001, "bizmoney": NaN}'),
                          (200, b'{"customerId": 3000001, "bizmoney": Infinity}'))
        for _ in range(2):
            self.assertEqual(self.expect(R.NaverApiError, self.reader.get_bizmoney, check_handle()).kind,
                             R.KIND_BAD_RESPONSE)

    def test_bizmoney_amount_required(self):
        for bad in ({"customerId": ACC, "budgetLock": False, "refundLock": False},
                    {"customerId": ACC, "bizmoney": None, "budgetLock": False, "refundLock": False}):
            self.naver.script("/billing/bizmoney", (200, bad))
            self.assertEqual(self.expect(R.NaverApiError, self.reader.get_bizmoney, check_handle()).kind,
                             R.KIND_BAD_RESPONSE)

    def test_bizmoney_lock_flags_required(self):
        for bad in ({"customerId": ACC, "bizmoney": 5, "refundLock": False},
                    {"customerId": ACC, "bizmoney": 5, "budgetLock": None, "refundLock": False},
                    {"customerId": ACC, "bizmoney": 5, "budgetLock": False, "refundLock": "false"}):
            self.naver.script("/billing/bizmoney", (200, bad))
            self.assertEqual(self.expect(R.NaverApiError, self.reader.get_bizmoney, check_handle()).kind,
                             R.KIND_BAD_RESPONSE)

    def test_bizmoney_mismatch_and_unknown(self):
        self.naver.script("/billing/bizmoney", (200, {"customerId": ACC + 1, "bizmoney": 5}),
                          (200, {"customerId": ACC, "bizmoney": "5"}), (200, {"customerId": ACC}),
                          (200, {"customerId": ACC, "bizmoney": True}))
        self.assertEqual(self.expect(R.NaverApiError, self.reader.get_bizmoney, check_handle()).kind, R.KIND_MISMATCH)
        for _ in range(3):
            self.assertEqual(self.expect(R.NaverApiError, self.reader.get_bizmoney, check_handle()).kind,
                             R.KIND_BAD_RESPONSE)

    def test_channels_preview_only_and_kept_fields(self):
        self.naver.route(r"/ncc/channels", lambda c: (200, [{"nccBusinessChannelId": "bsn-1", "customerId": ACC,
                                                              "name": "예시몰", "channelTp": "SITE",
                                                              "channelKey": "https://example.com",
                                                              "businessInfo": MARK_BIZINFO}]))
        out = self.reader.get_channels(preview_handle())
        self.assertNotIn(MARK_BIZINFO, json.dumps(out, ensure_ascii=False))
        self.assertEqual(out[0]["channelKey"], "https://example.com")

    def test_channel_customer_mismatch(self):
        for row in ({"nccBusinessChannelId": "bsn-1", "customerId": ACC + 9, "name": "남의 몰"},
                    {"nccBusinessChannelId": "bsn-1", "name": "번호 없음"}):
            self.naver.script("/ncc/channels", (200, [row]))
            self.assertEqual(self.expect(R.NaverApiError, self.reader.get_channels, preview_handle(by=7201)).kind,
                             R.KIND_MISMATCH)

    def test_not_json(self):
        self.naver.route(r"/ncc/campaigns", lambda c: (200, b"<html>oops</html>"))
        self.assertEqual(self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle()).kind,
                         R.KIND_BAD_RESPONSE)


# ── 5. 통계 — 모르는 모양은 0 이 아니다 ─────────────────────────────
def stat_rows(ids, **vals):
    return [{"id": i, "impCnt": vals.get("imp", 10), "clkCnt": 1, "salesAmt": vals.get("sales", 700), "ccnt": 0}
            for i in ids]


FRESH = cycle_str(NOW.replace(hour=2, minute=0))


class StatsParseTest(unittest.TestCase):
    F = ("impCnt", "clkCnt", "salesAmt", "ccnt")

    def test_top_and_wrapped_shapes(self):
        for body, shape in (({"data": stat_rows(["a", "b"]), "cycleBaseTm": FRESH}, "top"),
                            ({"summaryStatResponse": {"data": stat_rows(["a", "b"]), "cycleBaseTm": FRESH}}, "summary")):
            r = R.parse_stats(body, ["a", "b"], self.F, YDAY)
            self.assertEqual(r.shape, shape)
            self.assertEqual(r.rows["a"]["salesAmt"], 700)
            self.assertTrue(r.complete)
            self.assertEqual(r.reasons, ())

    def test_unknown_shapes_never_zero(self):
        for body in (None, [], [{"id": "a"}], {}, {"foo": 1}, {"data": None}, {"data": {"a": 1}},
                     {"summaryStatResponse": []}, {"dailyStatResponse": {"data": []}},
                     {"summaryStatResponse": {"data": []}, "dailyStatResponse": {"data": []}},
                     {"summaryStatResponse": {"rows": []}}):
            with self.assertRaises(R.StatsShapeUnknown, msg=repr(body)):
                R.parse_stats(body, ["a"], self.F, YDAY)

    def test_missing_rows_are_unknown_not_zero(self):
        r = R.parse_stats({"data": stat_rows(["a"]), "cycleBaseTm": FRESH}, ["a", "b", "c"], self.F, YDAY)
        self.assertEqual(r.missing_ids, ("b", "c"))
        self.assertNotIn("b", r.rows)
        self.assertFalse(r.complete)
        self.assertIn("missing-rows", r.reasons)
        empty = R.parse_stats({"data": [], "cycleBaseTm": FRESH}, ["a"], self.F, YDAY)
        self.assertEqual(empty.missing_ids, ("a",))
        self.assertFalse(empty.complete, "줄이 0개인 응답을 「광고비 0」으로 읽으면 안 된다")

    def test_missing_field_is_none(self):
        r = R.parse_stats({"data": [{"id": "a", "impCnt": 3}], "cycleBaseTm": FRESH}, ["a"], self.F, YDAY)
        self.assertEqual(r.rows["a"], {"impCnt": 3, "clkCnt": None, "salesAmt": None, "ccnt": None})

    def test_null_metric_makes_incomplete(self):
        r = R.parse_stats({"data": [{"id": "a"}], "cycleBaseTm": FRESH}, ["a"], self.F, YDAY)
        self.assertFalse(r.complete)
        self.assertIn("metric-unknown", r.reasons)
        self.assertEqual(len(r.unknown_values), 4)
        d = R.parse_daily({"data": [{"dateStart": YDAY.isoformat()}], "cycleBaseTm": FRESH}, "c", self.F, YDAY, YDAY)
        self.assertFalse(d.complete)

    def test_bad_values(self):
        for v in ("700", True, [1], {"v": 1}, float("nan"), float("inf")):
            with self.assertRaises(R.StatsShapeUnknown, msg=repr(v)):
                R.parse_stats({"data": [{"id": "a", "salesAmt": v}], "cycleBaseTm": FRESH}, ["a"], self.F, YDAY)

    def test_unexpected_and_duplicate_ids(self):
        with self.assertRaises(R.StatsShapeUnknown):
            R.parse_stats({"data": stat_rows(["z"]), "cycleBaseTm": FRESH}, ["a"], self.F, YDAY)
        with self.assertRaises(R.StatsShapeUnknown):
            R.parse_stats({"data": stat_rows(["a", "a"]), "cycleBaseTm": FRESH}, ["a"], self.F, YDAY)
        with self.assertRaises(R.StatsShapeUnknown):
            R.parse_stats({"data": [{"impCnt": 1}], "cycleBaseTm": FRESH}, ["a"], self.F, YDAY)

    def test_cycle_base_time(self):
        for raw in (None, "", "2026-09-29", "20260929", "202613290200", 202609290200):
            r = R.parse_stats({"data": stat_rows(["a"]), "cycleBaseTm": raw}, ["a"], self.F, YDAY)
            self.assertIsNone(r.cycle_base_tm)
            self.assertFalse(r.data_fresh)
            self.assertIn("cycle-unknown", r.reasons)
        behind = R.parse_stats({"data": stat_rows(["a"]), "cycleBaseTm": cycle_str(NOW.replace(day=28, hour=23))},
                               ["a"], self.F, YDAY)
        self.assertFalse(behind.data_fresh)
        self.assertIn("cycle-behind", behind.reasons)
        edge = R.parse_stats({"data": stat_rows(["a"]), "cycleBaseTm": cycle_str(NOW.replace(hour=0, minute=0))},
                             ["a"], self.F, YDAY)
        self.assertTrue(edge.data_fresh)

    def test_daily(self):
        days = [{"dateStart": (YDAY - timedelta(days=i)).isoformat(), "dateEnd": (YDAY - timedelta(days=i)).isoformat(),
                 "impCnt": 5, "clkCnt": 1, "salesAmt": 100, "ccnt": 0} for i in (0, 1, 3)]
        d = R.parse_daily({"dailyStatResponse": {"data": days, "cycleBaseTm": FRESH}}, "cmp", self.F,
                          YDAY - timedelta(days=3), YDAY)
        self.assertEqual(d.missing_days, ((YDAY - timedelta(days=2)).isoformat(),))
        self.assertFalse(d.complete)
        with self.assertRaises(R.StatsShapeUnknown):
            R.parse_daily({"data": [{"dateStart": "2020-01-01"}]}, "cmp", self.F, YDAY, YDAY)
        with self.assertRaises(R.StatsShapeUnknown):
            R.parse_daily({"data": [{"dateStart": YDAY.isoformat(), "dateEnd": "2099-01-01"}]}, "cmp", self.F, YDAY, YDAY)
        with self.assertRaises(R.StatsShapeUnknown):
            R.parse_daily({"summaryStatResponse": {"data": []}}, "cmp", self.F, YDAY, YDAY)
        dup = [{"dateStart": YDAY.isoformat(), "impCnt": 500, "clkCnt": 3, "salesAmt": 9000, "ccnt": 0},
               {"dateStart": YDAY.isoformat(), "impCnt": 0, "clkCnt": 0, "salesAmt": 0, "ccnt": 0}]
        with self.assertRaises(R.StatsShapeUnknown):
            R.parse_daily({"data": dup, "cycleBaseTm": FRESH}, "cmp", self.F, YDAY, YDAY)


class StatsReadTest(Base):
    def test_chunks_and_merge(self):
        ids = [f"cmp-c{i}" for i in range(250)]

        def reply(c):
            got = c.query["ids"]
            rows = stat_rows([i for i in got if i != "cmp-c7"])
            return 200, {"summaryStatResponse": {"data": rows, "cycleBaseTm": FRESH}}
        self.naver.route(r"/stats", reply)
        r = self.reader.get_stats_summary(check_handle(), ids, YDAY, YDAY)
        self.assertEqual(len([c for c in self.naver.calls if c.path == "/stats"]), 3)
        self.assertEqual(len(r.rows), 249)
        self.assertEqual(r.missing_ids, ("cmp-c7",))
        self.assertFalse(r.complete)
        q = self.naver.calls[0].query
        self.assertEqual(json.loads(q["timeRange"][0]), {"since": YDAY.isoformat(), "until": YDAY.isoformat()})
        self.assertEqual(json.loads(q["fields"][0]), ["impCnt", "clkCnt", "salesAmt", "ccnt"])

    def test_one_chunk_without_cycle_makes_whole_unknown(self):
        ids = [f"cmp-c{i}" for i in range(150)]
        state = {"n": 0}

        def reply(c):
            state["n"] += 1
            cyc = FRESH if state["n"] == 1 else None
            return 200, {"data": stat_rows(c.query["ids"]), "cycleBaseTm": cyc}
        self.naver.route(r"/stats", reply)
        r = self.reader.get_stats_summary(check_handle(), ids, YDAY, YDAY)
        self.assertIsNone(r.cycle_base_tm)
        self.assertFalse(r.complete)

    def test_one_chunk_behind_makes_whole_late(self):
        ids = [f"cmp-c{i}" for i in range(150)]
        state = {"n": 0}

        def reply(c):
            state["n"] += 1
            cyc = FRESH if state["n"] == 1 else cycle_str(NOW.replace(day=28, hour=20))
            return 200, {"data": stat_rows(c.query["ids"]), "cycleBaseTm": cyc}
        self.naver.route(r"/stats", reply)
        r = self.reader.get_stats_summary(check_handle(), ids, YDAY, YDAY)
        self.assertEqual(r.cycle_base_tm, NOW.replace(day=28, hour=20), "늦은 쪽(더 이른 시각)을 쓴다")
        self.assertIn("cycle-behind", r.reasons)
        self.assertFalse(r.complete)

    def test_cycle_ahead_boundary(self):
        for ahead, ok in ((timedelta(minutes=9), True), (timedelta(minutes=11), False), (timedelta(days=1), False)):
            self.naver.routes.clear()
            cyc = cycle_str(NOW + ahead)
            self.naver.route(r"/stats", lambda c, cyc=cyc: (200, {"data": stat_rows(c.query["ids"]), "cycleBaseTm": cyc}))
            r = self.reader.get_stats_summary(check_handle(), ["cmp-a"], YDAY, YDAY)
            self.assertEqual(r.cycle_base_tm is not None, ok, ahead)
            self.assertEqual(r.complete, ok, ahead)

    def test_unknown_shape_propagates(self):
        self.naver.route(r"/stats", lambda c: (200, {"weird": []}))
        with self.assertRaises(R.StatsShapeUnknown):
            self.reader.get_stats_summary(check_handle(), ["cmp-a"], YDAY, YDAY)

    def test_future_cycle_is_unknown(self):
        self.naver.route(r"/stats", lambda c: (200, {"data": stat_rows(c.query["ids"]), "cycleBaseTm": "209912312359"}))
        r = self.reader.get_stats_summary(check_handle(), ["cmp-a"], YDAY, YDAY)
        self.assertIsNone(r.cycle_base_tm)
        self.assertFalse(r.complete)
        self.naver.routes.clear()
        self.naver.route(r"/stats", lambda c: (200, {"data": [{"dateStart": YDAY.isoformat(), "impCnt": 0, "clkCnt": 0,
                                                              "salesAmt": 0, "ccnt": 0}], "cycleBaseTm": "209912312359"}))
        self.assertFalse(self.reader.get_stats_daily(check_handle(), "cmp-c", YDAY, YDAY).complete)

    def test_campaign_ids_only(self):
        """광고그룹·키워드 번호는 캠페인 종류가 섞이면 네이버가 400 으로 거절 — 당분간 캠페인 번호만."""
        for bad in (["grp-a001-01-000000000000001"], ["nkw-a001-01-000000000000001"], ["a"], [3], ["cmp-"],
                    ["cmp-a", "cmp-a"], []):
            self.expect(ValueError, self.reader.get_stats_summary, check_handle(), bad, YDAY, YDAY)
        self.expect(ValueError, self.reader.get_stats_daily, check_handle(), "grp-a001-01-1", YDAY, YDAY)
        self.assertEqual(self.naver.calls, [])

    def test_request_field_names(self):
        self.expect(ValueError, self.reader.get_stats_summary, check_handle(), ["cmp-a"], YDAY, YDAY, ("drtCrto",))
        self.naver.route(r"/stats", lambda c: (200, {"data": [{"id": "cmp-a", "crto": 1.5}], "cycleBaseTm": FRESH}))
        r = self.reader.get_stats_summary(check_handle(), ["cmp-a"], YDAY, YDAY, ("crto",))
        self.assertEqual(r.rows["cmp-a"]["crto"], 1.5)

    def test_purchase_fields_daily_only(self):
        self.expect(ValueError, self.reader.get_stats_summary, check_handle(), ["cmp-a"], YDAY, YDAY, ("purchaseCcnt",))
        self.assertEqual(self.naver.calls, [])

    def test_period_and_fields_validated(self):
        h = check_handle()
        today = NOW.date()
        self.expect(ValueError, self.reader.get_stats_summary, h, ["cmp-a"], today, today + timedelta(days=1))
        self.expect(ValueError, self.reader.get_stats_summary, h, ["cmp-a"], YDAY, YDAY - timedelta(days=1))
        self.expect(ValueError, self.reader.get_stats_summary, h, ["cmp-a"], YDAY - timedelta(days=100), YDAY)
        self.expect(ValueError, self.reader.get_stats_summary, h, ["cmp-a"], YDAY, YDAY, ("notAField",))
        self.expect(ValueError, self.reader.get_stats_summary, h, ["cmp-a", "cmp-a"], YDAY, YDAY)
        self.expect(ValueError, self.reader.get_stats_summary, h, [], YDAY, YDAY)
        self.assertEqual(self.naver.calls, [])

    def test_daily_call(self):
        self.naver.route(r"/stats", lambda c: (200, {"dailyStatResponse": {"data": [
            {"dateStart": YDAY.isoformat(), "impCnt": 1, "clkCnt": 0, "salesAmt": 0, "ccnt": 0}], "cycleBaseTm": FRESH}}))
        d = self.reader.get_stats_daily(check_handle(), "cmp-1", YDAY, YDAY)
        self.assertTrue(d.complete)
        self.assertEqual(self.naver.calls[0].query["id"], ["cmp-1"])
        self.assertEqual(self.naver.calls[0].query["timeIncrement"], ["1"])


class ZeroActivityTest(Base):
    """합계에 줄이 없던 캠페인 — 하루별로 모든 날·모든 지표가 정확히 0 일 때만 「활동 0」."""

    def days(self, vals, cycle=FRESH, drop=None):
        rows = []
        for i, v in enumerate(vals):
            d = (YDAY - timedelta(days=len(vals) - 1 - i)).isoformat()
            if d == drop:
                continue
            rows.append({"dateStart": d, "dateEnd": d, "impCnt": v, "clkCnt": 0, "salesAmt": 0, "ccnt": 0})
        return 200, {"summary": {}, "data": rows, "compTm": FRESH, "cycleBaseTm": cycle}

    def run_one(self, reply):
        self.naver.scripts.clear()
        self.naver.script("/stats", reply)
        return self.reader.confirm_no_activity(check_handle(), ["cmp-1"], YDAY - timedelta(days=6), YDAY)["cmp-1"]

    def test_all_zero_is_confirmed(self):
        self.assertTrue(self.run_one(self.days([0] * 7)))

    def test_anything_else_is_not(self):
        self.assertFalse(self.run_one(self.days([0, 0, 0, 1, 0, 0, 0])))
        self.assertFalse(self.run_one(self.days([0] * 7, drop=(YDAY - timedelta(days=2)).isoformat())))
        self.assertFalse(self.run_one(self.days([0, 0, 0, None, 0, 0, 0])))
        self.assertFalse(self.run_one(self.days([0] * 7, cycle=None)))
        self.assertFalse(self.run_one(self.days([0] * 7, cycle=cycle_str(NOW.replace(day=28, hour=20)))))
        self.assertFalse(self.run_one((200, {"data": [], "cycleBaseTm": FRESH})))

    def test_duplicate_day_raises_not_zero(self):
        """같은 날짜 줄이 두 번(앞은 광고비 있음 · 뒤는 0) — 뒤 것만 남겨 「활동 0」으로 읽으면 안 된다."""
        d = YDAY.isoformat()
        self.naver.script("/stats", (200, {"data": [
            {"dateStart": d, "impCnt": 500, "clkCnt": 3, "salesAmt": 9000, "ccnt": 0},
            {"dateStart": d, "impCnt": 0, "clkCnt": 0, "salesAmt": 0, "ccnt": 0}], "cycleBaseTm": FRESH}))
        with self.assertRaises(R.StatsShapeUnknown):
            self.reader.confirm_no_activity(check_handle(), ["cmp-1"], YDAY, YDAY)

    def test_unknown_shape_raises(self):
        self.naver.script("/stats", (200, {"odd": 1}))
        with self.assertRaises(R.StatsShapeUnknown):
            self.reader.confirm_no_activity(check_handle(), ["cmp-1"], YDAY, YDAY)

    def test_check_purpose_only(self):
        self.expect(H.HandleInvalid, self.reader.confirm_no_activity, preview_handle(), ["cmp-1"], YDAY, YDAY)
        self.expect(H.HandleInvalid, self.reader.confirm_no_activity, ACC, [], YDAY, YDAY)


# ── 6. 오류 분류 · 다시 보내기 · 속도 · 상한 ────────────────────────
class RetryTest(Base):
    def setUp(self):
        super().setUp()
        self.naver.route(r"/ncc/campaigns", lambda c: (200, [campaign(ACC, 1)]))

    def test_rate_then_ok_resigned(self):
        self.naver.script("/ncc/campaigns", (429, {"code": 1016}), (400, {"code": 1016}))
        self.assertEqual(len(self.reader.get_campaigns(check_handle())), 1)
        self.assertEqual(len(self.naver.calls), 3)
        self.assertEqual(len({c.ts for c in self.naver.calls}), 3, "다시 보낼 때마다 서명을 새로 해야 한다")
        waits = [s for s in self.clock.sleeps if s >= 1.5]
        self.assertEqual(len(waits), 2)
        self.assertTrue(2 <= waits[0] <= 2.5 and 4 <= waits[1] <= 5)

    def test_rate_gives_up(self):
        for _ in range(4):
            self.naver.script("/ncc/campaigns", (429, {"code": 1016}))
        e = self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle())
        self.assertEqual(e.kind, R.KIND_RATE)
        self.assertEqual(len(self.naver.calls), 4)
        waits = [w for w in self.clock.sleeps if w >= 1.5]
        self.assertEqual(len(waits), 3)
        for got, base in zip(waits, (2.0, 4.0, 8.0)):
            self.assertTrue(base <= got <= base * 1.25, (got, base))

    def test_default_call_cap(self):
        self.assertEqual(R.DEFAULT_MAX_CALLS, 20000)
        self.assertEqual(R.NaverReader(creds(), transport=FakeNaver())._max_calls, 20000)

    def test_burst_pauses_then_aborts(self):
        class NoJitter:
            def uniform(self, a, b):
                return 0.0
        r = R.NaverReader(creds(), transport=self.naver, clock=self.clock, rng=NoJitter())
        # 요청 다섯 개가 연달아 첫 시도에 429 → 2.33초 간격으로 5번 = 10초 안 5번 → 5분 멈춤
        for _ in range(5):
            self.naver.script("/ncc/campaigns", (429, {"code": 1016}), (200, [campaign(ACC, 1)]))
        for _ in range(5):
            self.assertEqual(len(r.get_campaigns(check_handle())), 1)
        self.assertEqual(self.clock.sleeps.count(R.RATE_PAUSE), 1)
        self.assertEqual(r.pauses, 1)
        # 또 몰리면 회차를 멈춘다(두 번째 멈춤 = 중단)
        for _ in range(5):
            self.naver.script("/ncc/campaigns", (429, {"code": 1016}), (200, [campaign(ACC, 1)]))
        self.expect(R.RunAbort, lambda: [r.get_campaigns(check_handle()) for _ in range(5)])
        self.assertEqual(self.clock.sleeps.count(R.RATE_PAUSE), 1, "두 번째는 멈추지 않고 중단")

    def test_spread_out_rate_does_not_pause(self):
        for _ in range(8):
            self.naver.script("/ncc/campaigns", (429, {"code": 1016}), (200, [campaign(ACC, 1)]))
        for _ in range(8):
            self.reader.get_campaigns(check_handle())
            self.clock.advance(30)
        self.assertEqual(self.reader.pauses, 0)
        self.assertNotIn(R.RATE_PAUSE, self.clock.sleeps)

    def test_server_retry(self):
        self.naver.script("/ncc/campaigns", (500, {}), (503, b""))
        self.assertEqual(len(self.reader.get_campaigns(check_handle())), 1)
        self.assertEqual(self.clock.sleeps.count(1.0) + self.clock.sleeps.count(2.0) >= 2, True)
        for _ in range(4):
            self.naver.script("/ncc/campaigns", (502, b"bad gateway"))
        self.assertEqual(self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle()).kind, R.KIND_SERVER)

    def test_network_errors(self):
        self.naver.script("/ncc/campaigns", socket.timeout("t"), ConnectionResetError("r"))
        self.assertEqual(len(self.reader.get_campaigns(check_handle())), 1)
        for _ in range(4):
            self.naver.script("/ncc/campaigns", urllib.error.URLError(f"host {MARK_API_KEY}"))
        e = self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle())
        self.assertEqual((e.kind, e.detail), (R.KIND_NETWORK, "URLError"))
        self.assertIsNone(e.__cause__)
        self.assertIsNone(e.__context__, "원래 오류(키가 섞일 수 있다)가 사슬에 붙으면 안 된다")

    def test_no_retry_kinds(self):
        for status, code, kind in ((401, None, R.KIND_KEY_REJECTED), (403, 1018, R.KIND_KEY_REJECTED),
                                   (400, 1006, R.KIND_KEY_REJECTED), (400, 11003, R.KIND_BAD_REQUEST),
                                   (404, None, R.KIND_NOT_FOUND), (418, None, R.KIND_OTHER), (302, None, R.KIND_OTHER)):
            before = len(self.naver.calls)
            self.naver.script("/ncc/campaigns", (status, {"code": code} if code else b""))
            e = self.expect(R.NaverApiError, self.reader.get_campaigns, check_handle())
            self.assertEqual(e.kind, kind, (status, code))
            self.assertEqual(len(self.naver.calls) - before, 1, "다시 보내면 안 되는 오류")

    def test_pacing(self):
        for _ in range(4):
            self.reader.get_campaigns(check_handle())
        small = [s for s in self.clock.sleeps if 0 < s < 1]
        self.assertEqual(len(small), 3)
        self.assertTrue(all(abs(s - 1 / 3) < 1e-9 for s in small))

    def test_call_cap(self):
        r = R.NaverReader(creds(), transport=self.naver, clock=self.clock, max_calls=2)
        r.get_campaigns(check_handle())
        r.get_campaigns(check_handle())
        self.expect(R.RunAbort, r.get_campaigns, check_handle())
        self.assertEqual(len(self.naver.calls), 2)


# ── 7. 비밀값 ────────────────────────────────────────────────────────
class SecretTest(unittest.TestCase):
    def test_masked_everywhere(self):
        c = creds()
        for text in (repr(c), str(c), repr(c.api_key), str(c.secret_key), f"{c.api_key}", f"{c.api_key:>40}",
                     "%s %r" % (c.api_key, c.secret_key), repr(R.NaverReader(c, transport=FakeNaver()))):
            self.assertNotIn(MARK_API_KEY, text)
            self.assertNotIn(MARK_SECRET, text)
            self.assertNotIn(str(AGENCY_ID), text)
        with self.assertRaises(TypeError):
            pickle.dumps(c.api_key)
        with self.assertRaises(AttributeError):
            c.api_key._value = "x"
        self.assertNotEqual(Secret("a"), Secret("a"), "값 비교로 비밀값을 알아낼 수 없게")

    def test_load(self):
        env = {"NAVER_MGR_CUSTOMER_ID": " 7654321 ", "NAVER_MGR_API_KEY": MARK_API_KEY,
               "NAVER_MGR_SECRET_KEY": MARK_SECRET}
        c = load_manager_credentials(env)
        self.assertEqual(c.customer_id, AGENCY_ID)
        self.assertEqual(c.api_key.reveal(), MARK_API_KEY)
        for broken in ({**env, "NAVER_MGR_API_KEY": ""}, {k: v for k, v in env.items() if k != "NAVER_MGR_SECRET_KEY"},
                       {**env, "NAVER_MGR_CUSTOMER_ID": "abc"}, {**env, "NAVER_MGR_CUSTOMER_ID": "0"}):
            with self.assertRaises(CredentialsMissing) as cm:
                load_manager_credentials(broken)
            self.assertNotIn(MARK_API_KEY, str(cm.exception))
            self.assertNotIn(MARK_SECRET, str(cm.exception))

    def test_key_charset(self):
        env = {"NAVER_MGR_CUSTOMER_ID": "7654321", "NAVER_MGR_API_KEY": MARK_API_KEY, "NAVER_MGR_SECRET_KEY": MARK_SECRET}
        for name in ("NAVER_MGR_API_KEY", "NAVER_MGR_SECRET_KEY"):
            for bad in (MARK_API_KEY + "\r\nX-Evil: 1", "키값한글포함abcdef", "abc def ghij", "short"):
                with self.assertRaises(CredentialsMissing) as cm:
                    load_manager_credentials({**env, name: bad})
                self.assertNotIn(MARK_API_KEY, str(cm.exception))

    def test_handle_reprs_hide_ids(self):
        for h in (check_handle(), preview_handle(by=7301), H.issue_manager_handle(AGENCY_ID, NOW)):
            text = repr(h) + str(h) + f"{h}"
            self.assertNotIn(str(ACC), text)
            self.assertNotIn(str(AGENCY_ID), text)

    def test_reprs_hide_ids(self):
        naver = FakeNaver()
        Agency(naver, sizes=(3,))
        r = R.NaverReader(creds(), transport=naver, clock=FakeClock(NOW))
        kids = r.list_all_children(r.manager_handle())
        self.assertNotIn("3000000", repr(kids) + str(kids))
        res = R.parse_stats({"data": stat_rows(["cmp-secret-1"]), "cycleBaseTm": FRESH}, ["cmp-secret-1"],
                            ("impCnt",), YDAY)
        self.assertNotIn("cmp-secret-1", repr(res))

    def test_tail(self):
        self.assertEqual(customer_tail(3000001), "…0001")
        self.assertEqual(customer_tail(12), "…12")

    def test_error_text_has_no_full_customer(self):
        e = R.NaverApiError(R.KIND_RATE, "/stats", 429, 1016, ACC)
        self.assertNotIn(str(ACC), str(e))
        self.assertIn("…0001", str(e))


if __name__ == "__main__":
    unittest.main()
