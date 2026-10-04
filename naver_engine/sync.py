"""① 전산 동기화 — 조직 스냅숏(1시간) · 계약 단계(6시간) (설계 v1.8 S7 · §9 · M3 · M12 · 반박 H1 · H3 · S7 적대 검토).

조직 스냅숏(``sync_org``)
- ① 에서 읽는다 → 저장소의 수락본을 「이전 조직」으로 삼는다(엔진을 다시 켜도 같다 — M12) →
  ``app.naver_auto.org_snapshot`` 의 검사가 **전부 받거나 전부 버린다** → 받으면 ``record_org``,
  버리면 버린 이유 코드만 기록하고 수락본은 그대로 둔다.
- 저장된 수락본을 읽지 못하면(줄이 없는데 받은 기록은 있는 경우 포함) 받지 않는다(``STORED_UNREADABLE``) —
  「이전 조직 없음」으로 여겨 감소·권한 확대 검사를 건너뛰는 길을 열지 않는다.
- 직전 수락본뿐 아니라 **기준선**(마지막 대표 확인 뒤 가장 많던 재직·담당 줄 · 가장 적던 팀장)과도 견준다 —
  한도 바로 밑으로 조금씩 나빠지는 톱니를 막는다(``*_BASELINE``).
- 확인으로 풀 수 있는 이유로만 버리면 그 스냅숏을 **붙잡아 둔다**(``hold_id``). 대표가 확인하면 ``confirm_org`` 가
  ① 을 **새로 읽지 않고** 붙잡아 둔 그 본문을 받는다 — 지금 다시 견줘 나오는 이유가 대표가 본 이유 안에 들 때만
  (그 사이 조직이 바뀌어 새 이유가 나오면 다시 붙잡고 다시 묻는다). 형식·순환·빈 조직·대표 수·미래 시각은 확인으로
  풀리지 않는다(① 쪽을 고쳐야 한다). **확인하는 사람이 대표인지는 부르는 쪽(S11 화면 API · scope)이 판정한다.**

계약 단계(``sync_stages``)
- 7단계 × 표기를 전부 받았을 때만(``StageSnapshot``) 가망 표를 고친다. 한 번이라도 실패하면 아무것도 바꾸지 않는다.
- **첫 회차**는 관리 단계 광고주 수를 v1.7 실측(약 940)과 ±20% 대조하고, 실측에서 줄이 있던 단계(``FIRST_REQUIRED_STAGES``)가
  하나라도 0 이면 받지 않는다(반박 H3 — 표기를 놓치면 한 단계가 통째로 빠진다). 버린 목록은 붙잡아 둔다.
- 둘째 회차부터는 저장소 브레이크가 본다(한꺼번에 · 한 단계 · 누적) — 멈추면 붙잡아 두고 ``confirm_stages`` 로 받는다.
- 읽기는 **마감**이 있다(``STAGES_MAX_READ`` · 다음 조용한 창 시작 중 이른 때) — ② 04:00 · ③ 06:00 대 계약 동기화와
  겹치지 않게(M3 · ① 커넥션 풀 보호). 마감을 넘기면 남은 표기를 부르지 않고 버린다.

공통
- ① 읽기 실패·검사 탈락·이상한 입력은 예외가 아니라 결과(``SyncResult``)로 돌려준다 — 스케줄러가 멈추지 않게. 기록에는
  종류 코드와 개수만 남는다(번호·이름·키 없음). 저장소 자체 오류(``StoreError`` — 잠금·파일)는 그대로 던진다.
- ``alert`` = 대표에게 알릴 것(S10): 확인이 필요함 · 확인으로 못 푸는 버림 · 실패가 오래 이어짐(조직 3시간 · 단계 12시간) ·
  한 번도 받은 적 없이 실패.
- **회차마다 새 ``ErpReader``** 를 넘긴다(호출 상한이 객체 평생 누적이라 같은 객체를 계속 쓰면 몇 시간 뒤 영영 막힌다).
- 시각은 부르는 쪽이 넣는다(``now`` · 시간대 필수). 이 모듈은 네트워크를 직접 열지 않는다(① 관문 ``erp_read`` 만).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional, Tuple

from app.naver_auto import org_snapshot as O

from . import erp_read as E
from . import store as S

ORG_EVERY = timedelta(hours=1)          # 설계 §9 — 조직은 1시간마다
STAGES_EVERY = timedelta(hours=6)       # 계약 단계는 6시간마다(받은 것 기준)
STAGES_RETRY = timedelta(hours=1)       # 실패·버림·멈춤 뒤 다시 부르기까지(① 을 두드리지 않게)
STAGES_MAX_READ = timedelta(minutes=10)   # 계약 단계 한 회차(15표기) 읽기 마감 — 조용한 창에 걸치지 않게
# 계약 단계를 부르지 않는 창(한국 시각) — ② 04:00(CronTrigger) · ③ 06:00 수집 **뒤** 계약 동기화(수집 소요를 모름 →
# 70분 여유 · S14 에서 ③ 실제 소요를 재 보고 조정). 창 시작 10분 전부터도 새로 시작하지 않는다(읽기 마감).
STAGES_QUIET = ((time(3, 50), time(4, 20)), (time(5, 50), time(7, 10)))
CLOCK_SKEW = timedelta(minutes=5)       # 마지막 기록이 이보다 더 미래면 시계를 뒤로 고친 것 — 기다리지 않는다
ORG_ALERT_AFTER = timedelta(hours=3)    # 조직을 이만큼 넘게 못 받으면 알린다(신선도 노랑과 같은 때)
STAGES_ALERT_AFTER = timedelta(hours=12)  # 계약 단계 — 두 회차

CODE_STORED_UNREADABLE = S.CODE_STORED_UNREADABLE
CODE_IMPLAUSIBLE_FIRST = "IMPLAUSIBLE_FIRST"
CODE_STAGE_EMPTY_FIRST = "STAGE_EMPTY_FIRST"
CODE_STORE_REFUSED = "STORE_REFUSED"
CODE_UNEXPECTED = "unexpected"
CODE_BRAKE = S.BRAKE_TOTAL
CODE_ACTIVE_DROP_BASELINE = "ACTIVE_DROP_BASELINE"
CODE_OWNER_DROP_BASELINE = "OWNER_DROP_BASELINE"
CODE_MANAGER_SPIKE_BASELINE = "MANAGER_SPIKE_BASELINE"

# 첫 회차에 0 이면 안 되는 단계 — v1.7 실측(진행중 573 · 환불중 139 · 전략 관리 90 · 홀딩중 69 · 사후 관리 68).
# 재계약 진행중(5)·계약 만료는 0 일 수 있어 넣지 않는다.
FIRST_REQUIRED_STAGES = ("진행중", "전략관리", "사후관리", "홀딩중", "환불중")

# 이전 조직(또는 기준선)과 견줄 때만 나오는 버림 — 정상적인 큰 변화일 수 있어 대표 확인으로 풀 수 있다.
# (형식 · 빈 조직 · 순환 · 대표 없음/너무 많음 · 미래 시각은 확인해도 그대로 버려진다 — ① 쪽을 고쳐야 한다.)
CONFIRMABLE_ORG_CODES = frozenset({
    "ACTIVE_DROP", "OWNER_DROP", "OWNER_BLANK_SPIKE", "TOP_MANAGER_ADDED", "SYSTEM_TEAM_LOST", "MANAGER_SPIKE",
    "PARENT_LOST", CODE_STORED_UNREADABLE,
    CODE_ACTIVE_DROP_BASELINE, CODE_OWNER_DROP_BASELINE, CODE_MANAGER_SPIKE_BASELINE,
})
# STALE(이전보다 새것이 아님)은 넣지 않는다 — 확인해도 저장소가 더 새 스냅숏만 받는다(①의 시각을 고쳐야 풀린다).
CONFIRMABLE_STAGE_CODES = frozenset({
    S.BRAKE_TOTAL, S.BRAKE_STAGE, S.BRAKE_BASELINE, CODE_IMPLAUSIBLE_FIRST, CODE_STAGE_EMPTY_FIRST,
})

# 이상한 입력에서 나올 수 있는 예외 — 결과(failed · unexpected)로 돌려준다(기록이 남아 부르는 때·알림이 돈다).
# TypeError 는 넣지 않는다 — 부르는 모양이 틀린 것(프로그램 결함)은 결과로 덮지 않고 드러낸다.
_UNEXPECTED = (ValueError, OverflowError, RecursionError)


@dataclass(frozen=True)
class SyncResult:
    kind: str                            # org · stages
    outcome: str                         # accepted · refused · braked · failed
    codes: Tuple[str, ...] = ()          # 버린·멈춘·실패한 이유 코드(받았으면 경고 코드 · 확인이면 CONFIRMED)
    rows: Optional[int] = None           # 받은(또는 받을 뻔한) 줄 수
    absent: Optional[int] = None         # 「목록에 없음」이 된(또는 될 뻔한) 줄 수
    needs_confirmation: bool = False     # 붙잡아 두었다 — 대표가 확인하면 받는다(hold_id)
    alert: bool = False                  # 대표에게 알릴 것(S10)
    hold_id: Optional[int] = None        # 붙잡음 번호 — confirm_org · confirm_stages 에 넘긴다

    def __repr__(self) -> str:   # 코드·개수만
        return (f"SyncResult(kind={self.kind}, outcome={self.outcome}, codes={list(self.codes)}, rows={self.rows}, "
                f"absent={self.absent}, needs_confirmation={self.needs_confirmation}, alert={self.alert}, "
                f"hold_id={self.hold_id})")


def _need_time(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 합니다")


def _need_fresh_reader(reader) -> None:
    calls = getattr(reader, "calls", None)
    if isinstance(calls, bool) or calls != 0:
        raise ValueError("회차마다 새 ErpReader 를 넘겨야 합니다(호출 상한은 객체 평생 누적)")


def _need_person(v) -> None:
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise ValueError("확인한 직원 번호는 0 이상 정수여야 합니다(대표 = 0)")


def _erp_code(e: E.ErpError) -> str:
    st = e.status
    if isinstance(st, int) and not isinstance(st, bool) and 100 <= st <= 599:
        return f"{e.kind}-{st}"
    return e.kind


def _unique(codes) -> Tuple[str, ...]:
    out = []
    for c in codes:
        if c not in out:
            out.append(c)
    return tuple(out[:S.MAX_SYNC_CODES])


def _aware(raw) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return t if t is not None and t.tzinfo is not None else None


def _failure_alert(store: S.Store, kind: str, now: datetime, after: timedelta) -> bool:
    """실패를 대표에게 알릴 것인가 — 오래 이어졌거나(받은 지 ``after`` 넘음) 한 번도 받은 적이 없을 때.
    (버림·멈춤·확인 필요는 그 자리에서 바로 알린다 — 스스로 풀리지 않는다.)"""
    ok = store.last_sync(kind, S.SYNC_ACCEPTED)
    if ok is None:
        return True
    at = _aware(ok["at"])
    return at is None or now - at >= after


def _failed(store: S.Store, kind: str, code: str, now: datetime, after: timedelta) -> SyncResult:
    store.record_sync_event(kind, S.SYNC_FAILED, (code,), now)
    return SyncResult(kind, S.SYNC_FAILED, (code,), alert=_failure_alert(store, kind, now, after))


def _refused_plain(store: S.Store, kind: str, codes, now: datetime, rows: Optional[int]) -> SyncResult:
    """확인으로 풀 수 없는 버림 — 붙잡지 않고 기록만 · 바로 알린다(① 이나 저장 규칙을 고쳐야 풀린다)."""
    codes = _unique(codes)
    store.record_sync_event(kind, S.SYNC_REFUSED, codes, now, rows=rows)
    return SyncResult(kind, S.SYNC_REFUSED, codes, rows=rows, alert=True)


def _hold_problem(hold: Optional[dict], hold_id, now: datetime) -> Optional[str]:
    if isinstance(hold_id, bool) or not isinstance(hold_id, int) or hold is None or hold["hold_id"] != hold_id:
        return S.HOLD_NOT_FOUND
    if hold["used_at"] is not None:
        return S.HOLD_USED if hold["used_by"] is not None else S.HOLD_SUPERSEDED
    if now - hold["at"] > S.HOLD_TTL or hold["at"] > now + S.FUTURE_SLACK:
        return S.HOLD_EXPIRED
    return None


# ── 조직 스냅숏 ──────────────────────────────────────────────────────
def _org_state(store: S.Store):
    """(이전 조직, 못 읽음, 기준선). 줄이 없는데 받은 기록이 있으면 못 읽음(M12 — 처음 받기로 여기지 않는다)."""
    try:
        stored = store.org_current()
        if stored is None:
            if store.last_sync(S.SYNC_ORG, S.SYNC_ACCEPTED) is not None:
                return None, True, None
            return None, False, store.org_baseline()
        return O.parse_org_snapshot(stored["body"]), False, store.org_baseline()
    except (S.StoreError, O.SnapshotFormatError):
        return None, True, None


def _baseline_codes(new: O.Org, base: Optional[dict]) -> list:
    """기준선(마지막 확인 뒤 가장 많던 재직·담당 줄 · 가장 적던 팀장)과 견준다 — 직전 수락본 비교와 같은 한도."""
    if base is None:
        return []
    out = []
    a0, a1 = base["active"], new.active_count()
    if a0 > 0 and (a0 - a1) / a0 > O.ACTIVE_DROP_LIMIT:
        out.append(CODE_ACTIVE_DROP_BASELINE)
    w0, w1 = base["owners"], len(new.owners)
    if w0 > 0 and (w0 - w1) / w0 > O.OWNER_DROP_LIMIT:
        out.append(CODE_OWNER_DROP_BASELINE)
    m0, m1 = base["managers"], new.active_manager_count()
    if m1 - m0 >= O.MANAGER_SPIKE_MIN and (m0 == 0 or (m1 - m0) / m0 > O.MANAGER_SPIKE_LIMIT):
        out.append(CODE_MANAGER_SPIKE_BASELINE)
    return out


def _org_codes(payload, prev: Optional[O.Org], unreadable: bool, base: Optional[dict], now: datetime,
               *, account_monitoring=False):
    """(새 조직 또는 None, 버림 코드, 경고 코드)."""
    try:
        new = O.parse_org_snapshot(payload)
    except O.SnapshotFormatError:
        return None, ("FORMAT",), ()
    check = (O.check_monitoring_snapshot if account_monitoring else O.check_snapshot)(new, prev, now)
    codes = [f.code for f in check.reasons]
    warnings = [f.code for f in check.warnings]
    if unreadable:
        codes.insert(0, CODE_STORED_UNREADABLE)
    else:
        baseline_codes = _baseline_codes(new, base)
        for code in baseline_codes:
            if account_monitoring and code == CODE_MANAGER_SPIKE_BASELINE:
                warnings.append(code)
            else:
                codes.append(code)
    return new, _unique(codes), _unique(warnings)


def _org_counts(org: O.Org) -> Tuple[int, int, int]:
    return org.active_count(), len(org.owners), org.active_manager_count()


def _refuse_org(store: S.Store, body, now: datetime, codes, new: Optional[O.Org]) -> SyncResult:
    rows = None if new is None else len(new.owners)
    if codes and set(codes) <= CONFIRMABLE_ORG_CODES:
        try:
            hid = store.refuse_org(body, now, codes)
        except S.StoreRefused:
            return _refused_plain(store, S.SYNC_ORG, tuple(codes) + (CODE_STORE_REFUSED,), now, rows)
        return SyncResult(S.SYNC_ORG, S.SYNC_REFUSED, codes, rows=rows, needs_confirmation=True, alert=True, hold_id=hid)
    return _refused_plain(store, S.SYNC_ORG, codes, now, rows)


def sync_org(reader: E.ErpReader, store: S.Store, now: datetime, *, account_monitoring=False) -> SyncResult:
    """조직 스냅숏을 한 번 받는다. 본인 담당 관제 옵션은 팀 이상만 경고로 격리한다."""
    if type(account_monitoring) is not bool:
        raise ValueError("계정 관제 여부는 참/거짓이어야 합니다")
    _need_time(now)
    _need_fresh_reader(reader)
    try:
        payload = reader.read_org_snapshot()
    except E.ErpError as e:
        return _failed(store, S.SYNC_ORG, _erp_code(e), now, ORG_ALERT_AFTER)
    except _UNEXPECTED:
        return _failed(store, S.SYNC_ORG, CODE_UNEXPECTED, now, ORG_ALERT_AFTER)
    try:
        prev, unreadable, base = _org_state(store)
        new, codes, warnings = _org_codes(payload, prev, unreadable, base, now,
                                         account_monitoring=account_monitoring)
        if codes:
            return _refuse_org(store, O.unwrap(payload) if new is not None else payload, now, codes, new)
        try:
            store.record_org(O.unwrap(payload), now, warnings=warnings, baseline=_org_counts(new))
        except S.StoreRefused:
            return _refused_plain(store, S.SYNC_ORG, (CODE_STORE_REFUSED,), now, len(new.owners))
        return SyncResult(S.SYNC_ORG, S.SYNC_ACCEPTED, warnings, rows=len(new.owners))
    except _UNEXPECTED:
        return _failed(store, S.SYNC_ORG, CODE_UNEXPECTED, now, ORG_ALERT_AFTER)


def confirm_org(store: S.Store, now: datetime, confirmed_by: int, hold_id: int) -> SyncResult:
    """대표가 본 그 붙잡음을 받는다 — ① 을 새로 읽지 않는다.

    지금 다시 견줘 나오는 이유가 **대표가 본 이유 안에** 들 때만 받는다(그 사이 수락본·기준선이 바뀌어 새 이유가 나오면
    다시 붙잡고 다시 묻는다). 받으면 우회한 이유 코드와 확인한 사람이 기록에 남는다. 붙잡음이 없거나(더 새로 붙잡음) ·
    이미 썼거나 · 3시간이 지났으면 ``HOLD_*`` 코드로 돌려준다(기록 없음 · ① 호출 없음)."""
    _need_time(now)
    _need_person(confirmed_by)
    hold = store.hold(S.SYNC_ORG)
    bad = _hold_problem(hold, hold_id, now)
    if bad is not None:
        return SyncResult(S.SYNC_ORG, S.SYNC_REFUSED, (bad,))
    held, body = frozenset(hold["codes"]), hold["body"]
    try:
        prev, unreadable, base = _org_state(store)
        new, codes, warnings = _org_codes(body, prev, unreadable, base, now)
        if new is None or not set(codes) <= held or not held <= CONFIRMABLE_ORG_CODES:
            return _refuse_org(store, body, now, codes, new)   # 대표가 보지 못한 이유 — 다시 붙잡고 다시 묻는다
        try:
            store.record_org(body, now, warnings=warnings, confirmed_by=confirmed_by, hold_id=hold_id,
                             baseline=_org_counts(new))
        except S.HoldRefused as e:
            return SyncResult(S.SYNC_ORG, S.SYNC_REFUSED, (e.code,))
        except S.StoreRefused:
            return SyncResult(S.SYNC_ORG, S.SYNC_REFUSED, (CODE_STORE_REFUSED,), rows=len(new.owners), alert=True)
        return SyncResult(S.SYNC_ORG, S.SYNC_ACCEPTED, _unique(warnings + tuple(hold["codes"]) + (S.CODE_CONFIRMED,)),
                          rows=len(new.owners))
    except _UNEXPECTED:
        return _failed(store, S.SYNC_ORG, CODE_UNEXPECTED, now, ORG_ALERT_AFTER)


def org_freshness(store: S.Store, now: datetime) -> str:
    """조직 수락본 신선도 — ``app.naver_auto.org_snapshot.org_freshness`` 한 곳의 규칙으로(엔진·화면 API 가 같게).

    수락본을 못 읽으면(본문이 망가짐 · 줄이 없는데 받은 기록은 있음) **낡음** — 쓸 수 없는 조직으로 올리기 관문을 열지 않는다."""
    _need_time(now)
    try:
        stored = store.org_current()
        if stored is None:
            return O.FRESH_STALE if store.last_sync(S.SYNC_ORG, S.SYNC_ACCEPTED) is not None else O.FRESH_NONE
        O.parse_org_snapshot(stored["body"])
    except (S.StoreError, O.SnapshotFormatError):
        return O.FRESH_STALE
    return O.org_freshness(stored["generated_at"], now)


def is_current_owner(store: S.Store, actor: int, now: datetime) -> bool:
    """즉시 읽기 요청의 대표 관문. 조직 해석은 코어 안에 두고 runtime에는 참/거짓만 준다."""
    if type(actor) is not int or not 0 <= actor < 2 ** 63:
        return False
    saved = store.org_current()
    if saved is None or not O.allows_raising(O.org_freshness(saved["generated_at"], now)):
        return False
    # scope.ALL과 같은 원본 정의: 재직 중이며 is_top_manager인 사람만.
    return actor in O.parse_org_snapshot(saved["body"]).top_managers()


# ── 계약 단계 ────────────────────────────────────────────────────────
def _judge_stages(store: S.Store, snap: E.StageSnapshot, now: datetime) -> SyncResult:
    rows = len(snap.rows) + len(snap.stage_conflicts)
    if store.stage_as_of() is None:   # 한 번도 받은 적 없음(실패·버림 기록과 상관없이 — 저장소가 기억하는 사실)
        codes = []
        if not snap.plausible():
            codes.append(CODE_IMPLAUSIBLE_FIRST)
        per_key = Counter(r.stage_key for r in snap.rows.values())
        if any(per_key.get(k, 0) == 0 for k in FIRST_REQUIRED_STAGES):
            codes.append(CODE_STAGE_EMPTY_FIRST)
        if codes:
            try:
                hid = store.refuse_stages(snap, codes)
            except S.StoreRefused:
                return _refused_plain(store, S.SYNC_STAGES, tuple(codes) + (CODE_STORE_REFUSED,), now, rows)
            return SyncResult(S.SYNC_STAGES, S.SYNC_REFUSED, tuple(codes), rows=rows, needs_confirmation=True,
                              alert=True, hold_id=hid)
    try:
        counts = store.record_prospects(snap)
    except S.SyncBraked as b:
        return SyncResult(S.SYNC_STAGES, S.SYNC_BRAKED, b.reasons, rows=rows, absent=b.would_absent,
                          needs_confirmation=True, alert=True, hold_id=b.hold_id)
    except S.StoreRefused:
        return _refused_plain(store, S.SYNC_STAGES, (CODE_STORE_REFUSED,), now, rows)
    return SyncResult(S.SYNC_STAGES, S.SYNC_ACCEPTED, (), rows=counts.present, absent=counts.now_absent)


def sync_stages(reader: E.ErpReader, store: S.Store, now: datetime) -> SyncResult:
    """계약 단계를 한 번 받는다(회차마다 새 reader · 읽기 마감 있음)."""
    _need_time(now)
    _need_fresh_reader(reader)
    try:
        snap = reader.read_stages(deadline=_stages_deadline(now))
    except E.ErpError as e:
        return _failed(store, S.SYNC_STAGES, _erp_code(e), now, STAGES_ALERT_AFTER)
    except _UNEXPECTED:
        return _failed(store, S.SYNC_STAGES, CODE_UNEXPECTED, now, STAGES_ALERT_AFTER)
    try:
        return _judge_stages(store, snap, now)
    except _UNEXPECTED:
        return _failed(store, S.SYNC_STAGES, CODE_UNEXPECTED, now, STAGES_ALERT_AFTER)


def confirm_stages(store: S.Store, now: datetime, confirmed_by: int, hold_id: int) -> SyncResult:
    """대표가 본 그 멈춤·버림의 목록을 받는다 — ① 을 새로 읽지 않는다(확인한 것과 받는 것이 같게)."""
    _need_time(now)
    _need_person(confirmed_by)
    if isinstance(hold_id, bool) or not isinstance(hold_id, int) or hold_id <= 0:
        return SyncResult(S.SYNC_STAGES, S.SYNC_REFUSED, (S.HOLD_NOT_FOUND,))
    try:
        counts = store.confirm_prospects_hold(hold_id, confirmed_by)
    except S.HoldRefused as e:
        return SyncResult(S.SYNC_STAGES, S.SYNC_REFUSED, (e.code,))
    except S.StoreRefused:
        return SyncResult(S.SYNC_STAGES, S.SYNC_REFUSED, (CODE_STORE_REFUSED,), alert=True)
    return SyncResult(S.SYNC_STAGES, S.SYNC_ACCEPTED, (S.CODE_CONFIRMED,), rows=counts.present,
                      absent=counts.now_absent)


# ── 언제 부르나 ──────────────────────────────────────────────────────
def _stages_deadline(now: datetime) -> datetime:
    """읽기 마감 = 지금 + ``STAGES_MAX_READ`` 와 다음 조용한 창 시작 중 이른 때(창 안이면 지금 — 곧바로 멈춘다)."""
    local = now.astimezone(S.KST)
    t = local.time()
    if any(a <= t < b for a, b in STAGES_QUIET):
        return now
    starts = [datetime.combine(local.date() + timedelta(days=d), a, tzinfo=S.KST)
              for d in (0, 1) for a, _ in STAGES_QUIET]
    nxt = min(s for s in starts if s > local)
    return min(now + STAGES_MAX_READ, nxt)


def _hold_open(store: S.Store, kind: str, now: datetime) -> bool:
    """대표 확인을 기다리는 붙잡음이 있는가 — 있으면 새로 읽지 않는다(새로 읽으면 대표가 보던 붙잡음이 바뀐다)."""
    h = store.hold(kind)
    return h is not None and h["used_at"] is None and h["at"] <= now + CLOCK_SKEW and now - h["at"] <= S.HOLD_TTL


def org_due(store: S.Store, now: datetime) -> bool:
    """마지막 시도(결과 무관)가 1시간 넘게 지났으면 부른다 — 확인을 기다리는 붙잡음(3시간 안)이 있으면 부르지 않는다."""
    _need_time(now)
    last = store.last_sync(S.SYNC_ORG)
    if last is None:
        return True
    at = _aware(last["at"])
    if at is None or at > now + CLOCK_SKEW:   # 시계를 뒤로 고쳤다 — 그 시각까지 조용히 기다리지 않는다
        return True
    if _hold_open(store, S.SYNC_ORG, now):
        return False
    return now - at >= ORG_EVERY


def stages_due(store: S.Store, now: datetime) -> bool:
    """읽기 마감까지 조용한 창이 없고 · 확인을 기다리는 붙잡음이 없고 · 마지막 시도가 1시간 넘게 지났고 ·
    마지막으로 받은 지 6시간 넘었으면 부른다."""
    _need_time(now)
    if _stages_deadline(now) < now + STAGES_MAX_READ:
        return False
    last = store.last_sync(S.SYNC_STAGES)
    if last is not None:
        at = _aware(last["at"])
        if at is None or at > now + CLOCK_SKEW:
            return True
        if _hold_open(store, S.SYNC_STAGES, now):
            return False
        if now - at < STAGES_RETRY:
            return False
    got = store.stage_as_of()
    return got is None or got > now + CLOCK_SKEW or now - got >= STAGES_EVERY
