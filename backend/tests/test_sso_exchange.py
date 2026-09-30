"""전산 교환 경계 시험. 외부 통신·운영 DB 없음."""
import json
import pathlib
import sys
import unittest
import importlib.util
import os
import subprocess
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import sso_exchange as X

CODE, VERIFIER, KEY = 'C' * 42 + 'A', 'V' * 42 + 'A', '0123456789abcdef' * 4


class ExchangeTest(unittest.TestCase):
    def exchange(self, status=200, body=None, env=None):
        calls = []
        def send(req, timeout):
            calls.append(req)
            self.assertEqual(timeout, 8)
            return status, json.dumps(body if body is not None else {'status':200,'result':{'id':'user','name':'Example'}}).encode()
        out = X.exchange(CODE, VERIFIER, env={'SSO_AD_CENTER_CLIENT_KEY':KEY} if env is None else env, send=send)
        return out, calls

    def test_exact_authenticated_destination_and_verifier(self):
        (kind, result), calls = self.exchange()
        self.assertEqual(kind, 'ok'); self.assertEqual(result['id'], 'user')
        req=calls[0]
        self.assertEqual(req.full_url,'https://api.metainc.co.kr/api/sso/exchange')
        self.assertEqual(req.get_method(),'POST')
        self.assertEqual(req.get_header('X-sso-client-key'),KEY)
        self.assertEqual(json.loads(req.data),{'destination':'AD_CENTER','code':CODE,'codeVerifier':VERIFIER})

    def test_missing_key_never_sends(self):
        (kind,_), calls=self.exchange(env={})
        self.assertEqual(kind,'outage'); self.assertEqual(calls,[])

    def test_rejection_never_creates_profile(self):
        for status in (401,403):
            (kind,result),_=self.exchange(status)
            self.assertEqual(kind,'rejected'); self.assertIsNone(result)

    def test_redirect_and_malformed_are_outages(self):
        for status,body in ((302,{}),(503,{}),(200,{'result':{}}),(200,{'status':401,'result':{'id':'u'}})):
            (kind,result),_=self.exchange(status,body)
            self.assertEqual(kind,'outage'); self.assertIsNone(result)

    def test_bad_input_never_sends(self):
        for value in ('', 'x', 'x'*44, 'a.b.c', None, 123, 'x'*42+'\n'):
            calls=[]
            kind,_=X.exchange(value,VERIFIER,env={'SSO_AD_CENTER_CLIENT_KEY':KEY},send=lambda *a:calls.append(a))
            self.assertEqual(kind,'rejected'); self.assertEqual(calls,[])


class RouteTest(unittest.TestCase):
    def test_real_router_role_replay_and_legacy_in_temporary_database(self):
        missing=[m for m in ('fastapi','httpx','sqlalchemy','jose','passlib','cryptography') if not importlib.util.find_spec(m)]
        if missing:
            if os.environ.get('NAVER_RELAY_REQUIRE_APP')=='1': self.fail('앱 의존성이 없습니다')
            self.skipTest('앱 의존성이 없습니다')
        with tempfile.TemporaryDirectory(prefix='s16-ad-test-') as folder:
            env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','TMPDIR')}
            env.update(DB_PATH=folder+'/test.db',FERNET_KEY_FILE=folder+'/fernet.key',
                       JWT_SECRET='s16-isolated-only-'+('Q7m9Ap4x'*7),SSO_AD_CENTER_CLIENT_KEY=KEY,
                       PYTHONDONTWRITEBYTECODE='1')
            result=subprocess.run([sys.executable,str(pathlib.Path(__file__).with_name('sso_code_harness.py'))],
                                  env=env,cwd=folder,capture_output=True,text=True,timeout=40)
            self.assertEqual(result.returncode,0,result.stderr[-2000:])
            out=json.loads(result.stdout)
            self.assertEqual(out,{'created':200,'role':'staff','cache':'no-store','replay':401,
                'admin_preserved':'admin','viewer':'viewer','cross_origin':403,'bad_shape':400,
                'no_echo':True,'too_big':413,'legacy':200})


if __name__ == '__main__': unittest.main()
