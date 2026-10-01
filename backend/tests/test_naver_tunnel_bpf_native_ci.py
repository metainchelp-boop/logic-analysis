"""로컬 합성 검사만 실행한다. systemd 서비스는 생성하지 않는다."""
import importlib.util
import os
from pathlib import Path
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def load():
    path = Path(__file__).resolve().parents[1] / "tools/naver_tunnel_bpf_native_ci.py"
    spec = importlib.util.spec_from_file_location("bpf_native_ci", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HarnessTests(unittest.TestCase):
    def test_cleanup_accepts_already_collected_unit_but_not_other_errors(self):
        m = load()
        unit = "naver-tunnel-bpf-ci-" + "a" * 12 + ".service"
        with patch.object(m, "run", return_value="not-found") as run, patch.object(m, "properties") as properties:
            m.stop_owned_unit(unit, "a" * 32)
            properties.assert_not_called()
            self.assertEqual(1, run.call_count)
        with patch.object(m, "run", side_effect=["loaded", "not-found"]), patch.object(m, "properties", side_effect=m.HarnessError("COMMAND_FAILED_SYSTEMCTL_5")):
            m.stop_owned_unit(unit, "a" * 32)
        with patch.object(m, "run", return_value="loaded"), patch.object(m, "properties", side_effect=m.HarnessError("OTHER_ERROR")):
            with self.assertRaises(m.HarnessError):
                m.stop_owned_unit(unit, "a" * 32)
    def test_only_exact_absent_unit_query_accepts_systemd_255_exit_five(self):
        m = load()
        command = ["/usr/bin/systemctl", "show", "naver-tunnel-bpf-ci-" + "a" * 12 + ".service", "--property=LoadState", "--value"]
        with patch.object(m.subprocess, "run", return_value=SimpleNamespace(returncode=5, stdout="not-found\n")):
            self.assertEqual("not-found", m.run(command))
            with self.assertRaises(m.HarnessError):
                m.run(["/usr/bin/systemctl", "start", command[2]])
        with patch.object(m.subprocess, "run", return_value=SimpleNamespace(returncode=5, stdout="unrecognized\n")):
            with self.assertRaises(m.HarnessError):
                m.run(command)
    def test_refuses_non_disposable_context_before_any_service_operation(self):
        m = load()
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(m.HarnessError):
            m.require_ci()

    def test_timeout_reproduces_strict_errno_guard_false_without_becoming_policy_pass(self):
        m = load()
        with patch.object(m.socket, "create_connection", side_effect=socket.timeout):
            kind = m.connect_kind("127.0.0.1", 12345)
        self.assertEqual("timeout", kind)
        self.assertFalse(m.strict_errno_guard(kind))
        self.assertTrue(m.strict_errno_guard("eperm"))
        self.assertTrue(m.strict_errno_guard("eacces"))
        with self.assertRaises(m.HarnessError):
            m.connect_kind("8.8.8.8", 22)

    def test_transient_unit_has_only_fixture_addresses_and_bounded_lifetime(self):
        m = load()
        command = m.unit_command("naver-tunnel-bpf-ci-" + "a" * 12 + ".service", "/tmp/fixture.sock", 10001, 10002)
        for value in ("IPAddressDeny=any", "IPAddressAllow=127.0.0.2", "RestrictAddressFamilies=AF_INET AF_UNIX",
                      "RuntimeMaxSec=15s", "TimeoutStopSec=2s"):
            self.assertIn("--property=" + value, command)
        self.assertNotIn("--scope", command)
        with self.assertRaises(m.HarnessError):
            m.unit_command("ssh.service", "/tmp/fixture.sock", 1, 2)

    def test_optional_bpf_reader_never_installs_or_changes_programs(self):
        m = load()
        with patch.object(m.shutil, "which", return_value=None):
            self.assertEqual({"status": "unknown", "attachments": []}, m.attachments("/system.slice/test.service"))
        with patch.object(m.shutil, "which", return_value="/usr/sbin/bpftool"), \
             patch.object(m, "run", return_value='[{"id":42,"attach_type":"egress","name":"ignored"}]') as run:
            result = m.attachments("/system.slice/test.service")
        self.assertEqual({"status": "observed", "attachments": [{"id": 42, "attach_type": "egress"}]}, result)
        self.assertEqual(["/usr/sbin/bpftool", "-j", "cgroup", "show", "/sys/fs/cgroup/system.slice/test.service"], run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
