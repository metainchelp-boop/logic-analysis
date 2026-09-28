"""엔진 저장소 — 엔진 전용 파일 하나 · 쓰는 곳 하나 (설계 v1.8 S6 · 대표 결정 D10 · 반박 H8 · H9 · H10).

지키는 것
- **지우지 않는다.** 고치기·더하기(upsert)만 한다. 목록에서 빠진 것은 「현재 목록에 없음」 표시만 바꾼다(반박 H8 —
  가망 표를 통째로 바꾸다 확인한 짝·이슈가 연쇄로 사라지는 길을 막는다). DB 연결 자체가 지우기·표 버리기를 거절한다
  (``_authorizer``) — 누가 나중에 지우는 SQL 을 더해도 실행되지 않는다. 외래 키·연쇄 삭제도 쓰지 않는다.
- **전부 받은 목록만 받는다.** 전산 단계는 ``erp_read.StageSnapshot``, 네이버 연결 목록은 ``naver_read.ChildAccounts``
  — 둘 다 「전부 받았을 때만 만들어지는」 모양이다(반박 H1). 일부만 받은 목록으로 「목록에 없음」을 찍지 않는다.
- **남길 칸만.** 네이버 계정 줄은 ``fields.CHILD_ACCOUNT`` 중 세 칸만 쓴다 — 계정책임자 아이디(``ownerNaverId``) 같은
  칸은 들어와도 저장되지 않는다(반박 H10). 키·비밀값은 이 파일로 오지 않는다.
- **모름 ≠ 0.** 빈 값은 NULL 로 두고 0 으로 채우지 않는다. 숫자가 아닌 값·NaN·무한은 거절한다(0 으로 바뀌지 않게).
- **쓰는 곳 하나.** 쓰기용으로 열면 옆 잠금 파일을 독점으로 잡는다 — 두 번째 쓰기는 바로 ``StoreBusy``.
  읽기용은 읽기 전용으로 열고, 연결도 쓰기를 거절한다.
- **파일은 우리만.** 새 파일은 권한 600 · 엔진 코드 폴더 안에는 만들지 않는다(반박 H9 — 코드를 보낼 때 덮이지 않게).
- **시각은 한국 시각으로 적는다**(③ 기존 표의 UTC 와 섞지 않는다). 날짜 칸은 ``date`` 만 받는다.
- 오류 문구에는 값(번호·이름·금액)을 넣지 않는다.

엔진이 한 회차에 부르는 순서(S7~S9): ``record_prospects`` → ``record_accounts`` → ``begin_run`` →
계정마다 ``record_account_day`` · ``record_campaign_days`` → ``finish_run``. 이슈 표는 S9 에서 더한다.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import erp_read as E
from . import fields as F
from . import handles as H
from . import naver_read as N

KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000
_CODE_DIR = os.path.dirname(os.path.realpath(__file__))

# 점검 상태 — backend/app/naver_auto/verdict.py 의 CHECK_* 와 같은 글자(시험이 대조한다)
ACCOUNT_STATUSES = frozenset({
    "ok", "pending", "not_checked", "partial", "key_rejected", "data_late", "system_gap", "link_broken", "not_eligible",
})
LINKS = frozenset({H.LINK_CONFIRMED, H.LINK_AUTO})
DECISIONS = frozenset({"confirmed", "rejected"})   # backend/app/naver_auto/matching.py 의 DECISION_* 와 같은 글자
RUN_RUNNING, RUN_DONE, RUN_FAILED = "running", "done", "failed"
RUN_END_STATUSES = frozenset({RUN_DONE, RUN_FAILED})

# 캠페인 하루치 — 더할 수 있는 원래 숫자만 남긴다(클릭률·클릭당 비용은 보여 줄 때 계산 · 주간·월간 합계가 맞게)
CAMPAIGN_METRICS = (
    ("impCnt", "imp_cnt"), ("clkCnt", "clk_cnt"), ("salesAmt", "sales_amt"), ("ccnt", "ccnt"),
    ("convAmt", "conv_amt"), ("purchaseCcnt", "purchase_ccnt"), ("purchaseConvAmt", "purchase_conv_amt"),
)

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS naver_auto_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL)""",
    # ① 관리 단계 가망 — 전산에서 받은 것만(남길 칸)
    """CREATE TABLE IF NOT EXISTS naver_auto_prospect (
        possibility_id INTEGER PRIMARY KEY CHECK (possibility_id > 0),
        name TEXT,
        stage_key TEXT,
        latest_end_date TEXT,
        end_unreadable INTEGER NOT NULL DEFAULT 0 CHECK (end_unreadable IN (0, 1)),
        stage_conflict INTEGER NOT NULL DEFAULT 0 CHECK (stage_conflict IN (0, 1)),
        present INTEGER NOT NULL CHECK (present IN (0, 1)),
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT,
        stage_synced_at TEXT,
        absent_since TEXT)""",
    # 네이버 대행 연결 목록의 하위 광고계정 — 남길 칸 셋
    """CREATE TABLE IF NOT EXISTS naver_auto_account (
        customer_id INTEGER PRIMARY KEY CHECK (customer_id > 0),
        ad_account_no INTEGER,
        account_name TEXT,
        present INTEGER NOT NULL CHECK (present IN (0, 1)),
        first_seen_on TEXT NOT NULL,
        last_seen_on TEXT,
        absent_days INTEGER NOT NULL DEFAULT 0 CHECK (absent_days >= 0),
        last_absent_on TEXT)""",
    # 사람이 짝 확인 화면에서 내린 판단 — 쌓기만 한다(되돌림도 칸을 채울 뿐 줄을 지우지 않는다)
    """CREATE TABLE IF NOT EXISTS naver_auto_link_decision (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        possibility_id INTEGER NOT NULL CHECK (possibility_id > 0),
        customer_id INTEGER NOT NULL CHECK (customer_id > 0),
        decision TEXT NOT NULL CHECK (decision IN ('confirmed', 'rejected')),
        decided_by INTEGER NOT NULL CHECK (decided_by >= 0),
        decided_at TEXT NOT NULL,
        revoked_by INTEGER CHECK (revoked_by IS NULL OR revoked_by >= 0),
        revoked_at TEXT,
        revoke_reason TEXT)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_link_decision_pair
        ON naver_auto_link_decision (possibility_id, customer_id)""",
    # 아침 점검 회차
    """CREATE TABLE IF NOT EXISTS naver_auto_check_run (
        run_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_date TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
        accounts_total INTEGER CHECK (accounts_total IS NULL OR accounts_total >= 0),
        accounts_ok INTEGER CHECK (accounts_ok IS NULL OR accounts_ok >= 0),
        error_kind TEXT)""",
    # 광고계정 × 날짜 — 판정 재료 · 규칙마다 돌림/못 돌림(반박 C1) · 금액 칸은 모름이면 NULL
    """CREATE TABLE IF NOT EXISTS naver_auto_account_day (
        customer_id INTEGER NOT NULL CHECK (customer_id > 0),
        day TEXT NOT NULL,
        possibility_id INTEGER CHECK (possibility_id IS NULL OR possibility_id > 0),
        link TEXT CHECK (link IS NULL OR link IN ('confirmed', 'auto')),
        run_id INTEGER NOT NULL,
        status TEXT NOT NULL,
        rules_run TEXT NOT NULL,
        rules_not_run TEXT NOT NULL,
        bizmoney REAL,
        budget_lock INTEGER CHECK (budget_lock IS NULL OR budget_lock IN (0, 1)),
        refund_lock INTEGER CHECK (refund_lock IS NULL OR refund_lock IN (0, 1)),
        yday_spend REAL,
        yday_imp REAL,
        yday_clk REAL,
        data_late INTEGER CHECK (data_late IS NULL OR data_late IN (0, 1)),
        checked_at TEXT NOT NULL,
        PRIMARY KEY (customer_id, day))""",
    # 캠페인 × 날짜 — 더할 수 있는 원래 숫자 7개 + 상태·사유·하루 예산 · 잠정(L8)·읽은 시각
    """CREATE TABLE IF NOT EXISTS naver_auto_campaign_day (
        campaign_id TEXT NOT NULL,
        day TEXT NOT NULL,
        customer_id INTEGER NOT NULL CHECK (customer_id > 0),
        campaign_tp TEXT,
        status TEXT,
        status_reason TEXT,
        daily_budget REAL,
        imp_cnt REAL,
        clk_cnt REAL,
        sales_amt REAL,
        ccnt REAL,
        conv_amt REAL,
        purchase_ccnt REAL,
        purchase_conv_amt REAL,
        provisional INTEGER NOT NULL CHECK (provisional IN (0, 1)),
        read_at TEXT NOT NULL,
        PRIMARY KEY (campaign_id, day))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_campaign_day_customer
        ON naver_auto_campaign_day (customer_id, day)""",
)

# 연결이 허락하지 않는 일 — 지우기 · 표/색인/보기/방아쇠 버리기 · 다른 DB 붙이기
_DENY_ALWAYS = frozenset({
    sqlite3.SQLITE_DELETE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_DROP_VIEW,
    sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_TEMP_TABLE, sqlite3.SQLITE_DROP_TEMP_INDEX,
    sqlite3.SQLITE_DROP_TEMP_VIEW, sqlite3.SQLITE_DROP_TEMP_TRIGGER, sqlite3.SQLITE_DROP_VTABLE,
    sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH,
})
_DENY_ON_READER = frozenset({
    sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_INDEX,
    sqlite3.SQLITE_CREATE_VIEW, sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_ALTER_TABLE,
})


class StoreError(RuntimeError):
    """저장소가 거절했다. 문구에 값(번호·이름·금액)을 넣지 않는다."""


class StoreBusy(StoreError):
    """다른 곳이 이미 쓰기용으로 열었다(쓰는 곳 하나)."""


class StoreRefused(StoreError):
    """이 자리·이 모양으로는 받지 않는다."""


@dataclass(frozen=True)
class SyncCounts:
    present: int
    new: int
    now_absent: int

    def __repr__(self) -> str:
        return f"SyncCounts(present={self.present}, new={self.new}, now_absent={self.now_absent})"


# ── 값 검사(값은 문구에 넣지 않는다) ──────────────────────────────────
def _kst_text(t: datetime, what: str) -> str:
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise StoreRefused(f"{what}: 시간대가 있는 시각이어야 합니다")
    return t.astimezone(KST).isoformat(timespec="seconds")


def _day_text(d, what: str) -> str:
    if type(d) is not date:   # 시각(datetime)은 날짜가 아니다
        raise StoreRefused(f"{what}: 날짜(date)여야 합니다")
    return d.isoformat()


def _pos_int(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise StoreRefused(f"{what}: 양의 정수여야 합니다")
    return v


def _opt_pos_int(v, what: str) -> Optional[int]:
    return None if v is None else _pos_int(v, what)


def _person(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:   # 대표 = 0번(설계 v1.6)
        raise StoreRefused(f"{what}: 직원 번호는 0 이상 정수여야 합니다")
    return v


def _num(v, what: str) -> Optional[float]:
    """숫자 또는 모름(None). NaN·무한·참거짓·글자는 거절 — 조용히 0 이나 NULL 로 바뀌지 않게."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise StoreRefused(f"{what}: 숫자가 아닙니다")
    return float(v)


def _opt_bool(v, what: str) -> Optional[int]:
    if v is None:
        return None
    if type(v) is not bool:
        raise StoreRefused(f"{what}: 참/거짓이어야 합니다")
    return int(v)


def _opt_text(v, what: str, limit: int = 200) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str) or len(v) > limit:
        raise StoreRefused(f"{what}: 글자가 아니거나 너무 깁니다")
    return v


def _codes(items, what: str) -> str:
    if items is None:
        raise StoreRefused(f"{what}: 비어 있으면 안 됩니다")
    out = []
    for it in items:
        if isinstance(it, str):
            out.append(_opt_text(it, what, 64))
        elif isinstance(it, (tuple, list)) and len(it) == 2 and all(isinstance(x, str) for x in it):
            out.append([_opt_text(it[0], what, 64), _opt_text(it[1], what, 64)])
        else:
            raise StoreRefused(f"{what}: 규칙 코드 목록이 아닙니다")
    return json.dumps(out, ensure_ascii=False)


# ── 열기 ─────────────────────────────────────────────────────────────
def _check_path(path) -> str:
    if not isinstance(path, str) or not path or path == ":memory:" or not os.path.isabs(path):
        raise StoreRefused("저장 파일은 절대 경로여야 합니다")
    real = os.path.realpath(path)
    if os.path.commonpath([real, _CODE_DIR]) == _CODE_DIR:
        raise StoreRefused("저장 파일을 엔진 코드 폴더 안에 둘 수 없습니다")   # 코드를 보낼 때 덮이지 않게(반박 H9)
    return real


def _authorizer(reader: bool):
    def check(action, arg1, arg2, dbname, source):
        if action in _DENY_ALWAYS or (reader and action in _DENY_ON_READER):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return check


def open_writer(path: str) -> "Store":
    """쓰기용으로 연다 — 잠금을 못 잡으면 바로 ``StoreBusy``(기다리지 않는다)."""
    real = _check_path(path)
    lock_fd = os.open(real + ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(lock_fd)
        raise StoreBusy("다른 곳이 이미 쓰기용으로 열었습니다") from None
    try:
        if not os.path.exists(real):
            os.close(os.open(real, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600))   # 우리만 읽고 쓰는 새 파일
        conn = sqlite3.connect(real, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            conn.close()
            raise StoreError("WAL 로 열지 못했습니다")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.set_authorizer(_authorizer(reader=False))
        store = Store(conn, real, lock_fd, writer=True)
        store._migrate()
        return store
    except BaseException:
        os.close(lock_fd)
        raise


def open_reader(path: str) -> "Store":
    """읽기 전용으로 연다(웹 API 등) — 연결이 쓰기를 거절한다."""
    real = _check_path(path)
    if not os.path.exists(real):
        raise StoreError("저장 파일이 아직 없습니다")
    conn = sqlite3.connect(f"file:{real}?mode=ro", uri=True, isolation_level=None,
                           timeout=BUSY_TIMEOUT_MS / 1000)
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.set_authorizer(_authorizer(reader=True))
    return Store(conn, real, None, writer=False)


# ── 저장소 ───────────────────────────────────────────────────────────
class Store:
    def __init__(self, conn: sqlite3.Connection, path: str, lock_fd: Optional[int], writer: bool) -> None:
        self._conn = conn
        self._path = path
        self._lock_fd = lock_fd
        self.writer = writer

    def __repr__(self) -> str:   # 경로·값을 보이지 않는다
        return f"Store(writer={self.writer})"

    def close(self) -> None:
        try:
            self._conn.close()
        finally:
            if self._lock_fd is not None:
                fd, self._lock_fd = self._lock_fd, None
                os.close(fd)   # 잠금도 함께 풀린다

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 내부 ──
    def _need_writer(self) -> None:
        if not self.writer:
            raise StoreRefused("읽기용으로 연 저장소입니다")

    def _tx(self):
        store = self

        class _Tx:
            def __enter__(self_inner):
                store._conn.execute("BEGIN IMMEDIATE")
                return store._conn

            def __exit__(self_inner, et, ev, tb):
                store._conn.execute("COMMIT" if et is None else "ROLLBACK")
                return False
        return _Tx()

    def _migrate(self) -> None:
        with self._tx() as c:
            for sql in _SCHEMA:
                c.execute(sql)
            row = c.execute("SELECT value FROM naver_auto_meta WHERE key = 'schema_version'").fetchone()
            if row is None:
                c.execute("INSERT INTO naver_auto_meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif int(row[0]) > SCHEMA_VERSION:
                raise StoreError("이 엔진보다 새 저장 파일입니다")   # 옛 엔진이 새 파일을 덮어쓰지 않게

    # ── ① 관리 단계 가망 ──
    def record_prospects(self, snap: "E.StageSnapshot") -> SyncCounts:
        """전산 7단계를 전부 받은 결과로 가망 표를 고친다 — 없어진 가망은 지우지 않고 「목록에 없음」."""
        self._need_writer()
        if not isinstance(snap, E.StageSnapshot):
            raise StoreRefused("전산 단계 목록은 전부 받은 결과(StageSnapshot)만 받습니다")
        at = _kst_text(snap.as_of, "받은 시각")
        rows = []
        for pid, r in snap.rows.items():
            if not isinstance(r, E.StageRow) or r.possibility_id != pid:
                raise StoreRefused("전산 단계 줄 모양이 아닙니다")
            rows.append((_pos_int(pid, "가망 번호"), _opt_text(r.name, "가망 이름"), _opt_text(r.stage_key, "단계", 40),
                         None if r.latest_end_date is None else _day_text(r.latest_end_date, "종료일"),
                         int(bool(r.end_unreadable)), 0))
        conflicts = sorted({_pos_int(p, "가망 번호") for p in snap.stage_conflicts})
        if set(conflicts) & set(snap.rows):
            raise StoreRefused("단계가 겹친 가망이 줄에도 있습니다")
        seen = [r[0] for r in rows] + conflicts
        with self._tx() as c:
            last = self._get_meta(c, "prospects_synced_at")
            if last is not None and datetime.fromisoformat(last) >= snap.as_of:
                raise StoreRefused("이미 적은 것보다 늦지 않은 단계 목록입니다")   # 옛 목록이 새 목록을 덮지 않게
            before = {p for (p,) in c.execute("SELECT possibility_id FROM naver_auto_prospect")}
            for pid, name, stage, end, unread, _ in rows:
                c.execute(
                    """INSERT INTO naver_auto_prospect (possibility_id, name, stage_key, latest_end_date, end_unreadable,
                           stage_conflict, present, first_seen_at, last_seen_at, stage_synced_at, absent_since)
                       VALUES (?, ?, ?, ?, ?, 0, 1, ?, ?, ?, NULL)
                       ON CONFLICT (possibility_id) DO UPDATE SET
                           name = excluded.name, stage_key = excluded.stage_key,
                           latest_end_date = excluded.latest_end_date, end_unreadable = excluded.end_unreadable,
                           stage_conflict = 0, present = 1, last_seen_at = excluded.last_seen_at,
                           stage_synced_at = excluded.stage_synced_at, absent_since = NULL""",
                    (pid, name, stage, end, unread, at, at, at))
            for pid in conflicts:   # 두 단계에 나온 가망 — 오늘은 들어가지 않는다(단계를 비운다)
                c.execute(
                    """INSERT INTO naver_auto_prospect (possibility_id, name, stage_key, latest_end_date, end_unreadable,
                           stage_conflict, present, first_seen_at, last_seen_at, stage_synced_at, absent_since)
                       VALUES (?, NULL, NULL, NULL, 0, 1, 1, ?, ?, ?, NULL)
                       ON CONFLICT (possibility_id) DO UPDATE SET
                           stage_key = NULL, stage_conflict = 1, present = 1, last_seen_at = excluded.last_seen_at,
                           stage_synced_at = excluded.stage_synced_at, absent_since = NULL""",
                    (pid, at, at, at))
            now_absent = 0
            for pid in sorted(before - set(seen)):
                cur = c.execute(
                    """UPDATE naver_auto_prospect SET present = 0, absent_since = COALESCE(absent_since, ?)
                       WHERE possibility_id = ? AND present = 1""", (at, pid))
                now_absent += cur.rowcount
            self._set_meta(c, "prospects_synced_at", at)
        return SyncCounts(len(seen), len(set(seen) - before), now_absent)

    # ── 네이버 대행 연결 목록 ──
    def record_accounts(self, kids: "N.ChildAccounts", day: date) -> SyncCounts:
        """대행 연결 목록을 전부 받은 결과로 계정 표를 고친다 — 없어진 계정은 「목록에 없음」 · 연속 없는 날을 센다.

        같은 날 두 번 불러도 없는 날은 한 번만 센다. 확인한 짝을 무효로 할지(2일 연속)는 짝 동기화(S8)가 정한다.
        """
        self._need_writer()
        if not isinstance(kids, N.ChildAccounts):
            raise StoreRefused("연결 목록은 전부 받은 결과(ChildAccounts)만 받습니다")
        d = _day_text(day, "날짜")
        rows = []
        for cid, rec in kids.accounts.items():
            if not isinstance(rec, Mapping):
                raise StoreRefused("연결 목록 줄 모양이 아닙니다")
            kept = F.keep(rec, F.CHILD_ACCOUNT)          # 남길 칸만 — 들어온 다른 칸은 여기서 끝난다
            if kept.get("customerId") != cid:
                raise StoreRefused("연결 목록 줄의 고객 번호가 맞지 않습니다")
            rows.append((_pos_int(cid, "고객 번호"), _opt_pos_int(kept.get("adAccountNo"), "광고계정 번호"),
                         _opt_text(kept.get("adAccountName"), "계정 이름")))
        with self._tx() as c:
            last = self._get_meta(c, "accounts_synced_on")
            if last is not None and last > d:
                raise StoreRefused("이미 적은 날보다 앞선 연결 목록입니다")   # 같은 날 다시 적기는 된다(없는 날은 한 번만 센다)
            before = {cid for (cid,) in c.execute("SELECT customer_id FROM naver_auto_account")}
            for cid, no, name in rows:
                c.execute(
                    """INSERT INTO naver_auto_account (customer_id, ad_account_no, account_name, present,
                           first_seen_on, last_seen_on, absent_days, last_absent_on)
                       VALUES (?, ?, ?, 1, ?, ?, 0, NULL)
                       ON CONFLICT (customer_id) DO UPDATE SET
                           ad_account_no = excluded.ad_account_no, account_name = excluded.account_name,
                           present = 1, last_seen_on = excluded.last_seen_on, absent_days = 0, last_absent_on = NULL""",
                    (cid, no, name, d, d))
            now_absent = 0
            seen = {r[0] for r in rows}
            for cid in sorted(before - seen):
                cur = c.execute(
                    """UPDATE naver_auto_account SET present = 0, absent_days = absent_days + 1, last_absent_on = ?
                       WHERE customer_id = ? AND (last_absent_on IS NULL OR last_absent_on < ?)""", (d, cid, d))
                now_absent += cur.rowcount
            self._set_meta(c, "accounts_synced_on", d)
        return SyncCounts(len(rows), len(seen - before), now_absent)

    # ── 사람의 짝 판단 ──
    def record_decision(self, possibility_id: int, customer_id: int, decision: str, decided_by: int,
                        at: datetime) -> int:
        """짝 확인 화면의 판단 한 줄을 쌓는다(같은 짝에 다시 판단하면 새 줄 — 가장 늦은 줄이 이긴다)."""
        self._need_writer()
        if decision not in DECISIONS:
            raise StoreRefused("판단은 confirmed · rejected 뿐입니다")
        vals = (_pos_int(possibility_id, "가망 번호"), _pos_int(customer_id, "고객 번호"), decision,
                _person(decided_by, "판단한 직원"), _kst_text(at, "판단 시각"))
        with self._tx() as c:
            cur = c.execute(
                """INSERT INTO naver_auto_link_decision (possibility_id, customer_id, decision, decided_by, decided_at)
                   VALUES (?, ?, ?, ?, ?)""", vals)
            return cur.lastrowid

    def revoke_decision(self, decision_id: int, revoked_by: int, at: datetime, reason: str) -> None:
        """판단을 거둔다 — 줄은 남기고 거둔 사람·시각·사유만 채운다(한 번만)."""
        self._need_writer()
        vals = (_person(revoked_by, "거둔 직원"), _kst_text(at, "거둔 시각"), _opt_text(reason, "사유", 64),
                _pos_int(decision_id, "판단 번호"))
        if not vals[2]:
            raise StoreRefused("거두는 사유가 있어야 합니다")
        with self._tx() as c:
            cur = c.execute(
                """UPDATE naver_auto_link_decision SET revoked_by = ?, revoked_at = ?, revoke_reason = ?
                   WHERE decision_id = ? AND revoked_at IS NULL""", vals)
            if cur.rowcount != 1:
                raise StoreRefused("거둘 판단이 없거나 이미 거둔 판단입니다")

    def current_decisions(self) -> List[Tuple[int, int, str]]:
        """짝마다 가장 늦은 · 거두지 않은 판단 — (가망 번호, 고객 번호, 판단). 짝 규칙(matching)에 넘긴다."""
        rows = self._conn.execute(
            """SELECT d.possibility_id, d.customer_id, d.decision FROM naver_auto_link_decision d
               WHERE d.revoked_at IS NULL AND d.decision_id = (
                   SELECT MAX(x.decision_id) FROM naver_auto_link_decision x
                   WHERE x.possibility_id = d.possibility_id AND x.customer_id = d.customer_id
                     AND x.revoked_at IS NULL)
               ORDER BY d.possibility_id, d.customer_id""").fetchall()
        return [(int(p), int(c), str(dec)) for p, c, dec in rows]

    # ── 아침 점검 회차 ──
    def begin_run(self, run_date: date, started_at: datetime) -> int:
        self._need_writer()
        d, t = _day_text(run_date, "점검 날짜"), _kst_text(started_at, "시작 시각")
        if t[:10] != d:
            raise StoreRefused("점검 날짜와 시작 시각의 한국 날짜가 다릅니다")
        with self._tx() as c:
            if c.execute("SELECT 1 FROM naver_auto_check_run WHERE run_date = ? AND status = 'running'", (d,)).fetchone():
                raise StoreRefused("같은 날 회차가 아직 돌고 있습니다")
            return c.execute("INSERT INTO naver_auto_check_run (run_date, started_at, status) VALUES (?, ?, 'running')",
                             (d, t)).lastrowid

    def finish_run(self, run_id: int, status: str, finished_at: datetime, accounts_total: Optional[int] = None,
                   accounts_ok: Optional[int] = None, error_kind: Optional[str] = None) -> None:
        self._need_writer()
        if status not in RUN_END_STATUSES:
            raise StoreRefused("회차는 done · failed 로만 끝납니다")
        for v in (accounts_total, accounts_ok):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                raise StoreRefused("계정 수는 0 이상 정수여야 합니다")
        vals = (status, _kst_text(finished_at, "끝난 시각"), accounts_total, accounts_ok,
                _opt_text(error_kind, "오류 종류", 64), _pos_int(run_id, "회차 번호"))
        with self._tx() as c:
            cur = c.execute(
                """UPDATE naver_auto_check_run SET status = ?, finished_at = ?, accounts_total = ?, accounts_ok = ?,
                       error_kind = ? WHERE run_id = ? AND status = 'running'""", vals)
            if cur.rowcount != 1:
                raise StoreRefused("돌고 있는 회차가 아닙니다")

    def _running_run_date(self, c, run_id: int) -> str:
        row = c.execute("SELECT run_date FROM naver_auto_check_run WHERE run_id = ? AND status = 'running'",
                        (run_id,)).fetchone()
        if row is None:
            raise StoreRefused("돌고 있는 회차가 아닙니다")   # 끝난 회차에는 더 적지 않는다
        return row[0]

    # ── 계정 하루치 ──
    def record_account_day(self, run_id: int, customer_id: int, *, status: str, rules_run: Sequence[str],
                           rules_not_run: Sequence[Tuple[str, str]], checked_at: datetime,
                           possibility_id: Optional[int] = None, link: Optional[str] = None,
                           bizmoney=None, budget_lock=None, refund_lock=None,
                           yday_spend=None, yday_imp=None, yday_clk=None, data_late=None) -> None:
        """그날(회차 날짜) 계정 한 곳의 점검 결과 — 같은 날 다시 적으면 고친다."""
        self._need_writer()
        if status not in ACCOUNT_STATUSES:
            raise StoreRefused("모르는 점검 상태")
        if link is not None and link not in LINKS:
            raise StoreRefused("모르는 짝 상태")
        vals = [_pos_int(customer_id, "고객 번호"), None, _opt_pos_int(possibility_id, "가망 번호"), link,
                _pos_int(run_id, "회차 번호"), status, _codes(rules_run, "돌린 규칙"),
                _codes(rules_not_run, "못 돌린 규칙"), _num(bizmoney, "비즈머니"), _opt_bool(budget_lock, "잠금"),
                _opt_bool(refund_lock, "잠금"), _num(yday_spend, "어제 비용"), _num(yday_imp, "어제 노출"),
                _num(yday_clk, "어제 클릭"), _opt_bool(data_late, "자료 늦음"), _kst_text(checked_at, "점검 시각")]
        with self._tx() as c:
            vals[1] = self._running_run_date(c, run_id)
            c.execute(
                """INSERT INTO naver_auto_account_day (customer_id, day, possibility_id, link, run_id, status, rules_run,
                       rules_not_run, bizmoney, budget_lock, refund_lock, yday_spend, yday_imp, yday_clk, data_late,
                       checked_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (customer_id, day) DO UPDATE SET
                       possibility_id = excluded.possibility_id, link = excluded.link, run_id = excluded.run_id,
                       status = excluded.status, rules_run = excluded.rules_run, rules_not_run = excluded.rules_not_run,
                       bizmoney = excluded.bizmoney, budget_lock = excluded.budget_lock,
                       refund_lock = excluded.refund_lock, yday_spend = excluded.yday_spend,
                       yday_imp = excluded.yday_imp, yday_clk = excluded.yday_clk, data_late = excluded.data_late,
                       checked_at = excluded.checked_at""", vals)

    # ── 캠페인 하루치 ──
    def record_campaign_days(self, customer_id: int, day: date, campaigns: Iterable[Mapping],
                             stats: Mapping[str, Mapping[str, Optional[float]]], *, provisional: bool,
                             read_at: datetime) -> int:
        """계정 한 곳의 그날(통계 날짜) 캠페인 줄 — 캠페인 정보는 ``fields.CAMPAIGN`` 남길 칸에서 넷만,
        숫자는 ``stats[캠페인 번호]`` 의 원래 숫자 7개만. 통계 줄이 없는 캠페인은 숫자를 모름(NULL)으로 둔다."""
        self._need_writer()
        cid, d = _pos_int(customer_id, "고객 번호"), _day_text(day, "날짜")
        if type(provisional) is not bool:
            raise StoreRefused("잠정 여부는 참/거짓이어야 합니다")
        t = _kst_text(read_at, "읽은 시각")
        if not isinstance(stats, Mapping):
            raise StoreRefused("통계 모양이 아닙니다")
        rows = []
        seen = set()
        for camp in campaigns:
            if not isinstance(camp, Mapping):
                raise StoreRefused("캠페인 줄 모양이 아닙니다")
            k = F.keep(camp, F.CAMPAIGN)
            ccid = k.get("nccCampaignId")
            if not isinstance(ccid, str) or not N._CAMPAIGN_ID.fullmatch(ccid) or ccid in seen:
                raise StoreRefused("캠페인 번호가 아니거나 겹칩니다")
            if k.get("customerId") != cid:
                raise StoreRefused("캠페인 줄의 고객 번호가 맞지 않습니다")
            seen.add(ccid)
            st = stats.get(ccid)
            if st is not None and not isinstance(st, Mapping):
                raise StoreRefused("통계 줄 모양이 아닙니다")
            metrics = [None if st is None else _num(st.get(src), "지표") for src, _ in CAMPAIGN_METRICS]
            rows.append([ccid, d, cid, _opt_text(k.get("campaignTp"), "캠페인 종류", 40),
                         _opt_text(k.get("status"), "상태", 40), _opt_text(k.get("statusReason"), "사유", 80),
                         _num(k.get("dailyBudget"), "하루 예산"), *metrics, int(provisional), t])
        if set(stats) - seen:
            raise StoreRefused("캠페인 목록에 없는 통계 줄이 있습니다")   # 다른 계정 숫자가 섞이지 않게
        cols = ", ".join(c for _, c in CAMPAIGN_METRICS)
        sets = ", ".join(f"{c} = excluded.{c}" for _, c in CAMPAIGN_METRICS)
        with self._tx() as c:
            for r in rows:
                own = c.execute("SELECT customer_id FROM naver_auto_campaign_day WHERE campaign_id = ? LIMIT 1",
                                (r[0],)).fetchone()
                if own is not None and own[0] != cid:
                    raise StoreRefused("다른 계정의 캠페인 번호입니다")
                c.execute(
                    f"""INSERT INTO naver_auto_campaign_day (campaign_id, day, customer_id, campaign_tp, status,
                            status_reason, daily_budget, {cols}, provisional, read_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (campaign_id, day) DO UPDATE SET
                            campaign_tp = excluded.campaign_tp, status = excluded.status,
                            status_reason = excluded.status_reason, daily_budget = excluded.daily_budget, {sets},
                            provisional = excluded.provisional, read_at = excluded.read_at""", r)
        return len(rows)

    # ── 읽기 ──
    def meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM naver_auto_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def _get_meta(self, c, key: str) -> Optional[str]:
        row = c.execute("SELECT value FROM naver_auto_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def _set_meta(self, c, key: str, value: str) -> None:
        c.execute("""INSERT INTO naver_auto_meta (key, value) VALUES (?, ?)
                     ON CONFLICT (key) DO UPDATE SET value = excluded.value""", (key, value))

    def prospects(self) -> List[dict]:
        cur = self._conn.execute(
            """SELECT possibility_id, name, stage_key, latest_end_date, end_unreadable, stage_conflict, present,
                      first_seen_at, last_seen_at, stage_synced_at, absent_since
               FROM naver_auto_prospect ORDER BY possibility_id""")
        return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    def accounts(self) -> List[dict]:
        cur = self._conn.execute(
            """SELECT customer_id, ad_account_no, account_name, present, first_seen_on, last_seen_on, absent_days,
                      last_absent_on FROM naver_auto_account ORDER BY customer_id""")
        return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    def account_day(self, customer_id: int, day: date) -> Optional[dict]:
        cur = self._conn.execute("SELECT * FROM naver_auto_account_day WHERE customer_id = ? AND day = ?",
                                 (_pos_int(customer_id, "고객 번호"), _day_text(day, "날짜")))
        r = cur.fetchone()
        if r is None:
            return None
        out = dict(zip([d[0] for d in cur.description], r))
        out["rules_run"] = json.loads(out["rules_run"])
        out["rules_not_run"] = [tuple(x) for x in json.loads(out["rules_not_run"])]
        return out

    def campaign_days(self, customer_id: int, since: date, until: date) -> List[dict]:
        cur = self._conn.execute(
            """SELECT * FROM naver_auto_campaign_day WHERE customer_id = ? AND day BETWEEN ? AND ?
               ORDER BY day, campaign_id""",
            (_pos_int(customer_id, "고객 번호"), _day_text(since, "시작 날짜"), _day_text(until, "끝 날짜")))
        return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    def run(self, run_id: int) -> Optional[dict]:
        cur = self._conn.execute("SELECT * FROM naver_auto_check_run WHERE run_id = ?", (_pos_int(run_id, "회차 번호"),))
        r = cur.fetchone()
        return None if r is None else dict(zip([d[0] for d in cur.description], r))
