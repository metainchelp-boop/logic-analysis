"""실제 화면 → 중계 → 엔진의 변경분 회귀 시험. 자료·SSO·네이버는 합성이다.

기본은 기존 파일 Store 시험이다. NAVER_VIEW_DELTA_MEMORY=1은 로컬 파일 잠금
환경과 분리한 SQLite 메모리 합성 시험이며 WAL/운영 파일 통합의 증거가 아니다.
시험 제어 주소와 합성 SSO는 이 하니스에만 있고 제품 서버에는 추가하지 않는다.
"""
from __future__ import annotations

from datetime import timedelta
import json
import os
import pathlib
import queue
import socket
import sqlite3
import subprocess
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from naver_engine.tests import test_screen as TS
from naver_engine.tests import test_web as TW
from naver_engine.tests import test_morning as TM
from naver_engine.tests import test_alerts as TA
from naver_engine.tests import test_account_catalog as TC
from naver_engine.tests import test_report_paging as RP
from naver_engine import erp_read as E, store as S
from app.naver_auto import matching as M


SCENARIO = pathlib.Path(__file__).with_name("view_delta_screen_browser.js")
BASELINE = "ac18566f0cadc733b9aa0b8b75bc1bb0681038ce"


class ViewDeltaScreenTest(TS.BrowserTest):
    """모든 변경은 주 스레드의 합성 Store에서 처리한다. 실제 엔진 GET은 그대로다."""

    def setUp(self):
        self.controls = queue.Queue()
        self.baseline_js = None
        if os.environ.get("NAVER_VIEW_DELTA_BASELINE") == "1":
            self.baseline_js = subprocess.check_output(
                ["git", "show", BASELINE + ":backend/naver_page/app.js"], cwd=TS.PAGE.parents[1])
        if os.environ.get("NAVER_VIEW_DELTA_MEMORY") == "1":
            self.memory_uri = "file:view_delta_" + uuid.uuid4().hex + "?mode=memory&cache=shared"
            self.enterContext(patch.object(S, "open_writer", self._memory_writer))
            self.enterContext(patch.object(S, "open_reader", self._memory_reader))
        connect = socket.socket.connect
        def local_only(sock, address):
            if sock.family != socket.AF_UNIX and not (
                    isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1")):
                raise AssertionError("합성 화면 시험은 외부에 연결할 수 없습니다")
            return connect(sock, address)
        self.enterContext(patch.object(socket.socket, "connect", local_only))
        super().setUp()
        self.seed_catalog()
        self.seed_reports()
        snapshot = self.st.inventory_snapshot(self.fc.now())
        self.st.begin_inventory_check(TM.A, snapshot, self.fc.now())
        self.st.record_inventory_check(TM.A, snapshot, self.fc.now(), {"status": "partial", "bizmoney": 4116.83})

    def _memory_writer(self, path, clock=None):
        conn = sqlite3.connect(self.memory_uri, uri=True, isolation_level=None)
        conn.execute("PRAGMA trusted_schema=OFF")
        store = S.Store(conn, path, None, writer=True, clock=clock)
        store._migrate()
        conn.set_authorizer(S._authorizer(S.PHASE_RUN))
        return store

    def _memory_reader(self, path):
        conn = sqlite3.connect(self.memory_uri, uri=True, isolation_level=None)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.set_authorizer(S._authorizer(S.PHASE_READ))
        return S.Store(conn, path, None, writer=False)

    def world(self, **kwargs):
        owners = [TA.owner(11, 100), TA.owner(12, 101), TA.owner(13, None),
                  TA.owner(14, 100), TA.owner(15, 100)]
        super().world(org_owners=owners)

    def make_app(self, **kwargs):
        return super().make_app(owner_verification=True, **kwargs)

    def seed_catalog(self):
        items = [TC.company(pid, "진행중", company_name=TM.shop(pid)) for pid in range(11, 16)]
        self.st.record_account_catalog({"generated_at": self.fc.now().isoformat(), "total": len(items),
            "complete": True, "items": items},
            [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)),
             E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))], self.fc.now())

    def seed_reports(self):
        # 전산 업체 하나의 서로 다른 과거 주간 21개. API는 실제 Store의 최신 판 조회를 사용한다.
        with self.st._tx() as conn:
            for index in range(21):
                period = RP.R.period("weekly", self.fc.now().date() - timedelta(days=7 * (index + 1)))
                payload = RP.payload(period, ready=True)
                conn.execute("""INSERT INTO naver_auto_report_snapshot
                    (report_id,possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
                    VALUES(?,11,?,?,?,?,?,?)""", (index + 1, period.key, payload["revision_fingerprint"],
                    self.fc.now().isoformat(), payload["status"], payload["review_status"],
                    json.dumps(payload, ensure_ascii=False)))

    def _handler(self):
        test, parent = self, super()._handler()
        class Handler(parent):
            def _any(self):
                path = self.path.partition("?")[0]
                if path.startswith("/__test__/"):
                    return self._send(404, (), b"")
                if path.startswith("/__view_delta_test__/"):
                    if self.command != "POST" or self.headers.get("Origin") != test.base:
                        return self._send(403, (), b"")
                    operation = path.rsplit("/", 1)[-1]
                    if operation not in {"add", "correct", "remove", "inventory-correct", "report-correct",
                                         "reports-shrink", "org-stale", "org-fresh", "near-midnight", "next-day"}:
                        return self._send(404, (), b"")
                    done, result = threading.Event(), {}
                    test.controls.put((operation, done, result))
                    if not done.wait(8):
                        return self._send(503, (), b"")
                    return self._send(200 if result.get("ok") else 500,
                        (("Content-Type", "application/json"), ("Cache-Control", "no-store")),
                        json.dumps(result).encode())
                if path == "/naver/sso-bootstrap.js":
                    body = "window.__metaincSso={started:true,legacyPresent:false,consume:()=>Promise.resolve(" + json.dumps(
                        {"code": getattr(test, "entry_code", TW.tok(1)), "codeVerifier": "V" * 42 + "A"}) + ")};"
                    return self._send(200, list(TS.R.PAGE_HEADERS) + [("Content-Type", "application/javascript")], body.encode())
                if path == "/naver/app.js" and test.baseline_js is not None:
                    return self._send(200, list(TS.R.PAGE_HEADERS) + [("Content-Type", "application/javascript")], test.baseline_js)
                if path.startswith("/naver/") and self.command == "GET":
                    file = TS.R.page_file(TS.PAGE, path[len("/naver/"):])
                    if file is not None and file.name == "index.html":
                        body = file.read_bytes().replace(b"<body>", b'<body><p id="syntheticNotice">' +
                            "시험 자료 · 실제 업체·운영 데이터가 아닙니다. 네이버 호출 없이 저장된 합성 자료만 표시합니다.".encode() + b"</p>")
                        return self._send(200, list(TS.R.PAGE_HEADERS) + [("Content-Type", "text/html; charset=utf-8")], body)
                return super()._any()
            do_GET = do_POST = do_HEAD = _any
        return Handler

    def drain_controls(self):
        while True:
            try:
                operation, done, result = self.controls.get_nowait()
            except queue.Empty:
                return
            try:
                self.apply_control(operation)
                result["ok"] = True
            except Exception as error:
                result["error"] = type(error).__name__
            finally:
                done.set()

    def apply_control(self, operation):
        if operation == "near-midnight":
            self.fc._now = self.fc.now().replace(hour=23, minute=59, second=40, microsecond=0)
        elif operation == "next-day":
            self.fc._now += timedelta(seconds=40)
        elif operation in ("org-stale", "org-fresh"):
            self.fc._now += timedelta(seconds=1)
            at = self.fc.now() - (timedelta(hours=27) if operation == "org-stale" else timedelta())
            # 낡은 현재 스냅샷은 공개 수락 경로로 되돌릴 수 없어 합성 fixture에서만 주입한다.
            with self.st._tx() as conn:
                body = TA.org_body(at, owners=[TA.owner(11, 100), TA.owner(12, 101),
                    TA.owner(13, None), TA.owner(14, 100), TA.owner(15, 100)])
                conn.execute("UPDATE naver_auto_org SET generated_at=?, body=?",
                             (at.isoformat(), json.dumps(body, ensure_ascii=False)))
        elif operation == "correct":
            with self.st._tx() as conn:
                conn.execute("UPDATE naver_auto_account_day SET bizmoney=43210 WHERE customer_id=? AND day=?",
                             (TM.A, self.fc.now().date().isoformat()))
        elif operation == "reports-shrink":
            with self.st._tx() as conn:
                # 삭제 권한을 풀지 않는다. 현재 전산 목록 밖으로 이동한 과거 판은 공개 목록에서 제외된다.
                conn.execute("UPDATE naver_auto_report_snapshot SET possibility_id=999 WHERE report_id>1")
        elif operation == "inventory-correct":
            with self.st._tx() as conn:
                conn.execute("UPDATE naver_auto_inventory_check SET bizmoney=54321 WHERE customer_id=?", (TM.A,))
        elif operation == "report-correct":
            with self.st._tx() as conn:
                row = conn.execute("SELECT payload_json FROM naver_auto_report_snapshot WHERE report_id=21").fetchone()
                payload = json.loads(row[0])
                payload["totals"]["spend"] = 9999
                payload["revision_no"] = 2
                conn.execute("""INSERT INTO naver_auto_report_snapshot
                    (report_id,possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,
                     payload_json)
                    SELECT 1000,possibility_id,period_key,?,generated_at,status,review_status,?
                    FROM naver_auto_report_snapshot WHERE report_id=21""",
                    ("f" * 64, json.dumps(payload, ensure_ascii=False)))
        else:
            # 원천 시각을 유지해 행 추가/삭제 외에 짝 판정이 함께 바뀌지 않게 한다.
            stage_at = self.st.stage_as_of()
            with self.st._tx() as conn:
                if operation == "add":
                    conn.execute("""INSERT OR REPLACE INTO naver_auto_prospect
                        (possibility_id,name,stage_key,latest_end_date,end_unreadable,stage_conflict,present,
                         first_seen_at,last_seen_at,stage_synced_at,absent_since)
                        VALUES(15,?,'진행중',NULL,0,0,1,?,?,?,NULL)""",
                        (TM.shop(15), stage_at.isoformat(), stage_at.isoformat(), stage_at.isoformat()))
                else:
                    conn.execute("UPDATE naver_auto_prospect SET present=0 WHERE possibility_id=15")

    def test_screen_in_real_browser(self):
        cfg = {"base": self.base, "now": self.fc.now().isoformat(),
               "staffCode": TW.tok(3),
               "baseline": self.baseline_js is not None,
               "executablePath": os.environ.get("NAVER_SCREEN_CHROMIUM") or None,
               "shots": os.environ.get("NAVER_SCREEN_SHOTS") or None}
        proc = subprocess.Popen([self.node, str(SCENARIO), json.dumps(cfg)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 120
        while proc.poll() is None and time.monotonic() < deadline:
            self.drain_controls()
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, (out + err)[-10000:])
        self.assertIn("view-delta-screen-ok", out)
        self.assertEqual(self.stray, [])
        print(out.strip())


if __name__ == "__main__":
    unittest.main()
