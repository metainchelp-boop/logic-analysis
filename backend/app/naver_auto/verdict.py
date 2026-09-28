"""광고주 판정 — 🔴 · ⚪ · 🟡 · 🟢 와 「확인 필요」를 정하는 **한 곳** (설계 v1.7 판정 표 · v1.8 J4 · 반박 C1·M2·H1·H4).

화면 · 🔔 · 보고서 · ① 건수가 모두 이 함수 하나를 쓴다(두 가지로 읽히지 않게). 순수 함수 — 저장·네트워크·시계를 모른다
(지금 시각과 마감 시각은 부르는 쪽이 넣는다).

우선순위(J4): 🔴 열린 긴급 > ⚪ 오늘 확인 못 함 > 🟡 열린 주의 > 🟢.
- **⚪ 는 절대 🟢 로 보이지 않는다.** 계정 하나라도 「오늘 · 온전히」 점검되지 않았으면 그 가망은 🟢 가 될 수 없다.
  「오늘」은 계정 결과의 날짜로 대조한다 — 어제 결과가 오늘 것처럼 보이지 않게.
- 「돌았지만 규칙 일부를 온전한 자료로 못 돌림」도 ⚪ 다(반박 C1(a)).
- 마감(08:00) 전 아직 안 돈 계정은 ⚪ 「점검 전」(확인 필요 아니오), 마감 뒤는 「점검 안 됨」(확인 필요 예) — 반박 M2.
- 전산 고객 번호로 이어진 자동 짝은 색과 상관없이 「확인 필요 예(계정 확인 전)」 — 반박 H4.
- 🙈 예외는 기간 안에서만 세지 않는다. 기간이 끝난 예외는 다시 🆕 처럼 센다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional, Sequence

KST = timezone(timedelta(hours=9))

RED, WHITE, YELLOW, GREEN = "red", "white", "yellow", "green"

# 계정 한 곳의 오늘 점검 상태(엔진 check_run 이 채운다)
CHECK_OK = "ok"                      # 꼭 읽을 것 전부 읽음 · 규칙 전부 온전한 자료로 돌림
CHECK_PENDING = "pending"            # 아직 차례가 안 옴(마감 전에만 의미가 있다)
CHECK_NOT_CHECKED = "not_checked"    # 마감까지 못 함
CHECK_PARTIAL = "partial"            # 일부만 읽힘 · 일부 규칙을 못 돌림
CHECK_KEY_REJECTED = "key_rejected"  # 네이버가 그 계정 읽기를 거절(401·403·1006·1018)
CHECK_DATA_LATE = "data_late"        # 네이버 어제 자료가 아직 다 안 들어옴(기준 시각)
CHECK_SYSTEM_GAP = "system_gap"      # 우리 쪽 자료 문제(예: 전산 단계 자료가 오래됨) — 직원이 할 일이 없고 대표 시스템 경보로 간다
CHECK_LINK_BROKEN = "link_broken"    # 확인했던 짝이 대행 연결 목록에서 사라짐(반박 H1)
CHECK_NOT_ELIGIBLE = "not_eligible"  # 들어가면 안 되는 계정(예: 전산 종료일이 14일 넘게 지남) — 손잡이 거절

LINK_CONFIRMED, LINK_AUTO = "confirmed", "auto"

WHITE_NO_LINK = "no_link"            # 이어진 네이버 계정이 없음(주간 목록으로 따로 · 확인 필요 아니오)

# ⚪ 사유 → 「확인 필요」인가
_WHITE_NEEDS = {
    CHECK_NOT_CHECKED: True,
    CHECK_PARTIAL: True,
    CHECK_KEY_REJECTED: True,
    CHECK_LINK_BROKEN: True,
    CHECK_NOT_ELIGIBLE: True,
    CHECK_DATA_LATE: False,          # 네이버 쪽 늦음 — 직원이 할 일이 없다(시스템 경보는 따로)
    CHECK_SYSTEM_GAP: False,         # 우리 쪽 자료 문제 — 모든 광고주가 한꺼번에 「확인 필요」로 뜨지 않게(시스템 경보는 따로)
    CHECK_PENDING: False,
    WHITE_NO_LINK: False,
}
# 화면에 먼저 보일 ⚪ 사유(앞일수록 먼저)
_WHITE_ORDER = (CHECK_NOT_CHECKED, CHECK_PARTIAL, CHECK_KEY_REJECTED, CHECK_LINK_BROKEN, CHECK_NOT_ELIGIBLE,
                CHECK_DATA_LATE, CHECK_SYSTEM_GAP, CHECK_PENDING, WHITE_NO_LINK)
_STATUSES = frozenset(_WHITE_ORDER) - {WHITE_NO_LINK} | {CHECK_OK}

SEV_RED, SEV_YELLOW, SEV_INFO = "red", "yellow", "info"
ST_NEW, ST_ACK, ST_EXCEPTION = "new", "ack", "exception"
ST_CLOSED = frozenset({"resolved", "auto_resolved", "closed_unlinked"})  # 닫힌 이슈 — 넘겨도 세지 않는다


@dataclass(frozen=True)
class AccountCheck:
    """가망에 이어진 네이버 계정 한 곳의 오늘 점검 결과."""
    customer_id: int = field(repr=False)   # 표시(repr)·로그에 고객 번호가 새지 않게
    link: str                            # confirmed · auto
    status: str                          # CHECK_*
    checked_on: Optional[date]           # 이 결과가 어느 날(KST) 것인가 — 오늘이 아니면 오늘 결과가 아니다
    rules_not_run: tuple = ()            # 온전한 자료로 못 돌린 규칙 코드


@dataclass(frozen=True)
class OpenIssue:
    severity: str                        # red · yellow · info
    state: str                           # new · ack · exception (닫힌 것은 세지 않음)
    exception_until: Optional[date] = None


@dataclass(frozen=True)
class Verdict:
    color: str
    needs_attention: bool
    reasons: tuple                       # 짧은 사유 코드들(화면 문구는 화면이 붙인다)
    white_reason: Optional[str] = None   # ⚪ 일 때 먼저 보일 사유


def _validate_issue(i: OpenIssue) -> None:
    if i.severity not in (SEV_RED, SEV_YELLOW, SEV_INFO):
        raise ValueError("모르는 이슈 등급")
    if i.state not in (ST_NEW, ST_ACK, ST_EXCEPTION) and i.state not in ST_CLOSED:
        raise ValueError("모르는 이슈 상태")
    if i.state == ST_EXCEPTION and type(i.exception_until) is not date:   # 시각(datetime)은 날짜가 아니다
        raise ValueError("예외에는 끝나는 날이 있어야 한다")


def _effective_state(i: OpenIssue, today: date) -> Optional[str]:
    """세는 상태 — 닫힌 것은 None · 기간이 끝난 예외는 새로(🆕)."""
    if i.state in ST_CLOSED:
        return None
    if i.state == ST_EXCEPTION:
        return ST_EXCEPTION if i.exception_until >= today else ST_NEW
    return i.state


def _account_status(a: AccountCheck, today: date, deadline_passed: bool) -> str:
    if not isinstance(a, AccountCheck):
        raise ValueError("계정 결과가 아니다")
    if a.status not in _STATUSES:
        raise ValueError("모르는 점검 상태")
    if a.link not in (LINK_CONFIRMED, LINK_AUTO):
        raise ValueError("모르는 짝 상태")
    if a.checked_on is not None and type(a.checked_on) is not date:
        raise ValueError("점검 날짜는 날짜(date)여야 한다")   # 시각이 오면 「오늘이 아님」으로 조용히 떨어진다
    if a.status in (CHECK_LINK_BROKEN, CHECK_NOT_ELIGIBLE):
        return a.status                  # 날짜와 상관없이 그 상태
    if a.checked_on != today:            # 어제(이전) 결과는 오늘 결과가 아니다
        return CHECK_NOT_CHECKED if deadline_passed else CHECK_PENDING
    if a.status == CHECK_PENDING and deadline_passed:
        return CHECK_NOT_CHECKED
    if a.status == CHECK_OK and a.rules_not_run:
        return CHECK_PARTIAL             # 돌았지만 규칙 일부를 못 돌림 = 온전하지 않음
    return a.status


def judge(*, accounts: Sequence[AccountCheck], issues: Iterable[OpenIssue], now: datetime,
          deadline: datetime) -> Verdict:
    """가망 하나의 오늘 판정. ``now``·``deadline`` 은 시간대가 있는 시각(마감 = 그날 08:00 KST)."""
    if not isinstance(now, datetime) or now.tzinfo is None or not isinstance(deadline, datetime) \
            or deadline.tzinfo is None:
        raise ValueError("시각에는 시간대가 있어야 한다")
    today = now.astimezone(KST).date()   # 「오늘」은 지금 시각의 한국 날짜 — 마감의 시간대에 기대지 않는다
    if deadline.astimezone(KST).date() != today:
        raise ValueError("마감은 오늘(KST) 날짜의 시각이어야 한다")   # 낡은 마감·다른 날 마감으로 어제 결과가 🟢 가 되지 않게
    deadline_passed = now >= deadline
    accounts = list(accounts)            # 한 번만 도는 반복자여도 두 번 본다(연결 없음 · 자동 짝 판정)

    issues = list(issues)
    for i in issues:
        _validate_issue(i)
    states = [(i.severity, _effective_state(i, today)) for i in issues]
    open_red = [s for sev, s in states if sev == SEV_RED and s in (ST_NEW, ST_ACK)]
    open_yellow = [s for sev, s in states if sev == SEV_YELLOW and s in (ST_NEW, ST_ACK)]

    statuses = [_account_status(a, today, deadline_passed) for a in accounts]
    whites = [s for s in statuses if s != CHECK_OK]
    if not accounts:
        whites = [WHITE_NO_LINK]
    auto = any(a.link == LINK_AUTO for a in accounts)

    reasons = []
    needs = False
    if open_red:
        reasons.append("open-red")
        needs = True                     # 👀 확인 중이어도 풀릴 때까지 확인 필요
    white_reason = None
    if whites:
        white_reason = min(whites, key=_WHITE_ORDER.index)
        reasons.extend(sorted(set(whites), key=_WHITE_ORDER.index))
        needs = needs or any(_WHITE_NEEDS[w] for w in whites)
    if open_yellow:
        reasons.append("open-yellow")
        needs = needs or ST_NEW in open_yellow
    if auto:
        reasons.append("account-unconfirmed")
        needs = True                     # 자동 짝 — 계정 확인 전(반박 H4)

    if open_red:
        color = RED
    elif whites:
        color = WHITE
    elif open_yellow:
        color = YELLOW
    else:
        color = GREEN
    return Verdict(color, needs, tuple(reasons), white_reason)
