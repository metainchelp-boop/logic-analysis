"""아침 점검 — 오늘 받은 짝 맞추기의 짝마다 네이버를 읽고 판정·이슈를 적는다 (설계 v1.7 매일 아침 점검 · v1.8 S9 ·
반박 C1 · M2 · M4 · M5 · L2 · 대표 결정 Q4 · I1 ⓐ · I2 ⓐ).

순서(연결 목록 받기 → 짝 맞추기 → 점검)
- **준비 확인**(``readiness``) — 오늘 06:30 뒤 연결 목록 받기를 했고 · 오늘(KST) 받은 짝 맞추기가 있고 · 그 짝 맞추기의
  입력(연결 목록 읽은 시각 · 단계 받은 시각 · 사람 판단 지문)이 **지금 저장소와 같을 때만** 돈다(S8 약속 — 아님 판단을
  받은 자동 짝을 30분 동안 점검하지 않게). 다르면 기다린다(``links.pairing_due`` 가 다시 맞춘다). 연결 목록이 「못 씀」
  (``ACCOUNTS_UNUSABLE``)이면 그날 점검 전체가 멈춘다 → 대표 시스템 경보. 오늘 짝 맞추기가 없어도 경보.
- **이관 상태를 먼저 적는다**(네이버 호출 0) — 「이관 빠짐」 짝 = ⚪ ``link_broken`` + 🔴 긴급 이슈 「이관이 빠졌습니다」
  (대표 결정 I1 ⓐ · 다시 이관되면 다음 아침 🔁 저절로 풀림) · 「오늘 이관 목록에 없음」 짝 = ⚪ ``link_missing``
  (첫날 · 이슈 없음 · 확인 필요 아니오 — I2 ⓐ). 막힘 줄(``blocked``)은 계정 표에 이어 읽지 않는다(``ad-account-number``
  줄의 번호는 광고계정 번호다 — S8 약속).
- **짝이 사라진 열린 이슈는 「연결 해제로 닫힘」**(M5) — 하루 기다린 뒤 · 한꺼번에 많으면 경보.
- **점검할 짝(확인 · 자동)** — 전날 🔴 이 열린 계정 → 어제 점검이 안 된 계정 → 나머지(L2). 계정마다 손잡이를 발급한다
  (``handles.issue_check_handle`` — 14일 규칙 · 단계 72시간). 거절 사유가 우리 쪽 자료(단계 오래됨 · 시각 모름)면
  ⚪ ``system_gap`` + 대표 경보 한 번(Q4), 그 밖이면 ⚪ ``not_eligible``.
- **읽기** — 캠페인 목록 → 비즈머니 → 29일 합계(한 번 · 100개씩) → 하루별(활동이 있었거나 켜졌는데 합계 줄이 없는 캠페인만).
  - 멈춘 캠페인의 빠진 합계 줄 = 0(0단계 실측) · 켜진 캠페인의 빠진 줄은 하루별로 읽어 「모든 날 · 모든 칸 = 0」일 때만 0
    (``confirm_no_activity`` 와 같은 규칙).
  - 하루별 값이 빠지거나 비면 0 이 아니라 모름. 단 같은 기간 합계와 알던 값의 합이 **정확히 같으면** 빠진 값은 0 이다
    (값은 음수가 아니다 — 음수가 하나라도 있으면 이 맞춰 보기를 하지 않는다).
  - 자료 기준 시각(합계 · 하루별 중 가장 이른 것)으로 **다 들어온 날**을 정한다. 못 읽으면 다 들어온 날이 없다(자료 늦음).
  - 어제가 다 안 들어왔으면(자료 늦음) 7일 평균은 그 앞 7일(모두 다 들어온 날)로 계산한다 — 늦은 날도 ③ 비즈머니가 돈다.
    7일 중 하루라도 모르면 평균은 없다(0 이 아니다 — 반박 C1).
- **한 계정 안의 읽기는 모두 되거나 모두 안 된 것**(반박 C1) — 호출 사이마다 마감(08:00)을 보고, 넘으면 그 계정은 적지 않는다
  (⚪ 점검 안 됨 · 판정 함수가 날짜로 가른다). 적기는 한 거래(``record_account_check`` — 계정 하루치 · 어제 캠페인 줄 · 이슈).
- **키 거절이 몰리면 멈춘다**(M4) — 처음 10곳이 모두 거절 · 또는 50곳 넘게 시도해 80% 이상 거절이면 회차를 멈추고 경보.
  어제도 키 거절이던 계정(광고주별 권한 문제)은 이 표본에서 뺀다 — 어제 실패 계정을 먼저 읽는 순서(L2) 때문에 그 계정들이
  맨 앞에 서서 「전 계정 거절」로 매일 회차가 멈추지 않게(검토 readiness-key-order).
- **네이버 서버·네트워크 오류가 몰려도 멈춘다** — 같은 기준(처음 10곳 모두 · 50곳 넘게 80%)으로 ``NAVER_UNAVAILABLE`` ·
  경보. 멈춘 회차 뒤 20분에 다시 도는 회차가 「일부만」 계정을 다시 읽는다(검토 readiness-server-outage).
- 네이버 속도 제한에 두 번 멈춤 · 호출 상한 = 회차 실패(``RUN_ABORT``) · 경보.
- **같은 날 다시 돌기** — 실패한 회차 뒤 · 또는 끝난(done) 회차여도 **아직 끝나지 않은 짝**이 남았으면 20분 뒤 · 하루 3번까지.
  「끝남」 = 오늘 계정 하루치가 **같은 가망**으로 적혔고 「일부만」·「자료 늦음」이 아님(키 거절로 멈춘 회차가 있었으면
  「키 거절」도 다시 본다 — 그 거절은 계정 탓이 아니었다). 자료 늦음 계정이 있으면 경보(``DATA_LATE`` — 판정은 확인 필요
  아니오라 따로 알린다 · 검토 failclosed-data-late).
- **준비가 늦으면 알린다** — 마감 30분 전(07:30)까지 준비가 안 되면 ``NOT_READY_LATE``(경보 · 짝 맞추기 낡음처럼 경보 없이
  막히는 날에도 아무도 모르는 날이 없게 · 검토 readiness-pairing-stale). 스케줄러는 06:30~08:00 동안 ``readiness`` 를 보고
  ``ALERTING`` 코드가 있으면 알린다.
- **계정 한 곳의 뜻밖의 오류는 그 계정만** 적지 않고(⚪ 점검 안 됨) 경보(``ACCOUNT_ERROR``) — 회차 전체가 죽지 않게(검토
  failclosed-stale-cycle). 이 저장소가 시작한 채 닫히지 못한 회차는 새 회차를 부를 때 실패로 닫는다(``RUN_ORPHANED``).

공통
- 결과는 예외가 아니라 ``MorningOutcome`` 으로 돌려준다(스케줄러가 멈추지 않게) · 코드와 개수만(번호·이름·금액 없음).
  저장소 자체 오류(``StoreError``)는 회차를 실패로 닫고 그대로 던진다.
- 회차마다 새 ``NaverReader``(호출 상한이 객체 평생 누적). 시계는 부르는 쪽이 넣는다(읽기 관문과 같은 시계).
- ``alert`` = 대표에게 알릴 것(S10 · 그림자 기간에도 — Q4).
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from app.naver_auto import checks as C
from app.naver_auto import issues as I
from app.naver_auto import verdict as V
from app.naver_auto.thresholds import DEFAULTS, Thresholds

from . import handles as H
from . import links as L
from . import naver_read as N
from . import store as S
from . import sync as Y

CHECK_START = time(6, 30)            # 설계 §매일 아침 점검 — 06:30 시작
CHECK_DEADLINE = time(8, 0)          # 08:00 전 끝(② 08:00·08:30 작업과 같은 서버·같은 주소 — 겹치지 않게)
RETRY_AFTER = timedelta(minutes=20)  # 실패한 회차 뒤 다시 돌기까지(마감 전만)
MAX_RUNS_PER_DAY = 3
WINDOW_DAYS = 29                     # 어제부터 29일 — 같은 요일 4주 전(어제 − 28일)까지
AVG_DAYS = 7
STAT_FIELDS = ("impCnt", "clkCnt", "salesAmt", "ccnt")   # 0단계에서 합계·하루별 응답을 확인한 네 칸(구매 칸은 확인 뒤)
KEY_ALL_MIN = 10                     # 처음 이만큼 모두 키 거절이면 멈춤(M4 「전 계정 거절은 즉시」)
KEY_RATIO_MIN = 50                   # 이만큼 시도한 뒤에만 비율로 판정(M4)
KEY_RATIO = 0.8
UNAVAILABLE_KINDS = frozenset({N.KIND_SERVER, N.KIND_NETWORK})   # 네이버 서버·네트워크 오류(계정 탓 아님)
NOT_READY_ALERT_BEFORE = timedelta(minutes=30)                    # 마감 30분 전까지 준비 안 되면 경보

# 손잡이 거절 사유 중 우리 쪽 자료 문제(직원이 할 일 없음 → ⚪ system_gap · 대표 경보 한 번)
SYSTEM_GAP_REASONS = frozenset({"stage-stale", "stage-time-unknown", "stage-time-in-future"})
RETRY_STATUSES = frozenset({V.CHECK_PARTIAL, V.CHECK_DATA_LATE})   # 같은 날 다시 도는 회차가 다시 볼 계정(없음 포함)
REASON_LINK_BROKEN = "link-broken"
REASON_LINK_MISSING = "link-missing"
FACT_NEVER_LISTED = "never-listed"

OUT_DONE, OUT_FAILED, OUT_REFUSED = "done", "failed", "refused"

CODE_TOO_EARLY = "TOO_EARLY"
CODE_AFTER_DEADLINE = "AFTER_DEADLINE"
CODE_ACCOUNTS_STEP_PENDING = "ACCOUNTS_STEP_PENDING"   # 오늘 06:30 뒤 연결 목록 받기를 아직 안 함(순서를 지킨다)
CODE_ACCOUNTS_OLD = "ACCOUNTS_OLD"                     # 경고: 오늘 연결 목록을 못 받아 어제 목록으로 맞춘 짝으로 돈다
CODE_ACCOUNTS_UNUSABLE = L.CODE_ACCOUNTS_UNUSABLE
CODE_PAIRING_NOT_TODAY = "PAIRING_NOT_TODAY"           # 오늘 받은 짝 맞추기가 없음 — 경보
CODE_PAIRING_STALE = "PAIRING_STALE"                   # 짝 맞추기 입력이 지금과 다름 — 다시 맞출 때까지 기다림
CODE_DONE_TODAY = "DONE_TODAY"
CODE_RUN_RUNNING = "RUN_RUNNING"
CODE_RUNS_EXHAUSTED = "RUNS_EXHAUSTED"
CODE_RUN_ABORT = L.CODE_RUN_ABORT
CODE_KEY_REJECTED_ALL = "KEY_REJECTED_ALL"
CODE_KEY_REJECTED_MANY = "KEY_REJECTED_MANY"
CODE_DEADLINE_CUT = "DEADLINE_CUT"                     # 08:00 까지 못 끝낸 계정이 있음 — ⚪ 점검 안 됨 · 경보
CODE_SYSTEM_GAP = "SYSTEM_GAP"                         # 우리 쪽 자료 문제 계정 — 대표 경보 한 번(Q4)
CODE_SHAPE_UNKNOWN = "NAVER_SHAPE_UNKNOWN"             # 모르는 응답 모양 — 경보(Q4)
CODE_PAIR_DUPLICATE = "PAIR_DUPLICATE"                 # 한 계정이 두 짝에 — 그 계정은 오늘 점검하지 않음 · 경보
CODE_UNLINK_MASS = "UNLINK_MASS"                       # 짝이 사라져 이슈를 한꺼번에 많이 닫음 — 경보
CODE_STORE_REFUSED = "STORE_REFUSED"                   # 저장소가 계정 결과를 받지 않음 — 그 계정은 점검 안 됨 · 경보
CODE_HANDLE_INVALID = L.CODE_HANDLE_INVALID
CODE_DATA_LATE = "DATA_LATE"                           # 자료 늦음 계정이 있음 — ④⑤⑥ 을 못 돌림 · 경보(판정은 확인 필요 아니오)
CODE_NAVER_UNAVAILABLE = "NAVER_UNAVAILABLE"           # 네이버 서버·네트워크 오류가 몰림 — 회차 멈춤 · 경보
CODE_NOT_READY_LATE = "NOT_READY_LATE"                 # 마감 30분 전까지 준비 안 됨 — 경보
CODE_RUN_ORPHANED = "RUN_ORPHANED"                     # 이 저장소가 시작한 회차가 닫히지 못한 채 남음 — 실패로 닫음 · 경보
CODE_ACCOUNT_ERROR = "ACCOUNT_ERROR"                   # 계정 한 곳의 뜻밖의 오류 — 그 계정만 점검 안 됨 · 경보
CODE_UNEXPECTED = "unexpected"

BLOCKING = frozenset({CODE_ACCOUNTS_STEP_PENDING, CODE_ACCOUNTS_UNUSABLE, CODE_PAIRING_NOT_TODAY, CODE_PAIRING_STALE})
ALERTING = frozenset({CODE_ACCOUNTS_UNUSABLE, CODE_PAIRING_NOT_TODAY, CODE_RUNS_EXHAUSTED, CODE_RUN_ABORT,
                      CODE_KEY_REJECTED_ALL, CODE_KEY_REJECTED_MANY, CODE_DEADLINE_CUT, CODE_SYSTEM_GAP,
                      CODE_SHAPE_UNKNOWN, CODE_PAIR_DUPLICATE, CODE_UNLINK_MASS, CODE_STORE_REFUSED,
                      CODE_HANDLE_INVALID, CODE_UNEXPECTED, CODE_DATA_LATE, CODE_NAVER_UNAVAILABLE,
                      CODE_NOT_READY_LATE, CODE_RUN_ORPHANED, CODE_ACCOUNT_ERROR})


@dataclass(frozen=True)
class MorningOutcome:
    outcome: str                              # done · failed · refused
    codes: Tuple[str, ...] = ()
    run_id: Optional[int] = None
    counts: Dict[str, int] = field(default_factory=dict, compare=False)          # 계정 상태별 · 대상 · 남김 등
    issue_counts: Dict[str, int] = field(default_factory=dict, compare=False)    # 이슈 기록 종류별
    alert: bool = False

    def __repr__(self) -> str:   # 코드·개수만
        return (f"MorningOutcome(outcome={self.outcome}, codes={list(self.codes)}, run_id={self.run_id}, "
                f"counts={dict(sorted(self.counts.items()))}, issues={dict(sorted(self.issue_counts.items()))}, "
                f"alert={self.alert})")


class _PastDeadline(Exception):
    """이 계정의 읽기가 마감을 넘었다 — 적지 않는다."""


class _KeyAbort(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# ── 시각 ─────────────────────────────────────────────────────────────
def _need_time(now) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("시각은 시간대가 있어야 합니다")
    return now


def _day_bounds(now: datetime) -> Tuple[date, datetime, datetime]:
    local = now.astimezone(S.KST)
    today = local.date()
    return (today, datetime.combine(today, CHECK_START, tzinfo=S.KST),
            datetime.combine(today, CHECK_DEADLINE, tzinfo=S.KST))


def window(today: date) -> Tuple[date, date, Tuple[date, ...]]:
    """점검이 읽는 기간 — (시작, 끝 = 어제, 날짜들(오래된 날 먼저))."""
    until = today - timedelta(days=1)
    since = until - timedelta(days=WINDOW_DAYS - 1)
    return since, until, tuple(since + timedelta(days=i) for i in range(WINDOW_DAYS))


def complete_through(cycles: Sequence[Optional[datetime]]) -> Optional[date]:
    """자료가 **다 들어온** 마지막 날 — 기준 시각(가장 이른 것)이 그다음 날 0시(KST) 이후인 날. 하나라도 못 읽으면 None."""
    if not cycles or any(c is None for c in cycles):
        return None
    return min(cycles).astimezone(S.KST).date() - timedelta(days=1)


# ── 준비 확인 ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Readiness:
    codes: Tuple[str, ...]
    pairing_id: Optional[int] = None

    @property
    def ready(self) -> bool:
        return not (set(self.codes) & BLOCKING)


def readiness(store: S.Store, now: datetime) -> Readiness:
    """점검을 돌려도 되는가 — 코드만(경보 여부는 부르는 쪽이 ``ALERTING`` 으로 본다)."""
    _need_time(now)
    today, start, deadline = _day_bounds(now)
    codes: List[str] = []
    last = store.last_sync(S.SYNC_ACCOUNTS)
    last_at = None if last is None else Y._aware(last["at"])
    if last_at is None or last_at < start or last_at > now + Y.CLOCK_SKEW:
        codes.append(CODE_ACCOUNTS_STEP_PENDING)
    read_at, stage_at = store.accounts_read_at(), store.stage_as_of()
    if read_at is not None and read_at < start:
        codes.append(CODE_ACCOUNTS_OLD)
    if L._accounts_unusable(store):
        codes.append(CODE_ACCOUNTS_UNUSABLE)
    ok = store.last_pairing(S.SYNC_ACCEPTED)
    pid = None
    if ok is None or ok["at"].astimezone(S.KST).date() != today or ok["at"] > now + Y.CLOCK_SKEW:
        codes.append(CODE_PAIRING_NOT_TODAY)
    elif (ok["accounts_read_at"] != read_at or ok["stages_as_of"] != stage_at
          or ok["decisions_hash"] != store.decision_fingerprint()):
        codes.append(CODE_PAIRING_STALE)
    else:
        pid = ok["pairing_id"]
    if set(codes) & BLOCKING and now >= deadline - NOT_READY_ALERT_BEFORE:
        codes.append(CODE_NOT_READY_LATE)   # 경보 없이 막히는 코드(단계 대기 · 짝 맞추기 낡음)로 그날을 넘기지 않게
    return Readiness(tuple(codes), pid)


def _runs_today(store: S.Store, today: date) -> List[dict]:
    return store.runs_on(today)


def _redo_statuses(runs: List[dict]) -> frozenset:
    """같은 날 다시 볼 계정 상태 — 일부만 · 자료 늦음. 키 거절로 멈춘 회차가 있었으면 키 거절도(그 거절은 계정 탓이 아니었다)."""
    key_abort = any(r["status"] == S.RUN_FAILED and r.get("error_kind") in (CODE_KEY_REJECTED_ALL, CODE_KEY_REJECTED_MANY)
                    for r in runs)
    return RETRY_STATUSES | ({V.CHECK_KEY_REJECTED} if key_abort else frozenset())


def _pair_rows(store: S.Store, pairing_id: int) -> Tuple[List[dict], set, Counter]:
    """오늘 짝 맞추기의 이관 상태 줄(점검할 짝 · 오늘 없음 · 이관 빠짐) — 두 짝에 나온 계정은 뺀다."""
    rows = store.pairing_rows(pairing_id)
    relevant = [r for r in rows if r["state"] in S.PAIR_CHECKABLE | {S.PAIR_MISSING, S.PAIR_BROKEN}]
    per_cid = Counter(r["customer_id"] for r in relevant)
    dups = {cid for cid, n in per_cid.items() if n > 1}
    return [r for r in relevant if r["customer_id"] not in dups], dups, per_cid


def _still_to_do(relevant: List[dict], marks: Mapping[int, tuple], redo: frozenset) -> List[dict]:
    """점검할 짝 중 오늘 아직 끝나지 않은 것 — 오늘 계정 하루치가 없거나 · **다른 가망**으로 적혔거나 · 다시 볼 상태."""
    out = []
    for r in relevant:
        if r["state"] not in S.PAIR_CHECKABLE:
            continue
        m = marks.get(r["customer_id"])
        if m is None or m[1] != r["possibility_id"] or m[0] in redo:
            out.append(r)
    return out


def _unfinished(store: S.Store, pairing_id: int, today: date, runs: List[dict]) -> List[dict]:
    relevant, _d, _c = _pair_rows(store, pairing_id)
    return _still_to_do(relevant, store.account_day_marks_on(today), _redo_statuses(runs))


def morning_due(store: S.Store, now: datetime) -> bool:
    """점검을 부를 때인가 — 06:30~08:00 · 준비됨 · 도는 회차 없음 · 앞 회차 뒤 20분 · 하루 3번까지 · 오늘 끝난 회차가
    있으면 아직 끝나지 않은 짝이 남았을 때만(자료 늦음·일부만·가망이 바뀐 짝 · 검토 failclosed-data-late · retry)."""
    _need_time(now)
    today, start, deadline = _day_bounds(now)
    if not start <= now < deadline:
        return False
    ready = readiness(store, now)
    if not ready.ready:
        return False
    runs = _runs_today(store, today)
    stale = set(store.my_running_runs())   # 이 저장소가 시작한 채 닫히지 못한 회차 — 부르면 닫고 돈다
    if any(r["status"] == S.RUN_RUNNING and r["run_id"] not in stale for r in runs) or len(runs) >= MAX_RUNS_PER_DAY:
        return False
    ends = [Y._aware(r["finished_at"]) for r in runs if r["finished_at"]]
    if any(e is not None and now - e < RETRY_AFTER for e in ends):
        return False
    if any(r["status"] == S.RUN_DONE for r in runs):
        return bool(_unfinished(store, ready.pairing_id, today, runs))
    return True


# ── 네이버 응답 → 점검 입력 ──────────────────────────────────────────
def _campaign_infos(raw: Sequence[Mapping], cid: int) -> Optional[Tuple[C.CampaignInfo, ...]]:
    """캠페인 목록 → 점검 입력. 모양을 모르면 None(모르는 모양을 켜짐·꺼짐으로 짐작하지 않는다)."""
    out, seen = [], set()
    for c in raw:
        ccid = c.get("nccCampaignId")
        if not isinstance(ccid, str) or not N._CAMPAIGN_ID.fullmatch(ccid) or ccid in seen or c.get("customerId") != cid:
            return None
        seen.add(ccid)
        tp, status, lock = c.get("campaignTp"), c.get("status"), c.get("userLock")
        # 켜짐·꺼짐의 핵심(userLock)은 참·거짓이어야 한다 · 곁 표지 셋은 없거나 비었으면 「아님」(0단계 실측: 대부분 옴)
        flags = [False if c.get(k) is None else c.get(k) for k in ("delFlag", "usePeriod", "sharedBudgetLock")]
        if not isinstance(tp, str) or not isinstance(status, str) or type(lock) is not bool \
                or any(type(x) is not bool for x in flags):
            return None
        end = c.get("periodEndDt")
        reason = c.get("statusReason")
        if reason is not None and not isinstance(reason, str):
            return None
        out.append(C.CampaignInfo(ccid, tp, status, lock, flags[0], flags[1],
                                  end if isinstance(end, str) else None, flags[2], status_reason=reason))
    return tuple(out)


def _running(c: C.CampaignInfo) -> bool:
    return c.status == C.ACTIVE_STATUS and not c.user_lock and not c.del_flag


def _known(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def reconcile(days: Mapping[str, Mapping[str, Optional[float]]], total: Optional[Mapping[str, Optional[float]]],
              want: Sequence[date]) -> Dict[date, Dict[str, Optional[float]]]:
    """하루별 값 → 날짜마다 네 칸. 빠진 날·빈 값은 모름(None). 같은 기간 합계(``total``)와 알던 값의 합이 정확히 같고
    모든 값이 음수가 아니면 그 칸의 모르는 값은 0 이다(합계 줄이 없는 캠페인은 합계를 모르는 것 — 맞춰 보지 않는다)."""
    out = {d: {f: None for f in STAT_FIELDS} for d in want}
    for d in want:
        row = days.get(d.isoformat())
        if row is not None:
            for f in STAT_FIELDS:
                v = row.get(f)
                out[d][f] = v if _known(v) else None
    if total is None:
        return out
    for f in STAT_FIELDS:
        t = total.get(f)
        vals = [out[d][f] for d in want]
        if not _known(t) or t < 0 or any(v is not None and v < 0 for v in vals) or None not in vals:
            continue
        s = sum(v for v in vals if v is not None)
        if math.isclose(s, t, rel_tol=1e-9, abs_tol=1e-6):
            for d in want:
                if out[d][f] is None:
                    out[d][f] = 0
    return out


@dataclass
class _Reads:
    campaigns_raw: Optional[List[dict]] = None
    campaigns: Optional[Tuple[C.CampaignInfo, ...]] = None
    campaigns_error: Optional[str] = None
    bizmoney: Optional[dict] = None
    bizmoney_error: Optional[str] = None
    series: Optional[Dict[str, Dict[date, Dict[str, Optional[float]]]]] = None   # 캠페인 → 날짜 → 칸
    through: Optional[date] = None             # 자료가 다 들어온 마지막 날
    stats_error: Optional[str] = None
    shape_unknown: bool = False


def _gate(clock: Callable[[], datetime], deadline: datetime) -> None:
    if _need_time(clock()) >= deadline:
        raise _PastDeadline()


def _naver_kind(e: N.NaverApiError) -> str:
    return e.kind


def read_account(reader: N.NaverReader, ah, cid: int, today: date, clock: Callable[[], datetime],
                 deadline: datetime) -> _Reads:
    """계정 한 곳을 읽는다 — 호출마다 마감을 본다(넘으면 ``_PastDeadline`` — 이 계정은 적지 않는다)."""
    r = _Reads()
    _gate(clock, deadline)
    try:
        raw = reader.get_campaigns(ah)
    except N.NaverApiError as e:
        r.campaigns_error = _naver_kind(e)
        r.shape_unknown = e.kind in (N.KIND_BAD_RESPONSE, N.KIND_MISMATCH)
        return r
    infos = _campaign_infos(raw, cid)
    if infos is None:
        r.campaigns_error, r.shape_unknown = N.KIND_BAD_RESPONSE, True
        return r
    r.campaigns_raw, r.campaigns = raw, infos
    _gate(clock, deadline)
    try:
        r.bizmoney = reader.get_bizmoney(ah)
    except N.NaverApiError as e:
        r.bizmoney_error = _naver_kind(e)
        r.shape_unknown = r.shape_unknown or e.kind in (N.KIND_BAD_RESPONSE, N.KIND_MISMATCH)
    since, until, want = window(today)
    series: Dict[str, Dict[date, Dict[str, Optional[float]]]] = {}
    if not infos:
        r.series, r.through = series, until      # 캠페인이 없으면 쓴 돈도 없다(읽을 통계 없음 — 늦을 것도 없다)
        return r
    zero = {d: {f: 0 for f in STAT_FIELDS} for d in want}
    try:
        _gate(clock, deadline)
        summ = reader.get_stats_summary(ah, [c.campaign_id for c in infos], since, until, fields=STAT_FIELDS)
        cycles = [summ.cycle_base_tm]
        for c in infos:
            row = summ.rows.get(c.campaign_id)
            if row is None and not _running(c):
                series[c.campaign_id] = {d: dict(v) for d, v in zero.items()}   # 멈춘 캠페인의 빠진 합계 줄 = 0(실측)
                continue
            if row is not None and all(_known(row.get(f)) and row.get(f) == 0 for f in STAT_FIELDS):
                series[c.campaign_id] = {d: dict(v) for d, v in zero.items()}   # 기간 합계가 정확히 0 — 날마다 0
                continue
            _gate(clock, deadline)
            daily = reader.get_stats_daily(ah, c.campaign_id, since, until, fields=STAT_FIELDS)
            cycles.append(daily.cycle_base_tm)
            series[c.campaign_id] = reconcile(daily.days, row, want)
    except N.NaverApiError as e:
        r.stats_error = _naver_kind(e)
        r.shape_unknown = r.shape_unknown or e.kind in (N.KIND_BAD_RESPONSE, N.KIND_MISMATCH)
        return r
    except N.StatsShapeUnknown:
        r.stats_error, r.shape_unknown = "STATS_SHAPE", True
        return r
    r.series, r.through = series, complete_through(cycles)
    return r


def _total(series, day: date, f: str, through: Optional[date]) -> Optional[float]:
    """그날 계정 합계 — 다 들어온 날이 아니거나 한 캠페인이라도 모르면 None."""
    if through is None or day > through:
        return None
    vals = [per[day][f] if day in per else None for per in series.values()]   # 읽은 기간 밖 날짜는 모름(검토 stale-cycle)
    if any(v is None for v in vals):
        return None
    return float(sum(vals))


def account_input(cid: int, r: _Reads, today: date, th: Thresholds) -> Tuple[C.AccountInput, Dict[str, object]]:
    """읽은 것 → 점검 입력(``checks.AccountInput``) + 계정 하루치 칸. 모르는 값은 None(0 으로 채우지 않는다)."""
    if r.campaigns is None:
        return C.AccountInput(cid, campaigns=None, campaigns_error=r.campaigns_error), {}
    biz = r.bizmoney or {}
    day_fields: Dict[str, object] = {
        "bizmoney": biz.get("bizmoney"), "budget_lock": biz.get("budgetLock"), "refund_lock": biz.get("refundLock")}
    if r.series is None:
        infos = r.campaigns
        return C.AccountInput(cid, campaigns=infos, bizmoney=biz.get("bizmoney"), budget_lock=biz.get("budgetLock"),
                              refund_lock=biz.get("refundLock"), bizmoney_error=r.bizmoney_error,
                              stats_error=r.stats_error or "stats-unread"), day_fields
    _since, yday, _want = window(today)
    through, series = r.through, r.series
    late = through is None or through < yday

    def total(d: date, f: str = "salesAmt") -> Optional[float]:
        return _total(series, d, f, through)

    def camp(ccid: str, d: date, f: str) -> Optional[float]:
        if through is None or d > through or d not in series[ccid]:
            return None
        return series[ccid][d][f]

    infos = []
    week = [yday - timedelta(days=i) for i in range(AVG_DAYS)]
    for c in r.campaigns:
        w = [camp(c.campaign_id, d, "impCnt") for d in week]
        infos.append(C.CampaignInfo(c.campaign_id, c.tp, c.status, c.user_lock, c.del_flag, c.use_period,
                                    c.period_end, c.shared_budget_lock, camp(c.campaign_id, yday, "impCnt"),
                                    None if any(v is None for v in w) else int(sum(w)), status_reason=c.status_reason))
    last = yday if not late else (None if through is None else min(through, yday - timedelta(days=1)))
    avg = None
    if last is not None:
        spend = [total(last - timedelta(days=i)) for i in range(AVG_DAYS)]
        avg = None if any(v is None for v in spend) else sum(spend) / AVG_DAYS
    recent = tuple(total(yday - timedelta(days=i)) for i in reversed(range(th.zero_spend_days)))
    same = tuple(total(yday - timedelta(days=7 * k)) for k in range(1, 5))
    acc = C.AccountInput(cid, campaigns=tuple(infos), bizmoney=biz.get("bizmoney"), budget_lock=biz.get("budgetLock"),
                         refund_lock=biz.get("refundLock"), bizmoney_error=r.bizmoney_error, avg_daily_spend=avg,
                         yday_spend=total(yday), recent_spend=recent, same_weekday_spend=same, data_late=late)
    day_fields.update(yday_spend=total(yday), yday_imp=total(yday, "impCnt"), yday_clk=total(yday, "clkCnt"),
                      data_late=late)
    return acc, day_fields


def yesterday_stats(r: _Reads, today: date) -> Dict[str, Dict[str, Optional[float]]]:
    """어제 캠페인 줄(다 들어왔을 때만 · 모르는 칸은 None) — 저장소 캠페인 하루치에 넘긴다."""
    _s, yday, _w = window(today)
    if r.series is None or r.through is None or r.through < yday:
        return {}
    return {ccid: dict(per[yday]) for ccid, per in r.series.items()}


@dataclass(frozen=True)
class _LinkFinding:
    rule: str
    code: str
    target: str
    level: str
    facts: tuple = ()


def _enabled(switches: Optional[Mapping[str, bool]]) -> Tuple[str, ...]:
    sw = dict(C.DEFAULT_SWITCHES)
    sw.update(switches or {})
    return tuple(r for r in C.ALL_RULES if sw.get(r))


# ── 회차 ─────────────────────────────────────────────────────────────
def _order(rows: List[dict], store: S.Store, today: date) -> List[dict]:
    """전날 🔴 이 열린 계정 → 어제 온전히 점검되지 않은 계정(어제 줄 없음 포함 — 마감·멈춤에 잘린 계정이 매일 같은 꼬리로
    잘리지 않게 · 검토 readiness-deadline-starvation) → 나머지(L2)."""
    red = {(i["possibility_id"], i["customer_id"]) for i in store.issues(open_only=True) if i["severity"] == "red"}
    yday = store.account_days_on(today - timedelta(days=1))

    def key(r):
        pk = (r["possibility_id"], r["customer_id"])
        rank = 0 if pk in red else 2 if yday.get(r["customer_id"]) == V.CHECK_OK else 1
        return rank, r["possibility_id"], r["customer_id"]
    return sorted(rows, key=key)


def _refused(codes, alert_extra: bool = False) -> MorningOutcome:
    cs = tuple(dict.fromkeys(codes))
    return MorningOutcome(OUT_REFUSED, cs, alert=alert_extra or bool(set(cs) & ALERTING))


def run_morning(reader: N.NaverReader, store: S.Store, clock: Callable[[], datetime], *,
                th: Thresholds = DEFAULTS, switches: Optional[Mapping[str, bool]] = None) -> MorningOutcome:
    """아침 점검 한 회차 — 결과는 ``MorningOutcome`` (저장소 자체 오류만 던진다)."""
    now = _need_time(clock())
    L._need_fresh_naver(reader)
    enabled = _enabled(switches)
    today, start, deadline = _day_bounds(now)
    if now < start:
        return _refused((CODE_TOO_EARLY,))
    if now >= deadline:
        return _refused((CODE_AFTER_DEADLINE,))
    return _run(reader, store, clock, now, today, deadline, th, switches, enabled)


def run_requested(reader: N.NaverReader, store: S.Store, clock: Callable[[], datetime], *,
                  max_seconds: int = 600, deadline: Optional[datetime] = None,
                  th: Thresholds = DEFAULTS, switches: Optional[Mapping[str, bool]] = None) -> MorningOutcome:
    """승인된 단발 당일 읽기. 예약 창만 달리하며 준비·재시도·하루 상한·대상 규칙은 보존한다.

    승인/단회 실행은 runtime bootstrap 경계에서 검증한다. 가짜 아침 시각을 만들지 않는다.
    전송의 남은 시간 제한은 부르는 쪽의 bounded clock/transport도 함께 적용해야 한다.
    """
    now = _need_time(clock())
    L._need_fresh_naver(reader)
    if type(max_seconds) is not int or not 1 <= max_seconds <= 600:
        raise ValueError("요청 시간은 1~600초여야 합니다")
    today = now.astimezone(S.KST).date()
    end_of_day = datetime.combine(today + timedelta(days=1), time.min, tzinfo=S.KST)
    limit = min(now + timedelta(seconds=max_seconds), end_of_day)
    if deadline is not None:
        deadline = _need_time(deadline)
        if deadline > limit:
            raise ValueError("요청 마감은 당일 제한 시간을 넘을 수 없습니다")
        limit = deadline
    if now >= limit:
        return _refused((CODE_AFTER_DEADLINE,))
    runs = _runs_today(store, today)
    ends = [Y._aware(r["finished_at"]) for r in runs if r["finished_at"]]
    if any(end is not None and now - end < RETRY_AFTER for end in ends):
        return _refused(("RETRY_NOT_DUE",))
    return _run(reader, store, clock, now, today, limit, th, switches, _enabled(switches))


def _run(reader, store, clock, now, today, deadline, th, switches, enabled):
    pre: List[str] = []
    for rid in store.my_running_runs():   # 앞 회차가 죽으면서 닫지도 못함 — 한 번에 하나만 돌므로 지금 닫는다
        store.finish_run(rid, S.RUN_FAILED, now, error_kind=CODE_RUN_ORPHANED)
        pre.append(CODE_RUN_ORPHANED)
    ready = readiness(store, now)
    if not ready.ready:
        return _refused(pre + list(ready.codes))
    runs = _runs_today(store, today)
    if any(r["status"] == S.RUN_RUNNING for r in runs):
        return _refused(pre + [CODE_RUN_RUNNING])
    if any(r["status"] == S.RUN_DONE for r in runs) and not _unfinished(store, ready.pairing_id, today, runs):
        return _refused(pre + [CODE_DONE_TODAY])
    if len(runs) >= MAX_RUNS_PER_DAY:
        return _refused(pre + [CODE_RUNS_EXHAUSTED])
    redo = _redo_statuses(runs)
    try:
        run_id = store.begin_run(today, now)
    except S.StoreRefused:
        return _refused(pre + [CODE_RUN_RUNNING])
    codes: List[str] = pre + list(ready.codes)
    counts: Counter = Counter()
    tally: Counter = Counter()
    try:
        status, err = _body(reader, store, clock, run_id, ready.pairing_id, today, deadline, th, switches, enabled,
                            redo, codes, counts, tally)
    except BaseException as e:
        kind = CODE_UNEXPECTED if not isinstance(e, S.StoreError) else "STORE_ERROR"
        try:
            store.finish_run(run_id, S.RUN_FAILED, _need_time(clock()), error_kind=kind)
        except S.StoreError:
            pass
        raise
    store.finish_run(run_id, status, _need_time(clock()), accounts_total=counts.get("targets", 0),
                     accounts_ok=counts.get(V.CHECK_OK, 0), error_kind=err)
    if counts.get(V.CHECK_DATA_LATE):
        codes.append(CODE_DATA_LATE)
    cs = tuple(dict.fromkeys(codes))
    return MorningOutcome(OUT_DONE if status == S.RUN_DONE else OUT_FAILED, cs, run_id, dict(counts), dict(tally),
                          alert=bool(set(cs) & ALERTING))


def _record(store: S.Store, run_id: int, row: dict, clock, counts: Counter, tally: Counter, codes: List[str],
            **kw) -> bool:
    try:
        got = store.record_account_check(run_id, row["customer_id"], possibility_id=row["possibility_id"],
                                         checked_at=_need_time(clock()), **kw)
    except S.StoreRefused:
        codes.append(CODE_STORE_REFUSED)
        counts["store_refused"] += 1
        return False
    counts[kw["status"]] += 1
    tally.update(got.counts)
    return True


def _body(reader, store: S.Store, clock, run_id: int, pairing_id: int, today: date, deadline: datetime,
          th: Thresholds, switches, enabled: Tuple[str, ...], redo: frozenset, codes: List[str], counts: Counter,
          tally: Counter) -> Tuple[str, Optional[str]]:
    relevant, dups, per_cid = _pair_rows(store, pairing_id)
    if dups:
        codes.append(CODE_PAIR_DUPLICATE)
        counts["duplicate_skipped"] += sum(per_cid[c] for c in dups)

    # ① 이관 상태 — 네이버 호출 없이 먼저 적는다
    for r in relevant:
        if r["state"] == S.PAIR_BROKEN:
            facts = (("reason", FACT_NEVER_LISTED),) if r["code"] == S.PAIR_CODE_NEVER_LISTED else ()
            try:
                target = I.account_target(r["customer_id"])
            except I.IssueRuleError:   # 규칙이 받지 않는 번호 — 그 줄만 빼고 알린다(한 줄이 회차를 멈추지 않게)
                codes.append(CODE_STORE_REFUSED)
                counts["store_refused"] += 1
                continue
            f = _LinkFinding(I.RULE_LINK, I.CODE_LINK_BROKEN, target, I.LINK_SEVERITY, facts)
            _record(store, run_id, r, clock, counts, tally, codes, link=r["link"], status=V.CHECK_LINK_BROKEN,
                    rules_run=(I.RULE_LINK,), rules_not_run=[(x, REASON_LINK_BROKEN) for x in enabled],
                    findings=(f,))
        elif r["state"] == S.PAIR_MISSING:
            _record(store, run_id, r, clock, counts, tally, codes, link=r["link"], status=V.CHECK_LINK_MISSING,
                    rules_run=(), rules_not_run=[(I.RULE_LINK, REASON_LINK_MISSING)] +
                    [(x, REASON_LINK_MISSING) for x in enabled])

    # ② 짝이 사라진 열린 이슈(M5)
    unl = store.close_unlinked_issues(run_id, pairing_id, _need_time(clock()))
    counts["unlinked_issues"] += unl.closed_issues
    if unl.closed_issues:
        tally[I.EV_UNLINKED] += unl.closed_issues
    if unl.mass:
        codes.append(CODE_UNLINK_MASS)

    # ③ 점검할 짝 — 오늘 아직 끝나지 않은 것만(첫 회차는 전부)
    todo = _order(_still_to_do(relevant, store.account_day_marks_on(today), redo), store, today)
    counts["targets"] = len(todo)
    prospects = {p["possibility_id"]: p for p in store.prospects()}
    stage_at = store.stage_as_of()
    yday = store.account_days_on(today - timedelta(days=1))
    attempts = unavailable = key_attempts = key_rejected = 0
    for i, r in enumerate(todo):
        if _need_time(clock()) >= deadline:
            counts["deadline_left"] += len(todo) - i
            codes.append(CODE_DEADLINE_CUT)
            break
        cid, pid = r["customer_id"], r["possibility_id"]
        p = prospects.get(pid)
        end = None if p is None or p["latest_end_date"] is None else date.fromisoformat(p["latest_end_date"])
        try:
            if p is None or p["present"] != 1 or p["stage_conflict"] or p["end_unreadable"]:
                raise H.NotEligible("prospect-not-managed")
            ah = H.issue_check_handle(customer_id=cid, possibility_id=pid, link_state=r["state"], stage=p["stage_key"],
                                      stage_as_of=stage_at, latest_end_date=end, now=_need_time(clock()))
        except H.NotEligible as e:
            status = V.CHECK_SYSTEM_GAP if e.reason in SYSTEM_GAP_REASONS else V.CHECK_NOT_ELIGIBLE
            if status == V.CHECK_SYSTEM_GAP:
                codes.append(CODE_SYSTEM_GAP)
            _record(store, run_id, r, clock, counts, tally, codes, link=r["state"], status=status,
                    rules_run=(I.RULE_LINK,), rules_not_run=[(x, e.reason) for x in enabled])
            continue
        try:
            reads = read_account(reader, ah, cid, today, clock, deadline)
            if _need_time(clock()) >= deadline:   # 마지막 읽기가 마감을 넘겨 끝났다 — 모두 되거나 모두 안 된 것
                raise _PastDeadline()
            acc, day = account_input(cid, reads, today, th)
            report = C.run_checks(acc, C.StageInfo(p["stage_key"], stage_at), _need_time(clock()), th, switches)
        except _PastDeadline:
            counts["deadline_left"] += len(todo) - i
            codes.append(CODE_DEADLINE_CUT)
            break
        except N.RunAbort:
            codes.append(CODE_RUN_ABORT)
            counts["abort_left"] += len(todo) - i
            return S.RUN_FAILED, CODE_RUN_ABORT
        except H.HandleInvalid:
            codes.append(CODE_HANDLE_INVALID)
            counts["handle_invalid"] += 1
            continue
        except Exception:   # 계정 한 곳의 뜻밖의 오류(이상한 응답 등) — 그 계정만 적지 않는다(⚪ 점검 안 됨) · 경보
            codes.append(CODE_ACCOUNT_ERROR)
            counts["account_error"] += 1
            continue
        if reads.shape_unknown:
            codes.append(CODE_SHAPE_UNKNOWN)
        attempts += 1
        if UNAVAILABLE_KINDS & {reads.campaigns_error, reads.bizmoney_error, reads.stats_error}:
            unavailable += 1
        if yday.get(cid) != V.CHECK_KEY_REJECTED:   # 어제도 거절이던 계정(광고주별 권한)은 「전 계정 거절」 표본이 아니다
            key_attempts += 1
            if reads.campaigns_error == N.KIND_KEY_REJECTED:
                key_rejected += 1
        if report.status == V.CHECK_SYSTEM_GAP:
            codes.append(CODE_SYSTEM_GAP)
        extra = {}
        if reads.campaigns_raw is not None:
            extra = dict(campaigns=reads.campaigns_raw, stats_day=window(today)[1],
                         stats=yesterday_stats(reads, today), provisional=True)
        _record(store, run_id, r, clock, counts, tally, codes, link=r["state"], status=report.status,
                rules_run=tuple(report.rules_run) + (I.RULE_LINK,), rules_not_run=report.rules_not_run,
                findings=report.findings, data_late=day.get("data_late"), bizmoney=day.get("bizmoney"),
                budget_lock=day.get("budget_lock"), refund_lock=day.get("refund_lock"),
                yday_spend=day.get("yday_spend"), yday_imp=day.get("yday_imp"), yday_clk=day.get("yday_clk"), **extra)
        stop = None
        if key_attempts >= KEY_ALL_MIN and key_rejected == key_attempts:
            stop = CODE_KEY_REJECTED_ALL
        elif key_attempts >= KEY_RATIO_MIN and key_rejected >= key_attempts * KEY_RATIO:
            stop = CODE_KEY_REJECTED_MANY
        elif (attempts >= KEY_ALL_MIN and unavailable == attempts) or \
                (attempts >= KEY_RATIO_MIN and unavailable >= attempts * KEY_RATIO):
            stop = CODE_NAVER_UNAVAILABLE
        if stop is not None:
            codes.append(stop)
            counts["abort_left"] += len(todo) - i - 1
            return S.RUN_FAILED, stop
    return S.RUN_DONE, (CODE_DEADLINE_CUT if CODE_DEADLINE_CUT in codes else None)


__all__ = ("run_morning", "run_requested", "morning_due", "readiness", "MorningOutcome", "Readiness", "window", "complete_through",
           "reconcile", "read_account", "account_input", "yesterday_stats")
