"""관제 개편(대표 결정 2026-10-06 · D1~D9) 서버 표시 칸 시험 — 숫자 4칸 · ⚪ 까닭 · 계정 확인할 곳 · 주 1회 관찰 ·
대표 「사람별 처리 현황」.

화면은 이 값을 **그대로** 그린다(색·확인 필요·숫자를 화면이 세지 않는다). 그래서 여기서 고정한다:
- 숫자 4칸(오늘 볼 곳 · 문제없음 · 연결 안 됨 · 점검 못 함)은 서로 겹치지 않고 더하면 ``counts.total``.
- 자동 짝(계정 확인 전)은 그것만으로 「확인 필요」가 되지 않는다(D3) — 「계정 확인할 곳」으로 따로 센다.
- 매일 점검하지 않는 단계(홀딩·환불·만료)의 「아직 안 읽음」은 확인 필요가 아니라 「주 1회 관찰」(연속 점검일 때만).
- 사람별 현황은 대표에게만 · 고르기와 상관없이 최대 범위 · 합이 판 숫자와 맞는다.
조직·가망은 ``test_web.WebBase`` 와 같다(대표 0 · 팀장 1 · 직원 100(가망 11 · 14) · 직원 101(가망 12) · 가망 13 = 담당 없음).
"""
from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from naver_engine.tests import test_web as TW   # backend 경로를 sys.path 에 넣는다 — 먼저 불러야 한다
from naver_engine import store as S  # noqa: E402
from naver_engine import views as W  # noqa: E402

from app.naver_auto import matching as M  # noqa: E402
from app.naver_auto import scope as SC  # noqa: E402
from app.naver_auto import verdict as V  # noqa: E402

TODAY = TW.TODAY
GROUPS = ("need", "ok", "unlinked", "unchecked")


def blocked_row(pid, code, cid=None):
    return {"possibility_id": pid, "customer_id": cid, "state": S.PAIR_BLOCKED, "code": code, "same_name": None,
            "claimed_elsewhere": None, "decision_id": None, "link": None}


class OverhaulBoardTest(TW.WebBase):
    def board(self, idx, query="attention=0"):
        s, b = self.get("/board", idx, query=query)
        self.assertEqual(s, 200)
        return b

    def ctx(self, **kw):
        return replace(W.load(self.st, self.fc.now()), **kw)

    # ── 숫자 4칸 ──
    def test_four_counts_partition_the_total(self):
        for idx in (0, 1, 100, 101):
            for query in ("attention=0", "attention=1"):
                b = self.board(idx, query)
                tc = b["today_counts"]
                self.assertEqual(set(tc), set(GROUPS) | {"need_red"})
                self.assertEqual(sum(tc[g] for g in GROUPS), b["counts"]["total"], (idx, query))
                self.assertLessEqual(tc["need_red"], tc["need"])
                self.assertLessEqual(tc["need_red"], b["counts"]["red"])
                for g in ("unlinked", "unchecked"):
                    self.assertEqual(sum(b["white_breakdown"][g].values()), tc[g], (idx, g))

    def test_fixture_groups_and_details(self):
        b = self.board(0)
        got = {r["possibility_id"]: (r["today_group"], r["look_today"], r["white_detail"]) for r in b["rows"]}
        self.assertEqual(got, {11: ("need", True, None), 12: ("need", True, None),
                               13: ("unlinked", False, W.W_NAME_CANDIDATE),
                               14: ("unlinked", False, W.W_NOT_TRANSFERRED)})
        self.assertEqual(b["today_counts"], {"need": 2, "need_red": 1, "ok": 0, "unlinked": 2, "unchecked": 0})
        self.assertEqual(b["white_breakdown"], {"unlinked": {W.W_NAME_CANDIDATE: 1, W.W_NOT_TRANSFERRED: 1},
                                                "unchecked": {}})
        self.assertEqual(b["account_confirm"], 1)   # 가망 12 — 자동 짝(계정 확인 전)
        # 직원은 본인 담당만 센다(범위 밖 숫자로 남의 광고주 수를 추론할 수 없게)
        self.assertEqual(self.board(101)["today_counts"], {"need": 1, "need_red": 0, "ok": 0, "unlinked": 0,
                                                           "unchecked": 0})
        self.assertEqual(self.board(101)["account_confirm"], 1)
        self.assertEqual(self.board(100)["account_confirm"], 0)

    def test_acked_yellow_stays_on_today_list_until_resolved(self):
        """👀 확인 중인 🟡 는 「확인 필요」는 아니어도 끝날 때까지 「오늘 볼 광고주」에 남는다(할 일이 남아 있다)."""
        for i in self.st.issues(12, open_only=True):
            self.assertEqual(self.post(f"/issues/{i['issue_id']}/ack", 101)[0], 200)
        b = self.board(0)
        [r] = [r for r in b["rows"] if r["possibility_id"] == 12]
        self.assertFalse(r["verdict"]["needs_attention"])
        self.assertEqual((r["look_today"], r["today_group"]), (True, "need"))

    # ── D3 자동 짝 ──
    def test_auto_link_alone_is_not_needs(self):
        """D3 — 열린 이슈를 다 풀면 자동 짝 광고주는 🟢 · 확인 필요 아니오 · 「계정 확인할 곳」에만."""
        for i in self.st.issues(12, open_only=True):
            self.assertEqual(self.post(f"/issues/{i['issue_id']}/resolve", 101)[0], 200)
        b = self.board(0)
        [r] = [r for r in b["rows"] if r["possibility_id"] == 12]
        self.assertEqual((r["verdict"]["color"], r["verdict"]["needs_attention"]), (V.GREEN, False))
        self.assertIn("account-unconfirmed", r["verdict"]["reasons"])
        self.assertTrue(r["account_unconfirmed"])
        self.assertEqual((r["today_group"], r["look_today"]), ("ok", False))
        self.assertEqual((b["counts"]["needs_attention"], b["today_counts"]["ok"], b["account_confirm"]), (1, 1, 1))
        _s, att = self.get("/board", 0)
        self.assertEqual({r["possibility_id"] for r in att["rows"]}, {11}, "확인 필요만 보기에서 빠진다")
        _s, one = self.get("/clients/12", 0)
        self.assertFalse(one["verdict"]["needs_attention"])

    # ── ⚪ 까닭 ──
    def test_white_detail_splits_no_link(self):
        ctx = self.ctx()
        rows = dict(ctx.rows_by_pid)
        cases = [
            ((), W.W_ID_MISSING),
            ((blocked_row(14, M.B_CLAIMED_BY_SEVERAL),), W.W_ID_CONFLICT),
            ((blocked_row(14, M.B_NAME_ELSEWHERE),), W.W_ID_CONFLICT),
            ((blocked_row(14, M.B_FORMAT),), W.W_ID_INVALID),
            ((blocked_row(14, M.B_AD_ACCOUNT_NO),), W.W_ID_INVALID),
            ((blocked_row(14, M.B_NOT_LINKED),), W.W_NOT_TRANSFERRED),
            ((blocked_row(14, M.B_AD_NOT_LINKED),), W.W_NOT_TRANSFERRED),
            ((blocked_row(14, M.B_NAME_DIFFERENT),), W.W_NAME_CANDIDATE),
            ((blocked_row(14, M.B_REJECTED),), W.W_ID_MISSING),
            # 충돌이 형식·이관보다 앞선다(이관 현황 실관리 분류와 같은 순서)
            ((blocked_row(14, M.B_NOT_LINKED), blocked_row(14, M.B_CONFIRMED_ELSEWHERE)), W.W_ID_CONFLICT),
            ((blocked_row(14, M.B_NOT_LINKED), blocked_row(14, M.B_LENGTH)), W.W_ID_INVALID),
        ]
        for got_rows, want in cases:
            with self.subTest(want=want, rows=[r["code"] for r in got_rows]):
                rows[14] = got_rows
                c = replace(ctx, rows_by_pid=dict(rows))
                v = W.judge(c, 14)
                self.assertEqual((v.color, v.white_reason), (V.WHITE, V.WHITE_NO_LINK))
                self.assertEqual(W.white_detail(c, 14, v), want)
                t = W.today_of(c, 14, {})
                self.assertEqual(t.group, "unlinked" if want in W.UNLINKED_DETAILS else "unchecked")
        self.assertEqual(W.white_detail(ctx, 11, W.judge(ctx, 11)), None, "⚪ 가 아니면 까닭 없음")

    def test_before_todays_pairing_no_link_is_unknown_not_unlinked(self):
        late = replace(W.load(self.st, TW.at(TODAY + timedelta(days=1), 9, 0)))
        self.assertFalse(late.pairing_today)
        v = W.judge(late, 13)
        self.assertEqual(W.white_detail(late, 13, v), W.W_PAIRING_PENDING)
        self.assertEqual(W.today_of(late, 13, {}).group, "unchecked")

    # ── 주 1회 관찰 ──
    def test_weekly_stage_unread_is_watch_not_needs(self):
        later = W.load(self.st, TW.at(TODAY + timedelta(days=1), 9, 0))
        quiet = {k: v for k, v in later.open_issues.items() if k != 12}   # 이슈 없이 「안 읽음」만 보려고

        def ctx_with(stage, continuous):
            prospects = dict(later.prospects)
            prospects[12] = {**prospects[12], "stage_key": stage}
            return replace(later, pairing_today=True, checks_today={}, open_issues=quiet, prospects=prospects,
                           continuous=continuous)
        for stage in sorted(W.WEEKLY_STAGES):
            with self.subTest(stage=stage):
                c = ctx_with(stage, True)
                v = W.judge(c, 12)
                self.assertEqual((v.color, v.white_reason, v.needs_attention), (V.WHITE, V.WHITE_WEEKLY, False))
                t = W.today_of(c, 12, {})
                self.assertEqual((t.group, t.detail, t.look), ("unchecked", V.WHITE_WEEKLY, False))
        # 매일 단계 · 옛 아침 점검(연속 점검 아님)은 예전처럼 「점검 안 됨 · 확인 필요」
        for stage, continuous in (("진행중", True), ("사후 관리", True), ("홀딩중", False)):
            with self.subTest(stage=stage, continuous=continuous):
                v = W.judge(ctx_with(stage, continuous), 12)
                self.assertEqual((v.white_reason, v.needs_attention), (V.CHECK_NOT_CHECKED, True))

    def test_weekly_stage_without_link_is_watch_not_unlinked(self):
        """끝난 지 오래된 계약 등 짝 줄이 없는 주 1회 단계는 「ID를 넣으세요」로 세지 않는다(매일 이을 일이 없다)."""
        ctx = self.ctx(continuous=True)
        prospects = dict(ctx.prospects)
        prospects[13] = {**prospects[13], "stage_key": "계약만료"}
        c = replace(ctx, prospects=prospects)
        v = W.judge(c, 13)
        self.assertEqual(W.white_detail(c, 13, v), V.WHITE_WEEKLY)
        self.assertEqual(W.today_of(c, 13, {}).group, "unchecked")

    # ── D4 사람별 현황 ──
    def test_people_summary_ceo_only_and_widest(self):
        for idx in (1, 100, 101):
            self.assertNotIn("people_summary", self.board(idx), idx)
        full = self.board(0)
        narrow = self.board(0, "selection=person%3A101&attention=0")
        self.assertEqual(full["people_summary"], narrow["people_summary"], "고르기와 상관없이 대표 최대 범위")
        ps = {p["idx"]: p for p in full["people_summary"]}
        self.assertEqual(set(ps), {1, 100, 101, None}, "재직 관리팀은 0곳이어도 한 줄 · 담당 미정 한 줄")
        self.assertIsNone(full["people_summary"][-1]["idx"], "담당 미정은 맨 끝")
        self.assertEqual((ps[100]["clients"], ps[100]["need"], ps[100]["red"], ps[100]["unlinked"]), (2, 1, 1, 1))
        self.assertEqual((ps[101]["clients"], ps[101]["need"], ps[101]["account_confirm"]), (1, 1, 1))
        self.assertEqual((ps[1]["clients"], ps[1]["need"]), (0, 0))
        self.assertEqual((ps[None]["clients"], ps[None]["unlinked"]), (1, 1))
        self.assertEqual(sum(p["clients"] for p in ps.values()), full["counts"]["total"])
        self.assertEqual(sum(p["need"] for p in ps.values()), full["today_counts"]["need"])
        self.assertEqual(sum(p["red"] for p in ps.values()), full["today_counts"]["need_red"])
        self.assertEqual(sum(p["unlinked"] for p in ps.values()), full["today_counts"]["unlinked"])

    def test_people_summary_counts_acked_and_stale(self):
        """👀 확인 중 수 · 12시간 넘게 아무도 안 본 🟡 수 — 올림(``escalations``)과 같은 기다림 규칙."""
        yellow = self.issue_of(12, "yellow")
        since = self.st.issue_new_since()
        began = since[yellow["issue_id"]]
        self.at(began + W.ESCALATE_AFTER + timedelta(minutes=1))
        ps = {p["idx"]: p for p in self.board(0)["people_summary"]}
        self.assertGreaterEqual(ps[101]["stale_yellow"], 1)
        self.assertEqual(ps[100]["stale_yellow"], 0, "🔴 는 올림 규칙(🟡)에 들지 않는다")
        self.assertEqual(self.post(f"/issues/{yellow['issue_id']}/ack", 101)[0], 200)
        ps = {p["idx"]: p for p in self.board(0)["people_summary"]}
        self.assertGreaterEqual(ps[101]["acked"], 1)
        self.assertEqual(ps[101]["stale_yellow"], len([i for i in self.st.issues(12, open_only=True)
                                                       if i["severity"] == "yellow" and i["state"] == "new"]))

    # ── D7 👀 메모 ──
    def test_ack_note_is_optional_and_kept_on_the_issue(self):
        yellow = self.issue_of(12, "yellow")["issue_id"]
        self.assertEqual(self.post(f"/issues/{yellow}/ack", 101, {"note": "광고주에게 충전 요청함"})[0], 200)
        [r] = [r for r in self.board(101)["issue_rows"] if r["issue_id"] == yellow]
        self.assertEqual((r["state"], r["hand"]["kind"], r["hand"]["note"]), ("ack", "acked", "광고주에게 충전 요청함"))
        _s, one = self.get("/clients/12", 101)
        [i] = [i for i in one["issues"] if i["issue_id"] == yellow]
        self.assertIn("광고주에게 충전 요청함", [e["note"] for e in i["events"]])
        red = self.issue_of(11, "red")["issue_id"]
        self.assertEqual(self.post(f"/issues/{red}/ack", 100)[0], 200, "메모 없이도 그대로")
        [r] = [r for r in self.board(100)["issue_rows"] if r["issue_id"] == red]
        self.assertIsNone(r["hand"]["note"])

    def test_ack_note_follows_exception_note_rules(self):
        yellow = self.issue_of(12, "yellow")["issue_id"]
        for bad, status in (({"note": " "}, 400), ({"note": "가" * 201}, 400), ({"note": 3}, 400),
                            ({"memo": "다른 칸"}, 400), ({"note": "두\n줄"}, 409)):
            with self.subTest(body=bad):
                self.assertEqual(self.post(f"/issues/{yellow}/ack", 101, bad)[0], status)
        self.assertEqual(self.issue_of(12, "yellow")["state"], "new", "거절된 메모는 상태도 바꾸지 않는다")

    def test_people_summary_has_no_owner_fields_or_customer_ids(self):
        for p in self.board(0)["people_summary"]:
            self.assertEqual(set(p), {"idx", "name", "team_name", "clients", "need", "red", "acked", "stale_yellow",
                                      "unlinked", "account_confirm"})


if __name__ == "__main__":
    unittest.main()
