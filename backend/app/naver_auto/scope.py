"""보는 범위 판정 — /naver/ 의 **한 곳** (설계 v1.4 §1~§8 · v1.5 확정 P1~P4).

누가 어떤 광고주를 보는지, 알림을 누가 받는지, 할 일 줄이 누구에게 가는지, 누가 승인하는지,
누가 무엇을 멈출 수 있는지를 모두 여기서 정한다. 화면 API(3차)와 엔진(2차)이 이 파일을 그대로 import 한다.

입력은 셋뿐이다.
- ``Org`` — ① 조직 스냅숏(``org_snapshot.accept_snapshot`` 으로 받은 것).
- ``Ownership`` — ③ 광고주 번호 → ① 담당 번호(메인 · 서브 · 직전 담당 · 담당 출처). 2차가 ③ ``clients.erp_possibility_id`` 로
  ① ``owners`` 줄과 이어 만든다(``ownership_for_client``).
  ③ ``clients`` 는 가망 번호 칸이 하나라 지금은 **광고주 1 = 가망 1** 이다. 설계 v1.4 §2 의 「가망 둘이면 담당 합집합 ·
  「담당 2명」 배지」는 한 광고주에 여러 가망을 잇는 연결이 ③ 에 생길 때 **이 파일에** 더한다(2차 코드에 흩어 두지 않는다).
- 보는 사람 = ① 직원 번호(idx). 대표는 ① ``is_top_manager`` 로만 안다.

⚠️ ③ 광고센터의 ``users.role`` · ``team_id`` · ``clients.owner_id`` 같은 칸은 받지도 읽지도 않는다(시험으로 고정).

⚠️ ``Scope`` 는 **요청마다** ``scope_of(org, 사람)`` 으로 새로 만든다. 다른 조직(다른 스냅숏 시각)에서 만든 Scope 나
손으로 만든 Scope 는 모든 판정 함수가 「범위 없음」으로 본다 — 캐시해 둔 옛 범위로 퇴사·강등 뒤에도 보이는 일을 막는다
(설계 v1.4 §4 「누르는 순간 다시 판정」 · §10 「옛 담당은 즉시 못 봄」). 로그인 때 ① my-profile 로 **좁히는** 것(§9)은
``profile_narrows`` · ``narrowed_scope_of`` 한 곳(S11) — 좁힌 표시는 자체 토큰에 실리고, 요청마다 좁힌 채로 다시 계산한다.

확정된 규칙:
- P1 ⓑ 서브 관리 담당도 보인다(배지 「서브」). 보기·승인·되돌리기·멈추기는 메인과 같다(자기 승인 금지도 메인과 같다).
  주의 알림·할 일 줄은 메인에게만, 긴급은 메인·서브 둘 다.
- P2 ⓐ 전체를 보는 사람은 대표(``is_top_manager``)뿐이다.
- P3 ⓐ 팀장의 비상 정지 = 본인 팀 + 하부 팀(주인 팀 기준). 회사 전체 정지는 대표만.

범위 밖과 없는 것은 **같은 예외 · 같은 문구**다(존재를 드러내지 않는다).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Union

from .org_snapshot import OWNER_SOURCE_PREV, SYSTEM_EMPLOYEE_IDX, Org, OrgPerson, OwnerRow, is_person_idx

# ── 범위 종류 ──
ALL = "ALL"      # 대표 — 전부 + 담당 미정
TEAM = "TEAM"    # 팀장(is_manager · 시스템 팀 아님) — 본인 팀 + 모든 하부 팀
MINE = "MINE"    # 그 밖의 재직자 — 본인 담당만
NONE = "NONE"    # 조직 표에 없음 · 재직 아님 · 음수 번호 · 낡은/손으로 만든 Scope — 0곳 (0번은 대표 — 사람이다)

# ── 광고주 담당 상태 ──
NORMAL = "normal"          # 메인 담당이 재직 중
PREV = "prev"              # 계약 만료(① owner_source=prev) — 직전 담당은 보기·멈추기만, 주인은 그 팀 팀장 사슬
VACANT = "vacant"          # 메인이 퇴사·정지·삭제 — 그 사람 팀의 팀장 사슬이 대신
UNASSIGNED = "unassigned"  # 빈칸 · 모르는 번호 · 이름으로만 이어짐 · 스냅숏에 없는 가망 — 대표만

# ── 광고주와 보는 사람의 관계(배지) ──
REL_MAIN = "main"
REL_SUB = "sub"
REL_PREV = "prev"
REL_TEAM = "team"
REL_ALL = "all"

# ── 할 수 있는 일 ──
ACT_VIEW = "view"
ACT_STOP = "stop"
ACT_REVERT = "revert"
ACT_APPROVE = "approve"   # 담당자 등급 승인. 팀장 등급은 can_approve()(approvers 사슬)로만 정한다.
ACT_HANDLE_ISSUE = "handle_issue"   # 관제 이슈 👀 확인 · ✅ 해결 · 🙈 예외(S11 · 예외의 층은 issue_actor 가 정한다)
ACT_CONFIRM_LINK = "confirm_link"   # 짝 확인 화면 「이 계정 맞음」 · 「아님」 · 「거두기」(S11 · 설계 v1.4 §5)
FULL_ACTIONS = frozenset({ACT_VIEW, ACT_STOP, ACT_REVERT, ACT_APPROVE, ACT_HANDLE_ISSUE, ACT_CONFIRM_LINK})
PREV_ACTIONS = frozenset({ACT_VIEW, ACT_STOP})   # 계약 만료 직전 담당 — 이슈 처리·짝 확인도 못 한다(보기·멈추기만)

# ── 알림 등급 · 승인 등급 ──
URGENT = "urgent"    # 긴급
CAUTION = "caution"  # 주의
LEVEL_STAFF = "staff"  # 담당자 등급
LEVEL_LEAD = "lead"    # 팀장 등급(상한 올리기 · 운전자 바꾸기 · 엔진에 다시 맡기기)

# ── ③ ↔ ① 연결 방법(③ clients.erp_match_method 요청 칸) ──
MATCH_PID = "pid"          # 가망 번호로 이어짐 — 이것만 믿는다
MATCH_NAME = "name"        # 이름으로만 이어짐 — 담당 미정과 같게
MATCH_UNKNOWN = "unknown"  # 모름 — 담당 미정과 같게(닫힌 쪽)
_MATCHES = frozenset({MATCH_PID, MATCH_NAME, MATCH_UNKNOWN})

# ── 고르기 글자 ──
MAX_SELECTION_DIGITS = 18  # 'person:<번호>' · 'team:<번호>' 의 번호 자릿수 상한(그 넘으면 400 — 큰 수 변환 오류로 500 이 나지 않게)

# ── 고정 문구(범위 밖 = 없음) ──
CLIENT_NOT_VISIBLE = "없거나 볼 수 없는 광고주입니다"
TARGET_NOT_VISIBLE = "없거나 볼 수 없는 범위입니다"
SELECTION_REJECTED = "고를 수 없는 보기 범위입니다"
STOP_NOT_ALLOWED = "이 범위를 한꺼번에 멈출 수 없습니다"
ACTION_NOT_ALLOWED = "이 광고주에서 할 수 없는 일입니다"


class ScopeError(Exception):
    """판정 거절의 공통 부모. 문구는 고정이다(무엇이 있는지 드러내지 않는다)."""

    message: str = ""

    def __init__(self) -> None:
        super().__init__(self.message)


class ClientNotVisible(ScopeError):
    """광고주가 없거나 범위 밖 — API 는 404. 둘을 가르지 않는다."""

    message = CLIENT_NOT_VISIBLE


class TargetNotVisible(ScopeError):
    """고른 사람·팀이 없거나 범위 밖 — API 는 404. 둘을 가르지 않는다."""

    message = TARGET_NOT_VISIBLE


class SelectionRejected(ScopeError):
    """보기 범위 글자가 틀렸거나 최대 범위보다 넓다 — API 는 400. 조용히 넓히거나 좁히지 않는다."""

    message = SELECTION_REJECTED


class StopNotAllowed(ScopeError):
    """묶음 비상 정지 권한이 없다(담당자·범위 없음)."""

    message = STOP_NOT_ALLOWED


class ActionNotAllowed(ScopeError):
    """광고주는 보이지만 그 일은 못 한다(예: 이전 담당의 되돌리기·승인). 보이는 광고주라 404 가 아니다 — 응답 코드는 3차에서 정한다."""

    message = ACTION_NOT_ALLOWED


@dataclass(frozen=True, slots=True)
class Scope:
    kind: str                   # ALL · TEAM · MINE · NONE
    viewer_idx: Optional[int]   # ① 직원 번호(NONE 이면 None)
    teams: frozenset[int]       # TEAM = 본인 팀 + 하부 팀 · ALL = 모든 팀 · 그 밖 = 빈 집합
    people: frozenset[int]      # 고를 수 있는 사람(TEAM = 범위 팀 소속 전원(퇴사자 포함) + 본인)
    generated_at: Optional[str]  # 기준 스냅숏 시각 — 판정 때 조직의 시각과 다르면 「범위 없음」
    narrowed: bool = False      # 로그인 때 ① my-profile 로 좁힌 범위(v1.4 §9 · S11) — 판정 때도 좁힌 채로 다시 계산한다


@dataclass(frozen=True, slots=True, kw_only=True)
class Ownership:
    """③ 광고주 하나의 담당(① 번호). ``match`` 는 일부러 기본값이 없다 — 연결 방법을 모르면 담당 미정이다.

    ``source`` 는 ① ``owner_source``(소문자 manage · prev · none). 계약 만료는 ① 가 ``main=None`` + ``source='prev'`` +
    ``prev=<직전 담당>`` 으로 보낸다(-1 을 보내지 않는다). ``source`` 가 ``prev`` 가 아니면 「이전 담당」으로 보지 않는다(닫힌 쪽).
    """

    client_id: int
    main: Optional[int]
    sub: Optional[int] = None
    prev: Optional[int] = None
    source: Optional[str] = None
    match: str

    def __post_init__(self) -> None:
        if not _is_int(self.client_id) or self.client_id <= 0:
            raise ValueError("client_id 는 양의 정수여야 합니다")
        for name, v in (("main", self.main), ("sub", self.sub), ("prev", self.prev)):
            if v is not None and not _is_int(v):
                raise ValueError(f"{name} 는 정수 또는 None 이어야 합니다")
        if self.source is not None and not isinstance(self.source, str):
            raise ValueError("source 는 글자 또는 None 이어야 합니다")
        if self.match not in _MATCHES:
            raise ValueError("match 는 pid · name · unknown 중 하나여야 합니다")


@dataclass(frozen=True, slots=True)
class KillSet:
    """비상 정지 집합 — GLOBAL(대표) 이면 client_ids 는 None, TEAM 이면 누르는 순간의 광고주 번호 집합."""

    kind: str  # "GLOBAL" · "TEAM"
    client_ids: Optional[frozenset[int]]
    by_idx: int


Rows = Union[Iterable[Ownership], Mapping[Any, Ownership]]


# ── 작은 도구 ──────────────────────────────────────────────────────

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _person(org: Org, idx: Any) -> Optional[OrgPerson]:
    if not is_person_idx(idx):   # 0 = 대표 계정 — 사람이다(음수만 시스템 자리)
        return None
    return org.people.get(idx)


def _iter_rows(rows: Rows) -> Iterable[Ownership]:
    return rows.values() if isinstance(rows, Mapping) else rows


def _top_managers(org: Org) -> frozenset[int]:
    """재직 중인 대표만(퇴사·정지·삭제된 대표 표시 계정은 넣지 않는다) — 정의는 ``Org.top_managers`` 한 곳."""
    return org.top_managers()


def _is_active_top(org: Org, idx: Any) -> bool:
    p = _person(org, idx)
    return p is not None and p.active and p.is_top_manager


def _can_lead(org: Org, p: Optional[OrgPerson]) -> bool:
    """팀 범위를 가질 수 있는 팀장인가(재직 · is_manager · 뿌리가 될 수 있는 팀)."""
    return p is not None and p.active and p.is_manager and org.can_root_team_scope(p.team_idx)


def _none_scope(org: Org) -> Scope:
    return Scope(NONE, None, frozenset(), frozenset(), org.generated_at)


def _live(org: Org, scope: Any) -> Scope:
    """이 조직에서 지금 다시 계산한 범위와 **똑같은** Scope 만 믿는다. 낡았거나 손으로 만든 것은 「범위 없음」.

    좁힌 범위(``narrowed``)는 ``narrowed_scope_of`` 로 다시 계산한 것과 같아야 한다 — 좁힌 표시를 떼거나(넓히기)
    손으로 붙여도 통하지 않는다."""
    if isinstance(scope, Scope) and scope.kind != NONE and _is_int(scope.viewer_idx) and type(scope.narrowed) is bool:
        again = narrowed_scope_of(org, scope.viewer_idx) if scope.narrowed else scope_of(org, scope.viewer_idx)
        if scope == again:
            return scope
    return _none_scope(org)


# ── 1. 보는 범위 ──────────────────────────────────────────────────

def scope_of(org: Org, viewer_idx: Any) -> Scope:
    """이 사람의 최대 범위. 화면에서 고르는 것은 이 안에서 좁히기만 한다."""
    p = _person(org, viewer_idx)
    if p is None or not p.active:
        return _none_scope(org)
    if p.is_top_manager:
        return Scope(ALL, p.idx, frozenset(org.teams), frozenset(org.people), org.generated_at)
    if _can_lead(org, p):
        teams = org.subtree(p.team_idx)
        people = {m for t in teams for m in org.members.get(t, ())}
        people.add(p.idx)
        return Scope(TEAM, p.idx, teams, frozenset(people), org.generated_at)
    return Scope(MINE, p.idx, frozenset(), frozenset({p.idx}), org.generated_at)


def narrowed_scope_of(org: Org, viewer_idx: Any) -> Scope:
    """로그인 때 좁힌 범위(v1.4 §9) — 팀 범위를 「본인 담당만」으로. 대표(ALL)는 좁히지 않는다(① my-profile 에는
    대표 표시가 없어 좁힐 근거가 없다) · 범위 없음은 그대로 없음. 넓히는 일은 없다."""
    s = scope_of(org, viewer_idx)
    if s.kind in (TEAM, MINE):
        return Scope(MINE, s.viewer_idx, frozenset(), frozenset({s.viewer_idx}), s.generated_at, True)
    return s


def profile_narrows(org: Org, viewer_idx: Any, profile_is_manager: Any, profile_team_idx: Any) -> bool:
    """① my-profile 이 스냅숏보다 좁은가 — 팀장이 아니라고 하거나 · 가장 깊은 팀이 스냅숏과 다르면(v1.4 §9 「즉시 좁힌다」).

    ``profile_is_manager`` 가 참거짓이 아니거나 팀 번호가 정수·None 이 아니면(모양을 모름) 좁힌다 — 닫힌 쪽.
    스냅숏이 팀 범위가 아니면(담당·대표·범위 없음) 좁힐 것이 없다."""
    s = scope_of(org, viewer_idx)
    if s.kind != TEAM:
        return False
    if type(profile_is_manager) is not bool or not (profile_team_idx is None or _is_int(profile_team_idx)):
        return True
    p = _person(org, viewer_idx)
    return (not profile_is_manager) or p is None or profile_team_idx != p.team_idx


# ── 2. 담당 상태 ──────────────────────────────────────────────────

def owner_state(org: Org, own: Ownership) -> str:
    """normal · prev · vacant · unassigned (설계 v1.4 §2 표).

    「이전 담당」 = 관리 담당이 비었거나 시스템 계정(-1)이면서 ① owner_source 가 ``prev`` 이고, 직전 담당이 직원 표에 있을 때.
    """
    if own.match != MATCH_PID:
        return UNASSIGNED
    if own.main is None or own.main == SYSTEM_EMPLOYEE_IDX:
        if own.source == OWNER_SOURCE_PREV and _person(org, own.prev) is not None:
            return PREV
        return UNASSIGNED
    p = _person(org, own.main)
    if p is None:
        return UNASSIGNED
    return NORMAL if p.active else VACANT


def owner_key(org: Org, own: Ownership) -> Optional[int]:
    """묶음·사람 고르기의 기준 사람 — 메인(재직·공백) 또는 직전 담당(이전 담당). 담당 미정이면 None."""
    st = owner_state(org, own)
    if st in (NORMAL, VACANT):
        return own.main
    if st == PREV:
        return own.prev
    return None


def _home_team(org: Org, own: Ownership) -> Optional[int]:
    """이 광고주의 주인 팀 — 기준 사람의 소속 팀. 팀장 사슬은 여기서 위로 간다."""
    key = owner_key(org, own)
    p = _person(org, key)
    return p.team_idx if p is not None else None


def _sub_person(org: Org, own: Ownership) -> Optional[OrgPerson]:
    if own.sub is None or own.sub == own.main:
        return None
    return _person(org, own.sub)


def _owners_of(org: Org, own: Ownership) -> frozenset[int]:
    """이 광고주의 담당(메인·서브 · 이전 담당이면 직전 담당·서브). 「가장 가까운 팀장」과 팀장 등급 승인에서 뺀다(P1 ⓑ — 서브도 메인과 같게)."""
    st = owner_state(org, own)
    if st == UNASSIGNED:
        return frozenset()
    out = {own.prev} if st == PREV else {own.main}
    if _sub_person(org, own) is not None:
        out.add(own.sub)
    return frozenset(x for x in out if is_person_idx(x))


def _key_is_top(org: Org, own: Ownership) -> bool:
    """기준 사람이 재직 대표인가 — 대표 위에는 팀장이 없다(설계 v1.4 §7 「위가 없음」)."""
    st = owner_state(org, own)
    return st in (NORMAL, PREV) and _is_active_top(org, owner_key(org, own))


# ── 3. 보이는가 · 관계 · 할 수 있는 일 ─────────────────────────────

def _can_see(org: Org, scope: Scope, own: Ownership) -> bool:
    if scope.kind == ALL:
        return True
    if scope.kind == NONE or scope.viewer_idx is None:
        return False
    st = owner_state(org, own)
    if st == UNASSIGNED:
        return False
    v = scope.viewer_idx
    if st == NORMAL and own.main == v:
        return True
    if st == PREV and own.prev == v:
        return True
    if _sub_person(org, own) is not None and own.sub == v:
        return True
    if scope.kind == TEAM:
        home = _home_team(org, own)
        return home is not None and home in scope.teams
    return False


def _relation(org: Org, scope: Scope, own: Ownership) -> Optional[str]:
    if not _can_see(org, scope, own):
        return None
    v = scope.viewer_idx
    st = owner_state(org, own)
    if st == NORMAL and own.main == v:
        return REL_MAIN
    if st == PREV and (own.prev == v or (_sub_person(org, own) is not None and own.sub == v)):
        return REL_PREV
    if _sub_person(org, own) is not None and own.sub == v:
        return REL_SUB
    return REL_ALL if scope.kind == ALL else REL_TEAM


def _allowed(org: Org, scope: Scope, own: Ownership) -> frozenset[str]:
    rel = _relation(org, scope, own)
    if rel is None:
        return frozenset()
    if scope.kind == ALL:
        return FULL_ACTIONS
    return PREV_ACTIONS if rel == REL_PREV else FULL_ACTIONS


def can_see(org: Org, scope: Scope, own: Ownership) -> bool:
    return _can_see(org, _live(org, scope), own)


def relation(org: Org, scope: Scope, own: Ownership) -> Optional[str]:
    """배지 — main · sub · prev · team · all. 볼 수 없으면 None.

    계약 만료(이전 담당) 광고주에서는 직전 담당과 서브 모두 「prev」(보기·멈추기만)다 — ① RefundViewScope 선례처럼 서브도 센다.
    """
    return _relation(org, _live(org, scope), own)


def allowed_actions(org: Org, scope: Scope, own: Ownership) -> frozenset[str]:
    """보기 · 멈추기 · 되돌리기 · 담당자 등급 승인. 대표는 늘 전부, 이전 담당은 보기·멈추기만."""
    return _allowed(org, _live(org, scope), own)


def issue_actor(org: Org, scope: Scope, own: Ownership) -> Optional[str]:
    """이슈 손길의 층(S11 · M7) — ``lead``(팀장 등급 승인 사슬에 든다 · 🔴 예외 가능) · ``owner``(이슈를 다룰 수 있다 ·
    🟡·ⓘ 예외까지) · None(못 다룬다). 글자는 ``issues.ACTOR_LEAD`` · ``ACTOR_OWNER`` 와 같다(시험이 대조).

    팀장 등급은 ``approvers(..., LEVEL_LEAD)`` 사슬 — 담당(메인·서브) 본인은 빠지므로 자기 광고주의 🔴 는 윗사람이 판단한다."""
    s = _live(org, scope)
    if ACT_HANDLE_ISSUE not in _allowed(org, s, own):
        return None
    if can_approve(org, own, LEVEL_LEAD, None, s.viewer_idx):
        return "lead"
    return "owner"


def require_client(org: Org, scope: Scope, rows_by_id: Mapping[int, Ownership], client_id: Any,
                   action: str) -> Ownership:
    """단건·쓰기용 — ``action``(view · stop · revert · approve)까지 한 번에 판정한다.

    - 없는 번호와 범위 밖 번호는 **같은 예외 · 같은 문구**(ClientNotVisible · 404).
    - 보이지만 그 일은 못 하면 ActionNotAllowed(예: 이전 담당의 되돌리기).
    - approve 는 **담당자 등급**이다. 팀장 등급 승인은 ``can_approve`` 로 판정한다.
    - 설계 v1.4 §4 의 ``ClientHandle``(네이버 어댑터가 받는 손잡이)은 3차에서 이 결과로 만든다.
    """
    if action not in FULL_ACTIONS:
        raise ValueError("action 은 view · stop · revert · approve · handle_issue · confirm_link 중 하나여야 합니다")
    s = _live(org, scope)
    own = rows_by_id.get(client_id) if _is_int(client_id) else None
    if own is None or own.client_id != client_id or not _can_see(org, s, own):
        raise ClientNotVisible()
    if action not in _allowed(org, s, own):
        raise ActionNotAllowed()
    return own


# ── 4. 목록 — 최대 범위 안에서 좁히기만 ───────────────────────────

def parse_selection(selection: Any) -> tuple:
    """'all' · 'me' · 'unassigned' · 'person:<idx>' · 'team:<idx>'. 그 밖은 SelectionRejected."""
    if not isinstance(selection, str):
        raise SelectionRejected()
    if selection in ("all", "me", "unassigned"):
        return (selection,)
    head, sep, tail = selection.partition(":")
    if (sep and head in ("person", "team") and tail.isascii() and tail.isdigit()
            and len(tail) <= MAX_SELECTION_DIGITS):
        return (head, int(tail))
    raise SelectionRejected()


def clients_in(org: Org, scope: Scope, rows: Rows, selection: Any = "all") -> frozenset[int]:
    """목록·집계용 광고주 번호 집합. 결과는 언제나 ``clients_in(..., 'all')`` 의 부분집합이다.

    - 최대 범위보다 넓은 요청(대표가 아닌데 「담당 미정」)·틀린 글자 → SelectionRejected(400).
    - 범위 밖이거나 없는 사람·팀 → TargetNotVisible(404) — 둘을 가르지 않는다.
    """
    s = _live(org, scope)
    sel = parse_selection(selection)
    kind = sel[0]
    if kind == "unassigned" and s.kind != ALL:
        raise SelectionRejected()
    if kind == "person" and not _person_selectable(org, s, sel[1]):
        raise TargetNotVisible()
    if kind == "team" and not _team_selectable(org, s, sel[1]):
        raise TargetNotVisible()

    visible = [o for o in _iter_rows(rows) if _can_see(org, s, o)]
    if kind == "all":
        return frozenset(o.client_id for o in visible)
    if kind == "me":
        return frozenset(o.client_id for o in visible
                         if _relation(org, s, o) in (REL_MAIN, REL_SUB, REL_PREV))
    if kind == "unassigned":
        return frozenset(o.client_id for o in visible if owner_state(org, o) == UNASSIGNED)
    if kind == "person":
        return frozenset(o.client_id for o in visible if owner_key(org, o) == sel[1])
    # team
    under = org.subtree(sel[1])
    return frozenset(o.client_id for o in visible if _home_team(org, o) in under)


def _person_selectable(org: Org, scope: Scope, idx: int) -> bool:
    if scope.kind == ALL:
        return idx in org.people
    if scope.kind in (TEAM, MINE):
        return idx in scope.people
    return False


def _team_selectable(org: Org, scope: Scope, team_idx: int) -> bool:
    if scope.kind == ALL:
        return team_idx in org.teams and not org.is_system_team(team_idx)
    if scope.kind == TEAM:
        return team_idx in scope.teams
    return False


# ── 5. 팀장 사슬 ──────────────────────────────────────────────────

def _lead_tiers(org: Org, start_team: Optional[int], exclude: frozenset[int]) -> list[frozenset[int]]:
    """주인 팀에서 위로 가며 만나는 팀장 묶음들(가까운 순). 그 팀장이 실제로 이 팀을 볼 수 있을 때만 넣는다."""
    tiers: list[frozenset[int]] = []
    seen: set[int] = set()
    t = start_team
    while t is not None and t > 0 and t in org.teams and t not in seen:
        seen.add(t)
        if org.can_root_team_scope(t) and start_team in org.subtree(t):
            leads = frozenset(
                m for m in org.members.get(t, ())
                if m not in exclude and _can_lead(org, org.people.get(m)))
            if leads:
                tiers.append(leads)
        t = org.parent_of(t)
    return tiers


def _owner_lead_tiers(org: Org, own: Ownership, exclude: frozenset[int]) -> list[frozenset[int]]:
    """담당 기준 팀장 사슬 — 기준 사람이 대표면 위가 없으므로 빈 사슬."""
    if _key_is_top(org, own):
        return []
    return _lead_tiers(org, _home_team(org, own), exclude)


def _nearest_leads(org: Org, own: Ownership) -> frozenset[int]:
    """가장 가까운 팀장 묶음(담당 본인 · 서브 제외). 같은 팀 팀장이 둘이면 둘 다."""
    tiers = _owner_lead_tiers(org, own, _owners_of(org, own))
    return tiers[0] if tiers else frozenset()


def _dedupe(tiers: Iterable[frozenset[int]]) -> tuple[frozenset[int], ...]:
    out: list[frozenset[int]] = []
    used: set[int] = set()
    for tier in tiers:
        t = frozenset(x for x in tier if x not in used)
        if t:
            out.append(t)
            used |= t
    return tuple(out)


# ── 6. 알림 받는 사람 ─────────────────────────────────────────────

def alert_recipients(org: Org, own: Ownership, level: str) -> frozenset[int]:
    """받는 사람(① 번호). 불변식: 받는 사람 ⊆ 그 광고주를 여는 사람.

    - 긴급 = 메인(·서브) + 가장 가까운 팀장(담당·서브 본인 제외 · 대표 담당이면 없음) + 대표
    - 주의 = 메인만(팀장은 ``digest_recipients`` 로 하루 요약)
    - 담당 공백·이전 담당 → 주의는 주인 팀의 가장 가까운 팀장(없으면 대표) · 긴급은 거기에 서브(·직전 담당)와 대표
    - 담당 미정 → 대표만
    """
    if level not in (URGENT, CAUTION):
        raise ValueError("level 은 urgent · caution 중 하나여야 합니다")
    ceos = _top_managers(org)
    st = owner_state(org, own)
    if st == UNASSIGNED:
        return ceos

    sub = _sub_person(org, own)
    subs = frozenset({sub.idx}) if sub is not None and sub.active else frozenset()
    nearest = _nearest_leads(org, own)

    if st == NORMAL:
        if level == CAUTION:
            return frozenset({own.main})
        return frozenset({own.main}) | subs | nearest | ceos

    if st == VACANT:
        if level == CAUTION:
            return nearest or ceos
        return nearest | subs | ceos

    # PREV — 주인은 직전 담당 팀의 팀장 사슬 · 직전 담당·서브는 멈출 수 있게 긴급만
    prev = _person(org, own.prev)
    if level == CAUTION:
        return nearest or ceos
    prevs = frozenset({prev.idx}) if prev is not None and prev.active else frozenset()
    return prevs | subs | nearest | ceos


def digest_recipients(org: Org, own: Ownership) -> frozenset[int]:
    """주의 알림의 팀장 하루 요약 받는 사람 — 정상 담당일 때 가장 가까운 팀장(메인·서브 본인 제외 · 대표 담당이면 없음)."""
    if owner_state(org, own) != NORMAL:
        return frozenset()
    return _nearest_leads(org, own)


# ── 7. 승인 사슬 · 할 일 줄 ────────────────────────────────────────

def _check_level_and_requester(level: str, requester_idx: Any) -> None:
    if level not in (LEVEL_STAFF, LEVEL_LEAD):
        raise ValueError("level 은 staff · lead 중 하나여야 합니다")
    if requester_idx is not None and not _is_int(requester_idx):
        # '111'(토큰 sub 글자) · 111.0 · True 를 그냥 두면 자기 승인 금지가 빠진다 — 닫힌 쪽으로 멈춘다.
        raise ValueError("requester_idx 는 ① 직원 번호(정수) 또는 None 이어야 합니다")


def approvers(org: Org, own: Ownership, level: str, requester_idx: Any = None) -> tuple[frozenset[int], ...]:
    """승인할 수 있는 사람들 — 가까운 순 묶음(tier). 받을 사람은 저장하지 않고 누를 때마다 계산한다.

    - 담당자 등급: [메인·서브] → 팀장 사슬(가까운 순) → 대표. 누구나 누를 수 있다.
      (할 일 줄은 여기 첫 묶음이 아니라 ``todo_chain`` 이 정한다 — P1 ⓑ 로 서브에게는 가지 않는다.)
    - 팀장 등급: 팀장 사슬(요청자·담당(메인·서브·직전) 제외) → 대표(요청자·담당 제외).
      자기 승인 금지 — 팀장이 자기 광고주에 올린 팀장 등급 일은 윗사람에게 간다.
      요청자나 기준 담당이 대표면 위가 없으므로 대표 묶음만. 대표가 비켜 줄 대표가 없으면 대표 본인이 승인한다
      (호출하는 쪽이 기록해 하루 요약에 올린다). 대표가 둘 이상이면 요청자 본인은 끝까지 빠진다.
    - 이전 담당(계약 만료) 광고주: 직전 담당·서브는 승인하지 못한다(보기·멈추기만).
    불변식: 모든 승인자 ⊆ 그 광고주를 여는 사람 · 담당자 등급 승인자 = ``allowed_actions`` 에 approve 가 있는 재직자.
    """
    _check_level_and_requester(level, requester_idx)
    st = owner_state(org, own)
    ceos = _top_managers(org)
    home = _home_team(org, own)

    tiers: list[frozenset[int]] = []
    if level == LEVEL_STAFF:
        sub = _sub_person(org, own)
        sub_idx = sub.idx if sub is not None and sub.active else None
        owners_out = _owners_of(org, own) if st == PREV else frozenset()
        if st in (NORMAL, VACANT):
            first = frozenset(x for x in ((own.main if st == NORMAL else None), sub_idx) if x is not None)
            if first:
                tiers.append(first)
        if st != UNASSIGNED:
            tiers.extend(_lead_tiers(org, home, owners_out))
        tiers.append(ceos)
    else:
        excl = set(_owners_of(org, own))
        if requester_idx is not None:
            excl.add(requester_idx)
        top_involved = _is_active_top(org, requester_idx) or _key_is_top(org, own)
        if st != UNASSIGNED and not top_involved:
            tiers.extend(_lead_tiers(org, home, frozenset(excl)))
        top = ceos - frozenset(excl)
        if not top:
            top = (ceos - {requester_idx}) or ceos
        tiers.append(top)
    return _dedupe(tiers)


def can_approve(org: Org, own: Ownership, level: str, requester_idx: Any, approver_idx: Any) -> bool:
    """누르는 순간 다시 판정한다 — 사슬 어디에든 있으면 누를 수 있다(상위 팀장·대표는 언제든).

    번호가 정수가 아니면(글자 '111' · 111.0 · 참/거짓) 늘 거짓 — 닫힌 쪽.
    """
    if not is_person_idx(approver_idx):
        return False
    if requester_idx is not None and not _is_int(requester_idx):
        return False
    return any(approver_idx in tier for tier in approvers(org, own, level, requester_idx))


def todo_chain(org: Org, own: Ownership, level: str, requester_idx: Any = None) -> tuple[frozenset[int], ...]:
    """할 일 줄이 가는 순서 — 첫 묶음이 지금 받는 사람, 다음 묶음이 12시간 뒤 올려 받는 사람(설계 v1.4 §6·§7).

    - 담당자 등급: 정상 = [메인] → 팀장 사슬 → 대표(P1 ⓑ — 서브에게는 할 일 줄이 가지 않는다).
      담당 공백·이전 담당 = 주인 팀의 팀장 사슬 → 대표(서브·직전 담당 제외). 담당 미정 = 대표.
    - 팀장 등급: ``approvers`` 와 같은 사슬(요청자·담당 제외 · 가장 가까운 팀장부터).
    불변식: 받는 사람 ⊆ 승인할 수 있는 사람(``approvers``) ⊆ 그 광고주를 여는 사람.
    """
    _check_level_and_requester(level, requester_idx)
    if level == LEVEL_LEAD:
        return approvers(org, own, level, requester_idx)
    st = owner_state(org, own)
    ceos = _top_managers(org)
    tiers: list[frozenset[int]] = []
    if st == NORMAL:
        tiers.append(frozenset({own.main}))
    if st != UNASSIGNED:
        tiers.extend(_owner_lead_tiers(org, own, _owners_of(org, own)))
    tiers.append(ceos)
    return _dedupe(tiers)


def todo_recipients(org: Org, own: Ownership, level: str, requester_idx: Any = None) -> frozenset[int]:
    """할 일 줄을 지금 받는 사람(``todo_chain`` 의 첫 묶음). 받을 사람이 없으면 빈 집합."""
    chain = todo_chain(org, own, level, requester_idx)
    return chain[0] if chain else frozenset()


# ── 8. 비상 정지 집합 ─────────────────────────────────────────────

def kill_set(org: Org, scope: Scope, rows: Rows) -> KillSet:
    """묶음 비상 정지(P3 ⓐ). 대표 = 회사 전체 · 팀장 = **주인 팀이 본인 팀·하부 팀 안인** 광고주 집합(화면에서 좁힌 보기와 무관).

    팀장이 다른 팀 광고주의 서브로만 보이는 곳은 넣지 않는다(그 팀의 정지가 아니다 — 한 곳씩 멈추기로).
    담당자·범위 없음은 묶음 정지를 못 한다(광고주 한 곳 멈추기는 ``allowed_actions`` 의 stop).
    """
    s = _live(org, scope)
    if s.kind == ALL:
        return KillSet("GLOBAL", None, s.viewer_idx)
    if s.kind == TEAM:
        ids = frozenset(o.client_id for o in _iter_rows(rows)
                        if _can_see(org, s, o) and _home_team(org, o) in s.teams)
        return KillSet("TEAM", ids, s.viewer_idx)
    raise StopNotAllowed()


# ── ① 담당 줄 → ③ 광고주 담당 ────────────────────────────────────

def ownership_from_owner_row(client_id: int, row: OwnerRow, match: str) -> Ownership:
    """① owners 한 줄을 ③ 광고주 하나의 담당으로. ``match`` 는 ③ 가 그 광고주를 어떻게 이었는지(pid 만 믿는다)."""
    return Ownership(client_id=client_id, main=row.manage_emp_idx, sub=row.sub_manage_emp_idx,
                     prev=row.prev_manage_owner_idx, source=row.owner_source, match=match)


def ownership_for_client(org: Org, client_id: int, possibility_id: Any, match: str) -> Ownership:
    """③ 광고주 하나(가망 번호 칸 하나)의 담당. 가망 번호가 없거나 스냅숏에 없으면(① 숨김 단계 등) 담당 미정."""
    row = org.owners_by_pid.get(possibility_id) if _is_int(possibility_id) else None
    if row is None:
        return Ownership(client_id=client_id, main=None, match=match)
    return ownership_from_owner_row(client_id, row, match)


def ownership_from_mapping(client_id: int, m: Mapping[str, Any]) -> Ownership:
    """{main, sub, prev, source, match} 사전에서. ``match`` 가 없으면 unknown(담당 미정) — 닫힌 쪽."""
    return Ownership(client_id=client_id, main=m.get("main"), sub=m.get("sub"), prev=m.get("prev"),
                     source=m.get("source"), match=m.get("match", MATCH_UNKNOWN))
