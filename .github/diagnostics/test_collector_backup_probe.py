"""Synthetic local databases only; this suite cannot contact the operating server."""
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch


PROBE_PATH = Path(__file__).with_name("collector_backup_probe.py")
spec = importlib.util.spec_from_file_location("server_backup_probe", PROBE_PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ServerBackupProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="collector-server-backup-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.sqlite"
        self.parent = self.root / "backups"
        self.parent.mkdir()
        self.job = self.parent / "collector-validation-test"

    def seed(self):
        conn = sqlite3.connect(self.source)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE collected_serp(id INTEGER PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO collected_serp VALUES(1, 'private-row-never-output')")
        conn.execute('CREATE TABLE "private_customer_table" (value TEXT)')
        conn.execute("INSERT INTO private_customer_table VALUES('private-token-never-output')")
        conn.execute("CREATE VIEW private_view AS SELECT * FROM collected_serp")
        conn.commit()
        return conn

    @staticmethod
    def logical_hash(conn):
        return hashlib.sha256("\n".join(conn.iterdump()).encode()).hexdigest()

    def run_probe(self, **kwargs):
        return probe.create_verified_backup(self.source, self.job, **kwargs)

    def test_wal_snapshot_restored_copy_and_source_unchanged(self):
        with closing(self.seed()) as original:
            before = self.logical_hash(original)
            identity = self.source.stat().st_ino
            self.assertGreater(Path(str(self.source) + "-wal").stat().st_size, 0)
            original.execute("INSERT INTO collected_serp VALUES(2, 'not-yet-committed')")
            result = self.run_probe()
            self.assertTrue(result["passed"], result)
            self.assertTrue(result["isolated_restore_verified"])
            self.assertFalse(result["original_restore_performed"])
            self.assertEqual(result["backup"]["known_table_counts"], {"collected_serp": 1})
            self.assertEqual(result["backup"]["ordinary_table_count"], 2)
            original.rollback()
            self.assertEqual(self.logical_hash(original), before)
            self.assertEqual(self.source.stat().st_ino, identity)
            self.assertEqual(original.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(stat.S_IMODE(self.job.stat().st_mode), 0o700)
        self.assertEqual(sorted(path.name for path in self.job.iterdir()), sorted(probe.ARTIFACT_NAMES))
        backup, restored = (self.job / name for name in probe.ARTIFACT_NAMES)
        self.assertEqual(backup.read_bytes(), restored.read_bytes())
        for path in (backup, restored):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(result["backup"]["sha256"], hashlib.sha256(backup.read_bytes()).hexdigest())
        output = json.dumps(result)
        for private in ("private-row-never-output", "private-token-never-output",
                        "private_customer_table", "private_view", "not-yet-committed"):
            self.assertNotIn(private, output)

    def test_later_source_writes_remain_in_source_but_not_snapshot(self):
        with closing(self.seed()) as original:
            copy = probe._copy_new

            def write_then_copy(source, output, check):
                original.execute("INSERT INTO collected_serp VALUES(2, 'later-write')")
                original.commit()
                return copy(source, output, check)

            with patch.object(probe, "_copy_new", write_then_copy):
                result = self.run_probe()
            self.assertTrue(result["passed"], result)
            self.assertEqual(original.execute("SELECT COUNT(*) FROM collected_serp").fetchone()[0], 2)
            self.assertEqual(result["restored_copy"]["known_table_counts"]["collected_serp"], 1)

    def test_source_and_restored_connections_are_read_only(self):
        with closing(self.seed()):
            connect = sqlite3.connect
            with patch.object(probe.sqlite3, "connect", wraps=connect) as tracked:
                self.assertTrue(self.run_probe()["passed"])
        calls = [call.args[0] for call in tracked.call_args_list]
        self.assertEqual(calls[0], self.source.as_uri() + "?mode=ro")
        self.assertIn((self.job / "restored-copy.sqlite").as_uri() + "?mode=ro", calls)
        self.assertEqual(len([uri for uri in calls if "?mode=rw" in uri]), 1)

    def test_insufficient_space_does_not_create_job(self):
        with closing(self.seed()):
            with patch.object(probe.shutil, "disk_usage", return_value=type("Disk", (), {"free": 1})()):
                result = self.run_probe()
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "INSUFFICIENT_FREE_SPACE")
        self.assertFalse(self.job.exists())

    def test_size_limits_do_not_create_job(self):
        with closing(self.seed()):
            with patch.object(probe, "MAX_SOURCE_BYTES", 1):
                self.assertEqual(self.run_probe()["error_code"], "SOURCE_SIZE_LIMIT")
            with patch.object(probe, "MAX_RETAINED_BYTES", 1):
                self.assertEqual(self.run_probe()["error_code"], "RETAINED_SIZE_LIMIT")
        self.assertFalse(self.job.exists())

    def test_existing_directory_and_existing_files_are_never_overwritten(self):
        with closing(self.seed()):
            self.job.mkdir()
            target = self.job / "backup.sqlite"
            target.write_bytes(b"existing-backup")
            result = self.run_probe()
            self.assertFalse(result["passed"])
            self.assertEqual(target.read_bytes(), b"existing-backup")
            with self.assertRaisesRegex(probe.ProbeError, "OUTPUT_ALREADY_EXISTS"):
                probe._new_file(target)
            self.assertEqual(target.read_bytes(), b"existing-backup")

    def test_symlink_source_parent_job_and_hardlink_are_rejected(self):
        with closing(self.seed()):
            alias = self.root / "alias.sqlite"
            alias.symlink_to(self.source)
            self.assertEqual(probe.create_verified_backup(alias, self.job)["error_code"], "PATH_ALIAS_FORBIDDEN")
            alias.unlink()
            os.link(self.source, alias)
            self.assertEqual(self.run_probe()["error_code"], "FILE_ALIAS_FORBIDDEN")
            alias.unlink()
            self.job.symlink_to(self.root / "absent")
            self.assertFalse(self.run_probe()["passed"])
            self.assertFalse((self.root / "absent").exists())
            self.job.unlink()
            self.parent.rmdir()
            self.parent.symlink_to(self.root)
            self.assertEqual(self.run_probe()["error_code"], "PATH_ALIAS_FORBIDDEN")

    def test_missing_parent_is_not_created_and_sidecar_target_is_rejected(self):
        with closing(self.seed()):
            sidecar = Path(str(self.source) + "-journal")
            result = probe.create_verified_backup(self.source, sidecar)
            self.assertEqual(result["error_code"], "OWNED_BACKUP_JOB_DIRECTORY_REQUIRED")
            self.assertFalse(sidecar.exists())
            self.parent.rmdir()
            self.assertFalse(self.run_probe()["passed"])
            self.assertFalse(self.parent.exists())

    def test_timeout_reports_failure_and_never_false_success(self):
        with closing(self.seed()):
            with patch.object(probe.time, "monotonic", side_effect=[0, 2, 2]):
                result = self.run_probe(timeout_seconds=1)
        self.assertEqual(result["error_code"], "PROBE_TIMEOUT")
        self.assertFalse(result["passed"])
        self.assertFalse(result["isolated_restore_verified"])
        self.assertFalse(self.job.exists())

    def test_timeout_during_online_backup_retains_only_incomplete_new_file(self):
        with closing(self.seed()) as original:
            before = self.logical_hash(original)
            connect = sqlite3.connect
            clock = {"now": 0}

            def expire_at_destination(database, **kwargs):
                connection = connect(database, **kwargs)
                if "?mode=rw" in database:
                    clock["now"] = 181
                return connection

            with patch.object(probe.sqlite3, "connect", expire_at_destination):
                with patch.object(probe.time, "monotonic", side_effect=lambda: clock["now"]):
                    result = self.run_probe()
            self.assertEqual(self.logical_hash(original), before)
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "PROBE_TIMEOUT")
        self.assertEqual(result["artifact_state"], "incomplete")
        self.assertEqual([item["file_name"] for item in result["retained_files"]], ["backup.sqlite"])

    def test_free_space_is_rechecked_before_restored_copy(self):
        with closing(self.seed()):
            adequate = type("Disk", (), {"free": 100 * 1024**3})()
            depleted = type("Disk", (), {"free": 1})()
            with patch.object(probe.shutil, "disk_usage", side_effect=[adequate, depleted]):
                result = self.run_probe()
        self.assertEqual(result["error_code"], "INSUFFICIENT_FREE_SPACE")
        self.assertFalse(result["passed"])
        self.assertEqual(result["backup"]["integrity_check"], "ok")
        self.assertFalse((self.job / "restored-copy.sqlite").exists())

    def test_concurrent_restore_target_is_not_overwritten(self):
        with closing(self.seed()):
            actual = probe._copy_new

            def create_competing_file(source, output, check):
                output.write_bytes(b"concurrent-owner")
                actual(source, output, check)

            with patch.object(probe, "_copy_new", create_competing_file):
                result = self.run_probe()
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "OUTPUT_ALREADY_EXISTS")
        self.assertEqual((self.job / "restored-copy.sqlite").read_bytes(), b"concurrent-owner")

    def test_source_inode_replacement_cannot_be_reported_as_unchanged(self):
        with closing(self.seed()) as original:
            actual = probe._copy_new

            def replace_then_copy(source, output, check):
                actual(source, output, check)
                self.source.rename(self.root / "old-source.sqlite")
                self.source.write_bytes(b"externally-replaced")

            with patch.object(probe, "_copy_new", replace_then_copy):
                result = self.run_probe()
            self.assertEqual(original.execute("SELECT COUNT(*) FROM collected_serp").fetchone()[0], 1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "SOURCE_REPLACED")
        self.assertEqual(self.source.read_bytes(), b"externally-replaced")

    def test_failure_does_not_emit_raw_errors(self):
        with closing(self.seed()):
            with patch.object(probe, "_metadata", side_effect=sqlite3.DatabaseError("SECRET-CUSTOMER-TOKEN")):
                result = self.run_probe()
        self.assertFalse(result["passed"])
        self.assertEqual(result["error_code"], "SQLITE_OPERATION_FAILED")
        self.assertNotIn("SECRET-CUSTOMER-TOKEN", json.dumps(result))
        self.assertFalse((self.job / "restored-copy.sqlite").exists())

    def test_restore_corruption_never_passes(self):
        with closing(self.seed()):
            actual = probe._copy_new

            def corrupt_copy(source, output, check):
                actual(source, output, check)
                with output.open("r+b") as handle:
                    handle.write(b"bad-header")

            with patch.object(probe, "_copy_new", corrupt_copy):
                result = self.run_probe()
        self.assertFalse(result["passed"])
        self.assertFalse(result["isolated_restore_verified"])

    def test_invalid_timeout_and_corrupt_source_are_safe_failures(self):
        self.source.write_bytes(b"not a database")
        for timeout in (0, -1, float("nan"), float("inf"), True, 181):
            self.assertEqual(self.run_probe(timeout_seconds=timeout)["error_code"], "INVALID_TIMEOUT")
        self.assertEqual(self.run_probe()["error_code"], "SQLITE_OPERATION_FAILED")
        self.assertFalse(self.job.exists())


if __name__ == "__main__":
    unittest.main()
