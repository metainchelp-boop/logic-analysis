"""전용 키 생성 모드의 합성 파일/프로세스 경계 검사. 실제 서버 접근 없음."""
import base64
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_ad_tunnel_preflight import module, source, WORKFLOW


class TunnelKeygenTests(unittest.TestCase):
    def test_baseline_mismatch_refuses_before_any_write(self):
        ns = module()
        with patch.object(ns["os"], "geteuid", return_value=0), \
                patch.dict(ns, baseline=lambda _: "b" * 64), \
                patch.object(ns["os"], "mkdir") as mkdir:
            with self.assertRaisesRegex(RuntimeError, "baseline_changed"):
                ns["tunnel_keygen"]({}, "a" * 64)
            mkdir.assert_not_called()

    def synthetic(self, *, changed=False, exists=False, kind=None, failure=False):
        ns = module()
        original_fstat = os.fstat
        pub = "ssh-ed25519 " + base64.b64encode(
            b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"x" * 32).decode() + " naver-erp-tunnel"
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "naver-erp-tunnel"
            if exists:
                folder.symlink_to(Path(temporary) / "missing")
            def path(value):
                return folder if str(value) == "/etc/metainc/naver-erp-tunnel" else Path(value)
            def fake_stat(value):
                info = value
                return SimpleNamespace(st_mode=info.st_mode, st_uid=0, st_gid=0,
                    st_nlink=info.st_nlink, st_size=info.st_size, st_dev=info.st_dev, st_ino=info.st_ino)
            real_lstat = Path.lstat
            def lstat(value):
                return fake_stat(real_lstat(value))
            calls = []
            def keygen(args, **kwargs):
                calls.append((args, kwargs))
                private = Path(args[-1])
                private.write_text("synthetic-private-never-output")
                private.chmod(0o600)
                public = private.with_suffix(".pub")
                public.write_text(pub + "\n")
                public.chmod(0o600)
                if kind == "mode":
                    private.chmod(0o644)
                elif kind == "hardlink":
                    os.link(private, folder / "alias")
                elif kind == "symlink":
                    public.unlink()
                    public.symlink_to(private)
                elif kind == "public":
                    public.write_text("synthetic-private-never-output")
                if failure:
                    raise subprocess.TimeoutExpired("synthetic-private-never-output", 20)
                return subprocess.CompletedProcess(args, 0)
            ns.update(created=[])
            output = io.StringIO()
            with patch.object(ns["pathlib"], "Path", side_effect=path), \
                    patch.object(Path, "lstat", lstat), \
                    patch.object(ns["os"], "geteuid", return_value=0), \
                    patch.object(ns["os"], "fstat", side_effect=lambda fd: fake_stat(original_fstat(fd))), \
                    patch.dict(ns, metadata=lambda _: {"exists": True, "symlink": False,
                        "directory": True, "uid": 0, "gid": 0, "mode": "0o755"},
                        baseline=lambda r: "b" * 64 if r.get("after") and changed else "a" * 64,
                        inspect=lambda: {"after": True}), \
                    patch.object(ns["subprocess"], "run", side_effect=keygen), \
                    contextlib.redirect_stdout(output):
                if changed or exists or kind or failure:
                    with self.assertRaises((RuntimeError, OSError, subprocess.TimeoutExpired)):
                        ns["tunnel_keygen"]({}, "a" * 64)
                    result = None
                else:
                    result = ns["tunnel_keygen"]({}, "a" * 64)
            self.assertNotIn("synthetic-private-never-output", output.getvalue())
            if exists:
                self.assertEqual(calls, [])
                self.assertTrue(folder.is_symlink())
            else:
                self.assertTrue(folder.exists())  # 실패 잔재도 자동 삭제/교체하지 않는다.
                self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
                self.assertEqual(calls[0][1]["stdout"], subprocess.DEVNULL)
                self.assertEqual(calls[0][1]["stderr"], subprocess.DEVNULL)
                self.assertEqual(calls[0][1]["stdin"], subprocess.DEVNULL)
            return result, pub

    def test_success_returns_only_validated_public_key_and_safe_metadata(self):
        result, pub = self.synthetic()
        self.assertEqual(result["public_key"], pub)
        self.assertTrue(result["containers_unchanged"])
        self.assertFalse(result["private_key_exported"])
        self.assertFalse(result["service_installed"])
        self.assertEqual(result["directory_mode"], "0o700")
        for item in result["files"].values():
            self.assertEqual((item["uid"], item["gid"], item["mode"], item["links"]), (0, 0, "0o600", 1))
            self.assertRegex(item["inode_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("synthetic-private-never-output", json.dumps(result))

    def test_main_failure_hides_private_error_and_public_key(self):
        ns = module()
        def failure(*_):
            raise RuntimeError("synthetic-private-never-output")
        ns.update(created=[], inspect=lambda: {}, baseline=lambda _: "a" * 64,
            tunnel_keygen=failure, os=SimpleNamespace(environ={"AD_PREPARE_MODE": "tunnel-keygen",
                "AD_EXPECTED_BASELINE": "a" * 64}))
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            exec(compile(ast.Module(body=[ast.parse(source()).body[-1]], type_ignores=[]),
                "synthetic-main", "exec"), ns)
        self.assertEqual(output.getvalue(), "AD_DEPLOY_PREFLIGHT_FAILED=RuntimeError\nAD_DEPLOY_CREATED_PATHS=[]\n")

    def test_existing_broken_link_refuses_before_keygen(self):
        self.synthetic(exists=True)

    def test_permissions_links_malformed_public_timeout_and_changed_container_refuse(self):
        for kind in ("mode", "hardlink", "symlink", "public"):
            with self.subTest(kind=kind):
                self.synthetic(kind=kind)
        self.synthetic(changed=True)
        self.synthetic(failure=True)

    def test_workflow_keygen_guards_fail_before_ssh(self):
        document = WORKFLOW.read_text()
        import textwrap
        guard = textwrap.dedent(document.split("        run: |\n", 1)[1].split("      - name:", 1)[0])
        base = dict(os.environ, AD_PREPARE_MODE="tunnel-keygen", AD_EXPECTED_BASELINE="a" * 64,
                    AD_RUN_EVENT="workflow_dispatch", AD_RUN_REF="refs/heads/codex/ad-deploy-prep-20261001",
                    AD_RUN_INPUTS=json.dumps({"collector": "off", "rank_link": "off"}))
        self.assertEqual(subprocess.run(["bash", "-c", guard], env=base, capture_output=True).returncode, 0)
        mutations = ({"AD_RUN_EVENT": "push"}, {"AD_RUN_REF": "refs/heads/main"},
                     {"AD_EXPECTED_BASELINE": "$(echo private)"},
                     {"AD_RUN_INPUTS": json.dumps({"collector": "on"})},
                     {"AD_RUN_INPUTS": json.dumps({"future_diagnostic": "on"})})
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.assertNotEqual(subprocess.run(["bash", "-c", guard], env=dict(base, **mutation),
                    capture_output=True).returncode, 0)
        job_if = document.split("  ad-deploy-prepare:\n", 1)[1].splitlines()[0]
        self.assertIn("github.event_name == 'workflow_dispatch'", job_if)
        self.assertIn("github.ref == 'refs/heads/codex/ad-deploy-prep-20261001'", job_if)
        self.assertIn("inputs.ad_prepare == 'tunnel-keygen'", job_if)
        self.assertIn("if: ${{ !inputs.ad_prepare || inputs.ad_prepare == 'off' }}", document)


if __name__ == "__main__":
    unittest.main()
