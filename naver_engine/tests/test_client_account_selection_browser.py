"""로컬 합성 ERP/SQLite·실제 화면 JS의 계정 전환 경합 시험. 운영 서버를 사용하지 않는다."""
import json
import pathlib
import subprocess
import time
from naver_engine.tests import test_screen as TS
from naver_engine.tests import test_web as TW
from naver_engine.tests import test_client_account_selection as CS

class ClientAccountBrowserTest(TS.BrowserTest):
    def setUp(self):
        super().setUp()
        CS.add_split_accounts(self)

    def test_account_selector_loading_races_errors_and_navigation(self):
        cfg = {'base': self.base, 'sso': TW.tok(1), 'a': CS.key(TW.A), 'e': CS.key(CS.E)}
        proc = subprocess.Popen([self.node, str(pathlib.Path(__file__).with_name('client_account_browser.js')), json.dumps(cfg)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 90
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        lines = [ln for ln in out.splitlines() if ln.startswith('[')]
        self.assertTrue(lines, err[-4000:])
        results = json.loads(lines[-1])
        self.selector_checks = results
        self.assertEqual([r for r in results if not r['pass']], [], json.dumps(results, ensure_ascii=False))
        self.assertGreaterEqual(len(results), 14)
        self.assertEqual(self.stray, [])
