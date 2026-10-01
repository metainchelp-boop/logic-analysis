#!/usr/bin/env python3
"""Approved new-only AD tunnel installation; never enables or changes apps."""
import base64
import ctypes
import grp
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import platform
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time

BE_IP = "1.234.23.117"
UNIT = "metainc-naver-erp-tunnel.service"
GROUP = "metainc-naver-erp-tunnel"
FOLDER = "/etc/metainc/naver-erp-tunnel"
RUNTIME = "/run/metainc-naver-erp-tunnel"
CONFIG = FOLDER + "/ssh_config"
KNOWN_HOSTS = FOLDER + "/known_hosts"
PROBE = FOLDER + "/bpf_preflight.py"
UNIT_PATH = "/etc/systemd/system/" + UNIT
LEGACY_PROBE_SHA256 = "6c20ea88447430315141f327901cbe241ea3ccc692125d399850ef2c4a4bb264"
PROBE_SHA256 = "caf9c1ac0463be5d41133a959d1111fe1452f77a0f5feccedaee921c4de0e175"
SSH_TEMPLATE = '''# 전용 service의 -F로만 사용한다. 개인/시스템 SSH config 또는 agent를 합치지 않는다.
# @BE_SSH_IPV4@는 검증한 숫자 IPv4로 치환. known_hosts는 확인된 ECDSA P-256 host key만.
Host naver-erp-tunnel
    HostName @BE_SSH_IPV4@
    Port 22
    User naver-erp-tunnel
    AddressFamily inet
    CanonicalizeHostname no
    BatchMode yes
    IdentitiesOnly yes
    IdentityAgent none
    IdentityFile /etc/metainc/naver-erp-tunnel/id_ed25519
    PubkeyAcceptedAlgorithms ssh-ed25519
    HostKeyAlgorithms ecdsa-sha2-nistp256
    UserKnownHostsFile /etc/metainc/naver-erp-tunnel/known_hosts
    GlobalKnownHostsFile /dev/null
    KnownHostsCommand none
    StrictHostKeyChecking yes
    UpdateHostKeys no
    VerifyHostKeyDNS no
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PreferredAuthentications publickey
    ForwardAgent no
    ForwardX11 no
    PermitLocalCommand no
    ProxyCommand none
    ProxyJump none
    ControlMaster no
    ControlPath none
    ControlPersist no
    RequestTTY no
    SessionType none
    StdinNull yes
    ConnectTimeout 10
    ConnectionAttempts 1
    ExitOnForwardFailure yes
    ServerAliveInterval 15
    ServerAliveCountMax 2
    TCPKeepAlive no
    StreamLocalBindMask 0117
    StreamLocalBindUnlink no
    LogLevel ERROR
    LocalForward /run/metainc-naver-erp-tunnel/erp.sock 127.0.0.1:18081
'''
SERVICE_TEMPLATE = '''# AD 후보 전용. @BE_SSH_IPV4@ 치환·검증 및 승인 전 enable/start 금지.
# Group 10001은 엔진 컨테이너의 고정 GID. key는 root:root 0600, engine에 mount하지 않는다.
[Unit]
Description=Naver ERP isolated SSH forwarder (candidate only)
Wants=network-online.target
After=network-online.target
StartLimitIntervalSec=120s
StartLimitBurst=3

[Service]
Type=simple
User=root
Group=10001
UMask=0077
RuntimeDirectory=metainc-naver-erp-tunnel
RuntimeDirectoryMode=0750
# 컨테이너 directory bind의 inode를 지킨다. 잔류 socket은 자동 unlink하지 않는다.
RuntimeDirectoryPreserve=yes
ExecStart=/usr/bin/ssh -F /etc/metainc/naver-erp-tunnel/ssh_config -N -T naver-erp-tunnel
Restart=on-failure
RestartSec=10s
TimeoutStopSec=15s
KillMode=control-group
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
CapabilityBoundingSet=
AmbientCapabilities=
RestrictAddressFamilies=AF_UNIX AF_INET
RestrictSUIDSGID=yes
LockPersonality=yes
ReadWritePaths=/run/metainc-naver-erp-tunnel
IPAddressDeny=any
IPAddressAllow=@BE_SSH_IPV4@
StandardOutput=null
StandardError=null

[Install]
WantedBy=multi-user.target
'''


class InstallError(RuntimeError):
    pass


def digest(body):
    return hashlib.sha256(body).hexdigest()


def key_wire(key, algorithm):
    if not isinstance(key, str) or not re.fullmatch(re.escape(algorithm) + r" [A-Za-z0-9+/]+={0,2}", key):
        raise InstallError("INVALID_PUBLIC_KEY")
    encoded = key.split()[1]
    try:
        wire = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise InstallError("INVALID_PUBLIC_KEY") from None
    if base64.b64encode(wire).decode() != encoded:
        raise InstallError("NONCANONICAL_PUBLIC_KEY")
    return wire


def normalize_derived_public_key(value):
    # ssh-keygen -y may retain the exact comment set by our dedicated key generator.
    # This exception applies only to locally derived output, never supplied public keys.
    match = re.fullmatch(r"(ssh-ed25519 [A-Za-z0-9+/]+={0,2})(?: naver-erp-tunnel)?", value) if isinstance(value, str) else None
    if match is None:
        raise InstallError("INVALID_DERIVED_PUBLIC_KEY")
    return match.group(1)


def validate_package(package):
    fields = {"expected_docker_baseline", "expected_public_fingerprint", "known_host_key", "work_switches_off"}
    if not isinstance(package, dict) or set(package) != fields or package["work_switches_off"] is not True:
        raise InstallError("INVALID_PACKAGE")
    if not isinstance(package["expected_docker_baseline"], str) or not re.fullmatch(r"[0-9a-f]{64}", package["expected_docker_baseline"]):
        raise InstallError("INVALID_BASELINE")
    if not isinstance(package["expected_public_fingerprint"], str) or not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", package["expected_public_fingerprint"]):
        raise InstallError("INVALID_FINGERPRINT")
    remaining = key_wire(package["known_host_key"], "ecdsa-sha2-nistp256")
    pieces = []
    while remaining:
        if len(remaining) < 4:
            raise InstallError("INVALID_HOST_KEY")
        length = int.from_bytes(remaining[:4], "big")
        if not 0 < length <= len(remaining) - 4:
            raise InstallError("INVALID_HOST_KEY")
        pieces.append(remaining[4:4 + length])
        remaining = remaining[4 + length:]
    if len(pieces) != 3 or pieces[:2] != [b"ecdsa-sha2-nistp256", b"nistp256"] or len(pieces[2]) != 65 or pieces[2][0] != 4:
        raise InstallError("INVALID_HOST_KEY")
    x, y = int.from_bytes(pieces[2][1:33], "big"), int.from_bytes(pieces[2][33:], "big")
    prime = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
    b = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
    if x >= prime or y >= prime or (y*y - (x*x*x - 3*x + b)) % prime:
        raise InstallError("INVALID_HOST_KEY_POINT")
    return package


def manifest(package, probe_source=None):
    validate_package(package)
    if digest(SSH_TEMPLATE.encode()) != "1c37f158c26a988973707c36b2f4ccade561c6e1fa93334a12ece8abaf9df0aa" or digest(SERVICE_TEMPLATE.encode()) != "93c18df46c539dc2cbc1a103536aaa7c6e8444c9215897ae3b8c5fb8a59bd24a":
        raise InstallError("TEMPLATE_CHANGED")
    probe = Path(__file__).with_name("naver_erp_tunnel_bpf_preflight.py").read_bytes() if probe_source is None else probe_source
    if not isinstance(probe, bytes) or digest(probe) != PROBE_SHA256:
        raise InstallError("PROBE_CHANGED")
    service = SERVICE_TEMPLATE.replace("ExecStart=", "ExecStartPre=/usr/bin/python3 " + PROBE + "\nExecStart=", 1)
    return {CONFIG: (SSH_TEMPLATE.replace("@BE_SSH_IPV4@", BE_IP).encode(), 0o600),
            KNOWN_HOSTS: ((BE_IP + " " + package["known_host_key"] + "\n").encode(), 0o600),
            PROBE: (probe, 0o600), UNIT_PATH: (service.replace("@BE_SSH_IPV4@", BE_IP).encode(), 0o644)}


def validate_started(host, package):
    running = host.verify_running()
    attachment = host.verify_bpf_attachment()
    ingress = host.verify_ingress()
    host.parent_controls()
    if host.baseline() != package["expected_docker_baseline"]:
        raise InstallError("BASELINE_CHANGED")
    return {"running": running, "containers_unchanged": True, "bpf_attachment": attachment,
            "bpf_runtime_enforcement_verified": True,
            "bpf_scope": "direct_attachment_and_unit_candidate_and_parent_positive_controls",
            "parent_positive_controls_before_after": True,
            "enabled": False, "work_switches_off": True, "work_switches_off_verified": False,
            "auth_boundary_roundtrip_verified": True, **ingress}


def install(package, *, host=None, probe_source=None):
    package = validate_package(package)
    files = manifest(package, probe_source)
    host = host if host is not None else NativeHost()
    host.preflight(package)
    if host.baseline() != package["expected_docker_baseline"]:
        raise InstallError("BASELINE_CHANGED")
    created = []
    if host.baseline() != package["expected_docker_baseline"]:
        raise InstallError("BASELINE_CHANGED")
    stage = "create_group"
    try:
        host.create_group()
        stage = "publish"
        host.publish(files, created)
        stage = "verify_config"
        host.verify_config()
        if host.baseline() != package["expected_docker_baseline"]:
            raise InstallError("BASELINE_CHANGED")
        stage = "parent_controls"
        host.parent_controls()
        stage = "start"
        host.start()
        stage = "validate_started"
        verified = validate_started(host, package)
        return {"ok": True, "created": created,
                "expected_created_sha256": {name: digest(files[name][0]) for name in created},
                **verified}
    except Exception as error:
        stopped = False
        if UNIT_PATH in created:
            try:
                host.stop()
                stopped = True
            except Exception:
                pass
        code = str(error) if isinstance(error, InstallError) and re.fullmatch(r"[A-Z0-9_]{1,80}", str(error)) else None
        return {"ok": False, "error_kind": type(error).__name__, "error_code": code, "stage": stage, "created": created,
                "expected_created_sha256": {name: digest(files[name][0]) for name in created},
                "new_unit_stopped": stopped, "group_may_remain": True, "manual_review_required": True,
                "automatic_deletions": 0, "enabled": False, "work_switches_off": True,
                "bpf_runtime_enforcement_verified": False}


def activate_installed(package, *, host=None, probe_source=None):
    """Explicit legacy-probe upgrade only; never creates accounts or enables units."""
    package = validate_package(package)
    files = manifest(package, probe_source)
    host = host if host is not None else NativeHost()
    host.preflight_installed(package, files)
    for _ in range(2):
        if host.baseline() != package["expected_docker_baseline"]:
            raise InstallError("BASELINE_CHANGED")
    changed = []
    stage = "replace_probe"
    try:
        host.replace_probe(files, changed)
        stage = "verify_config"
        host.verify_config()
        if host.baseline() != package["expected_docker_baseline"]:
            raise InstallError("BASELINE_CHANGED")
        stage = "parent_controls"
        host.parent_controls()
        stage = "start"
        host.start()
        stage = "validate_started"
        verified = validate_started(host, package)
        return {"ok": True, "activation": True, "changed": changed,
                "expected_changed_sha256": {name: digest(files[name][0]) for name in changed}, **verified}
    except Exception as error:
        stopped = False
        try:
            host.stop()
            stopped = True
        except Exception:
            pass
        code = str(error) if isinstance(error, InstallError) and re.fullmatch(r"[A-Z0-9_]{1,80}", str(error)) else None
        return {"ok": False, "activation": True, "stage": stage, "error_kind": type(error).__name__,
                "error_code": code, "changed": changed, "new_unit_stopped": stopped,
                "manual_review_required": True, "automatic_deletions": 0, "enabled": False,
                "work_switches_off": True, "bpf_runtime_enforcement_verified": False}


def run(args):
    result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C"})
    if result.returncode or len(result.stdout) > 131072:
        raise InstallError("NATIVE_COMMAND_FAILED")
    return result.stdout.decode("utf-8").strip()


# Linux v5.15 UAPI bpf.h: enum bpf_cmd=16, attach types ingress=0/egress=1,
# query fields at offsets 0,4,8,12,16,24; flags=0 queries direct attachments.
# https://github.com/torvalds/linux/blob/v5.15/include/uapi/linux/bpf.h
class BpfQuery(ctypes.Structure):
    _fields_ = [("target_fd", ctypes.c_uint32), ("attach_type", ctypes.c_uint32),
                ("query_flags", ctypes.c_uint32), ("attach_flags", ctypes.c_uint32),
                ("prog_ids", ctypes.c_uint64), ("prog_cnt", ctypes.c_uint32)]


def bpf_query_count(fd, attach_type):
    # x86 syscall_64.tbl and arm64 -> asm-generic/unistd.h in the same v5.15 tree.
    numbers = {"x86_64": 321, "aarch64": 280}
    machine = platform.machine()
    if (platform.system() != "Linux" or machine not in numbers or sys.byteorder != "little"
            or ctypes.sizeof(ctypes.c_void_p) != 8 or ctypes.sizeof(ctypes.c_long) != 8
            or ctypes.sizeof(BpfQuery) != 32 or BpfQuery.prog_ids.offset != 16
            or BpfQuery.prog_cnt.offset != 24 or attach_type not in (0, 1)
            or type(fd) is not int or fd < 0):
        raise InstallError("UNSUPPORTED_BPF_QUERY_ABI")
    identifiers = (ctypes.c_uint32 * 256)()
    query = BpfQuery(target_fd=fd, attach_type=attach_type, query_flags=0,
                     prog_ids=ctypes.addressof(identifiers), prog_cnt=256)
    libc = ctypes.CDLL(None, use_errno=True)
    syscall = libc.syscall
    syscall.restype = ctypes.c_long
    # Never load/attach/detach programs, enter namespaces, or retry a denied query.
    ctypes.set_errno(0)
    result = syscall(ctypes.c_long(numbers[machine]), ctypes.c_int(16),
                     ctypes.byref(query), ctypes.c_uint(ctypes.sizeof(query)))
    if result != 0:
        raise InstallError("BPF_QUERY_FAILED")
    count = query.prog_cnt
    if not 1 <= count <= 256 or any(identifiers[index] == 0 for index in range(count)):
        raise InstallError("DIRECT_BPF_ATTACHMENT_MISSING")
    return count


class NativeHost:
    def parent_controls(self):
        for address in (BE_IP, "127.0.0.1"):
            with socket.create_connection((address, 22), timeout=3):
                pass
        return {"be_ssh_reachable": True, "local_ssh_reachable": True}

    def inactive_unit(self):
        value = run(["/usr/bin/systemctl", "show", UNIT, "-p", "ActiveState", "-p", "MainPID",
                     "-p", "LoadState", "-p", "UnitFileState"])
        pairs = [line.split("=", 1) for line in value.splitlines()]
        expected = {"ActiveState": "inactive", "MainPID": "0", "LoadState": "loaded", "UnitFileState": "disabled"}
        if len(pairs) != 4 or any(len(pair) != 2 for pair in pairs) or dict(pairs) != expected:
            raise InstallError("INSTALLED_UNIT_NOT_INACTIVE_DISABLED")
        if os.path.lexists(RUNTIME + "/erp.sock"):
            raise InstallError("PREEXISTING_SOCKET")
        if os.path.lexists(RUNTIME):
            info = Path(RUNTIME).lstat()
            if (not stat.S_ISDIR(info.st_mode) or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (0, 10001, 0o750)
                    or any(Path(RUNTIME).iterdir())):
                raise InstallError("RUNTIME_NOT_EMPTY")

    def preflight_installed(self, package, files):
        self.verify_private_identity(package)
        self.inactive_unit()
        group = grp.getgrnam(GROUP)
        if group.gr_gid != 10001 or grp.getgrgid(10001).gr_name != GROUP or group.gr_mem or any(row.pw_gid == 10001 for row in pwd.getpwall()):
            raise InstallError("GROUP_NOT_EXCLUSIVE")
        identities = {}
        for name, (body, mode) in files.items():
            identities[name] = self.regular(name, mode)
            expected = LEGACY_PROBE_SHA256 if name == PROBE else digest(body)
            if digest(Path(name).read_bytes()) != expected:
                raise InstallError("INSTALLED_BASELINE_CHANGED")
        self.installed_identities = identities
        self.files = files

    def replace_probe(self, files, changed):
        self.inactive_unit()
        for name, (body, mode) in files.items():
            if self.regular(name, mode) != self.installed_identities[name]:
                raise InstallError("INSTALLED_INODE_CHANGED")
            expected = LEGACY_PROBE_SHA256 if name == PROBE else digest(body)
            if digest(Path(name).read_bytes()) != expected:
                raise InstallError("INSTALLED_BASELINE_CHANGED")
        fd, temporary = tempfile.mkstemp(prefix=".bpf-candidate-", dir=FOLDER)
        temporary_identity = os.fstat(fd)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                os.fchown(stream.fileno(), 0, 0)
                stream.write(files[PROBE][0])
                stream.flush()
                os.fsync(stream.fileno())
            if self.regular(PROBE, 0o600) != self.installed_identities[PROBE] or digest(Path(PROBE).read_bytes()) != LEGACY_PROBE_SHA256:
                raise InstallError("INSTALLED_PROBE_CHANGED")
            os.replace(temporary, PROBE)
            changed.append(PROBE)
        finally:
            if os.path.lexists(temporary):
                remaining = os.lstat(temporary)
                if (remaining.st_dev, remaining.st_ino) == (temporary_identity.st_dev, temporary_identity.st_ino):
                    os.unlink(temporary)

    def bpf_snapshot(self):
        properties = ("ControlGroup", "MainPID", "IPAddressAllow", "IPAddressDeny", "ActiveState")
        command = ["/usr/bin/systemctl", "show", UNIT]
        for name in properties:
            command.extend(("-p", name))
        lines = run(command).splitlines()
        pairs = [line.split("=", 1) for line in lines]
        if any(len(pair) != 2 for pair in pairs) or len(pairs) != len(properties):
            raise InstallError("BPF_UNIT_PROPERTIES_INVALID")
        values = dict(pairs)
        if set(values) != set(properties):
            raise InstallError("BPF_UNIT_PROPERTIES_INVALID")
        cgroup = "/system.slice/" + UNIT
        pid = values["MainPID"]
        if values["ActiveState"] != "active" or values["ControlGroup"] != cgroup or not re.fullmatch(r"[1-9][0-9]*", pid):
            raise InstallError("BPF_UNIT_NOT_ACTIVE")
        for name, expected in (("IPAddressAllow", {BE_IP + "/32"}),
                               ("IPAddressDeny", {"0.0.0.0/0", "::/0"})):
            tokens = values[name].split()
            try:
                actual = {str(ipaddress.ip_network(value, strict=True)) for value in tokens if "/" in value}
            except ValueError:
                raise InstallError("BPF_IP_POLICY_MISMATCH") from None
            if len(tokens) != len(expected) or actual != expected:
                raise InstallError("BPF_IP_POLICY_MISMATCH")
        if not Path("/sys/fs/cgroup/cgroup.controllers").is_file():
            raise InstallError("UNIFIED_CGROUP_REQUIRED")
        if Path("/proc/" + pid + "/cgroup").read_text().strip() != "0::" + cgroup:
            raise InstallError("PID_CGROUP_MISMATCH")
        parent = os.stat("/proc/self/ns/net")
        child = os.stat("/proc/" + pid + "/ns/net")
        namespace = (parent.st_dev, parent.st_ino)
        if namespace != (child.st_dev, child.st_ino):
            raise InstallError("NETWORK_NAMESPACE_MISMATCH")
        return values, namespace

    def verify_bpf_attachment(self):
        """Read-only completion gate after start; never changes BPF programs."""
        if os.geteuid() != 0 or platform.system() != "Linux":
            raise InstallError("BPF_ROOT_LINUX_REQUIRED")
        before = self.bpf_snapshot()
        path = "/sys/fs/cgroup" + before[0]["ControlGroup"]
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise InstallError("INVALID_CGROUP_DESCRIPTOR")
            ingress = bpf_query_count(descriptor, 0)
            egress = bpf_query_count(descriptor, 1)
            if self.bpf_snapshot() != before:
                raise InstallError("BPF_SNAPSHOT_CHANGED")
        finally:
            os.close(descriptor)
        return {"ingress_program_count": ingress, "egress_program_count": egress,
                "unit_cgroup_verified": True, "network_namespace_verified": True,
                "ip_policy_verified": True, "bpf_attachment_verified": True,
                "packet_enforcement_verified": False}

    def parents(self, path):
        for parent in Path(path).parents:
            item = parent.lstat()
            if not stat.S_ISDIR(item.st_mode) or (item.st_uid, item.st_gid) != (0, 0) or item.st_mode & 0o022:
                raise InstallError("UNSAFE_PARENT")

    def regular(self, path, mode):
        self.parents(path)
        info = Path(path).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (info.st_uid, info.st_gid) != (0, 0) or stat.S_IMODE(info.st_mode) != mode:
            raise InstallError("UNSAFE_FILE")
        return info.st_dev, info.st_ino

    def verify_private_identity(self, package):
        if os.geteuid() != 0:
            raise InstallError("ROOT_REQUIRED")
        self.parents(FOLDER + "/id_ed25519")
        folder = Path(FOLDER).lstat()
        if stat.S_IMODE(folder.st_mode) != 0o700:
            raise InstallError("KEY_DIRECTORY_MODE")
        private = self.regular(FOLDER + "/id_ed25519", 0o600)
        self.regular(FOLDER + "/id_ed25519.pub", 0o600)
        public = run(["/usr/bin/ssh-keygen", "-y", "-P", "", "-f", FOLDER + "/id_ed25519"])
        wire = key_wire(normalize_derived_public_key(public), "ssh-ed25519")
        if len(wire) != 51 or wire[:19] != b"\0\0\0\x0bssh-ed25519\0\0\0\x20":
            raise InstallError("CLIENT_KEY_NOT_ED25519")
        fp = "SHA256:" + base64.b64encode(hashlib.sha256(wire).digest()).decode().rstrip("=")
        if fp != package["expected_public_fingerprint"] or private != self.regular(FOLDER + "/id_ed25519", 0o600):
            raise InstallError("CLIENT_KEY_CHANGED")

    def preflight(self, package):
        self.verify_private_identity(package)
        for path in (CONFIG, KNOWN_HOSTS, PROBE, UNIT_PATH, RUNTIME):
            self.parents(path)
            if os.path.lexists(path):
                raise InstallError("PREEXISTING_TARGET")
        if run(["/usr/bin/systemctl", "show", UNIT, "-p", "LoadState", "--value"]) != "not-found":
            raise InstallError("PREEXISTING_UNIT")
        self.group_absent()
        with socket.create_connection(("127.0.0.1", 22), timeout=3):
            pass

    def group_absent(self):
        for function, value in ((grp.getgrgid, 10001), (grp.getgrnam, GROUP)):
            try:
                function(value)
            except KeyError:
                continue
            raise InstallError("GROUP_COLLISION")
        if any(row.pw_gid == 10001 for row in pwd.getpwall()):
            raise InstallError("GID_ALREADY_USED")

    def create_group(self):
        self.group_absent()
        run(["/usr/sbin/groupadd", "--system", "--gid", "10001", GROUP])
        group = grp.getgrnam(GROUP)
        if group.gr_gid != 10001 or group.gr_mem or any(row.pw_gid == 10001 for row in pwd.getpwall()):
            raise InstallError("GROUP_NOT_EXCLUSIVE")

    def baseline(self):
        names = run(["/usr/bin/docker", "ps", "-a", "--format", "{{.Names}}"])
        names = sorted(n for n in names.splitlines() if re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", n)
                       and re.search(r"ad-api|ad-dashboard|logic-analysis|studio|autobid", n))
        if not 0 < len(names) <= 20:
            raise InstallError("UNEXPECTED_CONTAINERS")
        fields = {"id": ".Id", "image_id": ".Image", "running": ".State.Running",
                  "started_at": ".State.StartedAt", "restart_count": ".RestartCount",
                  "project": '(index .Config.Labels "com.docker.compose.project")',
                  "service": '(index .Config.Labels "com.docker.compose.service")'}
        rows = []
        for name in names:
            row = {"name": name}
            for field, value in fields.items():
                row[field] = json.loads(run(["/usr/bin/docker", "inspect", "--format", "{{json " + value + "}}", name]))
            rows.append(row)
        if len([row for row in rows if row["service"] == "ad-api" and row["running"] is True]) != 1:
            raise InstallError("AD_NOT_RUNNING")
        return digest(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())

    def publish(self, files, created):
        for name in files:
            self.parents(name)
            if os.path.lexists(name):
                raise InstallError("PREEXISTING_TARGET")
        for name, (body, mode) in files.items():
            self.parents(name)
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
            created.append(name)
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), mode)
                os.fchown(stream.fileno(), 0, 0)
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
        self.files = files

    def verify_config(self):
        for name, (body, mode) in self.files.items():
            identity = self.regular(name, mode)
            if hasattr(self, "installed_identities") and name != PROBE and identity != self.installed_identities[name]:
                raise InstallError("INSTALLED_INODE_CHANGED")
            if Path(name).read_bytes() != body:
                raise InstallError("INSTALLED_FILE_CHANGED")
        run(["/usr/bin/systemd-analyze", "verify", UNIT_PATH])
        options = run(["/usr/bin/ssh", "-G", "-F", CONFIG, "naver-erp-tunnel"])
        values = dict(line.split(None, 1) for line in options.splitlines() if " " in line)
        required = {"hostname": BE_IP, "user": "naver-erp-tunnel", "port": "22",
                    "hostkeyalgorithms": "ecdsa-sha2-nistp256", "stricthostkeychecking": "true",
                    "identityagent": "none", "identityfile": FOLDER + "/id_ed25519",
                    "userknownhostsfile": KNOWN_HOSTS, "streamlocalbindunlink": "no",
                    "localforward": RUNTIME + "/erp.sock [127.0.0.1]:18081"}
        if any(values.get(key) != value for key, value in required.items()):
            raise InstallError("SSH_EFFECTIVE_CONFIG_MISMATCH")

    def start(self):
        run(["/usr/bin/systemctl", "daemon-reload"])
        run(["/usr/bin/systemctl", "start", UNIT])

    def verify_running(self):
        for _ in range(75):
            state = run(["/usr/bin/systemctl", "show", UNIT, "-p", "ActiveState", "-p", "MainPID", "-p", "NRestarts"])
            values = dict(line.split("=", 1) for line in state.splitlines())
            pid = values.get("MainPID", "0")
            if values.get("ActiveState") == "active" and pid.isdigit() and int(pid) > 0 and values.get("NRestarts") == "0":
                try:
                    sock = Path(RUNTIME + "/erp.sock").lstat()
                except FileNotFoundError:
                    time.sleep(0.2)
                    continue
                directory = Path(RUNTIME).lstat()
                status = Path("/proc/" + pid + "/status").read_text()
                ids = {name: re.search(r"(?m)^" + name + r":\s+(.+)$", status) for name in ("Uid", "Gid")}
                if (not all(ids.values()) or set(ids["Uid"][1].split()) != {"0"} or set(ids["Gid"][1].split()) != {"10001"}
                        or not stat.S_ISSOCK(sock.st_mode) or (sock.st_uid, sock.st_gid, stat.S_IMODE(sock.st_mode)) != (0, 10001, 0o660)
                        or not stat.S_ISDIR(directory.st_mode) or (directory.st_uid, directory.st_gid, stat.S_IMODE(directory.st_mode)) != (0, 10001, 0o750)):
                    raise InstallError("RUNTIME_IDENTITY_OR_SOCKET_MISMATCH")
                self.verify_config()
                return {"uid": 0, "gid": 10001, "socket_mode": "0660"}
            time.sleep(0.2)
        raise InstallError("NEW_UNIT_NOT_READY")

    def stop(self):
        run(["/usr/bin/systemctl", "stop", UNIT])

    def verify_ingress(self):
        class UnixConnection(http.client.HTTPConnection):
            def connect(self):
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                try:
                    connection.settimeout(5)
                    connection.connect(RUNTIME + "/erp.sock")
                except Exception:
                    connection.close()
                    raise
                self.sock = connection

        requests = (
            ("GET", "/api/ad-sync/contracts?stage=GENERAL&has_contract=true", None, 403),
            ("GET", "/api/ad-sync/org-snapshot", None, 403),
            ("GET", "/api/ad-sync/naver-customer-ids", None, 403),
            ("POST", "/api/sso/exchange", b"{}", 403),
            ("GET", "/api/employee-management/my-profile", None, 400),
        )
        for method, path, body, expected in requests:
            connection = UnixConnection("api.metainc.co.kr", timeout=5)
            try:
                headers = {"User-Agent": "NaverControlPreflight/1", "Connection": "close"}
                if body is not None:
                    headers.update({"Content-Type": "application/json", "Content-Length": "2"})
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
                status = response.status
                response.read(1024)
                if status != expected:
                    raise InstallError("INGRESS_BOUNDARY_MISMATCH")
            finally:
                connection.close()
        return {"unauthenticated_routes_rejected": 4, "other_routes_rejected": 1,
                "authenticated_data_read_verified": False}


def main():
    try:
        if len(sys.argv) != 1:
            raise InstallError("NO_ARGUMENTS_ALLOWED")
        encoded = os.environ.get("NAVER_TUNNEL_SERVICE_PACKAGE_B64", "")
        if not 0 < len(encoded) <= 16384:
            raise InstallError("INVALID_ENCODING")
        result = install(json.loads(base64.b64decode(encoded, validate=True)))
    except Exception as error:
        result = {"ok": False, "error_kind": type(error).__name__, "enabled": False}
    print("NAVER_TUNNEL_SERVICE_INSTALL_V1 " + json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
