"""관제 전용 ASGI 진입점: 기존 광고센터 앱·DB·수집기를 가져오지 않는다."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import socket
import tempfile
import time
import unittest
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]


class NaverEntryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.added_path = str(BACKEND) not in sys.path
        if cls.added_path:
            sys.path.insert(0, str(BACKEND))

    @classmethod
    def tearDownClass(cls):
        if cls.added_path:
            sys.path.remove(str(BACKEND))

    def test_import_does_not_load_main_database_auth_or_collectors(self):
        # 새 인터프리터에서 import만으로 생기는 모듈을 확인한다. 운영 환경변수는 전달하지 않는다.
        code = """
import sys
from app.naver_entry import app
for name in sys.modules:
    assert not (name in {'app.main', 'app.auth', 'app.database', 'app.models'} or
                name.startswith(('app.collector', 'app.db', 'sqlalchemy'))), name
assert not app.router.on_startup and not app.router.on_shutdown
print('standalone-import-ok')
"""
        result = subprocess.run([sys.executable, '-c', code], cwd=BACKEND,
                                env={'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1'},
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'standalone-import-ok')

    def test_only_naver_routes_and_no_documentation(self):
        from fastapi.testclient import TestClient
        app = importlib.import_module('app.naver_entry').app
        with patch.dict(os.environ, {'NAVER_AUTO_WEB': 'on'}, clear=True), TestClient(app) as client:
            for path in ('/', '/api/health', '/api/login', '/docs', '/redoc', '/openapi.json', '/naver'):
                self.assertEqual(client.get(path, follow_redirects=False).status_code, 404, path)
            page = client.get('/naver/')
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.headers['cache-control'], 'no-store')
            self.assertEqual(page.headers['referrer-policy'], 'no-referrer')
            self.assertIn("connect-src 'self'", page.headers['content-security-policy'])
            self.assertEqual(client.head('/naver/').content, b'')
            self.assertEqual(client.get('/naver/sso-bootstrap.js').status_code, 200)
            self.assertEqual(client.get('/naver/README.md').status_code, 404)
            self.assertEqual(client.post('/naver/').status_code, 405)
            relay = client.get('/api/naver-auto/board')
            self.assertEqual(relay.status_code, 503)
            self.assertEqual(relay.json(), {'error': 'engine-unavailable'})

    def test_disabled_routes_are_absent(self):
        from fastapi.testclient import TestClient
        app = importlib.import_module('app.naver_entry').app
        with patch.dict(os.environ, {'NAVER_AUTO_WEB': 'off'}, clear=True), TestClient(app) as client:
            for path in ('/naver/', '/naver/sso-bootstrap.js', '/api/naver-auto/board'):
                for method in ('GET', 'HEAD', 'POST'):
                    self.assertEqual(client.request(method, path).status_code, 404, (method, path))

    def test_real_unix_listener_has_no_raw_access_log(self):
        # 실제 UDS 기동도 별도 임시 폴더와 비밀값 없는 환경에서만 한다.
        with tempfile.TemporaryDirectory(prefix='naver-entry-', dir='/tmp') as folder:
            path = str(Path(folder) / 'relay.sock')
            proc = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.naver_entry:app',
                                     '--uds', path, '--workers', '1', '--no-access-log',
                                     '--no-proxy-headers', '--no-server-header', '--lifespan', 'off',
                                     '--log-level', 'warning'], cwd=BACKEND,
                                    env={'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1',
                                         'NAVER_AUTO_WEB': 'on'}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while not Path(path).exists() and proc.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(Path(path).exists(), '전용 UNIX 소켓이 생성되어야 합니다.')
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                    conn.settimeout(3)
                    conn.connect(path)
                    conn.sendall(b'GET /naver/?sso_start=SYNTHETIC_QUERY_ONLY HTTP/1.1\r\n'
                                 b'Host: dashboard.metainc.co.kr\r\nConnection: close\r\n\r\n')
                    response = conn.recv(65536)
                    self.assertTrue(response.startswith(b'HTTP/1.1 200'), response[:40])
                    self.assertIn(b'referrer-policy: no-referrer', response.lower())
            finally:
                proc.terminate()
                stdout, stderr = proc.communicate(timeout=5)
            self.assertNotIn(b'SYNTHETIC_QUERY_ONLY', stdout + stderr)
            self.assertNotIn(b'Traceback', stderr)


if __name__ == '__main__':
    unittest.main()
