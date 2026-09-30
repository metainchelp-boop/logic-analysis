"""코어 관문을 넓히지 않고 실행 외피의 추가 OS 기능만 좁게 허용한다."""
import ast
from pathlib import Path
from unittest import TestCase

ROOT = Path(__file__).resolve().parents[1]
NETWORK = {"socket", "socketserver", "wsgiref", "urllib", "http", "requests", "httpx", "aiohttp",
           "ssl", "asyncio", "subprocess", "paramiko", "ftplib", "smtplib"}


class RuntimeGuardTest(TestCase):
    def test_only_unix_server_and_backup_transport_own_network_os_imports(self):
        allow = {"server.py": {"socket", "socketserver", "wsgiref"}, "backup_transport.py": {"subprocess"}}
        for path in ROOT.glob("*.py"):
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
