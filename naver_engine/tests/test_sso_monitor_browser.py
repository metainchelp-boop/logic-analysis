"""메모리 응답만 사용하는 실제 Chromium의 referrer 없는 SSO 회귀."""
from pathlib import Path
import subprocess
import unittest

from naver_engine.tests import test_screen as TS


class SsoMonitorBrowserTest(unittest.TestCase):
    def test_real_opener_origin_and_pkce_without_referrer(self):
        node, env = TS._node_env()
        if node is None:
            if TS.REQUIRE:
                self.fail("Node·Playwright가 없어 SSO 브라우저 시험을 실행하지 못했습니다")
            self.skipTest("Node·Playwright 없음")
        scenario = Path(__file__).resolve().parents[2] / "tests/naver_sso_monitor_browser.test.js"
        result = subprocess.run([node, "--test", str(scenario)], capture_output=True,
                                text=True, timeout=45, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
