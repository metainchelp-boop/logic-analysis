"""① 전산 동기화 — 조직 스냅숏(1시간) · 계약 단계(6시간) (설계 v1.8 S7 · §9 · M3 · M12 · 반박 H1 · H3).

조직 스냅숏(``sync_org``)
- ① 에서 읽는다 → 저장소의 수락본을 「이전 조직」으로 삼는다(엔진을 다시 켜도 같다 — M12) →
  ``app.naver_auto.org_snapshot.accept_snapshot`` 이 **전부 받거나 전부 버린다** → 받으면 ``record_org``,
  버리면 버린 이유 코드만 기록하고 수락본은 그대로 둔다.
- 저장된 수락본을 읽지 못하면 받지 않는다(``STORED_UNREADABLE``) — 「이전 조직 없음」으로 여겨 감소·권한 확대 검사를
  건너뛰는 길을 열지 않는다.
- 감소·권한 확대 검사로 버려진 상태는 **스스로 풀리지 않는다**(마지막 수락본과만 견준다). 대표가 확인하면
  ``confirmed_by`` 로 이전 조직 없이 다시 받는다 — 형식·순환·빈 조직·대표 수·미래 시각 검사는 그때도 돈다.
  누가 확인했는지는 동기화 기록에 남는다. **확인하는 사람이 대표인지는 부르는 쪽(S11 화면 API · scope)이 판정한다.**

계약 단계(``sync_stages``)
- 7단계 × 표기를 전부 받았을 때만(``StageSnapshot``) 가망 표를 고친다. 한 번이라도 실패하면 아무것도 바꾸지 않는다.
- **첫 회차**는 관리 단계 광고주 수를 v1.7 실측(약 940)과 ±20% 대조한다(반박 H3 — 표기를 놓치면 크게 모자란다).
- 목록이 한꺼번에 크게 줄면 저장소 브레이크가 멈춘다(``SyncBraked``) — 대표 확인 뒤 ``confirmed_by`` 로 받는다.
- ③ 06:00 계약 동기화 · ② 04:00 동기화와 겹치지 않게 그 앞뒤 창에는 부르지 않는다(M3 · ① 커넥션 풀 보호).

공통
- ① 읽기 실패·검사 탈락은 예외가 아니라 결과(``SyncResult``)로 돌려준다 — 스케줄러가 멈추지 않게. 기록에는 종류 코드와
  개수만 남는다(번호·이름·키 없음). 저장소 자체 오류(``StoreError`` — 잠금·파일)는 그대로 던진다.
- 시각은 부르는 쪽이 넣는다(``now`` · 시간대 필수). 이 모듈은 네트워크를 직접 열지 않는다(① 관문 ``erp_read`` 만).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, Tuple

from app.naver_auto import org_snapshot as O

from . import erp_read as E
from . import store as S

ORG_EVERY = timedelta(hours=1)          # 설계 §9 — 조직은 1시간마다
STAGES_EVERY = timedelta(hours=6)       # 계약 단계는 6시간마다(받은 것 기준)
STAGES_RETRY = timedelta(hours=1)       # 실패·버림 뒤 다시 부르기까지(① 을 두드리지 않게)
# 계약 단계를 부르지 않는 창(한국 시각) — ② 04:00 · ③ 06:00 이 같은 ① 경로를 부른다(M3).
STAGES_QUIET = ((time(3, 50), time(4, 20)), (time(5, 50), time(6, 30)))

CODE_STORED_UNREADABLE = "STORED_UNREADABLE"
CODE_IMPLAUSIBLE_FIRST = "IMPLAUSIBLE_FIRST"
CODE_STORE_REFUSED = "STORE_REFUSED"
CODE_BRAKE = "BRAKE"
# 이전 조직과 견줄 때만 나오는 버림 — 정상적인 큰 변화일 수 있어 대표 확인으로 풀 수 있다.
# (형식 · 빈 조직 · 순환 · 대표 없음/너무 많음 · 미래 시각은 확인해도 그대로 버려진다 — ① 쪽을 고쳐야 한다.)
CONFIRMABLE_ORG_CODES = frozenset({
    "ACTIVE_DROP", "OWNER_DROP", "OWNER_BLANK_SPIKE", "TOP_MANAGER_ADDED", "SYSTEM_TEAM_LOST", "MANAGER_SPIKE",
    "PARENT_LOST", CODE_STORED_UNREADABLE,
})
# STALE(이전보다 새것이 아님)은 넣지 않는다 — 확인해도 저장소가 더 새 스냅숏만 받는다(①의 시각을 고쳐야 풀린다).


@dataclass(frozen=True)
class SyncResult:
    kind: str                            # org · stages
    outcome: str                         # accepted · refused · braked · failed
    codes: Tuple[str, ...] = ()          # 버린·멈춘·실패한 이유 코드(받았으면 경고 코드)
    rows: Optional[int] = None           # 받은(또는 받을 뻔한) 줄 수
    absent: Optional[int] = None         # 「목록에 없음」이 된(또는 될 뻔한) 줄 수
    needs_confirmation: bool = False     # 스스로 풀리지 않음 — 대표에게 알린다(S10)

    def __repr__(self) -> str:   # 코드·개수만
        return (f"SyncResult(kind={self.kind}, outcome={self.outcome}, codes={list(self.codes)}, rows={self.rows}, "
                f"absent={self.absent}, needs_confirmation={self.needs_confirmation})")


def _need_time(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 합니다")


def _erp_code(e: E.ErpError) -> str:
    return f"{e.kind}-{e.status}" if isinstance(e.status, int) and not isinstance(e.status, bool) else e.kind


def _unique(codes) -> Tuple[str, ...]:
    out = []
    for c in codes:
        if c not in out:
            out.append(c)
    return tuple(out[:S.MAX_SYNC_CODES])


# ── 조직 스냅숏 ──────────────────────────────────────────────────────
def sync_org(reader: E.ErpReader, store: S.Store, now: datetime, *, confirmed_by: Optional[int] = None) -> SyncResult:
    """조직 스냅숏을 한 번 받는다. ``confirmed_by`` = 대표가 확인한 다시 받기(이전 조직 없이 검사)."""
    _need_time(now)
    try:
        payload = reader.read_org_snapshot()
    except E.ErpError as e:
        code = _erp_code(e)
        store.record_sync_event(S.SYNC_ORG, S.SYNC_FAILED, (code,), now)
        return SyncResult(S.SYNC_ORG, S.SYNC_FAILED, (code,))
    prev = None
    if confirmed_by is None:
        try:
            stored = store.org_current()
            prev = None if stored is None else O.parse_org_snapshot(stored["body"])
        except (S.StoreError, O.SnapshotFormatError):
            store.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, (CODE_STORED_UNREADABLE,), now)
            return SyncResult(S.SYNC_ORG, S.SYNC_REFUSED, (CODE_STORED_UNREADABLE,), needs_confirmation=True)
    decision = O.accept_snapshot(payload, prev, now)
    if not decision.ok:
        codes = _unique(f.code for f in decision.reasons)
        store.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, codes, now)
        return SyncResult(S.SYNC_ORG, S.SYNC_REFUSED, codes,
                          needs_confirmation=bool(set(codes) & CONFIRMABLE_ORG_CODES))
    warnings = _unique(f.code for f in decision.check.warnings)
    org = decision.org
    try:
        store.record_org(O.unwrap(payload), now, warnings=warnings, confirmed_by=confirmed_by)
    except S.StoreRefused:
        store.record_sync_event(S.SYNC_ORG, S.SYNC_REFUSED, (CODE_STORE_REFUSED,), now, rows=len(org.owners))
        return SyncResult(S.SYNC_ORG, S.SYNC_REFUSED, (CODE_STORE_REFUSED,), rows=len(org.owners))
    return SyncResult(S.SYNC_ORG, S.SYNC_ACCEPTED, warnings, rows=len(org.owners))


def org_freshness(store: S.Store, now: datetime) -> str:
    """조직 수락본 신선도 — ``app.naver_auto.org_snapshot.org_freshness`` 한 곳의 규칙으로(엔진·화면 API 가 같게)."""
    _need_time(now)
    stored = store.org_current()
    return O.org_freshness(None if stored is None else stored["generated_at"], now)


# ── 계약 단계 ────────────────────────────────────────────────────────
def sync_stages(reader: E.ErpReader, store: S.Store, now: datetime, *,
                confirmed_by: Optional[int] = None) -> SyncResult:
    """계약 단계를 한 번 받는다. ``confirmed_by`` = 대표가 확인(첫 회차 대조 · 급감 브레이크를 넘긴다)."""
    _need_time(now)
    try:
        snap = reader.read_stages()
    except E.ErpError as e:
        code = _erp_code(e)
        store.record_sync_event(S.SYNC_STAGES, S.SYNC_FAILED, (code,), now)
        return SyncResult(S.SYNC_STAGES, S.SYNC_FAILED, (code,))
    rows = len(snap.rows) + len(snap.stage_conflicts)
    first = store.stage_as_of() is None   # 한 번도 받은 적 없음(판 번호와 상관없이 저장소가 기억하는 사실)
    if first and confirmed_by is None and not snap.plausible():
        store.record_sync_event(S.SYNC_STAGES, S.SYNC_REFUSED, (CODE_IMPLAUSIBLE_FIRST,), now, rows=rows)
        return SyncResult(S.SYNC_STAGES, S.SYNC_REFUSED, (CODE_IMPLAUSIBLE_FIRST,), rows=rows, needs_confirmation=True)
    try:
        counts = store.record_prospects(snap, allow_drop_by=confirmed_by)
    except S.SyncBraked as b:
        return SyncResult(S.SYNC_STAGES, S.SYNC_BRAKED, (CODE_BRAKE,), rows=rows, absent=b.would_absent,
                          needs_confirmation=True)
    except S.StoreRefused:
        store.record_sync_event(S.SYNC_STAGES, S.SYNC_REFUSED, (CODE_STORE_REFUSED,), now, rows=rows)
        return SyncResult(S.SYNC_STAGES, S.SYNC_REFUSED, (CODE_STORE_REFUSED,), rows=rows)
    return SyncResult(S.SYNC_STAGES, S.SYNC_ACCEPTED, (), rows=counts.present, absent=counts.now_absent)


# ── 언제 부르나 ──────────────────────────────────────────────────────
def _quiet(now: datetime) -> bool:
    t = now.astimezone(S.KST).time()
    return any(a <= t < b for a, b in STAGES_QUIET)


def org_due(store: S.Store, now: datetime) -> bool:
    """마지막 시도(결과 무관)가 1시간 넘게 지났으면 부른다."""
    _need_time(now)
    last = store.last_sync(S.SYNC_ORG)
    return last is None or now - datetime.fromisoformat(last["at"]) >= ORG_EVERY


def stages_due(store: S.Store, now: datetime) -> bool:
    """조용한 창이 아니고 · 마지막으로 받은 지 6시간 넘었고 · 마지막 시도가 1시간 넘게 지났으면 부른다."""
    _need_time(now)
    if _quiet(now):
        return False
    last_try = store.last_sync(S.SYNC_STAGES)
    if last_try is not None and now - datetime.fromisoformat(last_try["at"]) < STAGES_RETRY:
        return False
    got = store.stage_as_of()
    return got is None or now - got >= STAGES_EVERY
