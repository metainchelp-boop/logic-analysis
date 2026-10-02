"""S7 시험 — 조직 스냅숏 수락본 · 목록 급감 브레이크 · 동기화 기록 · 신선도 · 부르는 때 (설계 v1.8 S7 · M12 · H1 · H3 · M3).

가짜 ① 읽기(``FakeErp``)로만 돈다 — 네트워크 0. 판정 규칙은 ``backend/app/naver_auto/org_snapshot.py`` 를 그대로 쓴다.
"""
from __future__ import annotations

import ast
import copy
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone

ENGINE = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ENGINE.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.naver_auto import org_snapshot as O  # noqa: E402

from naver_engine import erp_read as E  # noqa: E402
from naver_engine import fields as F  # noqa: E402
from naver_engine import naver_read as N  # noqa: E402
from naver_engine import store as S  # noqa: E402
from naver_engine import sync as Y  # noqa: E402

KST = timezone(timedelta(hours=9))
T0 = datetime(2026, 9, 29, 10, 0, tzinfo=KST)
PHONE_MARK = "010-9876-5432"
LOGIN_MARK = "login_marker_zq8"
PID_MARK = 987_654_321


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def team(idx, name, level=1, parent=0, system=False):
    return {"idx": idx, "name": name, "level": level, "parent_idx": parent, "is_system": system}


def emp(idx, name, team_idx, manager=False, top=False, status="ACTIVE", deleted=False, management=True):
    return {"idx": idx, "name": name, "team_idx": team_idx, "is_manager": manager, "is_top_manager": top,
            "status": status, "is_deleted": deleted, "is_management": management}


def owner(pid, main, sub=None):
    return {"possibility_id": pid, "manage_emp_idx": main, "sub_manage_emp_idx": sub, "prev_manage_owner_idx": None,
            "sales_emp_idx": None, "owner_source": "manage" if main is not None else "none"}


def org_payload(at, staff=30, resigned=0, owners=40, extra=None):
    """대표(0번) + 팀장 1 + 직원 ``staff`` 명(앞에서 ``resigned`` 명 퇴사) · 담당 줄 ``owners`` 개."""
    teams = [team(0, "미분류", 0, 0, True), team(1, "퇴사자", 0, 0, True), team(10, "관리 본부"), team(11, "관리 1팀", 2, 10)]
    people = [emp(0, "대표", 0, manager=True, top=True), emp(1, "팀장", 11, manager=True)]
    for i in range(staff):
        people.append(emp(100 + i, f"직원{i}", 11, status="RESIGNED" if i < resigned else "ACTIVE"))
    own = [owner(5000 + i, 100 + (i % max(staff, 1)) if staff else 1) for i in range(owners)]
    body = {"generated_at": at.isoformat(), "teams": teams, "employees": people, "owners": own}
    if extra:
        extra(body)
    return body


class FakeErp:
    """``ErpReader`` 대신 — 부른 횟수와 받은 읽기 마감을 센다. 값이 예외면 던진다."""

    def __init__(self, org=None, stages=None):
        self.org, self.stages, self.calls, self.deadlines = org, stages, 0, []

    def read_org_snapshot(self):
        self.calls += 1
        if isinstance(self.org, BaseException):
            raise self.org
        return copy.deepcopy(self.org)

    def read_stages(self, deadline=None):
        self.calls += 1
        self.deadlines.append(deadline)
        if isinstance(self.stages, BaseException):
            raise self.stages
        return self.stages


# v1.7 실측처럼 관리 단계가 고루 있게 — 번호로 단계를 정한다(같은 번호는 늘 같은 단계)
REQ = ("진행중", "전략관리", "사후관리", "홀딩중", "환불중")


def stage_of(pid):
    return REQ[pid % len(REQ)]


def srow(pid, stage=None):
    return E.StageRow(pid, stage or stage_of(pid), None, date(2026, 12, 31), False)


def snap(pids, as_of, conflicts=(), per=None, stages=None):
    """``stages`` = {번호: 단계} 로 몇 곳만 바꿀 수 있다."""
    stages = stages or {}
    return E.StageSnapshot({p: srow(p, stages.get(p)) for p in pids}, as_of, {} if per is None else per,
                           tuple(conflicts))


def kids(cids, per=None):
    acc = {c: {"customerId": c, "adAccountNo": c + 1, "adAccountName": "계정", "ownerNaverId": "owner_x"} for c in cids}
    return N.ChildAccounts(acc, {1: len(acc)} if per is None else per, ())


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "engine.db")
        self.clock = Clock(T0 + timedelta(days=30))
        self.st = S.open_writer(self.path, clock=self.clock)

    def tearDown(self):
        try:
            if self.st is not None:
                self.st.close()
        finally:
            self.dir.cleanup()

    def at(self, t):
        """저장소 시계를 t 로 — 붙잡음 확인 시간(3시간)을 저장소 시계로 재기 때문."""
        self.clock.t = t
        return t

    def reopen(self):
        self.st.close()
        self.st = S.open_writer(self.path, clock=self.clock)
        return self.st

    def raw(self, sql, args=()):
        """엔진 연결 밖에서 파일을 고친다(손상·부분 복원 흉내)."""
        self.st.close()
        self.st = None
        con = sqlite3.connect(self.path)
        con.execute(sql, args)
        con.commit()
        con.close()
        self.st = S.open_writer(self.path, clock=self.clock)

    def file_bytes(self):
        self.st._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        out = b""
        for suffix in ("", "-wal", "-shm"):
            p = self.path + suffix
            if os.path.exists(p):
                with open(p, "rb") as f:
                    out += f.read()
        return out


# ── 판 번호 · 이관 ───────────────────────────────────────────────────
class MigrationTest(Base):
    def test_v1_file_gets_new_tables_and_keeps_data(self):
        self.st.record_accounts(kids([1234567]), T0)
        self.st.close()
        self.st = None
        raw = sqlite3.connect(self.path)   # 옛 판(1) 파일을 만든다 — 새 표가 없고 판 번호 1
        for t in ("naver_auto_org", "naver_auto_sync_log", "naver_auto_hold"):
            raw.execute(f"DROP TABLE {t}")
        raw.execute("UPDATE naver_auto_meta SET value = '1' WHERE key = 'schema_version'")
        raw.commit()
        raw.close()
        self.st = S.open_writer(self.path, clock=self.clock)
        self.assertEqual(self.st.meta("schema_version"), str(S.SCHEMA_VERSION))
        self.assertEqual(len(self.st.accounts()), 1)
        self.assertIsNone(self.st.org_current())
        self.assertEqual(self.st.sync_log(), [])
        self.assertIsNone(self.st.stage_as_of())
        self.assertIsNone(self.st.hold(S.SYNC_STAGES))

    def test_version_is_nine(self):
        # 2026-10-02 명세: 기존 계약 이력을 보존하면서 독립 계정×일 원천 수집 표를 더한 판이다.
        self.assertEqual(S.SCHEMA_VERSION, 9)   # 월간 원천 표 추가 후에도 기존 표·행을 보존한다.


# ── 목록 급감 브레이크 — 가망 ──────────────────────────────────────────
class ProspectBrakeTest(Base):
    def seed(self, n=50, t=T0):
        self.at(t)
        return self.st.record_prospects(snap(range(1, n + 1), t))

    def put(self, pids, t, **kw):
        self.at(t)
        return self.st.record_prospects(snap(pids, t, **kw))

    def brake(self, pids, t, **kw):
        with self.assertRaises(S.SyncBraked) as cm:
            self.put(pids, t, **kw)
        return cm.exception

    def test_boundary_exactly_twenty_percent_is_accepted(self):
        self.seed(50)
        c = self.put(range(11, 51), T0 + timedelta(hours=6))   # 10/50 = 딱 20%
        self.assertEqual(c.now_absent, 10)

    def test_more_than_twenty_percent_and_ten_rows_brakes_and_writes_nothing(self):
        self.seed(50)
        before = self.st.prospects()
        t = T0 + timedelta(hours=6)
        b = self.brake(range(12, 51), t)   # 11/50 = 22%
        self.assertIsInstance(b, S.StoreRefused)
        self.assertEqual((b.kind, b.present_before, b.would_absent), ("stages", 50, 11))
        self.assertEqual(b.reasons, ("BRAKE", "BRAKE_BASELINE"))
        self.assertEqual(self.st.prospects(), before)                               # 한 줄도 안 바뀜
        self.assertEqual(self.st.stage_as_of(), T0)                                 # 받은 시각도 그대로
        log = self.st.last_sync(S.SYNC_STAGES)
        self.assertEqual((log["outcome"], log["absent_count"], log["row_count"], log["codes"]),
                         ("braked", 11, 39, ["BRAKE", "BRAKE_BASELINE"]))
        self.assertEqual(datetime.fromisoformat(log["at"]), t)                     # 멈춤 기록 시각 = 그 목록 시각
        self.assertEqual(b.hold_id, log["sync_id"])                                 # 붙잡음 번호 = 그 기록
        self.assertNotIn("12", str(b).replace("11", ""))   # 문구에는 개수만(번호 없음)

    def test_braked_log_keeps_spelling_counts(self):
        self.seed(50)
        self.brake(range(12, 51), T0 + timedelta(hours=6), per={"진행중": 30, "진행 중": 9})
        self.assertEqual(self.st.last_sync(S.SYNC_STAGES)["detail"], {"진행 중": 9, "진행중": 30})

    def test_small_drop_under_ten_rows_is_accepted_even_over_ratio(self):
        self.seed(40)
        c = self.put(range(10, 41), T0 + timedelta(hours=6))   # 9/40 = 22.5% 이지만 9줄
        self.assertEqual(c.now_absent, 9)

    def test_exactly_ten_rows_over_ratio_brakes(self):
        self.seed(40)
        b = self.brake(range(11, 41), T0 + timedelta(hours=6))   # 10/40 = 25% · 딱 10줄
        self.assertEqual(b.would_absent, 10)
        self.assertIn("BRAKE", b.reasons)

    def test_ratio_is_against_rows_present_now_not_all_rows(self):
        self.seed(60)
        b = self.brake(range(21, 61), T0 + timedelta(hours=6))   # 20 빠짐 → 확인 → 있음 40
        self.st.confirm_prospects_hold(b.hold_id, 0)
        b = self.brake(range(31, 61), T0 + timedelta(hours=12))   # 10/40 = 25% (전체 60 으로 나누면 16.7%)
        self.assertEqual((b.present_before, b.would_absent), (40, 10))

    def test_only_newly_leaving_rows_count(self):
        self.seed(60)
        b = self.brake(range(16, 61), T0 + timedelta(hours=6))                 # 15 빠짐(확인)
        self.st.confirm_prospects_hold(b.hold_id, 0)
        c = self.put(range(16, 61), T0 + timedelta(hours=12))                  # 더 빠지는 것 없음
        self.assertEqual(c.now_absent, 0)
        c = self.put(range(25, 61), T0 + timedelta(hours=18))                  # 9/45 · 9줄 — 받음
        self.assertEqual(c.now_absent, 9)

    def test_conflicts_are_not_leaving(self):
        self.seed(50)
        c = self.put(range(20, 51), T0 + timedelta(hours=6), conflicts=range(1, 20))
        self.assertEqual(c.now_absent, 0)

    def test_one_stage_wiped_brakes_even_under_total_ratio(self):
        """환불중 두 표기가 0 을 돌려주면 139곳(전체의 14.8%)이 조용히 빠질 뻔했다(S7 검토 · 반박 H3 재발)."""
        stages = {p: ("환불중" if p > 800 else "진행중") for p in range(1, 940)}
        self.at(T0)
        self.st.record_prospects(snap(range(1, 940), T0, stages=stages))
        b = self.brake(range(1, 801), T0 + timedelta(hours=6), stages=stages)
        self.assertEqual((b.reasons, b.present_before, b.would_absent), (("BRAKE_STAGE",), 939, 139))
        self.assertEqual(sum(p["present"] for p in self.st.prospects()), 939)

    def test_big_move_between_stages_also_asks(self):
        stages = {p: ("환불중" if p > 100 else "진행중") for p in range(1, 161)}
        self.at(T0)
        self.st.record_prospects(snap(range(1, 161), T0, stages=stages))
        moved = {**stages, **{p: "진행중" for p in range(101, 116)}}   # 환불중 60 → 45(25%) · 빠지는 곳 0
        b = self.brake(range(1, 161), T0 + timedelta(hours=6), stages=moved)
        self.assertEqual((b.reasons, b.would_absent), (("BRAKE_STAGE",), 0))

    def test_small_stage_to_zero_is_accepted(self):
        stages = {p: ("재계약진행중" if p <= 5 else "진행중") for p in range(1, 101)}
        self.at(T0)
        self.st.record_prospects(snap(range(1, 101), T0, stages=stages))
        c = self.put(range(6, 101), T0 + timedelta(hours=6), stages=stages)   # 5줄 → 0 · 10줄 미만
        self.assertEqual(c.now_absent, 5)

    def test_slow_ratchet_hits_baseline(self):
        """매번 20% 아래로 조금씩 잘려도 기준선(가장 많던 수)보다 20% 넘게 줄면 멈춘다(S7 검토 — 톱니)."""
        self.seed(940)
        c = self.put(range(186, 941), T0 + timedelta(hours=6))   # 185 빠짐(19.7%) · 기준선 940
        self.assertEqual(c.now_absent, 185)
        b = self.brake(range(334, 941), T0 + timedelta(hours=12))   # 직전 755 대비 19.6% · 기준선 940 대비 35%
        self.assertIn("BRAKE_BASELINE", b.reasons)
        self.assertNotIn("BRAKE", b.reasons)
        self.st.confirm_prospects_hold(b.hold_id, 0)               # 확인하면 기준선을 지금 수로
        self.assertEqual(self.st.meta("prospects_baseline"), "607")
        c = self.put(range(354, 941), T0 + timedelta(hours=18))   # 20 빠짐 — 새 기준선 607 대비 3%
        self.assertEqual(c.now_absent, 20)

    def test_baseline_rises_with_growth(self):
        self.seed(50)
        self.put(range(1, 101), T0 + timedelta(hours=6))
        self.assertEqual(self.st.meta("prospects_baseline"), "100")
        b = self.brake(range(1, 80), T0 + timedelta(hours=12))
        self.assertEqual(b.reasons, ("BRAKE", "BRAKE_BASELINE"))

    def test_spelling_counts_kept_and_checked(self):
        self.at(T0)
        self.st.record_prospects(snap([1], T0, per={"진행중": 1, "진행 중": 0}))
        self.assertEqual(self.st.last_sync(S.SYNC_STAGES)["detail"], {"진행 중": 0, "진행중": 1})
        for per in ({"없는단계": 1}, {"진행중": -1}, {"진행중": True}, ["진행중"]):
            with self.assertRaises(S.StoreRefused, msg=repr(per)):
                self.st.record_prospects(snap([1], T0 + timedelta(hours=1), per=per))

    def test_unknown_stage_key_refused(self):
        self.at(T0)
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(snap([1], T0, stages={1: "환불완료"}))

    def test_ratio_matches_plausible_tolerance(self):
        self.assertEqual(S.BRAKE_DROP_RATIO, E.EXPECTED_TOLERANCE)
        self.assertEqual(S.BRAKE_MIN_ROWS, 10)


# ── 붙잡아 두기 — 확인하면 새로 읽지 않고 멈춘 그 목록을 받는다 ──────────────────
class StageHoldTest(Base):
    def setUp(self):
        super().setUp()
        self.at(T0)
        self.st.record_prospects(snap(range(1, 941), T0))
        self.t1 = self.at(T0 + timedelta(hours=6))
        with self.assertRaises(S.SyncBraked) as cm:
            self.st.record_prospects(snap(range(300, 941), self.t1))   # 299 빠질 뻔
        self.b = cm.exception

    def test_confirm_takes_held_list_and_records_bypassed_codes(self):
        hold = self.st.hold(S.SYNC_STAGES)
        self.assertEqual((hold["hold_id"], hold["codes"], hold["used_at"]), (self.b.hold_id, list(self.b.reasons), None))
        self.at(self.t1 + timedelta(minutes=30))
        c = self.st.confirm_prospects_hold(self.b.hold_id, 0)
        self.assertEqual((c.present, c.now_absent), (641, 299))
        self.assertEqual(sum(p["present"] for p in self.st.prospects()), 641)
        self.assertEqual(self.st.stage_as_of(), self.t1)                   # 받은 시각 = 멈춘 목록의 시각
        log = self.st.last_sync(S.SYNC_STAGES)
        self.assertEqual((log["outcome"], log["confirmed_by"], log["absent_count"]), ("accepted", 0, 299))
        self.assertEqual(log["codes"], list(self.b.reasons) + ["CONFIRMED"])
        self.assertEqual(self.st.hold(S.SYNC_STAGES)["used_by"], 0)

    def test_confirm_only_once(self):
        self.st.confirm_prospects_hold(self.b.hold_id, 0)
        with self.assertRaises(S.HoldRefused) as cm:
            self.st.confirm_prospects_hold(self.b.hold_id, 0)
        self.assertEqual(cm.exception.code, S.HOLD_USED)

    def test_newer_hold_replaces_older(self):
        t2 = self.at(self.t1 + timedelta(hours=1))
        with self.assertRaises(S.SyncBraked) as cm:
            self.st.record_prospects(snap(range(400, 941), t2))
        with self.assertRaises(S.HoldRefused) as old:
            self.st.confirm_prospects_hold(self.b.hold_id, 0)
        self.assertEqual(old.exception.code, S.HOLD_NOT_FOUND)
        self.assertEqual(self.st.confirm_prospects_hold(cm.exception.hold_id, 0).present, 541)

    def test_expired_after_three_hours_and_nothing_changes(self):
        self.at(self.t1 + S.HOLD_TTL + timedelta(microseconds=1))
        with self.assertRaises(S.HoldRefused) as cm:
            self.st.confirm_prospects_hold(self.b.hold_id, 0)
        self.assertEqual(cm.exception.code, S.HOLD_EXPIRED)
        self.assertEqual(sum(p["present"] for p in self.st.prospects()), 940)
        self.assertIsNone(self.st.hold(S.SYNC_STAGES)["used_at"])          # 표시도 되돌려진다
        self.at(self.t1 + S.HOLD_TTL)
        self.assertEqual(self.st.confirm_prospects_hold(self.b.hold_id, 0).present, 641)   # 딱 3시간은 된다

    def test_accepting_newer_list_supersedes_hold(self):
        t2 = self.at(self.t1 + timedelta(hours=1))
        self.st.record_prospects(snap(range(1, 941), t2))                 # ① 이 나아져 확인 없이 받음
        with self.assertRaises(S.HoldRefused) as cm:
            self.st.confirm_prospects_hold(self.b.hold_id, 0)
        self.assertEqual(cm.exception.code, S.HOLD_SUPERSEDED)
        self.assertEqual(sum(p["present"] for p in self.st.prospects()), 940)

    def test_bad_ids_and_confirmers_refused(self):
        for bad in (0, -1, True, "1", None):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)):
                self.st.confirm_prospects_hold(bad, 0)
        for bad in (-1, True, "0", 1.0, None):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)):
                self.st.confirm_prospects_hold(self.b.hold_id, bad)
        self.assertIsNone(self.st.hold(S.SYNC_STAGES)["used_at"])

    def test_refuse_stages_holds_first_run_list(self):
        self.reopen()
        with self.assertRaises(S.StoreRefused):
            self.st.refuse_stages(snap(range(1, 10), self.t1), ())
        hid = self.st.refuse_stages(snap(range(1, 10), self.t1 + timedelta(minutes=1)), ("IMPLAUSIBLE_FIRST",))
        self.assertEqual(self.st.hold(S.SYNC_STAGES)["codes"], ["IMPLAUSIBLE_FIRST"])
        self.assertEqual(self.st.last_sync(S.SYNC_STAGES)["outcome"], "refused")
        self.assertEqual(hid, self.st.last_sync(S.SYNC_STAGES)["sync_id"])

    def test_corrupt_hold_is_store_error(self):
        self.raw("UPDATE naver_auto_hold SET body = 'x'")
        with self.assertRaises(S.StoreError):
            self.st.confirm_prospects_hold(self.b.hold_id, 0)
        with self.assertRaises(S.StoreError):
            self.st.hold(S.SYNC_STAGES)


# ── 목록 급감 브레이크 — 네이버 연결 계정 ──────────────────────────────────
class AccountBrakeTest(Base):
    def put(self, cids, t, per=None):
        self.at(t)
        return self.st.record_accounts(kids(cids, per), t)

    def brake(self, cids, t, per=None):
        with self.assertRaises(S.SyncBraked) as cm:
            self.put(cids, t, per)
        return cm.exception

    def test_row_drop_brakes_and_keeps_absent_days(self):
        self.put(range(1000, 1050), T0)
        b = self.brake(range(1011, 1050), T0 + timedelta(days=1))
        self.assertEqual((b.present_before, b.would_absent, b.reasons),
                         (50, 11, ("BRAKE", "BRAKE_MANAGER", "BRAKE_BASELINE")))   # 관리계정 하나뿐이면 그 계정도 줄었다
        self.assertTrue(all(a["present"] == 1 and a["absent_days"] == 0 for a in self.st.accounts()))
        self.assertIsNotNone(self.st.last_sync(S.SYNC_ACCOUNTS, S.SYNC_BRAKED))

    def test_only_newly_leaving_accounts_count(self):
        self.put(range(1000, 1060), T0)
        b = self.brake(range(1015, 1060), T0 + timedelta(days=1))
        self.st.confirm_accounts_hold(b.hold_id, 0)                      # 15 빠짐(확인)
        c = self.put(range(1015, 1060), T0 + timedelta(days=2))          # 더 빠지는 것 없음 — 받음
        self.assertEqual(c.now_absent, 0)
        self.assertEqual({a["absent_days"] for a in self.st.accounts() if not a["present"]}, {2})

    def test_confirm_takes_held_accounts(self):
        self.put(range(1000, 1060), T0)
        t = T0 + timedelta(days=1)
        b = self.brake(range(1015, 1060), t)
        self.at(t + timedelta(hours=1))
        c = self.st.confirm_accounts_hold(b.hold_id, 7)
        self.assertEqual((c.present, c.now_absent), (45, 15))
        log = self.st.last_sync(S.SYNC_ACCOUNTS)
        self.assertEqual((log["confirmed_by"], log["codes"][-1], log["at"][:10]), (7, "CONFIRMED", t.date().isoformat()))
        with self.assertRaises(S.HoldRefused):
            self.st.confirm_accounts_hold(b.hold_id, 7)

    def test_manager_lost_with_leaving_account_brakes(self):
        self.put(range(1000, 1050), T0, per={1: 40, 2: 10})
        b = self.brake(range(1000, 1049), T0 + timedelta(days=1), per={1: 49})   # 한 줄만 빠져도
        self.assertEqual((b.reasons, b.managers_before, b.managers_now), (("BRAKE_MANAGER",), 2, 1))
        self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS)["manager_count"], 1)

    def test_manager_lost_without_leaving_account_is_accepted(self):
        self.put(range(1000, 1050), T0, per={1: 50, 2: 0})
        c = self.put(range(1000, 1050), T0 + timedelta(days=1), per={1: 50})
        self.assertEqual(c.now_absent, 0)
        self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS, S.SYNC_ACCEPTED)["manager_count"], 1)

    def test_manager_renumbered_with_same_count_brakes(self):
        """관리계정 수는 같아도 번호가 바뀌면(하나 사라지고 빈 것이 생김) 멈춘다(S7 검토 — 수만 견주던 빈틈)."""
        self.put(range(1000, 1050), T0, per={1: 40, 2: 10})
        b = self.brake(range(1000, 1049), T0 + timedelta(days=1), per={1: 40, 3: 9})
        self.assertEqual(b.reasons, ("BRAKE_MANAGER",))

    def test_small_manager_vanishing_brakes(self):
        """10줄이 안 되는 관리계정도 통째로 사라지고 빠질 계정이 있으면 멈춘다(관리계정 수만 보던 옛 규칙을 잃지 않게)."""
        self.put(range(1000, 1050), T0, per={1: 47, 2: 3})
        b = self.brake(range(1000, 1047), T0 + timedelta(days=1), per={1: 47})
        self.assertEqual(b.reasons, ("BRAKE_MANAGER",))

    def test_manager_present_with_zero_rows_brakes(self):
        self.put(range(1000, 1050), T0, per={1: 40, 2: 10})
        b = self.brake(range(1000, 1040), T0 + timedelta(days=1), per={1: 40, 2: 0})   # 10/50 = 딱 20% 지만
        self.assertEqual(b.reasons, ("BRAKE_MANAGER",))

    def test_one_manager_shrinks_a_lot(self):
        self.put(range(1000, 1100), T0, per={1: 40, 2: 60})
        b = self.brake(range(1000, 1085), T0 + timedelta(days=1), per={1: 40, 2: 45})   # 전체 15% · 2번 25%
        self.assertEqual(b.reasons, ("BRAKE_MANAGER",))
        c = self.put(range(1000, 1092), T0 + timedelta(days=2), per={1: 40, 2: 52})    # 2번 8줄 — 10줄 미만
        self.assertEqual(c.now_absent, 8)

    def test_manager_compared_to_last_accepted_not_braked(self):
        self.put(range(1000, 1050), T0, per={1: 40, 2: 10})
        self.brake(range(1000, 1049), T0 + timedelta(days=1), per={1: 49})
        b = self.brake(range(1000, 1049), T0 + timedelta(days=2), per={1: 49})   # 멈춘 목록을 기준으로 삼지 않는다
        c = self.st.confirm_accounts_hold(b.hold_id, 0)
        self.assertEqual(c.now_absent, 1)
        log = self.st.last_sync(S.SYNC_ACCOUNTS)
        self.assertEqual((log["confirmed_by"], log["codes"]), (0, ["BRAKE_MANAGER", "CONFIRMED"]))
        self.assertEqual(self.st.meta("accounts_per_manager"), '{"1": 49}')

    def test_slow_ratchet_hits_baseline(self):
        self.put(range(1000, 1100), T0)
        self.put(range(1019, 1100), T0 + timedelta(days=1))               # 19% · 기준선 100
        b = self.brake(range(1034, 1100), T0 + timedelta(days=2))         # 직전 81 대비 18.5% · 기준선 대비 34%
        self.assertEqual(b.reasons, ("BRAKE_BASELINE",))

    def test_manager_numbers_must_be_positive(self):
        for per in ({0: 1}, {-1: 1}, {True: 1}, {"1": 1}, {1: None}):
            with self.assertRaises(S.StoreRefused, msg=repr(per)):
                self.put([1000], T0, per=per)


# ── 동기화 기록 ─────────────────────────────────────────────────────
class SyncLogTest(Base):
    def test_outside_callers_cannot_write_accepted_or_braked(self):
        for outcome in ("accepted", "braked", "skipped", ""):
            with self.assertRaises(S.StoreRefused, msg=outcome):
                self.st.record_sync_event(S.SYNC_ORG, outcome, ("X",), T0)
        with self.assertRaises(S.StoreRefused):
            self.st.record_sync_event("naver", S.SYNC_FAILED, ("X",), T0)
        self.assertEqual(self.st.sync_log(), [])
        self.assertIsNone(self.st.hold(S.SYNC_ORG))   # 밖에서 적은 버림은 붙잡음을 만들지 않는다

    def test_codes_are_code_shaped_deduped_and_capped(self):
        self.st.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, ("ACTIVE_DROP", "status-403", "ACTIVE_DROP"), T0)
        self.assertEqual(self.st.last_sync(S.SYNC_ORG)["codes"], ["ACTIVE_DROP", "status-403"])
        many = tuple("C" + chr(ord("A") + i) for i in range(21))
        for bad in (("직원 12 퇴사",), ("a b",), ("X" * 41,), "ACTIVE_DROP", (1,), many):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)[:40]):
                self.st.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, bad, T0)

    def test_codes_cannot_carry_numbers(self):
        """번호·전화·키 조각이 코드 모양으로 영구 저장되지 않게 — 숫자는 끝의 HTTP 상태 세 자리 하나만(S7 검토)."""
        for bad in ("pid987654321", "cust-1234567", "emp-0-kim", "p01098765432", "status-9999", "status-099",
                    "status-403-500", "skA1b2c3d4", "bad-shape-2"):
            with self.assertRaises(S.StoreRefused, msg=bad):
                self.st.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, (bad,), T0)
        for ok in ("status-403", "bad-shape-200", "call-cap", "KEY_REJECTED", "not-json", "unexpected",
                   "ACTIVE_DROP_BASELINE"):
            self.st.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, (ok,), T0)
        self.assertEqual(Y._erp_code(E.ErpError("status", E.PATH_ORG_SNAPSHOT, 987654321)), "status")
        self.assertEqual(Y._erp_code(E.ErpError("status", E.PATH_ORG_SNAPSHOT, True)), "status")
        self.assertEqual(Y._erp_code(E.ErpError("status", E.PATH_ORG_SNAPSHOT, 599)), "status-599")

    def test_future_and_naive_times_refused(self):
        self.clock.t = T0
        for t in (T0 + timedelta(minutes=6), T0.replace(tzinfo=None)):
            with self.assertRaises(S.StoreRefused):
                self.st.record_sync_event(S.SYNC_ORG, S.SYNC_FAILED, ("network",), t)

    def test_reader_reads_but_cannot_write(self):
        self.st.record_sync_event(S.SYNC_STAGES, S.SYNC_FAILED, ("network",), T0)
        r = S.open_reader(self.path)
        try:
            self.assertEqual(r.last_sync(S.SYNC_STAGES)["codes"], ["network"])
            for call in (lambda: r.record_sync_event(S.SYNC_STAGES, S.SYNC_FAILED, ("network",), T0),
                         lambda: r.record_org(org_payload(T0), T0),
                         lambda: r.refuse_org(org_payload(T0), T0, ("ACTIVE_DROP",)),
                         lambda: r.refuse_stages(snap([1], T0), ("IMPLAUSIBLE_FIRST",)),
                         lambda: r.confirm_prospects_hold(1, 0), lambda: r.confirm_accounts_hold(1, 0)):
                with self.assertRaises(S.StoreRefused):
                    call()
        finally:
            r.close()

    def test_last_sync_filters_and_orders(self):
        self.st.record_sync_event(S.SYNC_ORG, S.SYNC_FAILED, ("a",), T0)
        self.st.record_sync_event(S.SYNC_STAGES, S.SYNC_FAILED, ("b",), T0 + timedelta(minutes=1))
        self.st.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, ("c",), T0 + timedelta(minutes=2))
        self.assertEqual(self.st.last_sync(S.SYNC_ORG)["codes"], ["c"])
        self.assertEqual(self.st.last_sync(S.SYNC_ORG, S.SYNC_FAILED)["codes"], ["a"])
        self.assertIsNone(self.st.last_sync(S.SYNC_ACCOUNTS))
        self.assertEqual([d["kind"] for d in self.st.sync_log()], ["org", "stages", "org"])
        for bad in (("naver", None), ("org", "done")):
            with self.assertRaises(S.StoreRefused):
                self.st.last_sync(*bad)


# ── 조직 수락본 ─────────────────────────────────────────────────────
class OrgStoreTest(Base):
    def test_only_kept_fields_are_stored(self):
        def leak(b):
            b["phone_numbers"] = [PHONE_MARK]
            for e in b["employees"]:
                e["login_id"] = LOGIN_MARK
                e["phone"] = PHONE_MARK
            b["owners"][0]["memo"] = PHONE_MARK
            b["teams"][0]["secret"] = LOGIN_MARK
        self.st.record_org(org_payload(T0, extra=leak), T0)
        self.st.refuse_org(org_payload(T0 + timedelta(hours=1), extra=leak), T0 + timedelta(hours=1), ("ACTIVE_DROP",))
        for body in (self.st.org_current()["body"], self.st.hold(S.SYNC_ORG)["body"]):   # 붙잡음도 남길 칸만
            self.assertEqual(set(body), {"generated_at", "teams", "employees", "owners"})
            self.assertTrue(all(set(e) <= set(F.ORG_EMPLOYEE) for e in body["employees"]))
            self.assertTrue(all(set(t) <= set(F.ORG_TEAM) for t in body["teams"]))
            self.assertTrue(all(set(o) <= set(F.ORG_OWNER) for o in body["owners"]))
        raw = self.file_bytes()
        for mark in (PHONE_MARK, LOGIN_MARK):
            self.assertNotIn(mark.encode(), raw)

    def test_values_must_be_flat(self):
        for bad in ({"a": 1}, [1], 1.5, float("nan"), "x" * 201, "a\x00b", 2 ** 64, "\ud83d직원"):
            p = org_payload(T0)
            p["employees"][0]["name"] = bad
            with self.assertRaises(S.StoreRefused, msg=repr(bad)[:30]):
                self.st.record_org(p, T0)
        self.assertIsNone(self.st.org_current())

    def test_shape_refused(self):
        for mutate in (lambda b: b.pop("owners"), lambda b: b.__setitem__("teams", "x"),
                       lambda b: b.__setitem__("employees", [1]), lambda b: b.__setitem__("generated_at", "어제"),
                       lambda b: b.__setitem__("generated_at", "2026-09-29T10:00:00"),
                       lambda b: b.__setitem__("generated_at", "0001-01-01T00:00:00+10:00")):
            p = org_payload(T0)
            mutate(p)
            with self.assertRaises(S.StoreRefused):
                self.st.record_org(p, T0)
        with self.assertRaises(S.StoreRefused):
            self.st.record_org([], T0)

    def test_confirmation_needs_hold(self):
        for kw in ({"confirmed_by": 0}, {"hold_id": 1}):
            with self.assertRaises(S.StoreRefused, msg=kw):
                self.st.record_org(org_payload(T0), T0, **kw)
        hid = self.st.refuse_org(org_payload(T0), T0, ("ACTIVE_DROP",))
        other = org_payload(T0, staff=29)
        self.at(T0 + timedelta(minutes=1))
        with self.assertRaises(S.StoreRefused):   # 확인한 본문과 다른 본문
            self.st.record_org(other, T0 + timedelta(minutes=1), confirmed_by=0, hold_id=hid)
        self.assertIsNone(self.st.hold(S.SYNC_ORG)["used_at"])
        self.st.record_org(org_payload(T0), T0 + timedelta(minutes=1), confirmed_by=0, hold_id=hid)
        self.assertEqual(self.st.last_sync(S.SYNC_ORG)["codes"], ["ACTIVE_DROP", "CONFIRMED"])

    def test_unreadable_row_overwritten_only_by_unreadable_hold(self):
        self.st.record_org(org_payload(T0), T0)
        self.raw("UPDATE naver_auto_org SET generated_at = 'x'")
        t1 = self.at(T0 + timedelta(hours=1))
        with self.assertRaises(S.StoreRefused):
            self.st.record_org(org_payload(t1), t1)
        hid = self.st.refuse_org(org_payload(t1), t1, ("ACTIVE_DROP",))
        with self.assertRaises(S.StoreRefused):
            self.st.record_org(org_payload(t1), t1, confirmed_by=0, hold_id=hid)
        hid = self.st.refuse_org(org_payload(t1), t1, ("STORED_UNREADABLE",))
        self.st.record_org(org_payload(t1), t1, confirmed_by=0, hold_id=hid)
        self.assertEqual(self.st.org_current()["generated_at"], t1)

    def test_baseline_kept_and_checked(self):
        for bad in ((1, 2), (1, 2, -1), (1, 2, True), [1, 2, "3"], {"active": 1}):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)):
                self.st.record_org(org_payload(T0), T0, baseline=bad)
        self.st.record_org(org_payload(T0), T0, baseline=(32, 40, 2))
        self.st.record_org(org_payload(T0 + timedelta(hours=1)), T0 + timedelta(hours=1), baseline=(30, 45, 3))
        self.assertEqual(self.st.org_baseline(), {"active": 32, "owners": 45, "managers": 2})
        self.raw("UPDATE naver_auto_meta SET value = '{\"active\": 1}' WHERE key = 'org_baseline'")
        with self.assertRaises(S.StoreError):
            self.st.org_baseline()

    def test_only_newer_snapshot_replaces(self):
        self.st.record_org(org_payload(T0 + timedelta(hours=1)), T0 + timedelta(hours=1))
        for t in (T0 + timedelta(hours=1), T0):
            with self.assertRaises(S.StoreRefused):
                self.st.record_org(org_payload(t), T0 + timedelta(hours=2))
        self.st.record_org(org_payload(T0 + timedelta(hours=1, microseconds=1)), T0 + timedelta(hours=2))
        self.assertEqual(self.st.org_current()["generated_at"], T0 + timedelta(hours=1, microseconds=1))

    def test_future_limits(self):
        self.clock.t = T0
        with self.assertRaises(S.StoreRefused):
            self.st.record_org(org_payload(T0 + timedelta(minutes=10, seconds=1)), T0)
        self.st.record_org(org_payload(T0 + timedelta(minutes=10)), T0)        # ① 시각은 10분까지(스냅숏 검사와 같게)
        with self.assertRaises(S.StoreRefused):
            self.st.record_org(org_payload(T0 + timedelta(minutes=10, microseconds=1)), T0)
        self.clock.t = T0 + timedelta(minutes=1)
        with self.assertRaises(S.StoreRefused):   # ① 시각은 괜찮아도(지금+9분) 받은 시각은 5분까지
            self.st.record_org(org_payload(T0 + timedelta(minutes=10, seconds=1)), T0 + timedelta(minutes=6, seconds=1))
        self.assertEqual(self.st.org_current()["generated_at"], T0 + timedelta(minutes=10))
        self.st.record_org(org_payload(T0 + timedelta(minutes=10, seconds=1)), T0 + timedelta(minutes=6))

    def test_slack_matches_snapshot_check(self):
        self.assertEqual(S.ORG_FUTURE_SLACK, O.FUTURE_TOLERANCE)

    def test_survives_restart_and_round_trips_through_parser(self):
        p = org_payload(T0)
        self.st.record_org(p, T0, warnings=("UNKNOWN_STATUS",))
        self.reopen()
        cur = self.st.org_current()
        self.assertEqual((cur["generated_at"], cur["received_at"], cur["confirmed_by"]), (T0, T0, None))
        a, b = O.parse_org_snapshot(p), O.parse_org_snapshot(cur["body"])
        self.assertEqual((dict(a.people), a.owners, dict(a.teams)), (dict(b.people), b.owners, dict(b.teams)))
        log = self.st.last_sync(S.SYNC_ORG)
        self.assertEqual((log["codes"], log["row_count"], log["detail"]),
                         (["UNKNOWN_STATUS"], 40, {"employees": 32, "teams": 4}))

    def test_generated_time_stored_in_kst_and_compared_as_time(self):
        utc = (T0 + timedelta(hours=1)).astimezone(timezone.utc)
        self.st.record_org(org_payload(utc), T0 + timedelta(hours=1))
        self.assertEqual(self.st.org_current()["generated_at"].utcoffset(), timedelta(hours=9))
        with self.assertRaises(S.StoreRefused):   # 글자는 달라도 같은 시각 — 새것이 아니다
            self.st.record_org(org_payload(T0 + timedelta(hours=1)), T0 + timedelta(hours=2))

    def test_naive_stored_times_are_unreadable(self):
        self.st.record_org(org_payload(T0), T0)
        for col in ("generated_at", "received_at", "accepted_at"):
            self.raw(f"UPDATE naver_auto_org SET {col} = '2026-09-29T10:00:00'")
            with self.assertRaises(S.StoreError, msg=col):
                self.st.org_current()
            self.raw(f"UPDATE naver_auto_org SET {col} = ?", (T0.isoformat(),))
        self.assertEqual(self.st.org_current()["generated_at"], T0)


# ── 조직 동기화 ─────────────────────────────────────────────────────
class SyncOrgTest(Base):
    def sync(self, payload, t):
        self.at(t)
        return Y.sync_org(FakeErp(payload), self.st, t)

    def test_first_time_accepted(self):
        r = self.sync(org_payload(T0), T0)
        self.assertEqual((r.outcome, r.rows, r.needs_confirmation, r.alert, r.hold_id), ("accepted", 40, False, False, None))
        self.assertEqual(self.st.org_current()["generated_at"], T0)
        self.assertEqual(self.st.org_baseline(), {"active": 32, "owners": 40, "managers": 2})

    def test_drop_refused_held_survives_restart_then_confirmed(self):
        self.sync(org_payload(T0), T0)
        t1 = T0 + timedelta(hours=1)
        r = self.sync(org_payload(t1, resigned=10), t1)   # 재직 32 → 22 (31%)
        self.assertEqual((r.outcome, r.needs_confirmation, r.alert), ("refused", True, True))
        self.assertEqual(r.codes, ("ACTIVE_DROP", "ACTIVE_DROP_BASELINE"))
        self.assertEqual(r.hold_id, self.st.last_sync(S.SYNC_ORG)["sync_id"])
        self.assertEqual(self.st.org_current()["generated_at"], T0)             # 수락본 그대로
        self.reopen()                                                           # 엔진을 다시 켜도(M12)
        t2 = T0 + timedelta(hours=2)
        r2 = self.sync(org_payload(t2, resigned=10), t2)
        self.assertEqual(r2.outcome, "refused")                                 # 이전 조직을 잊지 않는다
        self.assertNotEqual(r2.hold_id, r.hold_id)
        t3 = self.at(t2 + timedelta(minutes=5))
        self.assertEqual(Y.confirm_org(self.st, t3, 0, r.hold_id).codes, (S.HOLD_NOT_FOUND,))   # 옛 붙잡음
        r3 = Y.confirm_org(self.st, t3, 0, r2.hold_id)
        self.assertEqual((r3.outcome, r3.codes), ("accepted", ("ACTIVE_DROP", "ACTIVE_DROP_BASELINE", "CONFIRMED")))
        log = self.st.last_sync(S.SYNC_ORG)
        self.assertEqual((log["confirmed_by"], log["codes"]), (0, ["ACTIVE_DROP", "ACTIVE_DROP_BASELINE", "CONFIRMED"]))
        self.assertEqual([d["outcome"] for d in self.st.sync_log(S.SYNC_ORG)],
                         ["accepted", "refused", "refused", "accepted"])
        self.assertEqual(self.st.org_current()["generated_at"], t2)
        self.assertEqual(self.st.org_baseline()["active"], 22)                  # 확인하면 기준선을 새로

    def test_confirm_takes_held_body_not_a_new_read(self):
        """확인하는 순간 ① 을 다시 읽지 않는다 — 대표가 보지 못한 권한 확대가 끼어들 틈이 없다(S7 검토)."""
        self.sync(org_payload(T0), T0)
        t1 = T0 + timedelta(hours=1)
        r = self.sync(org_payload(t1, resigned=10), t1)

        def worse(b):   # 확인하는 사이 ① 이 이런 걸 돌려준다 해도 — 읽지 않으므로 들어올 수 없다
            b["employees"][1]["is_top_manager"] = True
            b["teams"][1].update(name="보통팀", is_system=False)
        fake = FakeErp(org_payload(t1 + timedelta(minutes=30), resigned=10, extra=worse))
        t2 = self.at(t1 + timedelta(minutes=30))
        r2 = Y.confirm_org(self.st, t2, 0, r.hold_id)
        self.assertEqual((r2.outcome, fake.calls), ("accepted", 0))
        org = O.parse_org_snapshot(self.st.org_current()["body"])
        self.assertEqual((org.top_managers(), org.active_count(), org.is_system_team(1)), (frozenset({0}), 22, True))
        self.assertEqual(self.st.org_current()["generated_at"], t1)

    def test_confirm_refuses_when_a_new_reason_appears(self):
        self.sync(org_payload(T0), T0)
        t1 = T0 + timedelta(hours=1)
        r = self.sync(org_payload(t1, resigned=10), t1)
        self.raw("UPDATE naver_auto_org SET body = ?", (json.dumps({"generated_at": T0.isoformat(), "teams": []}),))
        t2 = self.at(t1 + timedelta(minutes=10))
        r2 = Y.confirm_org(self.st, t2, 0, r.hold_id)   # 대표가 본 것은 감소 — 지금은 수락본을 못 읽음(새 이유)
        self.assertEqual((r2.outcome, r2.codes, r2.needs_confirmation), ("refused", ("STORED_UNREADABLE",), True))
        self.assertNotEqual(r2.hold_id, r.hold_id)
        self.assertEqual(self.st.org_current()["generated_at"], T0)
        r3 = Y.confirm_org(self.st, t2, 0, r2.hold_id)
        self.assertEqual(r3.outcome, "accepted")
        self.assertEqual(self.st.org_current()["generated_at"], t1)

    def test_basic_checks_are_never_held(self):
        cases = {
            "EMPTY": lambda b: b.__setitem__("employees", []),
            "TOP_MANAGER_NONE": lambda b: b["employees"].__setitem__(0, emp(0, "대표", 0, manager=True, top=False)),
            "FORMAT": lambda b: b.pop("owners"),
            "CYCLE": lambda b: b["teams"].__setitem__(2, team(10, "관리 본부", 1, 11)),
        }
        for code, mutate in cases.items():
            r = self.sync(org_payload(T0, extra=mutate), T0)
            self.assertEqual((r.outcome, r.needs_confirmation, r.hold_id, r.alert), ("refused", False, None, True), code)
            self.assertIn(code, r.codes)
        self.assertIsNone(self.st.org_current())
        self.assertIsNone(self.st.hold(S.SYNC_ORG))

    def test_mixed_confirmable_and_basic_is_not_held(self):
        self.sync(org_payload(T0), T0)
        t1 = T0 + timedelta(hours=1)
        r = self.sync(org_payload(t1, resigned=10, extra=lambda b: b["teams"].__setitem__(2, team(10, "본부", 1, 11))), t1)
        self.assertTrue({"ACTIVE_DROP", "CYCLE"} <= set(r.codes))
        self.assertEqual((r.needs_confirmation, r.hold_id, r.alert), (False, None, True))
        self.assertIsNone(self.st.hold(S.SYNC_ORG))

    def test_confirm_hold_problems(self):
        self.assertEqual(Y.confirm_org(self.st, self.at(T0), 0, 1).codes, (S.HOLD_NOT_FOUND,))
        self.sync(org_payload(T0), T0)
        t1 = T0 + timedelta(hours=1)
        r = self.sync(org_payload(t1, resigned=10), t1)
        n = len(self.st.sync_log(S.SYNC_ORG))
        for bad in (True, "1", None, r.hold_id + 1, 0):
            self.assertEqual(Y.confirm_org(self.st, t1, 0, bad).codes, (S.HOLD_NOT_FOUND,), repr(bad))
        for bad in (-1, True, "0", None, 1.0):
            with self.assertRaises(ValueError, msg=repr(bad)):
                Y.confirm_org(self.st, t1, bad, r.hold_id)
        late = t1 + S.HOLD_TTL + timedelta(microseconds=1)
        self.assertEqual(Y.confirm_org(self.st, late, 0, r.hold_id).codes, (S.HOLD_EXPIRED,))
        self.assertEqual(len(self.st.sync_log(S.SYNC_ORG)), n)                 # 붙잡음 문제는 기록을 남기지 않는다
        self.assertEqual(Y.confirm_org(self.st, t1, 0, r.hold_id).outcome, "accepted")
        self.assertEqual(Y.confirm_org(self.st, t1, 0, r.hold_id).codes, (S.HOLD_USED,))
        with self.assertRaises(ValueError):
            Y.confirm_org(self.st, t1.replace(tzinfo=None), 0, r.hold_id)

    def test_newer_accepted_org_supersedes_hold(self):
        self.sync(org_payload(T0), T0)
        t1 = T0 + timedelta(hours=1)
        r = self.sync(org_payload(t1, resigned=10), t1)
        t2 = t1 + timedelta(minutes=20)
        self.assertEqual(self.sync(org_payload(t2), t2).outcome, "accepted")   # ① 이 나아져 확인 없이 받음
        self.assertEqual(Y.confirm_org(self.st, t2, 0, r.hold_id).codes, (S.HOLD_SUPERSEDED,))

    def test_erp_failure_recorded_without_touching_stored(self):
        self.sync(org_payload(T0), T0)
        for err, code in ((E.ErpError("status", E.PATH_ORG_SNAPSHOT, 403), "status-403"),
                          (E.ErpError("status", E.PATH_ORG_SNAPSHOT, 9999), "status"),
                          (E.ErpError("network", E.PATH_ORG_SNAPSHOT, None, "URLError"), "network"),
                          (E.ErpIncomplete("bad-shape", E.PATH_ORG_SNAPSHOT, 200), "bad-shape-200")):
            r = self.sync(err, T0 + timedelta(hours=1))
            self.assertEqual((r.outcome, r.codes), ("failed", (code,)))
        self.assertEqual(self.st.org_current()["generated_at"], T0)
        self.assertEqual(self.st.last_sync(S.SYNC_ORG)["codes"], ["bad-shape-200"])

    def test_unreadable_stored_copy_is_not_treated_as_first_time(self):
        self.sync(org_payload(T0), T0)
        self.raw("UPDATE naver_auto_org SET body = ?", (json.dumps({"generated_at": T0.isoformat(), "teams": []}),))
        t1 = T0 + timedelta(hours=1)
        r = self.sync(org_payload(t1, resigned=10), t1)
        self.assertEqual((r.outcome, r.codes, r.needs_confirmation), ("refused", ("STORED_UNREADABLE",), True))
        self.assertEqual(Y.confirm_org(self.st, t1, 0, r.hold_id).outcome, "accepted")

    def test_row_missing_with_accepted_log_is_unreadable(self):
        """수락본 줄이 사라져도(바깥 손·부분 복원) 받은 기록이 있으면 처음 받기로 여기지 않는다(S7 검토 · M12)."""
        self.sync(org_payload(T0), T0)
        self.raw("DELETE FROM naver_auto_org")
        t1 = T0 + timedelta(hours=1)
        r = self.sync(org_payload(t1, resigned=25, owners=5), t1)
        self.assertEqual((r.outcome, r.codes, r.needs_confirmation), ("refused", ("STORED_UNREADABLE",), True))
        self.assertIsNone(self.st.org_current())

    def test_corrupt_or_naive_generated_column_is_recoverable_by_confirmation(self):
        for bad in ("x", "2026-09-29T10:00:00"):
            with self.subTest(bad=bad):
                self.reopen()
                self.raw("DELETE FROM naver_auto_org")
                self.raw("DELETE FROM naver_auto_sync_log")
                self.raw("DELETE FROM naver_auto_hold")
                self.raw("DELETE FROM naver_auto_meta WHERE key = 'org_baseline'")
                self.sync(org_payload(T0), T0)
                self.raw("UPDATE naver_auto_org SET generated_at = ?", (bad,))
                self.assertEqual(Y.org_freshness(self.st, T0), O.FRESH_STALE)
                t1 = T0 + timedelta(hours=1)
                r = self.sync(org_payload(t1), t1)
                self.assertEqual((r.codes, r.needs_confirmation), (("STORED_UNREADABLE",), True))
                self.assertEqual(Y.confirm_org(self.st, t1, 0, r.hold_id).outcome, "accepted")
                self.assertEqual(self.st.org_current()["generated_at"], t1)

    def test_values_the_store_would_refuse_are_format_results(self):
        """검사는 받는데 저장이 거절하던 값(201자 · NUL · 짝 없는 반쪽 대리 문자 · 2**63) — 결과로 돌려주고 알린다(S7 검토)."""
        for bad in ("x" * 201, "a\x00b", "\ud83d직원", 2 ** 63):
            with self.subTest(bad=repr(bad)[:20]):
                key = "idx" if isinstance(bad, int) else "name"
                r = self.sync(org_payload(T0, extra=lambda b: b["employees"][3].__setitem__(key, bad)), T0)
                self.assertEqual((r.outcome, r.codes, r.alert), ("refused", ("FORMAT",), True))
        self.assertEqual(len(self.st.sync_log(S.SYNC_ORG)), 4)
        self.assertFalse(Y.org_due(self.st, T0 + timedelta(minutes=59)))

    def test_unreadable_times_are_format_results(self):
        for gen in ("0001-01-01T00:00:00+10:00", "9999-12-31T23:59:59-10:00", " 2026-09-29T10:00:00+09:00",
                    "2026-09-29T10:00:00+09:00" + " " * 60):
            r = self.sync(org_payload(T0, extra=lambda b: b.__setitem__("generated_at", gen)), T0)
            self.assertEqual((r.outcome, r.codes), ("refused", ("FORMAT",)), gen)

    def test_unexpected_reader_errors_are_results_but_type_errors_surface(self):
        for err in (RecursionError("deep"), OverflowError("big"), ValueError("x")):
            r = self.sync(err, T0)
            self.assertEqual((r.outcome, r.codes), ("failed", ("unexpected",)), repr(err))
        self.assertEqual(self.st.last_sync(S.SYNC_ORG)["codes"], ["unexpected"])
        with self.assertRaises(TypeError):   # 부르는 모양이 틀린 것은 결과로 덮지 않는다
            self.sync(TypeError("bug"), T0)

    def test_reused_reader_refused(self):
        for f in (FakeErp(org_payload(T0)), object()):
            if isinstance(f, FakeErp):
                f.calls = 1
            with self.assertRaises(ValueError):
                Y.sync_org(f, self.st, T0)
            with self.assertRaises(ValueError):
                Y.sync_stages(f, self.st, T0)
        self.assertEqual(self.st.sync_log(), [])

    def test_wrapped_payload_accepted_and_unwrapped_in_store(self):
        r = self.sync({"status": 200, "result": org_payload(T0)}, T0)
        self.assertEqual(r.outcome, "accepted")
        self.assertIn("employees", self.st.org_current()["body"])

    def test_warning_codes_only_in_log(self):
        def odd(b):
            b["employees"][2]["status"] = None
        r = self.sync(org_payload(T0, extra=odd), T0)
        self.assertEqual((r.outcome, r.codes), ("accepted", ("UNKNOWN_STATUS",)))
        log = self.st.last_sync(S.SYNC_ORG)
        self.assertEqual(log["codes"], ["UNKNOWN_STATUS"])
        self.assertNotIn("100", json.dumps(log["codes"]))

    def test_store_refusal_becomes_result(self):
        def refuse(*a, **k):
            raise S.StoreRefused("x")
        self.st.record_org = refuse
        r = self.sync(org_payload(T0), T0)
        self.assertEqual((r.outcome, r.codes, r.needs_confirmation, r.alert), ("refused", ("STORE_REFUSED",), False, True))
        self.assertEqual(self.st.last_sync(S.SYNC_ORG)["codes"], ["STORE_REFUSED"])

    def test_naive_now_is_caller_error(self):
        with self.assertRaises(ValueError):
            Y.sync_org(FakeErp(org_payload(T0)), self.st, T0.replace(tzinfo=None))

    def test_confirmable_codes_are_exactly_the_comparison_codes(self):
        """버림 코드마다 「확인으로 풀 수 있나」가 정해져 있어야 한다 — 새 코드가 생기면 이 시험이 결정을 요구한다.

        버림(reasons)과 경고(warnings)를 따로 모은다 — 경고를 버림으로 옮기면 이 시험이 잡는다."""
        tree = ast.parse((BACKEND / "app" / "naver_auto" / "org_snapshot.py").read_text(encoding="utf-8"))
        check = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "check_snapshot")
        got = {"reasons": set(), "warnings": set()}
        findings = 0
        for n in ast.walk(check):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Finding":
                findings += 1
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append"
                    and isinstance(n.func.value, ast.Name) and n.func.value.id in got):
                arg = n.args[0]
                self.assertTrue(isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "Finding"
                                and isinstance(arg.args[0], ast.Constant))
                got[n.func.value.id].add(arg.args[0].value)
        prev_only = {"ACTIVE_DROP", "OWNER_DROP", "OWNER_BLANK_SPIKE", "TOP_MANAGER_ADDED", "SYSTEM_TEAM_LOST",
                     "MANAGER_SPIKE", "PARENT_LOST", "STALE"}
        basic = {"EMPTY", "CYCLE", "TOP_MANAGER_NONE", "TOP_MANAGER_LIMIT", "FUTURE"}
        warn = {"ORPHAN_TEAM", "UNKNOWN_STATUS", "UNKNOWN_TEAM_REF", "UNKNOWN_OWNER_SOURCE", "TOP_MANAGER_COUNT"}
        self.assertEqual(got["reasons"], prev_only | basic)
        self.assertEqual(got["warnings"], warn)
        self.assertEqual(findings, sum(1 for n in ast.walk(check) if isinstance(n, ast.Call)
                                       and isinstance(n.func, ast.Attribute) and n.func.attr == "append"))
        baseline = {"ACTIVE_DROP_BASELINE", "OWNER_DROP_BASELINE", "MANAGER_SPIKE_BASELINE"}
        self.assertEqual(Y.CONFIRMABLE_ORG_CODES, (prev_only - {"STALE"}) | {"STORED_UNREADABLE"} | baseline)
        self.assertEqual(Y.CONFIRMABLE_STAGE_CODES,
                         {"BRAKE", "BRAKE_STAGE", "BRAKE_BASELINE", "IMPLAUSIBLE_FIRST", "STAGE_EMPTY_FIRST"})

    def test_each_confirmable_code_disappears_without_prev(self):
        base = org_payload(T0, staff=30, owners=40)
        prev = O.accept_snapshot(base, None).org
        later = T0 + timedelta(hours=1)
        scenarios = {
            "ACTIVE_DROP": org_payload(later, resigned=10),
            "OWNER_DROP": org_payload(later, owners=30),
            "OWNER_BLANK_SPIKE": org_payload(later, extra=lambda b: [o.update(manage_emp_idx=None, owner_source="none")
                                                                      for o in b["owners"][:10]]),
            "TOP_MANAGER_ADDED": org_payload(later, extra=lambda b: b["employees"][1].update(is_top_manager=True)),
            "SYSTEM_TEAM_LOST": org_payload(later, extra=lambda b: b["teams"][1].update(name="보통팀", is_system=False)),
            "MANAGER_SPIKE": org_payload(later, extra=lambda b: [e.update(is_manager=True) for e in b["employees"][2:6]]),
            "PARENT_LOST": org_payload(later, extra=lambda b: b["teams"].pop(2)),
        }
        for code, payload in scenarios.items():
            with_prev = O.accept_snapshot(payload, prev, later)
            self.assertIn(code, {f.code for f in with_prev.reasons}, code)
            self.assertTrue(O.accept_snapshot(payload, None, later).ok, code)


# ── 조직 기준선 — 조금씩 나빠지는 톱니 ────────────────────────────────────
class OrgBaselineTest(Base):
    def sync(self, payload, t):
        self.at(t)
        return Y.sync_org(FakeErp(payload), self.st, t)

    def step(self, h, **kw):
        t = T0 + timedelta(hours=h)
        return self.sync(org_payload(t, **kw), t)

    def test_active_ratchet(self):
        self.step(0)                                                    # 재직 32
        self.assertEqual(self.step(1, resigned=6).outcome, "accepted")  # 26 (18.8%)
        r = self.step(2, resigned=11)                                   # 21 — 직전 대비 19.2% · 기준선 대비 34%
        self.assertEqual((r.codes, r.needs_confirmation), (("ACTIVE_DROP_BASELINE",), True))
        self.assertEqual(Y.confirm_org(self.st, T0 + timedelta(hours=2), 0, r.hold_id).outcome, "accepted")
        self.assertEqual(self.st.org_baseline()["active"], 21)
        self.assertEqual(self.step(3, resigned=12).outcome, "accepted")

    def test_owner_ratchet(self):
        self.step(0)
        self.assertEqual(self.step(1, owners=33).outcome, "accepted")   # 17.5%
        self.assertEqual(self.step(2, owners=27).codes, ("OWNER_DROP_BASELINE",))   # 직전 18.2% · 기준선 32.5%

    def test_manager_ratchet(self):
        self.step(0)                                                    # 팀장 2
        up = lambda k: (lambda b: [e.update(is_manager=True) for e in b["employees"][2:2 + k]])
        self.assertEqual(self.step(1, extra=up(2)).outcome, "accepted")            # 4 — 2명만 늘어 버림 아님
        self.assertEqual(self.step(2, extra=up(4)).codes, ("MANAGER_SPIKE_BASELINE",))   # 6 — 기준선 2 대비 4명


# ── 신선도 ─────────────────────────────────────────────────────────
class FreshnessTest(Base):
    def test_bands(self):
        self.assertEqual(Y.org_freshness(self.st, T0), O.FRESH_NONE)
        self.at(T0)
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0)
        us = timedelta(microseconds=1)
        for dt, want in ((timedelta(0), "fresh"), (timedelta(hours=3), "fresh"), (timedelta(hours=3) + us, "yellow"),
                         (timedelta(hours=26), "yellow"), (timedelta(hours=26) + us, "stale")):
            self.assertEqual(Y.org_freshness(self.st, T0 + dt), want, dt)
        self.assertEqual(O.org_freshness(T0 + timedelta(minutes=10), T0), "fresh")
        self.assertEqual(O.org_freshness(T0 + timedelta(minutes=10) + us, T0), "stale")   # 믿을 수 없는 미래

    def test_age_counts_from_erp_generated_time_not_receipt(self):
        self.at(T0 + timedelta(hours=2))
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0 + timedelta(hours=2))   # ① 가 10:00 에 만든 것을 12:00 에 받음
        self.assertEqual(Y.org_freshness(self.st, T0 + timedelta(hours=3, microseconds=1)), "yellow")

    def test_unusable_stored_copy_is_stale(self):
        """쓸 수 없는 수락본으로 올리기 관문을 열지 않는다(S7 검토) — 본문이 망가짐 · 못 읽음 · 줄이 사라짐."""
        self.at(T0)
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0)
        for sql, args in (("UPDATE naver_auto_org SET body = ?", (json.dumps({"generated_at": "x", "teams": []}),)),
                          ("UPDATE naver_auto_org SET body = 'x'", ()),
                          ("DELETE FROM naver_auto_org", ())):
            self.raw(sql, args)
            self.assertEqual(Y.org_freshness(self.st, T0), O.FRESH_STALE, sql)
            self.assertFalse(O.allows_raising(Y.org_freshness(self.st, T0)))

    def test_raising_allowed_only_fresh_or_yellow(self):
        self.assertEqual([O.allows_raising(x) for x in ("fresh", "yellow", "stale", "none", "")],
                         [True, True, False, False, False])

    def test_design_hours(self):
        self.assertEqual((O.ORG_YELLOW_AFTER, O.ORG_STALE_AFTER), (timedelta(hours=3), timedelta(hours=26)))

    def test_naive_times_refused(self):
        with self.assertRaises(ValueError):
            O.org_freshness(T0, T0.replace(tzinfo=None))
        with self.assertRaises(ValueError):
            O.org_freshness(T0.replace(tzinfo=None), T0)
        with self.assertRaises(ValueError):
            Y.org_freshness(self.st, T0.replace(tzinfo=None))


# ── 계약 단계 동기화 ────────────────────────────────────────────────
class SyncStagesTest(Base):
    def run_stages(self, stages, t):
        self.at(t)
        return Y.sync_stages(FakeErp(stages=stages), self.st, t)

    def test_first_run_must_be_plausible_then_confirm_takes_held_list(self):
        r = self.run_stages(snap(range(1, 301), T0), T0)
        self.assertEqual((r.outcome, r.codes, r.needs_confirmation, r.alert), ("refused", ("IMPLAUSIBLE_FIRST",), True, True))
        self.assertIsNotNone(r.hold_id)
        self.assertEqual(self.st.prospects(), [])
        self.assertIsNone(self.st.stage_as_of())
        r2 = Y.confirm_stages(self.st, T0, 0, r.hold_id)
        self.assertEqual((r2.outcome, r2.rows, r2.codes), ("accepted", 300, ("CONFIRMED",)))
        self.assertEqual(self.st.last_sync(S.SYNC_STAGES)["codes"], ["IMPLAUSIBLE_FIRST", "CONFIRMED"])

    def test_first_run_needs_every_required_stage(self):
        """환불중이 통째로 빠진 첫 목록(805곳)은 940 ±20% 안이라도 받지 않는다(S7 검토 · 반박 H3)."""
        no_refund = {p: "진행중" for p in range(1, 941) if stage_of(p) == "환불중"}
        r = self.run_stages(snap(range(1, 941), T0, stages=no_refund), T0)
        self.assertEqual((r.outcome, r.codes, r.needs_confirmation), ("refused", ("STAGE_EMPTY_FIRST",), True))
        self.assertEqual(Y.FIRST_REQUIRED_STAGES, ("진행중", "전략관리", "사후관리", "홀딩중", "환불중"))
        self.assertTrue(set(Y.FIRST_REQUIRED_STAGES) <= set(E.STAGE_SPELLINGS))

    def test_first_run_check_survives_failed_and_refused_attempts(self):
        self.run_stages(E.ErpIncomplete("network", E.PATH_CONTRACTS), T0)
        r = self.run_stages(snap(range(1, 301), T0 + timedelta(hours=1)), T0 + timedelta(hours=1))
        self.assertEqual(r.codes, ("IMPLAUSIBLE_FIRST",))
        r = self.run_stages(snap(range(1, 301), T0 + timedelta(hours=2)), T0 + timedelta(hours=2))
        self.assertEqual(r.codes, ("IMPLAUSIBLE_FIRST",))   # 버린 기록이 있어도 아직 받은 적은 없다

    def test_result_rows_include_conflicts(self):
        r = self.run_stages(snap(range(1, 301), T0, conflicts=range(301, 311)), T0)
        self.assertEqual((r.codes, r.rows), (("IMPLAUSIBLE_FIRST",), 310))
        self.assertEqual(self.st.last_sync(S.SYNC_STAGES)["row_count"], 310)

    def test_conflicts_count_toward_first_plausibility(self):
        self.assertFalse(snap(range(1, 741), T0).plausible())
        self.assertTrue(snap(range(1, 741), T0, conflicts=range(741, 761)).plausible())
        r = self.run_stages(snap(range(1, 741), T0, conflicts=range(741, 761)), T0)
        self.assertEqual((r.outcome, r.rows), ("accepted", 760))

    def test_plausible_first_then_later_runs_not_compared_to_940(self):
        self.assertEqual(self.run_stages(snap(range(1, 941), T0), T0).outcome, "accepted")
        r = self.run_stages(snap(range(1, 941), T0 + timedelta(hours=6)), T0 + timedelta(hours=6))
        self.assertEqual(r.outcome, "accepted")

    def test_confirmed_small_first_run_then_later_runs_accepted(self):
        r = self.run_stages(snap(range(1, 301), T0), T0)
        Y.confirm_stages(self.st, T0, 0, r.hold_id)
        r = self.run_stages(snap(range(1, 301), T0 + timedelta(hours=6)), T0 + timedelta(hours=6))
        self.assertEqual(r.outcome, "accepted")   # 940 대조는 첫 회차만

    def test_plausible_edges(self):
        for n, ok in ((752, True), (751, False), (1128, True), (1129, False)):
            self.assertEqual(snap(range(n), T0).plausible(), ok, n)

    def test_brake_becomes_result_and_confirm_takes_held_list(self):
        self.run_stages(snap(range(1, 941), T0), T0)
        t = T0 + timedelta(hours=6)
        r = self.run_stages(snap(range(300, 941), t), t)
        self.assertEqual((r.outcome, r.absent, r.needs_confirmation, r.alert), ("braked", 299, True, True))
        self.assertEqual(r.codes, ("BRAKE", "BRAKE_STAGE", "BRAKE_BASELINE"))
        self.assertEqual(sum(p["present"] for p in self.st.prospects()), 940)
        r2 = Y.confirm_stages(self.st, t + timedelta(minutes=5), 0, r.hold_id)
        self.assertEqual((r2.outcome, r2.rows, r2.absent), ("accepted", 641, 299))
        self.assertEqual(Y.confirm_stages(self.st, t, 0, r.hold_id).codes, (S.HOLD_USED,))

    def test_confirm_stages_bad_input(self):
        for bad in (True, "1", None, 0, -3):
            self.assertEqual(Y.confirm_stages(self.st, T0, 0, bad).codes, (S.HOLD_NOT_FOUND,), repr(bad))
        self.assertEqual(Y.confirm_stages(self.st, T0, 0, 12345).codes, (S.HOLD_NOT_FOUND,))
        for bad in (-1, True, None):
            with self.assertRaises(ValueError):
                Y.confirm_stages(self.st, T0, bad, 1)
        with self.assertRaises(ValueError):
            Y.confirm_stages(self.st, T0.replace(tzinfo=None), 0, 1)

    def test_erp_incomplete_changes_nothing(self):
        self.run_stages(snap(range(1, 941), T0), T0)
        r = self.run_stages(E.ErpIncomplete("status", E.PATH_CONTRACTS, 500, "단계 동기화 중단"), T0 + timedelta(hours=6))
        self.assertEqual((r.outcome, r.codes), ("failed", ("status-500",)))
        self.assertEqual(self.st.stage_as_of(), T0)

    def test_old_snapshot_is_store_refusal(self):
        self.run_stages(snap(range(1, 941), T0), T0)
        r = self.run_stages(snap(range(1, 941), T0), T0 + timedelta(hours=6))
        self.assertEqual((r.outcome, r.codes, r.needs_confirmation, r.alert), ("refused", ("STORE_REFUSED",), False, True))

    def test_reader_gets_read_deadline(self):
        for now, want in ((T0, T0 + Y.STAGES_MAX_READ),                                        # 10:00 → 10:10
                          (datetime(2026, 9, 30, 3, 45, tzinfo=KST), datetime(2026, 9, 30, 3, 50, tzinfo=KST)),
                          (datetime(2026, 9, 30, 4, 0, tzinfo=KST), datetime(2026, 9, 30, 4, 0, tzinfo=KST)),
                          (datetime(2026, 9, 29, 23, 55, tzinfo=KST), datetime(2026, 9, 30, 0, 5, tzinfo=KST)),
                          (datetime(2026, 9, 29, 20, 0, tzinfo=timezone.utc),                   # = 9/30 05:00 KST
                           datetime(2026, 9, 29, 20, 10, tzinfo=timezone.utc))):
            self.at(now)
            f = FakeErp(stages=E.ErpIncomplete("deadline", E.PATH_CONTRACTS))
            Y.sync_stages(f, self.st, now)
            self.assertEqual(f.deadlines, [want], now)

    def test_naive_now_is_caller_error(self):
        with self.assertRaises(ValueError):
            Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0)), self.st, T0.replace(tzinfo=None))
        self.assertEqual(self.st.sync_log(), [])

    def test_unexpected_reader_errors_are_results(self):
        r = self.run_stages(RecursionError("deep"), T0)
        self.assertEqual((r.outcome, r.codes), ("failed", ("unexpected",)))
        self.assertEqual(self.st.last_sync(S.SYNC_STAGES)["codes"], ["unexpected"])

    def test_result_repr_has_counts_only(self):
        r = Y.SyncResult("stages", "braked", ("BRAKE",), rows=PID_MARK, absent=3, hold_id=7)
        self.assertNotIn("name", repr(r))
        self.assertIn("rows=", repr(r))
        self.assertIn("hold_id=7", repr(r))


# ── 대표에게 알릴 것(S10 재료) ─────────────────────────────────────────
class AlertTest(Base):
    def test_org_failure_alerts_only_when_it_lasts(self):
        err = E.ErpError("network", E.PATH_ORG_SNAPSHOT)
        self.at(T0)
        self.assertTrue(Y.sync_org(FakeErp(err), self.st, T0).alert)          # 한 번도 받은 적 없음
        t = self.at(T0 + timedelta(hours=1))
        self.assertFalse(Y.sync_org(FakeErp(org_payload(t)), self.st, t).alert)
        for dt, want in ((Y.ORG_ALERT_AFTER - timedelta(minutes=1), False), (Y.ORG_ALERT_AFTER, True)):
            now = self.at(t + dt)
            self.assertEqual(Y.sync_org(FakeErp(err), self.st, now).alert, want, dt)

    def test_stage_failure_alerts_after_twelve_hours(self):
        self.at(T0)
        Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0)), self.st, T0)
        err = E.ErpIncomplete("network", E.PATH_CONTRACTS)
        for dt, want in ((timedelta(hours=11, minutes=59), False), (timedelta(hours=12), True)):
            now = self.at(T0 + dt)
            self.assertEqual(Y.sync_stages(FakeErp(stages=err), self.st, now).alert, want, dt)

    def test_accepted_never_alerts(self):
        self.at(T0)
        self.assertFalse(Y.sync_org(FakeErp(org_payload(T0)), self.st, T0).alert)
        self.assertFalse(Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0)), self.st, T0).alert)


# ── 부르는 때 ───────────────────────────────────────────────────────
class DueTest(Base):
    def test_org_every_hour_after_any_attempt(self):
        self.assertTrue(Y.org_due(self.st, T0))
        self.at(T0)
        Y.sync_org(FakeErp(E.ErpError("network", E.PATH_ORG_SNAPSHOT)), self.st, T0)
        self.assertFalse(Y.org_due(self.st, T0 + timedelta(minutes=59)))
        self.assertTrue(Y.org_due(self.st, T0 + timedelta(hours=1)))

    def test_org_waits_an_hour_after_receipt_not_after_generation(self):
        t = self.at(T0 + timedelta(hours=2))
        Y.sync_org(FakeErp(org_payload(T0)), self.st, t)   # ① 가 두 시간 전에 만든 것을 지금 받음
        self.assertFalse(Y.org_due(self.st, t + timedelta(minutes=59)))
        self.assertTrue(Y.org_due(self.st, t + timedelta(hours=1)))

    def test_org_hold_blocks_calls_until_it_expires(self):
        self.at(T0)
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0)
        t1 = self.at(T0 + timedelta(hours=1))
        r = Y.sync_org(FakeErp(org_payload(t1, resigned=10)), self.st, t1)
        self.assertTrue(r.needs_confirmation)
        self.assertFalse(Y.org_due(self.st, t1 + timedelta(hours=2)))       # 새로 읽으면 대표가 보던 붙잡음이 바뀐다
        self.assertFalse(Y.org_due(self.st, t1 + S.HOLD_TTL))
        self.assertTrue(Y.org_due(self.st, t1 + S.HOLD_TTL + timedelta(microseconds=1)))

    def test_stages_quiet_windows_include_read_time(self):
        day = datetime(2026, 9, 30, tzinfo=KST)
        for hh, mm, due in ((3, 39, True), (3, 40, True), (3, 41, False), (3, 50, False), (4, 19, False),
                            (4, 20, True), (5, 40, True), (5, 41, False), (6, 30, False), (7, 9, False),
                            (7, 10, True)):
            self.assertEqual(Y.stages_due(self.st, day.replace(hour=hh, minute=mm)), due, (hh, mm))
        utc = datetime(2026, 9, 29, 21, 0, tzinfo=timezone.utc)   # = 9/30 06:00 KST
        self.assertFalse(Y.stages_due(self.st, utc))

    def test_stages_every_six_hours_retry_after_one(self):
        t = self.at(datetime(2026, 9, 29, 8, 0, tzinfo=KST))
        Y.sync_stages(FakeErp(stages=snap(range(1, 941), t)), self.st, t)
        self.assertFalse(Y.stages_due(self.st, t + timedelta(hours=5, minutes=59)))
        self.assertTrue(Y.stages_due(self.st, t + timedelta(hours=6)))
        f = self.at(t + timedelta(hours=6))
        Y.sync_stages(FakeErp(stages=E.ErpIncomplete("network", E.PATH_CONTRACTS)), self.st, f)
        self.assertFalse(Y.stages_due(self.st, f + timedelta(minutes=59)))
        self.assertTrue(Y.stages_due(self.st, f + timedelta(hours=1)))

    def test_stages_after_brake_wait_for_confirmation_then_retry(self):
        t = self.at(datetime(2026, 9, 29, 8, 0, tzinfo=KST))
        Y.sync_stages(FakeErp(stages=snap(range(1, 941), t)), self.st, t)
        b = self.at(t + timedelta(hours=6))
        self.assertEqual(Y.sync_stages(FakeErp(stages=snap(range(300, 941), b)), self.st, b).outcome, "braked")
        self.assertFalse(Y.stages_due(self.st, b + timedelta(minutes=59)))
        self.assertFalse(Y.stages_due(self.st, b + timedelta(hours=2)))    # 재시도 1시간은 지났지만 붙잡음을 기다린다
        self.assertTrue(Y.stages_due(self.st, b + S.HOLD_TTL + timedelta(microseconds=1)))
        Y.confirm_stages(self.st, b, 0, self.st.hold(S.SYNC_STAGES)["hold_id"])
        self.assertFalse(Y.stages_due(self.st, b + timedelta(hours=2)))    # 확인 뒤엔 붙잡음이 없다 — 받은 목록 기준 6시간
        self.assertTrue(Y.stages_due(self.st, b + timedelta(hours=6)))

    def test_stages_after_store_refusal_retry_after_one_hour(self):
        t = self.at(datetime(2026, 9, 29, 8, 0, tzinfo=KST))
        Y.sync_stages(FakeErp(stages=snap(range(1, 941), t)), self.st, t)
        f = self.at(t + timedelta(hours=6))
        self.assertEqual(Y.sync_stages(FakeErp(stages=snap(range(1, 941), t)), self.st, f).codes, ("STORE_REFUSED",))
        self.assertFalse(Y.stages_due(self.st, f + timedelta(minutes=59)))
        self.assertTrue(Y.stages_due(self.st, f + timedelta(hours=1)))

    def test_stages_after_first_run_refusal_wait_for_hold(self):
        t = self.at(datetime(2026, 9, 29, 8, 0, tzinfo=KST))
        Y.sync_stages(FakeErp(stages=snap(range(1, 301), t)), self.st, t)
        self.assertFalse(Y.stages_due(self.st, t + timedelta(hours=2)))
        self.assertTrue(Y.stages_due(self.st, t + S.HOLD_TTL + timedelta(microseconds=1)))

    def test_clock_moved_back_does_not_silence(self):
        """마지막 기록이 지금보다 뒤면(시계를 뒤로 고침) 그 시각까지 조용히 기다리지 않는다(S7 검토)."""
        self.at(T0)
        Y.sync_org(FakeErp(E.ErpError("network", E.PATH_ORG_SNAPSHOT)), self.st, T0)
        Y.sync_stages(FakeErp(stages=E.ErpIncomplete("network", E.PATH_CONTRACTS)), self.st, T0)
        back = T0 - timedelta(hours=2)                                   # 08:00 KST — 조용한 창 밖
        self.assertTrue(Y.org_due(self.st, back))
        self.assertTrue(Y.stages_due(self.st, back))
        self.assertFalse(Y.org_due(self.st, T0 - Y.CLOCK_SKEW))           # 몇 분 어긋남은 그대로 기다린다

    def test_design_values(self):
        self.assertEqual(Y.STAGES_QUIET, ((time(3, 50), time(4, 20)), (time(5, 50), time(7, 10))))
        self.assertEqual((Y.ORG_EVERY, Y.STAGES_EVERY, Y.STAGES_RETRY, Y.STAGES_MAX_READ),
                         (timedelta(hours=1), timedelta(hours=6), timedelta(hours=1), timedelta(minutes=10)))
        self.assertEqual((S.HOLD_TTL, Y.ORG_ALERT_AFTER, Y.STAGES_ALERT_AFTER),
                         (timedelta(hours=3), timedelta(hours=3), timedelta(hours=12)))

    def test_stage_stale_threshold_leaves_room_for_retries(self):
        """점검 규칙의 「단계 자료 낡음」 최소가 단계 주기 + 재시도 + 조용한 창보다 커야 한다(S7 검토 — 여유 0)."""
        from app.naver_auto import thresholds as T
        lo, _hi = T.RANGES["stage_stale_hours"]
        quiet = max(datetime.combine(date(2026, 1, 1), b) - datetime.combine(date(2026, 1, 1), a)
                    for a, b in Y.STAGES_QUIET) + Y.STAGES_MAX_READ
        self.assertGreaterEqual(timedelta(hours=lo), Y.STAGES_EVERY + Y.STAGES_RETRY + quiet)
        self.assertGreaterEqual(timedelta(hours=T.DEFAULTS.stage_stale_hours), timedelta(hours=lo))


# ── 구문 시험 — 조직 수락본·붙잡음을 적는 길 · 엔진이 읽는 backend 모듈 ─────────────────
PRIVILEGED = ("record_org", "refuse_org", "refuse_stages", "confirm_prospects_hold", "confirm_accounts_hold",
              "record_pairing", "record_pairing_event",
              # 사람 판단 쓰기 — 「확인」은 자동 규칙을 모두 이긴다. 범위를 검사하는 S11 화면 API(web.py) 한 곳에서만 부른다
              # (검토 security-4)
              "record_decision", "record_decisions", "revoke_decision",
              # 아침 점검(S9) — 계정 하루치·이슈를 따로 적으면 「정상」만 남고 이슈가 빠지거나, 규칙을 거치지 않은 이슈가
              # 생긴다. 회차·계정 결과·연결 해제 닫기는 morning.py 한 곳에서만 · 따로 적는 옛 함수는 어디서도 부르지 않는다
              "begin_run", "finish_run", "record_account_check", "close_unlinked_issues", "record_account_day",
              "record_campaign_days",
              # 이슈 사람의 손길 — 누가 누를 수 있는지 scope 로 판정하는 S11 화면 API(web.py) 한 곳에서만 부른다
              # (그 속 ``_human`` 은 아무 변화든 받아 적는다 — 이름을 직접 불러 한도·사유를 건너뛰지 못하게 · 검토 security-1)
              "ack_issue", "resolve_issue", "except_issue", "_human",
              # 알림(S10) — 받는 사람·문구 틀·보낸 결과를 적는 길은 alerts.py 한 곳(받는 사람 규칙 scope 를 건너뛴 알림 ·
              # 보내지도 않은 「보냄」 기록이 생기지 않게)
              "record_alert", "record_delivery", "record_heartbeat",
              # 화면 API(S11) — 열람·쓰기 기록 · 🔔 읽음 · 기준값은 web.py 한 곳(범위·대표 판정을 건너뛴 쓰기가 없게)
              "record_access", "mark_alert_read", "mark_alerts_read_all", "record_thresholds",
              # G1~G3 — 완결 원천 및 전송 기록은 공유 성과 모듈만 만든다.
              "begin_metrics_attempt", "record_metrics_snapshot", "finish_metrics_attempt")
BANNED_NAMES = ("exec", "eval", "compile", "__import__", "globals", "vars", "locals", "open", "breakpoint",
                "__builtins__", "getattr_static")
BANNED_ATTRS = ("modules", "__dict__", "__getattribute__", "__subclasses__", "__globals__", "__code__",
                "__closure__", "__builtins__", "getattr_static")
ATTR_FUNCS = ("getattr", "setattr", "delattr", "hasattr")


def _folded(tree):
    """글자 상수와, 상수끼리 이어 붙인 글자(「"record_" + "org"」 · f"{'record_'}org" · "".join([...]))."""
    def fold(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            a, b = fold(n.left), fold(n.right)
            return a + b if a is not None and b is not None else None
        if isinstance(n, ast.JoinedStr):
            parts = []
            for v in n.values:
                s = fold(v.value) if isinstance(v, ast.FormattedValue) else fold(v)
                if s is None:
                    return None
                parts.append(s)
            return "".join(parts)
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "join"
                and fold(n.func.value) is not None and len(n.args) == 1):
            parts = _const_items(n.args[0], fold)
            return None if parts is None else fold(n.func.value).join(parts)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mod) and fold(n.left) is not None:   # "%s_%s" % (…)
            args = _const_items(n.right, fold) if isinstance(n.right, (ast.Tuple, ast.List)) else [fold(n.right)]
            try:
                return None if args is None or None in args else fold(n.left) % tuple(args)
            except (TypeError, ValueError):
                return None
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "format"
                and fold(n.func.value) is not None and not n.keywords):             # "{}_{}".format(…)
            args = [fold(a) for a in n.args]
            try:
                return None if None in args else fold(n.func.value).format(*args)
            except (IndexError, KeyError, ValueError):
                return None
        return None
    for n in ast.walk(tree):
        s = fold(n)
        if s is not None:
            yield s


def _const_items(n, fold):
    """글자 목록 — ``[..]`` · ``(..)`` · 상수 목록을 도는 생성식(``w for w in ("a", "b")``)까지(검토 guard-privileged)."""
    if isinstance(n, (ast.List, ast.Tuple)):
        parts = [fold(e) for e in n.elts]
        return None if None in parts else parts
    if isinstance(n, (ast.GeneratorExp, ast.ListComp)) and len(n.generators) == 1 and not n.generators[0].ifs \
            and isinstance(n.elt, ast.Name) and isinstance(n.generators[0].target, ast.Name) \
            and n.elt.id == n.generators[0].target.id:
        return _const_items(n.generators[0].iter, fold)
    return None


def _imports(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield n, a.name
        elif isinstance(n, ast.ImportFrom):
            base = ("." * n.level) + (n.module or "")
            yield n, base
            for a in n.names:
                yield n, f"{base}.{a.name}" if n.module else base + a.name


def _without_docstrings(tree):
    """설명문(문서 문자열)을 뺀 코드 — 설명에 적힌 함수 이름으로 시험이 흔들리지 않게."""
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                body[0] = ast.Pass()
    return tree


def _privileged_uses(tree):
    """특권 저장 함수를 가리키는 곳 — 속성 이름 · 글자(이어 붙인 것 포함) · 글자로 된 getattr 까지."""
    tree = _without_docstrings(tree)
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and n.attr in PRIVILEGED:
            names.add(n.attr)
        if isinstance(n, ast.Name) and n.id in PRIVILEGED:
            names.add(n.id)
    for s in _folded(tree):
        for p in PRIVILEGED:
            if p in s:
                names.add(p + ":str")
    return names


def _escapes(tree):
    """이름·속성·글자로 된 getattr·금지 import — 규칙을 건너뛰는 길."""
    out = []
    called = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ATTR_FUNCS:
            called.add(id(n.func))
            if len(n.args) < 2 or not isinstance(n.args[1], ast.Constant):
                out.append(n.func.id + "(글자 아님)")
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in BANNED_NAMES:
            out.append(n.id)
        if isinstance(n, ast.Attribute) and n.attr in BANNED_ATTRS:
            out.append("." + n.attr)
        if isinstance(n, ast.Name) and n.id in ATTR_FUNCS and id(n) not in called:   # 별칭 · map/partial 에 넘기기
            out.append(n.id + "(값으로 씀)")
    for _n, mod in _imports(tree):
        root = mod.lstrip(".").split(".")[0]
        if root in ("inspect", "builtins", "importlib", "ctypes", "gc", "marshal", "pickle"):
            out.append("import " + mod)
    return out


class SyncGuardTest(unittest.TestCase):
    SOURCES = sorted(p for p in ENGINE.rglob("*.py") if "tests" not in p.relative_to(ENGINE).parts)
    SHARED = sorted((BACKEND / "app" / "naver_auto").glob("*.py"))

    def rel(self, p):
        return p.relative_to(ENGINE).as_posix()

    def test_privileged_store_calls_only_from_sync(self):
        """수락본·붙잡음·짝 결과를 적는 함수(검사 없이 부르면 「이전 조직」·확인 받음·점검할 짝이 가짜가 된다)는
        엔진 맨 위 동기화 모듈 두 곳에서만 — ① 쪽은 sync.py · 네이버 연결 목록·짝은 links.py(S8)."""
        found = {}
        for p in self.SOURCES:
            if self.rel(p) == "store.py":
                continue
            uses = _privileged_uses(ast.parse(p.read_text(encoding="utf-8")))
            if uses:
                found[self.rel(p)] = uses
        self.assertEqual(set(found), {"sync.py", "links.py", "morning.py", "alerts.py", "web.py", "metrics.py"})
        self.assertEqual(found["metrics.py"], {"begin_metrics_attempt", "record_metrics_snapshot", "finish_metrics_attempt"})
        # 사람 판단 · 이슈 손길 · 읽음 · 기준값 · 열람 기록 — scope 로 누를 수 있는 사람을 정한 화면 API 한 곳(S11)
        # 2026-10-02 명세: 현재 보이는 알림만 읽음 처리하므로 전체 일괄 함수는 호출하지 않는다.
        # PRIVILEGED에는 계속 남겨 우회 호출이 추가되면 이 정확한 허용 집합 검사로 거절한다.
        self.assertEqual(found["web.py"], {"record_decisions", "revoke_decision", "ack_issue", "resolve_issue",
                                           "except_issue", "record_access", "mark_alert_read",
                                           "record_thresholds"})
        self.assertEqual(found["alerts.py"], {"record_alert", "record_delivery", "record_heartbeat"})
        self.assertEqual(found["sync.py"], {"record_org", "refuse_org", "refuse_stages", "confirm_prospects_hold"})
        self.assertEqual(found["links.py"], {"confirm_accounts_hold", "record_pairing", "record_pairing_event"})
        self.assertEqual(found["morning.py"], {"begin_run", "finish_run", "record_account_check",
                                               "close_unlinked_issues"})

    def test_privileged_guard_catches_bypasses(self):
        bad = ('def f(st):\n    getattr(st, "record_" + "org")(1, 2)\n',
               'def f(st, k):\n    getattr(st, k)\n',
               'import inspect\ndef f(st):\n    inspect.getattr_static(st, "record_org")\n',
               'def f(st):\n    getattr(st, f"{\'refuse\'}_org")\n',
               'def f(st):\n    getattr(st, "".join(["confirm_", "prospects_hold"]))\n',
               'def f(st):\n    st.confirm_accounts_hold(1, 0)\n',
               'def f(st):\n    st.record_decision(1, 2, "confirmed", 0, None)\n',
               'def f(st):\n    getattr(st, "revoke_" + "decision")(1, 0, None, "x")\n',
               'def f(st):\n    st.except_issue(1, 0, "lead", None, "x", None)\n',
               'def f(st):\n    st._human(1, 2, None, lambda I, s, d: None)\n',
               'def f(st):\n    getattr(st, "record_account_" + "day")(1, 2)\n',
               'import builtins\nbuiltins.getattr\n',
               'def f(st):\n    __builtins__["getattr"](st, "x")\n',
               'def f():\n    __import__("naver_engine.store")\n',
               # 검토 guard-privileged-write-getattr-indirection — getattr 을 값으로 · 생성식 join · % · format
               'def f(st, now):\n    g = list(map(getattr, [st], ["_".join(w for w in ("record", "decision"))]))[0]\n',
               'def f(st, k):\n    _g = getattr\n    _g(st, "record_" + k)\n',
               'import functools\ndef f(st):\n    functools.partial(getattr, st)\n',
               'def f(st):\n    getattr(st, "%s_%s" % ("record", "access"))\n',
               'def f(st):\n    getattr(st, "{}_{}".format("mark", "alert_read"))\n')
        for src in bad:
            tree = ast.parse(src)
            self.assertTrue(_privileged_uses(tree) or _escapes(tree), src)

    def test_store_private_names_stay_inside_store(self):
        """저장소의 비공개 이름(``_tx`` · ``_conn`` · ``_write_issue`` · ``_refuse_and_hold`` …)은 store.py 밖에서 쓰지 않는다 —
        공개 함수의 검사를 건너뛰고 거래·쓰기 연결을 바로 잡는 길이 된다(검토 security-1). 자기 객체(``self``)의 같은 이름은 무관."""
        tree = ast.parse((ENGINE / "store.py").read_text(encoding="utf-8"))
        priv = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef) and n.name == "Store":
                priv |= {b.name for b in n.body if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self":
                priv.add(n.attr)
        priv = {x for x in priv if x.startswith("_") and not x.startswith("__")}
        self.assertTrue({"_tx", "_conn", "_human", "_write_issue", "_refuse_and_hold"} <= priv)

        def uses(t):
            return sorted({n.attr for n in ast.walk(t) if isinstance(n, ast.Attribute) and n.attr in priv
                           and not (isinstance(n.value, ast.Name) and n.value.id in ("self", "cls"))}
                          | {s for s in _folded(t) if s in priv})
        for p in self.SOURCES:
            if self.rel(p) == "store.py":
                continue
            self.assertEqual(uses(ast.parse(p.read_text(encoding="utf-8"))), [], self.rel(p))
        for src in ('def f(st):\n    st._human(1, 2, None, None)\n', 'def f(st):\n    st._conn.execute("x")\n',
                    'def f(store):\n    with store._tx() as c:\n        pass\n', 'def f(st):\n    getattr(st, "_tx")\n'):
            self.assertTrue(uses(ast.parse(src)), src)

    def test_nested_sync_file_does_not_count(self):
        tree = ast.parse('def f(st):\n    st.record_org({}, None)\n')
        self.assertTrue(_privileged_uses(tree))
        self.assertNotEqual(pathlib.PurePosixPath("sub/sync.py").as_posix(), "sync.py")   # 이름이 같아도 자리가 다르다

    def test_engine_imports_only_naver_auto_from_backend(self):
        for p in self.SOURCES:
            for _n, name in _imports(ast.parse(p.read_text(encoding="utf-8"))):
                if name == "app" or name.startswith("app."):
                    self.assertTrue(name == "app" or name == "app.naver_auto" or name.startswith("app.naver_auto."),
                                    f"{self.rel(p)}: {name}")
            self.assertEqual(_escapes(ast.parse(p.read_text(encoding="utf-8"))), [], self.rel(p))

    def test_engine_import_guard_catches_prefix_trick(self):
        for src in ("import app.naver_auto_x\n", "from app import main\n", "from app.naver_autox import y\n"):
            names = [name for _n, name in _imports(ast.parse(src)) if name == "app" or name.startswith("app.")]
            self.assertFalse(all(n == "app" or n == "app.naver_auto" or n.startswith("app.naver_auto.")
                                 for n in names), src)

    def test_shared_backend_modules_stay_pure(self):
        """엔진이 같은 프로세스에서 돌리는 backend/app/naver_auto 는 엔진 규칙을 따른다 — 쓸 수 있는 import 만(허용 목록)."""
        allowed = {"__future__", "typing", "dataclasses", "datetime", "types", "re", "unicodedata", "math",
                   "collections", "functools", "itertools", "enum"}
        self.assertTrue(self.SHARED)
        for p in self.SHARED:
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n, mod in _imports(tree):
                if isinstance(n, ast.ImportFrom) and n.level:
                    self.assertEqual(n.level, 1, f"{p.name}: {mod}")   # 같은 폴더만
                    continue
                self.assertIn(mod.split(".")[0], allowed, f"{p.name}: {mod}")
            self.assertEqual(_escapes(tree), [], p.name)
            for s in _folded(tree):
                for bad in ("socket", "urllib", "sqlite3", "subprocess", "os.system"):
                    self.assertNotEqual(s, bad, f"{p.name}: 글자로 {bad}")

    def test_backend_app_package_is_empty(self):
        """엔진은 app 패키지를 import 한다 — app/__init__.py 에 코드가 생기면 엔진 안에서 돈다."""
        self.assertEqual((BACKEND / "app" / "__init__.py").read_text(encoding="utf-8").strip(), "")
        body = ast.parse((BACKEND / "app" / "naver_auto" / "__init__.py").read_text(encoding="utf-8")).body
        self.assertTrue(all(isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) for n in body),
                        "naver_auto/__init__.py 에는 설명만 둔다")


if __name__ == "__main__":
    unittest.main()
