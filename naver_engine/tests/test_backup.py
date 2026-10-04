"""S14 백업 — 운영 파일/네트워크 없이 공개 인터페이스의 결과를 검증한다."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import stat
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone, timedelta

from naver_engine import backup as B
from naver_engine import store as S


NOW = datetime(2026, 9, 30, 3, 0, tzinfo=timezone.utc)
DATA = b"synthetic snapshot bytes"
COUNTS = {"naver_auto_meta": 2}


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.local, self.outgoing = self.root / "local", self.root / "outgoing"

    @staticmethod
    def snapshot(path):
        path.write_bytes(DATA)
        return COUNTS

    @staticmethod
    def encrypt(source, destination):
        # 파일/명령 seam만 대체한다. 암호화 자체는 별도 OpenSSL 실물 시험으로 검증한다.
        destination.write_bytes(b"encrypted:" + source.read_bytes())

    def make(self, **extra):
        return B.create_backup(self.snapshot, self.local, self.outgoing, now=NOW,
                               encrypt=extra.pop("encrypt", self.encrypt), **extra)

    def test_private_compressed_snapshot_with_manifest_is_not_offsite_success(self):
        result = self.make()
        self.assertEqual(result.code, "READY")
        self.assertFalse(result.offsite_verified)
        self.assertEqual(stat.S_IMODE(result.local_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(result.encrypted_path.stat().st_mode), 0o600)
        with zipfile.ZipFile(result.local_path) as archive:
            self.assertEqual(set(archive.namelist()), {"snapshot.sqlite", "manifest.json"})
            self.assertEqual(archive.read("snapshot.sqlite"), DATA)
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["row_counts"], COUNTS)
        self.assertEqual(manifest["sha256"], hashlib.sha256(DATA).hexdigest())
        self.assertEqual([p.suffix for p in self.outgoing.iterdir()], [".cms"])

    def test_offsite_success_requires_matching_receipt(self):
        ready = self.make()
        size = ready.encrypted_path.stat().st_size
        digest = B.file_digest(ready.encrypted_path)
        good = B.publish_backup(ready, lambda path: {"sha256": digest, "size": size})
        self.assertEqual(good.code, "OFFSITE_OK")
        self.assertTrue(good.offsite_verified)
        bad = B.publish_backup(ready, lambda path: {"sha256": "0" * 64, "size": size})
        self.assertEqual(bad.code, "UPLOAD_FAILED")
        self.assertFalse(bad.offsite_verified)

    def test_encryption_failure_preserves_local_copy_and_no_upload(self):
        def broken(source, destination):
            destination.write_bytes(b"partial")
            raise RuntimeError("secret-path-marker")
        result = self.make(encrypt=broken)
        self.assertEqual(result.code, "ENCRYPTION_FAILED")
        self.assertTrue(result.local_path.is_file())
        self.assertEqual(list(self.outgoing.iterdir()), [])
        self.assertNotIn("secret-path-marker", repr(result))

    def test_restore_verifies_digest_integrity_and_exact_row_counts_before_publish(self):
        result = self.make()
        output = self.root / "restored.sqlite"
        def inspect(path):
            self.assertEqual(path.read_bytes(), DATA)
            return COUNTS
        self.assertEqual(B.restore_archive(result.local_path, output, inspect), COUNTS)
        self.assertEqual(output.read_bytes(), DATA)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        bad = self.root / "bad.sqlite"
        with self.assertRaises(B.BackupError):
            B.restore_archive(result.local_path, bad, lambda path: {"naver_auto_meta": 3})
        self.assertFalse(bad.exists())
        with self.assertRaises(B.BackupError):
            B.restore_archive(result.local_path, output, inspect)

    @unittest.skipUnless(sys.platform == "linux", "실제 inode flock+WAL 계약은 Linux CI에서 검증")
    def test_sqlite_online_snapshot_includes_uncheckpointed_wal_and_restores_counts(self):
        with S.open_writer(str(self.root / "engine.sqlite"), clock=lambda: NOW) as writer:
            writer.begin_run(NOW.date(), NOW)
            self.assertTrue((self.root / "engine.sqlite-wal").is_file())
            result = B.create_backup(writer.snapshot_to, self.local, self.outgoing, now=NOW,
                                     encrypt=self.encrypt)
            self.assertEqual(result.code, "READY")
            restored = self.root / "restored.sqlite"
            counts = B.restore_archive(result.local_path, restored, S.inspect_snapshot)
            self.assertEqual(counts["naver_auto_check_run"], 1)
            with S.open_reader(str(restored)) as reader:
                self.assertEqual(len(reader.runs_on(NOW.date())), 1)
            with self.assertRaises(S.StoreError):
                writer.snapshot_to(restored)

    def test_snapshot_helper_copies_synthetic_wal_without_source_checkpoint(self):
        path = self.root / "synthetic.sqlite"
        connection = sqlite3.connect(path, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sample (id INTEGER)")
        connection.execute("INSERT INTO sample VALUES (1)")
        # 이 helper 시험은 Linux의 독점 writer 잠금 검증을 대신하지 않는다.
        with S.Store(connection, str(path), None, writer=True) as writer:
            result = B.create_backup(writer.snapshot_to, self.local, self.outgoing, now=NOW,
                                     encrypt=self.encrypt)
            self.assertEqual(result.code, "READY")
            self.assertEqual(B.restore_archive(result.local_path, self.root / "restored.sqlite",
                                              S.inspect_snapshot), {"sample": 1})

    def test_retention_only_removes_old_owned_recognized_private_backups(self):
        self.make()
        old = self.local / ("naver-20260901T030000Z-" + "a" * 32 + ".zip")
        old.write_bytes(b"old")
        old.chmod(0o600)
        unrelated = self.local / "customer-record.zip"
        unrelated.write_bytes(b"keep")
        symlink = self.local / ("naver-20260901T030000Z-" + "b" * 32 + ".zip")
        symlink.symlink_to(unrelated)
        os.utime(old, (NOW.timestamp() - 29 * 86400,) * 2)
        self.assertEqual(B.prune_local(self.local, now=NOW), 1)
        self.assertFalse(old.exists())
        self.assertEqual(unrelated.read_bytes(), b"keep")
        self.assertTrue(symlink.is_symlink())

    def test_job_retries_same_ciphertext_hourly_and_persists_verified_state(self):
        class StoreProxy:
            snapshot_to = staticmethod(self.snapshot)
            def runs_on(self, day):
                return [{"status": "done"}]
        sent = []
        def sender(path):
            sent.append(path.name)
            if len(sent) == 1:
                raise RuntimeError("lost receipt")
            return {"sha256": B.file_digest(path), "size": path.stat().st_size}
        root = self.root / "job"
        job = B.BackupJob(root, self.encrypt, sender)
        self.assertEqual(job(StoreProxy(), NOW).code, "UPLOAD_FAILED")
        self.assertEqual(job(StoreProxy(), NOW + timedelta(minutes=30)).code, "RETRY_WAIT")
        restarted = B.BackupJob(root, self.encrypt, sender)
        self.assertEqual(restarted(StoreProxy(), NOW + timedelta(hours=1)).code, "OFFSITE_OK")
        self.assertEqual(sent[0], sent[1])
        self.assertEqual(restarted(StoreProxy(), NOW + timedelta(hours=2)).code, "ALREADY_BACKED_UP")
        self.assertIsNotNone(restarted.status()["last_offsite_at"])
        self.assertNotIn(sent[0], json.dumps(restarted.status()))

    def test_job_is_independent_of_morning_runs_and_refuses_untrusted_status_file(self):
        class StoreProxy:
            snapshot_to = staticmethod(BackupTest.snapshot)
            def runs_on(self, day):
                raise AssertionError("백업은 아침 회차 유무나 진행 상태에 의존하지 않습니다")
        root = self.root / "job"
        job = B.BackupJob(root, self.encrypt,
                         lambda path: {"sha256": B.file_digest(path), "size": path.stat().st_size})
        self.assertEqual(job(StoreProxy(), NOW).code, "OFFSITE_OK")
        self.assertIsNotNone(job.status()["last_attempt_at"])
        state = root / "state.json"
        state.write_text("not-json")
        state.chmod(0o600)
        with self.assertRaises(B.BackupError):
            B.BackupJob(root, self.encrypt, lambda path: None)

    def test_eight_day_upload_outage_keeps_daily_local_snapshots_but_one_pending_ciphertext(self):
        snapshots, uploaded = [], []
        class StoreProxy:
            def runs_on(self, day):
                return [{"status": "done"}]
            def snapshot_to(self, path):
                snapshots.append(len(snapshots) + 1)
                path.write_bytes(DATA + str(snapshots[-1]).encode())
                return COUNTS
        def failed_sender(path):
            uploaded.append(path.name)
            raise RuntimeError("synthetic outage")
        root = self.root / "job"
        for day in range(8):
            job = B.BackupJob(root, self.encrypt, failed_sender)
            result = job(StoreProxy(), NOW + timedelta(days=day))
            self.assertEqual(result.code, "UPLOAD_FAILED")
        self.assertEqual(len(snapshots), 8)
        self.assertEqual(len(list((root / "local").glob("*.zip"))), 8)
        self.assertEqual(len(list((root / "outgoing").glob("*.cms"))), 1)
        self.assertEqual(len(set(uploaded)), 1)
        self.assertIsNone(job.status()["last_offsite_at"])
        def recovered_sender(path):
            uploaded.append(path.name)
            return {"sha256": B.file_digest(path), "size": path.stat().st_size}
        job = B.BackupJob(root, self.encrypt, recovered_sender)
        self.assertEqual(job(StoreProxy(), NOW + timedelta(days=7, hours=1)).code, "OFFSITE_OK")
        self.assertEqual(uploaded[0], uploaded[-1])  # 오래된 수신 불명 사본부터 같은 내용으로 재확인
        self.assertEqual(job(StoreProxy(), NOW + timedelta(days=7, hours=2)).code, "OFFSITE_OK")
        self.assertNotEqual(uploaded[0], uploaded[-1])  # 다음 시도는 이미 만든 오늘 사본
        self.assertEqual(len(snapshots), 8)

    def test_corrupt_snapshot_and_symlink_destinations_never_restore(self):
        source = self.make().local_path
        target = self.root / "target.sqlite"
        target.symlink_to(self.root / "unrelated")
        with self.assertRaises(B.BackupError):
            B.restore_archive(source, target, lambda path: COUNTS)
        self.assertTrue(target.is_symlink())
        corrupt = self.root / "corrupt.sqlite"
        corrupt.write_bytes(b"not a sqlite database")
        corrupt.chmod(0o600)
        with self.assertRaises(S.StoreError):
            S.inspect_snapshot(corrupt)
