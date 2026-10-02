"""코어 관문을 넓히지 않고 실행 외피의 추가 OS 기능만 좁게 허용한다."""
import ast
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
NETWORK = {"socket", "socketserver", "wsgiref", "urllib", "http", "requests", "httpx", "aiohttp",
           "ssl", "asyncio", "subprocess", "paramiko", "ftplib", "smtplib"}


class RuntimeGuardTest(TestCase):
    def assert_tunnel_network_seam(self, source):
        """이 전송기만의 좁은 예외. 변조 소스 시험에서도 같은 검사를 사용한다."""
        tree = ast.parse(source)
        imports = {
            "import base64", "import http.client", "import io", "import json", "import math",
            "import os", "from pathlib import Path", "import re", "import socket", "import stat",
            "import time", "import urllib.parse", "from __future__ import annotations",
            "from naver_engine import erp_profile as EP", "from naver_engine import erp_read as E",
            "from naver_engine.naver_read import MAX_BODY as _URLLIB_MAX_BODY",
        }
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.assertIn(ast.unparse(node), imports)
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        allowed_attrs = {
            "http": {"http.client", "http.client.HTTPResponse", "http.client.HTTPException"},
            "urllib": {"urllib.parse", "urllib.parse.urlsplit", "urllib.parse.parse_qsl", "urllib.parse.urlencode"},
            "os": {"os.fsencode", "os.geteuid", "os.lstat"},
            "socket": {"socket.socket", "socket.AF_UNIX", "socket.SOCK_STREAM"},
            "E": {"E.ERP_HOST", "E.ERP_SCHEME", "E.PATH_CONTRACTS", "E.PATH_ORG_SNAPSHOT", "E.PATH_NAVER_IDS", "E.PATH_ACCOUNT_CATALOG",
                  "E.KEY_MIN_LENGTH", "E.KEY_MAX_LENGTH", "E.MAX_BODY", "E.TIMEOUT",
                  "E.STAGE_SPELLINGS", "E.STAGE_SPELLINGS.values"},
            "EP": {"EP.ERP_SCHEME", "EP.PATH_EXCHANGE", "EP.MAX_BODY", "EP.TIMEOUT"},
        }
        creations, connections = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn(node.id, {"getattr", "setattr", "vars", "globals", "locals", "__builtins__",
                                           "eval", "exec", "compile", "__import__"})
                if node.id in allowed_attrs and isinstance(node.ctx, ast.Load):
                    self.assertIsInstance(parents[node], ast.Attribute, "전송 모듈 별칭/동적 전달 금지")
                    self.assertIs(parents[node].value, node)
            if not isinstance(node, ast.Attribute):
                continue
            expression = ast.unparse(node)
            root = expression.split(".", 1)[0]
            if root in allowed_attrs:
                self.assertIn(expression, allowed_attrs[root])
            self.assertNotIn(node.attr, {"__dict__", "__class__", "system", "popen", "execv", "execve", "posix_spawn"})
            if expression in {"http.client", "urllib.parse"}:
                self.assertIsInstance(parents[node], ast.Attribute, "HTTP/URL 모듈 별칭 금지")
                self.assertIs(parents[node].value, node)
            if expression == "http.client.HTTPResponse":
                call = parents[node]
                self.assertIsInstance(call, ast.Call)
                self.assertIs(call.func, node)
                self.assertEqual(ast.unparse(call), "http.client.HTTPResponse(_ResponseSocket(conn, deadline))")
            if expression == "socket.socket":
                call = parents[node]
                self.assertIsInstance(call, ast.Call)
                self.assertIs(call.func, node)
                self.assertEqual(ast.unparse(call), "socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)")
                owner = parents[call]
                self.assertIsInstance(owner, ast.withitem)
                self.assertEqual(ast.unparse(owner.optional_vars), "conn")
                creations.append(call)
            if node.attr in {"connect", "connect_ex"}:
                call = parents[node]
                self.assertIsInstance(call, ast.Call)
                self.assertIs(call.func, node)
                self.assertEqual(ast.unparse(call), "conn.connect(self._path)")
                connections.append(call)
        self.assertEqual(len(creations), 1)
        self.assertEqual(len(connections), 1)

    def test_tunnel_import_guard_rejects_real_source_mutants(self):
        source = (ROOT / "erp_tunnel_transport.py").read_text()
        for extra in ("import urllib.request", "import socket as net", "from socket import socket",
                      "from http.client import HTTPConnection", "import subprocess", "import importlib",
                      "import ctypes", "import requests", "from naver_engine.naver_read import UrllibTransport"):
            with self.subTest(extra=extra):
                with self.assertRaises(AssertionError):
                    self.assert_tunnel_network_seam(source + "\n" + extra + "\n")

    def test_tunnel_socket_guard_rejects_real_source_mutants(self):
        source = (ROOT / "erp_tunnel_transport.py").read_text()
        original = "socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)"
        replacements = (
            "socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
            "socket.socket(socket.AF_INET6, socket.SOCK_STREAM)",
            "socket.socket(2, socket.SOCK_STREAM)",
            "socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)",
            "socket.socket(socket.AF_UNIX)", "socket.socket()",
            "socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, fileno=3)",
            "socket.create_connection(('example.invalid', 80))",
            "socket.fromfd(3, socket.AF_UNIX, socket.SOCK_STREAM)",
        )
        mutants = [source.replace(original, replacement, 1) for replacement in replacements]
        mutants += [source.replace("conn.connect(self._path)", replacement, 1) for replacement in (
            "conn.connect(('127.0.0.1', 80))", "conn.connect_ex(('127.0.0.1', 80))",
            "conn.connect(self._path)\n                conn.connect(self._path)",
        )]
        mutants.append(source + "\nfactory = socket.socket\nfactory()\n")
        for index, mutant in enumerate(mutants):
            with self.subTest(case=index):
                self.assertNotEqual(source, mutant)
                with self.assertRaises(AssertionError):
                    self.assert_tunnel_network_seam(mutant)

    def test_tunnel_guard_rejects_dns_tcp_process_and_dynamic_bypass_mutants(self):
        source = (ROOT / "erp_tunnel_transport.py").read_text()
        for extra in (
            "socket.getaddrinfo('example.invalid', 80)", "socket.gethostbyname('example.invalid')",
            "socket.create_connection(('127.0.0.1', 80))", "http.client.HTTPConnection('example.invalid')",
            "http.client.HTTPSConnection('example.invalid')", "urllib.request.urlopen('http://example.invalid')",
            "os.system('test-only')", "os.popen('test-only')", "os.posix_spawn('/bin/sh', [], {})",
            "E.UrllibTransport().send(None, 1)", "EP.UrllibTransport().send(None, 1)",
            "EP.urllib.request.urlopen('http://example.invalid')",
            "getattr(socket, 'create_connection')(('127.0.0.1', 80))",
            "vars(socket)['create_connection'](('127.0.0.1', 80))",
            "socket.__dict__['create_connection'](('127.0.0.1', 80))",
            "__import__('subprocess').run(['test-only'])", "alias = socket\nalias.socket()",
            "alias = http.client\nalias.HTTPConnection('example.invalid')",
            "factory = http.client.HTTPResponse\nfactory(None)",
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(AssertionError):
                    self.assert_tunnel_network_seam(source + "\n" + extra + "\n")

    def test_only_unix_server_and_backup_transport_own_network_os_imports(self):
        allow = {"server.py": {"socket", "socketserver", "wsgiref"}, "backup_transport.py": {"subprocess"},
                 "erp_tunnel_transport.py": {"socket", "http", "urllib"}}
        for path in ROOT.glob("*.py"):
            if path.name == "erp_tunnel_transport.py":
                self.assert_tunnel_network_seam(path.read_text())
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                imports = []
                if isinstance(node, ast.Import):
                    imports = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = [node.module or ""]
                for name in imports:
                    base = name.split(".")[0]
                    if base in NETWORK:
                        self.assertIn(base, allow.get(path.name, set()), (path.name, name))
                    self.assertNotIn(base, {"sqlite3", "ctypes", "importlib"}, (path.name, name))
                    if name.startswith("app"):
                        self.fail("실행 외피에서 기존 광고 변경 어댑터를 직접 불러오면 안 됩니다")

    def test_no_secret_reveal_or_dynamic_execution(self):
        for path in ROOT.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call):
                    name = node.func.id if isinstance(node.func, ast.Name) else ""
                    self.assertNotIn(name, {"eval", "exec", "compile", "__import__"})
                    if name == "getattr":
                        self.assertEqual(path.name, "writer.py")
                    if isinstance(node.func, ast.Attribute):
                        self.assertNotIn(node.func.attr, {"reveal", "system", "popen"} if path.name != "__main__.py"
                                         else {"reveal", "popen"})

    def test_socket_only_uses_unix_family(self):
        tree = ast.parse((ROOT / "server.py").read_text())
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertIn("AF_UNIX", attrs)
        self.assertFalse(attrs & {"AF_INET", "AF_INET6", "create_connection"})
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "socket":
                self.assertIsInstance(node.args[0], ast.Attribute)
                self.assertEqual(node.args[0].attr, "AF_UNIX")
