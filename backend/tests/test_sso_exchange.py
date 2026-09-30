"""전산 교환 경계 시험. 외부 통신·운영 DB 없음."""
import json
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app import sso_exchange as X

CODE, VERIFIER, KEY = 'C' * 43, 'V' * 43, '0123456789abcdef' * 4


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


if __name__ == '__main__': unittest.main()
