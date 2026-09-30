"""임시 합성 키와 실제 로컬 OpenSSL만 사용한다. SSH 전송은 모두 대역이다."""
import base64
import contextlib
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
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("backup_acceptance", ROOT / "tools/naver-backup-acceptance.py")
A = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(A)
OPENSSL = "/opt/homebrew/bin/openssl" if sys.platform == "darwin" else "/usr/bin/openssl"
REAL_RUN = subprocess.run
REAL_TEMP = tempfile.TemporaryDirectory


class AcceptanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = REAL_TEMP(prefix="acceptance-test-certificate-")
        cls.addClassCleanup(cls.fixture.cleanup)
        root = pathlib.Path(cls.fixture.name).resolve()
        cls.cert_path, key_path = root / "synthetic-cert.pem", root / "synthetic-key.pem"
        REAL_RUN([OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                  "-subj", "/CN=synthetic-acceptance-only", "-keyout", str(key_path),
                  "-out", str(cls.cert_path)], check=True, stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL, timeout=30)
        cls.certificate, cls.private = cls.cert_path.read_text(), key_path.read_text()

    def setUp(self):
        self.temp = REAL_TEMP(prefix="acceptance-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.evidence = self.root / "evidence"
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        self.ssh_calls, self.keygen_calls, self.sent = [], [], []
        self.keygen_result = (0, b"ssh-ed25519 synthetic-upload-public\n", b"")
        self.probe_result = None
        self.values = {name: f"{index:064x}" for index, name in enumerate((
            "SSO_AD_CENTER_CLIENT_KEY", "SSO_NAVER_CONTROL_CLIENT_KEY", "NAVER_ENGINE_ERP_KEY",
            "NAVER_AUTO_TOKEN_SECRET"), 1)}
        openssl_patch = patch.object(A.T, "OPENSSL", OPENSSL)
        openssl_patch.start()
        self.addCleanup(openssl_patch.stop)
        stage_patch = patch.object(A, "STAGE", "initial")
        stage_patch.start()
        self.addCleanup(stage_patch.stop)

    def fake_run(self, command, *args, **kwargs):
        if command[0] == OPENSSL:
            return REAL_RUN(command, *args, **kwargs)
        if command[0] == "/usr/bin/ssh-keygen":
            self.keygen_calls.append(command)
            self.assertEqual(command[1:3], ["-y", "-f"])
            self.assertEqual(pathlib.Path(command[3]).name, "upload-key")
            return subprocess.CompletedProcess(command, *self.keygen_result)
        if command[0] != A.T.SSH:
            raise AssertionError("허용하지 않은 외부 프로세스")
        self.ssh_calls.append(command)
        if len(self.ssh_calls) == 1 and self.probe_result is not None:
            self.assertEqual(command[-2:], [A.T.RECEIVER, "true"])
            self.assertEqual(kwargs.get("input"), b"")
            return subprocess.CompletedProcess(command, *self.probe_result)
        if "-R" in command:
            # -G는 설정만 펼친다. synthetic.invalid로 바꾸며 연결/인증/포워딩하지 않는다.
            probe = REAL_RUN([command[0], "-G", *command[1:-1], "synthetic.invalid"],
                             capture_output=True, timeout=5, env=A.T.COMMAND_ENV)
            self.assertEqual(probe.returncode, 0)
            self.assertIn(b"clearallforwardings no\n", probe.stdout)
            self.assertIn(b"remoteforward ", probe.stdout)
            return subprocess.CompletedProcess(command, 255, b"", b"remote port forwarding failed for listen port 0")
        if kwargs.get("input"):
            header, payload = kwargs["input"].split(b"\n", 1)
            self.assertNotEqual(json.loads(header)["sha256"], hashlib.sha256(payload).hexdigest())
        return subprocess.CompletedProcess(command, 1, b"", "백업 수신 실패\n".encode())

    def sender(self, cipher):
        payload = cipher.read_bytes()
        self.sent.append(payload)
        return {"sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)}

    def run_acceptance(self, mode, values):
        environment = {"ACCEPTANCE_MODE": mode, "ACCEPTANCE_EVIDENCE": str(self.evidence),
                       "NAVER_BACKUP_RECIPIENT_CERT_PEM": self.certificate, **values}
        def temporary(*args, **kwargs):
            kwargs.setdefault("dir", self.root)
            return REAL_TEMP(*args, **kwargs)
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(A.tempfile, "TemporaryDirectory", side_effect=temporary), \
                patch.object(A.subprocess, "run", side_effect=self.fake_run), \
                patch.object(A.T, "SshSender", return_value=self.sender), \
                contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            result = A.main()
        self.assert_private_output_absent(environment)
        return result

    def assert_private_output_absent(self, environment):
        output = self.stdout.getvalue() + self.stderr.getvalue()
        if self.evidence.exists():
            for artifact in self.evidence.rglob("*"):
                self.assertTrue(artifact.is_file())
                self.assertEqual(artifact.suffix, ".json")
                self.assertEqual(artifact.stat().st_mode & 0o777, 0o600)
                output += artifact.read_text()
        for value in (self.private, "PRIVATE KEY", "synthetic-upload-private", "RAW_PROCESS_DETAIL", str(self.root),
                      *self.values.values()):
            self.assertNotIn(value, output)
        self.assertFalse(any(path.name.startswith("naver-backup-acceptance-") for path in self.root.iterdir()))

    def stdout_reports(self):
        return [json.loads(line) for line in self.stdout.getvalue().splitlines()]

    def test_upload_key_terminal_newline_is_restored_and_real_openssh_parses_it(self):
        generated = self.root / "generated-synthetic-key"
        REAL_RUN(["/usr/bin/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(generated)],
                 check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        complete = generated.read_text()
        stripped = A.new_file(self.root / "stripped-synthetic-key", complete.rstrip("\n").encode())
        rejected = REAL_RUN(["/usr/bin/ssh-keygen", "-y", "-f", str(stripped)],
                            capture_output=True, timeout=10, env=A.T.COMMAND_ENV)
        self.assertNotEqual(rejected.returncode, 0)
        for index, value in enumerate((complete, complete.rstrip("\n"))):
            with patch.dict(os.environ, {"NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY": value}, clear=True):
                materialized = A.environment_file(self.root, "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY",
                                                 "materialized-synthetic-" + str(index))
                self.assertNotIn("NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY", os.environ)
            self.assertEqual(materialized.read_text(), complete)
            self.assertEqual(materialized.stat().st_mode & 0o777, 0o600)
            parsed = REAL_RUN(["/usr/bin/ssh-keygen", "-y", "-f", str(materialized)],
                              capture_output=True, timeout=10, env=A.T.COMMAND_ENV)
            self.assertEqual(parsed.returncode, 0)
        self.assertEqual(self.stdout.getvalue() + self.stderr.getvalue(), "")

    def assert_transfer_precheck_failure(self, expected_stage, expected_ssh_calls):
        code = self.run_acceptance("transfer", {
            "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY": "synthetic-upload-private",
            "NAVER_BACKUP_KNOWN_HOSTS": "synthetic-known-hosts",
        })
        self.assertEqual(code, 1)
        self.assertEqual(len(self.keygen_calls), 1)
        self.assertEqual(len(self.ssh_calls), expected_ssh_calls)
        self.assertEqual(self.sent, [])
        self.assertEqual(list(self.evidence.iterdir()), [])
        self.assertEqual(json.loads(self.stderr.getvalue()), {
            "status": "acceptance_failed", "stage": expected_stage, "secrets_printed": False,
        })
        reports = self.stdout_reports()
        self.assertTrue(reports)
        self.assertTrue(all(set(item) == {"status", "stage"} and item["status"] == "checking"
                            for item in reports))
        self.assertNotIn("first_upload", [item["stage"] for item in reports])

    def test_offline_key_parse_failure_blocks_ssh_and_upload_without_raw_diagnostics(self):
        self.keygen_result = (255, b"synthetic-upload-private", b"RAW_PROCESS_DETAIL PRIVATE KEY")
        self.assert_transfer_precheck_failure("offline_upload_key_parse", 0)

    def test_connection_failures_emit_only_safe_classification_and_never_upload(self):
        cases = (
            (b"Permission denied (publickey).", "authentication_refused"),
            (b"Host key verification failed", "host_key_refused"),
            (b"REMOTE HOST IDENTIFICATION HAS CHANGED", "host_key_refused"),
            (b"Connection timed out", "connection_timeout"),
            (b"Connection refused", "connection_refused"),
        )
        for index, (marker, expected_stage) in enumerate(cases):
            with self.subTest(stage=expected_stage, marker=marker):
                self.evidence = self.root / ("evidence-" + str(index))
                self.stdout, self.stderr = io.StringIO(), io.StringIO()
                self.ssh_calls, self.keygen_calls, self.sent = [], [], []
                self.probe_result = (255, b"synthetic-upload-private",
                                     marker + b" RAW_PROCESS_DETAIL PRIVATE KEY")
                self.assert_transfer_precheck_failure(expected_stage, 1)
                self.assertNotIn(marker.decode(), self.stdout.getvalue() + self.stderr.getvalue())

    def test_probe_exit255_is_not_refusal_success_even_with_receiver_error_text(self):
        self.probe_result = (255, b"RAW_PROCESS_DETAIL", "백업 수신 실패\n".encode())
        self.assert_transfer_precheck_failure("read_only_forced_command_probe", 1)

    def test_remote_execution_permission_failure_is_not_authentication_failure(self):
        self.probe_result = (126, b"", b"/bin/sh: 1: /usr/bin/python3: Permission denied\n")
        self.assert_transfer_precheck_failure("remote_execution_refused", 1)

    def test_generic_permission_text_cannot_prove_authentication_failure(self):
        self.probe_result = (255, b"", b"Permission denied RAW_PROCESS_DETAIL")
        self.assert_transfer_precheck_failure("read_only_forced_command_probe", 1)

    def test_read_only_probe_separates_remote_permission_error_from_authentication(self):
        self.probe_result = (2, b"RAW_PROCESS_DETAIL", b'Authenticated to private-host using "publickey".\n'
                             b"/usr/bin/python3: can't open file '/usr/local/libexec/metainc/naver-backup-receiver.py': Permission denied\n"
                             b"debug1: Exit status 2\nRAW_PROCESS_DETAIL PRIVATE KEY")
        code = self.run_acceptance("probe", {"NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY": "synthetic-upload-private",
                                             "NAVER_BACKUP_KNOWN_HOSTS": "synthetic-known-hosts"})
        self.assertEqual(0, code)
        self.assertEqual([], self.sent)
        self.assertEqual(1, len(self.ssh_calls))
        self.assertIn("-v", self.ssh_calls[0])
        report = self.stdout_reports()[-1]
        self.assertEqual(2, report["remote_exit_code"])
        self.assertTrue(report["signals"]["publickey_authentication_accepted"])
        self.assertTrue(report["signals"]["python_cannot_open_file"])
        self.assertFalse(report["signals"]["authentication_denied"])
        self.assertFalse(report["upload_attempted"])
        self.assertNotIn("private-host", self.stdout.getvalue())

    def test_probe_without_expected_receiver_refusal_never_reaches_upload(self):
        for code in (0, 1, 2):
            with self.subTest(exit_code=code):
                self.evidence = self.root / ("evidence-" + str(code))
                self.stdout, self.stderr = io.StringIO(), io.StringIO()
                self.ssh_calls, self.keygen_calls, self.sent = [], [], []
                self.probe_result = (code, b"synthetic-upload-private", b"RAW_PROCESS_DETAIL PRIVATE KEY")
                self.assert_transfer_precheck_failure("read_only_forced_command_probe", 1)

    def fixture_readback(self):
        folder = self.root / "readback-fixture"
        folder.mkdir(mode=0o700)
        archive, day = A.synthetic_archive(folder)
        cipher = folder / "fixture.cms"
        A.T.OpenSslEncryptor(self.cert_path)(archive, cipher)
        raw = cipher.read_bytes()
        return {"ciphertext_b64": base64.b64encode(raw).decode(),
                "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw), "expected_kst_date": day}

    def test_keys_mode_real_openssl_roundtrip_and_aead_rejection_emit_no_private_material(self):
        code = self.run_acceptance("keys", {**self.values, "NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM": self.private})
        self.assertEqual(code, 0, self.stderr.getvalue())
        report = self.stdout_reports()[-1]
        self.assertEqual(report["status"], "stored_ad_keys_verified")
        self.assertTrue(report["aead_tamper_refused"])
        self.assertEqual(report["restored"]["row_counts"], {"synthetic_leads": 3, "synthetic_events": 2})
        self.assertEqual(self.ssh_calls, [])

    def test_receiver_readback_real_ciphertext_restores_and_reports_only_evidence(self):
        readback = self.fixture_readback()
        code = self.run_acceptance("restore", {"NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM": self.private,
                                               "RECEIVED_SYNTHETIC_JSON": json.dumps(readback)})
        self.assertEqual(code, 0, self.stderr.getvalue())
        report = self.stdout_reports()[-1]
        self.assertEqual(report["status"], "received_synthetic_restore_verified")
        self.assertEqual(report["ciphertext_sha256"], readback["sha256"])
        self.assertTrue(report["aead_tamper_refused"])
        self.assertEqual(self.ssh_calls, [])

    def test_transfer_mockssh_and_effective_forwarding_options(self):
        code = self.run_acceptance("transfer", {"NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY": "synthetic-upload-private",
                                               "NAVER_BACKUP_KNOWN_HOSTS": "synthetic-known-hosts"})
        self.assertEqual(code, 0, self.stderr.getvalue())
        reports = self.stdout_reports()
        report = reports[-1]
        self.assertEqual(report["status"], "synthetic_transfer_verified")
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[0], self.sent[1])
        self.assertEqual(len(self.keygen_calls), 1)
        self.assertEqual(len(self.ssh_calls), 6)
        self.assertEqual([item["stage"] for item in reports if item["status"] == "checking"], [
            "offline_upload_key_parse", "read_only_forced_command_probe", "synthetic_encryption",
            "first_upload", "same_content_retry", "tampered_transport_refusal", "remote_command_refusal",
            "remote_prune_refusal", "sftp_refusal", "forwarding_refusal",
        ])
        fixture = next(item for item in reports if item["status"] == "synthetic_fixture")
        self.assertEqual(fixture["ciphertext"], report["ciphertext"])
        self.assertEqual(fixture["expected_kst_date"], report["expected_kst_date"])
        self.assertTrue(all(report[name] for name in ("same_content_retry", "tamper_refused",
            "remote_command_refused", "remote_prune_refused", "sftp_refused", "forwarding_refused")))
        self.assertFalse(report["engine_host_sender_verified"])

    def test_authentication_exit255_and_false_receipts_are_not_refusal_success(self):
        for code, output in ((255, b""), (0, b""), (1, b'{"sha256":"fake"}')):
            with self.subTest(code=code, output=output), \
                    patch.object(A.subprocess, "run", return_value=subprocess.CompletedProcess([], code, output, b"")), \
                    self.assertRaises(ValueError):
                A.ssh_check([A.T.SSH, "synthetic.invalid"])

    def test_tampered_aead_cipher_with_matching_outer_hash_never_reports_success(self):
        readback = self.fixture_readback()
        raw = bytearray(base64.b64decode(readback["ciphertext_b64"]))
        raw[-5] ^= 1
        readback.update(ciphertext_b64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())
        code = self.run_acceptance("restore", {"NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM": self.private,
                                               "RECEIVED_SYNTHETIC_JSON": json.dumps(readback)})
        self.assertEqual(code, 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertEqual(json.loads(self.stderr.getvalue())["status"], "acceptance_failed")
        self.assertEqual(list(self.evidence.iterdir()), [])

    def test_recovery_rejects_upload_private_key_even_when_other_values_are_valid(self):
        code = self.run_acceptance("keys", {**self.values, "NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM": self.private,
                                            "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY": "synthetic-upload-private"})
        self.assertEqual(code, 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertEqual(list(self.evidence.iterdir()), [])

    def test_transfer_rejects_recovery_private_key_before_any_ssh_call(self):
        code = self.run_acceptance("transfer", {"NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM": self.private,
            "NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY": "synthetic-upload-private", "NAVER_BACKUP_KNOWN_HOSTS": "synthetic"})
        self.assertEqual(code, 1)
        self.assertEqual(self.ssh_calls, [])
        self.assertEqual(self.sent, [])

    def test_keys_mode_rejects_duplicate_dedicated_values_without_success_artifact(self):
        values = {**self.values, "NAVER_AUTO_TOKEN_SECRET": self.values["SSO_AD_CENTER_CLIENT_KEY"],
                  "NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM": self.private}
        self.assertEqual(self.run_acceptance("keys", values), 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertEqual(list(self.evidence.iterdir()), [])
        self.assertEqual(self.ssh_calls, [])

    def test_readback_outer_hash_mismatch_is_refused_without_success_artifact(self):
        readback = self.fixture_readback()
        readback["sha256"] = "0" * 64
        self.assertEqual(self.run_acceptance("restore", {
            "NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM": self.private,
            "RECEIVED_SYNTHETIC_JSON": json.dumps(readback)}), 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertEqual(list(self.evidence.iterdir()), [])

    def test_workflow_separates_private_keys_and_limits_new_jobs_to_manual_approved_branch(self):
        workflow = (ROOT / ".github/workflows/naver-runtime-tests.yml").read_text()
        transfer = workflow.split("  backup-transfer:\n", 1)[1].split("  backup-recovery:\n", 1)[0]
        recovery = workflow.split("  backup-recovery:\n", 1)[1].split("  linux-tests:\n", 1)[0]
        self.assertIn("NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY:", transfer)
        self.assertNotIn("NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM", transfer)
        self.assertIn("NAVER_BACKUP_RECOVERY_PRIVATE_KEY_PEM:", recovery)
        self.assertNotIn("NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY", recovery)
        self.assertIn("environment: naver-backup-recovery", recovery)
        for job in (transfer, recovery):
            self.assertIn("github.event_name == 'workflow_dispatch'", job)
            self.assertIn("github.ref == 'refs/heads/codex/naver-backup-recovery-20261001'", job)
            self.assertIn("persist-credentials: false", job)
            self.assertIn("-evidence/*.json", job)


if __name__ == "__main__":
    unittest.main()
