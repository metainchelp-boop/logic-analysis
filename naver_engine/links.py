"""네이버 대행 연결 목록 · 짝 맞추기 · 이관 빠짐 (설계 v1.8 S8 · 반박 H1 · H4 · J3 · S7 뒤 조각 몫 ⑵ · ⑶).

**이관** = 광고주 광고계정이 우리 회사(대행사 관리계정)에 연결된 상태 — 대행 연결 목록에 있으면 이관됨(대표 정의
2026-09-29). 대표 지시 「대시보드에서 접속 상태가 끊긴 것을 감지 · 끊긴 것을 이관이 빠진 것으로 확인」 — 광고주 계정에
들어가지 못했다는 신호(점검 실패)가 아니라 **대행 연결 목록에서 빠졌는지**로 판정한다.

연결 목록(``sync_accounts``) — 하루 한 번(06:30 뒤)
- 네이버 관문이 **전부 받았을 때만** 만드는 ``ChildAccounts`` 만 저장소에 넘긴다. 일부만 받음 · 네이버 오류 · 호출 상한은
  실패 결과로 돌려주고 계정 표에는 아무것도 적지 않는다.
- 저장소 브레이크(한꺼번에 · 관리계정 번호 단위 · 기준선 누적 · **확인한 짝이 있는 계정**)가 걸리면 붙잡아 두고
  ``confirm_accounts`` 가 네이버를 **새로 읽지 않고** 그 목록을 받는다(S7 과 같은 방식 · 3시간 · 한 번).
- 멈춘 날 · 실패한 날은 계정 표를 바꾸지 않으므로 「목록에 없음」 날짜도 늘지 않는다 — 확인한 짝이 멈춤·실패 때문에
  「이관 빠짐」이 되지 않는다.
- 받은 목록에 광고계정 번호가 없거나 겹친 계정이 있으면 받되 알린다(``ACCOUNTS_UNUSABLE``) — 짝 규칙이 그 목록을 쓸 수
  없으므로 짝 맞추기는 ① 을 부르지 않고 기다린다(30분마다 ① 을 두드리며 같은 버림을 쌓지 않게 · 검토 pairing-002).
- 저장된 목록 시각이 지금보다 미래(시계를 뒤로 고침)면 네이버를 읽지 않고 실패로 남긴다(``CLOCK_BEHIND`` · 알림은 처음
  한 번) — 더 이른 시각의 목록은 저장소가 받지 않으므로 읽어도 버려질 뿐이다(검토 sync-3).

짝 맞추기(``pair_links``)
- 입력은 넷 — 저장소가 **마지막으로 전부 받은 연결 목록**(``ACCOUNTS_MAX_AGE`` 안) · 계약 단계(점검 손잡이와 같은 72시간 안) ·
  사람 판단(계정마다 가장 늦은 확인 하나 — 저장소가 고른다) · ① 에 적힌 네이버 고객 번호(회차마다 읽는다 · ① 목록을
  통째로 저장하지 않는다 — 막힘 줄만 짝 확인 화면 S11 이 보여 줄 수 있게 적힌 번호를 남긴다 · 사유 ``ad-account-number``
  줄의 번호 칸은 광고계정 번호다 → 막힘 줄을 계정 표에 이어 읽지 말 것).
  연결 목록·단계가 없거나 낡았으면 ① 을 부르지 않고 버린다.
- 관리 대상 가망 = 단계 목록에 있고 · 단계 겹침이 없고 · 종료일을 읽었고 · 점검 손잡이와 **같은 규칙**
  (``handles.eligibility_reason``)을 통과한 가망. 끝난 지 14일 넘은 가망은 짝을 맞추지 않는다.
- 짝 규칙은 ``app.naver_auto.matching.match`` 한 곳이다(확인한 짝 > 자동 짝 · 이름 후보는 사람 확인 전 안 들어감).
- **이어졌던 짝의 계정이 오늘 목록에 없으면** — 서로 다른 날짜 두 번 이상(``LINK_BROKEN_MIN_DAYS``) **그리고** 처음 빠진
  읽기부터 마지막으로 빠진 읽기까지 20시간 이상(``LINK_BROKEN_MIN_SPAN`` — 자정을 사이에 둔 두 번은 「2일」이 아니다)이면
  「이관 빠짐」(확인 필요 예), 아니면 「오늘 이관 목록에 없음」. 이어졌던 짝 = ⑴ 사람이 확인한 짝(살아 있는 확인) ·
  ⑵ ① 에 적힌 고객 번호로 **자동 짝이 된 적 있는** 짝(``store.matched_before("auto")``) 중 ① 에 그 번호가 아직 적혀 있는 것.
  한 번도 이어진 적 없는 번호(① 에만 적힘 · 목록에 없음)는 「이관 안 됨」(막힘 ``not-linked``)이지 이관 빠짐이 아니다.
  확인한 계정이 한 번도 목록에 없었으면 바로 이관 빠짐(``never-listed``).
- **짝 무효는 사람 판단 표에 적지 않는다** — 매일 새로 계산한다(계정이 목록에 돌아오면 짝이 그대로 산다).
- 같은 계정을 다른 가망에 더 늦게 확인해 밀린 확인은 「밀린 확인」 줄로 남긴다(짝 확인 화면 S11 이 보여 준다).
- 결과는 ``record_pairing`` 이 회차로 쌓는다(가망·계정 번호 · 상태 · 코드 — 이름 없음). 계산하는 사이 입력이 바뀌면
  (``PairingStale``) 버리고 다음에 다시 맞춘다.

공통
- 오류·검사 탈락은 예외가 아니라 결과로 돌려준다(스케줄러가 멈추지 않게) · 기록에는 코드와 개수만. 부르는 모양이 틀린 것
  (프로그램 결함 · 관문의 안전 거절)은 결과로 덮지 않고 드러낸다.
- 회차마다 새 ``NaverReader`` · 새 ``ErpReader`` 를 넘긴다(호출 상한이 객체 평생 누적).
- 시각은 부르는 쪽이 넣는다(``now`` · 시간대 필수). 이 모듈은 네트워크를 직접 열지 않는다(관문 두 개만).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Mapping, Optional, Tuple

from app.naver_auto import matching as M

from . import erp_read as E
from . import handles as H
from . import naver_read as N
from . import store as S
from . import sync as Y

ACCOUNTS_START = time(6, 30)               # 아침 점검 시작(설계 §점검 06:30~08:00) — 그날 목록은 이 뒤에 받는다
ACCOUNTS_RETRY = timedelta(minutes=30)     # 실패·멈춤 뒤 다시 부르기까지
ACCOUNTS_ALERT_AFTER = timedelta(hours=26)  # 연결 목록을 이만큼 넘게 못 받으면 알린다(하루 한 번 + 여유)
ACCOUNTS_MAX_AGE = timedelta(hours=30)     # 짝 맞추기에 쓸 수 있는 연결 목록의 나이(어제 목록까지 · 그보다 낡으면 맞추지 않음)
LINK_BROKEN_MIN_DAYS = 2                   # 「연결 끊김」 — 서로 다른 날짜 두 번 이상 목록에 없고
LINK_BROKEN_MIN_SPAN = timedelta(hours=20)  # 처음 빠진 읽기부터 마지막으로 빠진 읽기까지 20시간 이상(자정 앞뒤 두 번 ≠ 2일)
PAIRING_RETRY = timedelta(minutes=30)      # 짝 맞추기를 어떤 결과로든 시도한 뒤 다시 맞추기까지(① 읽기 간격 30분 이상 약속)
PAIRING_ALERT_AFTER = timedelta(hours=26)  # 받은 짝 맞추기가 이만큼 넘게 없으면 알린다

CODE_INCOMPLETE = "INCOMPLETE_LIST"        # 네이버 목록을 전부 받지 못함
CODE_RUN_ABORT = "RUN_ABORT"               # 호출 상한 · 속도 제한으로 회차 멈춤
CODE_HANDLE_INVALID = "HANDLE_INVALID"     # 관리계정 손잡이를 쓸 수 없음(발급한 날이 지남 등)
CODE_ACCOUNTS_NONE = "ACCOUNTS_NONE"       # 연결 목록을 한 번도 받지 않음
CODE_ACCOUNTS_STALE = "ACCOUNTS_STALE"     # 연결 목록이 낡음(``ACCOUNTS_MAX_AGE``)
CODE_STAGES_NONE = "STAGES_NONE"           # 계약 단계를 한 번도 받지 않음
CODE_STAGES_STALE = "STAGES_STALE"         # 계약 단계가 낡음(점검 손잡이와 같은 72시간)
CODE_BAD_INPUT = "BAD_INPUT"               # 짝 규칙이 입력을 거절(광고계정 번호 없음 · 겹침 등) — 저장된 목록·① 쪽 문제
CODE_ACCOUNTS_HELD = "ACCOUNTS_HELD"       # 경고: 연결 목록 확인 대기 중 — 마지막으로 받은 목록으로 맞췄다
CODE_STAGES_HELD = "STAGES_HELD"           # 경고: 계약 단계 확인 대기 중 — 마지막으로 받은 단계로 맞췄다
CODE_NEVER_LISTED = S.PAIR_CODE_NEVER_LISTED   # 결과 줄 사유: 확인한 계정이 한 번도 연결 목록에 없었음
CODE_ACCOUNTS_UNUSABLE = "ACCOUNTS_UNUSABLE"   # 받은 연결 목록에 광고계정 번호가 없거나 겹친 계정 — 짝 규칙이 못 씀
CODE_CLOCK_BEHIND = "CLOCK_BEHIND"         # 저장된 연결 목록 시각이 지금보다 미래 — 시계를 뒤로 고쳤다

# 네이버 목록 브레이크는 모두 대표 확인으로 풀 수 있다(목록이 정말로 줄었을 수 있다)
CONFIRMABLE_ACCOUNT_CODES = frozenset({S.BRAKE_TOTAL, S.BRAKE_MANAGER, S.BRAKE_BASELINE, S.BRAKE_CONFIRMED})

_UNEXPECTED = Y._UNEXPECTED


@dataclass(frozen=True)
class PairingOutcome:
    outcome: str                         # accepted · refused · failed
    codes: Tuple[str, ...] = ()          # 버림·실패 이유(받았으면 경고 코드)
    pairing_id: Optional[int] = None     # 받은 회차 번호 — ``store.pairing_rows`` 로 줄을 읽는다
    counts: Optional[Dict[str, int]] = field(default=None, compare=False)
    alert: bool = False                  # 대표에게 알릴 것(S10)

    def __repr__(self) -> str:   # 코드·개수만
        return (f"PairingOutcome(outcome={self.outcome}, codes={list(self.codes)}, pairing_id={self.pairing_id}, "
                f"counts={self.counts}, alert={self.alert})")


def _need_fresh_naver(reader) -> None:
    calls, pauses = getattr(reader, "calls", None), getattr(reader, "pauses", None)
    if isinstance(calls, bool) or calls != 0 or isinstance(pauses, bool) or pauses != 0:
        raise ValueError("회차마다 새 NaverReader 를 넘겨야 합니다(호출 상한은 객체 평생 누적)")


def _naver_code(e: N.NaverApiError) -> str:
    st = e.status
    if isinstance(st, int) and not isinstance(st, bool) and 100 <= st <= 599:
        return f"{e.kind}-{st}"
    return e.kind


def _local_start(now: datetime) -> datetime:
    local = now.astimezone(S.KST)
    return datetime.combine(local.date(), ACCOUNTS_START, tzinfo=S.KST)


def _accounts_unusable(store: S.Store) -> bool:
    """목록에 있는 계정 중 광고계정 번호가 없거나 두 계정이 같은 번호 — 짝 규칙(번호 공간 가르기)이 이 목록을 거절한다."""
    nos = [a["ad_account_no"] for a in store.accounts() if a["present"] == 1]
    return any(n is None for n in nos) or len(set(nos)) != len(nos)


# ── 연결 목록 ────────────────────────────────────────────────────────
def sync_accounts(reader: N.NaverReader, store: S.Store, now: datetime) -> Y.SyncResult:
    """대행 연결 목록을 한 번 받는다(회차마다 새 reader)."""
    Y._need_time(now)
    _need_fresh_naver(reader)
    kind = S.SYNC_ACCOUNTS
    got = store.accounts_read_at()
    if got is not None and got > now + Y.CLOCK_SKEW:   # 더 이른 목록은 받지 않는다 — 네이버를 읽어도 버려질 뿐
        last = store.last_sync(kind)
        first = last is None or CODE_CLOCK_BEHIND not in last["codes"]
        store.record_sync_event(kind, S.SYNC_FAILED, (CODE_CLOCK_BEHIND,), now)
        return Y.SyncResult(kind, S.SYNC_FAILED, (CODE_CLOCK_BEHIND,), alert=first)
    try:
        kids = reader.list_all_children(reader.manager_handle())
    except N.IncompleteList:
        return Y._failed(store, kind, CODE_INCOMPLETE, now, ACCOUNTS_ALERT_AFTER)
    except N.NaverApiError as e:
        return Y._failed(store, kind, _naver_code(e), now, ACCOUNTS_ALERT_AFTER)
    except N.RunAbort:
        return Y._failed(store, kind, CODE_RUN_ABORT, now, ACCOUNTS_ALERT_AFTER)
    except H.HandleInvalid:
        return Y._failed(store, kind, CODE_HANDLE_INVALID, now, ACCOUNTS_ALERT_AFTER)
    except _UNEXPECTED:
        return Y._failed(store, kind, Y.CODE_UNEXPECTED, now, ACCOUNTS_ALERT_AFTER)
    rows = len(kids.accounts)
    try:
        counts = store.record_accounts(kids, now)
    except S.SyncBraked as b:
        return Y.SyncResult(kind, S.SYNC_BRAKED, b.reasons, rows=rows, absent=b.would_absent,
                            needs_confirmation=True, alert=True, hold_id=b.hold_id)
    except S.StoreRefused:
        return Y._refused_plain(store, kind, (Y.CODE_STORE_REFUSED,), now, rows)
    except _UNEXPECTED:
        return Y._failed(store, kind, Y.CODE_UNEXPECTED, now, ACCOUNTS_ALERT_AFTER)
    if _accounts_unusable(store):
        return Y.SyncResult(kind, S.SYNC_ACCEPTED, (CODE_ACCOUNTS_UNUSABLE,), rows=counts.present,
                            absent=counts.now_absent, alert=True)
    return Y.SyncResult(kind, S.SYNC_ACCEPTED, (), rows=counts.present, absent=counts.now_absent)


def confirm_accounts(store: S.Store, now: datetime, confirmed_by: int, hold_id: int) -> Y.SyncResult:
    """대표가 본 그 멈춤의 연결 목록을 받는다 — 네이버를 새로 읽지 않는다(확인한 것과 받는 것이 같게).
    **확인하는 사람이 대표인지는 부르는 쪽(S11 화면 API · scope)이 판정한다.**"""
    Y._need_time(now)
    Y._need_person(confirmed_by)
    kind = S.SYNC_ACCOUNTS
    if isinstance(hold_id, bool) or not isinstance(hold_id, int) or hold_id <= 0:
        return Y.SyncResult(kind, S.SYNC_REFUSED, (S.HOLD_NOT_FOUND,))
    hold = store.hold(kind)
    if hold is not None and hold["hold_id"] == hold_id and not set(hold["codes"]) <= CONFIRMABLE_ACCOUNT_CODES:
        return Y.SyncResult(kind, S.SYNC_REFUSED, (Y.CODE_STORE_REFUSED,), alert=True)
    try:
        counts = store.confirm_accounts_hold(hold_id, confirmed_by)
    except S.HoldRefused as e:
        return Y.SyncResult(kind, S.SYNC_REFUSED, (e.code,))
    except S.StoreRefused:
        return Y.SyncResult(kind, S.SYNC_REFUSED, (Y.CODE_STORE_REFUSED,), alert=True)
    unusable = _accounts_unusable(store)
    return Y.SyncResult(kind, S.SYNC_ACCEPTED, (S.CODE_CONFIRMED,) + ((CODE_ACCOUNTS_UNUSABLE,) if unusable else ()),
                        rows=counts.present, absent=counts.now_absent, alert=unusable)


def accounts_due(store: S.Store, now: datetime) -> bool:
    """오늘 06:30 뒤이고 · 확인을 기다리는 붙잡음이 없고 · 마지막 시도가 30분 넘게 지났고 · 오늘 06:30 뒤에 받은 목록이
    없으면 부른다."""
    Y._need_time(now)
    start = _local_start(now)
    if now < start:
        return False
    last = store.last_sync(S.SYNC_ACCOUNTS)
    if last is not None:
        at = Y._aware(last["at"])
        if at is None or at > now + Y.CLOCK_SKEW:   # 시계를 뒤로 고쳤다 — 그 시각까지 조용히 기다리지 않는다
            return True
        if Y._hold_open(store, S.SYNC_ACCOUNTS, now):
            return False
        if now - at < ACCOUNTS_RETRY:
            return False
    got = store.accounts_read_at()
    return got is None or got > now + Y.CLOCK_SKEW or got < start


# ── 연결 끊김 ────────────────────────────────────────────────────────
def link_state(times: Optional[Mapping]) -> Tuple[str, Optional[str]]:
    """이어졌던 짝의 계정이 오늘 목록에 없을 때 — (상태, 사유 코드). ``times`` = ``store.account_times()`` 의 그 계정 값.

    - 계정 표에 줄이 없음(한 번도 목록에 없던 계정) → 「이관 빠짐」(``never-listed``)
    - 서로 다른 날짜 두 번 이상 · 처음 빠진 읽기부터 마지막으로 빠진 읽기까지 20시간 이상 → 「이관 빠짐」
    - 그 밖(첫날 · 자정 앞뒤 두 번 · 시각을 모르는 옛 계정) → 「오늘 이관 목록에 없음」"""
    if times is None:
        return S.PAIR_BROKEN, CODE_NEVER_LISTED
    since, last = times.get("absent_since"), times.get("absent_last_at")
    if times.get("present") != 1 and times.get("absent_days", 0) >= LINK_BROKEN_MIN_DAYS \
            and since is not None and last is not None and last - since >= LINK_BROKEN_MIN_SPAN:
        return S.PAIR_BROKEN, None
    return S.PAIR_MISSING, None


# ── 짝 맞추기 ────────────────────────────────────────────────────────
def _usable(t: Optional[datetime], now: datetime, max_age: timedelta) -> Optional[str]:
    """None = 쓸 수 있음 · "none" = 없음 · "stale" = 낡음(또는 미래)."""
    if t is None:
        return "none"
    if t > now + Y.CLOCK_SKEW or now - t > max_age:
        return "stale"
    return None


def _input_problems(store: S.Store, now: datetime):
    read_at, stage_at = store.accounts_read_at(), store.stage_as_of()
    codes = []
    a = _usable(read_at, now, ACCOUNTS_MAX_AGE)
    if a is not None:
        codes.append(CODE_ACCOUNTS_NONE if a == "none" else CODE_ACCOUNTS_STALE)
    elif _accounts_unusable(store):   # 짝 규칙이 거절할 목록 — ① 을 두드리지 않는다(연결 목록 받기가 알린다)
        codes.append(CODE_ACCOUNTS_UNUSABLE)
    s = _usable(stage_at, now, H.STAGE_MAX_AGE)
    if s is not None:
        codes.append(CODE_STAGES_NONE if s == "none" else CODE_STAGES_STALE)
    return read_at, stage_at, tuple(codes)


def _scope(store: S.Store, stage_at: datetime, now: datetime) -> List[M.ErpProspect]:
    """관리 대상 가망 — 단계 목록에 있고 · 겹침 없고 · 종료일을 읽었고 · 점검 손잡이 규칙을 통과한 것."""
    out = []
    for p in store.prospects():
        if p["present"] != 1 or p["stage_conflict"] or p["end_unreadable"]:
            continue
        end = None if p["latest_end_date"] is None else date.fromisoformat(p["latest_end_date"])
        if H.eligibility_reason(p["stage_key"], stage_at, end, now) is not None:
            continue
        out.append(M.ErpProspect(p["possibility_id"], p["name"]))
    return out


def _pairing_failure_alert(store: S.Store, now: datetime) -> bool:
    ok = store.last_pairing(S.SYNC_ACCEPTED)
    return ok is None or now - ok["at"] >= PAIRING_ALERT_AFTER


def _pairing_refused(store: S.Store, now: datetime, codes, alert: bool = True) -> PairingOutcome:
    codes = Y._unique(codes)
    store.record_pairing_event(now, S.SYNC_REFUSED, codes)
    return PairingOutcome(S.SYNC_REFUSED, codes, alert=alert)


def _pairing_failed(store: S.Store, now: datetime, code: str) -> PairingOutcome:
    store.record_pairing_event(now, S.SYNC_FAILED, (code,))
    return PairingOutcome(S.SYNC_FAILED, (code,), alert=_pairing_failure_alert(store, now))


def _rows(result: M.PairingResult, winners, lost, times: Mapping, scope_ids, auto_before) -> List[dict]:
    confirmed = {(d.possibility_id, d.customer_id): d.decision_id for d in winners if d.decision == "confirmed"}
    confirmed_cids = {cid for _pid, cid in confirmed}
    rows = []
    for p in result.pairs:
        r = {"state": p.link, "possibility_id": p.possibility_id, "customer_id": p.customer_id,
             "code": p.name_relation}
        if p.link == S.PAIR_CONFIRMED:
            r["decision_id"] = confirmed[(p.possibility_id, p.customer_id)]
        rows.append(r)
    for pid, cid in result.confirmed_missing:
        state, code = link_state(times.get(cid))
        rows.append({"state": state, "possibility_id": pid, "customer_id": cid, "code": code,
                     "decision_id": confirmed[(pid, cid)], "link": S.PAIR_CONFIRMED})
    for b in result.blocked:
        key = (b.possibility_id, b.customer_id)
        if b.reason == M.B_NOT_LINKED and b.customer_id is not None:
            if key in confirmed:
                continue   # 확인한 짝의 이관 빠짐 줄이 이미 말한다(같은 계정을 막힘으로 한 번 더 세지 않는다)
            if key in auto_before and b.customer_id not in confirmed_cids:
                # 자동 짝으로 이어졌던 계정이 목록에서 빠짐 — 「이관 안 됨」이 아니라 이관 빠짐(오늘 없음)
                state, code = link_state(times.get(b.customer_id))
                rows.append({"state": state, "possibility_id": b.possibility_id, "customer_id": b.customer_id,
                             "code": code, "link": S.PAIR_AUTO})
                continue
        rows.append({"state": S.PAIR_BLOCKED, "possibility_id": b.possibility_id, "customer_id": b.customer_id,
                     "code": b.reason})
    for c in result.candidates:
        rows.append({"state": S.PAIR_CANDIDATE, "possibility_id": c.possibility_id, "customer_id": c.customer_id,
                     "code": c.relation, "same_name": c.same_name_accounts, "claimed_elsewhere": c.claimed_elsewhere})
    for d in lost:
        if d.possibility_id in scope_ids:   # 관리 대상 가망의 밀린 확인만 보여 준다
            rows.append({"state": S.PAIR_SUPERSEDED, "possibility_id": d.possibility_id, "customer_id": d.customer_id,
                         "decision_id": d.decision_id})
    return rows


def _warnings(store: S.Store, now: datetime) -> Tuple[str, ...]:
    out = []
    if Y._hold_open(store, S.SYNC_ACCOUNTS, now):
        out.append(CODE_ACCOUNTS_HELD)
    if Y._hold_open(store, S.SYNC_STAGES, now):
        out.append(CODE_STAGES_HELD)
    return tuple(out)


def pair_links(reader: E.ErpReader, store: S.Store, now: datetime) -> PairingOutcome:
    """짝을 한 번 맞춘다(회차마다 새 reader) — 결과는 저장소에 회차로 쌓인다."""
    Y._need_time(now)
    Y._need_fresh_reader(reader)
    read_at, stage_at, problems = _input_problems(store, now)
    if problems:   # 쓸 수 없는 입력으로 ① 을 두드리지 않는다
        return _pairing_refused(store, now, problems)
    try:
        ids = reader.read_naver_customer_ids()
    except E.ErpError as e:
        return _pairing_failed(store, now, Y._erp_code(e))
    except _UNEXPECTED:
        return _pairing_failed(store, now, Y.CODE_UNEXPECTED)
    try:
        scope = _scope(store, stage_at, now)
        winners, lost = store.link_decisions()
        saved_accounts = store.accounts()
        accounts = {a["customer_id"]: {"customerId": a["customer_id"], "adAccountNo": a["ad_account_no"],
                                       "adAccountName": a["account_name"]}
                    for a in saved_accounts if a["present"] == 1}
        previous = {}
        for a in saved_accounts:
            if a["present"] == 0 and a["ad_account_no"] is not None:
                previous.setdefault(a["ad_account_no"], set()).add(a["customer_id"])
        previous = {no: next(iter(cids)) for no, cids in previous.items() if len(cids) == 1}
        creds = [M.ErpCredential(r.possibility_id, r.vendor, r.customer_id_raw,
                                ad_account_no_raw=r.ad_account_no_raw) for r in ids]
        decisions = [M.HumanDecision(d.possibility_id, d.customer_id, d.decision) for d in winners]
        result = M.match(scope, creds, accounts, decisions, accounts_complete=True, previous_ad_accounts=previous)
        rows = _rows(result, winners, lost, store.account_times(), {p.possibility_id for p in scope},
                     store.matched_before(S.PAIR_AUTO))
    except M.BadInput:
        return _pairing_refused(store, now, (CODE_BAD_INPUT,))
    except _UNEXPECTED:
        return _pairing_failed(store, now, Y.CODE_UNEXPECTED)
    warnings = _warnings(store, now)
    try:
        pid = store.record_pairing(now, accounts_read_at=read_at, stages_as_of=stage_at,
                                   decision_ids=[d.decision_id for d in winners + lost], rows=rows,
                                   counts={"prospects": len(scope), "ignored": result.ignored_rows}, codes=warnings)
    except S.PairingStale:
        return _pairing_refused(store, now, (S.CODE_INPUTS_CHANGED,), alert=False)   # 다음 회차에 다시 맞춘다
    except S.StoreRefused:
        return _pairing_refused(store, now, (Y.CODE_STORE_REFUSED,))
    return PairingOutcome(S.SYNC_ACCEPTED, warnings, pairing_id=pid, counts=dict(store.pairing_run(pid)["counts"]))


def pairing_due(store: S.Store, now: datetime) -> bool:
    """유효한 연결 목록·단계가 있으면 30분 간격으로 전산 번호 변경도 다시 읽는다.

    전산 입력은 엔진에 저장하지 않아 목록/사람 판단 지문만으로 변경을 알 수 없다.
    실패 재시도도 기존 30분 제한을 유지한다. 네이버 전체 목록 재조회 주기는 바꾸지 않는다.
    """
    Y._need_time(now)
    read_at, stage_at, problems = _input_problems(store, now)
    if problems:
        return False   # 입력 쪽 동기화가 알린다 — 쓸 수 없는 입력으로 버림 기록을 쌓지 않는다
    last = store.last_pairing()
    if last is not None:
        if last["at"] > now + Y.CLOCK_SKEW:
            return True
        if now - last["at"] < PAIRING_RETRY:
            return False
    ok = store.last_pairing(S.SYNC_ACCEPTED)
    if ok is None:
        return True
    if ok["at"].astimezone(S.KST).date() != now.astimezone(S.KST).date():
        return True
    return (ok["accounts_read_at"] != read_at or ok["stages_as_of"] != stage_at
            or ok["decisions_hash"] != store.decision_fingerprint()
            or now - ok["at"] >= PAIRING_RETRY)
