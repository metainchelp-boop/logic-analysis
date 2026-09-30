"""실제 키·네트워크 없이 합성 SQLite 압축본으로 복원 CLI를 검증한다."""
import json
import hashlib
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import patch

from naver_engine import backup as B
from naver_runtime.restore_check import check_restore


class RestoreCheckTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.output = self.root / "new-check"
        def snapshot(path):
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute("CREATE TABLE sample (value TEXT)")
                connection.execute("INSERT INTO sample VALUES (?)", ("secret-row-marker",))
            return {"sample": 1}
        self.archive = B.create_local_backup(snapshot, self.root / "local", now=datetime(
            2026, 9, 30, 15, 0, tzinfo=timezone.utc)).local_path

    def run_cli(self, *extra):
        return subprocess.run([sys.executable, "-m", "naver_runtime.restore_check",
                               "--archive", str(self.archive), "--expected-kst-date", "2026-10-01",
                               "--output-dir", str(self.output), *extra],
                              capture_output=True, text=True, timeout=15,
                              env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"})

    def replace_manifest(self, change):
        with zipfile.ZipFile(self.archive) as archive:
            snapshot = archive.read("snapshot.sqlite")
            manifest = json.loads(archive.read("manifest.json"))
        change(manifest)
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("snapshot.sqlite", snapshot)
            archive.writestr("manifest.json", json.dumps(manifest))

    def assert_refused(self, *extra):
        result = self.run_cli(*extra)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout), {
            "status": "failed", "message": "복원 검증에 실패했습니다."})
        self.assertEqual(result.stderr, "")
        self.assertNotIn("secret-row-marker", result.stdout)
        self.assertNotIn(str(self.root), result.stdout)

    def test_cli_restores_new_database_and_reports_only_verification_evidence(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["backup_kst_date"], "2026-10-01")
        self.assertEqual(report["row_counts"], {"sample": 1})
        self.assertEqual({p.name for p in self.output.iterdir()}, {"snapshot.sqlite"})
        self.assertEqual((self.output / "snapshot.sqlite").stat().st_mode & 0o777, 0o600)
        self.assertNotIn("secret-row-marker", result.stdout + result.stderr)
        self.assertNotIn(str(self.root), result.stdout + result.stderr)

    def test_created_at_requires_the_generators_explicit_utc_format(self):
        for index, created in enumerate(("2026-10-01T00:00:00", "2026-10-01T00:00:00+09:00",
                                        "2026-09-30T15:00:00Z", "secret-row-marker", None)):
            with self.subTest(created=created):
                self.output = self.root / f"check-{index}"
                self.replace_manifest(lambda m: m.update(created_at=created))
                self.assert_refused()
                self.assertFalse(self.output.exists())

    def test_missing_date_and_wrong_expected_day_are_refused(self):
        self.assert_refused("--expected-kst-date", "2026-09-30")
        self.assertFalse(self.output.exists())
        self.replace_manifest(lambda m: m.pop("created_at"))
        self.assert_refused()
        self.assertFalse(self.output.exists())

    def test_invalid_expected_date_and_unknown_arguments_never_echo_values(self):
        for value in ("2026-10-1", "2026-02-30", "secret-row-marker"):
            self.assert_refused("--expected-kst-date", value)
            self.assertFalse(self.output.exists())
        self.assert_refused("--secret-row-marker", str(self.root))
        self.assertFalse(self.output.exists())

    def test_microsecond_timestamp_matches_generator_format(self):
        self.replace_manifest(lambda m: m.update(created_at="2026-09-30T15:00:00.123456+00:00"))
        result = self.run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["backup_kst_date"], "2026-10-01")

    def test_hash_and_row_count_tampering_are_refused_without_output(self):
        original = self.archive.read_bytes()
        changes = (lambda m: m.update(sha256="0" * 64),
                   lambda m: m.update(row_counts={"sample": 2}),
                   lambda m: m.update(row_counts={"different_table": 1}))
        for change in changes:
            self.archive.write_bytes(original)
            self.replace_manifest(change)
            self.assert_refused()
            self.assertFalse(self.output.exists())

    def test_invalid_zip_and_unexpected_entries_are_refused(self):
        original = self.archive.read_bytes()
        self.archive.write_bytes(b"secret-row-marker-not-a-zip")
        self.assert_refused()
        self.assertFalse(self.output.exists())
        self.archive.write_bytes(original)
        with zipfile.ZipFile(self.archive, "a") as archive:
            archive.writestr("../secret-row-marker", "not allowed")
        self.assert_refused()
        self.assertFalse(self.output.exists())
        self.assertFalse((self.root / "secret-row-marker").exists())

    def test_matching_hash_does_not_bypass_database_integrity_check(self):
        with zipfile.ZipFile(self.archive) as archive:
            manifest = json.loads(archive.read("manifest.json"))
        damaged = b"secret-row-marker-not-a-database"
        manifest["sha256"] = hashlib.sha256(damaged).hexdigest()
        with zipfile.ZipFile(self.archive, "w") as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("snapshot.sqlite", damaged)
        self.assert_refused()
        self.assertFalse(self.output.exists())

    def test_existing_output_directory_and_source_archive_are_unchanged(self):
        before = self.archive.read_bytes()
        self.output.mkdir(mode=0o700)
        existing = self.output / "snapshot.sqlite"
        existing.write_bytes(b"existing-private-data")
        self.assert_refused()
        self.assertEqual(existing.read_bytes(), b"existing-private-data")
        self.assertEqual(self.archive.read_bytes(), before)

    def test_existing_output_file_and_symlink_are_unchanged(self):
        self.output.write_bytes(b"existing-private-data")
        self.assert_refused()
        self.assertEqual(self.output.read_bytes(), b"existing-private-data")
        self.output = self.root / "symlink-output"
        self.output.symlink_to(self.root / "new-check")
        self.assert_refused()
        self.assertTrue(self.output.is_symlink())

    def test_source_symlink_is_refused_and_original_is_preserved(self):
        original, before = self.archive, self.archive.read_bytes()
        self.archive = self.root / "linked.zip"
        self.archive.symlink_to(original)
        self.assert_refused()
        self.assertFalse(self.output.exists())
        self.assertEqual(original.read_bytes(), before)

    def test_filesystem_failure_after_publish_leaves_no_unreported_database(self):
        original_link = os.link
        def fail_after_link(*args, **kwargs):
            original_link(*args, **kwargs)
            raise OSError("secret-row-marker")
        with patch("os.link", side_effect=fail_after_link), self.assertRaises(Exception):
            check_restore(self.archive, "2026-10-01", self.output)
        self.assertFalse(self.output.exists())

    def test_source_replacement_between_check_and_open_is_refused(self):
        replacement = self.root / "replacement.zip"
        replacement.write_bytes(self.archive.read_bytes())
        replacement.chmod(0o600)
        original_open = os.open
        def replace_before_open(path, *args, **kwargs):
            if pathlib.Path(path) == self.archive:
                os.replace(replacement, self.archive)
            return original_open(path, *args, **kwargs)
        with patch("os.open", side_effect=replace_before_open), self.assertRaises(Exception):
            check_restore(self.archive, "2026-10-01", self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
