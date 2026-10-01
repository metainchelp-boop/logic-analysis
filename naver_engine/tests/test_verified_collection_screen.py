"""실제 화면→중계→엔진의 좁은 연결/조회 경로. 외부 네트워크·운영자료 없음."""
import json
from pathlib import Path
import subprocess
import time

from naver_engine.tests import test_screen as TS
from naver_engine.tests import test_web as TW


class VerifiedCollectionScreenTest(TS.BrowserTest):
    def make_app(self, **kw):
        self.collection_requests = []
        def request(actor):
            self.collection_requests.append(actor)
            return {'id': 17, 'status': 'accepted', 'codes': []}
        return super().make_app(owner_verification=True, verified_linking=True,
                                request_collection=request,
                                collection_status=lambda: {'id': None, 'status': 'idle', 'codes': []}, **kw)

    def test_screen_in_real_browser(self):
        cfg = {'base': self.base, 'code': TW.tok(1), 'now': self.fc.now().isoformat()}
        before = self.st.issues(), self.st.thresholds()
        scenario = Path(__file__).with_name('verified_collection_browser.js')
        proc = subprocess.Popen([self.node, str(scenario), json.dumps(cfg)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 90
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, err[-3000:])
        self.assertIn('verified-collection-screen-ok', out)
        self.assertEqual(self.stray, [])
        self.assertEqual(self.collection_requests, [0])
        self.assertEqual(before, (self.st.issues(), self.st.thresholds()))
