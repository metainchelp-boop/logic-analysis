#!/usr/bin/env python3
"""Ubuntu22.04 일회용 --network none 컨테이너 전용 합성 검증. 설치 도구 아님."""
from __future__ import annotations

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import pwd
import signal
import socket
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "deploy/naver-erp-tunnel"
ACCOUNT = "naver-erp-tunnel"
STAGE = "container-guard"
DEADLINE = 0.0
CHECKS = 0


class Refused(Exception):
    pass


def check(value):
    global CHECKS
    if not value:
        raise Refused()
    CHECKS += 1


def stage(name):
    global STAGE
    STAGE = name
    print(json.dumps({"stage": name}), flush=True)


def timeout(maximum=8):
    remaining = DEADLINE - time.monotonic()
    if remaining <= 0:
        raise Refused()
    return min(maximum, remaining)


def run(argv, *, data=None, expected=0, **kwargs):
    result = subprocess.run(argv, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout(), check=False, **kwargs)
    if expected is not None:
        check(result.returncode == expected)
    return result


def write(path, content, mode=0o600):
    # 이 helper는 container-guard 뒤의 새 임시 트리에서만 호출한다.
    with path.open("x", encoding="utf-8") as handle:
        handle.write(content)
    path.chmod(mode)


def wait_port(port, process):
    end = time.monotonic() + timeout()
    while time.monotonic() < end:
        if process.poll() is not None:
            raise Refused()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conn:
            conn.settimeout(0.1)
            if conn.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.03)
    raise Refused()


def available_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class FixtureServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, *_args):
        # 합성 서버의 원문 요청/예외도 로그에 쓰지 않는다.
        pass

    def server_bind(self):
        # HTTPServer의 getfqdn/DNS 호출도 사용하지 않는다.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "localhost", self.server_address[1]


class Fixture(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls = 0

    def log_message(self, *_args):
        pass

    def do_GET(self):
        self.respond()

    def do_POST(self):
        self.respond()

    def respond(self):
        self.connection.settimeout(3)
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1024:
            self.send_error(413)
            return
        self.rfile.read(length)
        Fixture.calls += 1
        body = json.dumps({"method": self.command, "target": self.path,
                           "headers": {key.lower(): value for key, value in self.headers.items()}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("api.metainc.co.kr", timeout=timeout(5))
        self.path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def request(path, method, target, body=None, headers=None):
    connection = UnixHTTP(path)
    try:
        connection.request(method, target, body=body, headers=headers or {})
        response = connection.getresponse()
        payload = response.read(65537)
        check(len(payload) <= 65536)
        return response.status, payload
    finally:
        connection.close()


def container_guard():
    # 호스트·일반 runner·망 있는 container에서 사용자/파일 생성 전에 중단한다.
    if (sys.platform != "linux" or os.geteuid() != 0
            or os.environ.get("NAVER_TUNNEL_NATIVE_CI") != "1"
            or not Path("/.dockerenv").is_file()
            or {p.name for p in Path("/sys/class/net").iterdir()} != {"lo"}):
        raise Refused()
    if any(name.startswith(("NAVER_BACKUP_", "NAVER_ENGINE_", "NAVER_CONTROL_"))
           or name in {"SSH_AUTH_SOCK", "GITHUB_TOKEN", "GH_TOKEN"} for name in os.environ):
        raise Refused()
    try:
        pwd.getpwnam(ACCOUNT)
    except KeyError:
        return
    raise Refused()


def exercise(root, processes):
    stage("synthetic-keys")
    root.chmod(0o755)
    keys = root / "keys"
    keys.mkdir(mode=0o700)
    host, client = keys / "host", keys / "client"
    run(["ssh-keygen", "-q", "-t", "ecdsa", "-b", "256", "-N", "", "-f", str(host)])
    run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(client)])
    ssh_port = available_port()
    auth = root / "authorized_keys"
    public = client.with_suffix(".pub").read_text().split()[1]
    auth_template = (TEMPLATES / "authorized_keys.template").read_text()
    write(auth, auth_template.replace("@AD_EGRESS_IPV4@", "127.0.0.1")
          .replace("@NEW_TUNNEL_PUBLIC_KEY_BASE64@", public), 0o644)
    known = keys / "known_hosts"
    host_public = " ".join(host.with_suffix(".pub").read_text().split()[:2])
    write(known, "[127.0.0.1]:" + str(ssh_port) + " " + host_public + "\n")

    stage("native-sshd-policy")
    fragment = root / "sshd-match.conf"
    write(fragment, (TEMPLATES / "be-sshd.conf").read_text().replace(
        "/etc/ssh/authorized_keys/naver-erp-tunnel", str(auth)), 0o644)
    base = (f"Port {ssh_port}\nListenAddress 127.0.0.1\nHostKey {host}\n"
            f"PidFile {root / 'sshd.pid'}\nUsePAM yes\nStrictModes yes\nPermitRootLogin no\nLogLevel ERROR\n")
    original, sshd_config = root / "sshd-original.conf", root / "sshd.conf"
    write(original, base)
    write(sshd_config, base + f"Include {fragment}\n")
    run(["/usr/sbin/sshd", "-t", "-f", str(sshd_config)])
    context = "user=root,addr=127.0.0.1,host=localhost"
    before = run(["/usr/sbin/sshd", "-T", "-f", str(original), "-C", context]).stdout
    after = run(["/usr/sbin/sshd", "-T", "-f", str(sshd_config), "-C", context]).stdout
    check(before == after)
    effective = run(["/usr/sbin/sshd", "-T", "-f", str(sshd_config), "-C",
                     f"user={ACCOUNT},addr=127.0.0.1,host=localhost"]).stdout.decode()
    for item in ("maxsessions 0", "allowtcpforwarding local", "permitopen 127.0.0.1:18081",
                 "allowstreamlocalforwarding no", "permitlisten none", "authenticationmethods publickey"):
        check(item in effective.splitlines())
    sshd = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", str(sshd_config)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    processes.append(sshd)
    wait_port(ssh_port, sshd)

    stage("native-nginx")
    fixture = FixtureServer(("127.0.0.1", 0), Fixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    try:
        policy = root / "nginx-ingress.conf"
        write(policy, (TEMPLATES / "be-nginx.conf").read_text())
        nginx_conf = root / "nginx.conf"
        write(nginx_conf, f"daemon off; master_process off; pid {root / 'nginx.pid'};\n"
              "error_log /dev/null; events { worker_connections 64; }\nhttp { access_log off;\n"
              f"client_body_temp_path {root / 'body'}; proxy_temp_path {root / 'proxy'};\n"
              f"upstream sales_be_up {{ server 127.0.0.1:{fixture.server_port}; }}\ninclude {policy};\n}}\n")
        run(["nginx", "-t", "-c", str(nginx_conf)])
        nginx = subprocess.Popen(["nginx", "-c", str(nginx_conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(nginx)
        wait_port(18081, nginx)

        stage("unix-forward")
        sockets = root / "socket"
        sockets.mkdir(mode=0o750)
        os.chown(sockets, 0, 10001)
        socket_path = sockets / "erp.sock"
        client_config = root / "ssh-client.conf"
        rendered = (TEMPLATES / "ad-ssh.conf").read_text()
        for old, new in (("@BE_SSH_IPV4@", "127.0.0.1"), ("Port 22", f"Port {ssh_port}"),
                         ("/etc/metainc/naver-erp-tunnel/id_ed25519", str(client)),
                         ("/etc/metainc/naver-erp-tunnel/known_hosts", str(known)),
                         ("/run/metainc-naver-erp-tunnel/erp.sock", str(socket_path))):
            rendered = rendered.replace(old, new)
        write(client_config, rendered)
        client_args = ["ssh", "-F", str(client_config)]
        forward = subprocess.Popen(client_args + ["-N", "-T", ACCOUNT], group=10001,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        processes.append(forward)
        end = time.monotonic() + timeout()
        while not socket_path.exists() and time.monotonic() < end and forward.poll() is None:
            time.sleep(0.03)
        check(socket_path.exists() and forward.poll() is None)
        info = socket_path.lstat()
        check(stat.S_ISSOCK(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o660 and info.st_uid == 0 and info.st_gid == 10001)

        stage("four-routes-and-header-normalization")
        targets = ("/api/ad-sync/contracts?stage=%EC%A7%84%ED%96%89%EC%A4%91&has_contract=true",
                   "/api/ad-sync/org-snapshot", "/api/ad-sync/naver-customer-ids", "/api/sso/exchange")
        for target in targets:
            method = "POST" if target.endswith("exchange") else "GET"
            status, payload = request(socket_path, method, target, b"{}" if method == "POST" else None,
                                      {"Content-Type": "application/json", "X-Api-Key": "d" * 64,
                                       "X-Sso-Client-Key": "e" * 64, "X-Metainc-Naver-Ingress": "0",
                                       "Host": "untrusted.invalid", "User-Agent": "Mozilla/5.0",
                                       "Authorization": "Bearer synthetic", "Cookie": "synthetic=value",
                                       "Referer": "https://untrusted.invalid/", "Forwarded": "for=127.0.0.1",
                                       "X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1",
                                       "X-Forwarded-Proto": "https", "X-Unknown": "synthetic"})
            check(status == 200)
            value = json.loads(payload)
            check(value["method"] == method and value["target"] == target)
            headers = value["headers"]
            check(headers["host"] == "api.metainc.co.kr" and headers["x-metainc-naver-ingress"] == "1")
            check(headers["user-agent"] == "Python-urllib/3 NaverControl")
            check(not set(headers).intersection({"authorization", "cookie", "referer", "forwarded", "x-forwarded-for",
                                                   "x-real-ip", "x-forwarded-proto", "x-unknown"}))
        calls = Fixture.calls
        for method, target in [(method, path) for method in ("HEAD", "OPTIONS", "DELETE", "PUT", "TRACE", "CONNECT")
                               for path in targets] + [("POST", targets[1]), ("GET", targets[3]),
                               ("GET", "/api/ad-sync/%6frg-snapshot"), ("GET", "/api//ad-sync/org-snapshot"),
                               ("GET", "/api/ad-sync/contracts/../org-snapshot"), ("GET", targets[1] + "?x=y"),
                               ("GET", "/api/ad-sync/naver-alerts"), ("POST", targets[3] + "?x=y")]:
            check(request(socket_path, method, target)[0] in {400, 404, 405})
        check(request(socket_path, "POST", targets[3], b"x" * 1025)[0] == 413)
        check(request(socket_path, "GET", targets[1], b"x")[0] == 400)
        check(Fixture.calls == calls)

        stage("unprivileged-adapter-and-private-key-boundary")
        script = ("import os,sys,urllib.request; sys.path.insert(0,sys.argv[1]); "
                  "from naver_runtime.erp_tunnel_transport import ErpTunnelTransport; "
                  "assert not os.access(sys.argv[3],os.R_OK); "
                  "r=urllib.request.Request('http://api.metainc.co.kr/api/ad-sync/org-snapshot',"
                  "headers={'Accept':'application/json','X-Api-Key':'d'*64}); "
                  "assert ErpTunnelTransport(sys.argv[2]).send(r,3)[0]==200")
        run([sys.executable, "-c", script, str(ROOT), str(socket_path), str(client)],
            user=10001, group=10001, extra_groups=[])

        stage("ssh-denials")
        probe = client_args + ["-v", "-o", "ClearAllForwardings=yes", "-o", "SessionType=default", "-T"]
        for name, args in (("exec", [ACCOUNT, "id"]), ("sftp", ["-s", ACCOUNT, "sftp"])):
            stage("ssh-denial-" + name)
            refused = run(probe + args, data=b"", expected=None)
            # MaxSessions=0 can report "open failed" rather than "administratively prohibited".
            # Authentication must have succeeded; a bad key/host error is not denial evidence.
            check(refused.returncode == 255 and b"Authenticated to " in refused.stderr
                  and b"channel 0: open failed:" in refused.stderr)
        for destination in (f"127.0.0.1:{fixture.server_port}", "localhost:18081", "127.0.0.1:22"):
            stage("ssh-denial-other-destination")
            refused = run(client_args + ["-o", "ClearAllForwardings=yes", "-W", destination, ACCOUNT],
                          data=b"GET / HTTP/1.1\r\nHost: fixture\r\n\r\n", expected=None)
            check(refused.returncode == 255 and b"administratively prohibited" in refused.stderr)
        # ClearAllForwardings=yes는 command line의 -R까지 지우므로 이 probe에서는 쓰지 않는다.
        remote_config = root / "ssh-remote-probe.conf"
        write(remote_config, "\n".join(line for line in rendered.splitlines()
                                        if not line.strip().startswith("LocalForward ")) + "\n")
        stage("ssh-denial-remote-forward")
        refused = run(["ssh", "-F", str(remote_config), "-o", "ExitOnForwardFailure=yes",
                      "-R", "127.0.0.1:19081:127.0.0.1:18081", "-N", "-T", ACCOUNT], expected=None)
        check(refused.returncode == 255 and b"remote port forwarding failed" in refused.stderr)
        # 정상 소켓이 같은 정책에서 계속 동작해야 인증/연결 실패를 권한 거절로 오인하지 않는다.
        check(request(socket_path, "GET", targets[1])[0] == 200)
    finally:
        fixture.shutdown()
        fixture.server_close()


def stop_processes(processes):
    failed = False
    for process in reversed(processes):
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except Exception:
            failed = True
    processes.clear()
    return not failed


def main():
    global DEADLINE
    processes, created, armed, succeeded = [], False, False, False
    started = time.monotonic()
    DEADLINE = started + 150
    try:
        container_guard()
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Refused()))
        signal.alarm(165)
        armed = True
        stage("isolated-account")
        run(["useradd", "--system", "--user-group", "--no-create-home", "--home-dir", "/nonexistent",
             "--shell", "/usr/sbin/nologin", ACCOUNT])
        created = True
        # StrictModes가 world-writable /tmp 조상 경로의 authorized_keys를 거절할 수 있어
        # root-owned /run 아래 새 전용 트리만 사용한다(guard를 통과한 일회용 container).
        with tempfile.TemporaryDirectory(prefix="naver-tunnel-native-", dir="/run") as directory:
            try:
                exercise(Path(directory), processes)
            finally:
                check(stop_processes(processes))
        succeeded = True
    except Exception:
        succeeded = False
    finally:
        if not stop_processes(processes):
            succeeded = False
        if created:
            try:
                result = subprocess.run(["userdel", ACCOUNT], stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=3)
                succeeded = succeeded and result.returncode == 0
            except Exception:
                succeeded = False
        if armed:
            signal.alarm(0)
    if succeeded:
        print(json.dumps({"ok": True, "checks": CHECKS, "credentials": "synthetic-only",
                          "network": "loopback-only", "elapsed_seconds": round(time.monotonic() - started, 2)}))
        return 0
    print(json.dumps({"ok": False, "stage": STAGE, "error": "native-check-refused"}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
