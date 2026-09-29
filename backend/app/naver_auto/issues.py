"""이슈 상태 규칙 — 한 곳 (설계 v1.7 이슈 · v1.8 반박 C1 · M5 · M7 · 대표 결정 I1 ⓐ).

순수 함수 — 저장·네트워크·시계를 모른다. 엔진 저장소(S9)가 거래 안에서 이 규칙으로 이슈 줄을 고치고, 화면 API(S11)도
같은 규칙을 쓴다(사람이 누르는 확인·해결·예외).

단계: 🆕 ``new``(점검이 만듦) → 👀 ``ack``(담당이 봄) → ✅ ``resolved``(사람) · 🔁 ``auto_resolved``(다음 점검에서 조건이
사라짐) · 🙈 ``exception``(사유 + 기간) · 「연결 해제로 닫힘」 ``closed_unlinked``(짝이 거절·무효 — M5).

지키는 것
- **같은 원인 + 같은 대상은 한 줄**(열쇠 = 가망 + 점검 항목 + 대상) — 저장소가 열쇠로 한 줄만 둔다. 이 규칙은 줄 하나의
  상태만 본다.
- **닫힌 이슈가 다시 보이면 🆕** 으로 되살리고 「다시 생김」을 하나 센다(✅ 사람이 해결했는데 그대로인 경우 포함).
- **저절로 풀림은 부르는 쪽 판정이 먼저다** — 그 규칙이 오늘 온전한 자료로 돌았고 조건이 사라졌을 때만
  (``should_auto_resolve``) · 자료 늦음인 날은 부르지 않는다(👀·🙈 를 건드리지 않게 · 반박 C1).
- **등급이 올라가면 다시 🆕** — 🟡 로 확인해 둔 것이 🔴 가 되면 그냥 두지 않는다. 예외도 준 등급보다 올라가면 끝난다.
- **예외 한도(M7)** — 🟡·ⓘ = 담당 이상 · 오늘 포함 최대 30일 / 🔴 = 팀장 이상만 · 오늘 포함 최대 7일. 예외 중에는 다시
  예외를 줄 수 없다(끝나고 다시 본 뒤에만 — 끝없이 이어 붙이지 못하게). 누가 담당·팀장인지는 부르는 쪽(``scope``)이 정해
  ``actor`` 로 넘긴다.
- **이관 빠짐(I1 ⓐ)** — 점검 항목 ``link_broken`` · 🔴 긴급 · 다시 이관되면 다음 아침 🔁 저절로 풀림 · 예외는 위 🔴 한도.
- 오류 문구에는 값(번호·날짜)을 넣지 않는다 — 사유 코드만.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Iterable, Optional, Tuple

from .verdict import SEV_INFO, SEV_RED, SEV_YELLOW, ST_ACK, ST_CLOSED, ST_EXCEPTION, ST_NEW

ST_RESOLVED, ST_AUTO_RESOLVED, ST_UNLINKED = "resolved", "auto_resolved", "closed_unlinked"
OPEN_STATES = frozenset({ST_NEW, ST_ACK, ST_EXCEPTION})
CLOSED_STATES = frozenset({ST_RESOLVED, ST_AUTO_RESOLVED, ST_UNLINKED})
STATES = OPEN_STATES | CLOSED_STATES
SEVERITIES = (SEV_INFO, SEV_YELLOW, SEV_RED)
_RANK = {s: i for i, s in enumerate(SEVERITIES)}

# 이관 빠짐 이슈(대표 결정 I1 ⓐ) — 규칙 ``link`` · 항목 ``link_broken`` · 🔴
RULE_LINK = "link"
CODE_LINK_BROKEN = "link_broken"
LINK_SEVERITY = SEV_RED

# 예외를 주는 사람의 층 — 담당(메인·서브) · 팀장 이상(팀장 · 대표). 누가 어느 층인지는 scope 가 정한다.
ACTOR_OWNER, ACTOR_LEAD = "owner", "lead"
_ACTORS = (ACTOR_OWNER, ACTOR_LEAD)
EXCEPTION_MAX_DAYS = {SEV_INFO: 30, SEV_YELLOW: 30, SEV_RED: 7}   # 오늘 포함 날수
EXCEPTION_MIN_ACTOR = {SEV_INFO: ACTOR_OWNER, SEV_YELLOW: ACTOR_OWNER, SEV_RED: ACTOR_LEAD}
NOTE_MAX = 200   # 예외 사유 글자 수

# 기록(이슈 기록 표의 kind) — 상태나 등급이 바뀔 때만 한 줄(매일 「봤음」은 줄이 아니라 마지막 본 날로 남는다)
EV_OPENED = "opened"
EV_REAPPEARED = "reappeared"
EV_ESCALATED = "escalated"
EV_DEESCALATED = "deescalated"
EV_EXCEPTION_ENDED = "exception_ended"
EV_AUTO_RESOLVED = "auto_resolved"
EV_UNLINKED = "closed_unlinked"
EV_ACKED = "acked"
EV_RESOLVED = "resolved"
EV_EXCEPTED = "excepted"
EVENTS = (EV_OPENED, EV_REAPPEARED, EV_ESCALATED, EV_DEESCALATED, EV_EXCEPTION_ENDED, EV_AUTO_RESOLVED, EV_UNLINKED,
          EV_ACKED, EV_RESOLVED, EV_EXCEPTED)

# 거절 사유 코드
E_BAD_INPUT = "bad-input"
E_NOT_OPEN = "not-open"
E_NOT_NEW = "not-new"
E_ACTOR = "actor-too-low"
E_TOO_LONG = "exception-too-long"
E_PAST = "exception-in-past"
E_ALREADY = "exception-active"
E_NOTE = "note-required"

# 대상 — 계정이면 "acc:<고객 번호>" · 캠페인이면 네이버 캠페인 번호(checks.Finding.target 과 같은 모양)
_TARGET = re.compile(r"acc:[1-9][0-9]{0,14}|cmp-[A-Za-z0-9-]{1,60}")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,39}")


class IssueRuleError(ValueError):
    """규칙이 받지 않는 손길 — ``code`` 는 사유 코드(값 없음)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class IssueState:
    """이슈 한 줄의 지금(저장소가 읽어 넣는다)."""
    state: str
    severity: str
    first_seen_on: date
    last_seen_on: date
    reappear_count: int = 0
    exception_until: Optional[date] = None
    exception_severity: Optional[str] = None   # 예외를 준 때의 등급 — 그보다 올라가면 예외가 끝난다


@dataclass(frozen=True)
class Change:
    """규칙이 낸 새 상태 — ``event`` 가 None 이면 기록할 변화가 없다(마지막 본 날만 고친다)."""
    state: IssueState
    event: Optional[str]
    from_state: Optional[str]


def _is_day(d) -> bool:
    return type(d) is date   # 시각(datetime)은 날짜가 아니다


def _need_day(d) -> date:
    if not _is_day(d):
        raise IssueRuleError(E_BAD_INPUT)
    return d


def _need_severity(s) -> str:
    if s not in _RANK:
        raise IssueRuleError(E_BAD_INPUT)
    return s


def valid_target(target) -> bool:
    return isinstance(target, str) and _TARGET.fullmatch(target) is not None


def valid_code(code) -> bool:
    return isinstance(code, str) and _CODE.fullmatch(code) is not None


def account_target(customer_id: int) -> str:
    """계정 단위 이슈의 대상 글자 — ``checks`` 의 계정 대상과 같은 모양."""
    if isinstance(customer_id, bool) or not isinstance(customer_id, int) or not 0 < customer_id < 10 ** 15:
        raise IssueRuleError(E_BAD_INPUT)
    return f"acc:{customer_id}"


def check_state(cur: IssueState) -> IssueState:
    """저장소가 읽은 줄이 규칙에 맞는 모양인지 — 아니면 ``IssueRuleError(bad-input)``(망가진 줄로 규칙을 돌리지 않게)."""
    if not isinstance(cur, IssueState) or cur.state not in STATES or cur.severity not in _RANK:
        raise IssueRuleError(E_BAD_INPUT)
    if not _is_day(cur.first_seen_on) or not _is_day(cur.last_seen_on) or cur.first_seen_on > cur.last_seen_on:
        raise IssueRuleError(E_BAD_INPUT)
    if isinstance(cur.reappear_count, bool) or not isinstance(cur.reappear_count, int) or cur.reappear_count < 0:
        raise IssueRuleError(E_BAD_INPUT)
    if cur.state == ST_EXCEPTION:
        if not _is_day(cur.exception_until) or cur.exception_severity not in _RANK:
            raise IssueRuleError(E_BAD_INPUT)
    elif cur.exception_until is not None or cur.exception_severity is not None:
        raise IssueRuleError(E_BAD_INPUT)
    return cur


def effective_state(cur: IssueState, today: date) -> str:
    """세는 상태 — 기간이 끝난 예외는 🆕(``verdict._effective_state`` 와 같은 규칙)."""
    check_state(cur)
    _need_day(today)
    if cur.state == ST_EXCEPTION and cur.exception_until < today:
        return ST_NEW
    return cur.state


def _clear_exception(s: IssueState) -> IssueState:
    return replace(s, exception_until=None, exception_severity=None)


def open_new(severity: str, today: date) -> Change:
    _need_severity(severity)
    _need_day(today)
    return Change(IssueState(ST_NEW, severity, today, today, 0), EV_OPENED, None)


def observe(cur: Optional[IssueState], severity: str, today: date) -> Change:
    """오늘 점검이 이 이슈의 조건을 (다시) 봤다."""
    _need_severity(severity)
    _need_day(today)
    if cur is None:
        return open_new(severity, today)
    check_state(cur)
    if today < cur.last_seen_on:
        raise IssueRuleError(E_BAD_INPUT)   # 날짜가 뒤로 가지 않는다(시계를 뒤로 고친 날 · 늦게 도착한 옛 결과)
    seen = replace(cur, last_seen_on=today, severity=severity)
    up, down = _RANK[severity] > _RANK[cur.severity], _RANK[severity] < _RANK[cur.severity]
    if cur.state in CLOSED_STATES:
        return Change(replace(_clear_exception(seen), state=ST_NEW, reappear_count=cur.reappear_count + 1),
                      EV_REAPPEARED, cur.state)
    if cur.state == ST_EXCEPTION:
        if cur.exception_until < today:
            return Change(replace(_clear_exception(seen), state=ST_NEW), EV_EXCEPTION_ENDED, cur.state)
        if _RANK[severity] > _RANK[cur.exception_severity]:
            return Change(replace(_clear_exception(seen), state=ST_NEW), EV_ESCALATED, cur.state)
        return Change(seen, EV_ESCALATED if up else EV_DEESCALATED if down else None, cur.state)
    if up:
        return Change(replace(seen, state=ST_NEW), EV_ESCALATED, cur.state)   # 🟡 로 봐 둔 것이 🔴 가 됨 — 다시 새로
    return Change(seen, EV_DEESCALATED if down else None, cur.state)


def should_auto_resolve(rule: str, code: str, target: str, *, rules_run: Iterable[str],
                        found: Iterable[Tuple[str, str]], data_late: bool) -> bool:
    """이 이슈를 🔁 저절로 풀어도 되는가 — 그 규칙이 오늘 온전한 자료로 돌았고 · 오늘 발견에 없고 · 자료 늦음이 아닐 때만.

    ``found`` = 오늘 발견의 (항목, 대상) 모음 · ``data_late`` 는 참·거짓만(모르면 늦은 것으로 넘긴다)."""
    if type(data_late) is not bool:
        raise IssueRuleError(E_BAD_INPUT)
    if data_late:
        return False
    ran = set(rules_run)
    return rule in ran and (code, target) not in set(found)


def auto_resolve(cur: IssueState, today: date) -> Optional[Change]:
    """조건이 사라졌다(``should_auto_resolve`` 가 참일 때만 부른다) — 열린 것만 🔁. 닫힌 것은 그대로(None)."""
    check_state(cur)
    _need_day(today)
    if cur.state not in OPEN_STATES:
        return None
    return Change(replace(_clear_exception(cur), state=ST_AUTO_RESOLVED), EV_AUTO_RESOLVED, cur.state)


def close_unlinked(cur: IssueState, today: date) -> Optional[Change]:
    """짝이 거절·무효가 됨(M5) — 열린 것만 「연결 해제로 닫힘」. 닫힌 것은 그대로(None)."""
    check_state(cur)
    _need_day(today)
    if cur.state not in OPEN_STATES:
        return None
    return Change(replace(_clear_exception(cur), state=ST_UNLINKED), EV_UNLINKED, cur.state)


# ── 사람의 손길(S11 화면 API 가 scope 로 누가 누를 수 있는지 판정한 뒤 부른다) ─────────────
def ack(cur: IssueState, today: date) -> Change:
    """👀 확인 중 — 🆕 에서만(기간이 끝난 예외도 🆕 로 친다)."""
    if effective_state(cur, today) != ST_NEW:
        raise IssueRuleError(E_NOT_NEW)
    return Change(replace(_clear_exception(cur), state=ST_ACK), EV_ACKED, cur.state)


def resolve(cur: IssueState, today: date) -> Change:
    """✅ 해결 — 열린 것에서만. 다음 점검에서 그대로면 다시 🆕(``observe``)."""
    check_state(cur)
    _need_day(today)
    if cur.state not in OPEN_STATES:
        raise IssueRuleError(E_NOT_OPEN)
    return Change(replace(_clear_exception(cur), state=ST_RESOLVED), EV_RESOLVED, cur.state)


def clean_note(note) -> str:
    """예외 사유 — 빈 글자 금지 · ``NOTE_MAX`` 자 이하 · 줄바꿈 등 제어 문자 금지."""
    if not isinstance(note, str):
        raise IssueRuleError(E_NOTE)
    s = note.strip()
    if not s:
        raise IssueRuleError(E_NOTE)
    if len(s) > NOTE_MAX or any(ord(ch) < 32 or ord(ch) == 127 for ch in s):
        raise IssueRuleError(E_BAD_INPUT)
    return s


def grant_exception(cur: IssueState, until: date, actor: str, today: date, note: str) -> Change:
    """🙈 예외 — 열린 것에서만 · 예외 중이면 거절(끝난 뒤에만 다시) · 등급별 한도(M7)."""
    check_state(cur)
    _need_day(today)
    _need_day(until)
    if actor not in _ACTORS:
        raise IssueRuleError(E_BAD_INPUT)
    clean_note(note)
    eff = effective_state(cur, today)
    if eff not in OPEN_STATES:
        raise IssueRuleError(E_NOT_OPEN)
    if eff == ST_EXCEPTION:
        raise IssueRuleError(E_ALREADY)
    need = EXCEPTION_MIN_ACTOR[cur.severity]
    if _ACTORS.index(actor) < _ACTORS.index(need):
        raise IssueRuleError(E_ACTOR)
    if until < today:
        raise IssueRuleError(E_PAST)
    if (until - today).days + 1 > EXCEPTION_MAX_DAYS[cur.severity]:
        raise IssueRuleError(E_TOO_LONG)
    return Change(replace(cur, state=ST_EXCEPTION, exception_until=until, exception_severity=cur.severity),
                  EV_EXCEPTED, cur.state)


def max_exception_until(severity: str, today: date) -> date:
    """그 등급에 줄 수 있는 가장 늦은 예외 끝날(오늘 포함 한도) — 화면이 달력 끝을 정할 때."""
    _need_severity(severity)
    _need_day(today)
    return today + timedelta(days=EXCEPTION_MAX_DAYS[severity] - 1)


__all__ = ("IssueState", "Change", "IssueRuleError", "observe", "open_new", "should_auto_resolve", "auto_resolve",
           "close_unlinked", "ack", "resolve", "grant_exception", "effective_state", "check_state", "clean_note",
           "account_target", "valid_target", "valid_code", "max_exception_until")
