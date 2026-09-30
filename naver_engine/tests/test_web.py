"""S11 시험 — 관제 화면 API(``web``) · 화면 자료(``views``) · 자체 토큰(``session``) · ① 내 정보 관문(``erp_profile``) ·
저장소 판 6(열람·쓰기 기록 · 🔔 읽음 · 기준값) (설계 v1.8 S11 · v1.4 §5 · §6 · §9 · §12).

가짜 네이버 · 가짜 ① 로만 돈다 — 네트워크 0. 범위 규칙은 ``backend/app/naver_auto/scope.py`` 를 그대로 쓴다.
예시 번호·이름은 모두 지어낸 것이다. 조직: 대표 0 · 관리 1팀 팀장 1 · 직원 100(가망 11 · 14) · 직원 101(가망 12) ·
가망 13 = 담당 없음(대표만).
"""
from __future__ import annotations

import ast
import io
import json
import os
import pathlib
import random
import re
import sqlite3
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone

ENGINE = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ENGINE.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import issues as I  # noqa: E402
from app.naver_auto import matching as M  # noqa: E402
from app.naver_auto import scope as SC  # noqa: E402
from app.naver_auto import verdict as V  # noqa: E402

from naver_engine import erp_profile as EP  # noqa: E402
from naver_engine import erp_read as E  # noqa: E402
from naver_engine import links as L  # noqa: E402
from naver_engine import session as SE  # noqa: E402
from naver_engine import store as S  # noqa: E402
from naver_engine import views as W  # noqa: E402
from naver_engine import web as WEB  # noqa: E402
from naver_engine.credentials import CredentialsMissing, Secret  # noqa: E402
from naver_engine.tests import test_alerts as TA  # noqa: E402
from naver_engine.tests import test_morning as TM  # noqa: E402

KST = timezone(timedelta(hours=9))
T0 = TM.T0                                  # 2026-09-29(화) 06:40
TODAY = T0.date()
A, B, C_, D = TM.A, TM.B, TM.C_, TM.D
TOKEN_SECRET = "t" * 40
MARK_SSO = "SSOMARKaaaaaaaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbb.cccccc"   # ① 토큰 표지 — 어디에도 남으면 안 된다
MARK_LOGIN_ID = "loginmark77"                                                  # ① 로그인 아이디 표지
MARK_PHONE = "010-7777-7777"
BAD_SSO = MARK_SSO.replace("SSOMARK", "BADMARK")                                # 모양은 맞지만 ① 이 거절하는 토큰


def tok(i: int) -> str:
    """서로 다른 ① 토큰(표지 SSOMARK 는 그대로 — 어디에 남는지 보는 시험이 함께 잡는다)."""
    return MARK_SSO[:-6] + f"c{i:05d}"


def bad(i: int) -> str:
    return BAD_SSO[:-6] + f"c{i:05d}"


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime.combine(d, time(h, m), tzinfo=KST)


# ── 가짜 ① 내 정보 ────────────────────────────────────────────────────
class FakeProfileErp:
    """① my-profile 흉내 — 토큰 → 응답. 받은 요청을 적는다(토큰은 표지로만 대조)."""

    def __init__(self):
        self.people = {}      # 토큰 → (상태, 본문)
        self.calls = []

    def person(self, token, idx, manager=False, teams=((11, 10), (10, 0)), status=200):
        result = {"idx": idx, "id": MARK_LOGIN_ID, "name": "이름", "isManager": manager, "phone": MARK_PHONE,
                  "teamList": [{"idx": t, "name": "팀", "teamLevel": 1, "parentIdx": par} for t, par in teams],
                  "authority": {"authorityIdx": 1, "name": "권한"}, "residentNumberMasked": "900101-1******"}
        self.people[token] = (status, json.dumps({"status": 200, "result": result}).encode("utf-8"))

    def send(self, req, timeout):
        auth = req.get_header("Authorization") or ""
        self.calls.append((req.get_method(), req.full_url, auth.startswith("Bearer ")))
        tok = auth[len("Bearer "):]
        if tok not in self.people:
            return 401, b'{"status":401}'
        return self.people[tok]


class WebBase(TM.Base):
    """가망 11 · 12(자동 짝) · 13(이름 후보) · 14(막힘) · 오늘 짝 맞추기 · 아침 점검 · 🔴 하나 · 🟡 둘."""

    def setUp(self):
        super().setUp()
        self._names = dict(TM.NAMES)
        self.addCleanup(self._restore_names)
        self.world()
        self.erp = FakeProfileErp()
        self.signer = SE.TokenSigner(Secret(TOKEN_SECRET))
        self.app = self.make_app()

    def _restore_names(self):
        TM.NAMES.clear()
        TM.NAMES.update(self._names)

    def make_app(self, **kw):
        return WEB.App(open_read=lambda: S.open_reader(self.path), write=lambda fn: fn(self.st), signer=self.signer,
                       profiles=EP.ErpProfileReader(transport=self.erp), clock=self.fc.now, **kw)

    def world(self, org_owners=None, extra_people=()):
        t = self.at(T0)
        self.st.record_org(TA.org_body(t - timedelta(minutes=30), owners=org_owners, extra_people=extra_people),
                           t - timedelta(minutes=20))
        rows = [TM.srow(p) for p in (11, 12, 13, 14)]
        self.st.record_prospects(E.StageSnapshot({r.possibility_id: r for r in rows}, t - timedelta(minutes=5), {}, ()))
        TM.NAMES[A] = "에이상점"                    # 계정 이름에 번호를 싣지 않는다 — 응답에 번호 원문이 없는지 볼 수 있게
        TM.NAMES[B] = TM.shop(12)
        TM.NAMES[C_] = TM.shop(13)
        TM.NAMES[D] = "다른이름"
        self.st.record_accounts(TM.kids(A, B, C_, D), t - timedelta(minutes=4))
        self.st.record_decision(11, A, "confirmed", 0, t - timedelta(minutes=3))
        erp = TM.FakeErp([E.NaverIdRow(12, M.VENDOR_NAVER, str(B)), E.NaverIdRow(14, M.VENDOR_NAVER, "9999999")])
        res = L.pair_links(erp, self.st, t - timedelta(minutes=2))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED, res)
        self.standard_ads()
        out = self.run_check()
        self.assertEqual(out.outcome, "done", out)
        # 🔴 하나(가망 11 · 계정 A) — 규칙 모듈을 그대로 지나는 저장소 길로
        rid = self.st.begin_run(TODAY, self.at(T0 + timedelta(minutes=10)))
        self.st.record_account_check(rid, A, possibility_id=11, link="confirmed", status="ok",
                                     rules_run=("bizmoney", "link"), rules_not_run=(), checked_at=self.fc.now(),
                                     findings=(TA.F("bizmoney", "bizmoney_low", f"acc:{A}", "red"),))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        self.at(at(TODAY, 9, 0))

    # ── 부르기 ──
    def token(self, idx, narrowed=False, now=None):
        return self.signer.issue(idx, now or self.fc.now(), narrowed=narrowed)

    def call(self, method, path, token=None, body=None, query="", raw=None, headers=None):
        env = {"REQUEST_METHOD": method, "PATH_INFO": WEB.PREFIX + path, "QUERY_STRING": query,
               "wsgi.input": io.BytesIO(b"")}
        if token is not None:
            env["HTTP_AUTHORIZATION"] = "Bearer " + token
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode("utf-8"))
        if data is not None:
            env.update({"CONTENT_LENGTH": str(len(data)), "CONTENT_TYPE": "application/json",
                        "wsgi.input": io.BytesIO(data)})
        env.update(headers or {})
        got = {}

        def start(status, hdrs):
            got["status"], got["headers"] = int(status.split()[0]), dict(hdrs)
        chunks = self.app(env, start)
        payload = b"".join(chunks)
        return got["status"], json.loads(payload.decode("utf-8")), got["headers"], payload

    def get(self, path, idx, query="", **kw):
        s, b, _h, _p = self.call("GET", path, self.token(idx, **kw), query=query)
        return s, b

    def post(self, path, idx, body=None, **kw):
        s, b, _h, _p = self.call("POST", path, self.token(idx, **kw), body=body)
        return s, b

    def repair(self, ids, stages=None, names=None, extra=None):
        """① 네이버 고객 번호 줄을 바꿔 지금 시각에 짝을 다시 맞춘다(``ids`` = [(가망, 번호)] · ``stages`` = 가망 → StageRow)."""
        t = self.at(self.fc.now() + timedelta(minutes=5))   # 단계·계정 목록은 앞 것보다 늦어야 받는다
        rows = {p: TM.srow(p) for p in (11, 12, 13, 14)}
        rows.update(stages or {})
        TM.NAMES.update(names or {})
        self.st.record_prospects(E.StageSnapshot(rows, t - timedelta(minutes=3), {}, ()))
        kids = TM.kids(A, B, C_, D)
        if extra:   # 시험이 더하는 계정 {고객 번호: 남길 칸}
            acc = {**kids.accounts, **extra}
            kids = TM.N.ChildAccounts(acc, {1: len(acc)}, ())
        self.st.record_accounts(kids, t - timedelta(minutes=2))
        res = L.pair_links(TM.FakeErp([E.NaverIdRow(p, M.VENDOR_NAVER, str(c)) for p, c in ids]), self.st,
                           t - timedelta(minutes=1))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED, res)

    def issue_of(self, pid, severity):
        return [i for i in self.st.issues(pid, open_only=True) if i["severity"] == severity][0]

    def resign(self, idx):
        """조직 표에서 그 사람을 퇴사로(새 수락본)."""
        body = TA.org_body(self.fc.now() - timedelta(minutes=5))
        for e in body["employees"]:
            if e["idx"] == idx:
                e["status"] = "RESIGNED"
        self.st.record_org(body, self.fc.now(), warnings=())


# ── 자체 토큰 ────────────────────────────────────────────────────────
class TokenTest(unittest.TestCase):
    def setUp(self):
        self.s = SE.TokenSigner(Secret(TOKEN_SECRET))
        self.now = at(TODAY, 9, 0)

    def test_roundtrip_and_ceo_zero(self):
        c = self.s.verify(self.s.issue(0, self.now), self.now)
        self.assertEqual((c.emp_idx, c.narrowed), (0, False))   # 대표 = 0 — 사람이다
        self.assertEqual(c.expires_at - c.issued_at, timedelta(hours=1))
        c2 = self.s.verify(self.s.issue(4242, self.now), self.now)
        self.assertNotIn("4242", repr(c2))                  # 번호가 표시에 없다
        self.assertNotIn("emp_idx", repr(c2))
        self.assertEqual(repr(self.s), "TokenSigner(****)")

    def test_expiry_one_hour(self):
        tok = self.s.issue(100, self.now)
        self.s.verify(tok, self.now + timedelta(minutes=59))
        with self.assertRaises(SE.TokenInvalid) as e:
            self.s.verify(tok, self.now + timedelta(hours=1))
        self.assertEqual(e.exception.code, SE.BAD_EXPIRED)

    def test_tamper_refused(self):
        tok = self.s.issue(100, self.now)
        v, body, sig = tok.split(".")
        payload = json.loads(SE._unb64(body))
        for change in ({"sub": 0}, {"nar": 1}, {"exp": payload["exp"] + 3600}, {"aud": "other"}):
            forged = dict(payload, **change)
            b2 = SE._b64(json.dumps(forged, sort_keys=True, separators=(",", ":")).encode("ascii"))
            with self.assertRaises(SE.TokenInvalid) as e:
                self.s.verify(f"{v}.{b2}.{sig}", self.now)
            self.assertEqual(e.exception.code, SE.BAD_SIGNATURE)
        for bad in ("", "v1..", "v2." + body + "." + sig, tok + ".x", tok.replace(".", ".%", 1), "가" * 5, None, 5,
                    "v1." + body + "." + sig + "=" * 2000):
            with self.assertRaises(SE.TokenInvalid):
                self.s.verify(bad, self.now)
        other = SE.TokenSigner(Secret("u" * 40))
        with self.assertRaises(SE.TokenInvalid) as e:
            other.verify(tok, self.now)
        self.assertEqual(e.exception.code, SE.BAD_SIGNATURE)

    def test_signed_but_bad_claims_refused(self):
        """비밀값을 가진 쪽이 만든 글이라도 약속 밖(1시간 넘음 · 12시간 넘음 · 모르는 칸 · 대상 다름)이면 받지 않는다."""
        def mint(p):
            b = SE._b64(json.dumps(p, sort_keys=True, separators=(",", ":")).encode("ascii"))
            return "v1." + b + "." + self.s._sign(b)
        base = {"aud": "naver-auto", "sub": 1, "iat": int(self.now.timestamp()), "exp": int(self.now.timestamp()) + 60,
                "lat": int(self.now.timestamp()), "nar": 0}
        self.s.verify(mint(base), self.now)
        for change, code in (({"exp": base["iat"] + 7200}, SE.BAD_MALFORMED),
                             ({"lat": base["iat"] - 13 * 3600, "exp": base["iat"] + 60}, SE.BAD_MALFORMED),
                             ({"aud": "naver"}, SE.BAD_AUDIENCE), ({"sub": -1}, SE.BAD_MALFORMED),
                             ({"sub": True}, SE.BAD_MALFORMED), ({"nar": True}, SE.BAD_MALFORMED),
                             ({"extra": 1}, SE.BAD_MALFORMED), ({"iat": base["iat"] + 3600, "exp": base["iat"] + 3700,
                                                               "lat": base["iat"] + 3600}, SE.BAD_NOT_YET)):
            with self.assertRaises(SE.TokenInvalid, msg=change) as e:
                self.s.verify(mint(dict(base, **change)), self.now)
            self.assertEqual(e.exception.code, code, change)

    def test_refresh_keeps_login_time_and_narrowing_until_twelve_hours(self):
        tok = self.s.issue(1, self.now, narrowed=True)
        c = self.s.verify(tok, self.now)
        t = self.now
        for _ in range(11):
            t += timedelta(minutes=59)
            c = self.s.verify(self.s.refresh(c, t), t)
            self.assertTrue(c.narrowed)
            self.assertEqual(c.login_at, self.now.replace(microsecond=0))
        last = self.s.refresh(c, self.now + timedelta(hours=11, minutes=30))
        self.assertLessEqual(self.s.verify(last, self.now + timedelta(hours=11, minutes=30)).expires_at,
                             self.now + timedelta(hours=12))
        with self.assertRaises(SE.TokenInvalid) as e:
            self.s.refresh(c, self.now + timedelta(hours=12))
        self.assertEqual(e.exception.code, SE.BAD_SESSION_OVER)

    def test_secret_required(self):
        for env in ({}, {"NAVER_AUTO_TOKEN_SECRET": ""}, {"NAVER_AUTO_TOKEN_SECRET": "x" * 31},
                    {"NAVER_AUTO_TOKEN_SECRET": "가" * 40}, {"NAVER_AUTO_TOKEN_SECRET": "a b" * 20}):
            with self.assertRaises(CredentialsMissing) as e:
                SE.load_token_secret(env)
            self.assertNotIn("x" * 31, str(e.exception))
        self.assertIsInstance(SE.load_token_secret({"NAVER_AUTO_TOKEN_SECRET": "k" * 32}), Secret)
        with self.assertRaises(CredentialsMissing):
            WEB.build_app(open_read=lambda: None, write=lambda fn: None, env={})
        with self.assertRaises(TypeError):
            WEB.App(open_read=lambda: None, write=lambda fn: None, signer=None, profiles=None)


# ── ① 내 정보 관문 ───────────────────────────────────────────────────
class ProfileGateTest(unittest.TestCase):
    def setUp(self):
        self.erp = FakeProfileErp()
        self.r = EP.ErpProfileReader(transport=self.erp)

    def test_keeps_only_three_fields(self):
        self.erp.person(MARK_SSO, 0, manager=True, teams=((0, None),))
        p = self.r.read_profile(EP.load_sso(MARK_SSO))
        self.assertEqual((p.idx, p.says_manager, p.team_idx, p.team_known), (0, True, 0, True))   # 대표 = 0 도 사람
        self.assertEqual(set(vars(p)) if hasattr(p, "__dict__") else set(p.__dataclass_fields__),
                         {"idx", "says_manager", "team_idx", "team_known"})
        self.assertEqual(repr(p), "Profile(****)")
        self.assertEqual(self.erp.calls, [("GET", "http://api.metainc.co.kr/api/employee-management/my-profile", True)])

    def test_leaf_team_is_own_team(self):
        self.erp.person(MARK_SSO, 5, teams=((10, 0), (11, 10), (12, 11)))   # 순서가 섞여도 끝 팀
        self.assertEqual(self.r.read_profile(EP.load_sso(MARK_SSO)).team_idx, 12)
        for teams, known in ((((11, 10), (12, 10)), False), ((), True), ((("x", 1),), False)):
            self.erp.person(MARK_SSO, 5, teams=teams)
            p = self.r.read_profile(EP.load_sso(MARK_SSO))
            self.assertEqual(p.team_known, known, teams)

    def test_rejected_and_unavailable(self):
        with self.assertRaises(EP.ProfileError) as e:
            self.r.read_profile(EP.load_sso(MARK_SSO))
        self.assertEqual(e.exception.kind, EP.KIND_REJECTED)
        self.erp.person(MARK_SSO, 5, status=500)
        with self.assertRaises(EP.ProfileError) as e:
            self.r.read_profile(EP.load_sso(MARK_SSO))
        self.assertEqual(e.exception.kind, EP.KIND_UNAVAILABLE)
        self.assertNotIn(MARK_SSO[:10], str(e.exception))
        for bad in (None, "", "short", "has space " * 3, "a" * 5000, "줄\n" * 10, 5):
            with self.assertRaises(EP.ProfileError):
                EP.load_sso(bad)

    def test_bad_idx_refused(self):
        for idx in (-1, None, "7", True, 1.5):
            self.erp.people[MARK_SSO] = (200, json.dumps({"status": 200, "result": {"idx": idx}}).encode())
            with self.assertRaises(EP.ProfileError, msg=idx) as e:
                self.r.read_profile(EP.load_sso(MARK_SSO))
            self.assertEqual(e.exception.kind, EP.KIND_BAD_SHAPE)

    def test_gate_refuses_other_methods_paths(self):
        for m, path in (("POST", EP.PATH_MY_PROFILE), ("GET", E.PATH_CONTRACTS), ("GET", EP.PATH_MY_PROFILE + "/x")):
            with self.assertRaises(EP.ProfileForbidden):
                self.r._gate(m, path, Secret(MARK_SSO))
        with self.assertRaises(EP.ProfileForbidden):
            self.r._gate("GET", EP.PATH_MY_PROFILE, MARK_SSO)   # 날 글자 토큰은 받지 않는다
        self.assertEqual(self.erp.calls, [])


# ── 저장소 판 6 ──────────────────────────────────────────────────────
class StoreV6Test(WebBase):
    def test_v5_file_gets_new_tables(self):
        self.st.close()
        self.st = None
        raw = sqlite3.connect(self.path)
        for t in ("naver_auto_access_log", "naver_auto_threshold_change"):
            raw.execute(f"DROP TABLE {t}")
        raw.execute("UPDATE naver_auto_meta SET value = '5' WHERE key = 'schema_version'")
        raw.commit()
        raw.close()
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.assertEqual(self.st.meta("schema_version"), "7")
        self.assertEqual(self.st.access_log(), [])
        self.assertEqual(self.st.thresholds(), W.T.DEFAULTS)

    def test_access_log_codes_only(self):
        self.st.record_access(0, "view", "client", 11, "ok", self.fc.now())
        self.st.record_access(None, "login", "session", None, "sso-rejected", self.fc.now())
        for bad in (dict(action="보기"), dict(action="view 11"), dict(result="ok:가게"), dict(target_kind="x"),
                    dict(viewer_idx=-1), dict(target_id=-5), dict(action="a" * 41)):
            args = dict(viewer_idx=0, action="view", target_kind="client", target_id=11, result="ok", at=self.fc.now())
            args.update(bad)
            with self.assertRaises(S.StoreRefused, msg=bad):
                self.st.record_access(**args)
        rows = self.st.access_log()
        self.assertEqual([(r["emp_idx"], r["action"], r["result"]) for r in rows],
                         [(None, "login", "sso-rejected"), (0, "view", "ok")])
        cols = {c[1] for c in sqlite3.connect(self.path).execute("PRAGMA table_info(naver_auto_access_log)")}
        self.assertEqual(cols, {"log_id", "at", "emp_idx", "action", "target_kind", "target_id", "result"})

    def test_mark_read_own_rows_only(self):
        aid = self.st.record_alert(S.ALERT_DIGEST, TODAY, "compose", "digest", (), "/naver/issues",
                                   [{"emp_idx": 100, "severity": "NORMAL", "params": {"red": 0, "yellow": 1}},
                                    {"emp_idx": 101, "severity": "NORMAL", "params": {"red": 0, "yellow": 2}}],
                                   self.fc.now())
        rs = {r["emp_idx"]: r["recipient_id"] for r in self.st.alert_recipients(aid)}
        with self.assertRaises(S.ScreenRefused) as e:
            self.st.mark_alert_read(rs[101], 100, self.fc.now())   # 남의 줄
        self.assertEqual(e.exception.code, "not-found")
        with self.assertRaises(S.ScreenRefused):
            self.st.mark_alert_read(9999, 100, self.fc.now())      # 없는 줄 — 같은 거절
        self.assertTrue(self.st.mark_alert_read(rs[100], 100, self.fc.now()))
        self.assertFalse(self.st.mark_alert_read(rs[100], 100, self.fc.now()))
        self.assertIsNone({r["emp_idx"]: r for r in self.st.alert_recipients(aid)}[101]["read_at"])
        self.assertEqual([r["recipient_id"] for r in self.st.my_alerts(100, TODAY)], [rs[100]])

    def test_thresholds_validated_and_history(self):
        new = self.st.record_thresholds({"zero_spend_days": 5}, 0, self.fc.now())
        self.assertEqual(new.zero_spend_days, 5)
        self.assertEqual(self.st.thresholds(), new)
        for bad, code in (({"zero_spend_days": 99}, "out-of-range"), ({"nope": 1}, "out-of-range"),
                          ({"zero_spend_days": 5}, "no-change"), ({}, "no-change"),
                          ({"bizmoney_red_days": 3.0}, "out-of-range")):   # 🔴 날수 < 🟡 날수
            with self.assertRaises(S.ScreenRefused, msg=bad) as e:
                self.st.record_thresholds(bad, 0, self.fc.now())
            self.assertEqual(e.exception.code, code, bad)
        [h] = self.st.threshold_changes()
        self.assertEqual((h["before"]["zero_spend_days"], h["after"]["zero_spend_days"], h["changed_by"]), (3, 5, 0))

    def test_reader_cannot_write_v6(self):
        r = S.open_reader(self.path)
        try:
            for call in (lambda: r.record_access(0, "view", "client", 1, "ok", self.fc.now()),
                         lambda: r.mark_alert_read(1, 0, self.fc.now()),
                         lambda: r.record_thresholds({"zero_spend_days": 4}, 0, self.fc.now())):
                with self.assertRaises(S.StoreRefused):
                    call()
        finally:
            r.close()


# ── 범위 · 좁히기 ────────────────────────────────────────────────────
class ScopeAdditionsTest(WebBase):
    def org(self):
        return W.load_org(self.st)

    def test_narrowing_team_to_mine_only(self):
        org = self.org()
        self.assertEqual(SC.scope_of(org, 1).kind, SC.TEAM)
        n = SC.narrowed_scope_of(org, 1)
        self.assertEqual((n.kind, n.people, n.narrowed), (SC.MINE, frozenset({1}), True))
        self.assertEqual(SC.narrowed_scope_of(org, 0).kind, SC.ALL)       # 대표는 좁히지 않는다
        self.assertEqual(SC.narrowed_scope_of(org, 777).kind, SC.NONE)
        owns = W.load(self.st, self.fc.now()).owns
        self.assertEqual(SC.clients_in(org, n, owns), frozenset())        # 팀장 본인 담당 없음 → 0곳
        forged = SC.Scope(SC.TEAM, 1, n.teams, n.people, n.generated_at, True)
        self.assertEqual(SC.clients_in(org, forged, owns), frozenset())   # 손으로 만든 「좁힌 팀」은 범위 없음
        unmarked = SC.Scope(SC.MINE, 1, frozenset(), frozenset({1}), n.generated_at)
        self.assertEqual(SC.clients_in(org, unmarked, owns), frozenset())

    def test_profile_narrows(self):
        org = self.org()
        self.assertFalse(SC.profile_narrows(org, 1, True, 11))
        self.assertTrue(SC.profile_narrows(org, 1, False, 11))           # 팀장 아님
        self.assertTrue(SC.profile_narrows(org, 1, True, 10))            # 다른 팀
        self.assertTrue(SC.profile_narrows(org, 1, None, 11))            # 모름 = 좁힌다
        self.assertTrue(SC.profile_narrows(org, 1, True, "11"))
        self.assertFalse(SC.profile_narrows(org, 100, False, 11))        # 담당은 좁힐 것이 없다
        self.assertFalse(SC.profile_narrows(org, 0, False, None))        # 대표는 my-profile 로 좁히지 않는다

    def test_issue_actor_layers(self):
        org = self.org()
        owns = W.load(self.st, self.fc.now()).owns
        self.assertEqual(I.ACTOR_LEAD, "lead")
        self.assertEqual(I.ACTOR_OWNER, "owner")
        self.assertEqual(SC.issue_actor(org, SC.scope_of(org, 100), owns[11]), "owner")
        self.assertEqual(SC.issue_actor(org, SC.scope_of(org, 1), owns[11]), "lead")
        self.assertEqual(SC.issue_actor(org, SC.scope_of(org, 0), owns[11]), "lead")
        self.assertIsNone(SC.issue_actor(org, SC.scope_of(org, 101), owns[11]))   # 볼 수 없음
        prev_own = SC.Ownership(client_id=99, main=None, prev=100, source="prev", match=SC.MATCH_PID)
        self.assertIsNone(SC.issue_actor(org, SC.scope_of(org, 100), prev_own))    # 이전 담당은 보기·멈추기만
        self.assertEqual(SC.allowed_actions(org, SC.scope_of(org, 100), prev_own), SC.PREV_ACTIONS)


# ── 웹 — 모든 경로가 보는 사람을 지난다 ───────────────────────────────
SAMPLE = {"pid": "11", "iid": "1", "rid": "1", "kind": "org"}


def _path_of(route):
    p = route.pattern.pattern
    for name, val in SAMPLE.items():
        p = re.sub(r"\(\?P<%s>[^)]*\)" % name, val, p)
    return p


class RouteGuardTest(WebBase):
    def test_every_route_but_login_needs_viewer(self):
        """경로 목록을 훑어 — 토큰 없이 부를 수 있는 것은 로그인 하나 · 나머지는 모두 401(설계 v1.4 §12 ①)."""
        open_routes = [(r.method, r.pattern.pattern) for r in WEB.ROUTES if not r.auth]
        self.assertEqual(open_routes, [("POST", "/session")])
        for r in WEB.ROUTES:
            if not r.auth:
                continue
            path = _path_of(r)
            for tok in (None, "v1.x.y", self.signer.issue(100, self.fc.now() - timedelta(hours=2))):
                s, b, _h, _p = self.call(r.method, path, tok, body={} if r.method == "POST" else None)
                self.assertEqual(s, 401, (r.method, path, tok, b))

    def test_handlers_take_viewer(self):
        """경로 함수는 (요청, 보는 사람, 지금, …) 을 받는다 — 보는 사람 없이 쓰는 경로를 만들 수 없게."""
        import inspect
        for r in WEB.ROUTES:
            params = list(inspect.signature(r.handler).parameters)
            self.assertEqual(params[:4], ["self", "req", "v", "now"], r.handler.__name__)

    def test_authorization_header_must_be_bearer(self):
        tok = self.token(100)
        for head in ("Basic " + tok, tok, "Bearer", "Bearer  ", "Token " + tok):
            s, b, _h, _p = self.call("GET", "/me", headers={"HTTP_AUTHORIZATION": head})
            self.assertEqual(s, 401, head)
        s, _b, _h, _p = self.call("GET", "/me", headers={"HTTP_AUTHORIZATION": "bearer " + tok})
        self.assertEqual(s, 200)                       # 머리 글자의 대소문자는 가리지 않는다
        s, _b, _h, _p = self.call("GET", "/me", query="token=" + tok)
        self.assertEqual(s, 401)                       # 주소에 실은 토큰은 받지 않는다

    def test_unknown_and_wrong_method(self):
        tok = self.token(0)
        self.assertEqual(self.call("GET", "/nope", tok)[0], 404)
        self.assertEqual(self.call("DELETE", "/me", tok)[0], 405)
        self.assertEqual(self.call("POST", "/me", tok, body={})[0], 405)
        env_status = self.call("GET", "/me", tok, headers={"PATH_INFO": "/other/me"})[0]
        self.assertEqual(env_status, 404)

    def test_headers_no_store(self):
        s, _b, h, _p = self.call("GET", "/me", self.token(100))
        self.assertEqual(s, 200)
        for k, v in (("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
                     ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY")):
            self.assertEqual(h[k], v)


# ── 로그인 ──────────────────────────────────────────────────────────
class LoginTest(WebBase):
    def login(self, token=MARK_SSO):
        s, b, _h, _p = self.call("POST", "/session", body={"sso": token})
        return s, b

    def test_login_staff_and_ceo_zero(self):
        self.erp.person(MARK_SSO, 100, teams=((11, 10), (10, 0)))
        s, b = self.login()
        self.assertEqual((s, b["narrowed"]), (200, False))
        s, me, _h, _p = self.call("GET", "/me", b["token"])
        self.assertEqual((me["idx"], me["scope"]), (100, SC.MINE))
        self.erp.person(MARK_SSO, 0, manager=True, teams=((0, None),))
        s, b = self.login()
        _s, me, _h, _p = self.call("GET", "/me", b["token"])
        self.assertEqual((me["idx"], me["scope"]), (0, SC.ALL))   # 대표 0번 → 전체

    def test_lead_narrowed_when_profile_says_not_manager(self):
        self.erp.person(MARK_SSO, 1, manager=False, teams=((11, 10), (10, 0)))
        s, b = self.login()
        self.assertEqual((s, b["narrowed"]), (200, True))
        s, board, _h, _p = self.call("GET", "/board", b["token"], query="attention=0")
        self.assertEqual(board["counts"]["total"], 0)   # 팀 범위가 아니라 본인 담당만(0곳)
        self.erp.person(MARK_SSO, 1, manager=True, teams=((11, 10), (10, 0)))
        s, b = self.login()
        s, board, _h, _p = self.call("GET", "/board", b["token"], query="attention=0")
        self.assertEqual((b["narrowed"], board["counts"]["total"]), (False, 3))

    def test_refused_logins(self):
        s, b = self.login()
        self.assertEqual((s, b["error"]), (401, EP.KIND_REJECTED))
        self.erp.person(MARK_SSO, 777)
        s, b = self.login()
        self.assertEqual((s, b["error"]), (403, "no-scope"))   # 조직 표에 없는 사람
        self.erp.person(MARK_SSO, 5, status=500)
        self.assertEqual(self.login()[0], 503)
        self.assertEqual(self.call("POST", "/session", body={"sso": MARK_SSO, "as": 0})[0], 400)
        self.assertEqual(self.call("POST", "/session", raw=b"{", headers={})[0], 400)
        self.assertEqual(self.call("POST", "/session", raw=b'{"sso":"x"}',
                                   headers={"CONTENT_TYPE": "text/plain"})[0], 415)
        self.assertEqual(self.call("POST", "/session", raw=b"x" * (WEB.BODY_MAX + 1))[0], 413)
        results = [r["result"] for r in self.st.access_log()]
        self.assertIn(EP.KIND_REJECTED, results)
        self.assertIn("no-scope", results)

    def test_login_throttled(self):
        """전체 창 — 서로 다른 토큰이어도 창마다 login_max 번만 ① 을 부른다(① 커넥션 보호)."""
        self.app = self.make_app(login_max=3, monotonic=lambda: 100.0)
        for i in range(4):
            self.erp.person(tok(i), 100)
        self.assertEqual([self.login(tok(i))[0] for i in range(4)], [200, 200, 200, 429])

    def src(self, source, peer="127.0.0.1", sso=MARK_SSO, environ=None):
        s, b, _h, _p = self.call("POST", "/session", body={"sso": sso},
                                 headers={"REMOTE_ADDR": peer, "HTTP_X_NAVER_AUTO_SOURCE": source, **(environ or {})})
        return s

    def test_junk_does_not_use_up_logins(self):
        """① 을 부르지 않는 거절(모양 틀림)은 세지 않는다 · 창마다 한 줄만 기록(검토 login-throttle-global-lockout)."""
        self.app = self.make_app(login_max=3, login_source_max=3, monotonic=lambda: 100.0)
        for body in [{}] * 20 + [{"sso": "x"}] * 20:
            self.assertIn(self.call("POST", "/session", body=body)[0], (400, 401))
        self.assertEqual(self.erp.calls, [])
        self.erp.person(MARK_SSO, 100)
        self.assertEqual(self.login()[0], 200)
        results = [r["result"] for r in self.st.access_log()]
        self.assertEqual((results.count("bad-body"), results.count(EP.KIND_REJECTED)), (1, 1))

    def test_one_source_cannot_lock_out_everyone(self):
        """한 곳(③ 중계가 넘긴 요청한 곳)에서 ① 이 거절할 토큰을 몰아쳐도 다른 곳의 로그인은 된다 · 전체 상한은 따로.
        한 곳 상한은 ① 이 **거절한** 시도만 센다(S12 검토 office-nat · inflight · unavailable)."""
        self.app = self.make_app(login_max=8, login_source_max=2, monotonic=lambda: 100.0)
        for i in range(10):
            self.erp.person(tok(i), 100)
        self.assertEqual([self.src("10.0.0.1", sso=bad(i)) for i in range(3)], [401, 401, 429])   # 전체 2
        self.assertEqual(self.src("10.0.0.1", sso=tok(0)), 429)       # 그 곳은 창이 지날 때까지 막힘(진짜 토큰도)
        self.assertEqual(self.src("10.0.0.2", sso=tok(1)), 200)       # 다른 곳은 된다 · 전체 3
        # 중계가 아닌 곳이 넣은 머리는 믿지 않는다 — 연결한 주소 하나로 센다(머리를 믿었다면 셋 다 401)
        with self.assertLogs("naver_engine.web", "WARNING"):
            got = [self.src(f"10.9.9.{i}", peer="203.0.113.5", sso=bad(10 + i)) for i in range(3)]
        self.assertEqual(got, [401, 401, 429])                         # 전체 5
        self.assertEqual([self.src("10.0.0.3", sso=bad(20)), self.src("10.0.0.4", sso=bad(21))], [401, 401])   # 7
        self.assertEqual(self.src("10.0.0.5", sso=tok(2)), 200)       # 8
        self.assertEqual(self.src("10.0.0.6", sso=tok(3)), 429)       # 전체 상한(8)
        self.assertEqual([r["result"] for r in self.st.access_log()].count("throttled"), 1)   # 창마다 한 줄

    def test_office_many_people_one_address(self):
        """사무실처럼 여럿이 한 주소(nginx X-Real-IP 하나)로 들어와도 ① 이 받아 준 로그인은 한 곳 상한(6)과 무관 ·
        같은 주소에서 거절될 토큰은 6번까지."""
        self.app = self.make_app(monotonic=lambda: 100.0)
        for i in range(12):
            self.erp.person(tok(i), 100)
        self.assertEqual([self.src("203.0.113.9", sso=tok(i)) for i in range(12)], [200] * 12)
        self.assertEqual([self.src("203.0.113.9", sso=bad(i)) for i in range(7)], [401] * 6 + [429])
        self.assertEqual(self.src("203.0.113.10", sso=tok(0)), 200)

    def test_one_valid_token_cannot_fill_everyone(self):
        """받아 주는 토큰 하나를 한 곳에서 되풀이해도 창마다 3번 — 전체 창을 혼자 채워 다른 사람을 막지 못한다 ·
        막힌 시도는 ① 을 부르지 않는다 · 범위 없는 사람(403)도 같다(S12 2차 검토 refund-replay)."""
        self.app = self.make_app(login_max=10, monotonic=lambda: 100.0)
        self.erp.person(tok(0), 100)
        self.erp.person(tok(1), 101)
        self.erp.person(tok(2), 777)
        self.assertEqual([self.src("198.51.100.7", sso=tok(0)) for _ in range(12)], [200] * 3 + [429] * 9)
        self.assertEqual(self.src("203.0.113.44", sso=tok(1)), 200)
        self.assertEqual([self.src("198.51.100.8", sso=tok(2)) for _ in range(5)], [403] * 3 + [429] * 2)
        self.assertEqual(len(self.erp.calls), 3 + 1 + 3)

    def test_outage_not_counted_for_address(self):
        """① 장애(503)는 한 곳 창에 남지 않는다 — ① 이 돌아오면 같은 사무실 로그인이 바로 된다(S12 2차 검토 unavailable)."""
        self.app = self.make_app(monotonic=lambda: 100.0)
        for i in range(8):
            self.erp.person(tok(i), 100, status=500)
        self.assertEqual([self.src("203.0.113.9", sso=tok(i)) for i in range(8)], [503] * 8)
        self.erp.person(tok(8), 100)
        self.assertEqual(self.src("203.0.113.9", sso=tok(8)), 200)

    def test_windows_slide(self):
        """창은 실제로 미끄러진다 — 움직이는 시계로 한 곳 · 같은 토큰 · 전체 창이 창 길이가 지나면 풀리고, 그 전에는 안
        풀린다(시계를 얼린 시험만으로는 기록이 영영 안 지워지는 고장을 못 잡는다 · 2차 검토 frozen-clock)."""
        now = [100.0]
        w = WEB.LOGIN_WINDOW
        self.app = self.make_app(login_max=4, login_source_max=2, login_token_max=2, monotonic=lambda: now[0])
        # 한 곳 창(① 이 거절한 시도)
        self.assertEqual([self.src("10.9.0.1", sso=bad(i)) for i in range(3)], [401, 401, 429])
        now[0] += w - 1
        self.assertEqual(self.src("10.9.0.1", sso=bad(3)), 429)
        now[0] += 2
        self.assertEqual(self.src("10.9.0.1", sso=bad(4)), 401)
        # 같은 토큰 창
        now[0] += w + 1
        self.erp.person(tok(0), 100)
        self.assertEqual([self.src(f"10.9.1.{i}", sso=tok(0)) for i in range(3)], [200, 200, 429])
        now[0] += w - 1
        self.assertEqual(self.src("10.9.1.9", sso=tok(0)), 429)
        now[0] += 2
        self.assertEqual(self.src("10.9.1.9", sso=tok(0)), 200)
        # 전체 창
        now[0] += w + 1
        for i in range(1, 7):
            self.erp.person(tok(i), 100)
        self.assertEqual([self.src(f"10.9.2.{i}", sso=tok(i)) for i in range(1, 6)], [200] * 4 + [429])
        now[0] += w - 1
        self.assertEqual(self.src("10.9.2.9", sso=tok(6)), 429)
        now[0] += 2
        self.assertEqual(self.src("10.9.2.9", sso=tok(6)), 200)

    def test_trusted_transport_mark(self):
        """유닉스 소켓 서버(S14)가 environ 에 넣는 표지 — IP 없는 연결에서 값이 정확히 True 일 때만 머리를 믿는다 ·
        브라우저 머리로는 못 만든다 · TCP 연결에 붙은 표지는 무시 · 믿지 않는 머리는 값 없이 1분 한 줄 경고."""
        mark = {WEB.TRUSTED_TRANSPORT: True}
        self.app = self.make_app(login_source_max=1, monotonic=lambda: 100.0)
        self.assertEqual([self.src(f"10.1.1.{i}", peer="", sso=bad(i), environ=mark) for i in range(3)], [401] * 3)
        for n, fake in enumerate(({}, {WEB.TRUSTED_TRANSPORT: "1"}, {WEB.TRUSTED_TRANSPORT: 1},
                                  {"HTTP_NAVER_ENGINE.TRUSTED_TRANSPORT": True},
                                  {"HTTP_X_NAVER_ENGINE_TRUSTED_TRANSPORT": "true"})):
            self.app = self.make_app(login_source_max=1, monotonic=lambda: 100.0)
            with self.assertLogs("naver_engine.web", "WARNING") as cm:
                got = [self.src(f"10.2.2.{i}", peer="", sso=bad(10 * n + 10 + i), environ=fake) for i in range(2)]
            self.assertEqual(got, [401, 429], fake)            # 표지가 없거나 틀리면 모두 「unknown」 한 곳
            self.assertEqual(len([x for x in cm.output if "믿지 않음" in x]), 1)   # 창마다 한 줄
            self.assertNotIn("10.2.2", " ".join(cm.output))
        self.app = self.make_app(login_source_max=1, monotonic=lambda: 100.0)
        with self.assertLogs("naver_engine.web", "WARNING"):
            got = [self.src(f"10.3.3.{i}", peer="203.0.113.5", sso=bad(90 + i), environ=mark) for i in range(2)]
        self.assertEqual(got, [401, 429])                       # TCP(루프백 밖) + 표지 = 믿지 않음

    def test_expiry_and_session_end_reported(self):
        """응답의 남은 시간은 토큰의 실제 남은 시간 · 세션 끝(로그인 + 12시간)을 함께(검토 expires-in-misreported)."""
        self.erp.person(MARK_SSO, 100)
        start = self.fc.now()
        s, b = self.login()
        self.assertEqual((b["expires_in"], b["session_ends_at"]),
                         (3600, (start + SE.SESSION_MAX).isoformat(timespec="seconds")))
        tok = b["token"]
        for step in range(1, 20):
            self.at(start + timedelta(minutes=50 * step))
            s, b, _h, _p = self.call("POST", "/session/refresh", tok)
            if s != 200:
                break
            tok = b["token"]
            self.assertEqual(b["session_ends_at"], (start + SE.SESSION_MAX).isoformat(timespec="seconds"))
        self.assertEqual(step, 15)                                   # 12시간이 넘으면 끝(12:30) — 계속 이어 가지 못한다
        self.assertEqual(b["error"], "token-expired")
        self.at(start + timedelta(hours=11, minutes=30))
        s, b, _h, _p = self.call("POST", "/session/refresh", self.signer.issue(100, start + timedelta(hours=11),
                                                                            login_at=start))
        self.assertEqual((s, b["expires_in"]), (200, 1800))

    def test_refresh_keeps_narrowing(self):
        self.erp.person(MARK_SSO, 1, manager=False)
        _s, b = self.login()
        self.at(self.fc.now() + timedelta(minutes=50))
        s, r, _h, _p = self.call("POST", "/session/refresh", b["token"])
        self.assertEqual((s, r["narrowed"], self.signer.verify(r["token"], self.fc.now()).narrowed), (200, True, True))
        _s, board, _h, _p = self.call("GET", "/board", r["token"], query="attention=0")
        self.assertEqual(board["counts"]["total"], 0)

    def test_login_narrows_on_any_doubt(self):
        """my-profile 이 팀장이 아니라 하거나 · 다른 팀이거나 · 모양이 모르겠으면 좁힌다(늘리지 않는다 · 검토 test-gap)."""
        cases = [dict(manager=True, teams=((11, 10), (12, 10), (10, 0))),    # 끝 팀이 둘 — 모름
                 dict(manager=True, teams=((10, 0),)),                     # 가장 깊은 팀이 조직 표와 다름
                 dict(manager="false"), dict(manager=1), dict(manager="Y")]  # 참거짓이 아님
        for i, kw in enumerate(cases):
            self.erp.person(tok(i), 1, **kw)
            s, b = self.login(tok(i))
            self.assertEqual((s, b["narrowed"]), (200, True), kw)
            _s, board, _h, _p = self.call("GET", "/board", b["token"], query="attention=0")
            self.assertEqual(board["counts"]["total"], 0, kw)

    def test_login_needs_audit(self):
        self.erp.person(MARK_SSO, 100)

        def broken(fn):
            raise S.StoreBusy("x")
        self.app = WEB.App(open_read=lambda: S.open_reader(self.path), write=broken, signer=self.signer,
                           profiles=EP.ErpProfileReader(transport=self.erp), clock=self.fc.now)
        s, b = self.login()
        self.assertEqual((s, b), (503, {"error": "audit-unavailable"}))

    def test_sso_and_personal_fields_never_kept(self):
        self.erp.person(MARK_SSO, 100)
        s, b = self.login()
        self.call("GET", "/me", b["token"])
        self.st.close()
        self.st = None
        raw = pathlib.Path(self.path).read_bytes()
        for side in ("-wal", "-shm"):
            if os.path.exists(self.path + side):
                raw += pathlib.Path(self.path + side).read_bytes()
        for mark in (MARK_SSO, MARK_LOGIN_ID, MARK_PHONE, "900101"):
            self.assertNotIn(mark.encode("utf-8"), raw, mark)
        self.assertNotIn(MARK_SSO, b["token"])


# ── 범위 밖 = 없음 ───────────────────────────────────────────────────
class VisibilityTest(WebBase):
    def test_board_scoped(self):
        for idx, want in ((100, {11, 14}), (101, {12}), (1, {11, 12, 14}), (0, {11, 12, 13, 14})):
            s, b = self.get("/board", idx, query="attention=0")
            self.assertEqual(s, 200)
            self.assertEqual({r["possibility_id"] for r in b["rows"]}, want, idx)
            self.assertEqual(b["counts"]["total"], len(want))

    def test_same_404_for_missing_and_out_of_scope(self):
        s1, b1, _h, p1 = self.call("GET", "/clients/12", self.token(100))   # 있지만 범위 밖
        s2, b2, _h, p2 = self.call("GET", "/clients/99999", self.token(100))   # 없음
        s3, b3, _h, p3 = self.call("GET", "/clients/0", self.token(100))
        self.assertEqual((s1, s2, s3), (404, 404, 404))
        self.assertEqual(p1, p2)
        self.assertEqual(p1, p3)
        self.assertEqual(b1["message"], SC.CLIENT_NOT_VISIBLE)
        iid = self.issue_of(12, "yellow")["issue_id"]
        s4, _b, _h, p4 = self.call("POST", f"/issues/{iid}/ack", self.token(100))
        s5, _b, _h, p5 = self.call("POST", "/issues/99999/ack", self.token(100))
        self.assertEqual((s4, s5, p4, p5), (404, 404, p1, p1))

    def test_random_people_and_numbers(self):
        """가짜 조직 × 무작위 사람 × 무작위 번호 → 보이면 200, 아니면 늘 같은 404 본문(설계 v1.4 §12 ②)."""
        rnd = random.Random(7)
        ctx = W.load(self.st, self.fc.now())
        ref = None
        for _ in range(120):
            who = rnd.choice([0, 1, 100, 101])
            pid = rnd.choice([11, 12, 13, 14, 15, 0, 999999999])
            s, _b, _h, p = self.call("GET", f"/clients/{pid}", self.token(who))
            seen = pid in SC.clients_in(ctx.org, SC.scope_of(ctx.org, who), ctx.owns)
            self.assertEqual(s, 200 if seen else 404, (who, pid))
            if not seen:
                ref = ref or p
                self.assertEqual(p, ref)

    def test_out_of_scope_data_does_not_change_my_answers(self):
        """범위 밖 광고주·이슈·후보·알림이 늘어도 내 응답은 한 글자도 안 바뀐다(수·배지로 추론 불가 · §12 ③)."""
        def snap():
            out = {}
            for path, q in (("/me", ""), ("/board", "attention=0"), ("/board", ""), ("/links/pending", ""),
                            ("/ended", ""), ("/unlinked", ""), ("/bell", ""), ("/health", ""), ("/clients/11", "")):
                s, b = self.get(path, 100, query=q)
                self.assertEqual(s, 200, path)
                out[path + q] = b
            return out
        before = snap()
        # 101 담당 가망에 🔴 하나 · 101 에게만 알림 하나
        rid = self.st.begin_run(TODAY, self.fc.now())
        self.st.record_account_check(rid, B, possibility_id=12, link="auto", status="ok",
                                     rules_run=("bizmoney", "link"), rules_not_run=(), checked_at=self.fc.now(),
                                     findings=(TA.F("bizmoney", "bizmoney_low", f"acc:{B}", "red"),))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        self.st.record_alert(S.ALERT_DIGEST, TODAY, "compose", "digest", (), "/naver/issues",
                             [{"emp_idx": 101, "severity": "URGENT", "params": {"red": 1, "yellow": 2}}], self.fc.now())
        after = snap()
        for k in before:
            if k in ("/board", "/boardattention=0", "/health"):
                before[k]["band"] = after[k]["band"] = None   # 회차 줄(대표 아닌 사람에겐 상태·시각만)
                before[k].pop("runs", None)
                after[k].pop("runs", None)
            self.assertEqual(before[k], after[k], k)

    def test_out_of_scope_data_does_not_change_101_answers(self):
        """같은 시험을 101 쪽에서 — 100 의 광고주(11 · 14)에 🔴 · 막힘 · 알림을 더해도 101 의 응답은 그대로."""
        def snap():
            out = {}
            for path, q in (("/me", ""), ("/board", "attention=0"), ("/links/pending", ""), ("/ended", ""),
                            ("/unlinked", ""), ("/bell", ""), ("/clients/12", "")):
                s, b = self.get(path, 101, query=q)
                self.assertEqual(s, 200, path)
                b.pop("band", None)
                b.pop("pairing_at", None)
                b.pop("pairing_today", None)
                for r in b.get("rows", ()):
                    r.pop("ref", None)   # 가리킴표는 짝 맞추기마다 새로 — 수·있고 없음을 말하지 않는다
                out[path + q] = b
            return out
        before = snap()
        rid = self.st.begin_run(TODAY, self.fc.now())
        self.st.record_account_check(rid, A, possibility_id=11, link="confirmed", status="ok",
                                     rules_run=("bizmoney", "link"), rules_not_run=(), checked_at=self.fc.now(),
                                     findings=(TA.F("bizmoney", "bizmoney_low", f"acc:{A}", "yellow"),))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        self.st.record_alert(S.ALERT_DIGEST, TODAY, "compose", "digest", (), "/naver/issues",
                             [{"emp_idx": 100, "severity": "URGENT", "params": {"red": 1, "yellow": 2}}], self.fc.now())
        self.repair([(12, B), (14, 9999999)], stages={14: TM.srow(14, stage="계약만료", end=TODAY - timedelta(days=2))})
        self.assertEqual(before, snap())

    def test_as_parameter_ignored(self):
        s, b = self.get("/board", 100, query="attention=0&as=0")
        self.assertEqual({r["possibility_id"] for r in b["rows"]}, {11, 14})

    def test_selection_rules(self):
        self.assertEqual(self.get("/board", 100, query="selection=unassigned")[0], 400)   # 대표만
        self.assertEqual(self.get("/board", 100, query="selection=person:101")[0], 404)    # 범위 밖 사람
        bodies = {self.call("GET", "/board", self.token(100), query=q)[3]
                  for q in ("selection=person:101", "selection=person:99999", "selection=team:11",
                            "selection=team:99999")}
        self.assertEqual(len(bodies), 1)                                                   # 없는 사람·팀과 같은 본문
        self.assertEqual(json.loads(bodies.pop())["message"], SC.TARGET_NOT_VISIBLE)
        s, b = self.get("/board", 1, query="selection=person%3A101&attention=0")
        self.assertEqual((s, {r["possibility_id"] for r in b["rows"]}), (200, {12}))
        s, b = self.get("/board", 0, query="selection=unassigned&attention=0")
        self.assertEqual({r["possibility_id"] for r in b["rows"]}, {13})
        self.assertEqual(self.get("/board", 0, query="selection=%ZZ")[0], 400)
        self.assertEqual(self.get("/board", 0, query="attention=2")[0], 400)

    def test_resigned_zero_from_next_request(self):
        tok = self.token(100)
        self.assertEqual(self.call("GET", "/me", tok)[0], 200)
        self.resign(100)
        s, b, _h, _p = self.call("GET", "/me", tok)
        self.assertEqual((s, b["error"]), (401, "no-scope"))
        self.assertEqual(self.call("POST", "/session/refresh", tok)[0], 401)

    def test_token_expiry_and_refresh(self):
        tok = self.token(100)
        s, b, _h, _p = self.call("POST", "/session/refresh", tok)
        self.assertEqual(s, 200)
        self.at(self.fc.now() + timedelta(hours=1))
        self.assertEqual(self.call("GET", "/me", tok)[1]["error"], "token-expired")
        self.assertEqual(self.call("GET", "/me", b["token"])[0], 401)

    def test_ceo_band_counts_only_for_ceo(self):
        _s, ceo = self.get("/board", 0)
        self.assertIn("accounts_total", ceo["band"]["runs"][0])
        self.assertIn("accounts_total", self.get("/health", 0)[1]["runs"][0])
        for idx, kw in ((100, {}), (1, {}), (1, {"narrowed": True})):    # 담당 · 팀장 · 좁힌 팀장
            _s, b = self.get("/board", idx, **kw)
            _s, h = self.get("/health", idx, **kw)
            for run in b["band"]["runs"] + h["runs"]:
                for k in ("accounts_total", "accounts_ok", "error_kind"):
                    self.assertNotIn(k, run, (idx, kw))

    def test_ended_and_unlinked_scoped(self):
        """📦 계약 끝남 · ⚪ 이관 안 됨 목록도 범위 안만(검토 test-gap-ended-unlinked-scope)."""
        self.repair([(12, B), (14, 9999999)],
                    stages={12: TM.srow(12, stage="계약만료", end=TODAY - timedelta(days=3))})
        want = {0: ({12}, {14}), 1: ({12}, {14}), 100: (set(), {14}), 101: ({12}, set())}
        for idx, (ended, unlinked) in want.items():
            _s, e = self.get("/ended", idx)
            _s, u = self.get("/unlinked", idx)
            self.assertEqual(({r["possibility_id"] for r in e["rows"]}, {r["possibility_id"] for r in u["rows"]}),
                             (ended, unlinked), idx)

    def test_ended_link_left_after_grace(self):
        """끝난 지 14일이 넘어 짝 맞추기가 빼도 「네이버 연결 남음」은 사람 확인·자동 연결 기록 + 오늘 목록에서
        (검토 ended-still-linked-false-after-grace) · 종료일을 모르는 계약 만료도 점검은 멈춘 것."""
        for days, stopped in ((10, False), (20, True)):
            self.repair([(12, B), (14, 9999999)],
                        stages={11: TM.srow(11, stage="계약만료", end=TODAY - timedelta(days=days))})
            [row] = self.get("/ended", 100)[1]["rows"]
            self.assertEqual((row["possibility_id"], row["still_linked"], row["checks_stopped"]), (11, True, stopped))
        self.repair([(12, B), (14, 9999999)], stages={12: TM.srow(12, stage="계약만료", end=TODAY - timedelta(days=30))})
        [row] = self.get("/ended", 101)[1]["rows"]
        self.assertEqual((row["still_linked"], row["checks_stopped"]), (True, True))   # 자동으로 이어졌던 계정
        self.repair([(12, B), (14, 9999999)], stages={11: TM.srow(11, stage="계약만료")})
        [row] = self.get("/ended", 100)[1]["rows"]
        self.assertEqual(row["checks_stopped"], True)

    def test_customer_ids_never_whole(self):
        """고객 번호는 어느 화면·어느 사람에게도 끝 4자리만(검토 test-gap-customer-id-masking)."""
        rid = self.st.begin_run(TODAY, self.fc.now())
        self.st.record_account_check(rid, B, possibility_id=12, link="auto", status="ok",
                                     rules_run=("bizmoney", "link"), rules_not_run=(), checked_at=self.fc.now(),
                                     findings=(TA.F("bizmoney", "bizmoney_low", f"acc:{B}", "red"),))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        for idx in (0, 1, 100, 101):
            for path, q in (("/me", ""), ("/board", "attention=0"), ("/links/pending", ""), ("/ended", ""),
                            ("/unlinked", ""), ("/bell", ""), ("/health", ""), ("/clients/11", ""),
                            ("/clients/12", ""), ("/clients/13", ""), ("/clients/14", "")):
                _s, _b, _h, p = self.call("GET", path, self.token(idx), query=q)
                for cid in (A, B, C_, D, 9999999):
                    self.assertNotIn(str(cid).encode("ascii"), p, (idx, path))

    def test_large_ids_audited(self):
        """API 가 받는 번호 범위(18자리)와 기록 범위가 같다(검토 audit-target-id-range-mismatch)."""
        self.assertEqual(self.get("/clients/3000000000", 100)[0], 404)
        self.assertEqual(self.st.access_log(viewer_idx=100)[0]["target_id"], 3000000000)

    def test_settings_scope(self):
        self.assertEqual(self.get("/settings", 100)[0], 403)
        s, team = self.get("/settings", 1)
        self.assertEqual((s, team["can_edit"], "holds" in team), (200, False, False))
        s, ceo = self.get("/settings", 0)
        self.assertEqual((s, ceo["can_edit"], ceo["holds"]), (200, True, []))


# ── 판정 조립 ────────────────────────────────────────────────────────
class VerdictAssemblyTest(WebBase):
    def test_colors(self):
        _s, b = self.get("/board", 0, query="attention=0")
        got = {r["possibility_id"]: r["verdict"]["color"] for r in b["rows"]}
        self.assertEqual(got, {11: V.RED, 12: V.YELLOW, 13: V.WHITE, 14: V.WHITE})
        auto = {r["possibility_id"]: r["account_unconfirmed"] for r in b["rows"]}
        self.assertTrue(auto[12])
        # 13(이름 후보) · 14(이관 안 됨)는 ⚪ 연결 없음 — 확인 필요 아니오(주간 목록 · I3 ⓐ)
        self.assertEqual(b["counts"], {"red": 1, "white": 2, "yellow": 1, "green": 0, "needs_attention": 2, "total": 4})
        _s, att = self.get("/board", 0)
        self.assertEqual({r["possibility_id"] for r in att["rows"]}, {11, 12})   # 기본 = 확인 필요만

    def test_yesterdays_pairing_is_not_todays_result(self):
        """어제 받은 짝 맞추기 — 오늘 계정 하루치가 있어도 오늘 결과가 아니다(마감 전 ⚪ 점검 전 · 뒤 ⚪ 점검 안 됨)."""
        ctx = W.load(self.st, at(TODAY + timedelta(days=1), 7, 0))
        self.assertFalse(ctx.pairing_today)
        self.assertEqual({c.status for c in W.account_checks(ctx, 11)}, {V.CHECK_PENDING})
        self.assertEqual(W.judge(ctx, 12).white_reason, V.CHECK_PENDING)
        late = W.load(self.st, at(TODAY + timedelta(days=1), 9, 0))
        self.assertEqual(W.judge(late, 12).white_reason, V.CHECK_NOT_CHECKED)
        self.assertTrue(W.judge(late, 12).needs_attention)

    def test_not_today_pairing_ignores_today_rows_and_stale_missing(self):
        """짝 맞추기가 오늘 것이 아니면 오늘 계정 하루치가 있어도 · 「오늘 없음」·「이관 빠짐」 줄이 있어도 점검 전/안 됨."""
        from dataclasses import replace
        ctx = W.load(self.st, self.fc.now())
        self.assertTrue(ctx.pairing_today)
        rows = dict(ctx.rows_by_pid)
        rows[13] = ({"possibility_id": 13, "customer_id": C_, "state": S.PAIR_MISSING, "code": None, "same_name": None,
                     "claimed_elsewhere": None, "decision_id": None, "link": "confirmed"},)
        rows[14] = ({"possibility_id": 14, "customer_id": D, "state": S.PAIR_BROKEN, "code": None, "same_name": None,
                     "claimed_elsewhere": None, "decision_id": None, "link": "auto"},)
        today_ctx = replace(ctx, rows_by_pid=rows)
        self.assertEqual([c.status for c in W.account_checks(today_ctx, 13)], [V.CHECK_LINK_MISSING])
        self.assertEqual([c.status for c in W.account_checks(today_ctx, 14)], [V.CHECK_LINK_BROKEN])
        old = replace(today_ctx, pairing_today=False)
        for pid in (11, 12, 13, 14):
            self.assertEqual({c.status for c in W.account_checks(old, pid)}, {V.CHECK_PENDING}, pid)

    def test_account_day_of_other_prospect_is_not_mine(self):
        ctx = W.load(self.st, self.fc.now())
        forged = dict(ctx.checks_today)
        forged[A] = dict(forged[A], possibility_id=12)
        from dataclasses import replace
        ctx2 = replace(ctx, checks_today=forged)
        self.assertEqual([c.status for c in W.account_checks(ctx2, 11)], [V.CHECK_PENDING])

    def test_unreadable_status_is_white_not_crash(self):
        ctx = W.load(self.st, self.fc.now())
        forged = dict(ctx.checks_today)
        forged[A] = dict(forged[A], status="weird")
        from dataclasses import replace
        v = W.judge(replace(ctx, checks_today=forged), 11)
        self.assertEqual((v.color, v.needs_attention), (V.WHITE, True))


# ── 이슈 손길 ────────────────────────────────────────────────────────
class IssueHandsTest(WebBase):
    def test_owner_acks_and_resolves(self):
        iid = self.issue_of(12, "yellow")["issue_id"]
        s, b = self.post(f"/issues/{iid}/ack", 101)
        self.assertEqual((s, b["state"]), (200, "ack"))
        s, b = self.post(f"/issues/{iid}/ack", 101)
        self.assertEqual(s, 409)
        s, b = self.post(f"/issues/{iid}/resolve", 101)
        self.assertEqual((s, b["state"]), (200, "resolved"))
        [ev] = [e for e in self.st.issue_events(iid) if e["kind"] == "acked"]
        self.assertEqual(ev["by_person"], 101)
        self.assertEqual([(r["action"], r["result"]) for r in self.st.access_log(viewer_idx=101)][:3],
                         [("resolve", "ok"), ("ack", "refused-" + I.E_NOT_NEW), ("ack", "ok")])

    def test_exception_layers(self):
        red = self.issue_of(11, "red")["issue_id"]
        yellow = self.issue_of(12, "yellow")["issue_id"]
        until = (TODAY + timedelta(days=5)).isoformat()
        s, b = self.post(f"/issues/{red}/except", 100, {"until": until, "note": "사유"})
        self.assertEqual((s, b["error"]), (409, I.E_ACTOR))            # 담당은 🔴 예외를 못 준다
        s, b = self.post(f"/issues/{red}/except", 1, {"until": until, "note": "사유"})
        self.assertEqual((s, b["state"]), (200, "exception"))          # 팀장은 된다(7일 안)
        s, b = self.post(f"/issues/{yellow}/except", 101, {"until": (TODAY + timedelta(days=40)).isoformat(),
                                                           "note": "사유"})
        self.assertEqual(s, 409)                                       # 30일 넘음
        s, b = self.post(f"/issues/{yellow}/except", 101, {"until": until, "note": "사유"})
        self.assertEqual(s, 200)
        for bad in ({"until": until}, {"until": "2026-13-01", "note": "x"}, {"until": until, "note": ""},
                    {"until": until, "note": "x" * 201}, {"until": 5, "note": "x"}):
            self.assertEqual(self.post(f"/issues/{red}/except", 0, bad)[0], 400, bad)

    def test_stale_org_blocks_exception_not_ack(self):
        self.at(self.fc.now() + timedelta(hours=30))
        yellow = self.issue_of(12, "yellow")["issue_id"]
        s, b = self.post(f"/issues/{yellow}/except", 101, {"until": (self.fc.now().date()).isoformat(),
                                                           "note": "사유"})
        self.assertEqual((s, b["error"]), (409, "org-stale"))
        self.assertEqual(self.post(f"/issues/{yellow}/ack", 101)[0], 200)

    def test_prev_owner_cannot_handle(self):
        owners = [TA.owner(11, 100), TA.owner(12, 101), TA.owner(13, None),
                  {"possibility_id": 14, "manage_emp_idx": None, "sub_manage_emp_idx": None,
                   "prev_manage_owner_idx": 100, "sales_emp_idx": None, "owner_source": "prev"}]
        self.st.record_org(TA.org_body(self.fc.now() - timedelta(minutes=1), owners=owners), self.fc.now())
        ctx = W.load(self.st, self.fc.now())
        self.assertEqual(SC.relation(ctx.org, SC.scope_of(ctx.org, 100), ctx.owns[14]), SC.REL_PREV)
        rid = self.st.begin_run(TODAY, self.fc.now())
        self.st.record_account_check(rid, A, possibility_id=14, link="confirmed", status="ok",
                                     rules_run=("bizmoney", "link"), rules_not_run=(), checked_at=self.fc.now(),
                                     findings=(TA.F("bizmoney", "bizmoney_low", f"acc:{A}", "yellow"),))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        iid = self.issue_of(14, "yellow")["issue_id"]
        s, b = self.post(f"/issues/{iid}/ack", 100)
        self.assertEqual((s, b["error"]), (403, "action-not-allowed"))
        self.assertEqual(self.get("/clients/14", 100)[0], 200)   # 보기는 된다


# ── 짝 확인 ──────────────────────────────────────────────────────────
class LinksTest(WebBase):
    def pending(self, idx):
        s, b = self.get("/links/pending", idx)
        self.assertEqual(s, 200)
        return b

    def ref_of(self, idx, pid, state=None):
        rows = [r for r in self.pending(idx)["rows"] if r["possibility_id"] == pid
                and (state is None or r["state"] == state)]
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def test_pending_rows_scoped_and_masked(self):
        ceo = self.pending(0)
        by = {r["possibility_id"]: r for r in ceo["rows"]}
        self.assertEqual(set(by), {12, 13, 14})                  # 자동 짝(12)도 사람이 확인할 때까지 여기서
        self.assertEqual((by[13]["state"], by[13]["tail"], by[13]["can_confirm"]), ("candidate", str(C_)[-4:], True))
        self.assertEqual((by[14]["code"], by[14]["can_confirm"]), ("not-linked", False))
        self.assertEqual((by[12]["state"], by[12]["can_confirm"], by[12]["can_reject"]), ("auto", True, True))
        payload = json.dumps(ceo)
        self.assertNotIn(str(C_), payload)                       # 번호 원문 없음 — 끝 4자리만
        self.assertEqual({r["possibility_id"] for r in self.pending(100)["rows"]}, {14})
        self.assertEqual([(r["possibility_id"], r["can_confirm"]) for r in self.pending(101)["rows"]], [(12, True)])

    def test_auto_pair_confirmable_by_owner(self):
        """자동 짝은 「계정 확인 전」 — 담당이 여기서 「이 계정 맞음」·「아님」을 누른다(설계 v1.8 Q5 · M4 · 계획 7)."""
        row = self.ref_of(101, 12, "auto")
        self.assertEqual(row["account_name"], TM.shop(12))
        s, b = self.post("/links/confirm", 101, {"refs": [row["ref"]]})
        self.assertEqual((s, b["decided"]), (200, 1))
        self.assertIn((12, B, "confirmed", 101), [(d.possibility_id, d.customer_id, d.decision, d.decided_by)
                                                 for d in self.st.current_decisions()])
        self.repair([(12, B), (14, 9999999)])
        _s, c = self.get("/clients/12", 101)
        self.assertNotIn("account-unconfirmed", c["verdict"]["reasons"])
        self.assertEqual([a["link"] for a in c["accounts"]], ["confirmed"])

    def test_confirm_cannot_take_account_held_out_of_scope(self):
        """범위 밖 광고주가 쥔 계정은 담당·팀장이 이어 가져오지 못한다 — 같은 409 · 아무것도 적지 않는다 · 이름도 주지 않는다
        (검토 link-confirm-steals-out-of-scope-account · 세 갈래)."""
        # ① 사람(101)이 자기 자동 짝을 확인한 뒤 · 100 이 자기 가망 ① 에 같은 번호를 적음 → 14 는 「다른 가망에 확인됨」
        self.post("/links/confirm", 101, {"refs": [self.ref_of(101, 12, "auto")["ref"]]})
        self.repair([(14, B)])
        row = self.ref_of(100, 14)
        self.assertEqual((row["code"], row["can_confirm"], row["account_name"], row["other_candidate"]),
                         ("confirmed-elsewhere", False, None, True))
        before = [(d.decision_id, d.possibility_id) for d in self.st.current_decisions()]
        self.assertEqual(self.post("/links/confirm", 100, {"refs": [row["ref"]]}), (409, {"error": "not-linkable"}))
        self.assertEqual([(d.decision_id, d.possibility_id) for d in self.st.current_decisions()], before)
        self.assertEqual(self.st.access_log(viewer_idx=100)[0]["result"], "not-linkable")   # 거절도 기록
        # ② 자동 짝(12)과 100 의 ① 이 같은 번호 → 둘 다 「여러 가망이 적음」 — 100 은 못 가져간다 · 두 가망을 다 보는 팀장은 된다
        self.st.revoke_decision([d for d in self.st.current_decisions() if d.possibility_id == 12][0].decision_id,
                                0, self.fc.now(), "시험")
        self.repair([(12, B), (14, B)])
        row = self.ref_of(100, 14)
        self.assertEqual((row["code"], row["can_confirm"], row["account_name"]), ("claimed-by-several", False, None))
        self.assertEqual(self.post("/links/confirm", 100, {"refs": [row["ref"]]})[0], 409)
        lead = self.ref_of(1, 14)
        self.assertEqual((lead["can_confirm"], lead["account_name"]), (True, TM.shop(12)))
        self.assertEqual(self.post("/links/confirm", 1, {"refs": [lead["ref"]]})[0], 200)
        # ③ 이름 후보의 계정을 범위 밖 가망이 쥔 경우는 test_name_candidate_held_by_out_of_scope_prospect

    def test_name_candidate_held_by_out_of_scope_prospect(self):
        """이름 후보의 계정을 범위 밖 가망이 쥐었다(사람 확인) — 확인·미리보기 거절 · 이름 없이 「다른 후보 있음」만."""
        TM.NAMES[D] = TM.shop(14)
        self.st.record_decision(13, D, "confirmed", 0, self.fc.now())    # 대표만 보는 가망 13 에 확인
        self.repair([(14, 9999999)], stages={13: TM.srow(13, stage="계약만료", end=TODAY - timedelta(days=30))})
        row = self.ref_of(100, 14, "candidate")
        self.assertEqual((row["can_confirm"], row["account_name"], row["other_candidate"]), (False, None, True))
        seen = []
        self.app = self.make_app(previewer=lambda h: seen.append(h) or ["남의캠페인"])
        row = self.ref_of(100, 14, "candidate")
        self.assertEqual(self.post("/links/confirm", 100, {"refs": [row["ref"]]})[0], 409)
        self.assertEqual(self.post("/links/preview", 100, {"ref": row["ref"]}), (409, {"error": "not-linkable"}))
        self.assertEqual(seen, [])                                        # 네이버를 부르지도 않았다
        self.assertEqual([d.possibility_id for d in self.st.current_decisions() if d.customer_id == D], [13])
        ceo = self.ref_of(0, 14, "candidate")
        self.assertEqual((ceo["can_confirm"], ceo["account_name"]), (True, TM.shop(14)))

    def test_claim_by_unmanaged_prospect_is_ceo_only(self):
        """같은 번호를 관리 대상 밖 가망(계약 끝난 지 오래 · 짝 줄이 없다)도 ① 에 적었다 — 누가 주장하는지 화면이 모르므로
        대표만 잇는다(담당·팀장 모두 409 · 이름 없이)."""
        self.repair([(12, B), (14, D), (15, D)])
        for idx in (100, 1):
            row = self.ref_of(idx, 14)
            self.assertEqual((row["code"], row["can_confirm"], row["account_name"], row["other_candidate"]),
                             ("claimed-by-several", False, None, True), idx)
            self.assertEqual(self.post("/links/confirm", idx, {"refs": [row["ref"]]})[0], 409, idx)
        ceo = self.ref_of(0, 14)
        self.assertEqual((ceo["can_confirm"], ceo["account_name"]), (True, "다른이름"))
        self.assertEqual(self.post("/links/confirm", 0, {"refs": [ceo["ref"]]})[0], 200)

    def test_human_confirmation_holder_counts_even_with_other_holders(self):
        """계정을 쥔 곳이 여럿 — 내가 다룰 수 있는 가망(이름이 같음)과, 사람이 확인한 범위 밖 가망. 하나라도 범위 밖이면 거절
        (사람 확인만 따로 빠져도 잡히게)."""
        TM.NAMES[D] = "가게14본점"
        self.st.record_decision(13, D, "confirmed", 0, self.fc.now())    # 대표만 보는 13(계약 끝난 지 오래)에 확인
        self.repair([(14, 9999999)], stages={11: TM.srow(11, name="가게14본점"),
                                               13: TM.srow(13, stage="계약만료", end=TODAY - timedelta(days=30))})
        row = self.ref_of(100, 14, "candidate")
        self.assertEqual((row["can_confirm"], row["account_name"]), (False, None))
        self.assertEqual(self.post("/links/confirm", 100, {"refs": [row["ref"]]})[0], 409)
        self.assertEqual([d.possibility_id for d in self.st.current_decisions() if d.customer_id == D], [13])

    def test_pairing_row_holder_counts_even_with_other_holders(self):
        """범위 밖 가망(101 의 12)이 ① 에 그 번호를 적어 짝 줄(이름 다름)이 있고, 내가 다룰 수 있는 가망(11)은 이름이 같다 —
        짝 줄 주인이 범위 밖이면 거절(짝 줄만 따로 빠져도 잡히게)."""
        TM.NAMES[D] = "가게14본점"
        self.repair([(12, B), (12, D), (14, 9999999)], stages={11: TM.srow(11, name="가게14본점")})
        self.assertIn("name-different", [r["code"] for r in self.pending(101)["rows"]])
        row = self.ref_of(100, 14, "candidate")
        self.assertEqual((row["can_confirm"], row["account_name"]), (False, None))
        self.assertEqual(self.post("/links/confirm", 100, {"refs": [row["ref"]]})[0], 409)

    def test_name_holder_counts(self):
        """아무도 번호를 적거나 확인하지 않았지만 계정 이름이 범위 밖 가망(대표만 보는 13)의 상호와 같다 — 거절
        (이름이 가리키는 가망만 따로 빠져도 잡히게 · 담당이 남의 번호를 적어 가져오는 길)."""
        self.st.record_decision(13, C_, "confirmed", 0, self.fc.now())   # 13 은 짝이 있어 후보를 받지 않는다
        TM.NAMES[D] = "가게14본점"
        self.repair([(12, B), (14, 9999999)], stages={13: TM.srow(13, name="가게14본점")})
        row = self.ref_of(100, 14, "candidate")
        self.assertEqual((row["can_confirm"], row["account_name"], row["other_candidate"]), (False, None, True))
        self.assertEqual(self.post("/links/confirm", 100, {"refs": [row["ref"]]})[0], 409)
        self.assertTrue(self.ref_of(0, 14, "candidate")["can_confirm"])

    def test_preview_of_account_held_elsewhere_refused(self):
        """검토 link-preview-reads-out-of-scope-account — 대표가 12 에 확인한 계정을 100 이 ① 에 적어 미리보기를 누름."""
        self.st.record_decision(12, B, "confirmed", 0, self.fc.now())
        self.repair([(14, B)])
        seen = []
        self.app = self.make_app(previewer=lambda h: seen.append(h) or ["101광고주캠페인"])
        row = self.ref_of(100, 14)
        self.assertEqual(row["code"], "confirmed-elsewhere")
        self.assertEqual(self.post("/links/preview", 100, {"ref": row["ref"]})[0], 409)
        self.assertEqual(seen, [])

    def test_number_space_overlap_not_joined(self):
        """적힌 번호가 한 계정(E)의 고객 번호이면서 다른 계정(B)의 광고계정 번호 — 「번호 공간 겹침」 막힘은 번호가 누구의 것인지
        모르므로 계정 이름을 싣지 않는다(검토 blocked-rows-joined 재현 (b))."""
        e_id = 8_000_000 + B % 1_000_000                                   # B 의 광고계정 번호와 같은 고객 번호
        self.repair([(12, B), (14, e_id)],
                    extra={e_id: {"customerId": e_id, "adAccountNo": 9_111_111, "adAccountName": "남의가게"}})
        for idx in (0, 100):
            row = self.ref_of(idx, 14)
            self.assertEqual((row["code"], row["account_name"], row["can_confirm"], row["other_candidate"]),
                             ("ambiguous-space", None, False, False), idx)

    def test_blocked_rows_not_joined_to_account_table(self):
        """번호가 계정이 아닌 막힘(광고계정 번호 · 번호 공간 겹침)과 남이 쥔 계정의 막힘은 계정 이름을 싣지 않는다
        (설계 v1.8 S8 security-1 · 검토 blocked-rows-joined-to-account-table)."""
        ad_no_of_b = 8_000_000 + B % 1_000_000
        self.repair([(14, ad_no_of_b)])
        row = self.ref_of(100, 14)
        self.assertEqual((row["code"], row["account_name"], row["can_confirm"], row["can_reject"]),
                         ("ad-account-number", None, False, False))
        for r in self.pending(0)["rows"]:
            if r["code"] in W.NOT_A_CUSTOMER:
                self.assertIsNone(r["account_name"], r)

    def test_confirm_candidate_records_decision(self):
        ref = [r for r in self.pending(0)["rows"] if r["possibility_id"] == 13][0]["ref"]
        s, b = self.post("/links/confirm", 0, {"refs": [ref]})
        self.assertEqual((s, b["decided"]), (200, 1))
        latest = [d for d in self.st.current_decisions() if d.possibility_id == 13]
        self.assertEqual([(d.customer_id, d.decision, d.decided_by) for d in latest], [(C_, "confirmed", 0)])

    def test_batch_with_one_out_of_scope_writes_nothing(self):
        """묶음 — 하나라도 범위 밖·없는 가리킴표면 전체 거절 · 아무것도 적지 않는다(같은 404)."""
        ref13 = [r for r in self.pending(0)["rows"] if r["possibility_id"] == 13][0]["ref"]
        before = len(self.st.current_decisions())
        for idx, refs in ((100, [ref13]), (0, [ref13, "0" * W.REF_LENGTH])):
            s, b, _h, p = self.call("POST", "/links/confirm", self.token(idx), body={"refs": refs})
            self.assertEqual((s, b["message"]), (404, SC.CLIENT_NOT_VISIBLE))
        self.assertEqual(len(self.st.current_decisions()), before)
        self.assertEqual(self.post("/links/confirm", 0, {"refs": [ref13, ref13]})[0], 400)
        self.assertEqual(self.post("/links/confirm", 0, {"refs": []})[0], 400)

    def test_not_linkable_rows_refused(self):
        ref14 = [r for r in self.pending(0)["rows"] if r["possibility_id"] == 14][0]["ref"]
        self.assertEqual(self.post("/links/confirm", 0, {"refs": [ref14]}), (409, {"error": "not-linkable"}))
        self.assertEqual(self.st.access_log(viewer_idx=0)[0]["result"], "not-linkable")

    def test_batch_decisions_one_transaction(self):
        """묶음 판단은 한 거래 — 둘째 줄이 틀리면 첫 줄도 남지 않는다 · 쓰기 실패는 기록(검토 batch-decisions-not-atomic)."""
        before = len(self.st.current_decisions())
        with self.assertRaises(S.StoreRefused):
            self.st.record_decisions([(13, C_), (14, -1)], "confirmed", 0, self.fc.now())
        with self.assertRaises(S.StoreRefused):
            self.st.record_decisions([(13, C_), (13, C_)], "confirmed", 0, self.fc.now())
        self.assertEqual(len(self.st.current_decisions()), before)
        ref13 = self.ref_of(0, 13)["ref"]

        def broken(fn):
            raise S.StoreBusy("x")
        self.app = WEB.App(open_read=lambda: S.open_reader(self.path), write=broken, signer=self.signer,
                           profiles=EP.ErpProfileReader(transport=self.erp), clock=self.fc.now)
        self.assertEqual(self.post("/links/confirm", 0, {"refs": [ref13]}), (503, {"error": "store-busy"}))
        self.assertEqual(len(self.st.current_decisions()), before)
        self.app = self.make_app()
        s, _b = self.post("/links/confirm", 0, {"refs": [ref13]})
        self.assertEqual(s, 200)
        log = self.st.access_log(viewer_idx=0)
        self.assertEqual((log[0]["action"], log[0]["target_id"], log[0]["result"]), ("link-confirm", 13, "ok"))

    def test_prev_owner_cannot_confirm_reject_revoke_preview(self):
        """이전 담당(계약 만료 직전 담당)은 보기·멈추기만 — 짝 확인·아님·거두기·미리보기 모두 안 된다(검토 test-gap)."""
        owners = [{"possibility_id": 11, "manage_emp_idx": None, "sub_manage_emp_idx": None,
                   "prev_manage_owner_idx": 100, "sales_emp_idx": None, "owner_source": "prev"},
                  TA.owner(12, 101),
                  {"possibility_id": 13, "manage_emp_idx": None, "sub_manage_emp_idx": None,
                   "prev_manage_owner_idx": 100, "sales_emp_idx": None, "owner_source": "prev"},
                  TA.owner(14, 100)]
        self.st.record_org(TA.org_body(self.fc.now() - timedelta(minutes=1), owners=owners), self.fc.now())
        ref13 = self.ref_of(0, 13)["ref"]
        self.app = self.make_app(previewer=lambda h: ["캠페인"])
        before = [(d.decision_id, d.possibility_id) for d in self.st.current_decisions()]
        for path, body in (("/links/confirm", {"refs": [ref13]}), ("/links/reject", {"refs": [ref13]}),
                           ("/links/preview", {"ref": ref13})):
            s, b = self.post(path, 100, body)
            self.assertEqual((s, b["error"]), (403, "action-not-allowed"), path)
        [d11] = [d for d in self.st.current_decisions() if d.possibility_id == 11]
        self.assertEqual(self.post("/links/revoke", 100, {"decision_id": d11.decision_id, "reason": "틀림"})[0], 404)
        self.assertEqual([(d.decision_id, d.possibility_id) for d in self.st.current_decisions()], before)
        self.assertEqual(self.st.access_log(viewer_idx=100)[-1]["result"], "not-allowed")

    def test_revoke_and_preview_same_404_body(self):
        [d] = [x for x in self.pending(0)["decisions"] if x["possibility_id"] == 11]
        s1, _b, _h, p1 = self.call("POST", "/links/revoke", self.token(101),
                                   body={"decision_id": d["decision_id"], "reason": "틀림"})
        s2, _b, _h, p2 = self.call("POST", "/links/revoke", self.token(101), body={"decision_id": 99999, "reason": "틀림"})
        self.assertEqual((s1, s2, p1), (404, 404, p2))
        ref13 = self.ref_of(0, 13)["ref"]
        s3, _b, _h, p3 = self.call("POST", "/links/preview", self.token(100), body={"ref": ref13})
        s4, _b, _h, p4 = self.call("POST", "/links/preview", self.token(100), body={"ref": "0" * W.REF_LENGTH})
        self.assertEqual((s3, s4, p3, p4), (404, 404, p1, p1))

    def test_revoke_refused_is_logged(self):
        [d] = [x for x in self.pending(0)["decisions"] if x["possibility_id"] == 11]
        s, b = self.post("/links/revoke", 100, {"decision_id": d["decision_id"], "reason": "틀\x00림"})
        self.assertEqual((s, b["error"]), (409, "revoke-refused"))
        self.assertEqual(self.st.access_log(viewer_idx=100)[0]["result"], "refused")

    def test_preview_drops_unencodable_names(self):
        self.app = self.make_app(previewer=lambda h: ["캠페인\ud800", 5, "정상"])
        s, b = self.post("/links/preview", 0, {"ref": self.ref_of(0, 13)["ref"]})
        self.assertEqual((s, b["campaigns"]), (200, ["정상"]))

    def test_stale_org_blocks_confirm_not_reject(self):
        ref13 = [r for r in self.pending(0)["rows"] if r["possibility_id"] == 13][0]["ref"]
        self.at(self.fc.now() + timedelta(hours=27))
        s, b = self.post("/links/confirm", 0, {"refs": [ref13]})
        self.assertEqual((s, b["error"]), (409, "org-stale"))
        s, b = self.post("/links/reject", 0, {"refs": [ref13]})
        self.assertEqual((s, b["decision"]), (200, "rejected"))

    def test_revoke_scoped(self):
        [d] = [x for x in self.pending(0)["decisions"] if x["possibility_id"] == 11]
        self.assertEqual(self.post("/links/revoke", 101, {"decision_id": d["decision_id"], "reason": "틀림"})[0], 404)
        self.assertEqual(self.post("/links/revoke", 100, {"decision_id": 9999, "reason": "틀림"})[0], 404)
        s, b = self.post("/links/revoke", 100, {"decision_id": d["decision_id"], "reason": "틀림"})
        self.assertEqual(s, 200)
        self.assertEqual(self.post("/links/revoke", 100, {"decision_id": d["decision_id"], "reason": "틀림"})[0], 404)

    def test_preview_needs_previewer_and_eligible(self):
        ref13 = [r for r in self.pending(0)["rows"] if r["possibility_id"] == 13][0]["ref"]
        self.assertEqual(self.post("/links/preview", 0, {"ref": ref13})[1]["error"], "preview-unavailable")
        seen = []
        self.app = self.make_app(previewer=lambda h: seen.append(h) or ["캠페인1", "캠페인2", "캠페인3", "캠페인4"])
        ref13 = [r for r in self.pending(0)["rows"] if r["possibility_id"] == 13][0]["ref"]
        s, b = self.post("/links/preview", 0, {"ref": ref13})
        self.assertEqual((s, b["campaigns"]), (200, ["캠페인1", "캠페인2", "캠페인3"]))
        self.assertEqual(len(seen), 1)
        self.assertEqual(self.post("/links/preview", 100, {"ref": ref13})[0], 404)

    def test_preview_needs_audit(self):
        """미리보기는 네이버에서 읽은 광고주 자료 — 기록을 못 적으면 보여 주지 않는다(검토 test-gap-audit-required)."""
        ref13 = self.ref_of(0, 13)["ref"]

        def broken(fn):
            raise S.StoreBusy("x")
        self.app = WEB.App(open_read=lambda: S.open_reader(self.path), write=broken, signer=self.signer,
                           profiles=EP.ErpProfileReader(transport=self.erp), clock=self.fc.now,
                           previewer=lambda h: ["캠페인1"])
        s, b, _h, p = self.call("POST", "/links/preview", self.token(0), body={"ref": ref13})
        self.assertEqual((s, b), (503, {"error": "audit-unavailable"}))
        self.assertNotIn("캠페인1".encode("utf-8"), p)


# ── 🔔 · 설정 ────────────────────────────────────────────────────────
class BellSettingsTest(WebBase):
    def test_bell_only_mine(self):
        aid = self.st.record_alert(S.ALERT_DIGEST, TODAY, "compose", "digest", (), "/naver/issues",
                                   [{"emp_idx": 100, "severity": "NORMAL", "params": {"red": 1, "yellow": 2}},
                                    {"emp_idx": 101, "severity": "NORMAL", "params": {"red": 0, "yellow": 7}}],
                                   self.fc.now())
        rs = {r["emp_idx"]: r["recipient_id"] for r in self.st.alert_recipients(aid)}
        s, b = self.get("/bell", 100)
        self.assertEqual((s, b["unread"], len(b["items"])), (200, 1, 1))
        self.assertEqual(b["items"][0]["title"], "오늘 확인할 광고주 3곳")
        self.assertEqual(self.post(f"/bell/{rs[101]}/read", 100)[0], 404)
        self.assertEqual(self.post(f"/bell/{rs[100]}/read", 100), (200, {"read": True, "changed": True}))
        self.assertEqual(self.get("/bell", 100)[1]["unread"], 0)
        self.assertEqual(self.get("/bell", 101)[1]["unread"], 1)
        self.assertEqual(self.post("/bell/read-all", 101), (200, {"changed": 1}))
        got = [(r["action"], r["result"]) for r in self.st.access_log(viewer_idx=100)]
        self.assertIn(("bell-read", "ok"), got)
        self.assertIn(("bell-read", "not-found"), got)
        self.assertEqual(self.st.access_log(viewer_idx=101)[0]["action"], "bell-read-all")

    def test_thresholds_ceo_only(self):
        s, b = self.post("/settings/thresholds", 1, {"changes": {"zero_spend_days": 4}})
        self.assertEqual((s, b["error"]), (403, "ceo-only"))
        s, b = self.post("/settings/thresholds", 0, {"changes": {"zero_spend_days": 4}})
        self.assertEqual((s, b["thresholds"]["zero_spend_days"]), (200, 4))
        s, b = self.post("/settings/thresholds", 0, {"changes": {"zero_spend_days": 99, "nope": 1}})
        self.assertEqual((s, b["error"], b["fields"]), (400, "out-of-range", ["zero_spend_days"]))
        self.assertEqual(self.post("/settings/thresholds", 0, {"changes": {"zero_spend_days": 4}})[0], 409)
        s, b = self.post("/settings/thresholds", 0, {"changes": {"zero_spend_days": 10 ** 400}})
        self.assertEqual((s, b["error"]), (400, "out-of-range"))   # 저장소 장애(503)가 아니다
        body = TA.org_body(self.fc.now() - timedelta(minutes=1))
        for e in body["employees"]:
            if e["idx"] == 0:
                e["name"] = "김대표"
        self.st.record_org(body, self.fc.now())
        _s, st = self.get("/settings", 1)
        self.assertEqual((st["thresholds"]["zero_spend_days"], st["history"][0]["by"]), (4, "대표"))   # 이름 없이
        self.assertEqual(self.get("/settings", 0)[1]["history"][0]["by"], "김대표")                  # 대표 화면만 이름

    def test_hold_confirm_ceo_only(self):
        self.assertEqual(self.post("/holds/org/confirm", 1, {"hold_id": 1})[0], 403)
        s, b = self.post("/holds/org/confirm", 0, {"hold_id": 1})
        self.assertEqual((s, b["outcome"]), (409, "refused"))   # 붙잡음 없음
        self.assertEqual(self.post("/holds/nope/confirm", 0, {"hold_id": 1})[0], 404)


# ── 12시간 안 풀린 🟡 — 한 단계 위로 ───────────────────────────────────
class EscalationTest(WebBase):
    def test_yellow_goes_up_after_twelve_hours_until_acked(self):
        _s, lead = self.get("/board", 1)
        self.assertEqual(lead["escalated_to_me"], [])
        self.at(T0 + timedelta(hours=12, minutes=1))
        _s, lead = self.get("/board", 1)
        self.assertEqual({e["possibility_id"] for e in lead["escalated_to_me"]}, {12})   # 🟡 둘(가망 12)
        self.assertEqual(self.get("/board", 101)[1]["escalated_to_me"], [])            # 담당 본인은 아님
        self.assertEqual(self.get("/board", 0)[1]["escalated_to_me"], [])              # 아직 대표 차례 아님
        self.at(T0 + timedelta(hours=24, minutes=1))
        self.assertEqual({e["possibility_id"] for e in self.get("/board", 0)[1]["escalated_to_me"]}, {12})
        for i in self.st.issues(12, open_only=True):
            self.post(f"/issues/{i['issue_id']}/ack", 101)
        self.assertEqual(self.get("/board", 0)[1]["escalated_to_me"], [])              # 👀 확인하면 멈춘다
        red = [e for e in self.get("/board", 0)[1]["escalated_to_me"] if e["possibility_id"] == 11]
        self.assertEqual(red, [])                                                       # 🔴 는 이미 모두에게

    def test_escalation_ignores_selection_but_not_scope(self):
        """나에게 올라온 일은 고르기와 상관없다 — 좁힌 팀장에게는 없다(검토 escalation-hidden-by-selection · test-gap)."""
        self.at(T0 + timedelta(hours=12, minutes=1))
        for q in ("", "selection=me", "selection=person%3A100", "selection=person%3A101"):
            got = {e["possibility_id"] for e in self.get("/board", 1, query=q)[1]["escalated_to_me"]}
            self.assertEqual(got, {12}, q)
        self.assertEqual(self.get("/board", 1, narrowed=True)[1]["escalated_to_me"], [])

    def test_expired_exception_counts_and_escalates(self):
        """기간이 끝난 예외는 🆕 로 센다 — 판의 줄 숫자·원인별 묶음·올리기가 판정과 같다(검토 expired-exception)."""
        red = self.issue_of(11, "red")["issue_id"]
        self.assertEqual(self.post(f"/issues/{red}/except", 1, {"until": TODAY.isoformat(), "note": "사유"})[0], 200)
        yellow = self.issue_of(12, "yellow")["issue_id"]
        self.assertEqual(self.post(f"/issues/{yellow}/except", 101, {"until": TODAY.isoformat(), "note": "사유"})[0], 200)
        _s, b = self.get("/board", 100, query="attention=0")
        self.assertEqual([r["open_red"] for r in b["rows"] if r["possibility_id"] == 11], [0])   # 오늘은 예외
        self.at(at(TODAY + timedelta(days=1), 7, 30))
        _s, b = self.get("/board", 100, query="attention=0")
        [row] = [r for r in b["rows"] if r["possibility_id"] == 11]
        self.assertEqual((row["verdict"]["color"], row["open_red"]), (V.RED, 1))
        self.assertIn("bizmoney_low", {g["code"] for g in b["issues"]})
        self.assertEqual(self.get("/board", 1)[1]["escalated_to_me"], [])                     # 끝난 지 12시간 전
        self.at(at(TODAY + timedelta(days=1), 12, 1))
        self.assertIn(12, {e["possibility_id"] for e in self.get("/board", 1)[1]["escalated_to_me"]})

    def test_single_tier_chain_never_escalates_to_itself(self):
        """담당 미정(대표만) 광고주의 🟡 — 사슬이 한 칸이라 올릴 곳이 없다(대표 자신의 일이 「올라온 일」로 뜨지 않는다)."""
        rid = self.st.begin_run(TODAY, self.fc.now())
        self.st.record_account_check(rid, C_, possibility_id=13, link="confirmed", status="ok",
                                     rules_run=("bizmoney", "link"), rules_not_run=(), checked_at=self.fc.now(),
                                     findings=(TA.F("bizmoney", "bizmoney_low", f"acc:{C_}", "yellow"),))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        self.at(self.fc.now() + timedelta(hours=40))
        got = {e["possibility_id"] for e in self.get("/board", 0)[1]["escalated_to_me"]}
        self.assertNotIn(13, got)
        self.assertIn(12, got)


# ── 감사 · 오류 ─────────────────────────────────────────────────────
class AuditTest(WebBase):
    def test_client_view_logged_and_required(self):
        self.assertEqual(self.get("/clients/11", 100)[0], 200)
        self.assertEqual(self.get("/clients/12", 100)[0], 404)
        rows = self.st.access_log(viewer_idx=100)
        self.assertEqual([(r["action"], r["target_id"], r["result"]) for r in rows[:2]],
                         [("view", 12, "not-visible"), ("view", 11, "ok")])

        def broken(fn):
            raise S.StoreBusy("x")
        self.app = WEB.App(open_read=lambda: S.open_reader(self.path), write=broken, signer=self.signer,
                           profiles=EP.ErpProfileReader(transport=self.erp), clock=self.fc.now)
        s, b = self.get("/clients/11", 100)
        self.assertEqual((s, b["error"]), (503, "audit-unavailable"))   # 열람 기록을 못 적으면 보여 주지 않는다

    def test_store_refusal_is_409_not_outage(self):
        """저장소가 이 값을 받지 않은 것(거절)은 저장소 장애(503)가 아니다 — 다시 시도하게 만들지 않는다(검토 client-input)."""
        def refusing(fn):
            raise S.StoreRefused("받지 않음")
        self.app = WEB.App(open_read=lambda: S.open_reader(self.path), write=refusing, signer=self.signer,
                           profiles=EP.ErpProfileReader(transport=self.erp), clock=self.fc.now)
        with self.assertLogs("naver_engine.web", level="WARNING"):
            self.assertEqual(self.post("/bell/read-all", 100), (409, {"error": "refused"}))

    def test_unserializable_response_is_json_500(self):
        class Odd(WEB.App):
            def _respond(self, environ):
                return 200, {"x": "\ud800"}
        self.app = Odd(open_read=lambda: S.open_reader(self.path), write=lambda fn: fn(self.st), signer=self.signer,
                       profiles=EP.ErpProfileReader(transport=self.erp), clock=self.fc.now)
        with self.assertLogs("naver_engine.web", level="ERROR"):
            s, b, h, _p = self.call("GET", "/me", self.token(100))
        self.assertEqual((s, b, h["Cache-Control"]), (500, {"error": "internal"}, "no-store"))

    def test_preview_ledger_thread_safe(self):
        """미리보기 장부는 여러 줄기에서 동시에 발급·사용해도 깨지지 않는다(검토 preview-handle-state-not-thread-safe)."""
        import threading
        from naver_engine import handles as HH
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        errors = []
        now = self.fc.now()

        def work(who):
            try:
                for _ in range(150):
                    h = HH.issue_preview_handle(customer_id=C_, possibility_id=13, candidate_id=1, stage="진행중",
                                                stage_as_of=now - timedelta(minutes=5), latest_end_date=None, now=now,
                                                requested_by=who)
                    HH.require_account(h, now, (HH.PURPOSE_PREVIEW,))
            except HH.NotEligible:
                pass
            except Exception as e:   # noqa: BLE001 — 깨진 것을 모은다
                errors.append(type(e).__name__)
        try:
            threads = [threading.Thread(target=work, args=(1000 + i,)) for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            sys.setswitchinterval(old)
        self.assertEqual(errors, [])

    def test_unexpected_error_is_generic(self):
        def boom():
            raise RuntimeError("비밀 " + MARK_SSO)
        self.app = WEB.App(open_read=boom, write=lambda fn: fn(self.st), signer=self.signer,
                           profiles=EP.ErpProfileReader(transport=self.erp), clock=self.fc.now)
        with self.assertLogs("naver_engine.web", level="ERROR") as cm:
            s, b, _h, p = self.call("GET", "/me", self.token(100))
        self.assertEqual((s, b), (500, {"error": "internal"}))
        self.assertNotIn(MARK_SSO, "".join(cm.output))


# ── 구문 시험 ────────────────────────────────────────────────────────
class SyntaxGuardTest(unittest.TestCase):
    SOURCES = sorted(p for p in ENGINE.glob("*.py"))

    PERSON = re.compile(r"(idx|main|sub|prev|viewer|requester|approver|person|emp|who|decided_by|changed_by)", re.I)

    def risky(self, node) -> bool:
        """사람 번호를 담은 것 같은 이름 · 칸(``x["by_person"]`` · ``x.get("emp_idx")``) · ``bool(그것)``."""
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self.risky(node.operand)
        if isinstance(node, ast.Name):
            return self.PERSON.search(node.id) is not None
        if isinstance(node, ast.Attribute):
            return self.PERSON.search(node.attr) is not None
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            return self.PERSON.search(node.slice.value) is not None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" \
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return self.PERSON.search(node.args[0].value) is not None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "bool" and node.args:
            return self.risky(node.args[0])
        return False

    def truthy_hits(self, tree):
        out = []
        for node in ast.walk(tree):
            tests = []
            if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
                tests = [node.test]
            elif isinstance(node, ast.BoolOp):
                tests = list(node.values)
            elif isinstance(node, ast.comprehension):
                tests = list(node.ifs)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("bool", "filter") \
                    and node.args:
                tests = [node.args[-1]] if node.func.id == "bool" else []
            out += [getattr(node, "lineno", "?") for t in tests if self.risky(t)]
        return out

    def test_no_truthiness_on_person_numbers(self):
        """0 = 대표 — 엔진 어디서도 사람 번호를 참거짓으로 읽지 않는다(``idx or`` · ``if not idx`` · ``if e["by_person"]`` ·
        ``bool(who)`` · §12 ⑥ · 검토 guard-truthiness)."""
        for p in self.SOURCES:
            self.assertEqual(self.truthy_hits(ast.parse(p.read_text(encoding="utf-8"))), [], p.name)

    OWNER_FIELDS = {"main", "sub", "prev", "owners_by_pid", "owners", "manage_emp_idx", "sub_manage_emp_idx",
                    "prev_manage_owner_idx", "is_manager", "is_top_manager", "members", "subtree"}

    def owner_hits(self, tree):
        """담당 칸을 속성 · 글자 getattr · 글자 칸(``asdict(own)["prev"]``) · 담당 줄 통째 풀기(asdict/vars)로 읽는 곳."""
        out = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in self.OWNER_FIELDS:
                out.append("." + n.attr)
            if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) and n.slice.value in self.OWNER_FIELDS:
                out.append(f"[{n.slice.value!r}]")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("getattr", "hasattr") \
                    and len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and n.args[1].value in self.OWNER_FIELDS:
                out.append(f"getattr(…, {n.args[1].value!r})")
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("asdict", "astuple", "vars") \
                    and n.args and isinstance(n.args[0], ast.Name) and "own" in n.args[0].id.lower():
                out.append(f"{n.func.id}({n.args[0].id})")
        return out

    def test_screen_modules_do_not_read_owner_fields(self):
        """누가 보는지는 scope.py 한 곳 — 화면 모듈은 담당 칸(메인·서브·직전)·담당 줄을 직접 읽지 않는다(§12 ⑤)."""
        for name in ("views.py", "web.py"):
            self.assertEqual(self.owner_hits(ast.parse((ENGINE / name).read_text(encoding="utf-8"))), [], name)

    def test_guard_catches_sabotage_shapes(self):
        for src in ("def f(idx):\n    return idx or 0\n", "def f(viewer_idx):\n    if not viewer_idx:\n        pass\n",
                    'def f(e):\n    return 1 if e["by_person"] else None\n',
                    'def f(e):\n    if e.get("emp_idx"):\n        pass\n',
                    'def f(claims):\n    who = claims.emp_idx\n    return bool(who)\n',
                    'def f(x):\n    if not x["decided_by"]:\n        pass\n'):
            self.assertTrue(self.truthy_hits(ast.parse(src)), src)
        for src in ('def f(own):\n    return own.main\n', 'def f(own):\n    return getattr(own, "main")\n',
                    'from dataclasses import asdict\ndef f(own):\n    return asdict(own)["prev"]\n',
                    'def f(own):\n    return vars(own)\n'):
            self.assertTrue(self.owner_hits(ast.parse(src)), src)


if __name__ == "__main__":
    unittest.main()
