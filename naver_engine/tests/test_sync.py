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


def emp(idx, name, team_idx, manager=False, top=False, status="ACTIVE", deleted=False):
    return {"idx": idx, "name": name, "team_idx": team_idx, "is_manager": manager, "is_top_manager": top,
            "status": status, "is_deleted": deleted}


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
    """``ErpReader`` 대신 — 부른 횟수를 센다. 값이 예외면 던진다."""

    def __init__(self, org=None, stages=None):
        self.org, self.stages, self.calls = org, stages, 0

    def read_org_snapshot(self):
        self.calls += 1
        if isinstance(self.org, BaseException):
            raise self.org
        return copy.deepcopy(self.org)

    def read_stages(self):
        self.calls += 1
        if isinstance(self.stages, BaseException):
            raise self.stages
        return self.stages


def srow(pid, stage="진행중"):
    return E.StageRow(pid, stage, None, date(2026, 12, 31), False)


def snap(pids, as_of, conflicts=(), per=None):
    return E.StageSnapshot({p: srow(p) for p in pids}, as_of, {} if per is None else per, tuple(conflicts))


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

    def reopen(self):
        self.st.close()
        self.st = S.open_writer(self.path, clock=self.clock)
        return self.st

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
        raw.execute("DROP TABLE naver_auto_org")
        raw.execute("DROP TABLE naver_auto_sync_log")
        raw.execute("UPDATE naver_auto_meta SET value = '1' WHERE key = 'schema_version'")
        raw.commit()
        raw.close()
        self.st = S.open_writer(self.path, clock=self.clock)
        self.assertEqual(self.st.meta("schema_version"), "2")
        self.assertEqual(len(self.st.accounts()), 1)
        self.assertIsNone(self.st.org_current())
        self.assertEqual(self.st.sync_log(), [])
        self.assertIsNone(self.st.stage_as_of())

    def test_version_is_two(self):
        self.assertEqual(S.SCHEMA_VERSION, 2)


# ── 목록 급감 브레이크 — 가망 ──────────────────────────────────────────
class ProspectBrakeTest(Base):
    def seed(self, n=50):
        self.st.record_prospects(snap(range(1, n + 1), T0))

    def test_boundary_exactly_twenty_percent_is_accepted(self):
        self.seed(50)
        c = self.st.record_prospects(snap(range(11, 51), T0 + timedelta(hours=6)))   # 10/50 = 딱 20%
        self.assertEqual(c.now_absent, 10)

    def test_more_than_twenty_percent_and_ten_rows_brakes_and_writes_nothing(self):
        self.seed(50)
        before = self.st.prospects()
        with self.assertRaises(S.SyncBraked) as cm:
            self.st.record_prospects(snap(range(12, 51), T0 + timedelta(hours=6)))   # 11/50 = 22%
        b = cm.exception
        self.assertIsInstance(b, S.StoreRefused)
        self.assertEqual((b.kind, b.present_before, b.would_absent), ("stages", 50, 11))
        self.assertEqual(self.st.prospects(), before)                               # 한 줄도 안 바뀜
        self.assertEqual(self.st.stage_as_of(), T0)                                 # 받은 시각도 그대로
        log = self.st.last_sync(S.SYNC_STAGES)
        self.assertEqual((log["outcome"], log["absent_count"], log["row_count"], log["codes"]),
                         ("braked", 11, 39, ["BRAKE"]))
        self.assertNotIn("12", str(b).replace("11", ""))   # 문구에는 개수만(번호 없음)

    def test_small_drop_under_ten_rows_is_accepted_even_over_ratio(self):
        self.seed(40)
        c = self.st.record_prospects(snap(range(10, 41), T0 + timedelta(hours=6)))   # 9/40 = 22.5% 이지만 9줄
        self.assertEqual(c.now_absent, 9)

    def test_exactly_ten_rows_over_ratio_brakes(self):
        self.seed(40)
        with self.assertRaises(S.SyncBraked) as cm:
            self.st.record_prospects(snap(range(11, 41), T0 + timedelta(hours=6)))   # 10/40 = 25% · 딱 10줄
        self.assertEqual(cm.exception.would_absent, 10)

    def test_ratio_is_against_rows_present_now_not_all_rows(self):
        self.seed(60)
        self.st.record_prospects(snap(range(21, 61), T0 + timedelta(hours=6)), allow_drop_by=0)   # 20 빠짐 → 있음 40
        with self.assertRaises(S.SyncBraked) as cm:   # 10/40 = 25% (전체 60 으로 나누면 16.7% 라 받을 뻔)
            self.st.record_prospects(snap(range(31, 61), T0 + timedelta(hours=12)))
        self.assertEqual((cm.exception.present_before, cm.exception.would_absent), (40, 10))

    def test_brake_persists_until_confirmed_then_records_who(self):
        self.seed(50)
        for h in (6, 12):
            with self.assertRaises(S.SyncBraked):
                self.st.record_prospects(snap(range(20, 51), T0 + timedelta(hours=h)))
        c = self.st.record_prospects(snap(range(20, 51), T0 + timedelta(hours=18)), allow_drop_by=0)
        self.assertEqual(c.now_absent, 19)
        log = self.st.last_sync(S.SYNC_STAGES, S.SYNC_ACCEPTED)
        self.assertEqual((log["confirmed_by"], log["codes"], log["absent_count"]), (0, ["CONFIRMED"], 19))
        self.assertEqual([r["outcome"] for r in self.st.sync_log(S.SYNC_STAGES)],
                         ["accepted", "braked", "braked", "accepted"])

    def test_confirmer_must_be_person_number(self):
        self.seed(50)
        for bad in (-1, True, "0", 1.0):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)):
                self.st.record_prospects(snap(range(20, 51), T0 + timedelta(hours=6)), allow_drop_by=bad)
        self.assertEqual(sum(p["present"] for p in self.st.prospects()), 50)

    def test_conflicts_are_not_leaving(self):
        self.seed(50)
        c = self.st.record_prospects(snap(range(20, 51), T0 + timedelta(hours=6), conflicts=range(1, 20)))
        self.assertEqual(c.now_absent, 0)

    def test_only_newly_leaving_rows_count(self):
        self.seed(60)
        self.st.record_prospects(snap(range(16, 61), T0 + timedelta(hours=6)), allow_drop_by=0)   # 15 빠짐(확인)
        c = self.st.record_prospects(snap(range(16, 61), T0 + timedelta(hours=12)))              # 더 빠지는 것 없음
        self.assertEqual(c.now_absent, 0)
        c = self.st.record_prospects(snap(range(25, 61), T0 + timedelta(hours=18)))   # 9/45 · 9줄 — 받음
        self.assertEqual(c.now_absent, 9)

    def test_spelling_counts_kept_and_checked(self):
        self.st.record_prospects(snap([1], T0, per={"진행중": 1, "진행 중": 0}))
        self.assertEqual(self.st.last_sync(S.SYNC_STAGES)["detail"], {"진행 중": 0, "진행중": 1})
        for per in ({"없는단계": 1}, {"진행중": -1}, {"진행중": True}, ["진행중"]):
            with self.assertRaises(S.StoreRefused, msg=repr(per)):
                self.st.record_prospects(snap([1], T0 + timedelta(hours=1), per=per))

    def test_ratio_matches_plausible_tolerance(self):
        self.assertEqual(S.BRAKE_DROP_RATIO, E.EXPECTED_TOLERANCE)
        self.assertEqual(S.BRAKE_MIN_ROWS, 10)


# ── 목록 급감 브레이크 — 네이버 연결 계정 ──────────────────────────────────
class AccountBrakeTest(Base):
    def test_row_drop_brakes_and_keeps_absent_days(self):
        self.st.record_accounts(kids(range(1000, 1050)), T0)
        with self.assertRaises(S.SyncBraked) as cm:
            self.st.record_accounts(kids(range(1011, 1050)), T0 + timedelta(days=1))
        self.assertEqual((cm.exception.present_before, cm.exception.would_absent), (50, 11))
        self.assertTrue(all(a["present"] == 1 and a["absent_days"] == 0 for a in self.st.accounts()))
        self.assertIsNotNone(self.st.last_sync(S.SYNC_ACCOUNTS, S.SYNC_BRAKED))

    def test_only_newly_leaving_accounts_count(self):
        self.st.record_accounts(kids(range(1000, 1060)), T0)
        self.st.record_accounts(kids(range(1015, 1060)), T0 + timedelta(days=1), allow_drop_by=0)   # 15 빠짐(확인)
        c = self.st.record_accounts(kids(range(1015, 1060)), T0 + timedelta(days=2))   # 더 빠지는 것 없음 — 받음
        self.assertEqual(c.now_absent, 0)
        self.assertEqual({a["absent_days"] for a in self.st.accounts() if not a["present"]}, {2})

    def test_manager_lost_with_leaving_account_brakes(self):
        self.st.record_accounts(kids(range(1000, 1050), per={1: 40, 2: 10}), T0)
        with self.assertRaises(S.SyncBraked) as cm:
            self.st.record_accounts(kids(range(1000, 1049), per={1: 49}), T0 + timedelta(days=1))   # 한 줄만 빠져도
        self.assertEqual((cm.exception.managers_before, cm.exception.managers_now), (2, 1))
        self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS)["manager_count"], 1)

    def test_manager_lost_without_leaving_account_is_accepted(self):
        self.st.record_accounts(kids(range(1000, 1050), per={1: 50, 2: 0}), T0)
        c = self.st.record_accounts(kids(range(1000, 1050), per={1: 50}), T0 + timedelta(days=1))
        self.assertEqual(c.now_absent, 0)
        self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS, S.SYNC_ACCEPTED)["manager_count"], 1)

    def test_manager_count_compared_to_last_accepted_not_braked(self):
        self.st.record_accounts(kids(range(1000, 1050), per={1: 40, 2: 10}), T0)
        with self.assertRaises(S.SyncBraked):
            self.st.record_accounts(kids(range(1000, 1049), per={1: 49}), T0 + timedelta(days=1))
        with self.assertRaises(S.SyncBraked):   # 멈춘 기록(관리계정 1)을 기준으로 삼지 않는다
            self.st.record_accounts(kids(range(1000, 1049), per={1: 49}), T0 + timedelta(days=2))
        c = self.st.record_accounts(kids(range(1000, 1049), per={1: 49}), T0 + timedelta(days=3), allow_drop_by=0)
        self.assertEqual(c.now_absent, 1)
        self.assertEqual(self.st.last_sync(S.SYNC_ACCOUNTS)["confirmed_by"], 0)


# ── 동기화 기록 ─────────────────────────────────────────────────────
class SyncLogTest(Base):
    def test_outside_callers_cannot_write_accepted_or_braked(self):
        for outcome in ("accepted", "braked", "skipped", ""):
            with self.assertRaises(S.StoreRefused, msg=outcome):
                self.st.record_sync_event(S.SYNC_ORG, outcome, ("X",), T0)
        with self.assertRaises(S.StoreRefused):
            self.st.record_sync_event("naver", S.SYNC_FAILED, ("X",), T0)
        self.assertEqual(self.st.sync_log(), [])

    def test_codes_are_code_shaped_deduped_and_capped(self):
        self.st.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, ("ACTIVE_DROP", "status-403", "ACTIVE_DROP"), T0)
        self.assertEqual(self.st.last_sync(S.SYNC_ORG)["codes"], ["ACTIVE_DROP", "status-403"])
        for bad in (("직원 12 퇴사",), ("a b",), ("X" * 41,), "ACTIVE_DROP", (1,), tuple(f"C{i}" for i in range(21))):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)[:40]):
                self.st.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, bad, T0)

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
            with self.assertRaises(S.StoreRefused):
                r.record_sync_event(S.SYNC_STAGES, S.SYNC_FAILED, ("network",), T0)
            with self.assertRaises(S.StoreRefused):
                r.record_org(org_payload(T0), T0)
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
        body = self.st.org_current()["body"]
        self.assertEqual(set(body), {"generated_at", "teams", "employees", "owners"})
        self.assertTrue(all(set(e) <= set(F.ORG_EMPLOYEE) for e in body["employees"]))
        self.assertTrue(all(set(t) <= set(F.ORG_TEAM) for t in body["teams"]))
        self.assertTrue(all(set(o) <= set(F.ORG_OWNER) for o in body["owners"]))
        raw = self.file_bytes()
        for mark in (PHONE_MARK, LOGIN_MARK):
            self.assertNotIn(mark.encode(), raw)

    def test_values_must_be_flat(self):
        for bad in ({"a": 1}, [1], 1.5, float("nan"), "x" * 201, "a\x00b", 2 ** 64):
            p = org_payload(T0)
            p["employees"][0]["name"] = bad
            with self.assertRaises(S.StoreRefused, msg=repr(bad)[:30]):
                self.st.record_org(p, T0)
        self.assertIsNone(self.st.org_current())

    def test_shape_refused(self):
        for mutate in (lambda b: b.pop("owners"), lambda b: b.__setitem__("teams", "x"),
                       lambda b: b.__setitem__("employees", [1]), lambda b: b.__setitem__("generated_at", "어제"),
                       lambda b: b.__setitem__("generated_at", "2026-09-29T10:00:00")):
            p = org_payload(T0)
            mutate(p)
            with self.assertRaises(S.StoreRefused):
                self.st.record_org(p, T0)
        with self.assertRaises(S.StoreRefused):
            self.st.record_org([], T0)

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
        self.st.record_org(p, T0, warnings=("UNKNOWN_STATUS",), confirmed_by=0)
        self.reopen()
        cur = self.st.org_current()
        self.assertEqual((cur["generated_at"], cur["received_at"], cur["confirmed_by"]), (T0, T0, 0))
        a, b = O.parse_org_snapshot(p), O.parse_org_snapshot(cur["body"])
        self.assertEqual((dict(a.people), a.owners, dict(a.teams)), (dict(b.people), b.owners, dict(b.teams)))
        log = self.st.last_sync(S.SYNC_ORG)
        self.assertEqual((log["codes"], log["row_count"], log["detail"]),
                         (["UNKNOWN_STATUS", "CONFIRMED"], 40, {"employees": 32, "teams": 4}))

    def test_generated_time_stored_in_kst_and_compared_as_time(self):
        utc = (T0 + timedelta(hours=1)).astimezone(timezone.utc)
        self.st.record_org(org_payload(utc), T0 + timedelta(hours=1))
        self.assertEqual(self.st.org_current()["generated_at"].utcoffset(), timedelta(hours=9))
        with self.assertRaises(S.StoreRefused):   # 글자는 달라도 같은 시각 — 새것이 아니다
            self.st.record_org(org_payload(T0 + timedelta(hours=1)), T0 + timedelta(hours=2))


# ── 조직 동기화 ─────────────────────────────────────────────────────
class SyncOrgTest(Base):
    def test_first_time_accepted(self):
        r = Y.sync_org(FakeErp(org_payload(T0)), self.st, T0)
        self.assertEqual((r.outcome, r.rows, r.needs_confirmation), ("accepted", 40, False))
        self.assertEqual(self.st.org_current()["generated_at"], T0)

    def test_drop_refused_and_survives_restart(self):
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0)
        drop = org_payload(T0 + timedelta(hours=1), resigned=10)   # 재직 32 → 22 (31%)
        r = Y.sync_org(FakeErp(drop), self.st, T0 + timedelta(hours=1))
        self.assertEqual((r.outcome, r.needs_confirmation), ("refused", True))
        self.assertIn("ACTIVE_DROP", r.codes)
        self.assertEqual(self.st.org_current()["generated_at"], T0)             # 수락본 그대로
        self.reopen()                                                           # 엔진을 다시 켜도(M12)
        drop2 = org_payload(T0 + timedelta(hours=2), resigned=10)
        r2 = Y.sync_org(FakeErp(drop2), self.st, T0 + timedelta(hours=2))
        self.assertEqual(r2.outcome, "refused")                                 # 이전 조직을 잊지 않는다
        self.assertEqual(self.st.org_current()["generated_at"], T0)
        r3 = Y.sync_org(FakeErp(drop2), self.st, T0 + timedelta(hours=2, minutes=5), confirmed_by=0)
        self.assertEqual(r3.outcome, "accepted")
        log = self.st.last_sync(S.SYNC_ORG)
        self.assertEqual((log["confirmed_by"], log["codes"][-1]), (0, "CONFIRMED"))
        self.assertEqual([d["outcome"] for d in self.st.sync_log(S.SYNC_ORG)],
                         ["accepted", "refused", "refused", "accepted"])

    def test_confirmation_does_not_skip_basic_checks(self):
        cases = {
            "EMPTY": lambda b: b.__setitem__("employees", []),
            "TOP_MANAGER_NONE": lambda b: b["employees"].__setitem__(0, emp(0, "대표", 0, manager=True, top=False)),
            "FORMAT": lambda b: b.pop("owners"),
            "CYCLE": lambda b: b["teams"].__setitem__(2, team(10, "관리 본부", 1, 11)),
        }
        for code, mutate in cases.items():
            r = Y.sync_org(FakeErp(org_payload(T0, extra=mutate)), self.st, T0, confirmed_by=0)
            self.assertEqual(r.outcome, "refused", code)
            self.assertIn(code, r.codes)
            self.assertFalse(r.needs_confirmation, code)
        self.assertIsNone(self.st.org_current())

    def test_erp_failure_recorded_without_touching_stored(self):
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0)
        for err, code in ((E.ErpError("status", E.PATH_ORG_SNAPSHOT, 403), "status-403"),
                          (E.ErpError("network", E.PATH_ORG_SNAPSHOT, None, "URLError"), "network"),
                          (E.ErpIncomplete("bad-shape", E.PATH_ORG_SNAPSHOT, 200), "bad-shape-200")):
            r = Y.sync_org(FakeErp(err), self.st, T0 + timedelta(hours=1))
            self.assertEqual((r.outcome, r.codes), ("failed", (code,)))
        self.assertEqual(self.st.org_current()["generated_at"], T0)
        self.assertEqual(self.st.last_sync(S.SYNC_ORG)["codes"], ["bad-shape-200"])

    def test_unreadable_stored_copy_is_not_treated_as_first_time(self):
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0)
        self.st.close()
        self.st = None
        raw = sqlite3.connect(self.path)
        raw.execute("UPDATE naver_auto_org SET body = ?", (json.dumps({"generated_at": T0.isoformat(), "teams": []}),))
        raw.commit()
        raw.close()
        self.st = S.open_writer(self.path, clock=self.clock)
        drop = org_payload(T0 + timedelta(hours=1), resigned=10)
        r = Y.sync_org(FakeErp(drop), self.st, T0 + timedelta(hours=1))
        self.assertEqual((r.outcome, r.codes, r.needs_confirmation), ("refused", ("STORED_UNREADABLE",), True))
        r = Y.sync_org(FakeErp(drop), self.st, T0 + timedelta(hours=1), confirmed_by=0)
        self.assertEqual(r.outcome, "accepted")

    def test_wrapped_payload_accepted_and_unwrapped_in_store(self):
        r = Y.sync_org(FakeErp({"status": 200, "result": org_payload(T0)}), self.st, T0)
        self.assertEqual(r.outcome, "accepted")
        self.assertIn("employees", self.st.org_current()["body"])

    def test_warning_codes_only_in_log(self):
        def odd(b):
            b["employees"][2]["status"] = None
        r = Y.sync_org(FakeErp(org_payload(T0, extra=odd)), self.st, T0)
        self.assertEqual((r.outcome, r.codes), ("accepted", ("UNKNOWN_STATUS",)))
        log = self.st.last_sync(S.SYNC_ORG)
        self.assertEqual(log["codes"], ["UNKNOWN_STATUS"])
        self.assertNotIn("100", json.dumps(log["codes"]))

    def test_store_refusal_becomes_result(self):
        self.clock.t = T0
        future = org_payload(T0 + timedelta(minutes=9))
        Y.sync_org(FakeErp(future), self.st, T0)
        same = org_payload(T0 + timedelta(minutes=9))
        r = Y.sync_org(FakeErp(same), self.st, T0 + timedelta(minutes=1), confirmed_by=0)   # 확인해도 새것만
        self.assertEqual((r.outcome, r.codes), ("refused", ("STORE_REFUSED",)))

    def test_naive_now_is_caller_error(self):
        with self.assertRaises(ValueError):
            Y.sync_org(FakeErp(org_payload(T0)), self.st, T0.replace(tzinfo=None))

    def test_confirmable_codes_are_exactly_the_comparison_codes(self):
        """버림 코드마다 「확인으로 풀 수 있나」가 정해져 있어야 한다 — 새 코드가 생기면 이 시험이 결정을 요구한다."""
        tree = ast.parse((BACKEND / "app" / "naver_auto" / "org_snapshot.py").read_text(encoding="utf-8"))
        check = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "check_snapshot")
        reasons = {n.args[0].value for n in ast.walk(check)
                   if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "Finding"
                   and isinstance(n.args[0], ast.Constant)
                   and any(isinstance(p, ast.Attribute) and p.attr == "append" and getattr(p.value, "id", "") == "reasons"
                           for p in ast.walk(check) if isinstance(p, ast.Attribute))}
        prev_only = {"ACTIVE_DROP", "OWNER_DROP", "OWNER_BLANK_SPIKE", "TOP_MANAGER_ADDED", "SYSTEM_TEAM_LOST",
                     "MANAGER_SPIKE", "PARENT_LOST", "STALE"}
        basic = {"EMPTY", "CYCLE", "TOP_MANAGER_NONE", "TOP_MANAGER_LIMIT", "FUTURE"}
        warn = {"ORPHAN_TEAM", "UNKNOWN_STATUS", "UNKNOWN_TEAM_REF", "UNKNOWN_OWNER_SOURCE", "TOP_MANAGER_COUNT"}
        self.assertEqual(reasons, prev_only | basic | warn)
        self.assertEqual(Y.CONFIRMABLE_ORG_CODES, (prev_only - {"STALE"}) | {"STORED_UNREADABLE"})

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
        }
        for code, payload in scenarios.items():
            with_prev = O.accept_snapshot(payload, prev, later)
            self.assertIn(code, {f.code for f in with_prev.reasons}, code)
            self.assertTrue(O.accept_snapshot(payload, None, later).ok, code)


# ── 신선도 ─────────────────────────────────────────────────────────
class FreshnessTest(Base):
    def test_bands(self):
        self.assertEqual(Y.org_freshness(self.st, T0), O.FRESH_NONE)
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0)
        us = timedelta(microseconds=1)
        for dt, want in ((timedelta(0), "fresh"), (timedelta(hours=3), "fresh"), (timedelta(hours=3) + us, "yellow"),
                         (timedelta(hours=26), "yellow"), (timedelta(hours=26) + us, "stale")):
            self.assertEqual(Y.org_freshness(self.st, T0 + dt), want, dt)
        self.assertEqual(O.org_freshness(T0 + timedelta(minutes=10), T0), "fresh")
        self.assertEqual(O.org_freshness(T0 + timedelta(minutes=10) + us, T0), "stale")   # 믿을 수 없는 미래

    def test_age_counts_from_erp_generated_time_not_receipt(self):
        Y.sync_org(FakeErp(org_payload(T0)), self.st, T0 + timedelta(hours=2))   # ① 가 10:00 에 만든 것을 12:00 에 받음
        self.assertEqual(Y.org_freshness(self.st, T0 + timedelta(hours=3, microseconds=1)), "yellow")

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


# ── 계약 단계 동기화 ────────────────────────────────────────────────
class SyncStagesTest(Base):
    def test_first_run_must_be_plausible_unless_confirmed(self):
        r = Y.sync_stages(FakeErp(stages=snap(range(1, 301), T0)), self.st, T0)
        self.assertEqual((r.outcome, r.codes, r.needs_confirmation), ("refused", ("IMPLAUSIBLE_FIRST",), True))
        self.assertEqual(self.st.prospects(), [])
        self.assertIsNone(self.st.stage_as_of())
        r = Y.sync_stages(FakeErp(stages=snap(range(1, 301), T0)), self.st, T0, confirmed_by=0)
        self.assertEqual((r.outcome, r.rows), ("accepted", 300))

    def test_plausible_first_then_later_runs_not_compared_to_940(self):
        self.assertEqual(Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0)), self.st, T0).outcome, "accepted")
        r = Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0 + timedelta(hours=6))), self.st, T0 + timedelta(hours=6))
        self.assertEqual(r.outcome, "accepted")

    def test_confirmed_small_first_run_then_later_runs_accepted(self):
        Y.sync_stages(FakeErp(stages=snap(range(1, 301), T0)), self.st, T0, confirmed_by=0)
        r = Y.sync_stages(FakeErp(stages=snap(range(1, 301), T0 + timedelta(hours=6))), self.st, T0 + timedelta(hours=6))
        self.assertEqual(r.outcome, "accepted")   # 940 대조는 첫 회차만

    def test_plausible_edges(self):
        for n, ok in ((752, True), (751, False), (1128, True), (1129, False)):
            self.assertEqual(snap(range(n), T0).plausible(), ok, n)

    def test_brake_becomes_result(self):
        Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0)), self.st, T0)
        r = Y.sync_stages(FakeErp(stages=snap(range(300, 941), T0 + timedelta(hours=6))), self.st,
                          T0 + timedelta(hours=6))
        self.assertEqual((r.outcome, r.codes, r.absent, r.needs_confirmation), ("braked", ("BRAKE",), 299, True))
        self.assertEqual(sum(p["present"] for p in self.st.prospects()), 940)

    def test_erp_incomplete_changes_nothing(self):
        Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0)), self.st, T0)
        r = Y.sync_stages(FakeErp(stages=E.ErpIncomplete("status", E.PATH_CONTRACTS, 500, "단계 동기화 중단")),
                          self.st, T0 + timedelta(hours=6))
        self.assertEqual((r.outcome, r.codes), ("failed", ("status-500",)))
        self.assertEqual(self.st.stage_as_of(), T0)

    def test_old_snapshot_is_store_refusal(self):
        Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0)), self.st, T0)
        r = Y.sync_stages(FakeErp(stages=snap(range(1, 941), T0)), self.st, T0 + timedelta(hours=6))
        self.assertEqual((r.outcome, r.codes), ("refused", ("STORE_REFUSED",)))

    def test_result_repr_has_counts_only(self):
        r = Y.SyncResult("stages", "braked", ("BRAKE",), rows=PID_MARK, absent=3)
        self.assertNotIn("name", repr(r))
        self.assertIn("rows=", repr(r))


# ── 부르는 때 ───────────────────────────────────────────────────────
class DueTest(Base):
    def test_org_every_hour_after_any_attempt(self):
        self.assertTrue(Y.org_due(self.st, T0))
        Y.sync_org(FakeErp(E.ErpError("network", E.PATH_ORG_SNAPSHOT)), self.st, T0)
        self.assertFalse(Y.org_due(self.st, T0 + timedelta(minutes=59)))
        self.assertTrue(Y.org_due(self.st, T0 + timedelta(hours=1)))

    def test_stages_quiet_windows(self):
        day = datetime(2026, 9, 30, tzinfo=KST)
        for hh, mm, due in ((3, 49, True), (3, 50, False), (4, 19, False), (4, 20, True), (5, 49, True),
                            (5, 50, False), (6, 29, False), (6, 30, True)):
            self.assertEqual(Y.stages_due(self.st, day.replace(hour=hh, minute=mm)), due, (hh, mm))
        utc = datetime(2026, 9, 29, 21, 0, tzinfo=timezone.utc)   # = 9/30 06:00 KST
        self.assertFalse(Y.stages_due(self.st, utc))

    def test_stages_every_six_hours_retry_after_one(self):
        t = datetime(2026, 9, 29, 8, 0, tzinfo=KST)
        Y.sync_stages(FakeErp(stages=snap(range(1, 941), t)), self.st, t)
        self.assertFalse(Y.stages_due(self.st, t + timedelta(hours=5, minutes=59)))
        self.assertTrue(Y.stages_due(self.st, t + timedelta(hours=6)))
        f = t + timedelta(hours=6)
        Y.sync_stages(FakeErp(stages=E.ErpIncomplete("network", E.PATH_CONTRACTS)), self.st, f)
        self.assertFalse(Y.stages_due(self.st, f + timedelta(minutes=59)))
        self.assertTrue(Y.stages_due(self.st, f + timedelta(hours=1)))

    def test_windows_are_design_values(self):
        self.assertEqual(Y.STAGES_QUIET, ((time(3, 50), time(4, 20)), (time(5, 50), time(6, 30))))
        self.assertEqual((Y.ORG_EVERY, Y.STAGES_EVERY, Y.STAGES_RETRY),
                         (timedelta(hours=1), timedelta(hours=6), timedelta(hours=1)))


# ── 구문 시험 — 조직 수락본을 적는 길 · 엔진이 읽는 backend 모듈 ─────────────────
class SyncGuardTest(unittest.TestCase):
    SOURCES = sorted(p for p in ENGINE.rglob("*.py") if "tests" not in p.parts)

    def test_record_org_called_only_from_sync(self):
        found = set()
        for p in self.SOURCES:
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(n, ast.Attribute) and n.attr == "record_org":
                    found.add(p.name)
                if isinstance(n, ast.Constant) and n.value == "record_org":
                    found.add(p.name + ":str")
        self.assertEqual(found, {"sync.py"})

    def test_engine_imports_only_naver_auto_from_backend(self):
        for p in self.SOURCES:
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                names = []
                if isinstance(n, ast.Import):
                    names = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    names = [n.module]
                for name in names:
                    if name == "app" or name.startswith("app."):
                        self.assertTrue(name.startswith("app.naver_auto"), f"{p.name}: {name}")

    def test_shared_backend_modules_stay_pure(self):
        banned = ("urllib", "http", "socket", "ssl", "requests", "httpx", "aiohttp", "subprocess", "sqlite3",
                  "sqlalchemy", "fcntl", "os", "sys", "importlib", "pathlib", "shutil", "pickle")
        folder = BACKEND / "app" / "naver_auto"
        for p in sorted(folder.glob("*.py")):
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                mods = []
                if isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                    mods = [n.module]
                for m in mods:
                    self.assertFalse(m.split(".")[0] in banned or m.startswith("app."), f"{p.name}: {m}")


if __name__ == "__main__":
    unittest.main()
