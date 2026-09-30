"""① 전산 알림 관문(erp_alert.py) 시험 — 가짜 ① 로만(네트워크 0). 번호·문구는 모두 지어낸 값이다.

가짜 ① (``FakeAlertErp``)은 ① 계약 §12·§13 을 그대로 흉내 낸다 — 규칙 검사(400) · 같은 날 같은 사람 같은 열쇠 한 번 ·
사람별 하루 20 · 전체 200 · 심박 기록. 알림 규칙 시험(test_alerts.py)도 이 가짜를 쓴다.

돌리는 법(저장소 맨 위에서):  python3 -m unittest discover -s naver_engine/tests
"""
from __future__ import annotations

import json
import logging
import re
import traceback
import unicodedata
import unittest
import urllib.error
import urllib.parse
from unittest import mock
from datetime import date, datetime, timedelta, timezone

from naver_engine import erp_alert as A
from naver_engine import erp_read as E
from naver_engine.credentials import CredentialsMissing, Secret
from naver_engine.naver_read import UrllibTransport

KST = timezone(timedelta(hours=9))
MARK_KEY = "MARKERPKEY-1a2b3c4d-5e6f7a8b9c0d1e2f"
MARK_TITLE = "MARKTITLE"
MARK_LINE = "MARKLINE"


class FakeAlertErp:
    """① 비서방 알림 넣기 · 심박 흉내. ``today`` 는 ① 서버 날짜(한국)."""

    def __init__(self, today: date = date(2026, 9, 29), active=None, cap_target=20, cap_total=200):
        self.today = today
        self.active = set(range(0, 1000)) if active is None else set(active)
        self.cap_target, self.cap_total = cap_target, cap_total
        self.calls = []
        self.messages = []          # (날짜, 받는 사람, 열쇠, 중요도, 본문)
        self.heartbeats = {}        # 날짜 → 상태
        self.override = {}          # 경로 → (상태, 본문) — 이 경로는 흉내 대신 이 값을 돌려준다
        self.raise_next = None
        self.next_idx = 1000

    def send(self, req, timeout):
        u = urllib.parse.urlsplit(req.full_url)
        body = None if req.data is None else json.loads(req.data.decode("utf-8"))
        self.calls.append({"method": req.get_method(), "scheme": u.scheme, "host": u.hostname, "path": u.path,
                           "key_ok": req.get_header("X-api-key") == MARK_KEY, "body": body,
                           "ctype": req.get_header("Content-type"), "timeout": timeout})
        if self.raise_next is not None:
            e, self.raise_next = self.raise_next, None
            raise e
        if u.path in self.override:
            return self.override[u.path]
        if req.get_header("X-api-key") != MARK_KEY:
            return 401, json.dumps({"status": 401, "message": "인증 실패"}).encode()
        if u.path == A.PATH_ALERTS:
            return self._alert(body)
        if u.path == A.PATH_HEARTBEAT:
            return self._heartbeat(body)
        return 404, b"{}"

    @staticmethod
    def _bad():
        return 400, json.dumps({"status": 400, "message": "거절"}).encode()

    @staticmethod
    def _clean(v, limit):
        if not isinstance(v, str) or not v.strip():
            return None
        v = v.strip()
        if len(v) > limit or any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp", "Cs") for c in v):
            return None
        return v

    def _alert(self, b):
        if not isinstance(b, dict) or b.get("severity") not in ("NORMAL", "URGENT"):
            return self._bad()
        title = self._clean(b.get("title"), 60)
        lines = b.get("lines") or []
        if title is None or len(lines) > 8 or any(self._clean(x, 120) is None for x in lines):
            return self._bad()
        link = b.get("link_path") or "/naver/"
        if len(link) > 200 or not re.fullmatch(r"/naver/[A-Za-z0-9/_.~?=&%#-]*", link) or "//" in link \
                or ".." in link or "sso" in link.lower():
            return self._bad()
        key = b.get("dedupe_key")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{8,64}", key):
            return self._bad()
        t = b.get("target_emp_idx")
        if isinstance(t, bool) or not isinstance(t, int) or t < 0 or t not in self.active:
            return self._bad()
        today = [m for m in self.messages if m[0] == self.today]
        recent = [m for m in self.messages if m[0] >= self.today - timedelta(days=1)]   # ① 같은 열쇠 창 = 오늘·어제
        if any(m[1] == t and m[2] == key for m in recent):
            return self._ok({"delivered": False, "reason": "duplicate", "message_idx": None})
        if sum(1 for m in today if m[1] == t) >= self.cap_target:
            return self._ok({"delivered": False, "reason": "daily_cap_target", "message_idx": None})
        if len(today) >= self.cap_total:
            return self._ok({"delivered": False, "reason": "daily_cap_total", "message_idx": None})
        self.next_idx += 1
        content = "\n".join(["[네이버 관제] " + title] + [x.strip() for x in lines]
                            + ["관제 화면: https://dashboard.metainc.co.kr" + link])
        self.messages.append((self.today, t, key, b["severity"], content))
        return self._ok({"delivered": True, "reason": "sent", "message_idx": self.next_idx})

    def _heartbeat(self, b):
        if not isinstance(b, dict) or b.get("status") not in ("ok", "trouble") or b.get("day") != self.today.isoformat():
            return self._bad()
        self.heartbeats[self.today] = b["status"]
        return self._ok({"recorded": True})

    @staticmethod
    def _ok(result):
        return 200, json.dumps({"status": 200, "result": result}).encode()

    def sent_to(self, target):
        return [m for m in self.messages if m[1] == target]


def poster(fake=None, **kw):
    return A.ErpAlertPoster(Secret(MARK_KEY), transport=fake if fake is not None else FakeAlertErp(), **kw)


def payload(**kw):
    base = dict(target_emp_idx=0, severity="NORMAL", title="아침 점검 — 🔴 2곳", lines=["확인할 광고주 2곳"],
                link_path="/naver/", dedupe_key="morning:2026-09-29:0")
    base.update(kw)
    return A.build_payload(**base)


class ContractValuesTest(unittest.TestCase):
    def test_values_match_erp_contract(self):
        """① 계약 §12(① ``AdSyncNaverAlertService``) 의 값 — 한쪽만 바꾸면 이 시험이 멈춘다."""
        self.assertEqual((A.TITLE_MAX, A.LINE_MAX, A.LINES_MAX, A.LINK_MAX), (60, 120, 8, 200))
        self.assertEqual(A.SEVERITIES, {"NORMAL", "URGENT"})
        self.assertEqual(A.REASONS, {"sent", "duplicate", "daily_cap_target", "daily_cap_total"})
        self.assertEqual(A._DEDUPE_KEY.pattern, r"[A-Za-z0-9._:-]{8,64}")
        self.assertEqual(A._LINK.pattern, r"/naver/[A-Za-z0-9/_.~?=&%#-]*")
        self.assertEqual((A.PATH_ALERTS, A.PATH_HEARTBEAT), ("/api/ad-sync/naver-alerts", "/api/ad-sync/naver-heartbeat"))
        self.assertIs(A.ERP_HOST, E.ERP_HOST)

    def test_path_set_is_exactly_three(self):
        self.assertEqual(A._PATHS, {A.PATH_ALERTS, A.PATH_HEARTBEAT, A.PATH_METRICS})
        self.assertEqual(A._ALLOWED_METHODS, {"POST"})


class PayloadRulesTest(unittest.TestCase):
    def test_good(self):
        p = payload(title="  아침 점검  ", lines=["  한 줄  "])
        self.assertEqual((p.title, p.lines), ("아침 점검", ("한 줄",)))
        self.assertEqual(p.body()["lines"], ["한 줄"])

    def test_title_limits(self):
        payload(title="가" * 59 + "🔴")            # 이모지는 한 글자(60자)
        with self.assertRaises(A.AlertRejected):
            payload(title="가" * 61)
        for bad in ("", "   ", None, 7, "줄\n바꿈", "탭\t있음", "폭없음\u200b", "방향\u202e바꿈", "잇기\u200d",
                    "구\u2028분", "문\u2029단", "널\x00", "반쪽\ud800"):
            with self.assertRaises(A.AlertRejected, msg=repr(bad)):
                payload(title=bad)

    def test_lines_limits(self):
        payload(lines=[])
        payload(lines=["가"] * 8)
        payload(lines=["가" * 120])
        for bad in (["가"] * 9, ["가" * 121], ["", "가"], ["  "], ["a\nb"], "한 줄", None, [3]):
            with self.assertRaises(A.AlertRejected, msg=repr(bad)[:40]):
                payload(lines=bad)

    def test_link_rules(self):
        for ok in ("/naver/", "/naver/issues", "/naver/issues?day=2026-09-29&x=1#top", "/naver/a_b.c~d%20"):
            payload(link_path=ok)
        for bad in ("/", "/naver", "naver/", "/other/", "/naver//x", "/naver/../x", "/naver/sso", "/naver/SsO",
                    "/naver/?sso=1", "/naver/한글", "/naver/a b", "/naver/" + "a" * 194, None, "",
                    "http://evil/naver/", "/naver/\n"):
            with self.assertRaises(A.AlertRejected, msg=repr(bad)[:40]):
                payload(link_path=bad)
        payload(link_path="/naver/" + "a" * 193)   # 200자 딱

    def test_dedupe_key_rules(self):
        for ok in ("abcdefgh", "a" * 64, "sys:2026-09-29:ACCOUNTS_UNUSABLE", "d.1_2-3:4"):
            payload(dedupe_key=ok)
        for bad in ("abcdefg", "a" * 65, "키:2026-09-29", "a b c d e", "abc/defgh", None, 12345678):
            with self.assertRaises(A.AlertRejected, msg=repr(bad)[:40]):
                payload(dedupe_key=bad)

    def test_target_and_severity(self):
        payload(target_emp_idx=0)
        payload(target_emp_idx=999, severity="URGENT")
        for bad in (-1, True, "0", 1.0, None, 10 ** 15):
            with self.assertRaises(A.AlertRejected):
                payload(target_emp_idx=bad)
        for bad in ("urgent", "Normal", "INFO", None, ""):
            with self.assertRaises(A.AlertRejected):
                payload(severity=bad)

    def test_repr_and_errors_carry_no_text(self):
        p = payload(title=MARK_TITLE, lines=[MARK_LINE])
        self.assertNotIn(MARK_TITLE, repr(p))
        self.assertNotIn(MARK_LINE, repr(p))
        self.assertNotIn("morning", repr(p))
        try:
            payload(title=MARK_TITLE + "\n")
        except A.AlertRejected as e:
            self.assertNotIn(MARK_TITLE, str(e))


class SendAlertTest(unittest.TestCase):
    def test_sends_one_post_with_key_and_body(self):
        fake = FakeAlertErp()
        res = poster(fake).send_alert(payload(target_emp_idx=7, severity="URGENT", title=MARK_TITLE,
                                              lines=[MARK_LINE], link_path="/naver/issues"))
        self.assertEqual(res, A.AlertResult(True, "sent", 1001))
        c = fake.calls[0]
        self.assertEqual((c["method"], c["scheme"], c["host"], c["path"]),
                         ("POST", "http", "api.metainc.co.kr", "/api/ad-sync/naver-alerts"))
        self.assertTrue(c["key_ok"])
        self.assertEqual(c["ctype"], "application/json; charset=utf-8")
        self.assertEqual(c["body"], {"target_emp_idx": 7, "severity": "URGENT", "title": MARK_TITLE,
                                     "lines": [MARK_LINE], "link_path": "/naver/issues",
                                     "dedupe_key": "morning:2026-09-29:0"})
        self.assertEqual(c["timeout"], A.TIMEOUT)
        self.assertTrue(fake.messages[0][4].startswith("[네이버 관제] " + MARK_TITLE))

    def test_not_delivered_reasons_are_results(self):
        fake = FakeAlertErp(cap_target=2, cap_total=3)
        p = poster(fake)
        self.assertEqual(p.send_alert(payload(dedupe_key="k-aaaaaa1")).reason, "sent")
        self.assertEqual(p.send_alert(payload(dedupe_key="k-aaaaaa1")), A.AlertResult(False, "duplicate", None))
        self.assertEqual(p.send_alert(payload(dedupe_key="k-aaaaaa2")).reason, "sent")
        self.assertEqual(p.send_alert(payload(dedupe_key="k-aaaaaa3")).reason, "daily_cap_target")
        self.assertEqual(p.send_alert(payload(target_emp_idx=1, dedupe_key="k-aaaaaa4")).reason, "sent")
        self.assertEqual(p.send_alert(payload(target_emp_idx=2, dedupe_key="k-aaaaaa5")).reason, "daily_cap_total")

    def test_bad_responses_are_failures(self):
        cases = [
            ((400, b'{"status":400}'), "status-400"),
            ((401, b"{}"), "status-401"),
            ((500, b"<html>"), "status-500"),
            ((200, b"<html>"), "not-json"),
            ((200, b"\xff\xfe"), "not-json"),
            ((200, b"[]"), "bad-shape"),
            ((200, json.dumps({"status": 201, "result": {}}).encode()), "bad-shape"),
            ((200, json.dumps({"status": 200, "result": {"delivered": True, "reason": "sent"}}).encode()), "bad-shape"),
            ((200, json.dumps({"status": 200, "result": {"delivered": True, "reason": "sent", "message_idx": 0}}).encode()),
             "bad-shape"),
            ((200, json.dumps({"status": 200, "result": {"delivered": True, "reason": "sent",
                                                         "message_idx": True}}).encode()), "bad-shape"),
            ((200, json.dumps({"status": 200, "result": {"delivered": True, "reason": "duplicate",
                                                         "message_idx": 5}}).encode()), "bad-shape"),
            ((200, json.dumps({"status": 200, "result": {"delivered": False, "reason": "sent"}}).encode()), "bad-shape"),
            ((200, json.dumps({"status": 200, "result": {"delivered": False, "reason": "queued"}}).encode()), "bad-shape"),
            ((200, json.dumps({"status": 200, "result": {"delivered": False, "reason": "duplicate",
                                                         "message_idx": 9}}).encode()), "bad-shape"),
            ((200, json.dumps({"status": 200, "result": {"delivered": 1, "reason": "sent",
                                                         "message_idx": 9}}).encode()), "bad-shape"),
            ((200, b"[" * 100000 + b"]" * 100000), "too-large"),
        ]
        for resp, code in cases:
            fake = FakeAlertErp()
            fake.override[A.PATH_ALERTS] = resp
            with self.assertRaises(A.AlertSendError, msg=code) as cm:
                poster(fake).send_alert(payload())
            self.assertEqual(cm.exception.code, code)

    def test_network_errors_carry_no_key(self):
        for exc in (urllib.error.URLError("refused " + MARK_KEY), OSError("reset " + MARK_KEY),
                    TimeoutError("slow " + MARK_KEY), RuntimeError("boom " + MARK_KEY)):
            fake = FakeAlertErp()
            fake.raise_next = exc
            with self.assertRaises(A.AlertSendError) as cm:
                poster(fake).send_alert(payload(title=MARK_TITLE))
            text = str(cm.exception) + "".join(traceback.format_exception(cm.exception))
            self.assertNotIn(MARK_KEY, text)
            self.assertNotIn(MARK_TITLE, text)
            self.assertIn(cm.exception.code, ("network", "other"))

    def test_wrong_key_is_status_401(self):
        fake = FakeAlertErp()
        p = A.ErpAlertPoster(Secret("OTHER-KEY-0123456789abcdef0123456789"), transport=fake)
        with self.assertRaises(A.AlertSendError) as cm:
            p.send_alert(payload())
        self.assertEqual(cm.exception.code, "status-401")

    def test_hand_made_payload_rechecked(self):
        fake = FakeAlertErp()
        bad = A.AlertPayload(0, "NORMAL", "줄\n바꿈", (), "/naver/", "abcdefgh")
        with self.assertRaises(A.AlertRejected):
            poster(fake).send_alert(bad)
        with self.assertRaises(A.AlertRejected):
            poster(fake).send_alert({"target_emp_idx": 0})
        self.assertEqual(fake.calls, [])

    def test_call_cap(self):
        fake = FakeAlertErp()
        p = poster(fake, max_calls=2)
        p.send_alert(payload(dedupe_key="k-cap00001"))
        p.send_alert(payload(dedupe_key="k-cap00002"))
        with self.assertRaises(A.AlertSendError) as cm:
            p.send_alert(payload(dedupe_key="k-cap00003"))
        self.assertEqual(cm.exception.code, "call-cap")
        self.assertEqual(len(fake.calls), 2)

    def test_key_must_be_secret_and_default_transport(self):
        with self.assertRaises(CredentialsMissing):
            A.ErpAlertPoster(MARK_KEY)
        p = A.ErpAlertPoster(Secret(MARK_KEY))
        self.assertIsInstance(p._transport, UrllibTransport)
        self.assertNotIn(MARK_KEY, repr(p))

    def test_gate_refuses_other_methods_and_paths(self):
        fake = FakeAlertErp()
        p = poster(fake)
        for m in ("GET", "PUT", "DELETE", "post"):
            with self.assertRaises(A.AlertWriteForbidden):
                p._gate(m, A.PATH_ALERTS, {})
        for path in (E.PATH_CONTRACTS, "/api/ad-sync/naver-alerts/", "/api/ad-sync/naver-alerts?x=1", "//evil/x",
                     "/api/employee-management/my-profile"):
            with self.assertRaises(A.AlertWriteForbidden):
                p._gate("POST", path, {})
        with self.assertRaises(A.AlertWriteForbidden):
            p._gate("POST", A.PATH_ALERTS, [])
        self.assertEqual(fake.calls, [])
        self.assertEqual(p.calls, 0)          # 요청을 만들기 전에 막혔다(호출 수에도 들어가지 않음)

    def test_gate_refuses_other_host_even_if_base_changes(self):
        # 주소 글자가 어떻게 바뀌어도(다른 호스트 · https · 뒤에 붙인 호스트) 요청이 나가지 않는다 — 두 번째 확인 단독 시험
        for base in ("http://evil.example", "https://api.metainc.co.kr", "http://api.metainc.co.kr.evil.example"):
            fake = FakeAlertErp()
            with mock.patch.object(A, "BASE_URL", base):
                with self.assertRaises(A.AlertWriteForbidden):
                    poster(fake).send_alert(payload())
            self.assertEqual(fake.calls, [], base)

    def test_hand_made_payload_is_rebuilt_before_send(self):
        # build_payload 를 거치지 않은 객체(몸체를 바꿔치는 하위 클래스)도 ① 에는 다시 만든 몸체만 간다
        class Sneaky(A.AlertPayload):
            def body(self):
                b = super().body()
                b["title"] = "바꿔치기"
                b["note"] = "광고주 이름"
                return b

        good = payload()
        sneaky = Sneaky(good.target_emp_idx, good.severity, good.title, good.lines, good.link_path, good.dedupe_key)
        fake = FakeAlertErp()
        self.assertTrue(poster(fake).send_alert(sneaky).delivered)
        [call] = fake.calls
        self.assertEqual(call["body"], good.body())

    def test_oversized_request_refused_before_send(self):
        fake = FakeAlertErp()
        with self.assertRaises(A.AlertRejected):
            poster(fake)._gate("POST", A.PATH_ALERTS, {"x": "가" * 20000})
        self.assertEqual(fake.calls, [])

    def test_logs_carry_nothing(self):
        lines = []

        class H(logging.Handler):
            def emit(self, r):
                lines.append(self.format(r))
        h = H()
        root = logging.getLogger()
        root.addHandler(h)
        old = root.level
        root.setLevel(logging.DEBUG)
        try:
            fake = FakeAlertErp()
            poster(fake).send_alert(payload(title=MARK_TITLE, lines=[MARK_LINE]))
            fake.override[A.PATH_ALERTS] = (500, b"x")
            with self.assertRaises(A.AlertSendError):
                poster(fake).send_alert(payload(title=MARK_TITLE, lines=[MARK_LINE]))
        finally:
            root.removeHandler(h)
            root.setLevel(old)
        joined = "\n".join(lines)
        for m in (MARK_KEY, MARK_TITLE, MARK_LINE):
            self.assertNotIn(m, joined)


class HeartbeatTest(unittest.TestCase):
    def test_sends_day_and_status_only(self):
        fake = FakeAlertErp(today=date(2026, 9, 29))
        poster(fake).send_heartbeat(date(2026, 9, 29), "ok")
        c = fake.calls[0]
        self.assertEqual((c["method"], c["host"], c["path"]), ("POST", "api.metainc.co.kr", A.PATH_HEARTBEAT))
        self.assertEqual(c["body"], {"day": "2026-09-29", "status": "ok"})
        self.assertEqual(fake.heartbeats, {date(2026, 9, 29): "ok"})

    def test_rules(self):
        fake = FakeAlertErp()
        p = poster(fake)
        for bad_day in (datetime(2026, 9, 29, tzinfo=KST), "2026-09-29", None):
            with self.assertRaises(A.AlertRejected):
                p.send_heartbeat(bad_day, "ok")
        for bad in ("OK", "fine", None):
            with self.assertRaises(A.AlertRejected):
                p.send_heartbeat(date(2026, 9, 29), bad)
        self.assertEqual(fake.calls, [])

    def test_needs_recorded_true(self):
        for resp, code in (((200, json.dumps({"status": 200, "result": {}}).encode()), "bad-shape"),
                           ((200, json.dumps({"status": 200, "result": {"recorded": 1}}).encode()), "bad-shape"),
                           ((400, b"{}"), "status-400"), ((404, b"{}"), "status-404")):
            fake = FakeAlertErp()
            fake.override[A.PATH_HEARTBEAT] = resp
            with self.assertRaises(A.AlertSendError) as cm:
                poster(fake).send_heartbeat(date(2026, 9, 29), "trouble")
            self.assertEqual(cm.exception.code, code)

    def test_wrong_day_is_400(self):
        fake = FakeAlertErp(today=date(2026, 9, 30))
        with self.assertRaises(A.AlertSendError) as cm:
            poster(fake).send_heartbeat(date(2026, 9, 29), "ok")
        self.assertEqual(cm.exception.code, "status-400")


if __name__ == "__main__":
    unittest.main()
