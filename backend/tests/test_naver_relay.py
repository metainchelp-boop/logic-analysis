"""S12 시험 — ③ → 관제 엔진 중계 핵심(``app/naver_relay.py``) · 표준 라이브러리만(fastapi 없이 돈다).

가짜 엔진(루프백 TCP · 유닉스 소켓)을 띄워 **엔진이 실제로 받은 것**을 본다 — 머리 허용 목록 · 요청한 곳 ·
③ 토큰 막기 · 다른 곳 막기 · 64KB · 엔진 답 검사 · 주소 설정(루프백·소켓만) · 화면 파일 · 기록에 값 0 · 구문 시험.
네트워크 0(127.0.0.1 · 이 시험이 만든 소켓 파일만). 예시 값은 모두 지어낸 것이다.
돌리는 법(backend 폴더에서): python3 -m unittest -v tests.test_naver_relay
"""
from __future__ import annotations

import ast
import http.server
import io
import json
import logging
import os
import pathlib
import shutil
import socket
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import naver_relay as R  # noqa: E402

RELAY_SRC = BACKEND / "app" / "naver_relay.py"
ROUTER_SRC = BACKEND / "app" / "routers" / "naver.py"
MAIN_SRC = BACKEND / "app" / "main.py"

ENGINE_TOKEN = "v1.eyJzdWIiOjB9TUFSS0VSVE9LRU4." + "S" * 43            # 엔진 토큰 모양(서명 43자)
ERP3_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJlLW1hcmtlci14eXo"   # ③ 로그인 토큰 모양
MARK_IP = "203.0.113.77"
MARK_BODY = "BODYMARKER-9d1c"
MARK_QUERY = "QMARK7"
HOST = "dashboard.example.test"


# ── 가짜 엔진 ─────────────────────────────────────────────────────────
class Engine:
    """받은 요청을 적고, 정해 둔 답을 돌려준다."""

    def __init__(self):
        self.got = []
        self.status = 200
        self.ctype = "application/json; charset=utf-8"
        self.body = b'{"ok":true}'
        self.extra = [("Set-Cookie", "engine=1"), ("X-Engine-Secret", "leak")]
        self.delay = 0.0
        self.cut = False       # 길이만 말하고 끊기

    def handler(self):
        eng = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _any(self):
                n = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(n) if n else b""
                eng.got.append({"method": self.command, "path": self.path,
                                "headers": [(k.lower(), v) for k, v in self.headers.items()], "body": data})
                if eng.delay:
                    time.sleep(eng.delay)
                self.send_response(eng.status)
                self.send_header("Content-Type", eng.ctype)
                for k, v in eng.extra:
                    self.send_header(k, v)
                if eng.cut:
                    self.send_header("Content-Length", str(len(eng.body) + 1000))
                    self.end_headers()
                    self.wfile.write(eng.body)
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.send_header("Content-Length", str(len(eng.body)))
                self.end_headers()
                self.wfile.write(eng.body)

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _any

        return H


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def handle_error(self, request, client_address):   # 중계가 먼저 끊은 연결 — 시험 출력만 어지럽힌다
        pass


class _TcpHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="relay-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.eng = Engine()
        self.tcp = _TcpHTTPServer(("127.0.0.1", 0), self.eng.handler())
        self.sock = os.path.join(self.tmp, "engine.sock")
        self.unix = _UnixHTTPServer(self.sock, self.eng.handler())
        for srv in (self.tcp, self.unix):
            t = threading.Thread(target=srv.serve_forever, daemon=True)
            t.start()
            self.addCleanup(srv.server_close)
            self.addCleanup(srv.shutdown)
        self.env_tcp = {R.ENV_SWITCH: "on", R.ENV_ENGINE: f"127.0.0.1:{self.tcp.server_address[1]}"}
        self.env_unix = {R.ENV_SWITCH: "on", R.ENV_ENGINE: "unix:" + self.sock}
        R._last_warn.clear()
        lg = logging.getLogger("naver_relay")
        nh = logging.NullHandler()
        lg.addHandler(nh)
        self.addCleanup(lg.removeHandler, nh)

    def inc(self, **kw):
        base = dict(method="GET", sub="/board", query="", authorization=("Bearer " + ENGINE_TOKEN,),
                    content_type=None, body=None, real_ip=MARK_IP, peer="172.17.0.1",
                    origin=None, host=HOST, fetch_site="same-origin")
        base.update(kw)
        return R.Incoming(**base)

    def headers(self, i=-1):
        return dict(self.eng.got[i]["headers"])


class ConfigTest(unittest.TestCase):
    def test_switch_on_only_exact(self):
        self.assertTrue(R.enabled({R.ENV_SWITCH: "on"}))
        for v in ("", "ON", "1", "true", "on ", "yes", "off"):
            self.assertFalse(R.enabled({R.ENV_SWITCH: v}), v)
        self.assertFalse(R.enabled({}))

    def test_engine_address_loopback_or_socket_only(self):
        self.assertEqual(R.engine_target({R.ENV_ENGINE: "127.0.0.1:5090"}), R.Target("tcp", host="127.0.0.1", port=5090))
        self.assertEqual(R.engine_target({R.ENV_ENGINE: "[::1]:5090"}), R.Target("tcp", host="::1", port=5090))
        self.assertEqual(R.engine_target({R.ENV_ENGINE: "unix:/run/naver/engine.sock"}),
                         R.Target("unix", path="/run/naver/engine.sock"))
        for bad in ("", "5090", "localhost:5090", "0.0.0.0:5090", "127.0.0.2:5090", "10.0.0.1:5090",
                    "1.234.23.117:80", "[::]:5090", "[::2]:1", "127.0.0.1:0", "127.0.0.1:70000", "127.0.0.1:",
                    "http://127.0.0.1:5090", "127.0.0.1:5090/x", " 127.0.0.1:5090", "127.0.0.1:5090\n",
                    "unix:relative.sock", "unix:/run/../etc/x.sock", "unix:/run//x.sock", "unix:/run/./x.sock",
                    "unix:/a b.sock", "unix:/" + "a" * 120, "unix:", "file:/run/x.sock", "127.0.0.1:5090,10.0.0.1:1"):
            self.assertIsNone(R.engine_target({R.ENV_ENGINE: bad}), bad)
        self.assertIsNone(R.engine_target({}))

    def test_open_refuses_unchecked_target(self):
        """연결 만들기도 루프백·소켓 말고는 거절한다(설정 검사를 건너뛴 Target 이 와도)."""
        for t in (R.Target("tcp", host="10.0.0.1", port=80), R.Target("tcp", host="localhost", port=80),
                  R.Target("tcp", host="0.0.0.0", port=80), R.Target("http", host="127.0.0.1", port=80)):
            with self.assertRaises(ValueError):
                R._open(t, 1.0)


class ForwardTest(EngineCase):
    def test_get_forwarded_over_tcp_and_unix(self):
        for env in (self.env_tcp, self.env_unix):
            out = R.relay(self.inc(query="attention=0&" + MARK_QUERY + "=1"), env)
            self.assertEqual((out.status, out.body), (200, b'{"ok":true}'))
            g = self.eng.got[-1]
            self.assertEqual((g["method"], g["path"]), ("GET", "/api/naver-auto/board?attention=0&QMARK7=1"))
        self.assertEqual(len(self.eng.got), 2)

    def test_only_allowed_headers_reach_engine(self):
        R.relay(self.inc(method="POST", sub="/links/confirm", content_type="application/json; charset=utf-8",
                         body=b'{"ids":[1]}'), self.env_unix)
        h = self.headers()
        self.assertEqual(set(h), {"host", "accept", "connection", "content-type", "content-length",
                                  "authorization", "x-naver-auto-source"})
        self.assertEqual((h["host"], h["content-type"], h["content-length"], h["x-naver-auto-source"]),
                         (R.ENGINE_HOST_HEADER, "application/json", "11", MARK_IP))
        self.assertEqual(h["authorization"], "Bearer " + ENGINE_TOKEN)
        self.assertEqual(self.eng.got[-1]["body"], b'{"ids":[1]}')

    def test_erp3_token_and_other_auth_never_forwarded(self):
        for auth in ("Bearer " + ERP3_JWT, "Basic YWRtaW46YWRtaW4=", "Bearer v1.x.short", "Bearer " + ENGINE_TOKEN + " extra",
                     ENGINE_TOKEN, "", "Bearer" + ENGINE_TOKEN, "Bearer\t" + ENGINE_TOKEN, "Bearer " + ENGINE_TOKEN + "\n",
                     "Bearer v2." + ENGINE_TOKEN[3:], "Token " + ENGINE_TOKEN):
            R.relay(self.inc(authorization=(auth,)), self.env_tcp)
            self.assertNotIn("authorization", self.headers(), auth)
        R.relay(self.inc(authorization=()), self.env_tcp)
        self.assertNotIn("authorization", self.headers())

    def test_engine_token_spelling_normalized(self):
        """엔진이 받는 모양(bearer 대소문자 · 사이 빈칸 · 끝 빈칸)은 받아 「Bearer 토큰」 한 모양으로 넘긴다(검토 bearer-shape)."""
        for auth in ("bearer " + ENGINE_TOKEN, "BEARER  " + ENGINE_TOKEN, "Bearer " + ENGINE_TOKEN + "  ",
                     "bEaReR " + ENGINE_TOKEN):
            R.relay(self.inc(authorization=(auth,)), self.env_tcp)
            self.assertEqual(self.headers()["authorization"], "Bearer " + ENGINE_TOKEN, auth)

    def test_two_authorization_values_refused_before_engine(self):
        out = R.relay(self.inc(authorization=("Bearer " + ENGINE_TOKEN, "Bearer " + ENGINE_TOKEN)), self.env_tcp)
        self.assertEqual((out.status, json.loads(out.body)), (400, {"error": "bad-authorization"}))
        self.assertEqual(self.eng.got, [])

    def test_source_is_real_ip_then_peer(self):
        R.relay(self.inc(real_ip=MARK_IP, peer="172.17.0.1"), self.env_tcp)
        self.assertEqual(self.headers()["x-naver-auto-source"], MARK_IP)
        for bad in ("evil<script>", "1.2.3.4, 5.6.7.8", "a" * 65, "", " 1.2.3.4"):
            R.relay(self.inc(real_ip=bad, peer="172.17.0.9"), self.env_tcp)
            self.assertEqual(self.headers()["x-naver-auto-source"], "172.17.0.9", bad)
        R.relay(self.inc(real_ip=None, peer=None), self.env_tcp)
        self.assertNotIn("x-naver-auto-source", self.headers())
        R.relay(self.inc(real_ip="bad!", peer="also bad"), self.env_tcp)
        self.assertNotIn("x-naver-auto-source", self.headers())
        R.relay(self.inc(real_ip="1.2.3", peer="172.17.0.4"), self.env_tcp)     # 글자 모양은 맞지만 주소가 아님
        self.assertEqual(self.headers()["x-naver-auto-source"], "172.17.0.4")
        for zoned in ("::1%eth0", "fe80::1%25x"):                                  # 주소 풀이는 받아도 글자 모양이 막는다(겹)
            R.relay(self.inc(real_ip=zoned, peer="172.17.0.5"), self.env_tcp)
            self.assertEqual(self.headers()["x-naver-auto-source"], "172.17.0.5", zoned)

    def test_source_groups_ipv6_by_64(self):
        """IPv6 는 /64 대역 하나로 — 한 사람이 제 대역 안에서 주소를 바꿔도 엔진에는 같은 곳(S12 2차 검토 ipv6-rotation)."""
        for real, want in (("2001:db8:1:2:aaaa::1", "2001:db8:1:2::"), ("2001:DB8:1:2:ffff:ffff:ffff:ffff", "2001:db8:1:2::"),
                           ("2001:db8:1:3::1", "2001:db8:1:3::"), ("::ffff:203.0.113.5", "203.0.113.5"),
                           ("::1", "::1"), ("203.0.113.5", "203.0.113.5")):
            R.relay(self.inc(real_ip=real), self.env_tcp)
            self.assertEqual(self.headers()["x-naver-auto-source"], want, real)

    def test_get_body_not_forwarded(self):
        R.relay(self.inc(body=b'{"x":1}', content_type="application/json"), self.env_tcp)
        self.assertEqual(self.eng.got[-1]["body"], b"")
        self.assertNotIn("content-type", self.headers())

    def test_empty_post_has_zero_length(self):
        R.relay(self.inc(method="POST", sub="/bell/read-all", body=None), self.env_tcp)
        h = self.headers()
        self.assertEqual((h.get("content-length"), "content-type" in h), ("0", False))

    def test_engine_answer_passed_but_engine_headers_dropped(self):
        self.eng.body = json.dumps({"rows": ["가", "나"]}, ensure_ascii=False).encode("utf-8")
        for st in (200, 400, 401, 403, 404, 409, 429, 503):
            self.eng.status = st
            out = R.relay(self.inc(), self.env_tcp)
            self.assertEqual((out.status, out.body), (st, self.eng.body))
            self.assertEqual(out.headers, R.RESPONSE_HEADERS)
            self.assertNotIn("Set-Cookie", dict(out.headers))


class RefuseBeforeEngineTest(EngineCase):
    """이 거절들은 엔진에 닿기 전에 끝난다 — 가짜 엔진이 받은 것이 0."""

    def assertRefused(self, inc, status, code, env=None):
        out = R.relay(inc, env or self.env_tcp)
        self.assertEqual((out.status, json.loads(out.body)), (status, {"error": code}), inc)
        self.assertEqual(out.headers, R.RESPONSE_HEADERS)
        self.assertEqual(self.eng.got, [], inc)

    def test_switch_off(self):
        for env in ({R.ENV_ENGINE: self.env_tcp[R.ENV_ENGINE]}, {**self.env_tcp, R.ENV_SWITCH: "ON"}):
            with self.assertRaises(R.RelayOff):
                R.relay(self.inc(), env)
        self.assertEqual(self.eng.got, [])

    def test_cross_origin(self):
        for o, fs in (("https://evil.example", "cross-site"), ("https://evil.example", None),
                      ("https://logic.metainc.co.kr", "same-site"), (None, "same-site"), (None, "cross-site"),
                      ("null", None), ("https://" + HOST + ".evil.example", None), ("evil", None),
                      ("https://" + HOST, "cross-site"), (None, "weird")):
            self.assertRefused(self.inc(origin=o, fetch_site=fs), 403, "cross-origin")
        self.assertRefused(self.inc(origin="https://" + HOST, host=None, fetch_site=None), 403, "cross-origin")

    def test_same_host_other_port_refused(self):
        """같은 호스트라도 포트가 다르면 다른 곳(같은 서버의 0.0.0.0:5070 자동입찰 화면 같은 것) — Sec-Fetch-Site 를 안 보내는
        클라이언트도 Origin 겹이 막는다(2차 검토 origin-port). 기본 포트(80·443)는 없는 것과 같다."""
        for o, host in (("http://" + HOST + ":5070", HOST), ("https://" + HOST + ":8443", HOST),
                        ("http://" + HOST, HOST + ":5051"), ("http://" + HOST + ":443", HOST),
                        ("http://[::1]:5070", "[::1]:5051")):
            self.assertRefused(self.inc(origin=o, host=host, fetch_site=None), 403, "cross-origin")
        for o, host in (("https://" + HOST + ":443", HOST), ("http://" + HOST, HOST + ":80"),
                        ("http://" + HOST + ":80", HOST + ":443")):
            self.assertEqual(R.relay(self.inc(origin=o, host=host, fetch_site=None), self.env_tcp).status, 200, (o, host))

    def test_same_origin_passes(self):
        for o, host, fs in (("https://" + HOST, HOST, "same-origin"), ("http://" + HOST + ":5051", HOST + ":5051", None),
                            (None, HOST, "none"), (None, None, None), ("HTTPS://" + HOST.upper(), HOST, "Same-Origin"),
                            ("http://[::1]:5051", "[::1]:5051", None)):
            out = R.relay(self.inc(origin=o, host=host, fetch_site=fs), self.env_tcp)
            self.assertEqual(out.status, 200, (o, host, fs))

    def test_methods(self):
        for m in ("PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "get", "TRACE"):
            self.assertRefused(self.inc(method=m), 405, "method-not-allowed")

    def test_paths(self):
        for sub in ("", "/", "/../x", "/board/..", "/board.json", "/a b", "/%2e%2e", "board", "/board/",
                    "//board", "/a/b/c/d/e/f/g", "/" + "a" * 65, "/bo\nard", "/보드", "/board?x=1"):
            self.assertRefused(self.inc(sub=sub), 404, "not-found")

    def test_query(self):
        for q in ("a b=1", "x=\n", "q=가", "q=" + "a" * R.QUERY_MAX, "\x7f"):
            self.assertRefused(self.inc(query=q), 400, "bad-query")

    def test_body(self):
        self.assertRefused(self.inc(method="POST", sub="/session", content_type="application/json",
                                    body=b"x" * (R.BODY_MAX + 1)), 413, "too-large")
        for ct in (None, "text/plain", "application/json-seq", "multipart/form-data", "application/x-www-form-urlencoded"):
            self.assertRefused(self.inc(method="POST", sub="/session", content_type=ct, body=b'{"sso":"x"}'),
                               415, "json-only")

    def test_limit_exactly_64kb_passes(self):
        body = b'"' + b"a" * (R.BODY_MAX - 2) + b'"'
        out = R.relay(self.inc(method="POST", sub="/session", content_type="application/json", body=body), self.env_tcp)
        self.assertEqual(out.status, 200)
        self.assertEqual(len(self.eng.got[-1]["body"]), R.BODY_MAX)

    def test_loop_to_itself(self):
        """엔진 주소를 ③ 자기 자신으로 잘못 넣으면 중계가 넣은 Host(naver-engine)가 루프백 연결로 · nginx 머리 없이
        되돌아온다 — 바로 503(검토 self-loop)."""
        for host in (R.ENGINE_HOST_HEADER, "Naver-Engine", R.ENGINE_HOST_HEADER + ":5051"):
            for peer in ("127.0.0.1", "::1"):
                self.assertRefused(self.inc(host=host, origin=None, fetch_site=None, real_ip=None, peer=peer),
                                   503, "engine-misconfigured")

    def test_outside_host_is_not_a_loop(self):
        """밖에서 Host 만 흉내 내면(nginx 를 지나 X-Real-IP 가 붙거나 · 루프백이 아닌 연결) 되돌이가 아니다 — 거짓 경보 0
        (S12 2차 검토 host-loop-false-alarm)."""
        with self.assertNoLogs("naver_relay", level="WARNING"):
            for kw in (dict(real_ip=MARK_IP, peer="127.0.0.1"), dict(real_ip=None, peer="172.17.0.1"),
                       dict(real_ip=MARK_IP, peer="172.17.0.1")):
                out = R.relay(self.inc(host=R.ENGINE_HOST_HEADER, fetch_site=None, **kw), self.env_tcp)
                self.assertEqual(out.status, 200, kw)

    def test_not_configured(self):
        for env in ({R.ENV_SWITCH: "on"}, {R.ENV_SWITCH: "on", R.ENV_ENGINE: "10.0.0.1:80"}):
            self.assertRefused(self.inc(), 503, "engine-unavailable", env)


class EngineAnswerTest(EngineCase):
    def test_bad_status_or_type(self):
        for st, ct in ((302, "application/json"), (201, "application/json"), (418, "application/json"),
                       (200, "text/html"), (200, "application/javascript"), (500, "text/plain"), (204, "application/json")):
            self.eng.status, self.eng.ctype = st, ct
            if st == 204:
                self.eng.body = b""
            out = R.relay(self.inc(), self.env_tcp)
            self.assertEqual((out.status, json.loads(out.body)), (502, {"error": "bad-gateway"}), (st, ct))

    def test_answer_without_length_refused(self):
        """길이 없는 답(조각 전송 · 끊길 때까지) · 길이와 조각 전송을 함께 말한 답은 잘렸는지 알 수 없다 — 받지 않는다
        (2차 검토 te-layer — 길이를 말한 조각 전송은 Transfer-Encoding 겹 하나만 막는다)."""
        served = []

        class Chunked(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_GET(self):
                served.append("chunked")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"b\r\n{\"ok\":true}\r\n0\r\n\r\n")

        class LenAndChunked(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            short = False

            def log_message(self, *a):
                pass

            def do_GET(self):
                served.append("len+chunked")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", "11" if self.short else "5")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                self.wfile.write(b"1a\r\n{\"ok\":true,\"more\":\"xxxxx\"}\r\n0\r\n\r\n")

        class LenAndChunkedShort(LenAndChunked):
            short = True

        class NoLen(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def do_GET(self):
                served.append("nolen")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

        for h in (Chunked, NoLen, LenAndChunked, LenAndChunkedShort):
            srv = _TcpHTTPServer(("127.0.0.1", 0), h)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                out = R.relay(self.inc(), {R.ENV_SWITCH: "on", R.ENV_ENGINE: f"127.0.0.1:{srv.server_address[1]}"})
                self.assertEqual((out.status, json.loads(out.body)), (502, {"error": "bad-gateway"}), h.__name__)
            finally:
                srv.shutdown()
                srv.server_close()
        self.assertEqual(sorted(served), ["chunked", "len+chunked", "len+chunked", "nolen"])   # 네 곳 모두 실제로 답했다

    def test_too_large_answer(self):
        old = R.RESPONSE_MAX
        R.RESPONSE_MAX = 1000
        try:
            self.eng.body = b'"' + b"a" * 1000 + b'"'
            self.assertEqual(R.relay(self.inc(), self.env_tcp).status, 502)
            self.eng.body = b'"' + b"a" * 998 + b'"'
            self.assertEqual(R.relay(self.inc(), self.env_tcp).status, 200)
        finally:
            R.RESPONSE_MAX = old

    def test_engine_down(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        for env in ({R.ENV_SWITCH: "on", R.ENV_ENGINE: f"127.0.0.1:{port}"},
                    {R.ENV_SWITCH: "on", R.ENV_ENGINE: "unix:" + os.path.join(self.tmp, "none.sock")}):
            out = R.relay(self.inc(), env)
            self.assertEqual((out.status, json.loads(out.body)), (503, {"error": "engine-unavailable"}))

    def test_engine_cut_mid_answer(self):
        self.eng.cut = True
        out = R.relay(self.inc(), self.env_unix)
        self.assertEqual(out.status, 503)

    def test_slow_engine_times_out(self):
        self.eng.delay = 1.0
        t = time.monotonic()
        out = R.relay(self.inc(), self.env_unix, total_timeout=0.3)
        self.assertEqual((out.status, json.loads(out.body)), (504, {"error": "engine-timeout"}))
        self.assertLess(time.monotonic() - t, 0.9)


class InflightTest(EngineCase):
    """M7 — 엔진이 느릴 때 한 워커에서 엔진을 기다리는 요청은 MAX_INFLIGHT 까지만 · 넘치면 기다리지 않고 바로 503."""

    def test_extra_requests_answer_at_once(self):
        self.eng.delay = 1.0
        n = R.MAX_INFLIGHT + 4
        outs, lock = [], threading.Lock()

        def one():
            t = time.monotonic()
            o = R.relay(self.inc(), self.env_unix)
            with lock:
                outs.append((o.status, json.loads(o.body) if o.status != 200 else None, time.monotonic() - t))
        ts = [threading.Thread(target=one) for _ in range(n)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(10)
        busy = [o for o in outs if o[0] == 503]
        self.assertEqual(len(busy), 4)
        self.assertTrue(all(o[1] == {"error": "relay-busy"} and o[2] < 0.5 for o in busy), busy)
        self.assertEqual(sorted(o[0] for o in outs if o[0] != 503), [200] * R.MAX_INFLIGHT)
        self.assertEqual(len(self.eng.got), R.MAX_INFLIGHT)
        self.eng.delay = 0
        self.assertEqual(R.relay(self.inc(), self.env_unix).status, 200)     # 자리는 모두 돌아왔다
        self.assertEqual(R._slots._value, R.MAX_INFLIGHT)

    def test_slot_returned_on_every_failure(self):
        for env in ({R.ENV_SWITCH: "on", R.ENV_ENGINE: "127.0.0.1:1"}, self.env_unix):
            self.eng.status = 302
            for _ in range(R.MAX_INFLIGHT + 2):
                R.relay(self.inc(), env)
        self.eng.cut = True
        for _ in range(R.MAX_INFLIGHT + 2):
            R.relay(self.inc(), self.env_unix)
        self.assertEqual(R._slots._value, R.MAX_INFLIGHT)


class LogTest(EngineCase):
    """기록에는 종류 이름만 — 토큰·본문·주소·쿼리 0 · 1분에 한 줄."""

    def test_no_values_in_logs(self):
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        lg = logging.getLogger("naver_relay")
        lg.addHandler(h)
        lg.setLevel(logging.DEBUG)
        self.addCleanup(lg.removeHandler, h)
        body = json.dumps({"sso": MARK_BODY}).encode()
        scenarios = [({R.ENV_SWITCH: "on"}, {}), ({R.ENV_SWITCH: "on", R.ENV_ENGINE: "127.0.0.1:1"}, {}),
                     (self.env_unix, {"cut": True}), (self.env_unix, {"status": 302}), (self.env_unix, {"delay": 0.5})]
        for env, eng in scenarios:
            self.eng.cut, self.eng.status, self.eng.delay = eng.get("cut", False), eng.get("status", 200), eng.get("delay", 0)
            R._last_warn.clear()
            R.relay(self.inc(method="POST", sub="/session", content_type="application/json", body=body,
                             query=MARK_QUERY + "=1"), env, total_timeout=0.2)
        # 연결 시간 제한(대기열이 찬 채 풀리지 않음) — 「socket.timeout」 갈래도 지난다
        full = os.path.join(self.tmp, "full.sock")
        lst = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        lst.bind(full)
        lst.listen(0)
        self.addCleanup(lst.close)
        fill = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        fill.connect(full)
        self.addCleanup(fill.close)
        R._last_warn.clear()
        out = R.relay(self.inc(method="POST", sub="/session", content_type="application/json", body=body,
                               query=MARK_QUERY + "=1"), {R.ENV_SWITCH: "on", R.ENV_ENGINE: "unix:" + full},
                      total_timeout=0.3)
        self.assertEqual(out.status, 504)
        text = buf.getvalue()
        self.assertTrue(text)
        self.assertIn("engine-timeout", text)
        for mark in (MARK_BODY, MARK_IP, MARK_QUERY, "TUFSS0VSVE9LRU4", ENGINE_TOKEN, "172.17.0.1", self.sock):
            self.assertNotIn(mark, text)

    def test_every_branch_carries_no_values(self):
        """_warn 을 부르는 갈래를 표지 값을 실은 요청으로 하나씩 지난다 — 기록에 토큰·본문·주소·쿼리·경로가 없다
        (2차 검토 log-leak-untested-branches · 구문 시험 test_warn_kinds_are_fixed_words 와 겹)."""
        buf = io.StringIO()
        h = logging.StreamHandler(buf)
        lg = logging.getLogger("naver_relay")
        lg.addHandler(h)
        lg.setLevel(logging.DEBUG)
        self.addCleanup(lg.removeHandler, h)
        body = json.dumps({"sso": MARK_BODY}).encode()

        def marked(**kw):
            base = dict(method="POST", sub="/session", content_type="application/json", body=body, query=MARK_QUERY + "=1")
            base.update(kw)
            return self.inc(**base)
        kinds = []

        def run(inc, env, **kw):
            R._last_warn.clear()
            before = buf.getvalue()
            R.relay(inc, env, **kw)
            kinds.append(buf.getvalue()[len(before):].strip())
        run(marked(host=R.ENGINE_HOST_HEADER, peer="127.0.0.1", real_ip=None, fetch_site=None), self.env_tcp)   # 되돌이
        taken = 0
        while R._slots.acquire(blocking=False):                   # 자리 다 참
            taken += 1
        try:
            run(marked(), self.env_unix)
        finally:
            for _ in range(taken):
                R._slots.release()
        old = R.RESPONSE_MAX
        R.RESPONSE_MAX = 5
        try:
            run(marked(), self.env_unix)                          # 답 너무 큼
        finally:
            R.RESPONSE_MAX = old
        self.eng.cut = True
        run(marked(), self.env_unix)                              # 끊김
        self.eng.cut = False

        class NoThread(threading.Timer):
            def start(self):
                raise RuntimeError("no")
        with mock.patch.object(R.threading, "Timer", NoThread):
            run(marked(), self.env_unix)                          # 스레드 없음
        self.assertEqual([bool(k) for k in kinds], [True] * 5, kinds)
        for want in ("engine-loop", "relay-busy", "engine-answer-too-large", "engine-cut", "relay-no-thread"):
            self.assertTrue(any(want in k for k in kinds), want)
        text = buf.getvalue()
        for mark in (MARK_BODY, MARK_IP, MARK_QUERY, "TUFSS0VSVE9LRU4", ENGINE_TOKEN, "172.17.0.1", self.sock, HOST):
            self.assertNotIn(mark, text)

    def test_one_line_per_minute(self):
        with self.assertLogs("naver_relay", level="WARNING") as cm:
            for _ in range(5):
                R.relay(self.inc(), {R.ENV_SWITCH: "on"})
        self.assertEqual(len(cm.output), 1)

    def test_each_kind_gets_its_line(self):
        """한 종류가 다른 종류를 가리지 않는다 — 종류마다 1분에 한 줄(검토 self-loop · 기록)."""
        with self.assertLogs("naver_relay", level="WARNING") as cm:
            for _ in range(3):
                R.relay(self.inc(), {R.ENV_SWITCH: "on"})
                R.relay(self.inc(host=R.ENGINE_HOST_HEADER, fetch_site=None, real_ip=None, peer="127.0.0.1"),
                        self.env_tcp)
        self.assertEqual(len(cm.output), 2)
        self.assertTrue(any("engine-not-configured" in x for x in cm.output))
        self.assertTrue(any("engine-loop" in x for x in cm.output))

    def test_repr_hides_values(self):
        r = repr(self.inc(method="POST", body=MARK_BODY.encode(), origin="https://x.example", query=MARK_QUERY + "=1"))
        for mark in (MARK_BODY, MARK_IP, ENGINE_TOKEN, "172.17.0.1", HOST, "x.example", MARK_QUERY):
            self.assertNotIn(mark, r)
        self.assertNotIn(MARK_BODY, repr(R.Outgoing(200, MARK_BODY.encode())))
        for env in (self.env_unix, self.env_tcp):             # 엔진 주소(소켓 경로 · 포트)도 repr 에 없다
            t = R.engine_target(env)
            self.assertEqual(repr(t), "Target(%s)" % t.kind)
        self.assertNotIn(self.sock, repr(R.engine_target(self.env_unix)))


class PageFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="page-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "naver"
        (self.root / "assets").mkdir(parents=True)
        (self.root / "index.html").write_text("<!doctype html>")
        (self.root / "app.js").write_text("1")
        (self.root / "assets" / "logo.png").write_bytes(b"\x89PNG")
        (self.root / "notes.py").write_text("x")
        (self.root / ".env").write_text("SECRET=1")
        (self.tmp / "outside.js").write_text("x")
        (self.root / "link.js").symlink_to(self.tmp / "outside.js")
        (self.root / "dir.js").mkdir()
        (self.root / "alias.js").symlink_to(self.root / "notes.py")      # 폴더 안 · 다른 종류
        (self.root / "same.js").symlink_to(self.root / "app.js")          # 폴더 안 · 같은 종류

    def test_allowed(self):
        self.assertEqual(R.page_file(self.root, ""), (self.root / "index.html").resolve())
        self.assertEqual(R.page_file(self.root, "index.html"), (self.root / "index.html").resolve())
        self.assertEqual(R.page_file(self.root, "app.js"), (self.root / "app.js").resolve())
        self.assertEqual(R.page_file(self.root, "assets/logo.png"), (self.root / "assets" / "logo.png").resolve())
        self.assertEqual(R.page_type(R.page_file(self.root, "app.js")), "text/javascript; charset=utf-8")

    def test_refused(self):
        for rest in ("../outside.js", "assets/../../outside.js", "notes.py", ".env", "link.js", "dir.js",
                     "missing.js", "/etc/passwd", "app.js/", "a b.js", "APP.JS.map", "assets", "app", "앱.js",
                     "a/b/c/d/e.js", "index.html?x", "app.JS"):
            self.assertIsNone(R.page_file(self.root, rest), rest)
        self.assertIsNone(R.page_file(self.tmp / "none", ""))

    def test_link_inside_root_to_other_kind(self):
        """폴더 안 링크가 다른 종류(.py)를 가리키면 없음 — 요청 이름(.js)만 보면 통과해 page_type 에서 500 이 났다(2차 검토)."""
        self.assertIsNone(R.page_file(self.root, "alias.js"))
        p = R.page_file(self.root, "same.js")
        self.assertEqual(p, (self.root / "app.js").resolve())
        self.assertEqual(R.page_type(p), "text/javascript; charset=utf-8")

    def test_page_headers_keep_sso_home(self):
        h = dict(R.PAGE_HEADERS)
        self.assertEqual((h["Referrer-Policy"], h["Cache-Control"], h["X-Frame-Options"]), ("no-referrer", "no-store", "DENY"))
        csp = h["Content-Security-Policy"]
        for part in ("connect-src 'self'", "script-src 'self'", "frame-ancestors 'none'", "base-uri 'none'",
                     "object-src 'none'", "form-action 'self'"):
            self.assertIn(part, csp)
        self.assertNotIn("unsafe-eval", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)


# ── 날 바이트 엔진(모양이 이상한 답 · 느린 답 · 대기열) ───────────────────────
class RawEngine:
    """유닉스 소켓 · 연결마다 ``serve(conn)`` 을 부른다(요청 머리는 먼저 읽어 둔다). ``accept_after`` 초 동안은 받지 않는다."""

    def __init__(self, path, serve, backlog=5, accept_after=0.0):
        self.path, self.serve, self.accept_after = path, serve, accept_after
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(path)
        self.sock.listen(backlog)
        self.stop = threading.Event()
        self.conns = []
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        if self.accept_after:
            time.sleep(self.accept_after)
        self.sock.settimeout(0.1)
        while not self.stop.is_set():
            try:
                c, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            self.conns.append(c)
            threading.Thread(target=self._one, args=(c,), daemon=True).start()

    def _one(self, c):
        try:
            c.settimeout(5)
            buf = b""
            while b"\r\n\r\n" not in buf:
                got = c.recv(4096)
                if not got:
                    return
                buf += got
            self.serve(c)
        except OSError:
            pass
        finally:
            try:
                c.close()
            except OSError:
                pass

    def close(self):
        self.stop.set()
        self.sock.close()


def _drip(c, data, gap):
    for i in range(len(data)):
        c.sendall(data[i:i + 1])
        time.sleep(gap)


class RawCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="relay-raw-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, "e.sock")
        self.env = {R.ENV_SWITCH: "on", R.ENV_ENGINE: "unix:" + self.path}
        R._last_warn.clear()
        lg = logging.getLogger("naver_relay")
        nh = logging.NullHandler()
        lg.addHandler(nh)
        self.addCleanup(lg.removeHandler, nh)

    def engine(self, serve, **kw):
        e = RawEngine(self.path, serve, **kw)
        self.addCleanup(e.close)
        return e

    def inc(self):
        return R.Incoming(method="GET", sub="/board", authorization=("Bearer " + ENGINE_TOKEN,), real_ip=MARK_IP,
                          host=HOST, fetch_site="same-origin")


class DeadlineTest(RawCase):
    """전체 시간(total_timeout)은 끝까지 지킨다 — 읽을 때마다 새로 열리는 소켓 시간 제한만으로는 안 된다(검토 total-deadline)."""

    def assertTimesOut(self, serve):
        self.engine(serve)
        t = time.monotonic()
        out = R.relay(self.inc(), self.env, total_timeout=0.6)
        took = time.monotonic() - t
        self.assertEqual((out.status, json.loads(out.body)), (504, {"error": "engine-timeout"}))
        self.assertLess(took, 1.2)
        self.assertEqual(R._slots._value, R.MAX_INFLIGHT)

    def test_header_drip(self):
        self.assertTimesOut(lambda c: _drip(c, b"HTTP/1.1 200 OK\r\n" + b"X-Slow: 1\r\n" * 200, 0.05))

    def test_continue_forever(self):
        def serve(c):
            for _ in range(200):
                c.sendall(b"HTTP/1.1 100 Continue\r\n\r\n")
                time.sleep(0.05)
        self.assertTimesOut(serve)

    def test_body_drip(self):
        def serve(c):
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n")
            _drip(c, b"x" * 100, 0.05)
        self.assertTimesOut(serve)

    def test_quick_answer_not_cut(self):
        body = b'{"ok":true}'
        self.engine(lambda c: c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                                        + str(len(body)).encode() + b"\r\n\r\n" + body))
        for _ in range(3):
            out = R.relay(self.inc(), self.env, total_timeout=0.6)
            self.assertEqual((out.status, out.body), (200, body))


class EarlyAnswerTest(RawCase):
    """엔진이 본문을 다 받기 전에 답하고 닫아도(405·413) 그 답을 돌려준다 — 보내다 끊긴 것을 「엔진 없음」으로 바꾸지
    않는다(S12 2차 검토 unix-early-answer-epipe). 답 없이 닫으면 지금처럼 503."""

    def run_early(self, answer):
        closed = threading.Event()
        lst = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        lst.bind(self.path)
        lst.listen(4)
        self.addCleanup(lst.close)

        def serve():
            c, _ = lst.accept()
            if answer:
                c.sendall(answer)
            c.close()
            closed.set()
        threading.Thread(target=serve, daemon=True).start()
        orig = R._UnixConnection.connect

        def connect(conn):
            orig(conn)
            closed.wait(3)                 # 엔진이 답하고 닫은 뒤에야 보낸다 — 보내기에서 반드시 끊긴다
        inc = R.Incoming(method="POST", sub="/session", authorization=("Bearer " + ENGINE_TOKEN,), real_ip=MARK_IP,
                         host=HOST, fetch_site="same-origin", content_type="application/json",
                         body=b'{"sso":"' + b"a" * 60000 + b'"}')
        with mock.patch.object(R._UnixConnection, "connect", connect):
            return R.relay(inc, self.env)

    def test_answer_before_body_is_passed(self):
        body = b'{"error":"method-not-allowed"}'
        out = self.run_early(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Type: application/json\r\nContent-Length: "
                             + str(len(body)).encode() + b"\r\n\r\n" + body)
        self.assertEqual((out.status, out.body), (405, body))
        self.assertEqual(R._slots._value, R.MAX_INFLIGHT)

    def test_closed_without_answer_is_unavailable(self):
        out = self.run_early(b"")
        self.assertEqual((out.status, json.loads(out.body)), (503, {"error": "engine-unavailable"}))
        self.assertEqual(R._slots._value, R.MAX_INFLIGHT)


class TimerLeakTest(EngineCase):
    """끝난 요청의 마감 감시 스레드는 바로 거둔다 — 빠른 요청마다 30초짜리 스레드가 쌓이지 않는다(2차 검토 timer-cancel)."""

    def test_no_timer_left(self):
        for _ in range(20):
            self.assertEqual(R.relay(self.inc(), self.env_unix).status, 200)
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            left = [t for t in threading.enumerate()
                    if isinstance(t, threading.Timer) and getattr(t, "function", None) is R._cut and t.is_alive()]
            if not left:
                break
            time.sleep(0.02)
        self.assertEqual(left, [])


class TimerStartTest(EngineCase):
    """마감 감시 스레드를 못 만들면 연결을 열지 않고 503 — ③ 500·스택으로 새지 않는다(S12 2차 검토 timer-start)."""

    def test_no_thread_no_connection(self):
        class NoThread(threading.Timer):
            def start(self):
                raise RuntimeError("can't start new thread")
        with mock.patch.object(R.threading, "Timer", NoThread):
            out = R.relay(self.inc(), self.env_unix)
        self.assertEqual((out.status, json.loads(out.body)), (503, {"error": "relay-busy"}))
        self.assertEqual(self.eng.got, [])
        self.assertEqual(R._slots._value, R.MAX_INFLIGHT)
        self.assertEqual(R.relay(self.inc(), self.env_unix).status, 200)


class ContentLengthTest(RawCase):
    """엔진 답 길이 칸 — ASCII 숫자만 · 이상한 값은 ③ 500·스택이 아니라 502(검토 content-length-superscript)."""

    def answer(self, length_bytes, body=b'{"ok":true}'):
        def serve(c):
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + length_bytes
                      + b"\r\n\r\n" + body)
        return serve

    def test_odd_lengths_refused(self):
        for raw in (b"\xb2", b"1_1", b"+11", b"-1", b"0x0b", b"\xd9\xa1", b"11, 11", b" "):
            e = self.engine(self.answer(raw))
            out = R.relay(self.inc(), self.env)
            self.assertEqual((out.status, json.loads(out.body)), (502, {"error": "bad-gateway"}), raw)
            e.close()
            os.unlink(self.path)

    def test_trailing_space_ok(self):
        self.engine(self.answer(b"11 "))
        self.assertEqual(R.relay(self.inc(), self.env).status, 200)


class UnixBacklogTest(RawCase):
    """엔진 대기열이 잠깐 차도 「엔진 없음」이 아니다 — 연결 시간 제한 안에서 다시 시도(검토 unix-connect-no-wait)."""

    def test_full_queue_then_free(self):
        body = b'{"ok":true}'
        self.engine(lambda c: c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 11\r\n\r\n"
                                        + body), backlog=0, accept_after=0.5)
        fill = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(fill.close)
        fill.connect(self.path)                                   # 대기열을 채운다(엔진은 아직 받지 않는다)
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(1.0)
        with self.assertRaises(BlockingIOError):                   # 이 머신에서 대기열이 정말 찼는지 먼저 확인
            probe.connect(self.path)
        probe.close()
        t = time.monotonic()
        out = R.relay(self.inc(), self.env)
        self.assertEqual(out.status, 200)
        self.assertGreater(time.monotonic() - t, 0.3)

    def test_gives_up_after_connect_timeout(self):
        self.engine(lambda c: None, backlog=0, accept_after=30)
        fill = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(fill.close)
        fill.connect(self.path)
        t = time.monotonic()
        out = R.relay(self.inc(), self.env, total_timeout=0.4)
        self.assertEqual(out.status, 504)
        self.assertLess(time.monotonic() - t, 1.0)


# ── 구문 시험 ─────────────────────────────────────────────────────────
def _tree(p):
    return ast.parse(p.read_text(encoding="utf-8"))


NET_NAMES = {"HTTPConnection", "HTTPSConnection", "create_connection", "urlopen", "socketpair", "fromfd"}
NET_MODULES = {"http", "http.client", "socket", "urllib", "urllib.request", "ssl"}


def _egress_violations(tree) -> list:
    """나가는 연결을 만들 수 있는 이름이 정한 자리(``_open`` · ``_UnixConnection``) 밖에 나오는 곳 — 호출이 아니어도
    (참조 · 모듈 수준 · lambda · 클래스 본문) · from-import · 이름 글자(getattr 우회) · __import__ 까지(2차 검토 egress-guard)."""
    bad = []
    ann = set()
    for n in ast.walk(tree):
        nodes = []
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nodes = [a.annotation for a in n.args.args + n.args.kwonlyargs + n.args.posonlyargs] + [n.returns]
        elif isinstance(n, ast.AnnAssign):
            nodes = [n.annotation]
        for a in nodes:
            if a is not None:
                ann |= {id(x) for x in ast.walk(a)}               # 표기(타입 힌트)는 연결을 만들지 않는다

    def visit(node, where):
        for child in ast.iter_child_nodes(node):
            w = where
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                w = where if where in ("_open", "_UnixConnection") else child.name
            if id(child) not in ann:
                if isinstance(child, ast.ImportFrom) and (child.module or "") in NET_MODULES:
                    bad.append("from-import " + (child.module or ""))
                if isinstance(child, ast.Name) and (child.id in NET_NAMES or child.id == "__import__"):
                    bad.append(f"{w}:{child.id}")
                if isinstance(child, ast.Attribute) and child.attr in NET_NAMES and w not in ("_open", "_UnixConnection"):
                    bad.append(f"{w}:.{child.attr}")
                if isinstance(child, ast.Attribute) and child.attr == "socket" and isinstance(child.value, ast.Name) \
                        and child.value.id == "socket" and w != "_UnixConnection":
                    bad.append(f"{w}:socket.socket")
                if isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value in NET_NAMES:
                    bad.append(f"{w}:'{child.value}'")
            visit(child, w)
    visit(tree, "<module>")
    return bad


class StructureTest(unittest.TestCase):
    ALLOWED_IMPORTS = {"__future__", "http.client", "ipaddress", "logging", "os", "pathlib", "re", "socket",
                       "threading", "time", "dataclasses", "typing"}

    def test_relay_imports_only_stdlib_basics(self):
        got = set()
        for n in ast.walk(_tree(RELAY_SRC)):
            if isinstance(n, ast.Import):
                got |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                got.add(n.module)
        self.assertLessEqual(got, self.ALLOWED_IMPORTS)
        for bad in ("urllib", "urllib.request", "requests", "httpx", "subprocess", "http.server"):
            self.assertNotIn(bad, got)

    def test_egress_names_only_in_open(self):
        self.assertEqual(_egress_violations(_tree(RELAY_SRC)), [])
        self.assertEqual(_egress_violations(_tree(ROUTER_SRC)), [])

    def test_egress_check_catches_bypass_shapes(self):
        """검토가 찾은 우회 모양을 가짜 소스로 넣어 구문 시험이 모두 잡는지."""
        shapes = [
            "from http.client import HTTPSConnection\ndef _report(k):\n    HTTPSConnection('203.0.113.5').request('POST', '/c')",
            "import http.client\n_OUT = lambda: http.client.HTTPConnection('203.0.113.5', 80)",
            "def f():\n    from socket import create_connection as _cc\n    _cc(('203.0.113.5', 80))",
            "import socket\ndef f():\n    return socket.create_connection(('203.0.113.5', 80))",
            "import http.client\ndef f():\n    return getattr(http.client, 'HTTPSConnection')('x')",
            "def f():\n    return __import__('http.client')",
            "import socket\nclass X:\n    s = socket.socket()",
            "import http.client\nclass Other(http.client.HTTPConnection):\n    pass",
        ]
        for src in shapes:
            self.assertNotEqual(_egress_violations(ast.parse(src)), [], src)
        ok = ("import http.client\nimport socket\ndef _open(t):\n    return http.client.HTTPConnection('127.0.0.1', 1)\n"
              "class _UnixConnection(http.client.HTTPConnection):\n    def connect(self):\n        s = socket.socket()\n"
              "def _read(conn: http.client.HTTPConnection) -> http.client.HTTPResponse:\n    pass")
        self.assertEqual(_egress_violations(ast.parse(ok)), [])

    def test_limits_fit_the_server(self):
        """M7 · 마감 — 한 워커의 엔진 대기 상한은 스레드풀 기본(40)보다 넉넉히 작게 · 전체 마감은 gunicorn --timeout(120)
        보다 한참 짧게(라우터는 기본값을 쓴다 · 2차 검토 m7-capacity · deadline-default)."""
        self.assertLessEqual(R.MAX_INFLIGHT, 16)
        self.assertLessEqual(R.TOTAL_TIMEOUT, 30)
        self.assertLessEqual(R.CONNECT_TIMEOUT, R.TOTAL_TIMEOUT)
        docker = (BACKEND.parent / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('"--timeout", "120"', docker)

    def test_router_checks_switch_first(self):
        """fastapi 없이도 M6 겹을 지킨다 — 라우트 맞춤 · 본문 읽기 · 화면이 스위치를 맨 먼저 보고 · 중계는 꺼짐(RelayOff)을
        없는 주소의 답으로 바꾸고 · Authorization 은 모두(getlist) 읽는다(두 개면 중계가 400 · 2차 검토)."""
        tree = _tree(ROUTER_SRC)
        fns = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name, want in (("_capped_body", "raise _off(request.method)"), ("_page", "raise _off(request.method)"),
                           ("matches", "return (Match.NONE, {})")):
            first = fns[name].body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                first = fns[name].body[1]
            self.assertIsInstance(first, ast.If, name)
            self.assertEqual(ast.unparse(first.test), "not R.enabled()", name)
            self.assertEqual(ast.unparse(first.body[0]), want, name)
        handlers = [h for h in ast.walk(fns["naver_relay_route"]) if isinstance(h, ast.ExceptHandler)]
        self.assertEqual([ast.unparse(h.type) for h in handlers], ["R.RelayOff"])
        self.assertEqual(ast.unparse(handlers[0].body[0]), "raise _off(request.method) from None")
        calls = [c for c in ast.walk(fns["naver_relay_route"]) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Attribute) and c.args and isinstance(c.args[0], ast.Constant)
                 and c.args[0].value == "authorization"]
        self.assertEqual([c.func.attr for c in calls], ["getlist"])
        classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        self.assertIn("_SwitchedRoute", classes)
        self.assertIn("route_class=_SwitchedRoute", ROUTER_SRC.read_text(encoding="utf-8"))

    def test_connections_only_through_open(self):
        """나가는 연결은 _open(검사한 Target) · _UnixConnection 에서만 — 다른 곳에서 새 연결을 만들지 않는다."""
        tree = _tree(RELAY_SRC)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        ctor = {c.func.attr for c in calls if isinstance(c.func, ast.Attribute)} & {"HTTPConnection", "HTTPSConnection",
                                                                                    "create_connection", "urlopen"}
        self.assertEqual(ctor, {"HTTPConnection"})
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef):
                for c in ast.walk(fn):
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute):
                        if c.func.attr == "HTTPConnection":
                            self.assertEqual(fn.name, "_open")
                        if c.func.attr == "socket" and isinstance(c.func.value, ast.Name) and c.func.value.id == "socket":
                            self.assertEqual(fn.name, "connect")
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_open":
                        self.assertEqual(fn.name, "_forward")     # 연결은 슬롯을 잡은 뒤 한 곳에서만

    def test_warn_kinds_are_fixed_words(self):
        """기록 종류는 정해 둔 글자뿐 — 모든 _warn 부르는 곳의 인자가 글자 상수 · 예외 종류 이름 · 그 둘의 고르기만
        (주소·쿼리·경로·값을 이어 붙이는 길이 없다 · 방해 시험이 처음에 놓친 모양)."""
        def ok(a):
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                return True
            if isinstance(a, ast.Attribute) and a.attr == "__name__" and isinstance(a.value, ast.Call) \
                    and isinstance(a.value.func, ast.Name) and a.value.func.id == "type":
                return True
            if isinstance(a, ast.IfExp):
                return ok(a.body) and ok(a.orelse)
            return False
        calls = [c for c in ast.walk(_tree(RELAY_SRC)) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Name) and c.func.id == "_warn"]
        self.assertGreaterEqual(len(calls), 10)
        for c in calls:
            self.assertEqual((len(c.args), c.keywords), (1, []), ast.unparse(c))
            self.assertTrue(ok(c.args[0]), ast.unparse(c))

    def test_logs_carry_kind_only(self):
        for c in ast.walk(_tree(RELAY_SRC)):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and \
                    isinstance(c.func.value, ast.Name) and c.func.value.id == "log":
                self.assertIsInstance(c.args[0], ast.Constant)
                for a in c.args[1:]:
                    self.assertIsInstance(a, ast.Name)
                    self.assertEqual(a.id, "kind")
                self.assertEqual(c.keywords, [])

    def test_router_relay_is_sync_def_and_copies_named_headers_only(self):
        tree = _tree(ROUTER_SRC)
        fns = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for name in ("naver_relay_route", "naver_page_root", "naver_page_file", "_page"):
            self.assertIsInstance(fns[name], ast.FunctionDef, name)      # M7 — 스레드풀에서 돈다
        self.assertIsInstance(fns["_capped_body"], ast.AsyncFunctionDef)
        keys = set()
        for c in ast.walk(tree):
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in ("get", "getlist") \
                    and isinstance(c.func.value, ast.Name) and c.func.value.id == "h":
                keys.add(c.args[0].value)
        self.assertEqual(keys, {"authorization", "content-type", "x-real-ip", "origin", "host", "sec-fetch-site"})
        src = ROUTER_SRC.read_text(encoding="utf-8")
        for bad in ("cookies", "dict(request.headers", "request.headers.items", "headers.raw", "x-forwarded-for",
                    "x-naver-auto-source"):
            self.assertNotIn(bad, src.lower())
        mods = set()                       # 라우터는 연결을 만들지 않는다 — 정한 모듈만(글자 검사는 starlette.requests 에 걸린다)
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                mods |= {a.name for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                mods.add("." * n.level + (n.module or ""))
        self.assertEqual(mods, {"__future__", "pathlib", "typing", "fastapi", "fastapi.responses", "fastapi.routing",
                                "starlette.requests", "starlette.routing", ".."})

    def test_page_files_outside_static_mount(self):
        """화면 파일 자리는 정적 마운트 폴더 밖 — 마운트가 어떤 주소 철자로도 닿지 못한다(검토 static-mount-bypass)."""
        tree = _tree(ROUTER_SRC)
        roots = [ast.unparse(n.value) for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "PAGE_ROOT" for t in n.targets)]
        self.assertEqual(roots, ["pathlib.Path(__file__).resolve().parents[2] / 'naver_page'"])
        self.assertFalse((BACKEND / "static" / "naver").exists())
        self.assertFalse(any(p.is_dir() for p in (BACKEND / "static").rglob("naver*")))   # naver-categories.js 같은 파일은 무관
        main = MAIN_SRC.read_text(encoding="utf-8")
        self.assertIn('_static = pathlib.Path(__file__).resolve().parent.parent / "static"', main)
        self.assertNotIn("naver_page", main)                  # 정적 마운트가 그 폴더를 가리키지 않는다

    def test_router_before_static_mount(self):
        """M6 — 스위치 라우터가 정적 마운트보다 먼저 등록된다(정적 마운트가 /naver/ 를 먼저 내주지 않게)."""
        body = _tree(MAIN_SRC).body
        inc = mount = None
        for i, st in enumerate(body):
            if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Attribute):
                f = st.value.func
                if f.attr == "include_router" and ast.unparse(st.value.args[0]) == "naver.router":
                    self.assertEqual(st.value.keywords, [])          # 머리 경로 붙이지 않음 — /naver · /api/naver-auto 그대로
                    inc = i
                if f.attr == "mount" and ast.unparse(st.value.args[0]) == "'/'":
                    mount = i
        self.assertIsNotNone(inc)
        self.assertIsNotNone(mount)
        self.assertLess(inc, mount)


if __name__ == "__main__":
    unittest.main()
