"""직원 진입 진단: 실제 수신부+앱의 Node VM 시험을 기존 unittest discovery에 포함한다."""
from pathlib import Path
import os
import shutil
import subprocess
import unittest


class NaverStaffEntryTest(unittest.TestCase):
    def test_real_bootstrap_and_app_diagnostics(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "직원 진입 진단 시험에는 Node가 필요합니다.")
        result = subprocess.run(
            [node, "--test", str(Path(__file__).with_name("naver_staff_entry.test.js"))],
            capture_output=True, text=True, timeout=30,
            env={"PATH": os.environ.get("PATH", "")},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
