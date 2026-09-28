"""네이버 계정에 들어가도 되는지 판정하는 **한 곳** — 통과해야 손잡이(handle)를 준다.

읽기 관문(``naver_read``)은 날 번호를 받지 않는다. 이 파일이 발급한 손잡이만 받는다(설계 v1.8 · 반박 H2).
그래서 「계약 끝나고 14일이 지나면 들어가지 않는다」(대표 법적 확인 후속)를 부르는 쪽이 잊어도 지켜진다.

손잡이 두 종류:
- ``ManagerHandle`` — 대행사 계정 자기 자신(관리계정 목록 · 하위 계정 목록만).
- ``AccountHandle`` — 광고주 계정 한 곳. 목적이 둘이다.
    ``check``   아침 점검. 짝이 확인됐거나(confirmed) 전산 고객 번호로 이어진 짝(auto)일 때만.
    ``preview`` 짝 확인 화면에서 **사람이 그 줄을 누를 때만**(누른 직원 번호 필수). 저장하지 않는다.

손잡이는 발급한 날(KST)에만 쓸 수 있다 — 밤사이 계약 단계가 바뀌어도 어제 손잡이로 들어가지 못한다.
손잡이 값은 이 프로세스만 아는 열쇠로 서명돼 있어, 번호만 바꾼 가짜 손잡이는 거절된다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

KST = timezone(timedelta(hours=9))

PURPOSE_CHECK = "check"
PURPOSE_PREVIEW = "preview"
_PURPOSES = frozenset({PURPOSE_CHECK, PURPOSE_PREVIEW})

LINK_CONFIRMED = "confirmed"  # 사람이 「이 계정 맞음」을 눌렀다
LINK_AUTO = "auto"            # ① 전산에 적힌 고객 번호와 같다(확인 필요 표시는 그대로 — 반박 H4)
LINK_CHECKABLE = frozenset({LINK_CONFIRMED, LINK_AUTO})

# 관제 대상 단계(M3) — ① 계약 단계 이름에서 빈칸을 모두 뺀 글자로 비교한다.
# ① 코드는 「사후관리」(붙여 씀), 계약서는 「사후 관리」 — 둘 다 같은 단계로 읽는다(반박 H3).
STAGE_ENDED = "계약만료"
MONITORED_STAGES = frozenset({"진행중", "전략관리", "사후관리", "홀딩중", "재계약진행중", "환불중", STAGE_ENDED})
ENDED_GRACE_DAYS = 14               # 계약이 끝나고 14일까지만 들어간다(그날 포함)
STAGE_MAX_AGE = timedelta(hours=72)  # 단계 자료가 이보다 낡았으면 들어가지 않는다(끝난 계약이 진행중으로 보일 수 있다)

PREVIEW_TTL = timedelta(minutes=10)   # 미리보기 손잡이는 누른 뒤 10분 안에만
PREVIEW_MAX_USES = 3                  # 한 번 누르면 호출 3번까지(캠페인 이름 · 비즈채널)
PREVIEW_DAILY_CAP = 300               # 한 사람이 하루에 발급할 수 있는 미리보기 손잡이 수

_MAX_ID = 10 ** 15
_DIGITS = re.compile(r"[0-9]{1,15}")
_WS = re.compile(r"\s+")
_KEY = os.urandom(32)  # 이 프로세스만 아는 서명 열쇠 — 이 파일 밖에서 쓰면 시험이 실패한다
_PREVIEW_LEFT = {}     # 미리보기 손잡이 번호 → (남은 사용 횟수, 발급 시각)
_PREVIEW_ISSUED = {}   # (직원 번호, 날짜) → 오늘 발급 수


class NotEligible(Exception):
    """이 계정에는 들어가지 않는다. ``reason`` 은 사람이 읽는 짧은 사유 코드."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class HandleInvalid(RuntimeError):
    """손잡이가 아니거나, 오늘 것이 아니거나, 목적이 맞지 않거나, 위조됐다."""


def stage_key(stage) -> str:
    return _WS.sub("", stage) if isinstance(stage, str) else ""


def normalize_customer_id(raw) -> int:
    """네이버 고객 번호 — 양의 정수(참·거짓 값 금지) 또는 숫자만 있는 글자."""
    if isinstance(raw, bool):
        raise NotEligible("customer-id-invalid")
    if isinstance(raw, int):
        if 0 < raw < _MAX_ID:
            return raw
        raise NotEligible("customer-id-invalid")
    if isinstance(raw, str) and _DIGITS.fullmatch(raw.strip()) and int(raw.strip()) > 0:
        return int(raw.strip())
    raise NotEligible("customer-id-invalid")


def _kst_today(now: datetime) -> date:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 합니다")
    return now.astimezone(KST).date()


def _tag(*parts) -> str:
    msg = "|".join(str(p) for p in parts).encode("utf-8")
    return hmac.new(_KEY, msg, hashlib.sha256).hexdigest()


class _Frozen:
    __slots__ = ()

    def __setattr__(self, name, value):
        raise AttributeError("손잡이는 바꿀 수 없습니다")

    def __delattr__(self, name):
        raise AttributeError("손잡이는 바꿀 수 없습니다")

    def __reduce__(self):
        raise TypeError("손잡이는 직렬화할 수 없습니다")


class ManagerHandle(_Frozen):
    __slots__ = ("customer_id", "issued_on", "_tag")

    def __init__(self, customer_id: int, issued_on: date, tag: str) -> None:
        object.__setattr__(self, "customer_id", customer_id)
        object.__setattr__(self, "issued_on", issued_on)
        object.__setattr__(self, "_tag", tag)

    def __repr__(self) -> str:
        return f"ManagerHandle(…{str(self.customer_id)[-4:]}, {self.issued_on})"


class AccountHandle(_Frozen):
    __slots__ = ("customer_id", "possibility_id", "purpose", "issued_on", "requested_by", "candidate_id",
                 "issued_at", "nonce", "_tag")

    def __init__(self, customer_id: int, possibility_id: int, purpose: str, issued_on: date,
                 requested_by: Optional[int], candidate_id: Optional[int], issued_at: datetime, nonce: str,
                 tag: str) -> None:
        object.__setattr__(self, "customer_id", customer_id)
        object.__setattr__(self, "possibility_id", possibility_id)
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "issued_on", issued_on)
        object.__setattr__(self, "requested_by", requested_by)
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "nonce", nonce)
        object.__setattr__(self, "_tag", tag)

    def __repr__(self) -> str:
        return f"AccountHandle({self.purpose}, …{str(self.customer_id)[-4:]}, 가망 {self.possibility_id}, {self.issued_on})"


def _check_stage(stage, stage_as_of: datetime, latest_end_date: Optional[date], now: datetime) -> None:
    key = stage_key(stage)
    if key not in MONITORED_STAGES:
        raise NotEligible("stage-not-monitored")
    if not isinstance(stage_as_of, datetime) or stage_as_of.tzinfo is None:
        raise NotEligible("stage-time-unknown")
    if now - stage_as_of > STAGE_MAX_AGE:
        raise NotEligible("stage-stale")
    if stage_as_of - now > timedelta(minutes=5):
        raise NotEligible("stage-time-in-future")
    if latest_end_date is not None and (not isinstance(latest_end_date, date) or isinstance(latest_end_date, datetime)):
        raise NotEligible("end-date-invalid")
    if key == STAGE_ENDED and latest_end_date is None:
        raise NotEligible("ended-end-date-unknown")
    # 종료일이 적혀 있으면 **어느 단계든** 14일 규칙을 건다 — 전산 단계가 계약보다 늦게 바뀌는 곳이 있다
    # (① 상태 보드 실측: 계약이 끝났는데 단계가 진행중·재계약 진행중인 곳 28). 사람이 전산을 고치면 다시 들어간다.
    if latest_end_date is not None and (_kst_today(now) - latest_end_date).days > ENDED_GRACE_DAYS:
        raise NotEligible("ended-over-14-days")


def _check_possibility(possibility_id) -> int:
    if isinstance(possibility_id, bool) or not isinstance(possibility_id, int) or possibility_id <= 0:
        raise NotEligible("possibility-invalid")
    return possibility_id


def issue_check_handle(*, customer_id, possibility_id, link_state, stage, stage_as_of: datetime,
                       latest_end_date: Optional[date], now: datetime) -> AccountHandle:
    """아침 점검용 손잡이. 통과 못 하면 ``NotEligible(사유)``."""
    cid = normalize_customer_id(customer_id)
    pid = _check_possibility(possibility_id)
    if link_state not in LINK_CHECKABLE:
        raise NotEligible("link-not-checkable")
    _check_stage(stage, stage_as_of, latest_end_date, now)
    today = _kst_today(now)
    return AccountHandle(cid, pid, PURPOSE_CHECK, today, None, None, now, "",
                         _tag("A", PURPOSE_CHECK, cid, pid, today, None, None, now.isoformat(), ""))


def issue_preview_handle(*, customer_id, possibility_id, candidate_id, stage, stage_as_of: datetime,
                         latest_end_date: Optional[date], now: datetime, requested_by) -> AccountHandle:
    """짝 확인 화면 미리보기용 손잡이 — 사람이 그 후보 줄을 누를 때만(반박 H2 · 대표 결정 Q2).

    ``requested_by`` = 누른 ① 직원 번호(대표 = 0) · ``candidate_id`` = 짝 후보 기록 번호.
    10분 안에 · 호출 3번까지만 쓸 수 있고, 한 사람이 하루에 300개까지만 발급한다 — 일괄로 1,784곳을 읽는 길을 막는다.
    """
    cid = normalize_customer_id(customer_id)
    pid = _check_possibility(possibility_id)
    if isinstance(candidate_id, bool) or not isinstance(candidate_id, int) or candidate_id <= 0:
        raise NotEligible("candidate-invalid")
    if isinstance(requested_by, bool) or not isinstance(requested_by, int) or requested_by < 0:
        raise NotEligible("requester-invalid")
    _check_stage(stage, stage_as_of, latest_end_date, now)
    today = _kst_today(now)
    _prune(now, today)
    key = (requested_by, today)
    if _PREVIEW_ISSUED.get(key, 0) >= PREVIEW_DAILY_CAP:
        raise NotEligible("preview-daily-cap")
    _PREVIEW_ISSUED[key] = _PREVIEW_ISSUED.get(key, 0) + 1
    nonce = os.urandom(12).hex()
    _PREVIEW_LEFT[nonce] = (PREVIEW_MAX_USES, now)
    return AccountHandle(cid, pid, PURPOSE_PREVIEW, today, requested_by, candidate_id, now, nonce,
                         _tag("A", PURPOSE_PREVIEW, cid, pid, today, requested_by, candidate_id, now.isoformat(), nonce))


def _prune(now: datetime, today: date) -> None:
    """지난 미리보기 기록을 비운다(메모리가 쌓이지 않게)."""
    for n in [n for n, (_left, at) in _PREVIEW_LEFT.items() if now - at > PREVIEW_TTL]:
        del _PREVIEW_LEFT[n]
    for k in [k for k in _PREVIEW_ISSUED if k[1] != today]:
        del _PREVIEW_ISSUED[k]


def issue_manager_handle(customer_id, now: datetime) -> ManagerHandle:
    """대행사 계정 자기 자신의 손잡이(관리계정·하위 계정 목록만)."""
    cid = normalize_customer_id(customer_id)
    today = _kst_today(now)
    return ManagerHandle(cid, today, _tag("M", cid, today))


def require_account(handle, now: datetime, purposes: Iterable[str]) -> AccountHandle:
    """읽기 관문이 부른다. 오늘 발급한 진짜 손잡이이고 목적이 맞을 때만 돌려준다."""
    if type(handle) is not AccountHandle:
        raise HandleInvalid("계정 손잡이가 아닙니다(날 번호는 받지 않습니다)")
    allowed = frozenset(purposes)
    if handle.purpose not in _PURPOSES or handle.purpose not in allowed:
        raise HandleInvalid("이 호출에 쓸 수 없는 손잡이입니다")
    if not isinstance(handle.issued_at, datetime) or handle.issued_at.tzinfo is None:
        raise HandleInvalid("손잡이 발급 시각이 없습니다")
    expect = _tag("A", handle.purpose, handle.customer_id, handle.possibility_id, handle.issued_on, handle.requested_by,
                  handle.candidate_id, handle.issued_at.isoformat(), handle.nonce)
    if not hmac.compare_digest(expect, handle._tag):
        raise HandleInvalid("손잡이 서명이 맞지 않습니다")
    if handle.issued_on != _kst_today(now):
        raise HandleInvalid("오늘 발급한 손잡이가 아닙니다")
    if handle.purpose == PURPOSE_PREVIEW:
        if not (timedelta(0) <= now - handle.issued_at <= PREVIEW_TTL):
            raise HandleInvalid("미리보기 손잡이 시간이 지났습니다")
        left, at = _PREVIEW_LEFT.get(handle.nonce, (0, None))
        if left <= 0:
            raise HandleInvalid("미리보기 손잡이를 이미 다 썼습니다")
        _PREVIEW_LEFT[handle.nonce] = (left - 1, at)
    return handle


def require_manager(handle, now: datetime, customer_id: int) -> ManagerHandle:
    if type(handle) is not ManagerHandle:
        raise HandleInvalid("관리계정 손잡이가 아닙니다")
    expect = _tag("M", handle.customer_id, handle.issued_on)
    if not hmac.compare_digest(expect, handle._tag):
        raise HandleInvalid("손잡이 서명이 맞지 않습니다")
    if handle.customer_id != customer_id:
        raise HandleInvalid("대행사 계정이 아닙니다")
    if handle.issued_on != _kst_today(now):
        raise HandleInvalid("오늘 발급한 손잡이가 아닙니다")
    return handle
