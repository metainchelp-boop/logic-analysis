"""Synthetic local artifacts only; never contact or read the operating server."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("verify_existing",
    Path(__file__).with_name("collector_backup_verify_existing.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ExistingBackupVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="collector-existing-backup-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.backup = self.root / "backup.sqlite"
        self.restored = self.root / "restored-copy.sqlite"
        schema = [
            ("table", "collected_serp", "collected_serp",
             "CREATE TABLE collected_serp(id INTEGER PRIMARY KEY, value TEXT)"),
            ("table", "private_customer_table", "private_customer_table",
             "CREATE TABLE private_customer_table(value TEXT)"),
            ("view", "private_view", "private_view",
             "CREATE VIEW private_view AS SELECT * FROM collected_serp"),
        ]
        with closing(sqlite3.connect(self.backup)) as conn:
            for row in schema:
                conn.execute(row[3])
            conn.execute("INSERT INTO collected_serp VALUES(1, 'private-row-never-output')")
            conn.executemany("INSERT INTO private_customer_table VALUES(?)", [("private-token",)] * 2)
            conn.commit()
        shutil.copyfile(self.backup, self.restored)
        encode = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=True,
                                           separators=(",", ":")).encode()
        self.expected = {
            "bytes": self.backup.stat().st_size,
            "sha256": hashlib.sha256(self.backup.read_bytes()).hexdigest(),
            "ordinary_table_count": 2,
            "schema_sha256": hashlib.sha256(encode(schema)).hexdigest(),
            "all_ordinary_table_counts_sha256": hashlib.sha256(encode(
                {"collected_serp": 1, "private_customer_table": 2})).hexdigest(),
        }

    def run_phase(self, phase, **kwargs):
        return probe.verify_existing(phase, self.root, self.expected, **kwargs)

    def test_both_phases_pass_without_modifying_or_creating_any_file(self):
        before = {path.name: (path.read_bytes(), probe._stamp(path.stat()))
                  for path in self.root.iterdir()}
        with patch.object(Path, "mkdir", side_effect=AssertionError("creation forbidden")):
            for phase in ("digests", "restored_metadata"):
                result = self.run_phase(phase)
                self.assertTrue(result["passed"], result)
                self.assertEqual(result["files_created"], 0)
                self.assertFalse(result["source_database_opened"])
                self.assertEqual(result["artifact_stats_before"], result["artifact_stats_after"])
                for private in ("private_customer_table", "private_view", "private-row", "private-token"):
                    self.assertNotIn(private, json.dumps(result))
        after = {path.name: (path.read_bytes(), probe._stamp(path.stat()))
                 for path in self.root.iterdir()}
        self.assertEqual(before, after)

    def test_digest_phase_hashes_each_artifact_once_and_never_opens_sqlite(self):
        with patch.object(probe, "_hash_file", wraps=probe._hash_file) as hashed:
            with patch.object(probe.sqlite3, "connect", side_effect=AssertionError("SQLite forbidden")):
                result = self.run_phase("digests")
        self.assertTrue(result["passed"], result)
        self.assertEqual([call.args[0] for call in hashed.call_args_list], [self.backup, self.restored])

    def test_metadata_opens_only_restored_copy_read_only_immutable(self):
        with patch.object(probe.sqlite3, "connect", wraps=sqlite3.connect) as connected:
            result = self.run_phase("restored_metadata")
        self.assertTrue(result["passed"], result)
        connected.assert_called_once_with(self.restored.as_uri() + "?mode=ro&immutable=1",
                                          uri=True, timeout=1)

    def test_digest_mismatch_fails_closed(self):
        self.expected["sha256"] = "0" * 64
        result = self.run_phase("digests")
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "ARTIFACT_DIGEST_MISMATCH")

    def test_metadata_mismatch_fails_for_schema_counts_or_table_count(self):
        for key in ("schema_sha256", "all_ordinary_table_counts_sha256", "ordinary_table_count"):
            expected = dict(self.expected)
            expected[key] = 99 if key == "ordinary_table_count" else "0" * 64
            result = probe.verify_existing("restored_metadata", self.root, expected)
            self.assertFalse(result["passed"])
            self.assertEqual(result["error_code"], "RESTORED_METADATA_MISMATCH")

    def test_missing_size_changed_and_sidecar_artifacts_are_rejected(self):
        sidecar = Path(str(self.restored) + "-wal")
        sidecar.touch()
        self.assertEqual(self.run_phase("digests")["error_code"], "STANDALONE_ARTIFACT_REQUIRED")
        sidecar.unlink()
        self.restored.write_bytes(b"truncated")
        self.assertEqual(self.run_phase("digests")["error_code"], "ARTIFACT_SIZE_MISMATCH")
        self.restored.unlink()
        self.assertEqual(self.run_phase("digests")["error_code"], "FILESYSTEM_VERIFICATION_FAILED")

    def test_symlink_hardlink_and_directory_alias_are_rejected(self):
        self.restored.unlink()
        self.restored.symlink_to(self.backup)
        self.assertEqual(self.run_phase("digests")["error_code"], "PATH_ALIAS_FORBIDDEN")
        self.restored.unlink()
        os.link(self.backup, self.restored)
        self.assertEqual(self.run_phase("digests")["error_code"], "FILE_ALIAS_FORBIDDEN")
        self.restored.unlink()
        shutil.copyfile(self.backup, self.restored)
        alias = self.root / "directory-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        result = probe.verify_existing("digests", alias, self.expected)
        self.assertEqual(result["error_code"], "PATH_ALIAS_FORBIDDEN")

    def test_change_during_phase_cannot_pass(self):
        actual = probe._hash_file

        def change_after_hash(path, stamp, check):
            digest = actual(path, stamp, check)
            os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1000000))
            return digest

        with patch.object(probe, "_hash_file", change_after_hash):
            result = self.run_phase("digests")
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "ARTIFACT_CHANGED")

    def test_timeout_and_invalid_inputs_fail_closed(self):
        with patch.object(probe.time, "monotonic", side_effect=[0, 181, 181]):
            result = self.run_phase("digests")
        self.assertEqual(result["error_code"], "PHASE_TIMEOUT")
        self.assertFalse(result["passed"])
        self.assertEqual(self.run_phase("private-invalid-phase")["error_code"], "INVALID_PHASE")
        for timeout in (0, 181, float("nan"), True):
            self.assertEqual(self.run_phase("digests", timeout_seconds=timeout)["error_code"], "INVALID_TIMEOUT")

    def test_sqlite_error_is_sanitized(self):
        with patch.object(probe.sqlite3, "connect", side_effect=sqlite3.DatabaseError("private-raw-error")):
            result = self.run_phase("restored_metadata")
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "SQLITE_VERIFICATION_FAILED")
        self.assertNotIn("private-raw-error", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
