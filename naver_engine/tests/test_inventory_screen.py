"""합성 전산/네이버 계정으로 실제 화면→중계→엔진까지 검사한다."""
import json
import os
from pathlib import Path
import subprocess
import time

from naver_engine import erp_read as E
from naver_engine.tests import test_screen as TS, test_web as TW, test_morning as TM
from app.naver_auto import matching as M


class InventoryScreenTest(TS.BrowserTest):
    def make_app(self, **kw):
        return super().make_app(owner_verification=True, **kw)

    def test_screen_in_real_browser(self):
        items = [{"possibility_id": pid, "company_name": TM.NAMES[cid], "stage": stage,
                  "stage_known": True, "stage_hidden": False}
                 for pid, cid, stage in ((11, TM.A, "계약 만료"), (12, TM.B, "환불 완료"))]
        self.st.record_account_catalog({"generated_at": self.fc.now().isoformat(), "total": 2,
                                        "complete": True, "items": items},
                                       [E.NaverIdRow(11, M.VENDOR_NAVER, str(TM.A)),
                                        E.NaverIdRow(12, M.VENDOR_NAVER, str(TM.B))], self.fc.now())
        cfg = {"base": self.base, "ceo": TW.tok(1), "staff": TW.tok(3), "now": self.fc.now().isoformat(),
               "shots": os.environ.get("NAVER_SCREEN_SHOTS") or None}
        proc = subprocess.Popen([self.node, str(Path(__file__).with_name("inventory_screen_browser.js")), json.dumps(cfg)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 90
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, err[-3000:])
        self.assertIn("inventory-screen-ok", out)
        self.assertEqual(self.stray, [])
