"""이관 분류·상향 목록: 실제 화면 → 중계 → 엔진의 합성 브라우저 시험."""
import pathlib
from datetime import timedelta
from unittest.mock import patch

from naver_engine.tests import test_view_delta_screen as VD


class ViewSectionsScreenTest(VD.ViewDeltaScreenTest):
    def setUp(self):
        super().setUp()
        self.seed_escalations()

    def seed_escalations(self):
        """현재 합성 시각은 유지하고 두 업체의 주의 항목을 36시간 전부터 열린 것으로 만든다."""
        now = self.fc.now()
        rid = self.st.begin_run(now.date(), now)
        for pid, cid in ((11, VD.TM.A), (12, VD.TM.B)):
            self.st.record_account_check(rid, cid, possibility_id=pid, link="confirmed", status="ok",
                rules_run=("bizmoney", "link"), rules_not_run=(), checked_at=now,
                findings=(VD.TA.F("bizmoney", "bizmoney_low", f"acc:{cid}", "yellow"),))
        self.st.finish_run(rid, VD.S.RUN_DONE, now)
        # 하니스 자료의 시작 시각만 구성한다. 제품 조회/상향 판정 및 권한 규칙은 실제 코드다.
        with self.st._tx() as conn:
            conn.execute("UPDATE naver_auto_issue_event SET at=? WHERE to_state='new'",
                         ((now - timedelta(hours=36)).isoformat(),))

    def apply_control(self, operation):
        super().apply_control(operation)
        if operation == "add":
            now = self.fc.now()
            rid = self.st.begin_run(now.date(), now)
            self.st.record_account_check(rid, VD.TM.A, possibility_id=11, link="confirmed", status="ok",
                rules_run=("spend",), rules_not_run=(), checked_at=now,
                findings=(VD.TA.F("spend", "spend_up", f"acc:{VD.TM.A}", "yellow"),))
            self.st.finish_run(rid, VD.S.RUN_DONE, now)
            with self.st._tx() as conn:
                conn.execute("""UPDATE naver_auto_issue_event SET at=? WHERE issue_id IN
                    (SELECT issue_id FROM naver_auto_issue WHERE code='spend_up') AND to_state='new'""",
                    ((now - timedelta(hours=36)).isoformat(),))

    def test_screen_in_real_browser(self):
        scenario = pathlib.Path(__file__).with_name("view_sections_screen_browser.js")
        with patch.object(VD, "SCENARIO", scenario):
            super().test_screen_in_real_browser()
