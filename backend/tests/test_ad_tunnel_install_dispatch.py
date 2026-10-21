"""터널 설치 전달 경계만 합성 검사. 서버/실제 키 접근 없음."""
import ast
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from test_naver_erp_tunnel_service_install import package

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/debug-rank.yml"


def job():
    return WORKFLOW.read_text().split("  ad-tunnel-install:\n", 1)[1].split("\n  diagnose:", 1)[0]


def script(label):
    return textwrap.dedent(job().split("<<'" + label + "'\n", 1)[1].split(label, 1)[0])


class InstallDispatchTests(unittest.TestCase):
    def test_exact_branch_dispatch_and_mode_are_required(self):
        guard = job().splitlines()[0]
        for condition in ("github.event_name == 'workflow_dispatch'",
                          "github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'",
                          "inputs.ad_prepare == 'tunnel-install'",
                          "inputs.ad_prepare == 'tunnel-activate'"):
            self.assertIn(condition, guard)
        self.assertIn("persist-credentials: false", job())
        self.assertIn("contents: read", job())
        self.assertNotIn("upload-artifact", job())

    def package_locally(self, inputs=None, **changes):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "github-env"
            values = {"ad_prepare": "tunnel-install", "ad_expected_baseline": json.dumps(package()),
                      "collector": "off", "rank_link": "off"}
            if inputs is not None:
                values.update(inputs)
            env = dict(os.environ, AD_RUN_EVENT="workflow_dispatch",
                AD_RUN_REF="refs/heads/codex/ad-deploy-prep-20261001", AD_RUN_INPUTS=json.dumps(values),
                GITHUB_ENV=str(output), PYTHONDONTWRITEBYTECODE="1")
            env.update(changes)
            result = subprocess.run(["python3", "-c", script("INSTALL_PACKAGE")], env=env,
                cwd=WORKFLOW.parents[2], capture_output=True, text=True, timeout=10)
            body = output.read_text() if output.exists() else ""
            return result, body

    def test_valid_public_package_contains_only_two_trusted_sources_and_four_public_fields(self):
        result, body = self.package_locally()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        name, encoded = body.strip().split("=", 1)
        self.assertEqual(name, "NAVER_TUNNEL_INSTALL_BUNDLE_B64")
        bundle = json.loads(base64.b64decode(encoded, validate=True))
        self.assertEqual(set(bundle), {"operation", "package", "installer_source", "probe_source"})
        self.assertEqual(bundle["operation"], "tunnel-install")
        self.assertEqual(bundle["package"], package())
        for field, filename in (("installer_source", "naver_erp_tunnel_service_install.py"),
                                ("probe_source", "naver_erp_tunnel_bpf_preflight.py")):
            self.assertEqual(base64.b64decode(bundle[field], validate=True),
                (WORKFLOW.parents[2] / "backend/tools" / filename).read_bytes())

    def test_activation_uses_same_public_package_with_explicit_operation(self):
        result, body = self.package_locally({"ad_prepare": "tunnel-activate"})
        self.assertEqual(result.returncode, 0, result.stderr)
        bundle = json.loads(base64.b64decode(body.strip().split("=", 1)[1], validate=True))
        self.assertEqual(bundle["operation"], "tunnel-activate")
        self.assertEqual(bundle["package"], package())

    def test_input_rejections_have_no_payload_or_raw_error(self):
        examples = [({"collector": "on"}, {}), ({"ad_prepare": "inspect"}, {}),
            ({}, {"AD_RUN_REF": "refs/heads/main"}), ({}, {"AD_RUN_EVENT": "push"}),
            ({"ad_expected_baseline": "private-marker"}, {}),
            ({"ad_expected_baseline": json.dumps(dict(package(), private_key="private-marker"))}, {}),
            ({"ad_expected_baseline": json.dumps(dict(package(), work_switches_off=False))}, {}),
            ({"ad_expected_baseline": json.dumps(dict(package(), expected_public_fingerprint="private-marker"))}, {}),
            ({"ad_expected_baseline": json.dumps(dict(package(), known_host_key="private-marker"))}, {}),
            ({"ad_expected_baseline": '{"duplicate":1,"duplicate":2}'}, {})]
        for inputs, changes in examples:
            with self.subTest(inputs=inputs, changes=changes):
                result, body = self.package_locally(inputs, **changes)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(body, "")
                self.assertEqual(result.stderr, "")
                self.assertEqual(result.stdout, "NAVER_TUNNEL_INSTALL_INPUT_REJECTED\n")

    def remote(self, source, *, malformed=False, operation="tunnel-install"):
        bundle = {"operation": operation, "package": package(), "installer_source": base64.b64encode(source.encode()).decode(),
                  "probe_source": base64.b64encode(b"synthetic-probe").decode()}
        encoded = "invalid-base64" if malformed else base64.b64encode(json.dumps(bundle).encode()).decode()
        output, errors = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {"NAVER_TUNNEL_INSTALL_BUNDLE_B64": encoded,
                "SHOULD_NOT_INHERIT": "private-marker"}, clear=True), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors), \
                self.assertRaises(SystemExit) as code:
            exec(compile(script("INSTALL_REMOTE"), "synthetic-loader", "exec"), {"__name__": "__main__"})
        self.assertEqual(errors.getvalue(), "")
        self.assertNotIn("private-marker", output.getvalue())
        result = json.loads(output.getvalue().split(" ", 1)[1])
        return code.exception.code, result

    def test_remote_clears_ambient_environment_and_executes_only_in_memory(self):
        source = '''
import os
def validate_package(package):
    assert len(package) == 4
def install(package, *, probe_source):
    assert set(os.environ) == {"PATH", "LANG"}
    assert probe_source == b"synthetic-probe"
    print("private-marker")
    return {"ok": True, "containers_unchanged": True}
'''
        code, result = self.remote(source)
        self.assertEqual(code, 0)
        self.assertEqual(result, {"ok": True, "containers_unchanged": True})

    def test_activation_calls_only_bounded_activation_function(self):
        source = '''
def validate_package(package):
    assert len(package) == 4
def install(*args, **kwargs):
    raise AssertionError("wrong_operation")
def activate_installed(package, *, probe_source):
    assert probe_source == b"synthetic-probe"
    return {"ok": True, "activated": True}
'''
        code, result = self.remote(source, operation="tunnel-activate")
        self.assertEqual((code, result), (0, {"ok": True, "activated": True}))
        code, result = self.remote(source, operation="__dict__")
        self.assertEqual(code, 1)
        self.assertEqual(result["stage"], "decode")

    def test_remote_errors_and_non_success_receipts_fail_without_raw_detail(self):
        code, result = self.remote("raise ValueError('private-marker')")
        self.assertEqual(code, 1)
        self.assertEqual(result, {"ok": False, "stage": "install", "error_kind": "ValueError", "error_code": None})
        code, result = self.remote("", malformed=True)
        self.assertEqual(code, 1)
        self.assertEqual(result["stage"], "decode")
        code, result = self.remote("def validate_package(p): pass\ndef install(p, **kw): return {'ok': False}")
        self.assertEqual((code, result), (1, {"ok": False}))

    def test_only_controlled_uppercase_installer_error_code_is_reported(self):
        for text, expected in (("BASELINE_CHANGED", "BASELINE_CHANGED"),
                               ("private-marker", None), ("A" * 81, None)):
            source = "class InstallError(RuntimeError): pass\ndef validate_package(p): raise InstallError(" + repr(text) + ")"
            code, result = self.remote(source)
            self.assertEqual(code, 1)
            self.assertEqual(result["error_code"], expected)

    def test_dispatch_secret_allowlist_and_python_syntax(self):
        import re
        self.assertEqual(re.findall(r"secrets\.([A-Z_]+)", job()), ["VPS_HOST", "VPS_USER", "VPS_SSH_KEY"])
        self.assertEqual(job().count("envs: NAVER_TUNNEL_INSTALL_BUNDLE_B64"), 1)
        for label in ("INSTALL_PACKAGE", "INSTALL_REMOTE"):
            ast.parse(script(label), feature_version=(3, 8))


if __name__ == "__main__":
    unittest.main()
