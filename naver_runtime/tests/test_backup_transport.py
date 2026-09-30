"""외부 접속 없는 암호화·명령 관문 시험. 키는 시험용 임시 생성 후 폐기한다."""
import json
import io
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from naver_runtime import backup_transport as T


class CryptoTest(unittest.TestCase):
    def test_cms_public_certificate_roundtrip_and_tampering_is_rejected(self):
        openssl = shutil.which("openssl")
        self.assertIsNotNone(openssl)
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder).resolve()
            key, cert = root / "test-key.pem", root / "test-cert.pem"
            subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj",
                            "/CN=synthetic-backup-test", "-keyout", str(key), "-out", str(cert), "-days", "1"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            source, encrypted = root / "plain.zip", root / "encrypted.cms"
            source.write_bytes(b"synthetic private snapshot" * 100)
            source.chmod(0o600)
            with patch.object(T, "OPENSSL", openssl):
                T.OpenSslEncryptor(cert)(source, encrypted)
            decrypted = subprocess.run([openssl, "cms", "-decrypt", "-binary", "-inform", "DER",
                                        "-in", str(encrypted), "-recip", str(cert), "-inkey", str(key)],
                                       check=True, capture_output=True).stdout
            self.assertEqual(decrypted, source.read_bytes())
            data = bytearray(encrypted.read_bytes())
            data[-5] ^= 1
            encrypted.write_bytes(data)
            bad = subprocess.run([openssl, "cms", "-decrypt", "-binary", "-inform", "DER",
                                  "-in", str(encrypted), "-recip", str(cert), "-inkey", str(key)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.assertNotEqual(bad.returncode, 0)

    def test_ssh_sender_has_fixed_host_and_strict_host_key_without_remote_command(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder).resolve()
            key, hosts, payload = root / "upload-key", root / "known-hosts", root / "cipher.cms"
            for p in (key, hosts, payload):
                p.write_bytes(b"synthetic")
                p.chmod(0o600)
            with patch.object(T.subprocess, "Popen") as run:
                run.return_value.stdout = io.BytesIO(b'{"sha256":"digest","size":9}')
                run.return_value.wait.return_value = 0
                result = T.SshSender(key, hosts)(payload)
            command = run.call_args.args[0]
            self.assertEqual(command[-1], "naver-backup@api.metainc.co.kr")
            self.assertIn("StrictHostKeyChecking=yes", command)
            self.assertIn("BatchMode=yes", command)
            self.assertFalse(run.call_args.kwargs["shell"])
            self.assertEqual(result["size"], 9)

    def test_payload_larger_than_tmpfs_limit_stages_only_in_private_backup_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder).resolve()
            key, hosts, payload = root / "upload-key", root / "known-hosts", root / "cipher.cms"
            for p in (key, hosts, payload):
                p.write_bytes(b"synthetic")
                p.chmod(0o600)
            with payload.open("r+b") as stream:
                stream.truncate(65 * 1024 * 1024)
            original = T.tempfile.TemporaryFile
            def temporary(*args, **kwargs):
                self.assertEqual(kwargs.get("dir"), root)
                result = original(*args, **kwargs)
                self.assertEqual(os.fstat(result.fileno()).st_mode & 0o777, 0o600)
                return result
            with patch.object(T.tempfile, "TemporaryFile", side_effect=temporary), \
                    patch.object(T.subprocess, "Popen") as run:
                run.return_value.stdout = io.BytesIO(b'{"sha256":"digest","size":68157440}')
                run.return_value.wait.return_value = 0
                self.assertEqual(T.SshSender(key, hosts)(payload)["size"], 65 * 1024 * 1024)

    def test_oversized_receipt_and_timeout_kill_sender_without_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder).resolve()
            key, hosts, payload = root / "upload-key", root / "known-hosts", root / "cipher.cms"
            for p in (key, hosts, payload):
                p.write_bytes(b"synthetic")
                p.chmod(0o600)
            with patch.object(T.subprocess, "Popen") as run:
                run.return_value.stdout = io.BytesIO(b"x" * 2049)
                run.return_value.wait.return_value = 0
                with self.assertRaises(T.BackupError):
                    T.SshSender(key, hosts)(payload)
                run.return_value.kill.assert_called_once()
            with patch.object(T.subprocess, "Popen") as run:
                run.return_value.stdout = io.BytesIO(b"")
                run.return_value.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 300), -9]
                with self.assertRaises(T.BackupError):
                    T.SshSender(key, hosts)(payload)
                run.return_value.kill.assert_called_once()
