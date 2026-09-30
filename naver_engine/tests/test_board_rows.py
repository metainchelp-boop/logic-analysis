"""S13 시험 — 관제 판 가산(``views.board`` · ``views.client``): 이슈 한 줄씩 · 오늘 풀린 것 · 이관 칸 · 어제 광고비 ·
비즈머니 · 누를 수 있는 것(설계 v1.8 S13 · 대표 요구 ③ 「관제 대시보드에서 이슈 관리」).

화면(``backend/naver_page``)은 이 값을 **그대로** 그린다 — 색·단추·숫자를 화면이 스스로 계산하지 않는다. 그래서 이 값이
범위 안만 · 서버 규칙 그대로인지를 여기서 고정한다. 조직·가망은 ``test_web.WebBase`` 와 같다(대표 0 · 팀장 1 ·
직원 100(가망 11 · 14) · 직원 101(가망 12) · 가망 13 = 담당 없음).
"""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from naver_engine.tests import test_web as TW   # backend 경로를 sys.path 에 넣는다 — 먼저 불러야 한다
from naver_engine import store as S  # noqa: E402
from naver_engine import views as W  # noqa: E402
from naver_engine.tests import test_alerts as TA  # noqa: E402
from naver_engine.tests import test_morning as TM  # noqa: E402

from app.naver_auto import issues as I  # noqa: E402
from app.naver_auto import verdict as V  # noqa: E402

TODAY = TW.TODAY
A, B, C_, D = TW.A, TW.B, TW.C_, TW.D


class IssueRowsTest(TW.WebBase):
    def rows(self, idx, query="attention=0", **kw):
        s, b = self.get("/board", idx, query=query, **kw)
        self.assertEqual(s, 200)
        return b

    def open_ids(self, pids):
        return {i["issue_id"] for p in pids for i in self.st.issues(p, open_only=True)
                if W.counting_state(i, TODAY) in W.ISSUE_OPEN}

    def test_rows_are_scoped(self):
        """이슈 한 줄씩도 범위 안만 — 보이는 가망의 열린 이슈와 정확히 같다(더도 덜도)."""
        for idx, pids in ((100, (11, 14)), (101, (12,)), (1, (11, 12, 14)), (0, (11, 12, 13, 14))):
            b = self.rows(idx)
            self.assertEqual({r["issue_id"] for r in b["issue_rows"]}, self.open_ids(pids), idx)
            self.assertTrue({r["possibility_id"] for r in b["issue_rows"]} <= set(pids), idx)

    def test_rows_follow_selection(self):
        """고르기(사람)로 좁히면 이슈 줄도 좁아진다 — 표와 같은 가망."""
        b = self.rows(1, query="selection=person%3A101&attention=0")
        self.assertEqual({r["possibility_id"] for r in b["issue_rows"]}, {12})
        self.assertEqual({r["possibility_id"] for r in b["rows"]}, {12})

    def test_rows_do_not_depend_on_attention(self):
        """표를 「확인 필요만」으로 보든 전체로 보든 이슈 줄 · 이관 띠는 같다."""
        a, b = self.rows(0, query="attention=1"), self.rows(0, query="attention=0")
        self.assertEqual(a["issue_rows"], b["issue_rows"])
        self.assertEqual(a["links"], b["links"])

    def test_red_first(self):
        b = self.rows(0)
        sev = [r["severity"] for r in b["issue_rows"]]
        self.assertEqual(sev, sorted(sev, key={"red": 0, "yellow": 1, "info": 2}.get))
        self.assertEqual(sev[0], "red")

    def test_can_owner_lead_ceo(self):
        """누를 수 있는 것 = 서버 규칙 — 담당은 🔴 예외 불가 · 팀장·대표는 7일 · 🟡 는 담당도 30일."""
        red = self.issue_of(11, "red")["issue_id"]
        yellow = self.issue_of(12, "yellow")["issue_id"]

        def can(idx, iid):
            [r] = [r for r in self.rows(idx)["issue_rows"] if r["issue_id"] == iid]
            return r["can"]
        c = can(100, red)
        self.assertEqual((c["ack"], c["resolve"], c["except"], c["except_blocked"]), (True, True, False, "actor-too-low"))
        for idx in (1, 0):
            c = can(idx, red)
            self.assertEqual((c["except"], c["except_until_max"]), (True, (TODAY + timedelta(days=6)).isoformat()), idx)
        c = can(101, yellow)
        self.assertEqual((c["except"], c["except_until_max"]), (True, (TODAY + timedelta(days=29)).isoformat()))

    def test_can_matches_server(self):
        """단추가 켜졌으면 서버가 받는다 · 꺼졌으면 거절한다(화면과 서버가 두 가지로 읽히지 않게)."""
        cases = []
        for idx in (0, 1, 100, 101):
            for r in self.rows(idx)["issue_rows"]:
                cases.append((idx, r["issue_id"], r["can"]))
        self.assertTrue(cases)
        snap = self.st.issues()
        for idx, iid, c in cases:
            for act in ("ack", "resolve", "except"):
                self._restore_issues(snap)
                body = None
                if act == "except":
                    until = c["except_until_max"] or TODAY.isoformat()
                    body = {"until": until, "note": "사유"}
                s, _b = self.post(f"/issues/{iid}/{act}", idx, body)
                self.assertEqual(s == 200, c[act], (idx, iid, act, s))

    def _restore_issues(self, snap):
        """시험마다 같은 출발점 — 이슈 상태를 처음 것으로(저장소 연결로 직접 · 시험 전용)."""
        conn = self.st._conn
        for i in snap:
            conn.execute("UPDATE naver_auto_issue SET state = ?, exception_until = ?, exception_severity = ? "
                         "WHERE issue_id = ?", (i["state"], i["exception_until"], i["exception_severity"], i["issue_id"]))
        conn.commit()

    def test_prev_owner_sees_no_buttons(self):
        owners = [TA.owner(11, 100), TA.owner(12, 101), TA.owner(13, None),
                  {"possibility_id": 14, "manage_emp_idx": None, "sub_manage_emp_idx": None,
                   "prev_manage_owner_idx": 100, "sales_emp_idx": None, "owner_source": "prev"}]
        self.st.record_org(TA.org_body(self.fc.now() - timedelta(minutes=1), owners=owners), self.fc.now())
        rid = self.st.begin_run(TODAY, self.fc.now())
        self.st.record_account_check(rid, A, possibility_id=14, link="confirmed", status="ok",
                                     rules_run=("bizmoney", "link"), rules_not_run=(), checked_at=self.fc.now(),
                                     findings=(TA.F("bizmoney", "bizmoney_low", f"acc:{A}", "yellow"),))
        self.st.finish_run(rid, S.RUN_DONE, self.fc.now())
        iid = self.issue_of(14, "yellow")["issue_id"]
        [r] = [r for r in self.rows(100)["issue_rows"] if r["issue_id"] == iid]
        self.assertEqual((r["can"]["ack"], r["can"]["resolve"], r["can"]["except"], r["can"]["except_blocked"]),
                         (False, False, False, None))
        self.assertEqual(r["relation"], "prev")

    def test_stale_org_blocks_except_button(self):
        self.at(self.fc.now() + timedelta(hours=30))
        yellow = self.issue_of(12, "yellow")["issue_id"]
        [r] = [r for r in self.get("/board", 101, query="attention=0")[1]["issue_rows"] if r["issue_id"] == yellow]
        self.assertEqual((r["can"]["ack"], r["can"]["except"], r["can"]["except_blocked"]), (True, False, "org-stale"))

    def test_hand_and_done_rows(self):
        """👀 누른 사람·시각이 줄에 · ✅ 해결 · 🙈 예외는 「오늘 풀린 것」으로 옮겨 간다."""
        yellow = self.issue_of(12, "yellow")["issue_id"]
        self.assertEqual(self.post(f"/issues/{yellow}/ack", 101)[0], 200)
        [r] = [r for r in self.rows(101)["issue_rows"] if r["issue_id"] == yellow]
        name = W.load(self.st, self.fc.now()).org.people[101].name
        self.assertEqual((r["state"], r["hand"]["kind"], r["hand"]["by"]), ("ack", "acked", name))
        self.assertEqual(self.post(f"/issues/{yellow}/resolve", 101)[0], 200)
        b = self.rows(101)
        self.assertNotIn(yellow, {r["issue_id"] for r in b["issue_rows"]})
        [d] = [r for r in b["done_rows"] if r["issue_id"] == yellow]
        self.assertEqual((d["state"], d["hand"]["kind"]), ("resolved", "resolved"))
        self.assertEqual((d["can"]["ack"], d["can"]["resolve"], d["can"]["except"]), (False, False, False))
        red = self.issue_of(11, "red")["issue_id"]
        until = (TODAY + timedelta(days=2)).isoformat()
        self.assertEqual(self.post(f"/issues/{red}/except", 1, {"until": until, "note": "광고주 자동 충전"})[0], 200)
        [e] = [r for r in self.rows(1)["done_rows"] if r["issue_id"] == red]
        self.assertEqual((e["state"], e["exception_until"], e["hand"]["note"]), ("exception", until, "광고주 자동 충전"))
        # 범위 밖(101)에게는 11 의 예외 줄이 없다
        self.assertNotIn(red, {r["issue_id"] for r in self.rows(101)["done_rows"]})

    def test_closed_today_scoped(self):
        """오늘 닫힌 이슈도 범위·고르기 안만 — 팀장이 닫은 11 의 🔴 는 101 · 「사람: 101」 고르기에 없다."""
        red = self.issue_of(11, "red")["issue_id"]
        self.assertEqual(self.post(f"/issues/{red}/resolve", 1)[0], 200)
        self.assertIn(red, {r["issue_id"] for r in self.rows(1)["done_rows"]})
        self.assertIn(red, {r["issue_id"] for r in self.rows(100)["done_rows"]})
        self.assertNotIn(red, {r["issue_id"] for r in self.rows(101)["done_rows"]})
        self.assertNotIn(red, {r["issue_id"] for r in self.rows(1, query="selection=person%3A101&attention=0")["done_rows"]})

    def test_closed_yesterday_not_in_done(self):
        yellow = self.issue_of(12, "yellow")["issue_id"]
        self.assertEqual(self.post(f"/issues/{yellow}/resolve", 101)[0], 200)
        self.at(self.fc.now() + timedelta(days=1))
        self.assertNotIn(yellow, {r["issue_id"] for r in self.rows(0)["done_rows"]})

    def test_expired_exception_is_open_again(self):
        """기간이 끝난 🙈 는 다시 「오늘의 이슈」(🆕) — 판정·숫자와 같은 규칙(``counting_state``)."""
        yellow = self.issue_of(12, "yellow")["issue_id"]
        self.assertEqual(self.post(f"/issues/{yellow}/except", 101, {"until": TODAY.isoformat(), "note": "사유"})[0], 200)
        self.assertIn(yellow, {r["issue_id"] for r in self.rows(101)["done_rows"]})
        self.at(self.fc.now() + timedelta(days=1))
        [r] = [r for r in self.get("/board", 101, query="attention=0")[1]["issue_rows"] if r["issue_id"] == yellow]
        self.assertEqual((r["state"], r["stored_state"], r["can"]["ack"], r["can"]["except"]),
                         ("new", "exception", True, False))   # 점검이 다시 보기 전에는 예외를 이어 붙이지 않는다

    def test_client_issues_carry_can(self):
        _s, c = self.get("/clients/11", 100)
        [red] = [i for i in c["issues"] if i["severity"] == "red"]
        self.assertEqual((red["state_now"], red["can"]["except_blocked"]), ("new", "actor-too-low"))
        _s, c = self.get("/clients/11", 1)
        [red] = [i for i in c["issues"] if i["severity"] == "red"]
        self.assertTrue(red["can"]["except"])


class LinkAndNumbersTest(TW.WebBase):
    def test_link_states_today(self):
        _s, b = self.get("/board", 0, query="attention=0")
        got = {r["possibility_id"]: r["link"] for r in b["rows"]}
        self.assertEqual(got, {11: W.LINK_LISTED, 12: W.LINK_LISTED, 13: W.LINK_NONE, 14: W.LINK_NOT_LINKED})
        self.assertEqual(b["links"], {W.LINK_LISTED: 2, W.LINK_MISSING: 0, W.LINK_BROKEN: 0, W.LINK_NOT_LINKED: 1,
                                      W.LINK_NONE: 1, W.LINK_PENDING: 0})

    def test_link_missing_broken_and_not_today(self):
        ctx = W.load(self.st, self.fc.now())
        rows = dict(ctx.rows_by_pid)
        rows[11] = (dict(rows[11][0], state=S.PAIR_MISSING),)
        rows[12] = (dict(rows[12][0], state=S.PAIR_BROKEN), dict(rows[12][0], state=S.PAIR_MISSING))
        c2 = replace(ctx, rows_by_pid=rows)
        self.assertEqual((W.link_state(c2, 11), W.link_state(c2, 12)), (W.LINK_MISSING, W.LINK_BROKEN))
        old = replace(c2, pairing_today=False)
        for pid in (11, 12, 13, 14):
            self.assertEqual(W.link_state(old, pid), W.LINK_PENDING, pid)   # 어제 짝 맞추기를 오늘 것으로 보이지 않는다

    def test_numbers_come_from_todays_account_day(self):
        ctx = W.load(self.st, self.fc.now())
        for pid, cid in ((11, A), (12, B)):
            ad = self.st.account_day(cid, TODAY)
            want = {"yday_spend": None if ad["yday_spend"] is None else round(ad["yday_spend"]),
                    "bizmoney": None if ad["bizmoney"] is None else round(ad["bizmoney"])}
            self.assertEqual(W.today_numbers(ctx, pid), want, pid)
        self.assertEqual(W.today_numbers(ctx, 13), {"yday_spend": None, "bizmoney": None})
        self.assertEqual(W.today_numbers(replace(ctx, pairing_today=False), 12), {"yday_spend": None, "bizmoney": None})

    def test_numbers_sum_and_ignore_other_prospect(self):
        ctx = W.load(self.st, self.fc.now())
        checks = dict(ctx.checks_today)
        checks[B] = dict(checks[B], yday_spend=1200.4, bizmoney=5000.0)
        rows = dict(ctx.rows_by_pid)
        rows[12] = rows[12] + (dict(rows[12][0], customer_id=D, state=S.PAIR_CONFIRMED),)
        checks[D] = {"status": "ok", "possibility_id": 12, "rules_not_run": [], "yday_spend": 800, "bizmoney": 1.0}
        c2 = replace(ctx, checks_today=checks, rows_by_pid=rows)
        self.assertEqual(W.today_numbers(c2, 12), {"yday_spend": 2000, "bizmoney": 5001})
        checks[D] = dict(checks[D], possibility_id=11)                      # 다른 가망 짝으로 적힌 하루치
        self.assertEqual(W.today_numbers(replace(c2, checks_today=checks), 12), {"yday_spend": 1200, "bizmoney": 5000})
        for bad in (True, float("nan"), float("inf"), "12"):
            checks[B] = dict(checks[B], yday_spend=bad, bizmoney=bad)
            checks[D] = dict(checks[D], possibility_id=99)
            self.assertEqual(W.today_numbers(replace(c2, checks_today=checks), 12),
                             {"yday_spend": None, "bizmoney": None}, bad)

    def test_client_page_has_link_and_numbers(self):
        _s, c = self.get("/clients/12", 101)
        self.assertEqual((c["link"], c["account_unconfirmed"]), (W.LINK_LISTED, True))
        self.assertIn("yday_spend", c)
        self.assertIn("bizmoney", c)


if __name__ == "__main__":
    unittest.main()
