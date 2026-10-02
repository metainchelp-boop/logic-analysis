"""실관리 화면의 실제 앱 DOM/API 계약 검사를 unittest discovery에도 포함한다."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest


class NaverManagementUITest(unittest.TestCase):
    def test_management_reports_dom_contracts(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "실관리 화면 회귀 검사에는 Node가 필요합니다.")
        result = subprocess.run(
            [node, "--test", str(Path(__file__).with_name("naver_management_ui.test.js"))],
            capture_output=True, text=True, timeout=30,
            env={"PATH": os.environ.get("PATH", "")},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
