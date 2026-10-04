"""Offline PDF contract/asset checks; does not start services or call external providers."""
import hashlib
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "backend/naver_page/vendor/report-pdf"


class ReportPDFTest(unittest.TestCase):
    def test_vendored_assets_match_reviewed_sizes_digests_and_license_notices(self):
        manifest = json.loads((ASSETS / "manifest.json").read_text())
        self.assertEqual({item["file"] for item in manifest["assets"]}, {
            "pdf-lib-1.17.1.min.js", "fontkit-1.1.1.umd.min.js", "NanumGothic-Regular.ttf.gz", "sha256-1.0.0.min.js"})
        for item in manifest["assets"]:
            with self.subTest(asset=item["file"]):
                raw = (ASSETS / item["file"]).read_bytes()
                self.assertEqual(len(raw), item["bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), item["sha256"])
                self.assertLessEqual(len(raw), 1024 * 1024)  # Preserve the deployment archive member cap.
                if "uncompressed_sha256" in item:
                    decoded = gzip.decompress(raw)
                    self.assertEqual(len(decoded), item["uncompressed_bytes"])
                    self.assertEqual(hashlib.sha256(decoded).hexdigest(), item["uncompressed_sha256"])
                self.assertGreater((ASSETS / item["license_file"]).stat().st_size, 500)
        for name in manifest["additional_license_files"]:
            self.assertGreater((ASSETS / name).stat().st_size, 500)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required for browser PDF byte-contract tests")
    def test_pdf_generation_and_download_contracts(self):
        result = subprocess.run([shutil.which("node"), "--test", "naver_engine/tests/report_pdf.test.js"],
                                cwd=ROOT, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
