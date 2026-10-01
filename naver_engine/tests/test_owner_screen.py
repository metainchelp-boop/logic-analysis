"""기존 S13 실제 Chromium/중계/엔진 도우미를 대표 읽기 전용 모드로 재사용한다."""
import json
from pathlib import Path
import subprocess
import time

from naver_engine.tests import test_screen as TS
from naver_engine.tests import test_web as TW


class OwnerScreenTest(TS.BrowserTest):
    def make_app(self, **kw):
        return super().make_app(owner_verification=True, **kw)

    def test_screen_in_real_browser(self):
        cfg = {'base': self.base, 'code': TW.tok(1), 'now': self.fc.now().isoformat()}
        before = (self.st.issues(), self.st.link_decisions(), self.st.thresholds())
        scenario = Path(__file__).with_name('owner_screen_browser.js')
        proc = subprocess.Popen([self.node, str(scenario), json.dumps(cfg)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 90
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, err[-3000:])
        self.assertIn('owner-screen-ok:', out)
        self.assertEqual(self.stray, [])
        self.assertEqual(before, (self.st.issues(), self.st.link_decisions(), self.st.thresholds()))
