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


def run_harness(mode, *extra, timeout=90):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="relay-app-"))
    try:
        shutil.copytree(BACKEND / "app", tmp / "app", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(BACKEND / "static", tmp / "static")
        naver = tmp / "static" / "naver"
        naver.mkdir(exist_ok=True)
        (naver / "index.html").write_text("<!doctype html><title>M6PROBE-INDEX</title>", encoding="utf-8")
        (naver / "m6.js").write_text("// M6PROBE-JS", encoding="utf-8")
        (naver / "secret.py").write_text("M6PROBE-PY", encoding="utf-8")
        shutil.copy(HARNESS, tmp / "harness.py")
        env = {k: v for k, v in os.environ.items() if not k.startswith("NAVER_AUTO_")}
        env.update({"DB_PATH": str(tmp / "t.db"), "FERNET_KEY_FILE": str(tmp / "k.key"), "PYTHONDONTWRITEBYTECODE": "1"})
        p = subprocess.run([sys.executable, "-W", "ignore", "harness.py", mode, *extra], cwd=tmp, env=env,
                           capture_output=True, text=True, timeout=timeout)
        line = [ln for ln in p.stdout.splitlines() if ln.startswith("@@RESULT@@")]
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
        ref = self.r["ref_get"]
        self.assertEqual(ref["status"], 404)
        for method, p, res in self.r["off"]:
            self.assertEqual(res["status"], 404, (method, p))
            self.assertNotIn("M6PROBE", res["text"], (method, p))
            if method == "GET":
                self.assertEqual(res["text"], ref["text"], (method, p))
                self.assertEqual(res["headers"].get("content-type"), ref["headers"].get("content-type"))
        self.assertGreaterEqual(len(self.r["off"]), 60)

    def test_on_serves_page_with_guard_headers(self):
        on = {(m, p): res for m, p, res in self.r["on"]}
        for key in (("GET", "/naver"), ("GET", "/naver/"), ("GET", "/naver/index.html")):
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
        for key in (("GET", "/naver/secret.py"), ("GET", "/naver/%2e%2e/%2e%2e/app/main.py"), ("GET", "/naver/missing.js")):
            self.assertEqual(on[key]["status"], 404, key)
            self.assertNotIn("M6PROBE", on[key]["text"])
            self.assertNotIn("import", on[key]["text"])
        self.assertEqual(on[("POST", "/naver/")]["status"], 405)
        eng = on[("GET", "/api/naver-auto/board")]
        self.assertEqual((eng["status"], json.loads(eng["text"])), (503, {"error": "engine-unavailable"}))
        self.assertEqual(self.r["health"]["status"], 200)


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


if __name__ == "__main__":
    unittest.main()
