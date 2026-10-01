"""대표 검증판 — 실제 WSGI/저장소 경로, 합성 자료와 가짜 전산만 사용한다."""
from datetime import timedelta
import json
import unittest

from naver_engine.tests import test_web as TW


class OwnerRequestGateTest(unittest.TestCase):
    def test_all_business_and_unknown_requests_refused_before_any_side_effect(self):
        touched = []

        def forbidden(*args):
            touched.append(True)
            raise AssertionError("거절 요청은 저장소·감사·전산·미리보기를 부를 수 없습니다")

        class UnreadableBody:
            read = forbidden

        app = TW.WEB.App(open_read=forbidden, write=forbidden,
                         signer=TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET)),
                         profiles=forbidden, previewer=forbidden, owner_verification=True)
        paths = ["/issues/1/ack", "/issues/1/resolve", "/issues/1/except", "/links/confirm",
                 "/links/reject", "/links/revoke", "/links/preview", "/bell/1/read", "/bell/read-all",
                 "/settings/thresholds", "/holds/org/confirm", "/holds/stages/confirm",
                 "/holds/accounts/confirm", "/future-business-write", "/session/extra"]
        requests = [("POST", path) for path in paths]
        requests += [(method, "/session") for method in ("PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")]
        requests += [("GET", "/future-get-write")]
        for method, path in requests:
            with self.subTest(method=method, path=path):
                env = {"REQUEST_METHOD": method, "PATH_INFO": TW.WEB.PREFIX + path,
                       "CONTENT_LENGTH": "10", "CONTENT_TYPE": "application/json",
                       "wsgi.input": UnreadableBody(), "QUERY_STRING": "owner_verification=false"}
                status = []
                result = app(env, lambda s, h: status.append(int(s.split()[0])))
                self.assertEqual(status, [403])
                self.assertEqual(json.loads(b"".join(result)), {"error": "verification-read-only"})
        self.assertEqual(touched, [])


class OwnerVerificationTest(TW.WebBase):
    def make_app(self, **kw):
        return super().make_app(owner_verification=True, **kw)

    def test_staff_cannot_exchange_login_code(self):
        self.erp.person(TW.MARK_SSO, 100)
        status, body, _, _ = self.call("POST", "/session", body={
            "code": TW.MARK_SSO, "codeVerifier": TW.VERIFIER})
        self.assertEqual((status, body), (403, {"error": "owner-only"}))

    def test_owner_zero_logs_in_reads_and_refreshes(self):
        self.erp.person(TW.MARK_SSO, 0, manager=True, teams=((0, None),))
        status, body, _, _ = self.call("POST", "/session", body={
            "code": TW.MARK_SSO, "codeVerifier": TW.VERIFIER})
        self.assertEqual(status, 200)
        token = body["token"]
        status, me, _, _ = self.call("GET", "/me", token)
        self.assertEqual((status, me["idx"], me["scope"]), (200, 0, TW.SC.ALL))
        self.assertIs(me["owner_verification"], True)
        self.assertEqual(self.call("POST", "/session/refresh", token)[0], 200)

    def test_current_owner_role_is_required_for_every_request_and_refresh(self):
        token = self.token(0)
        self.assertEqual(self.call("GET", "/me", token)[0], 200)
        body = TW.TA.org_body(self.fc.now() - timedelta(minutes=1))
        for person in body["employees"]:
            if person["idx"] == 0:
                person["is_top_manager"] = False
        self.st.record_org(body, self.fc.now())
        for method, path in (("GET", "/me"), ("GET", "/board"), ("POST", "/session/refresh")):
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path, token)[:2], (403, {"error": "owner-only"}))

    def test_staff_lead_and_nonzero_top_account_cannot_use_direct_api_or_login(self):
        body = TW.TA.org_body(self.fc.now() - timedelta(minutes=1),
                              extra_people=(TW.TA.emp(7, "여분 대표", 0, manager=True, top=True),))
        self.st.record_org(body, self.fc.now())
        for idx in (100, 1, 7):
            with self.subTest(idx=idx):
                self.assertEqual(self.get("/me", idx), (403, {"error": "owner-only"}))
                self.assertEqual(self.post("/session/refresh", idx), (403, {"error": "owner-only"}))
                code = TW.tok(idx)
                self.erp.person(code, idx, manager=True)
                self.assertEqual(self.call("POST", "/session", body={
                    "code": code, "codeVerifier": TW.VERIFIER})[:2], (403, {"error": "owner-only"}))

    def test_resigned_owner_cannot_read_refresh_or_login(self):
        token = self.token(0)
        self.resign(0)
        for method, path in (("GET", "/me"), ("POST", "/session/refresh")):
            with self.subTest(path=path):
                self.assertEqual(self.call(method, path, token)[:2], (401, {"error": "no-scope"}))
        self.erp.person(TW.MARK_SSO, 0, manager=True)
        self.assertEqual(self.call("POST", "/session", body={
            "code": TW.MARK_SSO, "codeVerifier": TW.VERIFIER})[:2], (403, {"error": "no-scope"}))

    def test_missing_org_refuses_owner_read_and_login(self):
        self.st.close()
        self.path += ".empty"
        self.st = TW.S.open_writer(self.path, clock=self.fc.now)
        self.assertEqual(self.get("/me", 0), (503, {"error": "org-unavailable"}))
        self.erp.person(TW.MARK_SSO, 0, manager=True)
        self.assertEqual(self.call("POST", "/session", body={
            "code": TW.MARK_SSO, "codeVerifier": TW.VERIFIER})[:2], (503, {"error": "org-unavailable"}))

    def test_owner_can_use_only_the_fixed_read_routes(self):
        for path in ("/me", "/board", "/clients/11", "/links/pending", "/ended", "/unlinked",
                     "/bell", "/settings", "/health"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, 0)[0], 200)
        self.assertEqual(self.erp.calls, [])

    def test_owner_business_posts_do_not_change_stored_work(self):
        before = (self.st.issues(), self.st.link_decisions(), self.st.thresholds(), self.st.access_log())
        requests = [
            ("/issues/1/ack", {}), ("/issues/1/resolve", {}),
            ("/issues/1/except", {"until": TW.TODAY.isoformat(), "note": "검증"}),
            ("/links/confirm", {"refs": ["synthetic"]}), ("/links/reject", {"refs": ["synthetic"]}),
            ("/links/revoke", {"ref": "synthetic"}), ("/links/preview", {"ref": "synthetic"}),
            ("/bell/1/read", {}), ("/bell/read-all", {}),
            ("/settings/thresholds", {"changes": {"zero_spend_days": 4}}),
            ("/holds/org/confirm", {"hold_id": 1}), ("/holds/stages/confirm", {"hold_id": 1}),
            ("/holds/accounts/confirm", {"hold_id": 1}), ("/future-business-write", {}),
        ]
        for path, body in requests:
            with self.subTest(path=path):
                self.assertEqual(self.post(path, 0, body), (403, {"error": "verification-read-only"}))
        after = (self.st.issues(), self.st.link_decisions(), self.st.thresholds(), self.st.access_log())
        self.assertEqual(before, after)
        self.assertEqual(self.erp.calls, [])

    def test_forged_token_and_unknown_identity_stay_closed(self):
        token = self.token(0)
        parts = token.split(".")
        parts[2] = ("a" if parts[2][0] != "a" else "b") + parts[2][1:]
        self.assertEqual(self.call("GET", "/me", ".".join(parts))[0], 401)
        self.assertEqual(self.get("/me", 777), (401, {"error": "no-scope"}))
