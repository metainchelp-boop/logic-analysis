"""Offline installer contracts: no SSH, systemd, Docker or host mutation."""
import base64
import contextlib
import errno
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools/naver_erp_tunnel_service_install.py"


def module():
    spec = importlib.util.spec_from_file_location("naver_erp_tunnel_service_install", MODULE_PATH)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def wire(*parts):
    return b"".join(len(part).to_bytes(4, "big") + part for part in parts)


def package():
    point = bytes.fromhex(
        "04" "6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296"
        "4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5")
    public = wire(b"ecdsa-sha2-nistp256", b"nistp256", point)
    return {
        "expected_docker_baseline": "a" * 64,
        "expected_public_fingerprint": "SHA256:" + base64.b64encode(bytes(32)).decode().rstrip("="),
        "known_host_key": "ecdsa-sha2-nistp256 " + base64.b64encode(public).decode(),
        "work_switches_off": True,
    }


class FakeHost:
    def __init__(self, baselines=None, fail_at=None, publish_unit=True):
        self.events = []
        self.baselines = list(baselines or ["a" * 64] * 4)
        self.fail_at = fail_at
        self.publish_unit = publish_unit

    def record(self, event):
        self.events.append(event)
        if self.fail_at == event:
            raise RuntimeError("synthetic-private-exception-marker")

    def preflight(self, value):
        self.record("preflight")

    def baseline(self):
        self.events.append("baseline")
        return self.baselines.pop(0)

    def create_group(self):
        self.record("create_group")

    def publish(self, entries, created):
        for path in entries:
            if self.publish_unit or not str(path).endswith(".service"):
                created.append(str(path))
        self.record("publish")

    def verify_config(self):
        self.record("verify_config")

    def start(self):
        self.record("start")

    def verify_running(self):
        self.record("verify_running")
        return {"uid": 0, "gid": 10001, "socket_mode": "0660"}

    def verify_ingress(self):
        self.record("verify_ingress")
        return {"unauthenticated_routes_rejected": 4, "other_routes_rejected": 1,
                "authenticated_data_read_verified": False}

    def stop(self):
        self.record("stop")


class TunnelServiceInstallTests(unittest.TestCase):
    def test_baseline_mismatch_refuses_before_any_host_mutation(self):
        installer = module()
        host = FakeHost(baselines=["b" * 64])
        with self.assertRaises(installer.InstallError):
            installer.install(package(), host=host)
        self.assertNotIn("create_group", host.events)

    def test_second_baseline_check_refuses_before_any_host_mutation(self):
        installer = module()
        host = FakeHost(baselines=["a" * 64, "b" * 64])
        with self.assertRaises(installer.InstallError):
            installer.install(package(), host=host)
        self.assertNotIn("create_group", host.events)
        self.assertNotIn("stop", host.events)

    def test_package_rejects_unknown_missing_and_wrong_type_fields(self):
        installer = module()
        invalid = [dict(package(), extra="forbidden"), dict(package(), work_switches_off=False),
                   dict(package(), work_switches_off=1), dict(package(), expected_docker_baseline="g" * 64),
                   dict(package(), expected_public_fingerprint="SHA256:" + "A" * 42)]
        for key in package():
            missing = package()
            del missing[key]
            invalid.append(missing)
        for value in invalid:
            with self.subTest(keys=sorted(value)):
                with self.assertRaises(installer.InstallError):
                    installer.validate_package(value)
        installer.validate_package(package())

    def test_known_host_key_rejects_noncanonical_or_malformed_ssh_wire(self):
        installer = module()
        valid = package()["known_host_key"]
        malformed = [valid + " comment", valid + "\n", valid.replace(" ", "  ", 1),
                     "ssh-ed25519 " + valid.split()[1]]
        for raw in (b"not-wire", wire(b"ecdsa-sha2-nistp384", b"nistp256", b"\x04" + bytes(64)),
                    wire(b"ecdsa-sha2-nistp256", b"nistp384", b"\x04" + bytes(64)),
                    wire(b"ecdsa-sha2-nistp256", b"nistp256", b"\x02" + bytes(64)),
                    wire(b"ecdsa-sha2-nistp256", b"nistp256", b"\x04" + bytes(63)),
                    base64.b64decode(valid.split()[1]) + b"trailing"):
            malformed.append("ecdsa-sha2-nistp256 " + base64.b64encode(raw).decode())
        for value in malformed:
            with self.subTest(length=len(value)):
                with self.assertRaises(installer.InstallError):
                    installer.validate_package(dict(package(), known_host_key=value))

    def test_reviewed_templates_remain_byte_exact(self):
        installer = module()
        for name, expected in (
            ("SSH_TEMPLATE", "1c37f158c26a988973707c36b2f4ccade561c6e1fa93334a12ece8abaf9df0aa"),
            ("SERVICE_TEMPLATE", "93c18df46c539dc2cbc1a103536aaa7c6e8444c9215897ae3b8c5fb8a59bd24a"),
        ):
            value = getattr(installer, name)
            with self.subTest(template=name):
                self.assertEqual(hashlib.sha256(value.encode()).hexdigest(), expected)

    def test_manifest_is_exactly_four_fixed_files_with_one_prestart_probe(self):
        installer = module()
        entries = installer.manifest(package())
        folder = "/etc/metainc/naver-erp-tunnel/"
        unit_path = "/etc/systemd/system/metainc-naver-erp-tunnel.service"
        self.assertEqual(set(entries), {folder + "ssh_config", folder + "known_hosts",
                                        folder + "bpf_preflight.py", unit_path})
        for name, (body, mode) in entries.items():
            self.assertIsInstance(body, bytes)
            self.assertEqual(mode, 0o644 if name == unit_path else 0o600)
            self.assertNotIn(b"@BE_SSH_IPV4@", body)
        self.assertEqual(entries[folder + "known_hosts"][0],
                         ("1.234.23.117 " + package()["known_host_key"] + "\n").encode())
        service = entries[unit_path][0].decode()
        original = installer.SERVICE_TEMPLATE.replace("@BE_SSH_IPV4@", "1.234.23.117")
        insertion = "ExecStartPre=/usr/bin/python3 " + folder + "bpf_preflight.py\n"
        self.assertEqual(service, original.replace("ExecStart=", insertion + "ExecStart=", 1))
        self.assertEqual(entries[folder + "bpf_preflight.py"][0],
                         MODULE_PATH.with_name("naver_erp_tunnel_bpf_preflight.py").read_bytes())

    def test_success_keeps_work_switches_off_and_never_enables_unit(self):
        installer = module()
        host = FakeHost()
        receipt = installer.install(package(), host=host)
        self.assertTrue(receipt["ok"])
        self.assertFalse(receipt["enabled"])
        self.assertTrue(receipt["work_switches_off"])
        self.assertTrue(receipt["bpf_runtime_enforcement_verified"])
        self.assertTrue(receipt["auth_boundary_roundtrip_verified"])
        self.assertEqual(receipt["unauthenticated_routes_rejected"], 4)
        self.assertEqual(receipt["other_routes_rejected"], 1)
        self.assertFalse(receipt["authenticated_data_read_verified"])
        self.assertNotIn("stop", host.events)
        self.assertLess(host.events.index("verify_config"), host.events.index("start"))
        self.assertLess(host.events.index("start"), host.events.index("verify_running"))
        self.assertLess(host.events.index("verify_running"), host.events.index("verify_ingress"))
        self.assertEqual(host.events[-1], "baseline")

    def test_memory_delivery_requires_exact_probe_without_local_source_read(self):
        installer = module()
        probe = MODULE_PATH.with_name("naver_erp_tunnel_bpf_preflight.py").read_bytes()
        with patch.object(Path, "read_bytes", side_effect=AssertionError("no local read")):
            self.assertTrue(installer.install(package(), host=FakeHost(), probe_source=probe)["ok"])
            for changed in (probe + b"\n", probe.decode(), b"invalid"):
                with self.assertRaisesRegex(installer.InstallError, "PROBE_CHANGED"):
                    installer.install(package(), host=FakeHost(), probe_source=changed)

    def test_post_publication_failure_stops_only_new_unit_and_preserves_evidence(self):
        installer = module()
        for failure in ("publish", "verify_config", "start", "verify_running", "verify_ingress"):
            host = FakeHost(fail_at=failure)
            with self.subTest(failure=failure):
                receipt = installer.install(package(), host=host)
                self.assertFalse(receipt["ok"])
                self.assertIn("stop", host.events)
                self.assertTrue(receipt["group_may_remain"])
                self.assertTrue(receipt["manual_review_required"])
                self.assertTrue(receipt["created"])
                self.assertNotIn("synthetic-private-exception-marker", json.dumps(receipt))

    def test_failure_before_unit_publication_does_not_stop_existing_service(self):
        installer = module()
        for host in (FakeHost(fail_at="create_group"), FakeHost(fail_at="publish", publish_unit=False)):
            receipt = installer.install(package(), host=host)
            self.assertFalse(receipt["ok"])
            self.assertNotIn("stop", host.events)
            self.assertTrue(receipt["manual_review_required"])

    def test_changed_docker_baseline_after_mutation_stops_and_reports_failure(self):
        installer = module()
        for baselines in (["a" * 64, "a" * 64, "b" * 64],
                          ["a" * 64, "a" * 64, "a" * 64, "b" * 64]):
            host = FakeHost(baselines=baselines)
            receipt = installer.install(package(), host=host)
            self.assertFalse(receipt["ok"])
            self.assertIn("stop", host.events)
            self.assertTrue(receipt["manual_review_required"])

    def run_bpf_probe(self, *, allow_error=None, deny_error=None):
        probe = MODULE_PATH.with_name("naver_erp_tunnel_bpf_preflight.py").read_text()
        attempts = []

        class Connection:
            def settimeout(self, value):
                pass

            def connect(self, endpoint):
                attempts.append(endpoint)
                failure = allow_error if endpoint[0] == "1.234.23.117" else deny_error
                if failure is not None:
                    raise failure

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        def create_connection(endpoint, timeout=None):
            connection = Connection()
            connection.connect(endpoint)
            return connection

        fake_socket = SimpleNamespace(create_connection=create_connection, socket=lambda *a, **k: Connection(),
                                      AF_INET=2, SOCK_STREAM=1, timeout=TimeoutError)
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with patch.dict("sys.modules", {"socket": fake_socket}), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                exec(compile(probe, "offline-bpf-probe", "exec"), {"__name__": "__main__"})
            except SystemExit as result:
                code = result.code
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        return code, attempts

    def test_bpf_probe_requires_allowed_be_and_explicit_kernel_denial(self):
        for denied in (errno.EACCES, errno.EPERM):
            with self.subTest(denied=denied):
                code, attempts = self.run_bpf_probe(deny_error=OSError(denied, "private-detail"))
                self.assertEqual(code, 0)
                self.assertEqual(attempts, [("1.234.23.117", 22), ("127.0.0.1", 22)])

    def test_bpf_probe_refuses_allowed_failure_refusal_timeout_or_unblocked_loopback(self):
        for options in ({"allow_error": OSError(errno.ECONNREFUSED, "private-detail")},
                        {"deny_error": OSError(errno.ECONNREFUSED, "private-detail")},
                        {"deny_error": TimeoutError("private-detail")}, {}):
            with self.subTest(options=sorted(options)):
                code, _ = self.run_bpf_probe(**options)
                self.assertNotEqual(code, 0)

    def test_native_group_collision_refuses_gid_name_and_primary_members(self):
        installer = module()
        existing_group = SimpleNamespace(gr_gid=10001, gr_mem=[])
        cases = ((existing_group, KeyError(), []),
                 (KeyError(), existing_group, []),
                 (KeyError(), KeyError(), [SimpleNamespace(pw_gid=10001)]))
        for gid, name, users in cases:
            with self.subTest(collision=(not isinstance(gid, Exception), not isinstance(name, Exception), bool(users))):
                gid_result = {"side_effect": gid} if isinstance(gid, Exception) else {"return_value": gid}
                name_result = {"side_effect": name} if isinstance(name, Exception) else {"return_value": name}
                with patch.object(installer.grp, "getgrgid", **gid_result), \
                        patch.object(installer.grp, "getgrnam", **name_result), \
                        patch.object(installer.pwd, "getpwall", return_value=users), \
                        patch.object(installer.subprocess, "run") as execute:
                    with self.assertRaises(installer.InstallError):
                        installer.NativeHost().create_group()
                    execute.assert_not_called()

    def test_native_publish_preexisting_target_refuses_before_opening_any_file(self):
        installer = module()
        entries = installer.manifest(package())
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_gid=0)
        for existing in entries:
            created = []
            with self.subTest(existing=existing), \
                    patch.object(installer.Path, "lstat", return_value=directory), \
                    patch.object(installer.os.path, "lexists", side_effect=lambda value: value == existing), \
                    patch.object(installer.os, "open") as opening:
                with self.assertRaises(installer.InstallError):
                    installer.NativeHost().publish(entries, created)
                opening.assert_not_called()
                self.assertEqual(created, [])

    def run_ingress(self, statuses, *, expect_error=False):
        installer = module()
        sockets = []

        class ResponseStream(io.BytesIO):
            def read(self, size=-1):
                self.read_sizes.append(size)
                return super().read(size)

        class UnixSocket:
            def __init__(self, status):
                self.sent = b""
                self.connected = []
                self.timeouts = []
                self.closed = False
                body = b"synthetic-private-response-marker" * 64
                header = ("HTTP/1.1 %d Status\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" %
                          (status, len(body))).encode()
                self.stream = ResponseStream(header + body)
                self.stream.read_sizes = []

            def settimeout(self, value):
                self.timeouts.append(value)

            def connect(self, path):
                self.connected.append(path)

            def sendall(self, data):
                self.sent += bytes(data)

            def makefile(self, mode):
                self.mode = mode
                return self.stream

            def close(self):
                self.closed = True

        def socket_factory(family, kind):
            self.assertEqual((family, kind), (installer.socket.AF_UNIX, installer.socket.SOCK_STREAM))
            connection = UnixSocket(statuses[len(sockets)])
            sockets.append(connection)
            return connection

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(installer.socket, "socket", side_effect=socket_factory), \
                patch.object(installer.socket, "create_connection", side_effect=AssertionError("TCP forbidden")) as tcp, \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            if expect_error:
                with self.assertRaisesRegex(installer.InstallError, "INGRESS_BOUNDARY_MISMATCH"):
                    installer.NativeHost().verify_ingress()
                receipt = None
            else:
                receipt = installer.NativeHost().verify_ingress()
            tcp.assert_not_called()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        for connection in sockets:
            self.assertEqual(connection.connected, ["/run/metainc-naver-erp-tunnel/erp.sock"])
            self.assertEqual(connection.timeouts, [5])
            self.assertEqual(connection.stream.read_sizes, [1024])
            self.assertTrue(connection.closed)
        return receipt, sockets

    def test_native_ingress_uses_only_fixed_unauthenticated_unix_requests(self):
        receipt, sockets = self.run_ingress([403, 403, 403, 403, 400])
        expected = (
            b"GET /api/ad-sync/contracts?stage=GENERAL&has_contract=true HTTP/1.1",
            b"GET /api/ad-sync/org-snapshot HTTP/1.1",
            b"GET /api/ad-sync/naver-customer-ids HTTP/1.1",
            b"POST /api/sso/exchange HTTP/1.1",
            b"GET /api/employee-management/my-profile HTTP/1.1",
        )
        self.assertEqual(len(sockets), len(expected))
        for connection, first_line in zip(sockets, expected):
            headers, body = connection.sent.split(b"\r\n\r\n", 1)
            self.assertEqual(headers.split(b"\r\n", 1)[0], first_line)
            self.assertIn(b"User-Agent: NaverControlPreflight/1", headers)
            self.assertIn(b"Connection: close", headers)
            lowered = headers.lower()
            for forbidden in (b"authorization:", b"proxy-authorization:", b"cookie:", b"x-api-key:"):
                self.assertNotIn(forbidden, lowered)
            if first_line.startswith(b"POST"):
                self.assertEqual(body, b"{}")
                self.assertIn(b"Content-Length: 2", headers)
                self.assertIn(b"Content-Type: application/json", headers)
            else:
                self.assertEqual(body, b"")
        self.assertEqual(receipt, {"unauthenticated_routes_rejected": 4, "other_routes_rejected": 1,
                                   "authenticated_data_read_verified": False})

    def test_native_ingress_unexpected_status_fails_without_printing_body(self):
        for index in range(5):
            statuses = [403, 403, 403, 403, 400]
            statuses[index] = 200
            with self.subTest(index=index):
                _, sockets = self.run_ingress(statuses, expect_error=True)
                self.assertEqual(len(sockets), index + 1)


if __name__ == "__main__":
    unittest.main()
