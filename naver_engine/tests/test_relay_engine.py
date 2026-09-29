"""S12 이어 붙이기 시험 — ③ 중계 핵심(``backend/app/naver_relay.py``) → **진짜 엔진 화면 API**(``web.App``).

엔진을 표준 라이브러리 WSGI 서버로 127.0.0.1 에 띄우고(시험이 만든 포트 · 네트워크 0) 중계를 거쳐 부른다.
- 중계가 채운 「요청한 곳」이 엔진의 한 곳마다 로그인 제한에 **실제로** 쓰인다(엔진이 루프백에서 온 머리를 믿는다).
- ③ 로그인 토큰 모양은 엔진까지 가지 않는다 → 엔진은 「토큰 없음」 401.
- 중계를 거친 답 = 엔진을 바로 부른 답(글자 하나까지).
엔진은 시험 스레드에서 돌린다(저장소 연결이 이 스레드 것) — 중계 호출만 옆 스레드.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import socketserver
import tempfile
import threading
import unittest
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from naver_engine.tests import test_web as TW   # backend 경로를 sys.path 에 넣는다 — 먼저 불러야 한다
from naver_engine import web as WEB  # noqa: E402

from app import naver_relay as R  # noqa: E402

ERP3_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLW1hcmtlci14eXo"


class _Quiet(WSGIRequestHandler):
    def log_message(self, *a):
        pass


class _UnixWSGIServer(WSGIServer):
    """S14 가 쓸 모양 — 유닉스 소켓으로 받는 WSGI 서버. ``mark`` 가 참이면 environ 에 믿음 표지를 넣는다."""
    address_family = socket.AF_UNIX
    mark = False

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "naver-engine", 0
        self.setup_environ()


class _UnixHandler(_Quiet):
    def setup(self):
        super().setup()
        self.client_address = ("", 0)                 # 유닉스 소켓에는 IP 가 없다

    def get_environ(self):
        env = super().get_environ()
        env["REMOTE_ADDR"] = ""
        if self.server.mark:
            env[WEB.TRUSTED_TRANSPORT] = True
        return env


class RelayToEngineTest(TW.WebBase):
    def setUp(self):
        super().setUp()
        self.server = make_server("127.0.0.1", 0, lambda env, sr: self.app(env, sr),
                                  server_class=WSGIServer, handler_class=_Quiet)
        self.server.timeout = 5                          # 중계가 엔진을 안 부르면 기다리지 않고 돌아온다(시험이 멈추지 않게)
        self.addCleanup(self.server.server_close)
        self.env = {R.ENV_SWITCH: "on", R.ENV_ENGINE: f"127.0.0.1:{self.server.server_address[1]}"}

    def via(self, inc: R.Incoming) -> R.Outgoing:
        """중계 호출은 옆 스레드 · 엔진은 이 스레드에서 요청 하나를 받는다."""
        box = {}
        t = threading.Thread(target=lambda: box.setdefault("out", R.relay(inc, self.env, total_timeout=10)))
        t.start()
        self.server.handle_request()
        t.join(10)
        self.assertFalse(t.is_alive())
        return box["out"]

    def inc(self, method="GET", sub="/me", token=None, body=None, real_ip="203.0.113.1", auth=None):
        a = auth if auth is not None else (("Bearer " + token,) if token else ())
        return R.Incoming(method=method, sub=sub, authorization=a,
                          content_type="application/json" if body is not None else None,
                          body=None if body is None else json.dumps(body).encode("utf-8"),
                          real_ip=real_ip, peer="172.17.0.1", host="d.example", fetch_site="same-origin")

    def unix(self, mark: bool):
        tmp = tempfile.mkdtemp(prefix="relay-e2e-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "engine.sock")
        srv = _UnixWSGIServer(path, _UnixHandler)
        srv.mark = mark
        srv.set_app(lambda env, sr: self.app(env, sr))
        srv.timeout = 5
        self.addCleanup(srv.server_close)
        self.server, self.env = srv, {R.ENV_SWITCH: "on", R.ENV_ENGINE: "unix:" + path}

    def logins(self, source, n, sso=TW.BAD_SSO):
        return [self.via(self.inc("POST", "/session", body={"sso": sso}, real_ip=source)).status for _ in range(n)]

    def test_unix_socket_with_mark_counts_each_source(self):
        """유닉스 소켓(S14 권장) — 서버가 믿음 표지를 넣으면 중계가 넘긴 요청한 곳마다 따로 센다(검토 unix-source-collapse)."""
        self.app = self.make_app(login_max=20, login_source_max=2, monotonic=lambda: 100.0)
        self.unix(mark=True)
        self.assertEqual(self.logins("203.0.113.10", 3), [401, 401, 429])
        self.assertEqual(self.logins("203.0.113.20", 2), [401, 401])      # 다른 곳은 따로
        self.erp.person(TW.MARK_SSO, 100)
        self.assertEqual(self.logins("203.0.113.30", 5, sso=TW.MARK_SSO), [200] * 5)   # ① 이 받아 준 로그인은 한 곳 상한 밖

    def test_unix_socket_without_mark_collapses(self):
        """표지 없는 유닉스 서버 = 모두 한 곳 — S14 가 표지를 빠뜨리면 이렇게 된다는 것을 고정(표지가 왜 필요한지)."""
        self.app = self.make_app(login_max=20, login_source_max=2, monotonic=lambda: 100.0)
        self.unix(mark=False)
        self.assertEqual(self.logins("203.0.113.10", 2), [401, 401])
        self.assertEqual(self.logins("203.0.113.20", 1), [429])

    def test_same_answer_as_direct(self):
        tok = self.token(0)
        out = self.via(self.inc(sub="/board", token=tok))
        s, _b, _h, payload = self.call("GET", "/board", tok)
        self.assertEqual((out.status, out.body), (s, payload))
        self.assertEqual(out.status, 200)

    def test_erp3_token_does_not_reach_engine(self):
        out = self.via(self.inc(auth=("Bearer " + ERP3_JWT,)))
        self.assertEqual((out.status, json.loads(out.body)), (401, {"error": "token-missing"}))

    def test_login_limit_counts_per_source_given_by_relay(self):
        """엔진은 중계(루프백)가 넘긴 요청한 곳을 믿는다 — 한 곳이 ① 이 거절할 토큰을 몰아쳐도 다른 곳 로그인은 된다."""
        self.app = self.make_app(login_max=10, login_source_max=2, monotonic=lambda: 100.0)
        self.erp.person(TW.MARK_SSO, 100)
        self.assertEqual(self.logins("203.0.113.10", 3), [401, 401, 429])
        self.assertEqual(self.logins("203.0.113.20", 1), [401])
        self.assertEqual(self.logins("203.0.113.20", 1, sso=TW.MARK_SSO), [200])

    def test_login_then_board_through_relay(self):
        self.erp.person(TW.MARK_SSO, 100)
        out = self.via(self.inc("POST", "/session", body={"sso": TW.MARK_SSO}))
        self.assertEqual(out.status, 200)
        tok = json.loads(out.body)["token"]
        self.assertTrue(tok.startswith("v1."))
        board = self.via(self.inc(sub="/board", token=tok))
        self.assertEqual(board.status, 200)
        self.assertIn("counts", json.loads(board.body))
        self.assertNotIn(TW.MARK_SSO, out.body.decode("utf-8") + board.body.decode("utf-8"))

    def test_body_limit_matches_engine(self):
        self.assertEqual(R.BODY_MAX, WEB.BODY_MAX)
        self.assertEqual(R.QUERY_MAX, WEB.QUERY_MAX)
        self.assertEqual(R.SOURCE_HEADER.upper().replace("-", "_"), WEB.SOURCE_HEADER[len("HTTP_"):])
        self.assertEqual(dict(R.RESPONSE_HEADERS), dict(WEB.HEADERS))
        # 엔진 경로는 모두 중계 경로 모양 안에 든다(중계가 막는 엔진 경로 0)
        import re
        for route in WEB.ROUTES:
            sample = re.sub(r"\(\?P<\w+>[^)]*\)", "12", route.pattern.pattern).replace("org|stages|accounts", "org")
            self.assertTrue(R._SUB.fullmatch(sample), sample)
        self.assertEqual({r.method for r in WEB.ROUTES}, {"GET", "POST"})


if __name__ == "__main__":
    unittest.main()
