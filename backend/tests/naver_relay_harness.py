"""S12 앱 시험 도우미 — ``test_naver_relay_app.py`` 가 **복사한 backend 폴더 안에서** 따로 띄운다(fastapi 필요).

진짜 ``app.main`` 을 불러 정적 마운트·다른 라우터·CORS 까지 그대로 둔 채 본다. 결과는 JSON 한 줄로 표준 출력에.
모드: m6 (스위치 꺼짐·켜짐 입구) · headers (라우터가 넘기는 머리) · m7 (느린 엔진이 /api/health 를 막지 않는지)
"""
from __future__ import annotations

import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import time

ROOT = os.getcwd()
sys.path.insert(0, ROOT)
_LOCK = []


def _hold_collector_lock():
    """app.main 을 부르기 전에 수집 잠금을 먼저 잡는다 — 그러면 start_scheduler 가 「다른 워커가 가졌다」로 보고 수집
    스레드(06:00 외부 호출)를 띄우지 않는다. 잠금 파일은 임시 폴더(DB_PATH 옆)."""
    import fcntl
    path = os.path.join(os.path.dirname(os.environ["DB_PATH"]), "collector.lock")
    fh = open(path, "w")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    _LOCK.append(fh)

ENGINE_TOKEN = "v1.eyJzdWIiOjB9TUFSS0VSVE9LRU4." + "S" * 43


class Engine:
    def __init__(self, delay=0.0):
        self.got = []
        self.delay = delay

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
                                "headers": sorted((k.lower(), v) for k, v in self.headers.items()),
                                "body_len": len(data)})
                if eng.delay:
                    time.sleep(eng.delay)
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", "engine=leak")
                self.send_header("X-Engine-Only", "1")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _any

        return H


class UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


def start_engine(delay=0.0):
    eng = Engine(delay)
    path = os.path.join(ROOT, "engine.sock")
    srv = UnixServer(path, eng.handler())
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return eng, path


def resp(r):
    return {"status": r.status_code, "text": r.text[:300], "headers": {k.lower(): v for k, v in r.headers.items()}}


METHODS = ("GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH")


def mode_m6():
    from fastapi.testclient import TestClient
    import app.main as m
    c = TestClient(m.app)
    out = {"ref": {mt: resp(c.request(mt, "/zzz-none-s12")) for mt in METHODS},
           "ref_api": {mt: resp(c.request(mt, "/api/zzz-none-s12")) for mt in METHODS}, "off": [], "on": []}
    paths = ["/naver", "/naver/", "/naver/index.html", "/naver/m6.js", "/naver/secret.py", "/api/naver-auto/board",
             "/api/naver-auto/session", "/api/naver-auto/", "/naver/%2e%2e/%2e%2e/app/main.py", "/naver_page/index.html"]
    os.environ.pop("NAVER_AUTO_WEB", None)
    for method in METHODS:
        for p in paths:
            out["off"].append([method, p, resp(c.request(method, p))])
    os.environ["NAVER_AUTO_WEB"] = "yes"          # on 이 아닌 값 = 꺼짐
    for p in paths:
        out["off"].append(["GET", p, resp(c.get(p))])
    os.environ["NAVER_AUTO_WEB"] = "on"
    os.environ.pop("NAVER_AUTO_ENGINE", None)
    for method, p in (("GET", "/naver"), ("GET", "/naver/"), ("HEAD", "/naver/"), ("GET", "/naver/index.html"),
                      ("GET", "/naver/m6.js"), ("GET", "/naver/secret.py"), ("POST", "/naver/"),
                      ("GET", "/naver/%2e%2e/%2e%2e/app/main.py"), ("GET", "/naver/missing.js"),
                      ("GET", "/naver/README.md"), ("GET", "/naver_page/index.html"),
                      ("GET", "/api/naver-auto/board"), ("GET", "/api/naver-auto/../x")):
        out["on"].append([method, p, resp(c.request(method, p))])
    out["health"] = resp(c.get("/api/health"))
    out["collector_started"] = "_lock_fh" in vars(sys.modules["app.collector"])
    return out


BYPASS = ["//naver/", "//naver/index.html", "/./naver/index.html", "/%2e/naver/index.html", "/x/../naver/index.html",
          "/%2fnaver/index.html", "///naver/m6.js", "/naver//index.html", "/naver/./index.html", "/NAVER/",
          "/naver_page/index.html", "/static/../naver_page/index.html", "/%6eaver/index.html", "/naver%2findex.html",
          "/naver/index.html%00", "/naver/", "/naver/index.html"]


DOTS = ["/naver/../index.html", "/naver/..", "/naver/.", "/api/naver-auto/../../app.js", "/api/naver-auto/..",
        "/naver/%2e%2e/index.html", "/api/naver-auto/%2e%2e/%2e%2e/index.html"]


def mode_bypass():
    """날 요청 줄 — 브라우저·시험 도구가 고쳐 주지 않는 주소 철자를 uvicorn 에 그대로 보낸다."""
    import uvicorn
    import app.main as m
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(m.app, log_level="error", lifespan="off"))
    threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True).start()
    t0 = time.monotonic()
    while not server.started and time.monotonic() - t0 < 10:
        time.sleep(0.02)

    def raw(path):
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        s.sendall(("GET " + path + " HTTP/1.1\r\nHost: d.example\r\nConnection: close\r\n\r\n").encode("latin-1"))
        data = b""
        while True:
            got = s.recv(65536)
            if not got:
                break
            data += got
        s.close()
        head, _sep, body = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        hdrs = {ln.split(":", 1)[0].strip().lower(): ln.split(":", 1)[1].strip() for ln in lines[1:] if ":" in ln}
        return {"status": int(lines[0].split()[1]), "text": body.decode("latin-1")[:300], "headers": hdrs}

    out = {"off": [], "on": [], "dots": []}
    os.environ.pop("NAVER_AUTO_WEB", None)
    for p in BYPASS:
        out["off"].append([p, raw(p)])
    for p in DOTS:                                     # 꺼짐 — 같은 모양의 없는 주소와 대조
        twin = p.replace("naver", "nxver")
        out["dots"].append([p, twin, raw(p), raw(twin)])
    os.environ["NAVER_AUTO_WEB"] = "on"
    for p in BYPASS:
        out["on"].append([p, raw(p)])
    server.should_exit = True
    return out


def mode_headers():
    from fastapi.testclient import TestClient
    import app.main as m
    eng, path = start_engine()
    os.environ["NAVER_AUTO_WEB"] = "on"
    os.environ["NAVER_AUTO_ENGINE"] = "unix:" + path
    c = TestClient(m.app)
    lg = c.post("/api/auth/login", json={"email": "admin@metainc.co.kr", "password": "admin1234"})
    erp3 = lg.json().get("access_token") or lg.json().get("token") or ""
    out = {"login": lg.status_code, "erp3_token_len": len(erp3), "calls": []}
    noisy = {"Cookie": "session=COOKIEMARK", "X-Naver-Auto-Source": "9.9.9.9", "X-Forwarded-For": "8.8.8.8",
             "X-Real-IP": "203.0.113.9", "X-Custom": "CUSTOMMARK", "Sec-Fetch-Site": "same-origin",
             "Forwarded": "for=7.7.7.7", "X-Api-Key": "APIKEYMARK"}
    out["calls"].append(["erp3", resp(c.get("/api/naver-auto/board", headers={**noisy, "Authorization": "Bearer " + erp3}))])
    out["calls"].append(["engine", resp(c.get("/api/naver-auto/board?attention=0",
                                              headers={**noisy, "Authorization": "Bearer " + ENGINE_TOKEN}))])
    out["calls"].append(["post", resp(c.post("/api/naver-auto/links/confirm", content=b'{"ids":[1]}',
                                             headers={"Content-Type": "application/json; charset=utf-8",
                                                      "Authorization": "Bearer " + ENGINE_TOKEN}))])
    before = len(eng.got)
    big = b"{" + b" " * (64 * 1024) + b"}"
    out["calls"].append(["big", resp(c.post("/api/naver-auto/session", content=big,
                                            headers={"Content-Type": "application/json"}))])

    def gen():
        for _ in range(20):
            yield b" " * 4096
    out["calls"].append(["chunked", resp(c.post("/api/naver-auto/session", content=gen(),
                                                headers={"Content-Type": "application/json"}))])
    out["calls"].append(["bad-length", resp(c.post("/api/naver-auto/session", content=b"{}",
                                                   headers={"Content-Type": "application/json", "Content-Length": "x2"}))])
    out["calls"].append(["two-auth", resp(c.get("/api/naver-auto/board", headers=[("Authorization", "Bearer " + ENGINE_TOKEN),
                                                                               ("Authorization", "Bearer " + erp3)]))])
    out["calls"].append(["evil", resp(c.get("/api/naver-auto/board", headers={"Origin": "https://evil.example"}))])
    out["calls"].append(["same-site", resp(c.get("/api/naver-auto/board", headers={"Sec-Fetch-Site": "same-site"}))])
    out["refused_contacts"] = len(eng.got) - before
    out["engine_got"] = eng.got
    return out


def mode_m7():
    import http.client
    import uvicorn
    import app.main as m
    from app import naver_relay as R
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5      # harness.py m7 <지연> <동시 수>
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    need = min(n, R.MAX_INFLIGHT)
    eng, path = start_engine(delay=delay)
    os.environ["NAVER_AUTO_WEB"] = "on"
    os.environ["NAVER_AUTO_ENGINE"] = "unix:" + path
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(m.app, log_level="error", lifespan="off"))
    threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True).start()
    t0 = time.monotonic()
    while not server.started and time.monotonic() - t0 < 10:
        time.sleep(0.02)

    def get(p, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
        s = time.monotonic()
        conn.request("GET", p, headers=headers or {})
        r = conn.getresponse()
        body = r.read()
        conn.close()
        return r.status, time.monotonic() - s, body

    results = {}

    errors = []

    def slow(i):
        try:
            results[i] = get("/api/naver-auto/board", {"Authorization": "Bearer " + ENGINE_TOKEN})
        except Exception as e:                        # 시험 쪽 연결 실패 — 종류만 적는다
            errors.append(type(e).__name__)
    threads = [threading.Thread(target=slow, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    while len(eng.got) < need and time.monotonic() - t0 < 12:
        time.sleep(0.02)
    engine_busy_before_health = len(eng.got)
    hs, hdur, _hb = get("/api/health")
    for t in threads:
        t.join()
    server.should_exit = True
    return {"health": [hs, round(hdur, 3)], "engine_busy": engine_busy_before_health, "inflight_max": R.MAX_INFLIGHT,
            "slow": [[s, round(d, 3)] for s, d, _b in results.values()], "delay": delay, "engine_total": len(eng.got),
            "errors": sorted(errors)}


if __name__ == "__main__":
    _hold_collector_lock()
    fn = {"m6": mode_m6, "bypass": mode_bypass, "headers": mode_headers, "m7": mode_m7}[sys.argv[1]]
    res = fn()
    sys.stdout.write("\n@@RESULT@@" + json.dumps(res) + "\n")   # ASCII 로 — 본문의 \x85 같은 글자가 줄을 끊지 않게
    sys.stdout.flush()
    os._exit(0)
