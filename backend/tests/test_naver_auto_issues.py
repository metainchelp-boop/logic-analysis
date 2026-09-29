"""네이버 관제 이슈 상태 규칙(issues.py) 시험 — 한 줄 · 다시 생김 · 저절로 풀림 조건 · 등급 올라감 · 예외 한도(M7) · 이관 빠짐(I1).

돌리는 법(backend 폴더에서):  python3 -m unittest -v tests.test_naver_auto_issues
"""
from __future__ import annotations

import itertools
import pathlib
import random
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import checks as C  # noqa: E402
from app.naver_auto import issues as I  # noqa: E402
from app.naver_auto import verdict as V  # noqa: E402

KST = timezone(timedelta(hours=9))
D0 = date(2026, 9, 29)


def st(state=I.ST_NEW, sev=V.SEV_YELLOW, first=D0 - timedelta(days=3), last=D0 - timedelta(days=1), re=0,
       until=None, exc_sev=None):
    return I.IssueState(state, sev, first, last, re, until, exc_sev)


def exc(sev=V.SEV_YELLOW, until=D0 + timedelta(days=3), exc_sev=None, **kw):
    return st(I.ST_EXCEPTION, sev, until=until, exc_sev=exc_sev or sev, **kw)


class ConstantsTest(unittest.TestCase):
    def test_states_match_verdict(self):
        self.assertEqual(I.CLOSED_STATES, V.ST_CLOSED)
        self.assertEqual(I.OPEN_STATES, {V.ST_NEW, V.ST_ACK, V.ST_EXCEPTION})
        self.assertEqual(set(I.SEVERITIES), {V.SEV_RED, V.SEV_YELLOW, V.SEV_INFO})

    def test_limits(self):
        self.assertEqual(I.EXCEPTION_MAX_DAYS, {V.SEV_INFO: 30, V.SEV_YELLOW: 30, V.SEV_RED: 7})
        self.assertEqual(I.EXCEPTION_MIN_ACTOR[V.SEV_RED], I.ACTOR_LEAD)
        self.assertEqual(I.EXCEPTION_MIN_ACTOR[V.SEV_YELLOW], I.ACTOR_OWNER)
        self.assertEqual(I.LINK_SEVERITY, V.SEV_RED)             # 이관 빠짐 = 🔴 긴급(I1 ⓐ)

    def test_link_code_not_a_check_rule(self):
        self.assertNotIn(I.RULE_LINK, C.ALL_RULES)                # 점검 규칙과 겹치면 한쪽이 다른 쪽 이슈를 풀어 버린다
        self.assertTrue(I.valid_code(I.RULE_LINK) and I.valid_code(I.CODE_LINK_BROKEN))

    def test_targets_match_checks(self):
        f = C.run_checks(C.AccountInput(1234567, campaigns=None, campaigns_error=C.KIND_KEY_REJECTED), None,
                         datetime(2026, 9, 29, 7, tzinfo=KST))
        self.assertTrue(all(I.valid_target(x.target) for x in f.findings))
        self.assertEqual(I.account_target(1234567), f.findings[0].target)
        self.assertTrue(I.valid_target("cmp-a0000000000abc-1"))
        for bad in ("acc:0", "acc:01", "acc:", "acc:1234567890123456", "cmp-", "grp-1", "acc:1 ", "", None, 5):
            self.assertFalse(I.valid_target(bad), bad)
        for bad in (0, -1, True, 10 ** 15, "12"):
            with self.assertRaises(I.IssueRuleError):
                I.account_target(bad)


class ObserveTest(unittest.TestCase):
    def test_new(self):
        c = I.observe(None, V.SEV_YELLOW, D0)
        self.assertEqual((c.state.state, c.state.first_seen_on, c.state.last_seen_on, c.state.reappear_count, c.event),
                         (V.ST_NEW, D0, D0, 0, I.EV_OPENED))

    def test_open_stays_same_and_only_last_seen_moves(self):
        for s in (V.ST_NEW, V.ST_ACK):
            c = I.observe(st(s), V.SEV_YELLOW, D0)
            self.assertEqual((c.state.state, c.state.last_seen_on, c.event), (s, D0, None))
            self.assertEqual(c.state.first_seen_on, D0 - timedelta(days=3))

    def test_escalation_reopens_acked(self):
        c = I.observe(st(V.ST_ACK, V.SEV_YELLOW), V.SEV_RED, D0)
        self.assertEqual((c.state.state, c.state.severity, c.event), (V.ST_NEW, V.SEV_RED, I.EV_ESCALATED))
        c = I.observe(st(V.ST_ACK, V.SEV_INFO), V.SEV_YELLOW, D0)
        self.assertEqual((c.state.state, c.event), (V.ST_NEW, I.EV_ESCALATED))

    def test_deescalation_keeps_state(self):
        c = I.observe(st(V.ST_ACK, V.SEV_RED), V.SEV_YELLOW, D0)
        self.assertEqual((c.state.state, c.state.severity, c.event), (V.ST_ACK, V.SEV_YELLOW, I.EV_DEESCALATED))

    def test_closed_reappears_as_new(self):
        for s in I.CLOSED_STATES:
            c = I.observe(st(s, re=2), V.SEV_YELLOW, D0)
            self.assertEqual((c.state.state, c.state.reappear_count, c.event, c.from_state),
                             (V.ST_NEW, 3, I.EV_REAPPEARED, s))
            self.assertEqual(c.state.first_seen_on, D0 - timedelta(days=3))   # 처음 본 날은 그대로

    def test_exception_holds_until_end(self):
        c = I.observe(exc(until=D0), V.SEV_YELLOW, D0)                 # 끝나는 날까지는 예외
        self.assertEqual((c.state.state, c.event), (V.ST_EXCEPTION, None))
        c = I.observe(exc(until=D0 - timedelta(days=1)), V.SEV_YELLOW, D0)
        self.assertEqual((c.state.state, c.event, c.state.exception_until), (V.ST_NEW, I.EV_EXCEPTION_ENDED, None))

    def test_exception_ends_when_severity_passes_granted(self):
        c = I.observe(exc(V.SEV_YELLOW), V.SEV_RED, D0)
        self.assertEqual((c.state.state, c.event, c.state.exception_severity), (V.ST_NEW, I.EV_ESCALATED, None))
        # 🔴 로 준 예외는 🟡 로 내려갔다 다시 🔴 가 돼도 그대로
        c = I.observe(exc(V.SEV_YELLOW, exc_sev=V.SEV_RED), V.SEV_RED, D0)
        self.assertEqual((c.state.state, c.event), (V.ST_EXCEPTION, I.EV_ESCALATED))

    def test_day_never_goes_back(self):
        with self.assertRaises(I.IssueRuleError):
            I.observe(st(last=D0), V.SEV_YELLOW, D0 - timedelta(days=1))

    def test_bad_inputs(self):
        for sev in ("RED", None, "critical"):
            with self.assertRaises(I.IssueRuleError):
                I.observe(None, sev, D0)
        with self.assertRaises(I.IssueRuleError):
            I.observe(None, V.SEV_RED, datetime(2026, 9, 29, tzinfo=KST))   # 시각은 날짜가 아니다
        broken = (st(state="gone"), st(sev="x"), st(first=D0, last=D0 - timedelta(days=1)), st(re=-1), st(re=True),
                  st(I.ST_EXCEPTION), exc(until=datetime(2026, 9, 30)), st(V.ST_NEW, until=D0),
                  st(V.ST_ACK, exc_sev=V.SEV_RED), exc(exc_sev="x"))
        for b in broken:
            with self.assertRaises(I.IssueRuleError, msg=repr(b)):
                I.observe(b, V.SEV_YELLOW, D0)


class AutoResolveTest(unittest.TestCase):
    def test_condition(self):
        yes = I.should_auto_resolve("bizmoney", "bizmoney_low", "acc:1", rules_run=("bizmoney",), found=(),
                                    data_late=False)
        self.assertTrue(yes)
        # 규칙이 안 돎 · 오늘도 발견 · 자료 늦음 → 풀지 않는다
        self.assertFalse(I.should_auto_resolve("bizmoney", "bizmoney_low", "acc:1", rules_run=(), found=(),
                                               data_late=False))
        self.assertFalse(I.should_auto_resolve("bizmoney", "bizmoney_low", "acc:1", rules_run=("bizmoney",),
                                               found=(("bizmoney_low", "acc:1"),), data_late=False))
        self.assertFalse(I.should_auto_resolve("bizmoney", "bizmoney_low", "acc:1", rules_run=("bizmoney",), found=(),
                                               data_late=True))
        # 같은 규칙의 다른 항목이 오늘 보였어도 이 항목은 사라졌다
        self.assertTrue(I.should_auto_resolve("bizmoney", "bizmoney_empty", "acc:1", rules_run=("bizmoney",),
                                              found=(("bizmoney_low", "acc:1"),), data_late=False))
        # 다른 대상(캠페인)의 같은 항목은 이 대상과 무관
        self.assertTrue(I.should_auto_resolve("period_end", "period_ending", "cmp-a", rules_run=("period_end",),
                                              found=(("period_ending", "cmp-b"),), data_late=False))
        for late in (None, 0, "false"):
            with self.assertRaises(I.IssueRuleError):
                I.should_auto_resolve("x", "y", "acc:1", rules_run=("x",), found=(), data_late=late)

    def test_only_open_is_resolved(self):
        for s in (V.ST_NEW, V.ST_ACK):
            c = I.auto_resolve(st(s), D0)
            self.assertEqual((c.state.state, c.event, c.from_state), (I.ST_AUTO_RESOLVED, I.EV_AUTO_RESOLVED, s))
        c = I.auto_resolve(exc(), D0)
        self.assertEqual((c.state.state, c.state.exception_until), (I.ST_AUTO_RESOLVED, None))
        for s in I.CLOSED_STATES:
            self.assertIsNone(I.auto_resolve(st(s), D0))

    def test_unlink_only_open(self):
        c = I.close_unlinked(st(V.ST_ACK), D0)
        self.assertEqual((c.state.state, c.event), (I.ST_UNLINKED, I.EV_UNLINKED))
        for s in I.CLOSED_STATES:
            self.assertIsNone(I.close_unlinked(st(s), D0))


class HumanTest(unittest.TestCase):
    def test_ack_only_from_new(self):
        c = I.ack(st(V.ST_NEW), D0)
        self.assertEqual((c.state.state, c.event), (V.ST_ACK, I.EV_ACKED))
        c = I.ack(exc(until=D0 - timedelta(days=1)), D0)                 # 끝난 예외 = 🆕
        self.assertEqual((c.state.state, c.state.exception_until), (V.ST_ACK, None))
        for bad in (st(V.ST_ACK), exc(), st(I.ST_RESOLVED), st(I.ST_AUTO_RESOLVED), st(I.ST_UNLINKED)):
            with self.assertRaises(I.IssueRuleError) as cm:
                I.ack(bad, D0)
            self.assertEqual(cm.exception.code, I.E_NOT_NEW)

    def test_resolve_from_any_open(self):
        for cur in (st(V.ST_NEW), st(V.ST_ACK), exc()):
            c = I.resolve(cur, D0)
            self.assertEqual((c.state.state, c.event, c.state.exception_until), (I.ST_RESOLVED, I.EV_RESOLVED, None))
        for s in I.CLOSED_STATES:
            with self.assertRaises(I.IssueRuleError) as cm:
                I.resolve(st(s), D0)
            self.assertEqual(cm.exception.code, I.E_NOT_OPEN)

    def test_yellow_exception_by_owner_30_days(self):
        c = I.grant_exception(st(V.ST_ACK), D0 + timedelta(days=29), I.ACTOR_OWNER, D0, "광고주 휴가")
        self.assertEqual((c.state.state, c.state.exception_until, c.state.exception_severity, c.event),
                         (V.ST_EXCEPTION, D0 + timedelta(days=29), V.SEV_YELLOW, I.EV_EXCEPTED))
        self.assertEqual(I.max_exception_until(V.SEV_YELLOW, D0), D0 + timedelta(days=29))
        with self.assertRaises(I.IssueRuleError) as cm:
            I.grant_exception(st(V.ST_ACK), D0 + timedelta(days=30), I.ACTOR_LEAD, D0, "x")
        self.assertEqual(cm.exception.code, I.E_TOO_LONG)

    def test_red_exception_lead_only_7_days(self):
        red = st(V.ST_NEW, V.SEV_RED)
        with self.assertRaises(I.IssueRuleError) as cm:
            I.grant_exception(red, D0 + timedelta(days=1), I.ACTOR_OWNER, D0, "x")
        self.assertEqual(cm.exception.code, I.E_ACTOR)
        c = I.grant_exception(red, D0 + timedelta(days=6), I.ACTOR_LEAD, D0, "x")
        self.assertEqual(c.state.exception_until, D0 + timedelta(days=6))
        with self.assertRaises(I.IssueRuleError) as cm:
            I.grant_exception(red, D0 + timedelta(days=7), I.ACTOR_LEAD, D0, "x")
        self.assertEqual(cm.exception.code, I.E_TOO_LONG)
        self.assertEqual(I.grant_exception(red, D0, I.ACTOR_LEAD, D0, "x").state.exception_until, D0)   # 오늘 하루

    def test_link_broken_exception_is_red_rule(self):
        link = I.observe(None, I.LINK_SEVERITY, D0).state
        with self.assertRaises(I.IssueRuleError):
            I.grant_exception(link, D0 + timedelta(days=2), I.ACTOR_OWNER, D0, "x")

    def test_no_chaining_exceptions(self):
        with self.assertRaises(I.IssueRuleError) as cm:
            I.grant_exception(exc(until=D0 + timedelta(days=2)), D0 + timedelta(days=20), I.ACTOR_OWNER, D0, "x")
        self.assertEqual(cm.exception.code, I.E_ALREADY)
        # 끝난 예외는 다시 줄 수 있다(다시 본 뒤)
        c = I.grant_exception(exc(until=D0 - timedelta(days=1)), D0 + timedelta(days=2), I.ACTOR_OWNER, D0, "x")
        self.assertEqual(c.state.exception_until, D0 + timedelta(days=2))

    def test_exception_refusals(self):
        with self.assertRaises(I.IssueRuleError) as cm:
            I.grant_exception(st(), D0 - timedelta(days=1), I.ACTOR_LEAD, D0, "x")
        self.assertEqual(cm.exception.code, I.E_PAST)
        for s in I.CLOSED_STATES:
            with self.assertRaises(I.IssueRuleError) as cm:
                I.grant_exception(st(s), D0, I.ACTOR_LEAD, D0, "x")
            self.assertEqual(cm.exception.code, I.E_NOT_OPEN)
        for note, code in (("", I.E_NOTE), ("   ", I.E_NOTE), (None, I.E_NOTE), ("x" * 201, I.E_BAD_INPUT),
                           ("줄\n바꿈", I.E_BAD_INPUT), ("탭\t끝", I.E_BAD_INPUT)):
            with self.assertRaises(I.IssueRuleError) as cm:
                I.grant_exception(st(), D0, I.ACTOR_LEAD, D0, note)
            self.assertEqual(cm.exception.code, code, repr(note))
        for actor in ("admin", "ceo", None, 1):
            with self.assertRaises(I.IssueRuleError):
                I.grant_exception(st(), D0, actor, D0, "x")
        with self.assertRaises(I.IssueRuleError):
            I.grant_exception(st(), datetime(2026, 9, 30), I.ACTOR_LEAD, D0, "x")
        self.assertEqual(I.clean_note("  이유 "), "이유")


class RandomWalkTest(unittest.TestCase):
    """무작위 5,000걸음 — 어떤 순서로 불러도 모양이 맞고, 닫힌 것은 관찰로만 다시 열리고, 예외는 한도 안에만 있다."""

    def test_walk(self):
        rng = random.Random(29)
        for _ in range(200):
            cur, day = None, D0
            for _ in range(25):
                day += timedelta(days=rng.choice((0, 1, 1, 2)))
                op = rng.choice(("see", "see", "auto", "unlink", "ack", "resolve", "exc"))
                sev = rng.choice(I.SEVERITIES)
                try:
                    if op == "see" or cur is None:
                        before = cur
                        ch = I.observe(cur, sev, day)
                        if before is not None and before.state in I.CLOSED_STATES:
                            self.assertEqual(ch.state.reappear_count, before.reappear_count + 1)
                    elif op == "auto":
                        ch = I.auto_resolve(cur, day)
                    elif op == "unlink":
                        ch = I.close_unlinked(cur, day)
                    elif op == "ack":
                        ch = I.ack(cur, day)
                    elif op == "resolve":
                        ch = I.resolve(cur, day)
                    else:
                        ch = I.grant_exception(cur, day + timedelta(days=rng.randint(0, 40)),
                                               rng.choice((I.ACTOR_OWNER, I.ACTOR_LEAD)), day, "사유")
                except I.IssueRuleError:
                    continue
                if ch is None:
                    self.assertIn(cur.state, I.CLOSED_STATES)
                    continue
                I.check_state(ch.state)
                if ch.state.state == V.ST_EXCEPTION and op == "exc":
                    span = (ch.state.exception_until - day).days + 1
                    self.assertLessEqual(span, I.EXCEPTION_MAX_DAYS[ch.state.severity])
                if ch.event is not None:
                    self.assertIn(ch.event, I.EVENTS)
                cur = ch.state


if __name__ == "__main__":
    unittest.main()
