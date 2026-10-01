"""배포하지 않는 템플릿 정책 시험. 실서버/실제 키/외부 연결을 사용하지 않는다."""
from pathlib import Path
import configparser
import re
import shlex
import shutil
import subprocess
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
PATHS = ("/api/ad-sync/contracts", "/api/ad-sync/org-snapshot",
         "/api/ad-sync/naver-customer-ids", "/api/sso/exchange")


def nginx_nodes(source):
    lexer = shlex.shlex(source, posix=True, punctuation_chars="{};")
    lexer.whitespace_split = True
    tokens = iter(lexer)

    def block(nested=False):
        nodes, words = [], []
        for token in tokens:
            if token == ";":
                if not words:
                    raise ValueError("empty directive")
                nodes.append((tuple(words), None))
                words = []
            elif token == "{":
                nodes.append((tuple(words), block(True)))
                words = []
            elif token == "}":
                if words or not nested:
                    raise ValueError("unexpected brace")
                return nodes
            elif any(char in token for char in "{};"):
                raise ValueError("unsupported syntax")
            else:
                words.append(token)
        if nested or words:
            raise ValueError("incomplete directive")
        return nodes
    return block()


class PolicyTests(unittest.TestCase):
    def test_ad_forwarder_uses_only_private_host_runtime(self):
        unit = configparser.ConfigParser(interpolation=None, strict=True)
        unit.optionxform = str
        unit.read_string((ROOT / "ad-tunnel.service").read_text())
        service = dict(unit["Service"])
        expected = {
            "Type": "simple", "User": "root", "Group": "10001", "UMask": "0077",
            "RuntimeDirectory": "metainc-naver-erp-tunnel", "RuntimeDirectoryMode": "0750",
            "RuntimeDirectoryPreserve": "yes",
            "ExecStart": "/usr/bin/ssh -F /etc/metainc/naver-erp-tunnel/ssh_config -N -T naver-erp-tunnel",
            "Restart": "on-failure", "RestartSec": "10s", "TimeoutStopSec": "15s",
            "KillMode": "control-group", "NoNewPrivileges": "yes", "ProtectSystem": "strict",
            "ProtectHome": "yes", "PrivateTmp": "yes", "PrivateDevices": "yes",
            "CapabilityBoundingSet": "", "AmbientCapabilities": "",
            "RestrictAddressFamilies": "AF_UNIX AF_INET", "RestrictSUIDSGID": "yes",
            "LockPersonality": "yes", "ReadWritePaths": "/run/metainc-naver-erp-tunnel",
            "IPAddressDeny": "any", "IPAddressAllow": "@BE_SSH_IPV4@",
            "StandardOutput": "null", "StandardError": "null",
        }
        self.assertEqual(service, expected)
        self.assertEqual(set(unit.sections()), {"Unit", "Service", "Install"})
        self.assertEqual(dict(unit["Unit"]), {
            "Description": "Naver ERP isolated SSH forwarder (candidate only)",
            "Wants": "network-online.target", "After": "network-online.target",
            "StartLimitIntervalSec": "120s", "StartLimitBurst": "3",
        })
        self.assertEqual(dict(unit["Install"]), {"WantedBy": "multi-user.target"})

    def test_ad_ssh_client_has_one_unix_forward_no_agent_or_ambient_configuration(self):
        lines = [shlex.split(line, comments=True) for line in (ROOT / "ad-ssh.conf").read_text().splitlines()]
        lines = [line for line in lines if line]
        self.assertEqual(lines[0], ["Host", "naver-erp-tunnel"])
        expected = {
            "HostName": "@BE_SSH_IPV4@", "Port": "22", "User": "naver-erp-tunnel",
            "AddressFamily": "inet", "CanonicalizeHostname": "no",
            "BatchMode": "yes", "IdentitiesOnly": "yes", "IdentityAgent": "none",
            "IdentityFile": "/etc/metainc/naver-erp-tunnel/id_ed25519",
            "PubkeyAcceptedAlgorithms": "ssh-ed25519", "HostKeyAlgorithms": "ecdsa-sha2-nistp256",
            "UserKnownHostsFile": "/etc/metainc/naver-erp-tunnel/known_hosts",
            "GlobalKnownHostsFile": "/dev/null", "KnownHostsCommand": "none",
            "StrictHostKeyChecking": "yes", "UpdateHostKeys": "no", "VerifyHostKeyDNS": "no",
            "PasswordAuthentication": "no", "KbdInteractiveAuthentication": "no",
            "PreferredAuthentications": "publickey", "ForwardAgent": "no", "ForwardX11": "no",
            "PermitLocalCommand": "no", "ProxyCommand": "none", "ProxyJump": "none",
            "ControlMaster": "no", "ControlPath": "none", "ControlPersist": "no",
            "RequestTTY": "no", "SessionType": "none", "StdinNull": "yes",
            "ConnectTimeout": "10", "ConnectionAttempts": "1", "ExitOnForwardFailure": "yes",
            "ServerAliveInterval": "15", "ServerAliveCountMax": "2", "TCPKeepAlive": "no",
            "StreamLocalBindMask": "0117", "StreamLocalBindUnlink": "no", "LogLevel": "ERROR",
            "LocalForward": "/run/metainc-naver-erp-tunnel/erp.sock 127.0.0.1:18081",
        }
        self.assertEqual(len(lines[1:]), len(expected))
        self.assertEqual({line[0]: " ".join(line[1:]) for line in lines[1:]}, expected)

    @unittest.skipUnless(shutil.which("ssh"), "오프라인 ssh -G 파서가 없습니다")
    def test_native_ssh_config_expansion_does_not_connect(self):
        # RFC 5737 문서용 주소. -G는 config 평가만 하고 연결·키 로드 전에 종료한다.
        candidate = (ROOT / "ad-ssh.conf").read_text().replace("@BE_SSH_IPV4@", "192.0.2.44")
        result = subprocess.run([shutil.which("ssh"), "-G", "-F", "/dev/stdin", "naver-erp-tunnel"],
                                input=candidate, text=True, capture_output=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, "SSH 설정 평가 실패")
        values = dict(line.split(" ", 1) for line in result.stdout.splitlines())
        self.assertEqual(values["hostname"], "192.0.2.44")
        self.assertEqual(values["user"], "naver-erp-tunnel")
        self.assertEqual(values["localforward"], "/run/metainc-naver-erp-tunnel/erp.sock [127.0.0.1]:18081")
        self.assertEqual(values["stricthostkeychecking"], "true")
        self.assertEqual(values["identityagent"], "none")
        self.assertEqual(values["sessiontype"], "none")
        self.assertNotIn("remoteforward", values)
        self.assertNotIn("dynamicforward", values)

    def test_native_harness_rejects_host_before_account_or_key_creation(self):
        import os
        import sys
        import json
        # 표준 env를 넘기되 명시 컨테이너 승인 flag는 제거하므로 Docker 안에서도 거절만 검증한다.
        environment = dict(os.environ)
        environment.pop("NAVER_TUNNEL_NATIVE_CI", None)
        result = subprocess.run([sys.executable, str(ROOT.parents[1] / "tools/naver-tunnel-native-ci.py")],
                                env=environment, capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr), {"ok": False, "stage": "container-guard", "error": "native-check-refused"})

    def test_ssh_account_can_only_forward_to_fixed_ingress_and_has_no_sessions(self):
        lines = [shlex.split(line, comments=True) for line in (ROOT / "be-sshd.conf").read_text().splitlines()]
        lines = [line for line in lines if line]
        self.assertEqual(lines[0], ["Match", "User", "naver-erp-tunnel"])
        self.assertEqual(lines[-1], ["Match", "all"])
        expected = {
            "AuthenticationMethods": "publickey", "PubkeyAuthentication": "yes",
            "PubkeyAcceptedAlgorithms": "ssh-ed25519", "PasswordAuthentication": "no",
            "KbdInteractiveAuthentication": "no", "HostbasedAuthentication": "no",
            "AuthorizedKeysFile": "/etc/ssh/authorized_keys/naver-erp-tunnel",
            "AuthorizedKeysCommand": "none", "TrustedUserCAKeys": "none",
            "MaxSessions": "0", "PermitTTY": "no", "PermitUserRC": "no",
            "AllowAgentForwarding": "no", "X11Forwarding": "no", "PermitTunnel": "no",
            "AllowTcpForwarding": "local", "PermitOpen": "127.0.0.1:18081",
            "PermitListen": "none", "AllowStreamLocalForwarding": "no", "GatewayPorts": "no",
        }
        self.assertEqual(len(lines[1:-1]), len(expected))
        self.assertEqual(dict(lines[1:-1]), expected)
        key = (ROOT / "authorized_keys.template").read_text().strip()
        self.assertEqual(key, 'restrict,port-forwarding,from="@AD_EGRESS_IPV4@",permitopen="127.0.0.1:18081" '
                             'ssh-ed25519 @NEW_TUNNEL_PUBLIC_KEY_BASE64@ naver-erp-tunnel')

    def test_ingress_replaces_trust_headers_and_never_logs_or_caches_payload(self):
        nodes = nginx_nodes((ROOT / "be-nginx.conf").read_text())
        server = next(c for w, c in nodes if w == ("server",))
        headers = {w[1]: w[2] for w, c in server if w[0] == "proxy_set_header"}
        self.assertEqual(len([w for w, c in server if w[0] == "proxy_set_header"]), len(headers))
        self.assertEqual(headers, {
            "Host": "api.metainc.co.kr", "Connection": "close", "Accept": "application/json",
            "User-Agent": "Python-urllib/3 NaverControl", "X-Metainc-Naver-Ingress": "1",
            "X-Api-Key": "$http_x_api_key", "X-Sso-Client-Key": "$http_x_sso_client_key",
            "Content-Type": "$http_content_type", "Content-Length": "$content_length",
            "Forwarded": "", "X-Forwarded-For": "", "X-Forwarded-Proto": "", "X-Real-IP": "",
            "Authorization": "", "Cookie": "", "Referer": "",
        })
        required = {
            ("proxy_pass_request_headers", "off"), ("access_log", "off"), ("error_log", "/dev/null"),
            ("proxy_cache", "off"), ("proxy_buffering", "off"), ("proxy_max_temp_file_size", "0"),
            ("client_max_body_size", "1k"), ("client_body_buffer_size", "2k"),
            ("client_body_timeout", "8s"), ("client_header_timeout", "8s"), ("send_timeout", "30s"),
            ("proxy_connect_timeout", "3s"), ("proxy_send_timeout", "8s"), ("proxy_read_timeout", "30s"),
            ("proxy_next_upstream", "off"), ("proxy_request_buffering", "on"),
            ("proxy_http_version", "1.1"), ("gzip", "off"),
        }
        additional = {("listen", "127.0.0.1:18081", "default_server"), ("server_name", "_"),
                      ("client_header_buffer_size", "2k"), ("large_client_header_buffers", "2", "2k"),
                      ("keepalive_timeout", "0")}
        directives = [w for w, c in server if c is None and w[0] != "proxy_set_header"]
        self.assertEqual(set(directives), required | additional)
        self.assertEqual(len(directives), len(set(directives)))
        # location에서 한 header만 재정의해도 server의 header whitelist 상속이 모두 사라진다.
        for w, children in server:
            if w[0] == "location":
                self.assertFalse(any(item[0][0] == "proxy_set_header" for item in children))

    def test_ingress_rejects_other_methods_queries_and_body_framing(self):
        nodes = nginx_nodes((ROOT / "be-nginx.conf").read_text())
        maps = {words[2]: children for words, children in nodes if words[0] == "map"}
        self.assertEqual([w for w, c in nodes], [
            ("map", "$request_method:$request_uri", "$naver_erp_route"),
            ("map", "$request_method:$http_content_length:$http_transfer_encoding", "$naver_erp_framing"),
            ("server",),
        ])
        self.assertEqual(set(maps), {"$naver_erp_route", "$naver_erp_framing"})

        def accepts(name, value):
            entries = maps[name]
            self.assertIn((("default", "0"), None), entries)
            for (pattern, result), child in entries:
                self.assertIsNone(child)
                if pattern == value or (pattern.startswith("~") and re.fullmatch(pattern[1:], value)):
                    return result == "1"
            return False

        for value in ("GET:/api/ad-sync/contracts?stage=%EC%A7%84%ED%96%89+%EC%A4%91&has_contract=true",
                      "GET:" + PATHS[1], "GET:" + PATHS[2], "POST:" + PATHS[3]):
            self.assertTrue(accepts("$naver_erp_route", value), value)
        for method in ("HEAD", "OPTIONS", "DELETE", "PUT", "PATCH", "CONNECT", "TRACE"):
            for path in PATHS:
                self.assertFalse(accepts("$naver_erp_route", method + ":" + path))
        for value in ("POST:" + PATHS[1], "GET:" + PATHS[3], "POST:" + PATHS[3] + "?destination=LOGIC",
                      "GET:/api/ad-sync/contracts?stage=a&has_contract=false",
                      "GET:/api/ad-sync/contracts?stage=a&has_contract=true&extra=a",
                      "GET:/api/ad-sync/contracts/../org-snapshot", "GET:/api//ad-sync/org-snapshot",
                      "GET:/api/ad-sync/%6frg-snapshot", "GET:/api/ad-sync/org-snapshot/",
                      "GET:/api/ad-sync/naver-alerts", "GET:/api/ad-sync/org-snapshot?x=y"):
            self.assertFalse(accepts("$naver_erp_route", value), value)
        for value in ("GET::", "GET:0:", "POST:140:", "POST:1024:"):
            self.assertTrue(accepts("$naver_erp_framing", value))
        for value in ("GET:1:", "GET::chunked", "POST::chunked", "POST:1:chunked", "POST:0:", "POST:1,1:"):
            self.assertFalse(accepts("$naver_erp_framing", value))
        server = next(c for w, c in nodes if w == ("server",))
        for name in maps:
            self.assertIn((("if", "(" + name, "=", "0)"), [(("return", "400"), None)]), server)

    def test_loopback_ingress_has_only_four_exact_routes_and_active_upstream(self):
        nodes = nginx_nodes((ROOT / "be-nginx.conf").read_text())
        servers = [children for words, children in nodes if words == ("server",)]
        self.assertEqual(len(servers), 1)
        server = servers[0]
        self.assertEqual([w for w, _ in server if w[0] == "listen"],
                         [("listen", "127.0.0.1:18081", "default_server")])
        locations = {words: children for words, children in server if words[0] == "location"}
        self.assertEqual(len([w for w, c in server if w[0] == "location"]), len(locations))
        self.assertEqual(set(locations), {("location", "=", path) for path in PATHS} | {("location", "/")})
        for path in PATHS:
            self.assertIn((("proxy_pass", "http://sales_be_up"), None), locations[("location", "=", path)])
        self.assertEqual(locations[("location", "/")], [(("return", "404"), None)])

    def test_mutant_policy_expansions_fail_closed(self):
        mutants = (
            ("be-nginx.conf", "127.0.0.1:18081", "0.0.0.0:18081", "test_loopback_ingress_has_only_four_exact_routes_and_active_upstream"),
            ("be-nginx.conf", "http://sales_be_up", "http://127.0.0.1:6060", "test_loopback_ingress_has_only_four_exact_routes_and_active_upstream"),
            ("be-nginx.conf", "X-Metainc-Naver-Ingress 1", "X-Metainc-Naver-Ingress $http_x_metainc_naver_ingress", "test_ingress_replaces_trust_headers_and_never_logs_or_caches_payload"),
            ("be-nginx.conf", "proxy_pass_request_headers off", "proxy_pass_request_headers on", "test_ingress_replaces_trust_headers_and_never_logs_or_caches_payload"),
            ("be-nginx.conf", "access_log off", "access_log /tmp/requests.log", "test_ingress_replaces_trust_headers_and_never_logs_or_caches_payload"),
            ("be-nginx.conf", "proxy_set_header Cookie \"\";", "proxy_set_header Cookie \"\";\n    proxy_set_header Cookie $http_cookie;", "test_ingress_replaces_trust_headers_and_never_logs_or_caches_payload"),
            ("be-sshd.conf", "MaxSessions 0", "MaxSessions 1", "test_ssh_account_can_only_forward_to_fixed_ingress_and_has_no_sessions"),
            ("be-sshd.conf", "PermitOpen 127.0.0.1:18081", "PermitOpen any", "test_ssh_account_can_only_forward_to_fixed_ingress_and_has_no_sessions"),
            ("be-sshd.conf", "AllowTcpForwarding local", "AllowTcpForwarding yes", "test_ssh_account_can_only_forward_to_fixed_ingress_and_has_no_sessions"),
            ("be-sshd.conf", "Match User naver-erp-tunnel", "Match all", "test_ssh_account_can_only_forward_to_fixed_ingress_and_has_no_sessions"),
            ("ad-ssh.conf", "StrictHostKeyChecking yes", "StrictHostKeyChecking no", "test_ad_ssh_client_has_one_unix_forward_no_agent_or_ambient_configuration"),
            ("ad-ssh.conf", "IdentityAgent none", "IdentityAgent SSH_AUTH_SOCK", "test_ad_ssh_client_has_one_unix_forward_no_agent_or_ambient_configuration"),
            ("ad-ssh.conf", "StreamLocalBindUnlink no", "StreamLocalBindUnlink yes", "test_ad_ssh_client_has_one_unix_forward_no_agent_or_ambient_configuration"),
            ("ad-tunnel.service", "RuntimeDirectoryMode=0750", "RuntimeDirectoryMode=0777", "test_ad_forwarder_uses_only_private_host_runtime"),
            ("ad-tunnel.service", "RuntimeDirectoryPreserve=yes", "RuntimeDirectoryPreserve=no", "test_ad_forwarder_uses_only_private_host_runtime"),
            ("ad-tunnel.service", "StandardError=null", "StandardError=journal", "test_ad_forwarder_uses_only_private_host_runtime"),
        )
        read_text = Path.read_text
        for name, before, after, check in mutants:
            original = read_text(ROOT / name)
            self.assertIn(before, original)
            changed = original.replace(before, after)
            def read(path, *args, **kwargs):
                return changed if path == ROOT / name else read_text(path, *args, **kwargs)
            with self.subTest(name=name, mutation=before), patch.object(Path, "read_text", read):
                with self.assertRaises(AssertionError):
                    getattr(self, check)()


if __name__ == "__main__":
    unittest.main()
