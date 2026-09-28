"""엔진 저장소 — 엔진 전용 파일 하나 · 쓰는 곳 하나 (설계 v1.8 S6 · 대표 결정 D10 · 반박 H8 · H9 · H10).

지키는 것
- **지우지 않는다.** 고치기·더하기(upsert)만 한다. 목록에서 빠진 것은 「현재 목록에 없음」 표시만 바꾼다(반박 H8 —
  가망 표를 통째로 바꾸다 확인한 짝·이슈가 연쇄로 사라지는 길을 막는다). DB 연결 자체가 지우기 · 표/색인/보기/방아쇠
  버리기 · 표 고치기(ALTER — 칸 버리기·이름 바꾸기) · 방아쇠·보기 만들기 · 다른 DB 붙이기 · 허용 목록 밖 PRAGMA 를
  거절한다(``_authorizer``). 연결이 못 막는 「바꿔 넣기(REPLACE)」와 ALTER 글자는 시험이 코드 글자로 막는다.
  외래 키·연쇄 삭제도 쓰지 않는다. 오래된 줄 정리(2년 보관)는 나중에 **따로 여는 길**로만 만든다.
- **전부 받은 목록만 받는다.** 전산 단계는 ``erp_read.StageSnapshot``, 네이버 연결 목록은 ``naver_read.ChildAccounts``
  — 둘 다 「전부 받았을 때만 만들어지는」 모양이다(반박 H1). 일부만 받은 목록으로 「목록에 없음」을 찍지 않고,
  빈 목록으로 전부를 빼지도 않는다.
- **남길 칸만.** 네이버 계정 줄은 ``fields.CHILD_ACCOUNT`` 중 세 칸만 쓴다 — 계정책임자 아이디(``ownerNaverId``) 같은
  칸은 들어와도 저장되지 않는다(반박 H10). 키·비밀값은 이 파일로 오지 않는다. 규칙·사유·오류 종류 칸은 **코드 모양만**
  받는다(오류 문구·주소가 영구 저장되지 않게).
- **모름 ≠ 0.** 빈 값은 NULL 로 두고 0 으로 채우지 않는다. 숫자가 아닌 값·NaN·무한은 거절한다(0 으로 바뀌지 않게).
  통계 줄이 없는 캠페인은 알던 숫자를 모름으로 덮지 않는다.
- **쓰는 곳 하나.** 쓰기용으로 열면 **저장 파일 자체(inode)** 에 독점 잠금을 건다 — 다른 이름·하드링크로 열어도 두 번째
  쓰기는 바로 ``StoreBusy``. 잠금을 쥐면 살아 있는 다른 회차가 있을 수 없으므로 「돌고 있음」으로 남은 회차는 도중에
  죽은 것이다 → 연 때 「실패(orphaned)」로 닫는다. 읽기용은 읽기 전용으로 열고, 연결도 쓰기를 거절한다.
- **파일은 우리만.** 권한 600(이미 있던 파일 · -wal · -shm 도 고친다) · 우리 소유 일반 파일만 · 다른 사람이 쓸 수 있는
  폴더는 거절 · 엔진 코드 폴더 안에는 만들지 않는다(반박 H9 — 코드를 보낼 때 덮이지 않게).
- **시각은 한국 시각으로 적는다**(③ 기존 표의 UTC 와 섞지 않는다 · 마이크로초까지). 날짜 칸은 ``date`` 만 받는다.
  **미래 시각은 거절한다**(한 번 들어가면 그 시각까지 동기화가 막힌다) — 시계는 부르는 쪽이 넣을 수 있다.
- 오류 문구에는 값(번호·이름·금액·경로)을 넣지 않는다. 파일·DB 오류도 종류 이름만 남긴 ``StoreError`` 로 바꾼다.

- **목록이 한꺼번에 크게 줄면 멈춘다(S7 브레이크).** 가망·계정을 「목록에 없음」으로 찍기 전에, 이번에 새로 빠질 줄이
  ``BRAKE_MIN_ROWS`` 줄 이상이고 직전에 있던 줄의 ``BRAKE_DROP_RATIO`` 를 넘으면(계정은 관리계정 수가 줄고 빠질 줄이
  있어도) 아무것도 적지 않고 ``SyncBraked`` 를 던진다 — 잘린 응답 하나로 광고주 수백 곳이 「관리 대상 아님」이 되지
  않게. 정상적인 큰 변화는 대표가 확인한 뒤 ``allow_drop_by`` 로 받는다(누가 받았는지 동기화 기록에 남는다).
- **조직 스냅숏은 수락본 하나만 남긴다(S7 · M12).** 건전성 검사를 통과한 것만 ``record_org`` 로 들어오고, 엔진이 다시
  켜져도 이 수락본이 다음 검사의 「이전 조직」이 된다. 남길 칸만(``fields.ORG_*``) · 더 새 스냅숏만.
- **동기화마다 한 줄 남긴다(S7).** 받음 · 버림 · 멈춤(브레이크) · 실패 — 종류 코드와 개수만(번호·이름 없음).

엔진이 부르는 순서(S7~S9): 1시간마다 ``sync.sync_org`` → 6시간마다 ``sync.sync_stages``(``record_prospects``) →
하루 한 번 ``record_accounts`` → ``begin_run`` → 계정마다 ``record_account_day`` · ``record_campaign_days`` →
``finish_run``. 이슈 표는 S9 에서 더한다.
"""
from __future__ import annotations

import fcntl as _fcntl
import json
import math
import os
import pathlib
import re
import sqlite3 as _sqlite3
import stat as _stat
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import erp_read as E
from . import fields as F
from . import naver_read as N

__all__ = ("open_writer", "open_reader", "Store", "StoreError", "StoreBusy", "StoreRefused", "SyncBraked",
           "SyncCounts")

KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 2   # 2 = S7(조직 수락본 · 동기화 기록) — 옛 판(1) 파일은 열 때 표를 더하고 판 번호를 올린다
BUSY_TIMEOUT_MS = 5000
FUTURE_SLACK = timedelta(minutes=5)   # 시계가 조금 어긋나도 받는다 · 그보다 앞선 시각은 거절
ORG_FUTURE_SLACK = timedelta(minutes=10)   # ① 스냅숏 시각 — app.naver_auto.org_snapshot.FUTURE_TOLERANCE 와 같다(시험이 대조)

# 목록 급감 브레이크(S7) — 새로 빠질 줄이 BRAKE_MIN_ROWS 이상이고 직전에 있던 줄의 20% 를 넘으면 멈춘다.
# 20% 는 erp_read.StageSnapshot.plausible() 의 허용 폭과 같다(시험이 대조).
BRAKE_DROP_RATIO = 0.20
BRAKE_MIN_ROWS = 10

SYNC_ORG, SYNC_STAGES, SYNC_ACCOUNTS = "org", "stages", "accounts"
SYNC_KINDS = frozenset({SYNC_ORG, SYNC_STAGES, SYNC_ACCOUNTS})
SYNC_ACCEPTED, SYNC_REFUSED, SYNC_BRAKED, SYNC_FAILED = "accepted", "refused", "braked", "failed"
SYNC_OUTCOMES = frozenset({SYNC_ACCEPTED, SYNC_REFUSED, SYNC_BRAKED, SYNC_FAILED})
_EXTERNAL_OUTCOMES = frozenset({SYNC_REFUSED, SYNC_FAILED})   # 받음·멈춤은 저장소만 적는다(가짜 「받음」으로 브레이크를 못 속이게)
MAX_SYNC_CODES = 20
ORG_MAX_ROWS = 100_000
_CODE_DIR = os.path.dirname(os.path.realpath(__file__))

# 점검 상태 — backend/app/naver_auto/verdict.py 의 CHECK_* 와 같은 글자(시험이 대조한다)
ACCOUNT_STATUSES = frozenset({
    "ok", "pending", "not_checked", "partial", "key_rejected", "data_late", "system_gap", "link_broken", "not_eligible",
})
LINKS = frozenset({"confirmed", "auto"})           # handles.LINK_* 와 같은 글자(시험이 대조한다)
DECISIONS = frozenset({"confirmed", "rejected"})   # backend/app/naver_auto/matching.py 의 DECISION_* 와 같은 글자
RUN_RUNNING, RUN_DONE, RUN_FAILED = "running", "done", "failed"
RUN_END_STATUSES = frozenset({RUN_DONE, RUN_FAILED})
ORPHANED = "orphaned"

# 코드 모양 — 규칙 이름(checks.ALL_RULES) · 사유(checks 의 "stats-unread" 등) · 오류 종류(naver_read.KIND_* · erp 종류)
_RULE_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_REASON_CODE = re.compile(r"[a-z0-9][a-z0-9_]*(?:-[a-z0-9_]+)*")
_ERROR_KIND = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{0,39}")

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
    # 캠페인 × 날짜 — 더할 수 있는 원래 숫자 7개 + 상태·사유·하루 예산 · 잠정(L8)·읽은 시각 · 숫자를 읽었는지
    """CREATE TABLE IF NOT EXISTS naver_auto_campaign_day (
        campaign_id TEXT NOT NULL,
        day TEXT NOT NULL,
        customer_id INTEGER NOT NULL CHECK (customer_id > 0),
        run_id INTEGER NOT NULL,
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
        metrics_read INTEGER NOT NULL CHECK (metrics_read IN (0, 1)),
        provisional INTEGER NOT NULL CHECK (provisional IN (0, 1)),
        read_at TEXT NOT NULL,
        PRIMARY KEY (campaign_id, day))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_campaign_day_customer
        ON naver_auto_campaign_day (customer_id, day)""",
    # ① 조직 스냅숏 수락본 — 한 줄(가장 최근에 받은 것)만 · 남길 칸만(S7 · M12)
    """CREATE TABLE IF NOT EXISTS naver_auto_org (
        slot TEXT PRIMARY KEY CHECK (slot = 'current'),
        generated_at TEXT NOT NULL,
        received_at TEXT NOT NULL,
        accepted_at TEXT NOT NULL,
        confirmed_by INTEGER CHECK (confirmed_by IS NULL OR confirmed_by >= 0),
        body TEXT NOT NULL)""",
    # 동기화 기록 — 쌓기만 · 종류 코드와 개수만(S7)
    """CREATE TABLE IF NOT EXISTS naver_auto_sync_log (
        sync_id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL CHECK (kind IN ('org', 'stages', 'accounts')),
        at TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'refused', 'braked', 'failed')),
        codes TEXT NOT NULL,
        row_count INTEGER CHECK (row_count IS NULL OR row_count >= 0),
        manager_count INTEGER CHECK (manager_count IS NULL OR manager_count >= 0),
        absent_count INTEGER CHECK (absent_count IS NULL OR absent_count >= 0),
        detail TEXT,
        confirmed_by INTEGER CHECK (confirmed_by IS NULL OR confirmed_by >= 0))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_sync_log_kind
        ON naver_auto_sync_log (kind, sync_id)""",
)

# ── 연결 거절 규칙 ────────────────────────────────────────────────
_A = _sqlite3
_DDL = frozenset({
    _A.SQLITE_CREATE_TABLE, _A.SQLITE_CREATE_INDEX, _A.SQLITE_CREATE_VIEW, _A.SQLITE_CREATE_TRIGGER,
    _A.SQLITE_CREATE_TEMP_TABLE, _A.SQLITE_CREATE_TEMP_INDEX, _A.SQLITE_CREATE_TEMP_VIEW, _A.SQLITE_CREATE_TEMP_TRIGGER,
    _A.SQLITE_CREATE_VTABLE,
})
_DENY_ALWAYS = frozenset({
    _A.SQLITE_DELETE, _A.SQLITE_DROP_TABLE, _A.SQLITE_DROP_INDEX, _A.SQLITE_DROP_VIEW, _A.SQLITE_DROP_TRIGGER,
    _A.SQLITE_DROP_TEMP_TABLE, _A.SQLITE_DROP_TEMP_INDEX, _A.SQLITE_DROP_TEMP_VIEW, _A.SQLITE_DROP_TEMP_TRIGGER,
    _A.SQLITE_DROP_VTABLE, _A.SQLITE_ATTACH, _A.SQLITE_DETACH,
    _A.SQLITE_CREATE_VIEW, _A.SQLITE_CREATE_TRIGGER, _A.SQLITE_CREATE_TEMP_VIEW, _A.SQLITE_CREATE_TEMP_TRIGGER,
    _A.SQLITE_CREATE_VTABLE,
})
_WRITES = frozenset({_A.SQLITE_INSERT, _A.SQLITE_UPDATE})
# 표 고치기(ALTER)는 이관 단계에서만 — 그때도 칸 버리기·이름 바꾸기는 SQLite 가 안에서 부르는 함수 단계에서 거절한다
# (ADD COLUMN 은 이 함수들을 부르지 않는다). 확장 불러오기도 거절.
_DENY_FUNCTIONS = frozenset({"sqlite_drop_column", "sqlite_rename_table", "sqlite_rename_column", "sqlite_rename_test",
                             "sqlite_rename_quotefix", "load_extension"})
# 읽기만 하는 PRAGMA — 값을 바꾸는 꼴(PRAGMA x = y)은 거절한다. 설정은 거절 규칙을 걸기 전에 끝낸다.
_PRAGMA_READ_OK = frozenset({"table_info", "database_list", "integrity_check", "quick_check", "journal_mode",
                             "user_version", "page_count", "synchronous"})
_PRAGMA_WRITER_OK = frozenset({"wal_checkpoint"})   # WAL 을 본 파일로 옮기기만 한다(자료는 그대로)

PHASE_MIGRATE, PHASE_RUN, PHASE_READ = "migrate", "run", "read"


def _authorizer(phase: str):
    """``migrate`` = 표·색인 만들기까지 · ``run`` = 쓰기(더하기·고치기)만 · ``read`` = 읽기만."""
    def check(action, arg1, arg2, dbname, source):
        if action in _DENY_ALWAYS:
            return _A.SQLITE_DENY
        if action == _A.SQLITE_FUNCTION:
            return _A.SQLITE_DENY if (arg2 or "").lower() in _DENY_FUNCTIONS else _A.SQLITE_OK
        if action == _A.SQLITE_ALTER_TABLE:
            return _A.SQLITE_OK if phase == PHASE_MIGRATE else _A.SQLITE_DENY
        if action in _DDL:
            return _A.SQLITE_OK if phase == PHASE_MIGRATE else _A.SQLITE_DENY
        if action in _WRITES:
            return _A.SQLITE_DENY if phase == PHASE_READ else _A.SQLITE_OK
        if action == _A.SQLITE_PRAGMA:
            name = (arg1 or "").lower()
            if name in _PRAGMA_READ_OK and (arg2 is None or name == "table_info"):
                return _A.SQLITE_OK
            if phase != PHASE_READ and name in _PRAGMA_WRITER_OK:
                return _A.SQLITE_OK
            return _A.SQLITE_DENY
        return _A.SQLITE_OK
    return check


class StoreError(RuntimeError):
    """저장소가 거절했거나 실패했다. 문구에 값(번호·이름·금액·경로)을 넣지 않는다."""


class StoreBusy(StoreError):
    """다른 곳이 이미 쓰기용으로 열었다(쓰는 곳 하나)."""


class StoreRefused(StoreError):
    """이 자리·이 모양으로는 받지 않는다."""


class SyncBraked(StoreRefused):
    """목록이 한꺼번에 크게 줄어 「목록에 없음」을 찍기 전에 멈췄다 — 아무것도 적지 않았다(개수만 싣는다)."""

    def __init__(self, kind: str, present_before: int, would_absent: int,
                 managers_before: Optional[int] = None, managers_now: Optional[int] = None) -> None:
        self.kind, self.present_before, self.would_absent = kind, present_before, would_absent
        self.managers_before, self.managers_now = managers_before, managers_now
        super().__init__(f"목록 급감 — 멈춤({kind}): 있던 {present_before} 중 {would_absent} 이 빠질 뻔했습니다")


def _braked(present_before: int, would_absent: int) -> bool:
    """새로 빠질 줄이 BRAKE_MIN_ROWS 이상이고 직전에 있던 줄의 BRAKE_DROP_RATIO 를 **넘으면**(같으면 받는다)."""
    return would_absent >= BRAKE_MIN_ROWS and would_absent > present_before * BRAKE_DROP_RATIO


@dataclass(frozen=True)
class SyncCounts:
    present: int     # 이번 목록에 있는 수
    new: int         # 처음 본 수
    now_absent: int  # 이번에 처음 「목록에 없음」이 된 수(이미 빠져 있던 것은 세지 않는다)

    def __repr__(self) -> str:
        return f"SyncCounts(present={self.present}, new={self.new}, now_absent={self.now_absent})"


# ── 값 검사(값은 문구에 넣지 않는다) ──────────────────────────────────
def _kst_text(t: datetime, what: str) -> str:
    if not isinstance(t, datetime) or t.tzinfo is None:
        raise StoreRefused(f"{what}: 시간대가 있는 시각이어야 합니다")
    return t.astimezone(KST).isoformat(timespec="microseconds")   # 같은 초 안의 앞뒤도 가른다


def _day_text(d, what: str) -> str:
    if type(d) is not date:   # 시각(datetime)은 날짜가 아니다
        raise StoreRefused(f"{what}: 날짜(date)여야 합니다")
    return d.isoformat()


def _pos_int(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 2 ** 63:
        raise StoreRefused(f"{what}: 양의 정수여야 합니다")
    return v


def _opt_pos_int(v, what: str) -> Optional[int]:
    return None if v is None else _pos_int(v, what)


def _person(v, what: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < 2 ** 63:   # 대표 = 0번(설계 v1.6)
        raise StoreRefused(f"{what}: 직원 번호는 0 이상 정수여야 합니다")
    return v


def _num(v, what: str) -> Optional[float]:
    """숫자 또는 모름(None). NaN·무한·참거짓·글자는 거절 — 조용히 0 이나 NULL 로 바뀌지 않게."""
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise StoreRefused(f"{what}: 숫자가 아닙니다")
    try:
        f = float(v)
    except OverflowError:
        raise StoreRefused(f"{what}: 숫자가 너무 큽니다") from None
    if not math.isfinite(f):
        raise StoreRefused(f"{what}: 숫자가 아닙니다")
    return f


def _opt_bool(v, what: str) -> Optional[int]:
    if v is None:
        return None
    if type(v) is not bool:
        raise StoreRefused(f"{what}: 참/거짓이어야 합니다")
    return int(v)


def _opt_text(v, what: str, limit: int = 200) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str) or len(v) > limit or "\x00" in v:
        raise StoreRefused(f"{what}: 글자가 아니거나 너무 깁니다")
    return v


def _code(v, pattern, what: str) -> str:
    if not isinstance(v, str) or not pattern.fullmatch(v):
        raise StoreRefused(f"{what}: 코드 모양이 아닙니다")
    return v


def _seq(v, what: str) -> list:
    """목록·튜플만 — 글자 하나를 글자 목록으로 받지 않는다."""
    if isinstance(v, (str, bytes, bytearray, Mapping)) or not isinstance(v, (list, tuple)):
        raise StoreRefused(f"{what}: 목록이어야 합니다")
    return list(v)


def _rules(rules_run, rules_not_run) -> Tuple[str, str]:
    ran = [_code(r, _RULE_CODE, "돌린 규칙") for r in _seq(rules_run, "돌린 규칙")]
    pairs = []
    for p in _seq(rules_not_run, "못 돌린 규칙"):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise StoreRefused("못 돌린 규칙: (규칙, 사유) 쌍이어야 합니다")
        pairs.append([_code(p[0], _RULE_CODE, "못 돌린 규칙"), _code(p[1], _REASON_CODE, "사유")])
    names = ran + [p[0] for p in pairs]
    if len(set(names)) != len(names):
        raise StoreRefused("같은 규칙이 두 번 적혔습니다")   # 돌림과 못 돌림에 동시에 있을 수 없다
    return json.dumps(ran), json.dumps(pairs)


def _codes(codes) -> list:
    """코드 모양 글자 목록 — 겹치면 한 번 · 최대 MAX_SYNC_CODES 개(오류 문구·번호가 기록에 남지 않게)."""
    out = []
    for x in _seq(codes, "코드"):
        x = _code(x, _ERROR_KIND, "코드")
        if x not in out:
            out.append(x)
    if len(out) > MAX_SYNC_CODES:
        raise StoreRefused("코드가 너무 많습니다")
    return out


def _count(v, what: str) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < 2 ** 31:
        raise StoreRefused(f"{what}: 0 이상 정수여야 합니다")
    return v


def _spelling_counts(per) -> dict:
    """단계 표기 → 받은 줄 수(표기는 erp_read.STAGE_SPELLINGS 의 글자만) — 어느 표기가 0 인지 나중에 보려고 남긴다."""
    if not isinstance(per, Mapping):
        raise StoreRefused("표기별 줄 수 모양이 아닙니다")
    known = {sp for v in E.STAGE_SPELLINGS.values() for sp in v}
    out = {}
    for k, v in per.items():
        if k not in known:
            raise StoreRefused("모르는 단계 표기입니다")
        out[k] = _count(v, "표기별 줄 수")
    return out


def _org_value(v, what: str):
    """조직 칸 값 — 글자(200자 이하) · 정수 · 참거짓 · 빈 값만(안에 다른 구조를 숨겨 들이지 않게)."""
    if v is None or type(v) is bool:
        return v
    if isinstance(v, int):
        if not -2 ** 63 <= v < 2 ** 63:
            raise StoreRefused(f"{what}: 정수가 너무 큽니다")
        return v
    if isinstance(v, str):
        return _opt_text(v, what)
    raise StoreRefused(f"{what}: 글자·정수·참거짓·빈 값만 받습니다")


# ── 열기 ─────────────────────────────────────────────────────────────
def _check_path(path) -> str:
    if not isinstance(path, str) or not path or path == ":memory:" or "\x00" in path or not os.path.isabs(path):
        raise StoreRefused("저장 파일은 절대 경로여야 합니다")
    real = os.path.realpath(path)
    if os.path.commonpath([real, _CODE_DIR]) == _CODE_DIR:
        raise StoreRefused("저장 파일을 엔진 코드 폴더 안에 둘 수 없습니다")   # 코드를 보낼 때 덮이지 않게(반박 H9)
    return real


def _check_dir(real: str) -> None:
    st = os.stat(os.path.dirname(real))
    if st.st_mode & 0o022 and not st.st_mode & _stat.S_ISVTX:
        raise StoreRefused("다른 사람이 쓸 수 있는 폴더에는 두지 않습니다")   # 저장 파일 옆 -wal·-shm 을 남이 심지 못하게


def _own_file(fd: int, what: str) -> None:
    st = os.fstat(fd)
    if not _stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid():
        raise StoreRefused(f"{what}: 우리 소유 일반 파일이 아닙니다")
    if st.st_nlink != 1:
        raise StoreRefused(f"{what}: 다른 이름(하드링크)이 있는 파일은 쓰지 않습니다")   # 두 이름 = 두 쓰기
    if st.st_mode & 0o077:
        os.fchmod(fd, 0o600)


def _fix_side_files(real: str) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        p = real + suffix
        try:
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue
        try:
            _own_file(fd, "곁 파일")
        finally:
            os.close(fd)


def _wrap(e: BaseException, what: str) -> StoreError:
    return StoreError(f"{what}: {type(e).__name__}")   # 경로·값이 든 원래 문구는 싣지 않는다


def open_writer(path: str, clock: Optional[Callable[[], datetime]] = None) -> "Store":
    """쓰기용으로 연다 — 잠금을 못 잡으면 바로 ``StoreBusy``(기다리지 않는다)."""
    real = _check_path(path)
    try:
        _check_dir(real)
        lock_fd = os.open(real, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)   # 우리만 읽고 쓰는 파일
    except StoreError:
        raise
    except OSError as e:
        raise _wrap(e, "저장 파일을 열지 못했습니다") from None
    conn = None
    try:
        try:
            _fcntl.flock(lock_fd, _fcntl.LOCK_EX | _fcntl.LOCK_NB)   # 이름이 아니라 파일 자체에 건다
        except OSError:
            raise StoreBusy("다른 곳이 이미 쓰기용으로 열었습니다") from None
        _own_file(lock_fd, "저장 파일")
        _fix_side_files(real)
        conn = _sqlite3.connect(real, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA trusted_schema = OFF")
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise StoreError("WAL 로 열지 못했습니다")
        conn.execute("PRAGMA synchronous = FULL")   # 사람의 짝 판단이 「저장됨」 뒤 전원이 꺼져도 남게
        if hasattr(conn, "setconfig"):
            conn.setconfig(_sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)   # 스키마 직접 고치기 막음
        _fix_side_files(real)
        store = Store(conn, real, lock_fd, writer=True, clock=clock)
        store._migrate()
        conn.set_authorizer(_authorizer(PHASE_RUN))
        store._close_orphaned_runs()
        return store
    except BaseException as e:
        if conn is not None:
            conn.close()   # SQLite 연결을 먼저 닫고 우리 fd 를 닫는다(반대면 SQLite 의 잠금이 풀린다)
        os.close(lock_fd)
        if isinstance(e, (StoreError, KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(e, (OSError, _sqlite3.Error, ValueError)):
            raise _wrap(e, "저장 파일을 열지 못했습니다") from None
        raise


def open_reader(path: str) -> "Store":
    """읽기 전용으로 연다(웹 API 등) — 연결이 쓰기를 거절한다. 경로는 URI 로 이스케이프한다(``?``·``#``·``%``)."""
    real = _check_path(path)
    if not os.path.isfile(real):
        raise StoreError("저장 파일이 아직 없습니다")
    uri = pathlib.Path(real).as_uri() + "?mode=ro"
    try:
        conn = _sqlite3.connect(uri, uri=True, isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA trusted_schema = OFF")
        conn.set_authorizer(_authorizer(PHASE_READ))
        opened = [r[2] for r in conn.execute("PRAGMA database_list").fetchall() if r[1] == "main"]
    except _sqlite3.Error as e:
        raise _wrap(e, "저장 파일을 읽기용으로 열지 못했습니다") from None
    if opened != [real]:
        conn.close()
        raise StoreRefused("검사한 파일과 다른 파일이 열렸습니다")
    return Store(conn, real, None, writer=False)


# ── 저장소 ───────────────────────────────────────────────────────────
class Store:
    def __init__(self, conn, path: str, lock_fd: Optional[int], writer: bool,
                 clock: Optional[Callable[[], datetime]] = None) -> None:
        self._conn = conn
        self._path = path
        self._lock_fd = lock_fd
        self.writer = writer
        self._clock = clock or (lambda: datetime.now(KST))
        self._my_runs = set()
        self.orphaned_runs = 0

    def __repr__(self) -> str:   # 경로·값을 보이지 않는다
        return f"Store(writer={self.writer})"

    def close(self) -> None:
        try:
            self._conn.close()
        finally:
            if self._lock_fd is not None:
                fd, self._lock_fd = self._lock_fd, None
                os.close(fd)   # 연결을 닫은 뒤에 — 잠금도 함께 풀린다

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 내부 ──
    def _need_writer(self) -> None:
        if not self.writer:
            raise StoreRefused("읽기용으로 연 저장소입니다")

    def _now(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise StoreError("시계가 시간대 있는 시각을 주지 않습니다")
        return now

    def _not_future(self, t: datetime, what: str) -> None:
        if t > self._now() + FUTURE_SLACK:
            raise StoreRefused(f"{what}: 미래 시각은 받지 않습니다")

    def _tx(self):
        store = self

        class _Tx:
            def __enter__(self_inner):
                try:
                    store._conn.execute("BEGIN IMMEDIATE")
                except _sqlite3.Error as e:
                    raise _wrap(e, "저장을 시작하지 못했습니다") from None
                return store._conn

            def __exit__(self_inner, et, ev, tb):
                if et is None:
                    try:
                        store._conn.execute("COMMIT")
                        return False
                    except _sqlite3.Error as e:
                        et, ev = type(e), e
                if store._conn.in_transaction:   # SQLite 가 이미 되돌렸으면 다시 되돌리지 않는다(원래 오류를 가리지 않게)
                    try:
                        store._conn.execute("ROLLBACK")
                    except _sqlite3.Error:
                        pass
                if isinstance(ev, _sqlite3.Error):
                    raise _wrap(ev, "저장하지 못했습니다") from None
                return False
        return _Tx()

    def _migrate(self) -> None:
        self._conn.set_authorizer(_authorizer(PHASE_MIGRATE))
        with self._tx() as c:
            for sql in _SCHEMA:
                c.execute(sql)
            row = c.execute("SELECT value FROM naver_auto_meta WHERE key = 'schema_version'").fetchone()
            try:
                have = None if row is None else int(row[0])
            except (TypeError, ValueError):
                raise StoreError("저장 파일 판 번호를 읽지 못했습니다") from None
            if have is not None and have > SCHEMA_VERSION:
                raise StoreError("이 엔진보다 새 저장 파일입니다")   # 옛 엔진이 새 파일을 덮어쓰지 않게
            if have != SCHEMA_VERSION:   # 새 파일이거나 옛 판 — 이관을 마치면 판 번호를 올린다
                self._set_meta(c, "schema_version", str(SCHEMA_VERSION))

    def _close_orphaned_runs(self) -> None:
        """잠금을 쥔 지금 「돌고 있음」인 회차는 도중에 죽은 것 — 실패로 닫는다(그날 다시 돌릴 수 있게)."""
        now = _kst_text(self._now(), "지금")
        with self._tx() as c:
            cur = c.execute("""UPDATE naver_auto_check_run SET status = 'failed', finished_at = ?, error_kind = ?
                               WHERE status = 'running'""", (now, ORPHANED))
            self.orphaned_runs = cur.rowcount

    def _get_meta(self, c, key: str) -> Optional[str]:
        row = c.execute("SELECT value FROM naver_auto_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def _set_meta(self, c, key: str, value: str) -> None:
        c.execute("""INSERT INTO naver_auto_meta (key, value) VALUES (?, ?)
                     ON CONFLICT (key) DO UPDATE SET value = excluded.value""", (key, value))

    def _meta_time(self, c, key: str) -> Optional[datetime]:
        raw = self._get_meta(c, key)
        if raw is None:
            return None
        try:
            t = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            raise StoreError("저장된 동기화 시각을 읽지 못했습니다") from None
        if t.tzinfo is None:
            raise StoreError("저장된 동기화 시각에 시간대가 없습니다")
        return t

    # ── 동기화 기록(S7) ──
    def _log_sync(self, c, kind: str, at: str, outcome: str, codes: Sequence[str] = (), rows: Optional[int] = None,
                  managers: Optional[int] = None, absent: Optional[int] = None, detail: Optional[Mapping] = None,
                  confirmed_by: Optional[int] = None) -> int:
        cur = c.execute(
            """INSERT INTO naver_auto_sync_log (kind, at, outcome, codes, row_count, manager_count, absent_count, detail,
                   confirmed_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (kind, at, outcome, json.dumps(list(codes)), rows, managers, absent,
             None if detail is None else json.dumps(dict(detail), ensure_ascii=False, sort_keys=True), confirmed_by))
        return cur.lastrowid

    def _log_braked(self, kind: str, at: str, b: "SyncBraked", rows: int) -> None:
        with self._tx() as c:   # 본 저장은 이미 되돌렸다 — 멈춘 사실만 따로 남긴다
            self._log_sync(c, kind, at, SYNC_BRAKED, ("BRAKE",), rows=rows, managers=b.managers_now,
                           absent=b.would_absent)

    def record_sync_event(self, kind: str, outcome: str, codes: Sequence[str], at: datetime,
                          rows: Optional[int] = None) -> int:
        """버림(건전성 검사 · 첫 회차 대조) · 실패(① 읽기 오류)를 남긴다 — 받음·멈춤은 저장소가 스스로 적는다."""
        self._need_writer()
        if kind not in SYNC_KINDS:
            raise StoreRefused("동기화 종류가 아닙니다")
        if outcome not in _EXTERNAL_OUTCOMES:
            raise StoreRefused("밖에서 적을 수 있는 결과는 refused · failed 뿐입니다")
        vals = (_codes(codes), _kst_text(at, "동기화 시각"), _count(rows, "줄 수"))
        self._not_future(at, "동기화 시각")
        with self._tx() as c:
            return self._log_sync(c, kind, vals[1], outcome, vals[0], rows=vals[2])

    # ── ① 관리 단계 가망 ──
    def record_prospects(self, snap: "E.StageSnapshot", *, allow_drop_by: Optional[int] = None) -> SyncCounts:
        """전산 7단계를 전부 받은 결과로 가망 표를 고친다 — 없어진 가망은 지우지 않고 「목록에 없음」.

        한꺼번에 크게 빠지면(``_braked``) 아무것도 적지 않고 ``SyncBraked`` — 대표가 확인한 뒤 ``allow_drop_by``
        (확인한 직원 번호 · 대표 = 0)로 다시 부르면 받는다."""
        self._need_writer()
        if not isinstance(snap, E.StageSnapshot):
            raise StoreRefused("전산 단계 목록은 전부 받은 결과(StageSnapshot)만 받습니다")
        at = _kst_text(snap.as_of, "받은 시각")
        self._not_future(snap.as_of, "받은 시각")
        allow = None if allow_drop_by is None else _person(allow_drop_by, "확인한 직원")
        rows = []
        for pid, r in snap.rows.items():
            if not isinstance(r, E.StageRow) or r.possibility_id != pid:
                raise StoreRefused("전산 단계 줄 모양이 아닙니다")
            rows.append((_pos_int(pid, "가망 번호"), _opt_text(r.name, "가망 이름"), _opt_text(r.stage_key, "단계", 40),
                         None if r.latest_end_date is None else _day_text(r.latest_end_date, "종료일"),
                         _opt_bool(r.end_unreadable, "종료일 못 읽음")))
        conflicts = sorted({_pos_int(p, "가망 번호") for p in snap.stage_conflicts})
        if set(conflicts) & set(snap.rows):
            raise StoreRefused("단계가 겹친 가망이 줄에도 있습니다")
        detail = _spelling_counts(snap.per_spelling)
        seen = [r[0] for r in rows] + conflicts
        try:
            with self._tx() as c:
                last = self._meta_time(c, "prospects_synced_at")
                if last is not None and last >= snap.as_of:
                    raise StoreRefused("이미 적은 것보다 늦지 않은 단계 목록입니다")   # 옛 목록이 새 목록을 덮지 않게
                before = {p: pr for p, pr in c.execute("SELECT possibility_id, present FROM naver_auto_prospect")}
                if not seen and any(before.values()):
                    raise StoreRefused("빈 단계 목록으로 전부를 빼지 않습니다")
                seen_set = set(seen)
                leaving = sorted(p for p, pr in before.items() if pr == 1 and p not in seen_set)
                present_before = sum(1 for pr in before.values() if pr == 1)
                if allow is None and _braked(present_before, len(leaving)):
                    raise SyncBraked(SYNC_STAGES, present_before, len(leaving))
                for pid, name, stage, end, unread in rows:
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
                for pid in leaving:   # 처음 빠진 때만 적는다 — 이미 빠진 줄은 그대로
                    cur = c.execute(
                        """UPDATE naver_auto_prospect SET present = 0, absent_since = ?
                           WHERE possibility_id = ? AND present = 1""", (at, pid))
                    now_absent += cur.rowcount
                self._set_meta(c, "prospects_synced_at", at)
                self._log_sync(c, SYNC_STAGES, at, SYNC_ACCEPTED, ("CONFIRMED",) if allow is not None else (),
                               rows=len(seen), absent=now_absent, detail=detail, confirmed_by=allow)
        except SyncBraked as b:
            self._log_braked(SYNC_STAGES, at, b, len(seen))
            raise
        return SyncCounts(len(seen), len(set(seen) - set(before)), now_absent)

    def stage_as_of(self) -> Optional[datetime]:
        """전산 단계를 마지막으로 받은 시각 — 점검 규칙의 「단계 자료가 26시간 넘게 낡음」(system_gap) 재료."""
        return self._meta_time(self._conn, "prospects_synced_at")

    # ── 네이버 대행 연결 목록 ──
    def record_accounts(self, kids: "N.ChildAccounts", read_at: datetime, *,
                        allow_drop_by: Optional[int] = None) -> SyncCounts:
        """대행 연결 목록을 전부 받은 결과로 계정 표를 고친다 — 없어진 계정은 「목록에 없음」 · 연속 없는 날을 센다.

        날짜는 읽은 시각의 한국 날짜다. 같은 날 두 번 받아도 없는 날은 한 번만 세고, 더 이른 시각의 목록은 받지 않는다.
        확인한 짝을 무효로 할지(2일 연속)는 짝 동기화(S8)가 ``absent_days`` 를 보고 정한다.
        한꺼번에 크게 빠지거나 **관리계정 수가 줄고 빠질 계정이 있으면** 아무것도 적지 않고 ``SyncBraked``.
        """
        self._need_writer()
        if not isinstance(kids, N.ChildAccounts):
            raise StoreRefused("연결 목록은 전부 받은 결과(ChildAccounts)만 받습니다")
        at = _kst_text(read_at, "읽은 시각")
        self._not_future(read_at, "읽은 시각")
        allow = None if allow_drop_by is None else _person(allow_drop_by, "확인한 직원")
        d = at[:10]
        per = kids.per_manager
        if not isinstance(per, Mapping) or not per or any(
                isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in per.values()):
            raise StoreRefused("관리계정별 줄 수가 없습니다")
        if sum(per.values()) < len(kids.accounts) or (sum(per.values()) > 0) != bool(kids.accounts):
            raise StoreRefused("관리계정별 줄 수와 계정 수가 맞지 않습니다")   # 겹친 번호는 합쳐지므로 합계 ≥ 계정 수
        rows = []
        for cid, rec in kids.accounts.items():
            if not isinstance(rec, Mapping):
                raise StoreRefused("연결 목록 줄 모양이 아닙니다")
            kept = F.keep(rec, F.CHILD_ACCOUNT)          # 남길 칸만 — 들어온 다른 칸은 여기서 끝난다
            if kept.get("customerId") != cid:
                raise StoreRefused("연결 목록 줄의 고객 번호가 맞지 않습니다")
            rows.append((_pos_int(cid, "고객 번호"), _opt_pos_int(kept.get("adAccountNo"), "광고계정 번호"),
                         _opt_text(kept.get("adAccountName"), "계정 이름")))
        managers_now = len(per)
        try:
            with self._tx() as c:
                last = self._meta_time(c, "accounts_read_at")
                if last is not None and last >= read_at:
                    raise StoreRefused("이미 적은 것보다 늦지 않은 연결 목록입니다")
                before = {cid: pr for cid, pr in c.execute("SELECT customer_id, present FROM naver_auto_account")}
                if not rows and any(before.values()):
                    raise StoreRefused("빈 연결 목록으로 전부를 빼지 않습니다")
                seen = {r[0] for r in rows}
                leaving = sum(1 for cid, pr in before.items() if pr == 1 and cid not in seen)
                present_before = sum(1 for pr in before.values() if pr == 1)
                prev = c.execute(
                    """SELECT manager_count FROM naver_auto_sync_log WHERE kind = 'accounts' AND outcome = 'accepted'
                       ORDER BY sync_id DESC LIMIT 1""").fetchone()
                managers_before = None if prev is None else prev[0]
                manager_lost = managers_before is not None and managers_now < managers_before and leaving > 0
                if allow is None and (_braked(present_before, leaving) or manager_lost):
                    raise SyncBraked(SYNC_ACCOUNTS, present_before, leaving, managers_before, managers_now)
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
                for cid in sorted(set(before) - seen):
                    c.execute(
                        """UPDATE naver_auto_account SET present = 0, absent_days = absent_days + 1, last_absent_on = ?
                           WHERE customer_id = ? AND (last_absent_on IS NULL OR last_absent_on < ?)""", (d, cid, d))
                    if before[cid] == 1:
                        now_absent += 1
                self._set_meta(c, "accounts_read_at", at)
                self._log_sync(c, SYNC_ACCOUNTS, at, SYNC_ACCEPTED, ("CONFIRMED",) if allow is not None else (),
                               rows=len(rows), managers=managers_now, absent=now_absent, confirmed_by=allow)
        except SyncBraked as b:
            self._log_braked(SYNC_ACCOUNTS, at, b, len(rows))
            raise
        return SyncCounts(len(rows), len(seen - set(before)), now_absent)

    # ── ① 조직 스냅숏 수락본(S7 · M12) ──
    def record_org(self, body: Mapping, received_at: datetime, *, warnings: Sequence[str] = (),
                   confirmed_by: Optional[int] = None) -> None:
        """건전성 검사(``app.naver_auto.org_snapshot.accept_snapshot``)를 통과한 스냅숏 본문을 수락본으로 남긴다.

        남길 칸만(``fields.ORG_*``) · 값은 글자·정수·참거짓·빈 값만 · 더 새 스냅숏만(``generated_at``) · 미래 시각 거절.
        ``confirmed_by`` 는 대표가 확인하고 이전 조직 없이 다시 받은 경우(동기화 기록에 남는다).
        이 함수는 ``sync.py`` 에서만 부른다(구문 시험) — 검사를 거치지 않은 본문이 들어오지 않게."""
        self._need_writer()
        if not isinstance(body, Mapping):
            raise StoreRefused("조직 스냅숏 본문 모양이 아닙니다")
        gen = body.get("generated_at")
        try:
            gen_dt = datetime.fromisoformat(gen) if isinstance(gen, str) and len(gen) <= 64 else None
        except ValueError:
            gen_dt = None
        if gen_dt is None or gen_dt.tzinfo is None:
            raise StoreRefused("조직 스냅숏 시각을 읽지 못했습니다")
        if gen_dt > self._now() + ORG_FUTURE_SLACK:
            raise StoreRefused("조직 스냅숏 시각: 미래 시각은 받지 않습니다")
        rec = _kst_text(received_at, "받은 시각")
        self._not_future(received_at, "받은 시각")
        allow = None if confirmed_by is None else _person(confirmed_by, "확인한 직원")
        codes = _codes(warnings)
        kept = {"generated_at": gen}
        for key, allowed in (("teams", F.ORG_TEAM), ("employees", F.ORG_EMPLOYEE), ("owners", F.ORG_OWNER)):
            items = _seq(body.get(key), f"조직 {key}")
            if len(items) > ORG_MAX_ROWS:
                raise StoreRefused(f"조직 {key}: 줄이 너무 많습니다")
            out = []
            for it in items:
                if not isinstance(it, Mapping):
                    raise StoreRefused(f"조직 {key}: 줄 모양이 아닙니다")
                out.append({k: _org_value(v, f"조직 {key}") for k, v in F.keep(it, allowed).items()})
            kept[key] = out
        text = json.dumps(kept, ensure_ascii=False, separators=(",", ":"))
        gen_text = _kst_text(gen_dt, "조직 스냅숏 시각")
        with self._tx() as c:
            row = c.execute("SELECT generated_at FROM naver_auto_org WHERE slot = 'current'").fetchone()
            if row is not None and datetime.fromisoformat(row[0]) >= gen_dt:
                raise StoreRefused("이미 적은 것보다 새 조직 스냅숏이 아닙니다")   # 옛 스냅숏이 새것을 덮지 않게
            now = _kst_text(self._now(), "지금")
            c.execute(
                """INSERT INTO naver_auto_org (slot, generated_at, received_at, accepted_at, confirmed_by, body)
                   VALUES ('current', ?, ?, ?, ?, ?)
                   ON CONFLICT (slot) DO UPDATE SET generated_at = excluded.generated_at,
                       received_at = excluded.received_at, accepted_at = excluded.accepted_at,
                       confirmed_by = excluded.confirmed_by, body = excluded.body""",
                (gen_text, rec, now, allow, text))
            self._log_sync(c, SYNC_ORG, rec, SYNC_ACCEPTED, codes + (["CONFIRMED"] if allow is not None else []),
                           rows=len(kept["owners"]),
                           detail={"teams": len(kept["teams"]), "employees": len(kept["employees"])},
                           confirmed_by=allow)

    # ── 사람의 짝 판단 ──
    def record_decision(self, possibility_id: int, customer_id: int, decision: str, decided_by: int,
                        at: datetime) -> int:
        """짝 확인 화면의 판단 한 줄을 쌓는다(같은 짝에 다시 판단하면 새 줄 — 가장 늦은 줄이 이긴다)."""
        self._need_writer()
        if decision not in DECISIONS:
            raise StoreRefused("판단은 confirmed · rejected 뿐입니다")
        vals = (_pos_int(possibility_id, "가망 번호"), _pos_int(customer_id, "고객 번호"), decision,
                _person(decided_by, "판단한 직원"), _kst_text(at, "판단 시각"))
        self._not_future(at, "판단 시각")
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
        if not vals[2] or not vals[2].strip():
            raise StoreRefused("거두는 사유가 있어야 합니다")
        self._not_future(at, "거둔 시각")
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
               WHERE d.decision_id = (   -- 거두지 않은 판단 중 가장 늦은 것(거둔 줄은 안쪽에서 빠진다)
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
        self._not_future(started_at, "시작 시각")
        with self._tx() as c:
            if c.execute("SELECT 1 FROM naver_auto_check_run WHERE run_date = ? AND status = 'running'", (d,)).fetchone():
                raise StoreRefused("같은 날 회차가 아직 돌고 있습니다")
            rid = c.execute("INSERT INTO naver_auto_check_run (run_date, started_at, status) VALUES (?, ?, 'running')",
                            (d, t)).lastrowid
        self._my_runs.add(rid)
        return rid

    def finish_run(self, run_id: int, status: str, finished_at: datetime, accounts_total: Optional[int] = None,
                   accounts_ok: Optional[int] = None, error_kind: Optional[str] = None) -> None:
        self._need_writer()
        if status not in RUN_END_STATUSES:
            raise StoreRefused("회차는 done · failed 로만 끝납니다")
        for v in (accounts_total, accounts_ok):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < 2 ** 31):
                raise StoreRefused("계정 수는 0 이상 정수여야 합니다")
        kind = None if error_kind is None else _code(error_kind, _ERROR_KIND, "오류 종류")
        vals = (status, _kst_text(finished_at, "끝난 시각"), accounts_total, accounts_ok, kind,
                _pos_int(run_id, "회차 번호"))
        self._not_future(finished_at, "끝난 시각")
        if run_id not in self._my_runs:
            raise StoreRefused("이 저장소가 시작한 회차가 아닙니다")
        with self._tx() as c:
            cur = c.execute(
                """UPDATE naver_auto_check_run SET status = ?, finished_at = ?, accounts_total = ?, accounts_ok = ?,
                       error_kind = ? WHERE run_id = ? AND status = 'running'""", vals)
            if cur.rowcount != 1:
                raise StoreRefused("돌고 있는 회차가 아닙니다")
        self._my_runs.discard(run_id)

    def _running_run_date(self, c, run_id: int) -> str:
        if run_id not in self._my_runs:
            raise StoreRefused("이 저장소가 시작한 회차가 아닙니다")   # 도중에 죽은 회차 번호로 적지 않는다
        row = c.execute("SELECT run_date FROM naver_auto_check_run WHERE run_id = ? AND status = 'running'",
                        (run_id,)).fetchone()
        if row is None:
            raise StoreRefused("돌고 있는 회차가 아닙니다")   # 끝난 회차에는 더 적지 않는다
        return row[0]

    def running_runs(self) -> List[int]:
        """「돌고 있음」인 회차 번호 — 쓰기용으로 연 직후라면 도중에 죽은 회차는 이미 닫혀 있다."""
        return [int(r[0]) for r in self._conn.execute(
            "SELECT run_id FROM naver_auto_check_run WHERE status = 'running' ORDER BY run_id")]

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
        ran, not_ran = _rules(rules_run, rules_not_run)
        vals = [_pos_int(customer_id, "고객 번호"), None, _opt_pos_int(possibility_id, "가망 번호"), link,
                _pos_int(run_id, "회차 번호"), status, ran, not_ran, _num(bizmoney, "비즈머니"),
                _opt_bool(budget_lock, "잠금"), _opt_bool(refund_lock, "잠금"), _num(yday_spend, "어제 비용"),
                _num(yday_imp, "어제 노출"), _num(yday_clk, "어제 클릭"), _opt_bool(data_late, "자료 늦음"),
                _kst_text(checked_at, "점검 시각")]
        self._not_future(checked_at, "점검 시각")
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
    def record_campaign_days(self, run_id: int, customer_id: int, day: date, campaigns: Iterable[Mapping],
                             stats: Mapping[str, Mapping[str, Optional[float]]], *, provisional: bool,
                             read_at: datetime) -> int:
        """계정 한 곳의 그날(통계 날짜) 캠페인 줄 — 돌고 있는 이 저장소의 회차 안에서만.

        캠페인 정보는 ``fields.CAMPAIGN`` 남길 칸에서 넷만, 숫자는 ``stats[캠페인 번호]`` 의 원래 숫자 7개만.
        - 통계 줄이 없는 캠페인: 처음이면 숫자는 모름, 이미 있으면 **알던 숫자·잠정·읽은 시각을 그대로 둔다**.
        - 확정(잠정 아님) 숫자는 잠정 숫자로 덮지 않고, 더 이른 시각에 읽은 숫자로도 덮지 않는다.
        돌려주는 값은 실제로 적거나 고친 줄 수다."""
        self._need_writer()
        cid, d = _pos_int(customer_id, "고객 번호"), _day_text(day, "날짜")
        if type(provisional) is not bool:
            raise StoreRefused("잠정 여부는 참/거짓이어야 합니다")
        t = _kst_text(read_at, "읽은 시각")
        self._not_future(read_at, "읽은 시각")
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
            rows.append([ccid, d, cid, None, _opt_text(k.get("campaignTp"), "캠페인 종류", 40),
                         _opt_text(k.get("status"), "상태", 40), _opt_text(k.get("statusReason"), "사유", 80),
                         _num(k.get("dailyBudget"), "하루 예산"), *metrics, int(st is not None), int(provisional), t])
        if set(stats) - seen:
            raise StoreRefused("캠페인 목록에 없는 통계 줄이 있습니다")   # 다른 계정 숫자가 섞이지 않게
        cols = ", ".join(c for _, c in CAMPAIGN_METRICS)
        keep_or_new = ", ".join(
            f"{c} = CASE WHEN excluded.metrics_read = 1 THEN excluded.{c} ELSE naver_auto_campaign_day.{c} END"
            for _, c in CAMPAIGN_METRICS)
        written = 0
        with self._tx() as c:
            rid = _pos_int(run_id, "회차 번호")
            self._running_run_date(c, rid)
            for r in rows:
                r[3] = rid
                own = c.execute("SELECT customer_id FROM naver_auto_campaign_day WHERE campaign_id = ? LIMIT 1",
                                (r[0],)).fetchone()
                if own is not None and own[0] != cid:
                    raise StoreRefused("다른 계정의 캠페인 번호입니다")
                cur = c.execute(
                    f"""INSERT INTO naver_auto_campaign_day (campaign_id, day, customer_id, run_id, campaign_tp, status,
                            status_reason, daily_budget, {cols}, metrics_read, provisional, read_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (campaign_id, day) DO UPDATE SET
                            run_id = excluded.run_id, campaign_tp = excluded.campaign_tp, status = excluded.status,
                            status_reason = excluded.status_reason, daily_budget = excluded.daily_budget,
                            {keep_or_new},
                            metrics_read = MAX(excluded.metrics_read, naver_auto_campaign_day.metrics_read),
                            provisional = CASE WHEN excluded.metrics_read = 1 THEN excluded.provisional
                                               ELSE naver_auto_campaign_day.provisional END,
                            read_at = CASE WHEN excluded.metrics_read = 1 THEN excluded.read_at
                                           ELSE naver_auto_campaign_day.read_at END
                        WHERE excluded.read_at >= naver_auto_campaign_day.read_at
                          AND NOT (excluded.metrics_read = 1 AND excluded.provisional = 1
                                   AND naver_auto_campaign_day.metrics_read = 1
                                   AND naver_auto_campaign_day.provisional = 0)""", r)
                written += cur.rowcount
        return written

    # ── 읽기 ──
    def meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM naver_auto_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

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
        out["rules_run"] = list(json.loads(out["rules_run"]))
        out["rules_not_run"] = [tuple(x) for x in json.loads(out["rules_not_run"])]
        return out

    def campaign_days(self, customer_id: int, since: date, until: date) -> List[dict]:
        s, u = _day_text(since, "시작 날짜"), _day_text(until, "끝 날짜")
        if s > u:
            raise StoreRefused("시작 날짜가 끝 날짜보다 늦습니다")
        cur = self._conn.execute(
            """SELECT * FROM naver_auto_campaign_day WHERE customer_id = ? AND day BETWEEN ? AND ?
               ORDER BY day, campaign_id""", (_pos_int(customer_id, "고객 번호"), s, u))
        return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    def org_current(self) -> Optional[dict]:
        """조직 수락본 — ``body`` 는 ``app.naver_auto.org_snapshot.parse_org_snapshot`` 에 그대로 넘기는 본문."""
        r = self._conn.execute(
            "SELECT generated_at, received_at, accepted_at, confirmed_by, body FROM naver_auto_org WHERE slot = 'current'"
        ).fetchone()
        if r is None:
            return None
        try:
            body = json.loads(r[4])
            times = [datetime.fromisoformat(t) for t in r[:3]]
        except (TypeError, ValueError):
            raise StoreError("저장된 조직 수락본을 읽지 못했습니다") from None
        if not isinstance(body, dict):
            raise StoreError("저장된 조직 수락본을 읽지 못했습니다")
        return {"body": body, "generated_at": times[0], "received_at": times[1], "accepted_at": times[2],
                "confirmed_by": r[3]}

    def _sync_rows(self, where: str, args: tuple, limit: int) -> List[dict]:
        cur = self._conn.execute("SELECT * FROM naver_auto_sync_log" + where + " ORDER BY sync_id DESC LIMIT ?",
                                 args + (limit,))
        out = []
        for r in cur.fetchall():
            d = dict(zip([x[0] for x in cur.description], r))
            d["codes"] = list(json.loads(d["codes"]))
            d["detail"] = None if d["detail"] is None else json.loads(d["detail"])
            out.append(d)
        return out

    def sync_log(self, kind: Optional[str] = None, limit: int = 100) -> List[dict]:
        """동기화 기록 — 새것부터."""
        if kind is not None and kind not in SYNC_KINDS:
            raise StoreRefused("동기화 종류가 아닙니다")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 10_000:
            raise StoreRefused("몇 줄인지 1~10000 이어야 합니다")
        return self._sync_rows("" if kind is None else " WHERE kind = ?", () if kind is None else (kind,), limit)

    def last_sync(self, kind: str, outcome: Optional[str] = None) -> Optional[dict]:
        """그 종류의 마지막 동기화(결과를 주면 그 결과의 마지막)."""
        if kind not in SYNC_KINDS:
            raise StoreRefused("동기화 종류가 아닙니다")
        if outcome is not None and outcome not in SYNC_OUTCOMES:
            raise StoreRefused("동기화 결과가 아닙니다")
        where, args = " WHERE kind = ?", (kind,)
        if outcome is not None:
            where, args = where + " AND outcome = ?", args + (outcome,)
        rows = self._sync_rows(where, args, 1)
        return rows[0] if rows else None

    def run(self, run_id: int) -> Optional[dict]:
        cur = self._conn.execute("SELECT * FROM naver_auto_check_run WHERE run_id = ?", (_pos_int(run_id, "회차 번호"),))
        r = cur.fetchone()
        return None if r is None else dict(zip([d[0] for d in cur.description], r))
