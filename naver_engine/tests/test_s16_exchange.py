"""관제의 새 로그인 계약만 시험 — 네트워크 없는 가짜 전산."""
import json
import unittest
from naver_engine import erp_profile as EP
from naver_engine.credentials import Secret

CODE, VERIFIER, KEY = 'C'*43, 'V'*43, '0123456789abcdef'*4


class ExchangeTest(unittest.TestCase):
    def test_only_code_and_verifier_to_bound_https_destination(self):
        calls=[]
        class Transport:
            def send(self, req, timeout):
                calls.append(req)
                return 200, b'{"status":200,"result":{"idx":0,"isManager":false,"teamList":[]}}'
        reader=EP.ErpProfileReader(transport=Transport(), env={'SSO_NAVER_CONTROL_CLIENT_KEY':KEY})
        profile=reader.read_profile(EP.load_code(CODE),EP.load_code(VERIFIER))
        self.assertEqual(profile.idx,0)
        request=calls[0]
        self.assertEqual(request.full_url,'https://api.metainc.co.kr/api/sso/exchange')
        self.assertEqual(request.get_method(),'POST')
        self.assertEqual(request.get_header('X-sso-client-key'),KEY)
        self.assertEqual(json.loads(request.data),{'destination':'NAVER_CONTROL','code':CODE,'codeVerifier':VERIFIER})

    def test_no_key_means_no_network(self):
        class Transport:
            def send(self,*args): raise AssertionError('must not send')
        reader=EP.ErpProfileReader(transport=Transport(),env={})
        with self.assertRaises(EP.ProfileError) as error:
            reader.read_profile(EP.load_code(CODE),EP.load_code(VERIFIER))
        self.assertEqual(error.exception.kind,EP.KIND_UNAVAILABLE)

    def test_old_jwt_rejected(self):
        for old in ('a.b.c','Bearer '+CODE,'a'*44,'a'*42+'\n'):
            with self.assertRaises(EP.ProfileError): EP.load_code(old)

    def test_bad_verifier_does_not_leave_gate(self):
        reader=EP.ErpProfileReader(env={'SSO_NAVER_CONTROL_CLIENT_KEY':KEY})
        with self.assertRaises(EP.ProfileForbidden):
            reader._gate('POST',EP.PATH_EXCHANGE,EP.load_code(CODE),'raw')
        self.assertEqual(reader.calls,0)
