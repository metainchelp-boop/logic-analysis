"""관제 화면 자료 — **범위 안의 것만** · 판정은 ``verdict.judge`` 한 곳 · 저장소는 읽기만(설계 v1.7 · v1.8 S11 · v1.4 §5).

누가 무엇을 보는지는 ``backend/app/naver_auto/scope.py`` 한 곳이 정한다. 이 파일은 그 결과(보이는 가망 번호 · 관계 · 할 수
있는 일)로 화면 자료를 모을 뿐이다 — 담당 칸(메인·서브·직전)을 직접 읽어 가르지 않는다(구문 시험이 고정).

지키는 것
- **범위 밖 = 없음.** 숫자(5칸 · 원인별 묶음 · 표 · 계약 끝남 · 이관 안 됨 · 짝 확인)는 모두 보이는 가망만 센다 — 범위가 다른
  두 사람의 숫자로 범위 밖 광고주 수를 추론할 수 없다. 한 장·쓰기의 없는 번호와 범위 밖 번호는 같은 문구(``CLIENT_NOT_VISIBLE``).
- **판정 조립(S9·S10 약속)** — 가장 늦게 받은 짝 맞추기의 짝마다, **그 짝 맞추기가 오늘 것일 때만** 오늘 계정 하루치를 쓰고,
  계정 하루치의 가망이 짝의 가망과 같을 때만 「오늘 결과」다. 어제 짝 맞추기의 「오늘 없음」·「이관 빠짐」을 오늘 것으로 넣지
  않는다(점검 전 · 점검 안 됨). 판정 함수가 받지 않는 저장 값은 ⚪ 점검 안 됨(확인 필요)으로 — 화면이 멈추지 않게.
- **고객 번호는 끝 4자리만** · 짝 후보는 서버가 만든 가리킴표(``ref``)로만 가리킨다(번호 원문을 화면에 주지 않는다) ·
  다른 가망의 후보이기도 하면 「다른 후보 있음」만(누구인지 밝히지 않는다).
- **실패한 곳 수는 대표만**(엔진 상태 띠 · v1.4 §5) · 붙잡음(대표 확인)도 대표만.
- 🔔 는 **나에게 온 줄만**(범위 고르기와 상관없다) · 문구는 ``alerts.render`` 한 곳(이름·금액·번호가 들어갈 자리가 없다).
- **12시간 안 풀린 🟡 는 한 단계 위로**(v1.4 §6 · §7) — 🆕 가 된 뒤 12시간이 지나도 👀 확인이 없으면 ``todo_chain`` 의 다음
  묶음(팀장 → 상위 팀장 → 대표)에게 「올라온 일」로 보인다. 올라간 사람은 이미 그 광고주를 볼 수 있다(할 일 줄 ⊆ 여는 사람).
"""
from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from app.naver_auto import issues as IS
from app.naver_auto import matching as M
from app.naver_auto import org_snapshot as O
from app.naver_auto import scope as SC
from app.naver_auto import thresholds as T
from app.naver_auto import verdict as V

from . import alerts as AL
from . import handles as H
from . import management as MG
from . import store as S
from . import sync as Y

KST = S.KST
DEADLINE_AT = time(8, 0)                 # 점검 마감 — verdict 의 「점검 전 / 점검 안 됨」 경계
HISTORY_DAYS = 14                        # 광고주 한 장 현황
BELL_DAYS = 14                           # 🔔 에 보이는 기간
ESCALATE_AFTER = timedelta(hours=12)     # 🟡 이 🆕 인 채 이만큼 지나면 한 단계 위로(v1.4 §6)
ISSUE_OPEN = frozenset({"new", "ack"})   # 「확인할 일」(예외 🙈 는 빼고)
LINK_ROW_STATES = frozenset({S.PAIR_CONFIRMED, S.PAIR_AUTO, S.PAIR_MISSING, S.PAIR_BROKEN})
# 짝 확인 화면에 보일 줄 — 자동 짝도 사람이 확인하기 전까지는 여기서 「이 계정 맞음」·「아님」을 기다린다(설계 v1.8 Q5 · M4 ·
# 계획 7 「자동 짝 목록」 · 검토 auto-pair-never-confirmable)
PENDING_STATES = frozenset({S.PAIR_AUTO, S.PAIR_BLOCKED, S.PAIR_CANDIDATE, S.PAIR_SUPERSEDED, S.PAIR_BROKEN,
                            S.PAIR_MISSING})
LINKABLE_STATES = frozenset({S.PAIR_AUTO, S.PAIR_CANDIDATE, S.PAIR_BLOCKED})   # 「이 계정 맞음」·「아님」을 누를 수 있는 줄
# 짝 맞추기가 「다른 가망이 이 계정을 쥐었다·주장한다」고 말한 막힘(matching.B_CLAIMED_BY_SEVERAL · B_CONFIRMED_ELSEWHERE)
CLAIM_CODES = frozenset({"claimed-by-several", "confirmed-elsewhere"})
CODE_NOT_LINKED = "not-linked"           # matching.B_NOT_LINKED — 한 번도 이관된 적 없음(I3 「이관 안 됨」)
# ① 에 적힌 번호가 고객 번호가 아닌 막힘 — 사람이 「이 계정 맞음」으로 이을 수 없다(번호 자체가 계정이 아니다)
NOT_A_CUSTOMER = frozenset({"ad-account-id-format", "ad-account-not-linked", "account-identifiers-conflict",
                           "ad-account-number", "customer-id-format", "customer-id-length", "ambiguous-space"})
REPORT_PREPARING = "preparing"           # 광고주별 주간·월간 보고서 — 4차
ISSUE_DONE = frozenset({"resolved", "auto_resolved", "closed_unlinked"})   # 닫힌 이슈 — 관제 판 「오늘 풀린 것」(S13)
HAND_KINDS = frozenset({"acked", "resolved", "excepted"})   # 사람이 누른 기록 — 이슈 줄에 「누가 · 언제」(S13)
# 이슈가 다시 시작된 기록 — 이보다 앞선 사람 손길은 지난 일이다(예외가 끝나 🆕 로 돌아온 줄에 옛 사유를 붙이지 않게 ·
# 검토 hand-stale-after-reset). 🔁 저절로 풀림 · 짝이 사라져 닫힘도 사람 손길 뒤의 기계 일이라 그 앞 손길을 싣지 않는다.
RESET_KINDS = frozenset({"opened", "reappeared", "exception_ended", "auto_resolved", "closed_unlinked"})
# 관제 판 이관 칸(S13) — 가망마다 오늘 짝 맞추기 줄에서 한 값. 「pending」 = 오늘 짝 맞추기 전(어제 것을 오늘로 보이지 않게)
LINK_LISTED, LINK_MISSING, LINK_BROKEN, LINK_NOT_LINKED, LINK_NONE, LINK_PENDING = (
    "listed", "missing", "broken", "not_linked", "none", "pending")
LINK_KINDS = (LINK_LISTED, LINK_MISSING, LINK_BROKEN, LINK_NOT_LINKED, LINK_NONE, LINK_PENDING)
# ── 관제 개편(대표 결정 2026-10-06 · D1~D9) — 화면이 세지 않게 서버가 내는 표시용 칸 ─────────────────
# 매일 점검하지 않는 관제 단계(홀딩·환불·만료). 연속 점검(이관 현황 원천이 있을 때)은 이 단계 계정을 매일 읽지 않는다
# (``management.classify`` 「주 1회」) — 그 「아직 안 읽음」은 확인 필요가 아니라 ⚪ 「주 1회 관찰」.
WEEKLY_STAGES = H.MONITORED_STAGES - MG.DAILY_STAGES
# ⚪ 「이어진 계정 없음」의 까닭 — 이관 현황 실관리 분류(``inventory._managed_coverage``)와 같은 순서로 가른다
W_PAIRING_PENDING, W_ID_CONFLICT, W_ID_INVALID, W_NOT_TRANSFERRED, W_NAME_CANDIDATE, W_ID_MISSING = (
    "pairing_pending", "id_conflict", "id_invalid", "not_transferred", "name_candidate", "id_missing")
_W_CONFLICT = frozenset({M.B_IDENTIFIER_CONFLICT, M.B_AMBIGUOUS_SPACE, M.B_CLAIMED_BY_SEVERAL,
                         M.B_CONFIRMED_ELSEWHERE, M.B_NAME_ELSEWHERE})
_W_INVALID = frozenset({M.B_FORMAT, M.B_LENGTH, M.B_AD_FORMAT, M.B_AD_ACCOUNT_NO})
_W_UNLISTED = frozenset({M.B_NOT_LINKED, M.B_AD_NOT_LINKED})
# 숫자 칸 「🔌 연결 안 됨」 — 사람이 광고 계정 ID·연결을 해야 다음 날부터 점검되는 까닭(그 밖 ⚪ 는 「점검 못 함」)
UNLINKED_DETAILS = frozenset({W_ID_MISSING, W_NAME_CANDIDATE, W_ID_CONFLICT, W_ID_INVALID, W_NOT_TRANSFERRED})
_REF_KEY = os.urandom(32)                # 짝 후보 가리킴표 서명 — 이 프로세스만 안다(다시 켜면 화면을 새로 불러온다)
REF_LENGTH = 24


class OrgUnavailable(RuntimeError):
    """조직 수락본이 없거나 못 읽음 — 범위를 계산할 수 없다(화면 API 는 503 · 닫힌 쪽)."""


# ── 요청 하나의 재료 ─────────────────────────────────────────────────
@dataclass(frozen=True)
class Ctx:
    now: datetime
    today: date
    deadline: datetime
    org: O.Org
    freshness: str
    prospects: Mapping[int, dict]            # 가망 번호 → 저장된 가망(목록에 없는 것 포함)
    owns: Mapping[int, SC.Ownership]         # 가망 번호 → 담당(엔진은 가망 번호 = 광고주 번호)
    pairing: Optional[dict]                  # 마지막으로 받은 짝 맞추기
    pairing_today: bool
    rows_by_pid: Mapping[int, Tuple[dict, ...]]
    accounts: Mapping[int, dict]             # 고객 번호 → 계정(이름 · 목록에 있는지)
    checks_today: Mapping[int, dict]         # 고객 번호 → 오늘 계정 하루치 판정 재료
    open_issues: Mapping[int, Tuple[dict, ...]]   # 가망 번호 → 열린 이슈(🆕 · 👀 · 🙈)
    live_decisions: Tuple[S.LinkDecision, ...]   # 살아 있는 사람 판단(짝마다 가장 늦은 · 한 계정의 확인은 하나)
    lost_decisions: Tuple[S.LinkDecision, ...]   # 밀린 확인(뒤 확인을 거두면 다시 산다)
    name_owners: Mapping[str, frozenset]     # 느슨한 상호 → 지금 목록에 있는 가망 번호(계정 이름이 가리키는 가망)
    continuous: bool = False                 # 연속 점검인가(이관 현황 원천이 있다 — 매일 4단계만 매일 읽는다)
    catalog: Optional[dict] = None            # 선택 조회만 현재 ERP 번호를 검증한다. 이미 읽은 요청 원천을 재사용한다.

    def __repr__(self) -> str:
        return f"Ctx(prospects={len(self.prospects)})"


@dataclass(frozen=True)
class InventoryCtx:
    """계정 목록·성과 집계가 사용하는 현재 원천. 구형 판정/이슈 재료는 별도 Ctx에 둔다."""
    now: datetime
    today: date
    org: O.Org
    prospects: Mapping[int, dict]
    accounts: Mapping[int, dict]
    live_decisions: Tuple[S.LinkDecision, ...]

    def __repr__(self) -> str:
        return f"InventoryCtx(prospects={len(self.prospects)})"


def _need_time(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("now 는 시간대가 있는 시각이어야 합니다")


def load_org(store: S.Store) -> O.Org:
    """조직 수락본 — 없거나 못 읽으면 ``OrgUnavailable``."""
    try:
        stored = store.org_current()
        if stored is None:
            raise OrgUnavailable("조직 자료가 없습니다")
        return O.parse_org_snapshot(stored["body"])
    except (S.StoreError, O.SnapshotFormatError):
        raise OrgUnavailable("조직 자료를 읽지 못했습니다") from None


def load_inventory(store: S.Store, now: datetime, org: Optional[O.Org] = None) -> InventoryCtx:
    """요청의 조직/판단/계정을 다시 읽는다. 권한·숨김 단계·정책 판정은 inventory가 현재 원천으로 한다."""
    _need_time(now)
    org = load_org(store) if org is None else org
    prospects = {p["possibility_id"]: p for p in store.prospects()}
    winners, _ = store.link_decisions()
    accounts = {a["customer_id"]: a for a in store.accounts()}
    return InventoryCtx(now, now.astimezone(KST).date(), org, prospects, accounts, tuple(winners))


def load(store: S.Store, now: datetime, org: Optional[O.Org] = None) -> Ctx:
    """화면 요청 하나에 쓰는 재료를 한 번에 읽는다(가망마다 따로 읽지 않게)."""
    _need_time(now)
    org = load_org(store) if org is None else org
    local = now.astimezone(KST)
    today = local.date()
    deadline = datetime.combine(today, DEADLINE_AT, KST)
    prospects = {p["possibility_id"]: p for p in store.prospects()}
    owns = {pid: SC.ownership_for_client(org, pid, pid, SC.MATCH_PID) for pid in prospects}
    # 전체 목록의 숨김/알 수 없는 단계 근거가 들어오면 이전 조직 담당이 남아 있어도
    # 모든 기존 상세·이슈·매칭 경로에서 직원의 접근을 막는다. 대표 진단 범위는 유지한다.
    catalog = store.account_catalog()
    if catalog is not None:
        for row in catalog["items"]:
            pid = row["possibility_id"]
            if pid in owns and (row["stage_hidden"] or not row["stage_known"]):
                owns[pid] = SC.Ownership(client_id=pid, main=None, match=SC.MATCH_UNKNOWN)
    pairing = store.last_pairing(S.SYNC_ACCEPTED)
    rows: Dict[int, List[dict]] = {}
    if pairing is not None:
        for r in store.pairing_rows(pairing["pairing_id"]):
            rows.setdefault(r["possibility_id"], []).append(r)
    issues: Dict[int, List[dict]] = {}
    for i in store.issues(open_only=True):
        issues.setdefault(i["possibility_id"], []).append(i)
    winners, lost = store.link_decisions()
    names: Dict[str, set] = {}
    for pid, p in prospects.items():
        key = M.loose_name(p["name"]) if p["present"] == 1 else None
        if key is not None:
            names.setdefault(key, set()).add(pid)
    return Ctx(now, today, deadline, org, Y.org_freshness(store, now), prospects, owns, pairing,
               pairing is not None and pairing["at"].astimezone(KST).date() == today,
               {k: tuple(v) for k, v in rows.items()}, {a["customer_id"]: a for a in store.accounts()},
               store.account_day_checks_on(today), {k: tuple(v) for k, v in issues.items()},
               tuple(winners), tuple(lost), {k: frozenset(v) for k, v in names.items()},
               continuous=catalog is not None, catalog=catalog)


# ── 작은 도구 ────────────────────────────────────────────────────────
def tail4(customer_id) -> Optional[str]:
    """고객 번호 끝 4자리(표시용)."""
    if isinstance(customer_id, bool) or not isinstance(customer_id, int):
        return None
    s = str(customer_id)
    return s[-4:]


def _person_name(org: O.Org, idx) -> Optional[str]:
    p = org.people.get(idx) if isinstance(idx, int) and not isinstance(idx, bool) else None
    return None if p is None else p.name


def _team_name(org: O.Org, team_idx) -> Optional[str]:
    t = org.teams.get(team_idx) if isinstance(team_idx, int) and not isinstance(team_idx, bool) else None
    return None if t is None else t.name


def _day(raw) -> Optional[date]:
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


def _iso(t: Optional[datetime]) -> Optional[str]:
    return None if t is None else t.astimezone(KST).isoformat(timespec="seconds")


def visible(ctx: Ctx, scope: SC.Scope, selection: str = "all", *, managed_only: bool = True) -> frozenset:
    """보이는 가망 번호 — ``scope.clients_in`` 한 곳. ``managed_only`` 면 지금 관리 목록에 있는 가망만."""
    ids = SC.clients_in(ctx.org, scope, ctx.owns, selection)
    if not managed_only:
        return ids
    return frozenset(pid for pid in ids if ctx.prospects[pid]["present"] == 1)


def make_ref(pairing_id: int, pid: int, customer_id: Optional[int], state: str) -> str:
    """짝 후보 가리킴표 — 번호 원문 대신 화면에 준다(이 프로세스 · 이 짝 맞추기에서만 통한다)."""
    msg = f"{pairing_id}:{pid}:{customer_id}:{state}".encode("ascii")
    return hmac.new(_REF_KEY, msg, hashlib.sha256).hexdigest()[:REF_LENGTH]


def find_ref(ctx: Ctx, ref) -> Optional[dict]:
    """가리킴표 → 마지막 짝 맞추기의 그 줄(없거나 낡았으면 None)."""
    if ctx.pairing is None or not isinstance(ref, str) or len(ref) != REF_LENGTH:
        return None
    for rows in ctx.rows_by_pid.values():
        for r in rows:
            want = make_ref(ctx.pairing["pairing_id"], r["possibility_id"], r["customer_id"], r["state"])
            if hmac.compare_digest(want, ref):
                return r
    return None


# ── 짝 확인 — 이 계정을 누가 쥐었나(S11 검토 link-confirm-steals · link-preview · blocked-rows-joined) ──
def link_holders(ctx: Ctx, pid: int, customer_id: Optional[int]) -> frozenset:
    """이 계정을 쥐었거나 주장하는 **다른** 가망 — 사람 확인(살아 있는 것 · 밀린 것) · 마지막 짝 맞추기의 어느 줄이든 ·
    계정 이름이 상호와 같은 지금 목록의 가망(``name-points-elsewhere`` 가 가리키는 곳)."""
    if customer_id is None:
        return frozenset()
    out = {d.possibility_id for d in ctx.live_decisions + ctx.lost_decisions
           if d.customer_id == customer_id and d.decision == "confirmed" and d.possibility_id != pid}
    for other, rows in ctx.rows_by_pid.items():
        if other != pid and any(r["customer_id"] == customer_id for r in rows):
            out.add(other)
    a = ctx.accounts.get(customer_id)
    key = None if a is None else M.loose_name(a["account_name"])
    if key is not None:
        out |= ctx.name_owners.get(key, frozenset()) - {pid}
    return frozenset(out)


def linkable(ctx: Ctx, row: dict) -> bool:
    """「이 계정 맞음」·「아님」을 누를 수 있는 줄인가 — 줄 종류 · 번호가 계정의 고객 번호 · 계정 표에 있음
    (자동 짝은 오늘 목록에 있을 때만)."""
    cid = row["customer_id"]
    if row["state"] not in LINKABLE_STATES or cid is None or row["code"] in NOT_A_CUSTOMER or cid not in ctx.accounts:
        return False
    return row["state"] != S.PAIR_AUTO or ctx.accounts[cid]["present"] == 1


def clear_for(ctx: Ctx, scope: SC.Scope, pid: int, row: dict, holders: Optional[frozenset] = None) -> bool:
    """이 줄의 계정을 ``scope`` 가 이어도(미리 보아도 · 이름을 보아도) 되나 — 다른 가망이 쥐었거나 주장하면 그 가망 **모두**에
    짝 확인을 할 수 있을 때만. 누가 주장하는지 모르는 막힘(관리 대상 밖 가망의 ① 등)은 대표만. 확인은 자동 규칙을 모두
    이기므로 범위 밖 광고주의 짝을 빼앗지 못하게 하는 길이 여기다(설계 v1.8 S8 「S11 이 범위를 검사」)."""
    if scope.kind == SC.ALL:
        return True
    hs = link_holders(ctx, pid, row["customer_id"]) if holders is None else holders
    if (bool(row.get("claimed_elsewhere")) or row["code"] in CLAIM_CODES) and not hs:
        return False
    for h in hs:
        own = ctx.owns.get(h)
        if own is None or SC.ACT_CONFIRM_LINK not in SC.allowed_actions(ctx.org, scope, own):
            return False
    return True


# ── 판정 ────────────────────────────────────────────────────────────
def _link_of(r: dict) -> str:
    if r.get("link") in (V.LINK_CONFIRMED, V.LINK_AUTO):
        return r["link"]
    return V.LINK_CONFIRMED if r["state"] == S.PAIR_CONFIRMED else V.LINK_AUTO


def account_checks(ctx: Ctx, pid: int) -> List[V.AccountCheck]:
    """가망 하나의 계정 점검 결과 — 오늘 짝 맞추기일 때만 오늘 결과 · 가망까지 대조(S9·S10 약속)."""
    out = []
    for r in ctx.rows_by_pid.get(pid, ()):
        if r["state"] not in LINK_ROW_STATES or r["customer_id"] is None:
            continue
        cid, link = r["customer_id"], _link_of(r)
        got = ctx.checks_today.get(cid) if ctx.pairing_today else None
        if got is not None and got["possibility_id"] == pid:
            out.append(V.AccountCheck(cid, link, got["status"], ctx.today, tuple(got["rules_not_run"])))
        elif ctx.pairing_today and r["state"] == S.PAIR_MISSING:
            out.append(V.AccountCheck(cid, link, V.CHECK_LINK_MISSING, None))
        elif ctx.pairing_today and r["state"] == S.PAIR_BROKEN:
            out.append(V.AccountCheck(cid, link, V.CHECK_LINK_BROKEN, None))
        else:
            out.append(V.AccountCheck(cid, link, V.CHECK_PENDING, None))
    return out


def counting_state(i: dict, today: date) -> str:
    """세는 상태 — 기간이 끝난 예외(또는 끝나는 날을 못 읽는 예외)는 🆕(``issues.effective_state`` · 판정과 같은 규칙 ·
    검토 expired-exception-counted-red-but-hidden)."""
    if i["state"] == V.ST_EXCEPTION:
        until = _day(i.get("exception_until"))
        if until is None or until < today:
            return V.ST_NEW
    return i["state"]


def _open_issue(i: dict) -> V.OpenIssue:
    return V.OpenIssue(i["severity"], i["state"], _day(i.get("exception_until")))


def weekly(ctx: Ctx, pid: int) -> bool:
    """이 가망을 매일 읽지 않는가 — 연속 점검이고 단계가 주 1회 관찰 단계일 때만(``management.classify`` 와 같은 단계 글자)."""
    return ctx.continuous and H.stage_key(ctx.prospects[pid]["stage_key"]) in WEEKLY_STAGES


def judge(ctx: Ctx, pid: int) -> V.Verdict:
    """가망 하나의 오늘 판정 — 저장된 값을 판정 함수가 받지 않으면 ⚪ 점검 안 됨(확인 필요). 관제 판은 자동 짝을
    「확인 필요」에서 빼고 「계정 확인할 곳」으로 따로 센다(대표 결정 D3) · 주 1회 관찰 단계는 ``weekly``."""
    try:
        return V.judge(accounts=account_checks(ctx, pid), issues=[_open_issue(i) for i in ctx.open_issues.get(pid, ())],
                       now=ctx.now, deadline=ctx.deadline, auto_needs_attention=False, weekly_watch=weekly(ctx, pid))
    except ValueError:
        return V.Verdict(V.WHITE, True, ("unreadable",), V.CHECK_NOT_CHECKED)


def white_detail(ctx: Ctx, pid: int, v: V.Verdict) -> Optional[str]:
    """⚪ 의 까닭 한 코드(화면 문구 · 까닭별 숫자) — 판정은 바꾸지 않는다. 「이어진 계정 없음」은 짝 맞추기 줄로 더 가른다
    (오늘 짝 맞추기 전이면 모른다 · 주 1회 관찰 단계면 매일 이을 일이 없다)."""
    if v.color != V.WHITE:
        return None
    if "unreadable" in v.reasons:
        return "unreadable"
    if v.white_reason != V.WHITE_NO_LINK:
        return v.white_reason
    if not ctx.pairing_today:
        return W_PAIRING_PENDING
    if weekly(ctx, pid):
        return V.WHITE_WEEKLY
    rows = ctx.rows_by_pid.get(pid, ())
    states = {r["state"] for r in rows}
    blocked = {r["code"] for r in rows if r["state"] == S.PAIR_BLOCKED}
    if blocked & _W_CONFLICT or S.PAIR_SUPERSEDED in states:
        return W_ID_CONFLICT
    if blocked & _W_INVALID:
        return W_ID_INVALID
    if blocked & _W_UNLISTED:
        return W_NOT_TRANSFERRED
    if S.PAIR_CANDIDATE in states or M.B_NAME_DIFFERENT in blocked:
        return W_NAME_CANDIDATE
    return W_ID_MISSING


def _verdict_out(v: V.Verdict) -> dict:
    return {"color": v.color, "needs_attention": v.needs_attention, "reasons": list(v.reasons),
            "white_reason": v.white_reason}


def _owner(ctx: Ctx, own: SC.Ownership) -> dict:
    key = SC.owner_key(ctx.org, own)
    person = ctx.org.people.get(key) if key is not None else None
    team = None if person is None else person.team_idx
    return {"state": SC.owner_state(ctx.org, own), "idx": key, "name": _person_name(ctx.org, key),
            "team_idx": team, "team_name": _team_name(ctx.org, team)}


def _auto_link(ctx: Ctx, pid: int) -> bool:
    return any(r["state"] == S.PAIR_AUTO for r in ctx.rows_by_pid.get(pid, ()))


# ── 관제 판 표 칸 · 이슈 한 줄씩(S13) ─────────────────────────────────────
def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")):
        return None
    return float(v)


NUMBER_KEYS = ("yday_spend", "bizmoney")                        # 관제 판 표 칸
CLIENT_NUMBER_KEYS = ("yday_spend", "bizmoney", "yday_imp", "yday_clk")   # 광고주 한 장 타일


def today_numbers(ctx: Ctx, pid: int, keys: Tuple[str, ...] = NUMBER_KEYS) -> dict:
    """오늘 점검이 읽은 숫자(이 가망에 이어진 계정 합) — 어제 광고비 · 비즈머니 잔액(광고주 한 장은 노출·클릭까지). 판정
    조립과 같은 약속: 오늘 짝 맞추기일 때만 · 계정 하루치의 가망이 이 가망일 때만. **점검할 계정이 모두 그 숫자를 줬을
    때만 합**을 낸다 — 한 계정이라도 오늘 하루치가 없거나(다른 가망 짝으로 적힌 것 포함) 그 칸이 비면 None(일부만 더한
    값을 전체처럼 보이지 않게 · 검토 partial-sum-looks-complete). 모름 ≠ 0."""
    out = {k: None for k in keys}
    if not ctx.pairing_today:
        return out
    sums: Dict[str, Optional[float]] = {k: 0.0 for k in keys}
    seen = False
    for r in ctx.rows_by_pid.get(pid, ()):
        if r["state"] not in S.PAIR_CHECKABLE or r["customer_id"] is None:
            continue
        got = ctx.checks_today.get(r["customer_id"])
        if got is None or got["possibility_id"] != pid:
            return out
        seen = True
        for k in keys:
            v = _num(got.get(k))
            sums[k] = None if v is None or sums[k] is None else sums[k] + v
    if not seen:
        return out
    return {k: None if sums[k] is None else round(sums[k]) for k in keys}


def has_unlinked(ctx: Ctx, pid: int) -> bool:
    """이관 안 된 번호가 있나 — 짝 맞추기 막힘 ``not-linked`` 줄이 하나라도(I3 · ``unlinked()`` · 월요일 「이관 받을 곳」
    알림과 같은 규칙). 이어진 계정이 따로 있어도 참 — 「이관」 칸(``link_state``)과 다른 축이다(검토 unlinked-screen-fewer)."""
    return any(r["state"] == S.PAIR_BLOCKED and r["code"] == CODE_NOT_LINKED for r in ctx.rows_by_pid.get(pid, ()))


def link_state(ctx: Ctx, pid: int) -> str:
    """관제 판 「이관」 칸 — 오늘 짝 맞추기 줄에서 한 값(빠짐 > 오늘 없음 > 이관됨 > 이관 안 됨 > 없음). 오늘 짝 맞추기가
    아니면 「pending」 — 어제 짝 맞추기의 「오늘 없음」·「이관 빠짐」을 오늘 것으로 보이지 않는다(판정 조립과 같은 약속)."""
    if not ctx.pairing_today:
        return LINK_PENDING
    states = [(r["state"], r["code"]) for r in ctx.rows_by_pid.get(pid, ())]
    if any(st == S.PAIR_BROKEN for st, _c in states):
        return LINK_BROKEN
    if any(st == S.PAIR_MISSING for st, _c in states):
        return LINK_MISSING
    if any(st in S.PAIR_CHECKABLE for st, _c in states):
        return LINK_LISTED
    if any(st == S.PAIR_BLOCKED and c == CODE_NOT_LINKED for st, c in states):
        return LINK_NOT_LINKED
    return LINK_NONE


def _hand_of(ctx: Ctx, events: Iterable[dict]) -> Optional[dict]:
    """이슈에 사람이 가장 늦게 한 일(👀 · ✅ · 🙈) — 누가 · 언제 · 예외 사유. 이슈가 다시 시작된 기록(``RESET_KINDS``)보다
    앞선 손길은 지난 일이라 싣지 않는다."""
    last = None
    for e in events:
        if e["kind"] in RESET_KINDS:
            last = None
        elif e["kind"] in HAND_KINDS and e["by_person"] is not None:
            last = e
    if last is None:
        return None
    return {"kind": last["kind"], "at": last["at"], "by": _person_name(ctx.org, last["by_person"]),
            "note": last["note"], "exception_until": last["exception_until"]}


def hand_now(ctx: Ctx, i: dict, hand: Optional[dict]) -> Optional[dict]:
    """지금 상태에 맞는 사람 손길 — 🆕(기간이 끝나 🆕 로 세는 예외 포함)는 사람이 아직 손대지 않은 상태라 없음. 끝난 예외의
    기록(예외 끝남)은 다음 아침 점검이 적으므로 그 전에도 옛 사유를 붙이지 않게 세는 상태로 가른다."""
    return None if counting_state(i, ctx.today) == V.ST_NEW else hand


def hands(ctx: Ctx, store: S.Store, issue_ids: Iterable[int]) -> Dict[int, Optional[dict]]:
    """이슈 여럿의 마지막 사람 손길 — 한 번에 읽는다(이슈마다 따로 읽지 않게 · 검토 board-n-plus-1)."""
    ids = sorted(set(issue_ids))
    events = store.issue_hand_events(ids, HAND_KINDS | RESET_KINDS) if ids else {}
    return {n: _hand_of(ctx, events.get(n, ())) for n in ids}


def issue_can(ctx: Ctx, scope: SC.Scope, own: SC.Ownership, i: dict) -> dict:
    """이 이슈에서 지금 누를 수 있는 것 — 서버 규칙(``scope`` · ``issues``)을 그대로 비춘다(화면은 단추만 켜고 끈다 ·
    누르면 서버가 다시 판정한다). 예외는 등급별 한도 · 층(팀장 이상 🔴) · 조직 신선도(올리기 관문)까지."""
    handle = SC.ACT_HANDLE_ISSUE in SC.allowed_actions(ctx.org, scope, own)
    eff = counting_state(i, ctx.today)
    actor = SC.issue_actor(ctx.org, scope, own)
    need = IS.EXCEPTION_MIN_ACTOR.get(i["severity"])
    rank = (IS.ACTOR_OWNER, IS.ACTOR_LEAD)
    tall = actor is not None and need is not None and rank.index(actor) >= rank.index(need)
    can_except = (handle and tall and i["state"] != V.ST_EXCEPTION and eff in ISSUE_OPEN
                  and O.allows_raising(ctx.freshness))
    # 막힌 까닭은 서버가 거절하는 순서 그대로(``web._h_issue_except`` 조직 신선도 → ``issues.grant_exception`` 예외 중 →
    # 층) — 열린 줄(🆕·👀)에서만 ·
    # 닫힌 줄 · 「오늘 풀린 것」에는 단추 자체가 없다(검토 except-blocked-on-closed-row)
    blocked = None
    if handle and not can_except and eff in ISSUE_OPEN:
        blocked = ("org-stale" if not O.allows_raising(ctx.freshness) else
                   "exception-active" if i["state"] == V.ST_EXCEPTION else "actor-too-low")
    return {"ack": handle and eff == V.ST_NEW,
            "resolve": handle and i["state"] in ("new", "ack", "exception"),
            "except": can_except,
            "except_until_max": IS.max_exception_until(i["severity"], ctx.today).isoformat() if can_except else None,
            "except_blocked": blocked}


def issue_row(ctx: Ctx, store: S.Store, scope: SC.Scope, i: dict, hand: Optional[dict] = None) -> dict:
    """관제 판 이슈 한 줄 — 원인별 묶음 아래 광고주마다(S13). 고객 번호는 끝 4자리만 · 사실 칸은 저장된 그대로(금액·일수).
    사람 손길(``hand``)은 부르는 쪽이 ``hands`` 로 한 번에 읽어 넘긴다."""
    pid = i["possibility_id"]
    own = ctx.owns[pid]
    return {"issue_id": i["issue_id"], "possibility_id": pid, "name": ctx.prospects[pid]["name"],
            "owner": _owner(ctx, own), "relation": SC.relation(ctx.org, scope, own),
            "code": i["code"], "rule": i["rule"], "severity": i["severity"],
            "state": counting_state(i, ctx.today), "stored_state": i["state"],
            "first_seen_on": i["first_seen_on"], "last_seen_on": i["last_seen_on"],
            "reappear_count": i["reappear_count"], "exception_until": i["exception_until"],
            "facts": i["facts"], "target_tail": tail4(i["customer_id"]), "updated_at": i["updated_at"],
            "hand": hand_now(ctx, i, hand), "can": issue_can(ctx, scope, own, i)}


# ── 12시간 안 풀린 🟡 — 한 단계 위로 ────────────────────────────────────
def yellow_waited(ctx: Ctx, since: Mapping[int, datetime], i: dict) -> Optional[timedelta]:
    """🆕 🟡 가 아무 손길 없이 기다린 시간 — 🟡 🆕 가 아니거나 시작 시각을 모르면 None(올림 · 사람별 현황이 같이 쓴다)."""
    if i["severity"] != V.SEV_YELLOW or counting_state(i, ctx.today) != V.ST_NEW:
        return None
    if i["state"] == V.ST_EXCEPTION:   # 예외가 끝나 🆕 가 됨 — 끝난 다음 날 0시부터 센다
        until = _day(i.get("exception_until"))
        began = None if until is None else datetime.combine(until + timedelta(days=1), time(0), KST)
    else:
        began = since.get(i["issue_id"])
    return None if began is None else ctx.now - began


def escalations(ctx: Ctx, store: S.Store, scope: SC.Scope, ids: Iterable[int],
                since: Optional[Mapping[int, datetime]] = None) -> List[dict]:
    """지금 나에게 올라온 🟡 — 🆕 가 된 뒤 12시간마다 ``todo_chain`` 의 다음 묶음으로(담당 → 팀장 → 상위 팀장 → 대표)."""
    since = store.issue_new_since() if since is None else since
    viewer = scope.viewer_idx
    out = []
    for pid in sorted(ids):
        own = ctx.owns[pid]
        for i in ctx.open_issues.get(pid, ()):
            waited = yellow_waited(ctx, since, i)
            if waited is None or waited < ESCALATE_AFTER:
                continue
            chain = SC.todo_chain(ctx.org, own, SC.LEVEL_STAFF)
            step = min(1 + int((waited - ESCALATE_AFTER) / ESCALATE_AFTER), len(chain) - 1)
            if step >= 1 and viewer in chain[step]:
                out.append({"issue_id": i["issue_id"], "possibility_id": pid, "code": i["code"],
                            "name": ctx.prospects[pid]["name"],   # 화면이 광고주 이름을 따로 찾지 않게(S13 · 범위 안)
                            "waited_hours": int(waited.total_seconds() // 3600), "step": step})
    return out


# ── 화면 자료 ────────────────────────────────────────────────────────
def me(ctx: Ctx | InventoryCtx, scope: SC.Scope, *, freshness: Optional[str] = None) -> dict:
    """나 — 대표는 재직 관리팀 명단, 직원은 본인만. 부서 계층은 제공하지 않는다."""
    idx = scope.viewer_idx
    person = ctx.org.people.get(idx)
    people = [{"idx": p, "name": _person_name(ctx.org, p), "team_idx": ctx.org.people[p].team_idx,
               "active": ctx.org.people[p].active} for p in sorted(scope.people) if p in ctx.org.people]
    return {"idx": idx, "name": None if person is None else person.name, "scope": scope.kind,
            "narrowed": scope.narrowed, "team_idx": None if person is None else person.team_idx,
            "team_name": None if person is None else _team_name(ctx.org, person.team_idx),
            "teams": [], "people": people, "org_freshness": ctx.freshness if freshness is None else freshness,
            "org_generated_at": ctx.org.generated_at}


def _band(ctx: Ctx, store: S.Store, scope: SC.Scope) -> dict:
    """점검 띠 — 오늘 회차 상태 · 짝 맞추기 · 조직 신선도. 실패한 곳 수(계정 수)는 대표만."""
    runs = store.runs_on(ctx.today)
    ceo = scope.kind == SC.ALL
    stage_at = store.stage_as_of()
    stage_state = "accepted" if stage_at is not None else "not_accepted"
    if stage_at is None:
        hold = store.hold(S.SYNC_STAGES)
        if hold is not None and hold["used_at"] is None:
            stage_state = "held"
    out_runs = []
    for r in runs:
        d = {"status": r["status"], "started_at": r["started_at"], "finished_at": r["finished_at"]}
        if ceo:
            d.update(accounts_total=r["accounts_total"], accounts_ok=r["accounts_ok"], error_kind=r["error_kind"])
        out_runs.append(d)
    return {"today": ctx.today.isoformat(), "deadline_passed": ctx.now >= ctx.deadline, "runs": out_runs,
            "pairing_at": None if ctx.pairing is None else _iso(ctx.pairing["at"]), "pairing_today": ctx.pairing_today,
            "org_freshness": ctx.freshness, "org_generated_at": ctx.org.generated_at,
            "stage_as_of": _iso(stage_at), "stage_state": stage_state}


@dataclass(frozen=True)
class Today:
    """가망 하나의 「오늘」 요약 — 관제 판 숫자 4칸 · 오늘 볼 광고주 · 사람별 현황이 같은 값을 쓴다(화면이 세지 않게)."""
    verdict: V.Verdict
    red: int                 # 열린(🆕·👀) 🔴 이슈 수
    yellow: int              # 열린(🆕·👀) 🟡 이슈 수
    acked: int               # 👀 확인 중인 🔴·🟡 이슈 수
    stale: int               # 🆕 🟡 가 12시간 넘게 아무 손길 없는 수(올림과 같은 규칙)
    detail: Optional[str]    # ⚪ 까닭 한 코드(``white_detail``)
    look: bool               # 오늘 볼 광고주인가 — 확인 필요 또는 열린 🔴·🟡 가 있음(👀 확인 중도 끝날 때까지 남는다)
    group: str               # 숫자 4칸 중 하나: need · ok · unlinked · unchecked(서로 겹치지 않는다)


TODAY_GROUPS = ("need", "ok", "unlinked", "unchecked")


def today_of(ctx: Ctx, pid: int, since: Mapping[int, datetime], v: Optional[V.Verdict] = None) -> Today:
    """오늘 볼 곳인가 · 어느 숫자 칸인가 — 판정(``judge``)과 열린 이슈만으로(대표 결정 2026-10-06 숫자 4칸)."""
    v = judge(ctx, pid) if v is None else v
    red = yellow = acked = stale = 0
    for i in ctx.open_issues.get(pid, ()):
        state = counting_state(i, ctx.today)
        if state not in ISSUE_OPEN or i["severity"] not in (V.SEV_RED, V.SEV_YELLOW):
            continue
        red += i["severity"] == V.SEV_RED
        yellow += i["severity"] == V.SEV_YELLOW
        acked += state == V.ST_ACK
        waited = yellow_waited(ctx, since, i)
        stale += waited is not None and waited >= ESCALATE_AFTER
    detail = white_detail(ctx, pid, v)
    look = v.needs_attention or red > 0 or yellow > 0
    group = ("need" if look else "ok" if v.color != V.WHITE else
             "unlinked" if detail in UNLINKED_DETAILS else "unchecked")
    return Today(v, red, yellow, acked, stale, detail, look, group)


def people_summary(ctx: Ctx, scope: SC.Scope, ids: Iterable[int], todays: Mapping[int, Today]) -> List[dict]:
    """대표 첫 화면 「사람별 처리 현황」(대표 결정 D4) — 담당(``scope.owner_key``)별 오늘 볼 곳 · 긴급 · 👀 확인 중 ·
    12시간 넘게 안 본 🟡 · 연결 안 됨 · 계정 확인할 곳. 고르기와 상관없이 대표 최대 범위 · 재직 관리팀은 0이어도 한 줄 ·
    담당 미정은 맨 끝 한 줄(``idx`` 없음)."""
    groups: Dict[Optional[int], dict] = {}

    def row(idx: Optional[int], name: Optional[str], team_name: Optional[str]) -> dict:
        return {"idx": idx, "name": name, "team_name": team_name, "clients": 0, "need": 0, "red": 0, "acked": 0,
                "stale_yellow": 0, "unlinked": 0, "account_confirm": 0}

    for idx in sorted(scope.people):   # 재직 관리팀 직원은 0곳이어도 한 줄(보는 대표 본인은 담당 광고주가 있을 때만)
        person = ctx.org.people.get(idx)
        if person is not None and person.active and idx != scope.viewer_idx:
            groups[idx] = row(idx, person.name, _team_name(ctx.org, person.team_idx))
    for pid in sorted(ids):
        o = _owner(ctx, ctx.owns[pid])
        g = groups.get(o["idx"])
        if g is None:
            g = groups[o["idx"]] = row(o["idx"], o["name"], o["team_name"])
        t = todays[pid]
        g["clients"] += 1
        g["need"] += t.look
        g["red"] += t.look and t.verdict.color == V.RED
        g["acked"] += t.acked
        g["stale_yellow"] += t.stale
        g["unlinked"] += t.group == "unlinked"
        g["account_confirm"] += _auto_link(ctx, pid)
    return sorted(groups.values(), key=lambda g: (g["idx"] is None, g["team_name"] or "", g["name"] or "",
                                                 -1 if g["idx"] is None else g["idx"]))


def board(ctx: Ctx, store: S.Store, scope: SC.Scope, selection: str = "all", attention_only: bool = True) -> dict:
    """관제 판 — 점검 띠 · 숫자 · 오늘의 이슈(원인별) · 전 광고주 표(팀 → 사람 · 기본 「확인 필요만」) · 올라온 🟡.
    개편(2026-10-06): 숫자 4칸(``today_counts``) · ⚪ 까닭별 숫자 · 계정 확인할 곳 · 대표만 사람별 현황을 더한다."""
    ids = visible(ctx, scope, selection)
    widest = visible(ctx, scope)          # 올림 · 사람별 현황은 고르기와 상관없이 최대 범위
    ceo = scope.kind == SC.ALL
    since = store.issue_new_since()
    todays = {pid: today_of(ctx, pid, since) for pid in sorted(ids | widest if ceo else ids)}
    counts = {"red": 0, "white": 0, "yellow": 0, "green": 0, "needs_attention": 0, "total": len(ids)}
    today_counts = {k: 0 for k in TODAY_GROUPS}
    today_counts["need_red"] = 0
    breakdown: Dict[str, Dict[str, int]] = {"unlinked": {}, "unchecked": {}}
    account_confirm = 0
    by_code: Dict[str, dict] = {}
    rows = []
    for pid in sorted(ids):
        t = todays[pid]
        v = t.verdict
        counts[v.color] += 1
        counts["needs_attention"] += 1 if v.needs_attention else 0
        today_counts[t.group] += 1
        today_counts["need_red"] += t.look and v.color == V.RED
        if t.group in breakdown:
            breakdown[t.group][t.detail] = breakdown[t.group].get(t.detail, 0) + 1
        auto = _auto_link(ctx, pid)
        account_confirm += auto
        for i in ctx.open_issues.get(pid, ()):
            state = counting_state(i, ctx.today)
            if state not in ISSUE_OPEN:
                continue
            g = by_code.setdefault(i["code"], {"code": i["code"], "rule": i["rule"], "severity": i["severity"],
                                               "clients": set(), "new": 0})
            g["clients"].add(pid)
            g["new"] += state == V.ST_NEW
            if i["severity"] == V.SEV_RED:
                g["severity"] = V.SEV_RED
        if attention_only and not v.needs_attention:
            continue
        p, own = ctx.prospects[pid], ctx.owns[pid]
        rows.append({"possibility_id": pid, "name": p["name"], "stage": p["stage_key"],
                     "relation": SC.relation(ctx.org, scope, own), "owner": _owner(ctx, own),
                     "verdict": _verdict_out(v), "open_red": t.red, "open_yellow": t.yellow,
                     "account_unconfirmed": auto, "link": link_state(ctx, pid),
                     "unlinked": has_unlinked(ctx, pid), **today_numbers(ctx, pid),
                     "white_detail": t.detail, "look_today": t.look, "today_group": t.group})
    issues = sorted(({**g, "clients": len(g["clients"])} for g in by_code.values()),
                    key=lambda g: (g["severity"] != V.SEV_RED, -g["clients"], g["code"]))
    rows.sort(key=lambda r: (r["owner"]["team_name"] or "", r["owner"]["name"] or "", r["possibility_id"]))
    # 이관 띠(S13) — 표(확인 필요만)와 상관없이 고른 범위의 모든 가망
    links = {k: 0 for k in LINK_KINDS}
    links["unlinked_numbers"] = 0   # 이관 안 된 번호가 있는 곳(위 칸들과 겹칠 수 있음 · 월요일 알림과 같은 수)
    for pid in ids:
        links[link_state(ctx, pid)] += 1
        links["unlinked_numbers"] += has_unlinked(ctx, pid)
    # 이슈 한 줄씩(S13) — 고른 범위 안만 · 열린 것(🆕·👀) = 「오늘의 이슈」 · 🙈 예외 · 오늘 닫힌 것 = 「오늘 풀린 것」
    open_src, done_src = [], []
    for pid in sorted(ids):
        for i in ctx.open_issues.get(pid, ()):
            (open_src if counting_state(i, ctx.today) in ISSUE_OPEN else done_src).append(i)
    done_src += [i for i in store.issues_closed_on(ctx.today) if i["possibility_id"] in ids]
    hand = hands(ctx, store, (i["issue_id"] for i in open_src + done_src))
    open_rows = [issue_row(ctx, store, scope, i, hand.get(i["issue_id"])) for i in open_src]
    done_rows = [issue_row(ctx, store, scope, i, hand.get(i["issue_id"])) for i in done_src]
    sev = {V.SEV_RED: 0, V.SEV_YELLOW: 1, V.SEV_INFO: 2}
    open_rows.sort(key=lambda r: (sev.get(r["severity"], 3), r["code"], r["state"] != V.ST_NEW, r["possibility_id"],
                                  r["issue_id"]))
    done_rows.sort(key=lambda r: (r["updated_at"], r["issue_id"]), reverse=True)
    out = {"band": _band(ctx, store, scope), "counts": counts, "issues": issues, "rows": rows,
           "attention_only": attention_only, "selection": selection, "links": links,
           "issue_rows": open_rows, "done_rows": done_rows,
           # 나에게 올라온 일은 고르기(나만 · 사람 · 팀)와 상관없다 — 최대 범위 안에서만(검토 escalation-hidden-by-selection)
           "escalated_to_me": escalations(ctx, store, scope, widest, since),
           # 개편 숫자 4칸 — 서로 겹치지 않고 더하면 counts.total(``today_of``) · 화면은 세지 않고 이 값을 그린다
           "today_counts": today_counts, "white_breakdown": breakdown, "account_confirm": account_confirm}
    if ceo:
        out["people_summary"] = people_summary(ctx, scope, widest, todays)
    return out


def _history(store: S.Store, ctx: Ctx, customer_id: int, pid: int) -> List[dict]:
    out = []
    for back in range(HISTORY_DAYS):
        d = ctx.today - timedelta(days=back)
        ad = store.account_day(customer_id, d)
        if ad is None or ad["possibility_id"] != pid:   # 다른 가망 짝으로 적힌 날은 이 광고주 기록이 아니다
            out.append({"day": d.isoformat(), "status": None})
            continue
        out.append({"day": d.isoformat(), "status": ad["status"], "bizmoney": ad["bizmoney"],
                    "yday_spend": ad["yday_spend"], "yday_imp": ad["yday_imp"], "yday_clk": ad["yday_clk"],
                    "data_late": ad["data_late"], "rules_not_run": [list(x) for x in ad["rules_not_run"]]})
    return out


def day_totals(accounts: List[dict]) -> List[dict]:
    """광고주 한 장 14일 막대 — 날마다 이어진 계정의 전날 광고비 합. 그날 읽은 계정이 모두가 아니면 ``complete`` 거짓(화면이
    「일부 계정만」으로 흐리게) · 하나도 없으면 None(빈 막대). 화면이 계정별 기록을 다시 더하지 않게 서버가 센다."""
    days: Dict[str, dict] = {}
    for a in accounts:
        for d in a["history"]:
            x = days.setdefault(d["day"], {"day": d["day"], "yday_spend": None, "read": 0})
            v = _num(d.get("yday_spend")) if d.get("status") is not None else None
            if v is not None:
                x["yday_spend"] = (x["yday_spend"] or 0.0) + v
                x["read"] += 1
    n = len(accounts)
    return [{"day": k, "yday_spend": None if x["yday_spend"] is None else round(x["yday_spend"]),
             "complete": n > 0 and x["read"] == n} for k, x in sorted(days.items())]


def _issue_out(ctx: Ctx, store: S.Store, i: dict) -> dict:
    events = [{"kind": e["kind"], "at": e["at"], "from_state": e["from_state"], "to_state": e["to_state"],
               "severity": e["severity"], "by": _person_name(ctx.org, e["by_person"]),
               "exception_until": e["exception_until"], "note": e["note"]} for e in store.issue_events(i["issue_id"])]
    return {"issue_id": i["issue_id"], "code": i["code"], "rule": i["rule"], "severity": i["severity"],
            "state": i["state"], "first_seen_on": i["first_seen_on"], "last_seen_on": i["last_seen_on"],
            "exception_until": i["exception_until"], "reappear_count": i["reappear_count"],
            "facts": i["facts"], "target_tail": tail4(i["customer_id"]), "events": events}


def _client_account_key(customer_id: int) -> str:
    # report_views.account_key와 같은 표시 식별자. 권한 토큰이 아니며 현재 업체의 짝을 아래에서 다시 확인한다.
    return hashlib.sha256(str(customer_id).encode("ascii")).hexdigest()


def _client_current_decision(ctx: Ctx, pid: int, row: dict) -> bool:
    cid = row["customer_id"]
    decisions = tuple(d for d in ctx.live_decisions if d.customer_id == cid)
    if any((d.decision == "confirmed" and d.possibility_id != pid) or
           (d.decision == "rejected" and d.possibility_id == pid) for d in decisions):
        return False
    # 수락 pairing이 아직 갱신되지 않았어도 회수한 수동 연결은 선택 조회를 열지 않는다.
    return _link_of(row) != "confirmed" or any(d.decision == "confirmed" and d.possibility_id == pid for d in decisions)


def _client_current_mapping(ctx: Ctx, store: S.Store, pid: int, row: dict) -> bool:
    from .inventory import CATALOG_INTERVAL  # 기존 catalog의 유효기간을 재사용(전체 재조회 없음).
    cid = row["customer_id"]
    # 현재 살아 있는 사람 확인은 ERP 자동 입력보다 우선한다(기존 matching 규칙).
    if any(d.customer_id == cid and d.possibility_id == pid and d.decision == "confirmed" for d in ctx.live_decisions):
        return True
    catalog = ctx.catalog
    status = store.account_catalog_status()
    if catalog is None or not status or status["state"] != "accepted":
        return False
    at = datetime.fromisoformat(catalog["generated_at"])
    if not -timedelta(minutes=5) <= ctx.now - at <= CATALOG_INTERVAL * 2:
        return False
    company = next((p for p in catalog["items"] if p["possibility_id"] == pid), None)
    if company is None:
        return False
    # 계정 전체와 모든 업체의 번호 주장은 남긴다. 번호 공간 충돌/중복 주장을 줄여서 풀지 않는다.
    current = {k: {"customerId": k, "adAccountNo": a["ad_account_no"], "adAccountName": a["account_name"]}
               for k, a in ctx.accounts.items() if a["present"] == 1}
    ids = [M.ErpCredential(r["possibility_id"], r["vendor"], r["customer_id_raw"], ad_account_no_raw=r["ad_account_no_raw"])
           for r in catalog["ids"]]
    decisions = [M.HumanDecision(d.possibility_id, d.customer_id, d.decision) for d in ctx.live_decisions]
    try:
        result = M.match((M.ErpProspect(pid, company["company_name"]),), ids, current, decisions,
                         accounts_complete=True, auto_evidence=store.automatic_link_evidence())
    except M.BadInput:
        return False
    if not any(p.possibility_id == pid and p.customer_id == cid for p in result.pairs):
        return False                       # 자동 missing/broken을 임의의 과거 관계로 열지 않는다.
    # 선택 업체만 후보 탐색했어도 현재 prospect와 새 catalog의 다른 업체 이름 주장은 남긴다.
    name = ctx.accounts[cid]["account_name"]
    key = M.loose_name(name)
    if M.name_relation(company["company_name"], name) == M.REL_SAME or key is None:
        return True
    return not (ctx.name_owners.get(key, frozenset()) - {pid}) and not any(
        p["possibility_id"] != pid and M.loose_name(p["company_name"]) == key for p in catalog["items"])


def client(ctx: Ctx, store: S.Store, scope: SC.Scope, pid, account_key: Optional[str] = None) -> dict:
    """광고주 한 장 — 판정 · 계정별 14일 · 이슈 기록 · 연결 · 보고서(4차 준비 중) · 할 수 있는 일. 범위 밖 = 없음(404)."""
    own = SC.require_client(ctx.org, scope, ctx.owns, pid, SC.ACT_VIEW)
    linked = tuple(r for r in ctx.rows_by_pid.get(pid, ())
                   if r["state"] in LINK_ROW_STATES and r["customer_id"] is not None)
    choices = []
    for r in linked:
        a = ctx.accounts.get(r["customer_id"])
        choices.append({"account_key": _client_account_key(r["customer_id"]), "tail": tail4(r["customer_id"]),
                        "account_name": None if a is None else a["account_name"], "link": _link_of(r), "state": r["state"]})
    selected_cid = None
    if account_key is not None:
        if not isinstance(account_key, str) or len(account_key) != 64 or any(c not in "0123456789abcdef" for c in account_key):
            raise SC.ClientNotVisible()
        selected = tuple(r for r in linked if _client_account_key(r["customer_id"]) == account_key)
        if not selected or any(not _client_current_decision(ctx, pid, r) or
                               not _client_current_mapping(ctx, store, pid, r) for r in selected):
            raise SC.ClientNotVisible()
        selected_cid = selected[0]["customer_id"]
        ctx = replace(ctx, rows_by_pid={**ctx.rows_by_pid, pid: selected},
                      open_issues={**ctx.open_issues, pid: tuple(i for i in ctx.open_issues.get(pid, ())
                                                               if i["customer_id"] == selected_cid)})
    p = ctx.prospects[pid]
    v = judge(ctx, pid)
    accounts = []
    for r in ctx.rows_by_pid.get(pid, ()):
        if r["state"] not in LINK_ROW_STATES or r["customer_id"] is None:
            continue
        a = ctx.accounts.get(r["customer_id"])
        accounts.append({"account_key": _client_account_key(r["customer_id"]),
                         "tail": tail4(r["customer_id"]), "account_name": None if a is None else a["account_name"],
                         "link": _link_of(r), "state": r["state"],
                         "history": _history(store, ctx, r["customer_id"], pid)})
    since = ctx.today - timedelta(days=HISTORY_DAYS)
    shown = [i for i in store.issues(pid)
             if (selected_cid is None or i["customer_id"] == selected_cid) and (i["state"] in ("new", "ack", "exception") or (_day(i["last_seen_on"]) or ctx.today) >= since)]
    hand = hands(ctx, store, (i["issue_id"] for i in shown))
    issues = [{**_issue_out(ctx, store, i), "state_now": counting_state(i, ctx.today), "can": issue_can(ctx, scope, own, i),
               "hand": hand_now(ctx, i, hand.get(i["issue_id"]))} for i in shown]
    allowed = SC.allowed_actions(ctx.org, scope, own)
    actor = SC.issue_actor(ctx.org, scope, own)
    from . import setup_checks as SETUP
    setup_cid = selected_cid
    if setup_cid is None and len(linked) == 1 and _client_current_decision(ctx, pid, linked[0]) and _client_current_mapping(ctx, store, pid, linked[0]):
        setup_cid = linked[0]["customer_id"]
    setup_plan = None
    structure = None
    setup_observation = None
    if setup_cid is not None:
        saved_plan = store.automation_plan(pid, _client_account_key(setup_cid))["plan"]
        setup_plan = {"goal": saved_plan["goal"], "budget_plan": {"daily_budget": saved_plan["daily_spend_cap"]}}
        structure = store.structure_checks([setup_cid], ctx.now).get(setup_cid)
        setup_observation = store.setup_observation(setup_cid, ctx.now)
    setup_checks = SETUP.project_setup(now=ctx.now, structure=structure, plan=setup_plan, observation=setup_observation)
    return {"possibility_id": pid, "name": p["name"], "stage": p["stage_key"], "managed": p["present"] == 1,
            "today": ctx.today.isoformat(),   # 화면이 예외 기간을 서버의 「오늘」로 세게(S13)
            "latest_end_date": p["latest_end_date"], "relation": SC.relation(ctx.org, scope, own),
            "owner": _owner(ctx, own), "verdict": _verdict_out(v), "accounts": accounts, "issues": issues,
            "account_choices": choices, "setup_checks": setup_checks,
            "account_selection": {"kind": "company" if account_key is None else "account", "account_key": account_key},
            "link": link_state(ctx, pid), "account_unconfirmed": _auto_link(ctx, pid), "unlinked": has_unlinked(ctx, pid),
            "white_detail": white_detail(ctx, pid, v),
            **today_numbers(ctx, pid, CLIENT_NUMBER_KEYS), "days": day_totals(accounts),
            "report": REPORT_PREPARING,
            "actions": {"handle_issue": SC.ACT_HANDLE_ISSUE in allowed, "confirm_link": SC.ACT_CONFIRM_LINK in allowed,
                        "exception_actor": actor,
                        "exception_max_days": {"red": 7 if actor == "lead" else 0,
                                               "yellow": 30 if actor is not None else 0},
                        "raising_allowed": O.allows_raising(ctx.freshness)}}


def links_pending(ctx: Ctx, store: S.Store, scope: SC.Scope) -> dict:
    """짝 확인 — 막힘 · 이름 후보 · 밀린 확인 · 오늘 없음 · 이관 빠짐(보이는 가망만) + 살아 있는 사람 판단(거두기용)."""
    if ctx.pairing is None:
        return {"pairing_at": None, "rows": [], "decisions": []}
    ids = visible(ctx, scope)
    pairing_id = ctx.pairing["pairing_id"]
    rows = []
    for pid in sorted(ids):
        own = ctx.owns[pid]
        can = SC.ACT_CONFIRM_LINK in SC.allowed_actions(ctx.org, scope, own)
        for r in ctx.rows_by_pid.get(pid, ()):
            if r["state"] not in PENDING_STATES:
                continue
            cid = r["customer_id"]
            customer = cid is not None and r["code"] not in NOT_A_CUSTOMER   # 번호 자체가 계정이 아닌 막힘은 계정 표에 잇지 않는다
            holders = link_holders(ctx, pid, cid) if customer else frozenset()
            clear = customer and clear_for(ctx, scope, pid, r, holders)
            a = ctx.accounts.get(cid) if clear else None   # 남이 쥔 계정의 이름은 주지 않는다(누구인지 밝히지 않는다)
            ok = can and linkable(ctx, r)
            rows.append({"ref": make_ref(pairing_id, pid, cid, r["state"]), "possibility_id": pid,
                         "name": ctx.prospects[pid]["name"], "state": r["state"], "code": r["code"],
                         "tail": tail4(cid), "account_name": None if a is None else a["account_name"],
                         "same_name": r["same_name"],
                         "other_candidate": customer and (bool(r["claimed_elsewhere"]) or r["code"] in CLAIM_CODES
                                                          or bool(holders)),
                         # 「이 계정 맞음」은 올리기 관문(조직 신선도)을 지나야 서버가 받는다 — 예외 단추와 같게(검토
                         # confirm-enabled-when-org-stale) · 「아님」은 막지 않는다
                         "can_confirm": ok and clear and O.allows_raising(ctx.freshness), "can_reject": ok,
                         "confirm_blocked": "org-stale" if ok and clear and not O.allows_raising(ctx.freshness) else None})
    decisions = []
    for d in ctx.live_decisions + ctx.lost_decisions:
        if d.possibility_id in ids and SC.ACT_CONFIRM_LINK in SC.allowed_actions(ctx.org, scope, ctx.owns[d.possibility_id]):
            decisions.append({"decision_id": d.decision_id, "possibility_id": d.possibility_id,
                              "decision": d.decision, "tail": tail4(d.customer_id),
                              "decided_by": _person_name(ctx.org, d.decided_by), "decided_at": _iso(d.decided_at)})
    return {"pairing_at": _iso(ctx.pairing["at"]), "pairing_today": ctx.pairing_today, "rows": rows,
            "decisions": decisions}


def _still_linked(ctx: Ctx, auto_before: set, pid: int) -> bool:
    """이 광고주의 계정이 아직 대행 연결 목록(오늘)에 있나 — 짝 맞추기 줄이 아니라 사람 확인 · 자동으로 이어졌던 기록에서
    (끝난 지 14일이 넘으면 짝 맞추기가 그 가망을 빼므로 · 검토 ended-still-linked-false-after-grace). 다른 가망에 확인된 계정 ·
    이 가망에 「아님」으로 판단한 계정은 빼고."""
    confirmed_to = {d.customer_id: d.possibility_id for d in ctx.live_decisions if d.decision == "confirmed"}
    rejected = {d.customer_id for d in ctx.live_decisions if d.decision == "rejected" and d.possibility_id == pid}
    mine = {cid for cid, p in confirmed_to.items() if p == pid}
    mine |= {cid for p, cid in auto_before if p == pid and confirmed_to.get(cid, pid) == pid}
    mine |= {r["customer_id"] for r in ctx.rows_by_pid.get(pid, ())
             if r["state"] in (S.PAIR_CONFIRMED, S.PAIR_AUTO) and r["customer_id"] is not None}
    return any(ctx.accounts.get(cid, {}).get("present") == 1 for cid in mine - rejected)


def ended(ctx: Ctx, store: S.Store, scope: SC.Scope) -> dict:
    """📦 계약 끝난 광고주 — 단계가 계약 만료이거나 종료일이 지난 곳(보이는 가망만 · 저장된 기록에서만)."""
    rows = []
    auto_before = store.matched_before(S.PAIR_AUTO)
    stage_at = store.stage_as_of()
    for pid in sorted(visible(ctx, scope)):
        p = ctx.prospects[pid]
        end = _day(p["latest_end_date"])
        if p["stage_key"] != H.STAGE_ENDED and not (end is not None and end < ctx.today):
            continue
        days = None if end is None else (ctx.today - end).days
        stopped = bool(p["end_unreadable"]) or H.eligibility_reason(p["stage_key"], stage_at, end, ctx.now) is not None
        rows.append({"possibility_id": pid, "name": p["name"], "stage": p["stage_key"], "end_date": p["latest_end_date"],
                     "days_since_end": days, "checks_stopped": stopped,
                     "still_linked": _still_linked(ctx, auto_before, pid),
                     "owner": _owner(ctx, ctx.owns[pid])})
    return {"rows": rows}


def unlinked(ctx: Ctx, scope: SC.Scope) -> dict:
    """⚪ 「이관 안 됨」 — 한 번도 이관된 적 없는 곳(짝 맞추기 막힘 ``not-linked`` · I3 ⓐ · 보이는 가망만)."""
    rows = []
    for pid in sorted(visible(ctx, scope)):
        if has_unlinked(ctx, pid):
            rows.append({"possibility_id": pid, "name": ctx.prospects[pid]["name"],
                         "stage": ctx.prospects[pid]["stage_key"], "owner": _owner(ctx, ctx.owns[pid])})
    return {"pairing_at": None if ctx.pairing is None else _iso(ctx.pairing["at"]), "rows": rows}


def bell(store: S.Store, viewer_idx: int, now: datetime) -> dict:
    """🔔 — 현재 접근권한 재검증. PID 없는 과거 집계는 직원에게 숫자·원래 경로를 주지 않는다."""
    _need_time(now)
    scope = SC.scope_of(load_org(store), viewer_idx)
    if scope.kind == SC.NONE:
        return {"items": [], "unread": 0}
    ceo = scope.kind == SC.ALL
    since = now.astimezone(KST).date() - timedelta(days=BELL_DAYS - 1)
    items = []
    for r in store.my_alerts(viewer_idx, since):
        if not ceo and r["template"] not in ("digest", "weekly_unlinked"):
            continue  # 시스템·전사·옛 팀장 집계는 대표만. 모르는 틀도 닫힌 쪽.
        try:
            title, lines = AL.render(r["template"], r["source"], r["codes"], r["params"])
        except AL.RenderError:
            title, lines = "알림", ()
        link = r["link_path"]
        if not ceo:
            # 과거 집계에는 광고주 번호가 없어 현재 담당 집합으로 재계산할 수 없다.
            title, lines, link = "관제 알림", ("현재 담당 광고주는 관제 화면에서 확인해 주세요",), "/naver/"
        items.append({"recipient_id": r["recipient_id"], "kind": r["kind"], "day": r["day"], "severity": r["severity"],
                      "title": title, "lines": list(lines), "link": link, "status": r["status"],
                      "held_reason": r["held_reason"], "read": r["read_at"] is not None})
    return {"items": items, "unread": sum(1 for i in items if not i["read"])}


def settings(ctx: Ctx, store: S.Store, scope: SC.Scope) -> dict:
    """⚙️ 설정 — 기준값 · 허용 범위 · 고친 이력 · 점검 시각 · (대표만) 붙잡아 둔 목록. 담당자(MINE)는 부르는 쪽이 거절한다."""
    ceo = scope.kind == SC.ALL
    history = []
    for h in store.threshold_changes():
        history.append({"change_id": h["change_id"], "at": _iso(h["at"]), "before": h["before"], "after": h["after"],
                        "by": _person_name(ctx.org, h["changed_by"]) if ceo else "대표"})
    out = {"thresholds": _thresholds_out(store.thresholds()), "ranges": {k: list(v) for k, v in T.RANGES.items()},
           "history": history, "can_edit": ceo, "deadline": DEADLINE_AT.isoformat(timespec="minutes"),
           "org_freshness": ctx.freshness, "org_generated_at": ctx.org.generated_at}
    if ceo:
        holds = []
        for kind in sorted(S.SYNC_KINDS):
            h = store.hold(kind)
            if h is not None and h["used_at"] is None:
                holds.append({"kind": kind, "hold_id": h["hold_id"], "at": _iso(h["at"]), "codes": list(h["codes"])})
        out["holds"] = holds
    return out


def _thresholds_out(th: T.Thresholds) -> dict:
    return asdict(th)


def health(ctx: Ctx, store: S.Store, scope: SC.Scope) -> dict:
    """엔진 상태 — 조직 신선도 · 오늘 회차 상태(계정 수는 대표만)."""
    band = _band(ctx, store, scope)
    return {"ok": True, "org_freshness": band["org_freshness"], "runs": band["runs"], "pairing_today": band["pairing_today"]}
