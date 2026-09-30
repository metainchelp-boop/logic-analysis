import http.client
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest

from naver_engine.web import TRUSTED_TRANSPORT
from naver_runtime.server import UnixServer, ServerError, health_app


def request(path, url="/_engine/health"):
    conn = http.client.HTTPConnection("local", timeout=3)
    conn.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.sock.settimeout(3)
    conn.sock.connect(str(path))
    try:
        conn.request("GET", url)
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


class ServerTest(unittest.TestCase):
    def test_unix_socket_has_trust_mark_private_mode_and_no_tcp_listener(self):
        with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as folder:
            path = Path(folder).resolve() / "engine.sock"
            seen = []
            health = health_app(lambda: {"state": "disabled"})
            def app(env, start):
                seen.append((env.get(TRUSTED_TRANSPORT), env.get("REMOTE_ADDR")))
                return health(env, start)
            with UnixServer(str(path), app):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o660)
                self.assertEqual(request(path), (200, {"state": "disabled"}))
                self.assertEqual(request(path, "/api/naver-auto/session")[0], 404)
            self.assertFalse(path.exists())
            self.assertEqual(seen, [(True, ""), (True, "")])

    def test_never_removes_a_regular_file_or_symlink(self):
        with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as folder:
            root = Path(folder).resolve()
            path = root / "engine.sock"
            path.write_text("do-not-remove")
            with self.assertRaises(ServerError):
                UnixServer(str(path), health_app(lambda: {}))
            self.assertEqual(path.read_text(), "do-not-remove")
            other = root / "other.sock"
            other.symlink_to(path)
            with self.assertRaises(ServerError):
                UnixServer(str(other), health_app(lambda: {}))
            self.assertTrue(other.is_symlink())

    def test_second_server_cannot_replace_first_and_stale_socket_recovers(self):
        with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as folder:
            path = Path(folder).resolve() / "engine.sock"
            with UnixServer(str(path), health_app(lambda: {"state": "disabled"})):
                inode = path.stat().st_ino
                with self.assertRaises((OSError, ServerError)):
                    UnixServer(str(path), health_app(lambda: {}))
                self.assertEqual(inode, path.stat().st_ino)
                self.assertEqual(request(path)[0], 200)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as stale:
                stale.bind(str(path))
            with UnixServer(str(path), health_app(lambda: {"state": "disabled"})):
                self.assertEqual(request(path)[0], 200)
