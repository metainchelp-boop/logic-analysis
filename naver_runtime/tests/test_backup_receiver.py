"""합성 표준입력과 임시 폴더만 사용하는 수신 전용 프로토콜 시험."""
import hashlib
import ast
import importlib.util
import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from datetime import datetime, timezone, timedelta

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "naver-backup-receiver.py"


class ReceiverTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("backup_receiver", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.LIMITS = self.module.Limits(4 * 1024 * 1024, 64, 0, 0)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()

    @staticmethod
    def frame(data, digest=None):
        header = {"version": 1, "size": len(data), "sha256": digest or hashlib.sha256(data).hexdigest()}
        return io.BytesIO(json.dumps(header).encode() + b"\n" + data)

    def test_append_only_same_content_retry_returns_receipt_without_overwrite(self):
        first = self.module.receive(self.root, self.frame(b"ciphertext"))
        path = next(self.root.glob("naver-received-*.cms"))
        inode = path.stat().st_ino
        second = self.module.receive(self.root, self.frame(b"ciphertext"))
        self.assertEqual(first, second)
        self.assertEqual(path.stat().st_ino, inode)
        with self.assertRaises(self.module.ReceiverError):
            self.module.receive(self.root, self.frame(b"malicious", first["sha256"]))
        self.assertEqual(path.read_bytes(), b"ciphertext")
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_same_content_retry_does_not_require_python311_file_digest(self):
        expected = self.module.receive(self.root, self.frame(b"ciphertext"))
        with patch.object(hashlib, "file_digest", None, create=True):
            self.assertEqual(self.module.receive(self.root, self.frame(b"ciphertext")), expected)

    def test_full_quota_refuses_new_content_but_same_hash_retry_uses_no_temp_space(self):
        limits = self.module.Limits(10, 1, 0, 0)
        expected = self.module.receive(self.root, self.frame(b"ciphertext"), limits=limits)
        with self.assertRaises(self.module.ReceiverError):
            self.module.receive(self.root, self.frame(b"new"), limits=limits)
        with patch.object(self.module.tempfile, "mkstemp", side_effect=AssertionError("no new file")), \
                patch.object(self.module.os, "statvfs", side_effect=AssertionError("no capacity needed")):
            self.assertEqual(self.module.receive(self.root, self.frame(b"ciphertext"), limits=limits), expected)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_shared_lock_is_nonblocking_and_does_not_create_its_own_lock_file(self):
        lock = self.root / "receiver.lock"
        with self.assertRaises(OSError):
            with self.module.exclusive_lock(lock, owner=os.geteuid()):
                self.fail("missing lock must refuse")
        self.assertFalse(lock.exists())
        lock.write_bytes(b"")
        lock.chmod(0o600)
        with self.module.exclusive_lock(lock, owner=os.geteuid()):
            with self.assertRaises(self.module.ReceiverError):
                with self.module.exclusive_lock(lock, owner=os.geteuid()):
                    self.fail("concurrent receiver/prune must refuse")
        with self.module.exclusive_lock(lock, owner=os.geteuid()):
            pass

    def test_deadline_covers_header_body_and_final_eof_with_temporary_cleanup(self):
        original_handler = signal.getsignal(signal.SIGALRM)
        for payload in (b"{", self.frame(b"ciphertext").getvalue()[:-1],
                        self.frame(b"ciphertext").getvalue()):
            with self.subTest(payload=payload):
                read_fd, write_fd = os.pipe()
                try:
                    os.write(write_fd, payload)
                    with os.fdopen(read_fd, "rb") as stream, self.assertRaisesRegex(
                            self.module.ReceiverError, "TIMEOUT"):
                        with self.module.deadline(0.05):
                            self.module.receive(self.root, stream)
                finally:
                    os.close(write_fd)
                self.assertEqual(list(self.root.iterdir()), [])
                self.assertEqual(signal.getsignal(signal.SIGALRM), original_handler)
                self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_existing_fifo_is_rejected_before_reading_it(self):
        content = b"ciphertext"
        path = self.root / ("naver-received-" + hashlib.sha256(content).hexdigest() + ".cms")
        os.mkfifo(path, 0o600)
        with self.module.deadline(0.2), self.assertRaisesRegex(self.module.ReceiverError, "UNSAFE_FILE"):
            self.module.receive(self.root, self.frame(content))

    def test_orphan_temporary_and_unrecognized_files_count_toward_quota(self):
        for name in (".receiving-abcdefgh", "operator-file"):
            path = self.root / name
            path.write_bytes(b"12345678")
            path.chmod(0o600)
        for limits in (self.module.Limits(18, 10, 0, 0), self.module.Limits(100, 2, 0, 0)):
            with self.assertRaisesRegex(self.module.ReceiverError, "QUOTA_EXCEEDED"):
                self.module.receive(self.root, self.frame(b"new"), limits=limits)
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_byte_and_inode_reserves_fail_closed_at_boundary(self):
        limits = self.module.Limits(100, 4, 10, 3)
        for available in (SimpleNamespace(f_bavail=12, f_frsize=1, f_favail=4),
                          SimpleNamespace(f_bavail=13, f_frsize=1, f_favail=3)):
            with patch.object(self.module.os, "statvfs", return_value=available), \
                    self.assertRaisesRegex(self.module.ReceiverError, "INSUFFICIENT_SPACE"):
                self.module.receive(self.root, self.frame(b"new"), limits=limits)
            self.assertEqual(list(self.root.iterdir()), [])
        available = SimpleNamespace(f_bavail=13, f_frsize=1, f_favail=4)
        with patch.object(self.module.os, "statvfs", return_value=available):
            self.assertEqual(self.module.receive(self.root, self.frame(b"new"), limits=limits)["size"], 3)

    def test_reserve_is_rechecked_during_write_and_partial_file_is_removed(self):
        ample = SimpleNamespace(f_bavail=100, f_frsize=1, f_favail=10)
        full = SimpleNamespace(f_bavail=0, f_frsize=1, f_favail=0)
        with patch.object(self.module.os, "statvfs", side_effect=[ample, full]), \
                self.assertRaises(self.module.ReceiverError):
            self.module.receive(self.root, self.frame(b"new"))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_short_filesystem_writes_cannot_produce_a_false_success_receipt(self):
        real_fdopen = self.module.os.fdopen
        class ShortWriter:
            def __init__(self, stream):
                self.stream = stream
            def __enter__(self):
                self.stream.__enter__()
                return self
            def __exit__(self, *args):
                return self.stream.__exit__(*args)
            def __getattr__(self, name):
                return getattr(self.stream, name)
            def write(self, data):
                return self.stream.write(data[:2])
        def short_fdopen(*args, **kwargs):
            return ShortWriter(real_fdopen(*args, **kwargs))
        content = b"synthetic ciphertext"
        with patch.object(self.module.os, "fdopen", side_effect=short_fdopen):
            receipt = self.module.receive(self.root, self.frame(content))
        path = next(self.root.glob("naver-received-*.cms"))
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(receipt["size"], path.stat().st_size)

    def test_prune_only_removes_old_private_single_link_orphans(self):
        now = datetime.now(timezone.utc)
        old = self.root / ".receiving-abcdefgh"
        recent = self.root / ".receiving-12345678"
        linked = self.root / ".receiving-ijklmnop"
        unrelated = self.root / "operator-file"
        for path in (old, recent, linked, unrelated):
            path.write_bytes(b"partial")
            path.chmod(0o600)
            os.utime(path, ((now - timedelta(hours=2)).timestamp(),) * 2)
        os.utime(recent, ((now - timedelta(minutes=5)).timestamp(),) * 2)
        os.link(linked, self.root / "unrelated-hardlink")
        self.assertEqual(self.module.prune(self.root, now=now, owner=os.geteuid()), 1)
        self.assertFalse(old.exists())
        self.assertTrue(all(p.exists() for p in (recent, linked, unrelated)))

    def test_missing_or_invalid_limits_never_start_a_new_file(self):
        for limits in (None, self.module.Limits(0, 10, 0, 0), self.module.Limits(10, True, 0, 0),
                       self.module.Limits(10, 1, -1, 0)):
            self.module.LIMITS = limits
            with self.assertRaises(self.module.ReceiverError):
                self.module.receive(self.root, self.frame(b"new"))
            self.assertEqual(list(self.root.iterdir()), [])

    def test_lock_rejects_fifo_symlink_wrong_owner_and_writable_file(self):
        lock = self.root / "receiver.lock"
        os.mkfifo(lock, 0o600)
        with self.module.deadline(0.2), self.assertRaisesRegex(self.module.ReceiverError, "UNSAFE_LOCK"):
            with self.module.exclusive_lock(lock, owner=os.geteuid()):
                self.fail("fifo lock")
        lock.unlink()
        lock.symlink_to(self.root / "missing")
        with self.assertRaisesRegex(self.module.ReceiverError, "UNSAFE_LOCK"):
            with self.module.exclusive_lock(lock, owner=os.geteuid()):
                self.fail("symlink lock")
        lock.unlink()
        lock.write_bytes(b"")
        lock.chmod(0o666)
        with self.assertRaisesRegex(self.module.ReceiverError, "UNSAFE_LOCK"):
            with self.module.exclusive_lock(lock, owner=os.geteuid()):
                self.fail("writable lock")
        lock.chmod(0o600)
        with self.assertRaisesRegex(self.module.ReceiverError, "UNSAFE_LOCK"):
            with self.module.exclusive_lock(lock, owner=os.geteuid() + 1):
                self.fail("wrong owner")

    def test_main_prune_is_root_local_only_and_uses_the_shared_lock(self):
        for uid, environment in ((12345, {}), (0, {"SSH_CONNECTION": "synthetic"}),
                                 (0, {"SSH_ORIGINAL_COMMAND": "--prune"})):
            with patch.object(sys, "argv", [str(SCRIPT), "--prune"]), \
                    patch.dict(os.environ, environment, clear=True), patch.object(os, "geteuid", return_value=uid), \
                    patch.object(self.module, "exclusive_lock") as lock, \
                    redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
                self.assertEqual(self.module.main(), 1)
                lock.assert_not_called()
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(error.getvalue(), "백업 수신 실패\n")
        lock_path = self.root / "receiver.lock"
        lock_path.write_bytes(b"")
        lock_path.chmod(0o600)
        actual_owner = lock_path.stat().st_uid
        real_lock = self.module.exclusive_lock
        acquired = []
        @contextmanager
        def test_lock(path):
            self.assertEqual(path, lock_path)
            with real_lock(path, owner=actual_owner):
                acquired.append(True)
                yield
        with patch.object(sys, "argv", [str(SCRIPT), "--prune"]), patch.dict(os.environ, {}, clear=True), \
                patch.object(os, "geteuid", return_value=0), \
                patch.object(self.module.pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=actual_owner)), \
                patch.object(self.module, "ROOT", self.root), patch.object(self.module, "LOCK_FILE", lock_path), \
                patch.object(self.module, "exclusive_lock", side_effect=test_lock), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(self.module.main(), 0)
            self.assertEqual(json.loads(output.getvalue()), {"removed": 0})
        self.assertEqual(acquired, [True])

    def test_receiver_syntax_and_digest_path_do_not_require_newer_than_python38(self):
        tree = ast.parse(SCRIPT.read_text(), feature_version=(3, 8))
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr == "file_digest"
                             for node in ast.walk(tree)))

    def test_unrecognized_paths_and_truncated_frames_are_refused(self):
        for payload in (b'{"name":"../../source"}\nsecret', b'{}\n',
                        self.frame(b"cipher").getvalue()[:-1], self.frame(b"cipher").getvalue() + b"extra"):
            with self.subTest(payload=payload), self.assertRaises(self.module.ReceiverError):
                self.module.receive(self.root, io.BytesIO(payload))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_retry_recovers_exact_private_temporary_hardlink_after_process_crash(self):
        # finally가 실행되는 보통 예외가 아니라 link 직후 실제 프로세스 종료를 재현한다.
        child = '''import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("receiver_crash", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.LIMITS = module.Limits(4 * 1024 * 1024, 64, 0, 0)
original_link = os.link
def crash_after_link(*args, **kwargs):
    original_link(*args, **kwargs)
    os._exit(17)
module.os.link = crash_after_link
module.receive(sys.argv[2], sys.stdin.buffer)
'''
        content = b"complete synthetic ciphertext before crash"
        crashed = subprocess.run([sys.executable, "-c", child, str(SCRIPT), str(self.root)],
                                 input=self.frame(content).getvalue(), capture_output=True, timeout=10,
                                 env={"PATH": os.environ.get("PATH", "")})
        self.assertEqual(crashed.returncode, 17)
        path = next(self.root.glob("naver-received-*.cms"))
        original_inode = path.stat().st_ino
        self.assertEqual(path.stat().st_nlink, 2)
        self.assertEqual(len(list(self.root.glob(".receiving-*"))), 1)
        receipt = self.module.receive(self.root, self.frame(content))
        self.assertEqual(receipt, {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)})
        self.assertEqual(path.stat().st_ino, original_inode)
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_retry_does_not_generalize_crash_recovery_to_arbitrary_hardlinks(self):
        content = b"synthetic existing ciphertext"
        self.module.receive(self.root, self.frame(content))
        path = next(self.root.glob("naver-received-*.cms"))
        arbitrary = self.root / "operator-copy.cms"
        os.link(path, arbitrary)
        with self.assertRaises(self.module.ReceiverError):
            self.module.receive(self.root, self.frame(content))
        self.assertEqual(path.stat().st_nlink, 2)
        self.assertEqual(path.read_bytes(), content)
        self.assertTrue(arbitrary.exists())

    def test_retry_preserves_unverified_temporary_hardlink_content(self):
        content = b"expected synthetic ciphertext"
        path = self.root / ("naver-received-" + hashlib.sha256(content).hexdigest() + ".cms")
        path.write_bytes(b"different stored bytes")
        path.chmod(0o600)
        alias = self.root / ".receiving-abcdefgh"
        os.link(path, alias)
        with self.assertRaises(self.module.ReceiverError):
            self.module.receive(self.root, self.frame(content))
        self.assertEqual(path.stat().st_nlink, 2)
        self.assertTrue(alias.exists())
        self.assertEqual(path.read_bytes(), b"different stored bytes")

    def test_receiver_retention_uses_server_mtime_and_never_follows_symlinks(self):
        self.module.receive(self.root, self.frame(b"old"))
        old = next(self.root.glob("naver-received-*.cms"))
        now = datetime.now(timezone.utc)
        os.utime(old, ((now - timedelta(days=31)).timestamp(),) * 2)
        unrelated = self.root / "unrelated.txt"
        unrelated.write_bytes(b"keep")
        symlink = self.root / ("naver-received-" + "a" * 64 + ".cms")
        symlink.symlink_to(unrelated)
        self.assertEqual(self.module.prune(self.root, now=now, owner=os.geteuid()), 1)
        self.assertFalse(old.exists())
        self.assertTrue(symlink.is_symlink())
        self.assertEqual(unrelated.read_bytes(), b"keep")
