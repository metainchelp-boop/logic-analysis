"""합성 로컬 서버의 관제 필터·대시보드 화면 동작을 검사한다."""
import json
import os
from pathlib import Path
import subprocess
import time

from naver_engine.tests import test_screen as TS, test_web as TW


class DashboardScreenTest(TS.BrowserTest):
    def test_screen_in_real_browser(self):
        cfg = {"base": self.base, "code": TW.tok(1), "now": self.fc.now().isoformat(),
               "shots": os.environ.get("NAVER_SCREEN_SHOTS") or None}
        scenario = Path(__file__).with_name("dashboard_screen_browser.js")
        proc = subprocess.Popen([self.node, str(scenario), json.dumps(cfg)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 90
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, err[-6000:])
        self.assertIn("dashboard-screen-ok", out)
        self.assertEqual(self.stray, [])
