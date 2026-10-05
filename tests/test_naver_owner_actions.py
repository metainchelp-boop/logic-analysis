"""네이버 관제 실사용 손길(2026-10-05) — 제한판 위에서 이름 붙인 손길만 연다. 합성 자료·가짜 전산만 사용한다.

봉인 소스 용량(2MiB) 때문에 이 시험은 봉인 경로 밖(tests/)에 둔다.

운영 배선과 같은 설정(``owner_verification`` · ``verified_linking`` · ``owner_actions`` 모두 켬)으로
기존 이슈 손길·🔔·점검 기준·붙잡음·짝 확인 시험을 그대로 다시 돌려, 열린 손길이 원래 설계와 같게 동작하고
짝 확인의 엄격한 길은 바뀌지 않았음을 보인다.
"""
import io
import json
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import MagicMock, patch

from naver_engine import web as WEB
from naver_runtime import __main__ as RUNTIME
from naver_runtime.config import Config
from naver_engine.tests import test_catalog_links as CLT
from naver_engine.tests import test_verified_collection as VC
from naver_engine.tests import test_web as TW

OPENED = ("/issues/1/ack", "/issues/1/resolve", "/issues/1/except", "/bell/1/read", "/bell/read-all",
          "/settings/thresholds", "/holds/org/confirm", "/holds/stages/confirm", "/holds/accounts/confirm",
          "/links/revoke")   # 거두기 = 대표만 · 사유 한 줄(2026-10-06 대표 결정 D5 — handler 가 막는다)
STILL_CLOSED = ("/links/reject", "/links/preview", "/issues/1/reopen", "/issues/x/ack",
                "/issues/1/ack/extra", "/bell/read", "/holds/other/confirm", "/settings/other",
                "/future-business-write", "/session/extra")


def production(**kw):
    """운영 배선(naver_runtime.__main__)과 같은 세 스위치."""
    return dict(owner_verification=True, verified_linking=True, owner_actions=True, **kw)


class OwnerActionGateTest(unittest.TestCase):
    def app(self, touched, **kw):
        def forbidden(*args):
            touched.append(True)
            raise AssertionError("로그인 전 요청은 저장소·감사·전산·미리보기를 부를 수 없습니다")
        return TW.WEB.App(open_read=forbidden, write=forbidden, signer=TW.SE.TokenSigner(TW.Secret(TW.TOKEN_SECRET)),
                          profiles=forbidden, previewer=forbidden, **kw)

    def send(self, app, method, path, readable=False):
        class UnreadableBody:
            def read(self, *_a):
                raise AssertionError("막는 요청은 본문을 읽지 않습니다")
        env = {"REQUEST_METHOD": method, "PATH_INFO": TW.WEB.PREFIX + path,
               "CONTENT_LENGTH": "2" if readable else "10", "CONTENT_TYPE": "application/json",
               "wsgi.input": io.BytesIO(b"{}") if readable else UnreadableBody(),
               "QUERY_STRING": "owner_actions=false"}
        status = []
        body = json.loads(b"".join(app(env, lambda s, h: status.append(int(s.split()[0])))))
        return status[0], body

    def test_opened_actions_still_need_a_token_before_any_side_effect(self):
        touched = []
        app = self.app(touched, **production())
        for path in OPENED:
            with self.subTest(path=path):
                # 연 경로는 기존 쓰기 경로처럼 본문(64KB 상한)을 읽은 뒤 토큰을 본다 — 저장소·감사는 그 뒤다.
                self.assertEqual(self.send(app, "POST", path, readable=True), (401, {"error": "token-missing"}))
        self.assertEqual(touched, [])

    def test_unnamed_routes_and_other_methods_stay_closed_before_any_side_effect(self):
        touched = []
        app = self.app(touched, **production())
        requests = [("POST", p) for p in STILL_CLOSED]
        requests += [(m, p) for p in OPENED for m in ("GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")]
        for method, path in requests:
            with self.subTest(method=method, path=path):
                self.assertEqual(self.send(app, method, path), (403, {"error": "verification-read-only"}))
        self.assertEqual(touched, [])

    def test_switch_off_keeps_every_opened_action_closed(self):
        touched = []
        for kw in (dict(owner_verification=True), dict(owner_verification=True, verified_linking=True)):
            app = self.app(touched, **kw)
            for path in OPENED:
                with self.subTest(kw=kw, path=path):
                    self.assertEqual(self.send(app, "POST", path), (403, {"error": "verification-read-only"}))
        self.assertEqual(touched, [])

    def test_switch_must_be_a_real_boolean_on_the_verification_board(self):
        for bad in (1, "true", None):
            with self.subTest(bad=bad), self.assertRaises(TypeError):
                self.app([], owner_verification=True, owner_actions=bad)
        with self.assertRaises(ValueError):
            self.app([], owner_actions=True)


class OwnerActionsMeTest(TW.WebBase):
    def test_me_tells_the_screen_only_when_actions_are_open(self):
        self.app = self.make_app(**production())
        for idx in (0, 100):
            with self.subTest(idx=idx):
                me = self.get("/me", idx)[1]
                self.assertIs(me["owner_verification"], True)
                self.assertIs(me["owner_actions"], True)
        self.app = self.make_app(owner_verification=True, verified_linking=True)
        self.assertNotIn("owner_actions", self.get("/me", 0)[1])


class OwnerActionsDoNotWriteLinksTest(TW.WebBase):
    def make_app(self, **kw):
        return super().make_app(**production(**kw))

    def test_reject_and_preview_write_nothing(self):
        before = (self.st.link_decisions(), self.st.issues(), self.st.thresholds())
        for path, body in (("/links/reject", {"refs": ["0" * TW.W.REF_LENGTH]}),
                           ("/links/preview", {"ref": "0" * TW.W.REF_LENGTH})):
            for idx in (0, 100):
                with self.subTest(path=path, idx=idx):
                    self.assertEqual(self.post(path, idx, body), (403, {"error": "verification-read-only"}))
        self.assertEqual(before, (self.st.link_decisions(), self.st.issues(), self.st.thresholds()))


class OwnerRevokeCeoOnlyTest(TW.WebBase):
    """대표 결정 D5(2026-10-06) — 운영 배선에서 거두기는 대표만 · 사유 한 줄. 직원·팀장은 아무것도 쓰지 못한다."""

    def make_app(self, **kw):
        return super().make_app(**production(**kw))

    def test_staff_and_lead_are_refused_before_reading_the_decision(self):
        [d] = [d for d in self.st.current_decisions() if d.possibility_id == 11]
        before = self.st.link_decisions()
        for idx in (1, 100, 101):
            with self.subTest(idx=idx):
                self.assertEqual(self.post("/links/revoke", idx, {"decision_id": d.decision_id, "reason": "틀림"}),
                                 (403, {"error": "ceo-only"}))
        self.assertEqual(before, self.st.link_decisions())
        self.assertEqual(self.st.access_log(viewer_idx=100)[0]["result"], "not-allowed")

    def test_ceo_needs_one_line_reason(self):
        [d] = [d for d in self.st.current_decisions() if d.possibility_id == 11]
        before = self.st.link_decisions()
        for bad in ("틀림\n다른 줄", "틀\u2028림", "틀\u200b림", " ", "가" * 65):
            with self.subTest(reason=bad):
                self.assertEqual(self.post("/links/revoke", 0, {"decision_id": d.decision_id, "reason": bad}),
                                 (400, {"error": "bad-body"}))
        self.assertEqual(before, self.st.link_decisions())

    def test_ceo_revokes_and_it_is_recorded_once(self):
        [d] = [d for d in self.st.current_decisions() if d.possibility_id == 11]
        self.assertEqual(self.post("/links/revoke", 0, {"decision_id": 99999, "reason": "틀림"})[0], 404)
        self.assertEqual(self.post("/links/revoke", 0, {"decision_id": d.decision_id, "reason": "다른 업체 계정"}),
                         (200, {"revoked": d.decision_id}))
        self.assertNotIn(d.decision_id, [x.decision_id for x in self.st.current_decisions()])
        self.assertEqual(self.post("/links/revoke", 0, {"decision_id": d.decision_id, "reason": "틀림"})[0], 404)
        self.assertEqual(self.st.access_log(viewer_idx=0)[-1]["result"], "not-visible")


class RuntimeWiringTest(unittest.TestCase):
    def test_runtime_opens_only_the_named_hands(self):
        stop = Event()
        stop.set()
        env = {'SSO_NAVER_CONTROL_CLIENT_KEY': '0123456789abcdef' * 4,
               'NAVER_AUTO_TOKEN_SECRET': 'local-test-token-signing-value-000000000000'}
        with patch.object(RUNTIME, 'Writer', return_value=MagicMock()), \
             patch.object(RUNTIME, 'UnixServer', return_value=MagicMock()) as server:
            self.assertEqual(RUNTIME.run(Config('/tmp/synthetic/data/db', '/tmp/synthetic/socket/api',
                                                web_enabled=True), env, stop=stop), 0)
        app = server.call_args.args[1]
        for path, wanted in (('/issues/1/ack', 401), ('/bell/read-all', 401), ('/settings/thresholds', 401),
                             ('/holds/org/confirm', 401), ('/links/reject', 403), ('/links/revoke', 401),
                             ('/links/preview', 403)):
            status = []
            app({'PATH_INFO': WEB.PREFIX + path, 'REQUEST_METHOD': 'POST', 'CONTENT_LENGTH': '0',
                 'wsgi.input': io.BytesIO()}, lambda s, h: status.append(int(s[:3])))
            self.assertEqual(status, [wanted], path)


class OwnerActionsCopyTest(unittest.TestCase):
    PAGE = Path(__file__).resolve().parents[1] / 'backend/naver_page'

    def test_copy_names_the_opened_issue_hands_only(self):
        source = (self.PAGE / 'app.js').read_text()
        html = (self.PAGE / 'index.html').read_text()
        self.assertIn('<span id="noticeActs">', html)
        self.assertIn('이슈는 이 화면에서 👀 확인 중 · ✅ 해결 · 🙈 예외로 처리합니다. 광고 변경·자동입찰·알림 전송은 하지 않습니다.', source)
        self.assertIn('🔔 알림 목록은 저장된 기록이며 눌러서 읽음 처리할 수 있습니다', source)
        self.assertNotIn('검증판의 알림 전송은 꺼져 있습니다', source)
        self.assertNotIn('읽기 전용 검증판에서는 업무 내용을 변경할 수 없습니다', source)
        self.assertNotIn('네이버 관제(읽기 전용)', source)


# ── 기존 시험을 운영 배선 그대로 다시 돌린다(원래 설계와 같은 판정) ─────────────────────
class ProductionIssueHandsTest(TW.IssueHandsTest):
    def make_app(self, **kw):
        return super().make_app(**production(**kw))


class ProductionBellSettingsTest(TW.BellSettingsTest):
    def make_app(self, **kw):
        return super().make_app(**production(**kw))

    def test_hold_confirm_ceo_only(self):
        """원래 시험과 같다 — 다만 이름 없는 붙잡음 종류는 경로를 찾기 전 제한판이 먼저 막는다(404 대신 403)."""
        self.assertEqual(self.post("/holds/org/confirm", 1, {"hold_id": 1})[0], 403)
        s, b = self.post("/holds/org/confirm", 0, {"hold_id": 1})
        self.assertEqual((s, b["outcome"]), (409, "refused"))   # 붙잡음 없음
        self.assertEqual(self.post("/holds/nope/confirm", 0, {"hold_id": 1}),
                         (403, {"error": "verification-read-only"}))


class ProductionEscalationTest(TW.EscalationTest):
    def make_app(self, **kw):
        return super().make_app(**production(**kw))


class ProductionVerifiedCollectionTest(VC.VerifiedCollectionTest):
    """짝 확인의 엄격한 길(광고계정 ID 대조 · 원천 바뀜 거절)이 손길을 연 뒤에도 그대로다."""

    def make_app(self, **kw):
        return super().make_app(owner_actions=True, **kw)


class ProductionCatalogLinksTest(CLT.CatalogLinksTest):
    def setUp(self):
        real = WEB.App
        with patch.object(WEB, "App", lambda **kw: real(owner_actions=True, **kw)):
            super().setUp()
        self.assertIs(self.app._owner_actions, True)


if __name__ == "__main__":
    unittest.main()
