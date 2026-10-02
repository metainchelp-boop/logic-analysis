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
        # 2026-10-02 명세: 관리팀장도 MINE — 이 fixture의 팀장 1에게 직접 담당은 없다.
        for idx, pids in ((100, (11, 14)), (101, (12,)), (1, ()), (0, (11, 12, 13, 14))):
            b = self.rows(idx)
            self.assertEqual({r["issue_id"] for r in b["issue_rows"]}, self.open_ids(pids), idx)
            self.assertTrue({r["possibility_id"] for r in b["issue_rows"]} <= set(pids), idx)

    def test_rows_follow_selection(self):
        """고르기(사람)로 좁히면 이슈 줄도 좁아진다 — 표와 같은 가망."""
        # 2026-10-02 명세: 다른 직원 고르기는 대표만, 관리팀장은 거절한다.
        self.assertEqual(self.get("/board", 1, query="selection=person%3A101&attention=0")[0], 404)
        b = self.rows(0, query="selection=person%3A101&attention=0")
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
        """2026-10-02 명세: 담당은 🔴 예외 불가 · 대표만 7일 · 팀장에게 타 담당 줄은 없다."""
        red = self.issue_of(11, "red")["issue_id"]
        yellow = self.issue_of(12, "yellow")["issue_id"]

        def can(idx, iid):
            [r] = [r for r in self.rows(idx)["issue_rows"] if r["issue_id"] == iid]
            return r["can"]
        c = can(100, red)
        self.assertEqual((c["ack"], c["resolve"], c["except"], c["except_blocked"]), (True, True, False, "actor-too-low"))
        self.assertNotIn(red, {r["issue_id"] for r in self.rows(1)["issue_rows"]})
        c = can(0, red)
        self.assertEqual((c["except"], c["except_until_max"]), (True, (TODAY + timedelta(days=6)).isoformat()))
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

    def test_stale_org_blocks_staff_board_before_rendering_buttons(self):
        """2026-10-02 명세: 낡은 조직은 직원 전체 응답을 503으로 닫고 대표 진단만 남긴다."""
        self.at(self.fc.now() + timedelta(hours=30))
        yellow = self.issue_of(12, "yellow")["issue_id"]
        self.assertEqual(self.get("/board", 101, query="attention=0"), (503, {"error": "org-stale"}))
        [r] = [r for r in self.rows(0)["issue_rows"] if r["issue_id"] == yellow]
        self.assertEqual((r["can"]["ack"], r["can"]["except"], r["can"]["except_blocked"]), (True, False, "org-stale"))

    def test_stale_org_reason_before_too_low(self):
        """2026-10-02 명세: 직원은 이슈 권한보다 조직 최신성을 먼저 확인하여 읽기·쓰기를 503으로 닫는다."""
        self.at(self.fc.now() + timedelta(hours=30))
        red = self.issue_of(11, "red")["issue_id"]
        self.assertEqual(self.get("/board", 100, query="attention=0"), (503, {"error": "org-stale"}))
        s, b = self.post(f"/issues/{red}/except", 100, {"until": TODAY.isoformat(), "note": "사유"})
        self.assertEqual((s, b["error"]), (503, "org-stale"))
        self.st.record_org(TA.org_body(self.fc.now() - timedelta(minutes=1)), self.fc.now())
        [r] = [r for r in self.get("/board", 100, query="attention=0")[1]["issue_rows"] if r["issue_id"] == red]
        self.assertEqual(r["can"]["except_blocked"], "actor-too-low")   # 조직을 새로 받은 뒤에야 층 까닭

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
        # 2026-10-02 명세: 타 담당 이슈의 예외 승인·완료 열람은 팀장이 아니라 대표 몫이다.
        self.assertEqual(self.post(f"/issues/{red}/except", 1, {"until": until, "note": "광고주 자동 충전"})[0], 404)
        self.assertEqual(self.post(f"/issues/{red}/except", 0, {"until": until, "note": "광고주 자동 충전"})[0], 200)
        [e] = [r for r in self.rows(0)["done_rows"] if r["issue_id"] == red]
        self.assertEqual((e["state"], e["exception_until"], e["hand"]["note"]), ("exception", until, "광고주 자동 충전"))
        # 범위 밖(101)에게는 11 의 예외 줄이 없다
        self.assertNotIn(red, {r["issue_id"] for r in self.rows(101)["done_rows"]})

    def test_closed_today_scoped(self):
        """2026-10-02 명세: 대표가 닫은 11의 🔴도 타 담당 직원·팀장·사람101 선택에는 없다."""
        red = self.issue_of(11, "red")["issue_id"]
        self.assertEqual(self.post(f"/issues/{red}/resolve", 1)[0], 404)
        self.assertEqual(self.post(f"/issues/{red}/resolve", 0)[0], 200)
        self.assertIn(red, {r["issue_id"] for r in self.rows(0)["done_rows"]})
        self.assertNotIn(red, {r["issue_id"] for r in self.rows(1)["done_rows"]})
        self.assertIn(red, {r["issue_id"] for r in self.rows(100)["done_rows"]})
        self.assertNotIn(red, {r["issue_id"] for r in self.rows(101)["done_rows"]})
        self.assertNotIn(red, {r["issue_id"] for r in self.rows(0, query="selection=person%3A101&attention=0")["done_rows"]})

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
        # 2026-10-02 명세: 직원은 낡은 조직에서 행 자체를 받지 않는다. 대표 진단으로 만료 상태를 검사한다.
        self.assertEqual(self.get("/board", 101, query="attention=0"), (503, {"error": "org-stale"}))
        [r] = [r for r in self.rows(0)["issue_rows"] if r["issue_id"] == yellow]
        self.assertEqual((r["state"], r["stored_state"], r["can"]["ack"], r["can"]["except"]),
                         ("new", "exception", True, False))   # 점검이 다시 보기 전에는 예외를 이어 붙이지 않는다
        # 막힌 까닭 = 서버가 먼저 거절하는 까닭(하루가 지나 조직 자료가 낡음) · 지난 예외 사유는 🆕 줄에 붙지 않는다
        self.assertEqual((r["can"]["except_blocked"], r["hand"]), ("org-stale", None))
        s, b = self.post(f"/issues/{yellow}/except", 101, {"until": TODAY.isoformat(), "note": "다시"})
        self.assertEqual((s, b["error"]), (503, "org-stale"))
        # 조직을 새로 받으면 다음 까닭 = 「예외 중」(층이 아니다 · 검토 exception-active)
        self.st.record_org(TA.org_body(self.fc.now() - timedelta(minutes=1)), self.fc.now())
        for idx in (101, 0):   # 새 정책상 타 담당 팀장 대신 대표에게 같은 차단 이유가 보여야 한다.
            [r] = [r for r in self.get("/board", idx, query="attention=0")[1]["issue_rows"] if r["issue_id"] == yellow]
            self.assertEqual(r["can"]["except_blocked"], "exception-active", idx)
        s, b = self.post(f"/issues/{yellow}/except", 0, {"until": TODAY.isoformat(), "note": "다시"})
        self.assertEqual((s, b["error"]), (409, "exception-active"))
        s, b = self.post(f"/issues/{yellow}/ack", 101)
        self.assertEqual(s, 200)
        [r] = [r for r in self.get("/board", 101, query="attention=0")[1]["issue_rows"] if r["issue_id"] == yellow]
        self.assertEqual(r["hand"]["kind"], "acked")   # 다시 시작된 뒤 사람이 한 일은 싣는다

    def test_blocked_reason_only_on_open_rows(self):
        """닫힌 줄 · 예외 중인 줄(「오늘 풀린 것」)에는 막힌 까닭도 없다 — 단추 자체가 없다(검토 except-blocked-on-closed)."""
        red = self.issue_of(11, "red")["issue_id"]
        self.assertEqual(self.post(f"/issues/{red}/resolve", 100)[0], 200)
        [d] = [r for r in self.rows(100)["done_rows"] if r["issue_id"] == red]
        self.assertEqual(d["can"], {"ack": False, "resolve": False, "except": False, "except_until_max": None,
                                    "except_blocked": None})
        self._restore_issues(self.st.issues())
        yellow = self.issue_of(12, "yellow")["issue_id"]
        until = (TODAY + timedelta(days=2)).isoformat()
        self.assertEqual(self.post(f"/issues/{yellow}/except", 101, {"until": until, "note": "사유"})[0], 200)
        for idx in (101, 0):   # 2026-10-02 명세: 완료 줄도 현재 담당 또는 대표만 열람한다.
            [e] = [r for r in self.rows(idx)["done_rows"] if r["issue_id"] == yellow]
            self.assertEqual((e["can"]["except"], e["can"]["except_blocked"]), (False, None), idx)

    def test_hand_of_resets(self):
        """사람 손길은 이슈가 다시 시작된 기록 뒤만 — 예외가 끝남 · 다시 생김 · 🔁 저절로 풀림 · 짝이 사라져 닫힘."""
        ctx = W.load(self.st, self.fc.now())

        def ev(kind, by=None, note=None):
            return {"kind": kind, "at": "t", "by_person": by, "note": note, "exception_until": None}
        cases = [
            ([ev("opened"), ev("acked", 101)], "acked"),
            ([ev("opened"), ev("acked", 101), ev("resolved", 101)], "resolved"),
            ([ev("opened"), ev("excepted", 101, "old"), ev("exception_ended")], None),
            ([ev("opened"), ev("resolved", 101), ev("reappeared")], None),
            ([ev("opened"), ev("acked", 101), ev("auto_resolved")], None),
            ([ev("opened"), ev("acked", 101), ev("closed_unlinked")], None),
            ([ev("opened"), ev("acked", 101), ev("reappeared"), ev("excepted", 1, "new")], "excepted"),
            ([ev("opened"), ev("acked", 101), ev("escalated")], "acked"),     # 등급 바뀜은 다시 시작이 아니다
            ([ev("opened"), ev("acked", None)], None),                       # 사람 번호 없는 기록은 손길이 아니다
        ]
        for events, want in cases:
            got = W._hand_of(ctx, events)
            self.assertEqual(None if got is None else got["kind"], want, [e["kind"] for e in events])

    def test_board_reads_hands_once(self):
        """관제 판은 사람 손길을 한 번에 읽는다 — 이슈마다 기록을 따로 읽지 않는다(검토 board-n-plus-1)."""
        yellow = self.issue_of(12, "yellow")["issue_id"]
        self.assertEqual(self.post(f"/issues/{yellow}/ack", 101)[0], 200)
        calls = []
        real = S.Store.issue_hand_events

        def spy(st, ids, kinds):
            calls.append(list(ids))
            return real(st, ids, kinds)

        def boom(*_a, **_k):
            raise AssertionError("이슈마다 기록을 읽었다")
        orig_events = S.Store.issue_events
        S.Store.issue_hand_events, S.Store.issue_events = spy, boom
        try:
            b = self.rows(0)
        finally:
            S.Store.issue_hand_events, S.Store.issue_events = real, orig_events
        self.assertEqual(len(calls), 1)
        self.assertEqual(set(calls[0]), {r["issue_id"] for r in b["issue_rows"] + b["done_rows"]})
        [r] = [r for r in b["issue_rows"] if r["issue_id"] == yellow]
        self.assertEqual(r["hand"]["kind"], "acked")

    def test_hand_events_chunked(self):
        """IN 목록은 묶음으로 나눠 읽는다(SQLite 변수 한도) — 많은 번호도 같은 결과."""
        ids = [i["issue_id"] for i in self.st.issues()]
        want = self.st.issue_hand_events(ids, W.HAND_KINDS | W.RESET_KINDS)
        old = S.ISSUE_READ_CHUNK
        S.ISSUE_READ_CHUNK = 1
        try:
            got = self.st.issue_hand_events(ids + [10 ** 9 + n for n in range(1200)], W.HAND_KINDS | W.RESET_KINDS)
        finally:
            S.ISSUE_READ_CHUNK = old
        self.assertEqual(got, want)
        with self.assertRaises(S.StoreRefused):
            self.st.issue_hand_events([0], W.HAND_KINDS)
        # 고른 종류만 — 모든 이슈에 있는 「열림」 기록은 손길만 고르면 빠지고, 「열림」만 고르면 그것만 온다
        only_open = self.st.issue_hand_events(ids, {"opened"})
        self.assertTrue(only_open)
        self.assertEqual({e["kind"] for es in only_open.values() for e in es}, {"opened"})
        hand_only = self.st.issue_hand_events(ids, W.HAND_KINDS)
        self.assertNotIn("opened", {e["kind"] for es in hand_only.values() for e in es})

    def test_client_issues_carry_can(self):
        _s, c = self.get("/clients/11", 100)
        [red] = [i for i in c["issues"] if i["severity"] == "red"]
        self.assertEqual((red["state_now"], red["can"]["except_blocked"]), ("new", "actor-too-low"))
        # 2026-10-02 명세: 타 담당 팀장의 상세 열람은 404, 대표의 승인 버튼만 남는다.
        self.assertEqual(self.get("/clients/11", 1)[0], 404)
        _s, c = self.get("/clients/11", 0)
        [red] = [i for i in c["issues"] if i["severity"] == "red"]
        self.assertTrue(red["can"]["except"])


class LinkAndNumbersTest(TW.WebBase):
    def test_link_states_today(self):
        _s, b = self.get("/board", 0, query="attention=0")
        got = {r["possibility_id"]: r["link"] for r in b["rows"]}
        self.assertEqual(got, {11: W.LINK_LISTED, 12: W.LINK_LISTED, 13: W.LINK_NONE, 14: W.LINK_NOT_LINKED})
        self.assertEqual(b["links"], {W.LINK_LISTED: 2, W.LINK_MISSING: 0, W.LINK_BROKEN: 0, W.LINK_NOT_LINKED: 1,
                                      W.LINK_NONE: 1, W.LINK_PENDING: 0, "unlinked_numbers": 1})
        self.assertEqual({r["possibility_id"]: r["unlinked"] for r in b["rows"]}, {11: False, 12: False, 13: False, 14: True})

    def test_unlinked_flag_matches_unlinked_list(self):
        """「이관 안 된 번호 있음」은 월요일 알림·``/unlinked`` 와 같은 규칙 — 이어진 계정이 따로 있어도(「이관」 칸은
        이관됨) 잡는다(검토 unlinked-screen-fewer)."""
        ctx = W.load(self.st, self.fc.now())
        rows = dict(ctx.rows_by_pid)
        extra = dict(rows[12][0], customer_id=8888888, state=S.PAIR_BLOCKED, code=W.CODE_NOT_LINKED)
        rows[12] = rows[12] + (extra,)
        c2 = replace(ctx, rows_by_pid=rows)
        scope = TW.SC.scope_of(c2.org, 0)
        self.assertEqual((W.link_state(c2, 12), W.has_unlinked(c2, 12)), (W.LINK_LISTED, True))
        listed = {r["possibility_id"] for r in W.unlinked(c2, scope)["rows"]}
        b = W.board(c2, self.st, scope, "all", False)
        flagged = {r["possibility_id"] for r in b["rows"] if r["unlinked"]}
        self.assertEqual(listed, {12, 14})
        self.assertEqual(flagged, listed)
        self.assertEqual(b["links"]["unlinked_numbers"], len(listed))

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

    def test_numbers_sum_only_when_every_account_read(self):
        """모든 계정이 숫자를 줬을 때만 합 — 한 계정이라도 오늘 하루치가 없거나 다른 가망 짝으로 적혔거나 그 칸이 비면
        None(일부만 더한 값을 전체처럼 · 0원처럼 보이지 않게 · 검토 partial-sum-looks-complete)."""
        ctx = W.load(self.st, self.fc.now())
        checks = dict(ctx.checks_today)
        checks[B] = dict(checks[B], yday_spend=1200.4, bizmoney=5000.0)
        rows = dict(ctx.rows_by_pid)
        rows[12] = rows[12] + (dict(rows[12][0], customer_id=D, state=S.PAIR_CONFIRMED),)
        checks[D] = {"status": "ok", "possibility_id": 12, "rules_not_run": [], "yday_spend": 800, "bizmoney": 1.0}
        c2 = replace(ctx, checks_today=checks, rows_by_pid=rows)
        self.assertEqual(W.today_numbers(c2, 12), {"yday_spend": 2000, "bizmoney": 5001})
        none = {"yday_spend": None, "bizmoney": None}
        c3 = dict(checks)
        c3[D] = dict(checks[D], possibility_id=11)                          # 다른 가망 짝으로 적힌 하루치
        self.assertEqual(W.today_numbers(replace(c2, checks_today=c3), 12), none)
        c3 = dict(checks)
        del c3[D]                                                           # 오늘 못 읽은 계정
        self.assertEqual(W.today_numbers(replace(c2, checks_today=c3), 12), none)
        c3 = dict(checks)
        c3[B] = dict(checks[B], yday_spend=0, bizmoney=0)                   # 진짜 0원 + 못 읽은 계정 → 0원이 아니다
        del c3[D]
        self.assertEqual(W.today_numbers(replace(c2, checks_today=c3), 12), none)
        for bad in (None, True, float("nan"), float("inf"), "12"):          # 한 칸만 비면 그 칸만 None
            c3 = dict(checks)
            c3[D] = dict(checks[D], bizmoney=bad)
            self.assertEqual(W.today_numbers(replace(c2, checks_today=c3), 12), {"yday_spend": 2000, "bizmoney": None}, bad)
        self.assertEqual(W.today_numbers(c2, 12, W.CLIENT_NUMBER_KEYS)["yday_imp"], None)   # 노출은 적지 않은 재료

    def test_client_tiles_and_days_from_server(self):
        """광고주 한 장 타일 · 14일 막대는 서버가 센 값 — 화면이 계정별 기록을 다시 더하지 않는다. 그날 모든 계정을 읽지
        못했으면 ``complete`` 거짓."""
        _s, c = self.get("/clients/12", 101)
        for k in W.CLIENT_NUMBER_KEYS:
            self.assertIn(k, c)
        ctx = W.load(self.st, self.fc.now())
        self.assertEqual({k: c[k] for k in W.CLIENT_NUMBER_KEYS}, W.today_numbers(ctx, 12, W.CLIENT_NUMBER_KEYS))
        days = c["days"]
        self.assertEqual([d["day"] for d in days], sorted(d["day"] for d in days))
        self.assertEqual(len(days), W.HISTORY_DAYS)
        accounts = [{"history": [{"day": "2026-09-29", "status": "ok", "yday_spend": 100},
                                 {"day": "2026-09-30", "status": "ok", "yday_spend": 50}]},
                    {"history": [{"day": "2026-09-29", "status": None},
                                 {"day": "2026-09-30", "status": "ok", "yday_spend": 25.4}]}]
        self.assertEqual(W.day_totals(accounts), [{"day": "2026-09-29", "yday_spend": 100, "complete": False},
                                                  {"day": "2026-09-30", "yday_spend": 75, "complete": True}])
        self.assertEqual(W.day_totals([]), [])
        self.assertEqual(W.day_totals([{"history": [{"day": "2026-09-30", "status": "ok", "yday_spend": None}]}]),
                         [{"day": "2026-09-30", "yday_spend": None, "complete": False}])

    def test_confirm_blocked_when_org_stale(self):
        """조직 자료가 낡으면 「이 계정 맞음」은 꺼지고 까닭을 준다(서버가 409 org-stale 로 거절하는 것과 같게) · 「아님」은 그대로."""
        ctx = W.load(self.st, self.fc.now())
        scope = TW.SC.scope_of(ctx.org, 0)
        fresh = W.links_pending(ctx, self.st, scope)["rows"]
        stale = W.links_pending(replace(ctx, freshness="stale"), self.st, scope)["rows"]
        self.assertTrue(any(r["can_confirm"] for r in fresh))
        self.assertTrue(all(r["confirm_blocked"] is None for r in fresh))
        for a, b in zip(fresh, stale):
            self.assertFalse(b["can_confirm"])
            self.assertEqual(b["can_reject"], a["can_reject"])
            self.assertEqual(b["confirm_blocked"], "org-stale" if a["can_confirm"] else None)

    def test_client_page_has_link_and_numbers(self):
        _s, c = self.get("/clients/12", 101)
        self.assertEqual((c["link"], c["account_unconfirmed"]), (W.LINK_LISTED, True))
        self.assertIn("yday_spend", c)
        self.assertIn("bizmoney", c)


class ThresholdFieldsTest(TW.WebBase):
    def test_only_wrong_fields_named(self):
        """기준값 저장 거절 때 틀린 칸만 짚는다 — 함께 고친 맞는 칸까지 「틀렸다」고 하지 않는다(검토 thresholds-all-fields)."""
        s, b = self.post("/settings/thresholds", 0, {"changes": {"jump_min_weeks": 3.5, "zero_spend_days": 5}})
        self.assertEqual((s, b["error"], b["fields"]), (400, "out-of-range", ["jump_min_weeks"]))
        s, b = self.post("/settings/thresholds", 0, {"changes": {"bizmoney_red_days": 2.5, "bizmoney_yellow_days": 2.0}})
        self.assertEqual((s, b["fields"]), (400, ["bizmoney_red_days", "bizmoney_yellow_days"]))   # 서로 맞지 않음 = 두 칸
        s, b = self.post("/settings/thresholds", 0, {"changes": {"zzz": 1, "zero_spend_days": 5}})
        self.assertEqual((s, b["fields"]), (400, []))                    # 모르는 이름은 되돌려 적지 않는다
        self.assertEqual(self.st.thresholds().zero_spend_days, 3)        # 하나라도 틀리면 아무것도 안 바뀜


if __name__ == "__main__":
    unittest.main()
