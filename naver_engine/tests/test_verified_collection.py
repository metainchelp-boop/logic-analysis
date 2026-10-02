"""좁은 연결/조회 허용. 실제 공개 WSGI 경로, 합성 신원/저장소만 사용한다."""
import io
import json
import unittest
from datetime import timedelta

from naver_engine.tests import test_web as TW


class CollectionGateTest(unittest.TestCase):
    def test_enabled_mode_still_refuses_unapproved_routes_before_side_effects(self):
        def forbidden(*args):
            raise AssertionError('차단 경로에서 저장/외부 호출 금지')

        app = TW.WEB.App(open_read=forbidden, write=forbidden,
                         signer=TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET)), profiles=forbidden,
                         owner_verification=True, verified_linking=True)
        for path in ('/links/reject', '/links/revoke', '/links/preview', '/issues/1/ack',
                     '/settings/thresholds', '/holds/stages/confirm', '/bell/read-all', '/unknown'):
            status = []
            output = app({'REQUEST_METHOD': 'POST', 'PATH_INFO': TW.WEB.PREFIX + path,
                          'CONTENT_LENGTH': 'invalid', 'wsgi.input': io.BytesIO(b'')},
                         lambda s, h: status.append(int(s.split()[0])))
            self.assertEqual(status, [403])
            self.assertEqual(json.loads(b''.join(output)), {'error': 'verification-read-only'})


class VerifiedCollectionTest(TW.WebBase):
    def make_app(self, **kw):
        self.requests = []
        def request(actor):
            self.requests.append(actor)
            return {'id': 17, 'status': 'accepted', 'codes': []}
        return super().make_app(owner_verification=True, verified_linking=True,
                                request_collection=request,
                                collection_status=lambda: {'id': 17, 'status': 'accepted', 'codes': []}, **kw)

    def test_owner_can_request_but_staff_team_and_narrowed_cannot(self):
        self.assertTrue(self.get('/me', 0)[1]['verified_linking'])
        self.assertTrue(self.get('/me', 100)[1]['verified_linking'])
        for idx in (1, 100):
            self.assertEqual(self.post('/collection/request', idx, {})[0], 403)
            self.assertEqual(self.get('/collection/status', idx)[0], 403)
        self.assertEqual(self.call('POST', '/collection/request', self.token(0, narrowed=True), {})[0], 403)
        self.assertEqual(self.post('/collection/request', 0, {}),
                         (200, {'id': 17, 'status': 'accepted', 'codes': []}))
        self.assertEqual(self.requests, [0])

    def test_only_current_uncontested_explicit_rows_can_be_confirmed(self):
        rows = self.get('/links/pending', 0)[1]['rows']
        auto = next(r for r in rows if r['state'] == TW.S.PAIR_AUTO)
        candidate = next(r for r in rows if r['state'] == TW.S.PAIR_CANDIDATE)
        self.assertTrue(auto['can_confirm'])
        self.assertFalse(candidate['can_confirm'])
        self.assertEqual(self.post('/links/confirm', 100, {'refs': [auto['ref']]})[0], 404)
        before = self.st.link_decisions()
        self.assertEqual(self.post('/links/confirm', 0, {'refs': [candidate['ref']]})[0], 409)
        self.assertEqual(before, self.st.link_decisions())
        self.assertEqual(self.post('/links/confirm', 0, {'refs': [auto['ref']]})[0], 200)

    def test_demoted_requester_and_extra_request_fields_are_rejected(self):
        self.assertEqual(self.post('/collection/request', 0, {'target': 'all'})[0], 400)
        self.resign(0)
        self.assertEqual(self.post('/collection/request', 0, {})[0], 401)
        self.assertEqual(self.requests, [])

    def test_name_difference_requires_single_exact_ad_account_proof(self):
        erp = TW.TM.FakeErp([TW.E.NaverIdRow(14, TW.M.VENDOR_NAVER, str(TW.D))])
        TW.L.pair_links(erp, self.st, self.fc.now())
        row = next(r for r in self.get('/links/pending', 0)[1]['rows'] if r['code'] == 'name-different')
        self.assertTrue(row['can_confirm'])
        ad_no = next(a['ad_account_no'] for a in self.st.accounts() if a['customer_id'] == TW.D)
        before = self.st.link_decisions()
        for proof in (None, '1', str(TW.D), True):
            body = {'refs': [row['ref']]}
            if proof is not None:
                body['ad_account_no'] = proof
            self.assertEqual(self.post('/links/confirm', 0, body)[0], 409)
            self.assertEqual(before, self.st.link_decisions())
        self.assertEqual(self.post('/links/confirm', 0, {'refs': [row['ref']], 'ad_account_no': str(ad_no)})[0], 200)

    def test_changed_account_snapshot_refuses_old_pair_before_write(self):
        row = next(r for r in self.get('/links/pending', 0)[1]['rows'] if r['state'] == TW.S.PAIR_AUTO)
        self.st.record_accounts(TW.TM.kids(TW.A, TW.B, TW.C_, TW.D), self.fc.now())
        before = self.st.link_decisions()
        self.assertEqual(self.post('/links/confirm', 0, {'refs': [row['ref']]})[0], 409)
        self.assertEqual(before, self.st.link_decisions())

    def test_ended_contract_and_stale_org_cannot_confirm(self):
        row = next(r for r in self.get('/links/pending', 0)[1]['rows'] if r['state'] == TW.S.PAIR_AUTO)
        self.at(self.fc.now() + timedelta(days=2))
        self.assertEqual(self.post('/links/confirm', 0, {'refs': [row['ref']]})[0], 409)
        self.assertEqual(self.post('/collection/request', 0, {})[0], 409)


if __name__ == '__main__':
    unittest.main()
