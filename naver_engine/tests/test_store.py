"""엔진 저장소 시험 (설계 v1.8 S6 · 반박 H8 · H9 · H10 · 대표 결정 D10).

- 지우지 않는다 — 연결이 지우기·표 버리기를 거절하고, 코드의 SQL 글자에도 지우기·바꿔 넣기·연쇄가 없다.
- 전부 받은 목록만 받고, 빠진 것은 「목록에 없음」 표시만 바꾼다(줄은 남는다).
- 남길 칸만 — 들어온 개인정보 칸(표지 값)은 저장 파일 어디에도 없다.
- 모름 ≠ 0 · 쓰는 곳 하나 · 파일 권한 600 · 엔진 코드 폴더 밖 · 한국 시각.
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


def snap(rows, as_of=NOW, conflicts=()):
    return E.StageSnapshot({r.possibility_id: r for r in rows}, as_of, {}, tuple(conflicts))


def row(pid, stage="진행중", name=None, end=None, unreadable=False):
    return E.StageRow(pid, stage, name, end, unreadable)


def kids(*accounts):
    acc = {}
    for cid, no, name in accounts:
        acc[cid] = {"customerId": cid, "adAccountNo": no, "adAccountName": name, "accountRole": "MANAGE",
                    "ownerNaverId": SECRET_OWNER}
    return N.ChildAccounts(acc, {1: len(acc)}, ({"managerAccountNo": 1},))


def camp(cid, ccid, **extra):
    c = {"nccCampaignId": ccid, "customerId": cid, "name": "캠페인", "campaignTp": "SHOPPING", "status": "ELIGIBLE",
         "statusReason": "ELIGIBLE", "dailyBudget": 50000, "trackingUrl": SECRET_TRACK}
    c.update(extra)
    return c


def stat_row(**kw):
    base = {"impCnt": 100.0, "clkCnt": 5.0, "salesAmt": 1200.0, "ccnt": 1.0, "convAmt": 30000.0,
            "purchaseCcnt": 1.0, "purchaseConvAmt": 30000.0}
    base.update(kw)
    return base


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "engine.db")
        self.st = S.open_writer(self.path)

    def tearDown(self):
        try:
            self.st.close()
        finally:
            self.dir.cleanup()

    def file_bytes(self):
        out = b""
        for suffix in ("", "-wal", "-shm"):
            p = self.path + suffix
            if os.path.exists(p):
                with open(p, "rb") as fh:
                    out += fh.read()
        return out


class OpenTest(Base):
    def test_new_file_is_owner_only_and_wal(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.st.record_accounts(kids((1234567, 11, "a")), DAY)
        self.assertTrue(os.path.exists(self.path + "-wal"))
        self.assertEqual(stat.S_IMODE(os.stat(self.path + "-wal").st_mode), 0o600)
        self.assertEqual(self.st._conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.assertEqual(self.st.meta("schema_version"), "1")

    def test_single_writer(self):
        with self.assertRaises(S.StoreBusy):
            S.open_writer(self.path)
        self.st.close()
        again = S.open_writer(self.path)
        again.close()
        self.st = S.open_writer(self.path)

    def test_refused_paths(self):
        for bad in ("engine.db", ":memory:", "", None, str(ENGINE / "data.db"), str(ENGINE / "tests" / "x.db")):
            with self.assertRaises(S.StoreRefused, msg=repr(bad)):
                S.open_writer(bad)
        link = os.path.join(self.dir.name, "into_code")
        os.symlink(str(ENGINE), link)
        with self.assertRaises(S.StoreRefused):
            S.open_writer(os.path.join(link, "x.db"))   # 바로가기로 코드 폴더 안에 두는 길도 막는다

    def test_newer_schema_refused(self):
        self.st._conn.execute("UPDATE naver_auto_meta SET value = '99' WHERE key = 'schema_version'")
        self.st.close()
        with self.assertRaises(S.StoreError):
            S.open_writer(self.path)
        self.st = S.open_reader(self.path)

    def test_repr_hides_path(self):
        self.assertNotIn(self.dir.name, repr(self.st))
        self.assertNotIn("engine.db", repr(self.st))


class NoDeleteTest(Base):
    def test_connection_refuses_delete_and_drop(self):
        self.st.record_accounts(kids((1234567, 11, "a")), DAY)
        for sql in ("DELETE FROM naver_auto_account", "DROP TABLE naver_auto_account",
                    "DROP INDEX naver_auto_campaign_day_customer",
                    f"ATTACH DATABASE '{os.path.join(self.dir.name, 'o.db')}' AS o"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                self.st._conn.execute(sql)
        self.assertEqual(len(self.st.accounts()), 1)

    def test_sql_text_has_no_delete_replace_cascade(self):
        # 바꿔 넣기(REPLACE)는 SQLite 안에서 지우고 다시 넣는다 — 연결이 막지 못하므로 코드 글자로 막는다
        tree = ast.parse((ENGINE / "store.py").read_text(encoding="utf-8"))
        words = ("DELETE", "DROP", "REPLACE", "TRUNCATE", "REFERENCES", "CASCADE", "ATTACH", "VACUUM")
        sql_seen = 0
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                up = n.value.upper()
                if any(k in up for k in ("INSERT", "UPDATE", "CREATE", "SELECT")):
                    sql_seen += 1
                    for w in words:
                        self.assertNotIn(w, up, f"SQL 에 {w}")
            if isinstance(n, ast.JoinedStr):
                for v in n.values:
                    if isinstance(v, ast.Constant):
                        for w in words:
                            self.assertNotIn(w, str(v.value).upper(), f"SQL 에 {w}")
        self.assertGreater(sql_seen, 15)

    def test_every_insert_is_plain_or_upsert(self):
        tree = ast.parse((ENGINE / "store.py").read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            texts = []
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                texts = [n.value]
            elif isinstance(n, ast.JoinedStr):
                texts = ["".join(str(v.value) for v in n.values if isinstance(v, ast.Constant))]
            for t in texts:
                up = " ".join(t.upper().split())
                if "INSERT" in up:
                    self.assertTrue(up.startswith("INSERT INTO"), up[:40])
                    self.assertNotIn("INSERT OR", up)

    def test_no_foreign_keys_declared(self):
        for sql in S._SCHEMA:
            self.assertNotIn("FOREIGN", sql.upper())
            self.assertNotIn("REFERENCES", sql.upper())


class ReaderTest(Base):
    def test_reader_cannot_write(self):
        self.st.record_accounts(kids((1234567, 11, "a")), DAY)
        r = S.open_reader(self.path)
        try:
            self.assertEqual(len(r.accounts()), 1)
            with self.assertRaises(S.StoreRefused):
                r.record_accounts(kids((7654321, 12, "b")), DAY)
            with self.assertRaises(sqlite3.DatabaseError):
                r._conn.execute("UPDATE naver_auto_account SET present = 0")
            with self.assertRaises(sqlite3.DatabaseError):
                r._conn.execute("INSERT INTO naver_auto_meta (key, value) VALUES ('x', 'y')")
        finally:
            r.close()
        self.assertEqual(self.st.accounts()[0]["present"], 1)

    def test_reader_is_read_only_even_without_authorizer(self):
        """두 겹 방어를 하나씩 — 읽기 전용으로 연 것만으로도 쓰기가 막힌다."""
        self.st.record_accounts(kids((1234567, 11, "a")), DAY)
        r = S.open_reader(self.path)
        try:
            r._conn.set_authorizer(None)
            with self.assertRaises(sqlite3.OperationalError):
                r._conn.execute("UPDATE naver_auto_account SET present = 0")
        finally:
            r.close()

    def test_authorizer_rules(self):
        w, rd = S._authorizer(reader=False), S._authorizer(reader=True)
        for a in (sqlite3.SQLITE_DELETE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_ATTACH,
                  sqlite3.SQLITE_DETACH, sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_VIEW):
            self.assertEqual(w(a, None, None, None, None), sqlite3.SQLITE_DENY, a)
            self.assertEqual(rd(a, None, None, None, None), sqlite3.SQLITE_DENY, a)
        for a in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_ALTER_TABLE):
            self.assertEqual(w(a, None, None, None, None), sqlite3.SQLITE_OK, a)
            self.assertEqual(rd(a, None, None, None, None), sqlite3.SQLITE_DENY, a)
        self.assertEqual(rd(sqlite3.SQLITE_SELECT, None, None, None, None), sqlite3.SQLITE_OK)

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
        c2 = self.st.record_prospects(snap([row(12, "사후관리")], as_of=NOW + timedelta(hours=6)))
        self.assertEqual((c2.present, c2.new, c2.now_absent), (1, 0, 1))
        p = {x["possibility_id"]: x for x in self.st.prospects()}
        self.assertEqual(set(p), {11, 12})                      # 줄은 남는다
        self.assertEqual(p[11]["present"], 0)
        self.assertEqual(p[11]["name"], NAME_MARK)              # 마지막으로 받은 값 그대로
        self.assertEqual(p[11]["latest_end_date"], "2026-12-31")
        self.assertEqual(p[11]["absent_since"], (NOW + timedelta(hours=6)).isoformat())
        c3 = self.st.record_prospects(snap([row(11), row(12)], as_of=NOW + timedelta(hours=12)))
        self.assertEqual((c3.present, c3.new, c3.now_absent), (2, 0, 0))
        p = {x["possibility_id"]: x for x in self.st.prospects()}
        self.assertEqual((p[11]["present"], p[11]["absent_since"]), (1, None))

    def test_absent_since_keeps_first_day(self):
        self.st.record_prospects(snap([row(11), row(12)]))
        self.st.record_prospects(snap([row(12)], as_of=NOW + timedelta(hours=6)))
        self.st.record_prospects(snap([row(12)], as_of=NOW + timedelta(hours=12)))
        p = {x["possibility_id"]: x for x in self.st.prospects()}
        self.assertEqual(p[11]["absent_since"], (NOW + timedelta(hours=6)).isoformat())

    def test_conflict_clears_stage(self):
        self.st.record_prospects(snap([row(11, "진행중")]))
        self.st.record_prospects(snap([], as_of=NOW + timedelta(hours=6), conflicts=[11]))
        p = self.st.prospects()[0]
        self.assertEqual((p["stage_key"], p["stage_conflict"], p["present"]), (None, 1, 1))
        self.st.record_prospects(snap([row(11, "환불중")], as_of=NOW + timedelta(hours=12)))
        p = self.st.prospects()[0]
        self.assertEqual((p["stage_key"], p["stage_conflict"]), ("환불중", 0))

    def test_older_snapshot_refused(self):
        self.st.record_prospects(snap([row(11)]))
        for t in (NOW, NOW - timedelta(minutes=1)):
            with self.assertRaises(S.StoreRefused):
                self.st.record_prospects(snap([], as_of=t))
        self.assertEqual(self.st.prospects()[0]["present"], 1)

    def test_times_are_kst(self):
        self.st.record_prospects(snap([row(11)], as_of=NOW.astimezone(timezone.utc)))
        self.assertTrue(self.st.prospects()[0]["stage_synced_at"].endswith("+09:00"))

    def test_bad_rows_refused_without_change(self):
        self.st.record_prospects(snap([row(11)]))
        bad = E.StageSnapshot({12: row(13)}, NOW + timedelta(hours=1), {}, ())
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(bad)
        with self.assertRaises(S.StoreRefused):
            self.st.record_prospects(snap([row(12)], as_of=NOW + timedelta(hours=1), conflicts=[12]))
        self.assertEqual([x["possibility_id"] for x in self.st.prospects()], [11])
        self.assertEqual(self.st.prospects()[0]["present"], 1)


class AccountTest(Base):
    def test_only_complete_list(self):
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts({1234567: {"customerId": 1234567}}, DAY)

    def test_personal_fields_never_stored(self):
        self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b")), DAY)
        self.st.record_campaign_days(1234567, DAY, [camp(1234567, "cmp-a001")], {"cmp-a001": stat_row()},
                                     provisional=False, read_at=NOW)
        self.st._conn.execute("PRAGMA wal_checkpoint(FULL)")
        blob = self.file_bytes()
        self.assertNotIn(SECRET_OWNER.encode(), blob)
        self.assertNotIn(SECRET_TRACK.encode(), blob)
        cols = {r[1] for r in self.st._conn.execute("PRAGMA table_info(naver_auto_account)")}
        self.assertEqual(cols, {"customer_id", "ad_account_no", "account_name", "present", "first_seen_on",
                                "last_seen_on", "absent_days", "last_absent_on"})

    def test_absent_days_count_once_per_day_and_reset(self):
        self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b")), DAY)
        c = self.st.record_accounts(kids((1234567, 11, "a")), DAY + timedelta(days=1))
        self.assertEqual((c.present, c.new, c.now_absent), (1, 0, 1))
        self.st.record_accounts(kids((1234567, 11, "a")), DAY + timedelta(days=1))   # 같은 날 다시
        a = {x["customer_id"]: x for x in self.st.accounts()}
        self.assertEqual((a[7654321]["present"], a[7654321]["absent_days"]), (0, 1))
        self.st.record_accounts(kids((1234567, 11, "a")), DAY + timedelta(days=2))
        a = {x["customer_id"]: x for x in self.st.accounts()}
        self.assertEqual(a[7654321]["absent_days"], 2)
        self.assertEqual(a[7654321]["account_name"], "b")
        self.st.record_accounts(kids((1234567, 11, "a"), (7654321, 12, "b2")), DAY + timedelta(days=3))
        a = {x["customer_id"]: x for x in self.st.accounts()}
        self.assertEqual((a[7654321]["present"], a[7654321]["absent_days"], a[7654321]["account_name"]), (1, 0, "b2"))

    def test_older_day_refused(self):
        self.st.record_accounts(kids((1234567, 11, "a")), DAY)
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(kids(), DAY - timedelta(days=1))
        self.assertEqual(self.st.accounts()[0]["present"], 1)

    def test_bad_rows(self):
        k = kids((1234567, 11, "a"))
        k.accounts[1234567]["customerId"] = 7654321
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(k, DAY)
        for bad in (datetime(2026, 9, 29, tzinfo=KST), "2026-09-29"):
            with self.assertRaises(S.StoreRefused):
                self.st.record_accounts(kids((1234567, 11, "a")), bad)
        k = kids((1234567, True, "a"))
        with self.assertRaises(S.StoreRefused):
            self.st.record_accounts(k, DAY)
        self.assertEqual(self.st.accounts(), [])

    def test_error_text_has_no_values(self):
        k = kids((1234567, 11, "a" * 500))
        with self.assertRaises(S.StoreRefused) as cm:
            self.st.record_accounts(k, DAY)
        self.assertNotIn("1234567", str(cm.exception))
        self.assertNotIn("aaaa", str(cm.exception))


class DecisionTest(Base):
    def test_latest_wins_and_revoke(self):
        d1 = self.st.record_decision(11, 1234567, "confirmed", 0, NOW)          # 대표 = 0번
        self.st.record_decision(11, 7654321, "rejected", 5, NOW)
        self.assertEqual(self.st.current_decisions(), [(11, 1234567, "confirmed"), (11, 7654321, "rejected")])
        d3 = self.st.record_decision(11, 1234567, "rejected", 5, NOW + timedelta(minutes=1))
        self.assertEqual(self.st.current_decisions()[0], (11, 1234567, "rejected"))
        self.st.revoke_decision(d3, 0, NOW + timedelta(minutes=2), "잘못 누름")
        self.assertEqual(self.st.current_decisions()[0], (11, 1234567, "confirmed"))   # 앞의 판단이 다시 산다
        with self.assertRaises(S.StoreRefused):
            self.st.revoke_decision(d3, 0, NOW, "두 번")
        self.st.revoke_decision(d1, 0, NOW, "거둠")
        self.assertEqual(self.st.current_decisions(), [(11, 7654321, "rejected")])
        n = self.st._conn.execute("SELECT COUNT(*) FROM naver_auto_link_decision").fetchone()[0]
        self.assertEqual(n, 3)                                                   # 줄은 모두 남는다

    def test_bad_decisions(self):
        for args in ((11, 1234567, "auto", 0, NOW), (11, 1234567, "confirmed", -1, NOW),
                     (11, 1234567, "confirmed", True, NOW), (0, 1234567, "confirmed", 0, NOW),
                     (11, "1234567", "confirmed", 0, NOW), (11, 1234567, "confirmed", 0, datetime(2026, 9, 29))):
            with self.assertRaises(S.StoreRefused, msg=repr(args[2:4])):
                self.st.record_decision(*args)
        d = self.st.record_decision(11, 1234567, "confirmed", 0, NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.revoke_decision(d, 0, NOW, "")
        with self.assertRaises(S.StoreRefused):
            self.st.revoke_decision(999, 0, NOW, "없음")


class RunTest(Base):
    def test_run_lifecycle(self):
        rid = self.st.begin_run(DAY, NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.begin_run(DAY, NOW)                         # 같은 날 두 회차가 동시에 돌지 않는다
        self.st.finish_run(rid, "done", NOW + timedelta(minutes=30), 940, 930)
        with self.assertRaises(S.StoreRefused):
            self.st.finish_run(rid, "failed", NOW + timedelta(minutes=31))
        r = self.st.run(rid)
        self.assertEqual((r["status"], r["accounts_total"], r["accounts_ok"]), ("done", 940, 930))
        rid2 = self.st.begin_run(DAY, NOW + timedelta(hours=1))   # 끝난 뒤 다시 돌리기는 된다
        self.assertNotEqual(rid, rid2)

    def test_start_must_be_same_kst_day(self):
        with self.assertRaises(S.StoreRefused):
            self.st.begin_run(DAY, datetime(2026, 9, 28, 14, 59, tzinfo=timezone.utc))   # = 9/28 23:59 KST
        rid = self.st.begin_run(DAY, datetime(2026, 9, 28, 21, 40, tzinfo=timezone.utc))   # = 9/29 06:40 KST
        self.assertEqual(self.st.run(rid)["run_date"], "2026-09-29")

    def test_bad_finish(self):
        rid = self.st.begin_run(DAY, NOW)
        for status, total in (("running", None), ("ok", None), ("done", -1), ("done", True)):
            with self.assertRaises(S.StoreRefused):
                self.st.finish_run(rid, status, NOW, total)


class AccountDayTest(Base):
    def setUp(self):
        super().setUp()
        self.rid = self.st.begin_run(DAY, NOW)

    def put(self, **kw):
        args = dict(status="ok", rules_run=["bizmoney"], rules_not_run=[("spend_jump", "not-enough-history")],
                    checked_at=NOW)
        args.update(kw)
        self.st.record_account_day(self.rid, 1234567, **args)

    def test_unknown_stays_null_not_zero(self):
        self.put(bizmoney=None, yday_spend=None, possibility_id=11, link="auto")
        d = self.st.account_day(1234567, DAY)
        self.assertIsNone(d["bizmoney"])
        self.assertIsNone(d["yday_spend"])
        self.assertEqual(d["rules_not_run"], [("spend_jump", "not-enough-history")])
        self.assertEqual(d["day"], "2026-09-29")

    def test_zero_is_zero(self):
        self.put(bizmoney=0, yday_spend=0.0, budget_lock=False, data_late=False)
        d = self.st.account_day(1234567, DAY)
        self.assertEqual((d["bizmoney"], d["yday_spend"], d["budget_lock"], d["data_late"]), (0.0, 0.0, 0, 0))

    def test_bad_values_refused(self):
        for kw in ({"bizmoney": float("nan")}, {"bizmoney": float("inf")}, {"bizmoney": True},
                   {"bizmoney": "1000"}, {"status": "green"}, {"link": "name"}, {"budget_lock": 1},
                   {"rules_run": None}, {"rules_not_run": [("a",)]}, {"checked_at": datetime(2026, 9, 29, 6, 40)}):
            with self.assertRaises(S.StoreRefused, msg=repr(list(kw))):
                self.put(**kw)
        self.assertIsNone(self.st.account_day(1234567, DAY))

    def test_rewrite_same_day(self):
        self.put(status="partial", bizmoney=100.0)
        self.put(status="ok", bizmoney=200.5)
        d = self.st.account_day(1234567, DAY)
        self.assertEqual((d["status"], d["bizmoney"]), ("ok", 200.5))
        self.assertEqual(self.st._conn.execute("SELECT COUNT(*) FROM naver_auto_account_day").fetchone()[0], 1)

    def test_not_after_run_finished(self):
        self.st.finish_run(self.rid, "failed", NOW, error_kind="KEY_REJECTED")
        with self.assertRaises(S.StoreRefused):
            self.put()

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
    def test_metrics_and_unknown(self):
        n = self.st.record_campaign_days(1234567, DAY, [camp(1234567, "cmp-a001"), camp(1234567, "cmp-a002")],
                                         {"cmp-a001": stat_row(salesAmt=None)}, provisional=True, read_at=NOW)
        self.assertEqual(n, 2)
        rows = {r["campaign_id"]: r for r in self.st.campaign_days(1234567, DAY, DAY)}
        self.assertEqual(rows["cmp-a001"]["imp_cnt"], 100.0)
        self.assertIsNone(rows["cmp-a001"]["sales_amt"])        # 빈 칸은 모름
        self.assertIsNone(rows["cmp-a002"]["imp_cnt"])          # 통계 줄이 없는 캠페인도 모름(0 아님)
        self.assertEqual(rows["cmp-a002"]["daily_budget"], 50000.0)
        self.assertEqual(rows["cmp-a001"]["provisional"], 1)
        self.assertTrue(rows["cmp-a001"]["read_at"].endswith("+09:00"))

    def test_rewrite_clears_provisional(self):
        self.st.record_campaign_days(1234567, DAY, [camp(1234567, "cmp-a001")], {"cmp-a001": stat_row()},
                                     provisional=True, read_at=NOW)
        self.st.record_campaign_days(1234567, DAY, [camp(1234567, "cmp-a001")], {"cmp-a001": stat_row(impCnt=150.0)},
                                     provisional=False, read_at=NOW + timedelta(hours=1))
        r = self.st.campaign_days(1234567, DAY, DAY)
        self.assertEqual((len(r), r[0]["imp_cnt"], r[0]["provisional"]), (1, 150.0, 0))

    def test_bad_inputs_refused(self):
        cases = [
            ([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row(), "cmp-zzz9": stat_row()}),   # 목록에 없는 통계
            ([camp(7654321, "cmp-a001")], {}),                                                 # 다른 계정 줄
            ([camp(1234567, "cmp-a001"), camp(1234567, "cmp-a001")], {}),                      # 번호 겹침
            ([camp(1234567, "x-1")], {}),                                                      # 번호 모양 아님
            ([camp(1234567, "cmp-a001")], {"cmp-a001": stat_row(impCnt=float("nan"))}),
            ([camp(1234567, "cmp-a001", dailyBudget="50000")], {}),
        ]
        for cs, stats in cases:
            with self.assertRaises(S.StoreRefused):
                self.st.record_campaign_days(1234567, DAY, cs, stats, provisional=False, read_at=NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.record_campaign_days(1234567, DAY, [], {}, provisional=1, read_at=NOW)
        self.assertEqual(self.st.campaign_days(1234567, DAY, DAY), [])

    def test_campaign_of_other_account_rolls_back_whole_call(self):
        self.st.record_campaign_days(7654321, DAY, [camp(7654321, "cmp-b001")], {}, provisional=False, read_at=NOW)
        with self.assertRaises(S.StoreRefused):
            self.st.record_campaign_days(1234567, DAY, [camp(1234567, "cmp-a001"), camp(1234567, "cmp-b001")],
                                         {}, provisional=False, read_at=NOW)
        self.assertEqual(self.st.campaign_days(1234567, DAY, DAY), [])   # 앞 줄도 들어가지 않았다
        self.assertEqual(len(self.st.campaign_days(7654321, DAY, DAY)), 1)


if __name__ == "__main__":
    unittest.main()
