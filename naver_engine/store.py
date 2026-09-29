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
  않게. 한 단계만 크게 빠져도(``BRAKE_STAGE``) · 기준선(마지막 확인 뒤 가장 많던 수)보다 누적으로 크게 줄어도
  (``BRAKE_BASELINE`` — 조금씩 잘리는 톱니 방지) · 계정은 있던 관리계정(번호)이 사라지거나 0줄·크게 줄어도(``BRAKE_MANAGER``)
  멈춘다. 멈춘 목록은 **그대로 붙잡아 둔다**(``naver_auto_hold``) — 대표가 확인하면 새로 읽지 않고 **그 목록을** 받는다
  (``confirm_*_hold`` · 3시간 안 · 한 번만 · 누가 받았는지와 우회한 코드가 기록에 남는다 · S7 적대 검토).
- **조직 스냅숏은 수락본 하나만 남긴다(S7 · M12).** 건전성 검사를 통과한 것만 ``record_org`` 로 들어오고, 엔진이 다시
  켜져도 이 수락본이 다음 검사의 「이전 조직」이 된다. 남길 칸만(``fields.ORG_*``) · 더 새 스냅숏만.
- **동기화마다 한 줄 남긴다(S7).** 받음 · 버림 · 멈춤(브레이크) · 실패 — 종류 코드와 개수만(번호·이름 없음).
- **짝 판단은 계정마다 가장 늦은 확인 하나만 산다(S8).** 짝마다 가장 늦은 · 거두지 않은 판단을 고른 뒤, 한 계정을 여러
  가망에 「확인」했으면 가장 늦게 적은 확인(판단 번호가 큰 것) 하나만 살리고 앞 확인은 「밀린 확인」으로 따로 돌려준다
  (줄은 지우지 않는다 · 뒤 확인을 거두면 앞 확인이 다시 산다). 확인한 짝이 있는 계정이 한꺼번에 크게 빠져도 멈춘다
  (``BRAKE_CONFIRMED`` — 끝난·쉬는 계정이 섞인 전체 분모로는 안 보이는 것 · S7 뒤 조각 몫 ⑵).
- **계정이 목록에 있던·없던 시각을 남긴다(S8).** 날짜 수(``absent_days``)만으로는 자정을 사이에 둔 두 번이 「2일」이
  된다 — 처음 빠진 읽기 시각·마지막으로 빠진 읽기 시각을 따로 두어 「이관 빠짐」이 시각 간격도 보게 한다(S7 뒤 조각 몫 ⑶).
  **이관** = 광고주 광고계정이 우리 회사(대행사 관리계정)에 연결된 상태 — 대행 연결 목록에 있으면 이관됨(대표 정의).
  「이관 빠짐」은 **이어졌던 짝**(사람이 확인한 짝 · 자동 짝으로 이어진 적 있는 짝 — ``naver_auto_link_memory``)에만 판정한다.
  표는 **더하기만** 했다(칸을 고치지 않는다 — 옛 판 파일도 열 때 표만 더한다).
- **짝 맞추기 결과는 회차마다 쌓는다(S8).** 받은 회차는 가망·계정 번호와 상태·코드만 줄로 남기고(이름 없음), 버림·실패는
  코드만 남긴다. 적는 순간 입력(연결 목록 읽은 시각 · 단계 받은 시각 · 사람 판단)이 계산할 때와 같지 않으면 받지 않는다
  (``PairingStale``) · 점검할 짝의 계정은 지금 목록에 있어야 하고 가망은 지금 관리 대상이어야 한다.

엔진이 부르는 순서(S7~S9): 1시간마다 ``sync.sync_org`` → 6시간마다 ``sync.sync_stages``(``record_prospects``) →
하루 한 번 ``links.sync_accounts``(``record_accounts``) → ``links.pair_links``(``record_pairing``) → ``begin_run`` →
계정마다 ``record_account_check``(계정 하루치 · 캠페인 하루치 · 이슈를 한 거래로) → ``close_unlinked_issues`` →
``finish_run``(S9 ``morning``).

- **이슈는 한 줄 · 지우지 않는다(S9).** 열쇠 = 가망 + 점검 항목 + 대상. 상태 규칙은 ``backend/app/naver_auto/issues.py``
  한 곳 — 저장소는 그 규칙이 낸 상태를 거래 안에서 적고, 상태·등급이 바뀔 때만 기록 한 줄을 남긴다. 사람의 손길(확인 ·
  해결 · 예외)도 같은 규칙을 지난다 — 예외 한도(🟡 30일 · 🔴 팀장 이상 7일)를 부르는 쪽이 건너뛸 수 없다.
"""
from __future__ import annotations

import fcntl as _fcntl
import hashlib
import json
import math
import os
import pathlib
import re
import sqlite3 as _sqlite3
import stat as _stat
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import erp_read as E
from . import fields as F
from . import handles as H
from . import naver_read as N

__all__ = ("open_writer", "open_reader", "Store", "StoreError", "StoreBusy", "StoreRefused", "SyncBraked",
           "HoldRefused", "SyncCounts", "LinkDecision", "PairingStale", "IssueRefused", "IssueTally", "UnlinkCounts")

KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 4   # 2 = S7(조직 수락본 · 동기화 기록) · 3 = S8(계정 시각 · 짝 결과) · 4 = S9(이슈 · 이슈 기록) — 옛 판 파일은 열 때 표를 더하고 판 번호를 올린다
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
HOLD_TTL = timedelta(hours=3)   # 붙잡아 둔 목록을 확인할 수 있는 시간 — 지나면 다시 읽어 새로 붙잡는다
BRAKE_TOTAL, BRAKE_STAGE, BRAKE_BASELINE, BRAKE_MANAGER = "BRAKE", "BRAKE_STAGE", "BRAKE_BASELINE", "BRAKE_MANAGER"
BRAKE_CONFIRMED = "BRAKE_CONFIRMED"   # 확인한 짝이 있는 계정이 한꺼번에 크게 빠짐(S8)
CODE_CONFIRMED = "CONFIRMED"
CODE_STORED_UNREADABLE = "STORED_UNREADABLE"   # 저장된 조직 수락본을 못 읽음 — 이 붙잡음을 확인할 때만 망가진 줄을 덮어쓴다
HOLD_NOT_FOUND, HOLD_USED, HOLD_EXPIRED = "HOLD_NOT_FOUND", "HOLD_USED", "HOLD_EXPIRED"
HOLD_SUPERSEDED = "HOLD_SUPERSEDED"   # 확인하기 전에 더 새 목록을 (확인 없이) 받았다 — 옛 붙잡음은 받을 수 없다
_CODE_DIR = os.path.dirname(os.path.realpath(__file__))

# 점검 상태 — backend/app/naver_auto/verdict.py 의 CHECK_* 와 같은 글자(시험이 대조한다)
ACCOUNT_STATUSES = frozenset({
    "ok", "pending", "not_checked", "partial", "key_rejected", "data_late", "system_gap", "link_broken", "not_eligible",
    "link_missing",
})
LINKS = frozenset({"confirmed", "auto"})           # handles.LINK_* 와 같은 글자(시험이 대조한다)
DECISIONS = frozenset({"confirmed", "rejected"})   # backend/app/naver_auto/matching.py 의 DECISION_* 와 같은 글자
# 짝 맞추기 결과 줄의 상태(S8) — confirmed·auto 는 handles.LINK_* 와 같은 글자(시험이 대조한다)
PAIR_CONFIRMED, PAIR_AUTO = "confirmed", "auto"          # 점검해도 되는 짝(확인 · 자동)
# ⚠️ 「이관」 = 광고주 광고계정이 우리 회사(대행사 관리계정)에 연결된 상태 — 대행 연결 목록에 있으면 이관됨(대표 정의 2026-09-29)
PAIR_MISSING = "missing"          # 이어졌던 짝(확인 · 자동)의 계정이 오늘 연결 목록에 없음 — 아직 「이관 빠짐」은 아님
PAIR_BROKEN = "broken"            # 이관 빠짐 — 이어졌던 짝의 계정이 2일(서로 다른 날짜) · 20시간 넘게 연결 목록에 없음(확인 필요 예)
PAIR_BLOCKED = "blocked"          # ① 에 번호가 적혀 있는데 자동 짝이 못 됨(사유 코드)
PAIR_CANDIDATE = "candidate"      # 이름만 비슷함 — 사람이 확인할 때까지 들어가지 않는다
PAIR_SUPERSEDED = "superseded"    # 같은 계정을 다른 가망에 더 늦게 확인해 밀린 확인(사람이 볼 수 있게)
PAIR_STATES = frozenset({PAIR_CONFIRMED, PAIR_AUTO, PAIR_MISSING, PAIR_BROKEN, PAIR_BLOCKED, PAIR_CANDIDATE,
                         PAIR_SUPERSEDED})
PAIR_CHECKABLE = frozenset({PAIR_CONFIRMED, PAIR_AUTO})
PAIR_RELATIONS = frozenset({"same", "contains", "different", "unknown"})   # matching.REL_* 와 같은 글자(시험이 대조)
# 막힘 줄 사유 — matching.B_* 와 같은 글자(시험이 대조) · 그 밖의 글자(숫자 조각 등)는 사유 칸에 들어가지 않는다
PAIR_BLOCK_CODES = frozenset({"customer-id-format", "customer-id-length", "not-linked", "ad-account-number",
                              "ambiguous-space", "claimed-by-several", "confirmed-elsewhere", "rejected-by-human",
                              "name-different", "name-points-elsewhere"})
PAIR_CODE_NEVER_LISTED = "never-listed"   # 이관 빠짐 사유: 확인한 계정이 한 번도 연결 목록에 없었음(그 밖은 사유 없음)
PAIRING_OUTCOMES = frozenset({SYNC_ACCEPTED, SYNC_REFUSED, SYNC_FAILED})
PAIRING_INPUT_COUNTS = ("prospects", "ignored")   # 줄로는 알 수 없는 개수 — 부르는 쪽이 넣는다(나머지는 저장소가 줄에서 센다)
PAIRING_MAX_ROWS = 200_000
CODE_INPUTS_CHANGED = "INPUTS_CHANGED"   # 짝을 계산하는 사이 입력(연결 목록·단계·사람 판단)이 바뀜 — 다시 계산한다

# 이슈(S9) — backend/app/naver_auto/issues.py 의 상태·등급·기록 종류와 같은 글자(시험이 대조한다)
ISSUE_STATES = frozenset({"new", "ack", "exception", "resolved", "auto_resolved", "closed_unlinked"})
ISSUE_SEVERITIES = frozenset({"red", "yellow", "info"})
ISSUE_EVENTS = frozenset({"opened", "reappeared", "escalated", "deescalated", "exception_ended", "auto_resolved",
                          "closed_unlinked", "acked", "resolved", "excepted"})
FACTS_MAX = 10   # 발견 사실 칸 수(규칙이 내는 것은 3개 이하)

RUN_RUNNING, RUN_DONE, RUN_FAILED = "running", "done", "failed"
RUN_END_STATUSES = frozenset({RUN_DONE, RUN_FAILED})
ORPHANED = "orphaned"

# 코드 모양 — 규칙 이름(checks.ALL_RULES) · 사유(checks 의 "stats-unread" 등) · 오류 종류(naver_read.KIND_* · erp 종류)
_RULE_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_REASON_CODE = re.compile(r"[a-z0-9][a-z0-9_]*(?:-[a-z0-9_]+)*")
# 오류·동기화 코드 — 영문 낱말(밑줄)을 줄표로 잇고, 숫자는 끝의 HTTP 상태 세 자리 하나만(번호·키 조각이 기록에 남지 않게)
_ERROR_KIND = re.compile(r"(?=.{1,40}\Z)[A-Za-z][A-Za-z_]*(?:-[A-Za-z_]+)*(?:-[1-5][0-9]{2})?")

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
    # 붙잡아 둔 목록 — 멈춤·버림 때의 결과 그대로(종류마다 가장 최근 하나 · 확인하면 새로 읽지 않고 이것을 받는다)
    """CREATE TABLE IF NOT EXISTS naver_auto_hold (
        kind TEXT PRIMARY KEY CHECK (kind IN ('org', 'stages', 'accounts')),
        sync_id INTEGER NOT NULL,
        at TEXT NOT NULL,
        codes TEXT NOT NULL,
        body TEXT NOT NULL,
        used_at TEXT,
        used_by INTEGER CHECK (used_by IS NULL OR used_by >= 0))""",
    # 계정이 연결 목록에 있던·없던 읽기 시각(S8) — 「연결 끊김」은 날짜 수와 시각 간격을 함께 본다(표를 더하기만 — 칸을 고치지 않는다)
    """CREATE TABLE IF NOT EXISTS naver_auto_account_time (
        customer_id INTEGER PRIMARY KEY CHECK (customer_id > 0),
        last_seen_at TEXT,
        absent_since TEXT,
        absent_last_at TEXT)""",
    # 짝 맞추기 회차(S8) — 받음·버림·실패 · 코드와 개수만
    """CREATE TABLE IF NOT EXISTS naver_auto_pairing_run (
        pairing_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'refused', 'failed')),
        codes TEXT NOT NULL,
        accounts_read_at TEXT,
        stages_as_of TEXT,
        decisions_hash TEXT,
        counts TEXT)""",
    # 짝 맞추기 결과 줄(받은 회차만) — 가망·계정 번호와 상태·코드만(이름 없음)
    """CREATE TABLE IF NOT EXISTS naver_auto_pairing_row (
        pairing_id INTEGER NOT NULL CHECK (pairing_id > 0),
        possibility_id INTEGER NOT NULL CHECK (possibility_id > 0),
        customer_id INTEGER CHECK (customer_id IS NULL OR customer_id > 0),
        state TEXT NOT NULL CHECK (state IN ('confirmed', 'auto', 'missing', 'broken', 'blocked', 'candidate',
                                             'superseded')),
        code TEXT,
        same_name INTEGER CHECK (same_name IS NULL OR same_name >= 1),
        claimed_elsewhere INTEGER CHECK (claimed_elsewhere IS NULL OR claimed_elsewhere IN (0, 1)),
        decision_id INTEGER CHECK (decision_id IS NULL OR decision_id > 0),
        link TEXT CHECK (link IS NULL OR link IN ('confirmed', 'auto')))""",
    # 짝이 이어졌던 적이 있다(짝 종류마다 처음·마지막으로 이어진 짝 맞추기 시각) — 「이관 빠짐」은 이어졌던 짝에만 판정한다
    """CREATE TABLE IF NOT EXISTS naver_auto_link_memory (
        possibility_id INTEGER NOT NULL CHECK (possibility_id > 0),
        customer_id INTEGER NOT NULL CHECK (customer_id > 0),
        link TEXT NOT NULL CHECK (link IN ('confirmed', 'auto')),
        first_matched_at TEXT NOT NULL,
        last_matched_at TEXT NOT NULL,
        PRIMARY KEY (possibility_id, customer_id, link))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_pairing_row_run
        ON naver_auto_pairing_row (pairing_id, possibility_id)""",
    # 이슈(S9) — 같은 원인 + 같은 대상은 한 줄(열쇠 = 가망 + 점검 항목 + 대상) · 지우지 않고 상태만 바꾼다
    """CREATE TABLE IF NOT EXISTS naver_auto_issue (
        issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        possibility_id INTEGER NOT NULL CHECK (possibility_id > 0),
        code TEXT NOT NULL,
        target TEXT NOT NULL,
        customer_id INTEGER NOT NULL CHECK (customer_id > 0),
        rule TEXT NOT NULL,
        severity TEXT NOT NULL CHECK (severity IN ('red', 'yellow', 'info')),
        state TEXT NOT NULL CHECK (state IN ('new', 'ack', 'exception', 'resolved', 'auto_resolved', 'closed_unlinked')),
        first_seen_on TEXT NOT NULL,
        last_seen_on TEXT NOT NULL,
        reappear_count INTEGER NOT NULL DEFAULT 0 CHECK (reappear_count >= 0),
        exception_until TEXT,
        exception_severity TEXT CHECK (exception_severity IS NULL OR exception_severity IN ('red', 'yellow', 'info')),
        updated_at TEXT NOT NULL,
        facts TEXT,
        CHECK ((state = 'exception') = (exception_until IS NOT NULL AND exception_severity IS NOT NULL)),
        UNIQUE (possibility_id, code, target))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_issue_pair
        ON naver_auto_issue (possibility_id, customer_id, state)""",
    # 이슈 기록 — 상태·등급이 바뀔 때만 한 줄(누가 · 언제 · 무엇 · 예외 사유) · 쌓기만
    """CREATE TABLE IF NOT EXISTS naver_auto_issue_event (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_id INTEGER NOT NULL CHECK (issue_id > 0),
        at TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('opened', 'reappeared', 'escalated', 'deescalated', 'exception_ended',
                                           'auto_resolved', 'closed_unlinked', 'acked', 'resolved', 'excepted')),
        from_state TEXT,
        to_state TEXT NOT NULL,
        severity TEXT NOT NULL,
        by_person INTEGER CHECK (by_person IS NULL OR by_person >= 0),
        run_id INTEGER CHECK (run_id IS NULL OR run_id > 0),
        exception_until TEXT,
        note TEXT)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_issue_event_issue
        ON naver_auto_issue_event (issue_id, event_id)""",
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
    """목록이 한꺼번에 크게 줄어 「목록에 없음」을 찍기 전에 멈췄다 — 아무것도 적지 않았다(개수·코드만 싣는다).

    멈춘 목록은 그대로 **붙잡아 둔다**(``hold_id``) — 대표가 확인하면 새로 읽지 않고 **그 목록을** 받는다(확인한 것과 받는 것이
    같게 · S7 적대 검토). ``reasons`` = 멈춘 이유 코드(``BRAKE`` 한 번에 · ``BRAKE_STAGE`` 한 단계 · ``BRAKE_BASELINE`` 누적 ·
    ``BRAKE_MANAGER`` 관리계정)."""

    def __init__(self, kind: str, present_before: int, would_absent: int, reasons: Tuple[str, ...] = (),
                 hold_id: Optional[int] = None, managers_before: Optional[int] = None,
                 managers_now: Optional[int] = None) -> None:
        self.kind, self.present_before, self.would_absent = kind, present_before, would_absent
        self.reasons, self.hold_id = tuple(reasons), hold_id
        self.managers_before, self.managers_now = managers_before, managers_now
        super().__init__(f"목록 급감 — 멈춤({kind}): 있던 {present_before} 중 {would_absent} 이 빠질 뻔했습니다")


class _Brake(Exception):
    """거래 안에서 멈춤을 알리는 내부 신호 — 거래를 되돌린 뒤 붙잡아 두기·기록을 따로 적는다."""

    def __init__(self, reasons, present_before: int, would_absent: int, managers_before=None, managers_now=None):
        super().__init__("brake")
        self.reasons, self.present_before, self.would_absent = tuple(reasons), present_before, would_absent
        self.managers_before, self.managers_now = managers_before, managers_now


class HoldRefused(StoreRefused):
    """확인할 붙잡음이 없음(또는 더 새로 붙잡음) · 이미 씀 · 확인 시간이 지남 — ``code`` 로 가른다(문구에 값 없음)."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PairingStale(StoreRefused):
    """짝을 계산하는 사이 입력(연결 목록 · 단계 · 사람 판단)이 바뀌었거나, 점검할 짝의 계정·가망이 지금 목록에 없다 —
    아무것도 적지 않았다. 다시 계산하면 된다(``code`` = ``INPUTS_CHANGED``)."""

    code = CODE_INPUTS_CHANGED


class IssueRefused(StoreRefused):
    """이슈 규칙이 받지 않는 사람의 손길 — ``code`` 는 사유 코드(``issues.E_*`` · 없는 이슈면 ``not-found``)."""

    def __init__(self, code: str) -> None:
        super().__init__(f"이슈 손길을 받지 않습니다: {code}")
        self.code = code


@dataclass(frozen=True)
class IssueTally:
    """계정 한 곳의 이슈 변화 — 기록 종류별 개수(``seen`` = 열린 이슈를 다시 봄 · 기록 줄은 없음)."""
    counts: dict

    def __repr__(self) -> str:
        return f"IssueTally({dict(sorted(self.counts.items()))})"


@dataclass(frozen=True)
class UnlinkCounts:
    closed_issues: int      # 닫은 이슈 수
    closed_pairs: int       # 이슈를 닫은 짝(가망 · 계정) 수
    pairs_with_open: int    # 닫기 전 열린 이슈가 있던 짝 수
    mass: bool              # 한꺼번에 많이 닫음(브레이크와 같은 비율) — 대표에게 알린다

    def __repr__(self) -> str:
        return (f"UnlinkCounts(closed_issues={self.closed_issues}, closed_pairs={self.closed_pairs}, "
                f"pairs_with_open={self.pairs_with_open}, mass={self.mass})")


@dataclass(frozen=True)
class LinkDecision:
    """지금 살아 있는 사람의 짝 판단 한 줄(또는 밀린 확인) — 번호·시각을 함께 준다(S8 · 짝 확인 화면 S11 이 쓴다)."""
    decision_id: int
    possibility_id: int
    customer_id: int = field(repr=False)   # 표시(repr)·로그에 고객 번호가 새지 않게
    decision: str = "confirmed"
    decided_by: int = 0
    decided_at: Optional[datetime] = None


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
    try:
        return t.astimezone(KST).isoformat(timespec="microseconds")   # 같은 초 안의 앞뒤도 가른다
    except OverflowError:
        raise StoreRefused(f"{what}: 한국 시각으로 바꿀 수 없는 시각입니다") from None


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


CUSTOMER_ID_LIMIT = 10 ** 15   # 네이버 고객 번호 — 읽기 관문(``handles._MAX_ID``)·이슈 규칙(``issues.account_target``)과 같은 한도


def _customer_id(v, what: str) -> int:
    """네이버 고객 번호 — 양의 정수 · 15자리 이하(저장소가 받는 범위와 이슈 규칙이 받는 범위가 어긋나 16자리 번호 한 줄이
    아침 점검 회차 전체를 멈추지 않게 · 검토 issues-oversized)."""
    v = _pos_int(v, what)
    if v >= CUSTOMER_ID_LIMIT:
        raise StoreRefused(f"{what}: 고객 번호 범위를 넘습니다")
    return v


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
    try:
        v.encode("utf-8")   # 짝 없는 대리 문자는 저장에서 터진다 — 먼저 거절한다(원래 예외에 본문 전체가 실리지 않게)
    except UnicodeEncodeError:
        raise StoreRefused(f"{what}: 쓸 수 없는 글자가 있습니다") from None
    return v


def _or_none(check, v, what: str):
    """네이버가 준 표시용 칸 하나가 저장 규칙에 안 맞으면 그 칸만 비운다(줄은 남긴다) — 이상한 이름·번호 하나로
    1,784곳 연결 목록 전체가 날마다 버려지지 않게(① 읽기 관문의 상호와 같은 방식 · 검토 sync-1). 광고계정 번호가
    비면 짝 맞추기가 그 목록을 쓰지 않고 연결 목록 받기가 알린다(links ``ACCOUNTS_UNUSABLE``)."""
    try:
        return check(v, what)
    except StoreRefused:
        return None


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


def _issue_rules():
    """이슈 상태 규칙(``backend/app/naver_auto/issues.py``) — 이슈를 다루는 함수에서만 불러온다(엔진은 backend 를
    경로에 두고 돈다 · links · sync 와 같다). 저장소를 여는 것만으로는 backend 가 필요 없게 여기서 늦게 부른다."""
    from app.naver_auto import issues
    return issues


def _facts(facts) -> Optional[str]:
    """발견 사실 — (이름, 값) 쌍 · 이름은 코드 모양 · 값은 숫자 · 코드 모양 글자 · 단계 열쇠 · 코드 목록만(이름·주소 없음)."""
    pairs = _seq(facts, "발견 사실")
    if not pairs:
        return None
    if len(pairs) > FACTS_MAX:
        raise StoreRefused("발견 사실이 너무 많습니다")
    out = {}
    for p in pairs:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise StoreRefused("발견 사실은 (이름, 값) 쌍이어야 합니다")
        k, v = _code(p[0], _RULE_CODE, "사실 이름"), p[1]
        if k in out:
            raise StoreRefused("같은 사실 이름이 두 번 있습니다")
        if isinstance(v, bool) or v is None:
            raise StoreRefused("사실 값 모양이 아닙니다")
        if isinstance(v, (int, float)):
            f = _num(v, "사실 값")
            out[k] = int(v) if isinstance(v, int) else f
        elif isinstance(v, str):
            if v not in H.MONITORED_STAGES:
                _code(v, _REASON_CODE, "사실 값")
            out[k] = v
        else:
            items = _seq(v, "사실 값")
            if len(items) > FACTS_MAX:
                raise StoreRefused("사실 값이 너무 많습니다")
            out[k] = [_code(x, _REASON_CODE, "사실 값") for x in items]
    return json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _aware_time(raw) -> Optional[datetime]:
    """시간대 있는 ISO 시각 글자 → 시각 · 못 읽거나 시간대가 없으면 None."""
    if not isinstance(raw, str):
        return None
    try:
        t = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return t if t.tzinfo is not None else None


def _stage_row(pid, name, stage, end, unread) -> tuple:
    if stage not in E.STAGE_SPELLINGS:
        raise StoreRefused("모르는 단계입니다")
    return (_pos_int(pid, "가망 번호"), _opt_text(name, "가망 이름"), stage, end, unread)


def _bad_hold() -> StoreError:
    return StoreError("붙잡아 둔 목록을 읽지 못했습니다")


def _read_hold_row(at_raw, codes_raw, body_raw):
    try:
        codes, body = json.loads(codes_raw), json.loads(body_raw)
    except (TypeError, ValueError, RecursionError):
        raise _bad_hold() from None
    at = _aware_time(at_raw)
    if at is None or not isinstance(codes, list) or not all(isinstance(x, str) for x in codes):
        raise _bad_hold()
    return at, codes, body


def _stage_body(body):
    """붙잡아 둔 단계 목록 → (받은 시각 글자, 받은 시각, 줄, 겹침, 표기별 줄 수). 다시 검사한다(모양이 틀리면 StoreError)."""
    try:
        at = body["as_of"]
        as_of = _aware_time(at)
        if as_of is None:
            raise _bad_hold()
        rows = []
        for r in _seq(body["rows"], "줄"):
            pid, name, stage, end, unread = r
            if end is not None and (not isinstance(end, str) or date.fromisoformat(end).isoformat() != end):
                raise _bad_hold()
            if unread not in (None, 0, 1) or isinstance(unread, bool):
                raise _bad_hold()
            rows.append(_stage_row(pid, name, stage, end, unread))
        conflicts = sorted({_pos_int(x, "가망 번호") for x in _seq(body["conflicts"], "겹침")})
        detail = _spelling_counts(body["per_spelling"])
    except (KeyError, TypeError, ValueError, StoreRefused):
        raise _bad_hold() from None
    if len({r[0] for r in rows}) != len(rows) or {r[0] for r in rows} & set(conflicts):
        raise _bad_hold()
    return at, as_of, rows, conflicts, detail


def _read_per_manager(v) -> Optional[dict]:
    """저장된 관리계정별 줄 수 {"번호": 줄 수} → {번호: 줄 수}."""
    if v is None:
        return None
    if not isinstance(v, dict):
        raise StoreError("저장된 관리계정별 줄 수를 읽지 못했습니다")
    out = {}
    for k, n in v.items():
        if not isinstance(k, str) or not k.isdigit() or isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise StoreError("저장된 관리계정별 줄 수를 읽지 못했습니다")
        out[int(k)] = n
    return out


def _account_body(body):
    try:
        at = body["read_at"]
        read_at = _aware_time(at)
        if read_at is None:
            raise _bad_hold()
        rows = []
        for r in _seq(body["rows"], "줄"):
            cid, no, name = r
            rows.append((_pos_int(cid, "고객 번호"), _opt_pos_int(no, "광고계정 번호"), _opt_text(name, "계정 이름")))
        per = _read_per_manager(body["per"])
    except (KeyError, TypeError, ValueError, StoreRefused, StoreError):
        raise _bad_hold() from None
    if not per or len({r[0] for r in rows}) != len(rows):
        raise _bad_hold()
    return at, read_at, rows, per


_ORG_BASE_KEYS = ("active", "owners", "managers")


def _org_baseline_value(t) -> dict:
    if not isinstance(t, (tuple, list)) or len(t) != 3:
        raise StoreRefused("조직 기준선은 (재직, 담당 줄, 팀장) 세 수입니다")
    vals = [_count(x, "조직 기준선") for x in t]
    if any(x is None for x in vals):
        raise StoreRefused("조직 기준선은 (재직, 담당 줄, 팀장) 세 수입니다")
    return dict(zip(_ORG_BASE_KEYS, vals))


def _read_org_baseline(v) -> Optional[dict]:
    if v is None:
        return None
    if not isinstance(v, dict) or set(v) != set(_ORG_BASE_KEYS) or any(
            isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in v.values()):
        raise StoreError("저장된 조직 기준선을 읽지 못했습니다")
    return dict(v)


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
                if isinstance(ev, (UnicodeError, OverflowError)):   # 값 때문에 묶기에서 터진 것 — 종류 이름만(원래 예외의 값을 끊는다)
                    raise StoreRefused(f"저장하지 못했습니다: {type(ev).__name__}") from None
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

    def _refuse_and_hold(self, kind: str, at: str, outcome: str, codes: Sequence[str], body: str,
                         rows: Optional[int] = None, managers: Optional[int] = None, absent: Optional[int] = None,
                         detail: Optional[Mapping] = None) -> int:
        """멈춤·버림을 한 줄 남기고 그 결과를 **그대로** 붙잡아 둔다 — 붙잡음 번호 = 그 기록 번호(대표가 본 그 기록)."""
        with self._tx() as c:   # 본 저장은 이미 되돌렸다(멈춤) · 또는 처음부터 적지 않았다(버림)
            sid = self._log_sync(c, kind, at, outcome, codes, rows=rows, managers=managers, absent=absent, detail=detail)
            c.execute(
                """INSERT INTO naver_auto_hold (kind, sync_id, at, codes, body, used_at, used_by)
                   VALUES (?, ?, ?, ?, ?, NULL, NULL)
                   ON CONFLICT (kind) DO UPDATE SET sync_id = excluded.sync_id, at = excluded.at,
                       codes = excluded.codes, body = excluded.body, used_at = NULL, used_by = NULL""",
                (kind, sid, at, json.dumps(list(codes)), body))
        return sid

    def _hold_take(self, c, kind: str, hold_id, by: int) -> Tuple[list, object]:
        """확인할 붙잡음을 꺼내 「씀」으로 표시한다(같은 거래 — 받기가 실패하면 표시도 되돌려진다).

        그 번호여야 하고(더 새로 붙잡았으면 옛 번호는 없음) · 아직 안 썼고 · ``HOLD_TTL`` 안이어야 한다(저장소 시계 기준)."""
        hid = _pos_int(hold_id, "붙잡음 번호")
        row = c.execute("SELECT sync_id, at, codes, body, used_at, used_by FROM naver_auto_hold WHERE kind = ?",
                        (kind,)).fetchone()
        if row is None or row[0] != hid:
            raise HoldRefused(HOLD_NOT_FOUND, "확인할 붙잡음이 없거나 더 새로 붙잡은 것으로 바뀌었습니다")
        if row[4] is not None:
            if row[5] is None:
                raise HoldRefused(HOLD_SUPERSEDED, "확인하기 전에 더 새 목록을 받았습니다")
            raise HoldRefused(HOLD_USED, "이미 확인해 받은 붙잡음입니다")
        at, codes, body = _read_hold_row(row[1], row[2], row[3])
        now = self._now()
        if now - at > HOLD_TTL or at > now + FUTURE_SLACK:
            raise HoldRefused(HOLD_EXPIRED, "확인할 수 있는 시간이 지났습니다 — 다시 읽어 새로 붙잡습니다")
        c.execute("UPDATE naver_auto_hold SET used_at = ?, used_by = ? WHERE kind = ? AND sync_id = ?",
                  (_kst_text(now, "지금"), by, kind, hid))
        return codes, body

    def _supersede_hold(self, c, kind: str) -> None:
        """확인 없이 새 목록을 받았다 — 기다리던 붙잡음은 더는 받을 수 없다(쓴 사람 없이 「씀」 표시)."""
        c.execute("UPDATE naver_auto_hold SET used_at = ? WHERE kind = ? AND used_at IS NULL",
                  (_kst_text(self._now(), "지금"), kind))

    def _meta_json(self, c, key: str):
        raw = self._get_meta(c, key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError, RecursionError):
            raise StoreError("저장된 기준선을 읽지 못했습니다") from None

    def _meta_count(self, c, key: str) -> Optional[int]:
        v = self._meta_json(c, key)
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise StoreError("저장된 기준선을 읽지 못했습니다")
        return v

    def record_sync_event(self, kind: str, outcome: str, codes: Sequence[str], at: datetime,
                          rows: Optional[int] = None) -> int:
        """버림(확인으로 풀 수 없는 것) · 실패(① 읽기 오류)를 남긴다 — 받음·멈춤·붙잡는 버림은 저장소가 스스로 적는다."""
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
    def _stage_parts(self, snap: "E.StageSnapshot"):
        if not isinstance(snap, E.StageSnapshot):
            raise StoreRefused("전산 단계 목록은 전부 받은 결과(StageSnapshot)만 받습니다")
        at = _kst_text(snap.as_of, "받은 시각")
        self._not_future(snap.as_of, "받은 시각")
        rows = []
        for pid, r in snap.rows.items():
            if not isinstance(r, E.StageRow) or r.possibility_id != pid:
                raise StoreRefused("전산 단계 줄 모양이 아닙니다")
            rows.append(_stage_row(pid, r.name, r.stage_key,
                                   None if r.latest_end_date is None else _day_text(r.latest_end_date, "종료일"),
                                   _opt_bool(r.end_unreadable, "종료일 못 읽음")))
        conflicts = sorted({_pos_int(p, "가망 번호") for p in snap.stage_conflicts})
        if set(conflicts) & set(snap.rows):
            raise StoreRefused("단계가 겹친 가망이 줄에도 있습니다")
        detail = _spelling_counts(snap.per_spelling)
        body = json.dumps({"as_of": at, "rows": [list(r) for r in rows], "conflicts": conflicts, "per_spelling": detail},
                          ensure_ascii=False, separators=(",", ":"))
        return at, rows, conflicts, detail, body

    def _apply_prospects(self, c, at: str, as_of: datetime, rows, conflicts, detail, allow: Optional[int],
                         bypassed: Sequence[str] = ()) -> SyncCounts:
        last = self._meta_time(c, "prospects_synced_at")
        if last is not None and last >= as_of:
            raise StoreRefused("이미 적은 것보다 늦지 않은 단계 목록입니다")   # 옛 목록이 새 목록을 덮지 않게
        before = {p: (pr, k) for p, pr, k in
                  c.execute("SELECT possibility_id, present, stage_key FROM naver_auto_prospect")}
        seen = [r[0] for r in rows] + list(conflicts)
        if not seen and any(pr for pr, _ in before.values()):
            raise StoreRefused("빈 단계 목록으로 전부를 빼지 않습니다")
        seen_set = set(seen)
        leaving = sorted(p for p, (pr, _) in before.items() if pr == 1 and p not in seen_set)
        present_before = sum(1 for pr, _ in before.values() if pr == 1)
        baseline = self._meta_count(c, "prospects_baseline")
        if allow is None:
            reasons = []
            if _braked(present_before, len(leaving)):
                reasons.append(BRAKE_TOTAL)
            was = Counter(k for pr, k in before.values() if pr == 1 and k is not None)
            now_k = Counter(r[2] for r in rows)
            if any(_braked(n, n - now_k.get(k, 0)) for k, n in was.items()):
                reasons.append(BRAKE_STAGE)   # 한 단계가 통째로(또는 크게) 빠짐 — 전체 비율 아래라도(반박 H3)
            if baseline is not None and _braked(baseline, baseline - len(seen)):
                reasons.append(BRAKE_BASELINE)   # 조금씩 잘려 누적으로 크게 줄어듦(톱니 방지)
            if reasons:
                raise _Brake(reasons, present_before, len(leaving))
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
        # 기준선 = 마지막 대표 확인(또는 처음) 뒤 가장 많던 수 — 확인하면 지금 수로 새로 잡는다
        new_base = len(seen) if allow is not None or baseline is None else max(baseline, len(seen))
        self._set_meta(c, "prospects_baseline", json.dumps(new_base))
        if allow is None:
            self._supersede_hold(c, SYNC_STAGES)
        self._set_meta(c, "prospects_synced_at", at)
        codes = list(bypassed) + ([CODE_CONFIRMED] if allow is not None else [])
        self._log_sync(c, SYNC_STAGES, at, SYNC_ACCEPTED, codes, rows=len(seen), absent=now_absent, detail=detail,
                       confirmed_by=allow)
        return SyncCounts(len(seen), len(seen_set - set(before)), now_absent)

    def record_prospects(self, snap: "E.StageSnapshot") -> SyncCounts:
        """전산 7단계를 전부 받은 결과로 가망 표를 고친다 — 없어진 가망은 지우지 않고 「목록에 없음」.

        한꺼번에 크게 빠지거나(``BRAKE``) · 한 단계가 크게 빠지거나(``BRAKE_STAGE``) · 기준선보다 누적으로 크게 줄면
        (``BRAKE_BASELINE``) 아무것도 적지 않고 그 목록을 붙잡아 둔 뒤 ``SyncBraked``(``hold_id``). 대표가 확인하면
        ``confirm_prospects_hold`` 가 **새로 읽지 않고 붙잡아 둔 그 목록을** 받는다."""
        self._need_writer()
        at, rows, conflicts, detail, body = self._stage_parts(snap)
        try:
            with self._tx() as c:
                return self._apply_prospects(c, at, snap.as_of, rows, conflicts, detail, None)
        except _Brake as b:
            sid = self._refuse_and_hold(SYNC_STAGES, at, SYNC_BRAKED, b.reasons, body, rows=len(rows) + len(conflicts),
                                        absent=b.would_absent, detail=detail)
            raise SyncBraked(SYNC_STAGES, b.present_before, b.would_absent, b.reasons, hold_id=sid) from None

    def refuse_stages(self, snap: "E.StageSnapshot", codes: Sequence[str]) -> int:
        """첫 회차 대조로 버린 목록을 붙잡아 두고 붙잡음 번호를 돌려준다(``sync.py`` 에서만 부른다 — 구문 시험)."""
        self._need_writer()
        cs = _codes(codes)
        if not cs:
            raise StoreRefused("버린 이유 코드가 없습니다")
        at, rows, conflicts, detail, body = self._stage_parts(snap)
        return self._refuse_and_hold(SYNC_STAGES, at, SYNC_REFUSED, cs, body, rows=len(rows) + len(conflicts),
                                     detail=detail)

    def confirm_prospects_hold(self, hold_id: int, confirmed_by: int) -> SyncCounts:
        """대표가 본 그 멈춤·버림의 목록을 받는다 — ① 을 새로 읽지 않는다. 우회한 코드와 확인한 사람이 기록에 남는다."""
        self._need_writer()
        who = _person(confirmed_by, "확인한 직원")
        with self._tx() as c:
            codes, body = self._hold_take(c, SYNC_STAGES, hold_id, who)
            at, as_of, rows, conflicts, detail = _stage_body(body)
            return self._apply_prospects(c, at, as_of, rows, conflicts, detail, who, bypassed=codes)

    def stage_as_of(self) -> Optional[datetime]:
        """전산 단계를 마지막으로 받은 시각 — 점검 규칙의 「단계 자료가 26시간 넘게 낡음」(system_gap) 재료."""
        return self._meta_time(self._conn, "prospects_synced_at")

    # ── 네이버 대행 연결 목록 ──
    def _account_parts(self, kids: "N.ChildAccounts", read_at: datetime):
        if not isinstance(kids, N.ChildAccounts):
            raise StoreRefused("연결 목록은 전부 받은 결과(ChildAccounts)만 받습니다")
        at = _kst_text(read_at, "읽은 시각")
        self._not_future(read_at, "읽은 시각")
        per = kids.per_manager
        if not isinstance(per, Mapping) or not per:
            raise StoreRefused("관리계정별 줄 수가 없습니다")
        per = {_pos_int(m, "관리계정 번호"): _count(n, "관리계정별 줄 수") for m, n in per.items()}
        if any(n is None for n in per.values()):
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
            rows.append((_pos_int(cid, "고객 번호"), _or_none(_opt_pos_int, kept.get("adAccountNo"), "광고계정 번호"),
                         _or_none(_opt_text, kept.get("adAccountName"), "계정 이름")))
        body = json.dumps({"read_at": at, "rows": [list(r) for r in rows], "per": {str(m): n for m, n in per.items()}},
                          ensure_ascii=False, separators=(",", ":"))
        return at, rows, per, body

    @staticmethod
    def _managed_prospects(c, now: datetime) -> set:
        """확인 짝 브레이크의 분모에 넣을 가망 — 지금 단계 목록에 있고 · 겹침 없고 · 종료일을 읽었고 · 점검 손잡이와 같은
        단계·14일 규칙(``handles.eligibility_reason``)을 통과한 것(검토 rules-1 — 끝난 광고주의 옛 확인이 분모를 불려
        진짜 급감을 가리지 않게). 단계 자료의 나이는 여기서 보지 않는다(짝 맞추기가 낡은 단계를 따로 거절한다)."""
        out = set()
        for pid, key, end in c.execute(
                """SELECT possibility_id, stage_key, latest_end_date FROM naver_auto_prospect
                   WHERE present = 1 AND stage_conflict = 0 AND end_unreadable = 0"""):
            if H.eligibility_reason(key, now, None if end is None else date.fromisoformat(end), now) is None:
                out.add(int(pid))
        return out

    def _apply_accounts(self, c, at: str, read_at: datetime, rows, per, allow: Optional[int],
                        bypassed: Sequence[str] = ()) -> SyncCounts:
        d = at[:10]
        last = self._meta_time(c, "accounts_read_at")
        if last is not None and last >= read_at:
            raise StoreRefused("이미 적은 것보다 늦지 않은 연결 목록입니다")
        before = {cid: pr for cid, pr in c.execute("SELECT customer_id, present FROM naver_auto_account")}
        if not rows and any(before.values()):
            raise StoreRefused("빈 연결 목록으로 전부를 빼지 않습니다")
        seen = {r[0] for r in rows}
        leaving = sum(1 for cid, pr in before.items() if pr == 1 and cid not in seen)
        present_before = sum(1 for pr in before.values() if pr == 1)
        prev_per = _read_per_manager(self._meta_json(c, "accounts_per_manager"))
        baseline = self._meta_count(c, "accounts_baseline")
        managers_before = None if prev_per is None else len(prev_per)
        if allow is None:
            reasons = []
            if _braked(present_before, leaving):
                reasons.append(BRAKE_TOTAL)
            if prev_per is not None and leaving > 0 and any(
                    (n0 > 0 and per.get(m, 0) == 0) or _braked(n0, n0 - per.get(m, 0)) for m, n0 in prev_per.items()):
                reasons.append(BRAKE_MANAGER)   # 있던 관리계정이 사라짐·0줄·크게 줄었는데 빠질 계정이 있다(번호 단위)
            if baseline is not None and _braked(baseline, baseline - len(rows)):
                reasons.append(BRAKE_BASELINE)
            # 확인한 짝이 있는 계정만 따로 센다(S8) — 끝난·쉬는 계정이 섞인 전체 분모로는 안 보이는 급감
            winners, _lost = self._resolve_decisions(c)
            managed = self._managed_prospects(c, read_at)
            held = {d.customer_id for d in winners if d.decision == "confirmed" and d.possibility_id in managed
                    and before.get(d.customer_id) == 1}
            if _braked(len(held), len(held - seen)):
                reasons.append(BRAKE_CONFIRMED)
            if reasons:
                raise _Brake(reasons, present_before, leaving, managers_before, len(per))
        for cid, no, name in rows:
            c.execute(
                """INSERT INTO naver_auto_account (customer_id, ad_account_no, account_name, present,
                       first_seen_on, last_seen_on, absent_days, last_absent_on)
                   VALUES (?, ?, ?, 1, ?, ?, 0, NULL)
                   ON CONFLICT (customer_id) DO UPDATE SET
                       ad_account_no = excluded.ad_account_no, account_name = excluded.account_name,
                       present = 1, last_seen_on = excluded.last_seen_on, absent_days = 0, last_absent_on = NULL""",
                (cid, no, name, d, d))
            c.execute(
                """INSERT INTO naver_auto_account_time (customer_id, last_seen_at, absent_since, absent_last_at)
                   VALUES (?, ?, NULL, NULL)
                   ON CONFLICT (customer_id) DO UPDATE SET
                       last_seen_at = excluded.last_seen_at, absent_since = NULL, absent_last_at = NULL""", (cid, at))
        now_absent = 0
        for cid in sorted(set(before) - seen):
            c.execute(
                """UPDATE naver_auto_account SET present = 0, absent_days = absent_days + 1, last_absent_on = ?
                   WHERE customer_id = ? AND (last_absent_on IS NULL OR last_absent_on < ?)""", (d, cid, d))
            # 처음 빠진 읽기 시각은 그대로 두고 마지막으로 빠진 읽기 시각만 옮긴다(시각 줄이 없던 옛 계정은 지금부터 센다)
            c.execute(
                """INSERT INTO naver_auto_account_time (customer_id, last_seen_at, absent_since, absent_last_at)
                   VALUES (?, NULL, ?, ?)
                   ON CONFLICT (customer_id) DO UPDATE SET
                       absent_since = COALESCE(naver_auto_account_time.absent_since, excluded.absent_since),
                       absent_last_at = excluded.absent_last_at""", (cid, at, at))
            if before[cid] == 1:
                now_absent += 1
        new_base = len(rows) if allow is not None or baseline is None else max(baseline, len(rows))
        self._set_meta(c, "accounts_baseline", json.dumps(new_base))
        if allow is None:
            self._supersede_hold(c, SYNC_ACCOUNTS)
        self._set_meta(c, "accounts_per_manager", json.dumps({str(m): n for m, n in sorted(per.items())}))
        self._set_meta(c, "accounts_read_at", at)
        codes = list(bypassed) + ([CODE_CONFIRMED] if allow is not None else [])
        self._log_sync(c, SYNC_ACCOUNTS, at, SYNC_ACCEPTED, codes, rows=len(rows), managers=len(per),
                       absent=now_absent, confirmed_by=allow)
        return SyncCounts(len(rows), len(seen - set(before)), now_absent)

    def record_accounts(self, kids: "N.ChildAccounts", read_at: datetime) -> SyncCounts:
        """대행 연결 목록을 전부 받은 결과로 계정 표를 고친다 — 없어진 계정은 「목록에 없음」 · 연속 없는 날을 센다.

        날짜는 읽은 시각의 한국 날짜다. 같은 날 두 번 받아도 없는 날은 한 번만 세고, 더 이른 시각의 목록은 받지 않는다.
        처음 빠진 읽기 시각·마지막으로 빠진 읽기 시각도 남긴다(``account_times``) — 확인한 짝을 「연결 끊김」으로 볼지
        (2일 · 20시간)는 짝 맞추기(``links``)가 이 둘을 보고 정한다. 멈춘 날은 아무것도 적지 않으므로 세지 않는다.
        한꺼번에 크게 빠지거나 · **있던 관리계정(번호)이 사라지거나 0줄·크게 줄고 빠질 계정이 있거나** · 기준선보다 누적으로
        크게 줄거나 · **확인한 짝이 있는 계정이 크게 빠지면**(``BRAKE_CONFIRMED``) 아무것도 적지 않고 붙잡아 둔 뒤
        ``SyncBraked`` — 확인은 ``confirm_accounts_hold``.
        """
        self._need_writer()
        at, rows, per, body = self._account_parts(kids, read_at)
        try:
            with self._tx() as c:
                return self._apply_accounts(c, at, read_at, rows, per, None)
        except _Brake as b:
            sid = self._refuse_and_hold(SYNC_ACCOUNTS, at, SYNC_BRAKED, b.reasons, body, rows=len(rows),
                                        managers=b.managers_now, absent=b.would_absent)
            raise SyncBraked(SYNC_ACCOUNTS, b.present_before, b.would_absent, b.reasons, hold_id=sid,
                             managers_before=b.managers_before, managers_now=b.managers_now) from None

    def confirm_accounts_hold(self, hold_id: int, confirmed_by: int) -> SyncCounts:
        """대표가 본 그 멈춤의 연결 목록을 받는다 — 네이버를 새로 읽지 않는다."""
        self._need_writer()
        who = _person(confirmed_by, "확인한 직원")
        with self._tx() as c:
            codes, body = self._hold_take(c, SYNC_ACCOUNTS, hold_id, who)
            at, read_at, rows, per = _account_body(body)
            return self._apply_accounts(c, at, read_at, rows, per, who, bypassed=codes)

    # ── ① 조직 스냅숏 수락본(S7 · M12) ──
    def _org_parts(self, body: Mapping):
        if not isinstance(body, Mapping):
            raise StoreRefused("조직 스냅숏 본문 모양이 아닙니다")
        gen = body.get("generated_at")
        gen_dt = _aware_time(gen) if isinstance(gen, str) and len(gen) <= 64 else None
        if gen_dt is None:
            raise StoreRefused("조직 스냅숏 시각을 읽지 못했습니다")
        gen_text = _kst_text(gen_dt, "조직 스냅숏 시각")
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
        return gen_dt, gen_text, kept, json.dumps(kept, ensure_ascii=False, separators=(",", ":"))

    def record_org(self, body: Mapping, received_at: datetime, *, warnings: Sequence[str] = (),
                   confirmed_by: Optional[int] = None, hold_id: Optional[int] = None,
                   baseline: Optional[Tuple[int, int, int]] = None) -> None:
        """건전성 검사(``app.naver_auto.org_snapshot``)를 통과한 스냅숏 본문을 수락본으로 남긴다.

        남길 칸만(``fields.ORG_*``) · 값은 글자·정수·참거짓·빈 값만 · 더 새 스냅숏만(``generated_at``) · 미래 시각 거절.
        ``confirmed_by`` 는 ``hold_id`` 와 함께만 — 대표가 본 **그 붙잡음의 본문**과 같아야 받는다(다른 본문이면 거절).
        저장된 수락본이 망가져 있으면 ``STORED_UNREADABLE`` 붙잡음을 확인할 때만 덮어쓴다.
        ``baseline`` = (재직 · 담당 줄 · 재직 팀장) 수 — 누적 비교 기준선(확인하면 지금 수로 새로 잡는다).
        이 함수는 ``sync.py`` 에서만 부른다(구문 시험) — 검사를 거치지 않은 본문이 들어오지 않게."""
        self._need_writer()
        if (confirmed_by is None) != (hold_id is None):
            raise StoreRefused("대표 확인은 붙잡음 번호와 함께만 받습니다")
        gen_dt, gen_text, kept, text = self._org_parts(body)
        if gen_dt > self._now() + ORG_FUTURE_SLACK:
            raise StoreRefused("조직 스냅숏 시각: 미래 시각은 받지 않습니다")
        rec = _kst_text(received_at, "받은 시각")
        self._not_future(received_at, "받은 시각")
        allow = None if confirmed_by is None else _person(confirmed_by, "확인한 직원")
        codes = _codes(warnings)
        base = None if baseline is None else _org_baseline_value(baseline)
        with self._tx() as c:
            held: list = []
            if allow is not None:
                held, held_body = self._hold_take(c, SYNC_ORG, hold_id, allow)
                if held_body != kept:
                    raise StoreRefused("확인한 조직과 받으려는 조직이 다릅니다")
            row = c.execute("SELECT generated_at FROM naver_auto_org WHERE slot = 'current'").fetchone()
            if row is not None:
                old = _aware_time(row[0])
                if old is None:
                    if CODE_STORED_UNREADABLE not in held:
                        raise StoreRefused("저장된 수락본을 읽지 못했습니다 — 대표 확인으로만 바꿉니다")
                elif old >= gen_dt:
                    raise StoreRefused("이미 적은 것보다 새 조직 스냅숏이 아닙니다")   # 옛 스냅숏이 새것을 덮지 않게
            now = _kst_text(self._now(), "지금")
            c.execute(
                """INSERT INTO naver_auto_org (slot, generated_at, received_at, accepted_at, confirmed_by, body)
                   VALUES ('current', ?, ?, ?, ?, ?)
                   ON CONFLICT (slot) DO UPDATE SET generated_at = excluded.generated_at,
                       received_at = excluded.received_at, accepted_at = excluded.accepted_at,
                       confirmed_by = excluded.confirmed_by, body = excluded.body""",
                (gen_text, rec, now, allow, text))
            if base is not None:
                prev = None if allow is not None else _read_org_baseline(self._meta_json(c, "org_baseline"))
                if prev is not None:   # 가장 많던 재직·담당 줄 · 가장 적던 팀장(마지막 확인 뒤)
                    base = {"active": max(prev["active"], base["active"]), "owners": max(prev["owners"], base["owners"]),
                            "managers": min(prev["managers"], base["managers"])}
                self._set_meta(c, "org_baseline", json.dumps(base, sort_keys=True))
            if allow is None:
                self._supersede_hold(c, SYNC_ORG)
            self._log_sync(c, SYNC_ORG, rec, SYNC_ACCEPTED, codes + [x for x in held if x not in codes]
                           + ([CODE_CONFIRMED] if allow is not None else []),
                           rows=len(kept["owners"]),
                           detail={"teams": len(kept["teams"]), "employees": len(kept["employees"])},
                           confirmed_by=allow)

    def refuse_org(self, body: Mapping, received_at: datetime, codes: Sequence[str]) -> int:
        """확인으로 풀 수 있는 이유로 버린 스냅숏을 남길 칸만 붙잡아 두고 붙잡음 번호를 돌려준다(``sync.py`` 에서만)."""
        self._need_writer()
        cs = _codes(codes)
        if not cs:
            raise StoreRefused("버린 이유 코드가 없습니다")
        _gen_dt, _gen_text, kept, text = self._org_parts(body)
        rec = _kst_text(received_at, "받은 시각")
        self._not_future(received_at, "받은 시각")
        return self._refuse_and_hold(SYNC_ORG, rec, SYNC_REFUSED, cs, text, rows=len(kept["owners"]),
                                     detail={"teams": len(kept["teams"]), "employees": len(kept["employees"])})

    # ── 사람의 짝 판단 ──
    def record_decision(self, possibility_id: int, customer_id: int, decision: str, decided_by: int,
                        at: datetime) -> int:
        """짝 확인 화면의 판단 한 줄을 쌓는다(같은 짝에 다시 판단하면 새 줄 — 가장 늦은 줄이 이긴다)."""
        self._need_writer()
        if decision not in DECISIONS:
            raise StoreRefused("판단은 confirmed · rejected 뿐입니다")
        vals = (_pos_int(possibility_id, "가망 번호"), _customer_id(customer_id, "고객 번호"), decision,
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

    def _resolve_decisions(self, c) -> Tuple[List[LinkDecision], List[LinkDecision]]:
        """(살아 있는 판단, 밀린 확인).

        1) 짝(가망 × 계정)마다 거두지 않은 판단 중 가장 늦게 적은 것(판단 번호가 큰 것)을 고른다.
        2) 그중 「확인」이 한 계정에 여럿이면(서로 다른 가망) 가장 늦게 적은 확인 하나만 산다 — 앞 확인은 「밀린 확인」.
           뒤 확인을 거두면 앞 확인이 다시 산다(줄은 지우지 않는다 · 설계 v1.8 S8 「가장 늦은 확인만 살림」).
        「늦음」은 적은 순서(판단 번호)다 — 판단 시각은 부르는 쪽이 넣어 앞뒤가 뒤바뀔 수 있다."""
        latest = {}
        for did, pid, cid, dec, by, at_raw in c.execute(
                """SELECT decision_id, possibility_id, customer_id, decision, decided_by, decided_at
                   FROM naver_auto_link_decision WHERE revoked_at IS NULL ORDER BY decision_id"""):
            at_ = _aware_time(at_raw)
            if at_ is None or dec not in DECISIONS:
                raise StoreError("저장된 짝 판단을 읽지 못했습니다")
            latest[(pid, cid)] = LinkDecision(int(did), int(pid), int(cid), str(dec), int(by), at_)
        best = {}
        for d in latest.values():
            if d.decision == "confirmed" and (d.customer_id not in best or d.decision_id > best[d.customer_id].decision_id):
                best[d.customer_id] = d
        winners, lost = [], []
        for d in latest.values():
            if d.decision == "confirmed" and best[d.customer_id] is not d:
                lost.append(d)
            else:
                winners.append(d)
        key = (lambda d: (d.possibility_id, d.customer_id))
        return sorted(winners, key=key), sorted(lost, key=key)

    @staticmethod
    def _decisions_hash(ids) -> str:
        return hashlib.sha256(",".join(str(i) for i in sorted(ids)).encode("ascii")).hexdigest()

    def link_decisions(self) -> Tuple[List[LinkDecision], List[LinkDecision]]:
        """(살아 있는 판단, 밀린 확인)을 **한 번에** 읽는다 — 짝 맞추기가 두 목록을 같은 순간의 것으로 쓰게."""
        return self._resolve_decisions(self._conn)

    def decision_fingerprint(self) -> str:
        """지금 사람 판단의 지문(살아 있는 판단 + 밀린 확인의 번호) — 마지막 짝 맞추기 뒤 판단이 바뀌었는지 본다."""
        w, lost = self._resolve_decisions(self._conn)
        return self._decisions_hash(d.decision_id for d in w + lost)

    def current_decisions(self) -> List[LinkDecision]:
        """살아 있는 사람의 판단 — 짝마다 가장 늦은 · 거두지 않은 판단(한 계정의 확인은 가장 늦은 하나만) · 번호·시각 포함.
        짝 규칙(matching)에 넘긴다."""
        return self._resolve_decisions(self._conn)[0]

    def superseded_confirmations(self) -> List[LinkDecision]:
        """밀린 확인 — 같은 계정을 다른 가망에 더 늦게 확인해 지금은 살아 있지 않은 확인(짝 확인 화면에 보여 준다)."""
        return self._resolve_decisions(self._conn)[1]

    # ── 짝 맞추기 결과(S8) ──
    def _pairing_rows(self, rows):
        """결과 줄 → 저장할 튜플. 상태마다 칸 모양을 검사한다(값은 문구에 넣지 않는다)."""
        out, seen = [], set()
        for r in _seq(rows, "짝 결과 줄"):
            if not isinstance(r, Mapping):
                raise StoreRefused("짝 결과 줄 모양이 아닙니다")
            if set(r) - {"state", "possibility_id", "customer_id", "code", "same_name", "claimed_elsewhere",
                         "decision_id", "link"}:
                raise StoreRefused("짝 결과 줄에 모르는 칸이 있습니다")   # 이름 같은 칸이 들어오지 않게
            st = r.get("state")
            if st not in PAIR_STATES:
                raise StoreRefused("짝 결과 상태가 아닙니다")
            pid = _pos_int(r.get("possibility_id"), "가망 번호")
            cid = None if r.get("customer_id") is None else _customer_id(r.get("customer_id"), "고객 번호")
            code = r.get("code")
            same = r.get("same_name")
            claimed = r.get("claimed_elsewhere")
            did = _opt_pos_int(r.get("decision_id"), "판단 번호")
            link = r.get("link")
            if st in (PAIR_MISSING, PAIR_BROKEN):
                if link not in LINKS:
                    raise StoreRefused("이관 빠짐 줄에는 이어졌던 짝 종류(confirmed · auto)가 있어야 합니다")
            elif link is not None:
                raise StoreRefused("짝 종류 칸은 이관 빠짐 줄에만 있습니다")
            if st != PAIR_BLOCKED and cid is None:
                raise StoreRefused("짝 결과 줄에 고객 번호가 없습니다")
            if st in (PAIR_CONFIRMED, PAIR_AUTO, PAIR_CANDIDATE):
                if code not in PAIR_RELATIONS:
                    raise StoreRefused("이름 관계 코드가 아닙니다")
            elif st == PAIR_BLOCKED:
                if code not in PAIR_BLOCK_CODES:
                    raise StoreRefused("막힌 까닭 코드가 아닙니다")
            elif st in (PAIR_MISSING, PAIR_BROKEN):
                if code is not None and code != PAIR_CODE_NEVER_LISTED:
                    raise StoreRefused("이관 빠짐 사유 코드가 아닙니다")
            elif code is not None:
                raise StoreRefused("밀린 확인 줄에는 사유가 없습니다")
            from_decision = st in (PAIR_CONFIRMED, PAIR_SUPERSEDED) or (link == PAIR_CONFIRMED)
            if from_decision != (did is not None):
                raise StoreRefused("판단 번호는 확인에서 나온 줄에만 있습니다")
            if st == PAIR_CANDIDATE:
                if isinstance(same, bool) or not isinstance(same, int) or not 1 <= same < 2 ** 31 \
                        or type(claimed) is not bool:
                    raise StoreRefused("이름 후보 칸 모양이 아닙니다")
                same, claimed = same, int(claimed)
            elif same is not None or claimed is not None:
                raise StoreRefused("이름 후보 칸은 이름 후보에만 있습니다")
            if cid is not None:
                k = (st, pid, cid)
                if k in seen:
                    raise StoreRefused("같은 짝 결과 줄이 두 번 있습니다")
                seen.add(k)
            out.append((pid, cid, st, code, same, claimed, did, link))
        if len(out) > PAIRING_MAX_ROWS:
            raise StoreRefused("짝 결과 줄이 너무 많습니다")
        return out

    def record_pairing(self, at: datetime, *, accounts_read_at: datetime, stages_as_of: datetime,
                       decision_ids: Iterable[int], rows, counts: Mapping, codes: Sequence[str] = ()) -> int:
        """받은 짝 맞추기 한 회차를 쌓는다 → 회차 번호.

        ``accounts_read_at`` · ``stages_as_of`` · ``decision_ids``(계산에 쓴 살아 있는 판단 + 밀린 확인의 번호 전부)가
        지금 저장소와 같아야 받는다 — 계산하는 사이 바뀌었으면 ``PairingStale``. 점검할 짝(확인 · 자동)의 계정은 지금 목록에
        있고 가망은 지금 관리 단계 목록에 있어야 한다 · 「오늘 없음」·「이관 빠짐」의 계정은 지금 목록에 없어야 한다 ·
        판단에서 나온 줄은 그 판단의 짝과 같아야 한다 · 자동 짝에서 나온 「이관 빠짐」은 자동 짝으로 이어진 적이 있어야 한다.
        받으면 점검할 짝(확인 · 자동)을 「이어진 적 있음」(``naver_auto_link_memory``)에 기억한다.
        ``counts`` 는 줄로 알 수 없는 개수만(``PAIRING_INPUT_COUNTS``)."""
        self._need_writer()
        t = _kst_text(at, "짝 맞춘 시각")
        read_t, stage_t = _kst_text(accounts_read_at, "연결 목록 읽은 시각"), _kst_text(stages_as_of, "단계 받은 시각")
        self._not_future(at, "짝 맞춘 시각")
        cs = _codes(codes)
        if not isinstance(counts, Mapping) or set(counts) != set(PAIRING_INPUT_COUNTS):
            raise StoreRefused("짝 맞추기 개수 모양이 아닙니다")
        given = {k: _count(counts[k], "짝 맞추기 개수") for k in PAIRING_INPUT_COUNTS}
        if any(v is None for v in given.values()):
            raise StoreRefused("짝 맞추기 개수 모양이 아닙니다")
        if isinstance(decision_ids, (str, bytes, bytearray, Mapping)) or \
                not isinstance(decision_ids, (list, tuple, set, frozenset)):
            raise StoreRefused("판단 번호: 목록이어야 합니다")
        ids = {_pos_int(x, "판단 번호") for x in decision_ids}
        vals = self._pairing_rows(rows)
        with self._tx() as c:
            winners, lost = self._resolve_decisions(c)
            by_id = {d.decision_id: d for d in winners + lost}
            if (self._meta_time(c, "accounts_read_at") != accounts_read_at
                    or self._meta_time(c, "prospects_synced_at") != stages_as_of or set(by_id) != ids):
                raise PairingStale("짝을 계산하는 사이 연결 목록·단계·사람 판단이 바뀌었습니다")
            present = {cid for (cid,) in c.execute("SELECT customer_id FROM naver_auto_account WHERE present = 1")}
            live = {pid for (pid,) in c.execute(
                "SELECT possibility_id FROM naver_auto_prospect WHERE present = 1 AND stage_conflict = 0")}
            win_ids = {d.decision_id for d in winners if d.decision == "confirmed"}
            lost_ids = {d.decision_id for d in lost}
            auto_before = self._matched(c, PAIR_AUTO)
            for pid, cid, st, _code_, _s, _c, did, link in vals:
                if st in (PAIR_MISSING, PAIR_BROKEN) and link == PAIR_AUTO and (pid, cid) not in auto_before:
                    raise StoreRefused("자동 짝으로 이어진 적이 없는데 이관 빠짐으로 적으려 했습니다")
                if st in PAIR_CHECKABLE and (cid not in present or pid not in live):
                    raise PairingStale("점검할 짝의 계정·가망이 지금 목록에 없습니다")
                if st in (PAIR_MISSING, PAIR_BROKEN) and cid in present:
                    raise PairingStale("「오늘 없음」·「이관 빠짐」인데 계정이 지금 목록에 있습니다")
                if did is not None:
                    d = by_id.get(did)
                    ok = d is not None and (d.possibility_id, d.customer_id) == (pid, cid) and \
                        (did in lost_ids if st == PAIR_SUPERSEDED else did in win_ids)
                    if not ok:
                        raise PairingStale("판단에서 나온 줄이 지금 판단과 맞지 않습니다")
            tally = Counter(v[2] for v in vals)
            full = dict(given, **{s_: tally.get(s_, 0) for s_ in sorted(PAIR_STATES)})
            cur = c.execute(
                """INSERT INTO naver_auto_pairing_run (at, outcome, codes, accounts_read_at, stages_as_of, decisions_hash,
                       counts) VALUES (?, 'accepted', ?, ?, ?, ?, ?)""",
                (t, json.dumps(cs), read_t, stage_t, self._decisions_hash(ids), json.dumps(full, sort_keys=True)))
            pid_run = cur.lastrowid
            for v in vals:
                c.execute(
                    """INSERT INTO naver_auto_pairing_row (pairing_id, possibility_id, customer_id, state, code, same_name,
                           claimed_elsewhere, decision_id, link) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (pid_run,) + v)
                if v[2] in PAIR_CHECKABLE:   # 이어진 짝을 기억한다 — 나중에 계정이 목록에서 빠지면 「이관 빠짐」
                    c.execute(
                        """INSERT INTO naver_auto_link_memory (possibility_id, customer_id, link, first_matched_at,
                               last_matched_at) VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT (possibility_id, customer_id, link) DO UPDATE SET
                               last_matched_at = excluded.last_matched_at""", (v[0], v[1], v[2], t, t))
            return pid_run

    @staticmethod
    def _matched(c, link: str) -> set:
        return {(int(p), int(k)) for p, k in c.execute(
            "SELECT possibility_id, customer_id FROM naver_auto_link_memory WHERE link = ?", (link,))}

    def matched_before(self, link: str) -> set:
        """그 종류로 이어진 적이 있는 짝 {(가망 번호, 고객 번호)} — 「이관 빠짐」 판정 재료(받은 짝 맞추기에서만 쌓인다)."""
        if link not in LINKS:
            raise StoreRefused("짝 종류가 아닙니다")
        return self._matched(self._conn, link)

    def record_pairing_event(self, at: datetime, outcome: str, codes: Sequence[str]) -> int:
        """짝 맞추기 버림·실패를 코드만 남긴다(결과 줄 없음) → 회차 번호."""
        self._need_writer()
        if outcome not in (SYNC_REFUSED, SYNC_FAILED):
            raise StoreRefused("밖에서 적을 수 있는 결과는 refused · failed 뿐입니다")
        t, cs = _kst_text(at, "짝 맞춘 시각"), _codes(codes)
        if not cs:
            raise StoreRefused("이유 코드가 없습니다")
        self._not_future(at, "짝 맞춘 시각")
        with self._tx() as c:
            cur = c.execute("""INSERT INTO naver_auto_pairing_run (at, outcome, codes, accounts_read_at, stages_as_of,
                                   decisions_hash, counts) VALUES (?, ?, ?, NULL, NULL, NULL, NULL)""",
                            (t, outcome, json.dumps(cs)))
            return cur.lastrowid

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
    @staticmethod
    def _account_day_vals(run_id, customer_id, status, rules_run, rules_not_run, checked_at, possibility_id, link,
                          bizmoney, budget_lock, refund_lock, yday_spend, yday_imp, yday_clk, data_late) -> list:
        if status not in ACCOUNT_STATUSES:
            raise StoreRefused("모르는 점검 상태")
        if link is not None and link not in LINKS:
            raise StoreRefused("모르는 짝 상태")
        ran, not_ran = _rules(rules_run, rules_not_run)
        return [_customer_id(customer_id, "고객 번호"), None, _opt_pos_int(possibility_id, "가망 번호"), link,
                _pos_int(run_id, "회차 번호"), status, ran, not_ran, _num(bizmoney, "비즈머니"),
                _opt_bool(budget_lock, "잠금"), _opt_bool(refund_lock, "잠금"), _num(yday_spend, "어제 비용"),
                _num(yday_imp, "어제 노출"), _num(yday_clk, "어제 클릭"), _opt_bool(data_late, "자료 늦음"),
                _kst_text(checked_at, "점검 시각")]

    @staticmethod
    def _write_account_day(c, vals: list) -> None:
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

    def record_account_day(self, run_id: int, customer_id: int, *, status: str, rules_run: Sequence[str],
                           rules_not_run: Sequence[Tuple[str, str]], checked_at: datetime,
                           possibility_id: Optional[int] = None, link: Optional[str] = None,
                           bizmoney=None, budget_lock=None, refund_lock=None,
                           yday_spend=None, yday_imp=None, yday_clk=None, data_late=None) -> None:
        """그날(회차 날짜) 계정 한 곳의 점검 결과 — 같은 날 다시 적으면 고친다."""
        self._need_writer()
        vals = self._account_day_vals(run_id, customer_id, status, rules_run, rules_not_run, checked_at, possibility_id,
                                      link, bizmoney, budget_lock, refund_lock, yday_spend, yday_imp, yday_clk,
                                      data_late)
        self._not_future(checked_at, "점검 시각")
        with self._tx() as c:
            vals[1] = self._running_run_date(c, run_id)
            self._write_account_day(c, vals)

    # ── 캠페인 하루치 ──
    @staticmethod
    def _campaign_rows(cid: int, d: str, campaigns: Iterable[Mapping], stats, provisional, t: str) -> list:
        if type(provisional) is not bool:
            raise StoreRefused("잠정 여부는 참/거짓이어야 합니다")
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
        return rows

    @staticmethod
    def _write_campaign_rows(c, rid: int, cid: int, rows: list) -> int:
        cols = ", ".join(c_ for _, c_ in CAMPAIGN_METRICS)
        keep_or_new = ", ".join(
            f"{c_} = CASE WHEN excluded.metrics_read = 1 THEN excluded.{c_} ELSE naver_auto_campaign_day.{c_} END"
            for _, c_ in CAMPAIGN_METRICS)
        written = 0
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
        rows = self._campaign_rows(cid, d, campaigns, stats, provisional, t)
        with self._tx() as c:
            rid = _pos_int(run_id, "회차 번호")
            self._running_run_date(c, rid)
            return self._write_campaign_rows(c, rid, cid, rows)

    # ── 이슈(S9) ──
    @staticmethod
    def _issue_state(r):
        """저장된 이슈 줄 → 규칙이 읽는 모양(``app.naver_auto.issues.IssueState``) · 못 읽으면 StoreError."""
        I = _issue_rules()
        try:
            st = I.IssueState(r["state"], r["severity"], date.fromisoformat(r["first_seen_on"]),
                              date.fromisoformat(r["last_seen_on"]), int(r["reappear_count"]),
                              None if r["exception_until"] is None else date.fromisoformat(r["exception_until"]),
                              r["exception_severity"])
            return I.check_state(st)
        except (TypeError, ValueError):
            raise StoreError("저장된 이슈를 읽지 못했습니다") from None

    @staticmethod
    def _issue_rows(c, where: str, args: tuple) -> List[dict]:
        cur = c.execute("SELECT * FROM naver_auto_issue WHERE " + where + " ORDER BY issue_id", args)
        names = [x[0] for x in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def _write_issue(self, c, row: Optional[dict], key: Tuple[int, str, str], cid: int, rule: str, ch, at: str, *,
                     run_id: Optional[int] = None, by: Optional[int] = None, note: Optional[str] = None,
                     facts: Optional[str] = None, set_facts: bool = False) -> int:
        """규칙이 낸 변화(``Change``)를 한 줄에 적고, 상태·등급이 바뀌었으면 기록 한 줄."""
        s = ch.state
        if s.state not in ISSUE_STATES or s.severity not in ISSUE_SEVERITIES:
            raise StoreRefused("이슈 상태·등급이 아닙니다")
        if ch.event is not None and ch.event not in ISSUE_EVENTS:
            raise StoreRefused("이슈 기록 종류가 아닙니다")
        until = None if s.exception_until is None else _day_text(s.exception_until, "예외 끝날")
        vals = (cid, rule, s.severity, s.state, _day_text(s.first_seen_on, "처음 본 날"),
                _day_text(s.last_seen_on, "마지막 본 날"), _count(s.reappear_count, "다시 생김"), until,
                s.exception_severity, at)
        if row is None:
            iid = c.execute(
                """INSERT INTO naver_auto_issue (possibility_id, code, target, customer_id, rule, severity, state,
                       first_seen_on, last_seen_on, reappear_count, exception_until, exception_severity, updated_at,
                       facts) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                key + vals + (facts,)).lastrowid
        else:
            iid = row["issue_id"]
            c.execute(
                """UPDATE naver_auto_issue SET customer_id = ?, rule = ?, severity = ?, state = ?, first_seen_on = ?,
                       last_seen_on = ?, reappear_count = ?, exception_until = ?, exception_severity = ?, updated_at = ?,
                       facts = CASE WHEN ? THEN ? ELSE facts END
                   WHERE issue_id = ?""", vals + (int(set_facts), facts, iid))
        if ch.event is not None:
            c.execute(
                """INSERT INTO naver_auto_issue_event (issue_id, at, kind, from_state, to_state, severity, by_person,
                       run_id, exception_until, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (iid, at, ch.event, ch.from_state, s.state, s.severity, by, run_id, until, note))
        return iid

    def record_account_check(self, run_id: int, customer_id: int, *, possibility_id: int, link: str, status: str,
                             rules_run: Sequence[str], rules_not_run: Sequence[Tuple[str, str]], checked_at: datetime,
                             findings: Sequence = (), data_late: Optional[bool] = None,
                             bizmoney=None, budget_lock=None, refund_lock=None, yday_spend=None, yday_imp=None,
                             yday_clk=None, campaigns: Optional[Sequence[Mapping]] = None,
                             stats_day: Optional[date] = None,
                             stats: Optional[Mapping[str, Mapping[str, Optional[float]]]] = None,
                             provisional: bool = True) -> "IssueTally":
        """아침 점검 계정 한 곳 — 계정 하루치 · (읽었으면) 캠페인 하루치 · 이슈를 **한 거래**로 적는다(S9).

        도중에 죽으면 아무것도 남지 않는다 — 계정 하루치만 「정상」으로 남고 이슈는 빠지는 일이 없게.
        - 발견(``checks.Finding`` 모양 — rule · code · target · level · facts)마다 이슈 한 줄(열쇠 = 가망 + 항목 + 대상)을
          ``issues.observe`` 로 고친다. 발견의 규칙은 ``rules_run`` 에 있어야 하고, 계정 대상은 이 계정이어야 하고,
          캠페인 대상은 읽은 캠페인이어야 한다(다른 계정 이슈를 만들지 못하게).
        - 이 짝(가망 · 계정)의 열린 이슈 중 규칙이 오늘 돌았고 오늘 발견에 없는 것만 🔁(``issues.should_auto_resolve``).
          자료 늦음(``data_late`` 가 거짓이 아니면)이면 풀지 않는다 — 이관 규칙(``link``)은 통계와 무관해 예외.
        돌려주는 값은 기록 종류별 개수다."""
        self._need_writer()
        I = _issue_rules()
        if link not in LINKS:
            raise StoreRefused("모르는 짝 상태")
        pid = _pos_int(possibility_id, "가망 번호")
        vals = self._account_day_vals(run_id, customer_id, status, rules_run, rules_not_run, checked_at, pid, link,
                                      bizmoney, budget_lock, refund_lock, yday_spend, yday_imp, yday_clk, data_late)
        cid = vals[0]
        at = vals[-1]
        self._not_future(checked_at, "점검 시각")
        ran = set(json.loads(vals[6]))
        camp_rows = None
        if campaigns is not None:
            camp_rows = self._campaign_rows(cid, _day_text(stats_day, "통계 날짜"), campaigns,
                                            {} if stats is None else stats, provisional, at)
        elif stats_day is not None or stats is not None:
            raise StoreRefused("캠페인 없이 통계만 적을 수 없습니다")
        camp_ids = set() if camp_rows is None else {r[0] for r in camp_rows}
        try:
            acc = I.account_target(cid)
        except I.IssueRuleError:
            raise StoreRefused("고객 번호 모양이 아닙니다") from None
        plan = []
        for f in _seq(findings, "발견"):
            rule, code, target, level = (getattr(f, "rule", None), getattr(f, "code", None),
                                         getattr(f, "target", None), getattr(f, "level", None))
            if not (I.valid_code(rule) and I.valid_code(code) and I.valid_target(target)) or \
                    level not in ISSUE_SEVERITIES:
                raise StoreRefused("발견 모양이 아닙니다")
            if rule not in ran:
                raise StoreRefused("돌리지 않은 규칙의 발견입니다")
            if target.startswith("acc:") and target != acc:
                raise StoreRefused("다른 계정의 발견입니다")
            if target.startswith("cmp-") and target not in camp_ids:
                raise StoreRefused("읽지 않은 캠페인의 발견입니다")
            plan.append((rule, code, target, level, _facts(getattr(f, "facts", ()))))
        found = [(p[1], p[2]) for p in plan]
        if len(set(found)) != len(found):
            raise StoreRefused("같은 발견이 두 번 있습니다")
        late = data_late is not False
        tally = Counter()
        with self._tx() as c:
            rid = vals[4]
            vals[1] = self._running_run_date(c, rid)
            today = date.fromisoformat(vals[1])
            self._write_account_day(c, vals)
            if camp_rows is not None:
                self._write_campaign_rows(c, rid, cid, camp_rows)
            try:
                for rule, code, target, level, facts in plan:
                    got = self._issue_rows(c, "possibility_id = ? AND code = ? AND target = ?", (pid, code, target))
                    row = got[0] if got else None
                    ch = I.observe(None if row is None else self._issue_state(row), level, today)
                    self._write_issue(c, row, (pid, code, target), cid, rule, ch, at, run_id=rid, facts=facts,
                                      set_facts=True)
                    tally[ch.event or "seen"] += 1
                for row in self._issue_rows(c, "possibility_id = ? AND customer_id = ? AND state IN (?, ?, ?)",
                                            (pid, cid) + tuple(sorted(I.OPEN_STATES))):
                    rule_late = False if row["rule"] == I.RULE_LINK else late
                    if not I.should_auto_resolve(row["rule"], row["code"], row["target"], rules_run=ran, found=found,
                                                 data_late=rule_late):
                        continue
                    ch = I.auto_resolve(self._issue_state(row), today)
                    if ch is not None:
                        self._write_issue(c, row, (pid, row["code"], row["target"]), cid, row["rule"], ch, at,
                                          run_id=rid)
                        tally[ch.event] += 1
            except I.IssueRuleError as e:
                raise StoreRefused(f"이슈 규칙이 받지 않습니다: {e.code}") from None
        return IssueTally(dict(tally))

    def close_unlinked_issues(self, run_id: int, pairing_id: int, at: datetime) -> "UnlinkCounts":
        """짝이 거절·무효가 된 열린 이슈를 「연결 해제로 닫힘」으로(M5) — 이 회차 날짜에 받은 그 짝 맞추기 기준.

        그 회차에 점검할 짝(확인 · 자동) · 「오늘 없음」 · 「이관 빠짐」으로 남은 짝은 이어진 것으로 본다. 그 밖의 짝이라도
        어제·오늘 이어졌던 짝(``link_memory`` · 어제·오늘 받은 짝 맞추기의 점검할 짝 · 오늘 없음 · 이관 빠짐 줄)은 하루
        기다린다(① 전산·단계가 하루 흔들린 것으로 이슈의 👀·🙈 를 잃지 않게).
        한꺼번에 많이(브레이크와 같은 비율) 닫으면 ``mass`` 로 알린다 — 닫힌 이슈는 짝이 돌아오면 다시 🆕 로 살아난다."""
        self._need_writer()
        I = _issue_rules()
        t = _kst_text(at, "닫은 시각")
        self._not_future(at, "닫은 시각")
        pnum = _pos_int(pairing_id, "짝 맞추기 번호")
        with self._tx() as c:
            rid = _pos_int(run_id, "회차 번호")
            run_day = self._running_run_date(c, rid)
            today = date.fromisoformat(run_day)
            prow = c.execute("SELECT outcome, at FROM naver_auto_pairing_run WHERE pairing_id = ?", (pnum,)).fetchone()
            pat = None if prow is None else _aware_time(prow[1])
            if prow is None or prow[0] != SYNC_ACCEPTED or pat is None or pat.astimezone(KST).date() != today:
                raise StoreRefused("이 회차 날짜에 받은 짝 맞추기가 아닙니다")
            linked = {(int(p), int(k)) for p, k in c.execute(
                """SELECT possibility_id, customer_id FROM naver_auto_pairing_row
                   WHERE pairing_id = ? AND customer_id IS NOT NULL AND state IN (?, ?, ?, ?)""",
                (pnum, PAIR_CONFIRMED, PAIR_AUTO, PAIR_MISSING, PAIR_BROKEN))}
            recent = set()
            for p, k, last in c.execute("""SELECT possibility_id, customer_id, MAX(last_matched_at)
                                           FROM naver_auto_link_memory GROUP BY possibility_id, customer_id"""):
                lt = _aware_time(last)
                if lt is None:
                    raise StoreError("저장된 짝 기억을 읽지 못했습니다")
                if lt.astimezone(KST).date() >= today - timedelta(days=1):
                    recent.add((int(p), int(k)))
            # 어제·오늘 받은 짝 맞추기에서 이어져 있던 짝(점검할 짝 · 오늘 없음 · 이관 빠짐)도 하루 기다린다 — 짝 기억은
            # 점검할 짝만 적으므로 「이관 빠짐」 짝이 단계가 하루 흔들려 사라지면 유예 없이 🙈·👀 를 잃었다(검토 issues-grace)
            since = _kst_text(datetime.combine(today - timedelta(days=1), time(0), tzinfo=KST), "유예 시작")
            runs = []
            for gid, gat in c.execute("SELECT pairing_id, at FROM naver_auto_pairing_run WHERE outcome = ? AND at >= ?",
                                      (SYNC_ACCEPTED, since)):
                gt = _aware_time(gat)
                if gt is None:
                    raise StoreError("저장된 짝 맞추기 시각을 읽지 못했습니다")
                if today - timedelta(days=1) <= gt.astimezone(KST).date() <= today:
                    runs.append(int(gid))
            for gid in runs:
                recent.update((int(p), int(k)) for p, k in c.execute(
                    """SELECT possibility_id, customer_id FROM naver_auto_pairing_row
                       WHERE pairing_id = ? AND customer_id IS NOT NULL AND state IN (?, ?, ?, ?)""",
                    (gid, PAIR_CONFIRMED, PAIR_AUTO, PAIR_MISSING, PAIR_BROKEN)))
            rows = self._issue_rows(c, "state IN (?, ?, ?)", tuple(sorted(I.OPEN_STATES)))
            pairs_open = {(r["possibility_id"], r["customer_id"]) for r in rows}
            closing = {pk for pk in pairs_open if pk not in linked and pk not in recent}
            closed = 0
            try:
                for r in rows:
                    if (r["possibility_id"], r["customer_id"]) not in closing:
                        continue
                    ch = I.close_unlinked(self._issue_state(r), today)
                    if ch is not None:
                        self._write_issue(c, r, (r["possibility_id"], r["code"], r["target"]), r["customer_id"],
                                          r["rule"], ch, t, run_id=rid)
                        closed += 1
            except I.IssueRuleError as e:
                raise StoreRefused(f"이슈 규칙이 받지 않습니다: {e.code}") from None
        return UnlinkCounts(closed, len(closing), len(pairs_open), _braked(len(pairs_open), len(closing)))

    # ── 이슈 — 사람의 손길(S11 화면 API 가 scope 로 누를 수 있는 사람인지 판정한 뒤 부른다) ──
    def _human(self, issue_id, by, at: datetime, apply, note: Optional[str] = None) -> dict:
        self._need_writer()
        I = _issue_rules()
        iid, who, t = _pos_int(issue_id, "이슈 번호"), _person(by, "누른 사람"), _kst_text(at, "누른 시각")
        self._not_future(at, "누른 시각")
        today = at.astimezone(KST).date()
        with self._tx() as c:
            got = self._issue_rows(c, "issue_id = ?", (iid,))
            if not got:
                raise IssueRefused("not-found")
            row = got[0]
            try:
                ch = apply(I, self._issue_state(row), today)
            except I.IssueRuleError as e:
                raise IssueRefused(e.code) from None
            self._write_issue(c, row, (row["possibility_id"], row["code"], row["target"]), row["customer_id"],
                              row["rule"], ch, t, by=who, note=note)
        return self.issue(iid)

    def ack_issue(self, issue_id: int, by: int, at: datetime) -> dict:
        """👀 확인 중(🆕 에서만)."""
        return self._human(issue_id, by, at, lambda I, s, d: I.ack(s, d))

    def resolve_issue(self, issue_id: int, by: int, at: datetime) -> dict:
        """✅ 해결(열린 것에서만) — 다음 점검에서 그대로면 다시 🆕."""
        return self._human(issue_id, by, at, lambda I, s, d: I.resolve(s, d))

    def except_issue(self, issue_id: int, by: int, actor: str, until: date, note: str, at: datetime) -> dict:
        """🙈 예외 — 등급별 한도(🟡·ⓘ 담당 이상 30일 · 🔴 팀장 이상 7일 · 오늘 포함)를 규칙 한 곳이 막는다.
        ``actor`` 는 누른 사람의 층(``issues.ACTOR_OWNER`` · ``ACTOR_LEAD``) — scope 가 정해 넘긴다."""
        I = _issue_rules()
        try:
            text = I.clean_note(note)
        except I.IssueRuleError as e:
            raise IssueRefused(e.code) from None
        return self._human(issue_id, by, at, lambda I_, s, d: I_.grant_exception(s, until, actor, d, text), note=text)

    # ── 읽기 ──
    def meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM naver_auto_meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def accounts_read_at(self) -> Optional[datetime]:
        """연결 목록을 마지막으로 받은(읽은) 시각 — 짝 맞추기·부르는 때가 신선도를 본다."""
        return self._meta_time(self._conn, "accounts_read_at")

    def account_times(self) -> dict:
        """고객 번호 → {present, absent_days, last_seen_at, absent_since, absent_last_at} — 시각 줄이 없으면 시각은 None."""
        out = {}
        for cid, pr, days, seen, since, last in self._conn.execute(
                """SELECT a.customer_id, a.present, a.absent_days, t.last_seen_at, t.absent_since, t.absent_last_at
                   FROM naver_auto_account a LEFT JOIN naver_auto_account_time t ON t.customer_id = a.customer_id
                   ORDER BY a.customer_id"""):
            times = [None if x is None else _aware_time(x) for x in (seen, since, last)]
            if any(x is not None and y is None for x, y in zip((seen, since, last), times)):
                raise StoreError("저장된 계정 시각을 읽지 못했습니다")
            out[int(cid)] = {"present": int(pr), "absent_days": int(days), "last_seen_at": times[0],
                             "absent_since": times[1], "absent_last_at": times[2]}
        return out

    def _pairing_run(self, r, desc) -> dict:
        d = dict(zip([x[0] for x in desc], r))
        try:
            d["codes"] = list(json.loads(d["codes"]))
            d["counts"] = None if d["counts"] is None else json.loads(d["counts"])
        except (TypeError, ValueError, RecursionError):
            raise StoreError("저장된 짝 맞추기 기록을 읽지 못했습니다") from None
        for k in ("at", "accounts_read_at", "stages_as_of"):
            if d[k] is not None:
                t = _aware_time(d[k])
                if t is None:
                    raise StoreError("저장된 짝 맞추기 기록을 읽지 못했습니다")
                d[k] = t
        return d

    def last_pairing(self, outcome: Optional[str] = None) -> Optional[dict]:
        """마지막 짝 맞추기 회차(결과를 주면 그 결과의 마지막) — 줄 없이 회차 정보만."""
        if outcome is not None and outcome not in PAIRING_OUTCOMES:
            raise StoreRefused("짝 맞추기 결과가 아닙니다")
        sql, args = "SELECT * FROM naver_auto_pairing_run", ()
        if outcome is not None:
            sql, args = sql + " WHERE outcome = ?", (outcome,)
        cur = self._conn.execute(sql + " ORDER BY pairing_id DESC LIMIT 1", args)
        r = cur.fetchone()
        return None if r is None else self._pairing_run(r, cur.description)

    def pairing_run(self, pairing_id: int) -> Optional[dict]:
        """그 번호의 짝 맞추기 회차(줄 없이)."""
        cur = self._conn.execute("SELECT * FROM naver_auto_pairing_run WHERE pairing_id = ?",
                                 (_pos_int(pairing_id, "짝 맞추기 번호"),))
        r = cur.fetchone()
        return None if r is None else self._pairing_run(r, cur.description)

    def pairing_rows(self, pairing_id: int) -> List[dict]:
        """그 회차의 결과 줄 — 가망 번호 · 상태 순."""
        cur = self._conn.execute(
            """SELECT possibility_id, customer_id, state, code, same_name, claimed_elsewhere, decision_id, link
               FROM naver_auto_pairing_row WHERE pairing_id = ? ORDER BY possibility_id, state, customer_id""",
            (_pos_int(pairing_id, "짝 맞추기 번호"),))
        out = []
        for r in cur.fetchall():
            d = dict(zip([x[0] for x in cur.description], r))
            if d["claimed_elsewhere"] is not None:
                d["claimed_elsewhere"] = bool(d["claimed_elsewhere"])
            out.append(d)
        return out

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
        except (TypeError, ValueError, RecursionError):
            raise StoreError("저장된 조직 수락본을 읽지 못했습니다") from None
        times = [_aware_time(t) for t in r[:3]]
        if not isinstance(body, dict) or any(t is None for t in times):   # 시간대 없는 시각도 못 읽은 것(견줄 수 없다)
            raise StoreError("저장된 조직 수락본을 읽지 못했습니다")
        return {"body": body, "generated_at": times[0], "received_at": times[1], "accepted_at": times[2],
                "confirmed_by": r[3]}

    def org_baseline(self) -> Optional[dict]:
        """조직 누적 비교 기준선 — 마지막 대표 확인(또는 처음) 뒤 가장 많던 재직·담당 줄 · 가장 적던 재직 팀장."""
        return _read_org_baseline(self._meta_json(self._conn, "org_baseline"))

    def hold(self, kind: str) -> Optional[dict]:
        """그 종류의 붙잡음(가장 최근 하나) — 대표 확인 화면(S11)·부르는 때 판정이 읽는다. 본문은 엔진 안에서만 쓴다."""
        if kind not in SYNC_KINDS:
            raise StoreRefused("동기화 종류가 아닙니다")
        r = self._conn.execute(
            "SELECT sync_id, at, codes, body, used_at, used_by FROM naver_auto_hold WHERE kind = ?", (kind,)).fetchone()
        if r is None:
            return None
        at, codes, body = _read_hold_row(r[1], r[2], r[3])
        used = None if r[4] is None else _aware_time(r[4])
        if r[4] is not None and used is None:
            raise _bad_hold()
        return {"hold_id": r[0], "at": at, "codes": codes, "body": body, "used_at": used, "used_by": r[5]}

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

    @staticmethod
    def _issue_out(r: dict) -> dict:
        d = dict(r)
        try:
            d["facts"] = None if d["facts"] is None else json.loads(d["facts"])
        except (TypeError, ValueError, RecursionError):
            raise StoreError("저장된 이슈를 읽지 못했습니다") from None
        return d

    def issue(self, issue_id: int) -> Optional[dict]:
        got = self._issue_rows(self._conn, "issue_id = ?", (_pos_int(issue_id, "이슈 번호"),))
        return self._issue_out(got[0]) if got else None

    def issues(self, possibility_id: Optional[int] = None, *, open_only: bool = False) -> List[dict]:
        """이슈 줄(가망을 주면 그 가망만 · ``open_only`` 면 🆕·👀·🙈 만) — 번호 순."""
        where, args = "1 = 1", ()
        if possibility_id is not None:
            where, args = "possibility_id = ?", (_pos_int(possibility_id, "가망 번호"),)
        if open_only:
            where += " AND state IN ('new', 'ack', 'exception')"
        return [self._issue_out(r) for r in self._issue_rows(self._conn, where, args)]

    def issue_events(self, issue_id: int) -> List[dict]:
        cur = self._conn.execute("SELECT * FROM naver_auto_issue_event WHERE issue_id = ? ORDER BY event_id",
                                 (_pos_int(issue_id, "이슈 번호"),))
        names = [x[0] for x in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def runs_on(self, run_date: date) -> List[dict]:
        """그 날(KST) 점검 회차들 — 번호 순."""
        cur = self._conn.execute("SELECT * FROM naver_auto_check_run WHERE run_date = ? ORDER BY run_id",
                                 (_day_text(run_date, "점검 날짜"),))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def account_days_on(self, day: date) -> dict:
        """그 날 계정 하루치의 점검 상태 {고객 번호: 상태} — 점검 순서(L2)·같은 날 다시 도는 회차가 본다."""
        return {int(cid): st for cid, st in self._conn.execute(
            "SELECT customer_id, status FROM naver_auto_account_day WHERE day = ?", (_day_text(day, "날짜"),))}

    def run(self, run_id: int) -> Optional[dict]:
        cur = self._conn.execute("SELECT * FROM naver_auto_check_run WHERE run_id = ?", (_pos_int(run_id, "회차 번호"),))
        r = cur.fetchone()
        return None if r is None else dict(zip([d[0] for d in cur.description], r))
