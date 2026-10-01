#!/usr/bin/env python3
"""GitHub 일회용 runner의 systemd TCP drop 재현 자료. 운영 정책 판정/설치 도구가 아니다."""
import errno
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import uuid

FLAGS = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
         "CI": "true", "NAVER_TUNNEL_BPF_NATIVE_CI": "1"}
UNIT_PATTERN = r"naver-tunnel-bpf-ci-[0-9a-f]{12}\.service"


class HarnessError(Exception):
    pass


def require_ci():
    if (any(os.environ.get(k) != v for k, v in FLAGS.items()) or os.geteuid() != 0
            or sys.platform != "linux" or Path("/proc/1/comm").read_text().strip() != "systemd"
            or not Path("/run/systemd/system").is_dir()):
        raise HarnessError("DISPOSABLE_SYSTEMD_RUNNER_REQUIRED")


def run(command):
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, timeout=2, check=False,
                            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"})
    if result.returncode:
        raise HarnessError("COMMAND_FAILED")
    return result.stdout.strip()


def connect_kind(address, port):
    if address not in {"127.0.0.1", "127.0.0.2"} or type(port) is not int or not 1 <= port <= 65535:
        raise HarnessError("ONLY_SYNTHETIC_LOOPBACK_ALLOWED")
    try:
        with socket.create_connection((address, port), timeout=2):
            return "connected"
    except TimeoutError:
        return "timeout"
    except OSError as error:
        return {errno.EPERM: "eperm", errno.EACCES: "eacces", errno.ECONNREFUSED: "refused"}.get(error.errno, "other_error")


def strict_errno_guard(kind):
    # 기존 errno-only 판정의 재현값이며, timeout을 운영 통과로 바꾸지 않는다.
    return kind in {"eperm", "eacces"}


def unit_command(unit, endpoint, deny_port, allow_port):
    if not re.fullmatch(UNIT_PATTERN, unit):
        raise HarnessError("FOREIGN_UNIT_REFUSED")
    properties = ("IPAddressDeny=any", "IPAddressAllow=127.0.0.2", "RestrictAddressFamilies=AF_INET AF_UNIX",
                  "RuntimeMaxSec=15s", "TimeoutStartSec=4s", "TimeoutStopSec=2s", "PrivateNetwork=no",
                  "NoNewPrivileges=yes", "StandardOutput=null", "StandardError=null", "LimitCORE=0")
    return (["/usr/bin/systemd-run", "--quiet", "--collect", "--service-type=exec", "--unit=" + unit]
            + ["--property=" + item for item in properties]
            + ["--setenv=" + key + "=" + value for key, value in FLAGS.items()]
            + ["/usr/bin/python3", "-I", "-B", str(Path(__file__).resolve()), "--probe", endpoint,
               str(deny_port), str(allow_port)])


def attachments(cgroup):
    unknown = {"status": "unknown", "attachments": []}
    tool = shutil.which("bpftool", path="/usr/sbin:/usr/bin:/sbin:/bin")
    if tool is None:
        return unknown
    if not cgroup.startswith("/") or ".." in Path(cgroup).parts:
        raise HarnessError("INVALID_CGROUP")
    try:
        # 상속 항목으로 대체하지 않고 실제 unit cgroup의 직접 부착만 관측한다.
        values = json.loads(run([tool, "-j", "cgroup", "show", "/sys/fs/cgroup" + cgroup]))
        items = [{"id": value["id"], "attach_type": value["attach_type"]} for value in values
                 if value.get("attach_type") in {"ingress", "egress"} and type(value.get("id")) is int]
        return {"status": "observed", "attachments": items}
    except (HarnessError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError):
        return unknown


def properties(unit):
    text = run(["/usr/bin/systemctl", "show", unit, "--property=MainPID", "--property=ControlGroup", "--property=InvocationID"])
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def probe(endpoint, deny_port, allow_port):
    require_ci()
    result = {"deny": connect_kind("127.0.0.1", deny_port), "allow": connect_kind("127.0.0.2", allow_port)}
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
        channel.settimeout(3)
        channel.connect(endpoint)
        channel.sendall(json.dumps(result).encode() + b"\n")
        channel.recv(1)  # 실제 cgroup 부착 조회 동안만 fixture 프로세스를 유지한다.


def collect():
    require_ci()
    unit = "naver-tunnel-bpf-ci-" + uuid.uuid4().hex[:12] + ".service"
    created = False
    invocation = None
    listeners = []
    def expired(_signum, _frame):
        raise HarnessError("HARNESS_DEADLINE")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(16)  # 정리 조회/stop 각 최대 2초를 포함하여 총 20초 이내로 제한한다.
    try:
        if run(["/usr/bin/systemctl", "show", unit, "--property=LoadState", "--value"]) != "not-found":
            raise HarnessError("EXISTING_UNIT_REFUSED")
        with tempfile.TemporaryDirectory(prefix="naver-bpf-ci-") as folder:
            for address in ("127.0.0.1", "127.0.0.2"):
                listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                listeners.append(listener)
                listener.bind((address, 0))
                listener.listen(8)
            ports = [listener.getsockname()[1] for listener in listeners]
            def controls():
                return [connect_kind(address, port) for address, port in zip(("127.0.0.1", "127.0.0.2"), ports)]
            before = controls()
            if before != ["connected", "connected"]:
                raise HarnessError("POSITIVE_CONTROL_FAILED")
            endpoint = str(Path(folder) / "probe.sock")
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as channel:
                channel.bind(endpoint)
                channel.listen(1)
                channel.settimeout(8)
                run(unit_command(unit, endpoint, *ports))
                created = True
                identity = properties(unit)
                invocation = identity.get("InvocationID")
                if not re.fullmatch(r"[0-9a-f]{32}", invocation or ""):
                    raise HarnessError("UNIT_IDENTITY_UNKNOWN")
                connection, _ = channel.accept()
                with connection:
                    connection.settimeout(2)
                    report = b""
                    while not report.endswith(b"\n") and len(report) < 256:
                        piece = connection.recv(256 - len(report))
                        if not piece:
                            raise HarnessError("PROBE_DISCONNECTED")
                        report += piece
                    observed = json.loads(report)
                    pid = int(identity["MainPID"])
                    cgroup = identity["ControlGroup"]
                    if pid <= 1 or not cgroup.endswith("/" + unit):
                        raise HarnessError("WRONG_PROBE_UNIT")
                    cgroup_matches = ("0::" + cgroup) in Path("/proc/%d/cgroup" % pid).read_text().splitlines()
                    same_netns = os.readlink("/proc/%d/ns/net" % pid) == os.readlink("/proc/self/ns/net")
                    bpf = attachments(cgroup)
                    after = controls()
                    connection.sendall(b"1")
            if not cgroup_matches or not same_netns or after != before or observed.get("allow") != "connected":
                raise HarnessError("CONTROL_OR_CONTEXT_MISMATCH")
            return {"ok": True, "parent_before": before, "parent_after": after, "probe": observed,
                    "strict_errno_guard_passes": strict_errno_guard(observed.get("deny")),
                    "timeout_observed": observed.get("deny") == "timeout", "cgroup_matches": cgroup_matches,
                    "same_network_namespace": same_netns, "bpf": bpf, "production_policy_verified": False}
    finally:
        signal.alarm(0)
        # 임의/기존 unit는 정리하지 않는다. 동일 InvocationID의 이번 새 unit만 stop한다.
        try:
            if created and invocation and properties(unit).get("InvocationID") == invocation:
                run(["/usr/bin/systemctl", "stop", "--no-block", unit])
        finally:
            for listener in listeners:
                listener.close()
            signal.signal(signal.SIGALRM, previous)


def main():
    try:
        if len(sys.argv) == 5 and sys.argv[1] == "--probe":
            probe(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
            return 0
        if len(sys.argv) != 1:
            raise HarnessError("INVALID_ARGUMENTS")
        result = collect()
    except Exception as error:
        result = {"ok": False, "error_kind": type(error).__name__, "production_policy_verified": False}
    print("NAVER_TUNNEL_BPF_NATIVE_CI_V1 " + json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
