"""Offline tests only: every GitHub boundary is mocked; no CLI provisioning.

All generated cryptographic material is ephemeral test data. The public-output
directory and mocked GitHub values live only in a TemporaryDirectory/in memory.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa


SPEC = importlib.util.spec_from_file_location(
    "naver_key_provision", pathlib.Path(__file__).with_name("naver-key-provision.py"))
provisioner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provisioner)


class FakeGitHub:
    """Model only API metadata and the documented secret-set upsert behavior."""

    def __init__(self):
        p = provisioner
        self.metadata = {
            repo: {"private": repo != p.LOGIC, "permissions": {"admin": True}}
            for repo in (p.AD, p.BE, p.LOGIC)
        }
        self.collaborators = {
            repo: [{"login": "metainchelp-boop", "role_name": "admin"}]
            for repo in self.metadata
        }
        self.collaborators[p.BE].append({"login": "jjhud1000-bit", "role_name": "write"})
        self.environment = {"deployment_branch_policy": {
            "protected_branches": False, "custom_branch_policies": True}}
        self.policies = {"branch_policies": [{"name": p.BRANCH, "type": "branch"}]}
        self.values = {scope: {} for scope in p.NAMES}
        self.calls = []
        self.set_calls = []
        self.fail_set = None
        self.hide_after_set = False
        self.before_set = None
        self.before_list = None

    def __call__(self, *args, body=None):
        self.calls.append(args)
        if args[0] == "api":
            path = args[-1]
            for repo in self.metadata:
                if path == "repos/" + repo:
                    return json.dumps(self.metadata[repo]).encode()
                if path == f"repos/{repo}/collaborators?affiliation=all&per_page=100":
                    return json.dumps(self.collaborators[repo]).encode()
            if path.endswith("/deployment-branch-policies"):
                return json.dumps(self.policies).encode()
            if path.endswith("/environments/" + provisioner.RECOVERY):
                return json.dumps(self.environment).encode()
            raise AssertionError("Unexpected API path")
        if args[:2] not in (("secret", "list"), ("secret", "set")):
            raise AssertionError("Unexpected GitHub operation")
        repo = args[args.index("-R") + 1]
        environment = args[args.index("--env") + 1] if "--env" in args else None
        scope = (repo, environment)
        if args[1] == "list":
            if self.before_list:
                self.before_list(scope)
            existing = [] if self.hide_after_set and self.set_calls else self.values[scope]
            return json.dumps([{"name": name} for name in existing]).encode()
        name = args[2]
        self.set_calls.append((scope, name))
        if self.fail_set == len(self.set_calls):
            raise RuntimeError("GITHUB_OPERATION_FAILED")
        if self.before_set:
            self.before_set(scope, name)
        self.values[scope][name] = body
        return b""


class ProvisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Real key generation is strictly a test-only in-memory fixture.
        cls.recovery_fixture = rsa.generate_private_key(public_exponent=65537, key_size=4096)
        cls.host_public = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="naver-key-provision-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name).resolve()
        self.output = self.root / "public"
        self.hosts = self.root / "test-known-hosts"
        self.hosts.write_bytes(b"api.metainc.co.kr " + self.host_public + b"\n")
        self.github = FakeGitHub()
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        for patcher in (
            mock.patch.object(provisioner, "gh", side_effect=self.github),
            mock.patch.object(provisioner.subprocess, "run", side_effect=AssertionError("Network forbidden")),
            contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr),
        ):
            patcher.__enter__()
            self.addCleanup(patcher.__exit__, None, None, None)
        self.raw_values = [f"{number:064x}" for number in range(1, 6)]
        token_patch = mock.patch.object(provisioner.secrets, "token_hex", side_effect=self.raw_values)
        self.token = token_patch.start()
        self.addCleanup(token_patch.stop)
        rsa_patch = mock.patch.object(rsa, "generate_private_key", return_value=self.recovery_fixture)
        self.rsa = rsa_patch.start()
        self.addCleanup(rsa_patch.stop)

    def run_mock_provision(self):
        # This calls the Python function, never the CLI --provision entry point.
        provisioner.provision(self.output, self.hosts)

    def assert_no_issuance(self):
        self.token.assert_not_called()
        self.rsa.assert_not_called()
        self.assertEqual(self.github.set_calls, [])
        self.assertFalse(self.output.exists())

    def receipt(self):
        return json.loads((self.output / "receipt.json").read_text())

    def test_default_cli_is_preflight_only(self):
        with mock.patch.object(provisioner.sys, "argv", ["naver-key-provision.py"]):
            self.assertEqual(provisioner.main(), 0)
        self.assert_no_issuance()
        self.assertFalse(json.loads(self.stdout.getvalue())["keys_generated"])

    def test_each_existing_secret_blocks_all_issuance(self):
        for scope, requested in provisioner.NAMES.items():
            for name in requested:
                with self.subTest(scope=scope, name=name):
                    self.github.values[scope][name] = b"preexisting-test-value"
                    with self.assertRaisesRegex(RuntimeError, "SECRET_NAME_ALREADY_EXISTS"):
                        self.run_mock_provision()
                    self.assert_no_issuance()
                    self.assertEqual(self.github.values[scope].pop(name), b"preexisting-test-value")

    def test_repository_admin_or_privacy_failure_blocks_issuance(self):
        for repo in (provisioner.AD, provisioner.BE, provisioner.LOGIC):
            with self.subTest(repo=repo):
                self.github.metadata[repo]["permissions"]["admin"] = False
                with self.assertRaisesRegex(RuntimeError, "REPOSITORY_CUSTODY_NOT_CONFIRMED"):
                    self.run_mock_provision()
                self.assert_no_issuance()
                self.github.metadata[repo]["permissions"]["admin"] = True
        for repo in (provisioner.AD, provisioner.BE):
            self.github.metadata[repo]["private"] = False
            with self.assertRaisesRegex(RuntimeError, "REPOSITORY_CUSTODY_NOT_CONFIRMED"):
                self.run_mock_provision()
            self.assert_no_issuance()
            self.github.metadata[repo]["private"] = True

    def test_unexpected_collaborator_blocks_issuance(self):
        self.github.collaborators[provisioner.LOGIC].append({"login": "outsider", "role_name": "write"})
        with self.assertRaisesRegex(RuntimeError, "REPOSITORY_CUSTODIAN_CHANGED"):
            self.run_mock_provision()
        self.assert_no_issuance()

    def test_preflight_api_failure_blocks_issuance(self):
        with mock.patch.object(provisioner, "api", side_effect=RuntimeError("GITHUB_OPERATION_FAILED")):
            with self.assertRaisesRegex(RuntimeError, "GITHUB_OPERATION_FAILED"):
                self.run_mock_provision()
        self.assert_no_issuance()

    def test_invalid_pinned_hostname_blocks_preflight_and_issuance(self):
        self.hosts.write_bytes(b"unapproved.example " + self.host_public + b"\n")
        with self.assertRaisesRegex(RuntimeError, "INVALID_PINNED_HOST_KEY"):
            self.run_mock_provision()
        self.assert_no_issuance()
        self.assertEqual(self.github.calls, [])

    def test_environment_policy_failures_block_issuance(self):
        original = self.github.environment
        for environment in ({}, {"deployment_branch_policy": None}, {
                "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}}):
            self.github.environment = environment
            with self.assertRaisesRegex(RuntimeError, "RECOVERY_NOT_SEPARATED"):
                self.run_mock_provision()
            self.assert_no_issuance()
        self.github.environment = original
        for policies in ([], [{"name": "*", "type": "branch"}],
                         [{"name": provisioner.BRANCH, "type": "tag"}],
                         [{"name": provisioner.BRANCH, "type": "branch"}, {"name": "main", "type": "branch"}]):
            self.github.policies["branch_policies"] = policies
            with self.assertRaisesRegex(RuntimeError, "RECOVERY_BRANCH_NOT_EXCLUSIVE"):
                self.run_mock_provision()
            self.assert_no_issuance()

    def test_success_key_mapping_crypto_pairs_and_no_local_secret(self):
        self.run_mock_provision()
        self.assertEqual(len(self.github.set_calls), 14)
        self.rsa.assert_called_once_with(public_exponent=65537, key_size=4096)
        self.assertEqual(self.token.call_args_list, [mock.call(32)] * 5)
        ad = self.github.values[(provisioner.AD, None)]
        be = self.github.values[(provisioner.BE, None)]
        logic = self.github.values[(provisioner.LOGIC, None)]
        pairs = [(ad["SSO_AD_CENTER_CLIENT_KEY"], be["SSO_AD_CENTER_KEY_SHA256"]),
                 (logic["SSO_EXCHANGE_CLIENT_KEY"], be["SSO_LOGIC_ANALYSIS_KEY_SHA256"]),
                 (ad["SSO_NAVER_CONTROL_CLIENT_KEY"], be["SSO_NAVER_CONTROL_KEY_SHA256"]),
                 (ad["NAVER_ENGINE_ERP_KEY"], be["NAVER_ENGINE_KEY_SHA256"])]
        for raw, fingerprint in pairs:
            self.assertRegex(raw.decode(), r"^[0-9a-f]{64}$")
            self.assertEqual(fingerprint, hashlib.sha256(raw).hexdigest().encode())
            self.assertNotEqual(fingerprint, hashlib.sha256(bytes.fromhex(raw.decode())).hexdigest().encode())
        private = self.github.values[(provisioner.AD, provisioner.RECOVERY)][provisioner.PRIVATE]
        cert = x509.load_pem_x509_certificate(ad["NAVER_BACKUP_RECIPIENT_CERT_PEM"])
        key = serialization.load_pem_private_key(private, password=None)
        self.assertEqual(cert.public_key().public_numbers(), key.public_key().public_numbers())
        self.assertEqual(key.key_size, 4096)
        upload_key = serialization.load_ssh_private_key(ad["NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY"], password=None)
        upload_public = serialization.load_ssh_public_key(be["NAVER_BACKUP_UPLOAD_SSH_PUBLIC_KEY"])
        self.assertEqual(upload_key.public_key().public_bytes_raw(), upload_public.public_bytes_raw())
        self.assertEqual(set(p.name for p in self.output.iterdir()),
                         {"recipient.pem", "upload-key.pub", "known-hosts", "receipt.json"})
        public_bytes = b"".join(p.read_bytes() for p in self.output.iterdir())
        visible = public_bytes + self.stdout.getvalue().encode() + self.stderr.getvalue().encode()
        for hidden in [*(value.encode() for value in self.raw_values), private,
                       ad["NAVER_BACKUP_UPLOAD_SSH_PRIVATE_KEY"]]:
            self.assertNotIn(hidden, visible)
            self.assertNotIn(hidden.decode(), repr(self.github.calls))
        self.assertNotIn(b"PRIVATE KEY-----", public_bytes)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in self.output.iterdir()))
        receipt = self.receipt()
        self.assertTrue(receipt["complete"])
        self.assertEqual(receipt["metadata_verified_count"], 14)
        self.assertFalse(receipt["runtime_injection"])
        self.assertFalse(receipt["consumer_readback_verified"])

    def test_partial_write_failure_receipt_is_incomplete(self):
        self.github.fail_set = 3
        with self.assertRaisesRegex(RuntimeError, "GITHUB_OPERATION_FAILED"):
            self.run_mock_provision()
        receipt = self.receipt()
        self.assertFalse(receipt["complete"])
        self.assertEqual(receipt["metadata_verified_count"], 2)
        self.assertEqual(len(receipt["created"]), 2)
        self.assertEqual(self.stdout.getvalue(), "")

    def test_metadata_failure_receipt_does_not_claim_completion(self):
        self.github.hide_after_set = True
        with self.assertRaisesRegex(RuntimeError, "SECRET_METADATA_NOT_FOUND"):
            self.run_mock_provision()
        receipt = self.receipt()
        self.assertFalse(receipt["complete"])
        self.assertEqual(receipt["metadata_verified_count"], 0)
        self.assertEqual(len(receipt["created"]), 1)

    def test_collision_at_immediate_recheck_preserves_existing_value(self):
        scope = (provisioner.AD, provisioner.RECOVERY)
        calls = 0
        def inject_after_preflight(listed_scope):
            nonlocal calls
            if listed_scope == scope:
                calls += 1
                if calls == 2:
                    self.github.values[scope][provisioner.PRIVATE] = b"existing-test-private"
        self.github.before_list = inject_after_preflight
        with self.assertRaisesRegex(RuntimeError, "SECRET_NAME_COLLISION_DURING_PROVISION"):
            self.run_mock_provision()
        self.assertEqual(self.github.values[scope][provisioner.PRIVATE], b"existing-test-private")
        self.assertEqual(self.github.set_calls, [])
        self.assertFalse(self.receipt()["complete"])

    def test_existing_or_symlinked_output_is_never_overwritten(self):
        self.output.mkdir()
        existing = self.output / "preserve"
        existing.write_bytes(b"existing")
        with self.assertRaisesRegex(RuntimeError, "OUTPUT_MUST_BE_NEW"):
            self.run_mock_provision()
        self.assertEqual(existing.read_bytes(), b"existing")
        self.token.assert_not_called()
        other = self.root / "symlink"
        other.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "OUTPUT_MUST_BE_NEW"):
            provisioner.provision(other, self.hosts)
        self.assertEqual(self.github.calls, [])

    def test_duplicate_random_values_stop_before_crypto_or_upload(self):
        self.token.side_effect = ["a" * 64] * 5
        with self.assertRaisesRegex(RuntimeError, "KEY_COLLISION"):
            self.run_mock_provision()
        self.rsa.assert_not_called()
        self.assertEqual(self.github.set_calls, [])
        self.assertEqual(list(self.output.iterdir()), [])

    def test_error_details_are_not_echoed(self):
        with mock.patch.object(provisioner, "preflight", side_effect=ValueError("test-private-value /sensitive/path")), \
             mock.patch.object(provisioner.sys, "argv", ["naver-key-provision.py"]):
            self.assertEqual(provisioner.main(), 1)
        self.assertEqual(self.stdout.getvalue(), "")
        self.assertNotIn("test-private-value", self.stderr.getvalue())
        self.assertNotIn("/sensitive/path", self.stderr.getvalue())
        self.assertEqual(json.loads(self.stderr.getvalue())["reason"], "DETAILS_WITHHELD")


class TransportTests(unittest.TestCase):
    def test_secret_body_only_uses_stdin_and_failure_discards_diagnostics(self):
        body = b"test-only-private-value"
        result = subprocess.CompletedProcess([], 0, stdout=b"ok", stderr=b"")
        with mock.patch.object(provisioner.subprocess, "run", return_value=result) as run:
            self.assertEqual(provisioner.gh("secret", "set", "TEST_ONLY", "-R", "test/repo", body=body), b"ok")
        args, kwargs = run.call_args
        self.assertNotIn(body.decode(), repr(args))
        self.assertEqual(kwargs["input"], body)
        result.returncode, result.stderr = 1, body
        with mock.patch.object(provisioner.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(RuntimeError, "^GITHUB_OPERATION_FAILED$"):
                provisioner.gh("secret", "set", "TEST_ONLY", body=body)


if __name__ == "__main__":
    unittest.main()
