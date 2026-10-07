"""실제 합성 RSA/Ed25519·OpenSSL 시험. 운영 키·네트워크·서버는 사용하지 않는다."""
import contextlib
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("preview_seal", ROOT / "tools/naver-preview-seal.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)
OPENSSL = "/opt/homebrew/bin/openssl" if sys.platform == "darwin" else "/usr/bin/openssl"


def certificate(key, expired=False):
    now = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-preview-only")])
    return (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=2))
            .not_valid_after(now - timedelta(days=1) if expired else now + timedelta(days=1))
            .sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode())


class SealTest(unittest.TestCase):
    def test_workflow_optional_empty_input_may_be_omitted_but_not_populated(self):
        values = {'preview_seal': True, 'server_envelope_cert_pem': 'public', 'backup_acceptance': 'none'}
        self.assertEqual(P.validate_workflow_inputs(values), 'public')
        self.assertEqual(P.validate_workflow_inputs({**values, 'received_synthetic_json': ''}), 'public')
        for bad in ({**values, 'received_synthetic_json': '{}'}, {**values, 'unexpected': ''},
                    {**values, 'preview_seal': 'true'}, {**values, 'backup_acceptance': 'restore'}):
            with self.assertRaises(P.SealError):
                P.validate_workflow_inputs(bad)

    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.cert = certificate(cls.key)
        cls.upload = ed25519.Ed25519PrivateKey.generate()
        cls.host = ec.generate_private_key(ec.SECP256R1()).public_key()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="preview-seal-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.output = self.root / "cipher-only"
        pin = patch.object(P, "SERVER_CERT_PEM_SHA256", hashlib.sha256(self.cert.encode()).hexdigest())
        pin.start()
        self.addCleanup(pin.stop)
        self.env = {
            "SSO_NAVER_CONTROL_CLIENT_KEY": "1" * 64, "NAVER_ENGINE_ERP_KEY": "2" * 64,
            "NAVER_AUTO_TOKEN_SECRET": "3" * 64, "NAVER_MGR_CUSTOMER_ID": "1234567",
            "NAVER_MGR_API_KEY": "SYNTHETIC_ACCESS_MARKER", "NAVER_MGR_SECRET_KEY": "SYNTHETIC_SECRET_MARKER",
            "NAVER_BACKUP_RECIPIENT_CERT_PEM": self.cert,
            "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY": self.upload.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption()).decode(),
            "NAVER_BACKUP_KNOWN_HOSTS": "api.metainc.co.kr " + self.host.public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode() + "\n",
        }

    def seal(self, env=None, cert=None, *, compress_payload=False, source_tar_gz=b"synthetic-source"):
        with patch.object(P, "OPENSSL", OPENSSL):
            return P.seal_bundle(self.env if env is None else env, self.cert if cert is None else cert,
                                 self.output, source_commit=P.ACCOUNT_FIRST_COMMIT if compress_payload else "a" * 40,
                                 source_tar_gz=source_tar_gz, compress_payload=compress_payload)

    def decrypted_wire(self):
        private = self.root / "synthetic-decryption-key.pem"
        private.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        return subprocess.run([OPENSSL, "cms", "-decrypt", "-binary", "-inform", "DER",
                               "-in", str(self.output / "runtime-secrets.cms"), "-inkey", str(private)],
                              capture_output=True, timeout=10, check=True).stdout

    def test_roundtrip_contains_exact_runtime_and_backup_files_only(self):
        receipt = self.seal()
        private = self.root / "synthetic-decryption-key.pem"
        private.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        private.chmod(0o600)
        result = subprocess.run([OPENSSL, "cms", "-decrypt", "-binary", "-inform", "DER",
                                 "-in", str(self.output / "runtime-secrets.cms"), "-inkey", str(private)],
                                capture_output=True, timeout=10, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(set(payload), {"schema", "purpose", "files", "source_commit", "source_tar_gz_b64"})
        self.assertEqual(payload["purpose"], "naver-owner-verification-runtime")
        files = {row["path"]: row for row in payload["files"]}
        self.assertEqual(set(files), {
            "/etc/metainc/naver-engine/runtime.env", "/etc/metainc/naver-engine/backup-recipient.pem",
            "/etc/metainc/naver-engine/backup-upload-key", "/etc/metainc/naver-engine/backup-known-hosts"})
        runtime = files["/etc/metainc/naver-engine/runtime.env"]["content"]
        for flag in ("SYNC", "LINKS", "MORNING", "WEB", "BACKUP"):
            self.assertIn("NAVER_ENGINE_" + flag + "_ENABLED=true\n", runtime)
        for flag in ("ALERTS", "METRICS", "ISSUE_ALERTS"):
            self.assertIn("NAVER_ENGINE_" + flag + "_ENABLED=false\n", runtime)
        self.assertNotIn("SSO_AD_CENTER_CLIENT_KEY", runtime)
        self.assertNotIn("NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM", result.stdout.decode())
        self.assertEqual({row["mode"] for row in files.values()}, {0o600})
        self.assertEqual(files["/etc/metainc/naver-engine/backup-upload-key"]["uid"], 10001)
        cipher = (self.output / "runtime-secrets.cms").read_bytes()
        self.assertEqual(receipt["ciphertext_sha256"], hashlib.sha256(cipher).hexdigest())
        self.assertEqual(receipt["ciphertext_size"], len(cipher))
        self.assertLess(len(cipher), 20 * 1024)
        self.assertEqual({p.name for p in self.output.iterdir()}, {"runtime-secrets.cms", "receipt.json"})

    def test_compressed_approved_source_roundtrip_preserves_schema_one_and_source_bytes(self):
        commit = "e4f64e165ebdf81d4127218d5c91ff6904e75958"
        source = b"synthetic-approved-source"
        with patch.object(P, "OPENSSL", OPENSSL):
            receipt = P.seal_bundle(self.env, self.cert, self.output, source_commit=commit,
                                    source_tar_gz=source, compress_payload=True)
        wire = self.decrypted_wire()
        magic = b"NAVER-PREVIEW-PAYLOAD-GZIP-1\n"
        self.assertTrue(wire.startswith(magic))
        raw = gzip.decompress(wire[len(magic):])
        self.assertEqual(wire, magic + gzip.compress(raw, mtime=0))
        payload = json.loads(raw)
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["purpose"], "naver-owner-verification-runtime")
        self.assertEqual(payload["source_commit"], commit)
        self.assertEqual(base64.b64decode(payload["source_tar_gz_b64"], validate=True), source)
        self.assertEqual(payload["files"], P.runtime_files(self.env))
        self.assertEqual(receipt["source_tar_gz_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual({p.name for p in self.output.iterdir()}, {"runtime-secrets.cms", "receipt.json"})

    def test_compressed_encoding_is_explicit_boolean_and_requires_approved_pin(self):
        for index, value in enumerate((None, 1, "true")):
            with self.subTest(value=value), patch.object(P, "OPENSSL", OPENSSL), \
                    self.assertRaisesRegex(P.SealError, "INVALID_PAYLOAD_ENCODING"):
                P.seal_bundle(self.env, self.cert, self.root / ("invalid-encoding-" + str(index)),
                              source_commit=P.ACCOUNT_FIRST_COMMIT, source_tar_gz=b"source", compress_payload=value)
        with self.assertRaisesRegex(P.SealError, "UNAPPROVED_COMPRESSED_SOURCE"):
            P.seal_bundle(self.env, self.cert, self.output, source_commit="a" * 40,
                          source_tar_gz=b"source", compress_payload=True)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_approved_full_source_and_max_runtime_lengths_fit_unchanged_wire_and_cipher_limits(self):
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                              check=True, timeout=10).stdout.decode().strip()
        source = P.source_archive(P.ACCOUNT_FIRST_COMMIT, checkout_commit=head)
        rng = random.Random(20261004)
        def text(size):
            return "".join(chr(rng.randrange(33, 127)) for _ in range(size))
        env = {**self.env, "SSO_NAVER_CONTROL_CLIENT_KEY": "f" * 64,
               "NAVER_ENGINE_ERP_KEY": text(256), "NAVER_AUTO_TOKEN_SECRET": text(512),
               "NAVER_MGR_CUSTOMER_ID": "9" * 15, "NAVER_MGR_API_KEY": text(512),
               "NAVER_MGR_SECRET_KEY": text(512)}
        receipt = self.seal(env=env, compress_payload=True, source_tar_gz=source)
        wire = self.decrypted_wire()
        raw = gzip.decompress(wire[len(P.PAYLOAD_GZIP_MAGIC):])
        payload = json.loads(raw)
        self.assertEqual(base64.b64decode(payload["source_tar_gz_b64"], validate=True), source)
        self.assertEqual(receipt["source_tar_gz_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(P.MAX_BUNDLE, 2 * 1024 * 1024)
        self.assertEqual(P.MAX_PAYLOAD, 3 * 1024 * 1024)
        self.assertLess(len(source), P.MAX_BUNDLE)
        self.assertLess(len(wire), P.MAX_BUNDLE - 4096)
        self.assertLessEqual(receipt["ciphertext_size"], P.MAX_BUNDLE)
        self.assertLessEqual(len(raw), P.MAX_PAYLOAD)
        # Conservative size-only bound over credentials accepted by runtime_files:
        # real env max 2670 bytes; certificate/key <=4096 as incompressible printable text,
        # which overstates PEM entropy. The ECDSA host line is fixed by validation: a P-256
        # key blob with trailing data is refused. The canonical line is 179 bytes and the
        # non-strict base64 decoder also accepts one redundant '=', so the accepted max is 180.
        self.assertEqual(len(payload["files"][0]["content"]), 2670)
        host = payload["files"][3]["content"]
        self.assertEqual(len(host), 179)
        prefix, blob = host.rstrip("\n").rsplit(" ", 1)
        padded = prefix + " " + base64.b64encode(base64.b64decode(blob) + b"\x00" * 3000).decode() + "\n"
        with self.assertRaises(ValueError):
            P.runtime_files({**env, "NAVER_BACKUP_KNOWN_HOSTS": padded})
        longest = host.rstrip("\n") + "=\n"
        self.assertEqual(len(P.runtime_files({**env, "NAVER_BACKUP_KNOWN_HOSTS": longest})[3]["content"]), 180)
        with self.assertRaises(ValueError):
            P.runtime_files({**env, "NAVER_BACKUP_KNOWN_HOSTS": host.rstrip("\n") + "==\n"})
        for row in payload["files"][1:3]:
            row["content"] = text(4096)
        payload["files"][3]["content"] = text(180)
        self.assertEqual(sum(len(row["content"]) for row in payload["files"]), 11042)
        bounded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("ascii")
        self.assertLessEqual(len(bounded), P.MAX_PAYLOAD)
        self.assertLess(len(P.PAYLOAD_GZIP_MAGIC + gzip.compress(bounded, mtime=0)), P.MAX_BUNDLE - 4096)

    def test_compressed_json_wire_and_ciphertext_overflow_are_refused_before_output(self):
        with patch.object(P, "MAX_PAYLOAD", 1), self.assertRaisesRegex(P.SealError, "PAYLOAD_TOO_LARGE"):
            self.seal(compress_payload=True)
        self.assertFalse(self.output.exists())
        source = random.Random(20261004).randbytes(P.MAX_BUNDLE - 1)
        with self.assertRaisesRegex(P.SealError, "BUNDLE_TOO_LARGE"):
            self.seal(compress_payload=True, source_tar_gz=source)
        self.assertFalse(self.output.exists())
        oversized = subprocess.CompletedProcess([], 0, stdout=b"x" * (P.MAX_BUNDLE + 1))
        with patch.object(P.subprocess, "run", return_value=oversized), \
                self.assertRaisesRegex(P.SealError, "CIPHERTEXT_TOO_LARGE"):
            self.seal(compress_payload=True)
        self.assertFalse(self.output.exists())
        # Legacy mode must still refuse JSON beyond its original 2MiB-4096 bound,
        # even if its repetitive source could fit the compressed encoding.
        with self.assertRaisesRegex(P.SealError, "BUNDLE_TOO_LARGE"):
            self.seal(source_tar_gz=b"x" * (1600 * 1024))
        self.assertFalse(self.output.exists())

    def test_invalid_public_certificates_are_rejected_before_output(self):
        expired = certificate(self.key, expired=True)
        private = self.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()).decode()
        for value in ("", "BAD_CERT_MARKER", self.cert + self.cert, private, expired, "a" * 4097,
                      self.cert + "OTHER_FILE_MARKER", self.cert.replace("\n", "\r\n")):
            with self.subTest(case=value[:20]):
                with self.assertRaises((P.SealError, ValueError)):
                    self.seal(cert=value)
                self.assertFalse(self.output.exists())

    def test_valid_but_unapproved_public_certificate_cannot_receive_credentials(self):
        other = certificate(rsa.generate_private_key(public_exponent=65537, key_size=2048))
        with self.assertRaises(P.SealError):
            self.seal(cert=other)
        self.assertFalse(self.output.exists())

    def test_missing_credentials_newline_injection_and_foreign_keys_are_rejected(self):
        bad_environments = [{k: v for k, v in self.env.items() if k != name} for name in P.SECRET_NAMES]
        for name in P.SECRET_NAMES[:6]:
            for tail in ("\nNAVER_ENGINE_ALERTS_ENABLED=true", "\r", "\x00", "\n", " "):
                bad_environments.append({**self.env, name: self.env[name] + tail})
        for name in ("NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM", "VPS_SSH_KEY", "SSO_AD_CENTER_CLIENT_KEY"):
            bad_environments.append({**self.env, name: "FOREIGN_PRIVATE_MARKER"})
        for env in bad_environments:
            with self.assertRaises(Exception):
                self.seal(env=env)
            self.assertFalse(self.output.exists())

    def test_backup_key_and_host_line_are_strict(self):
        for name, value in (
            ("NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY", "PRIVATE_MARKER"),
            ("NAVER_BACKUP_KNOWN_HOSTS", self.env["NAVER_BACKUP_KNOWN_HOSTS"] + "evil.invalid ssh-ed25519 bad\n"),
            ("NAVER_BACKUP_KNOWN_HOSTS", self.env["NAVER_BACKUP_KNOWN_HOSTS"].replace("api.metainc.co.kr", "evil.invalid")),
            ("NAVER_BACKUP_KNOWN_HOSTS", "api.metainc.co.kr ssh-ed25519 eA==\n"),
            ("NAVER_BACKUP_KNOWN_HOSTS", "api.metainc.co.kr " + self.upload.public_key().public_bytes(
                serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode() + "\n"),
        ):
            with self.subTest(name=name), self.assertRaises(Exception):
                self.seal(env={**self.env, name: value})
        self.assertFalse(self.output.exists())

    def test_runtime_paths_cannot_be_overridden_and_match_runtime_loader(self):
        values = {**self.env, "NAVER_ENGINE_DB": "/etc/unsafe", "NAVER_BACKUP_CERT": "/wrong",
                  "NAVER_ENGINE_ALERTS_ENABLED": "true"}
        files = P.runtime_files(values)
        runtime = dict(line.split("=", 1) for line in files[0]["content"].splitlines())
        from naver_runtime.config import Config
        config = Config.from_env(runtime)
        config.validate_runtime(runtime)
        self.assertEqual(config.db, "/var/lib/naver-engine/engine.db")
        self.assertEqual(config.socket, "/run/naver-engine/engine.sock")
        self.assertEqual(config.erp_tunnel_socket, "/run/naver-erp-tunnel/erp.sock")
        self.assertFalse(config.alerts_enabled)
        self.assertEqual(runtime["NAVER_BACKUP_CERT"], "/run/secrets/naver-backup-recipient.pem")

    def test_unsafe_paths_existing_outputs_and_oversized_source_are_refused(self):
        existing = self.root / "existing"
        existing.mkdir()
        linked = self.root / "linked"
        linked.symlink_to(existing, target_is_directory=True)
        for output in (Path("relative"), existing, linked, linked / "new"):
            with self.subTest(path=str(output)), self.assertRaises(P.SealError):
                P.seal_bundle(self.env, self.cert, output, source_commit="a" * 40, source_tar_gz=b"source")
        with self.assertRaises(P.SealError):
            P.seal_bundle(self.env, self.cert, self.output, source_commit="a" * 40,
                          source_tar_gz=b"s" * P.MAX_BUNDLE)
        self.assertEqual(list(existing.iterdir()), [])
        self.assertFalse(self.output.exists())

    def test_tampered_ciphertext_is_not_accepted_by_real_openssl(self):
        private = self.root / "synthetic-key.pem"
        private.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        for compressed in (False, True):
            with self.subTest(compressed=compressed):
                self.output = self.root / ("cipher-" + str(compressed))
                self.seal(compress_payload=compressed)
                cipher = bytearray((self.output / "runtime-secrets.cms").read_bytes())
                cipher[-5] ^= 1
                result = subprocess.run([OPENSSL, "cms", "-decrypt", "-binary", "-inform", "DER", "-inkey", str(private)],
                                         input=bytes(cipher), capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)

    def workflow_env(self):
        return {**self.env, "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": P.BRANCH,
                "GITHUB_SHA": "a" * 40, "PREVIEW_SEAL_OUTPUT": str(self.output),
                "PREVIEW_SEAL_INPUTS": json.dumps({"preview_seal": True, "server_envelope_cert_pem": self.cert,
                    "backup_acceptance": "none", "received_synthetic_json": ""})}

    def test_cli_prints_only_cipher_receipt_and_never_raw_source_keys_or_paths(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.workflow_env(), clear=True), patch.object(sys, "argv", ["seal"]), \
             patch.object(P, "OPENSSL", OPENSSL), patch.object(P, "source_archive", return_value=b"SOURCE_MARKER"), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(P.main(), 0)
        output = stdout.getvalue() + stderr.getvalue() + (self.output / "receipt.json").read_text()
        for value in (*self.env.values(), str(self.root), "SOURCE_MARKER", "PRIVATE KEY"):
            self.assertNotIn(value, output)
        self.assertEqual(set(json.loads(stdout.getvalue())), {"ciphertext_sha256", "ciphertext_size",
            "public_certificate_sha256", "source_commit", "source_tar_gz_sha256"})
        self.assertEqual({p.name for p in self.root.iterdir()}, {"cipher-only"})
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in self.output.iterdir()))
        legacy = self.decrypted_wire()
        self.assertTrue(legacy.startswith(b"{"))
        self.assertEqual(json.loads(legacy)["schema"], 1)

    def test_account_first_cli_seals_only_approved_source_commit(self):
        # Release tooling may advance, but the approved application archive must not.
        env = {**self.workflow_env(), "GITHUB_REF": "refs/heads/codex/naver-account-first-20261002",
               "GITHUB_SHA": "c" * 40}
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, env, clear=True), patch.object(sys, "argv", ["seal"]), \
             patch.object(P, "OPENSSL", OPENSSL), patch.object(P, "source_archive", return_value=b"APPROVED_SOURCE"), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(P.main(), 0)
        receipt = json.loads(stdout.getvalue())
        self.assertEqual(receipt["source_commit"], "e4f64e165ebdf81d4127218d5c91ff6904e75958")
        self.assertEqual(receipt["source_tar_gz_sha256"], hashlib.sha256(b"APPROVED_SOURCE").hexdigest())
        self.assertEqual(stderr.getvalue(), "")
        self.assertTrue(self.decrypted_wire().startswith(b"NAVER-PREVIEW-PAYLOAD-GZIP-1\n"))

    def test_cli_context_wrong_modes_and_subprocess_errors_never_leak(self):
        for field, value in (("GITHUB_EVENT_NAME", "push"), ("GITHUB_REF", "refs/heads/main"),
                             ("PREVIEW_SEAL_INPUTS", "RAW_INPUT_MARKER")):
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {**self.workflow_env(), field: value}, clear=True), \
                 patch.object(sys, "argv", ["seal"]), contextlib.redirect_stdout(stdout), \
                 contextlib.redirect_stderr(stderr):
                self.assertEqual(P.main(), 1)
            self.assertEqual(stdout.getvalue(), "")
            expected = "PREVIEW_SEAL_REFUSED\n" if field == 'PREVIEW_SEAL_INPUTS' else "PREVIEW_SEAL_REFUSED:INVALID_WORKFLOW_CONTEXT\n"
            self.assertEqual(stderr.getvalue(), expected)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.workflow_env(), clear=True), patch.object(sys, "argv", ["seal"]), \
             patch.object(P, "source_archive", side_effect=RuntimeError("PRIVATE_PROCESS_MARKER")), \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            self.assertEqual(P.main(), 1)
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "PREVIEW_SEAL_REFUSED\n")


class SourceArchiveTest(unittest.TestCase):
    def test_approved_ancestor_archive_is_unchanged_and_checkout_or_lineage_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="preview-source-pin-fixture-") as temporary:
            root = Path(temporary).resolve()
            def git(*args):
                return subprocess.run(["git", "-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid",
                    *args], cwd=root, capture_output=True, check=True, timeout=10).stdout.decode().strip()
            git("init")
            for name in P.SOURCE_PATHS:
                target = root / name
                if "." not in target.name:
                    target = target / "fixture.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("approved-source")
            git("add", ".")
            git("commit", "-m", "Approved synthetic source")
            approved = git("rev-parse", "HEAD")
            expected = P.source_archive(approved, root=root)
            changed = root / "naver_engine" / "fixture.txt"
            changed.write_text("must-not-be-sealed")
            git("add", ".")
            git("commit", "-m", "New workflow checkout")
            checkout = git("rev-parse", "HEAD")
            self.assertEqual(P.source_archive(approved, root=root, checkout_commit=checkout), expected)
            with self.assertRaises(P.SealError):
                P.source_archive(approved, root=root, checkout_commit=approved)
            with self.assertRaises(P.SealError):
                P.source_archive(approved, root=root, checkout_commit="")
            git("checkout", "-b", "unrelated-release", approved)
            changed.write_text("unrelated-checkout")
            git("add", ".")
            git("commit", "-m", "Unrelated checkout")
            with self.assertRaises(P.SealError):
                P.source_archive(checkout, root=root, checkout_commit=git("rev-parse", "HEAD"))

    def test_excluded_test_folders_are_refused_if_an_archive_still_carries_them(self):
        # Defence in depth: even if git ignored the exclude pathspec, a test file must not be sealed.
        commit = "c" * 40
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for name in (*P.SOURCE_PATHS, P.SOURCE_EXCLUDED_PATHS[0] + "/test_leak.py"):
                data = b"x"
                info = tarfile.TarInfo(name if "." in Path(name).name else name + "/fixture.txt")
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        def fake_run(args, **kwargs):
            if args[:2] == ["git", "rev-parse"]:
                return subprocess.CompletedProcess(args, 0, stdout=(commit + "\n").encode())
            if args[:2] == ["git", "merge-base"]:
                return subprocess.CompletedProcess(args, 0, stdout=b"")
            self.assertEqual(args[:4], ["git", "archive", "--format=tar", commit])
            self.assertEqual([a for a in args if a.startswith(":(exclude)")],
                             [":(exclude)" + x for x in P.SOURCE_EXCLUDED_PATHS])
            return subprocess.CompletedProcess(args, 0, stdout=buffer.getvalue())
        with patch.object(P.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(P.SealError, "UNSAFE_SOURCE_ARCHIVE"):
                P.source_archive(commit, root=ROOT)

    def test_exact_committed_allowlist_only_and_bad_commit_or_symlink_refused(self):
        with tempfile.TemporaryDirectory(prefix="preview-source-fixture-") as temporary:
            root = Path(temporary).resolve()
            def git(*args):
                return subprocess.run(["git", "-c", "user.name=Synthetic Test", "-c", "user.email=synthetic@example.invalid",
                    *args], cwd=root, capture_output=True, check=True, timeout=10).stdout.decode().strip()
            git("init")
            for name in P.SOURCE_PATHS:
                target = root / name
                if "." not in target.name:
                    target = target / "fixture.txt"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("synthetic-source")
            (root / "excluded-secret-marker").write_text("NOT_IN_ARCHIVE")
            for name in P.SOURCE_EXCLUDED_PATHS:
                (root / name).mkdir(parents=True, exist_ok=True)
                (root / name / "test_fixture.py").write_text("TEST_NOT_IN_ARCHIVE")
            git("add", ".")
            git("commit", "-m", "Synthetic archive fixture")
            commit = git("rev-parse", "HEAD")
            source = P.source_archive(commit, root=root)
            self.assertEqual(source, P.source_archive(commit, root=root))
            with tarfile.open(fileobj=io.BytesIO(gzip.decompress(source)), mode="r:") as archive:
                names = archive.getnames()
                self.assertNotIn("excluded-secret-marker", names)
                # Test folders never ship: the runtime images drop **/tests/ and the server never runs them.
                self.assertEqual([n for n in names if any(n == x or n.startswith(x + "/")
                                                          for x in P.SOURCE_EXCLUDED_PATHS)], [])
                self.assertIn("naver_engine/fixture.txt", names)
                self.assertIn("naver_runtime/fixture.txt", names)
            with self.assertRaises(P.SealError):
                P.source_archive("b" * 40, root=root)
            (root / "naver_engine" / "link").symlink_to("/etc/passwd")
            git("add", ".")
            git("commit", "-m", "Synthetic unsafe archive fixture")
            with self.assertRaises(P.SealError):
                P.source_archive(git("rev-parse", "HEAD"), root=root)
