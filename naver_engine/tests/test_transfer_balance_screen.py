"""이관 잔액·전산 진입의 loopback 합성 브라우저 시험을 기본 discovery에 포함한다."""
import os
from pathlib import Path
import subprocess
import unittest
from naver_engine.tests.test_screen import _node_env


class TransferBalanceScreenTest(unittest.TestCase):
    def test_transfer_balance_in_browser(self):
        node, env = _node_env()
        if node is None:
            if os.environ.get("NAVER_SCREEN_REQUIRE_BROWSER") == "1":
                self.fail("Node·Playwright가 없어 합성 브라우저 시험을 실행하지 못했습니다")
            self.skipTest("Node·Playwright 없음")
        if os.environ.get("NAVER_SCREEN_SHOTS"):
            env["NAVER_SCREEN_SHOTS"] = os.environ["NAVER_SCREEN_SHOTS"]
        if os.environ.get("NAVER_SCREEN_CHROMIUM"):
            env["NAVER_SCREEN_CHROMIUM"] = os.environ["NAVER_SCREEN_CHROMIUM"]
        script = Path(__file__).resolve().parents[2] / "tests/transfer_balance_browser.test.js"
        result = subprocess.run([node, "--test", str(script)],capture_output=True,text=True,env=env,timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("transfer-balance-screen-ok",result.stdout)
