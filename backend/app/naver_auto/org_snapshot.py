"""① 전산 조직 스냅숏 — 읽기 · 형식 검사 · 건전성 검사 (순수 함수).

원천: ① ``GET /api/ad-sync/org-snapshot`` (설계 v1.4 §9). 응답은 ① 공통 래핑
``{"status":200,"result":{...}}`` 이거나 ``result`` 안의 본문 그대로다. 본문 형식:

    {
      generated_at,
      teams:     [{idx, name, level, parent_idx, is_system}],
      employees: [{idx, name, team_idx, is_manager, is_top_manager, status, is_deleted}],
      owners:    [{possibility_id, manage_emp_idx, sub_manage_emp_idx,
                   prev_manage_owner_idx, sales_emp_idx, owner_source}]
    }

① 코드에서 확인한 뜻(2026-09-28 · metainc-web-backend):
- 직원 상태 ``EmployeeStatus`` = ``ACTIVE``(재직) · ``RESIGNED``(퇴사) · ``SUSPENDED``(정지).
  ① ``Employee.isActive()`` 는 ``status == ACTIVE`` 만 본다. 완전 삭제(``resign()``)는 ``isDeleted = true`` 도 켠다.
  → 여기서 **재직 = status 가 ACTIVE 이고 is_deleted 가 거짓**이다. 모르는 상태 글자는 재직이 아닌 것으로 본다(닫힌 쪽).
- ``status`` 는 **null 일 수 있다**(① 계약 §9.3 「비었으면 null — 재직으로 보지 않는다」 · ① ``employee.status`` 칸이 nullable).
  null 은 형식 오류가 아니라 「재직 아님」이다(경고 UNKNOWN_STATUS 만 붙인다 — 한 명 때문에 스냅숏 전체를 버리지 않는다).
- ``is_manager`` · ``is_top_manager`` · ``is_deleted`` 는 ① 가 ``Boolean.TRUE.equals`` 로 내보내 null 이 오지 않는다 → 참/거짓이 아니면 형식 오류.
- ⚠️ **대표 계정은 직원 번호 0 이다**(① 전산 최초 계정 · 운영 읽기 전용 실측 2026-09-28 — 대표 표시·ACTIVE·팀 0).
  그래서 여기서 「사람 번호」는 **0 이상**이다(``is_person_idx`` 한 곳). 음수(-1 등)만 시스템 자리다.
  ⚠️ 0 을 빈 값처럼 다루지 말 것 — ``if not idx`` · ``idx or 기본값`` 은 대표를 지운다.
- ``owners`` 의 사람 번호 칸 4개는 **음수이면 null** 이다 — ① 는 ``-1`` 을 보내지 않는다(계약 §9.3). **0 은 대표 번호라 그대로 온다.**
  계약 만료(관리 담당이 시스템 계정 -1)는 ``manage_emp_idx = null`` + ``owner_source = "prev"`` + ``prev_manage_owner_idx`` 로 온다.
  ``owner_source`` 값은 **소문자** ``manage`` · ``prev`` · ``none`` 셋이다(① ``AdSyncOrgSnapshotService.ownerSource``).
- ``generated_at`` 은 ``+09:00`` 이 붙은 ISO-8601 문자열이다 — 읽지 못하거나 시간대가 없으면 형식 오류.
- 팀 번호 0 은 「미분류」 시스템 팀(``TeamService`` 가 ``findByIdx(0L)`` 로 쓴다). 「퇴사자」 팀은 level 0 · parent 0
  (``SystemTeamSeeder.RESIGNED_TEAM_NAME``). 최상위 팀들의 ``parent_idx`` 는 0 이다.
- 시스템 계정(-1)은 status 가 ACTIVE 이고 **대표 표시까지 켜져 있다**(BE #736 · 실측 2026-09-28). ① 는 음수 번호 직원을 보내지 않기로 했으므로,
  들어오면 계약 위반으로 전부 버린다(받으면 「대표가 둘」이 된다).
- 재직 대표가 0명인 스냅숏은 버린다(``TOP_MANAGER_NONE``) — ① 가 0번을 빠뜨리는 회귀면 담당 미정 광고주를 아무도 못 본다.

전부 받거나 전부 버린다: 한 줄이라도 형식이 틀리거나 건전성 검사에 걸리면 이 스냅숏 전체를 버리고 이전 것을 그대로 쓴다.

⚠️ 버려진 상태가 **스스로 풀리지 않는** 경우가 있다 — 감소·권한 확대 검사는 모두 「마지막으로 받은 조직」과만 견주므로,
정상적인 큰 변화(대규모 퇴사 · 대표 계정 교체 · 시스템 팀 이름 변경 등)도 한 번 버려지면 매시간 계속 버려진다.
2차(엔진)는 이것을 대표·관리자에게 알리고, **대표가 확인하면 ``accept_snapshot(payload, prev=None)`` 으로 다시 받는** 길을 둔다
(형식 · 순환 · 빈 조직 · 대표 수 상한 검사는 그때도 그대로 돈다). 26시간이 넘으면 승인·자동 켜기는 멈춘다(fail-closed).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional

# ── ① 전산에서 가져온 상수 ────────────────────────────────────────────
ACTIVE_STATUS = "ACTIVE"
KNOWN_STATUSES = frozenset({"ACTIVE", "RESIGNED", "SUSPENDED"})
RESIGNED_TEAM_NAME = "퇴사자"  # ① SystemTeamSeeder.RESIGNED_TEAM_NAME — 바뀌면 함께 고친다.
SYSTEM_EMPLOYEE_IDX = -1        # 「담당 없음」 시스템 계정 — 사람이 아니다(① 는 보내지 않는다 · 손으로 만든 자료 방어용).
REPRESENTATIVE_EMPLOYEE_IDX = 0  # 대표 계정(① 전산 최초 계정) — 사람이다. 0 을 「없음」으로 읽으면 대표가 사라진다.
OWNER_SOURCE_MANAGE = "manage"  # ① owner_source — 관리 담당이 사람
OWNER_SOURCE_PREV = "prev"      # ① owner_source — 관리 담당이 시스템 계정(-1, 계약 만료)이고 직전 관리 담당이 있음
OWNER_SOURCE_NONE = "none"      # ① owner_source — 그 밖
KNOWN_OWNER_SOURCES = frozenset({OWNER_SOURCE_MANAGE, OWNER_SOURCE_PREV, OWNER_SOURCE_NONE})

# ── 건전성 검사 기준(설계 v1.4 §9) ──────────────────────────────────
ACTIVE_DROP_LIMIT = 0.20        # 재직 직원이 20% 넘게 줄면 버린다.
OWNER_DROP_LIMIT = 0.20         # 담당 줄 수가 20% 넘게 줄면 버린다(잘린 응답).
OWNER_BLANK_SPIKE_LIMIT = 0.10  # 담당 빈칸 비율이 10%p 넘게 늘면 버린다.
TOP_MANAGER_MAX = 2             # 재직 대표(is_top_manager)가 이보다 많으면 버린다(P2 ⓐ = 대표 한 명 · 여분 계정 하나까지).
MANAGER_SPIKE_LIMIT = 0.20      # 재직 팀장(is_manager) 수가 20% 넘게 늘고
MANAGER_SPIKE_MIN = 3           #   3명 이상 늘면 버린다(권한 확대 의심).
FUTURE_TOLERANCE = timedelta(minutes=10)  # 받는 쪽 시계보다 이만큼 넘게 앞선 스냅숏은 버린다(시계 어긋남 방어).
# 값 한도 — 엔진 저장소(naver_engine/store.py)가 받는 한도와 **같다**(검사는 받는데 저장이 거절해 매시간 멈추지 않게 · S7 적대 검토).
TEXT_MAX = 200
TIME_TEXT_MAX = 64
INT_LIMIT = 2 ** 63

# 신선도(설계 §9 · M12) — 「담당 정보 HH:MM 기준」 띠. 3시간 넘으면 노랑 · 26시간 넘으면 승인·자동 켜기·운영 방식 올리기를
# 멈추고 멈추기·내리기만 허용한다(fail-closed). 경계는 「넘으면」이다(딱 3시간은 아직 맑음 · 딱 26시간은 아직 노랑).
ORG_YELLOW_AFTER = timedelta(hours=3)
ORG_STALE_AFTER = timedelta(hours=26)
FRESH_NONE = "none"      # 받은 조직이 아직 없다
FRESH_OK = "fresh"
FRESH_YELLOW = "yellow"
FRESH_STALE = "stale"


def is_person_idx(v: Any) -> bool:
    """사람 번호인가 — 정수(참/거짓 아님)이고 0(대표) 이상. 음수는 시스템 자리다. 이 규칙은 이 한 곳에서만 정한다."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= REPRESENTATIVE_EMPLOYEE_IDX


class SnapshotFormatError(ValueError):
    """스냅숏 형식이 계약과 다르다 — 이 스냅숏 전체를 버린다."""


@dataclass(frozen=True, slots=True)
class OrgTeam:
    idx: int
    name: str
    level: int
    parent_idx: Optional[int]
    is_system: bool


@dataclass(frozen=True, slots=True)
class OrgPerson:
    idx: int
    name: str
    team_idx: Optional[int]
    is_manager: bool
    is_top_manager: bool
    status: Optional[str]   # ① null 이면 None — 재직이 아니다
    is_deleted: bool

    @property
    def active(self) -> bool:
        """재직 = ACTIVE 이고 삭제되지 않음. 정지·퇴사·빈칸(null)·모르는 상태는 재직이 아니다."""
        return self.status == ACTIVE_STATUS and not self.is_deleted


@dataclass(frozen=True, slots=True)
class OwnerRow:
    possibility_id: int
    manage_emp_idx: Optional[int]
    sub_manage_emp_idx: Optional[int]
    prev_manage_owner_idx: Optional[int]
    sales_emp_idx: Optional[int]  # 권한에 쓰지 않는다(v1.4 §2) — 표시·대조용으로만 보관
    owner_source: Optional[str]   # ① 소문자 manage · prev · none — 「이전 담당」 판정에 쓴다(scope.owner_state)


@dataclass(frozen=True, eq=False)
class Org:
    """한 시각의 조직 — 만든 뒤 바뀌지 않는다(사전은 읽기 전용 보기)."""

    generated_at: str                        # ① 원문 그대로(표시·Scope 비교용)
    generated_dt: datetime                   # 읽은 시각(시간대 있음) — 새 스냅숏이 더 새것인지 견준다
    teams: Mapping[int, OrgTeam]
    people: Mapping[int, OrgPerson]
    owners: tuple[OwnerRow, ...]
    owners_by_pid: Mapping[int, OwnerRow]
    children: Mapping[int, tuple[int, ...]]  # 부모 팀(>0) → 자식 팀들. 부모 0 은 일부러 담지 않는다(0 에서 전사로 퍼지지 않게).
    members: Mapping[int, tuple[int, ...]]   # 팀 → 소속 직원(퇴사자 포함)
    cyclic_teams: frozenset[int]             # 부모를 따라가면 제자리로 돌아오는 팀
    orphan_teams: frozenset[int]             # 부모 번호(>0)가 팀 표에 없는 팀

    # ── 팀 판정 ──
    def is_system_team(self, team_idx: Optional[int]) -> bool:
        """시스템 팀 = 번호 ≤0 · ① is_system · 이름 「퇴사자」 · 표에 없는 번호(모르면 닫힌 쪽)."""
        if team_idx is None or team_idx <= 0:
            return True
        t = self.teams.get(team_idx)
        if t is None:
            return True
        return t.is_system or t.name == RESIGNED_TEAM_NAME

    def is_broken_team(self, team_idx: Optional[int]) -> bool:
        """순환에 들었거나 부모가 사라진 팀(설계 v1.4 §3 — 그 팀장은 본인 범위로 떨어진다)."""
        return team_idx in self.cyclic_teams or team_idx in self.orphan_teams

    def can_root_team_scope(self, team_idx: Optional[int]) -> bool:
        """팀 범위의 뿌리가 될 수 있는가 — 시스템 팀·고장 난 팀은 절대 안 된다."""
        return (team_idx is not None and team_idx > 0 and team_idx in self.teams
                and not self.is_system_team(team_idx) and not self.is_broken_team(team_idx))

    def parent_of(self, team_idx: Optional[int]) -> Optional[int]:
        t = self.teams.get(team_idx) if team_idx is not None else None
        if t is None or t.parent_idx is None or t.parent_idx <= 0:
            return None
        return t.parent_idx

    def subtree(self, team_idx: int) -> frozenset[int]:
        """이 팀 + 모든 하부 팀(① findAllSubTeams 와 같은 하향). 시스템 팀으로는 내려가지 않는다 · 순환 방지."""
        if team_idx is None or team_idx <= 0 or team_idx not in self.teams or self.is_system_team(team_idx):
            return frozenset()
        seen: set[int] = set()
        stack = [team_idx]
        while stack:
            t = stack.pop()
            if t in seen:
                continue
            seen.add(t)
            for c in self.children.get(t, ()):
                if c not in seen and c in self.teams and not self.is_system_team(c):
                    stack.append(c)
        return frozenset(seen)

    # ── 수 ──
    def active_count(self) -> int:
        return sum(1 for p in self.people.values() if p.active)

    def blank_owner_ratio(self) -> float:
        """담당 빈칸 비율 — 계약 만료(owner_source=prev · 직전 담당 있음)는 빈칸이 아니다(주인이 팀장 사슬로 정해진다)."""
        if not self.owners:
            return 0.0
        blank = sum(1 for o in self.owners if _is_blank_owner(o))
        return blank / len(self.owners)

    def top_managers(self) -> frozenset[int]:
        """재직 중인 대표(is_top_manager). 퇴사·정지·삭제된 대표 표시 계정은 넣지 않는다."""
        return frozenset(p.idx for p in self.people.values() if p.active and p.is_top_manager)

    def active_manager_count(self) -> int:
        return sum(1 for p in self.people.values() if p.active and p.is_manager)


def _is_blank_owner(o: OwnerRow) -> bool:
    if is_person_idx(o.manage_emp_idx):
        return False
    return not (o.owner_source == OWNER_SOURCE_PREV and is_person_idx(o.prev_manage_owner_idx))


@dataclass(frozen=True, slots=True)
class Finding:
    code: str      # 고정 코드(시험·알림용) — FORMAT · EMPTY · CYCLE · PARENT_LOST · ACTIVE_DROP · OWNER_DROP · OWNER_BLANK_SPIKE
                   #   · STALE · FUTURE · TOP_MANAGER_NONE · TOP_MANAGER_LIMIT · TOP_MANAGER_ADDED · SYSTEM_TEAM_LOST · MANAGER_SPIKE · 경고 코드
    message: str   # 사람이 읽는 한 줄(번호·숫자만 · 이름 없음)


@dataclass(frozen=True, slots=True)
class SnapshotCheck:
    ok: bool
    reasons: tuple[Finding, ...]   # 버린 이유(하나라도 있으면 ok=False)
    warnings: tuple[Finding, ...]  # 받되 알릴 것


@dataclass(frozen=True, slots=True)
class SnapshotDecision:
    """받을지 판정한 결과 — ``org`` 는 받았으면 새 조직, 버렸으면 이전 조직(그대로 · 없으면 None)."""

    ok: bool
    org: Optional[Org]
    check: SnapshotCheck

    @property
    def reasons(self) -> tuple[Finding, ...]:
        return self.check.reasons


# ── 형식 읽기 ─────────────────────────────────────────────────────

def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _int(row: Mapping, key: str, where: str, *, nullable: bool) -> Optional[int]:
    if key not in row:
        raise SnapshotFormatError(f"{where}: '{key}' 칸이 없습니다")
    v = row[key]
    if v is None:
        if nullable:
            return None
        raise SnapshotFormatError(f"{where}: '{key}' 가 비어 있습니다")
    if not _is_int(v):
        raise SnapshotFormatError(f"{where}: '{key}' 는 정수여야 합니다")
    if not -INT_LIMIT <= v < INT_LIMIT:
        raise SnapshotFormatError(f"{where}: '{key}' 정수가 너무 큽니다")
    return v


def _bool(row: Mapping, key: str, where: str) -> bool:
    if key not in row:
        raise SnapshotFormatError(f"{where}: '{key}' 칸이 없습니다")
    v = row[key]
    if not isinstance(v, bool):
        raise SnapshotFormatError(f"{where}: '{key}' 는 참/거짓이어야 합니다")
    return v


def _str(row: Mapping, key: str, where: str, *, nullable: bool) -> Optional[str]:
    if key not in row:
        raise SnapshotFormatError(f"{where}: '{key}' 칸이 없습니다")
    v = row[key]
    if v is None:
        if nullable:
            return None
        raise SnapshotFormatError(f"{where}: '{key}' 가 비어 있습니다")
    if not isinstance(v, str):
        raise SnapshotFormatError(f"{where}: '{key}' 는 글자여야 합니다")
    if len(v) > TEXT_MAX or "\x00" in v or not _encodable(v):
        raise SnapshotFormatError(f"{where}: '{key}' 글자가 너무 길거나 쓸 수 없는 글자가 있습니다")
    return v


def _encodable(v: str) -> bool:
    """UTF-8 로 쓸 수 있는가 — 짝 없는 대리 문자(JSON 의 \\ud83d 같은 것)는 저장·전송에서 터진다."""
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _rows(body: Mapping, key: str) -> list:
    v = body.get(key)
    if not isinstance(v, list):
        raise SnapshotFormatError(f"'{key}' 목록이 없습니다")
    for i, r in enumerate(v):
        if not isinstance(r, Mapping):
            raise SnapshotFormatError(f"{key}[{i}]: 줄 형식이 아닙니다")
    return v


def unwrap(payload: Any) -> Mapping:
    """① 공통 래핑 ``{"status":..,"result":{...}}`` 을 벗긴다. 본문 그대로여도 받는다.

    ``status`` 칸이 있으면 정확히 200 이어야 한다(500 · "200" · 참/거짓은 형식 오류)."""
    if not isinstance(payload, Mapping):
        raise SnapshotFormatError("응답 본문이 객체가 아닙니다")
    if "status" in payload:
        st = payload["status"]
        if not (_is_int(st) and st == 200):
            raise SnapshotFormatError("응답 status 가 200 이 아닙니다")
    if "teams" not in payload and isinstance(payload.get("result"), Mapping):
        return payload["result"]
    return payload


def _parse_time(v: Any) -> datetime:
    """ISO-8601 · 시간대 필수. ① 는 ``2026-09-28T14:00:00+09:00`` 모양으로 보낸다."""
    if not isinstance(v, str) or not v.strip():
        raise SnapshotFormatError("'generated_at' 이 없습니다")
    if len(v) > TIME_TEXT_MAX or v != v.strip():
        raise SnapshotFormatError("'generated_at' 모양이 아닙니다")   # 저장소와 같게 — 앞뒤 빈칸도 받지 않는다
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        raise SnapshotFormatError("'generated_at' 을 시각으로 읽을 수 없습니다") from None
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SnapshotFormatError("'generated_at' 에 시간대가 없습니다")
    try:
        dt.astimezone(timezone.utc)   # 서기 1년 +10:00 같은 값은 한국 시각으로 못 바꾼다
        dt.astimezone(timezone(timedelta(hours=9)))
    except OverflowError:
        raise SnapshotFormatError("'generated_at' 을 시각으로 읽을 수 없습니다") from None
    return dt


def _find_cycles(teams: Mapping[int, OrgTeam]) -> frozenset[int]:
    """부모 사슬이 제자리로 돌아오는 팀들(순환 고리 위의 팀만)."""
    done: set[int] = set()
    cyclic: set[int] = set()
    for start in teams:
        path: list[int] = []
        pos: dict[int, int] = {}
        t: Optional[int] = start
        while t is not None and t > 0 and t in teams and t not in done:
            if t in pos:
                cyclic.update(path[pos[t]:])
                break
            pos[t] = len(path)
            path.append(t)
            t = teams[t].parent_idx
        done.update(path)
    return frozenset(cyclic)


def parse_org_snapshot(payload: Any) -> Org:
    """응답을 읽어 바뀌지 않는 ``Org`` 를 만든다. 형식이 하나라도 틀리면 ``SnapshotFormatError`` (부분 적용 없음)."""
    body = unwrap(payload)
    generated_at = body.get("generated_at")
    generated_dt = _parse_time(generated_at)

    teams: dict[int, OrgTeam] = {}
    for i, r in enumerate(_rows(body, "teams")):
        w = f"teams[{i}]"
        idx = _int(r, "idx", w, nullable=False)
        if idx < 0:
            raise SnapshotFormatError(f"{w}: 팀 번호가 음수입니다")
        if idx in teams:
            raise SnapshotFormatError(f"{w}: 팀 번호 {idx} 가 두 번 나옵니다")
        teams[idx] = OrgTeam(
            idx=idx,
            name=_str(r, "name", w, nullable=False),
            level=_int(r, "level", w, nullable=False),
            parent_idx=_int(r, "parent_idx", w, nullable=True),
            is_system=_bool(r, "is_system", w),
        )

    people: dict[int, OrgPerson] = {}
    for i, r in enumerate(_rows(body, "employees")):
        w = f"employees[{i}]"
        idx = _int(r, "idx", w, nullable=False)
        if not is_person_idx(idx):
            # ① 는 음수 번호(시스템 계정 -1 등)를 보내지 않기로 했다. -1 은 ACTIVE 이고 대표 표시까지 켜져 있어
            # 사람으로 새면 「대표가 둘」이 된다. 0 은 대표 계정이라 받는다.
            raise SnapshotFormatError(f"{w}: 직원 번호 {idx} 는 사람이 아닙니다(음수는 받지 않음)")
        if idx in people:
            raise SnapshotFormatError(f"{w}: 직원 번호 {idx} 가 두 번 나옵니다")
        people[idx] = OrgPerson(
            idx=idx,
            name=_str(r, "name", w, nullable=True) or "",
            team_idx=_int(r, "team_idx", w, nullable=True),
            is_manager=_bool(r, "is_manager", w),
            is_top_manager=_bool(r, "is_top_manager", w),
            status=_str(r, "status", w, nullable=True),   # ① 계약: 비었으면 null(재직 아님)
            is_deleted=_bool(r, "is_deleted", w),
        )

    owners: list[OwnerRow] = []
    by_pid: dict[int, OwnerRow] = {}
    for i, r in enumerate(_rows(body, "owners")):
        w = f"owners[{i}]"
        pid = _int(r, "possibility_id", w, nullable=False)
        if pid <= 0:
            raise SnapshotFormatError(f"{w}: 가망 번호가 올바르지 않습니다")
        if pid in by_pid:
            raise SnapshotFormatError(f"{w}: 가망 번호 {pid} 가 두 번 나옵니다")
        row = OwnerRow(
            possibility_id=pid,
            manage_emp_idx=_int(r, "manage_emp_idx", w, nullable=True),
            sub_manage_emp_idx=_int(r, "sub_manage_emp_idx", w, nullable=True),
            prev_manage_owner_idx=_int(r, "prev_manage_owner_idx", w, nullable=True),
            sales_emp_idx=_int(r, "sales_emp_idx", w, nullable=True),
            owner_source=_str(r, "owner_source", w, nullable=True) if "owner_source" in r else None,
        )
        owners.append(row)
        by_pid[pid] = row

    children: dict[int, list[int]] = {}
    orphans: set[int] = set()
    for t in teams.values():
        p = t.parent_idx
        if p is None or p <= 0:
            continue
        children.setdefault(p, []).append(t.idx)
        if p not in teams:
            orphans.add(t.idx)

    members: dict[int, list[int]] = {}
    for p in people.values():
        if p.team_idx is not None:
            members.setdefault(p.team_idx, []).append(p.idx)

    return Org(
        generated_at=generated_at,
        generated_dt=generated_dt,
        teams=MappingProxyType(teams),
        people=MappingProxyType(people),
        owners=tuple(owners),
        owners_by_pid=MappingProxyType(by_pid),
        children=MappingProxyType({k: tuple(sorted(v)) for k, v in children.items()}),
        members=MappingProxyType({k: tuple(sorted(v)) for k, v in members.items()}),
        cyclic_teams=_find_cycles(teams),
        orphan_teams=frozenset(orphans),
    )


# ── 건전성 검사 ───────────────────────────────────────────────────

def check_snapshot(new: Org, prev: Optional[Org], now: Optional[datetime] = None) -> SnapshotCheck:
    """새 조직을 이전 조직과 견준다(설계 v1.4 §9 · §12-8). 이유가 하나라도 있으면 버린다.

    줄어드는 것(재직 · 담당 줄 · 부모 팀)뿐 아니라 **권한이 넓어지는 것**(대표가 늘어남 · 시스템 팀이 보통 팀이 됨 ·
    팀장이 한꺼번에 늘어남)도 버린다 — 그쪽이 광고주를 엉뚱한 사람에게 보이게 하는 방향이다.
    ``now`` 를 주면(시간대 있는 현재 시각) 그보다 10분 넘게 앞선 스냅숏도 버린다(순수 함수 — 시계는 부르는 쪽이 준다).
    """
    reasons: list[Finding] = []
    warnings: list[Finding] = []

    new_active = new.active_count()
    if new_active == 0 or not new.teams:
        reasons.append(Finding("EMPTY", f"재직 직원 {new_active}명 · 팀 {len(new.teams)}개 — 빈 조직은 받지 않습니다"))

    if new.cyclic_teams:
        nums = ", ".join(str(t) for t in sorted(new.cyclic_teams))
        reasons.append(Finding("CYCLE", f"팀 부모 사슬이 순환합니다(팀 번호 {nums})"))

    for t in sorted(new.orphan_teams):
        # 이전 조직에서 그 팀의 부모가 실제로 있었을 때만 「사라짐」이다. 처음부터 고아였던 팀은 경고만 —
        # 안 그러면 한 번 받은 고아 팀 때문에 다음 스냅숏부터 영원히 버려진다.
        if prev is not None and t in prev.teams and t not in prev.orphan_teams:
            reasons.append(Finding("PARENT_LOST", f"있던 팀 {t} 의 부모 팀 {new.teams[t].parent_idx} 가 사라졌습니다"))
        else:
            warnings.append(Finding("ORPHAN_TEAM", f"팀 {t} 의 부모 팀 {new.teams[t].parent_idx} 가 표에 없습니다(그 팀장은 본인 범위로)"))

    for p in new.people.values():
        if p.status is None:
            warnings.append(Finding("UNKNOWN_STATUS", f"직원 {p.idx} 의 상태가 비어 있습니다 — 재직이 아닌 것으로 봅니다"))
        elif p.status not in KNOWN_STATUSES:
            warnings.append(Finding("UNKNOWN_STATUS", f"직원 {p.idx} 의 상태 글자를 모릅니다 — 재직이 아닌 것으로 봅니다"))
        if p.team_idx is not None and p.team_idx not in new.teams:
            warnings.append(Finding("UNKNOWN_TEAM_REF", f"직원 {p.idx} 의 팀 {p.team_idx} 가 표에 없습니다 — 본인 범위로 봅니다"))

    unknown_src = sum(1 for o in new.owners if o.owner_source is not None and o.owner_source not in KNOWN_OWNER_SOURCES)
    if unknown_src:
        warnings.append(Finding("UNKNOWN_OWNER_SOURCE", f"담당 출처 글자를 모르는 줄 {unknown_src}개 — 「이전 담당」으로 보지 않습니다"))

    tops = new.top_managers()
    if not tops:
        reasons.append(Finding("TOP_MANAGER_NONE", "재직 대표가 없습니다 — 대표 계정(0번)이 빠졌을 수 있어 받지 않습니다"))
    elif len(tops) > TOP_MANAGER_MAX:
        reasons.append(Finding("TOP_MANAGER_LIMIT", f"재직 대표 표시가 {len(tops)}명입니다 — {TOP_MANAGER_MAX}명 넘게는 받지 않습니다"))
    elif len(tops) != 1:
        warnings.append(Finding("TOP_MANAGER_COUNT", f"재직 대표 표시가 {len(tops)}명입니다(보통 1명)"))

    if now is not None:
        if now.tzinfo is None:
            raise ValueError("now 는 시간대가 있는 시각이어야 합니다")
        if new.generated_dt > now + FUTURE_TOLERANCE:
            reasons.append(Finding("FUTURE", f"스냅숏 시각 {new.generated_at} 이 지금보다 앞섭니다"))

    if prev is not None:
        if new.generated_dt <= prev.generated_dt:
            reasons.append(Finding("STALE", f"스냅숏 시각 {new.generated_at} 이 이전 {prev.generated_at} 보다 새것이 아닙니다"))

        added = tops - prev.top_managers()
        if added:
            nums = ", ".join(str(i) for i in sorted(added))
            reasons.append(Finding("TOP_MANAGER_ADDED", f"대표 표시가 새로 붙은 직원이 있습니다(번호 {nums})"))

        lost = sorted(t for t in prev.teams if t in new.teams and prev.is_system_team(t) and not new.is_system_team(t))
        if lost:
            nums = ", ".join(str(t) for t in lost)
            reasons.append(Finding("SYSTEM_TEAM_LOST", f"시스템 팀이 보통 팀으로 바뀌었습니다(팀 번호 {nums})"))

        m0, m1 = prev.active_manager_count(), new.active_manager_count()
        if m1 - m0 >= MANAGER_SPIKE_MIN and (m0 == 0 or (m1 - m0) / m0 > MANAGER_SPIKE_LIMIT):
            reasons.append(Finding(
                "MANAGER_SPIKE",
                f"재직 팀장 {m0} → {m1}명 — {MANAGER_SPIKE_LIMIT:.0%} 넘게 · {MANAGER_SPIKE_MIN}명 이상 늘었습니다"))

        prev_active = prev.active_count()
        if prev_active > 0 and (prev_active - new_active) / prev_active > ACTIVE_DROP_LIMIT:
            reasons.append(Finding(
                "ACTIVE_DROP",
                f"재직 직원 {prev_active} → {new_active}명 — {ACTIVE_DROP_LIMIT:.0%} 넘게 줄었습니다"))

        prev_owners, new_owners = len(prev.owners), len(new.owners)
        if prev_owners > 0 and (prev_owners - new_owners) / prev_owners > OWNER_DROP_LIMIT:
            reasons.append(Finding(
                "OWNER_DROP",
                f"담당 줄 {prev_owners} → {new_owners}개 — {OWNER_DROP_LIMIT:.0%} 넘게 줄었습니다(잘린 응답 의심)"))

        if prev_owners > 0 and new_owners > 0:
            before, after = prev.blank_owner_ratio(), new.blank_owner_ratio()
            if after - before > OWNER_BLANK_SPIKE_LIMIT:
                reasons.append(Finding(
                    "OWNER_BLANK_SPIKE",
                    f"담당 빈칸 비율 {before:.0%} → {after:.0%} — {OWNER_BLANK_SPIKE_LIMIT:.0%}p 넘게 늘었습니다"))

    return SnapshotCheck(ok=not reasons, reasons=tuple(reasons), warnings=tuple(warnings))


def accept_snapshot(payload: Any, prev: Optional[Org], now: Optional[datetime] = None) -> SnapshotDecision:
    """전부 받거나 전부 버린다. 버리면 ``org`` 는 이전 조직 **그 객체** 다(한 줄도 섞지 않는다).

    응답이 무엇이든 예외를 던지지 않는다(``now`` 에 시간대 없는 시각을 넘기는 부르는 쪽 실수만 ValueError).
    ``prev=None`` 은 처음 받기 또는 대표가 확인한 다시 받기다(머리말 ⚠️ 참고)."""
    try:
        new = parse_org_snapshot(payload)
    except SnapshotFormatError as e:
        check = SnapshotCheck(ok=False, reasons=(Finding("FORMAT", str(e)),), warnings=())
        return SnapshotDecision(ok=False, org=prev, check=check)
    check = check_snapshot(new, prev, now)
    return SnapshotDecision(ok=check.ok, org=new if check.ok else prev, check=check)


# ── 신선도 ─────────────────────────────────────────────────────────

def org_freshness(generated_dt: Optional[datetime], now: datetime) -> str:
    """조직 수락본이 얼마나 새것인지 — ``none`` · ``fresh`` · ``yellow``(3시간 넘음) · ``stale``(26시간 넘음).

    기준은 ① 가 만든 시각(``generated_at``)이다. 허용(10분)보다 앞선 시각은 믿을 수 없으므로 ``stale`` 로 본다(닫힌 쪽).
    시간대 없는 시각은 부르는 쪽 실수라 ValueError."""
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 합니다")
    if generated_dt is None:
        return FRESH_NONE
    if not isinstance(generated_dt, datetime) or generated_dt.tzinfo is None:
        raise ValueError("generated_dt 는 시간대가 있는 시각이어야 합니다")
    if generated_dt > now + FUTURE_TOLERANCE:
        return FRESH_STALE
    age = now - generated_dt
    if age > ORG_STALE_AFTER:
        return FRESH_STALE
    if age > ORG_YELLOW_AFTER:
        return FRESH_YELLOW
    return FRESH_OK


def allows_raising(freshness: str) -> bool:
    """승인 · 자동 켜기 · 운영 방식 올리기가 되는가 — 맑음·노랑만. 없음·낡음·모르는 값은 안 된다(멈추기·내리기만)."""
    return freshness in (FRESH_OK, FRESH_YELLOW)
