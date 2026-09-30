"""실행 이미지에서도 재사용하는 실제 Linux 무호출 기동·종료 시험."""
import http.client
import json
import os
from pathlib import Path
import platform
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest


@unittest.skipUnless(platform.system() == "Linux", "Linux 실제 실행·SQLite 잠금 검증")
class LinuxRuntimeTest(unittest.TestCase):
    def test_disabled_process_socket_health_and_clean_sigterm(self):
        with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as folder:
            root = Path(folder).resolve()
            data, shared = root / "data", root / "socket"
            data.mkdir(mode=0o700)
            shared.mkdir(mode=0o750)
            db, endpoint = data / "engine.db", shared / "engine.sock"
            # allowlist만 전달한다. CI 또는 개발 환경의 업무 키는 상속하지 않는다.
            env = {key: os.environ[key] for key in ("PATH", "PYTHONPATH", "LANG") if key in os.environ}
            env.update(NAVER_ENGINE_DB=str(db), NAVER_ENGINE_SOCKET=str(endpoint), PYTHONDONTWRITEBYTECODE="1")
            process = subprocess.Popen([sys.executable, "-m", "naver_runtime", "run"], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline, body = time.monotonic() + 10, None
                while time.monotonic() < deadline and process.poll() is None:
                    if endpoint.exists():
                        connection = http.client.HTTPConnection("localhost", timeout=1)
                        connection.sock = socket.socket(socket.AF_UNIX)
                        connection.sock.settimeout(1)
                        try:
                            connection.sock.connect(str(endpoint))
                            connection.request("GET", "/_engine/health")
                            response = connection.getresponse()
                            body = json.loads(response.read())
                            if body["state"] == "ok":
                                self.assertEqual(response.status, 200)
                                break
                        finally:
                            connection.close()
                    time.sleep(.05)
                self.assertIsNotNone(body)
                self.assertEqual(body["state"], "ok")
                self.assertFalse(any(body["switches"].values()))
                self.assertEqual(db.stat().st_mode & 0o777, 0o600)
                self.assertEqual(endpoint.stat().st_mode & 0o777, 0o660)
                process.send_signal(signal.SIGTERM)
                out, err = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, err.decode())
                self.assertEqual(out, b"")
                self.assertFalse(endpoint.exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)
