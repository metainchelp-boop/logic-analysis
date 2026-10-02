"""읽기 전용 검증판 — 기존 직원 범위를 유지하며 합성 자료와 가짜 전산만 사용한다."""
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

    def test_staff_can_exchange_login_code_without_gaining_scope(self):
        self.erp.person(TW.MARK_SSO, 100)
        status, body, _, _ = self.call("POST", "/session", body={
            "code": TW.MARK_SSO, "codeVerifier": TW.VERIFIER})
        self.assertEqual(status, 200)
        status, me, _, _ = self.call("GET", "/me", body["token"])
        self.assertEqual((status, me["idx"], me["scope"]), (200, 100, TW.SC.MINE))
        self.assertIs(me["owner_verification"], True)

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

    def test_current_scope_is_recomputed_without_preserving_former_all_access(self):
        token = self.token(0)
        self.assertEqual(self.call("GET", "/me", token)[0], 200)
        body = TW.TA.org_body(self.fc.now() - timedelta(minutes=1))
        for person in body["employees"]:
            if person["idx"] == 0:
                person["is_top_manager"] = False
        self.st.record_org(body, self.fc.now())
        self.assertEqual(self.call("GET", "/me", token)[1]["scope"], TW.SC.MINE)
        self.assertEqual(self.call("GET", "/board", token, query="attention=0")[1]["rows"], [])
        self.assertEqual(self.call("GET", "/clients/11", token)[0], 404)
        self.assertEqual(self.call("POST", "/session/refresh", token)[0], 200)

    def test_staff_and_lead_are_mine_and_existing_nonzero_top_is_all(self):
        body = TW.TA.org_body(self.fc.now() - timedelta(minutes=1),
                              extra_people=(TW.TA.emp(7, "여분 대표", 0, manager=True, top=True),))
        self.st.record_org(body, self.fc.now())
        for idx, scope, pids, manager, teams in (
            (100, TW.SC.MINE, {11, 14}, False, ((11, 10), (10, 0))),
            # 2026-10-02 명세: 관리팀장도 본인 담당만. 직접 담당이 없는 이 fixture는 빈 목록이다.
            (1, TW.SC.MINE, set(), True, ((11, 10), (10, 0))),
            (7, TW.SC.ALL, {11, 12, 13, 14}, True, ((0, None),)),
        ):
            with self.subTest(idx=idx):
                self.assertEqual(self.get("/me", idx)[1]["scope"], scope)
                self.assertEqual(self.post("/session/refresh", idx)[0], 200)
                self.assertEqual({r["possibility_id"] for r in self.get("/board", idx, query="attention=0&as=0")[1]["rows"]}, pids)
                code = TW.tok(idx)
                self.erp.person(code, idx, manager=manager, teams=teams)
                status, session, _, _ = self.call("POST", "/session", body={
                    "code": code, "codeVerifier": TW.VERIFIER})
                self.assertEqual(status, 200)
                self.assertEqual(self.call("GET", "/me", session["token"])[1]["scope"], scope)

    def test_staff_cannot_enumerate_other_owners_or_expand_selection(self):
        self.assertEqual(self.get("/clients/11", 100)[0], 200)
        self.assertEqual(self.get("/clients/12", 100), self.get("/clients/99999", 100))
        self.assertEqual(self.get("/clients/12", 100)[0], 404)
        self.assertEqual(self.get("/board", 100, query="selection=unassigned")[0], 400)
        self.assertEqual(self.get("/board", 100, query="selection=person:101")[0], 404)
        self.assertEqual(self.get("/settings", 100)[0], 403)
        self.assertEqual(self.get("/me", 1, narrowed=True)[1]["scope"], TW.SC.MINE)

    def test_team_hierarchy_never_grants_other_staff_clients(self):
        """2026-10-02 명세: 부서 계층 권한을 없앴으므로 하부·형제 팀 모두 본인 담당이 아니면 거절한다."""
        body = TW.TA.org_body(self.fc.now() - timedelta(minutes=1), owners=[
            TW.TA.owner(11, 100), TW.TA.owner(12, 102), TW.TA.owner(13, 103), TW.TA.owner(14, 100)],
            extra_people=(TW.TA.emp(102, "하부", 12), TW.TA.emp(103, "다른 팀", 20)))
        body["teams"] += [TW.TA.team(12, "하부 팀", 3, 11), TW.TA.team(20, "다른 팀", 2, 10)]
        self.st.record_org(body, self.fc.now())
        self.assertEqual({r["possibility_id"] for r in self.get("/board", 1, query="attention=0")[1]["rows"]}, set())
        self.assertEqual(self.get("/clients/12", 1)[0], 404)
        self.assertEqual(self.get("/clients/13", 1)[0], 404)
        self.assertEqual(self.get("/board", 1, query="selection=team:20")[0], 404)

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

    def test_all_roles_business_posts_do_not_change_stored_work(self):
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
        for idx in (0, 1, 100, 101, 777):
            for path, body in requests:
                with self.subTest(idx=idx, path=path):
                    self.assertEqual(self.post(path, idx, body), (403, {"error": "verification-read-only"}))
        after = (self.st.issues(), self.st.link_decisions(), self.st.thresholds(), self.st.access_log())
        self.assertEqual(before, after)
        self.assertEqual(self.erp.calls, [])

    def test_forged_token_and_unknown_identity_stay_closed(self):
        self.assertEqual(self.call("GET", "/me")[0], 401)
        token = self.token(0)
        parts = token.split(".")
        parts[2] = ("a" if parts[2][0] != "a" else "b") + parts[2][1:]
        self.assertEqual(self.call("GET", "/me", ".".join(parts))[0], 401)
        self.assertEqual(self.get("/me", 777), (401, {"error": "no-scope"}))

    def test_resigned_deleted_and_unknown_staff_cannot_read_refresh_or_login(self):
        body = TW.TA.org_body(self.fc.now() - timedelta(minutes=1), extra_people=(
            TW.TA.emp(102, "퇴사", 11, status="RESIGNED"), TW.TA.emp(103, "삭제", 11, deleted=True)))
        self.st.record_org(body, self.fc.now())
        for idx in (102, 103, 777):
            with self.subTest(idx=idx):
                self.assertEqual(self.get("/me", idx), (401, {"error": "no-scope"}))
                self.assertEqual(self.post("/session/refresh", idx), (401, {"error": "no-scope"}))
                self.erp.person(TW.tok(idx), idx)
                self.assertEqual(self.call("POST", "/session", body={
                    "code": TW.tok(idx), "codeVerifier": TW.VERIFIER})[:2], (403, {"error": "no-scope"}))
