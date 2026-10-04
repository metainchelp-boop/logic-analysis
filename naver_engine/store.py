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

- **알림은 원천 한 줄 + 받는 사람별 한 줄(S10 · 설계 §6).** 원천에는 종류 · 날짜 · 문구 틀 이름 · 코드 · 관제 화면 경로만,
  받는 사람 줄에는 ① 직원 번호 · 중요도 · 숫자 칸(곳 수·건수 — 0 이상 정수만) · 보낸 결과 · 읽음 시각만 적는다 — 광고주
  이름 · 금액 · 상품명 · 고객 번호가 들어갈 칸이 없다(비서방 본문은 ``alerts.py`` 문구 틀과 이 숫자로만 만든다). 요약·목록은
  하루 한 번 · 보낸 결과는 「보낼 것」에서만 바뀐다(끝난 줄은 다시 바뀌지 않는다) · 중복 방지 열쇠는 저장소가 만든다.

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
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import erp_read as E
from . import fields as F
from . import handles as H
from . import naver_read as N
from . import management as P
from . import reporting as R

__all__ = ("open_writer", "open_reader", "Store", "StoreError", "StoreBusy", "StoreRefused", "SyncBraked",
           "HoldRefused", "SyncCounts", "LinkDecision", "PairingStale", "IssueRefused", "IssueTally", "UnlinkCounts",
           "AlertExists", "DeliveryRefused", "ScreenRefused", "inspect_snapshot")

KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 11   # 11 = 재확인 세대·원천 정정·보고서 대조 상태. 추가형 이관만 수행.
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
PAIR_BLOCK_CODES = frozenset({"ad-account-id-format", "ad-account-not-linked", "account-identifiers-conflict",
                              "customer-id-format", "customer-id-length", "not-linked", "ad-account-number",
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

# 알림(S10) — 원천 한 줄 + 받는 사람별 한 줄(설계 §6 engine_alert · engine_alert_recipient)
ALERT_SYSTEM = "system"                   # 시스템 경보(대표 · 그림자 기간에도 — Q4)
ALERT_DIGEST = "digest"                   # 사람마다 아침 요약(대표 결정 A1)
ALERT_LEAD_DIGEST = "lead_digest"         # 팀장 09:30 🟡 묶음
ALERT_SHADOW_SUMMARY = "shadow_summary"   # 그림자 기간 대표 하루 요약(대표 결정 A2)
ALERT_WEEKLY_UNLINKED = "weekly_unlinked"   # 매주 월요일 「이관 받을 곳」 목록(대표 결정 I3 ⓐ)
ALERT_KINDS = frozenset({ALERT_SYSTEM, ALERT_DIGEST, ALERT_LEAD_DIGEST, ALERT_SHADOW_SUMMARY, ALERT_WEEKLY_UNLINKED})
_ALERT_TAGS = {ALERT_SYSTEM: "sys", ALERT_DIGEST: "dg", ALERT_LEAD_DIGEST: "ld", ALERT_SHADOW_SUMMARY: "sh",
               ALERT_WEEKLY_UNLINKED: "wk"}
ALERT_SOURCES = frozenset({"org", "stages", "accounts", "pairing", "readiness", "morning", "compose", "metrics"})
ALERT_SEVERITIES = frozenset({"NORMAL", "URGENT"})      # erp_alert.SEVERITIES 와 같은 글자(시험이 대조)
DELIVERY_PENDING, DELIVERY_SENT, DELIVERY_DUPLICATE = "pending", "sent", "duplicate"
DELIVERY_CAP_TARGET, DELIVERY_CAP_TOTAL = "cap_target", "cap_total"
DELIVERY_FAILED, DELIVERY_HELD = "failed", "held"
DELIVERY_STATUSES = frozenset({DELIVERY_PENDING, DELIVERY_SENT, DELIVERY_DUPLICATE, DELIVERY_CAP_TARGET,
                               DELIVERY_CAP_TOTAL, DELIVERY_FAILED, DELIVERY_HELD})
HELD_REASONS = frozenset({"shadow", "weekend", "org_stale"})   # 비서방으로 보내지 않고 남겨만 둔 까닭
ALERT_TTL = timedelta(hours=12)           # 이만큼 지나도 못 보낸 알림은 보내지 않는다(어제 요약이 오늘 가지 않게)
ALERT_MAX_RECIPIENTS = 2000
ALERT_PARAMS_MAX = 12
ALERT_PARAM_LIMIT = 10 ** 7               # 알림 숫자 칸 상한(곳 수·건수 — 금액·번호가 들어갈 자리가 아니다)
_ALERT_TEMPLATE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_ALERT_PARAM = re.compile(r"[a-z][a-z0-9_]{0,19}")
_ALERT_LINK = re.compile(r"/naver/(?:[a-z0-9_-]+(?:/[a-z0-9_-]+)*)?")   # 관제 화면 경로 — 쿼리·조각 없이 짧은 경로만
ALERT_LINK_MAX = 60

# 화면 API(S11) — 열람·쓰기 기록(누가 · 언제 · 무엇을 · 어디에 · 결과 — 이름·금액·고객 번호 칸이 없다)
ACCESS_TARGETS = frozenset({"session", "client", "issue", "link", "alert", "settings", "hold", "board", "health"})
_ACCESS_CODE = re.compile(r"[a-z][a-z0-9_]*(?:-[a-z0-9_]+)*")   # 동작 · 결과 코드(40자 이하 · 숫자로 시작하지 않음)
ACCESS_CODE_MAX = 40
ACCESS_LOG_MAX_READ = 1000
THRESHOLD_HISTORY_MAX_READ = 200
ISSUE_READ_CHUNK = 500                   # 이슈 기록을 한 번에 읽을 때 IN 목록 한 묶음(SQLite 변수 한도 안)

RUN_RUNNING, RUN_DONE, RUN_FAILED = "running", "done", "failed"
RUN_END_STATUSES = frozenset({RUN_DONE, RUN_FAILED})
ORPHANED = "orphaned"

# 코드 모양 — 규칙 이름(checks.ALL_RULES) · 사유(checks 의 "stats-unread" 등) · 오류 종류(naver_read.KIND_* · erp 종류)
_RULE_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}")
_REASON_CODE = re.compile(r"[a-z0-9][a-z0-9_]*(?:-[a-z0-9_]+)*")
# 오류·동기화 코드 — 영문 낱말(밑줄)을 줄표로 잇고, 숫자는 끝의 HTTP 상태 세 자리 하나만(번호·키 조각이 기록에 남지 않게)
_ERROR_KIND = re.compile(r"(?=.{1,40}\Z)[A-Za-z][A-Za-z_]*(?:-[A-Za-z_]+)*(?:-[1-5][0-9]{2})?")
ERROR_CODE = _ERROR_KIND   # 밖에서 코드 모양을 미리 볼 때(알림 · S10) — 같은 규칙 한 곳

# 캠페인 하루치 — 더할 수 있는 원래 숫자만 남긴다(클릭률·클릭당 비용은 보여 줄 때 계산 · 주간·월간 합계가 맞게)
CAMPAIGN_METRICS = (
    ("impCnt", "imp_cnt"), ("clkCnt", "clk_cnt"), ("salesAmt", "sales_amt"), ("ccnt", "ccnt"),
    ("convAmt", "conv_amt"), ("purchaseCcnt", "purchase_ccnt"), ("purchaseConvAmt", "purchase_conv_amt"),
)
METRICS_MAX_ATTEMPTS = 8   # 같은 날·같은 짝 문맥: 재시작해도 실패 읽기/송신을 무한 반복하지 않는다.

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
    # 알림 원천(S10) — 종류 · 날짜(한국) · 어디서 · 문구 틀 이름 · 코드 · 관제 화면 경로만(이름·금액·번호 없음) · 쌓기만
    """CREATE TABLE IF NOT EXISTS naver_auto_alert (
        alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL CHECK (kind IN ('system', 'digest', 'lead_digest', 'shadow_summary', 'weekly_unlinked')),
        day TEXT NOT NULL,
        source TEXT NOT NULL,
        template TEXT NOT NULL,
        codes TEXT NOT NULL,
        link_path TEXT NOT NULL,
        created_at TEXT NOT NULL)""",
    # 요약·목록은 하루 한 번(시스템 경보는 코드마다 — 알림 모듈이 같은 날 같은 코드를 거른다)
    """CREATE UNIQUE INDEX IF NOT EXISTS naver_auto_alert_daily
        ON naver_auto_alert (kind, day) WHERE kind <> 'system'""",
    """CREATE INDEX IF NOT EXISTS naver_auto_alert_day ON naver_auto_alert (day, kind)""",
    # 받는 사람별(S10 · 설계 §6) — ① 직원 번호 · 중요도 · 사람마다 다른 숫자 칸 · 보낸 결과 · 읽음(🔔 — S11)
    """CREATE TABLE IF NOT EXISTS naver_auto_alert_recipient (
        recipient_id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id INTEGER NOT NULL CHECK (alert_id > 0),
        emp_idx INTEGER NOT NULL CHECK (emp_idx >= 0),
        severity TEXT NOT NULL CHECK (severity IN ('NORMAL', 'URGENT')),
        params TEXT NOT NULL,
        dedupe_key TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'duplicate', 'cap_target', 'cap_total', 'failed',
                                               'held')),
        held_reason TEXT CHECK (held_reason IS NULL OR held_reason IN ('shadow', 'weekend', 'org_stale')),
        attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        next_try_at TEXT,
        expires_at TEXT NOT NULL,
        message_idx INTEGER CHECK (message_idx IS NULL OR message_idx > 0),
        error_kind TEXT,
        finished_at TEXT,
        read_at TEXT,
        CHECK ((status = 'held') = (held_reason IS NOT NULL)),
        CHECK ((status = 'pending') = (next_try_at IS NOT NULL)),
        CHECK ((status = 'sent') = (message_idx IS NOT NULL)),
        UNIQUE (alert_id, emp_idx))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_alert_recipient_due
        ON naver_auto_alert_recipient (status, next_try_at)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_alert_recipient_emp
        ON naver_auto_alert_recipient (emp_idx, alert_id)""",
    # 화면 API 열람·쓰기 기록(S11 · 설계 §5 「광고주 한 장 열람 · 모든 쓰기 · 설정 변경」) — 쌓기만 · 이름·값 없음
    """CREATE TABLE IF NOT EXISTS naver_auto_access_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        emp_idx INTEGER CHECK (emp_idx IS NULL OR emp_idx >= 0),
        action TEXT NOT NULL,
        target_kind TEXT NOT NULL,
        target_id INTEGER CHECK (target_id IS NULL OR target_id >= 0),
        result TEXT NOT NULL)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_access_log_emp
        ON naver_auto_access_log (emp_idx, log_id)""",
    # 점검 기준값 고친 이력(S11 · Q3 「고치는 사람 = 대표만」) — 줄마다 고치기 전·뒤 9칸 전부 · 쌓기만 · 가장 늦은 줄이 지금 값
    """CREATE TABLE IF NOT EXISTS naver_auto_threshold_change (
        change_id INTEGER PRIMARY KEY AUTOINCREMENT,
        at TEXT NOT NULL,
        changed_by INTEGER NOT NULL CHECK (changed_by >= 0),
        before_values TEXT NOT NULL,
        after_values TEXT NOT NULL)""",
    # 공유 성과 전용. 아침 점검 회차·잠정 캠페인 자료와 분리한다. 원천은 내부 보관만 한다.
    """CREATE TABLE IF NOT EXISTS naver_auto_metrics_delivery (
        day TEXT NOT NULL,
        possibility_id INTEGER NOT NULL CHECK (possibility_id > 0),
        context_hash TEXT NOT NULL,
        source_json TEXT,
        payload_json TEXT,
        source_hash TEXT,
        collected_at TEXT,
        status TEXT NOT NULL CHECK (status IN ('reading', 'pending', 'held', 'retry', 'stored', 'no_client')),
        attempts INTEGER NOT NULL CHECK (attempts > 0),
        last_try_at TEXT NOT NULL,
        next_try_at TEXT NOT NULL,
        error_kind TEXT,
        PRIMARY KEY (day, possibility_id))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_inventory_check (
        customer_id INTEGER NOT NULL CHECK (customer_id > 0),
        day TEXT NOT NULL,
        snapshot_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('reading', 'partial', 'ok', 'retry', 'reauth_required', 'limited')),
        checked_at TEXT NOT NULL,
        error_code TEXT,
        bizmoney REAL,
        yday_spend REAL,
        yday_imp REAL,
        yday_clk REAL,
        campaigns_json TEXT,
        progress_json TEXT,
        progress_hash TEXT,
        attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0 AND attempts <= 4),
        next_try_at TEXT NOT NULL,
        PRIMARY KEY (customer_id, day))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_monthly_check (
        customer_id INTEGER NOT NULL CHECK (customer_id > 0),
        period_start TEXT NOT NULL,
        period_end TEXT NOT NULL,
        snapshot_at TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('reading', 'partial', 'ok', 'retry', 'limited')),
        error_code TEXT,
        imp INTEGER,
        clk INTEGER,
        spend INTEGER,
        conversion_value REAL,
        enabled_campaigns INTEGER,
        campaign_count INTEGER,
        campaign_fingerprint TEXT,
        progress_json TEXT,
        progress_hash TEXT,
        attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0 AND attempts <= 4),
        next_try_at TEXT NOT NULL,
        PRIMARY KEY (customer_id, period_start, period_end))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_monthly_period
        ON naver_auto_monthly_check (period_start, period_end)""",
)

_SCHEMA += (
    """CREATE TABLE IF NOT EXISTS naver_auto_management_state (
        customer_id INTEGER PRIMARY KEY, possibility_id INTEGER, stage_key TEXT,
        stage_revision TEXT NOT NULL, revision INTEGER NOT NULL,
        excluded_revision TEXT, included_revision TEXT, changed_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_management_event (
        event_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, stage_revision TEXT NOT NULL,
        possibility_id INTEGER, stage_key TEXT,
        action TEXT NOT NULL, actor INTEGER, reason TEXT, at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_performance_job (
        job_key TEXT PRIMARY KEY, customer_id INTEGER NOT NULL, kind TEXT NOT NULL,
        cycle_day TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
        snapshot_at TEXT NOT NULL, catalog_at TEXT NOT NULL, stage_revision TEXT NOT NULL,
        possibility_id INTEGER, matching_fingerprint TEXT NOT NULL,
        status TEXT NOT NULL, checked_at TEXT NOT NULL, next_try_at TEXT NOT NULL,
        attempts INTEGER NOT NULL, error_code TEXT, progress_json TEXT, progress_hash TEXT,
        bizmoney REAL, bizmoney_at TEXT, campaigns_json TEXT,
        last_success_at TEXT, last_bizmoney REAL, last_bizmoney_at TEXT,
        previous_bizmoney REAL, previous_bizmoney_at TEXT)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_performance_due
        ON naver_auto_performance_job (customer_id, cycle_day, status)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_performance_recent
        ON naver_auto_performance_job (customer_id, checked_at DESC)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_daily_performance (
        customer_id INTEGER NOT NULL, day TEXT NOT NULL,
        possibility_id INTEGER, matching_fingerprint TEXT NOT NULL,
        basic_complete INTEGER NOT NULL, conversion_complete INTEGER NOT NULL,
        conversion_attempts INTEGER NOT NULL,
        imp REAL, clk REAL, spend REAL, conversions REAL, conversion_value REAL,
        checked_at TEXT NOT NULL, source_at TEXT, conversion_checked_at TEXT,
        campaign_fingerprint TEXT NOT NULL,
        PRIMARY KEY (customer_id, day))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_snapshot (
        report_id INTEGER PRIMARY KEY, possibility_id INTEGER NOT NULL, period_key TEXT NOT NULL,
        revision_fingerprint TEXT NOT NULL, generated_at TEXT NOT NULL,
        status TEXT NOT NULL, review_status TEXT NOT NULL, payload_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_daily_revision (
        revision_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, day TEXT NOT NULL,
        recorded_at TEXT NOT NULL, payload_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_review (
        review_id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL, actor INTEGER NOT NULL,
        at TEXT NOT NULL, decision TEXT NOT NULL, note TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_manual_read (
        customer_id INTEGER PRIMARY KEY, requested_at TEXT NOT NULL, actor INTEGER NOT NULL,
        consumed_at TEXT)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_structure_job (
        job_key TEXT PRIMARY KEY, customer_id INTEGER NOT NULL, cycle_day TEXT NOT NULL,
        stage_revision TEXT NOT NULL,
        status TEXT NOT NULL, checked_at TEXT NOT NULL, next_try_at TEXT NOT NULL,
        attempts INTEGER NOT NULL, error_code TEXT, progress_json TEXT, progress_hash TEXT,
        reasons_json TEXT)""",
    """CREATE INDEX IF NOT EXISTS naver_auto_structure_recent
        ON naver_auto_structure_job (customer_id, checked_at DESC)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_validation (
        possibility_id INTEGER NOT NULL, period_key TEXT NOT NULL,
        expected_customers_json TEXT NOT NULL, payload_json TEXT NOT NULL,
        PRIMARY KEY (possibility_id, period_key))""",
    """CREATE TABLE IF NOT EXISTS naver_auto_report_dirty (
        possibility_id INTEGER NOT NULL, period_key TEXT NOT NULL,
        updated_at TEXT NOT NULL, pending INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (possibility_id, period_key))""",
    """CREATE INDEX IF NOT EXISTS naver_auto_report_dirty_pending
        ON naver_auto_report_dirty (pending, updated_at, possibility_id)""",
)

# 새 파일/기존 schema10 모두 같은 추가형 경로로 이관한다. 사용자 원천은 덮지 않는다.
_SCHEMA += (
    """CREATE TABLE IF NOT EXISTS naver_auto_morning_progress (
        customer_id INTEGER PRIMARY KEY, possibility_id INTEGER NOT NULL, day TEXT NOT NULL,
        binding TEXT NOT NULL, campaign_fingerprint TEXT NOT NULL, generation INTEGER NOT NULL,
        status TEXT NOT NULL, next_try_at TEXT NOT NULL, payload_bytes INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS naver_auto_morning_chunk (
        customer_id INTEGER NOT NULL, kind TEXT NOT NULL, slot INTEGER NOT NULL,
        generation INTEGER NOT NULL, body TEXT, checksum TEXT, size INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (customer_id, kind, slot))""",
)

_REVISION_COLUMNS = {
    "naver_auto_link_memory": (("auto_identity_fingerprint", "TEXT"),),
    "naver_auto_performance_job": (("generation", "TEXT NOT NULL DEFAULT ''"),
                                    ("source_wait_attempts", "INTEGER NOT NULL DEFAULT 0")),
    "naver_auto_daily_performance": (("source_generation", "TEXT NOT NULL DEFAULT ''"),
                                     ("source_revision", "INTEGER NOT NULL DEFAULT 1")),
    "naver_auto_manual_read": (("period_start", "TEXT"), ("period_end", "TEXT"),
                                ("possibility_id", "INTEGER"), ("request_kind", "TEXT NOT NULL DEFAULT 'manual'")),
}

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


class AlertExists(StoreRefused):
    """그 날 그 종류의 요약·목록을 이미 만들었다(하루 한 번) — 아무것도 적지 않았다."""


class DeliveryRefused(StoreRefused):
    """보낸 결과를 받지 않는다 — 없는 줄 · 이미 끝난 줄(보냄·실패·남겨 둠은 다시 바뀌지 않는다) · 모양이 틀림."""


class IssueRefused(StoreRefused):
    """이슈 규칙이 받지 않는 사람의 손길 — ``code`` 는 사유 코드(``issues.E_*`` · 없는 이슈면 ``not-found``)."""

    def __init__(self, code: str) -> None:
        super().__init__(f"이슈 손길을 받지 않습니다: {code}")
        self.code = code


class ScreenRefused(StoreRefused):
    """화면 API(S11) 쓰기를 받지 않음 — ``code`` = ``not-found``(없거나 남의 줄 · 둘을 가르지 않는다) · ``no-change`` ·
    ``out-of-range``(기준값 — ``fields`` 에 칸 이름만)."""

    def __init__(self, code: str, fields: Tuple[str, ...] = ()) -> None:
        super().__init__(f"화면 쓰기를 받지 않습니다: {code}")
        self.code = code
        self.fields = fields


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


def _threshold_rules():
    """점검 기준값 규칙(``backend/app/naver_auto/thresholds.py``) — 기준값을 다루는 함수에서만 늦게 부른다(이슈 규칙과 같게)."""
    from app.naver_auto import thresholds
    return thresholds


def _threshold_values(th) -> str:
    """기준값 9칸 → 글자(칸 이름 순). 숫자가 아닌 값은 규칙이 이미 막았다."""
    return json.dumps(asdict(th), sort_keys=True)


def _read_thresholds(raw):
    """저장된 9칸 → ``Thresholds`` — 규칙(``validate``)을 다시 지나게 해 범위 밖 값이 되살아나지 않게."""
    T = _threshold_rules()
    try:
        v = json.loads(raw)
    except (TypeError, ValueError, RecursionError):
        raise StoreError("저장된 기준값을 읽지 못했습니다") from None
    if not isinstance(v, dict) or set(v) != {f.name for f in fields(T.Thresholds)}:
        raise StoreError("저장된 기준값을 읽지 못했습니다")
    try:
        return T.validate(v, T.DEFAULTS)
    except T.ThresholdOutOfRange:
        raise StoreError("저장된 기준값이 허용 범위 밖입니다") from None


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


def _alert_params(params) -> str:
    """사람마다 다른 숫자 칸 — {이름: 0 이상 정수} · 이름은 코드 모양 · 값은 곳 수·건수 크기만(글자·금액·번호가 알림
    원천에 들어갈 자리를 두지 않는다 — 비서방 본문은 이 숫자와 문구 틀로만 만든다)."""
    if not isinstance(params, Mapping):
        raise StoreRefused("알림 숫자 칸 모양이 아닙니다")
    if len(params) > ALERT_PARAMS_MAX:
        raise StoreRefused("알림 숫자 칸이 너무 많습니다")
    out = {}
    for k, v in params.items():
        k = _code(k, _ALERT_PARAM, "알림 숫자 이름")
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < ALERT_PARAM_LIMIT:
            raise StoreRefused("알림 숫자 값은 0 이상 정수여야 합니다")
        out[k] = v
    return json.dumps(out, sort_keys=True, separators=(",", ":"))


def _alert_link(v) -> str:
    if not isinstance(v, str) or len(v) > ALERT_LINK_MAX or not _ALERT_LINK.fullmatch(v) or "sso" in v:
        raise StoreRefused("관제 화면 경로 모양이 아닙니다")
    return v


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


def inspect_snapshot(path) -> Dict[str, int]:
    """S14 독립 스냅샷의 무결성과 표별 줄 수. 실행 중 원본 DB가 아니라 닫힌 사본 전용이다."""
    raw = os.fspath(path)
    real = _check_path(raw)
    if real != raw:
        raise StoreRefused("스냅샷 경로에 링크를 둘 수 없습니다")
    conn = None
    try:
        fd = os.open(real, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            s = os.fstat(fd)
            if not _stat.S_ISREG(s.st_mode) or s.st_uid != os.geteuid() or s.st_nlink != 1 or s.st_mode & 0o077:
                raise StoreRefused("스냅샷은 우리만 읽는 일반 파일이어야 합니다")
            if any(os.path.lexists(real + suffix) for suffix in ("-wal", "-journal")):
                raise StoreRefused("닫히지 않은 스냅샷입니다")
            conn = _sqlite3.connect(pathlib.Path(real).as_uri() + "?mode=ro&immutable=1", uri=True)
            conn.execute("PRAGMA trusted_schema = OFF")
            conn.set_authorizer(_authorizer(PHASE_READ))
            if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise StoreError("스냅샷 무결성 검사 실패")
            names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            if not names or any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in names):
                raise StoreRefused("스냅샷 표 이름이 올바르지 않습니다")
            return {name: conn.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0] for name in names}
        finally:
            os.close(fd)
    except (OSError, _sqlite3.Error) as e:
        raise _wrap(e, "스냅샷을 검사하지 못했습니다") from None
    finally:
        if conn is not None:
            conn.close()


# ── 저장소 ───────────────────────────────────────────────────────────
def _rows(cursor):
    names = [r[0] for r in cursor.description]
    return [dict(zip(names, r)) for r in cursor]


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _performance_time(raw, end, now):
    """닫힌 일별 원천의 시각만 받는다. 확인 시각도 원천보다 앞설 수 없다."""
    try:
        if not isinstance(raw, str):
            raise ValueError()
        at = datetime.fromisoformat(raw)
        _kst_text(at, "원천 시각")
        if at.utcoffset() is None or at > now or at.astimezone(KST).date() <= end:
            raise ValueError()
        return at.astimezone(KST)
    except (TypeError, ValueError, OverflowError):
        raise StoreRefused("일별 원천 확인 시각이 올바르지 않습니다") from None


def _conversion_recheck(row, possibility_id, now):
    return possibility_id is not None and row["possibility_id"] == possibility_id and row["basic_complete"] \
        and not row["conversion_complete"] and row["conversion_attempts"] < 4 \
        and datetime.fromisoformat(row["checked_at"])+timedelta(hours=2) <= now


@contextmanager
def _report_read_snapshot(store):
    """조회 도중 writer가 게시해도 옛 숫자와 새 대조 상태가 섞이지 않는다."""
    own = not store._conn.in_transaction
    if own:
        store._conn.execute("BEGIN")
    try:
        yield
        if own:
            store._conn.execute("COMMIT")
    except Exception:
        if own and store._conn.in_transaction:
            store._conn.execute("ROLLBACK")
        raise


def _report_period(key):
    from .store import StoreRefused
    try:
        kind, start, end = key.split(":")
        value = R.period(kind, date.fromisoformat(start))
        if value.key != key:
            raise ValueError()
        return value
    except (AttributeError, TypeError, ValueError):
        raise StoreRefused("보고 기간이 올바르지 않습니다") from None


def _report_source_fingerprint(rows):
    values = [[row["customer_id"], row["day"], row.get("source_revision", 0),
               row["basic_complete"], row["conversion_complete"],
               *[row.get(key) for key in R.OUTPUT_FIELDS]] for row in rows]
    values.sort(key=lambda item: (item[0], item[1]))
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _report_validation(store, pid, period, expected, rows, now, *, source_fingerprint=None, required_after=None):
    from .store import _rows
    # 숫자 완결과 보고기간의 요구된 재대조 완료는 별개다.
    required = period.due_at.replace(hour=0, minute=1)
    jobs = _rows(store._conn.execute("""SELECT * FROM naver_auto_performance_job
        WHERE possibility_id=? AND period_start<=? AND period_end>=? ORDER BY checked_at""",
        (pid, period.end.isoformat(), period.start.isoformat())))
    queued = _rows(store._conn.execute("""SELECT * FROM naver_auto_manual_read
        WHERE possibility_id=? AND consumed_at IS NULL
        AND period_start<=? AND period_end>=?""", (pid, period.end.isoformat(), period.start.isoformat())))
    by_day = {(row["customer_id"], row["day"]): row for row in rows}
    def proof_time(row, field):
        try:
            value = datetime.fromisoformat(row.get(field) or "")
            return value.astimezone(R.KST) if value.tzinfo is not None and value.utcoffset() is not None else None
        except (TypeError, ValueError):
            return None
    pending, failed, attempts, successes = 0, False, [], []
    for cid in expected:
        for offset in range((period.end-period.start).days+1):
            day = (period.start+timedelta(days=offset)).isoformat()
            row = by_day.get((cid, day))
            relevant = [job for job in jobs if job["customer_id"] == cid and
                        job["period_start"] <= day <= job["period_end"]]
            checked = datetime.fromisoformat(row["checked_at"]) if row else None
            day_required = datetime.fromisoformat(required_after[str(cid)]) if required_after and str(cid) in required_after else required
            newest = relevant[-1] if relevant else None
            if newest:
                attempts.append(newest["checked_at"])
                generation = newest.get("generation")
                if generation:
                    day_required = max(day_required, datetime.fromisoformat(generation))
            source_generation = proof_time(row, "source_generation") if row else None
            source_at = proof_time(row, "source_at") if row else None
            # checked_at은 전체 읽기 종료 시각이지 새 세대의 원천 재조회 증거가 아니다.
            # source_at은 최소 cycleBaseTm이므로 같은 한국 날짜 안의 집계 지연은 허용한다.
            good = bool(row and row["basic_complete"] and row["conversion_complete"] and
                        source_generation is not None and source_at is not None and
                        day_required <= source_generation <= checked <= now and source_at <= checked and
                        source_at.date() >= source_generation.astimezone(R.KST).date())
            # 접수와 worker 시작 사이도 재대조 대기다. 요청 시각은 실제 원천 시도가 아니다.
            if any(request["customer_id"] == cid and request["period_start"] <= day <= request["period_end"]
                   for request in queued):
                good = False
            if newest and newest["status"] != "ok" and (checked is None or newest["checked_at"] >= row["checked_at"]):
                good = False
                failed = failed or newest["status"] in ("retry", "limited", "reauth_required")
            if good:
                successes.append(row["checked_at"])
            else:
                pending += 1
    return {"status": "complete" if expected and not pending else "failed" if failed else "pending",
            "last_attempt_at": max(attempts) if len(attempts) > 0 else max((r["checked_at"] for r in rows), default=None),
            "last_checked_at": min(successes) if expected and not pending else None,
            "pending_account_days": pending,
            "source_snapshot_fingerprint": source_fingerprint or _report_source_fingerprint(rows)}


def _report_public_validation(value):
    return {key: item for key, item in value.items() if not key.startswith("_")}


def _report_mark_dirty(connection, pid, key, at):
    period = _report_period(key)
    next_period = R.period(period.kind, period.end+timedelta(days=1))
    for target in (key, next_period.key):
        connection.execute("""INSERT INTO naver_auto_report_dirty(possibility_id,period_key,updated_at,pending)
            VALUES(?,?,?,1) ON CONFLICT(possibility_id,period_key) DO UPDATE SET
            updated_at=excluded.updated_at,pending=1""", (pid, target, at))


def _report_generate(store, now):
    from . import store as S
    store._need_writer()
    at = S._kst_text(now, "생성 시각")
    store._not_future(now, "생성 시각")
    decisions = store.synchronize_management(now)
    confirmed = {d.customer_id: d.possibility_id for d in store.current_decisions() if d.decision == "confirmed"}
    groups = {}
    for cid, value in decisions.items():
        pid, cadence = value["possibility_id"], value["decision"].cadence
        stage = "".join((value.get("stage") or "").split())
        # 고유 번호 자동 연결도 수집과 같은 귀속 판정을 사용한다. 사람의 승인 이력을 만들지는 않는다.
        # 비관리 계정의 원장은 보존하지만 새 업무 보고서를 계속 만들지는 않는다.
        if pid is not None and value["decision"].attributable and cadence == "daily" and stage in P.DAILY_STAGES:
            groups.setdefault(pid, []).append(cid)
    boundaries = {(pid, cid): store._performance_attribution_start(cid, pid)
                  for pid, cids in groups.items() for cid in cids}

    def current_accounts(pid, period):
        return {cid for cid in groups[pid] if boundaries[(pid, cid)] is None
                or boundaries[(pid, cid)] <= period.end.isoformat()}

    today = now.astimezone(S.KST).date()
    periods = R.due_periods(now, (today.replace(day=1)-timedelta(days=1)).replace(day=1))
    issues = {row["possibility_id"] for row in store.issues(open_only=True)}
    # 초판 및 최근 보고서의 검토정책 변화만 등록한다. 원천 정정은 수집 거래의 dirty가 담당한다.
    with store._tx() as connection:
        for pid in groups:
            legacy_periods = connection.execute("""SELECT r.period_key FROM naver_auto_report_snapshot r
                WHERE r.possibility_id=? AND COALESCE(json_extract(r.payload_json,'$.format_version'),1)<?
                AND r.report_id=(SELECT MAX(n.report_id) FROM naver_auto_report_snapshot n
                    WHERE n.possibility_id=r.possibility_id AND n.period_key=r.period_key)""", (pid, R.FORMAT_VERSION))
            for legacy in legacy_periods:
                connection.execute("""INSERT INTO naver_auto_report_dirty(possibility_id,period_key,updated_at,pending)
                    VALUES(?,?,?,1) ON CONFLICT(possibility_id,period_key) DO UPDATE SET pending=1,updated_at=excluded.updated_at""",
                    (pid, legacy[0], at))
            for period in periods:
                connection.execute("""INSERT INTO naver_auto_report_dirty
                    (possibility_id,period_key,updated_at,pending) VALUES(?,?,?,1)
                    ON CONFLICT(possibility_id,period_key) DO NOTHING""", (pid, period.key, at))
                latest = connection.execute("""SELECT review_status,payload_json FROM naver_auto_report_snapshot
                    WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1""",
                    (pid, period.key)).fetchone()
                required = "needs_staff_review" if period.kind == "monthly" or pid in issues else "not_required"
                if latest and (latest[0] != required or json.loads(latest[1]).get("format_version", 1) < R.FORMAT_VERSION):
                    # 승인 기록은 별도 표에 있으므로 당시 승인과 현재 요구정책을 혼동하지 않는다.
                    connection.execute("""UPDATE naver_auto_report_dirty SET pending=1,updated_at=?
                        WHERE possibility_id=? AND period_key=? AND pending=0""", (at, pid, period.key))
                expected_row = connection.execute("""SELECT expected_customers_json FROM naver_auto_report_validation
                    WHERE possibility_id=? AND period_key=?""", (pid, period.key)).fetchone()
                if expected_row and current_accounts(pid, period) - set(json.loads(expected_row[0])):
                    # 새 연결의 실적이 아직 없어도 분모에서 빼서 완결로 보이지 않는다.
                    connection.execute("""UPDATE naver_auto_report_dirty SET pending=1,updated_at=?
                        WHERE possibility_id=? AND period_key=?""", (at, pid, period.key))
        # 구형 writer가 남긴 dirty도 그 기간을 비교하는 기존 다음 판으로 전달한다.
        # 한 단계만 확장하며 숫자·원천 지문이 같으면 실제 새 판은 만들지 않는다.
        waiting = S._rows(connection.execute("SELECT possibility_id,period_key,updated_at FROM naver_auto_report_dirty WHERE pending=1"))
        for item in waiting:
            changed = _report_period(item["period_key"])
            following = R.period(changed.kind, changed.end+timedelta(days=1))
            if connection.execute("""SELECT 1 FROM naver_auto_report_snapshot
                WHERE possibility_id=? AND period_key=? LIMIT 1""", (item["possibility_id"], following.key)).fetchone():
                connection.execute("""INSERT INTO naver_auto_report_dirty(possibility_id,period_key,updated_at,pending)
                    VALUES(?,?,?,1) ON CONFLICT(possibility_id,period_key) DO UPDATE SET pending=1,updated_at=excluded.updated_at""",
                    (item["possibility_id"], following.key, item["updated_at"]))
    # 한 업체의 주간·월간을 절단하지 않는다. 대기 업체는 오래된 순서로 계속 배출한다.
    dirty = S._rows(store._conn.execute("""SELECT possibility_id,period_key,updated_at
        FROM naver_auto_report_dirty WHERE pending=1 ORDER BY updated_at,possibility_id,period_key"""))
    batches = {}
    for item in dirty:
        period = _report_period(item["period_key"])
        if period.due_at > now:
            continue
        pid = item["possibility_id"]
        if pid not in groups:
            # 단계가 돌아오면 보충할 수 있게 dirty와 이전 판/실적은 그대로 둔다.
            continue
        if pid not in batches and len(batches) >= 20:
            continue
        batches.setdefault(pid, []).append(period)
    made = 0
    for pid, targets in batches.items():
        with store._tx() as connection:
            prepared, batch_rows = [], {}
            def source_scope(period):
                saved = connection.execute("""SELECT expected_customers_json FROM naver_auto_report_validation
                    WHERE possibility_id=? AND period_key=?""", (pid, period.key)).fetchone()
                historical = [row[0] for row in connection.execute("""SELECT DISTINCT customer_id
                    FROM naver_auto_daily_performance WHERE possibility_id=? AND day BETWEEN ? AND ?""",
                    (pid, period.start.isoformat(), period.end.isoformat()))]
                return sorted(set(json.loads(saved[0]) if saved else ()) | set(historical) | current_accounts(pid, period))

            for period in sorted(targets, key=lambda value: (value.due_at, value.key)):
                state = connection.execute("""SELECT expected_customers_json,payload_json
                    FROM naver_auto_report_validation WHERE possibility_id=? AND period_key=?""",
                    (pid, period.key)).fetchone()
                expected = source_scope(period)
                rows = store.daily_performance(expected, period.start, period.end, possibility_id=pid)
                prior_period = R.previous_period(period)
                prior_expected = source_scope(prior_period)
                prior_rows = store.daily_performance(prior_expected, prior_period.start, prior_period.end, possibility_id=pid)
                batch_rows.update({(row["customer_id"], row["day"]): row for row in rows})
                previous = S._rows(connection.execute("""SELECT * FROM naver_auto_report_snapshot
                    WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1""", (pid, period.key)))
                report = R.snapshot(period, expected, rows, now, has_open_issues=pid in issues,
                                    previous_customers=prior_expected, previous_rows=prior_rows)
                if previous and json.loads(previous[0]["payload_json"]).get("format_version", 1) < R.FORMAT_VERSION \
                        and not (report["coverage"]["basic_complete_account_days"] or
                                 report["coverage"]["conversion_complete_account_days"]):
                    # 입증할 원천이 없는 옛 판은 미보관 표시로 남긴다. 빈 새 판으로 대체하지 않는다.
                    connection.execute("""UPDATE naver_auto_report_dirty SET pending=0
                        WHERE possibility_id=? AND period_key=?""", (pid, period.key))
                    continue
                prepared.append((period, expected, rows, previous[0] if len(previous) > 0 else None, report, state))
            source = _report_source_fingerprint(list(batch_rows.values()))
            for period, expected, rows, previous, report, state in prepared:
                required_after = {}
                for cid in expected:
                    required = period.due_at.replace(hour=0, minute=1)
                    decision = decisions.get(cid, {}).get("decision")
                    if decision is not None and decision.cadence == "weekly":
                        # 실관리 업체 보고서에 남아 있는 과거 비관리 계정분은 직전 일요일 대조를 재사용한다.
                        required -= timedelta(days=(required.weekday()+1) % 7)
                    required_after[str(cid)] = required.isoformat()
                validation = _report_validation(store, pid, period, expected, rows, now,
                                         source_fingerprint=source, required_after=required_after)
                prior_validation = json.loads(state[1]) if state else {}
                if validation["last_checked_at"] is None:
                    validation["last_checked_at"] = prior_validation.get("last_checked_at")
                if previous is None or previous["revision_fingerprint"] != report["revision_fingerprint"]:
                    old_payload = json.loads(previous["payload_json"]) if previous is not None else None
                    # 기존 판은 수정하지 않는다. 되돌아온 값도 새 판으로 보존한다.
                    revision = connection.execute("""SELECT COUNT(*) FROM naver_auto_report_snapshot
                        WHERE possibility_id=? AND period_key=?""", (pid, period.key)).fetchone()[0]+1
                    report.update(revision_no=revision,
                                  change_summary=R.revision_metadata(old_payload, report, previous["report_id"] if previous is not None else None),
                                  validation=_report_public_validation(validation))
                    prior_snapshot = connection.execute("""SELECT report_id,payload_json FROM naver_auto_report_snapshot
                        WHERE possibility_id=? AND period_key=? ORDER BY report_id DESC LIMIT 1""",
                        (pid, R.previous_period(period).key)).fetchone()
                    prior_payload = json.loads(prior_snapshot[1]) if prior_snapshot else None

                    def reference_for(payload, prior):
                        comparison = payload["details"]["comparison"]
                        if prior and prior.get("_data_fingerprint") == comparison["_data_fingerprint"]:
                            comparison["reference"] = {"report_id": prior_snapshot[0],
                                "revision_no": prior.get("revision_no"), "period_key": prior["period_key"]}

                    reference_for(report, prior_payload)
                    for cid, account in report["_account_reports"].items():
                        account_rows = [row for row in rows if row["customer_id"] == int(cid)]
                        account_validation = _report_validation(store, pid, period, [int(cid)], account_rows, now,
                                                               required_after={cid: required_after[cid]})
                        old_account = (old_payload or {}).get("_account_reports", {}).get(cid)
                        account.update(revision_no=revision,
                            change_summary=R.revision_metadata(old_account, account, previous["report_id"] if previous else None),
                            validation=_report_public_validation(account_validation))
                        reference_for(account, (prior_payload or {}).get("_account_reports", {}).get(cid))
                    if old_payload is not None and old_payload.get("format_version", 1) < R.FORMAT_VERSION:
                        report["details"]["status"] = "reconstructed"
                        for account in report["_account_reports"].values():
                            account["details"]["status"] = "reconstructed"
                    connection.execute("""INSERT INTO naver_auto_report_snapshot
                        (possibility_id,period_key,revision_fingerprint,generated_at,status,review_status,payload_json)
                        VALUES(?,?,?,?,?,?,?)""", (pid, period.key, report["revision_fingerprint"], at,
                                                  report["status"], report["review_status"], S._json(report)))
                    made += 1
                validation["_required_after"] = required_after
                connection.execute("""INSERT INTO naver_auto_report_validation
                    (possibility_id,period_key,expected_customers_json,payload_json) VALUES(?,?,?,?)
                    ON CONFLICT(possibility_id,period_key) DO UPDATE SET
                    expected_customers_json=excluded.expected_customers_json,payload_json=excluded.payload_json""",
                    (pid, period.key, S._json(expected), S._json(validation)))
                connection.execute("""UPDATE naver_auto_report_dirty SET pending=0
                    WHERE possibility_id=? AND period_key=?""", (pid, period.key))
    return {"generated": made, "accounts_confirmed": len(confirmed), "advertisers": len(batches)}


def _report_require_scope(store, pid, actor, now, action):
    from . import inventory as I, views as W, store as S
    from app.naver_auto import scope as SC
    org = W.load_org(store)
    catalog, state = I.catalog_status(store, now)
    if state != "accepted":
        raise S.StoreRefused("최신 전산 업체를 확인한 뒤 다시 조회해 주세요")
    company = next((row for row in catalog["items"] if row["possibility_id"] == pid), None)
    visible = company is not None and company["stage_known"] and not company["stage_hidden"]
    own = SC.ownership_for_client(org, pid, pid, SC.MATCH_PID if visible else SC.MATCH_UNKNOWN)
    SC.require_client(org, SC.scope_of(org, actor), {pid: own} if visible else {}, pid, action)


def _report_present(store, rows, *, current=False):
    from . import store as S
    output = []
    for row in rows:
        payload = _report_stored_payload(row.pop("payload_json"))
        row["payload"] = R.public_payload(payload)
        row["revision_no"] = payload.get("revision_no") or store._conn.execute("""SELECT COUNT(*)
            FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? AND report_id<=?""",
            (row["possibility_id"], row["period_key"], row["report_id"])).fetchone()[0]
        row["change_summary"] = payload.get("change_summary")
        row["validation"] = payload.get("validation", {"status": "pending", "last_checked_at": None})
        if current:
            saved = store._conn.execute("""SELECT expected_customers_json,payload_json FROM naver_auto_report_validation
                WHERE possibility_id=? AND period_key=?""", (row["possibility_id"], row["period_key"])).fetchone()
            dirty = store._conn.execute("""SELECT pending FROM naver_auto_report_dirty
                WHERE possibility_id=? AND period_key=?""", (row["possibility_id"], row["period_key"])).fetchone()
            if saved:
                row["validation"] = json.loads(saved[1])
                if dirty and dirty[0]:
                    period = _report_period(row["period_key"])
                    expected = json.loads(saved[0])
                    sources = store.daily_performance(expected, period.start, period.end, possibility_id=row["possibility_id"])
                    latest = _report_validation(store, row["possibility_id"], period, expected, sources, store._now(),
                                         required_after=row["validation"].get("_required_after"))
                    latest["last_checked_at"] = row["validation"].get("last_checked_at")
                    if latest["status"] == "complete":
                        latest["status"] = "updating"
                    row["validation"] = latest
        reviews = S._rows(store._conn.execute("""SELECT * FROM naver_auto_report_review
            WHERE report_id=? ORDER BY review_id DESC LIMIT 1""", (row["report_id"],)))
        row["review"] = reviews[0] if reviews else None
        if row["review"]:
            row["review_status"] = row["review"]["decision"]
        row["validation"] = _report_public_validation(row["validation"])
        row["payload"]["validation"] = row["validation"]
        output.append(row)
    return output


def _report_stored_payload(raw):
    payload = json.loads(raw)
    if payload.get("format_version", 1) < R.FORMAT_VERSION:
        # 옛 판에 현재 원천을 덧붙이지 않는다. 미보관이라는 표시만 추가한다.
        payload["format_version"] = 1
        payload["details"] = {"status": "legacy_unavailable", "daily": [], "comparison": None,
                              "briefing": [], "management_records": [], "next_actions": []}
    return payload


def _report_snapshot_detail(store, report_id):
    """내부 조회 계약. 호출자가 현재 회사·계정 권한을 검증한 뒤 공개화한다."""
    _pos_int(report_id, "보고서")
    with _report_read_snapshot(store):
        rows = _rows(store._conn.execute("SELECT * FROM naver_auto_report_snapshot WHERE report_id=?", (report_id,)))
        if not rows:
            return None
        row = rows[0]
        payload = _report_stored_payload(row.pop("payload_json"))
        row["payload"] = payload
        row["revision_no"] = payload.get("revision_no") or store._conn.execute("""SELECT COUNT(*)
            FROM naver_auto_report_snapshot WHERE possibility_id=? AND period_key=? AND report_id<=?""",
            (row["possibility_id"], row["period_key"], report_id)).fetchone()[0]
        row["change_summary"] = payload.get("change_summary")
        row["validation"] = payload.get("validation", {"status": "pending", "last_checked_at": None})
        return row


def _report_snapshots(store):
    from .store import _rows
    with _report_read_snapshot(store):
        rows = _rows(store._conn.execute("""SELECT r.* FROM naver_auto_report_snapshot r
            WHERE r.report_id=(SELECT MAX(n.report_id) FROM naver_auto_report_snapshot n
                WHERE n.possibility_id=r.possibility_id AND n.period_key=r.period_key)
            ORDER BY generated_at DESC,report_id DESC"""))
        return _report_present(store, rows, current=True)


def _report_history(store, possibility_id, actor, now, *, period_key=None, before_report_id=None, limit=20):
    from . import store as S
    from app.naver_auto import scope as SC
    S._pos_int(possibility_id, "업체")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise S.StoreRefused("보고서 이력은 1~50개씩 조회합니다")
    if period_key is not None:
        _report_period(period_key)
    if before_report_id is not None:
        S._pos_int(before_report_id, "이전 보고서")
    clauses, values = ["possibility_id=?"], [possibility_id]
    if period_key is not None:
        clauses.append("period_key=?")
        values.append(period_key)
    if before_report_id is not None:
        clauses.append("report_id<?")
        values.append(before_report_id)
    with _report_read_snapshot(store):
        _report_require_scope(store, possibility_id, actor, now, SC.ACT_VIEW)
        rows = S._rows(store._conn.execute("SELECT * FROM naver_auto_report_snapshot WHERE "+
                       " AND ".join(clauses)+" ORDER BY report_id DESC LIMIT ?", (*values, limit+1)))
        return {"items": _report_present(store, rows[:limit]),
                "next_before_report_id": rows[limit-1]["report_id"] if len(rows) > limit else None}


class ManagedStorage:
    """Store의 단일 writer/transaction/입력 검사 계약을 그대로 사용하는 좁은 확장."""

    def management_states(self):
        return {r["customer_id"]: r for r in _rows(self._conn.execute(
            "SELECT * FROM naver_auto_management_state"))}

    def synchronize_management(self, now):
        from . import management_store as MS, store as S
        self._need_writer()
        previous = self.management_states()
        decisions = MS.snapshot(self, now, stage_states=previous)
        at = S._kst_text(now, "정책 확인 시각")
        self._not_future(now, "정책 확인 시각")
        with self._tx() as c:
            for cid, row in decisions.items():
                if row["source_current"]:
                    evidence = row.get("_auto_identity")
                    # 완전한 최신 원천에서 재검증에 실패한 근거만 무효화한다. 이력 행은 남긴다.
                    c.execute("""UPDATE naver_auto_link_memory SET auto_identity_fingerprint=NULL
                        WHERE customer_id=? AND link='auto' AND auto_identity_fingerprint IS NOT NULL
                        AND (? IS NULL OR possibility_id<>?)""",
                        (cid, evidence[0] if evidence else None, evidence[0] if evidence else None))
                    if evidence:
                        c.execute("""INSERT INTO naver_auto_link_memory
                            (possibility_id, customer_id, link, first_matched_at, last_matched_at,
                             auto_identity_fingerprint) VALUES (?, ?, 'auto', ?, ?, ?)
                            ON CONFLICT (possibility_id, customer_id, link) DO UPDATE SET
                            last_matched_at=excluded.last_matched_at,
                            auto_identity_fingerprint=excluded.auto_identity_fingerprint""",
                            (evidence[0], cid, at, at, evidence[1]))
                if row["decision"].cadence == "blocked":
                    continue  # 불완전한 원천으로 기존 제외 이력을 무효화하지 않는다.
                pid, stage = row["possibility_id"], row["stage_key"]
                old = previous.get(cid)
                if old and (old["possibility_id"], old["stage_key"]) == (pid, stage):
                    continue
                rev = 1 if old is None else old["revision"] + 1
                identity = f"{cid}:{pid}:{stage}:{rev}"
                revision = hashlib.sha256(identity.encode()).hexdigest()
                c.execute("""INSERT INTO naver_auto_management_state
                    (customer_id, possibility_id, stage_key, stage_revision, revision, changed_at)
                    VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (customer_id) DO UPDATE SET
                    possibility_id=excluded.possibility_id, stage_key=excluded.stage_key,
                    stage_revision=excluded.stage_revision, revision=excluded.revision,
                    excluded_revision=NULL, included_revision=NULL, changed_at=excluded.changed_at""",
                    (cid, pid, stage, revision, rev, at))
                c.execute("""INSERT INTO naver_auto_management_event
                    (customer_id, stage_revision, possibility_id, stage_key, action, at)
                    VALUES (?, ?, ?, ?, 'stage_sync', ?)""", (cid, revision, pid, stage, at))
        return MS.snapshot(self, now)

    def record_management_override(self, customer_id, stage_revision, included, actor, now, reason):
        from . import store as S, management_store as MS
        self._need_writer()
        MS.require_action(self, now, actor, customer_id)
        S._customer_id(customer_id, "계정")
        if type(included) is not bool or not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 200:
            raise S.StoreRefused("포함 여부와 변경 사유를 확인해 주세요")
        current = self.synchronize_management(now).get(customer_id)
        if current is None or current["decision"].cadence == "blocked" \
                or current["stage_revision"] != stage_revision:
            raise S.StoreRefused("업무 단계 또는 연결 정보가 바뀌었습니다")
        # ERP 단계는 바꾸지 않는다. 수동 포함/제외는 현재 단계 전환 회차에만 유효하다.
        with self._tx() as c:
            c.execute("""UPDATE naver_auto_management_state SET excluded_revision=?,included_revision=?
                WHERE customer_id=? AND stage_revision=?""",
                (None if included else stage_revision, stage_revision if included else None, customer_id, stage_revision))
            c.execute("""INSERT INTO naver_auto_management_event
                (customer_id, stage_revision, action, actor, reason, at) VALUES (?, ?, ?, ?, ?, ?)""",
                (customer_id, stage_revision, "include" if included else "exclude", actor,
                 reason.strip(), S._kst_text(now, "변경 시각")))
        return self.management_states()[customer_id]

    def _performance_job(self, cid, kind, cycle, start, end, row, snapshot, catalog, *, matching_fingerprint=None):
        key = f"{cid}:{kind}:{cycle}:{start}:{end}"
        return {"job_key": key, "customer_id": cid, "kind": kind, "cycle_day": str(cycle),
                "period_start": str(start), "period_end": str(end), "snapshot_at": snapshot,
                "catalog_at": catalog, "stage_revision": row["stage_revision"],
                "matching_fingerprint": (self.decision_fingerprint() if matching_fingerprint is None
                                         else matching_fingerprint), "generation": P.generation_for(cycle)}

    @staticmethod
    def _collection_retry_ready(saved, at):
        """일시 통신/과거 예산 중단은 시간당 한 번만 재개한다. 과거 원인을 재분류하지 않는다."""
        if not saved:
            return True
        if saved["next_try_at"] > at:
            return False
        if saved["status"] == "limited" or (saved["status"] == "reading" and saved["attempts"] >= 4):
            return saved["error_code"] in ("SERVER", "NETWORK", "RATE", "REQUEST_DEADLINE",
                "REQUEST_CALL_CAP", "REQUEST_BUDGET") and at >= _kst_text(
                datetime.fromisoformat(saved["checked_at"])+timedelta(hours=1), "자동 복구")
        if saved["status"] in ("ok", "reauth_required", "superseded"):
            return False
        return saved["attempts"] < 4 or saved["status"] == "partial" or (
            saved["status"] == "retry" and saved["error_code"] in ("REQUEST_DEADLINE", "REQUEST_CALL_CAP"))

    def _collection_account_ready(self, customer_id, at):
        """다른 작업 종류로 같은 계정의 인증/통신 대기를 우회하지 않는다."""
        rows = []
        for table in ("naver_auto_performance_job", "naver_auto_structure_job"):
            row = self._conn.execute(f"""SELECT status,error_code,checked_at,next_try_at,attempts FROM {table}
                WHERE customer_id=? AND (status='ok' OR error_code IN ('KEY_REJECTED','RATE','SERVER','NETWORK'))
                ORDER BY checked_at DESC,rowid DESC LIMIT 1""", (customer_id,)).fetchone()
            if row:
                rows.append(dict(zip(("status","error_code","checked_at","next_try_at","attempts"),row)))
        if not rows:
            return True
        latest = max(rows,key=lambda row:(row["checked_at"],row["status"] != "ok"))
        if latest["status"] == "ok":
            return True
        if latest["error_code"] == "KEY_REJECTED":
            return False
        return self._collection_retry_ready(latest, at)

    def collection_account_ready(self, customer_id, now):
        """직렬 읽기 실행기용 공개 대기 검사. 키/이름/오류 원문을 반환하지 않는다."""
        return self._collection_account_ready(_customer_id(customer_id, "계정"), _kst_text(now, "현재"))

    def _morning_progress_binding(self, customer_id, possibility_id, day, now):
        from . import management_store as MS, morning_progress as MP
        customer_id = _customer_id(customer_id, "계정")
        possibility_id = _pos_int(possibility_id, "가망 번호")
        _kst_text(now, "진행 시각")
        self._not_future(now, "진행 시각")
        if type(day) is not date or day != now.astimezone(KST).date():
            raise StoreRefused("진행 날짜가 현재와 다릅니다")
        row = MS.snapshot(self, now).get(customer_id)
        if row is None or row["possibility_id"] != possibility_id or row["decision"].cadence != "daily" \
                or not self.inventory_account_valid(customer_id, row["snapshot_at"], now) \
                or not self.collection_account_ready(customer_id, now):
            raise StoreRefused("현재 상세점검 원천이 아닙니다")
        # 단순 수신시각 변경은 무시한다. 현재 귀속/숫자 근거/단계 세대는 매 저장 때 재검증한다.
        decisions = [(d.possibility_id, d.decision, d.decision_id) for d in self.current_decisions()
                     if d.customer_id == customer_id]
        return MP.digest(MP.packed([customer_id, possibility_id, day.isoformat(), row["stage_key"],
                                   row["stage_revision"], row.get("_auto_identity"), sorted(decisions)]))

    def morning_progress(self, customer_id, possibility_id, day, now):
        binding = self._morning_progress_binding(customer_id, possibility_id, day, now)
        rows = _rows(self._conn.execute("SELECT * FROM naver_auto_morning_progress WHERE customer_id=?", (customer_id,)))
        if not rows or rows[0]["binding"] != binding or rows[0]["status"] not in ("reading", "blocked"):
            return None
        result = rows[0]
        result["chunks"] = {(kind, slot): (body, checksum) for kind,slot,body,checksum in self._conn.execute(
            """SELECT kind,slot,body,checksum FROM naver_auto_morning_chunk
               WHERE customer_id=? AND generation=? AND body IS NOT NULL""", (customer_id,result["generation"]))}
        return result

    def begin_morning_progress(self, customer_id, possibility_id, day, campaign_fingerprint, now):
        from . import morning_progress as MP
        self._need_writer()
        binding = self._morning_progress_binding(customer_id, possibility_id, day, now)
        if not isinstance(campaign_fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", campaign_fingerprint):
            raise StoreRefused("진행 지문 형식이 아닙니다")
        previous = self.morning_progress(customer_id, possibility_id, day, now)
        if previous is not None and previous["campaign_fingerprint"] == campaign_fingerprint:
            if previous["status"] == "reading":
                return previous
            if _kst_text(now, "현재") < previous["next_try_at"]:
                raise MP.ProgressLimit()
        with self._tx() as c:
            c.execute("""INSERT INTO naver_auto_morning_progress
                (customer_id,possibility_id,day,binding,campaign_fingerprint,generation,status,next_try_at,payload_bytes)
                VALUES (?,?,?,?,?,1,'reading',?,0) ON CONFLICT(customer_id) DO UPDATE SET
                possibility_id=excluded.possibility_id,day=excluded.day,binding=excluded.binding,
                campaign_fingerprint=excluded.campaign_fingerprint,generation=generation+1,
                status='reading',next_try_at=excluded.next_try_at,payload_bytes=0""",
                (customer_id,possibility_id,day.isoformat(),binding,campaign_fingerprint,_kst_text(now,"현재")))
            c.execute("UPDATE naver_auto_morning_chunk SET body=NULL,checksum=NULL,size=0 WHERE customer_id=?", (customer_id,))
        return self.morning_progress(customer_id, possibility_id, day, now)

    def record_morning_progress(self, customer_id, generation, kind, slot, payload, now):
        from . import morning_progress as MP
        self._need_writer()
        customer_id = _customer_id(customer_id, "계정")
        generation = _pos_int(generation, "진행 세대")
        _kst_text(now, "진행 시각")
        self._not_future(now, "진행 시각")
        body = MP.payload_body(kind, slot, payload)
        size = len(body.encode("utf-8"))
        with self._tx() as c:
            rows = _rows(c.execute("SELECT * FROM naver_auto_morning_progress WHERE customer_id=?", (customer_id,)))
            if not rows:
                raise StoreRefused("진행 세대가 없습니다")
            head = rows[0]
            binding = self._morning_progress_binding(customer_id,head["possibility_id"],date.fromisoformat(head["day"]),now)
            if head["binding"] != binding or head["generation"] != generation or head["status"] != "reading":
                raise StoreRefused("진행 세대가 달라졌습니다")
            old = c.execute("SELECT size FROM naver_auto_morning_chunk WHERE customer_id=? AND kind=? AND slot=?",
                            (customer_id,kind,slot)).fetchone()
            total = head["payload_bytes"] + size - (old[0] if old else 0)
            if total > MP.MAX_BYTES:
                raise MP.ProgressLimit()
            c.execute("""INSERT INTO naver_auto_morning_chunk(customer_id,kind,slot,generation,body,checksum,size)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(customer_id,kind,slot) DO UPDATE SET
                generation=excluded.generation,body=excluded.body,checksum=excluded.checksum,size=excluded.size""",
                (customer_id,kind,slot,generation,body,MP.digest(body),size))
            c.execute("UPDATE naver_auto_morning_progress SET payload_bytes=? WHERE customer_id=?", (total,customer_id))

    def finish_morning_progress(self, customer_id, generation, now, *, blocked=False):
        self._need_writer()
        customer_id = _customer_id(customer_id, "계정")
        generation = _pos_int(generation, "진행 세대")
        _kst_text(now, "진행 시각")
        self._not_future(now, "진행 시각")
        if type(blocked) is not bool:
            raise StoreRefused("진행 대기 여부 형식이 아닙니다")
        with self._tx() as c:
            changed = c.execute("""UPDATE naver_auto_morning_progress SET status=?,next_try_at=?,payload_bytes=0
                WHERE customer_id=? AND generation=?""", ("blocked" if blocked else "consumed",
                _kst_text(now+timedelta(hours=1) if blocked else now,"진행 대기"),customer_id,generation)).rowcount
            if changed:
                c.execute("UPDATE naver_auto_morning_chunk SET body=NULL,checksum=NULL,size=0 WHERE customer_id=? AND generation=?",
                          (customer_id,generation))

    def performance_work(self, now, limit=24):
        from . import store as S
        if type(limit) is not int or not 1 <= limit <= 24:
            raise S.StoreRefused("원천 후보는 1~24개입니다")
        if now.astimezone(S.KST).time().replace(tzinfo=None) < P.COLLECTION_START:
            return []
        decisions = self.synchronize_management(now)
        snapshot = self.inventory_snapshot(now)
        if snapshot is None:
            return []
        catalog = self.account_catalog()
        if catalog is None:
            return []
        # 단일 writer의 후보 생성 안에서는 연결 판단을 바꾸거나 외부 요청을 하지 않는다.
        # 이 묶음에서만 재사용하고 매 요청 직전 performance_account_valid는 새로 검증한다.
        matching_fingerprint = self.decision_fingerprint()
        day, at = now.astimezone(S.KST).date(), S._kst_text(now, "현재")
        prior = {r["job_key"]: r for r in _rows(self._conn.execute(
            """SELECT * FROM naver_auto_performance_job WHERE cycle_day>=?
               OR status IN ('reading','partial','retry','source_wait')""",
            ((day-timedelta(days=40)).isoformat(),)))}
        candidates = []
        backfill = []

        def available(job):
            saved = prior.get(job["job_key"])
            if saved and saved["stage_revision"] != job["stage_revision"]:
                return None, True
            if saved and not self._collection_retry_ready(saved, at):
                return saved, False
            return saved, True

        def covered(job):
            # 당일/동일 이후 세대의 전체 성공 또는 진행 회차가 포함하면 목적만 재사용한다.
            return any(saved["customer_id"] == job["customer_id"]
                       and saved["stage_revision"] == job["stage_revision"]
                       and saved.get("possibility_id") == decisions[job["customer_id"]]["possibility_id"]
                       and saved.get("generation", "") >= job["generation"]
                       and saved["period_start"] <= job["period_start"] <= job["period_end"] <= saved["period_end"]
                       and saved["status"] not in ("limited", "reauth_required")
                       and saved["job_key"] != job["job_key"] for saved in prior.values())

        for cid, row in decisions.items():
            decision = row["decision"]
            if decision.cadence == "blocked":
                continue
            period = P.period_for(decision.cadence, day)
            job = self._performance_job(cid, decision.cadence, period.cycle_day, period.since,
                                        period.until, row, snapshot, catalog["generated_at"],
                                        matching_fingerprint=matching_fingerprint)
            old = prior.get(job["job_key"])
            if old and old["stage_revision"] != job["stage_revision"]:
                old = None
            recheck = old is not None and old["status"] == "ok" and decision.cadence == "daily" \
                and self._performance_conversion_due(job, row["possibility_id"], now)
            # 저장된 고정 기간은 자정/10시 뒤에도 이어 읽되 현재 권한·귀속을 재검증한다.
            for saved in prior.values():
                if saved["customer_id"] != cid or saved["stage_revision"] != row["stage_revision"] \
                        or saved["kind"] in ("manual", "manual_period") or saved["job_key"] == job["job_key"]:
                    continue
                carry = self._performance_job(cid, saved["kind"], date.fromisoformat(saved["cycle_day"]),
                    date.fromisoformat(saved["period_start"]), date.fromisoformat(saved["period_end"]),
                    row, snapshot, catalog["generated_at"], matching_fingerprint=matching_fingerprint)
                carry["generation"] = saved.get("generation") or carry["generation"]
                _, due = available(carry)
                if due and not covered(carry) and self.performance_account_valid(carry, now):
                    backfill.append((2, saved["checked_at"], cid, carry))
            prior_managed = False
            if decision.cadence != "daily" and day.weekday() == 6 and row["possibility_id"] is not None:
                prior_managed = self._performance_has_managed_history(cid, row["possibility_id"])
            fills = []
            planned = P.revalidation_periods(day, managed=decision.cadence == "daily", prior_managed=prior_managed)
            if decision.cadence == "daily" and not (old and old["status"] == "ok"):
                planned = []
            elif decision.cadence == "daily":
                month_start, month_end = day.replace(day=1), day-timedelta(days=1)
                complete = {r["day"] for r in self.daily_performance([cid], month_start, month_end)
                            if r["basic_complete"] and r["possibility_id"] == row["possibility_id"]}
                missing = [month_start+timedelta(days=n) for n in range(max(0,(month_end-month_start).days+1))
                           if str(month_start+timedelta(days=n)) not in complete]
                if missing:
                    planned.append(("backfill", day, min(missing), month_end))
            for kind, cycle, since, until in planned:
                fill = self._performance_job(cid, kind, cycle, since, until, row, snapshot, catalog["generated_at"],
                                            matching_fingerprint=matching_fingerprint)
                saved, due = available(fill)
                if due and not covered(fill) and not any(f["period_start"] <= fill["period_start"]
                        and fill["period_end"] <= f["period_end"] and f["generation"] >= fill["generation"] for f in fills):
                    fills.append(fill)
                    # 최초 수집을 우선하되 별도 예산 예약이 보충의 진행 기회를 보장한다.
                    backfill.append((2, fill["generation"] if saved is None else saved["checked_at"], cid, fill))
            if fills:
                # 과거 미완료 단일일을 새 보충 범위에 합친다. 원래 작업의 기간/체크포인트는
                # 보존하고 포함 범위 성공 후에만 superseded로 종료한다.
                backfill = [item for item in backfill if item[2] != cid or item[3] in fills or not any(
                    fill["period_start"] <= item[3]["period_start"] <= item[3]["period_end"] <= fill["period_end"]
                    and fill["generation"] >= item[3]["generation"] for fill in fills)]
            complete = period.cycle_day if old and old["status"] == "ok" and not recheck else None
            started = period.cycle_day if old else None
            if not P.is_due(decision, day, completed_cycle=complete, started_cycle=started):
                continue
            if covered(job) or (decision.cadence == "weekly" and any(f["kind"] == "reconcile" for f in fills)):
                continue
            if old and not recheck and not self._collection_retry_ready(old, at):
                continue
            candidates.append((0 if decision.cadence == "daily" else 1,
                               "" if old is None else old["checked_at"], cid, job))
        for request in _rows(self._conn.execute("SELECT * FROM naver_auto_manual_read")):
            cid = request["customer_id"]
            row = decisions.get(cid)
            if row is None or row["decision"].cadence == "blocked":
                continue
            request_day = datetime.fromisoformat(request["requested_at"]).astimezone(S.KST).date()
            if (day-request_day).days > 7 and request.get("consumed_at") is None:
                continue
            end = date.fromisoformat(request["period_end"]) if request.get("period_end") else request_day-timedelta(days=1)
            start = date.fromisoformat(request["period_start"]) if request.get("period_start") else (
                end if row["decision"].cadence == "daily" else end-timedelta(days=6))
            kind = request.get("request_kind") or ("manual_period" if request.get("period_start") else "manual")
            manual = self._performance_job(cid,kind,request_day,start,end,row,snapshot,catalog["generated_at"],
                                           matching_fingerprint=matching_fingerprint)
            manual["job_key"] += ":"+request["requested_at"]
            manual.update(requested_at=request["requested_at"],actor=request["actor"],generation=request["requested_at"])
            if not self.performance_account_valid(manual, now):
                continue
            saved = prior.get(manual["job_key"])
            if saved and saved["stage_revision"] != manual["stage_revision"]:
                saved = None
            if saved and not self._collection_retry_ready(saved, at):
                continue
            candidates.append((-1, "" if saved is None else saved["checked_at"], cid, manual))
        selected, used, manual_count = [], set(), 0
        lane_counts, account_ready = [0, 0], {}
        daily_waiting = any(item[3]["kind"] == "daily" for item in candidates)
        for _, _, cid, job in sorted(candidates+backfill, key=lambda item: (*item[:3], item[3]["job_key"])):
            if job["kind"] in ("manual", "manual_period") and daily_waiting and manual_count >= 1:
                continue
            # 최초/보충을 각각 후보로 두되 실제 reader가 계정 중복 호출을 막는다.
            supplemental = job["kind"] not in ("daily", "weekly", "manual") \
                or (job["kind"] == "daily" and job["cycle_day"] < str(day))
            if lane_counts[supplemental] >= limit:
                continue
            if cid not in account_ready:
                account_ready[cid] = self._collection_account_ready(cid, at)
            if not account_ready[cid]:
                continue
            lane = (cid, supplemental)
            if lane not in used:
                selected.append(job)
                used.add(lane)
                lane_counts[supplemental] += 1
                manual_count += job["kind"] in ("manual", "manual_period")
        primary = [j for j in selected if j["kind"] in ("daily", "weekly", "manual")
                   and not (j["kind"] == "daily" and j["cycle_day"] < str(day))]
        supplement = [j for j in selected if j not in primary]
        reserve = min(6, len(supplement), limit//3) if primary else limit
        return primary[:limit-reserve]+supplement[:max(reserve, limit-len(primary))]

    def _performance_has_managed_history(self, customer_id, possibility_id):
        if not self._conn.execute("SELECT 1 FROM naver_auto_report_snapshot WHERE possibility_id=? LIMIT 1",
                                  (possibility_id,)).fetchone():
            return False
        rows = self._conn.execute("""SELECT stage_key FROM naver_auto_management_event
            WHERE customer_id=? AND possibility_id=? AND action='stage_sync'""", (customer_id, possibility_id))
        return any(row[0] in P.DAILY_STAGES for row in rows)

    def performance_account_valid(self, job, now):
        from . import inventory as I, store as S, sync as Y
        from app.naver_auto import org_snapshot as O
        required = {"job_key", "customer_id", "kind", "cycle_day", "period_start", "period_end",
                    "snapshot_at", "catalog_at", "stage_revision", "matching_fingerprint", "generation"}
        if not isinstance(job, dict):
            return False
        if job.get("kind") in ("manual", "manual_period"):
            required |= {"requested_at", "actor"}
        if set(job) != required or job.get("kind") not in (
                "daily", "weekly", "backfill", "manual", "manual_period", "recent", "reconcile", "report_weekly", "report_monthly"):
            return False
        try:
            S._kst_text(now, "현재")
            S._customer_id(job["customer_id"], "계정")
            S._kst_text(job["snapshot_at"], "계정 원천")
            if job["snapshot_at"] > now:
                return False
            days = [date.fromisoformat(job[key]) for key in ("cycle_day", "period_start", "period_end")]
            if any(job[key] != day.isoformat() for key, day in zip(
                    ("cycle_day", "period_start", "period_end"), days)):
                return False
            cycle, start, end = days
            today = now.astimezone(S.KST).date()
            if not start <= end < today or not 0 <= (end-start).days < 31 or cycle > today:
                return False
            key = f"{job['customer_id']}:{job['kind']}:{cycle}:{start}:{end}"
            generation = datetime.fromisoformat(job["generation"])
            if generation.tzinfo is None or generation > now:
                return False
            if job["kind"] in ("manual", "manual_period"):
                S._person(job["actor"], "요청자")
                requested = datetime.fromisoformat(job["requested_at"])
                S._kst_text(requested, "요청 시각")
                if requested > now or requested.astimezone(S.KST).date() != cycle or generation != requested:
                    return False
                key += ":"+job["requested_at"]
            elif job["generation"] != P.generation_for(cycle):
                return False
            if job["job_key"] != key:
                return False
        except (S.StoreRefused, TypeError, ValueError, OverflowError):
            return False
        if not self.inventory_account_valid(job["customer_id"], job["snapshot_at"], now):
            return False
        catalog, state = I.catalog_status(self, now)
        if state != "accepted" or catalog["generated_at"] != job.get("catalog_at"):
            return False
        if not O.allows_raising(Y.org_freshness(self, now)) \
                or job.get("matching_fingerprint") != self.decision_fingerprint():
            return False
        row = self.management_states().get(job["customer_id"])
        if not row or row["stage_revision"] != job.get("stage_revision"):
            return False
        decision = P.classify(stage=row["stage_key"], stage_revision=row["stage_revision"],
                              matched=row["possibility_id"] is not None, authority_valid=True,
                              source_current=True, excluded_revision=row["excluded_revision"],
                              included_revision=row["included_revision"])
        if decision.cadence == "blocked":
            return False
        if job["kind"] in ("manual", "manual_period"):
            from . import management_store as MS
            from app.naver_auto import scope as SC
            requests = _rows(self._conn.execute("SELECT * FROM naver_auto_manual_read WHERE customer_id=?",
                                               (job["customer_id"],)))
            request = requests[0] if requests else None
            if not request or request["requested_at"] != job.get("requested_at") or request["actor"] != job.get("actor"):
                return False
            if request.get("possibility_id") != row["possibility_id"]:
                return False
            requested_kind = request.get("request_kind") or ("manual_period" if request.get("period_start") else "manual")
            if requested_kind != job["kind"]:
                return False
            try:
                MS.require_action(self,now,request["actor"],job["customer_id"],allow_unmatched=True)
            except (S.StoreRefused,SC.ClientNotVisible,SC.ActionNotAllowed):
                return False
            if job["kind"] == "manual_period":
                return request.get("period_start") == str(start) and request.get("period_end") == str(end) \
                    and request.get("possibility_id") == row["possibility_id"] \
                    and self._performance_history_valid(job["customer_id"], row["possibility_id"], start, end)
            if request.get("period_start"):
                return request["period_start"] == str(start) and request["period_end"] == str(end)
            return end == cycle-timedelta(days=1) and start == end-timedelta(
                days=0 if decision.cadence == "daily" else 6)
        if job["kind"] in ("recent", "reconcile", "report_weekly", "report_monthly"):
            allowed = P.revalidation_periods(cycle, managed=decision.cadence == "daily",
                prior_managed=decision.cadence != "daily" and row["possibility_id"] is not None
                    and self._performance_has_managed_history(job["customer_id"], row["possibility_id"]))
            return (job["kind"], cycle, start, end) in allowed
        if job["kind"] == "backfill":
            if decision.cadence != "daily":
                return False
            month = cycle.replace(day=1)
            previous_end = month-timedelta(days=1)
            week_end = cycle-timedelta(days=cycle.weekday()+1)
            return (month <= start <= end == cycle-timedelta(days=1)) or (
                cycle.day == 3
                and start == previous_end.replace(day=1) and end == previous_end) or (
                cycle == week_end+timedelta(days=1) and start == week_end-timedelta(days=6) and end == week_end)
        period = P.period_for(decision.cadence, cycle)
        return job["kind"] == decision.cadence and (cycle, start, end) == (
            period.cycle_day, period.since, period.until)

    def _performance_history_valid(self, customer_id, possibility_id, start, end):
        if possibility_id is None:
            return False
        boundary = self._performance_attribution_start(customer_id, possibility_id)
        rows = self.daily_performance([customer_id], start, end)
        return len(rows) == (end-start).days+1 and not (boundary and str(start) < boundary) and all(
            row["possibility_id"] == possibility_id for row in rows)

    def begin_performance_check(self, job, now):
        from . import store as S
        self._need_writer()
        if not self.performance_account_valid(job, now):
            raise S.StoreRefused("수집 대상 또는 원천이 바뀌었습니다")
        at = S._kst_text(now, "시작 시각")
        if not self._collection_account_ready(job["customer_id"], at):
            raise S.StoreRefused("계정의 인증 또는 통신 재시도 대기 중입니다")
        self._not_future(now, "시작 시각")
        pid = self.management_states()[job["customer_id"]]["possibility_id"]
        with self._tx() as c:
            old = c.execute("""SELECT status, next_try_at, attempts, stage_revision, possibility_id,generation,error_code,checked_at FROM naver_auto_performance_job
                WHERE job_key=?""", (job["job_key"],)).fetchone()
            legacy = old is not None and old[3] == job["stage_revision"] and not old[5]
            changed = old is not None and (old[3] != job["stage_revision"] or (old[5] and old[5] != job["generation"]))
            recheck = old is not None and old[0] == "ok" and not changed and job["kind"] in ("daily", "backfill") \
                and self._performance_conversion_due(job, pid, now)
            prior_retry = None if old is None else dict(zip(
                ("status","next_try_at","attempts","stage_revision","possibility_id","generation","error_code","checked_at"), old))
            if old and not changed and not recheck and not self._collection_retry_ready(prior_retry, at):
                raise S.StoreRefused("다시 수집할 시각이 아닙니다")
            if legacy and not recheck:
                from . import performance_reads as R
                saved = c.execute("SELECT progress_json,progress_hash FROM naver_auto_performance_job WHERE job_key=?",
                                  (job["job_key"],)).fetchone()
                if saved and saved[0] and hashlib.sha256(saved[0].encode()).hexdigest() == saved[1]:
                    try:
                        progress = json.loads(saved[0])
                        R.validate_progress(progress, {key:value for key,value in job.items() if key != "generation"})
                        for cycle in progress["cycles"]:
                            _performance_time(cycle, date.fromisoformat(job["period_end"]), now)
                        progress["generation"] = job["generation"]
                        R.validate_progress(progress, job)
                    except (ValueError, S.StoreRefused):
                        pass  # 손상 체크포인트는 읽기 시작 뒤 공통 검증에서 limited로 기록한다.
                    else:
                        raw = _json(progress)
                        c.execute("UPDATE naver_auto_performance_job SET progress_json=?,progress_hash=? WHERE job_key=?",
                                  (raw,hashlib.sha256(raw.encode()).hexdigest(),job["job_key"]))
            if changed or recheck:
                c.execute("""UPDATE naver_auto_performance_job SET progress_json=NULL,progress_hash=NULL,
                    attempts=0,source_wait_attempts=0,error_code=NULL,bizmoney=NULL,bizmoney_at=NULL,campaigns_json=NULL WHERE job_key=?""",
                    (job["job_key"],))
            if changed and old[4] != pid:
                c.execute("""UPDATE naver_auto_performance_job SET last_success_at=NULL,last_bizmoney=NULL,
                    last_bizmoney_at=NULL,previous_bizmoney=NULL,previous_bizmoney_at=NULL WHERE job_key=?""",
                    (job["job_key"],))
            c.execute("""INSERT INTO naver_auto_performance_job
                (job_key,customer_id,kind,cycle_day,period_start,period_end,snapshot_at,catalog_at,
                 stage_revision,possibility_id,matching_fingerprint,generation,status,checked_at,next_try_at,attempts)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'reading',?,?,0)
                ON CONFLICT(job_key) DO UPDATE SET status='reading', checked_at=excluded.checked_at,
                  next_try_at=excluded.next_try_at, snapshot_at=excluded.snapshot_at,
                  catalog_at=excluded.catalog_at, stage_revision=excluded.stage_revision,
                  possibility_id=excluded.possibility_id,matching_fingerprint=excluded.matching_fingerprint,
                  generation=excluded.generation""",
                (job["job_key"],job["customer_id"],job["kind"],job["cycle_day"],job["period_start"],
                 job["period_end"], S._kst_text(job["snapshot_at"], "계정 원천"), job["catalog_at"],
                 job["stage_revision"],pid,job["matching_fingerprint"],job["generation"],at,
                 S._kst_text(now+timedelta(minutes=2), "대기 시각")))
            self._performance_dirty(c, job, pid, at)
            if job["kind"] in ("manual", "manual_period"):
                c.execute("UPDATE naver_auto_manual_read SET consumed_at=? WHERE customer_id=? AND requested_at=?",
                          (at,job["customer_id"],job["requested_at"]))

    def _performance_dirty(self, connection, job, possibility_id, at):
        from . import reporting as R
        start, end = date.fromisoformat(job["period_start"]), date.fromisoformat(job["period_end"])
        stored = {r["day"]: r["possibility_id"] for r in self.daily_performance([job["customer_id"]], start, end)}
        boundary = self._performance_attribution_start(job["customer_id"], possibility_id)
        touched = set()
        for offset in range((end-start).days+1):
            day = start+timedelta(days=offset)
            pid = stored.get(str(day), possibility_id if boundary is None or str(day) >= boundary else None)
            if pid is not None:
                touched.update((pid, R.period(kind, day).key) for kind in ("weekly", "monthly"))
        for pid, key in touched:
            _report_mark_dirty(connection, pid, key, at)

    def performance_progress(self, job):
        from . import performance_reads as R
        row = self._conn.execute("SELECT progress_json,progress_hash FROM naver_auto_performance_job WHERE job_key=?",
                                 (job["job_key"],)).fetchone()
        if row is None or row[0] is None:
            return None
        if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
            raise R.CheckpointInvalid("이어읽기 지문이 다릅니다")
        source = json.loads(row[0])
        R.validate_progress(source, job)
        return source

    def record_performance_progress(self, job, now, source):
        from . import performance_reads as R, store as S
        self._need_writer()
        if not self.performance_account_valid(job, now):
            raise S.StoreRefused("수집 대상이 바뀌었습니다")
        R.validate_progress(source, job)
        self._not_future(now, "이어읽기 시각")
        for cycle in source["cycles"]:
            _performance_time(cycle, date.fromisoformat(job["period_end"]), now)
        raw = _json(source)
        with self._tx() as c:
            previous = self.performance_progress(job)
            progressed = previous is not None and source["next_index"] > previous["next_index"] \
                and source["fingerprint"] == previous["fingerprint"]
            count = c.execute("""UPDATE naver_auto_performance_job SET progress_json=?, progress_hash=?,
                attempts=CASE WHEN ? THEN 0 ELSE attempts END WHERE job_key=? AND status='reading'""",
                (raw, hashlib.sha256(raw.encode()).hexdigest(), bool(progressed), job["job_key"])).rowcount
            if count != 1:
                raise S.StoreRefused("시작하지 않은 수집입니다")

    def record_performance_check(self, job, now, values):
        from . import performance_reads as R, fields as F, store as S
        self._need_writer()
        if not self.performance_account_valid(job, now):
            raise S.StoreRefused("수집 대상이 바뀌었습니다")
        self._not_future(now, "수집 시각")
        if not isinstance(values, dict):
            raise S.StoreRefused("수집 결과 모양이 올바르지 않습니다")
        at, status = S._kst_text(now, "수집 시각"), values.get("status")
        if status not in ("ok", "partial", "retry", "source_wait", "limited", "reauth_required"):
            raise S.StoreRefused("수집 상태가 올바르지 않습니다")
        balance = S._num(values.get("bizmoney"), "잔액")
        balance_at = values.get("bizmoney_at")
        if balance_at is not None:
            balance_time = _performance_time(balance_at, date.fromisoformat(job["period_end"]), now)
            balance_at = S._kst_text(balance_time,"잔액 시각")
        code = values.get("error_code")
        safe_codes = {"KEY_REJECTED", "RATE", "SERVER", "BAD_REQUEST", "NOT_FOUND", "NETWORK",
            "BAD_RESPONSE", "MISMATCH", "OTHER", "CHECKPOINT_PENDING", "CHECKPOINT_INVALID",
            "SOURCE_AGGREGATING", "CAMPAIGNS_CHANGED", "REQUEST_BUDGET", "REQUEST_DEADLINE",
            "REQUEST_CALL_CAP", "STATS_INCOMPLETE", "STATS_SHAPE", "STATS_SHAPE_UNKNOWN",
            "STATS_NUMERIC_INVALID", "STATS_ROW_ID_INVALID", "STATS_DATE_INVALID", "STATS_PERIOD_OPEN",
            "STATS_METRIC_MISSING", "STATS_METRIC_INVALID", "STATS_DATE_INCOMPLETE", "STATS_CYCLE_INVALID",
            "STATS_CYCLE_FUTURE", "STATS_CAMPAIGNS_INVALID", "UNEXPECTED", "RETRY_EXHAUSTED"}
        if code is not None and (not isinstance(code, str) or code not in safe_codes):
            raise S.StoreRefused("수집 사유가 올바르지 않습니다")
        if status == "source_wait" and code != "SOURCE_AGGREGATING":
            raise S.StoreRefused("집계 대기 근거가 올바르지 않습니다")
        rows = []
        if status == "ok":
            progress = self.performance_progress(job)
            if progress is None or progress["next_index"] != len(progress["campaign_ids"]):
                raise S.StoreRefused("완결 원천이 아닙니다")
            expected = R.validate_progress(progress, job)
            end = date.fromisoformat(job["period_end"])
            cycles = [_performance_time(cycle, end, now) for cycle in progress["cycles"]]
            if values.get("campaign_fingerprint") != progress["fingerprint"]:
                raise S.StoreRefused("캠페인 원천 지문이 다릅니다")
            given = values.get("daily_rows")
            if not isinstance(given, list) or len(given) != len(expected):
                raise S.StoreRefused("원천 실적 날짜가 다릅니다")
            seen = set()
            for row in given:
                if not isinstance(row, dict):
                    raise S.StoreRefused("일별 원천 모양이 다릅니다")
                day = row.get("day")
                if not isinstance(day, str) or day not in expected or day in seen \
                        or type(row.get("customer_id")) is not int or row["customer_id"] != job["customer_id"]:
                    raise S.StoreRefused("원천 계정 또는 날짜가 다릅니다")
                seen.add(day)
                origin = expected[day]
                if row.get("basic_complete") is not True or row.get("conversion_complete") is not origin["conversion_complete"]:
                    raise S.StoreRefused("완결 상태가 원천과 다릅니다")
                if any(S._num(row.get(dst), "실적") != origin[src] for src, dst in (
                        ("impCnt", "imp"), ("clkCnt", "clk"), ("salesAmt", "spend"),
                        ("ccnt", "conversions"), ("convAmt", "conversion_value"))):
                    raise S.StoreRefused("공개 실적이 원천과 다릅니다")
                checked = _performance_time(row.get("checked_at"), end, now)
                source = _performance_time(row.get("source_at"), end, now)
                if source != (min(cycles) if cycles else checked) or checked < (max(cycles) if cycles else source):
                    raise S.StoreRefused("일별 확인 시각이 원천과 다릅니다")
                rows.append({**row, "checked_at": S._kst_text(checked, "확인 시각"),
                             "source_at": S._kst_text(source, "원천 시각")})
        pid = self.management_states()[job["customer_id"]]["possibility_id"]
        attribution_start = self._performance_attribution_start(job["customer_id"], pid) if rows else None
        campaigns = values.get("campaigns", [])
        if not isinstance(campaigns, list) or any(not isinstance(row, dict) for row in campaigns):
            raise S.StoreRefused("캠페인 원천 모양이 다릅니다")
        with self._tx() as c:
            current = c.execute("SELECT attempts,source_wait_attempts FROM naver_auto_performance_job WHERE job_key=? AND status='reading'",
                                (job["job_key"],)).fetchone()
            if current is None:
                raise S.StoreRefused("시작하지 않은 수집입니다")
            # 순수 내부 한도는 다음 회차로 양보한 것일 뿐 통신 실패가 아니다.
            # 원인을 구분하지 못한 구버전 REQUEST_BUDGET은 면제하지 않는다.
            attempts = current[0] + (status == "retry" and code not in ("REQUEST_DEADLINE", "REQUEST_CALL_CAP"))
            if attempts >= 4 and status == "retry":
                status = "limited"  # 중단 상태와 마지막 실제 실패 사유를 분리해 보존한다.
            delay = (2, 5, 15, 30)[max(0, min(attempts, 4)-1)] if status == "retry" else 0
            if status == "retry" and code in ("REQUEST_DEADLINE", "REQUEST_CALL_CAP"):
                delay = 0  # 이미 지난 실제 실패 대기를 내부 예산 양보 때문에 다시 시작하지 않는다.
            if status == "limited" and code in ("SERVER", "NETWORK", "RATE", "REQUEST_DEADLINE", "REQUEST_CALL_CAP", "REQUEST_BUDGET"):
                delay = 60
            waits = current[1]+(status == "source_wait")
            if status == "source_wait":
                delay = (15, 30, 60)[min(waits-1, 2)]
            if status == "ok" and any(not row["conversion_complete"] for row in rows):
                delay = 120
            c.execute("""UPDATE naver_auto_performance_job SET status=?,checked_at=?,next_try_at=?,
                attempts=?,source_wait_attempts=?,error_code=?,bizmoney=?,bizmoney_at=?,campaigns_json=? WHERE job_key=?""",
                (status, at, S._kst_text(now+timedelta(minutes=delay), "대기 시각"), attempts, waits, code,
                 balance, balance_at, _json([F.keep(r, F.CAMPAIGN) for r in campaigns]), job["job_key"]))
            self._performance_dirty(c, job, pid, at)
            if status == "ok":
                c.execute("""UPDATE naver_auto_performance_job SET previous_bizmoney=last_bizmoney,
                    previous_bizmoney_at=last_bizmoney_at,last_success_at=?,last_bizmoney=?,last_bizmoney_at=?
                    WHERE job_key=?""", (at,balance,balance_at,job["job_key"]))
                c.execute("""UPDATE naver_auto_performance_job SET status='superseded',error_code='RECHECK_COVERED'
                    WHERE customer_id=? AND stage_revision=? AND possibility_id IS ? AND job_key!=?
                    AND period_start>=? AND period_end<=? AND generation<=?
                    AND status IN ('reading','partial','retry','source_wait')""",
                    (job["customer_id"],job["stage_revision"],pid,job["job_key"],job["period_start"],
                     job["period_end"],job["generation"]))
            for row in rows:
                # 실패/누락 회차는 여기에 오지 않으므로 직전 성공 숫자를 지우지 않는다.
                # 이전 성공 전환은 이력에 보존한다. 현재 미확인 전환을 완결로 보이게 섞지 않는다.
                previous = _rows(c.execute("SELECT * FROM naver_auto_daily_performance WHERE customer_id=? AND day=?",
                                           (job["customer_id"],row["day"])))
                # 재매칭 전 실적일을 새 업체에 소급 귀속하지 않는다. 과거 업체의 성공 원천도 덮지 않는다.
                row_pid = pid if attribution_start is None or row["day"] >= attribution_start else None
                if row_pid is None and pid is not None and len(previous) > 0:
                    continue
                if len(previous) > 0 and previous[0]["possibility_id"] is not None and previous[0]["possibility_id"] != row_pid:
                    continue  # 현재 미매칭/다른 귀속으로 과거 업체의 원천을 소급 지우지 않는다.
                if len(previous) > 0 and ((previous[0].get("source_at") or "") > row["source_at"]
                        or (previous[0].get("source_generation") or "") > job["generation"]):
                    # 오래 걸린 과거 체크포인트가 새 성공 원천을 역행시키지 않는다.
                    continue
                material = len(previous) == 0 or any(previous[0].get(key) != value for key, value in {
                    "possibility_id": row_pid, "basic_complete": True,
                    "conversion_complete": row["conversion_complete"],
                    **{key: row.get(key) for key in ("imp", "clk", "spend", "conversions", "conversion_value")},
                    "campaign_fingerprint": values["campaign_fingerprint"]}.items())
                if len(previous) > 0 and material:
                    c.execute("INSERT INTO naver_auto_daily_revision(customer_id,day,recorded_at,payload_json) VALUES(?,?,?,?)",
                              (job["customer_id"],row["day"],at,_json(previous[0])))
                conversion_attempts = 0 if row["conversion_complete"] else min(4, 1+(
                    previous[0]["conversion_attempts"] if len(previous) > 0 and previous[0]["possibility_id"] == row_pid else 0))
                c.execute("""INSERT INTO naver_auto_daily_performance
                    (customer_id,day,possibility_id,matching_fingerprint,basic_complete,conversion_complete,conversion_attempts,imp,clk,spend,conversions,
                     conversion_value,checked_at,source_at,conversion_checked_at,campaign_fingerprint,source_generation,source_revision)
                    VALUES (?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(customer_id,day) DO UPDATE SET
                    possibility_id=excluded.possibility_id,matching_fingerprint=excluded.matching_fingerprint,
                    basic_complete=1,imp=excluded.imp,clk=excluded.clk,spend=excluded.spend,
                    conversion_attempts=excluded.conversion_attempts,
                    conversion_complete=excluded.conversion_complete,conversions=excluded.conversions,
                    conversion_value=excluded.conversion_value,conversion_checked_at=excluded.conversion_checked_at,
                    checked_at=excluded.checked_at,source_at=excluded.source_at,
                    campaign_fingerprint=excluded.campaign_fingerprint,source_generation=excluded.source_generation,
                    source_revision=excluded.source_revision""",
                    (job["customer_id"],row["day"],row_pid,job["matching_fingerprint"],
                     int(row["conversion_complete"]),conversion_attempts,row["imp"],row["clk"],
                     row["spend"],row.get("conversions"),row.get("conversion_value"),row["checked_at"],
                     row["source_at"],row["checked_at"] if row["conversion_complete"] else None,
                     values["campaign_fingerprint"],job["generation"],
                     (previous[0].get("source_revision", 1)+int(material)) if len(previous) > 0 else 1))
        return status

    def _performance_conversion_due(self, job, possibility_id, now):
        return any(_conversion_recheck(row, possibility_id, now) for row in self.daily_performance(
            [job["customer_id"]], date.fromisoformat(job["period_start"]), date.fromisoformat(job["period_end"])))

    def _performance_attribution_start(self, customer_id, possibility_id):
        """다른 업체로 관측된 계정의 새 귀속은 그 연결일 이후만 입증할 수 있다."""
        previous, boundary, gap = None, None, False
        for pid, at in self._conn.execute("""SELECT possibility_id,at FROM naver_auto_management_event
            WHERE customer_id=? AND action='stage_sync' ORDER BY event_id""", (customer_id,)):
            if pid is None:
                gap = previous is not None
                continue
            if previous is not None and (pid != previous or gap):
                # 변경 당일은 이전 귀속과 섞일 수 있으므로 다음 실적일부터 입증한다.
                boundary = (datetime.fromisoformat(at).astimezone(KST).date()+timedelta(days=1)).isoformat()
            previous = pid
            gap = False
        return boundary if previous == possibility_id else None

    def attribution_changes(self):
        """다른 업체로 관측된 이력이 있으면 귀속 없는 구버전 성공값을 재사용하지 않는다."""
        owners, changed, gaps = {}, {}, set()
        for cid, pid in self._conn.execute("""SELECT customer_id,possibility_id FROM naver_auto_management_event
            WHERE action='stage_sync' ORDER BY event_id"""):
            changed.setdefault(cid, False)
            if pid is not None:
                changed[cid] = changed[cid] or cid in gaps or (cid in owners and owners[cid] != pid)
                owners[cid] = pid
                gaps.discard(cid)
            elif cid in owners:
                gaps.add(cid)
        return changed

    def daily_performance(self, customer_ids, start, end, *, possibility_id=None):
        from . import store as S
        ids = sorted({S._customer_id(cid, "계정") for cid in customer_ids})
        start, end = S._day_text(start, "시작"), S._day_text(end, "끝")
        if possibility_id is not None:
            S._pos_int(possibility_id, "업체")
        if not ids or start > end:
            return []
        out = []
        for offset in range(0, len(ids), 400):
            chunk = ids[offset:offset+400]
            marks = ",".join("?" for _ in chunk)
            out.extend(_rows(self._conn.execute(f"""SELECT * FROM naver_auto_daily_performance
                WHERE customer_id IN ({marks}) AND day BETWEEN ? AND ? ORDER BY customer_id,day""",
                (*chunk, start, end))))
        for row in out:
            row["basic_complete"] = bool(row["basic_complete"])
            row["conversion_complete"] = bool(row["conversion_complete"])
        return out if possibility_id is None else [row for row in out if row["possibility_id"] == possibility_id]

    def performance_checks(self, now):
        """시도 상태와 마지막 성공 자료를 분리한다. 과거 값은 실제 기간을 함께 반환한다."""
        from . import management_store as MS
        decisions = MS.snapshot(self, now)
        attribution_changes = self.attribution_changes()
        jobs = _rows(self._conn.execute("SELECT * FROM naver_auto_performance_job ORDER BY checked_at,job_key"))
        latest, success, balances, revalidations = {}, {}, {}, {}
        for job in jobs:
            cid = job["customer_id"]
            current_pid = decisions.get(cid, {}).get("possibility_id")
            if current_pid is not None and job["possibility_id"] != current_pid:
                continue
            if job["kind"] not in ("daily", "weekly", "manual"):
                if job["status"] != "superseded" and job["stage_revision"] == decisions.get(cid, {}).get("stage_revision"):
                    revalidations[cid] = {key: job.get(key) for key in
                        ("kind", "status", "period_start", "period_end", "checked_at", "error_code", "generation")}
                    revalidations[cid]["last_success_at"] = job.get("last_success_at") or (
                        job["checked_at"] if job["status"] == "ok" else None)
                if job["kind"] != "reconcile" or getattr(decisions.get(cid, {}).get("decision"), "cadence", None) != "weekly":
                    continue
                # 비관리의 31일 정정 대조가 포함한 기존 7일 점검은 따로 그 기간만 투영한다.
                weekly = P.period_for("weekly", date.fromisoformat(job["cycle_day"]))
                job = {**job, "kind": "weekly", "period_start": str(weekly.since), "period_end": str(weekly.until)}
            latest[cid] = job
            last_at = job.get("last_success_at") or (job["checked_at"] if job["status"] == "ok" else None)
            if last_at is not None:
                good = {**job, "checked_at": last_at,
                        "bizmoney": job["last_bizmoney"] if job.get("last_success_at") else job["bizmoney"],
                        "bizmoney_at": job["last_bizmoney_at"] if job.get("last_success_at") else job["bizmoney_at"]}
                if cid not in success or last_at >= success[cid]["checked_at"]:
                    success[cid] = good
                if good["bizmoney"] is not None and good["bizmoney_at"] is not None:
                    balances.setdefault(cid, {})[good["bizmoney_at"]] = good["bizmoney"]
                if job.get("previous_bizmoney") is not None and job.get("previous_bizmoney_at") is not None:
                    balances.setdefault(cid, {})[job["previous_bizmoney_at"]] = job["previous_bizmoney"]
        for request in _rows(self._conn.execute("SELECT * FROM naver_auto_manual_read WHERE consumed_at IS NULL")):
            cid = request["customer_id"]
            owner = decisions.get(cid)
            if not owner or owner["decision"].cadence == "blocked" or request.get("possibility_id") != owner["possibility_id"]:
                continue
            previous = revalidations.get(cid)
            if previous is not None and (previous.get("checked_at") or "") > request["requested_at"]:
                continue
            end = request.get("period_end") or str(datetime.fromisoformat(request["requested_at"]).date()-timedelta(days=1))
            start = request.get("period_start") or str(date.fromisoformat(end)-timedelta(
                days=0 if owner["decision"].cadence == "daily" else 6))
            revalidations[cid] = {"kind": request.get("request_kind") or ("manual_period" if request.get("period_start") else "manual"),
                "status": "pending", "period_start": start, "period_end": end, "checked_at": None,
                "requested_at": request["requested_at"], "error_code": None, "generation": request["requested_at"], "last_success_at": None}
        result = {}
        for cid, row in decisions.items():
            decision, attempt, good = row["decision"], latest.get(cid), success.get(cid)
            period = P.period_for(decision.cadence, now) if decision.cadence != "blocked" else None
            current = attempt is not None and period is not None and attempt["stage_revision"] == row["stage_revision"] and (
                (attempt["cycle_day"] == str(period.cycle_day) and attempt["kind"] == decision.cadence)
                or (attempt["kind"] == "manual" and attempt["cycle_day"] == str(now.astimezone(KST).date())))
            item = {"cadence": decision.cadence, "policy_reason": decision.reason,
                    "attribution_changed": attribution_changes.get(cid, False),
                    "stage_revision": row["stage_revision"],
                    "excluded": decision.reason == "MANUAL_EXCLUSION",
                    "status": attempt["status"] if current else "pending",
                    "checked_at": attempt["checked_at"] if attempt is not None else None,
                    "error_code": attempt["error_code"] if current else None,
                    "last_success_at": good["checked_at"] if good else None,
                    "period_start": good["period_start"] if good else None,
                    "period_end": good["period_end"] if good else None,
                    "stale": not (current and attempt["status"] == "ok"),
                    "bizmoney": good["bizmoney"] if good else None,
                    "bizmoney_at": good["bizmoney_at"] if good else None,
                    "previous_bizmoney": None, "previous_bizmoney_at": None, "bizmoney_change": None,
                    "spend": None, "imp": None, "clk": None,
                    "revalidation": revalidations.get(cid), "source_rechecked_at": None}
            if good:
                history = sorted((at, balance) for at, balance in balances.get(cid, {}).items()
                                 if good["bizmoney_at"] is not None and at < good["bizmoney_at"])
                if history:
                    old_at, old_balance = history[-1]
                    item.update(previous_bizmoney=old_balance, previous_bizmoney_at=old_at)
                    if good["bizmoney"] is not None:
                        change = good["bizmoney"]-old_balance
                        item["bizmoney_change"] = change if math.isfinite(change) else None
                rows = self.daily_performance([cid], date.fromisoformat(good["period_start"]),
                                               date.fromisoformat(good["period_end"]))
                if row["possibility_id"] is not None:
                    rows = [r for r in rows if r["possibility_id"] == row["possibility_id"]]
                count = (date.fromisoformat(good["period_end"])-date.fromisoformat(good["period_start"])).days+1
                if len(rows) == count and all(r["basic_complete"] for r in rows):
                    item.update({k: sum(r[k] for r in rows) for k in ("spend", "imp", "clk")})
                    verified = [r.get("checked_at") for r in rows]
                    if all(verified):
                        item["source_rechecked_at"] = min(verified)
                item["activity_observed"] = any(r.get("spend", 0) > 0 or r.get("imp", 0) > 0 or r.get("clk", 0) > 0 for r in rows)
            result[cid] = item
        return result

    def latest_inventory_successes(self):
        """이전 버전 성공 자료도 실제 실적일과 함께 보존해 보여 준다."""
        rows = _rows(self._conn.execute("""SELECT i.* FROM naver_auto_inventory_check i WHERE i.status='ok'
            AND i.day=(SELECT MAX(p.day) FROM naver_auto_inventory_check p
                WHERE p.customer_id=i.customer_id AND p.status='ok')"""))
        out = {}
        for row in rows:
            day = (date.fromisoformat(row["day"])-timedelta(days=1)).isoformat()
            out[row["customer_id"]] = {"period_start":day,"period_end":day,
                "last_success_at":row["checked_at"],"bizmoney_at":row["checked_at"],
                "bizmoney":row["bizmoney"],"spend":row["yday_spend"],"imp":row["yday_imp"],"clk":row["yday_clk"]}
        return out

    def observed_campaign_reasons(self, customer_ids):
        from . import ad_reasons as A, store as S
        result = {}
        for cid in customer_ids:
            S._customer_id(cid,"계정")
            row = self._conn.execute("""SELECT campaigns_json,checked_at FROM naver_auto_performance_job
                WHERE customer_id=? AND campaigns_json IS NOT NULL AND campaigns_json!='[]'
                ORDER BY checked_at DESC LIMIT 1""",(cid,)).fetchone()
            if row is None:
                row = self._conn.execute("""SELECT campaigns_json,checked_at FROM naver_auto_inventory_check
                    WHERE customer_id=? AND campaigns_json IS NOT NULL AND campaigns_json!='[]'
                    ORDER BY checked_at DESC LIMIT 1""",(cid,)).fetchone()
            result[cid] = [] if row is None else [A.describe("campaign",record,checked_at=datetime.fromisoformat(row[1]))
                                                  for record in json.loads(row[0])]
        return result

    def performance_manual_request(self, customer_id, actor, now, *, start=None, end=None, possibility_id=None):
        from . import management_store as MS, store as S
        self._need_writer()
        owner = MS.require_action(self, now, actor, customer_id, possibility_id=possibility_id, allow_unmatched=True)
        if start is not None or end is not None:
            if type(start) is not date or type(end) is not date or not 0 <= (end-start).days < 31 \
                    or end >= now.astimezone(KST).date() or possibility_id is None \
                    or not self._performance_history_valid(customer_id, possibility_id, start, end):
                raise S.StoreRefused("기간은 과거 귀속이 확인된 닫힌 실적일 1~31일이어야 합니다")
        at = S._kst_text(now, "요청 시각")
        self._not_future(now, "요청 시각")
        requested_end = end or now.astimezone(KST).date()-timedelta(days=1)
        requested_start = start or requested_end-timedelta(days=0 if owner["decision"].cadence == "daily" else 6)
        with self._tx() as c:
            last = c.execute("SELECT requested_at,consumed_at,possibility_id FROM naver_auto_manual_read WHERE customer_id=?",
                             (customer_id,)).fetchone()
            if last and ((last[1] is None and last[2] == owner["possibility_id"])
                         or datetime.fromisoformat(last[0])+timedelta(hours=1) > now):
                raise S.StoreRefused("같은 계정의 요청이 대기 중이거나 재요청 간격 전입니다")
            overlaps = c.execute("""SELECT 1 FROM naver_auto_performance_job WHERE customer_id=?
                AND possibility_id=? AND period_start<=? AND period_end>=?
                AND status IN ('reading','retry','partial','source_wait') LIMIT 1""",
                (customer_id,owner["possibility_id"],str(requested_end),str(requested_start))).fetchone()
            if overlaps:
                raise S.StoreRefused("해당 기간의 재확인이 이미 진행 중입니다")
            c.execute("""INSERT INTO naver_auto_manual_read
                (customer_id,requested_at,actor,period_start,period_end,possibility_id,request_kind) VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(customer_id) DO UPDATE SET requested_at=excluded.requested_at,
                    actor=excluded.actor,consumed_at=NULL,period_start=excluded.period_start,
                    period_end=excluded.period_end,possibility_id=excluded.possibility_id,request_kind=excluded.request_kind""",
                (customer_id,at,actor,str(requested_start),str(requested_end),owner["possibility_id"],
                 "manual_period" if start is not None else "manual"))
            self._performance_dirty(c, {"customer_id": customer_id, "period_start": str(requested_start),
                                       "period_end": str(requested_end)}, owner["possibility_id"], at)
        return {"status": "accepted", "requested_at": at}

    def generate_reports(self, now):
        """확정된 계정의 저장 자료만 집계한다. 생성/검토와 외부 게시는 별개다."""
        return _report_generate(self, now)

    def report_snapshots(self):
        return _report_snapshots(self)

    def report_snapshot_detail(self, report_id):
        return _report_snapshot_detail(self, report_id)

    def report_history(self, possibility_id, actor, now, *, period_key=None, before_report_id=None, limit=20):
        return _report_history(self, possibility_id, actor, now, period_key=period_key,
                                    before_report_id=before_report_id, limit=limit)

    def record_report_review(self, report_id, actor, now, decision, note):
        from . import store as S, views as W, sync as Y, inventory as I
        from app.naver_auto import scope as SC, org_snapshot as O
        self._need_writer()
        S._pos_int(report_id, "보고서")
        if decision not in ("approved", "held") or not isinstance(note, str) or not 1 <= len(note.strip()) <= 500:
            raise S.StoreRefused("검토 상태와 사유를 확인해 주세요")
        current = next((r for r in self.report_snapshots() if r["report_id"] == report_id), None)
        if current is None:
            raise S.StoreRefused("보고서가 변경되었습니다. 최신본을 확인해 주세요")
        org = W.load_org(self)
        scope = SC.scope_of(org, actor)
        catalog, catalog_state = I.catalog_status(self, now)
        if catalog_state != "accepted":
            raise S.StoreRefused("최신 전산 업체를 확인한 뒤 다시 검토해 주세요")
        company = next((row for row in catalog["items"] if row["possibility_id"] == current["possibility_id"]), None)
        visible = company is not None and company["stage_known"] and not company["stage_hidden"]
        own = SC.ownership_for_client(org,current["possibility_id"],current["possibility_id"],
                                     SC.MATCH_PID if visible else SC.MATCH_UNKNOWN)
        SC.require_client(org,scope,{current["possibility_id"]:own},current["possibility_id"],SC.ACT_APPROVE)
        if not O.allows_raising(Y.org_freshness(self,now)) or (decision == "approved" and (
                current["status"] != "ready" or current.get("validation", {}).get("status") != "complete")):
            raise S.StoreRefused("미완결 보고서는 승인할 수 없습니다")
        self._not_future(now, "검토 시각")
        with self._tx() as c:
            latest = c.execute("""SELECT MAX(report_id) FROM naver_auto_report_snapshot
                WHERE possibility_id=? AND period_key=?""", (current["possibility_id"], current["period_key"])).fetchone()
            dirty = c.execute("""SELECT pending FROM naver_auto_report_dirty
                WHERE possibility_id=? AND period_key=?""", (current["possibility_id"], current["period_key"])).fetchone()
            if latest[0] != report_id or (decision == "approved" and dirty and dirty[0]):
                raise S.StoreRefused("보고서가 변경 중입니다. 재대조 완료 후 확인해 주세요")
            c.execute("""INSERT INTO naver_auto_report_review(report_id,actor,at,decision,note) VALUES(?,?,?,?,?)""",
                      (report_id,actor,S._kst_text(now,"검토 시각"),decision,note.strip()))
        return {"report_id": report_id, "review_status": decision, "published": False}


    def structure_work(self, now, limit=24):
        """성과와 별도 재개 지점을 가지되 같은 일일/일요일 정책 및 예산을 쓴다."""
        if type(limit) is not int or not 1 <= limit <= 24:
            raise StoreRefused("원천 후보는 1~24개입니다")
        decisions = self.synchronize_management(now)
        snapshot, catalog = self.inventory_snapshot(now), self.account_catalog()
        if snapshot is None or catalog is None:
            return []
        # 성과 후보와 동일하게 이 동기 호출 안에서만 재사용한다. 요청 시 검증은 유지한다.
        matching_fingerprint = self.decision_fingerprint()
        day, at = now.astimezone(KST).date(), _kst_text(now,"현재")
        prior = {r["job_key"]:r for r in _rows(self._conn.execute(
            "SELECT * FROM naver_auto_structure_job WHERE cycle_day>=?", ((day-timedelta(days=8)).isoformat(),)))}
        candidates = []
        def add(job, priority):
            job["job_key"] = "structure:"+job["job_key"]
            old = prior.get(job["job_key"])
            if old and old["stage_revision"] != job["stage_revision"]:
                old = None
            if old and not self._collection_retry_ready(old, at):
                return
            if job["kind"] == "weekly" and not P.is_due(decisions[job["customer_id"]]["decision"],day,
                    started_cycle=date.fromisoformat(job["cycle_day"]) if old else None):
                return
            candidates.append((priority,"" if old is None else old["checked_at"],job["customer_id"],job))
        for cid,row in decisions.items():
            cadence = row["decision"].cadence
            if cadence == "blocked":
                continue
            period = P.period_for(cadence,day)
            add(self._performance_job(cid,cadence,period.cycle_day,period.since,period.until,row,snapshot,
                                      catalog["generated_at"], matching_fingerprint=matching_fingerprint),
                0 if cadence == "daily" else 1)
        for request in _rows(self._conn.execute("SELECT * FROM naver_auto_manual_read")):
            cid, row = request["customer_id"], decisions.get(request["customer_id"])
            if row is None or row["decision"].cadence == "blocked" or request.get("request_kind") == "manual_period":
                continue
            cycle = datetime.fromisoformat(request["requested_at"]).astimezone(KST).date()
            if not 0 <= (day-cycle).days <= 7:
                continue
            end = date.fromisoformat(request["period_end"]) if request.get("period_end") else cycle-timedelta(days=1)
            start = date.fromisoformat(request["period_start"]) if request.get("period_start") else (
                end if row["decision"].cadence == "daily" else end-timedelta(days=6))
            job = self._performance_job(cid,"manual",cycle,start,end,row,snapshot,catalog["generated_at"],
                                        matching_fingerprint=matching_fingerprint)
            job["job_key"] += ":"+request["requested_at"]
            job.update(requested_at=request["requested_at"],actor=request["actor"],generation=request["requested_at"])
            if not self.performance_account_valid(job, now):
                continue
            add(job,-1)
        selected, used = [], set()
        manual_selected = False
        has_daily = any(entry[0] == 0 for entry in candidates)
        for _,_,cid,job in sorted(candidates,key=lambda x:(x[0],x[1],x[2],x[3]["job_key"])):
            if not self._collection_account_ready(cid, at):
                continue
            if job["kind"] == "manual" and has_daily and manual_selected:
                continue
            if cid not in used:
                selected.append(job)
                used.add(cid)
                manual_selected = manual_selected or job["kind"] == "manual"
            if len(selected) == limit:
                break
        return selected

    def structure_account_valid(self, job, now):
        if not isinstance(job,dict) or not isinstance(job.get("job_key"),str) \
                or not job["job_key"].startswith("structure:") or job.get("kind") == "backfill":
            return False
        return self.performance_account_valid(dict(job,job_key=job["job_key"][10:]),now)

    def begin_structure_check(self, job, now):
        self._need_writer()
        if not self.structure_account_valid(job,now):
            raise StoreRefused("구조 원천이 바뀌었습니다")
        at = _kst_text(now,"구조 시작")
        if not self._collection_account_ready(job["customer_id"], at):
            raise StoreRefused("계정의 인증 또는 통신 재시도 대기 중입니다")
        with self._tx() as c:
            old = c.execute("SELECT status,next_try_at,attempts,stage_revision,error_code,checked_at FROM naver_auto_structure_job WHERE job_key=?",
                            (job["job_key"],)).fetchone()
            prior_retry = None if old is None else dict(zip(
                ("status","next_try_at","attempts","stage_revision","error_code","checked_at"), old))
            if old and old[3] == job["stage_revision"] and not self._collection_retry_ready(prior_retry, at):
                raise StoreRefused("구조를 다시 수집할 시각이 아닙니다")
            c.execute("""INSERT INTO naver_auto_structure_job
                (job_key,customer_id,cycle_day,stage_revision,status,checked_at,next_try_at,attempts)
                VALUES (?,?,?,?,'reading',?,?,0) ON CONFLICT(job_key) DO UPDATE SET
                status='reading',checked_at=excluded.checked_at,next_try_at=excluded.next_try_at,
                progress_json=CASE WHEN stage_revision=excluded.stage_revision THEN progress_json ELSE NULL END,
                progress_hash=CASE WHEN stage_revision=excluded.stage_revision THEN progress_hash ELSE NULL END,
                reasons_json=CASE WHEN stage_revision=excluded.stage_revision THEN reasons_json ELSE NULL END,
                attempts=CASE WHEN stage_revision=excluded.stage_revision THEN attempts ELSE 0 END,
                stage_revision=excluded.stage_revision""",
                (job["job_key"],job["customer_id"],job["cycle_day"],job["stage_revision"],at,_kst_text(now+timedelta(minutes=2),"구조 대기")))

    def structure_progress(self, job):
        from . import structure_reads as R
        row = self._conn.execute("SELECT progress_json,progress_hash FROM naver_auto_structure_job WHERE job_key=?",
                                 (job["job_key"],)).fetchone()
        if row is None or row[0] is None:
            return None
        if not isinstance(row[0], str) or hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
            raise R.CheckpointInvalid("구조 원천 지문이 다릅니다")
        try:
            source = json.loads(row[0])
        except (TypeError, ValueError):
            raise R.CheckpointInvalid("구조 원천 모양을 확인하지 못했습니다") from None
        R.validate_progress(source,job)
        return source

    def record_structure_progress(self, job, now, source):
        from . import structure_reads as R
        self._need_writer()
        if not self.structure_account_valid(job,now):
            raise StoreRefused("구조 원천이 바뀌었습니다")
        R.validate_progress(source,job)
        for record in source["records"].values():
            observed = datetime.fromisoformat(record["checked_at"])
            if observed.tzinfo is None or observed > now:
                raise StoreRefused("미래 구조 원천은 저장하지 않습니다")
        body = _json(source)
        if len(body.encode()) > 8*1024*1024:
            raise StoreRefused("구조 저장 한도를 넘었습니다")
        with self._tx() as c:
            prior = c.execute("SELECT progress_json FROM naver_auto_structure_job WHERE job_key=? AND status='reading'",
                              (job["job_key"],)).fetchone()
            if prior is None:
                raise StoreRefused("시작하지 않은 구조 수집입니다")
            old = json.loads(prior[0]) if prior[0] else None
            advanced = old is not None and source.get("next_index",0)>old.get("next_index",0)
            c.execute("""UPDATE naver_auto_structure_job SET progress_json=?,progress_hash=?,
                attempts=CASE WHEN ? THEN 0 ELSE attempts END WHERE job_key=?""",
                (body,hashlib.sha256(body.encode()).hexdigest(),int(advanced),job["job_key"]))

    def record_structure_check(self, job, now, values):
        from . import structure_reads as R
        self._need_writer()
        if not self.structure_account_valid(job,now):
            raise StoreRefused("구조 원천이 바뀌었습니다")
        self._not_future(now,"구조 시각")
        status,code = values.get("status"),values.get("error_code")
        if status not in ("ok","partial","retry","limited","reauth_required") \
                or (code is not None and (not isinstance(code,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",code))):
            raise StoreRefused("구조 상태가 올바르지 않습니다")
        try:
            source = self.structure_progress(job)
        except R.CheckpointInvalid:
            if status != "limited" or code != "CHECKPOINT_INVALID":
                raise StoreRefused("손상 원천을 완료로 저장하지 않습니다") from None
            source = None
        reasons = [] if source is None else R.validate_progress(source,job)
        if status == "ok" and (source is None or source["next_index"] != len(source["queue"])):
            raise StoreRefused("미완결 구조입니다")
        if values.get("reasons",reasons) != reasons:
            raise StoreRefused("공개 구조가 원천과 다릅니다")
        with self._tx() as c:
            row = c.execute("SELECT attempts FROM naver_auto_structure_job WHERE job_key=? AND status='reading'",
                            (job["job_key"],)).fetchone()
            if row is None:
                raise StoreRefused("시작하지 않은 구조 수집입니다")
            # 상세 원인이 확인된 순수 내부 한도만 실패 횟수에서 제외한다.
            attempts = row[0]+(status=="retry" and code not in ("REQUEST_DEADLINE", "REQUEST_CALL_CAP"))
            if attempts>=4 and status=="retry":
                status = "limited"  # 마지막 실제 실패 사유는 중단 상태와 별도로 보존한다.
            delay = (2,5,15,30)[max(0,min(attempts,4)-1)] if status=="retry" else 0
            if status == "retry" and code in ("REQUEST_DEADLINE", "REQUEST_CALL_CAP"):
                delay = 0
            if status == "limited" and code in ("SERVER", "NETWORK", "RATE", "REQUEST_DEADLINE", "REQUEST_CALL_CAP", "REQUEST_BUDGET"):
                delay = 60
            c.execute("""UPDATE naver_auto_structure_job SET status=?,checked_at=?,next_try_at=?,
                attempts=?,error_code=?,reasons_json=? WHERE job_key=?""",
                (status,_kst_text(now,"구조 확인"),_kst_text(now+timedelta(minutes=delay),"구조 대기"),
                 attempts,code,_json(reasons),job["job_key"]))
        return status

    def structure_checks(self, customer_ids, now):
        wanted = sorted({_customer_id(cid,"고객 번호") for cid in customer_ids})
        if not wanted:
            return {}
        decisions = self.management_states()
        latest = []
        for offset in range(0, len(wanted), 400):
            chunk = wanted[offset:offset+400]
            marks = ",".join("(?)" for _ in chunk)
            latest.extend(_rows(self._conn.execute(f"""WITH wanted(customer_id) AS (VALUES {marks})
                SELECT r.customer_id,r.cycle_day,r.stage_revision,r.status,r.checked_at,r.error_code,r.reasons_json
                FROM wanted w JOIN naver_auto_structure_job r ON r.rowid=(
                    SELECT p.rowid FROM naver_auto_structure_job p WHERE p.customer_id=w.customer_id
                    ORDER BY p.checked_at DESC, p.rowid DESC LIMIT 1)""", chunk)))
        out = {}
        for row in latest:
            cid = row["customer_id"]
            state = decisions.get(cid)
            if state is None or state["stage_revision"] != row["stage_revision"]:
                out[cid] = {"status":"pending","checked_at":None,"error_code":None,"reasons":[],"stale":True}
                continue
            cadence = P.classify(stage=state["stage_key"],stage_revision=state["stage_revision"],
                matched=state["possibility_id"] is not None,authority_valid=True,source_current=True,
                excluded_revision=state["excluded_revision"],included_revision=state["included_revision"]).cadence if state else "weekly"
            current = cadence != "blocked" and row["cycle_day"] == str(P.period_for(cadence,now).cycle_day)
            out[cid] = {"status":row["status"] if current else "pending","checked_at":row["checked_at"],
                        "error_code":row["error_code"],"reasons":json.loads(row["reasons_json"] or "[]"),"stale":not current}
        return out

    def _structure_reason_state(self, customer_ids, now):
        """목록용 SQL은 사유 배열을 반환하지 않는다. 현재 귀속/회차와 개수만 읽는다."""
        from . import management_store as MS
        wanted = sorted({_customer_id(cid, "고객 번호") for cid in customer_ids})
        if not wanted:
            return {}
        policies = MS.snapshot(self, now)
        latest = {}
        for offset in range(0, len(wanted), 400):
            chunk = wanted[offset:offset+400]
            marks = ",".join("(?)" for _ in chunk)
            rows = _rows(self._conn.execute(f"""WITH wanted(customer_id) AS (VALUES {marks})
                SELECT r.rowid AS row_id,r.customer_id,r.job_key,r.cycle_day,r.stage_revision,
                    r.status,r.checked_at,r.error_code,json_array_length(COALESCE(r.reasons_json,'[]')) AS reason_count
                FROM wanted w JOIN naver_auto_structure_job r ON r.rowid=(
                    SELECT p.rowid FROM naver_auto_structure_job p WHERE p.customer_id=w.customer_id
                    ORDER BY p.checked_at DESC,p.rowid DESC LIMIT 1)""", chunk))
            latest.update({row["customer_id"]: row for row in rows})
        out = {}
        for cid in wanted:
            policy, row = policies.get(cid), latest.get(cid)
            source_current = policy is not None and policy["decision"].cadence != "blocked"
            summary = {"status": "pending", "checked_at": None, "error_code": None,
                       "reason_count": 0, "stale": not source_current}
            if row is not None:
                current = source_current and row["stage_revision"] == policy["stage_revision"]
                if current:
                    cadence = policy["decision"].cadence
                    current = row["cycle_day"] == str(P.period_for(cadence, now).cycle_day) or (
                        ":manual:" in row["job_key"] and row["cycle_day"] == str(now.astimezone(KST).date()))
                count = row["reason_count"]
                current = current and type(count) is int and 0 <= count <= 10000
                summary = {"status": row["status"] if current else "pending",
                           "checked_at": row["checked_at"] if current else None,
                           "error_code": row["error_code"] if current else None,
                           "reason_count": count if current else 0, "stale": not current}
            out[cid] = (summary, None if row is None else row["row_id"])
        return out

    def structure_reason_summaries(self, customer_ids, now):
        """상세 사유를 역직렬화하지 않는 계정별 목록 요약."""
        return {cid: summary for cid, (summary, _) in self._structure_reason_state(customer_ids, now).items()}

    def structure_reason_page(self, customer_id, now, page=0):
        """현재 원천의 단일 계정만 50개씩 읽는다. 호출자가 직원 열람 범위를 확인한다."""
        _customer_id(customer_id, "고객 번호")
        if type(page) is not int or not 0 <= page < 200:
            raise StoreRefused("BAD_PAGE")
        summary, row_id = self._structure_reason_state([customer_id], now)[customer_id]
        if summary["stale"]:
            raise StoreRefused("SOURCE_STALE")
        total = summary["reason_count"]
        if page > 0 and page*50 >= total:
            raise StoreRefused("BAD_PAGE")
        items = [] if row_id is None else [json.loads(row[0]) for row in self._conn.execute(
            """SELECT j.value FROM naver_auto_structure_job r,json_each(COALESCE(r.reasons_json,'[]')) j
                WHERE r.rowid=? ORDER BY CAST(j.key AS INTEGER) LIMIT 50 OFFSET ?""", (row_id, page*50))]
        return {"items": items, "total": total, "page": page, "page_size": 50,
                "next_page": page+1 if (page+1)*50 < total else None,
                "checked_at": summary["checked_at"], "status": summary["status"]}


class Store(ManagedStorage):
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

    def read_snapshot(self):
        """한 화면의 현재 권한과 자료를 같은 읽기 거래에서 대조한다. 업무 쓰기는 하지 않는다."""
        return _report_read_snapshot(self)

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

    def snapshot_to(self, path) -> Dict[str, int]:
        """S14 온라인 백업. 같은 writer 스레드·거래 밖에서 새 private 파일에만 쓴다."""
        self._need_writer()
        raw = os.fspath(path)
        real = _check_path(raw)
        if real != raw or self._conn.in_transaction:
            raise StoreRefused("스냅샷 경로 또는 거래 상태가 올바르지 않습니다")
        _check_dir(real)
        fd, target = None, None
        try:
            fd = os.open(real, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            _own_file(fd, "스냅샷")
            target = _sqlite3.connect(real)
            started = monotonic()
            def progress(status, remaining, total):
                if monotonic() - started > 60:
                    raise StoreError("스냅샷 시간 초과")
            self._conn.backup(target, pages=256, progress=progress, sleep=0.05)
            target.close()
            target = None
            os.fsync(fd)
            return inspect_snapshot(real)
        except (OSError, _sqlite3.Error) as e:
            raise _wrap(e, "스냅샷을 만들지 못했습니다") from None
        finally:
            if target is not None:
                target.close()
            if fd is not None:
                os.close(fd)

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
            for table, additions in _REVISION_COLUMNS.items():
                columns = {r[1] for r in c.execute("PRAGMA table_info(" + table + ")")}
                for column, declaration in additions:
                    if column not in columns:
                        # 식별자와 선언은 위 고정 상수에서만 오며 외부 입력은 사용하지 않는다.
                        c.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " " + declaration)
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

    def record_decisions(self, pairs: Sequence[Tuple[int, int]], decision: str, decided_by: int, at: datetime, *,
                         audit_action: Optional[str] = None, guard: Optional[Callable[[], None]] = None) -> List[int]:
        """짝 확인 화면의 **묶음** 판단 — 모든 줄(과 ``audit_action`` 이 있으면 줄마다 열람·쓰기 기록)을 **한 거래로** 쌓는다.
        하나라도 틀리면 아무것도 적지 않는다(중간에 멈춰도 앞 줄만 남지 않는다 · S11 검토 batch-decisions-not-atomic).
        ``guard`` 는 거래 안에서 원천을 재검사하고 바뀌었으면 예외로 전체 저장을 거절한다."""
        self._need_writer()
        if decision not in DECISIONS:
            raise StoreRefused("판단은 confirmed · rejected 뿐입니다")
        if not isinstance(pairs, (list, tuple)) or not pairs:
            raise StoreRefused("판단할 짝이 없습니다")
        who, t = _person(decided_by, "판단한 직원"), _kst_text(at, "판단 시각")
        rows = [(_pos_int(pid, "가망 번호"), _customer_id(cid, "고객 번호")) for pid, cid in pairs]
        if len(set(rows)) != len(rows):
            raise StoreRefused("같은 짝이 두 번 들어왔습니다")
        audits = [] if audit_action is None else [self._access_vals(who, audit_action, "link", pid, "ok", at)
                                                  for pid, _cid in rows]
        self._not_future(at, "판단 시각")
        with self._tx() as c:
            if guard is not None:
                guard()   # 원천/담당 재검증과 판단 저장 사이에 다른 writer가 끼지 못하게 한다.
            ids = [c.execute(
                """INSERT INTO naver_auto_link_decision (possibility_id, customer_id, decision, decided_by, decided_at)
                   VALUES (?, ?, ?, ?, ?)""", (pid, cid, decision, who, t)).lastrowid for pid, cid in rows]
            for vals in audits:
                c.execute("""INSERT INTO naver_auto_access_log (at, emp_idx, action, target_kind, target_id, result)
                             VALUES (?, ?, ?, ?, ?, ?)""", vals)
            return ids

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

    def automatic_link_evidence(self) -> dict:
        """검증된 자동 연결 숫자 지문만 읽는다. 기존 NULL 이력은 근거로 승격하지 않는다."""
        # 읽기 프로세스가 writer의 추가형 이관보다 먼저 시작해도 예전 엄격 규칙으로 읽는다.
        if "auto_identity_fingerprint" not in {r[1] for r in self._conn.execute(
                "PRAGMA table_info(naver_auto_link_memory)")}:
            return {}
        return {(int(pid), int(cid)): fingerprint for pid, cid, fingerprint in self._conn.execute(
            """SELECT possibility_id, customer_id, auto_identity_fingerprint
               FROM naver_auto_link_memory WHERE link='auto' AND auto_identity_fingerprint IS NOT NULL""")}

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
                             provisional: bool = True, morning_generation: Optional[int] = None) -> "IssueTally":
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
            if morning_generation is not None:
                generation = _pos_int(morning_generation, "진행 세대")
                head = c.execute("""SELECT possibility_id,day,generation,status,binding
                    FROM naver_auto_morning_progress WHERE customer_id=?""", (cid,)).fetchone()
                binding = self._morning_progress_binding(cid,pid,today,checked_at)
                if head is None or tuple(head) != (pid,vals[1],generation,"reading",binding):
                    raise StoreRefused("진행 원천/세대가 달라졌습니다")
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
            if morning_generation is not None:
                # 원장·이슈와 같은 거래다. DATA_LATE 뒤 재시작도 낡은 완결 조각을 다시 쓰지 않는다.
                c.execute("""UPDATE naver_auto_morning_progress SET status='consumed',payload_bytes=0,next_try_at=?
                    WHERE customer_id=? AND generation=?""", (at,cid,morning_generation))
                c.execute("""UPDATE naver_auto_morning_chunk SET body=NULL,checksum=NULL,size=0
                    WHERE customer_id=? AND generation=?""", (cid,morning_generation))
        return IssueTally(dict(tally))

    def close_unlinked_issues(self, run_id: int, pairing_id: int, at: datetime, *, account_monitoring=False) -> "UnlinkCounts":
        """짝이 거절·무효가 된 열린 이슈를 「연결 해제로 닫힘」으로(M5) — 이 회차 날짜에 받은 그 짝 맞추기 기준.

        그 회차에 점검할 짝(확인 · 자동) · 「오늘 없음」 · 「이관 빠짐」으로 남은 짝은 이어진 것으로 본다. 그 밖의 짝이라도
        어제·오늘 이어졌던 짝(``link_memory`` · 어제·오늘 받은 짝 맞추기의 점검할 짝 · 오늘 없음 · 이관 빠짐 줄)은 하루
        기다린다(① 전산·단계가 하루 흔들린 것으로 이슈의 👀·🙈 를 잃지 않게).
        한꺼번에 많이(브레이크와 같은 비율) 닫으면 ``mass`` 로 알린다 — 닫힌 이슈는 짝이 돌아오면 다시 🆕 로 살아난다."""
        self._need_writer()
        I = _issue_rules()
        t = _kst_text(at, "닫은 시각")
        self._not_future(at, "닫은 시각")
        if type(account_monitoring) is not bool:
            raise StoreRefused("관제 여부는 참/거짓이어야 합니다")
        protected = set()
        if account_monitoring:
            from . import management_store as MS, inventory as IC
            policies = MS.snapshot(self, at)
            _, catalog_state = IC.catalog_status(self, at)
            if self.inventory_snapshot(at) is None or catalog_state != "accepted" \
                    or any(not row["source_current"] for row in policies.values()):
                return UnlinkCounts(0, 0, 0, False)  # 낡은 원천으로 연결 해제를 판정하지 않는다.
            protected = {(row["possibility_id"],cid) for cid,row in policies.items()
                         if row["matched"] and row["source_current"]}
        pnum = 0 if account_monitoring and pairing_id is None else _pos_int(pairing_id, "짝 맞추기 번호")
        with self._tx() as c:
            rid = _pos_int(run_id, "회차 번호")
            run_day = self._running_run_date(c, rid)
            today = date.fromisoformat(run_day)
            prow = c.execute("SELECT outcome, at FROM naver_auto_pairing_run WHERE pairing_id = ?", (pnum,)).fetchone()
            pat = None if prow is None else _aware_time(prow[1])
            pairing_current = prow is not None and prow[0] == SYNC_ACCEPTED and pat is not None and pat.astimezone(KST).date() == today
            if not pairing_current and not account_monitoring:
                raise StoreRefused("이 회차 날짜에 받은 짝 맞추기가 아닙니다")
            linked = {(int(p), int(k)) for p, k in c.execute(
                """SELECT possibility_id, customer_id FROM naver_auto_pairing_row
                   WHERE pairing_id = ? AND customer_id IS NOT NULL AND state IN (?, ?, ?, ?)""",
                (pnum, PAIR_CONFIRMED, PAIR_AUTO, PAIR_MISSING, PAIR_BROKEN))}
            if account_monitoring:
                linked = protected | (linked if pairing_current else set())
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

    # ── 알림(S10) — 원천 한 줄 + 받는 사람별 한 줄 · 보낸 결과 ──
    def record_alert(self, kind: str, day: date, source: str, template: str, codes: Sequence[str], link_path: str,
                     recipients: Sequence[Mapping], at: datetime) -> int:
        """알림 원천과 받는 사람별 줄을 한 거래로 적는다. 받는 사람 = {emp_idx, severity, params, held_reason(없어도 됨)}.

        ``held_reason`` 이 있으면 비서방으로 보내지 않고 남겨만 둔다(그림자 · 주말 · 조직 낡음). 없으면 「보낼 것」 —
        중복 방지 열쇠는 저장소가 만든다(종류·날짜·원천 번호·받는 사람 — 다시 보내도 ① 이 같은 날 한 번만 넣는다).
        요약·목록 종류는 하루 한 번(``AlertExists``)."""
        self._need_writer()
        if kind not in ALERT_KINDS:
            raise StoreRefused("알림 종류가 아닙니다")
        if source not in ALERT_SOURCES:
            raise StoreRefused("알림이 나온 곳이 아닙니다")
        d, t = _day_text(day, "알림 날짜"), _kst_text(at, "알림 시각")
        self._not_future(at, "알림 시각")
        tpl = _code(template, _ALERT_TEMPLATE, "문구 틀")
        cs = _codes(codes)
        link = _alert_link(link_path)
        people = _seq(recipients, "받는 사람")
        if len(people) > ALERT_MAX_RECIPIENTS:
            raise StoreRefused("받는 사람이 너무 많습니다")
        rows, seen = [], set()
        for r in people:
            if not isinstance(r, Mapping):
                raise StoreRefused("받는 사람 모양이 아닙니다")
            emp = _person(r.get("emp_idx"), "받는 사람")
            if emp in seen:
                raise StoreRefused("같은 사람이 두 번 있습니다")
            seen.add(emp)
            sev = r.get("severity")
            if sev not in ALERT_SEVERITIES:
                raise StoreRefused("알림 중요도가 아닙니다")
            held = r.get("held_reason")
            if held is not None and held not in HELD_REASONS:
                raise StoreRefused("남겨 둔 까닭이 아닙니다")
            rows.append((emp, sev, _alert_params(r.get("params", {})), held))
        expires = _kst_text(at + ALERT_TTL, "알림 기한")
        with self._tx() as c:
            if kind != ALERT_SYSTEM and c.execute("SELECT 1 FROM naver_auto_alert WHERE kind = ? AND day = ?",
                                                  (kind, d)).fetchone():
                raise AlertExists("그 날 그 알림은 이미 만들었습니다")
            aid = c.execute(
                """INSERT INTO naver_auto_alert (kind, day, source, template, codes, link_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""", (kind, d, source, tpl, json.dumps(cs), link, t)).lastrowid
            tag = _ALERT_TAGS[kind] + ":" + d.replace("-", "") + ":" + str(aid) + ":"
            for emp, sev, params, held in rows:
                status = DELIVERY_PENDING if held is None else DELIVERY_HELD
                c.execute(
                    """INSERT INTO naver_auto_alert_recipient (alert_id, emp_idx, severity, params, dedupe_key, status,
                           held_reason, attempts, next_try_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                    (aid, emp, sev, params, tag + str(emp), status, held, t if held is None else None, expires))
        return aid

    def record_delivery(self, recipient_id: int, status: str, at: datetime, *, message_idx: Optional[int] = None,
                        error_kind: Optional[str] = None, next_try_at: Optional[datetime] = None) -> None:
        """보낸 결과 한 줄 — 「보낼 것」에서만 바뀐다(끝난 줄은 다시 바뀌지 않는다).

        ``pending`` = 이번에 못 보냄 · 다시 해 볼 시각(``next_try_at``)과 까닭(``error_kind``) 필요 · ``sent`` = ① 메시지 번호
        필요 · ``duplicate``·``cap_target``·``cap_total`` = ① 이 넣지 않음 · ``failed`` = 까닭 필요. 시도 수는 저장소가 센다."""
        self._need_writer()
        rid = _pos_int(recipient_id, "받는 사람 줄 번호")
        if status not in DELIVERY_STATUSES or status == DELIVERY_HELD:
            raise DeliveryRefused("보낸 결과가 아닙니다")
        t = _kst_text(at, "보낸 시각")
        self._not_future(at, "보낸 시각")
        mid = None
        if status == DELIVERY_SENT:
            mid = _pos_int(message_idx, "① 메시지 번호")
        elif message_idx is not None:
            raise DeliveryRefused("넣지 않은 알림에 메시지 번호가 있습니다")
        kind = None if error_kind is None else _code(error_kind, _ERROR_KIND, "못 보낸 까닭")
        if status in (DELIVERY_PENDING, DELIVERY_FAILED) and kind is None:
            raise DeliveryRefused("못 보낸 까닭이 없습니다")
        nxt = None
        if status == DELIVERY_PENDING:
            if next_try_at is None:
                raise DeliveryRefused("다시 해 볼 시각이 없습니다")
            nxt = _kst_text(next_try_at, "다시 해 볼 시각")
            if next_try_at <= at:
                raise DeliveryRefused("다시 해 볼 시각은 지금보다 뒤여야 합니다")
        elif next_try_at is not None:
            raise DeliveryRefused("끝난 알림에 다시 해 볼 시각이 있습니다")
        with self._tx() as c:
            row = c.execute("SELECT status FROM naver_auto_alert_recipient WHERE recipient_id = ?", (rid,)).fetchone()
            if row is None:
                raise DeliveryRefused("없는 받는 사람 줄입니다")
            if row[0] != DELIVERY_PENDING:
                raise DeliveryRefused("이미 끝난 알림입니다")
            c.execute(
                """UPDATE naver_auto_alert_recipient SET status = ?, attempts = attempts + 1, next_try_at = ?,
                       message_idx = ?, error_kind = ?, finished_at = ? WHERE recipient_id = ? AND status = 'pending'""",
                (status, nxt, mid, kind, None if status == DELIVERY_PENDING else t, rid))

    def record_heartbeat(self, day: date, status: str, at: datetime, *, sent: bool,
                         error_kind: Optional[str] = None) -> None:
        """「오늘 끝」 심박을 ① 에 보냈는지(대표 결정 A3) — 날짜 · ok/trouble · 보냄 여부 · 시도 수 · 못 보낸 까닭."""
        self._need_writer()
        d, t = _day_text(day, "심박 날짜"), _kst_text(at, "심박 시각")
        self._not_future(at, "심박 시각")
        if status not in ("ok", "trouble"):
            raise StoreRefused("심박 상태가 아닙니다")
        if type(sent) is not bool:
            raise StoreRefused("보냄 여부는 참/거짓이어야 합니다")
        kind = None if error_kind is None else _code(error_kind, _ERROR_KIND, "못 보낸 까닭")
        if sent == (kind is not None):
            raise StoreRefused("보냈으면 까닭이 없고, 못 보냈으면 까닭이 있어야 합니다")
        with self._tx() as c:
            old = self._meta_json(c, "heartbeat")
            if isinstance(old, dict) and old.get("day") == d and old.get("sent_at") is not None:
                raise StoreRefused("오늘 심박은 이미 보냈습니다")
            tries = old.get("tries", 0) if isinstance(old, dict) and old.get("day") == d else 0
            if isinstance(tries, bool) or not isinstance(tries, int) or tries < 0:
                raise StoreError("저장된 심박 기록을 읽지 못했습니다")
            self._set_meta(c, "heartbeat", json.dumps(
                {"day": d, "status": status, "tries": tries + 1, "last_try_at": t, "sent_at": t if sent else None,
                 "error_kind": kind}, sort_keys=True))

    # ── 화면 API(S11) — 열람·쓰기 기록 · 🔔 읽음 · 점검 기준값 ──
    def record_access(self, viewer_idx: Optional[int], action: str, target_kind: str, target_id: Optional[int],
                      result: str, at: datetime) -> int:
        """열람·쓰기 한 줄(누가 · 언제 · 무엇을 · 어디에 · 결과). 코드 모양만 받는다 — 이름·금액·고객 번호가 들어갈 칸이 없다.
        ``viewer_idx`` 는 ① 직원 번호(대표 = 0) · 로그인 전 실패처럼 사람을 모르면 None."""
        self._need_writer()
        vals = self._access_vals(viewer_idx, action, target_kind, target_id, result, at)
        self._not_future(at, "기록 시각")
        with self._tx() as c:
            return c.execute(
                """INSERT INTO naver_auto_access_log (at, emp_idx, action, target_kind, target_id, result)
                   VALUES (?, ?, ?, ?, ?, ?)""", vals).lastrowid

    @staticmethod
    def _access_vals(viewer_idx: Optional[int], action: str, target_kind: str, target_id: Optional[int], result: str,
                     at: datetime) -> tuple:
        """열람·쓰기 기록 한 줄의 값 — 대상 번호는 화면 API 가 받는 범위(0 이상 · 2**63 미만)와 같게(검토 audit-target-id)."""
        if target_kind not in ACCESS_TARGETS:
            raise StoreRefused("기록 대상 종류가 아닙니다")
        vals = (_kst_text(at, "기록 시각"), None if viewer_idx is None else _person(viewer_idx, "본 사람"),
                _code(action, _ACCESS_CODE, "동작"), target_kind,
                None if target_id is None else _person(target_id, "대상 번호"), _code(result, _ACCESS_CODE, "결과"))
        if len(vals[2]) > ACCESS_CODE_MAX or len(vals[5]) > ACCESS_CODE_MAX:
            raise StoreRefused("코드가 너무 깁니다")
        return vals

    def mark_alert_read(self, recipient_id: int, emp_idx: int, at: datetime) -> bool:
        """🔔 읽음 — **자기 줄만**(받는 사람 번호가 같을 때만). 이번에 읽음으로 바꿨으면 True · 이미 읽었으면 False.
        없는 줄과 남의 줄은 같은 ``ScreenRefused("not-found")``(있는지 드러내지 않는다)."""
        self._need_writer()
        rid, emp, t = _pos_int(recipient_id, "받는 사람 줄 번호"), _person(emp_idx, "읽은 사람"), _kst_text(at, "읽은 시각")
        self._not_future(at, "읽은 시각")
        with self._tx() as c:
            row = c.execute("SELECT read_at FROM naver_auto_alert_recipient WHERE recipient_id = ? AND emp_idx = ?",
                            (rid, emp)).fetchone()
            if row is None:
                raise ScreenRefused("not-found")
            if row[0] is not None:
                return False
            c.execute("""UPDATE naver_auto_alert_recipient SET read_at = ?
                         WHERE recipient_id = ? AND emp_idx = ? AND read_at IS NULL""", (t, rid, emp))
            return True

    def mark_alerts_read_all(self, emp_idx: int, since_day: date, at: datetime) -> int:
        """🔔 모두 읽음 — 그 사람 줄 중 ``since_day`` 뒤(그날 포함) 알림만. 바꾼 줄 수."""
        self._need_writer()
        emp, d, t = _person(emp_idx, "읽은 사람"), _day_text(since_day, "시작 날짜"), _kst_text(at, "읽은 시각")
        self._not_future(at, "읽은 시각")
        with self._tx() as c:
            return c.execute(
                """UPDATE naver_auto_alert_recipient SET read_at = ? WHERE emp_idx = ? AND read_at IS NULL
                   AND alert_id IN (SELECT alert_id FROM naver_auto_alert WHERE day >= ?)""", (t, emp, d)).rowcount

    def record_thresholds(self, changes: Mapping, changed_by: int, at: datetime):
        """기준값을 고친다 — 지금 값에 바꿀 칸만 얹어 규칙(``thresholds.validate``)을 지난 것만 · 하나라도 틀리면 아무것도
        바꾸지 않는다. 고치기 전·뒤 9칸을 한 줄로 쌓는다. **누가 고칠 수 있는지(대표만 · Q3)는 부르는 쪽이 scope 로 판정한다.**"""
        self._need_writer()
        T = _threshold_rules()
        if not isinstance(changes, Mapping) or not changes:
            raise ScreenRefused("no-change")
        who, t = _person(changed_by, "고친 사람"), _kst_text(at, "고친 시각")
        self._not_future(at, "고친 시각")
        with self._tx() as c:
            cur = self._current_thresholds(c)
            try:
                new = T.validate(dict(changes), cur)
            except T.ThresholdOutOfRange as e:
                # 틀린 칸만(맞는 칸까지 「틀렸다」고 하지 않게 · 검토 thresholds-all-fields-flagged) · 아는 이름만
                names = {f.name for f in fields(T.Thresholds)}
                bad = [k for k in getattr(e, "fields", ()) if isinstance(k, str) and k in names]
                raise ScreenRefused("out-of-range", tuple(sorted(set(bad)))) from None
            if new == cur:
                raise ScreenRefused("no-change")
            c.execute("""INSERT INTO naver_auto_threshold_change (at, changed_by, before_values, after_values)
                         VALUES (?, ?, ?, ?)""", (t, who, _threshold_values(cur), _threshold_values(new)))
        return new

    def _current_thresholds(self, c):
        row = c.execute("SELECT after_values FROM naver_auto_threshold_change ORDER BY change_id DESC LIMIT 1").fetchone()
        return _threshold_rules().DEFAULTS if row is None else _read_thresholds(row[0])

    def thresholds(self):
        """지금 점검 기준값 — 고친 이력의 가장 늦은 줄(없으면 처음 값). 아침 점검(S14 배선)이 이 값을 넘긴다."""
        return self._current_thresholds(self._conn)

    def threshold_changes(self, limit: int = 50) -> List[dict]:
        """고친 이력 — 새것부터 · {change_id · at · changed_by · before · after}."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= THRESHOLD_HISTORY_MAX_READ:
            raise StoreRefused("몇 줄인지 범위 밖입니다")
        out = []
        for cid, at_raw, by, before, after in self._conn.execute(
                """SELECT change_id, at, changed_by, before_values, after_values FROM naver_auto_threshold_change
                   ORDER BY change_id DESC LIMIT ?""", (limit,)):
            at_ = _aware_time(at_raw)
            if at_ is None:
                raise StoreError("저장된 기준값 이력을 읽지 못했습니다")
            out.append({"change_id": cid, "at": at_, "changed_by": by,
                        "before": asdict(_read_thresholds(before)), "after": asdict(_read_thresholds(after))})
        return out

    def my_alerts(self, emp_idx: int, since_day: date, limit: int = 200) -> List[dict]:
        """🔔 — **그 사람에게 온 줄만**(남겨 둔 것 포함) · 새것부터. 원천(종류 · 날짜 · 문구 틀 · 코드 · 경로)을 함께 준다."""
        emp, d = _person(emp_idx, "받는 사람"), _day_text(since_day, "시작 날짜")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 1000:
            raise StoreRefused("몇 줄인지 범위 밖입니다")
        cur = self._conn.execute(
            """SELECT r.recipient_id, r.severity, r.params, r.status, r.held_reason, r.read_at, r.finished_at,
                      a.alert_id, a.kind, a.day, a.source, a.template, a.codes, a.link_path, a.created_at
               FROM naver_auto_alert_recipient r JOIN naver_auto_alert a ON a.alert_id = r.alert_id
               WHERE r.emp_idx = ? AND a.day >= ? ORDER BY a.alert_id DESC, r.recipient_id DESC LIMIT ?""",
            (emp, d, limit))
        names = [x[0] for x in cur.description]
        return [self._alert_out(names, r) for r in cur.fetchall()]

    def access_log(self, limit: int = 100, viewer_idx: Optional[int] = None) -> List[dict]:
        """열람·쓰기 기록 — 새것부터(사람을 주면 그 사람만)."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= ACCESS_LOG_MAX_READ:
            raise StoreRefused("몇 줄인지 범위 밖입니다")
        sql, args = "SELECT * FROM naver_auto_access_log", ()
        if viewer_idx is not None:
            sql, args = sql + " WHERE emp_idx = ?", (_person(viewer_idx, "본 사람"),)
        cur = self._conn.execute(sql + " ORDER BY log_id DESC LIMIT ?", args + (limit,))
        names = [x[0] for x in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]

    def issue_new_since(self) -> dict:
        """지금 🆕 인 이슈 → 가장 늦게 🆕 가 된 시각(열림 · 다시 나옴 · 예외 끝남 · 사람이 해결했는데 그대로) — 12시간 안
        풀린 🟡 를 한 단계 위로 올리는 판정(S11 · v1.4 §6)이 쓴다. 기록이 없으면 이슈의 고친 시각."""
        out = {}
        for iid, since, upd in self._conn.execute(
                """SELECT i.issue_id, (SELECT MAX(e.at) FROM naver_auto_issue_event e
                                        WHERE e.issue_id = i.issue_id AND e.to_state = 'new'), i.updated_at
                   FROM naver_auto_issue i WHERE i.state = 'new'"""):
            t = _aware_time(since if since is not None else upd)
            if t is None:
                raise StoreError("저장된 이슈 시각을 읽지 못했습니다")
            out[int(iid)] = t
        return out

    # ── 전체 전산 업체 목록: 기존 계약별 점검/성과 원장을 변경하지 않는다 ──
    def record_account_catalog(self, body, ids, received_at: datetime) -> None:
        clean = E.validate_account_catalog(body, received_at)
        at = _kst_text(received_at, "전체 업체 수신 시각")
        self._not_future(received_at, "전체 업체 수신 시각")
        rows = []
        for r in ids:
            if not isinstance(r, E.NaverIdRow):
                raise StoreRefused("네이버 번호 자료 모양이 다릅니다")
            _pos_int(r.possibility_id, "가망 번호")
            vals = (r.vendor, r.customer_id_raw, r.ad_account_no_raw)
            if any(v is not None and (not isinstance(v, str) or len(v) > 200) for v in vals):
                raise StoreRefused("네이버 번호 자료 길이가 다릅니다")
            rows.append(asdict(r))
        with self._tx() as c:
            old = self._meta_json(c, "account_catalog")
            if old is not None:
                if datetime.fromisoformat(clean["generated_at"]) < datetime.fromisoformat(old["generated_at"]):
                    raise StoreRefused("전체 업체 자료 시각이 역행합니다")
                if old["total"] and clean["total"] < old["total"] * 0.8:
                    raise StoreRefused("전체 업체 자료 급감: 이전 수락본을 유지합니다")
            self._set_meta(c, "account_catalog", json.dumps({**clean, "ids": rows, "received_at": at}, ensure_ascii=False))
            self._set_meta(c, "account_catalog_status", json.dumps({"at": at, "state": "accepted"}))

    def record_account_catalog_failure(self, at: datetime, code: str) -> None:
        code = _code(code, _ERROR_KIND, "목록 동기화 실패 코드")
        with self._tx() as c:
            self._set_meta(c, "account_catalog_status", json.dumps({"at": _kst_text(at, "시각"),
                                                                  "state": "failed", "code": code}))

    def account_catalog(self):
        return self._meta_json(self._conn, "account_catalog")

    def account_catalog_status(self):
        return self._meta_json(self._conn, "account_catalog_status")

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

    # ── 공유 30일 성과(G1~G3) ──
    def metrics_context(self, now: datetime) -> Optional[dict]:
        """오늘 현재 수락본의 전체 짝. 낡음·거절·중복·판단 변경은 원천 전체를 보류한다."""
        _kst_text(now, "지금")
        today = now.astimezone(KST).date()
        morning_start = datetime.combine(today, time(6, 30), tzinfo=KST)
        if not any(r["status"] == RUN_DONE for r in self.runs_on(today)):
            return None
        pair = self.last_pairing()
        read_at, stage_at = self.accounts_read_at(), self.stage_as_of()
        if pair is None or pair["outcome"] != SYNC_ACCEPTED or read_at is None or stage_at is None \
                or not morning_start <= read_at <= now or stage_at.astimezone(KST).date() != today or stage_at > now \
                or pair["at"].astimezone(KST).date() != today or pair["at"] > now \
                or pair["accounts_read_at"] != read_at or pair["stages_as_of"] != stage_at \
                or pair["decisions_hash"] != self.decision_fingerprint():
            return None
        for kind in (SYNC_ACCOUNTS, SYNC_STAGES):
            sync = self.last_sync(kind)
            if sync is None or sync["outcome"] != SYNC_ACCEPTED:
                return None
        accounts = {a["customer_id"] for a in self.accounts() if a["present"] == 1}
        prospects = {p["possibility_id"]: p for p in self.prospects()}
        pairs, seen = {}, set()
        canonical = []
        for row in self.pairing_rows(pair["pairing_id"]):
            if row["state"] not in PAIR_CHECKABLE:
                continue
            pid, cid = row["possibility_id"], row["customer_id"]
            p = prospects.get(pid)
            if cid in seen or cid not in accounts or p is None or p["present"] != 1 \
                    or p["stage_conflict"] or p["end_unreadable"] or not 0 < pid < 10 ** 15:
                return None
            end = None if p["latest_end_date"] is None else date.fromisoformat(p["latest_end_date"])
            if H.eligibility_reason(p["stage_key"], stage_at, end, now) is not None:
                return None
            seen.add(cid)
            pairs.setdefault(pid, []).append(dict(possibility_id=pid, customer_id=cid, state=row["state"],
                                                  stage_key=p["stage_key"], latest_end_date=end))
            canonical.append([pid, cid, row["state"], p["stage_key"], p["latest_end_date"]])
        # 시각은 위에서 최신 수락본과 대조한다. 의미가 같은 정기 동기화만으로 캐시를 버리지 않는다.
        source = [today.isoformat(), pair["decisions_hash"], canonical]
        fingerprint = hashlib.sha256(json.dumps(source, separators=(",", ":")).encode("utf-8")).hexdigest()
        counts = Counter()
        for pid, status, attempts in self._conn.execute(
                "SELECT possibility_id, status, attempts FROM naver_auto_metrics_delivery WHERE day = ? AND context_hash = ?",
                (today.isoformat(), fingerprint)):
            if pid in pairs and status != "stored":
                # 마지막 허용 시도 중 프로세스가 끝나도 추가 호출 없이 보류로 보인다.
                counts["held" if attempts >= METRICS_MAX_ATTEMPTS and status != "no_client"
                       else "retry" if status in ("reading", "pending", "retry") else status] += 1
        return dict(fingerprint=fingerprint, pairs=pairs, stage_as_of=stage_at, day=today,
                    delivery_counts=dict(counts))

    def _metrics_context_for(self, fingerprint, now, possibility_id=None):
        context = self.metrics_context(now)
        if context is None or not isinstance(fingerprint, str) or context["fingerprint"] != fingerprint \
                or (possibility_id is not None and possibility_id not in context["pairs"]):
            raise StoreRefused("성과 원천이 바뀌었거나 완결되지 않았습니다")
        return context

    def _metrics_delivery(self, possibility_id, day):
        cur = self._conn.execute("SELECT * FROM naver_auto_metrics_delivery WHERE day = ? AND possibility_id = ?",
                                 (day.isoformat(), _pos_int(possibility_id, "가망 번호")))
        row = cur.fetchone()
        return None if row is None else dict(zip([d[0] for d in cur.description], row))

    def metrics_work(self, context_hash: str, now: datetime, limit: int) -> List[int]:
        """미시도 → 오래 기다린 순. 실패·보류도 last_try가 남아 앞 번호가 뒷 번호를 굶기지 않는다."""
        if type(limit) is not int or not 0 < limit <= 20:
            raise StoreRefused("성과 작업 수가 범위 밖입니다")
        context = self._metrics_context_for(context_hash, now)
        # 예약 순서만 고를 때 큰 30일 원천 본문을 계정마다 읽지 않는다.
        rows = {pid: (fingerprint, status, last, due, attempts, error)
                for pid, fingerprint, status, last, due, attempts, error in self._conn.execute(
            """SELECT possibility_id, context_hash, status, last_try_at, next_try_at, attempts, error_kind
               FROM naver_auto_metrics_delivery WHERE day = ?""", (context["day"].isoformat(),))}
        wanted = []
        for pid in context["pairs"]:
            row = rows.get(pid)
            if row is not None and row[0] == context_hash:
                if row[1] in ("stored", "no_client") or row[4] >= METRICS_MAX_ATTEMPTS \
                        or (row[1] == "held" and row[5] == "capacity"):
                    continue
                due = _aware_time(row[3])
                if due is None:
                    raise StoreError("저장된 성과 재시도 시각을 읽지 못했습니다")
                if now < due:
                    continue
            wanted.append(("" if row is None else row[2], pid))
        return [pid for _at, pid in sorted(wanted)[:limit]]

    def begin_metrics_attempt(self, possibility_id: int, context_hash: str, now: datetime) -> None:
        """외부 호출 전에 시도와 재시각을 영구 기록한다. 재시작해도 마지막 실패를 기억한다."""
        self._need_writer()
        self._not_future(now, "시도 시각")
        at = _kst_text(now, "시도 시각")
        with self._tx() as c:
            context = self._metrics_context_for(context_hash, now, possibility_id)
            day = context["day"]
            row = self._metrics_delivery(possibility_id, day)
            same = row is not None and row["context_hash"] == context_hash
            if same and (row["status"] in ("stored", "no_client") or row["attempts"] >= METRICS_MAX_ATTEMPTS
                         or (row["status"] == "held" and row["error_kind"] == "capacity")
                         or now < _aware_time(row["next_try_at"])):
                raise StoreRefused("성과를 다시 시도할 때가 아닙니다")
            attempts = row["attempts"] + 1 if same else 1
            gap = (2, 5, 15, 30)[min(attempts, 4) - 1]
            next_at = _kst_text(now + timedelta(minutes=gap), "재시도 시각")
            c.execute("""INSERT INTO naver_auto_metrics_delivery
                       (day, possibility_id, context_hash, status, attempts, last_try_at, next_try_at)
                       VALUES (?, ?, ?, 'reading', ?, ?, ?)
                       ON CONFLICT (day, possibility_id) DO UPDATE SET
                         source_json = CASE WHEN context_hash = excluded.context_hash THEN source_json ELSE NULL END,
                         payload_json = CASE WHEN context_hash = excluded.context_hash THEN payload_json ELSE NULL END,
                         source_hash = CASE WHEN context_hash = excluded.context_hash THEN source_hash ELSE NULL END,
                         collected_at = CASE WHEN context_hash = excluded.context_hash THEN collected_at ELSE NULL END,
                         context_hash = excluded.context_hash, status = 'reading', attempts = excluded.attempts,
                         last_try_at = excluded.last_try_at, next_try_at = excluded.next_try_at, error_kind = NULL""",
                      (day.isoformat(), possibility_id, context_hash, attempts, at, next_at))

    def record_metrics_snapshot(self, possibility_id: int, context_hash: str, accounts, now: datetime) -> None:
        """전체 계정·30일 확정 원천과 집계를 한 거래로 보관한다. 일부 원천은 아무것도 저장하지 않는다."""
        from . import metrics as G
        self._need_writer()
        self._not_future(now, "읽은 시각")
        at = _kst_text(now, "읽은 시각")
        with self._tx() as c:
            context = self._metrics_context_for(context_hash, now, possibility_id)
            row = self._metrics_delivery(possibility_id, context["day"])
            if row is None or row["context_hash"] != context_hash or row["status"] != "reading":
                raise StoreRefused("시작하지 않은 성과 읽기입니다")
            try:
                payload = G.aggregate(possibility_id, tuple(r["customer_id"] for r in context["pairs"][possibility_id]),
                                      accounts, context["day"], now)
                raw = json.dumps(accounts, sort_keys=True, separators=(",", ":"), allow_nan=False)
            except (G.MetricsIncomplete, TypeError, ValueError):
                raise StoreRefused("성과 원천이 완결되지 않았습니다") from None
            digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
            c.execute("""UPDATE naver_auto_metrics_delivery SET source_json = ?, payload_json = ?, source_hash = ?,
                         collected_at = ?, status = 'pending' WHERE day = ? AND possibility_id = ?""",
                      (raw, json.dumps(payload, sort_keys=True, separators=(",", ":")), digest, at,
                       context["day"].isoformat(), possibility_id))

    def metrics_payload(self, possibility_id: int, context_hash: str, now: datetime) -> Optional[dict]:
        """송신 직전에 오늘 짝과 원천 지문·전체 날짜·합계를 재검사한다. 번호가 없는 최소 본문만 반환한다."""
        from . import metrics as G
        context = self._metrics_context_for(context_hash, now, possibility_id)
        row = self._metrics_delivery(possibility_id, context["day"])
        if row is None or row["context_hash"] != context_hash or row["payload_json"] is None:
            return None
        try:
            raw = row["source_json"]
            if not isinstance(raw, str) or hashlib.sha256(raw.encode("utf-8")).hexdigest() != row["source_hash"]:
                raise ValueError()
            payload = G.aggregate(possibility_id, tuple(r["customer_id"] for r in context["pairs"][possibility_id]),
                                  json.loads(raw), context["day"], now)
            if payload != json.loads(row["payload_json"]):
                raise ValueError()
        except (G.MetricsIncomplete, TypeError, ValueError, RecursionError):
            raise StoreError("저장된 성과 원천을 확인하지 못했습니다") from None
        return payload

    def finish_metrics_attempt(self, possibility_id: int, context_hash: str, now: datetime, outcome: str, *,
                               error_kind: Optional[str] = None) -> str:
        """받았다는 정상 응답만 stored. 미연결·실패·보류를 성공으로 표시하지 않는다."""
        self._need_writer()
        self._not_future(now, "시도 끝 시각")
        if outcome not in ("stored", "no_client", "held", "retry"):
            raise StoreRefused("성과 전송 결과가 아닙니다")
        code = None if error_kind is None else _code(error_kind, _ERROR_KIND, "성과 오류 종류")
        with self._tx() as c:
            context = self._metrics_context_for(context_hash, now, possibility_id)
            row = self._metrics_delivery(possibility_id, context["day"])
            if row is None or row["context_hash"] != context_hash or row["status"] not in ("reading", "pending"):
                raise StoreRefused("진행 중인 성과 전송이 아닙니다")
            if outcome in ("stored", "no_client") and row["payload_json"] is None:
                raise StoreRefused("원천 없이 성과 전송을 완료할 수 없습니다")
            if outcome in ("held", "retry") and row["attempts"] >= METRICS_MAX_ATTEMPTS and code != "capacity":
                outcome, code = "held", "attempt-cap"
            c.execute("""UPDATE naver_auto_metrics_delivery SET status = ?, error_kind = ?
                         WHERE day = ? AND possibility_id = ?""",
                      (outcome, code, context["day"].isoformat(), possibility_id))
        return outcome

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

    def hold_body_sha256(self, kind: str, hold_id: int) -> Optional[str]:
        """관리 승인 대조용: 파싱/재직렬화 전 저장된 TEXT의 정확한 UTF-8 해시만 반환한다."""
        if kind not in SYNC_KINDS or type(hold_id) is not int or hold_id <= 0:
            raise StoreRefused("붙잡음 식별자가 올바르지 않습니다")
        row = self._conn.execute("SELECT body FROM naver_auto_hold WHERE kind = ? AND sync_id = ?",
                                 (kind, hold_id)).fetchone()
        if row is None:
            return None
        if not isinstance(row[0], str):
            raise _bad_hold()
        return hashlib.sha256(row[0].encode("utf-8")).hexdigest()

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

    def issue_hand_events(self, issue_ids, kinds) -> Dict[int, List[dict]]:
        """이슈 여럿의 기록 중 고른 종류만 — {이슈 번호: [기록 …]}(번호 순). 관제 판이 이슈마다 따로 읽지 않게 한 번에(S13 ·
        검토 board-n-plus-1). 칸은 사람 손길 표시에 쓰는 것만."""
        ids = [_pos_int(n, "이슈 번호") for n in issue_ids]
        ks = sorted({str(k) for k in kinds})
        out: Dict[int, List[dict]] = {}
        if not ids or not ks:
            return out
        cols = "issue_id, event_id, kind, at, by_person, note, exception_until"
        names = [c.strip() for c in cols.split(",")]
        for n in range(0, len(ids), ISSUE_READ_CHUNK):
            part = ids[n:n + ISSUE_READ_CHUNK]
            q = ("SELECT " + cols + " FROM naver_auto_issue_event WHERE issue_id IN (" + ",".join("?" * len(part)) +
                 ") AND kind IN (" + ",".join("?" * len(ks)) + ") ORDER BY issue_id, event_id")
            for r in self._conn.execute(q, (*part, *ks)):
                d = dict(zip(names, r))
                out.setdefault(int(d["issue_id"]), []).append(d)
        return out

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

    def account_day_marks_on(self, day: date) -> dict:
        """그 날 계정 하루치 {고객 번호: (상태, 가망 번호)} — 같은 날 다시 도는 회차가 「이 짝이 오늘 끝났나」를 가망까지
        대조해 본다(회차 사이에 계정이 다른 가망 짝으로 바뀌면 새 짝을 다시 읽게 · 검토 failclosed-retry)."""
        return {int(cid): (st, None if pid is None else int(pid)) for cid, st, pid in self._conn.execute(
            "SELECT customer_id, status, possibility_id FROM naver_auto_account_day WHERE day = ?",
            (_day_text(day, "날짜"),))}

    def account_day_checks_on(self, day: date) -> dict:
        """그 날 계정 하루치의 판정 재료 {고객 번호: {status · possibility_id · rules_not_run · bizmoney · yday_spend ·
        yday_imp · yday_clk}} — 관제 화면(S11)이 가망마다 판정(``verdict.judge``)을 만들 때 한 번에 읽는다(계정마다 따로 읽지
        않게). 숫자 칸은 관제 판 표 「어제 광고비」·「비즈머니」 · 광고주 한 장 타일(S13 · 판정에는 쓰지 않는다)."""
        out = {}
        for cid, st, pid, rnr, biz, spend, imp, clk in self._conn.execute(
                """SELECT customer_id, status, possibility_id, rules_not_run, bizmoney, yday_spend, yday_imp, yday_clk
                   FROM naver_auto_account_day WHERE day = ?""", (_day_text(day, "날짜"),)):
            try:
                missing = [tuple(x) for x in json.loads(rnr)]
            except (TypeError, ValueError, RecursionError):
                raise StoreError("저장된 계정 하루치를 읽지 못했습니다") from None
            out[int(cid)] = {"status": st, "possibility_id": None if pid is None else int(pid), "rules_not_run": missing,
                             "bizmoney": biz, "yday_spend": spend, "yday_imp": imp, "yday_clk": clk}
        return out

    def issues_closed_on(self, day: date) -> List[dict]:
        """그 날(KST) 닫힌 이슈 — ✅ 해결 · 🔁 저절로 풀림 · 짝이 사라져 닫힘(관제 판 「오늘 풀린 것」 · S13). 고친 시각은
        한국 시각 글자로 적지만 글자만 믿지 않고 시각으로 다시 대조한다(전날 글자로 넓게 고른 뒤 거른다)."""
        d = _day_text(day, "날짜")
        prev = _day_text(day - timedelta(days=1), "날짜")
        out = []
        for r in self._issue_rows(self._conn, "state IN ('resolved', 'auto_resolved', 'closed_unlinked') AND updated_at >= ?",
                                  (prev,)):
            t = _aware_time(r["updated_at"])
            if t is not None and t.astimezone(KST).date().isoformat() == d:
                out.append(self._issue_out(r))
        return out

    def my_running_runs(self) -> List[int]:
        """이 저장소가 시작했는데 아직 「돌고 있음」인 회차 — 아침 점검은 한 번에 하나만 도므로, 새 회차를 부를 때 이것이
        있으면 앞 회차가 죽으면서 닫지도 못한 것이다(닫기까지 실패 · 검토 readiness-stuck-running)."""
        running = set(self.running_runs())
        return sorted(r for r in self._my_runs if r in running)

    def run(self, run_id: int) -> Optional[dict]:
        cur = self._conn.execute("SELECT * FROM naver_auto_check_run WHERE run_id = ?", (_pos_int(run_id, "회차 번호"),))
        r = cur.fetchone()
        return None if r is None else dict(zip([d[0] for d in cur.description], r))

    # ── 알림 읽기(S10) ──
    @staticmethod
    def _alert_out(names, r) -> dict:
        d = dict(zip(names, r))
        try:
            if "codes" in d:
                d["codes"] = list(json.loads(d["codes"]))
            if "params" in d:
                d["params"] = json.loads(d["params"])
        except (TypeError, ValueError, RecursionError):
            raise StoreError("저장된 알림을 읽지 못했습니다") from None
        return d

    def alerts_on(self, day: date, kind: Optional[str] = None) -> List[dict]:
        """그 날(한국) 알림 원천 — 번호 순."""
        if kind is not None and kind not in ALERT_KINDS:
            raise StoreRefused("알림 종류가 아닙니다")
        sql, args = "SELECT * FROM naver_auto_alert WHERE day = ?", (_day_text(day, "알림 날짜"),)
        if kind is not None:
            sql, args = sql + " AND kind = ?", args + (kind,)
        cur = self._conn.execute(sql + " ORDER BY alert_id", args)
        names = [x[0] for x in cur.description]
        return [self._alert_out(names, r) for r in cur.fetchall()]

    def alert_recipients(self, alert_id: int) -> List[dict]:
        cur = self._conn.execute("SELECT * FROM naver_auto_alert_recipient WHERE alert_id = ? ORDER BY emp_idx",
                                 (_pos_int(alert_id, "알림 번호"),))
        names = [x[0] for x in cur.description]
        return [self._alert_out(names, r) for r in cur.fetchall()]

    def system_alert_keys_on(self, day: date) -> set:
        """그 날 이미 알린 시스템 경보 「나온 곳:코드」 — 같은 날 같은 코드를 되풀이하지 않게.

        받는 사람 줄이 **모두 기한 지남(12시간 동안 못 보냄)** 으로 끝난 경보는 알린 것으로 치지 않는다 — 같은 코드가
        다시 나면 새로 알린다(검토 trouble-heartbeat-masks). 다른 까닭으로 끝난 것(① 거절 400 · 하루 상한)은 다시 만들어도
        같은 까닭으로 막히므로 알린 것으로 친다(되풀이 기록을 막는다)."""
        out = set()
        for src, codes in self._conn.execute(
                """SELECT a.source, a.codes FROM naver_auto_alert a WHERE a.day = ? AND a.kind = 'system'
                   AND EXISTS (SELECT 1 FROM naver_auto_alert_recipient r WHERE r.alert_id = a.alert_id
                               AND NOT (r.status = 'failed' AND r.error_kind = 'expired'))""",
                (_day_text(day, "알림 날짜"),)):
            try:
                out |= {src + ":" + c for c in json.loads(codes)}
            except (TypeError, ValueError, RecursionError):
                raise StoreError("저장된 알림을 읽지 못했습니다") from None
        return out

    def due_deliveries(self, now: datetime, limit: int = 500, kind: Optional[str] = None) -> List[dict]:
        """보낼 때가 된 줄 — 긴급 먼저 · 번호 순. 원천(문구 틀 · 코드 · 경로 · 종류 · 날짜)을 함께 준다.
        ``kind`` 를 주면 그 종류만(시스템 경보를 요약보다 먼저 보내고 심박을 보내기 위해)."""
        t = _kst_text(now, "지금")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= 10_000:
            raise StoreRefused("몇 줄인지 1~10000 이어야 합니다")
        if kind is not None and kind not in ALERT_KINDS:
            raise StoreRefused("알림 종류가 아닙니다")
        cur = self._conn.execute(
            """SELECT r.recipient_id, r.alert_id, r.emp_idx, r.severity, r.params, r.dedupe_key, r.attempts,
                      r.expires_at, a.kind, a.day, a.source, a.template, a.codes, a.link_path
               FROM naver_auto_alert_recipient r JOIN naver_auto_alert a ON a.alert_id = r.alert_id
               WHERE r.status = 'pending' AND r.next_try_at <= ? AND (? IS NULL OR a.kind = ?)
               ORDER BY CASE r.severity WHEN 'URGENT' THEN 0 ELSE 1 END, r.recipient_id LIMIT ?""",
            (t, kind, kind, limit))
        names = [x[0] for x in cur.description]
        return [self._alert_out(names, r) for r in cur.fetchall()]

    def delivery_counts_on(self, day: date) -> dict:
        """그 날 알림의 받는 사람 줄 상태별 수 — {종류: {상태: 수}}."""
        out: dict = {}
        for kind, st, n in self._conn.execute(
                """SELECT a.kind, r.status, COUNT(*) FROM naver_auto_alert_recipient r
                   JOIN naver_auto_alert a ON a.alert_id = r.alert_id WHERE a.day = ? GROUP BY a.kind, r.status""",
                (_day_text(day, "알림 날짜"),)):
            out.setdefault(kind, {})[st] = n
        return out

    def issue_event_counts_on(self, day: date) -> dict:
        """그 날(한국) 이슈 기록 종류별 수 — 그림자 요약이 「새로 · 저절로 풀림」을 센다."""
        d = _day_text(day, "날짜")
        return {k: n for k, n in self._conn.execute(
            "SELECT kind, COUNT(*) FROM naver_auto_issue_event WHERE substr(at, 1, 10) = ? GROUP BY kind", (d,))}

    def heartbeat(self) -> Optional[dict]:
        """마지막 심박 기록 — {day(date) · status · tries · last_try_at · sent_at(없으면 None) · error_kind}."""
        v = self._meta_json(self._conn, "heartbeat")
        if v is None:
            return None
        try:
            out = dict(v)
            out["day"] = date.fromisoformat(v["day"])
            out["last_try_at"] = _aware_time(v["last_try_at"])
            out["sent_at"] = None if v["sent_at"] is None else _aware_time(v["sent_at"])
        except (TypeError, ValueError, KeyError):
            raise StoreError("저장된 심박 기록을 읽지 못했습니다") from None
        if out["last_try_at"] is None or (v["sent_at"] is not None and out["sent_at"] is None):
            raise StoreError("저장된 심박 기록을 읽지 못했습니다")
        return out

    # ── 계정우선 원천 수집: 전산 귀속·기존 점검 이력과 독립 ──
    def inventory_snapshot(self, now: datetime) -> Optional[datetime]:
        read_at, last = self.accounts_read_at(), self.last_sync(SYNC_ACCOUNTS)
        if read_at is None or last is None or last["outcome"] != SYNC_ACCEPTED \
                or not timedelta(0) <= now - read_at <= timedelta(hours=30):
            return None
        return read_at

    def inventory_account_valid(self, customer_id, snapshot_at, now):
        if self.inventory_snapshot(now) != snapshot_at:
            return False
        row = self._conn.execute("SELECT present FROM naver_auto_account WHERE customer_id = ?",
                                 (_customer_id(customer_id, "고객 번호"),)).fetchone()
        return row is not None and row[0] == 1

    def inventory_checks_on(self, day: date) -> dict:
        cur = self._conn.execute("""SELECT customer_id, status, checked_at, error_code, bizmoney,
            yday_spend, yday_imp, yday_clk FROM naver_auto_inventory_check WHERE day = ?""",
                                 (_day_text(day, "날짜"),))
        names = [d[0] for d in cur.description][1:]
        return {r[0]: dict(zip(names, r[1:])) for r in cur}

    def inventory_work(self, now: datetime, limit: int = 3) -> list:
        if type(limit) is not int or not 1 <= limit <= 24:
            raise StoreRefused("원천 수집 후보는 1~24개 계정입니다")
        if self.inventory_snapshot(now) is None:
            return []
        at = _kst_text(now, "지금")
        # 자격·이어읽기는 당일 기준, 순서만 마지막 시도 이력을 이어 간다.
        # 이력 없는 계정이 먼저, 이후 성공·부분·재시도 모두 오래 기다린 순서다.
        return [r[0] for r in self._conn.execute("""SELECT a.customer_id FROM naver_auto_account a
            LEFT JOIN naver_auto_inventory_check i ON i.customer_id = a.customer_id AND i.day = ?
            WHERE a.present = 1 AND (i.customer_id IS NULL OR
              (i.status NOT IN ('ok', 'reauth_required', 'limited') AND i.attempts < 4 AND i.next_try_at <= ?))
            ORDER BY (SELECT h.checked_at FROM naver_auto_inventory_check h
                WHERE h.customer_id = a.customer_id AND h.day <= ? ORDER BY h.day DESC LIMIT 1),
              a.customer_id LIMIT ?""", (at[:10], at, at[:10], limit))]

    def begin_inventory_check(self, customer_id, snapshot_at, now):
        self._need_writer()
        if not self.inventory_account_valid(customer_id, snapshot_at, now):
            raise StoreRefused("원천 수집의 계정 목록이 바뀌었습니다")
        at = _kst_text(now, "읽기 시작")
        with self._tx() as c:
            previous = c.execute("""SELECT status, attempts, next_try_at FROM naver_auto_inventory_check
                WHERE customer_id = ? AND day = ?""", (customer_id, at[:10])).fetchone()
            if previous is not None and (previous[0] in ("ok", "reauth_required", "limited") or previous[1] >= 4 or previous[2] > at):
                raise StoreRefused("계정 원천을 다시 읽을 때가 아닙니다")
            attempts = 0 if previous is None else previous[1]
            next_at = _kst_text(now + timedelta(minutes=2), "재시도 시각")
            c.execute("""INSERT INTO naver_auto_inventory_check
                (customer_id, day, snapshot_at, status, checked_at, attempts, next_try_at)
                VALUES (?, ?, ?, 'reading', ?, ?, ?)
                ON CONFLICT (customer_id, day) DO UPDATE SET status = 'reading', checked_at = excluded.checked_at,
                  attempts = excluded.attempts, next_try_at = excluded.next_try_at, snapshot_at = excluded.snapshot_at""",
                (customer_id, at[:10], _kst_text(snapshot_at, "목록 시각"), at, attempts, next_at))

    def inventory_progress(self, customer_id, day):
        from . import inventory_reads as IR
        row = self._conn.execute("""SELECT progress_json, progress_hash FROM naver_auto_inventory_check
            WHERE customer_id = ? AND day = ?""", (customer_id, _day_text(day, "날짜"))).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            if not isinstance(row[0], str) or hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                raise IR.CheckpointInvalid("원천 이어읽기 지문이 다릅니다")
            source = json.loads(row[0])
            IR.validate_progress(source, customer_id, day)
            return source
        except (ValueError, TypeError, RecursionError):
            raise IR.CheckpointInvalid("보관한 원천 이어읽기를 확인하지 못했습니다") from None

    def record_inventory_progress(self, customer_id, snapshot_at, now, source):
        from . import inventory_reads as IR
        self._need_writer()
        if not self.inventory_account_valid(customer_id, snapshot_at, now):
            raise StoreRefused("원천 수집의 계정 목록이 바뀌었습니다")
        at = _kst_text(now, "원천 배치 시각")
        IR.validate_progress(source, customer_id, now.astimezone(KST).date())
        raw = json.dumps(source, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._tx() as c:
            previous = self.inventory_progress(customer_id, now.astimezone(KST).date())
            progressed = previous is not None and previous["fingerprint"] == source["fingerprint"] \
                and (source["next_index"] > previous["next_index"]
                     or len(source.get("zero_ids", [])) > len(previous.get("zero_ids", [])))
            cur = c.execute("""UPDATE naver_auto_inventory_check SET progress_json = ?, progress_hash = ?,
                attempts = CASE WHEN ? THEN 0 ELSE attempts END
                WHERE customer_id = ? AND day = ? AND status = 'reading' AND snapshot_at = ?""",
                (raw, hashlib.sha256(raw.encode()).hexdigest(), progressed, customer_id, at[:10],
                 _kst_text(snapshot_at, "목록 시각")))
            if cur.rowcount != 1:
                raise StoreRefused("시작하지 않은 원천 이어읽기입니다")

    def record_inventory_check(self, customer_id, snapshot_at, now, values):
        from . import inventory_reads as IR
        self._need_writer()
        if not self.inventory_account_valid(customer_id, snapshot_at, now):
            raise StoreRefused("원천 수집의 계정 목록이 바뀌었습니다")
        at = _kst_text(now, "읽은 시각")
        self._not_future(now, "읽은 시각")
        values = dict(values)
        if values.get("status") not in {"partial", "ok", "retry", "reauth_required", "limited"}:
            raise StoreRefused("원천 수집 상태가 아닙니다")
        _num(values.get("bizmoney"), "잔액")
        if values["status"] != "ok":
            for key in ("yday_spend", "yday_imp", "yday_clk"):
                values[key] = None
        else:
            source = self.inventory_progress(customer_id, now.astimezone(KST).date())
            if source is None or source["next_index"] != len(source["campaign_ids"]):
                raise StoreRefused("완결된 원천이 아닙니다")
            totals = IR.validate_progress(source, customer_id, now.astimezone(KST).date())
            if any(values.get(target) != totals[name] for name, target in
                   zip(IR.FIELDS, ("yday_imp", "yday_clk", "yday_spend"))):
                raise StoreRefused("완결 원천과 공개 합계가 다릅니다")
        with self._tx() as c:
            current = c.execute("""SELECT attempts FROM naver_auto_inventory_check
                WHERE customer_id = ? AND day = ? AND status = 'reading'""", (customer_id, at[:10])).fetchone()
            if current is None:
                raise StoreRefused("시작하지 않은 원천 수집입니다")
            attempts = current[0] + (values["status"] == "retry")
            next_at = _kst_text(now + timedelta(minutes=(2, 5, 15, 30)[min(attempts, 4) - 1]), "재시도 시각") \
                if values["status"] == "retry" else at
            cur = c.execute("""UPDATE naver_auto_inventory_check SET
                status = CASE WHEN ? = 'retry' AND ? >= 4 THEN 'limited' ELSE ? END,
                checked_at = ?, error_code = CASE WHEN ? = 'retry' AND ? >= 4 THEN 'RETRY_EXHAUSTED' ELSE ? END,
                bizmoney = ?, yday_spend = ?, yday_imp = ?, yday_clk = ?, campaigns_json = ?,
                attempts = ?, next_try_at = ?
                WHERE customer_id = ? AND day = ? AND status = 'reading' AND snapshot_at = ?""",
                (values["status"], attempts, values["status"], at, values["status"], attempts, values.get("error_code"), values.get("bizmoney"), values.get("yday_spend"),
                 values.get("yday_imp"), values.get("yday_clk"),
                 json.dumps([F.keep(c, F.CAMPAIGN) for c in values.get("campaigns", [])]), attempts, next_at, customer_id, at[:10],
                 _kst_text(snapshot_at, "목록 시각")))
            if cur.rowcount != 1:
                raise StoreRefused("시작하지 않은 원천 수집입니다")
            return c.execute("SELECT status FROM naver_auto_inventory_check WHERE customer_id = ? AND day = ?",
                             (customer_id, at[:10])).fetchone()[0]

    # ── 월초~어제 원천: 당일 전일 수집이 끝난 계정만, 별도 외부 전송 없음 ──
    def monthly_checks_on(self, period_start: date, period_end: date) -> dict:
        start, end = _day_text(period_start, "월간 시작"), _day_text(period_end, "월간 끝")
        if start > end:
            return {}
        cur = self._conn.execute("""SELECT customer_id, period_start, period_end, snapshot_at, checked_at,
            status, error_code, imp, clk, spend, conversion_value, enabled_campaigns, campaign_count,
            campaign_fingerprint FROM naver_auto_monthly_check WHERE period_start = ? AND period_end = ?""", (start, end))
        names = [d[0] for d in cur.description]
        return {r[0]: dict(zip(names, r)) for r in cur}

    def monthly_work(self, now: datetime, limit: int = 24, *, exclude_checked_after=None) -> list:
        from . import monthly_reads as MR
        if type(limit) is not int or not 1 <= limit <= 24:
            raise StoreRefused("월간 후보는 1~24개 계정입니다")
        snapshot = self.inventory_snapshot(now)
        start, end = MR.window(now.astimezone(KST).date())
        if snapshot is None or start > end:
            return []
        at = _kst_text(now, "월간 현재 시각")
        cutoff = _kst_text(exclude_checked_after or now, "전일 시도 경계")
        # 같은 회차에 전일 읽기를 시도한 계정은 제외하여 계정별 8회/10초를 합산 초과하지 않는다.
        return [r[0] for r in self._conn.execute("""SELECT a.customer_id FROM naver_auto_account a
            JOIN naver_auto_inventory_check d ON d.customer_id = a.customer_id AND d.day = ?
            LEFT JOIN naver_auto_monthly_check m ON m.customer_id = a.customer_id
              AND m.period_start = ? AND m.period_end = ?
            WHERE a.present = 1 AND d.status = 'ok' AND d.checked_at < ? AND (m.customer_id IS NULL
              OR (m.status NOT IN ('ok', 'limited') AND m.attempts < 4 AND m.next_try_at <= ?))
            ORDER BY (SELECT h.checked_at FROM naver_auto_monthly_check h WHERE h.customer_id = a.customer_id
              ORDER BY h.period_end DESC LIMIT 1), a.customer_id LIMIT ?""",
            (at[:10], start.isoformat(), end.isoformat(), cutoff, at, limit))]

    def begin_monthly_check(self, customer_id, snapshot_at, now):
        from . import monthly_reads as MR
        self._need_writer()
        if not self.inventory_account_valid(customer_id, snapshot_at, now):
            raise StoreRefused("월간 계정 목록이 바뀌었습니다")
        start, end = MR.window(now.astimezone(KST).date())
        if start > end:
            raise StoreRefused("월간 기간에 완료된 날짜가 없습니다")
        at, snap = _kst_text(now, "월간 시작 시각"), _kst_text(snapshot_at, "월간 목록 시각")
        self._not_future(now, "월간 시작 시각")
        with self._tx() as c:
            previous = c.execute("""SELECT snapshot_at, status, attempts, next_try_at FROM naver_auto_monthly_check
                WHERE customer_id = ? AND period_start = ? AND period_end = ?""",
                (customer_id, start.isoformat(), end.isoformat())).fetchone()
            if previous is not None and (previous[1] in ("ok", "limited") or previous[2] >= 4 or previous[3] > at):
                raise StoreRefused("월간 원천을 다시 읽을 때가 아닙니다")
            attempts = previous[2] if previous is not None else 0
            c.execute("""INSERT INTO naver_auto_monthly_check
                (customer_id, period_start, period_end, snapshot_at, checked_at, status, attempts, next_try_at)
                VALUES (?, ?, ?, ?, ?, 'reading', ?, ?)
                ON CONFLICT (customer_id, period_start, period_end) DO UPDATE SET
                  snapshot_at = excluded.snapshot_at, checked_at = excluded.checked_at, status = 'reading',
                  imp = NULL, clk = NULL, spend = NULL, conversion_value = NULL, enabled_campaigns = NULL,
                  campaign_count = NULL, campaign_fingerprint = NULL, error_code = NULL,
                  attempts = excluded.attempts, next_try_at = excluded.next_try_at""",
                (customer_id, start.isoformat(), end.isoformat(), snap, at, attempts,
                 _kst_text(now + timedelta(minutes=2), "월간 재시도 시각")))

    def monthly_progress(self, customer_id, period_start, period_end):
        from . import monthly_reads as MR
        row = self._conn.execute("""SELECT progress_json, progress_hash FROM naver_auto_monthly_check
            WHERE customer_id = ? AND period_start = ? AND period_end = ?""",
            (_customer_id(customer_id, "고객 번호"), _day_text(period_start, "월간 시작"),
             _day_text(period_end, "월간 끝"))).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            if not isinstance(row[0], str) or hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                raise MR.CheckpointInvalid("월간 원천 지문이 다릅니다")
            source = json.loads(row[0])
            MR.validate_progress(source, customer_id, period_start, period_end)
            return source
        except (ValueError, TypeError, RecursionError):
            raise MR.CheckpointInvalid("보관한 월간 이어읽기를 확인하지 못했습니다") from None

    def record_monthly_progress(self, customer_id, snapshot_at, now, source):
        from . import monthly_reads as MR
        self._need_writer()
        if not self.inventory_account_valid(customer_id, snapshot_at, now):
            raise StoreRefused("월간 계정 목록이 바뀌었습니다")
        start, end = MR.window(now.astimezone(KST).date())
        MR.validate_progress(source, customer_id, start, end)
        if any(datetime.fromisoformat(cycle) > now + FUTURE_SLACK for cycle in source["cycles"]):
            raise MR.CheckpointInvalid("월간 원천 기준 시각이 미래입니다")
        raw = json.dumps(source, sort_keys=True, separators=(",", ":"), allow_nan=False)
        with self._tx() as c:
            previous = self.monthly_progress(customer_id, start, end)
            progressed = previous is not None and previous["fingerprint"] == source["fingerprint"] and (
                source["next_index"] > previous["next_index"] or len(source["zero_rows"]) > len(previous["zero_rows"]))
            cur = c.execute("""UPDATE naver_auto_monthly_check SET progress_json = ?, progress_hash = ?,
                attempts = CASE WHEN ? THEN 0 ELSE attempts END WHERE customer_id = ? AND period_start = ?
                AND period_end = ? AND status = 'reading' AND snapshot_at = ?""",
                (raw, hashlib.sha256(raw.encode()).hexdigest(), progressed, customer_id, start.isoformat(),
                 end.isoformat(), _kst_text(snapshot_at, "월간 목록 시각")))
            if cur.rowcount != 1:
                raise StoreRefused("시작하지 않은 월간 이어읽기입니다")

    def record_monthly_check(self, customer_id, snapshot_at, now, values):
        from . import monthly_reads as MR
        self._need_writer()
        if not self.inventory_account_valid(customer_id, snapshot_at, now):
            raise StoreRefused("월간 계정 목록이 바뀌었습니다")
        at, start_end = _kst_text(now, "월간 읽은 시각"), MR.window(now.astimezone(KST).date())
        self._not_future(now, "월간 읽은 시각")
        start, end = start_end
        values = dict(values)
        if values.get("status") not in {"partial", "ok", "retry", "limited"}:
            raise StoreRefused("월간 원천 수집 상태가 아닙니다")
        code = values.get("error_code")
        if code is not None:
            code = _code(code, _ERROR_KIND, "월간 수집 오류")
        if values["status"] == "ok":
            source = self.monthly_progress(customer_id, start, end)
            if source is None or source["next_index"] != len(source["campaign_ids"]):
                raise StoreRefused("완결된 월간 원천이 아닙니다")
            totals = MR.validate_progress(source, customer_id, start, end)
            if any(values.get(target) != totals[key] for key, target in zip(MR.FIELDS, MR.OUTPUTS)) \
                    or values.get("campaign_fingerprint") != source["fingerprint"]:
                raise StoreRefused("월간 원천과 공개 합계가 다릅니다")
            enabled, count = values.get("enabled_campaigns"), values.get("campaign_count")
            if not ((enabled is None and count is None) or
                    (type(enabled) is int and type(count) is int and 0 <= enabled <= count == len(source["campaign_ids"]))):
                raise StoreRefused("월간 캠페인 상태가 완결되지 않았습니다")
        else:
            for key in (*MR.OUTPUTS, "enabled_campaigns", "campaign_count", "campaign_fingerprint"):
                values[key] = None
        with self._tx() as c:
            row = c.execute("""SELECT attempts FROM naver_auto_monthly_check WHERE customer_id = ?
                AND period_start = ? AND period_end = ? AND status = 'reading' AND snapshot_at = ?""",
                (customer_id, start.isoformat(), end.isoformat(), _kst_text(snapshot_at, "월간 목록 시각"))).fetchone()
            if row is None:
                raise StoreRefused("시작하지 않은 월간 수집입니다")
            attempts = row[0] + (values["status"] == "retry")
            status = "limited" if attempts >= 4 and values["status"] == "retry" else values["status"]
            if status == "limited" and values["status"] == "retry":
                code = "RETRY_EXHAUSTED"
            next_at = now + timedelta(minutes=(2, 5, 15, 30)[min(attempts, 4) - 1]) if status == "retry" else now
            c.execute("""UPDATE naver_auto_monthly_check SET status = ?, checked_at = ?, error_code = ?,
                imp = ?, clk = ?, spend = ?, conversion_value = ?, enabled_campaigns = ?, campaign_count = ?,
                campaign_fingerprint = ?, attempts = ?, next_try_at = ? WHERE customer_id = ?
                AND period_start = ? AND period_end = ? AND status = 'reading'""",
                (status, at, code, *(values.get(key) for key in MR.OUTPUTS), values.get("enabled_campaigns"),
                 values.get("campaign_count"), values.get("campaign_fingerprint"), attempts,
                 _kst_text(next_at, "월간 재시도 시각"), customer_id, start.isoformat(), end.isoformat()))
            return status
