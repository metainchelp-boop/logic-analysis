"""엔진 저장소 시험 (설계 v1.8 S6 · 반박 H8 · H9 · H10 · 대표 결정 D10 · S6 적대 검토 반영).

- 지우지 않는다 — 연결이 지우기·표 버리기·표 고치기·방아쇠·보기·다른 DB 붙이기를 거절하고, 코드의 SQL 글자에도
  지우기·바꿔 넣기(``REPLACE INTO`` 포함)·연쇄·표 고치기가 없다.
- 전부 받은 목록만 받고, 빠진 것은 「목록에 없음」 표시만 바꾼다(줄은 남는다). 빈 목록·줄 수 안 맞는 목록은 거절.
- 남길 칸만 — 들어온 개인정보 칸(표지 값)은 저장 파일 어디에도 없다.
- 모름 ≠ 0 · 쓰는 곳 하나(파일 자체 잠금 · 하드링크 거절) · 권한 600 · 엔진 코드 폴더 밖 · 한국 시각 · 미래 시각 거절.
- 다시 적기(upsert)는 칸마다 시험한다 — 칸 하나를 빼거나 바꿔치기해도 시험이 잡는다.
"""
from __future__ import annotations

import ast
import os
import pathlib
import sqlite3
import stat
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from naver_engine import erp_read as E
from naver_engine import naver_read as N
from naver_engine import store as S

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 29, 6, 40, tzinfo=KST)
DAY = date(2026, 9, 29)
ENGINE = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ENGINE.parent / "backend"

SECRET_OWNER = "owner_marker_q7x"       # 계정책임자 아이디 표지 — 파일 어디에도 있으면 안 된다
SECRET_TRACK = "https://track.example/zz9"
NAME_MARK = "표지상회"
SQL_VERBS = ("SELECT", "INSERT", "UPDATE", "CREATE", "PRAGMA", "BEGIN", "COMMIT", "ROLLBACK", "DELETE", "DROP",
             "REPLACE", "ALTER", "ATTACH", "DETACH", "VACUUM", "WITH", "UPSERT", "REINDEX", "ANALYZE", "SAVEPOINT",
             "RELEASE", "END")
FORBIDDEN_SQL = ("DELETE", "DROP", "REPLACE", "TRUNCATE", "REFERENCES", "CASCADE", "ATTACH", "DETACH", "VACUUM",
                 "ALTER", "TRIGGER", "VIEW", "WRITABLE_SCHEMA", "LOAD_EXTENSION", "INSERT OR")


def at(**kw) -> datetime:
    return NOW + timedelta(**kw)


class Clock:
    """저장소에 넣는 시계 — 시험이 「지금」을 정한다."""

    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


def snap(rows, as_of=NOW, conflicts=()):
    return E.StageSnapshot({r.possibility_id: r for r in rows}, as_of, {}, tuple(conflicts))


def row(pid, stage="진행중", name=None, end=None, unreadable=False):
    return E.StageRow(pid, stage, name, end, unreadable)


def kids(*accounts, per=None):
    acc = {}
    for cid, no, name in accounts:
        acc[cid] = {"customerId": cid, "adAccountNo": no, "adAccountName": name, "accountRole": "MANAGE",
                    "ownerNaverId": SECRET_OWNER}
    return N.ChildAccounts(acc, {1: len(acc)} if per is None else per, ({"managerAccountNo": 1},))


def camp(cid, ccid, **extra):
    c = {"nccCampaignId": ccid, "customerId": cid, "name": "캠페인", "campaignTp": "SHOPPING", "status": "ELIGIBLE",
         "statusReason": "ELIGIBLE", "dailyBudget": 50000, "trackingUrl": SECRET_TRACK}
    c.update(extra)
    return c


def stat_row(**kw):
    """지표마다 다른 값 — 칸을 바꿔치기하면 보인다."""
    base = {"impCnt": 101.0, "clkCnt": 7.0, "salesAmt": 1301.0, "ccnt": 3.0, "convAmt": 30011.0,
            "purchaseCcnt": 2.0, "purchaseConvAmt": 29003.0}
    base.update(kw)
    return base


def sql_strings(tree):
    """SQL 로 보이는 글자 — 동사로 시작하거나 SQL 낱말이 든 상수, f-글자의 상수 조각."""
    for n in ast.walk(tree):
        texts = []
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            texts = [n.value]
        elif isinstance(n, ast.JoinedStr):
            texts = ["".join(str(v.value) for v in n.values if isinstance(v, ast.Constant))]
        for t in texts:
            up = " ".join(t.upper().split())
            first = up.split(" ", 1)[0].strip("(") if up else ""
            if first in SQL_VERBS or any(k in up for k in ("INSERT ", "UPDATE ", "CREATE ", "SELECT ")):
                yield up


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "engine.db")
        self.clock = Clock(at(days=7))
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
        out = b""
        for suffix in ("", "-wal", "-shm"):
            p = self.path + suffix
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    out += fh.read()
        return out

    def count(self, table):
        return self.st._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class OpenTest(Base):
    def test_new_file_is_owner_only_and_wal(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.st.record_accounts(kids((1234567, 11, "a")), NOW)
        for suffix in ("-wal", "-shm"):
            self.assertTrue(os.path.exists(self.path + suffix), suffix)
            self.assertEqual(stat.S_IMODE(os.stat(self.path + suffix).st_mode), 0o600, suffix)
        c = self.st._conn
        self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(c.execute("PRAGMA synchronous").fetchone()[0], 2)          # FULL
        self.assertEqual(self.st.meta("schema_version"), "1")
        self.assertEqual([n for n in os.listdir(self.dir.name) if n.endswith(".lock")], [])   # 잠금은 파일 자체에

    def test_connection_settings(self):
        c = self.st._conn
        c.set_authorizer(None)
        try:
            self.assertEqual(c.execute("PRAGMA trusted_schema").fetchone()[0], 0)
            self.assertTrue(c.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE))
        finally:
            c.set_authorizer(S._authorizer(S.PHASE_RUN))
        r = S.open_reader(self.path)
        try:
            r._conn.set_authorizer(None)
            self.assertEqual(r._conn.execute("PRAGMA trusted_schema").fetchone()[0], 0)
        finally:
            r.close()

    def test_existing_loose_files_tightened(self):
        p2 = os.path.join(self.dir.name, "loose.db")
        raw = sqlite3.connect(p2, isolation_level=None)
        try:
            raw.execute("PRAGMA journal_mode = WAL")
            raw.execute("CREATE TABLE other (a INTEGER)")
            raw.execute("INSERT INTO other VALUES (1)")
            for suffix in ("", "-wal", "-shm"):
                os.chmod(p2 + suffix, 0o644)
            st2 = S.open_writer(p2, clock=self.clock)
            try:
                for suffix in ("", "-wal", "-shm"):
                    self.assertEqual(stat.S_IMODE(os.stat(p2 + suffix).st_mode), 0o600, suffix)
            finally:
                st2.close()
        finally:
            raw.close()

    def test_single_writer_even_through_alias(self):
        with self.assertRaises(S.StoreBusy):
            S.open_writer(self.path, clock=self.clock)
        alias = os.path.join(self.dir.name, "alias.db")
        os.symlink(self.path, alias)
        with self.assertRaises(S.StoreBusy):
            S.open_writer(alias, clock=self.clock)
        self.st.close()
        again = S.open_writer(alias, clock=self.clock)
        again.close()
        self.st = S.open_writer(self.path, clock=self.clock)

    def test_hardlink_refused(self):
        self.st.close()
        self.st = None
        twin = os.path.join(self.dir.name, "twin.db")
        os.link(self.path, twin)
        for p in (self.path, twin):
            with self.assertRaises(S.StoreRefused, msg=p):
                S.open_writer(p, clock=self.clock)

    @unittest.skipUnless(hasattr(os, "geteuid") and os.geteuid() == 0, "소유자 바꾸기는 관리자만")
    def test_other_owner_refused(self):
        self.st.close()
        self.st = None
        os.chown(self.path, 12345, 12345)
        with self.assertRaises(S.StoreRefused):
            S.open_writer(self.path, clock=self.clock)

    def test_world_writable_folder_refused_unless_sticky(self):
        d = os.path.join(self.dir.name, "open")
        os.mkdir(d)
        os.chmod(d, 0o777)
        with self.assertRaises(S.StoreRefused):
            S.open_writer(os.path.join(d, "x.db"), clock=self.clock)
        self.assertFalse(os.path.exists(os.path.join(d, "x.db")))
        os.chmod(d, 0o1777)
        S.open_writer(os.path.join(d, "x.db"), clock=self.clock).close()

    def test_refused_paths(self):
        for bad in ("engine.db", ":memory:", "", None, str(ENGINE / "data.db"), str(ENGINE / "tests" / "x.db")):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)):
                S.open_writer(bad, clock=self.clock)
        link = os.path.join(self.dir.name, "into_code")
        os.symlink(str(ENGINE), link)
        with self.assertRaises(S.StoreRefused):
            S.open_writer(os.path.join(link, "x.db"), clock=self.clock)   # 바로가기로 코드 폴더 안에 두는 길도 막는다

    def test_open_errors_hide_the_path(self):
        secret_dir = os.path.join(self.dir.name, "hidden_dir_q9")
        for p in (os.path.join(secret_dir, "x.db"), self.dir.name):
            with self.assertRaises(S.StoreError) as cm:
                S.open_writer(p, clock=self.clock)
            self.assertNotIn("hidden_dir_q9", str(cm.exception))
            self.assertNotIn(self.dir.name, str(cm.exception))

    def test_clock_without_timezone_refused(self):
        p2 = os.path.join(self.dir.name, "naive.db")
        with self.assertRaises(S.StoreError):
            S.open_writer(p2, clock=lambda: datetime(2026, 9, 29, 6, 40))
        S.open_writer(p2, clock=self.clock).close()   # 잠금이 풀려 있다

    def test_schema_version_guard(self):
        for value, opens in (("99", False), ("x", False), ("0", True)):
            self.st._conn.execute("UPDATE naver_auto_meta SET value = ? WHERE key = 'schema_version'", (value,))
            self.st.close()
            self.st = None
            if opens:
                self.st = S.open_writer(self.path, clock=self.clock)
                self.assertEqual(self.st.meta("schema_version"), "1")   # 옛 판은 이관 뒤 판 번호를 올린다
            else:
                with self.assertRaises(S.StoreError, msg=value):
                    S.open_writer(self.path, clock=self.clock)
                r = S.open_reader(self.path)
                self.assertEqual(r.meta("schema_version"), value)       # 거절한 파일은 건드리지 않았다
                r.close()
                raw = sqlite3.connect(self.path)
                raw.execute("UPDATE naver_auto_meta SET value = '1' WHERE key = 'schema_version'")
                raw.commit()
                raw.close()
                self.st = S.open_writer(self.path, clock=self.clock)

    def test_reopen_keeps_everything(self):
        self.st.record_prospects(snap([row(11, name=NAME_MARK)]))
        self.st.record_accounts(kids((1234567, 11, "a")), NOW)
        d = self.st.record_decision(11, 1234567, "confirmed", 0, NOW)
        self.reopen()
        self.assertEqual([p["name"] for p in self.st.prospects()], [NAME_MARK])
        self.assertEqual([a["customer_id"] for a in self.st.accounts()], [1234567])
        self.assertEqual(self.st.current_decisions(), [(11, 1234567, "confirmed")])
        self.assertGreater(d, 0)
        with self.assertRaises(S.StoreRefused):   # 저장된 동기화 시각도 남아 옛 목록을 거절한다
            self.st.record_prospects(snap([row(11)], as_of=NOW))

    def test_repr_hides_path(self):
        self.assertNotIn(self.dir.name, repr(self.st))
        self.assertNotIn("engine.db", repr(self.st))
        self.assertEqual(repr(S.SyncCounts(1, 2, 3)), "SyncCounts(present=1, new=2, now_absent=3)")


class OrphanRunTest(Base):
    def test_run_left_running_is_closed_on_open(self):
        rid = self.st.begin_run(DAY, NOW)
        self.assertEqual(self.st.running_runs(), [rid])
        self.assertEqual(self.st.orphaned_runs, 0)
        self.reopen()                                               # 엔진이 도중에 죽은 뒤 다시 연다
        self.assertEqual(self.st.orphaned_runs, 1)
        self.assertEqual(self.st.running_runs(), [])
        r = self.st.run(rid)
        self.assertEqual((r["status"], r["error_kind"]), ("failed", S.ORPHANED))
        self.assertEqual(r["finished_at"], self.clock.t.isoformat(timespec="microseconds"))
        rid2 = self.st.begin_run(DAY, at(hours=1))                  # 그날 다시 돌릴 수 있다
        self.assertNotEqual(rid, rid2)

    def test_old_run_number_refused(self):
        rid = self.st.begin_run(DAY, NOW)
        self.reopen()
        with self.assertRaises(S.StoreRefused):
            self.st.finish_run(rid, "done", at(minutes=5))
        with self.assertRaises(S.StoreRefused):
            self.st.record_account_day(rid, 1234567, status="ok", rules_run=[], rules_not_run=[], checked_at=NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.record_campaign_days(rid, 1234567, DAY, [], {}, provisional=False, read_at=NOW)

    def test_other_store_run_refused(self):
        """이 저장소가 시작하지 않은 「돌고 있음」 줄(다른 연결이 넣은 것)에는 적지 않는다."""
        self.st.close()
        raw = sqlite3.connect(self.path)
        raw.execute("INSERT INTO naver_auto_check_run (run_date, started_at, status) VALUES (?, ?, 'running')",
                    ("2026-09-29", NOW.isoformat()))
        raw.commit()
        raw.close()
        self.st = S.open_writer(self.path, clock=self.clock)       # 열 때 닫힌다
        self.assertEqual(self.st.orphaned_runs, 1)
        self.assertEqual(self.st.running_runs(), [])
        raw = sqlite3.connect(self.path)                            # 열려 있는 동안 몰래 넣은 줄
        try:
            rid = raw.execute("INSERT INTO naver_auto_check_run (run_date, started_at, status) VALUES (?, ?, 'running')",
                              ("2026-09-28", at(days=-1).isoformat())).lastrowid
            raw.commit()
        finally:
            raw.close()
        self.assertEqual(self.st.running_runs(), [rid])
        with self.assertRaises(S.StoreRefused):
            self.st.record_account_day(rid, 1234567, status="ok", rules_run=[], rules_not_run=[], checked_at=NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.record_campaign_days(rid, 1234567, DAY, [], {}, provisional=False, read_at=NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.finish_run(rid, "done", NOW)
        self.assertEqual(self.st.run(rid)["status"], "running")


class NoDeleteTest(Base):
    def test_connection_refuses_destructive_sql(self):
        self.st.record_accounts(kids((1234567, 11, "a")), NOW)
        tables = sorted(r[0] for r in self.st._conn.execute("SELECT name FROM sqlite_master"))
        for sql in ("DELETE FROM naver_auto_account", "DROP TABLE naver_auto_account",
                    "DROP INDEX naver_auto_campaign_day_customer",
                    f"ATTACH DATABASE '{os.path.join(self.dir.name, 'o.db')}' AS o",
                    "ALTER TABLE naver_auto_account DROP COLUMN account_name",
                    "ALTER TABLE naver_auto_account RENAME TO gone",
                    "ALTER TABLE naver_auto_account RENAME COLUMN account_name TO x",
                    "ALTER TABLE naver_auto_account ADD COLUMN y TEXT",
                    "PRAGMA writable_schema = 1", "PRAGMA journal_mode = DELETE", "PRAGMA foreign_keys = 1",
                    "PRAGMA user_version = 7",
                    "CREATE TRIGGER t AFTER INSERT ON naver_auto_meta BEGIN SELECT 1; END",
                    "CREATE VIEW v AS SELECT * FROM naver_auto_account",
                    "CREATE TABLE extra (a INTEGER)", "CREATE TEMP TABLE tmp (a INTEGER)",
                    "CREATE INDEX extra_i ON naver_auto_account (account_name)",
                    "SELECT load_extension('x')"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.st._conn.execute(sql)
        c = self.st._conn
        self.assertEqual(sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master")), tables)
        self.assertEqual(len(self.st.accounts()), 1)
        self.assertEqual(self.st.accounts()[0]["account_name"], "a")
        self.assertEqual(c.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 0)
        self.assertNotIn(os.path.join(self.dir.name, "o.db"), [r[2] for r in c.execute("PRAGMA database_list")])
        self.assertFalse(os.path.exists(os.path.join(self.dir.name, "o.db")))

    def test_migrate_phase_adds_but_does_not_drop_or_rename(self):
        c = sqlite3.connect(":memory:", isolation_level=None)
        try:
            c.set_authorizer(S._authorizer(S.PHASE_MIGRATE))
            c.execute("CREATE TABLE t (a INTEGER, b TEXT)")
            c.execute("CREATE INDEX t_a ON t (a)")
            c.execute("ALTER TABLE t ADD COLUMN c TEXT")            # 이관은 더하기만
            for sql in ("ALTER TABLE t DROP COLUMN b", "ALTER TABLE t RENAME TO u", "ALTER TABLE t RENAME COLUMN a TO z",
                        "DROP TABLE t", "DELETE FROM t", "CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END",
                        "CREATE VIEW v AS SELECT * FROM t"):
                with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                    c.execute(sql)
            self.assertEqual([r[1] for r in c.execute("PRAGMA table_info(t)")], ["a", "b", "c"])
        finally:
            c.close()

    def test_sql_text_has_no_delete_replace_cascade(self):
        # 바꿔 넣기(REPLACE)는 SQLite 안에서 지우고 다시 넣는다 — 코드 글자로도 막는다(「REPLACE INTO」 포함)
        tree = ast.parse((ENGINE / "store.py").read_text(encoding="utf-8"))
        seen = 0
        for up in sql_strings(tree):
            seen += 1
            for w in FORBIDDEN_SQL:
                self.assertNotIn(w, up, f"SQL 에 {w}: {up[:60]}")
        self.assertGreater(seen, 20)
        probe = ast.parse('X = "REPLACE INTO t VALUES (1)"\nY = "replace into t values (1)"')
        self.assertEqual(len(list(sql_strings(probe))), 2)          # 검사기 자체가 이 모양을 본다

    def test_every_insert_is_plain_or_upsert(self):
        tree = ast.parse((ENGINE / "store.py").read_text(encoding="utf-8"))
        inserts = 0
        for up in sql_strings(tree):
            if "INSERT" in up:
                inserts += 1
                self.assertTrue(up.startswith("INSERT INTO"), up[:40])
                if "ON CONFLICT" in up:
                    self.assertIn("DO UPDATE SET", up)
        self.assertGreaterEqual(inserts, 9)

    def test_no_foreign_keys_declared(self):
        for sql in S._SCHEMA:
            self.assertNotIn("FOREIGN", sql.upper())
            self.assertNotIn("REFERENCES", sql.upper())


class AuthorizerTest(unittest.TestCase):
    def rule(self, phase, action, arg1=None, arg2=None):
        return S._authorizer(phase)(action, arg1, arg2, "main", None)

    def test_always_denied(self):
        a = sqlite3
        for act in (a.SQLITE_DELETE, a.SQLITE_DROP_TABLE, a.SQLITE_DROP_INDEX, a.SQLITE_DROP_VIEW, a.SQLITE_DROP_TRIGGER,
                    a.SQLITE_DROP_TEMP_TABLE, a.SQLITE_DROP_TEMP_INDEX, a.SQLITE_DROP_TEMP_VIEW,
                    a.SQLITE_DROP_TEMP_TRIGGER, a.SQLITE_DROP_VTABLE, a.SQLITE_ATTACH, a.SQLITE_DETACH,
                    a.SQLITE_CREATE_VIEW, a.SQLITE_CREATE_TRIGGER, a.SQLITE_CREATE_TEMP_VIEW,
                    a.SQLITE_CREATE_TEMP_TRIGGER, a.SQLITE_CREATE_VTABLE):
            for ph in (S.PHASE_MIGRATE, S.PHASE_RUN, S.PHASE_READ):
                self.assertEqual(self.rule(ph, act), a.SQLITE_DENY, (ph, act))

    def test_phase_table(self):
        a = sqlite3
        OK, NO = a.SQLITE_OK, a.SQLITE_DENY
        table = [
            (a.SQLITE_CREATE_TABLE, (OK, NO, NO)), (a.SQLITE_CREATE_INDEX, (OK, NO, NO)),
            (a.SQLITE_CREATE_TEMP_TABLE, (OK, NO, NO)), (a.SQLITE_CREATE_TEMP_INDEX, (OK, NO, NO)),
            (a.SQLITE_ALTER_TABLE, (OK, NO, NO)),
            (a.SQLITE_INSERT, (OK, OK, NO)), (a.SQLITE_UPDATE, (OK, OK, NO)),
            (a.SQLITE_SELECT, (OK, OK, OK)), (a.SQLITE_READ, (OK, OK, OK)), (a.SQLITE_TRANSACTION, (OK, OK, OK)),
        ]
        for act, want in table:
            got = tuple(self.rule(ph, act) for ph in (S.PHASE_MIGRATE, S.PHASE_RUN, S.PHASE_READ))
            self.assertEqual(got, want, act)

    def test_functions(self):
        a = sqlite3
        for fn in ("sqlite_drop_column", "sqlite_rename_table", "sqlite_rename_column", "sqlite_rename_test",
                   "sqlite_rename_quotefix", "load_extension", "LOAD_EXTENSION"):
            for ph in (S.PHASE_MIGRATE, S.PHASE_RUN, S.PHASE_READ):
                self.assertEqual(self.rule(ph, a.SQLITE_FUNCTION, None, fn), a.SQLITE_DENY, (ph, fn))
        for fn in ("max", "upper", "json_extract"):
            self.assertEqual(self.rule(S.PHASE_RUN, a.SQLITE_FUNCTION, None, fn), a.SQLITE_OK, fn)

    def test_pragmas(self):
        a = sqlite3
        OK, NO = a.SQLITE_OK, a.SQLITE_DENY
        cases = [
            ("user_version", None, (OK, OK, OK)), ("user_version", "5", (NO, NO, NO)),
            ("journal_mode", None, (OK, OK, OK)), ("journal_mode", "DELETE", (NO, NO, NO)),
            ("table_info", "naver_auto_meta", (OK, OK, OK)), ("synchronous", None, (OK, OK, OK)),
            ("synchronous", "OFF", (NO, NO, NO)), ("wal_checkpoint", None, (OK, OK, NO)),
            ("wal_checkpoint", "FULL", (OK, OK, NO)), ("writable_schema", None, (NO, NO, NO)),
            ("writable_schema", "1", (NO, NO, NO)), ("foreign_keys", "1", (NO, NO, NO)),
            ("TABLE_INFO", "x", (OK, OK, OK)),
        ]
        for name, arg, want in cases:
            got = tuple(self.rule(ph, a.SQLITE_PRAGMA, name, arg) for ph in (S.PHASE_MIGRATE, S.PHASE_RUN, S.PHASE_READ))
            self.assertEqual(got, want, (name, arg))


class ReaderTest(Base):
    def test_reader_cannot_write(self):
        self.st.record_accounts(kids((1234567, 11, "a")), NOW)
        r = S.open_reader(self.path)
        try:
            self.assertEqual(len(r.accounts()), 1)
            with self.assertRaises(S.StoreRefused):
                r.record_accounts(kids((7654321, 12, "b")), at(hours=1))
            with self.assertRaises(sqlite3.DatabaseError):
                r._conn.execute("UPDATE naver_auto_account SET present = 0")
            with self.assertRaises(sqlite3.DatabaseError):
                r._conn.execute("INSERT INTO naver_auto_meta (key, value) VALUES ('x', 'y')")
        finally:
            r.close()
        self.assertEqual(self.st.accounts()[0]["present"], 1)

    def test_reader_is_read_only_even_without_authorizer(self):
        """두 겹 방어를 하나씩 — 읽기 전용으로 연 것만으로도 쓰기가 막힌다."""
        self.st.record_accounts(kids((1234567, 11, "a")), NOW)
        r = S.open_reader(self.path)
        try:
            r._conn.set_authorizer(None)
            with self.assertRaises(sqlite3.OperationalError):
                r._conn.execute("UPDATE naver_auto_account SET present = 0")
        finally:
            r.close()

    def test_reader_authorizer_is_on(self):
        """다른 한 겹 — 읽기 전용 파일로도 막히지 않는 것(임시 표 · 다른 DB 붙이기 · 판 번호)을 연결이 거절한다."""
        r = S.open_reader(self.path)
        other = os.path.join(self.dir.name, "attached.db")
        try:
            for sql in ("CREATE TEMP TABLE t (a INTEGER)", f"ATTACH DATABASE '{other}' AS o", "PRAGMA user_version = 5",
                        "PRAGMA wal_checkpoint(FULL)"):
                with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                    r._conn.execute(sql)
        finally:
            r.close()
        self.assertFalse(os.path.exists(other))

    def test_reader_path_escaped(self):
        for dirname in ("a?mode=rw&x=", "b#c", "p%2e%2e"):
            d = os.path.join(self.dir.name, dirname)
            os.mkdir(d, 0o700)
            p = os.path.join(d, "engine.db")
            w = S.open_writer(p, clock=self.clock)
            try:
                w.record_accounts(kids((1234567, 11, dirname)), NOW)
                r = S.open_reader(p)
                try:
                    self.assertEqual([a["account_name"] for a in r.accounts()], [dirname])   # 검사한 그 파일
                    with self.assertRaises(sqlite3.DatabaseError):
                        r._conn.execute("UPDATE naver_auto_account SET present = 0")
                finally:
                    r.close()
            finally:
                w.close()
        stray = sorted(n for n in os.listdir(self.dir.name) if n not in ("a?mode=rw&x=", "b#c", "p%2e%2e") and
                       not n.startswith("engine.db"))
        self.assertEqual(stray, [])                                   # 엉뚱한 파일을 만들지 않았다

    def test_reader_missing_file(self):
        with self.assertRaises(S.StoreError):
            S.open_reader(os.path.join(self.dir.name, "none.db"))


class ProspectTest(Base):
    def test_only_complete_snapshot(self):
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects({11: row(11)})

    def test_absent_is_marked_not_removed(self):
        c1 = self.st.record_prospects(snap([row(11, name=NAME_MARK, end=date(2026, 12, 31)), row(12, "사후관리")]))
        self.assertEqual((c1.present, c1.new, c1.now_absent), (2, 2, 0))
        c2 = self.st.record_prospects(snap([row(12, "사후관리")], as_of=at(hours=6)))
        self.assertEqual((c2.present, c2.new, c2.now_absent), (1, 0, 1))
        p = {x["possibility_id"]: x for x in self.st.prospects()}
        self.assertEqual(set(p), {11, 12})                      # 줄은 남는다
        self.assertEqual(p[11]["present"], 0)
        self.assertEqual(p[11]["name"], NAME_MARK)              # 마지막으로 받은 값 그대로
        self.assertEqual(p[11]["latest_end_date"], "2026-12-31")
        self.assertEqual(p[11]["absent_since"], at(hours=6).isoformat(timespec="microseconds"))
        self.assertEqual(p[12]["absent_since"], None)
        c3 = self.st.record_prospects(snap([row(11), row(12)], as_of=at(hours=12)))
        self.assertEqual((c3.present, c3.new, c3.now_absent), (2, 0, 0))
        p = {x["possibility_id"]: x for x in self.st.prospects()}
        self.assertEqual((p[11]["present"], p[11]["absent_since"]), (1, None))

    def test_absent_since_keeps_first_time(self):
        self.st.record_prospects(snap([row(11), row(12)]))
        self.st.record_prospects(snap([row(12)], as_of=at(hours=6)))
        c = self.st.record_prospects(snap([row(12)], as_of=at(hours=12)))
        self.assertEqual(c.now_absent, 0)                       # 이미 빠진 가망은 다시 「새로 빠짐」이 아니다
        p = {x["possibility_id"]: x for x in self.st.prospects()}
        self.assertEqual(p[11]["absent_since"], at(hours=6).isoformat(timespec="microseconds"))
        self.assertEqual(p[11]["last_seen_at"], NOW.isoformat(timespec="microseconds"))

    def test_absent_present_absent(self):
        self.st.record_prospects(snap([row(11), row(12)]))
        self.st.record_prospects(snap([row(12)], as_of=at(hours=1)))
        self.st.record_prospects(snap([row(11), row(12)], as_of=at(hours=2)))
        c = self.st.record_prospects(snap([row(12)], as_of=at(hours=3)))
        self.assertEqual(c.now_absent, 1)                        # 돌아왔다 다시 빠지면 다시 셈
        p = {x["possibility_id"]: x for x in self.st.prospects()}
        self.assertEqual((p[11]["present"], p[11]["absent_since"]),
                         (0, at(hours=3).isoformat(timespec="microseconds")))

    def test_every_column_rewritten(self):
        self.st.record_prospects(snap([row(11, "진행중", "처음상호", date(2026, 12, 31), False)]))
        self.st.record_prospects(snap([row(11, "사후관리", "바뀐상호", date(2027, 1, 31), True)], as_of=at(hours=1)))
        p = self.st.prospects()[0]
        t0, t1 = NOW.isoformat(timespec="microseconds"), at(hours=1).isoformat(timespec="microseconds")
        self.assertEqual(p, {"possibility_id": 11, "name": "바뀐상호", "stage_key": "사후관리",
                             "latest_end_date": "2027-01-31", "end_unreadable": 1, "stage_conflict": 0, "present": 1,
                             "first_seen_at": t0, "last_seen_at": t1, "stage_synced_at": t1, "absent_since": None})
        self.st.record_prospects(snap([row(11, "진행중", None, None, False)], as_of=at(hours=2)))
        p = self.st.prospects()[0]
        self.assertEqual((p["name"], p["latest_end_date"], p["end_unreadable"]), (None, None, 0))   # 받은 그대로

    def test_conflict_clears_stage(self):
        self.st.record_prospects(snap([row(11, "진행중", name=NAME_MARK)]))
        self.st.record_prospects(snap([], as_of=at(hours=6), conflicts=[11]))
        p = self.st.prospects()[0]
        t6 = at(hours=6).isoformat(timespec="microseconds")
        self.assertEqual((p["stage_key"], p["stage_conflict"], p["present"], p["name"]), (None, 1, 1, NAME_MARK))
        self.assertEqual((p["last_seen_at"], p["stage_synced_at"]), (t6, t6))
        self.st.record_prospects(snap([row(11, "환불중")], as_of=at(hours=12)))
        p = self.st.prospects()[0]
        self.assertEqual((p["stage_key"], p["stage_conflict"]), ("환불중", 0))
        self.st.record_prospects(snap([], as_of=at(hours=13), conflicts=[12]))   # 처음 보는 가망이 겹쳐 들어옴
        p = {x["possibility_id"]: x for x in self.st.prospects()}
        self.assertEqual((p[12]["stage_key"], p[12]["stage_conflict"], p[12]["present"]), (None, 1, 1))
        self.assertEqual(p[11]["present"], 0)

    def test_older_or_same_snapshot_refused(self):
        self.st.record_prospects(snap([row(11)]))
        for t in (NOW, at(minutes=-1)):
            with self.assertRaises(S.StoreRefused):
                self.st.record_prospects(snap([row(12)], as_of=t))
        self.assertEqual([x["possibility_id"] for x in self.st.prospects()], [11])

    def test_same_second_order_kept(self):
        self.st.record_prospects(snap([row(11)], as_of=at(milliseconds=500)))
        with self.assertRaises(S.StoreRefused):                   # 같은 초 안의 더 이른 목록
            self.st.record_prospects(snap([row(12)], as_of=at(milliseconds=400)))
        self.st.record_prospects(snap([row(12)], as_of=at(milliseconds=600)))
        self.assertEqual({x["possibility_id"]: x["present"] for x in self.st.prospects()}, {11: 0, 12: 1})

    def test_empty_list_refused_when_something_present(self):
        c = self.st.record_prospects(snap([]))
        self.assertEqual((c.present, c.new, c.now_absent), (0, 0, 0))   # 처음 비어 있는 것은 된다
        self.st.record_prospects(snap([row(11)], as_of=at(hours=1)))
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(snap([], as_of=at(hours=2)))
        self.assertEqual(self.st.prospects()[0]["present"], 1)

    def test_times_are_kst(self):
        self.st.record_prospects(snap([row(11)], as_of=NOW.astimezone(timezone.utc)))
        p = self.st.prospects()[0]
        self.assertEqual(p["stage_synced_at"], "2026-09-29T06:40:00.000000+09:00")
        self.assertEqual(self.st.meta("prospects_synced_at"), "2026-09-29T06:40:00.000000+09:00")

    def test_future_refused(self):
        self.clock.t = NOW
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(snap([row(11)], as_of=at(minutes=6)))
        self.assertEqual(self.st.prospects(), [])
        self.st.record_prospects(snap([row(11)], as_of=at(minutes=4)))   # 시계 어긋남 5분까지는 받는다

    def test_bad_rows_refused_without_change(self):
        self.st.record_prospects(snap([row(11)]))
        bad = E.StageSnapshot({12: row(13)}, at(hours=1), {}, ())
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(bad)
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(snap([row(12)], as_of=at(hours=1), conflicts=[12]))
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(snap([row(12, end=datetime(2026, 12, 31, tzinfo=KST))], as_of=at(hours=1)))
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(snap([row(12, name="x" * 201)], as_of=at(hours=1)))
        self.assertEqual([x["possibility_id"] for x in self.st.prospects()], [11])
        self.assertEqual(self.st.prospects()[0]["present"], 1)
        self.assertEqual(self.st.meta("prospects_synced_at"), NOW.isoformat(timespec="microseconds"))


class AccountTest(Base):
    def test_only_complete_list(self):
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts({1234567: {"customerId": 1234567}}, NOW)

    def test_personal_fields_never_stored(self):
        self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b")), NOW)
        rid = self.st.begin_run(DAY, NOW)
        self.st.record_campaign_days(rid, 1234567, DAY, [camp(1234567, "cmp-a001")], {"cmp-a001": stat_row()},
                                     provisional=False, read_at=NOW)
        self.st._conn.execute("PRAGMA wal_checkpoint(FULL)")
        blob = self.file_bytes()
        self.assertNotIn(SECRET_OWNER.encode(), blob)
        self.assertNotIn(SECRET_TRACK.encode(), blob)
        self.assertNotIn(b"MANAGE", blob)                          # 계정 역할도 남길 칸 셋에 없다
        cols = {r[1] for r in self.st._conn.execute("PRAGMA table_info(naver_auto_account)")}
        self.assertEqual(cols, {"customer_id", "ad_account_no", "account_name", "present", "first_seen_on",
                                "last_seen_on", "absent_days", "last_absent_on"})

    def test_absent_days_count_once_per_day_and_reset(self):
        self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b")), NOW)
        c = self.st.record_accounts(kids((1234567, 11, "a")), at(days=1))
        self.assertEqual((c.present, c.new, c.now_absent), (1, 0, 1))
        c = self.st.record_accounts(kids((1234567, 11, "a")), at(days=1, hours=1))   # 같은 날 다시
        self.assertEqual(c.now_absent, 0)                          # 이미 빠진 계정은 「새로 빠짐」이 아니다
        a = {x["customer_id"]: x for x in self.st.accounts()}
        self.assertEqual((a[7654321]["present"], a[7654321]["absent_days"], a[7654321]["last_absent_on"]),
                         (0, 1, "2026-09-30"))
        self.st.record_accounts(kids((1234567, 11, "a")), at(days=2))
        a = {x["customer_id"]: x for x in self.st.accounts()}
        self.assertEqual((a[7654321]["absent_days"], a[7654321]["account_name"]), (2, "b"))
        self.assertEqual(a[7654321]["last_seen_on"], "2026-09-29")
        self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 13, "b2")), at(days=3))
        a = {x["customer_id"]: x for x in self.st.accounts()}
        self.assertEqual(a[7654321], {"customer_id": 7654321, "ad_account_no": 13, "account_name": "b2", "present": 1,
                                      "first_seen_on": "2026-09-29", "last_seen_on": "2026-10-02", "absent_days": 0,
                                      "last_absent_on": None})

    def test_same_day_absent_present_absent(self):
        self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b")), NOW)
        self.st.record_accounts(kids((1234567, 11, "a")), at(days=1))
        self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b")), at(days=1, hours=1))
        c = self.st.record_accounts(kids((1234567, 11, "a")), at(days=1, hours=2))
        self.assertEqual(c.now_absent, 1)
        a = {x["customer_id"]: x for x in self.st.accounts()}
        self.assertEqual((a[7654321]["present"], a[7654321]["absent_days"]), (0, 1))

    def test_days_are_kst(self):
        self.st.record_accounts(kids((1234567, 11, "a")), datetime(2026, 9, 28, 16, 0, tzinfo=timezone.utc))
        a = self.st.accounts()[0]
        self.assertEqual((a["first_seen_on"], a["last_seen_on"]), ("2026-09-29", "2026-09-29"))   # = 9/29 01:00 KST
        self.assertEqual(self.st.meta("accounts_read_at"), "2026-09-29T01:00:00.000000+09:00")

    def test_older_or_same_read_refused(self):
        self.st.record_accounts(kids((1234567, 11, "a")), NOW)
        for t in (NOW, at(minutes=-1), at(days=-1)):
            with self.assertRaises(S.StoreRefused):
                self.st.record_accounts(kids((7654321, 12, "b")), t)
        self.assertEqual([x["customer_id"] for x in self.st.accounts()], [1234567])
        self.assertEqual(self.st.accounts()[0]["present"], 1)

    def test_same_second_order_kept(self):
        self.st.record_accounts(kids((1234567, 11, "a")), at(milliseconds=500))
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(kids((7654321, 12, "b")), at(milliseconds=400))
        self.st.record_accounts(kids((7654321, 12, "b")), at(milliseconds=600))
        self.assertEqual({x["customer_id"]: x["present"] for x in self.st.accounts()}, {1234567: 0, 7654321: 1})

    def test_empty_list_refused_when_something_present(self):
        c = self.st.record_accounts(kids(per={1: 0}), NOW)
        self.assertEqual((c.present, c.new, c.now_absent), (0, 0, 0))
        self.st.record_accounts(kids((1234567, 11, "a")), at(hours=1))
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(kids(per={1: 0}), at(hours=2))
        self.assertEqual(self.st.accounts()[0]["present"], 1)

    def test_per_manager_checked(self):
        for per in ({}, {1: 0}, {1: True}, {1: -1}, [1]):
            with self.assertRaises(S.StoreRefused, msg=repr(per)):
                self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b"), per=per), NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b"), per={1: 1}), NOW)   # 합계 < 계정 수
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(kids(per={1: 3}), NOW)                                       # 줄은 있다는데 계정 0
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(kids(per={}), NOW)                                           # 관리계정이 하나도 없음
        self.assertEqual(self.st.accounts(), [])
        c = self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b"), per={1: 2, 2: 1}), NOW)   # 겹친 번호
        self.assertEqual(c.present, 2)

    def test_bad_rows(self):
        k = kids((1234567, 11, "a"))
        k.accounts[1234567]["customerId"] = 7654321
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(k, NOW)
        for bad in (DAY, "2026-09-29", datetime(2026, 9, 29, 6, 40)):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)):
                self.st.record_accounts(kids((1234567, 11, "a")), bad)
        for acc in ((1234567, True, "a"), (1234567, 0, "a"), (1234567, 11, 5), (-1, 11, "a")):
            with self.assertRaises(S.StoreRefused, msg=repr(acc)):
                self.st.record_accounts(kids(acc), NOW)
        self.assertEqual(self.st.accounts(), [])
        self.assertIsNone(self.st.meta("accounts_read_at"))

    def test_future_refused(self):
        self.clock.t = NOW
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(kids((1234567, 11, "a")), at(minutes=6))
        self.st.record_accounts(kids((1234567, 11, "a")), at(minutes=4))

    def test_error_text_has_no_values(self):
        k = kids((1234567, 11, "a" * 500))
        with self.assertRaises(S.StoreRefused) as cm:
            self.st.record_accounts(k, NOW)
        self.assertNotIn("1234567", str(cm.exception))
        self.assertNotIn("aaaa", str(cm.exception))
        with self.assertRaises(S.StoreRefused) as cm:
            self.st.record_decision(11, -7654321, "confirmed", 0, NOW)
        self.assertNotIn("7654321", str(cm.exception))
        rid = self.st.begin_run(DAY, NOW)
        with self.assertRaises(S.StoreRefused) as cm:
            self.st.record_account_day(rid, 1234567, status="ok", rules_run=[], rules_not_run=[], checked_at=NOW,
                                       bizmoney="987654")
        self.assertNotIn("987654", str(cm.exception))
        with self.assertRaises(S.StoreRefused) as cm:
            self.st.finish_run(rid, "failed", NOW, error_kind="https://api.example/7654321 boom")
        self.assertNotIn("7654321", str(cm.exception))


class DecisionTest(Base):
    def test_latest_wins_and_revoke(self):
        d1 = self.st.record_decision(11, 1234567, "confirmed", 0, NOW)          # 대표 = 0번
        self.st.record_decision(11, 7654321, "rejected", 5, NOW)
        self.assertEqual(self.st.current_decisions(), [(11, 1234567, "confirmed"), (11, 7654321, "rejected")])
        d3 = self.st.record_decision(11, 1234567, "rejected", 5, at(minutes=1))
        self.assertEqual(self.st.current_decisions()[0], (11, 1234567, "rejected"))
        self.st.revoke_decision(d3, 0, at(minutes=2), "잘못 누름")
        self.assertEqual(self.st.current_decisions()[0], (11, 1234567, "confirmed"))   # 앞의 판단이 다시 산다
        with self.assertRaises(S.StoreRefused):
            self.st.revoke_decision(d3, 0, at(minutes=3), "두 번")
        self.st.revoke_decision(d1, 0, at(minutes=3), "거둠")
        self.assertEqual(self.st.current_decisions(), [(11, 7654321, "rejected")])
        self.assertEqual(self.count("naver_auto_link_decision"), 3)              # 줄은 모두 남는다

    def test_times_and_people_stored(self):
        d = self.st.record_decision(11, 1234567, "confirmed", 7, NOW.astimezone(timezone.utc))
        self.st.revoke_decision(d, 3, at(minutes=1).astimezone(timezone.utc), "잘못 누름")
        r = self.st._conn.execute("""SELECT possibility_id, customer_id, decision, decided_by, decided_at, revoked_by,
                                            revoked_at, revoke_reason FROM naver_auto_link_decision""").fetchone()
        self.assertEqual(r, (11, 1234567, "confirmed", 7, "2026-09-29T06:40:00.000000+09:00", 3,
                             "2026-09-29T06:41:00.000000+09:00", "잘못 누름"))

    def test_bad_decisions(self):
        for args in ((11, 1234567, "auto", 0, NOW), (11, 1234567, "confirmed", -1, NOW),
                     (11, 1234567, "confirmed", True, NOW), (0, 1234567, "confirmed", 0, NOW),
                     (11, "1234567", "confirmed", 0, NOW), (11, 1234567, "confirmed", 0, datetime(2026, 9, 29))):
            with self.assertRaises(S.StoreRefused, msg=repr(args[2:4])):
                self.st.record_decision(*args)
        d = self.st.record_decision(11, 1234567, "confirmed", 0, NOW)
        for reason in ("", "   ", None, "x" * 65):
            with self.assertRaises(S.StoreRefused, msg=repr(reason)):
                self.st.revoke_decision(d, 0, NOW, reason)
        with self.assertRaises(S.StoreRefused):
            self.st.revoke_decision(999, 0, NOW, "없음")
        with self.assertRaises(S.StoreRefused):
            self.st.revoke_decision(d, -1, NOW, "사람 아님")
        self.assertEqual(self.st.current_decisions(), [(11, 1234567, "confirmed")])

    def test_future_refused(self):
        self.clock.t = NOW
        with self.assertRaises(S.StoreRefused):
            self.st.record_decision(11, 1234567, "confirmed", 0, at(minutes=6))
        d = self.st.record_decision(11, 1234567, "confirmed", 0, NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.revoke_decision(d, 0, at(minutes=6), "미래")
        self.assertEqual(self.count("naver_auto_link_decision"), 1)


class RunTest(Base):
    def test_run_lifecycle(self):
        rid = self.st.begin_run(DAY, NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.begin_run(DAY, at(minutes=1))                 # 같은 날 두 회차가 동시에 돌지 않는다
        self.st.finish_run(rid, "done", at(seconds=1800), 940, 930)
        with self.assertRaises(S.StoreRefused):
            self.st.finish_run(rid, "failed", at(seconds=1860))
        self.assertEqual(self.st.run(rid), {"run_id": rid, "run_date": "2026-09-29",
                                            "started_at": "2026-09-29T06:40:00.000000+09:00",
                                            "finished_at": "2026-09-29T07:10:00.000000+09:00", "status": "done",
                                            "accounts_total": 940, "accounts_ok": 930, "error_kind": None})
        rid2 = self.st.begin_run(DAY, at(hours=1))                # 끝난 뒤 다시 돌리기는 된다
        self.assertNotEqual(rid, rid2)
        self.assertEqual(self.st.running_runs(), [rid2])
        self.assertIsNone(self.st.run(999))

    def test_failed_run_stores_kind(self):
        rid = self.st.begin_run(DAY, NOW)
        self.st.finish_run(rid, "failed", at(minutes=2).astimezone(timezone.utc), error_kind="KEY_REJECTED")
        r = self.st.run(rid)
        self.assertEqual((r["status"], r["error_kind"], r["finished_at"], r["accounts_total"]),
                         ("failed", "KEY_REJECTED", "2026-09-29T06:42:00.000000+09:00", None))

    def test_error_kind_is_code_shaped(self):
        rid = self.st.begin_run(DAY, NOW)
        for kind in ("", "boom boom", "https://x", "a" * 41, "1abc", "키거절", "x\n"):
            with self.assertRaises(S.StoreRefused, msg=repr(kind)):
                self.st.finish_run(rid, "failed", NOW, error_kind=kind)
        self.assertEqual(self.st.running_runs(), [rid])
        self.st.finish_run(rid, "failed", NOW, error_kind="erp-timeout_2")

    def test_start_must_be_same_kst_day(self):
        with self.assertRaises(S.StoreRefused):
            self.st.begin_run(DAY, datetime(2026, 9, 28, 14, 59, tzinfo=timezone.utc))   # = 9/28 23:59 KST
        rid = self.st.begin_run(DAY, datetime(2026, 9, 28, 21, 40, tzinfo=timezone.utc))   # = 9/29 06:40 KST
        self.assertEqual(self.st.run(rid)["run_date"], "2026-09-29")
        with self.assertRaises(S.StoreRefused):
            self.st.begin_run(NOW, NOW)                                                     # 날짜 칸에 시각

    def test_bad_finish(self):
        rid = self.st.begin_run(DAY, NOW)
        for status, total, ok in (("running", None, None), ("ok", None, None), ("done", -1, None), ("done", True, None),
                                  ("done", None, 1.5), ("done", 2 ** 31, None)):
            with self.assertRaises(S.StoreRefused, msg=repr((status, total, ok))):
                self.st.finish_run(rid, status, NOW, total, ok)
        self.assertEqual(self.st.running_runs(), [rid])

    def test_future_refused(self):
        self.clock.t = NOW
        with self.assertRaises(S.StoreRefused):
            self.st.begin_run(DAY, at(minutes=6))
        rid = self.st.begin_run(DAY, NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.finish_run(rid, "done", at(minutes=6))
        self.assertEqual(self.st.running_runs(), [rid])


class AccountDayTest(Base):
    def setUp(self):
        super().setUp()
        self.rid = self.st.begin_run(DAY, NOW)

    def put(self, run_id=None, **kw):
        args = dict(status="ok", rules_run=["bizmoney"], rules_not_run=[("spend_jump", "not-enough-history")],
                    checked_at=NOW)
        args.update(kw)
        self.st.record_account_day(self.rid if run_id is None else run_id, 1234567, **args)

    def test_unknown_stays_null_not_zero(self):
        self.put(bizmoney=None, yday_spend=None, possibility_id=11, link="auto")
        d = self.st.account_day(1234567, DAY)
        self.assertIsNone(d["bizmoney"])
        self.assertIsNone(d["yday_spend"])
        self.assertEqual(d["rules_run"], ["bizmoney"])
        self.assertEqual(d["rules_not_run"], [("spend_jump", "not-enough-history")])
        self.assertEqual(d["day"], "2026-09-29")

    def test_zero_is_zero(self):
        self.put(bizmoney=0, yday_spend=0.0, budget_lock=False, data_late=False)
        d = self.st.account_day(1234567, DAY)
        self.assertEqual((d["bizmoney"], d["yday_spend"], d["budget_lock"], d["data_late"]), (0.0, 0.0, 0, 0))

    def test_bad_values_refused(self):
        for kw in ({"bizmoney": float("nan")}, {"bizmoney": float("inf")}, {"bizmoney": True},
                   {"bizmoney": "1000"}, {"bizmoney": 10 ** 400}, {"status": "green"}, {"link": "name"},
                   {"budget_lock": 1}, {"rules_run": None}, {"rules_run": "bizmoney"}, {"rules_run": ["Bizmoney"]},
                   {"rules_not_run": [("a",)]}, {"rules_not_run": [("a", "b", "c")]},
                   {"rules_not_run": ["ab"]}, {"rules_not_run": [("spend_jump", "Not Enough")]},
                   {"rules_not_run": [("bizmoney", "x")]},                    # 돌림과 못 돌림에 같은 규칙
                   {"rules_run": ["bizmoney", "bizmoney"]}, {"rules_not_run": {"spend_jump": "x"}},
                   {"checked_at": datetime(2026, 9, 29, 6, 40)}, {"possibility_id": 0}):
            with self.assertRaises(S.StoreRefused, msg=repr(kw)):
                self.put(**kw)
        self.assertIsNone(self.st.account_day(1234567, DAY))

    def test_every_column_rewritten(self):
        self.put(status="partial", rules_run=["bizmoney"], rules_not_run=[("spend_jump", "stats-unread")],
                 possibility_id=11, link="auto", bizmoney=100.0, budget_lock=False, refund_lock=True, yday_spend=1.0,
                 yday_imp=2.0, yday_clk=3.0, data_late=False, checked_at=NOW)
        self.put(status="ok", rules_run=["spend_jump", "no_impressions"], rules_not_run=[("bizmoney", "key-rejected")],
                 possibility_id=12, link="confirmed", bizmoney=200.5, budget_lock=True, refund_lock=False,
                 yday_spend=11.0, yday_imp=12.0, yday_clk=13.0, data_late=True, checked_at=at(minutes=3))
        d = self.st.account_day(1234567, DAY)
        self.assertEqual(d, {"customer_id": 1234567, "day": "2026-09-29", "possibility_id": 12, "link": "confirmed",
                             "run_id": self.rid, "status": "ok", "rules_run": ["spend_jump", "no_impressions"],
                             "rules_not_run": [("bizmoney", "key-rejected")], "bizmoney": 200.5, "budget_lock": 1,
                             "refund_lock": 0, "yday_spend": 11.0, "yday_imp": 12.0, "yday_clk": 13.0, "data_late": 1,
                             "checked_at": "2026-09-29T06:43:00.000000+09:00"})
        self.assertEqual(self.count("naver_auto_account_day"), 1)
        self.put(bizmoney=None, possibility_id=None, link=None, checked_at=at(minutes=4))
        d = self.st.account_day(1234567, DAY)
        self.assertEqual((d["bizmoney"], d["possibility_id"], d["link"]), (None, None, None))   # 받은 그대로(모름도)

    def test_rerun_same_day_takes_new_run(self):
        self.put(status="partial")
        self.st.finish_run(self.rid, "failed", at(minutes=10), error_kind="erp-timeout")
        rid2 = self.st.begin_run(DAY, at(minutes=20))
        self.put(run_id=rid2, status="ok", checked_at=at(minutes=21))
        d = self.st.account_day(1234567, DAY)
        self.assertEqual((d["run_id"], d["status"]), (rid2, "ok"))

    def test_not_after_run_finished(self):
        self.st.finish_run(self.rid, "failed", NOW, error_kind="KEY_REJECTED")
        with self.assertRaises(S.StoreRefused):
            self.put()
        with self.assertRaises(S.StoreRefused):
            self.put(run_id=999)

    def test_future_refused(self):
        self.clock.t = NOW
        with self.assertRaises(S.StoreRefused):
            self.put(checked_at=at(minutes=6))
        self.assertIsNone(self.st.account_day(1234567, DAY))

    def test_statuses_match_verdict(self):
        sys.path.insert(0, str(BACKEND))
        try:
            from app.naver_auto import matching, verdict
        finally:
            sys.path.remove(str(BACKEND))
        checks = {v for k, v in vars(verdict).items() if k.startswith("CHECK_")}
        self.assertEqual(S.ACCOUNT_STATUSES, checks)
        self.assertEqual(S.DECISIONS, {matching.DECISION_CONFIRMED, matching.DECISION_REJECTED})
        self.assertEqual(S.LINKS, {verdict.LINK_CONFIRMED, verdict.LINK_AUTO})


class CampaignDayTest(Base):
    def setUp(self):
        super().setUp()
        self.rid = self.st.begin_run(DAY, NOW)

    def put(self, cs, stats, cid=1234567, day=DAY, provisional=False, read_at=NOW, run_id=None):
        return self.st.record_campaign_days(self.rid if run_id is None else run_id, cid, day, cs, stats,
                                            provisional=provisional, read_at=read_at)

    def one(self, ccid="cmp-a001", day=DAY):
        return {r["campaign_id"]: r for r in self.st.campaign_days(1234567, day, day)}[ccid]

    def test_metrics_land_in_their_own_columns(self):
        n = self.put([camp(1234567, "cmp-a001"), camp(1234567, "cmp-a002")], {"cmp-a001": stat_row(salesAmt=None)},
                     provisional=True)
        self.assertEqual(n, 2)
        r = self.one()
        self.assertEqual({c: r[c] for _, c in S.CAMPAIGN_METRICS},
                         {"imp_cnt": 101.0, "clk_cnt": 7.0, "sales_amt": None, "ccnt": 3.0, "conv_amt": 30011.0,
                          "purchase_ccnt": 2.0, "purchase_conv_amt": 29003.0})
        self.assertEqual((r["metrics_read"], r["provisional"], r["run_id"], r["customer_id"]), (1, 1, self.rid, 1234567))
        self.assertEqual((r["campaign_tp"], r["status"], r["status_reason"], r["daily_budget"]),
                         ("SHOPPING", "ELIGIBLE", "ELIGIBLE", 50000.0))
        self.assertEqual(r["read_at"], "2026-09-29T06:40:00.000000+09:00")
        r2 = self.one("cmp-a002")
        self.assertEqual([r2[c] for _, c in S.CAMPAIGN_METRICS], [None] * 7)   # 통계 줄이 없으면 모름(0 아님)
        self.assertEqual(r2["metrics_read"], 0)

    def test_provisional_then_final(self):
        self.put([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row()}, provisional=True)
        n = self.put([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row(impCnt=150.0)}, read_at=at(hours=1))
        r = self.st.campaign_days(1234567, DAY, DAY)
        self.assertEqual((n, len(r), r[0]["imp_cnt"], r[0]["provisional"]), (1, 1, 150.0, 0))
        self.assertEqual(r[0]["read_at"], at(hours=1).isoformat(timespec="microseconds"))

    def test_final_not_downgraded_by_later_provisional(self):
        self.put([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row()})
        n = self.put([camp(1234567, "cmp-a001", status="PAUSED")], {"cmp-a001": stat_row(impCnt=999.0)},
                     provisional=True, read_at=at(hours=1))
        r = self.one()
        self.assertEqual((n, r["imp_cnt"], r["provisional"], r["status"]), (0, 101.0, 0, "ELIGIBLE"))

    def test_earlier_read_does_not_overwrite(self):
        self.put([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row()}, read_at=at(hours=1))
        n = self.put([camp(1234567, "cmp-a001", status="PAUSED")], {"cmp-a001": stat_row(impCnt=5.0)})
        r = self.one()
        self.assertEqual((n, r["imp_cnt"], r["status"]), (0, 101.0, "ELIGIBLE"))

    def test_missing_stats_keep_known_numbers(self):
        self.put([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row()}, provisional=True)
        n = self.put([camp(1234567, "cmp-a001", status="PAUSED", dailyBudget=70000)], {}, read_at=at(hours=1))
        r = self.one()
        self.assertEqual(n, 1)
        self.assertEqual([r[c] for _, c in S.CAMPAIGN_METRICS], [101.0, 7.0, 1301.0, 3.0, 30011.0, 2.0, 29003.0])
        self.assertEqual((r["metrics_read"], r["provisional"], r["read_at"]),
                         (1, 1, NOW.isoformat(timespec="microseconds")))     # 숫자에 붙은 잠정·읽은 시각도 그대로
        self.assertEqual((r["status"], r["daily_budget"]), ("PAUSED", 70000.0))   # 캠페인 정보는 새로
        n = self.put([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row(impCnt=120.0)}, read_at=at(hours=2))
        self.assertEqual((n, self.one()["imp_cnt"], self.one()["provisional"]), (1, 120.0, 0))

    def test_range_query(self):
        for back in range(7):
            self.put([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row(impCnt=float(back))},
                     day=DAY - timedelta(days=back))
        self.put([camp(7654321, "cmp-b001")], {}, cid=7654321)
        rows = self.st.campaign_days(1234567, DAY - timedelta(days=6), DAY)
        self.assertEqual([r["day"] for r in rows], [(DAY - timedelta(days=b)).isoformat() for b in range(6, -1, -1)])
        self.assertEqual([r["imp_cnt"] for r in rows], [6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0])
        self.assertEqual(len(self.st.campaign_days(1234567, DAY - timedelta(days=3), DAY - timedelta(days=1))), 3)
        self.assertEqual(self.st.campaign_days(1234567, DAY + timedelta(days=1), DAY + timedelta(days=9)), [])
        with self.assertRaises(S.StoreRefused):
            self.st.campaign_days(1234567, DAY, DAY - timedelta(days=1))
        with self.assertRaises(S.StoreRefused):
            self.st.campaign_days(1234567, NOW, DAY)

    def test_bad_inputs_refused(self):
        cases = [
            ([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row(), "cmp-zzz9": stat_row()}),   # 목록에 없는 통계
            ([camp(7654321, "cmp-a001")], {}),                                                 # 다른 계정 줄
            ([camp(1234567, "cmp-a001"), camp(1234567, "cmp-a001")], {}),                      # 번호 겹침
            ([camp(1234567, "x-1")], {}),                                                      # 번호 모양 아님
            ([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row(impCnt=float("nan"))}),
            ([camp(1234567, "cmp-a001")], {"cmp-a001": [1, 2]}),
            ([camp(1234567, "cmp-a001", dailyBudget="50000")], {}),
            (["cmp-a001"], {}),
        ]
        for cs, stats in cases:
            with self.assertRaises(S.StoreRefused, msg=repr(cs)[:60]):
                self.put(cs, stats)
        for kw in ({"provisional": 1}, {"day": NOW}, {"read_at": datetime(2026, 9, 29, 6, 40)}):
            with self.assertRaises(S.StoreRefused, msg=repr(kw)):
                self.put([], {}, **kw)
        with self.assertRaises(S.StoreRefused):
            self.st.record_campaign_days(self.rid, 1234567, DAY, [], [], provisional=False, read_at=NOW)
        self.assertEqual(self.st.campaign_days(1234567, DAY, DAY), [])

    def test_campaign_of_other_account_rolls_back_whole_call(self):
        self.put([camp(7654321, "cmp-b001")], {}, cid=7654321)
        with self.assertRaises(S.StoreRefused):
            self.put([camp(1234567, "cmp-a001"), camp(1234567, "cmp-b001")], {})
        self.assertEqual(self.st.campaign_days(1234567, DAY, DAY), [])   # 앞 줄도 들어가지 않았다
        self.assertEqual(len(self.st.campaign_days(7654321, DAY, DAY)), 1)

    def test_only_inside_running_run(self):
        self.st.finish_run(self.rid, "done", at(minutes=1))
        with self.assertRaises(S.StoreRefused):
            self.put([camp(1234567, "cmp-a001")], {})
        with self.assertRaises(S.StoreRefused):
            self.put([camp(1234567, "cmp-a001")], {}, run_id=999)
        rid2 = self.st.begin_run(DAY, at(minutes=2))
        self.assertEqual(self.put([camp(1234567, "cmp-a001")], {}, run_id=rid2), 1)
        self.assertEqual(self.one()["run_id"], rid2)

    def test_future_refused(self):
        self.clock.t = NOW
        with self.assertRaises(S.StoreRefused):
            self.put([camp(1234567, "cmp-a001")], {}, read_at=at(minutes=6))
        self.assertEqual(self.st.campaign_days(1234567, DAY, DAY), [])


class FailureTest(Base):
    def test_code_shapes(self):
        for good in ("bizmoney", "spend_jump", "a", "a" * 40):
            self.assertTrue(S._RULE_CODE.fullmatch(good), good)
        for bad in ("", "Bizmoney", "1abc", "a-b", "a b", "a" * 41, "규칙"):
            self.assertFalse(S._RULE_CODE.fullmatch(bad), bad)
        for good in ("stats-unread", "not-enough-history", "key_rejected", "3xx"):
            self.assertTrue(S._REASON_CODE.fullmatch(good), good)
        for bad in ("", "-x", "x-", "x--y", "Not", "a b", "a/b"):
            self.assertFalse(S._REASON_CODE.fullmatch(bad), bad)

    def test_database_errors_wrapped_without_values(self):
        """저장 중 DB 가 거절해도(방아쇠·가득 참 등) 문구에는 종류 이름만 — 번호·원래 문구가 새지 않는다."""
        self.st.close()
        raw = sqlite3.connect(self.path)
        raw.execute("""CREATE TRIGGER boom BEFORE INSERT ON naver_auto_link_decision
                       BEGIN SELECT RAISE(ABORT, 'boom 7654321'); END""")
        raw.commit()
        raw.close()
        self.st = S.open_writer(self.path, clock=self.clock)
        with self.assertRaises(S.StoreError) as cm:
            self.st.record_decision(11, 7654321, "confirmed", 0, NOW)
        self.assertNotIn("7654321", str(cm.exception))
        self.assertNotIn("boom", str(cm.exception))
        self.assertNotIsInstance(cm.exception, sqlite3.Error)
        self.assertFalse(self.st._conn.in_transaction)                          # 되돌린 뒤 다음 저장이 된다
        self.st.record_accounts(kids((1234567, 11, "a")), NOW)


if __name__ == "__main__":
    unittest.main()
