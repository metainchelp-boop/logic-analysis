"""운영 ERP/비밀값 없이 실제 인증 라우터와 임시 DB를 검사한다."""
import importlib
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SsoCodeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.db = str(Path(self.directory.name) / "auth.db")
        self.env = patch.dict(os.environ, {
            "DB_PATH": self.db, "JWT_SECRET_KEY": "local-test-signing-key-only-" * 2,
            "SSO_EXCHANGE_CLIENT_KEY": "a" * 64, "SSO_MANAGER_TEAMS": "관리팀",
        })
        self.env.start()
        self.auth = importlib.import_module("auth")
        self.db_patch = patch.object(self.auth, "DB_PATH", self.db)
        self.db_patch.start()
        with sqlite3.connect(self.db) as conn:
            conn.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
                    name TEXT DEFAULT '', role TEXT DEFAULT 'viewer', is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT '2026-09-30', updated_at TEXT DEFAULT '2026-09-30');
                CREATE TABLE login_logs (id INTEGER PRIMARY KEY, user_id INTEGER,
                    username TEXT, login_at TEXT, ip_address TEXT);
                INSERT INTO users(username,password_hash,name,role) VALUES
                    ('employee-test','unused-test-hash','기존 이름','viewer');
            """)
        self.app = FastAPI()
        self.app.include_router(self.auth.router)
        self.client = TestClient(self.app)
        self.profile = {"idx": 17, "id": "employee-test", "name": "직원", "isManager": False,
                        "authority": {"name": "영업"}, "teamList": [{"idx": 2, "parentIdx": None, "name": "영업팀"}]}
        self.calls = []
        self.exchange_status = 200
        self.exchange_body = None
        self.used_codes = set()
        self.erp_clock = 100
        self.erp_expiry = 160
        self.erp_destination = 'LOGIC_ANALYSIS'
        self.erp_challenge = base64.urlsafe_b64encode(hashlib.sha256(('V' * 43).encode()).digest()).decode().rstrip('=')

        def fake_send(session, prepared, **kwargs):
            self.calls.append((session, prepared, kwargs))
            response = requests.Response()
            response.status_code = self.exchange_status
            if prepared.url.endswith('/sso/exchange'):
                body = json.loads(prepared.body)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(body['codeVerifier'].encode()).digest()).decode().rstrip('=')
                if (self.erp_clock >= self.erp_expiry or body['destination'] != self.erp_destination
                        or body['code'] in self.used_codes or challenge != self.erp_challenge):
                    response.status_code = 401
                if response.status_code == 200:
                    self.used_codes.add(body['code'])
            response._content = json.dumps(self.exchange_body if self.exchange_body is not None else {"result": self.profile}).encode()
            return response

        self.transport = patch.object(requests.Session, "send", autospec=True, side_effect=fake_send)
        self.transport.start()

    def tearDown(self):
        self.transport.stop()
        self.client.close()
        self.db_patch.stop()
        self.env.stop()
        self.directory.cleanup()

    def post(self, **kwargs):
        return self.client.post("/api/auth/sso-code", json={"code": "C" * 43, "codeVerifier": "V" * 43},
                                headers={"Origin": "https://logic.metainc.co.kr", "Sec-Fetch-Site": "same-origin"}, **kwargs)

    def test_valid_exchange_keeps_existing_identity_and_local_session_contract(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["user"]["username"], "employee-test")
        self.assertEqual(result["user"]["name"], "기존 이름")
        self.assertEqual(result["user"]["role"], "viewer")
        self.assertNotIn("code", result)
        me = self.client.get("/api/auth/me", headers={"Authorization": "Bearer " + result["token"]})
        self.assertEqual(me.json(), result["user"])

    def test_new_employee_receives_existing_automatic_account_and_session(self):
        self.profile['id'] = 'new-employee-test'
        self.profile['teamList'] = [{'idx': 3, 'parentIdx': None, 'name': '관리팀'}]
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['user']['username'], 'new-employee-test')
        self.assertEqual(result['user']['role'], 'manager')
        self.assertTrue(result['token'])

    def test_new_exchange_passes_api_key_middleware_without_exposing_server_key(self):
        # 실제 미들웨어만 로드해 앱 lifespan/배치/운영 DB 초기화를 하지 않는다.
        source = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(source.read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ApiKeyAuthMiddleware']
        scope = {"BaseHTTPMiddleware": BaseHTTPMiddleware, "Request": object,
                 "JSONResponse": JSONResponse, "API_KEY": "separate-api-key", "AUTH_EXEMPT_PATHS": []}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), scope)
        self.app.add_middleware(scope['ApiKeyAuthMiddleware'])
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/auth/me').status_code, 401)

    def test_incomplete_identity_cannot_silently_downgrade_existing_manager(self):
        self.auth.update_user(1, role='manager')
        self.exchange_body = {'result': {'id': 'employee-test', 'name': '직원'}}
        response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('token', response.json())
        self.assertEqual(self.auth.get_user_by_username('employee-test')['role'], 'manager')

    def test_exchange_uses_fixed_destination_secure_transport_and_pkce_only(self):
        self.assertEqual(self.post().status_code, 200)
        session, request, kwargs = self.calls[0]
        self.assertFalse(session.trust_env)
        self.assertEqual(request.url, 'https://api.metainc.co.kr/api/sso/exchange')
        self.assertEqual(request.method, 'POST')
        self.assertEqual(json.loads(request.body), {'destination': 'LOGIC_ANALYSIS', 'code': 'C' * 43, 'codeVerifier': 'V' * 43})
        self.assertEqual(request.headers['X-Sso-Client-Key'], 'a' * 64)
        self.assertNotIn('Authorization', request.headers)
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['timeout'], (3, 8))
        self.assertEqual(kwargs['proxies'], {})
        self.assertEqual(len(self.calls), 1)

    def test_expired_code_does_not_create_session(self):
        self.erp_clock = 160
        response = self.post()
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get('cache-control'), 'no-store')

    def test_replay_does_not_create_second_session(self):
        self.assertEqual(self.post().status_code, 200)
        second = self.post()
        self.assertEqual(second.status_code, 401)
        self.assertNotIn('token', second.json())

    def test_other_destination_code_does_not_create_session(self):
        self.erp_destination = 'AD_CENTER'
        self.assertEqual(self.post().status_code, 401)

    def test_wrong_browser_verifier_does_not_create_session(self):
        self.erp_challenge = 'different-browser'
        self.assertEqual(self.post().status_code, 401)

    def test_missing_or_invalid_server_key_fails_closed_without_network(self):
        for value in ['', 'a' * 63, 'g' * 64, 'a' * 64 + '\n']:
            with self.subTest(length=len(value)), patch.dict(os.environ, {'SSO_EXCHANGE_CLIENT_KEY': value}):
                self.assertEqual(self.post().status_code, 503)
        self.assertEqual(self.calls, [])

    def test_wrong_origin_or_fetch_site_never_reaches_erp(self):
        for headers in [{}, {'Origin': 'null'}, {'Origin': 'https://evil.example'},
                        {'Origin': 'https://logic.metainc.co.kr', 'Sec-Fetch-Site': 'cross-site'}]:
            response = self.client.post('/api/auth/sso-code', json={'code': 'C' * 43, 'codeVerifier': 'V' * 43}, headers=headers)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, [])

    def test_redirect_error_and_timeout_do_not_retry_or_leak_credentials(self):
        for status in [301, 302, 307, 401, 500]:
            with self.subTest(status=status):
                self.exchange_status = status
                response = self.post()
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('token', response.json())
        self.assertEqual(len(self.calls), 5)
        self.transport.stop()
        with patch.object(requests.Session, 'send', side_effect=requests.Timeout('private-' + 'V' * 43)):
            response = self.post()
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('private', response.text)

    def test_roles_remain_existing_team_mapping_not_is_manager_flag(self):
        self.profile['isManager'] = True
        self.assertEqual(self.post().json()['user']['role'], 'viewer')
        self.used_codes.clear()
        self.profile['teamList'] = [{'idx': 3, 'parentIdx': None, 'name': '관리팀'}]
        self.assertEqual(self.post().json()['user']['role'], 'manager')
        for role in ['admin', 'superadmin']:
            self.used_codes.clear()
            self.auth.update_user(1, role=role)
            self.assertEqual(self.post().json()['user']['role'], role)

    def test_inactive_local_user_is_still_denied(self):
        self.auth.update_user(1, is_active=0)
        response = self.post()
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('token', response.json())

    def test_legacy_token_endpoint_remains_compatible(self):
        response = self.client.post('/api/auth/sso', json={'token': 'legacy-test-token'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['username'], 'employee-test')
        self.assertEqual(self.calls[0][1].headers['Authorization'], 'Bearer legacy-test-token')

    def test_invalid_code_verifier_and_extra_destination_never_reach_erp(self):
        for payload in [{'code': '', 'codeVerifier': 'V' * 43}, {'code': 'C' * 43},
                        {'code': 'C' * 43, 'codeVerifier': 'V' * 43, 'destination': 'AD_CENTER'}]:
            response = self.client.post('/api/auth/sso-code', json=payload, headers={'Origin': 'https://logic.metainc.co.kr'})
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
