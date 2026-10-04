"""Run report UI pure-model regressions without a browser or external calls."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReportUITest(unittest.TestCase):
    def test_report_ui_model_contracts(self):
        node = shutil.which("node")
        if node is None:
            if os.environ.get("NAVER_SCREEN_REQUIRE_BROWSER") == "1":
                self.fail("Node.js is required for report UI model tests in CI")
            self.skipTest("Node.js is unavailable")
        result = subprocess.run(
            [node, str(ROOT / "naver_engine/tests/report_ui_model_test.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
