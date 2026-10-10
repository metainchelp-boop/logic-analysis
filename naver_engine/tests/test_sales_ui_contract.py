"""Run sales-only UI contracts with synthetic DOM data and no browser or network."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]


class SalesUIContractTest(unittest.TestCase):
    def test_sales_ui_synthetic_dom_contracts(self):
        node = shutil.which("node")
        if node is None:
            if os.environ.get("NAVER_SCREEN_REQUIRE_BROWSER") == "1":
                self.fail("Node.js is required for sales UI contracts in CI")
            self.skipTest("Node.js is unavailable")
        result = subprocess.run(
            [node, str(ROOT / "naver_engine/tests/sales_ui_contract_test.js")],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
            env={key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TZ") if key in os.environ},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["suite"], "sales-ui-memory-dom")
        self.assertEqual(receipt["checks"], receipt["passed"])
        self.assertGreaterEqual(receipt["passed"], 26)
        self.assertEqual(receipt["network_calls"], 0)
        self.assertEqual(receipt["browser_calls"], 0)


if __name__ == "__main__":
    unittest.main()
