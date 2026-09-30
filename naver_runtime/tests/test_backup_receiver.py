"""합성 표준입력과 임시 폴더만 사용하는 수신 전용 프로토콜 시험."""
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "naver-backup-receiver.py"


class ReceiverTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("backup_receiver", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
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
