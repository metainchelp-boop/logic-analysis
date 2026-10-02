"""S8 시험 — 네이버 연결 목록 동기화 · 확인 짝 브레이크 · 짝 맞추기 · 연결 끊김 · 사람 판단 해석 (설계 v1.8 S8).

가짜 네이버(``fake_naver`` — 진짜 읽기 관문을 그대로 쓴다) · 가짜 ① 읽기로만 돈다 — 네트워크 0.
짝 규칙은 ``backend/app/naver_auto/matching.py`` 를 그대로 쓴다.
"""
from __future__ import annotations

import os
import pathlib
import random
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone

ENGINE = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ENGINE.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import matching as M  # noqa: E402
from app.naver_auto import verdict as V  # noqa: E402

from naver_engine import erp_read as E  # noqa: E402
from naver_engine import handles as H  # noqa: E402
from naver_engine import links as L  # noqa: E402
from naver_engine import naver_read as N  # noqa: E402
from naver_engine import store as S  # noqa: E402
from naver_engine import sync as Y  # noqa: E402
from naver_engine.credentials import ManagerCredentials, Secret  # noqa: E402
from naver_engine.tests.fake_naver import (AGENCY_ID, MARK_API_KEY, MARK_NEWFIELD, MARK_OWNER,  # noqa: E402
                                           MARK_SECRET, Agency, FakeClock, FakeNaver)

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 9, 29, 6, 40, tzinfo=KST)   # 화요일 아침 점검 시각
NAME_MARK = "표지상회"
A, B, C, D = 1234567, 2345678, 3456789, 4567890   # 고객 번호(지어낸 것)


def srow(pid, name, stage="진행중", end=None, unreadable=False):
    return E.StageRow(pid, stage, name, end, unreadable)


def stages(rows, as_of):
    return E.StageSnapshot({r.possibility_id: r for r in rows}, as_of, {}, ())


def kids(*accs, per=None):
    """(고객 번호, 광고계정 번호, 이름) — 들어와서는 안 되는 칸(ownerNaverId)도 함께 넣는다."""
    acc = {cid: {"customerId": cid, "adAccountNo": no, "adAccountName": name, "ownerNaverId": MARK_OWNER}
           for cid, no, name in accs}
    return N.ChildAccounts(acc, {1: len(acc)} if per is None else per, ())


def many(n, start=5_000_000):
    return [(start + i, 8_000_000 + i, f"계정{i}") for i in range(n)]


def nid(pid, raw, vendor=M.VENDOR_NAVER):
    return E.NaverIdRow(pid, vendor, raw)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeErp:
    """``ErpReader`` 대신 — 부른 횟수를 센다. 값이 예외면 던진다."""

    def __init__(self, ids=()):
        self.ids, self.calls = ids, 0

    def read_naver_customer_ids(self):
        self.calls += 1
        if isinstance(self.ids, BaseException):
            raise self.ids
        return tuple(self.ids)


class FakeReader:
    """``NaverReader`` 대신(오류 갈래만) — ``list_all_children`` 가 던질 것을 정한다."""

    def __init__(self, result):
        self.result, self.calls, self.pauses = result, 0, 0

    def manager_handle(self):
        return "mh"

    def list_all_children(self, mh):
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "engine.db")
        self.clock = Clock(T0)
        self.st = S.open_writer(self.path, clock=self.clock)

    def tearDown(self):
        try:
            if self.st is not None:
                self.st.close()
        finally:
            self.dir.cleanup()

    def at(self, t):
        self.clock.t = t
        return t

    def reopen(self):
        self.st.close()
        self.st = S.open_writer(self.path, clock=self.clock)

    # 기본 장면 — 확인한 짝 · 자동 짝 · 막힘 · 이름 후보 · 관리 대상 밖
    def seed(self, t=T0, with_decision=True):
        self.at(t)
        self.st.record_prospects(stages([
            srow(11, "메타상회"), srow(12, "하늘꽃집", "전략관리"), srow(13, "바다수산", "사후관리"),
            srow(14, "끝난가게", "계약만료", end=t.date() - timedelta(days=20)), srow(15, "푸른들판", "홀딩중"),
        ], t - timedelta(minutes=5)))
        self.st.record_accounts(kids((A, 7654321, "메타상회"), (B, 8765432, "하늘꽃집"), (C, 9876543, "푸른들판"),
                                     (D, 6543210, "끝난가게")), t - timedelta(minutes=2))
        if with_decision:
            self.did = self.st.record_decision(11, A, "confirmed", 0, t - timedelta(minutes=1))
        return FakeErp([nid(12, "2345678"), nid(13, "9999999"), nid(14, "4567890"), nid(15, None)])

    def rows(self, pairing_id):
        return [(r["state"], r["possibility_id"], r["customer_id"], r["code"]) for r in self.st.pairing_rows(pairing_id)]

    def pair(self, erp=None, t=None):
        if t is not None:
            self.at(t)
        return L.pair_links(erp or FakeErp(), self.st, self.clock.t)


# ── 연결 목록 동기화 ─────────────────────────────────────────────────
def creds():
    return ManagerCredentials(AGENCY_ID, Secret(MARK_API_KEY), Secret(MARK_SECRET))


class SyncAccountsTest(Base):
    def reader(self, sizes=(30, 5)):
        naver = FakeNaver()
        agency = Agency(naver, sizes=sizes)
        return N.NaverReader(creds(), transport=naver, clock=FakeClock(self.clock.t), rng=random.Random(3)), naver, agency

    def test_accepted_through_real_gate_keeps_only_three_fields(self):
        r, naver, _ = self.reader()
        res = L.sync_accounts(r, self.st, self.clock.t)
        self.assertEqual((res.kind, res.outcome, res.rows, res.alert), (S.SYNC_ACCOUNTS, S.SYNC_ACCEPTED, 35, False))
        self.assertEqual(len(self.st.accounts()), 35)
        self.assertTrue(naver.calls and all(c.method == "GET" for c in naver.calls))
        self.st._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        raw = b""
        for suffix in ("", "-wal"):
            if os.path.exists(self.path + suffix):
                with open(self.path + suffix, "rb") as f:
                    raw += f.read()
        for mark in (MARK_OWNER, MARK_NEWFIELD, MARK_API_KEY, MARK_SECRET):
            self.assertNotIn(mark.encode(), raw, mark[:6])
        self.assertEqual(self.st.accounts_read_at(), self.clock.t)
        self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS)["outcome"], S.SYNC_ACCEPTED)

    def test_reader_must_be_fresh(self):
        r, _n, _a = self.reader()
        L.sync_accounts(r, self.st, self.clock.t)
        with self.assertRaises(ValueError):
            L.sync_accounts(r, self.st, self.at(T0 + timedelta(hours=1)))
        for bad in (FakeReader(kids()), ):
            bad.pauses = 1
            with self.assertRaises(ValueError):
                L.sync_accounts(bad, self.st, self.clock.t)
        with self.assertRaises(ValueError):
            L.sync_accounts(FakeReader(kids()), self.st, datetime(2026, 9, 29, 7))   # 시간대 없는 시각

    def test_failures_become_results_and_write_nothing(self):
        cases = (
            (N.IncompleteList("x"), L.CODE_INCOMPLETE),
            (N.NaverApiError(N.KIND_KEY_REJECTED, "/manager-accounts", 401, None), "KEY_REJECTED-401"),
            (N.NaverApiError(N.KIND_NETWORK, "/manager-accounts", None, None), "NETWORK"),
            (N.RunAbort("call-cap"), L.CODE_RUN_ABORT),
            (H.HandleInvalid("x"), L.CODE_HANDLE_INVALID),
            (ValueError("x"), Y.CODE_UNEXPECTED),
            (RecursionError("x"), Y.CODE_UNEXPECTED),
        )
        for i, (exc, code) in enumerate(cases):
            with self.subTest(code=code):
                res = L.sync_accounts(FakeReader(exc), self.st, self.at(T0 + timedelta(minutes=i)))
                self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_FAILED, (code,), True))   # 받은 적 없음 → 알림
                self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS)["codes"], [code])
        self.assertEqual(self.st.accounts(), [])
        self.assertIsNone(self.st.accounts_read_at())

    def test_programming_errors_surface(self):
        for exc in (TypeError("x"), N.WriteForbidden("x"), N.PathForbidden("x")):
            with self.subTest(exc=type(exc).__name__):
                with self.assertRaises(type(exc)):
                    L.sync_accounts(FakeReader(exc), self.st, self.clock.t)

    def test_failure_alert_only_when_long(self):
        L.sync_accounts(FakeReader(kids(*many(20))), self.st, self.clock.t)
        res = L.sync_accounts(FakeReader(N.IncompleteList("x")), self.st, self.at(T0 + timedelta(hours=25)))
        self.assertFalse(res.alert)
        res = L.sync_accounts(FakeReader(N.IncompleteList("x")), self.st, self.at(T0 + timedelta(hours=26)))
        self.assertTrue(res.alert)

    def test_store_refusal_is_result(self):
        k = kids(*many(20))
        k.accounts[5_000_000]["customerId"] = 5_000_001   # 줄의 고객 번호가 열쇠와 다름
        res = L.sync_accounts(FakeReader(k), self.st, self.clock.t)
        self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_REFUSED, (Y.CODE_STORE_REFUSED,), True))
        self.assertEqual(self.st.accounts(), [])

    def test_clock_behind_does_not_read_naver_and_alerts_once(self):
        """저장된 목록 시각이 지금보다 미래 — 더 이른 목록은 받지 않으므로 네이버를 읽지 않는다(검토 sync-3)."""
        L.sync_accounts(FakeReader(kids(*many(20))), self.st, self.at(T0 + timedelta(hours=3)))
        first = FakeReader(kids(*many(20)))
        res = L.sync_accounts(first, self.st, self.at(T0))                                  # 시계를 뒤로
        self.assertEqual((res.outcome, res.codes, res.alert, first.calls), (S.SYNC_FAILED, (L.CODE_CLOCK_BEHIND,), True, 0))
        self.assertFalse(L.accounts_due(self.st, T0 + timedelta(minutes=29)))              # 30분 간격은 그대로
        self.assertTrue(L.accounts_due(self.st, T0 + timedelta(minutes=30)))
        again = FakeReader(kids(*many(20)))
        res = L.sync_accounts(again, self.st, self.at(T0 + timedelta(minutes=30)))
        self.assertEqual((res.outcome, res.codes, res.alert, again.calls), (S.SYNC_FAILED, (L.CODE_CLOCK_BEHIND,), False, 0))
        self.assertEqual(self.st.accounts_read_at(), T0 + timedelta(hours=3))
        self.assertFalse(L.accounts_due(self.st, T0 + timedelta(hours=3, minutes=5)))      # 시계가 따라잡으면 평소대로

    def test_unusable_list_accepted_with_alert(self):
        """광고계정 번호가 없거나 겹친 계정 — 받되 알린다(짝 맞추기는 그 목록으로 ① 을 부르지 않는다 · 검토 pairing-002)."""
        accs = many(20)
        cases = ([(A, None, "메타상회")] + accs, [(A, accs[0][1], "메타상회")] + accs)   # 번호 없음 · 겹침
        for i, rows in enumerate(cases):
            with self.subTest(i=i):
                res = L.sync_accounts(FakeReader(kids(*rows)), self.st, self.at(T0 + timedelta(hours=i)))
                self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_ACCEPTED, (L.CODE_ACCOUNTS_UNUSABLE,), True))
        res = L.sync_accounts(FakeReader(kids(*accs)), self.st, self.at(T0 + timedelta(hours=2)))
        self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_ACCEPTED, (), False))

    def test_confirm_reports_unusable_list(self):
        big = many(100)
        L.sync_accounts(FakeReader(kids(*big)), self.st, self.clock.t)
        res = L.sync_accounts(FakeReader(kids((A, None, "메타상회"), *big[:60])), self.st, self.at(T0 + timedelta(days=1)))
        self.assertEqual(res.outcome, S.SYNC_BRAKED)
        ok = L.confirm_accounts(self.st, self.clock.t, 0, res.hold_id)
        self.assertEqual((ok.outcome, ok.codes, ok.alert), (S.SYNC_ACCEPTED, (S.CODE_CONFIRMED, L.CODE_ACCOUNTS_UNUSABLE), True))

    def test_manager_number_out_of_range_is_data_not_programming_error(self):
        """네이버가 준 관리계정 번호가 경로 허용 모양(15자리) 밖 — 관문의 안전 거절이 아니라 실패 결과(검토 sync-2)."""
        for bad in (10 ** 15, 10 ** 20):
            with self.subTest(bad=bad):
                r, naver, agency = self.reader()
                agency.managers[0]["managerAccountNo"] = bad
                res = L.sync_accounts(r, self.st, self.clock.t)
                self.assertEqual((res.outcome, res.codes), (S.SYNC_FAILED, (L.CODE_INCOMPLETE,)))
                self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS)["codes"], [L.CODE_INCOMPLETE])
                self.assertFalse(any("/child-ad-accounts" in c.path for c in naver.calls))
        r, _n, agency = self.reader()
        agency.managers[0]["managerAccountNo"] = 10 ** 15 - 1   # 15자리까지는 받는다
        self.assertEqual(r.list_manager_accounts(r.manager_handle())[0]["managerAccountNo"], 10 ** 15 - 1)

    def test_brake_holds_and_confirm_takes_held_list_without_reading(self):
        L.sync_accounts(FakeReader(kids(*many(100))), self.st, self.clock.t)
        t1 = self.at(T0 + timedelta(days=1))
        res = L.sync_accounts(FakeReader(kids(*many(60))), self.st, t1)
        self.assertEqual((res.outcome, res.needs_confirmation, res.alert, res.absent), (S.SYNC_BRAKED, True, True, 40))
        self.assertIn(S.BRAKE_TOTAL, res.codes)
        self.assertEqual(sum(a["present"] for a in self.st.accounts()), 100)            # 아무것도 적지 않았다
        self.assertEqual({a["absent_days"] for a in self.st.accounts()}, {0})            # 멈춘 날은 세지 않는다
        self.assertFalse(L.accounts_due(self.st, self.at(t1 + timedelta(hours=1))))       # 붙잡음이 열려 있으면 안 부른다
        ok = L.confirm_accounts(self.st, self.clock.t, 0, res.hold_id)
        self.assertEqual((ok.outcome, ok.codes, ok.rows, ok.absent), (S.SYNC_ACCEPTED, (S.CODE_CONFIRMED,), 60, 40))
        self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS)["confirmed_by"], 0)
        again = L.confirm_accounts(self.st, self.clock.t, 0, res.hold_id)
        self.assertEqual(again.codes, (S.HOLD_USED,))
        for bad in (None, 0, -1, True, "1", res.hold_id + 1):
            with self.subTest(bad=bad):
                self.assertEqual(L.confirm_accounts(self.st, self.clock.t, 0, bad).codes[0],
                                 S.HOLD_USED if bad == res.hold_id else S.HOLD_NOT_FOUND)
        for who in (-1, True, "0", None):
            with self.assertRaises(ValueError):
                L.confirm_accounts(self.st, self.clock.t, who, res.hold_id)

    def test_confirm_refuses_hold_with_unknown_codes(self):
        L.sync_accounts(FakeReader(kids(*many(10))), self.st, self.clock.t)
        t = self.at(T0 + timedelta(minutes=1))   # 받을 수 있는 모양의 목록(11곳 · 더 새 시각) — 코드만 모르는 것
        rows = ",".join('[%d,%d,"x"]' % (cid, no) for cid, no, _n in many(11))
        body = '{"read_at":"%s","rows":[%s],"per":{"1":11}}' % (t.isoformat(timespec="microseconds"), rows)
        hid = self.st._refuse_and_hold(S.SYNC_ACCOUNTS, t.isoformat(timespec="microseconds"), S.SYNC_REFUSED,
                                       ["OTHER"], body)
        res = L.confirm_accounts(self.st, self.clock.t, 0, hid)
        self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_REFUSED, (Y.CODE_STORE_REFUSED,), True))
        self.assertEqual(sum(a["present"] for a in self.st.accounts()), 10)

    def test_confirm_expired_and_superseded(self):
        L.sync_accounts(FakeReader(kids(*many(100))), self.st, self.clock.t)
        res = L.sync_accounts(FakeReader(kids(*many(60))), self.st, self.at(T0 + timedelta(days=1)))
        late = L.confirm_accounts(self.st, self.at(T0 + timedelta(days=1, hours=3, minutes=1)), 0, res.hold_id)
        self.assertEqual(late.codes, (S.HOLD_EXPIRED,))
        res2 = L.sync_accounts(FakeReader(kids(*many(60))), self.st, self.at(T0 + timedelta(days=1, hours=4)))
        L.sync_accounts(FakeReader(kids(*many(100))), self.st, self.at(T0 + timedelta(days=1, hours=5)))   # 확인 없이 받음
        self.assertEqual(L.confirm_accounts(self.st, self.clock.t, 0, res2.hold_id).codes, (S.HOLD_SUPERSEDED,))


class ConfirmedBrakeTest(Base):
    """확인한 짝이 있는 계정만 따로 센다 — 전체·관리계정 분모로는 안 보이는 급감(S7 뒤 조각 몫 ⑵)."""

    def manage(self, pids, **kw):
        self.st.record_prospects(stages([srow(p, f"가게{p}", **kw) for p in pids], self.clock.t - timedelta(minutes=5)))

    def setup_confirmed(self, n_total=1000, n_confirmed=60):
        accs = many(n_total)
        self.manage(list(range(100, 300)))
        self.st.record_accounts(kids(*accs), self.clock.t)
        for i in range(n_confirmed):
            self.st.record_decision(100 + i, accs[i][0], "confirmed", 0, self.clock.t)
        return accs

    def test_confirmed_drop_brakes_when_total_does_not(self):
        accs = self.setup_confirmed()
        res = L.sync_accounts(FakeReader(kids(*accs[15:])), self.st, self.at(T0 + timedelta(days=1)))
        self.assertEqual((res.outcome, res.codes), (S.SYNC_BRAKED, (S.BRAKE_CONFIRMED,)))   # 15/1000 은 전체로 안 보인다
        ok = L.confirm_accounts(self.st, self.clock.t, 0, res.hold_id)
        self.assertEqual(ok.outcome, S.SYNC_ACCEPTED)

    def test_under_threshold_accepted(self):
        accs = self.setup_confirmed()
        res = L.sync_accounts(FakeReader(kids(*accs[12:])), self.st, self.at(T0 + timedelta(days=1)))   # 12 = 60 의 20%
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)

    def test_only_live_confirmations_count(self):
        accs = self.setup_confirmed(n_confirmed=0)
        # 한 계정을 두 가망에 확인(뒤 것만 산다) · 확인을 거둠 · 아님 — 산 확인만 센다
        for i in range(15):
            self.st.record_decision(100 + i, accs[i][0], "confirmed", 0, self.clock.t)
            self.st.record_decision(200 + i, accs[i][0], "confirmed", 0, self.clock.t)   # 같은 계정 → 1 로 센다
        for i in range(15, 45):
            d = self.st.record_decision(100 + i, accs[i][0], "confirmed", 0, self.clock.t)
            self.st.revoke_decision(d, 0, self.clock.t, "거둠")
        for i in range(45, 90):
            self.st.record_decision(100 + i, accs[i][0], "rejected", 0, self.clock.t)
        # 산 확인 15곳 중 15곳이 빠짐 → 멈춤(거둔·아님 계정은 분모에 없다)
        res = L.sync_accounts(FakeReader(kids(*accs[15:])), self.st, self.at(T0 + timedelta(days=1)))
        self.assertEqual(res.codes, (S.BRAKE_CONFIRMED,))
        # 거둔·아님 계정만 빠지면 멈추지 않는다
        res = L.sync_accounts(FakeReader(kids(*(accs[:15] + accs[90:]))), self.st, self.at(T0 + timedelta(days=1, hours=4)))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)

    def test_confirmations_outside_management_do_not_dilute(self):
        """끝난 광고주·단계 목록에서 빠진 가망의 옛 확인은 분모에 넣지 않는다(검토 rules-1)."""
        accs = many(1000)
        self.st.record_prospects(stages(
            [srow(p, f"가게{p}") for p in range(100, 160)]                                        # 관리 중 60
            + [srow(p, f"끝남{p}", "계약만료", end=T0.date() - timedelta(days=20)) for p in range(300, 340)]   # 끝난 지 20일
            + [srow(p, f"충돌{p}", end=None, unreadable=True) for p in range(400, 420)],          # 종료일 못 읽음
            T0 - timedelta(minutes=5)))
        self.st.record_accounts(kids(*accs), self.clock.t)
        for i in range(60):
            self.st.record_decision(100 + i, accs[i][0], "confirmed", 0, self.clock.t)
        for j, pid in enumerate(list(range(300, 340)) + list(range(400, 420)) + list(range(500, 540))):   # 목록에 없음 40
            self.st.record_decision(pid, accs[100 + j][0], "confirmed", 0, self.clock.t)
        res = L.sync_accounts(FakeReader(kids(*accs[15:])), self.st, self.at(T0 + timedelta(days=1)))   # 관리 중 15/60 빠짐
        self.assertEqual((res.outcome, res.codes), (S.SYNC_BRAKED, (S.BRAKE_CONFIRMED,)))

    def test_account_moved_to_unmanaged_prospect_not_counted(self):
        """관리 중 가망에 확인했다가 끝난 가망에 더 늦게 확인한 계정 — 산 확인은 끝난 가망 것이라 세지 않는다(밀린 확인은 안 셈)."""
        accs = many(1000)
        self.st.record_prospects(stages([srow(p, f"가게{p}") for p in range(100, 160)]
                                        + [srow(p, f"끝남{p}", "계약만료", end=T0.date() - timedelta(days=20))
                                           for p in range(300, 360)], T0 - timedelta(minutes=5)))
        self.st.record_accounts(kids(*accs), self.clock.t)
        for i in range(60):
            self.st.record_decision(100 + i, accs[i][0], "confirmed", 0, self.clock.t)
        for i in range(15):   # 앞 15곳은 끝난 가망으로 옮겨 확인(뒤 확인이 산다)
            self.st.record_decision(300 + i, accs[i][0], "confirmed", 0, self.clock.t)
        res = L.sync_accounts(FakeReader(kids(*accs[15:])), self.st, self.at(T0 + timedelta(days=1)))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)   # 관리 중 45곳은 그대로 — 옮긴 15곳은 분모에도 빠짐에도 없다

    def test_managed_rule_is_the_handle_rule(self):
        self.st.record_prospects(stages([srow(100, "가"), srow(101, "나", "홀딩중"),
                                         srow(102, "다", end=T0.date() - timedelta(days=14)),   # 끝난 지 14일 — 아직 관리
                                         srow(103, "라", end=T0.date() - timedelta(days=15)),   # 15일 — 관리 밖
                                         srow(105, "바", unreadable=True)],
                                        T0 - timedelta(minutes=5)))
        got = self.st._managed_prospects(self.st._conn, T0)
        self.assertEqual(got, {100, 101, 102})

    def test_already_absent_confirmed_not_counted(self):
        accs = self.setup_confirmed(n_confirmed=20)
        L.sync_accounts(FakeReader(kids(*accs[10:])), self.st, self.at(T0 + timedelta(days=1)))   # 10/20 = 50% — 그러나
        self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS)["outcome"], S.SYNC_BRAKED)            # 10 이상 · 20% 초과 → 멈춤
        self.st.confirm_accounts_hold(self.st.hold(S.SYNC_ACCOUNTS)["hold_id"], 0)
        # 이미 빠진 10곳은 다시 빠져도 세지 않는다 — 남은 10곳 중 2곳만 빠짐
        res = L.sync_accounts(FakeReader(kids(*accs[12:])), self.st, self.at(T0 + timedelta(days=2)))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)


class AccountsDueTest(Base):
    def test_window_and_retry(self):
        self.assertFalse(L.accounts_due(self.st, datetime(2026, 9, 29, 0, 0, tzinfo=KST)))
        self.assertTrue(L.accounts_due(self.st, datetime(2026, 9, 29, 0, 1, tzinfo=KST)))
        self.assertTrue(L.accounts_due(self.st, datetime(2026, 9, 28, 15, 1, tzinfo=timezone.utc)))   # = KST 00:01
        L.sync_accounts(FakeReader(kids(*many(10))), self.st, self.at(datetime(2026, 9, 29, 6, 31, tzinfo=KST)))
        self.assertFalse(L.accounts_due(self.st, self.at(datetime(2026, 9, 29, 23, 0, tzinfo=KST))))   # 오늘 받음
        self.assertFalse(L.accounts_due(self.st, self.at(datetime(2026, 9, 30, 0, 0, tzinfo=KST))))
        self.assertTrue(L.accounts_due(self.st, self.at(datetime(2026, 9, 30, 0, 1, tzinfo=KST))))

    def test_failed_retry_after_30_minutes(self):
        t = self.at(datetime(2026, 9, 29, 6, 40, tzinfo=KST))
        L.sync_accounts(FakeReader(N.IncompleteList("x")), self.st, t)
        self.assertFalse(L.accounts_due(self.st, t + timedelta(minutes=29)))
        self.assertTrue(L.accounts_due(self.st, t + timedelta(minutes=30)))

    def test_accepted_before_start_does_not_count_for_today(self):
        L.sync_accounts(FakeReader(kids(*many(10))), self.st, self.at(datetime(2026, 9, 29, 0, 0, tzinfo=KST)))
        self.assertTrue(L.accounts_due(self.st, self.at(datetime(2026, 9, 29, 0, 30, tzinfo=KST))))

    def braked(self):
        big = many(100)
        L.sync_accounts(FakeReader(kids(*big)), self.st, self.at(datetime(2026, 9, 28, 6, 40, tzinfo=KST)))
        t = self.at(datetime(2026, 9, 29, 6, 40, tzinfo=KST))
        res = L.sync_accounts(FakeReader(kids(*big[:50])), self.st, t)
        self.assertEqual(res.outcome, S.SYNC_BRAKED)
        return t, res, big

    def test_hold_blocks_until_it_expires(self):
        t, res, big = self.braked()
        self.assertFalse(L.accounts_due(self.st, t + timedelta(hours=1)))
        self.assertFalse(L.accounts_due(self.st, t + S.HOLD_TTL))
        self.assertTrue(L.accounts_due(self.st, t + S.HOLD_TTL + timedelta(seconds=1)))   # 확인하지 않은 붙잡음은 3시간
        again = L.sync_accounts(FakeReader(kids(*big[:50])), self.st, self.at(t + S.HOLD_TTL + timedelta(seconds=1)))
        self.assertEqual(again.outcome, S.SYNC_BRAKED)                                     # 다시 읽으면 새 붙잡음
        self.assertNotEqual(again.hold_id, res.hold_id)

    def test_confirmed_hold_no_longer_blocks(self):
        t, res, _big = self.braked()
        L.confirm_accounts(self.st, self.at(t + timedelta(minutes=10)), 0, res.hold_id)
        self.assertFalse(L.accounts_due(self.st, t + timedelta(hours=1)))                  # 오늘 받음
        self.assertTrue(L.accounts_due(self.st, datetime(2026, 9, 30, 6, 40, tzinfo=KST)))  # 다음 날 평소대로

    def test_superseded_hold_no_longer_blocks(self):
        t, res, big = self.braked()
        self.st.record_accounts(kids(*big), self.at(t + timedelta(minutes=10)))           # 멈추지 않는 목록이 붙잡음을 밀어냄
        self.assertIsNotNone(self.st.hold(S.SYNC_ACCOUNTS)["used_at"])
        self.assertFalse(L.accounts_due(self.st, t + timedelta(hours=1)))                  # 오늘 받음(붙잡음 때문이 아님)
        self.assertTrue(L.accounts_due(self.st, datetime(2026, 9, 30, 6, 40, tzinfo=KST)))

    def test_clock_moved_back(self):
        L.sync_accounts(FakeReader(N.IncompleteList("x")), self.st, self.at(datetime(2026, 9, 29, 8, 0, tzinfo=KST)))
        self.assertTrue(L.accounts_due(self.st, datetime(2026, 9, 29, 7, 0, tzinfo=KST)))   # 기록이 5분 넘게 미래
        with self.assertRaises(ValueError):
            L.accounts_due(self.st, datetime(2026, 9, 29, 7, 0))


# ── 연결 끊김 ────────────────────────────────────────────────────────
class LinkStateTest(Base):
    def state_on(self, reads, decision_at=None):
        """``reads`` = [(시각, A 가 목록에 있나)] — 마지막 뒤 A 의 짝 상태."""
        self.at(reads[0][0])
        self.st.record_prospects(stages([srow(11, "메타상회")], reads[0][0] - timedelta(minutes=5)))
        self.st.record_decision(11, A, "confirmed", 0, reads[0][0] - timedelta(minutes=5))
        for t, present in reads:
            self.at(t)
            accs = [(B, 8765432, "다른")] + ([(A, 7654321, "메타상회")] if present else [])
            self.st.record_accounts(kids(*accs), t)
        self.at(reads[-1][0] + timedelta(minutes=1))
        self.st.record_prospects(stages([srow(11, "메타상회")], self.clock.t))
        res = self.pair()
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED, res)
        return [r[:2] + (r[3],) for r in self.rows(res.pairing_id) if r[1] == 11]

    def test_first_day_missing(self):
        got = self.state_on([(T0, True), (T0 + timedelta(days=1), False)])
        self.assertEqual(got, [(S.PAIR_MISSING, 11, None)])

    def test_two_days_20_hours_broken(self):
        got = self.state_on([(T0, True), (T0 + timedelta(days=1), False), (T0 + timedelta(days=2), False)])
        self.assertEqual(got, [(S.PAIR_BROKEN, 11, None)])

    def test_exactly_20_hours_across_two_dates_broken(self):
        d1 = datetime(2026, 9, 30, 6, 0, tzinfo=KST)
        got = self.state_on([(T0, True), (d1, False), (d1 + timedelta(hours=20), False)])   # 10/1 02:00
        self.assertEqual(got, [(S.PAIR_BROKEN, 11, None)])

    def test_just_under_20_hours_missing(self):
        d1 = datetime(2026, 9, 30, 6, 0, tzinfo=KST)
        got = self.state_on([(T0, True), (d1, False), (d1 + timedelta(hours=19, minutes=59), False)])
        self.assertEqual(got, [(S.PAIR_MISSING, 11, None)])

    def test_around_midnight_is_not_two_days(self):
        got = self.state_on([(T0, True), (datetime(2026, 9, 29, 23, 50, tzinfo=KST), False),
                             (datetime(2026, 9, 30, 0, 10, tzinfo=KST), False)])
        self.assertEqual(got, [(S.PAIR_MISSING, 11, None)])   # 날짜는 둘이지만 20분

    def test_long_span_same_date_is_not_two_days(self):
        got = self.state_on([(datetime(2026, 9, 28, 23, 0, tzinfo=KST), True),
                             (datetime(2026, 9, 29, 0, 30, tzinfo=KST), False),
                             (datetime(2026, 9, 29, 20, 45, tzinfo=KST), False)])
        self.assertEqual(got, [(S.PAIR_MISSING, 11, None)])   # 20시간 넘지만 같은 날짜

    def test_braked_day_does_not_advance(self):
        self.at(T0)
        self.st.record_prospects(stages([srow(11, "메타상회")], T0 - timedelta(minutes=5)))
        self.st.record_decision(11, A, "confirmed", 0, T0 - timedelta(minutes=5))
        big = many(100)
        self.st.record_accounts(kids((A, 7654321, "메타상회"), *big), T0)
        self.st.record_accounts(kids(*big), self.at(T0 + timedelta(days=1)))            # 첫날 빠짐(받음)
        res = L.sync_accounts(FakeReader(kids(*big[:50])), self.st, self.at(T0 + timedelta(days=2)))
        self.assertEqual(res.outcome, S.SYNC_BRAKED)                                     # 둘째 날은 멈춤
        self.st.record_prospects(stages([srow(11, "메타상회")], self.clock.t))
        out = self.pair()
        self.assertIn((S.PAIR_MISSING, 11, A, None), self.rows(out.pairing_id))          # 멈춘 날 때문에 끊김이 되지 않는다
        self.assertEqual(self.st.account_times()[A]["absent_days"], 1)

    def test_reappears_then_confirmed_again_and_clock_resets(self):
        reads = [(T0, True), (T0 + timedelta(days=1), False), (T0 + timedelta(days=2), False),
                 (T0 + timedelta(days=3), True)]
        got = self.state_on(reads)
        self.assertEqual(got, [(S.PAIR_CONFIRMED, 11, "same")])
        t = self.st.account_times()[A]
        self.assertEqual((t["present"], t["absent_days"], t["absent_since"], t["absent_last_at"]), (1, 0, None, None))
        self.assertEqual(t["last_seen_at"], T0 + timedelta(days=3))

    def test_reappearance_through_confirmed_hold_resets_clock(self):
        """빠졌던 계정이 멈춘 뒤 대표가 확인한 목록으로 돌아와도 시각이 지워진다 — 자정 앞뒤 20분이 끊김이 되지 않게(검토 rules-3)."""
        self.at(T0)
        self.st.record_prospects(stages([srow(11, "메타상회")], T0 - timedelta(minutes=5)))
        self.st.record_decision(11, A, "confirmed", 0, T0 - timedelta(minutes=5))
        big = many(100)
        self.st.record_accounts(kids((A, 7654321, "메타상회"), *big), T0)
        self.st.record_accounts(kids(*big), self.at(T0 + timedelta(days=1)))                       # A 빠짐(받음)
        t2 = self.at(T0 + timedelta(days=2))
        res = L.sync_accounts(FakeReader(kids((A, 7654321, "메타상회"), *big[:50])), self.st, t2)   # A 돌아옴 · 멈춤
        self.assertEqual(res.outcome, S.SYNC_BRAKED)
        L.confirm_accounts(self.st, self.at(t2 + timedelta(minutes=10)), 0, res.hold_id)
        t = self.st.account_times()[A]
        self.assertEqual((t["present"], t["absent_since"], t["absent_last_at"], t["last_seen_at"]), (1, None, None, t2))
        for when in (datetime(2026, 10, 2, 23, 50, tzinfo=KST), datetime(2026, 10, 3, 0, 10, tzinfo=KST)):
            self.st.record_accounts(kids(*big[:50]), self.at(when))
        self.st.record_prospects(stages([srow(11, "메타상회")], self.clock.t))
        out = self.pair()
        self.assertIn((S.PAIR_MISSING, 11, A, None), self.rows(out.pairing_id))

    def test_absence_through_confirmed_hold_moves_clock(self):
        self.at(T0)
        big = many(100)
        self.st.record_accounts(kids((A, 7654321, "메타상회"), *big), T0)
        t1 = self.at(T0 + timedelta(days=1))
        res = L.sync_accounts(FakeReader(kids(*big[:50])), self.st, t1)                             # A 도 빠짐 · 멈춤
        L.confirm_accounts(self.st, self.at(t1 + timedelta(minutes=10)), 0, res.hold_id)
        t = self.st.account_times()[A]
        self.assertEqual((t["absent_since"], t["absent_last_at"], t["absent_days"]), (t1, t1, 1))

    def test_never_listed_confirmed_account_is_broken(self):
        self.at(T0)
        self.st.record_prospects(stages([srow(11, "메타상회")], T0 - timedelta(minutes=5)))
        self.st.record_accounts(kids((B, 8765432, "다른")), T0 - timedelta(minutes=1))
        self.st.record_decision(11, A, "confirmed", 0, T0)
        out = self.pair()
        self.assertEqual([r for r in self.rows(out.pairing_id) if r[1] == 11],
                         [(S.PAIR_BROKEN, 11, A, L.CODE_NEVER_LISTED)])

    def test_link_state_function(self):
        base = {"present": 0, "absent_days": 2, "absent_since": T0, "absent_last_at": T0 + timedelta(hours=20)}
        self.assertEqual(L.link_state(base), (S.PAIR_BROKEN, None))
        self.assertEqual(L.link_state(None), (S.PAIR_BROKEN, L.CODE_NEVER_LISTED))
        for change in ({"absent_days": 1}, {"absent_since": None}, {"absent_last_at": None}, {"present": 1},
                       {"absent_last_at": T0 + timedelta(hours=19, minutes=59, seconds=59)}):
            with self.subTest(change=change):
                self.assertEqual(L.link_state(dict(base, **change)), (S.PAIR_MISSING, None))

    def test_old_account_without_time_row_is_missing(self):
        # 옛 판(2) 파일 — 계정 시각 표가 없고 이미 여러 날 빠져 있던 계정: 시각을 모르면 끊김으로 올리지 않는다
        self.at(T0)
        self.st.record_prospects(stages([srow(11, "메타상회")], T0 - timedelta(minutes=5)))
        self.st.record_decision(11, A, "confirmed", 0, T0 - timedelta(minutes=5))
        self.st.record_accounts(kids((B, 8765432, "다른")), T0 - timedelta(minutes=1))
        self.st.close()
        self.st = None
        raw = sqlite3.connect(self.path)
        raw.execute("""INSERT INTO naver_auto_account (customer_id, ad_account_no, account_name, present, first_seen_on,
                       last_seen_on, absent_days, last_absent_on) VALUES (?, 7654321, 'x', 0, '2026-09-20', '2026-09-24',
                       5, '2026-09-29')""", (A,))
        raw.execute("DROP TABLE naver_auto_account_time")
        raw.execute("UPDATE naver_auto_meta SET value = '2' WHERE key = 'schema_version'")
        raw.commit()
        raw.close()
        self.reopen_fresh()
        self.assertEqual(self.st.meta("schema_version"), str(S.SCHEMA_VERSION))
        self.assertEqual(self.st.account_times()[A]["absent_since"], None)
        out = self.pair()
        self.assertIn((S.PAIR_MISSING, 11, A, None), self.rows(out.pairing_id))
        # 그 뒤 첫 읽기부터 센다 — 24시간 간격 두 번이면 끊김(검토 rules-4)
        d1 = self.at(datetime(2026, 9, 30, 6, 40, tzinfo=KST))
        self.st.record_accounts(kids((B, 8765432, "다른")), d1)
        self.assertEqual(self.st.account_times()[A]["absent_since"], d1)
        self.st.record_prospects(stages([srow(11, "메타상회")], self.at(d1 + timedelta(minutes=1))))
        self.assertIn((S.PAIR_MISSING, 11, A, None), self.rows(self.pair().pairing_id))
        d2 = self.at(d1 + timedelta(days=1))
        self.st.record_accounts(kids((B, 8765432, "다른")), d2)
        self.st.record_prospects(stages([srow(11, "메타상회")], self.at(d2 + timedelta(minutes=1))))
        self.assertIn((S.PAIR_BROKEN, 11, A, None), self.rows(self.pair().pairing_id))
        self.assertEqual(self.st.account_times()[A]["absent_since"], d1)

    def reopen_fresh(self):
        self.st = S.open_writer(self.path, clock=self.clock)


# ── 짝 맞추기 ────────────────────────────────────────────────────────
class PairLinksTest(Base):
    def test_ad_account_only_export_is_paired_with_canonical_customer(self):
        self.seed()
        res = self.pair(FakeErp([E.NaverIdRow(12, M.VENDOR_NAVER, None, "8765432")]))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)
        self.assertIn((S.PAIR_AUTO, 12, B, "same"), self.rows(res.pairing_id))

    def test_new_identifier_conflict_is_saved_without_account_join(self):
        self.seed()
        res = self.pair(FakeErp([E.NaverIdRow(12, M.VENDOR_NAVER, str(A), "8765432")]))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)
        self.assertIn((S.PAIR_BLOCKED, 12, None, M.B_IDENTIFIER_CONFLICT), self.rows(res.pairing_id))

    def test_accepted_rows_and_counts(self):
        erp = self.seed()
        res = self.pair(erp)
        self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_ACCEPTED, (), False))
        self.assertEqual(erp.calls, 1)
        self.assertEqual(sorted(self.rows(res.pairing_id)), sorted([
            (S.PAIR_CONFIRMED, 11, A, "same"),
            (S.PAIR_AUTO, 12, B, "same"),
            (S.PAIR_BLOCKED, 13, 9999999, M.B_NOT_LINKED),
            (S.PAIR_CANDIDATE, 15, C, "same"),
        ]))
        self.assertEqual(res.counts, {"prospects": 4, "ignored": 2, "confirmed": 1, "auto": 1, "missing": 0, "broken": 0,
                                      "blocked": 1, "candidate": 1, "superseded": 0})   # 14 = 관리 대상 밖 · 15 = 번호 빈칸
        conf = [r for r in self.st.pairing_rows(res.pairing_id) if r["state"] == S.PAIR_CONFIRMED][0]
        self.assertEqual(conf["decision_id"], self.did)
        cand = [r for r in self.st.pairing_rows(res.pairing_id) if r["state"] == S.PAIR_CANDIDATE][0]
        self.assertEqual((cand["same_name"], cand["claimed_elsewhere"]), (1, False))
        run = self.st.pairing_run(res.pairing_id)
        self.assertEqual((run["accounts_read_at"], run["stages_as_of"]), (self.st.accounts_read_at(), self.st.stage_as_of()))
        self.assertEqual(run["decisions_hash"], self.st.decision_fingerprint())

    def test_scope_uses_handle_rule(self):
        erp = self.seed()
        t = self.clock.t
        # 끝난 지 14일(그날 포함)까지는 들어간다 · 15일째는 안 들어간다 · 종료일 못 읽음 · 단계 겹침 · 목록에 없음도 안 들어간다
        # (관제 밖 단계는 저장소가 처음부터 받지 않는다 — 단계 7개 표기만 읽는다)
        snap_ = E.StageSnapshot({r.possibility_id: r for r in (
            srow(11, "메타상회", end=t.date() - timedelta(days=14)), srow(12, "하늘꽃집", "계약만료", end=t.date() - timedelta(days=15)),
            srow(13, "바다수산", unreadable=True))}, t, {}, (15,))
        self.st.record_prospects(snap_)
        res = self.pair(erp)
        got = self.rows(res.pairing_id)
        self.assertEqual(got, [(S.PAIR_CONFIRMED, 11, A, "same")])
        self.assertEqual(res.counts["prospects"], 1)
        for pid, stage, end in ((11, "진행중", t.date() - timedelta(days=14)), (12, "계약만료", t.date() - timedelta(days=15))):
            self.assertEqual(H.eligibility_reason(stage, t, end, t) is None, pid == 11)

    def test_eligibility_reason_matches_handle_issue(self):
        t = T0
        cases = (("진행중", t - timedelta(hours=1), None), ("계약 만료", t, t.date()), ("계약만료", t, None),
                 ("영업중", t, None), ("진행중", t - timedelta(hours=73), None), ("진행중", t + timedelta(minutes=6), None),
                 ("진행중", t, t.date() - timedelta(days=15)), ("진행중", datetime(2026, 9, 29), None))
        for stage, as_of, end in cases:
            with self.subTest(stage=stage, as_of=as_of, end=end):
                reason = H.eligibility_reason(stage, as_of, end, t)
                try:
                    H.issue_check_handle(customer_id=A, possibility_id=11, link_state=H.LINK_CONFIRMED, stage=stage,
                                         stage_as_of=as_of, latest_end_date=end, now=t)
                    issued = None
                except H.NotEligible as e:
                    issued = e.reason
                self.assertEqual(reason, issued)
        with self.assertRaises(ValueError):
            H.eligibility_reason("진행중", t, None, datetime(2026, 9, 29))

    def test_inputs_missing_or_stale_refused_before_calling_erp(self):
        erp = FakeErp()
        res = self.pair(erp)
        self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_REFUSED, (L.CODE_ACCOUNTS_NONE, L.CODE_STAGES_NONE), True))
        self.assertEqual(erp.calls, 0)
        self.assertEqual(self.st.last_pairing()["outcome"], S.SYNC_REFUSED)
        self.seed()
        res = self.pair(erp, t=T0 + timedelta(hours=30, minutes=1))
        self.assertEqual(res.codes, (L.CODE_ACCOUNTS_STALE,))
        self.st.record_accounts(kids((A, 7654321, "메타상회")), self.clock.t)
        res = self.pair(erp, t=T0 + timedelta(hours=72, minutes=1))
        self.assertEqual(res.codes, (L.CODE_ACCOUNTS_STALE, L.CODE_STAGES_STALE))
        self.assertEqual(erp.calls, 0)

    def test_future_inputs_are_stale(self):
        erp = self.seed(t=T0 + timedelta(hours=2))
        res = self.pair(erp, t=T0 + timedelta(hours=1, minutes=45))   # 시계를 뒤로 고침 — 입력이 5분 넘게 미래
        self.assertEqual(res.codes, (L.CODE_ACCOUNTS_STALE, L.CODE_STAGES_STALE))
        self.assertEqual(erp.calls, 0)

    def test_prospect_gone_from_list_not_paired(self):
        erp = self.seed()
        t = self.at(self.clock.t + timedelta(minutes=1))
        self.st.record_prospects(stages([srow(11, "메타상회"), srow(13, "바다수산", "사후관리"),
                                         srow(15, "푸른들판", "홀딩중")], t))   # 12 가 목록에서 빠짐(단계 칸은 남는다)
        res = self.pair(erp)
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)
        self.assertNotIn(12, [r[1] for r in self.rows(res.pairing_id)])
        self.assertEqual(res.counts["prospects"], 3)

    def test_input_age_boundaries(self):
        erp = self.seed()
        read_at, stage_at = self.st.accounts_read_at(), self.st.stage_as_of()
        res = self.pair(erp, t=read_at + L.ACCOUNTS_MAX_AGE)                             # 30시간 그대로면 쓴다
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)
        # 단계는 점검 손잡이 한도(72시간)까지 쓴다 — 연결 목록 한도(30시간)와 다르다
        self.st.record_accounts(kids((A, 7654321, "메타상회")), self.at(stage_at + timedelta(hours=60)))
        res = self.pair(FakeErp(erp.ids), t=stage_at + H.STAGE_MAX_AGE)
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED)
        res = self.pair(FakeErp(erp.ids), t=stage_at + H.STAGE_MAX_AGE + timedelta(seconds=1))
        self.assertEqual(res.codes, (L.CODE_STAGES_STALE,))

    def test_erp_failures(self):
        for i, (exc, code) in enumerate(((E.ErpError("status", E.PATH_NAVER_IDS, 503), "status-503"),
                                         (E.ErpIncomplete("bad-shape", E.PATH_NAVER_IDS, 200), "bad-shape-200"),
                                         (E.ErpError("network", E.PATH_NAVER_IDS), "network"),
                                         (ValueError("x"), Y.CODE_UNEXPECTED))):
            with self.subTest(code=code):
                if i == 0:
                    self.seed()
                res = self.pair(FakeErp(exc), t=T0 + timedelta(minutes=i))
                self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_FAILED, (code,), True))
                self.assertEqual(self.st.last_pairing()["codes"], [code])
        ok = self.pair(self.seed(t=T0 + timedelta(hours=1)))
        self.assertEqual(ok.outcome, S.SYNC_ACCEPTED)
        res = self.pair(FakeErp(E.ErpError("network", E.PATH_NAVER_IDS)), t=T0 + timedelta(hours=26))
        self.assertFalse(res.alert)                                                   # 받은 지 26시간 전이면 아직
        res = self.pair(FakeErp(E.ErpError("network", E.PATH_NAVER_IDS)), t=T0 + timedelta(hours=27))
        self.assertTrue(res.alert)

    def test_unusable_account_list_refused_before_calling_erp(self):
        """광고계정 번호 없음·겹침 — 짝 규칙이 거절할 목록으로 ① 을 두드리지 않고 · 다시 맞출 때로 치지 않는다(검토 pairing-002)."""
        for i, rows in enumerate((((A, None, "메타상회"), (B, 8765432, "하늘꽃집")),
                                  ((A, 8765432, "메타상회"), (B, 8765432, "하늘꽃집")))):
            with self.subTest(i=i):
                self.seed(t=T0 + timedelta(hours=i))
                self.st.record_accounts(kids(*rows), self.at(T0 + timedelta(hours=i, minutes=1)))
                erp = FakeErp([nid(12, "2345678")])
                res = self.pair(erp)
                self.assertEqual((res.outcome, res.codes, res.alert, erp.calls),
                                 (S.SYNC_REFUSED, (L.CODE_ACCOUNTS_UNUSABLE,), True, 0))
                for m in (31, 90, 600):   # 하루 내내 다시 맞출 때가 아니다(① 을 30분마다 두드리지 않는다)
                    self.assertFalse(L.pairing_due(self.st, T0 + timedelta(hours=i, minutes=m)))

    def test_bad_input_refused(self):
        erp = self.seed()
        orig = M.match

        def boom(*a, **k):
            raise M.BadInput("x")
        L.M.match = boom
        try:
            res = self.pair(erp)
        finally:
            L.M.match = orig
        self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_REFUSED, (L.CODE_BAD_INPUT,), True))

    def test_reader_must_be_fresh(self):
        erp = self.seed()
        erp.calls = 1
        with self.assertRaises(ValueError):
            self.pair(erp)

    def test_superseded_latest_confirmation_wins(self):
        erp = self.seed()
        d2 = self.st.record_decision(12, A, "confirmed", 3, self.clock.t)   # A 를 12 에 더 늦게 확인
        res = self.pair(erp)
        rows = self.rows(res.pairing_id)
        self.assertIn((S.PAIR_CONFIRMED, 12, A, "different"), rows)
        self.assertIn((S.PAIR_SUPERSEDED, 11, A, None), rows)
        self.assertNotIn(11, [r[1] for r in rows if r[0] in S.PAIR_CHECKABLE])
        sup = [r for r in self.st.pairing_rows(res.pairing_id) if r["state"] == S.PAIR_SUPERSEDED][0]
        self.assertEqual(sup["decision_id"], self.did)
        self.st.revoke_decision(d2, 0, self.clock.t, "잘못 누름")
        res = self.pair(FakeErp(erp.ids), t=self.clock.t + timedelta(minutes=31))
        self.assertIn((S.PAIR_CONFIRMED, 11, A, "same"), self.rows(res.pairing_id))       # 앞 확인이 다시 산다

    def test_superseded_outside_scope_not_listed(self):
        erp = self.seed()
        self.st.record_decision(14, A, "confirmed", 3, self.clock.t - timedelta(seconds=30))   # 먼저 적은 확인(밀림)
        self.st.record_decision(11, A, "confirmed", 3, self.clock.t)                            # 가장 늦은 확인
        res = self.pair(erp)
        self.assertNotIn(14, [r[1] for r in self.rows(res.pairing_id)])

    def test_warnings_when_holds_open(self):
        erp = self.seed()
        self.st.record_accounts(kids(*many(100)), self.at(T0 + timedelta(minutes=1)))
        L.sync_accounts(FakeReader(kids(*many(10))), self.st, self.at(T0 + timedelta(minutes=2)))
        self.assertIsNotNone(self.st.hold(S.SYNC_ACCOUNTS))
        res = self.pair(FakeErp([]))
        self.assertEqual((res.outcome, res.codes), (S.SYNC_ACCEPTED, (L.CODE_ACCOUNTS_HELD,)))
        self.assertEqual(self.st.pairing_run(res.pairing_id)["codes"], [L.CODE_ACCOUNTS_HELD])
        self.assertTrue(erp)

    def test_stale_inputs_at_record_time_retried_quietly(self):
        erp = self.seed()
        orig = self.st.record_pairing

        def racing(*a, **kw):   # 계산과 적기 사이에 사람 판단이 끼어든다
            self.st.record_decision(15, C, "confirmed", 0, self.clock.t)
            return orig(*a, **kw)
        self.st.record_pairing = racing
        res = self.pair(erp)
        self.assertEqual((res.outcome, res.codes, res.alert), (S.SYNC_REFUSED, (S.CODE_INPUTS_CHANGED,), False))
        self.assertEqual(self.st.last_pairing()["codes"], [S.CODE_INPUTS_CHANGED])
        del self.st.record_pairing
        self.assertTrue(L.pairing_due(self.st, self.clock.t + timedelta(minutes=30)))

    def test_outcome_repr_counts_only(self):
        res = self.pair(self.seed())
        self.assertNotIn(str(A), repr(res))
        d = self.st.current_decisions()[0]
        self.assertNotIn(str(A), repr(d))

    def test_rows_hold_no_names(self):
        self.seed()
        cols = [r[1] for r in self.st._conn.execute("PRAGMA table_info(naver_auto_pairing_row)")]
        self.assertEqual(cols, ["pairing_id", "possibility_id", "customer_id", "state", "code", "same_name",
                                "claimed_elsewhere", "decision_id", "link"])
        cols = [r[1] for r in self.st._conn.execute("PRAGMA table_info(naver_auto_link_memory)")]
        self.assertEqual(cols, ["possibility_id", "customer_id", "link", "first_matched_at", "last_matched_at"])


class TransferLostTest(Base):
    """이관 빠짐(대표 정의 2026-09-29 — 이관 = 광고주 광고계정이 우리 회사에 연결된 상태) — 이어졌던 짝의 계정이 대행 연결
    목록에서 빠지면 감지한다. 확인한 짝뿐 아니라 ① 고객 번호로 자동 짝이 됐던 계정도."""

    def day(self, n, accounts, ids, decisions=()):
        """n 일째 06:40 — 연결 목록 받기 · 단계 새로 · 짝 맞추기 → 12 번 가망 줄."""
        t = self.at(T0 + timedelta(days=n))
        self.st.record_prospects(stages([srow(11, "메타상회"), srow(12, "하늘꽃집", "전략관리")], t - timedelta(minutes=5)))
        self.st.record_accounts(kids(*accounts), t - timedelta(minutes=2))
        for pid, cid, dec in decisions:
            self.st.record_decision(pid, cid, dec, 0, t - timedelta(minutes=1))
        res = self.pair(FakeErp(ids))
        self.assertEqual(res.outcome, S.SYNC_ACCEPTED, res)
        return [r for r in self.st.pairing_rows(res.pairing_id)], res

    def lost(self, rows, pid):
        return [(r["state"], r["customer_id"], r["link"], r["code"]) for r in rows if r["possibility_id"] == pid]

    OTHER = (D, 6543210, "다른곳")

    def test_ad_account_only_pair_preserves_loss_and_recovery(self):
        ids = [E.NaverIdRow(12, M.VENDOR_NAVER, None, "8765432")]
        rows, _ = self.day(0, [(B, 8765432, "하늘꽃집"), self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_AUTO, B, None, "same")])
        rows, _ = self.day(1, [self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_MISSING, B, S.PAIR_AUTO, None)])
        rows, _ = self.day(2, [self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_BROKEN, B, S.PAIR_AUTO, None)])
        rows, _ = self.day(3, [(B, 8765432, "하늘꽃집"), self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_AUTO, B, None, "same")])

    def test_auto_pair_dropped_becomes_transfer_lost(self):
        ids = [nid(12, "2345678")]
        rows, _ = self.day(0, [(B, 8765432, "하늘꽃집"), self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_AUTO, B, None, "same")])
        self.assertIn((12, B), self.st.matched_before(S.PAIR_AUTO))
        rows, res = self.day(1, [self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_MISSING, B, S.PAIR_AUTO, None)])     # 첫날 = 오늘 이관 목록에 없음
        self.assertEqual((res.counts["missing"], res.counts["blocked"]), (1, 0))             # 「이관 안 됨」으로 세지 않는다
        rows, res = self.day(2, [self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_BROKEN, B, S.PAIR_AUTO, None)])      # 둘째 날 = 이관 빠짐
        rows, _ = self.day(3, [(B, 8765432, "하늘꽃집"), self.OTHER], ids)                    # 다시 이관되면 그대로 산다
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_AUTO, B, None, "same")])

    def test_never_linked_number_is_not_transfer_lost(self):
        rows, _ = self.day(0, [self.OTHER], [nid(12, "2345678")])
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_BLOCKED, B, None, M.B_NOT_LINKED)])  # 이관 안 됨

    def test_listed_but_never_paired_is_not_transfer_lost(self):
        # 목록에 있었지만 이름이 달라 자동 짝이 된 적 없는 번호 — 빠져도 「이관 빠짐」이 아니다(누구 계정인지 모른다)
        ids = [nid(12, "2345678")]
        rows, _ = self.day(0, [(B, 8765432, "전혀다른이름"), self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_BLOCKED, B, None, M.B_NAME_DIFFERENT)])
        rows, _ = self.day(1, [self.OTHER], ids)
        self.day(2, [self.OTHER], ids)
        rows, _ = self.day(3, [self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_BLOCKED, B, None, M.B_NOT_LINKED)])

    def test_confirmed_and_claimed_counted_once(self):
        ids = [nid(12, "2345678")]
        self.day(0, [(B, 8765432, "하늘꽃집"), self.OTHER], ids, decisions=[(12, B, "confirmed")])
        rows, _ = self.day(1, [self.OTHER], ids)
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_MISSING, B, S.PAIR_CONFIRMED, None)])   # 막힘 줄을 한 번 더 두지 않는다
        self.assertIsNotNone(rows[[r["possibility_id"] for r in rows].index(12)]["decision_id"])

    def test_account_now_confirmed_to_other_prospect(self):
        ids = [nid(12, "2345678")]
        self.day(0, [(B, 8765432, "하늘꽃집"), self.OTHER], ids)                             # 12 ↔ B 자동 짝
        rows, _ = self.day(1, [self.OTHER], ids, decisions=[(11, B, "confirmed")])            # 사람이 B 를 11 에 확인
        self.assertEqual(self.lost(rows, 11), [(S.PAIR_MISSING, B, S.PAIR_CONFIRMED, None)])
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_BLOCKED, B, None, M.B_NOT_LINKED)])  # 12 의 이관 빠짐이 아니다

    def test_rejected_or_number_removed(self):
        ids = [nid(12, "2345678")]
        self.day(0, [(B, 8765432, "하늘꽃집"), self.OTHER], ids)
        rows, _ = self.day(1, [self.OTHER], [])                                               # ① 에서 번호를 지움
        self.assertEqual(self.lost(rows, 12), [])
        rows, _ = self.day(2, [self.OTHER], ids, decisions=[(12, B, "rejected")])             # 사람이 「아님」
        self.assertEqual(self.lost(rows, 12), [(S.PAIR_BLOCKED, B, None, M.B_REJECTED)])

    def test_memory_times(self):
        ids = [nid(12, "2345678")]
        self.day(0, [(B, 8765432, "하늘꽃집"), self.OTHER], ids, decisions=[(11, D, "confirmed")])
        self.day(1, [(B, 8765432, "하늘꽃집"), self.OTHER], ids)
        mem = self.st._conn.execute("""SELECT possibility_id, customer_id, link, first_matched_at, last_matched_at
                                       FROM naver_auto_link_memory ORDER BY possibility_id""").fetchall()
        self.assertEqual([(m[0], m[2]) for m in mem], [(11, "confirmed"), (12, "auto")])
        self.assertLess(mem[1][3], mem[1][4])                                                  # 처음 · 마지막 이어진 시각
        with self.assertRaises(S.StoreRefused):
            self.st.matched_before("candidate")

    def test_store_row_rules_for_transfer_lost(self):
        self.seed()
        self.st.record_accounts(kids((A, 7654321, "메타상회")), self.at(T0 + timedelta(minutes=1)))   # B 가 빠짐
        args = RecordPairingTest.args
        bad = (
            {"state": "missing", "possibility_id": 12, "customer_id": B},                                     # 짝 종류 없음
            {"state": "missing", "possibility_id": 12, "customer_id": B, "link": "maybe"},
            {"state": "missing", "possibility_id": 12, "customer_id": B, "link": "auto", "decision_id": self.did},
            {"state": "missing", "possibility_id": 12, "customer_id": B, "link": "confirmed"},                # 판단 번호 없음
            {"state": "auto", "possibility_id": 11, "customer_id": A, "code": "same", "link": "auto"},        # 짝 종류는 빠짐 줄에만
            {"state": "missing", "possibility_id": 12, "customer_id": B, "link": "auto"},                     # 자동 짝이 된 적 없음
        )
        for r in bad:
            with self.subTest(r=sorted(r.items())):
                with self.assertRaises(S.StoreRefused):
                    self.st.record_pairing(self.clock.t, **args(self, [r]))


class PairingDueTest(Base):
    def test_due_rules(self):
        self.assertFalse(L.pairing_due(self.st, self.clock.t))                         # 입력 없음 — 부르지 않는다
        erp = self.seed()
        self.assertTrue(L.pairing_due(self.st, self.clock.t))
        self.pair(erp)
        self.assertFalse(L.pairing_due(self.st, self.clock.t + timedelta(minutes=29)))  # 방금 맞춤
        self.assertTrue(L.pairing_due(self.st, self.clock.t + timedelta(minutes=30)))  # 전산 번호 변경을 주기적으로 읽음
        t = self.at(self.clock.t + timedelta(hours=5))
        self.st.record_decision(15, C, "confirmed", 0, t)                               # 사람 판단이 바뀜
        self.assertTrue(L.pairing_due(self.st, t))
        self.pair(FakeErp(erp.ids))
        self.assertTrue(L.pairing_due(self.st, t + timedelta(minutes=31)))
        self.st.record_prospects(stages([srow(11, "메타상회")], self.at(t + timedelta(minutes=31))))   # 단계가 바뀜
        self.assertTrue(L.pairing_due(self.st, self.clock.t))
        self.pair(FakeErp(erp.ids))
        self.st.record_accounts(kids((A, 7654321, "메타상회")), self.at(self.clock.t + timedelta(minutes=31)))
        self.assertTrue(L.pairing_due(self.st, self.clock.t))                           # 연결 목록이 바뀜

    def test_new_day_due_and_retry_after_failure(self):
        erp = self.seed(t=datetime(2026, 9, 29, 22, 0, tzinfo=KST))
        self.pair(erp)
        self.assertTrue(L.pairing_due(self.st, datetime(2026, 9, 29, 23, 59, tzinfo=KST)))
        self.assertTrue(L.pairing_due(self.st, datetime(2026, 9, 30, 0, 1, tzinfo=KST)))   # 날짜가 바뀜(하루 한 번은)
        self.pair(FakeErp(E.ErpError("network", E.PATH_NAVER_IDS)), t=datetime(2026, 9, 30, 0, 2, tzinfo=KST))
        self.assertFalse(L.pairing_due(self.st, datetime(2026, 9, 30, 0, 31, tzinfo=KST)))
        self.assertTrue(L.pairing_due(self.st, datetime(2026, 9, 30, 0, 32, tzinfo=KST)))

    def test_revoking_a_superseded_confirmation_changes_fingerprint(self):
        erp = self.seed()
        self.st.record_decision(12, A, "confirmed", 0, self.clock.t)
        self.pair(erp)
        before = self.st.decision_fingerprint()
        self.st.revoke_decision(self.did, 0, self.clock.t, "거둠")   # 밀린 확인을 거둠 — 산 판단은 그대로
        self.assertNotEqual(self.st.decision_fingerprint(), before)
        self.assertTrue(L.pairing_due(self.st, self.clock.t + timedelta(minutes=30)))

    def test_clock_moved_back(self):
        erp = self.seed()
        self.pair(erp, t=T0 + timedelta(hours=1))
        self.assertTrue(L.pairing_due(self.st, T0 + timedelta(minutes=10)))


# ── 저장소 — 짝 결과 적기 검사 ──────────────────────────────────────────
class RecordPairingTest(Base):
    def args(self, rows=(), **over):
        winners, lost = self.st.link_decisions()
        kw = dict(accounts_read_at=self.st.accounts_read_at(), stages_as_of=self.st.stage_as_of(),
                  decision_ids=[d.decision_id for d in winners + lost], rows=list(rows),
                  counts={"prospects": 1, "ignored": 0})
        kw.update(over)
        return kw

    def test_stale_inputs(self):
        self.seed()
        cases = (dict(accounts_read_at=self.st.accounts_read_at() - timedelta(seconds=1)),
                 dict(stages_as_of=self.st.stage_as_of() + timedelta(seconds=1)),
                 dict(decision_ids=[]), dict(decision_ids=[self.did, self.did + 1]))
        for over in cases:
            with self.subTest(over=list(over)):
                with self.assertRaises(S.PairingStale) as cm:
                    self.st.record_pairing(self.clock.t, **self.args(**over))
                self.assertEqual(cm.exception.code, S.CODE_INPUTS_CHANGED)
        self.assertIsNone(self.st.last_pairing())

    def test_rows_must_match_current_lists(self):
        self.seed()
        bad = (
            {"state": "auto", "possibility_id": 12, "customer_id": 9_999_999, "code": "same"},        # 목록에 없는 계정
            {"state": "auto", "possibility_id": 99, "customer_id": B, "code": "same"},                # 단계 목록에 없는 가망
            {"state": "missing", "possibility_id": 11, "customer_id": A, "decision_id": 1, "link": "confirmed"},   # 목록에 있는데 「오늘 없음」
            {"state": "confirmed", "possibility_id": 12, "customer_id": B, "code": "same", "decision_id": 1},   # 짝이 다름
            {"state": "superseded", "possibility_id": 11, "customer_id": A, "decision_id": 1},        # 밀리지 않은 확인
        )
        for r in bad:
            with self.subTest(state=r["state"]):
                with self.assertRaises(S.PairingStale):
                    self.st.record_pairing(self.clock.t, **self.args([r]))

    def test_row_shapes(self):
        self.seed()
        ok = {"state": "auto", "possibility_id": 12, "customer_id": B, "code": "same"}
        bad = (
            dict(ok, state="maybe"), dict(ok, name=NAME_MARK), dict(ok, code="nope"), dict(ok, code=None),
            dict(ok, customer_id=None), dict(ok, customer_id="2345678"), dict(ok, possibility_id=0),
            dict(ok, decision_id=self.did), dict(ok, same_name=1),
            {"state": "candidate", "possibility_id": 15, "customer_id": C, "code": "same"},
            {"state": "candidate", "possibility_id": 15, "customer_id": C, "code": "same", "same_name": 0,
             "claimed_elsewhere": False},
            {"state": "candidate", "possibility_id": 15, "customer_id": C, "code": "same", "same_name": 1,
             "claimed_elsewhere": 0},
            {"state": "blocked", "possibility_id": 13, "customer_id": None, "code": "Bad Reason"},
            {"state": "blocked", "possibility_id": 13, "customer_id": None, "code": None},
            # 사유 칸에 숫자 조각·모르는 코드가 들어가지 않는다(검토 security-3)
            {"state": "blocked", "possibility_id": 13, "customer_id": None, "code": "2345678"},
            {"state": "blocked", "possibility_id": 13, "customer_id": None, "code": "010-1234-5678"},
            {"state": "blocked", "possibility_id": 13, "customer_id": None, "code": "900101-1234567"},
            {"state": "blocked", "possibility_id": 13, "customer_id": None, "code": "9" * 500},
            {"state": "blocked", "possibility_id": 13, "customer_id": None, "code": "not-linked-2345678"},
            {"state": "missing", "possibility_id": 11, "customer_id": A, "code": "not-linked", "link": "confirmed",
             "decision_id": self.did},
            {"state": "superseded", "possibility_id": 11, "customer_id": A, "code": "never-listed",
             "decision_id": self.did},
            {"state": "confirmed", "possibility_id": 11, "customer_id": A, "code": "same"},            # 판단 번호 없음
            "row", None,
        )
        for r in bad:
            with self.subTest(r=r if not isinstance(r, dict) else sorted(r.items())):
                with self.assertRaises(S.StoreRefused):
                    self.st.record_pairing(self.clock.t, **self.args([r]))
        # 고객 번호 한도(15자리) — 목록 대조보다 먼저 모양에서 거절(목록 대조의 「낡음」이 아니다 · 검토 issues-oversized)
        for r in ({"state": "blocked", "possibility_id": 13, "customer_id": 10 ** 15, "code": "not-linked"},
                  dict(ok, customer_id=10 ** 15)):
            with self.assertRaises(S.StoreRefused) as cm:
                self.st.record_pairing(self.clock.t, **self.args([r]))
            self.assertNotIsInstance(cm.exception, S.PairingStale)
        with self.assertRaises(S.StoreRefused):
            self.st.record_pairing(self.clock.t, **self.args([ok, dict(ok)]))                    # 같은 줄 두 번
        for counts in ({"prospects": 1}, {"prospects": 1, "ignored": -1}, {"prospects": 1, "ignored": 0, "auto": 5},
                       {"prospects": True, "ignored": 0}, "x"):
            with self.assertRaises(S.StoreRefused):
                self.st.record_pairing(self.clock.t, **self.args([ok], counts=counts))
        for ids in ("12", {1: 1}, 5, None):
            with self.assertRaises(S.StoreRefused):
                self.st.record_pairing(self.clock.t, **self.args([ok], decision_ids=ids))
        with self.assertRaises(S.StoreRefused):
            self.st.record_pairing(self.clock.t + timedelta(minutes=6), **self.args([ok]))       # 미래
        blocked_twice = [{"state": "blocked", "possibility_id": 13, "customer_id": None, "code": M.B_FORMAT}] * 2
        pid = self.st.record_pairing(self.clock.t, **self.args([ok] + blocked_twice))           # 번호 없는 막힘은 여러 줄
        self.assertEqual(self.st.pairing_run(pid)["counts"]["blocked"], 2)
        self.assertEqual(self.st.pairing_run(pid)["counts"]["auto"], 1)                         # 개수는 저장소가 줄에서 센다

    def test_reason_codes_by_state(self):
        """사유 칸 — 막힘은 짝 규칙 코드만 · 이관 빠짐은 없음 또는 never-listed 만 · 밀린 확인은 없음(검토 security-3).
        줄 모양 검사만 본다(목록 대조로 먼저 거절되는 경우와 섞이지 않게)."""
        lost = {"state": "missing", "possibility_id": 11, "customer_id": A, "link": "confirmed", "decision_id": 5}
        sup = {"state": "superseded", "possibility_id": 11, "customer_id": A, "decision_id": 5}
        for good in (dict(lost), dict(lost, code=None), dict(lost, code="never-listed"),
                     dict(lost, state="broken", code="never-listed"), dict(sup)):
            self.assertEqual(len(self.st._pairing_rows([good])), 1, good)
        for bad in (dict(lost, code="not-linked"), dict(lost, code="2345678"), dict(lost, state="broken", code="x"),
                    dict(sup, code="never-listed"), dict(sup, code="same")):
            with self.subTest(bad=sorted(bad.items())):
                with self.assertRaises(S.StoreRefused):
                    self.st._pairing_rows([bad])

    def test_events(self):
        pid = self.st.record_pairing_event(self.clock.t, S.SYNC_FAILED, ["network"])
        self.assertEqual(self.st.pairing_run(pid)["outcome"], S.SYNC_FAILED)
        for outcome, codes in ((S.SYNC_ACCEPTED, ["x"]), (S.SYNC_BRAKED, ["x"]), (S.SYNC_FAILED, []),
                               (S.SYNC_FAILED, ["https://x/1234567"])):
            with self.assertRaises(S.StoreRefused):
                self.st.record_pairing_event(self.clock.t, outcome, codes)
        self.assertEqual(self.st.pairing_rows(pid), [])
        with self.assertRaises(S.StoreRefused):
            self.st.last_pairing("braked")

    def test_reader_cannot_write(self):
        self.seed()
        r = S.open_reader(self.path)
        try:
            with self.assertRaises(S.StoreRefused):
                r.record_pairing(self.clock.t, **self.args())
            with self.assertRaises(S.StoreRefused):
                r.record_pairing_event(self.clock.t, S.SYNC_FAILED, ["network"])
        finally:
            r.close()


# ── 저장소 — 사람 판단 해석 ────────────────────────────────────────────
class DecisionResolutionTest(Base):
    def test_latest_confirmation_per_account(self):
        d1 = self.st.record_decision(11, A, "confirmed", 0, T0)
        d2 = self.st.record_decision(12, A, "confirmed", 5, T0 - timedelta(hours=1))   # 시각은 앞서도 나중에 적음 → 이김
        self.st.record_decision(13, A, "rejected", 5, T0)
        w, lost = self.st.link_decisions()
        self.assertEqual([(d.possibility_id, d.decision, d.decision_id) for d in w],
                         [(12, "confirmed", d2), (13, "rejected", 3)])
        self.assertEqual([(d.possibility_id, d.decision_id) for d in lost], [(11, d1)])
        self.assertEqual([d.decision_id for d in self.st.superseded_confirmations()], [d1])
        self.assertEqual(w[0].decided_at, T0 - timedelta(hours=1))
        self.assertEqual(w[0].decided_by, 5)
        self.st.revoke_decision(d2, 0, T0, "잘못 누름")
        self.assertEqual([(d.possibility_id, d.decision) for d in self.st.current_decisions()],
                         [(11, "confirmed"), (13, "rejected")])
        self.assertEqual(self.st.superseded_confirmations(), [])

    def test_later_rejection_of_winner_revives_older_confirmation(self):
        """(12,A) 확인 → (11,A) 확인 → (11,A) 아님 — 12 의 확인이 다시 산다(검토 rules-2)."""
        self.at(T0)
        d1 = self.st.record_decision(12, A, "confirmed", 0, T0)
        self.st.record_decision(11, A, "confirmed", 0, T0 + timedelta(minutes=1))
        d3 = self.st.record_decision(11, A, "rejected", 0, T0 + timedelta(minutes=2))
        winners, lost = self.st.link_decisions()
        self.assertEqual(sorted((d.decision_id, d.possibility_id, d.decision) for d in winners),
                         [(d1, 12, "confirmed"), (d3, 11, "rejected")])
        self.assertEqual(lost, [])
        self.st.record_prospects(stages([srow(11, "메타상회"), srow(12, "하늘꽃집")], T0 - timedelta(minutes=5)))
        self.st.record_accounts(kids((A, 7654321, "하늘꽃집"), (B, 8765432, "다른")), self.at(T0 + timedelta(minutes=3)))
        rows = self.rows(self.pair(FakeErp([nid(11, "1234567")])).pairing_id)
        self.assertIn((S.PAIR_CONFIRMED, 12, A, "same"), rows)
        self.assertIn((S.PAIR_BLOCKED, 11, A, M.B_REJECTED), rows)

    def test_matching_never_sees_two_confirmations(self):
        for pid in (11, 12, 13):
            self.st.record_decision(pid, A, "confirmed", 0, T0)
        dec = [M.HumanDecision(d.possibility_id, d.customer_id, d.decision) for d in self.st.current_decisions()]
        r = M.match([M.ErpProspect(11, "a"), M.ErpProspect(12, "b"), M.ErpProspect(13, "c")], [],
                    {A: {"customerId": A, "adAccountNo": 7654321, "adAccountName": "c"}}, dec, accounts_complete=True)
        self.assertEqual([(p.possibility_id, p.link) for p in r.pairs], [(13, V.LINK_CONFIRMED)])

    def test_unreadable_decision_time(self):
        self.st.record_decision(11, A, "confirmed", 0, T0)
        self.st._conn.execute("UPDATE naver_auto_link_decision SET decided_at = 'x'")
        with self.assertRaises(S.StoreError):
            self.st.current_decisions()


class ConstantsTest(unittest.TestCase):
    def test_pair_words_match_other_modules(self):
        self.assertEqual({S.PAIR_CONFIRMED, S.PAIR_AUTO}, set(H.LINK_CHECKABLE))
        self.assertEqual((S.PAIR_CONFIRMED, S.PAIR_AUTO), (V.LINK_CONFIRMED, V.LINK_AUTO))
        self.assertEqual(S.PAIR_RELATIONS, {M.REL_SAME, M.REL_CONTAINS, M.REL_DIFFERENT, M.REL_UNKNOWN})
        self.assertEqual(S.PAIR_BLOCK_CODES, {v for k, v in vars(M).items() if k.startswith("B_")})   # 막힘 사유 = matching
        self.assertEqual(L.CODE_NEVER_LISTED, S.PAIR_CODE_NEVER_LISTED)
        self.assertEqual(L.CONFIRMABLE_ACCOUNT_CODES, {S.BRAKE_TOTAL, S.BRAKE_MANAGER, S.BRAKE_BASELINE,
                                                       S.BRAKE_CONFIRMED})
        self.assertEqual(L.ACCOUNTS_START, time(0, 1))
        self.assertLess(L.LINK_BROKEN_MIN_SPAN, timedelta(hours=24))   # 매일 00:01 목록 두 번이면 끊김이 된다
        self.assertGreater(L.ACCOUNTS_MAX_AGE, timedelta(hours=24))    # 오늘 목록을 못 받아도 어제 목록으로 맞춘다


if __name__ == "__main__":
    unittest.main()
