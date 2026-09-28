"""네이버 관제 판정(verdict.py) 시험 — 🔴 > ⚪ > 🟡 > 🟢 · ⚪ 는 절대 🟢 가 아니다 · 확인 필요.

돌리는 법(backend 폴더에서):  python3 -m unittest -v tests.test_naver_auto_verdict
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

from app.naver_auto import verdict as V  # noqa: E402

KST = timezone(timedelta(hours=9))
TODAY = date(2026, 9, 29)
DEADLINE = datetime(2026, 9, 29, 8, 0, tzinfo=KST)
AFTER = datetime(2026, 9, 29, 8, 30, tzinfo=KST)
BEFORE = datetime(2026, 9, 29, 7, 0, tzinfo=KST)


def acc(status=V.CHECK_OK, link=V.LINK_CONFIRMED, on=TODAY, not_run=(), cid=1001):
    return V.AccountCheck(cid, link, status, on, tuple(not_run))


def iss(sev, state=V.ST_NEW, until=None):
    return V.OpenIssue(sev, state, until)


def j(accounts, issues=(), now=AFTER):
    return V.judge(accounts=accounts, issues=issues, now=now, deadline=DEADLINE)


class TableTest(unittest.TestCase):
    def test_green(self):
        v = j([acc()])
        self.assertEqual((v.color, v.needs_attention), (V.GREEN, False))

    def test_info_and_exception_keep_green(self):
        v = j([acc()], [iss(V.SEV_INFO), iss(V.SEV_YELLOW, V.ST_EXCEPTION, TODAY),
                        iss(V.SEV_RED, V.ST_EXCEPTION, TODAY + timedelta(days=3))])
        self.assertEqual((v.color, v.needs_attention), (V.GREEN, False))

    def test_closed_issues_do_not_count(self):
        for st in V.ST_CLOSED:
            self.assertEqual(j([acc()], [iss(V.SEV_RED, st)]).color, V.GREEN)

    def test_red(self):
        for st in (V.ST_NEW, V.ST_ACK):
            v = j([acc()], [iss(V.SEV_RED, st)])
            self.assertEqual((v.color, v.needs_attention), (V.RED, True), "👀 확인 중이어도 풀릴 때까지 확인 필요")

    def test_yellow(self):
        self.assertEqual((j([acc()], [iss(V.SEV_YELLOW)]).color, j([acc()], [iss(V.SEV_YELLOW)]).needs_attention),
                         (V.YELLOW, True))
        v = j([acc()], [iss(V.SEV_YELLOW, V.ST_ACK), iss(V.SEV_YELLOW, V.ST_ACK)])
        self.assertEqual((v.color, v.needs_attention), (V.YELLOW, False), "모두 👀 면 확인 필요 아니오")

    def test_expired_exception_counts_again(self):
        v = j([acc()], [iss(V.SEV_YELLOW, V.ST_EXCEPTION, TODAY - timedelta(days=1))])
        self.assertEqual((v.color, v.needs_attention), (V.YELLOW, True))
        v = j([acc()], [iss(V.SEV_RED, V.ST_EXCEPTION, TODAY - timedelta(days=1))])
        self.assertEqual(v.color, V.RED)

    def test_white_reasons_and_needs(self):
        cases = {
            V.CHECK_NOT_CHECKED: True, V.CHECK_PARTIAL: True, V.CHECK_KEY_REJECTED: True,
            V.CHECK_LINK_BROKEN: True, V.CHECK_NOT_ELIGIBLE: True, V.CHECK_DATA_LATE: False,
            V.CHECK_SYSTEM_GAP: False,
        }
        for st, need in cases.items():
            v = j([acc(st)])
            self.assertEqual((v.color, v.needs_attention, v.white_reason), (V.WHITE, need, st), st)

    def test_no_link(self):
        v = j([])
        self.assertEqual((v.color, v.needs_attention, v.white_reason), (V.WHITE, False, V.WHITE_NO_LINK))

    def test_before_and_after_deadline(self):
        v = j([acc(V.CHECK_PENDING)], now=BEFORE)
        self.assertEqual((v.color, v.needs_attention, v.white_reason), (V.WHITE, False, V.CHECK_PENDING))
        v = j([acc(V.CHECK_PENDING)], now=AFTER)
        self.assertEqual((v.color, v.needs_attention, v.white_reason), (V.WHITE, True, V.CHECK_NOT_CHECKED))

    def test_yesterday_result_is_not_today(self):
        """어제 🟢 결과가 오늘 것처럼 보이면 안 된다(설계 v1.7 「실패 대비」)."""
        y = TODAY - timedelta(days=1)
        v = j([acc(on=y)], now=BEFORE)
        self.assertEqual((v.color, v.white_reason, v.needs_attention), (V.WHITE, V.CHECK_PENDING, False))
        v = j([acc(on=y)], now=AFTER)
        self.assertEqual((v.color, v.white_reason, v.needs_attention), (V.WHITE, V.CHECK_NOT_CHECKED, True))
        self.assertEqual(j([acc(on=None)]).color, V.WHITE)

    def test_rules_not_run_is_partial(self):
        v = j([acc(not_run=("stage_spend",))])
        self.assertEqual((v.color, v.white_reason, v.needs_attention), (V.WHITE, V.CHECK_PARTIAL, True))

    def test_priority_red_white_yellow(self):
        self.assertEqual(j([acc(V.CHECK_NOT_CHECKED)], [iss(V.SEV_RED)]).color, V.RED)
        v = j([acc(V.CHECK_NOT_CHECKED)], [iss(V.SEV_YELLOW)])
        self.assertEqual(v.color, V.WHITE)
        self.assertIn("open-yellow", v.reasons)
        v = j([acc(V.CHECK_PENDING)], [iss(V.SEV_YELLOW)], now=BEFORE)
        self.assertEqual((v.color, v.needs_attention), (V.WHITE, True), "점검 전이어도 새 주의 이슈는 확인 필요")

    def test_multi_account_one_bad_blocks_green(self):
        v = j([acc(cid=1), acc(V.CHECK_KEY_REJECTED, cid=2), acc(cid=3)])
        self.assertEqual((v.color, v.white_reason), (V.WHITE, V.CHECK_KEY_REJECTED))

    def test_white_reason_order(self):
        v = j([acc(V.CHECK_DATA_LATE, cid=1), acc(V.CHECK_NOT_CHECKED, cid=2), acc(V.CHECK_PARTIAL, cid=3)])
        self.assertEqual(v.white_reason, V.CHECK_NOT_CHECKED)
        self.assertEqual(v.reasons[:3], (V.CHECK_NOT_CHECKED, V.CHECK_PARTIAL, V.CHECK_DATA_LATE))

    def test_auto_link_always_needs(self):
        v = j([acc(link=V.LINK_AUTO)])
        self.assertEqual((v.color, v.needs_attention), (V.GREEN, True))
        self.assertIn("account-unconfirmed", v.reasons)

    def test_bad_inputs(self):
        for bad in ([acc("weird")], [acc(link="name")], ["1001"]):
            with self.assertRaises(ValueError):
                j(bad)
        for bad in (iss("orange"), iss(V.SEV_RED, "maybe"), iss(V.SEV_RED, V.ST_EXCEPTION, None)):
            with self.assertRaises(ValueError):
                j([acc()], [bad])
        with self.assertRaises(ValueError):
            V.judge(accounts=[acc()], issues=[], now=datetime(2026, 9, 29, 9), deadline=DEADLINE)


class PropertyTest(unittest.TestCase):
    """무작위 조합 5,000개 — 약속이 한 번도 깨지지 않는다."""

    def test_invariants(self):
        rnd = random.Random(20260928)
        statuses = sorted(V._STATUSES)
        for _ in range(5000):
            n = rnd.randint(0, 3)
            accs = [acc(rnd.choice(statuses), rnd.choice([V.LINK_CONFIRMED, V.LINK_AUTO]),
                        rnd.choice([TODAY, TODAY - timedelta(days=1), None]),
                        rnd.choice([(), ("r3",)]), cid=k) for k in range(n)]
            isss = [iss(rnd.choice([V.SEV_RED, V.SEV_YELLOW, V.SEV_INFO]),
                        rnd.choice([V.ST_NEW, V.ST_ACK, V.ST_EXCEPTION, "resolved"]),
                        TODAY + timedelta(days=rnd.randint(-2, 2))) for _ in range(rnd.randint(0, 3))]
            now = rnd.choice([BEFORE, AFTER])
            v = V.judge(accounts=accs, issues=isss, now=now, deadline=DEADLINE)
            fully_ok = bool(accs) and all(a.status == V.CHECK_OK and a.checked_on == TODAY and not a.rules_not_run
                                          for a in accs)
            if v.color == V.GREEN:
                self.assertTrue(fully_ok, "⚪ 가 🟢 로 보였다")
            if not fully_ok:
                self.assertIn(v.color, (V.RED, V.WHITE), "온전히 점검 안 된 가망은 🔴 이나 ⚪ 여야 한다")
            if v.color == V.RED:
                self.assertTrue(v.needs_attention)
            if any(a.link == V.LINK_AUTO for a in accs):
                self.assertTrue(v.needs_attention)
            if v.color == V.GREEN and not any(a.link == V.LINK_AUTO for a in accs):
                self.assertFalse(v.needs_attention)


class PurityTest(unittest.TestCase):
    def test_pure_module(self):
        src = (BACKEND / "app" / "naver_auto" / "verdict.py").read_text(encoding="utf-8")
        for bad in ("import requests", "urllib", "sqlite", "sqlalchemy", "datetime.now", "time.time", "open(",
                    "from ..", "from app"):
            self.assertNotIn(bad, src, bad)


if __name__ == "__main__":
    unittest.main()
