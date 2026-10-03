"""실제 화면→중계→WSGI의 수집기 상태 회귀. 합성 메모리 DB·네이버 호출 0.

NAVER_RUNTIME_SCREEN_BASELINE=1은 직전 운영 화면으로 새 계약의 RED를 재현한다.
직접 --preview 실행 시 localhost 합성 직원 화면을 제공한다. 운영 자료/자격은 없다.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from naver_engine.tests import test_screen as TS, test_relay_engine as TR
from naver_engine.tests.test_catalog_links import make_fixture
from naver_engine import store as S, session as SE, web as WEB
from naver_engine.credentials import Secret

BASELINE = "01344b145d0b679a6ee730d7fa4b5990278dd654"
SCENARIO = Path(__file__).with_name("runtime_status_screen_browser.js")


class RuntimeStatusScreenTest(unittest.TestCase):
    def setUp(self):
        self.node, self.node_env = TS._node_env()
        if self.node is None:
            if TS.REQUIRE:
                self.fail("Node·Playwright가 없어 상태 화면 시험을 실행하지 못했습니다")
            self.skipTest("Node·Playwright 없음")
        def local_only(original):
            def guarded(sock, address):
                if sock.family != socket.AF_UNIX and not (
                        isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1")):
                    raise AssertionError("합성 상태 화면은 외부로 연결할 수 없습니다")
                return original(sock, address)
            return guarded
        for method in ("connect", "connect_ex"):
            self.enterContext(patch.object(socket.socket, method, local_only(getattr(socket.socket, method))))
        if getattr(self, "preview", False):
            # 실제 브라우저의 벽시계와 같은 시각으로 원천·세션을 처음부터 합성한다.
            with patch("naver_engine.tests.test_performance_batch_reads.NOW", datetime.now().astimezone()):
                fixture = make_fixture(accounts=2, managed=1, campaigns=0)
        else:
            fixture = make_fixture(accounts=2, managed=1, campaigns=0)
        self.fixture, self.st, self.fc = fixture, fixture.store, fixture.clock
        self.addCleanup(self.st.close)
        self.st._conn.execute("INSERT OR REPLACE INTO naver_auto_meta VALUES('schema_version','11')")
        self.st.synchronize_management(self.fc.now())
        self.signer = SE.TokenSigner(Secret("runtime-synthetic-" * 3))
        self.staff_session = {"token": self.signer.issue(100, self.fc.now()),
            "exp": int(self.fc.now().timestamp() * 1000) + 3600000, "ends": None, "narrowed": False}
        self.writes, self.reads, self.stray = [], [], []
        def open_read():
            conn = sqlite3.connect(":memory:", isolation_level=None)
            self.st._conn.backup(conn)
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.execute("PRAGMA query_only=ON")
            conn.set_authorizer(S._authorizer(S.PHASE_READ))
            return S.Store(conn, ":memory:", None, writer=False, clock=self.fc.now)
        def write(_fn):
            self.writes.append("unexpected-write")
            raise AssertionError("상태 조회는 쓰기를 요청할 수 없습니다")
        self.app = WEB.App(open_read=open_read, write=write, signer=self.signer, profiles=None,
            clock=self.fc.now, owner_verification=True, verified_linking=True,
            runtime_status=lambda: {"state":"collecting", "indicator":"green", "reason_code":"COLLECTING",
                "verified_at":self.fc.now().isoformat(), "valid_for_seconds":25, "retry_at":None})
        folder = tempfile.mkdtemp(prefix="runtime-screen-")
        self.addCleanup(shutil.rmtree, folder, True)
        sock = str(Path(folder) / "engine.sock")
        self.engine = TR._UnixWSGIServer(sock, TR._UnixHandler)
        self.engine.mark = True
        def app(env, start):
            self.reads.append((env["REQUEST_METHOD"], env["PATH_INFO"], env.get("QUERY_STRING", "")))
            return self.app(env, start)
        self.engine.set_app(app)
        self.engine.timeout = 0.05
        self.addCleanup(self.engine.server_close)
        self.relay_env = {TS.R.ENV_SWITCH:"on", TS.R.ENV_ENGINE:"unix:" + sock}
        self.old_files = {}
        if os.environ.get("NAVER_RUNTIME_SCREEN_BASELINE") == "1":
            self.old_files = {name:subprocess.check_output(["git","show",BASELINE+":backend/naver_page/"+name],
                cwd=TS.PAGE.parents[1]) for name in ("index.html","app.js","app.css")}
        self.front = TS._Front(("127.0.0.1", 0), self._handler())
        self.addCleanup(self.front.server_close)
        self.base = "http://127.0.0.1:" + str(self.front.server_address[1])
        threading.Thread(target=self.front.serve_forever, kwargs={"poll_interval":0.05}, daemon=True).start()
        self.addCleanup(self.front.shutdown)

    def _handler(self):
        test, parent = self, TS.BrowserTest._handler(self)
        class Handler(parent):
            def _any(self):
                path = self.path.partition("?")[0]
                if path == "/naver/sso-bootstrap.js" and self.command == "GET":
                    body = "window.__metaincSso={started:false,legacyPresent:false};sessionStorage.setItem(" + \
                        json.dumps("naverWatch.session") + "," + json.dumps(json.dumps(test.staff_session)) + ");"
                    return self._send(200, list(TS.R.PAGE_HEADERS) + [("Content-Type","application/javascript")], body.encode())
                if path.startswith("/naver/") and self.command == "GET":
                    file = TS.R.page_file(TS.PAGE, path[len("/naver/"):])
                    if file is not None and (file.name == "index.html" or file.name in test.old_files):
                        body = test.old_files.get(file.name, file.read_bytes())
                        if file.name == "index.html":
                            body = body.replace(b"<body>", b'<body><p id="syntheticNotice">' +
                                "시험 자료 · 실제 업체·운영 데이터가 아닙니다. 네이버 호출은 하지 않습니다.".encode() + b"</p>")
                        return self._send(200, list(TS.R.PAGE_HEADERS) + [("Content-Type",TS.R.page_type(file))], body)
                if path.startswith("/__test__/"):
                    return self._send(404, (), b"")
                return super()._any()
            do_GET = do_POST = do_HEAD = _any
        return Handler

    def test_runtime_status_in_real_browser(self):
        changes = self.st._conn.total_changes
        cfg = {"base":self.base, "now":self.fc.now().isoformat(),
            "executablePath":os.environ.get("NAVER_SCREEN_CHROMIUM") or None,
            "shots":os.environ.get("NAVER_SCREEN_SHOTS") or None}
        proc = subprocess.Popen([self.node,str(SCENARIO),json.dumps(cfg)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 100
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, err[-6000:])
        self.assertIn("runtime-status-screen-ok", out)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.stray, [])
        self.assertEqual(self.st._conn.total_changes, changes)
        self.assertEqual(self.fixture.http.calls, [])
        self.assertIn(("GET",WEB.PREFIX+"/health","runtime=1"),self.reads)
        self.assertTrue(all(method == "GET" for method,_path,_query in self.reads))


if __name__ == "__main__":
    if "--preview" not in sys.argv:
        unittest.main()
    else:
        test = RuntimeStatusScreenTest()
        test.preview = True
        try:
            test.setUp()
            print(json.dumps({"synthetic_preview":test.base+"/naver/dashboard","staff":True,
                "production_data":False,"naver_requests":0}),flush=True)
            while True:
                test.engine.handle_request()
        except KeyboardInterrupt:
            pass
        finally:
            test.doCleanups()
