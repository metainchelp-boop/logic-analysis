"""Actual JS route/reentry cache and authority guards, synthetic promises only."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


class ViewCacheBudgetTest(unittest.TestCase):
    def test_actual_frontend_reentry_and_bounded_cache_guards(self):
        node = shutil.which("node")
        if node is None:
            if os.environ.get("NAVER_SCREEN_REQUIRE_BROWSER") == "1":
                self.fail("Node.js is required for frontend cache tests in CI")
            self.skipTest("Node.js is unavailable")
        result = subprocess.run(
            [node, "--test-reporter=tap", str(Path(__file__).with_name("view_cache_budget_unit.js"))],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# pass 8", result.stdout)
