"""네이버 관제 실사용 손길(2026-10-05) — 운영 배선과 같은 세 스위치로 실제 Chromium/중계/엔진에서 누른다.

봉인 소스 용량(2MiB) 때문에 봉인 경로 밖(tests/)에 둔다."""
import json
from pathlib import Path
import subprocess
import time

from naver_engine.tests import test_screen as TS
from naver_engine.tests import test_web as TW


class OwnerActionsScreenTest(TS.BrowserTest):
    test_screen_in_real_browser = None   # 물려받은 S13 시나리오(제한판 없는 화면)는 test_screen 이 돌린다

    def make_app(self, **kw):
        return super().make_app(owner_verification=True, verified_linking=True, owner_actions=True, **kw)

    def test_opened_hands_work_and_link_writes_stay_closed_in_real_browser(self):
        yellow = self.issue_of(12, "yellow")["issue_id"]
        red = self.issue_of(11, "red")["issue_id"]
        self.assertNotEqual(self.st.thresholds().zero_spend_days, 4)
        decisions = self.st.link_decisions()
        cfg = {'base': self.base, 'ceo': TW.tok(1), 'staff': TW.tok(3), 'now': self.fc.now().isoformat(),
               'yellow': yellow, 'red': red, 'zeroSpendDays': 4, 'refLength': TW.W.REF_LENGTH}
        scenario = Path(__file__).with_name('naver_owner_actions_screen_browser.js')
        proc = subprocess.Popen([self.node, str(scenario), json.dumps(cfg)], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self.node_env)
        deadline = time.monotonic() + 120
        while proc.poll() is None and time.monotonic() < deadline:
            self.engine.handle_request()
        if proc.poll() is None:
            proc.kill()
        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, err[-3000:])
        self.assertIn('owner-actions-screen-ok:', out)
        self.assertEqual(self.stray, [])
        # 화면이 누른 손길이 저장소에 남았고(누가 · 무엇), 짝 판단은 하나도 바뀌지 않았다.
        self.assertEqual(self.st.issue(yellow)["state"], "ack")
        [ev] = [e for e in self.st.issue_events(yellow) if e["kind"] == "acked"]
        self.assertEqual(ev["by_person"], 0)
        self.assertEqual(self.st.issue(red)["state"], "new")
        self.assertEqual(self.st.thresholds().zero_spend_days, 4)
        self.assertEqual(self.st.link_decisions(), decisions)
        actions = {(r["action"], r["result"]) for r in self.st.access_log(viewer_idx=0)}
        self.assertTrue({("ack", "ok"), ("bell-read", "ok"), ("thresholds", "ok")} <= actions, actions)
        self.assertIn(("thresholds", "not-allowed"), {(r["action"], r["result"]) for r in self.st.access_log(viewer_idx=100)})
