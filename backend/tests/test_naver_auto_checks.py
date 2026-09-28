"""네이버 관제 아침 점검 규칙(checks.py) · 기준값(thresholds.py) 시험.

돌리는 법(backend 폴더에서):  python3 -m unittest -v tests.test_naver_auto_checks
"""
from __future__ import annotations

import pathlib
import random
import sys
import unittest
from datetime import datetime, timedelta, timezone

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import checks as C  # noqa: E402
from app.naver_auto import thresholds as T  # noqa: E402
from app.naver_auto import verdict as V  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 29, 6, 45, tzinfo=KST)
FRESH_STAGE = C.StageInfo("진행중", NOW - timedelta(hours=1))


def camp(cid="cmp-1", tp="SHOPPING", status="ELIGIBLE", lock=False, yday=100, week=700, **kw):
    return C.CampaignInfo(cid, tp, status, lock, yday_imp=yday, week_imp=week, **kw)


def account(**kw):
    base = dict(customer_id=3000001, campaigns=(camp(),), bizmoney=500000.5, budget_lock=False, refund_lock=False,
                avg_daily_spend=20000.0, yday_spend=20000.0, recent_spend=(20000.0, 21000.0, 20000.0),
                same_weekday_spend=(19000.0, 21000.0, 20000.0, 20000.0))
    base.update(kw)
    return C.AccountInput(**base)


def run(acc=None, stage=FRESH_STAGE, **kw):
    return C.run_checks(acc if acc is not None else account(), stage, NOW, **kw)


def codes(rep):
    return sorted((f.code, f.level) for f in rep.findings)


class HappyPathTest(unittest.TestCase):
    def test_all_rules_run_and_ok(self):
        r = run()
        self.assertEqual(r.status, V.CHECK_OK)
        self.assertEqual(r.findings, ())
        self.assertEqual(set(r.rules_run), set(C.ALL_RULES) - {C.R_BIZMONEY_LOCK})
        self.assertEqual(r.rules_not_run, ())


class KeyRejectedTest(unittest.TestCase):
    def test_key_rejected(self):
        r = run(account(campaigns=None, campaigns_error="KEY_REJECTED"))
        self.assertEqual(r.status, V.CHECK_KEY_REJECTED)
        self.assertEqual(codes(r), [("key_rejected", V.SEV_YELLOW)])
        self.assertTrue(all(reason == "campaigns-unread" for _r, reason in r.rules_not_run))
        self.assertEqual(r.findings[0].target, "acc:3000001")

    def test_other_read_failure_is_partial(self):
        for err in ("SERVER", "NETWORK", "BAD_RESPONSE", None):
            r = run(account(campaigns=None, campaigns_error=err))
            self.assertEqual(r.status, V.CHECK_PARTIAL, err)
            self.assertEqual(r.findings, ())
            self.assertNotIn(C.R_KEY, r.rules_run)


class BizmoneyTest(unittest.TestCase):
    def test_levels(self):
        for bal, want in ((19999.0, [("bizmoney_low", V.SEV_RED)]), (20000.0, [("bizmoney_low", V.SEV_YELLOW)]),
                          (59999.99, [("bizmoney_low", V.SEV_YELLOW)]), (60000.0, []), (-5000.0, [("bizmoney_low", V.SEV_RED)])):
            self.assertEqual(codes(run(account(bizmoney=bal))), want, bal)

    def test_zero_average(self):
        self.assertEqual(codes(run(account(avg_daily_spend=0.0, bizmoney=0.0))), [("bizmoney_empty", V.SEV_YELLOW)])
        self.assertEqual(codes(run(account(avg_daily_spend=0.0, bizmoney=100.0))), [])
        paused = (camp(status="PAUSED"),)
        self.assertEqual(codes(run(account(avg_daily_spend=0.0, bizmoney=0.0, campaigns=paused))), [])

    def test_unknown_inputs_skip(self):
        for kw, reason in ((dict(avg_daily_spend=None), "avg-incomplete"), (dict(bizmoney=None), "bizmoney-unread"),
                           (dict(bizmoney=float("nan")), "bizmoney-unread"), (dict(bizmoney=True), "bizmoney-unread"),
                           (dict(avg_daily_spend=float("inf")), "avg-incomplete")):
            r = run(account(**kw))
            self.assertIn((C.R_BIZMONEY, reason), r.rules_not_run)
            self.assertNotIn(C.R_BIZMONEY, r.rules_run)
            self.assertEqual(r.status, V.CHECK_PARTIAL, "모르는 값으로 규칙을 못 돌리면 🟢 가 아니다")

    def test_lock_off_by_default(self):
        r = run(account(budget_lock=True, refund_lock=True))
        self.assertEqual(r.findings, ())
        self.assertNotIn(C.R_BIZMONEY_LOCK, r.rules_run)
        self.assertNotIn(C.R_BIZMONEY_LOCK, [x for x, _ in r.rules_not_run])

    def test_lock_when_switched_on(self):
        sw = {C.R_BIZMONEY_LOCK: True}
        self.assertEqual(codes(run(account(budget_lock=True, refund_lock=True), switches=sw)),
                         [("budget_lock", V.SEV_RED), ("refund_lock", V.SEV_YELLOW)])
        r = run(account(budget_lock=None), switches=sw)
        self.assertIn((C.R_BIZMONEY_LOCK, "lock-unread"), r.rules_not_run)


class PeriodEndTest(unittest.TestCase):
    def test_boundaries_and_kst_date(self):
        def ending(raw):
            return run(account(campaigns=(camp(use_period=True, period_end=raw),)))
        # 한국 날짜로 바꿔 센다: UTC 9/30 15:30 = KST 10/1
        self.assertEqual(codes(ending("2026-09-30T15:30:00Z")), [("period_ending", V.SEV_INFO)])
        self.assertEqual(ending("2026-10-02T14:59:59Z").findings[0].facts, (("days_left", 3),))
        self.assertEqual(codes(ending("2026-10-02T15:00:00Z")), [], "KST 10/3 = 4일 뒤")
        self.assertEqual(codes(ending("2026-09-27T00:00:00Z")), [], "이미 끝난 기간")
        self.assertEqual(ending("2026-09-30T15:30:00Z").findings[0].target, "cmp-1")

    def test_unreadable_period_is_partial(self):
        r = run(account(campaigns=(camp(use_period=True, period_end="내일"),)))
        self.assertIn((C.R_PERIOD_END, "period-unreadable"), r.rules_not_run)
        self.assertEqual(r.status, V.CHECK_PARTIAL)

    def test_inactive_or_no_period_ignored(self):
        cs = (camp(use_period=False, period_end="bad"), camp("cmp-2", status="PAUSED", use_period=True, period_end="bad"))
        self.assertEqual(run(account(campaigns=cs)).status, V.CHECK_OK)


class DataLateTest(unittest.TestCase):
    def test_late_skips_4_5_6_only(self):
        stopped = (camp(yday=0, week=900),)
        r = run(account(data_late=True, campaigns=stopped, yday_spend=999999.0, bizmoney=100.0))
        self.assertEqual(r.status, V.CHECK_DATA_LATE)
        skipped = {x for x, reason in r.rules_not_run if reason == "data-late"}
        self.assertEqual(skipped, {C.R_NO_DELIVERY, C.R_SPEND_JUMP, C.R_STAGE_SPEND})
        self.assertIn(C.R_BIZMONEY, r.rules_run)
        self.assertEqual(codes(r), [("bizmoney_low", V.SEV_RED)], "④⑤⑥ 발견은 하나도 없어야 한다")

    def test_partial_beats_late(self):
        r = run(account(data_late=True, avg_daily_spend=None))
        self.assertEqual(r.status, V.CHECK_PARTIAL)

    def test_late_hides_stale_stage(self):
        # 자료 늦음이면 ⑥ 을 아예 안 보므로 「단계 오래됨」도 여기서는 나오지 않는다 — 단계 오래됨은 엔진이 따로 경보한다
        r = run(account(data_late=True), C.StageInfo("진행중", NOW - timedelta(hours=100)))
        self.assertEqual(r.status, V.CHECK_DATA_LATE)
        self.assertNotIn("stage-stale", [reason for _x, reason in r.rules_not_run])


class NoDeliveryTest(unittest.TestCase):
    def test_all_or_some(self):
        cs = (camp("cmp-1", yday=0), camp("cmp-2", yday=0))
        self.assertEqual(codes(run(account(campaigns=cs))), [("active_no_impressions", V.SEV_RED)])
        cs = (camp("cmp-1", yday=0), camp("cmp-2", yday=5))
        r = run(account(campaigns=cs))
        self.assertEqual(codes(r), [("active_no_impressions", V.SEV_YELLOW)])
        self.assertEqual(dict(r.findings[0].facts)["stopped"], 1)

    def test_exclusions(self):
        cs = (camp("cmp-1", yday=0, week=0),                   # 원래 안 나가던 캠페인
              camp("cmp-2", tp="BRAND_SEARCH", yday=0),         # 브랜드검색
              camp("cmp-3", status="PAUSED", yday=0),           # 멈춤
              camp("cmp-4", lock=True, yday=0),                 # 사용자가 끔
              camp("cmp-5", del_flag=True, yday=0))             # 지움
        self.assertEqual(codes(run(account(campaigns=cs))), [])

    def test_unknown_impressions_skip(self):
        for c in (camp(yday=None), camp(week=None)):
            r = run(account(campaigns=(c,)))
            self.assertIn((C.R_NO_DELIVERY, "impressions-unknown"), r.rules_not_run)
            self.assertEqual(r.status, V.CHECK_PARTIAL)

    def test_hints(self):
        cs = (camp(yday=0, shared_budget_lock=True),)
        r = run(account(campaigns=cs, bizmoney=100.0))
        f = [x for x in r.findings if x.code == "active_no_impressions"][0]
        self.assertEqual(dict(f.facts)["hints"], ("shared-budget-lock", "bizmoney"))


class SpendJumpTest(unittest.TestCase):
    def jump(self, base, yday):
        return codes(run(account(same_weekday_spend=base, yday_spend=yday)))

    def test_up_down_none(self):
        self.assertEqual(self.jump((100000.0,) * 4, 200000.0), [("spend_up", V.SEV_YELLOW)])
        self.assertEqual(self.jump((100000.0,) * 4, 199999.0), [])
        self.assertEqual(self.jump((100000.0,) * 4, 50000.0), [("spend_down", V.SEV_YELLOW)])
        self.assertEqual(self.jump((100000.0,) * 4, 50001.0), [])

    def test_small_spend_ignored_only_when_both_small(self):
        self.assertEqual(self.jump((5000.0,) * 4, 9000.0), [], "둘 다 1만원 미만")
        self.assertEqual(self.jump((5000.0,) * 4, 50000.0), [("spend_up", V.SEV_YELLOW)], "어제만 커도 급증")
        self.assertEqual(self.jump((0.0,) * 4, 20000.0), [("spend_up", V.SEV_YELLOW)], "0원 → 급증")
        self.assertEqual(self.jump((50000.0,) * 4, 0.0), [("spend_down", V.SEV_YELLOW)], "기준 커도 어제 0 이면 급감")

    def test_baseline_needs_three_weeks(self):
        self.assertEqual(self.jump((100000.0, 100000.0, 100000.0, None), 300000.0), [("spend_up", V.SEV_YELLOW)])
        r = run(account(same_weekday_spend=(100000.0, None, None, 100000.0), yday_spend=300000.0))
        self.assertIn((C.R_SPEND_JUMP, "baseline-insufficient"), r.rules_not_run)
        self.assertEqual(r.status, V.CHECK_PARTIAL)
        r = run(account(yday_spend=None))
        self.assertIn((C.R_SPEND_JUMP, "yesterday-unknown"), r.rules_not_run)


class StageSpendTest(unittest.TestCase):
    def test_ended_stage_spending(self):
        for st in ("환불중", "계약 만료", "계약만료"):
            r = run(account(yday_spend=1.0), C.StageInfo(st, NOW - timedelta(hours=2)))
            self.assertIn(("spend_after_contract", V.SEV_YELLOW), codes(r), st)
        r = run(account(yday_spend=0.0, same_weekday_spend=(0.0,) * 4), C.StageInfo("환불중", NOW - timedelta(hours=2)))
        self.assertEqual(codes(r), [])

    def test_running_zero_spend(self):
        r = run(account(recent_spend=(5000.0, 0.0, 0.0, 0.0)))
        self.assertIn(("running_zero_spend", V.SEV_YELLOW), codes(r))
        self.assertNotIn("running_zero_spend", [f.code for f in run(account(recent_spend=(0.0, 0.0, 1.0))).findings])
        r = run(account(recent_spend=(0.0, None, 0.0)))
        self.assertIn((C.R_STAGE_SPEND, "recent-unknown"), r.rules_not_run)
        r = run(account(recent_spend=(0.0, 0.0)))
        self.assertIn((C.R_STAGE_SPEND, "recent-unknown"), r.rules_not_run)

    def test_stale_or_missing_stage_is_system_gap(self):
        for stage in (C.StageInfo("진행중", NOW - timedelta(hours=27)), None,
                      C.StageInfo("진행중", datetime(2026, 9, 29, 6, 0))):
            r = run(stage=stage)
            self.assertEqual(r.status, V.CHECK_SYSTEM_GAP, stage)
            self.assertNotIn(C.R_STAGE_SPEND, r.rules_run)
        v = V.judge(accounts=[V.AccountCheck(1, V.LINK_CONFIRMED, V.CHECK_SYSTEM_GAP, NOW.date())], issues=[],
                    now=NOW.replace(hour=9), deadline=NOW.replace(hour=8, minute=0))
        self.assertEqual((v.color, v.needs_attention), (V.WHITE, False), "⚪ · 🟢 불가 · 광고주마다 확인 필요로 올리지 않음")

    def test_other_stage_runs_without_finding(self):
        r = run(account(recent_spend=(0.0, 0.0, 0.0)), C.StageInfo("홀딩중", NOW - timedelta(hours=1)))
        self.assertIn(C.R_STAGE_SPEND, r.rules_run)
        self.assertNotIn("running_zero_spend", [f.code for f in r.findings])


class InputGuardTest(unittest.TestCase):
    def test_bad_switch_and_time(self):
        with self.assertRaises(ValueError):
            run(switches={"no_such_rule": True})
        with self.assertRaises(ValueError):
            C.run_checks(account(), FRESH_STAGE, datetime(2026, 9, 29, 6, 0))

    def test_negative_amounts_are_unknown(self):
        # 음수 금액은 네이버가 줄 수 없는 값 — 모름으로 본다(규칙을 돌리지 않는다)
        r = run(account(avg_daily_spend=-100.0))
        self.assertIn((C.R_BIZMONEY, "avg-incomplete"), r.rules_not_run)
        r = run(account(yday_spend=-1.0))
        self.assertIn((C.R_SPEND_JUMP, "yesterday-unknown"), r.rules_not_run)
        r = run(account(recent_spend=(0.0, -5.0, 0.0)))
        self.assertIn((C.R_STAGE_SPEND, "recent-unknown"), r.rules_not_run)
        r = run(account(same_weekday_spend=(20000.0, -1.0, -1.0, 20000.0)))
        self.assertIn((C.R_SPEND_JUMP, "baseline-insufficient"), r.rules_not_run)
        r = run(account(yday_spend=-1.0), C.StageInfo("환불중", NOW - timedelta(hours=1)))
        self.assertIn((C.R_STAGE_SPEND, "yesterday-unknown"), r.rules_not_run)

    def test_switch_off_rule_is_neither_run_nor_missing(self):
        r = run(account(avg_daily_spend=None), switches={C.R_BIZMONEY: False})
        self.assertNotIn(C.R_BIZMONEY, r.rules_run)
        self.assertNotIn(C.R_BIZMONEY, [x for x, _ in r.rules_not_run])
        self.assertEqual(r.status, V.CHECK_OK)


class PropertyTest(unittest.TestCase):
    """무작위 3,000개 — 모르는 값이 섞이면 🟢 로 가는 「ok」가 나오지 않는다."""

    def test_unknown_never_ok(self):
        rnd = random.Random(929)
        pick = lambda *xs: rnd.choice(xs)  # noqa: E731
        for _ in range(3000):
            cs = tuple(camp(f"cmp-{i}", status=pick("ELIGIBLE", "PAUSED"), yday=pick(0, 5, None),
                            week=pick(0, 50, None)) for i in range(rnd.randint(0, 3)))
            acc = account(campaigns=cs, bizmoney=pick(0.0, 1000.0, 10 ** 6, None),
                          avg_daily_spend=pick(0.0, 20000.0, None), yday_spend=pick(0.0, 30000.0, None),
                          recent_spend=pick((0.0, 0.0, 0.0), (1.0, None, 0.0), None),
                          same_weekday_spend=pick((1.0,) * 4, (None,) * 4, None), data_late=pick(False, True))
            stage = pick(FRESH_STAGE, C.StageInfo("환불중", NOW - timedelta(hours=1)), None)
            r = C.run_checks(acc, stage, NOW)
            if r.status == V.CHECK_OK:
                self.assertEqual(r.rules_not_run, (), "못 돌린 규칙이 있는데 ok")
                self.assertFalse(acc.data_late)


class ThresholdsTest(unittest.TestCase):
    def test_defaults_match_design(self):
        d = T.DEFAULTS
        self.assertEqual((d.bizmoney_red_days, d.bizmoney_yellow_days, d.jump_up_ratio, d.jump_down_ratio,
                          d.jump_min_spend, d.stage_stale_hours, d.zero_spend_days, d.period_end_days),
                         (1.0, 3.0, 2.0, 0.5, 10000, 26, 3, 3))

    def test_validate(self):
        t = T.validate({"jump_up_ratio": 3, "zero_spend_days": 5.0})
        self.assertEqual((t.jump_up_ratio, t.zero_spend_days), (3.0, 5))
        self.assertIsInstance(t.zero_spend_days, int)
        for bad in ({"jump_up_ratio": 1.0}, {"jump_up_ratio": 11}, {"zero_spend_days": 2.5}, {"nope": 1},
                    {"jump_min_spend": True}, {"jump_up_ratio": "2"}, {"jump_up_ratio": float("nan")},
                    {"bizmoney_red_days": 3.0, "bizmoney_yellow_days": 3.0}):
            with self.assertRaises(T.ThresholdOutOfRange, msg=str(bad)):
                T.validate(bad)

    def test_thresholds_used(self):
        th = T.validate({"jump_up_ratio": 3.0})
        r = C.run_checks(account(same_weekday_spend=(100000.0,) * 4, yday_spend=250000.0), FRESH_STAGE, NOW, th)
        self.assertEqual(codes(r), [])


class PurityTest(unittest.TestCase):
    def test_pure_modules(self):
        for name in ("checks.py", "thresholds.py"):
            src = (BACKEND / "app" / "naver_auto" / name).read_text(encoding="utf-8")
            for bad in ("import requests", "urllib", "sqlite", "sqlalchemy", "datetime.now", "time.time", "open(",
                        "from app", "from ..", "import app"):
                self.assertNotIn(bad, src, f"{name}: {bad}")


if __name__ == "__main__":
    unittest.main()
