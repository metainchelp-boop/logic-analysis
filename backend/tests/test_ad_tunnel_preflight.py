"""관리 SSH의 inspect 분기만 합성 실행한다. 서버/키/환경파일 접근 없음."""
import ast
import contextlib
import io
import json
from pathlib import Path
import subprocess
import textwrap
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/debug-rank.yml"


def source():
    document = WORKFLOW.read_text()
    return textwrap.dedent(document.split("python3 - <<'PY'\n", 1)[1].split("\n            PY", 1)[0])


def module():
    tree = ast.parse(source())
    # main/prepare는 실행하지 않는다. 실제 파일의 함수 구현만 호출한다.
    safe = ast.Module(body=[node for node in tree.body if isinstance(
        node, (ast.Import, ast.ImportFrom, ast.FunctionDef))], type_ignores=[])
    namespace = {}
    exec(compile(safe, "synthetic-preflight", "exec"), namespace)
    return namespace


class TunnelPreflightTests(unittest.TestCase):
    def execute_main(self, *, mode="inspect", changed=False):
        ns = module()
        report = {"mode": "inspect", "containers": [{key: "synthetic-private-marker" for key in (
            "name", "id", "image_id", "running", "started_at", "restart_count", "project", "service")}]}
        after = json.loads(json.dumps(report))
        if changed:
            after["containers"][0]["id"] = "changed"
        inspect = Mock(side_effect=[report, after])
        tunnel = Mock(return_value={"synthetic": True})
        prepare = Mock(return_value={"mode": "prepare", "containers_unchanged": True})
        ns.update(inspect=inspect, tunnel_preflight=tunnel, tunnel_service_diagnostics=lambda: {}, prepare=prepare, created=[],
                  os=SimpleNamespace(environ={"AD_PREPARE_MODE": mode, "AD_EXPECTED_BASELINE": "a" * 64}))
        last = ast.parse(source()).body[-1]
        self.assertIsInstance(last, ast.Try)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            if changed:
                with self.assertRaises(SystemExit) as failure:
                    exec(compile(ast.Module(body=[last], type_ignores=[]), "synthetic-main", "exec"), ns)
                self.assertEqual(failure.exception.code, 1)
            else:
                exec(compile(ast.Module(body=[last], type_ignores=[]), "synthetic-main", "exec"), ns)
        return output.getvalue(), inspect, tunnel, prepare

    def test_inspect_checks_baseline_again_and_prepare_never_runs_tunnel_probe(self):
        output, inspect, tunnel, prepare = self.execute_main()
        self.assertEqual(inspect.call_count, 2)
        tunnel.assert_called_once_with()
        prepare.assert_not_called()
        report = json.loads(output.removeprefix("AD_DEPLOY_PREFLIGHT="))
        self.assertTrue(report["containers_unchanged"])
        self.assertEqual(report["tunnel_preflight"], {"synthetic": True})
        output, inspect, tunnel, prepare = self.execute_main(mode="prepare")
        self.assertEqual(inspect.call_count, 1)
        tunnel.assert_not_called()
        prepare.assert_called_once()
        self.assertNotIn("tunnel_preflight", output)

    def test_changed_container_refuses_without_printing_report_or_private_error(self):
        output, *_ = self.execute_main(changed=True)
        self.assertIn("AD_DEPLOY_PREFLIGHT_FAILED=RuntimeError", output)
        self.assertNotIn("AD_DEPLOY_PREFLIGHT=", output)
        self.assertNotIn("synthetic-private-marker", output)

    def test_probe_failures_are_unknown_and_never_return_raw_errors(self):
        ns = module()
        failures = (OSError("synthetic-private-marker"), subprocess.TimeoutExpired("private", 5),
                    subprocess.CompletedProcess([], 1, "synthetic-private-marker", "synthetic-private-marker"),
                    subprocess.CompletedProcess([], 0, "x" * 16385, ""))
        for failure in failures:
            with self.subTest(kind=type(failure).__name__):
                options = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                with patch.object(ns["subprocess"], "run", **options) as invoke:
                    self.assertIsNone(ns["probe"](["ssh", "-V"]))
                self.assertEqual(invoke.call_args.kwargs, {"capture_output": True, "text": True, "timeout": 5})

    def test_unsupported_bpf_and_malformed_route_are_not_reported_as_ready(self):
        ns = module()
        def probe(args):
            if args[0] == "systemd":
                return subprocess.CompletedProcess([], 0, "systemd 249\n-PAM -BPF_FRAMEWORK", "")
            if args[0] == "ip":
                return subprocess.CompletedProcess([], 0, "synthetic-private-marker", "")
            return None
        with patch.dict(ns, probe=probe, metadata=lambda _: {"exists": False}), \
                patch.object(ns["pwd"], "getpwuid", side_effect=KeyError), \
                patch.object(ns["grp"], "getgrgid", side_effect=KeyError), \
                patch.object(ns["pwd"], "getpwall", return_value=[]), \
                patch.object(ns["pathlib"].Path, "is_file", return_value=False), \
                patch.object(ns["pathlib"].Path, "is_dir", return_value=False):
            report = ns["tunnel_preflight"]()
        self.assertEqual(report["route"], {"available": False, "source_matches_expected": None})
        self.assertFalse(report["bpf"]["systemd_framework_compiled"])
        self.assertFalse(report["bpf"]["runtime_enforcement_verified"])
        self.assertEqual(report["bpf"]["assessment"], "read_only_indicators_only")
        self.assertNotIn("synthetic-private-marker", json.dumps(report))

    def test_route_unknown_mismatch_and_identity_collisions_do_not_reveal_names(self):
        ns = module()
        examples = (
            ([{"prefsrc": "192.0.2.2"}], True, False),
            ([{"src": "1.234.20.80"}], True, True),
            ([], False, None), ([{}, {}], False, None),
            ([{"prefsrc": "synthetic-private-marker"}], False, None),
            ({"prefsrc": "1.234.20.80"}, False, None),
            ([{"prefsrc": 123}], False, None),
        )
        account = SimpleNamespace(pw_name="synthetic-private-marker", pw_gid=10001)
        group = SimpleNamespace(gr_name="synthetic-private-marker", gr_mem=["synthetic-private-marker", "private-two"])
        with patch.object(ns["pwd"], "getpwuid", return_value=account), \
                patch.object(ns["grp"], "getgrgid", return_value=group), \
                patch.object(ns["pwd"], "getpwall", return_value=[account, account, SimpleNamespace(pw_gid=42)]), \
                patch.object(ns["pathlib"].Path, "is_file", return_value=False), \
                patch.object(ns["pathlib"].Path, "is_dir", return_value=False):
            for rows, available, matches in examples:
                def probe(args):
                    if args[0] == "ip":
                        return subprocess.CompletedProcess(args, 0, json.dumps(rows), "")
                    return None
                with self.subTest(rows=rows), patch.dict(ns, probe=probe, metadata=lambda _: {"exists": False}):
                    report = ns["tunnel_preflight"]()
                self.assertEqual(report["route"], {"available": available, "source_matches_expected": matches})
                self.assertEqual(report["identity"], {"uid_10001_exists": True, "uid_10001_primary_gid": 10001,
                    "gid_10001_exists": True, "gid_10001_explicit_member_count": 2, "gid_10001_primary_member_count": 2})
                self.assertIsNone(report["bpf"]["systemd_framework_compiled"])
                self.assertFalse(report["bpf"]["runtime_enforcement_verified"])
                self.assertNotIn("synthetic-private-marker", json.dumps(report))

    def test_path_metadata_uses_lstat_and_never_reads_contents(self):
        ns = module()
        with tempfile.TemporaryDirectory() as folder:
            plain = Path(folder) / "file"
            plain.write_text("synthetic-private-marker")
            plain.chmod(0o600)
            link = Path(folder) / "link"
            link.symlink_to(plain)
            broken = Path(folder) / "broken"
            broken.symlink_to(Path(folder) / "absent")
            with patch.object(Path, "read_text", side_effect=AssertionError("contents forbidden")), \
                    patch.object(Path, "read_bytes", side_effect=AssertionError("contents forbidden")):
                self.assertEqual(ns["metadata"](plain)["mode"], "0o600")
                self.assertTrue(ns["metadata"](link)["symlink"])
                self.assertTrue(ns["metadata"](broken)["symlink"])
                self.assertEqual(ns["metadata"](Path(folder) / "absent"), {"exists": False})

    def test_new_helpers_have_only_three_read_commands_and_no_file_writes(self):
        tree = ast.parse(source())
        funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        additions = ast.Module(body=[funcs[name] for name in ("tunnel_preflight", "probe")], type_ignores=[])
        commands = [ast.literal_eval(node.args[0]) for node in ast.walk(additions)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "probe"]
        self.assertEqual(commands, [["ssh", "-V"], ["systemd", "--version"],
                                   ["ip", "-json", "route", "get", "1.234.23.117"]])
        forbidden = {"open", "read_text", "read_bytes", "write_text", "write_bytes", "mkdir", "unlink", "chmod",
                     "chown", "remove", "replace", "Popen", "system", "exec", "eval"}
        for node in ast.walk(additions):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                self.assertNotIn(name, forbidden)

    def test_reports_only_source_match_metadata_counts_and_support_indicators(self):
        ns = module()
        outputs = {
            ("ssh", "-V"): subprocess.CompletedProcess([], 0, "", "OpenSSH_8.9p1 Ubuntu-3, synthetic-private-marker"),
            ("systemd", "--version"): subprocess.CompletedProcess([], 0, "systemd 249 (249.11)\n+PAM +BPF_FRAMEWORK", ""),
            ("ip", "-json", "route", "get", "1.234.23.117"): subprocess.CompletedProcess([], 0,
                json.dumps([{"prefsrc": "1.234.20.80", "gateway": "synthetic-private-marker", "dev": "synthetic-private-marker"}]), ""),
        }
        with patch.dict(ns, probe=lambda args: outputs[tuple(args)], metadata=lambda path: {"exists": False}), \
                patch.object(ns["pwd"], "getpwuid", side_effect=KeyError), \
                patch.object(ns["grp"], "getgrgid", side_effect=KeyError), \
                patch.object(ns["pwd"], "getpwall", return_value=[]), \
                patch.object(ns["pathlib"].Path, "is_file", return_value=True), \
                patch.object(ns["pathlib"].Path, "is_dir", return_value=True):
            report = ns["tunnel_preflight"]()
        self.assertEqual(report["ssh_version"], "OpenSSH_8.9p1")
        self.assertEqual(report["systemd_version"], "systemd 249")
        self.assertEqual(report["route"], {"available": True, "source_matches_expected": True})
        self.assertEqual(set(report["paths"]), {"config", "service", "runtime"})
        self.assertTrue(all(value == {"exists": False} for value in report["paths"].values()))
        self.assertFalse(report["identity"]["uid_10001_exists"])
        self.assertFalse(report["identity"]["gid_10001_exists"])
        self.assertEqual(report["identity"]["gid_10001_explicit_member_count"], 0)
        self.assertEqual(report["identity"]["gid_10001_primary_member_count"], 0)
        self.assertTrue(report["bpf"]["systemd_framework_compiled"])
        self.assertTrue(report["bpf"]["cgroup_v2"])
        self.assertFalse(report["bpf"]["runtime_enforcement_verified"])
        encoded = json.dumps(report)
        for private in ("synthetic-private-marker", "1.234.20.80", "1.234.23.117"):
            self.assertNotIn(private, encoded)


if __name__ == "__main__":
    unittest.main()
