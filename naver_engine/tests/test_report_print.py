"""Native print guards; offline synthetic DOM and browser, without authoring PDF files."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ReportPrintTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is required for native print platform tests")
    def test_native_print_platform_guards(self):
        result = subprocess.run([shutil.which("node"), "--test", "naver_engine/tests/report_print.test.js"],
                                cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_native_print_browser_public_layouts_and_csp(self):
        from naver_engine.tests.test_screen import _node_env
        node, env = _node_env()
        if not node:
            self.skipTest("Existing Playwright/Chromium installation is required; no download is performed")
        if os.environ.get("NAVER_REPORT_BROWSER"):
            env["NAVER_REPORT_BROWSER"] = os.environ["NAVER_REPORT_BROWSER"]
        result = subprocess.run([node, "naver_engine/tests/report_print_browser.test.js"], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
