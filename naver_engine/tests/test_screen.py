"""S13 시험 — /naver/ 관제 화면 파일(``backend/naver_page``).

두 갈래.
1. **글자 규칙**(언제나 돈다 · 네트워크 0) — 인라인 스크립트 0 · 인라인 손잡이(on…=) 0 · 인라인 스타일 속성 0 ·
   HTML 로 끼워 넣기(innerHTML 등) 0 · 바깥 주소 0 · 오래 두는 저장소 0 · 토큰 이름 · 끝나기 10분 전 갱신 · 1시간 쉼 · sso 를 가장 먼저
   지움 · 화면 주소 목록이 ③ 입구(``naver_relay.PAGE_SCREENS``)와 같음 · 엔진 알림 링크(``alerts.LINK_*``)가 모두 화면으로 열림.
2. **진짜 브라우저**(Chromium · Playwright · Node) — 앞 서버(화면 파일 = ③ 입구 규칙 · API = ③ 중계 ``naver_relay.relay``)
   → 진짜 엔진 화면 API(가짜 ① · 가짜 저장소) 를 띄우고 ``screen_browser.js`` 가 열고 누른다. 색·숫자·줄이 서버와 같은지,
   sso 가 주소창·뒤 요청·Referer 에 남지 않는지, 바깥 요청·CSP 위반·화면 오류가 0 인지, 👀·🙈·기준값 저장이 서버에
   닿는지, 토큰 끝 시각 기준 갱신(새로 고침 뒤에도) · 오래 쉼 · 세션 끝 화면 · 빠른 범위 바꾸기 · 옮겨 간 뒤 늦은 답까지. Node·Playwright·Chromium 이 없으면 건너뛴다 —
   **머지 전에는 ``NAVER_SCREEN_REQUIRE_BROWSER=1`` 로 건너뜀을 실패로** 만든다(S12 앱 시험과 같은 약속).
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import re
import shutil
import socketserver
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.parse
from datetime import timedelta

from naver_engine.tests import test_web as TW   # backend 경로를 sys.path 에 넣는다 — 먼저 불러야 한다
from naver_engine import alerts as AL  # noqa: E402
from naver_engine import store as S  # noqa: E402
from naver_engine.tests import test_relay_engine as TR  # noqa: E402

from app import naver_relay as R  # noqa: E402

PAGE = TW.BACKEND / "naver_page"
HTML = (PAGE / "index.html").read_text(encoding="utf-8")
JS = (PAGE / "app.js").read_text(encoding="utf-8")
CSS = (PAGE / "app.css").read_text(encoding="utf-8")
SCENARIO = pathlib.Path(__file__).with_name("screen_browser.js")
REQUIRE = os.environ.get("NAVER_SCREEN_REQUIRE_BROWSER") == "1"


def _code(js: str) -> str:
    """주석을 뺀 코드(글자 규칙이 설명 글에 걸리지 않게) — 문자열 안의 // 는 남긴다(대충: 줄 주석은 줄 앞 공백 뒤만)."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return "\n".join(line for line in js.splitlines() if not line.lstrip().startswith("//"))


CODE = _code(JS)
CSS_CODE = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


class TextRulesTest(unittest.TestCase):
    def test_no_inline_script_or_handlers_or_styles(self):
        scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", HTML, flags=re.S | re.I)
        self.assertEqual(len(scripts), 1)
        attrs, body = scripts[0]
        self.assertEqual(body.strip(), "")
        self.assertIn('src="/naver/app.js"', attrs)
        self.assertNotRegex(HTML, r"\son[a-z]+\s*=", "인라인 손잡이(onclick= …)")
        self.assertNotRegex(HTML, r"\sstyle\s*=", "인라인 스타일 속성")
        self.assertNotIn("javascript:", HTML.lower())

    def test_absolute_same_origin_paths_only(self):
        refs = re.findall(r'\b(?:src|href)="([^"]*)"', HTML)
        self.assertTrue(refs)
        for ref in refs:
            self.assertRegex(ref, r"^/naver/[a-z0-9_.-]+$", ref)
            p = R.page_file(PAGE, ref[len("/naver/"):])
            self.assertIsNotNone(p, ref)   # 입구가 실제로 내주는 파일(확장자·폴더 규칙)
        for text, name in ((HTML, "html"), (CODE, "js"), (CSS_CODE, "css"), (CSS, "css 설명 포함")):
            self.assertNotRegex(text, r"(?i)\b(?:https?|wss?|ftp):", name)
            self.assertNotRegex(text, r"(?<![A-Za-z0-9_])//[A-Za-z0-9.-]+\.[a-z]{2,}", name)   # //host 모양
        self.assertNotIn("@import", CSS_CODE)
        self.assertNotRegex(CSS_CODE, r"url\(", "css url()")

    def test_no_html_injection_or_eval(self):
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
                    "setTimeout('", 'setTimeout("', "setInterval('", 'setInterval("', "srcdoc", ".cookie"):
            self.assertNotIn(bad, CODE, bad)
        # 속성은 h() 한 곳으로만 · style 속성은 거절(CSP 인라인 스타일 속성에 기대지 않게) · href/src 를 만들지 않는다
        self.assertIn("else if (k === 'style') throw new Error('style');", CODE)
        self.assertNotRegex(CODE, r"setAttribute\(\s*['\"](?:href|src|srcdoc|on[a-z]+)['\"]")
        self.assertNotRegex(CODE, r"\.(?:href|src)\s*=")

    def test_storage_and_token(self):
        self.assertNotIn("localStorage", CODE)
        self.assertNotIn("indexedDB", CODE)
        self.assertEqual(re.findall(r"var KEY = '([^']+)';", CODE), ["naverWatch.session"])
        self.assertNotIn("getItem('token')", CODE)
        # 갱신은 토큰 끝 시각에서 센다(페이지를 연 때가 아니라 · 새로 고침해도) · 1시간 넘게 손대지 않으면 이 창의 로그인을 끝낸다
        self.assertIn("var REFRESH_AHEAD_MS = 10 * 60 * 1000;", CODE)
        self.assertIn("var IDLE_MS = 60 * 60 * 1000;", CODE)
        self.assertIn("state.timer = setInterval(tick, TICK_MS);", CODE)
        tick = CODE[CODE.index("function tick() {"):CODE.index("function scheduleRefresh")]
        self.assertIn("if (now - state.lastInput >= IDLE_MS) { lost('idle'); return; }", tick)
        self.assertIn("if (now >= s.exp) { lost(); return; }", tick)
        self.assertIn("if (s.exp - now <= REFRESH_AHEAD_MS && now >= state.retryAt) refresh();", tick)
        self.assertLess(tick.index("IDLE_MS"), tick.index("s.exp"))   # 오래 쉼을 먼저(끝난 토큰보다)
        sched = CODE[CODE.index("function scheduleRefresh() {"):CODE.index("document.addEventListener('visibilitychange'")]
        self.assertIn("tick();", sched)                                 # 새로 고침 · 잠자기 뒤 바로 한 번
        for ev in ("'pointerdown'", "'keydown'"):
            self.assertIn(ev, CODE)
        self.assertIn("state.lastInput = Date.now();", CODE)
        lost = CODE[CODE.index("function lost(kind) {"):CODE.index("function refresh()")]
        for part in ("dropSession();", "state.me = null;", "clearInterval(state.timer);"):
            self.assertIn(part, lost)
        # 부르는 곳은 한 곳 — /api/naver-auto 아래만 · 쿠키를 싣지 않는다 · Referer 를 싣지 않는다
        self.assertEqual(CODE.count("fetch("), 1)
        self.assertIn("return fetch(API + path, init)", CODE)
        self.assertIn("var API = '/api/naver-auto';", CODE)
        for part in ("credentials: 'omit'", "referrerPolicy: 'no-referrer'", "cache: 'no-store'"):
            self.assertIn(part, CODE)

    def test_sso_removed_first(self):
        """sso 는 가장 먼저 꺼내 지운다 — 시작 함수의 첫 줄이 takeSso() 이고 그 안에서 replaceState."""
        start = CODE[CODE.index("function start() {"):]
        first = start.split("\n")[1].strip()
        self.assertTrue(first.startswith("var sso = takeSso();"), first)
        take = CODE[CODE.index("function takeSso() {"):CODE.index("function ApiError")]
        self.assertIn("history.replaceState(", take)
        self.assertNotIn("api(", take)
        self.assertNotIn("fetch(", take)
        # sso 를 저장하지 않는다 — sessionStorage 에 쓰는 곳은 saveSession 한 곳(토큰·시각만)
        self.assertEqual(CODE.count("sessionStorage.setItem("), 1)
        save = CODE[CODE.index("function saveSession(j) {"):CODE.index("function dropSession")]
        self.assertNotIn("sso", save)

    def test_screen_names_match_entrance(self):
        """화면이 받는 주소 목록 = ③ 입구가 index.html 을 주는 목록(둘이 어긋나면 누른 링크가 404)."""
        m = re.search(r"var SCREEN = /\^\\/naver\\/\(\?:\(([a-z|]+)\)\|clients\\/\(\[1-9\]\[0-9\]\{0,17\}\)\)\?\$/;", CODE)
        self.assertIsNotNone(m, "SCREEN 모양")
        js_names = set(m.group(1).split("|"))
        py = re.fullmatch(r"\(\?:([a-z|]+)\|clients/\[1-9\]\[0-9\]\{0,17\}\)", R.PAGE_SCREENS.pattern)
        self.assertIsNotNone(py, R.PAGE_SCREENS.pattern)
        self.assertEqual(js_names, set(py.group(1).split("|")))

    def test_alert_links_open_screen(self):
        """엔진이 🔔·비서방에 싣는 링크(``alerts.LINK_*``)는 모두 입구에서 화면으로 열린다."""
        links = [v for k, v in vars(AL).items() if k.startswith("LINK_") and isinstance(v, str)]
        self.assertTrue(links)
        index = (PAGE / "index.html").resolve()
        for link in links:
            self.assertTrue(link.startswith("/naver/"), link)
            self.assertEqual(R.page_file(PAGE, link[len("/naver/"):]), index, link)

    def test_colors_only_from_server(self):
        """화면은 색을 계산하지 않는다 — 신호 색은 서버 판정(verdict.color) · 이슈 등급(severity) 글자로만."""
        colors = re.findall(r"'sig ' \+ ([A-Za-z_.()' ]+?)(?:[,)])", CODE)
        self.assertTrue(colors)
        for expr in colors:
            self.assertRegex(expr.strip(), r"^(?:v\.color|sev|info \? 'info' : g\.sev|\(info \? 'info' : g\.sev\)|"
                                            r"\(it\.severity === 'URGENT' \? 'red' : 'yellow'\))$", expr)
        # 판정 글자(needs_attention)는 서버 값을 읽기만 — 화면이 만들어 넣지 않는다
        self.assertNotRegex(CODE, r"needs_attention\s*=[^=]")
        self.assertNotRegex(CODE, r"\.color\s*=[^=]")
        # 광고주 한 장 숫자도 서버 값 — 계정별 기록(history)을 화면이 다시 더하지 않는다
        now = CODE[CODE.index("function renderNow() {"):CODE.index("function openOf(")]
        self.assertNotIn("history", now)
        for key in ("c.yday_spend", "c.bizmoney", "c.yday_imp", "c.yday_clk", "c.days"):
            self.assertIn(key, now)

    def test_races_and_double_submit(self):
        """늦게 온 옛 응답이 새 것을 덮지 않고 · 같은 일을 두 번 보내지 않는다(검토 scope-race · double-submit)."""
        self.assertIn("state.selection = this.value; state.gen++; openWatch();", CODE)
        watch = CODE[CODE.index("function openWatch() {"):CODE.index("function fail(e)")]
        self.assertIn("if (gen !== state.gen || sel !== state.selection) return;", watch)
        reload = CODE[CODE.index("function reload() {"):CODE.index("var except = null;")]
        self.assertIn("if (r.screen === 'client') { state.gen++; openClient(r.id); }", reload)
        self.assertIn("else if (r.screen === 'watch') { state.gen++; openWatch(); }", reload)
        self.assertNotIn("else openWatch()", reload)                   # 다른 화면으로 옮겨 갔으면 관제로 끌고 오지 않는다
        for key in ("once('issue:' + i.issue_id", "once('link:' + r.ref", "once('th'", "once('bell-all'"):
            self.assertIn(key, CODE)
        once = CODE[CODE.index("function once(key, btn, run) {"):CODE.index("function toast(t)")]
        self.assertIn("if (state.busy[key]) return;", once)
        self.assertIn("btn.disabled = true", once)


# ── 진짜 브라우저 ─────────────────────────────────────────────────────
def _node_env():
    node = shutil.which("node")
    if not node or not SCENARIO.exists():
        return None, None
    try:
        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        root = ""
    candidates = [p for p in (os.environ.get("NODE_PATH", ""), root) if p]
    for c in candidates:
        if (pathlib.Path(c) / "playwright").exists():
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "PLAYWRIGHT_BROWSERS_PATH", "TMPDIR", "LANG")}
            env["NODE_PATH"] = c
            return node, env
    return None, None


class _Front(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class BrowserTest(TW.WebBase):
    """앞 서버(옆 스레드) → ③ 중계 → 엔진(이 스레드 · 저장소 연결이 이 스레드 것) · 브라우저(Node 하위 프로세스)."""

    def setUp(self):
        node, env = _node_env()
        if node is None:
            if REQUIRE:
                self.fail("Node·Playwright·Chromium 이 없어 화면 시험을 못 돌렸습니다(NAVER_SCREEN_REQUIRE_BROWSER=1)")
            self.skipTest("Node·Playwright 없음 — 화면 브라우저 시험 건너뜀")
        self.node, self.node_env = node, env
        super().setUp()
        tmp = tempfile.mkdtemp(prefix="screen-")
        self.addCleanup(shutil.rmtree, tmp, True)
        sock = os.path.join(tmp, "engine.sock")
        self.engine = TR._UnixWSGIServer(sock, TR._UnixHandler)
        self.engine.mark = True
        self.engine.set_app(lambda env_, sr: self.app(env_, sr))
        self.engine.timeout = 0.05
        self.addCleanup(self.engine.server_close)
        self.relay_env = {R.ENV_SWITCH: "on", R.ENV_ENGINE: "unix:" + sock}
        self.stray = []
        self.front = _Front(("127.0.0.1", 0), self._handler())
        self.addCleanup(self.front.server_close)
        t = threading.Thread(target=self.front.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        t.start()
        self.addCleanup(self.front.shutdown)
        self.base = f"http://127.0.0.1:{self.front.server_address[1]}"
        # 사람 넷 — ① my-profile 가짜(대표 · 팀장 · 직원 둘) · ① 이 거절하는 토큰 하나
        for tok, idx, mgr in ((TW.tok(1), 0, True), (TW.tok(2), 1, True), (TW.tok(3), 100, False), (TW.tok(4), 101, False),
                              (TW.tok(5), 0, True), (TW.tok(6), 0, True), (TW.tok(7), 101, False), (TW.tok(8), 0, True)):
            teams = ((0, None),) if idx == 0 else ((11, 10), (10, 0))
            self.erp.person(tok, idx, manager=mgr, teams=teams)
        self.st.record_alert(S.ALERT_DIGEST, TW.TODAY, "compose", "digest", (), "/naver/issues",
                             [{"emp_idx": 0, "severity": "URGENT", "params": {"red": 1, "yellow": 2}}], self.fc.now())

    def _handler(self):
        test = self

        class H(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _send(self, status, headers, body):
                self.send_response(status)
                for k, v in headers:
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _any(self):
                path, _sep, query = self.path.partition("?")
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else None
                if path.startswith("/__test__/advance"):
                    minutes = int(urllib.parse.parse_qs(query).get("minutes", ["0"])[0])
                    test.fc._now = test.fc._now + timedelta(minutes=minutes)
                    return self._send(204, (), b"")
                if path.startswith(R.PREFIX + "/"):
                    inc = R.Incoming(method=self.command, sub=path[len(R.PREFIX):], query=query,
                                     authorization=tuple(self.headers.get_all("Authorization") or ()),
                                     content_type=self.headers.get("Content-Type"), body=body, real_ip=None,
                                     peer=self.client_address[0], origin=self.headers.get("Origin"),
                                     host=self.headers.get("Host"), fetch_site=self.headers.get("Sec-Fetch-Site"))
                    out = R.relay(inc, test.relay_env, total_timeout=10)
                    return self._send(out.status, out.headers, out.body)
                if path.startswith("/naver/") and self.command in ("GET", "HEAD"):
                    p = R.page_file(PAGE, urllib.parse.unquote(path[len("/naver/"):]))
                    if p is not None:
                        return self._send(200, list(R.PAGE_HEADERS) + [("Content-Type", R.page_type(p))], p.read_bytes())
                    return self._send(404, (("Referrer-Policy", "no-referrer"), ("Cache-Control", "no-store")), b"")
                test.stray.append(self.command + " " + path)   # ③ 다른 곳으로 새는 요청(favicon · 루트 등)
                return self._send(404, (), b"")

            do_GET = do_POST = do_HEAD = _any

        return H

    def test_screen_in_real_browser(self):
        cfg = {"base": self.base, "red": self.issue_of(11, "red")["issue_id"], "yellow": self.issue_of(12, "yellow")["issue_id"],
               "sso": {"ceo": TW.tok(1), "lead": TW.tok(2), "s100": TW.tok(3), "s101": TW.tok(4), "ceo2": TW.tok(5),
                       "ceo3": TW.tok(6), "idle101": TW.tok(7), "ceo4": TW.tok(8), "bad": TW.bad(9)},
               "shots": os.environ.get("NAVER_SCREEN_SHOTS") or None}   # 화면 사진(사람이 눈으로 볼 때만 · 예시 자료)
        proc = subprocess.Popen([self.node, str(SCENARIO), json.dumps(cfg)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=self.node_env)
        deadline = time.monotonic() + 240
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()            # 엔진은 이 스레드에서 한 번에 하나씩(저장소 연결이 이 스레드 것)
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=30)
        lines = [ln for ln in out.splitlines() if ln.startswith("[")]
        self.assertTrue(lines, "브라우저 시험 출력 없음:\n" + err[-4000:])
        results = json.loads(lines[-1])
        failed = [r for r in results if not r["pass"]]
        self.assertEqual(failed, [], json.dumps(failed, ensure_ascii=False, indent=1)[:6000])
        self.assertGreaterEqual(len(results), 110, len(results))
        self.assertEqual(self.stray, [], "화면이 /naver/·/api/naver-auto 밖을 불렀다")
        # sso 원문(① 토큰)은 엔진 저장소 어디에도 없다
        blob = pathlib.Path(self.path).read_bytes()
        for sso in cfg["sso"].values():
            self.assertNotIn(sso.encode("ascii"), blob)


if __name__ == "__main__":
    unittest.main()
