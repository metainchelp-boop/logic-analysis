"""S9 시험 — 아침 점검(``morning``) · 이슈 저장(판 4) · 사람의 손길 (설계 v1.8 S9 · 반박 C1 · M4 · M5 · L2 · 대표 결정 I1~I3).

가짜 네이버(진짜 읽기 관문을 그대로 쓴다) · 가짜 ① 읽기로만 돈다 — 네트워크 0. 판정·이슈 규칙은
``backend/app/naver_auto`` 를 그대로 쓴다. 예시 번호·이름·금액은 모두 지어낸 것이다.
"""
from __future__ import annotations

import json
import os
import pathlib
import random
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest import mock

ENGINE = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ENGINE.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import checks as C  # noqa: E402
from app.naver_auto import issues as I  # noqa: E402
from app.naver_auto import matching as M  # noqa: E402
from app.naver_auto import verdict as V  # noqa: E402

from naver_engine import erp_read as E  # noqa: E402
from naver_engine import handles as H  # noqa: E402
from naver_engine import links as L  # noqa: E402
from naver_engine import morning as MO  # noqa: E402
from naver_engine import naver_read as N  # noqa: E402
from naver_engine import store as S  # noqa: E402
from naver_engine.credentials import ManagerCredentials, Secret  # noqa: E402
from naver_engine.tests.fake_naver import (AGENCY_ID, MARK_API_KEY, MARK_NEWFIELD, MARK_SECRET, MARK_TRACK,  # noqa: E402
                                           FakeClock, FakeNaver, campaign, cycle_str)

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 9, 29, 6, 40, tzinfo=KST)   # 화요일 아침
TODAY = T0.date()
YDAY = TODAY - timedelta(days=1)
A, B, C_, D = 1234567, 2345678, 3456789, 4567890   # 고객 번호(지어낸 것)
NAME_MARK = "표지상회"


def creds():
    return ManagerCredentials(AGENCY_ID, Secret(MARK_API_KEY), Secret(MARK_SECRET))


def shop(pid):
    return f"가게{pid}"


def srow(pid, name=None, stage="진행중", end=None, unreadable=False):
    return E.StageRow(pid, stage, shop(pid) if name is None else name, end, unreadable)


NAMES = {}   # 고객 번호 → 계정 이름(자동 짝은 가망 이름과 같아야 이어진다 — 반박 H4)


def kids(*accs):
    acc = {cid: {"customerId": cid, "adAccountNo": 8_000_000 + cid % 1_000_000,
                 "adAccountName": NAMES.get(cid, f"계정{cid}")} for cid in accs}
    return N.ChildAccounts(acc, {1: len(acc)}, ())


class FakeErp:
    def __init__(self, ids=()):
        self.ids, self.calls = ids, 0

    def read_naver_customer_ids(self):
        self.calls += 1
        return tuple(self.ids)


def steady(imp=1000, clk=50, sales=20000, ccnt=2):
    return lambda d: (imp, clk, sales, ccnt)


def quiet(d):
    return (0, 0, 0, 0)


class Ads:
    """가짜 광고 계정 — 캠페인 · 비즈머니 · 통계. 합계는 **활동이 있는 캠페인만** 줄을 준다(0단계 실측) · 하루별은 날마다 준다."""

    def __init__(self, naver: FakeNaver) -> None:
        self.acc = {}
        self.cycle = datetime.combine(TODAY, time(5, 0), tzinfo=KST)   # 어제 자료 다 들어옴
        self.drop_days = {}         # 캠페인 → 하루별에서 뺄 날짜들
        self.fail = {}              # (고객, 경로 앞) → (상태, 본문)
        self.stats_calls = []
        naver.route(r"/ncc/campaigns", self._camps)
        naver.route(r"/billing/bizmoney", self._biz)
        naver.route(r"/stats", self._stats)

    def add(self, cid, camps=(), biz=100000.0):
        """camps = [(번호, 상태, 사용자 잠금, 하루 값 함수)]."""
        rows, series = [], {}
        for n, status, lock, fn in camps:
            c = campaign(cid, n)
            c.update(status=status, userLock=lock, delFlag=False, usePeriod=False, sharedBudgetLock=False)
            rows.append(c)
            series[c["nccCampaignId"]] = fn
        self.acc[cid] = {"campaigns": rows, "biz": biz, "series": series}

    def _err(self, call, key):
        hit = self.fail.get((int(call.customer), key))
        return hit

    def _camps(self, call):
        return self._err(call, "camps") or (200, self.acc[int(call.customer)]["campaigns"])

    def _biz(self, call):
        cid = int(call.customer)
        return self._err(call, "biz") or (200, {"customerId": cid, "bizmoney": self.acc[cid]["biz"],
                                                "budgetLock": False, "refundLock": False})

    def _vals(self, cid, cmp, d):
        return self.acc[cid]["series"][cmp](d)

    def _stats(self, call):
        cid = int(call.customer)
        hit = self._err(call, "stats")
        if hit:
            return hit
        rng = json.loads(call.query["timeRange"][0])
        since, until = date.fromisoformat(rng["since"]), date.fromisoformat(rng["until"])
        fields = json.loads(call.query["fields"][0])
        days = [since + timedelta(days=i) for i in range((until - since).days + 1)]
        cyc = cycle_str(self.cycle) if self.cycle is not None else None
        if "timeIncrement" in call.query:
            cmp = call.query["id"][0]
            self.stats_calls.append(("daily", cmp))
            data = []
            for d in days:
                if d in self.drop_days.get(cmp, ()):
                    continue
                v = dict(zip(("impCnt", "clkCnt", "salesAmt", "ccnt"), self._vals(cid, cmp, d)))
                data.append({"dateStart": d.isoformat(), "dateEnd": d.isoformat(), **{f: v[f] for f in fields}})
            return 200, {"data": data, "cycleBaseTm": cyc}
        ids = call.query["ids"]
        self.stats_calls.append(("summary", tuple(ids)))
        data = []
        for cmp in ids:
            tot = [0, 0, 0, 0]
            for d in days:
                for i, x in enumerate(self._vals(cid, cmp, d)):
                    tot[i] += x
            if any(tot):
                v = dict(zip(("impCnt", "clkCnt", "salesAmt", "ccnt"), tot))
                data.append({"id": cmp, **{f: v[f] for f in fields}})
        return 200, {"data": data, "cycleBaseTm": cyc}


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "engine.db")
        self.fc = FakeClock(T0)            # 네이버 · 저장소 · 점검이 같은 시계
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.naver = FakeNaver()
        self.ads = Ads(self.naver)

    def tearDown(self):
        try:
            if self.st is not None:
                self.st.close()
        finally:
            self.dir.cleanup()

    def at(self, t):
        self.fc._now = t
        return t

    def reader(self, **kw):
        return N.NaverReader(creds(), transport=self.naver, clock=self.fc, rng=random.Random(5), **kw)

    def run_check(self, **kw):
        return MO.run_morning(self.reader(), self.st, self.fc.now, **kw)

    def scene(self, confirmed=((11, A),), auto=((12, B),), t=T0, stage_age=timedelta(minutes=5), stages=None,
              extra_accounts=(), ends=None):
        """단계 → 연결 목록 → 사람 판단 → 짝 맞추기(모두 t 전 · 오늘 06:30 뒤) — 점검은 t 에."""
        self.at(t)
        pids = [p for p, _c in confirmed] + [p for p, _c in auto]
        rows = [srow(p, stage=(stages or {}).get(p, "진행중"), end=(ends or {}).get(p)) for p in pids]
        self.st.record_prospects(E.StageSnapshot({r.possibility_id: r for r in rows}, t - stage_age, {}, ()))
        for p, c in auto:
            NAMES[c] = shop(p)
        cids = [c for _p, c in confirmed] + [c for _p, c in auto] + list(extra_accounts)
        self.st.record_accounts(kids(*cids), t - timedelta(minutes=4))
        for p, c in confirmed:
            self.st.record_decision(p, c, "confirmed", 0, t - timedelta(minutes=3))
        erp = FakeErp([E.NaverIdRow(p, M.VENDOR_NAVER, str(c)) for p, c in auto])
        res = L.pair_links(erp, self.st, t - timedelta(minutes=2))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED, res)
        return res

    def standard_ads(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, steady()), (2, "PAUSED", False, quiet)], biz=100000.0)
        self.ads.add(B, [(1, "ELIGIBLE", False, quiet)], biz=0.0)

    def day(self, cid, d=TODAY):
        return self.st.account_day(cid, d)


# ── 순수 조각 ────────────────────────────────────────────────────────
class PureTest(unittest.TestCase):
    def test_window_is_29_days_to_yesterday(self):
        since, until, days = MO.window(TODAY)
        self.assertEqual((until, len(days), days[0], days[-1]), (YDAY, 29, since, YDAY))
        self.assertEqual(until - timedelta(days=28), since)           # 같은 요일 4주 전(어제 − 28일)까지

    def test_complete_through(self):
        c = datetime.combine(TODAY, time(5, 0), tzinfo=KST)
        self.assertEqual(MO.complete_through([c]), YDAY)
        self.assertEqual(MO.complete_through([c, c - timedelta(hours=6)]), YDAY - timedelta(days=1))   # 가장 이른 것
        self.assertEqual(MO.complete_through([datetime.combine(TODAY, time(0, 0), tzinfo=KST)]), YDAY)
        self.assertIsNone(MO.complete_through([c, None]))
        self.assertIsNone(MO.complete_through([]))
        utc = datetime(2026, 9, 28, 20, 0, tzinfo=timezone.utc)   # = 9/29 05:00 KST
        self.assertEqual(MO.complete_through([utc]), YDAY)

    def test_reconcile_fills_only_when_sums_match(self):
        want = [YDAY - timedelta(days=i) for i in (2, 1, 0)]
        days = {want[0].isoformat(): {"impCnt": 5, "clkCnt": 1, "salesAmt": 100, "ccnt": 0},
                want[2].isoformat(): {"impCnt": 5, "clkCnt": None, "salesAmt": 100, "ccnt": 0}}
        got = MO.reconcile(days, {"impCnt": 10, "clkCnt": 1, "salesAmt": 150, "ccnt": 0}, want)
        self.assertEqual(got[want[1]]["impCnt"], 0)       # 5 + 5 = 10 → 빠진 날은 0
        self.assertEqual(got[want[1]]["clkCnt"], 0)       # 1 = 1 → 빠진 날·빈 값 모두 0
        self.assertEqual(got[want[2]]["clkCnt"], 0)
        self.assertIsNone(got[want[1]]["salesAmt"])       # 200 ≠ 150 → 모름 그대로
        self.assertEqual(got[want[1]]["ccnt"], 0)
        # 합계를 모르면(합계 줄 없음) 맞춰 보지 않는다
        self.assertIsNone(MO.reconcile(days, None, want)[want[1]]["impCnt"])
        # 음수가 하나라도 있으면 맞춰 보지 않는다
        neg = {want[0].isoformat(): {"impCnt": -5, "clkCnt": 0, "salesAmt": 0, "ccnt": 0},
               want[2].isoformat(): {"impCnt": 5, "clkCnt": 0, "salesAmt": 0, "ccnt": 0}}
        self.assertIsNone(MO.reconcile(neg, {"impCnt": 0, "clkCnt": 0, "salesAmt": 0, "ccnt": 0}, want)[want[1]]["impCnt"])
        # 참·거짓·무한은 값이 아니다
        odd = {want[0].isoformat(): {"impCnt": True, "clkCnt": float("inf"), "salesAmt": 0, "ccnt": 0}}
        got = MO.reconcile(odd, None, want)
        self.assertEqual((got[want[0]]["impCnt"], got[want[0]]["clkCnt"]), (None, None))

    def test_account_input_unknown_is_not_zero(self):
        r = MO._Reads(campaigns_raw=[], campaigns=(C.CampaignInfo("cmp-1-1", "SHOPPING", "ELIGIBLE", False),),
                      bizmoney={"bizmoney": 5000.0, "budgetLock": False, "refundLock": False})
        _s, _u, want = MO.window(TODAY)
        series = {d: {"impCnt": 10, "clkCnt": 1, "salesAmt": 1000, "ccnt": 0} for d in want}
        series[YDAY - timedelta(days=3)] = {"impCnt": 10, "clkCnt": 1, "salesAmt": None, "ccnt": 0}
        r.series, r.through = {"cmp-1-1": series}, YDAY
        acc, day = MO.account_input(1, r, TODAY, C.DEFAULTS if hasattr(C, "DEFAULTS") else MO.DEFAULTS)
        self.assertIsNone(acc.avg_daily_spend)            # 7일 중 하루 모름 → 평균 없음(0 아님)
        self.assertEqual(acc.yday_spend, 1000.0)
        self.assertEqual(acc.recent_spend, (1000.0, 1000.0, 1000.0))
        self.assertEqual(acc.same_weekday_spend, (1000.0, 1000.0, 1000.0, 1000.0))
        self.assertIs(acc.data_late, False)
        self.assertEqual(acc.campaigns[0].week_imp, 70)
        self.assertEqual((day["yday_imp"], day["yday_clk"], day["data_late"]), (10.0, 1.0, False))

    def test_account_input_picks_the_right_days(self):
        r = MO._Reads(campaigns_raw=[], campaigns=(C.CampaignInfo("cmp-1-1", "SHOPPING", "ELIGIBLE", False),),
                      bizmoney={"bizmoney": 5000.0, "budgetLock": False, "refundLock": False})
        _s, _u, want = MO.window(TODAY)
        series = {d: {"impCnt": 1, "clkCnt": 0, "salesAmt": (YDAY - d).days * 10, "ccnt": 0} for d in want}
        r.series, r.through = {"cmp-1-1": series}, YDAY
        acc, _day = MO.account_input(1, r, TODAY, MO.DEFAULTS)
        self.assertEqual(acc.yday_spend, 0.0)
        self.assertEqual(acc.recent_spend, (20.0, 10.0, 0.0))                   # 오래된 날 먼저
        self.assertEqual(acc.same_weekday_spend, (70.0, 140.0, 210.0, 280.0))   # 어제와 같은 요일 1~4주 전
        self.assertEqual(acc.avg_daily_spend, sum(range(0, 70, 10)) / 7)        # 어제부터 7일
        self.assertEqual(acc.campaigns[0].week_imp, 7)

    def test_account_input_late_uses_earlier_week(self):
        r = MO._Reads(campaigns_raw=[], campaigns=(C.CampaignInfo("cmp-1-1", "SHOPPING", "ELIGIBLE", False),),
                      bizmoney={"bizmoney": 5000.0, "budgetLock": False, "refundLock": False})
        _s, _u, want = MO.window(TODAY)
        series = {d: {"impCnt": 10, "clkCnt": 1, "salesAmt": 700, "ccnt": 0} for d in want}
        series[YDAY] = {"impCnt": 1, "clkCnt": 0, "salesAmt": 1, "ccnt": 0}   # 어제는 덜 들어온 값
        r.series, r.through = {"cmp-1-1": series}, YDAY - timedelta(days=1)
        acc, day = MO.account_input(1, r, TODAY, MO.DEFAULTS)
        self.assertIs(acc.data_late, True)
        self.assertEqual(acc.avg_daily_spend, 700.0)      # 그 앞 7일(모두 다 들어온 날)
        self.assertIsNone(acc.yday_spend)                  # 덜 들어온 어제 값은 쓰지 않는다
        self.assertIsNone(acc.campaigns[0].yday_imp)
        self.assertIsNone(day["yday_spend"])
        r.through = None                                   # 기준 시각을 못 읽음 → 다 들어온 날이 없다
        acc, _day = MO.account_input(1, r, TODAY, MO.DEFAULTS)
        self.assertIsNone(acc.avg_daily_spend)
        self.assertIs(acc.data_late, True)

    def test_campaign_shape(self):
        ok = campaign(A, 1)
        ok.update(userLock=False, delFlag=None)
        self.assertIsNotNone(MO._campaign_infos([ok], A))              # 곁 표지가 비면 「아님」
        for bad in ({"userLock": None}, {"userLock": "false"}, {"status": None}, {"campaignTp": 3},
                    {"customerId": B}, {"nccCampaignId": "grp-1"}, {"usePeriod": "yes"}):
            c = dict(ok, **bad)
            self.assertIsNone(MO._campaign_infos([c], A), bad)
        self.assertIsNone(MO._campaign_infos([ok, dict(ok)], A))        # 같은 번호 두 번


# ── 저장소 판 4 · 이슈 ───────────────────────────────────────────────
class F:
    def __init__(self, rule, code, target, level, facts=()):
        self.rule, self.code, self.target, self.level, self.facts = rule, code, target, level, facts


class StoreIssueTest(Base):
    def put(self, cid=A, pid=11, findings=(), ran=("bizmoney", "link"), not_ran=(), late=False, run=None, **kw):
        rid = run or self.rid
        return self.st.record_account_check(rid, cid, possibility_id=pid, link="confirmed", status="ok",
                                            rules_run=ran, rules_not_run=not_ran, checked_at=self.fc.now(),
                                            findings=findings, data_late=late, **kw)

    def setUp(self):
        super().setUp()
        self.rid = self.st.begin_run(TODAY, T0)

    def test_constants_match_rules(self):
        self.assertEqual(S.ISSUE_STATES, I.STATES)
        self.assertEqual(S.ISSUE_SEVERITIES, set(I.SEVERITIES))
        self.assertEqual(S.ISSUE_EVENTS, set(I.EVENTS))
        self.assertEqual(S.SCHEMA_VERSION, 4)
        self.assertIn(V.CHECK_LINK_MISSING, S.ACCOUNT_STATUSES)

    def test_v3_file_gets_issue_tables(self):
        self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red"),))
        self.st.finish_run(self.rid, "done", T0)
        self.st.close()
        self.st = None
        raw = sqlite3.connect(self.path)
        for t in ("naver_auto_issue", "naver_auto_issue_event"):
            raw.execute(f"DROP TABLE {t}")
        raw.execute("UPDATE naver_auto_meta SET value = '3' WHERE key = 'schema_version'")
        raw.commit()
        raw.close()
        self.st = S.open_writer(self.path, clock=self.fc.now)
        self.assertEqual(self.st.meta("schema_version"), "4")
        self.assertEqual(self.st.issues(), [])
        self.assertEqual(self.st.account_day(A, TODAY)["status"], "ok")       # 옛 자료는 그대로

    def test_one_transaction(self):
        tally = self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red", (("days_left", 0.5),)),))
        self.assertEqual(tally.counts, {"opened": 1})
        [i] = self.st.issues()
        self.assertEqual((i["possibility_id"], i["customer_id"], i["code"], i["target"], i["severity"], i["state"],
                          i["first_seen_on"], i["facts"]),
                         (11, A, "bizmoney_low", f"acc:{A}", "red", "new", TODAY.isoformat(), {"days_left": 0.5}))
        self.assertEqual([e["kind"] for e in self.st.issue_events(i["issue_id"])], ["opened"])
        # 발견 하나가 틀리면 계정 하루치도 이슈도 남지 않는다
        with self.assertRaises(S.StoreRefused):
            self.put(cid=B, pid=12, findings=(F("bizmoney", "bizmoney_low", f"acc:{B}", "red"),
                                              F("period_end", "period_ending", "cmp-x-1", "info")))
        self.assertIsNone(self.st.account_day(B, TODAY))
        self.assertEqual(len(self.st.issues()), 1)

    def test_finding_checks(self):
        bad = (
            F("spend_jump", "spend_up", f"acc:{A}", "yellow"),               # 돌리지 않은 규칙
            F("bizmoney", "bizmoney_low", f"acc:{B}", "red"),                # 다른 계정
            F("bizmoney", "bizmoney_low", "cmp-a-1", "red"),                 # 읽지 않은 캠페인
            F("bizmoney", "bizmoney_low", f"acc:{A}", "critical"),           # 모르는 등급
            F("bizmoney", "Bizmoney", f"acc:{A}", "red"),                    # 코드 모양 아님
            F("bizmoney", "bizmoney_low", f"acc:{A}", "red", (("stage", NAME_MARK),)),         # 이름 같은 글자
            F("bizmoney", "bizmoney_low", f"acc:{A}", "red", (("u", "https://x.example"),)),   # 주소
            F("bizmoney", "bizmoney_low", f"acc:{A}", "red", (("n", None),)),
            F("bizmoney", "bizmoney_low", f"acc:{A}", "red", (("n", float("nan")),)),
        )
        for f in bad:
            with self.assertRaises(S.StoreRefused, msg=f.code):
                self.put(findings=(f,))
        with self.assertRaises(S.StoreRefused):   # 같은 발견 두 번
            self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red"),) * 2)
        self.assertEqual(self.st.issues(), [])
        # 단계 열쇠·코드 목록은 받는다
        self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red",
                             (("stage", "환불중"), ("hints", ("shared-budget-lock",)))),))
        self.assertEqual(self.st.issues()[0]["facts"], {"hints": ["shared-budget-lock"], "stage": "환불중"})

    def test_auto_resolve_rules(self):
        f = F("bizmoney", "bizmoney_low", f"acc:{A}", "yellow")
        self.put(findings=(f,))
        self.put(ran=("link",), not_ran=(("bizmoney", "stats-unread"),))      # 규칙이 안 돎 → 그대로
        self.assertEqual(self.st.issues()[0]["state"], "new")
        self.put(late=True)                                                    # 자료 늦음 → 그대로
        self.put(late=None)                                                    # 모름 = 늦음
        self.assertEqual(self.st.issues()[0]["state"], "new")
        tally = self.put()                                                     # 돌았고 없음 → 🔁
        self.assertEqual(tally.counts, {"auto_resolved": 1})
        self.assertEqual(self.st.issues()[0]["state"], "auto_resolved")
        self.assertEqual(self.st.issues(open_only=True), [])
        tally = self.put(findings=(f,))                                        # 다시 보임 → 🆕 · 다시 생김 1
        self.assertEqual(tally.counts, {"reappeared": 1})
        self.assertEqual((self.st.issues()[0]["state"], self.st.issues()[0]["reappear_count"]), ("new", 1))

    def test_link_rule_resolves_even_when_late(self):
        link = F(I.RULE_LINK, I.CODE_LINK_BROKEN, f"acc:{A}", "red")
        self.put(findings=(link,), ran=("link",))
        biz = F("bizmoney", "bizmoney_low", f"acc:{A}", "yellow")
        self.put(findings=(biz,))
        self.put(ran=("bizmoney", "link"), late=True)
        states = {i["code"]: i["state"] for i in self.st.issues()}
        self.assertEqual(states, {"link_broken": "auto_resolved", "bizmoney_low": "new"})

    def test_other_pair_untouched(self):
        self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "yellow"),))
        self.put(cid=B, pid=12)
        self.assertEqual(self.st.issues()[0]["state"], "new")
        self.put(cid=B, pid=11)                                   # 같은 가망 · 다른 계정 — A 의 이슈는 그대로
        self.assertEqual(self.st.issues()[0]["state"], "new")

    def test_bad_rule_output_refused(self):
        bad = I.Change(I.IssueState("gone", "red", TODAY, TODAY), I.EV_OPENED, None)
        with mock.patch.object(I, "observe", return_value=bad):
            with self.assertRaises(S.StoreRefused):
                self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red"),))
        self.assertIsNone(self.st.account_day(A, TODAY))
        bad = I.Change(I.IssueState("new", "red", TODAY, TODAY), "vanished", None)
        with mock.patch.object(I, "observe", return_value=bad):
            with self.assertRaises(S.StoreRefused):
                self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red"),))
        self.assertEqual(self.st.issues(), [])

    def test_human_refusals_before_rules(self):
        self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red"),))
        iid = self.st.issues()[0]["issue_id"]
        for by, at_ in ((-1, T0), (True, T0), ("0", T0), (0, T0 + timedelta(hours=1)), (0, datetime(2026, 9, 29, 6))):
            with self.assertRaises(S.StoreRefused) as cm:
                self.st.ack_issue(iid, by, at_)
            self.assertNotIsInstance(cm.exception, S.IssueRefused, repr((by, at_)))   # 규칙까지 가기 전에 거절
        self.assertEqual(self.st.issues()[0]["state"], "new")
        self.assertEqual([e["kind"] for e in self.st.issue_events(iid)], ["opened"])

    def test_human_hands(self):
        self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red"),))
        iid = self.st.issues()[0]["issue_id"]
        t = self.at(T0 + timedelta(minutes=5))
        with self.assertRaises(S.IssueRefused) as cm:
            self.st.except_issue(iid, 7, I.ACTOR_OWNER, TODAY + timedelta(days=2), "광고주 휴가", t)
        self.assertEqual(cm.exception.code, I.E_ACTOR)                        # 🔴 는 팀장 이상만
        with self.assertRaises(S.IssueRefused) as cm:
            self.st.except_issue(iid, 3, I.ACTOR_LEAD, TODAY + timedelta(days=7), "광고주 휴가", t)
        self.assertEqual(cm.exception.code, I.E_TOO_LONG)                      # 🔴 는 오늘 포함 7일
        got = self.st.except_issue(iid, 3, I.ACTOR_LEAD, TODAY + timedelta(days=6), "  광고주 휴가 ", t)
        self.assertEqual((got["state"], got["exception_until"], got["exception_severity"]),
                         ("exception", (TODAY + timedelta(days=6)).isoformat(), "red"))
        ev = self.st.issue_events(iid)[-1]
        self.assertEqual((ev["kind"], ev["by_person"], ev["note"], ev["run_id"]), ("excepted", 3, "광고주 휴가", None))
        with self.assertRaises(S.IssueRefused) as cm:
            self.st.ack_issue(iid, 7, t)
        self.assertEqual(cm.exception.code, I.E_NOT_NEW)
        got = self.st.resolve_issue(iid, 0, t)                                   # 대표 = 0번
        self.assertEqual(got["state"], "resolved")
        self.assertEqual(self.st.issue_events(iid)[-1]["by_person"], 0)
        with self.assertRaises(S.IssueRefused) as cm:
            self.st.resolve_issue(iid, 0, t)
        self.assertEqual(cm.exception.code, I.E_NOT_OPEN)
        for bad in ((iid + 99, 0), (iid, -1), (iid, True)):
            with self.assertRaises(S.StoreRefused):
                self.st.ack_issue(*bad, t)
        with self.assertRaises(S.IssueRefused) as cm:
            self.st.except_issue(iid, 0, I.ACTOR_LEAD, TODAY, "", t)
        self.assertEqual(cm.exception.code, I.E_NOTE)
        with self.assertRaises(S.StoreRefused):
            self.st.ack_issue(iid, 0, T0 + timedelta(hours=1))                     # 미래 시각

    def test_reader_cannot_write_issues(self):
        self.put(findings=(F("bizmoney", "bizmoney_low", f"acc:{A}", "red"),))
        r = S.open_reader(self.path)
        try:
            with self.assertRaises(S.StoreRefused):
                r.ack_issue(1, 0, T0)
            self.assertEqual(len(r.issues()), 1)
        finally:
            r.close()

    def test_campaign_rows_in_same_transaction(self):
        camps = [dict(campaign(A, 1), campaignTp="SHOPPING")]
        self.put(campaigns=camps, stats_day=YDAY, stats={f"cmp-{A}-1": {"impCnt": 5, "salesAmt": 100}})
        [row] = self.st.campaign_days(A, YDAY, YDAY)
        self.assertEqual((row["imp_cnt"], row["sales_amt"], row["conv_amt"], row["provisional"]), (5, 100, None, 1))
        with self.assertRaises(S.StoreRefused):
            self.put(stats_day=YDAY, stats={})                                 # 캠페인 없이 통계만

    def test_customer_id_over_limit_refused(self):
        """저장소가 받는 고객 번호 범위 = 이슈 규칙이 받는 범위(15자리 이하) — 규칙 오류가 저장소 밖으로 새지 않는다."""
        big = 10 ** 15
        with self.assertRaises(S.StoreRefused):
            self.put(cid=big)
        with self.assertRaises(S.StoreRefused):
            self.st.record_decision(13, big, "confirmed", 0, self.fc.now())
        self.st.record_decision(13, big - 1, "confirmed", 0, self.fc.now())
        self.assertIsNone(self.st.account_day(A, TODAY))

    def test_campaign_provisional_must_be_bool(self):
        camps = [dict(campaign(A, 1), campaignTp="SHOPPING")]
        for bad in (1, 0, "yes", None):                                        # 잠정 여부는 참·거짓만(한 거래 길)
            with self.assertRaises(S.StoreRefused, msg=repr(bad)):
                self.put(campaigns=camps, stats_day=YDAY, stats={}, provisional=bad)
        self.assertIsNone(self.st.account_day(A, TODAY))
        self.assertEqual(self.st.campaign_days(A, YDAY, YDAY), [])


class UnlinkStoreTest(Base):
    def test_close_after_grace(self):
        self.standard_ads()
        self.scene()
        MO.run_morning(self.reader(), self.st, self.fc.now)
        self.assertEqual({i["code"] for i in self.st.issues(open_only=True)}, {"bizmoney_empty", "running_zero_spend"})
        # 다음 날: 자동 짝이 ① 에서 사라짐(짝 맞추기에 B 없음) — 어제 이어졌으므로 하루 기다린다
        t1 = self.at(T0 + timedelta(days=1))
        self.ads.cycle = datetime.combine(t1.date(), time(5, 0), tzinfo=KST)
        self.st.record_prospects(E.StageSnapshot({11: srow(11), 12: srow(12)}, t1 - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(A, B), t1 - timedelta(minutes=4))
        res = L.pair_links(FakeErp(()), self.st, t1 - timedelta(minutes=2))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)
        out = MO.run_morning(self.reader(), self.st, self.fc.now)
        self.assertEqual(out.counts.get("unlinked_issues", 0), 0)
        self.assertEqual({i["state"] for i in self.st.issues()}, {"new"})
        # 그다음 날에도 없음 → 「연결 해제로 닫힘」
        t2 = self.at(T0 + timedelta(days=2))
        self.ads.cycle = datetime.combine(t2.date(), time(5, 0), tzinfo=KST)
        self.st.record_prospects(E.StageSnapshot({11: srow(11), 12: srow(12)}, t2 - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(A, B), t2 - timedelta(minutes=4))
        L.pair_links(FakeErp(()), self.st, t2 - timedelta(minutes=2))
        out = MO.run_morning(self.reader(), self.st, self.fc.now)
        self.assertEqual(out.counts["unlinked_issues"], 2)
        self.assertEqual({i["state"] for i in self.st.issues()}, {"closed_unlinked"})
        self.assertEqual([e["kind"] for e in self.st.issue_events(self.st.issues()[0]["issue_id"])],
                         ["opened", "closed_unlinked"])
        self.assertFalse(out.alert)

    def test_mass_unlink_alerts(self):
        pairs = tuple((100 + i, 5_000_000 + i) for i in range(12))
        for _p, cid in pairs:
            self.ads.add(cid, [(1, "ELIGIBLE", False, quiet)], biz=0.0)
        self.scene(confirmed=pairs, auto=())
        self.run_check()
        self.assertEqual(len({i["customer_id"] for i in self.st.issues(open_only=True)}), 12)
        for k in (1, 2):
            t = self.at(T0 + timedelta(days=k))
            if k == 1:
                for d in self.st.current_decisions():
                    self.st.revoke_decision(d.decision_id, 0, t - timedelta(minutes=10), "정리")
            self.st.record_accounts(kids(*[c for _p, c in pairs]), t - timedelta(minutes=4))
            self.assertEqual(L.pair_links(FakeErp(), self.st, t - timedelta(minutes=2)).outcome, S.SYNC_ACCEPTED)
            out = self.run_check()
        self.assertIn(MO.CODE_UNLINK_MASS, out.codes)
        self.assertTrue(out.alert)
        self.assertEqual(self.st.issues(open_only=True), [])

    def test_refuses_other_day_pairing(self):
        self.standard_ads()
        res = self.scene()
        rid = self.st.begin_run(TODAY + timedelta(days=1), self.at(T0 + timedelta(days=1)))
        with self.assertRaises(S.StoreRefused):
            self.st.close_unlinked_issues(rid, res.pairing_id, self.fc.now())


# ── 아침 점검 ────────────────────────────────────────────────────────
class MorningHappyTest(Base):
    def test_first_morning(self):
        self.standard_ads()
        self.scene()
        out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE, out)
        self.assertFalse(out.alert, out)
        self.assertEqual(out.counts["targets"], 2)
        a, b = self.day(A), self.day(B)
        self.assertEqual((a["status"], a["link"], a["possibility_id"]), ("ok", "confirmed", 11))
        self.assertEqual((b["status"], b["link"]), ("ok", "auto"))
        self.assertEqual((a["yday_spend"], a["yday_imp"], a["data_late"], a["bizmoney"]), (20000.0, 1000.0, 0, 100000.0))
        self.assertIn("link", a["rules_run"])
        self.assertEqual(a["rules_not_run"], [])
        # 이슈 — A 없음 · B 비즈머니 0(켜진 캠페인)
        # (B 는 진행중인데 최근 3일 0원 — 🟡 도 맞다)
        self.assertEqual([(i["customer_id"], i["code"], i["severity"]) for i in self.st.issues()],
                         [(B, "bizmoney_empty", "yellow"), (B, "running_zero_spend", "yellow")])
        # 어제 캠페인 줄(잠정) — 멈춘 캠페인은 0
        rows = {r["campaign_id"]: r for r in self.st.campaign_days(A, YDAY, YDAY)}
        self.assertEqual(rows[f"cmp-{A}-1"]["sales_amt"], 20000)
        self.assertEqual(rows[f"cmp-{A}-2"]["sales_amt"], 0)
        self.assertEqual(rows[f"cmp-{A}-1"]["provisional"], 1)
        run = self.st.run(out.run_id)
        self.assertEqual((run["status"], run["accounts_total"], run["accounts_ok"]), ("done", 2, 2))
        # 부른 것은 GET 뿐 · 계정마다 제 번호 · 멈춘 캠페인과 합계 0 캠페인은 하루별로 부르지 않는다
        self.assertTrue(all(c.method == "GET" and c.api_key_ok and c.sig_ok for c in self.naver.calls))
        self.assertEqual(sorted(x for k, x in self.ads.stats_calls if k == "daily"),
                         [f"cmp-{A}-1", f"cmp-{B}-1"])   # B 는 켜졌는데 합계 줄이 없어 하루별로 0 확인
        # 판정 — A 🟢(확인한 짝) · B 🟡 + 계정 확인 전
        ja = V.judge(accounts=[V.AccountCheck(A, "confirmed", a["status"], TODAY, tuple(a["rules_not_run"]))],
                     issues=[], now=self.fc.now(), deadline=datetime.combine(TODAY, time(8), tzinfo=KST))
        self.assertEqual(ja.color, V.GREEN)

    def test_personal_and_secret_marks_not_stored(self):
        self.standard_ads()
        self.scene()
        self.run_check()
        self.st._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        raw = b""
        for suffix in ("", "-wal"):
            if os.path.exists(self.path + suffix):
                with open(self.path + suffix, "rb") as f:
                    raw += f.read()
        for mark in (MARK_TRACK, MARK_NEWFIELD, MARK_API_KEY, MARK_SECRET):
            self.assertNotIn(mark.encode(), raw, mark[:6])

    def test_outcome_repr_has_no_numbers(self):
        self.standard_ads()
        self.scene()
        out = self.run_check()
        text = repr(out)
        for n in (str(A), str(B), "20000", "100000"):
            self.assertNotIn(n, text)

    def test_zero_campaigns_is_zero_spend(self):
        self.ads.add(A, [], biz=50000.0)
        self.ads.add(B, [(1, "ELIGIBLE", False, quiet)], biz=0.0)
        self.scene()
        self.run_check()
        a = self.day(A)
        self.assertEqual((a["status"], a["yday_spend"], a["data_late"]), ("ok", 0.0, 0))
        # 진행중인데 최근 3일 0원 → 🟡(캠페인이 없어도 돈이 안 나간 것은 사실)
        self.assertIn("running_zero_spend", {i["code"] for i in self.st.issues() if i["customer_id"] == A})


class ReadinessTest(Base):
    def test_window(self):
        self.standard_ads()
        self.scene()
        self.at(datetime.combine(TODAY, time(6, 29), tzinfo=KST))
        self.assertEqual(self.run_check().codes, (MO.CODE_TOO_EARLY,))
        self.at(datetime.combine(TODAY, time(8, 0), tzinfo=KST))
        out = self.run_check()
        self.assertEqual((out.outcome, out.codes, out.alert), (MO.OUT_REFUSED, (MO.CODE_AFTER_DEADLINE,), False))
        self.assertEqual(self.naver.calls, [])

    def test_accounts_step_must_come_first(self):
        self.standard_ads()
        self.at(T0)
        # 연결 목록을 어제 받고 오늘은 아직 — 짝 맞추기가 오늘이어도 기다린다
        self.st.record_prospects(E.StageSnapshot({11: srow(11)}, T0 - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(A), T0 - timedelta(hours=20))
        self.st.record_decision(11, A, "confirmed", 0, T0 - timedelta(minutes=3))
        L.pair_links(FakeErp(), self.st, T0 - timedelta(minutes=2))
        out = self.run_check()
        self.assertIn(MO.CODE_ACCOUNTS_STEP_PENDING, out.codes)
        self.assertEqual(out.outcome, MO.OUT_REFUSED)
        self.assertFalse(MO.morning_due(self.st, self.fc.now()))
        # 오늘 06:30 뒤 받기를 시도했다(실패여도) → 어제 목록으로 맞춘 짝으로 돈다(경고)
        self.st.record_sync_event(S.SYNC_ACCOUNTS, S.SYNC_FAILED, ("NETWORK",), T0 - timedelta(minutes=1))
        out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE, out)
        self.assertIn(MO.CODE_ACCOUNTS_OLD, out.codes)

    def test_pairing_must_be_today_and_current(self):
        self.standard_ads()
        self.scene()
        # 짝 맞춘 뒤 사람 판단이 바뀜 → 기다림(경보 아님)
        self.st.record_decision(12, B, "rejected", 0, T0 - timedelta(seconds=30))
        out = self.run_check()
        self.assertEqual((out.outcome, out.codes, out.alert), (MO.OUT_REFUSED, (MO.CODE_PAIRING_STALE,), False))
        self.assertEqual(self.naver.calls, [])

    def test_pairing_not_today_alerts(self):
        self.standard_ads()
        self.scene(t=T0)
        t1 = self.at(T0 + timedelta(days=1))
        self.st.record_accounts(kids(A, B), t1 - timedelta(minutes=4))   # 오늘 목록은 받았는데 짝 맞추기가 없음
        out = self.run_check()
        self.assertIn(MO.CODE_PAIRING_NOT_TODAY, out.codes)
        self.assertTrue(out.alert)

    def test_unusable_list_stops_everything(self):
        self.standard_ads()
        self.scene()
        acc = {cid: {"customerId": cid, "adAccountNo": 7777, "adAccountName": "x"} for cid in (A, B)}
        self.st.record_accounts(N.ChildAccounts(acc, {1: 2}, ()), T0 - timedelta(minutes=1))
        out = self.run_check()
        self.assertIn(MO.CODE_ACCOUNTS_UNUSABLE, out.codes)
        self.assertTrue(out.alert)
        self.assertEqual(self.naver.calls, [])

    def test_due(self):
        self.standard_ads()
        self.scene()
        self.assertTrue(MO.morning_due(self.st, self.fc.now()))
        out = self.run_check()
        self.assertFalse(MO.morning_due(self.st, self.fc.now()))            # 오늘 끝남
        self.assertEqual(self.run_check().codes, (MO.CODE_DONE_TODAY,))
        self.assertEqual(out.outcome, MO.OUT_DONE)


class RetryTest(Base):
    def test_failed_run_retries_only_unfinished(self):
        self.standard_ads()
        self.scene()
        self.ads.fail[(B, "stats")] = (500, {"code": 500})
        out = self.run_check()                                              # B 는 통계 서버 오류 → 일부만
        self.assertEqual(self.day(B)["status"], "partial")
        # 첫 회차를 실패로 만들어 본다(예: 속도 제한으로 멈춤) — 같은 날 다시 돌 수 있어야 한다
        self.st._conn.execute("UPDATE naver_auto_check_run SET status = 'failed' WHERE run_id = ?", (out.run_id,))
        self.assertFalse(MO.morning_due(self.st, self.fc.now()))            # 20분 전
        self.fc.advance(21 * 60)
        self.assertTrue(MO.morning_due(self.st, self.fc.now()))
        del self.ads.fail[(B, "stats")]
        before = len(self.naver.calls)
        out2 = self.run_check()
        self.assertEqual(out2.counts["targets"], 1)                         # A(정상)는 다시 읽지 않는다
        self.assertTrue(all(c.customer == str(B) for c in self.naver.calls[before:]))
        self.assertEqual(self.day(B)["status"], "ok")

    def test_three_runs_a_day(self):
        self.standard_ads()
        self.scene()
        for _ in range(3):
            rid = self.st.begin_run(TODAY, self.fc.now())
            self.st.finish_run(rid, "failed", self.fc.now(), error_kind="RUN_ABORT")
            self.fc.advance(60)
        out = self.run_check()
        self.assertEqual(out.codes, (MO.CODE_RUNS_EXHAUSTED,))
        self.assertTrue(out.alert)


class LinkStateTest(Base):
    def morning_of(self, k, present):
        """k 일 뒤 아침 — 연결 목록(present) · 짝 맞추기 · 점검."""
        t = self.at(T0 + timedelta(days=k))
        self.ads.cycle = datetime.combine(t.date(), time(5, 0), tzinfo=KST)
        self.st.record_prospects(E.StageSnapshot({11: srow(11), 12: srow(12)}, t - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(*present), t - timedelta(minutes=4))
        res = L.pair_links(FakeErp([E.NaverIdRow(12, M.VENDOR_NAVER, str(B))]), self.st, t - timedelta(minutes=2))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED, res)
        return self.run_check()

    def test_missing_then_broken_then_back(self):
        self.standard_ads()
        self.scene()
        self.run_check()
        # 첫날 목록에 없음 → ⚪ 오늘 이관 목록에 없음 · 이슈 없음(I2 ⓐ)
        out = self.morning_of(1, (B,))
        d1 = TODAY + timedelta(days=1)
        d = self.day(A, d1)
        self.assertEqual((d["status"], d["link"], d["rules_run"]), ("link_missing", "confirmed", []))
        self.assertIn(("link", "link-missing"), d["rules_not_run"])
        self.assertEqual([i["code"] for i in self.st.issues() if i["customer_id"] == A], [])
        self.assertFalse(out.alert)
        v = V.judge(accounts=[V.AccountCheck(A, "confirmed", d["status"], d1)], issues=[],
                    now=self.fc.now() + timedelta(hours=3), deadline=datetime.combine(d1, time(8), tzinfo=KST))
        self.assertEqual((v.color, v.needs_attention), (V.WHITE, False))   # 마감 뒤에도 확인 필요 아니오
        # 둘째 날(서로 다른 날 · 20시간 넘게) → 이관 빠짐 🔴(I1 ⓐ)
        self.morning_of(2, (B,))
        self.assertEqual(self.day(A, TODAY + timedelta(days=2))["status"], "link_broken")
        [iss] = [i for i in self.st.issues() if i["customer_id"] == A]
        self.assertEqual((iss["code"], iss["severity"], iss["state"], iss["rule"]), ("link_broken", "red", "new", "link"))
        # 다시 이관 → 다음 아침 🔁
        self.morning_of(3, (A, B))
        [iss] = [i for i in self.st.issues() if i["customer_id"] == A]
        self.assertEqual(iss["state"], "auto_resolved")
        self.assertEqual(self.day(A, TODAY + timedelta(days=3))["status"], "ok")

    def test_relisted_but_refused_handle_still_resolves_link(self):
        self.standard_ads()
        self.scene()
        self.run_check()
        self.morning_of(1, (B,))
        self.morning_of(2, (B,))
        self.assertEqual({i["code"] for i in self.st.issues(open_only=True) if i["customer_id"] == A}, {"link_broken"})
        real = H.issue_check_handle

        def refuse(**kw):
            if kw["customer_id"] == A:
                raise H.NotEligible("stage-stale")
            return real(**kw)
        with mock.patch.object(H, "issue_check_handle", side_effect=refuse):
            self.morning_of(3, (A, B))
        [iss] = [i for i in self.st.issues() if i["code"] == "link_broken"]
        self.assertEqual(iss["state"], "auto_resolved")                 # 다시 이관 = 목록에 있음(손잡이와 무관)
        self.assertEqual(self.day(A, TODAY + timedelta(days=3))["status"], "system_gap")

    def test_never_listed_confirmed_is_broken_at_once(self):
        self.standard_ads()
        self.at(T0)
        self.st.record_prospects(E.StageSnapshot({11: srow(11)}, T0 - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(B), T0 - timedelta(minutes=4))
        self.st.record_decision(11, D, "confirmed", 0, T0 - timedelta(minutes=3))   # 목록에 한 번도 없던 계정
        L.pair_links(FakeErp(), self.st, T0 - timedelta(minutes=2))
        out = self.run_check()
        self.assertEqual(self.day(D)["status"], "link_broken")
        [iss] = self.st.issues()
        self.assertEqual((iss["code"], iss["facts"]), ("link_broken", {"reason": "never-listed"}))
        self.assertEqual(self.naver.calls, [])                                       # 이관 상태는 네이버를 부르지 않는다
        self.assertEqual(out.counts["targets"], 0)

    def test_broken_pair_keeps_exception_through_one_day_wobble(self):
        """이관 빠짐 짝이 단계 흔들림으로 하루 사라져도 🙈 예외를 잃지 않는다(하루 기다림 · 검토 issues-grace)."""
        self.standard_ads()
        self.scene()
        self.run_check()
        self.morning_of(1, (B,))
        self.morning_of(2, (B,))
        [iss] = [i for i in self.st.issues() if i["code"] == "link_broken"]
        d2 = TODAY + timedelta(days=2)
        self.st.except_issue(iss["issue_id"], 0, I.ACTOR_LEAD, d2 + timedelta(days=6), "광고주 이관 다시 요청함",
                             self.fc.now())
        # 셋째 날: 가망 11 의 종료일이 40일 전으로 흔들려 관리 대상에서 빠짐 → 짝 줄이 없다
        t3 = self.at(T0 + timedelta(days=3))
        self.ads.cycle = datetime.combine(t3.date(), time(5, 0), tzinfo=KST)
        self.st.record_prospects(E.StageSnapshot({11: srow(11, end=t3.date() - timedelta(days=40)), 12: srow(12)},
                                                 t3 - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(B), t3 - timedelta(minutes=4))
        res = L.pair_links(FakeErp([E.NaverIdRow(12, M.VENDOR_NAVER, str(B))]), self.st, t3 - timedelta(minutes=2))
        self.assertNotIn((11, A), [(r["possibility_id"], r["customer_id"]) for r in self.st.pairing_rows(res.pairing_id)
                                   if r["state"] in ("confirmed", "auto", "missing", "broken")])
        out = self.run_check()
        self.assertEqual(out.counts.get("unlinked_issues", 0), 0)
        self.assertEqual(self.st.issue(iss["issue_id"])["state"], "exception")
        # 넷째 날: 단계가 돌아옴 → 다시 이관 빠짐 · 예외 그대로 · 다시 생김 0
        self.morning_of(4, (B,))
        got = self.st.issue(iss["issue_id"])
        self.assertEqual((got["state"], got["reappear_count"]), ("exception", 0))
        self.assertNotIn("closed_unlinked", [e["kind"] for e in self.st.issue_events(iss["issue_id"])])

    def test_blocked_row_for_same_account_does_not_skip_it(self):
        self.standard_ads()
        self.at(T0)
        self.st.record_prospects(E.StageSnapshot({11: srow(11), 13: srow(13)}, T0 - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(A), T0 - timedelta(minutes=4))
        self.st.record_decision(11, A, "confirmed", 0, T0 - timedelta(minutes=3))
        res = L.pair_links(FakeErp([E.NaverIdRow(13, M.VENDOR_NAVER, str(A))]), self.st, T0 - timedelta(minutes=2))
        rows = self.st.pairing_rows(res.pairing_id)
        self.assertIn(("blocked", 13, A), [(r["state"], r["possibility_id"], r["customer_id"]) for r in rows])
        out = self.run_check()
        self.assertNotIn(MO.CODE_PAIR_DUPLICATE, out.codes)          # 막힘 줄은 짝이 아니다 — 두 짝으로 세지 않는다
        self.assertEqual((self.day(A)["status"], self.day(A)["possibility_id"]), ("ok", 11))

    def test_blocked_rows_are_not_read(self):
        self.standard_ads()
        self.at(T0)
        self.st.record_prospects(E.StageSnapshot({13: srow(13)}, T0 - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(A), T0 - timedelta(minutes=4))
        # ① 에 적힌 번호가 목록의 광고계정 번호 — 막힘(ad-account-number) · 그 번호는 고객 번호가 아니다
        adno = 8_000_000 + A % 1_000_000
        L.pair_links(FakeErp([E.NaverIdRow(13, M.VENDOR_NAVER, str(adno))]), self.st, T0 - timedelta(minutes=2))
        out = self.run_check()
        self.assertEqual(out.counts.get("targets"), 0)
        self.assertIsNone(self.day(adno))
        self.assertEqual(self.st.issues(), [])


class HandleRefusalTest(Base):
    def test_mapping(self):
        self.standard_ads()
        self.scene()
        real = H.issue_check_handle

        def refuse(**kw):
            if kw["customer_id"] == A:
                raise H.NotEligible("stage-stale")
            if kw["customer_id"] == B:
                raise H.NotEligible("ended-over-14-days")
            return real(**kw)
        with mock.patch.object(H, "issue_check_handle", side_effect=refuse):
            out = self.run_check()
        self.assertEqual(self.day(A)["status"], "system_gap")
        self.assertEqual(self.day(B)["status"], "not_eligible")
        self.assertIn(("bizmoney", "ended-over-14-days"), self.day(B)["rules_not_run"])
        self.assertIn(MO.CODE_SYSTEM_GAP, out.codes)
        self.assertTrue(out.alert)
        self.assertEqual(self.naver.calls, [])

    def test_old_stage_is_system_gap_once(self):
        self.standard_ads()
        self.scene(stage_age=timedelta(hours=30))                     # 손잡이(72시간)는 되지만 ⑥ 은 26시간 넘음
        out = self.run_check()
        self.assertEqual({self.day(A)["status"], self.day(B)["status"]}, {"system_gap"})
        self.assertEqual(out.codes.count(MO.CODE_SYSTEM_GAP), 1)     # 경보 한 번(Q4)


class ReadsTest(Base):
    def test_running_campaign_missing_summary_row_is_checked_daily(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, quiet)], biz=50000.0)
        self.ads.add(B, [(1, "ELIGIBLE", False, quiet)], biz=0.0)
        self.ads.drop_days[f"cmp-{A}-1"] = {YDAY - timedelta(days=3)}    # 하루별 한 날 빠짐 → 합계를 모름 → 그날 모름
        self.scene()
        self.run_check()
        a = self.day(A)
        self.assertEqual(a["status"], "partial")                       # 7일 중 하루 모름 → 평균 · 노출 합 없음
        self.assertIn(("bizmoney", "avg-incomplete"), a["rules_not_run"])
        self.assertIn(("no_delivery", "impressions-unknown"), a["rules_not_run"])
        self.assertIn(f"cmp-{A}-1", [x for k, x in self.ads.stats_calls if k == "daily"])

    def test_active_campaign_missing_day_reconciled_by_summary(self):
        self.ads.add(A, [(1, "ELIGIBLE", False, steady())], biz=500000.0)
        self.ads.add(B, [(1, "ELIGIBLE", False, quiet)], biz=0.0)
        gap = YDAY - timedelta(days=10)
        base = steady()
        self.ads.acc[A]["series"][f"cmp-{A}-1"] = lambda d: (0, 0, 0, 0) if d == gap else base(d)
        self.ads.drop_days[f"cmp-{A}-1"] = {gap}                      # 합계와 합이 같다 → 빠진 날은 0
        self.scene()
        self.run_check()
        self.assertEqual(self.day(A)["status"], "ok")

    def test_data_late_still_runs_bizmoney(self):
        self.standard_ads()
        self.ads.cycle = datetime.combine(TODAY, time(0, 0), tzinfo=KST) - timedelta(minutes=1)
        self.ads.acc[A]["biz"] = 10000.0                               # 10000 ÷ 20000 = 0.5일 → 🔴
        self.scene()
        out = self.run_check()
        a = self.day(A)
        self.assertEqual((a["status"], a["data_late"], a["yday_spend"]), ("data_late", 1, None))
        self.assertIn("bizmoney", a["rules_run"])
        self.assertIn(("bizmoney_low", "red"), {(i["code"], i["severity"]) for i in self.st.issues()})
        self.assertIn(MO.CODE_DATA_LATE, out.codes)                  # 판정은 확인 필요 아니오 — 경보로 따로 알린다
        self.assertTrue(out.alert)
        rows = self.st.campaign_days(A, YDAY, YDAY)
        self.assertTrue(rows and all(r["sales_amt"] is None and r["metrics_read"] == 0 for r in rows))   # 덜 들어온 어제

    def test_cycle_unknown_is_not_zero(self):
        self.standard_ads()
        self.ads.cycle = None
        self.scene()
        self.run_check()
        a = self.day(A)
        self.assertEqual((a["status"], a["yday_spend"]), ("partial", None))
        self.assertIn(("bizmoney", "avg-incomplete"), a["rules_not_run"])

    def test_key_rejected_account(self):
        self.standard_ads()
        self.ads.fail[(A, "camps")] = (401, {"code": 1018})
        self.scene()
        self.run_check()
        a = self.day(A)
        self.assertEqual(a["status"], "key_rejected")
        self.assertEqual({(i["code"], i["severity"]) for i in self.st.issues() if i["customer_id"] == A},
                         {("key_rejected", "yellow")})
        self.assertEqual(self.st.campaign_days(A, YDAY, YDAY), [])

    def test_unknown_stats_shape(self):
        self.standard_ads()
        self.ads.fail[(A, "stats")] = (200, {"weird": []})
        self.scene()
        out = self.run_check()
        self.assertEqual(self.day(A)["status"], "partial")
        self.assertIn(MO.CODE_SHAPE_UNKNOWN, out.codes)
        self.assertTrue(out.alert)

    def test_bad_campaign_shape(self):
        self.standard_ads()
        self.ads.acc[A]["campaigns"][0]["userLock"] = "no"
        self.scene()
        out = self.run_check()
        self.assertEqual(self.day(A)["status"], "partial")
        self.assertIn(MO.CODE_SHAPE_UNKNOWN, out.codes)


class DeadlineTest(Base):
    def test_account_crossing_deadline_is_not_written(self):
        self.standard_ads()
        self.scene(t=datetime.combine(TODAY, time(7, 59), tzinfo=KST) + timedelta(seconds=30))
        seen = []

        def tick(call):
            seen.append(call.path)
            if call.path == "/billing/bizmoney":
                self.fc.advance(40)                                    # 첫 계정 읽는 도중 08:00 을 넘김
        self.naver.tick = tick
        out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertIn(MO.CODE_DEADLINE_CUT, out.codes)
        self.assertTrue(out.alert)
        self.assertIsNone(self.day(A))
        self.assertIsNone(self.day(B))
        self.assertEqual(out.counts["deadline_left"], 2)
        self.assertEqual(self.st.run(out.run_id)["error_kind"], MO.CODE_DEADLINE_CUT)
        self.assertEqual(self.st.issues(), [])
        self.assertNotIn("/stats", seen)                               # 마감을 넘긴 뒤로는 부르지 않는다


class DeadlineLastReadTest(Base):
    def test_last_read_finishing_after_deadline_is_not_written(self):
        self.standard_ads()
        self.scene(t=datetime.combine(TODAY, time(7, 59), tzinfo=KST) + timedelta(seconds=30))

        def tick(call):
            if call.path == "/stats" and "timeIncrement" in call.query:
                self.fc.advance(40)                                    # 첫 계정의 마지막 읽기가 08:00 뒤에 끝남
        self.naver.tick = tick
        out = self.run_check()
        self.assertIn(MO.CODE_DEADLINE_CUT, out.codes)
        first = int(next(c.customer for c in self.naver.calls if c.path == "/ncc/campaigns"))
        self.assertIsNone(self.day(first))
        self.assertEqual(out.counts["deadline_left"], 2)
        self.assertEqual(self.st.issues(), [])


class AbortTest(Base):
    def many(self, n):
        pairs = tuple((100 + i, 5_000_000 + i) for i in range(n))
        for _p, cid in pairs:
            self.ads.add(cid, [(1, "ELIGIBLE", False, steady())])
        return pairs

    def test_all_rejected_stops(self):
        pairs = self.many(12)
        for _p, cid in pairs:
            self.ads.fail[(cid, "camps")] = (403, {"code": 1006})
        self.scene(confirmed=pairs, auto=())
        out = self.run_check()
        self.assertEqual((out.outcome, out.alert), (MO.OUT_FAILED, True))
        self.assertIn(MO.CODE_KEY_REJECTED_ALL, out.codes)
        self.assertEqual(sum(1 for c in self.naver.calls), MO.KEY_ALL_MIN)
        self.assertEqual(out.counts["abort_left"], 2)
        self.assertEqual(self.st.run(out.run_id)["status"], "failed")

    def test_some_rejected_goes_on(self):
        pairs = self.many(12)
        self.ads.fail[(pairs[0][1], "camps")] = (403, {"code": 1006})
        self.scene(confirmed=pairs, auto=())
        out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertEqual(out.counts["key_rejected"], 1)

    def test_mostly_rejected_stops_after_fifty(self):
        pairs = self.many(60)
        for _p, cid in pairs[1:]:
            self.ads.fail[(cid, "camps")] = (403, {"code": 1006})
        self.scene(confirmed=pairs, auto=())
        out = self.run_check()
        self.assertEqual((out.outcome, out.alert), (MO.OUT_FAILED, True))
        self.assertIn(MO.CODE_KEY_REJECTED_MANY, out.codes)
        self.assertNotIn(MO.CODE_KEY_REJECTED_ALL, out.codes)
        self.assertEqual(out.counts["key_rejected"], MO.KEY_RATIO_MIN - 1)
        self.assertEqual(out.counts["abort_left"], 60 - MO.KEY_RATIO_MIN)

    def test_store_refusal_is_reported(self):
        self.standard_ads()
        self.scene()
        real = self.st.record_account_check

        def refuse(run_id, cid, **kw):
            if cid == A:
                raise S.StoreRefused("x")
            return real(run_id, cid, **kw)
        with mock.patch.object(self.st, "record_account_check", side_effect=refuse):
            out = self.run_check()
        self.assertIn(MO.CODE_STORE_REFUSED, out.codes)
        self.assertTrue(out.alert)
        self.assertIsNone(self.day(A))
        self.assertEqual(self.day(B)["status"], "ok")
        self.assertEqual(out.counts["store_refused"], 1)

    def test_call_cap_fails_run(self):
        self.standard_ads()
        self.scene()
        out = MO.run_morning(self.reader(max_calls=3), self.st, self.fc.now)
        self.assertEqual((out.outcome, out.alert), (MO.OUT_FAILED, True))
        self.assertIn(MO.CODE_RUN_ABORT, out.codes)
        self.assertEqual(self.st.run(out.run_id)["error_kind"], MO.CODE_RUN_ABORT)

    def test_reader_must_be_fresh(self):
        self.standard_ads()
        self.scene()
        r = self.reader()
        MO.run_morning(r, self.st, self.fc.now)
        with self.assertRaises(ValueError):
            MO.run_morning(r, self.st, self.fc.now)


class OrderTest(Base):
    def test_red_first_then_yesterday_failures(self):
        pairs = ((11, A), (12, B), (13, C_))
        for _p, cid in pairs:
            self.ads.add(cid, [(1, "ELIGIBLE", False, steady())])
        self.scene(confirmed=pairs, auto=())
        # 어제: C 는 점검 안 됨 · B 는 🔴 이슈 열림
        rid = self.st.begin_run(YDAY, self.at(T0 - timedelta(days=1)))
        self.st.record_account_check(rid, C_, possibility_id=13, link="confirmed", status="partial", rules_run=(),
                                     rules_not_run=(("bizmoney", "stats-unread"),), checked_at=self.fc.now())
        self.st.record_account_check(rid, B, possibility_id=12, link="confirmed", status="ok", rules_run=("bizmoney",),
                                     rules_not_run=(), checked_at=self.fc.now(),
                                     findings=(F("bizmoney", "bizmoney_low", f"acc:{B}", "red"),))
        self.st.record_account_check(rid, A, possibility_id=11, link="confirmed", status="ok", rules_run=("bizmoney",),
                                     rules_not_run=(), checked_at=self.fc.now())
        self.st.finish_run(rid, "done", self.fc.now())
        self.at(T0)
        self.run_check()
        self.assertEqual(self.read_order(), [B, C_, A])

    def read_order(self):
        return [int(c.customer) for c in self.naver.calls if c.path == "/ncc/campaigns"]

    def test_cut_at_deadline_comes_first_next_day(self):
        """마감에 잘려 어제 줄이 없는 계정은 다음 날 앞에서 읽는다(매일 같은 꼬리가 잘리지 않게 · 검토 deadline-starvation)."""
        pairs = ((11, A), (12, B), (13, C_))
        for _p, cid in pairs:
            self.ads.add(cid, [(1, "ELIGIBLE", False, steady())])
        self.scene(confirmed=pairs, auto=(), t=datetime.combine(TODAY, time(7, 58), tzinfo=KST))

        def slow(call):
            if call.path == "/ncc/campaigns":
                self.fc.advance(50)                                   # 한 계정 50초 — 셋째 계정은 08:00 을 넘는다
        self.naver.tick = slow
        out = self.run_check()
        self.assertIn(MO.CODE_DEADLINE_CUT, out.codes)
        self.assertIsNone(self.day(C_))
        self.naver.calls.clear()
        t1 = self.at(T0 + timedelta(days=1))
        self.ads.cycle = datetime.combine(t1.date(), time(5, 0), tzinfo=KST)
        self.naver.tick = None
        self.st.record_prospects(E.StageSnapshot({p: srow(p) for p, _c in pairs}, t1 - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(A, B, C_), t1 - timedelta(minutes=4))
        self.assertEqual(L.pair_links(FakeErp(), self.st, t1 - timedelta(minutes=2)).outcome, S.SYNC_ACCEPTED)
        self.run_check()
        self.assertEqual(self.read_order()[0], C_)


class DuplicateTest(Base):
    def test_account_in_two_pairs_is_skipped(self):
        self.standard_ads()
        self.scene()
        real = self.st.pairing_rows

        def twice(pid):
            rows = real(pid)
            extra = dict(rows[0], possibility_id=99)
            return rows + [extra]
        with mock.patch.object(self.st, "pairing_rows", side_effect=twice):
            out = self.run_check()
        self.assertIn(MO.CODE_PAIR_DUPLICATE, out.codes)
        self.assertTrue(out.alert)
        dup = self.st.pairing_rows(self.st.last_pairing("accepted")["pairing_id"])[0]["customer_id"]
        self.assertIsNone(self.day(dup))


# ── 적대 검토 반영(S9) ──────────────────────────────────────────────
class ReviewFixTest(Base):
    def many(self, n, start=100, cid0=5_000_000):
        pairs = tuple((start + i, cid0 + i) for i in range(n))
        for _p, cid in pairs:
            self.ads.add(cid, [(1, "ELIGIBLE", False, steady())])
        return pairs

    def repair(self, t, confirmed=(), auto=(), pids=None):
        """t 에 단계 · 연결 목록 · 짝 맞추기를 다시(점검 전 순서 그대로)."""
        pids = pids or [p for p, _c in confirmed] + [p for p, _c in auto]
        self.st.record_prospects(E.StageSnapshot({p: srow(p) for p in pids}, t - timedelta(minutes=5), {}, ()))
        self.st.record_accounts(kids(*[c for _p, c in confirmed] + [c for _p, c in auto]), t - timedelta(minutes=4))
        res = L.pair_links(FakeErp([E.NaverIdRow(p, M.VENDOR_NAVER, str(c)) for p, c in auto]), self.st,
                           t - timedelta(minutes=2))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED, res)
        return res

    def test_retry_rereads_account_whose_pair_moved_to_other_prospect(self):
        """회차 사이에 계정이 다른 가망 짝으로 바뀌면 다시 도는 회차가 새 짝으로 읽는다(검토 failclosed-retry)."""
        self.standard_ads()
        self.ads.acc[A]["biz"] = 10000.0
        self.scene()
        out = MO.run_morning(self.reader(max_calls=5), self.st, self.fc.now)   # A 를 적은 뒤 B 에서 호출 상한
        self.assertEqual(out.outcome, MO.OUT_FAILED)
        self.assertEqual(self.day(A)["possibility_id"], 11)
        t = self.fc.now() + timedelta(minutes=10)
        self.at(t)
        self.st.record_decision(13, A, "confirmed", 0, t - timedelta(minutes=3))   # 사람이 A 를 가망 13 으로 확인
        NAMES[B] = shop(12)
        self.repair(t, confirmed=((13, A),), auto=((12, B),), pids=[11, 12, 13])   # 판단은 위에서 적음(목록용)
        self.fc.advance(21 * 60)
        self.assertTrue(MO.morning_due(self.st, self.fc.now()))
        out2 = self.run_check()
        self.assertEqual(out2.outcome, MO.OUT_DONE)
        self.assertEqual(self.day(A)["possibility_id"], 13)
        self.assertIn(("bizmoney_low", 13), {(i["code"], i["possibility_id"]) for i in self.st.issues(open_only=True)})

    def test_data_late_rechecked_same_morning(self):
        """자료 늦음으로 끝난 회차 뒤 20분 — 늦은 계정만 다시 읽어 ④⑤⑥ 을 돌린다(검토 failclosed-data-late)."""
        self.standard_ads()
        self.ads.cycle = datetime.combine(TODAY, time(0, 0), tzinfo=KST) - timedelta(minutes=1)
        self.scene()
        out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertEqual((self.day(A)["status"], self.day(B)["status"]), ("data_late", "data_late"))
        self.assertIn(MO.CODE_DATA_LATE, out.codes)
        self.assertFalse(MO.morning_due(self.st, self.fc.now()))            # 20분 전
        self.ads.cycle = datetime.combine(TODAY, time(6, 50), tzinfo=KST)
        self.fc.advance(21 * 60)
        self.assertTrue(MO.morning_due(self.st, self.fc.now()))
        out2 = self.run_check()
        self.assertEqual((out2.outcome, out2.counts["targets"]), (MO.OUT_DONE, 2))
        self.assertNotIn(MO.CODE_DATA_LATE, out2.codes)
        self.assertEqual((self.day(A)["status"], self.day(B)["status"]), ("ok", "ok"))
        self.fc.advance(21 * 60)
        self.assertFalse(MO.morning_due(self.st, self.fc.now()))            # 끝나지 않은 짝이 없다
        self.assertEqual(self.run_check().codes, (MO.CODE_DONE_TODAY,))

    def test_done_run_with_all_ok_is_not_rerun(self):
        self.standard_ads()
        self.scene()
        self.run_check()
        self.fc.advance(21 * 60)
        self.assertFalse(MO.morning_due(self.st, self.fc.now()))
        before = len(self.naver.calls)
        self.assertEqual(self.run_check().codes, (MO.CODE_DONE_TODAY,))
        self.assertEqual(len(self.naver.calls), before)

    def test_stale_cycle_is_late_not_a_crash(self):
        """기준 시각이 창보다 오래되어도 회차가 죽지 않는다 — 그 계정은 자료 늦음 · 평균 없음(검토 stale-cycle)."""
        self.standard_ads()
        self.scene()
        p = {x["possibility_id"]: x for x in self.st.prospects()}[11]
        for days in (22, 23, 40):
            with self.subTest(days=days):
                self.ads.cycle = datetime.combine(TODAY - timedelta(days=days), time(5), tzinfo=KST)
                reads = MO.read_account(self.reader(), H.issue_check_handle(
                    customer_id=A, possibility_id=11, link_state="confirmed", stage=p["stage_key"],
                    stage_as_of=self.st.stage_as_of(), latest_end_date=None, now=self.fc.now()),
                    A, TODAY, self.fc.now, datetime.combine(TODAY, time(8), tzinfo=KST))
                acc, _day = MO.account_input(A, reads, TODAY, MO.DEFAULTS)
                self.assertTrue(acc.data_late)
                if days >= 23:                                        # 평균 7일이 읽은 기간 밖으로 — 모름(0 이 아니다)
                    self.assertIsNone(acc.avg_daily_spend)
                else:
                    self.assertIsNotNone(acc.avg_daily_spend)
        self.ads.cycle = datetime.combine(TODAY - timedelta(days=30), time(5), tzinfo=KST)
        out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertNotIn(MO.CODE_ACCOUNT_ERROR, out.codes)
        self.assertEqual(self.day(A)["status"], "partial")               # 평균 모름 → ③ 못 돌림 → 일부만(늦음보다 앞)
        self.assertNotEqual(self.day(B)["status"], "ok")

    def test_one_account_unexpected_error_is_isolated(self):
        self.standard_ads()
        self.scene()
        real = MO.account_input

        def boom(cid, *a, **k):
            if cid == A:
                raise KeyError("x")
            return real(cid, *a, **k)
        with mock.patch.object(MO, "account_input", side_effect=boom):
            out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertIn(MO.CODE_ACCOUNT_ERROR, out.codes)
        self.assertTrue(out.alert)
        self.assertIsNone(self.day(A))
        self.assertEqual(self.day(B)["status"], "ok")
        self.assertEqual(out.counts["account_error"], 1)

    def test_yesterday_rejected_accounts_do_not_trip_all_rejected(self):
        """어제도 키 거절이던 계정(광고주별)이 맨 앞에 서도 「전 계정 거절」로 멈추지 않는다(검토 key-order)."""
        good = self.many(5, start=300, cid0=6_000_050)                 # 광고계정 번호가 겹치지 않게(가짜 목록 규칙)
        bad = self.many(12, start=100, cid0=5_000_000)
        for _p, cid in bad:
            self.ads.fail[(cid, "camps")] = (403, {"code": 1006})
        self.scene(confirmed=bad + good, auto=())
        out = self.run_check()                                      # 첫날: 가망 번호 순이라 거절 12곳이 먼저 → 멈춤
        self.assertIn(MO.CODE_KEY_REJECTED_ALL, out.codes)
        t = self.at(T0 + timedelta(days=1))
        self.ads.cycle = datetime.combine(t.date(), time(5), tzinfo=KST)
        self.repair(t, confirmed=bad + good)
        yday_status = {cid: self.st.account_day(cid, TODAY) for _p, cid in bad}
        self.assertEqual(sum(1 for v in yday_status.values() if v and v["status"] == "key_rejected"), 10)
        out = self.run_check()
        self.assertNotIn(MO.CODE_KEY_REJECTED_ALL, out.codes)
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertEqual({self.day(c, t.date())["status"] for _p, c in good}, {"ok"})
        # 오늘 처음 거절되는 계정 10곳이면 여전히 멈춘다
        t2 = self.at(T0 + timedelta(days=2))
        self.ads.cycle = datetime.combine(t2.date(), time(5), tzinfo=KST)
        fresh = self.many(10, start=200, cid0=7_000_100)
        for _p, cid in fresh:
            self.ads.fail[(cid, "camps")] = (403, {"code": 1006})
        for fp, fc in fresh:
            self.st.record_decision(fp, fc, "confirmed", 0, t2 - timedelta(minutes=3))
        self.repair(t2, confirmed=bad + fresh + good)
        self.assertIn(MO.CODE_KEY_REJECTED_ALL, self.run_check().codes)

    def test_key_abort_sample_is_rechecked_by_retry(self):
        """전체 키 거절로 멈춘 회차가 적은 「키 거절」 계정은 다시 도는 회차가 다시 읽는다(검토 retry-skips-key)."""
        pairs = self.many(12)
        for _p, cid in pairs:
            self.ads.fail[(cid, "camps")] = (403, {"code": 1006})
        self.scene(confirmed=pairs, auto=())
        out = self.run_check()
        self.assertIn(MO.CODE_KEY_REJECTED_ALL, out.codes)
        self.assertEqual(len(self.st.issues(open_only=True)), 10)
        self.ads.fail.clear()
        self.fc.advance(21 * 60)
        self.assertTrue(MO.morning_due(self.st, self.fc.now()))
        out2 = self.run_check()
        self.assertEqual((out2.outcome, out2.counts["targets"]), (MO.OUT_DONE, 12))
        self.assertEqual({self.day(c)["status"] for _p, c in pairs}, {"ok"})
        self.assertEqual({i["code"] for i in self.st.issues(open_only=True)}, set())

    def test_naver_outage_stops_and_retry_rereads(self):
        """네이버 서버 오류가 몰리면 회차를 멈추고 알린다 · 20분 뒤 다시 읽는다(검토 server-outage)."""
        pairs = self.many(12)
        for _p, cid in pairs:
            self.ads.fail[(cid, "camps")] = (503, {"code": 503})
        self.scene(confirmed=pairs, auto=())
        out = self.run_check()
        self.assertEqual((out.outcome, out.alert), (MO.OUT_FAILED, True))
        self.assertIn(MO.CODE_NAVER_UNAVAILABLE, out.codes)
        self.assertEqual(self.st.run(out.run_id)["error_kind"], MO.CODE_NAVER_UNAVAILABLE)
        self.ads.fail.clear()
        self.fc.advance(21 * 60)
        self.assertTrue(MO.morning_due(self.st, self.fc.now()))
        out2 = self.run_check()
        self.assertEqual(out2.outcome, MO.OUT_DONE)
        self.assertEqual({self.day(c)["status"] for _p, c in pairs}, {"ok"})

    def test_few_server_errors_do_not_stop(self):
        pairs = self.many(12)
        self.ads.fail[(pairs[0][1], "camps")] = (503, {"code": 503})
        self.scene(confirmed=pairs, auto=())
        out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertNotIn(MO.CODE_NAVER_UNAVAILABLE, out.codes)
        self.assertEqual(self.day(pairs[0][1])["status"], "partial")

    def test_not_ready_late_alerts(self):
        """마감 30분 전까지 준비가 안 되면 경보(짝 맞추기 낡음처럼 경보 없는 막힘도 · 검토 pairing-stale)."""
        self.standard_ads()
        self.scene()
        t = self.at(datetime.combine(TODAY, time(7, 0), tzinfo=KST))
        self.st.record_accounts(kids(A, B), t)                   # 새 연결 목록 → 짝 맞추기가 낡음
        r = MO.readiness(self.st, t)
        self.assertEqual(r.codes, (MO.CODE_PAIRING_STALE,))
        self.assertFalse(set(r.codes) & MO.ALERTING)
        r = MO.readiness(self.st, self.at(datetime.combine(TODAY, time(7, 29), tzinfo=KST)))
        self.assertNotIn(MO.CODE_NOT_READY_LATE, r.codes)
        r = MO.readiness(self.st, self.at(datetime.combine(TODAY, time(7, 30), tzinfo=KST)))
        self.assertIn(MO.CODE_NOT_READY_LATE, r.codes)
        self.assertTrue(set(r.codes) & MO.ALERTING)
        self.assertFalse(r.ready)
        out = self.run_check()
        self.assertEqual((out.outcome, out.alert), (MO.OUT_REFUSED, True))

    def test_stuck_running_run_is_closed_next_time(self):
        """회차가 죽으면서 닫기도 실패하면 — 다음에 부를 때 실패로 닫고 돈다(검토 stuck-running)."""
        self.standard_ads()
        self.scene()
        with mock.patch.object(self.st, "record_account_check", side_effect=S.StoreError("disk")), \
                mock.patch.object(self.st, "finish_run", side_effect=S.StoreError("disk")):
            with self.assertRaises(S.StoreError):
                self.run_check()
        [run] = self.st.runs_on(TODAY)
        self.assertEqual(run["status"], "running")
        self.assertEqual(self.st.my_running_runs(), [run["run_id"]])
        self.fc.advance(21 * 60)
        self.assertTrue(MO.morning_due(self.st, self.fc.now()))
        out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertIn(MO.CODE_RUN_ORPHANED, out.codes)
        self.assertTrue(out.alert)
        old = self.st.run(run["run_id"])
        self.assertEqual((old["status"], old["error_kind"]), ("failed", MO.CODE_RUN_ORPHANED))
        self.assertEqual(self.st.my_running_runs(), [])

    def test_other_process_running_run_still_blocks(self):
        self.standard_ads()
        self.scene()
        # 다른 프로세스가 시작한 회차(이 저장소가 시작한 것이 아니다) — 닫지 않고 기다린다
        self.st._conn.execute("INSERT INTO naver_auto_check_run (run_date, started_at, status) VALUES (?, ?, 'running')",
                              (TODAY.isoformat(), self.fc.now().isoformat()))
        self.assertFalse(MO.morning_due(self.st, self.fc.now()))
        self.assertEqual(self.run_check().codes, (MO.CODE_RUN_RUNNING,))

    def test_bad_customer_id_row_does_not_stop_run(self):
        """규칙이 받지 않는 고객 번호 줄 하나가 회차 전체를 멈추지 않는다(검토 oversized-customer-id)."""
        self.standard_ads()
        self.scene()
        real = self.st.pairing_rows

        def with_bad(pid):
            rows = real(pid)
            return rows + [dict(rows[0], state="broken", possibility_id=77, customer_id=10 ** 15, link="confirmed",
                                code=S.PAIR_CODE_NEVER_LISTED)]
        with mock.patch.object(self.st, "pairing_rows", side_effect=with_bad):
            out = self.run_check()
        self.assertEqual(out.outcome, MO.OUT_DONE)
        self.assertIn(MO.CODE_STORE_REFUSED, out.codes)
        self.assertEqual((self.day(A)["status"], self.day(B)["status"]), ("ok", "ok"))


if __name__ == "__main__":
    unittest.main()
