"""S12 앱 시험 — 진짜 ③ 앱(``app.main``)에 붙은 중계·입구(M6 · M7 · 라우터가 넘기는 머리). **fastapi 가 있어야 돈다.**

backend 폴더를 임시 폴더에 복사하고(``static/naver/`` 에 표지 파일을 두려고) 따로 띄운 파이썬(``naver_relay_harness.py``)
에서 본다 — 운영 DB·저장소 파일은 건드리지 않는다. 가짜 엔진은 그 임시 폴더의 유닉스 소켓뿐(네트워크 0).
fastapi 가 없는 파이썬에서는 건너뛴다(건너뛴 수가 결과에 찍힌다). 돌리는 법: fastapi 가 깔린 파이썬으로
  python -m unittest -v tests.test_naver_relay_app
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
HARNESS = pathlib.Path(__file__).resolve().parent / "naver_relay_harness.py"
HAS_FASTAPI = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "uvicorn", "sqlalchemy", "jose"))

ENGINE_TOKEN = "v1.eyJzdWIiOjB9TUFSS0VSVE9LRU4." + "S" * 43
ALLOWED = {"host", "accept", "connection", "content-type", "content-length", "authorization", "x-naver-auto-source"}
# 자식 파이썬에 넘기는 환경 — 정한 이름만(운영 비밀값 · 외부 연동 스위치를 물려받지 않는다 · S12 2차 검토)
KEEP_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR")
TEST_JWT_SECRET = "s12-relay-test-only-not-a-secret"


def child_env(tmp):
    env = {k: os.environ[k] for k in KEEP_ENV if k in os.environ}
    env.update({"DB_PATH": str(tmp / "t.db"), "FERNET_KEY_FILE": str(tmp / "k.key"), "PYTHONDONTWRITEBYTECODE": "1",
                "JWT_SECRET": TEST_JWT_SECRET})
    return env


def run_harness(mode, *extra, timeout=90):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="relay-app-"))
    try:
        shutil.copytree(BACKEND / "app", tmp / "app", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(BACKEND / "static", tmp / "static")
        naver = tmp / "naver_page"                         # 화면 파일 자리 — 정적 마운트(static/) 밖
        naver.mkdir(exist_ok=True)
        shutil.copy(BACKEND / "naver_page" / "README.md", naver / "README.md")
        (naver / "index.html").write_text("<!doctype html><title>M6PROBE-INDEX</title>", encoding="utf-8")
        (naver / "m6.js").write_text("// M6PROBE-JS", encoding="utf-8")
        (naver / "secret.py").write_text("M6PROBE-PY", encoding="utf-8")
        shutil.copy(HARNESS, tmp / "harness.py")
        env = child_env(tmp)
        p = subprocess.run([sys.executable, "-W", "ignore", "harness.py", mode, *extra], cwd=tmp, env=env,
                           capture_output=True, text=True, timeout=timeout)
        line = [ln for ln in p.stdout.split("\n") if ln.startswith("@@RESULT@@")]
        if not line:
            raise AssertionError(f"harness {mode} 실패: {p.returncode}\n{p.stdout[-2000:]}\n{p.stderr[-4000:]}")
        return json.loads(line[-1][len("@@RESULT@@"):])
    finally:
        shutil.rmtree(tmp, True)


@unittest.skipUnless(HAS_FASTAPI, "fastapi 없음 — 서버 이미지 또는 시험용 가상환경에서 돌린다")
class M6EntranceTest(unittest.TestCase):
    """M6 — 스위치가 꺼지면 /naver · /api/naver-auto 는 **없는 주소와 똑같다**(정적 마운트가 먼저 내주지 않는다)."""

    @classmethod
    def setUpClass(cls):
        cls.r = run_harness("m6")

    def test_off_is_same_as_missing_route(self):
        """방식마다 — 없는 주소가 주는 답(GET·HEAD 404 · 그 밖 405)과 상태·본문·형식이 같다(검토 off-method-fingerprint)."""
        for method, p, res in self.r["off"]:
            ref = (self.r["ref_api"] if p.startswith("/api/") else self.r["ref"])[method]
            self.assertEqual((res["status"], res["text"], res["headers"].get("content-type")),
                             (ref["status"], ref["text"], ref["headers"].get("content-type")), (method, p))
            self.assertNotIn("M6PROBE", res["text"], (method, p))
        self.assertEqual(self.r["ref"]["GET"]["status"], 404)
        self.assertEqual(self.r["ref"]["POST"]["status"], 405)
        self.assertGreaterEqual(len(self.r["off"]), 70)

    def test_on_serves_page_with_guard_headers(self):
        on = {(m, p): res for m, p, res in self.r["on"]}
        for key in (("GET", "/naver/"), ("GET", "/naver/index.html")):
            res = on[key]
            self.assertEqual(res["status"], 200, key)
            self.assertIn("M6PROBE-INDEX", res["text"])
            h = res["headers"]
            self.assertTrue(h["content-type"].startswith("text/html"))
            self.assertEqual((h["cache-control"], h["referrer-policy"], h["x-frame-options"]), ("no-store", "no-referrer", "DENY"))
            self.assertIn("connect-src 'self'", h["content-security-policy"])
        self.assertEqual((on[("HEAD", "/naver/")]["status"], on[("HEAD", "/naver/")]["text"]), (200, ""))
        self.assertEqual(on[("GET", "/naver/m6.js")]["status"], 200)
        self.assertTrue(on[("GET", "/naver/m6.js")]["headers"]["content-type"].startswith("text/javascript"))
        for key in (("GET", "/naver"), ("GET", "/naver/secret.py"), ("GET", "/naver/%2e%2e/%2e%2e/app/main.py"),
                    ("GET", "/naver/missing.js"), ("GET", "/naver/README.md"), ("GET", "/naver_page/index.html")):
            self.assertEqual(on[key]["status"], 404, key)
            self.assertNotIn("M6PROBE", on[key]["text"])
            self.assertNotIn("import", on[key]["text"])
        self.assertEqual(on[("POST", "/naver/")]["status"], 405)
        for key in (("GET", "/naver/secret.py"), ("GET", "/naver/missing.js"), ("POST", "/naver/")):
            h = on[key]["headers"]                             # 화면 쪽 404·405 도 sso 가 새지 않게(검토 off-404-referer)
            self.assertEqual((h.get("referrer-policy"), h.get("cache-control")), ("no-referrer", "no-store"), key)
        eng = on[("GET", "/api/naver-auto/board")]
        self.assertEqual((eng["status"], json.loads(eng["text"])), (503, {"error": "engine-unavailable"}))
        self.assertEqual(self.r["health"]["status"], 200)
        self.assertFalse(self.r["collector_started"])        # 시험이 수집 스레드를 띄우지 않았다


@unittest.skipUnless(HAS_FASTAPI, "fastapi 없음 — 서버 이미지 또는 시험용 가상환경에서 돌린다")
class M6BypassTest(unittest.TestCase):
    """다른 주소 철자(빗금 둘 · 점 · 퍼센트)로도 스위치를 못 건너뛴다 — 화면이 나가면 반드시 라우터 머리(CSP)가 붙어 있다
    (검토 static-mount-bypass · 날 요청 줄을 진짜 uvicorn 에)."""

    @classmethod
    def setUpClass(cls):
        cls.r = run_harness("bypass")

    def test_off_never_serves(self):
        for p, res in self.r["off"]:
            self.assertNotIn("M6PROBE", res["text"], p)
            self.assertIn(res["status"], (400, 404), p)

    def test_off_dot_segments_same_as_twin(self):
        """꺼져 있으면 점 조각 주소도 S12 이전과 같은 답 — 같은 모양의 없는 주소(naver → nxver)와 상태·본문·머리가 같다
        (라우터가 아예 맞지 않는다 · 검토 off-dot-segment-fingerprint)."""
        self.assertGreaterEqual(len(self.r["dots"]), 6)
        for p, twin, a, b in self.r["dots"]:
            self.assertEqual((a["status"], a["text"]), (b["status"], b["text"]), p)
            skip = {"date", "location"}
            self.assertEqual({k: v for k, v in a["headers"].items() if k not in skip},
                             {k: v for k, v in b["headers"].items() if k not in skip}, p)
            self.assertEqual(a["headers"].get("location", "").replace("naver", "nxver"),
                             b["headers"].get("location", ""), p)
        self.assertIn(200, {a["status"] for _p, _t, a, _b in self.r["dots"]})    # 옛 답(정적 파일)이 그대로 나오는 것도 본다

    def test_on_only_through_router(self):
        served = []
        for p, res in self.r["on"]:
            if "M6PROBE" in res["text"]:
                served.append(p)
                h = res["headers"]
                self.assertIn("connect-src 'self'", h.get("content-security-policy", ""), p)
                self.assertEqual((h.get("cache-control"), h.get("referrer-policy")), ("no-store", "no-referrer"), p)
        self.assertIn("/naver/", served)
        self.assertIn("/naver/index.html", served)


@unittest.skipUnless(HAS_FASTAPI, "fastapi 없음 — 서버 이미지 또는 시험용 가상환경에서 돌린다")
class BodyReadTest(unittest.TestCase):
    """라우터 본문 읽기 — 64KB 를 넘는 순간 더 읽지 않는다(길이를 말하면 한 조각도 안 읽는다) · 꺼져 있으면 안 읽는다.
    중계 본체도 64KB 를 막지만(겹) 여기서 끊어야 큰 본문이 메모리에 쌓이지 않는다."""

    @classmethod
    def setUpClass(cls):
        import asyncio
        if str(BACKEND) not in sys.path:
            sys.path.insert(0, str(BACKEND))
        from starlette.requests import Request
        from app.routers import naver as N
        cls.N, cls.Request, cls.asyncio = N, Request, asyncio

    def read(self, chunks, headers=(), method="POST", on=True):
        pulled = []
        it = iter(chunks)

        async def receive():
            c = next(it, None)
            pulled.append(c)
            if c == "GONE":
                return {"type": "http.disconnect"}
            if c is None:
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.request", "body": c, "more_body": True}
        scope = {"type": "http", "method": method, "path": "/api/naver-auto/session", "headers": list(headers),
                 "query_string": b""}
        old = os.environ.get("NAVER_AUTO_WEB")
        os.environ["NAVER_AUTO_WEB"] = "on" if on else "off"
        try:
            got = self.asyncio.run(self.N._capped_body(self.Request(scope, receive)))
        except Exception as e:           # 꺼짐 — HTTPException
            got = e
        finally:
            if old is None:
                os.environ.pop("NAVER_AUTO_WEB", None)
            else:
                os.environ["NAVER_AUTO_WEB"] = old
        return got, len(pulled)

    def test_stops_right_after_limit(self):
        got, pulled = self.read([b"x" * 4096] * 1000)
        self.assertEqual(got, 413)
        self.assertLessEqual(pulled, 64 * 1024 // 4096 + 1)

    def test_declared_length_refused_without_reading(self):
        got, pulled = self.read([b"x" * 4096] * 100, headers=[(b"content-length", str(64 * 1024 + 1).encode())])
        self.assertEqual((got, pulled), (413, 0))
        got, pulled = self.read([b"{}"], headers=[(b"content-length", b"x2")])
        self.assertEqual((got, pulled), (400, 0))

    def test_under_limit_read_whole(self):
        got, _ = self.read([b'{"sso":', b'"x"}'])
        self.assertEqual(got, b'{"sso":"x"}')

    def test_client_gone_is_quiet(self):
        """보내다 끊은 브라우저 — 의존성 밖으로 예외(스택 기록)가 새지 않는다(검토 client-disconnect-traceback)."""
        got, _ = self.read([b"{", "GONE"])
        self.assertEqual(got, 400)

    def test_off_reads_nothing(self):
        got, pulled = self.read([b"x" * 4096] * 3, on=False)
        self.assertEqual((getattr(got, "status_code", None), pulled), (405, 0))
        got, pulled = self.read([b"x"], method="GET", on=False)
        self.assertEqual((getattr(got, "status_code", None), pulled), (404, 0))


@unittest.skipUnless(HAS_FASTAPI, "fastapi 없음 — 서버 이미지 또는 시험용 가상환경에서 돌린다")
class RouterHeadersTest(unittest.TestCase):
    """라우터가 엔진에 넘기는 것 — 정한 머리만 · ③ 로그인 토큰·쿠키·밖에서 온 요청한 곳 머리는 넘기지 않는다."""

    @classmethod
    def setUpClass(cls):
        cls.r = run_harness("headers")
        cls.calls = {name: res for name, res in cls.r["calls"]}
        cls.got = cls.r["engine_got"]

    def test_erp3_login_token_not_forwarded(self):
        self.assertEqual(self.r["login"], 200)
        self.assertGreater(self.r["erp3_token_len"], 20)       # 진짜 ③ 로그인 토큰으로 본다
        h = dict(self.got[0]["headers"])
        self.assertNotIn("authorization", h)
        self.assertEqual(self.calls["erp3"]["status"], 200)     # 엔진이 받는 것은 토큰 없는 요청(엔진이 401 로 막는다)

    def test_only_named_headers_and_source_from_nginx(self):
        for g in self.got:
            h = dict(g["headers"])
            self.assertLessEqual(set(h), ALLOWED, g)
            blob = json.dumps(g)
            for mark in ("COOKIEMARK", "CUSTOMMARK", "APIKEYMARK", "9.9.9.9", "8.8.8.8", "7.7.7.7"):
                self.assertNotIn(mark, blob)
        self.assertEqual(dict(self.got[0]["headers"])["x-naver-auto-source"], "203.0.113.9")
        h1 = dict(self.got[1]["headers"])
        self.assertEqual((h1["authorization"], self.got[1]["path"]),
                         ("Bearer " + ENGINE_TOKEN, "/api/naver-auto/board?attention=0"))
        h2 = dict(self.got[2]["headers"])
        self.assertEqual((self.got[2]["method"], h2["content-type"], self.got[2]["body_len"]), ("POST", "application/json", 11))
        self.assertEqual(len(self.got), 3)

    def test_refusals_never_reach_engine(self):
        self.assertEqual(self.r["refused_contacts"], 0)
        for name, st in (("big", 413), ("chunked", 413), ("evil", 403), ("same-site", 403)):
            self.assertEqual(self.calls[name]["status"], st, name)
        self.assertIn(self.calls["bad-length"]["status"], (400, 413))

    def test_engine_headers_not_passed_back(self):
        for name in ("erp3", "engine", "post"):
            h = self.calls[name]["headers"]
            self.assertNotIn("set-cookie", h, name)
            self.assertNotIn("x-engine-only", h, name)
            self.assertEqual((h["cache-control"], h["x-content-type-options"]), ("no-store", "nosniff"))


@unittest.skipUnless(HAS_FASTAPI, "fastapi 없음 — 서버 이미지 또는 시험용 가상환경에서 돌린다")
class M7SlowEngineTest(unittest.TestCase):
    """M7 — 엔진이 느려도(요청 3개가 엔진에서 2.5초씩 걸리는 동안) ③ /api/health 는 바로 답한다."""

    def test_health_not_blocked(self):
        r = run_harness("m7", "2.5")
        self.assertEqual(r["engine_busy"], 3)                    # 셋 다 엔진 안에 있을 때 잰다
        status, dur = r["health"]
        self.assertEqual(status, 200)
        self.assertLess(dur, 1.0, r)
        self.assertEqual([s for s, _d in r["slow"]], [200, 200, 200])
        self.assertTrue(all(d >= 2.3 for _s, d in r["slow"]), r)


class HarnessEnvTest(unittest.TestCase):
    """시험 도우미가 자식 파이썬에 넘기는 환경 — 정한 이름만 · 운영 비밀값 이름 0 · JWT 비밀값은 시험 값."""

    def test_child_env_allowlist(self):
        planted = {"JWT_SECRET": "PRODMARK", "ANTHROPIC_API_KEY": "PRODMARK", "ERP_SYNC_API_KEY": "PRODMARK",
                   "ERP_SYNC_URL": "PRODMARK", "ERP_SYNC_STATUS": "1", "MC_AD_API_TOKEN": "PRODMARK",
                   "YOUTUBE_API_KEY": "PRODMARK", "NAVER_AUTO_WEB": "on", "NAVER_AUTO_ENGINE": "unix:/x.sock"}
        old = {k: os.environ.get(k) for k in planted}
        os.environ.update(planted)
        try:
            env = child_env(pathlib.Path("/tmp/x"))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertLessEqual(set(env), set(KEEP_ENV) | {"DB_PATH", "FERNET_KEY_FILE", "PYTHONDONTWRITEBYTECODE", "JWT_SECRET"})
        self.assertNotIn("PRODMARK", json.dumps(env))
        self.assertEqual(env["JWT_SECRET"], TEST_JWT_SECRET)

    def test_harness_holds_collector_lock_first(self):
        """도우미는 app.main 을 부르기 전에 수집 잠금을 먼저 잡는다 — 시험이 06:00 수집 스레드를 띄우지 않게."""
        src = HARNESS.read_text(encoding="utf-8")
        self.assertIn("collector.lock", src)
        main_block = src[src.index('if __name__ == "__main__":'):]
        self.assertLess(main_block.index("_hold_collector_lock()"), main_block.index("fn = "))
        self.assertNotIn("import app", src.split("\ndef ")[0])    # 맨 위에서 app 을 부르지 않는다


if __name__ == "__main__":
    unittest.main()
