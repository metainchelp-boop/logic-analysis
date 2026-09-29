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
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from app.naver_auto import org_snapshot as O
from app.naver_auto import scope as SC
from app.naver_auto import thresholds as T
from app.naver_auto import verdict as V

from . import alerts as AL
from . import handles as H
from . import store as S
from . import sync as Y

KST = S.KST
DEADLINE_AT = time(8, 0)                 # 점검 마감 — verdict 의 「점검 전 / 점검 안 됨」 경계
HISTORY_DAYS = 14                        # 광고주 한 장 현황
BELL_DAYS = 14                           # 🔔 에 보이는 기간
ESCALATE_AFTER = timedelta(hours=12)     # 🟡 이 🆕 인 채 이만큼 지나면 한 단계 위로(v1.4 §6)
ISSUE_OPEN = frozenset({"new", "ack"})   # 「확인할 일」(예외 🙈 는 빼고)
LINK_ROW_STATES = frozenset({S.PAIR_CONFIRMED, S.PAIR_AUTO, S.PAIR_MISSING, S.PAIR_BROKEN})
PENDING_STATES = frozenset({S.PAIR_BLOCKED, S.PAIR_CANDIDATE, S.PAIR_SUPERSEDED, S.PAIR_BROKEN, S.PAIR_MISSING})
CODE_NOT_LINKED = "not-linked"           # matching.B_NOT_LINKED — 한 번도 이관된 적 없음(I3 「이관 안 됨」)
# ① 에 적힌 번호가 고객 번호가 아닌 막힘 — 사람이 「이 계정 맞음」으로 이을 수 없다(번호 자체가 계정이 아니다)
NOT_A_CUSTOMER = frozenset({"ad-account-number", "customer-id-format", "customer-id-length", "ambiguous-space"})
REPORT_PREPARING = "preparing"           # 광고주별 주간·월간 보고서 — 4차
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

    def __repr__(self) -> str:
        return f"Ctx(prospects={len(self.prospects)})"


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


def load(store: S.Store, now: datetime, org: Optional[O.Org] = None) -> Ctx:
    """화면 요청 하나에 쓰는 재료를 한 번에 읽는다(가망마다 따로 읽지 않게)."""
    _need_time(now)
    org = load_org(store) if org is None else org
    local = now.astimezone(KST)
    today = local.date()
    deadline = datetime.combine(today, DEADLINE_AT, KST)
    prospects = {p["possibility_id"]: p for p in store.prospects()}
    owns = {pid: SC.ownership_for_client(org, pid, pid, SC.MATCH_PID) for pid in prospects}
    pairing = store.last_pairing(S.SYNC_ACCEPTED)
    rows: Dict[int, List[dict]] = {}
    if pairing is not None:
        for r in store.pairing_rows(pairing["pairing_id"]):
            rows.setdefault(r["possibility_id"], []).append(r)
    issues: Dict[int, List[dict]] = {}
    for i in store.issues(open_only=True):
        issues.setdefault(i["possibility_id"], []).append(i)
    return Ctx(now, today, deadline, org, Y.org_freshness(store, now), prospects, owns, pairing,
               pairing is not None and pairing["at"].astimezone(KST).date() == today,
               {k: tuple(v) for k, v in rows.items()}, {a["customer_id"]: a for a in store.accounts()},
               store.account_day_checks_on(today), {k: tuple(v) for k, v in issues.items()})


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


def _open_issue(i: dict) -> V.OpenIssue:
    return V.OpenIssue(i["severity"], i["state"], _day(i.get("exception_until")))


def judge(ctx: Ctx, pid: int) -> V.Verdict:
    """가망 하나의 오늘 판정 — 저장된 값을 판정 함수가 받지 않으면 ⚪ 점검 안 됨(확인 필요)."""
    try:
        return V.judge(accounts=account_checks(ctx, pid), issues=[_open_issue(i) for i in ctx.open_issues.get(pid, ())],
                       now=ctx.now, deadline=ctx.deadline)
    except ValueError:
        return V.Verdict(V.WHITE, True, ("unreadable",), V.CHECK_NOT_CHECKED)


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


# ── 12시간 안 풀린 🟡 — 한 단계 위로 ────────────────────────────────────
def escalations(ctx: Ctx, store: S.Store, scope: SC.Scope, ids: Iterable[int]) -> List[dict]:
    """지금 나에게 올라온 🟡 — 🆕 가 된 뒤 12시간마다 ``todo_chain`` 의 다음 묶음으로(담당 → 팀장 → 상위 팀장 → 대표)."""
    since = store.issue_new_since()
    viewer = scope.viewer_idx
    out = []
    for pid in sorted(ids):
        own = ctx.owns[pid]
        for i in ctx.open_issues.get(pid, ()):
            if i["severity"] != V.SEV_YELLOW or i["state"] != V.ST_NEW or i["issue_id"] not in since:
                continue
            waited = ctx.now - since[i["issue_id"]]
            if waited < ESCALATE_AFTER:
                continue
            chain = SC.todo_chain(ctx.org, own, SC.LEVEL_STAFF)
            step = min(1 + int((waited - ESCALATE_AFTER) / ESCALATE_AFTER), len(chain) - 1)
            if step >= 1 and viewer in chain[step]:
                out.append({"issue_id": i["issue_id"], "possibility_id": pid, "code": i["code"],
                            "waited_hours": int(waited.total_seconds() // 3600), "step": step})
    return out


# ── 화면 자료 ────────────────────────────────────────────────────────
def me(ctx: Ctx, scope: SC.Scope) -> dict:
    """나 — 이름 · 범위 종류 · 좁힘 · 고를 수 있는 팀·사람(범위 안만)."""
    idx = scope.viewer_idx
    person = ctx.org.people.get(idx)
    teams = [{"idx": t, "name": _team_name(ctx.org, t), "parent_idx": ctx.org.parent_of(t)}
             for t in sorted(scope.teams) if not ctx.org.is_system_team(t)]
    people = [{"idx": p, "name": _person_name(ctx.org, p), "team_idx": ctx.org.people[p].team_idx,
               "active": ctx.org.people[p].active} for p in sorted(scope.people) if p in ctx.org.people]
    return {"idx": idx, "name": None if person is None else person.name, "scope": scope.kind,
            "narrowed": scope.narrowed, "team_idx": None if person is None else person.team_idx,
            "team_name": None if person is None else _team_name(ctx.org, person.team_idx),
            "teams": teams, "people": people, "org_freshness": ctx.freshness,
            "org_generated_at": ctx.org.generated_at}


def _band(ctx: Ctx, store: S.Store, scope: SC.Scope) -> dict:
    """점검 띠 — 오늘 회차 상태 · 짝 맞추기 · 조직 신선도. 실패한 곳 수(계정 수)는 대표만."""
    runs = store.runs_on(ctx.today)
    ceo = scope.kind == SC.ALL
    out_runs = []
    for r in runs:
        d = {"status": r["status"], "started_at": r["started_at"], "finished_at": r["finished_at"]}
        if ceo:
            d.update(accounts_total=r["accounts_total"], accounts_ok=r["accounts_ok"], error_kind=r["error_kind"])
        out_runs.append(d)
    return {"today": ctx.today.isoformat(), "deadline_passed": ctx.now >= ctx.deadline, "runs": out_runs,
            "pairing_at": None if ctx.pairing is None else _iso(ctx.pairing["at"]), "pairing_today": ctx.pairing_today,
            "org_freshness": ctx.freshness, "org_generated_at": ctx.org.generated_at,
            "stage_as_of": _iso(store.stage_as_of())}


def board(ctx: Ctx, store: S.Store, scope: SC.Scope, selection: str = "all", attention_only: bool = True) -> dict:
    """관제 판 — 점검 띠 · 숫자 5칸 · 오늘의 이슈(원인별) · 전 광고주 표(팀 → 사람 · 기본 「확인 필요만」) · 올라온 🟡."""
    ids = visible(ctx, scope, selection)
    counts = {"red": 0, "white": 0, "yellow": 0, "green": 0, "needs_attention": 0, "total": len(ids)}
    by_code: Dict[str, dict] = {}
    rows = []
    for pid in sorted(ids):
        v = judge(ctx, pid)
        counts[v.color] += 1
        counts["needs_attention"] += 1 if v.needs_attention else 0
        red = yellow = 0
        for i in ctx.open_issues.get(pid, ()):
            if i["state"] not in ISSUE_OPEN:
                continue
            red += i["severity"] == V.SEV_RED
            yellow += i["severity"] == V.SEV_YELLOW
            g = by_code.setdefault(i["code"], {"code": i["code"], "rule": i["rule"], "severity": i["severity"],
                                               "clients": set(), "new": 0})
            g["clients"].add(pid)
            g["new"] += i["state"] == V.ST_NEW
            if i["severity"] == V.SEV_RED:
                g["severity"] = V.SEV_RED
        if attention_only and not v.needs_attention:
            continue
        p, own = ctx.prospects[pid], ctx.owns[pid]
        rows.append({"possibility_id": pid, "name": p["name"], "stage": p["stage_key"],
                     "relation": SC.relation(ctx.org, scope, own), "owner": _owner(ctx, own),
                     "verdict": _verdict_out(v), "open_red": red, "open_yellow": yellow,
                     "account_unconfirmed": _auto_link(ctx, pid)})
    issues = sorted(({**g, "clients": len(g["clients"])} for g in by_code.values()),
                    key=lambda g: (g["severity"] != V.SEV_RED, -g["clients"], g["code"]))
    rows.sort(key=lambda r: (r["owner"]["team_name"] or "", r["owner"]["name"] or "", r["possibility_id"]))
    return {"band": _band(ctx, store, scope), "counts": counts, "issues": issues, "rows": rows,
            "attention_only": attention_only, "selection": selection,
            "escalated_to_me": escalations(ctx, store, scope, ids)}


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


def _issue_out(ctx: Ctx, store: S.Store, i: dict) -> dict:
    events = [{"kind": e["kind"], "at": e["at"], "from_state": e["from_state"], "to_state": e["to_state"],
               "severity": e["severity"], "by": _person_name(ctx.org, e["by_person"]),
               "exception_until": e["exception_until"], "note": e["note"]} for e in store.issue_events(i["issue_id"])]
    return {"issue_id": i["issue_id"], "code": i["code"], "rule": i["rule"], "severity": i["severity"],
            "state": i["state"], "first_seen_on": i["first_seen_on"], "last_seen_on": i["last_seen_on"],
            "exception_until": i["exception_until"], "reappear_count": i["reappear_count"],
            "facts": i["facts"], "target_tail": tail4(i["customer_id"]), "events": events}


def client(ctx: Ctx, store: S.Store, scope: SC.Scope, pid) -> dict:
    """광고주 한 장 — 판정 · 계정별 14일 · 이슈 기록 · 연결 · 보고서(4차 준비 중) · 할 수 있는 일. 범위 밖 = 없음(404)."""
    own = SC.require_client(ctx.org, scope, ctx.owns, pid, SC.ACT_VIEW)
    p = ctx.prospects[pid]
    v = judge(ctx, pid)
    accounts = []
    for r in ctx.rows_by_pid.get(pid, ()):
        if r["state"] not in LINK_ROW_STATES or r["customer_id"] is None:
            continue
        a = ctx.accounts.get(r["customer_id"])
        accounts.append({"tail": tail4(r["customer_id"]), "account_name": None if a is None else a["account_name"],
                         "link": _link_of(r), "state": r["state"],
                         "history": _history(store, ctx, r["customer_id"], pid)})
    since = ctx.today - timedelta(days=HISTORY_DAYS)
    issues = [_issue_out(ctx, store, i) for i in store.issues(pid)
              if i["state"] in ("new", "ack", "exception") or (_day(i["last_seen_on"]) or ctx.today) >= since]
    allowed = SC.allowed_actions(ctx.org, scope, own)
    actor = SC.issue_actor(ctx.org, scope, own)
    return {"possibility_id": pid, "name": p["name"], "stage": p["stage_key"], "managed": p["present"] == 1,
            "latest_end_date": p["latest_end_date"], "relation": SC.relation(ctx.org, scope, own),
            "owner": _owner(ctx, own), "verdict": _verdict_out(v), "accounts": accounts, "issues": issues,
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
            a = ctx.accounts.get(cid) if cid is not None else None
            is_customer = cid is not None and r["code"] not in NOT_A_CUSTOMER and a is not None
            rows.append({"ref": make_ref(pairing_id, pid, cid, r["state"]), "possibility_id": pid,
                         "name": ctx.prospects[pid]["name"], "state": r["state"], "code": r["code"],
                         "tail": tail4(cid), "account_name": None if a is None else a["account_name"],
                         "same_name": r["same_name"], "other_candidate": bool(r["claimed_elsewhere"]),
                         "can_confirm": can and is_customer and r["state"] in (S.PAIR_CANDIDATE, S.PAIR_BLOCKED),
                         "can_reject": can and is_customer and r["state"] in (S.PAIR_CANDIDATE, S.PAIR_BLOCKED)})
    decisions = []
    for d in store.current_decisions() + store.superseded_confirmations():
        if d.possibility_id in ids and SC.ACT_CONFIRM_LINK in SC.allowed_actions(ctx.org, scope, ctx.owns[d.possibility_id]):
            decisions.append({"decision_id": d.decision_id, "possibility_id": d.possibility_id,
                              "decision": d.decision, "tail": tail4(d.customer_id),
                              "decided_by": _person_name(ctx.org, d.decided_by), "decided_at": _iso(d.decided_at)})
    return {"pairing_at": _iso(ctx.pairing["at"]), "pairing_today": ctx.pairing_today, "rows": rows,
            "decisions": decisions}


def ended(ctx: Ctx, scope: SC.Scope) -> dict:
    """📦 계약 끝난 광고주 — 단계가 계약 만료이거나 종료일이 지난 곳(보이는 가망만 · 저장된 기록에서만)."""
    rows = []
    for pid in sorted(visible(ctx, scope)):
        p = ctx.prospects[pid]
        end = _day(p["latest_end_date"])
        if p["stage_key"] != H.STAGE_ENDED and not (end is not None and end < ctx.today):
            continue
        days = None if end is None else (ctx.today - end).days
        rows.append({"possibility_id": pid, "name": p["name"], "stage": p["stage_key"], "end_date": p["latest_end_date"],
                     "days_since_end": days, "checks_stopped": days is not None and days > H.ENDED_GRACE_DAYS,
                     "still_linked": any(r["state"] in (S.PAIR_CONFIRMED, S.PAIR_AUTO)
                                         for r in ctx.rows_by_pid.get(pid, ())),
                     "owner": _owner(ctx, ctx.owns[pid])})
    return {"rows": rows}


def unlinked(ctx: Ctx, scope: SC.Scope) -> dict:
    """⚪ 「이관 안 됨」 — 한 번도 이관된 적 없는 곳(짝 맞추기 막힘 ``not-linked`` · I3 ⓐ · 보이는 가망만)."""
    rows = []
    for pid in sorted(visible(ctx, scope)):
        if any(r["state"] == S.PAIR_BLOCKED and r["code"] == CODE_NOT_LINKED for r in ctx.rows_by_pid.get(pid, ())):
            rows.append({"possibility_id": pid, "name": ctx.prospects[pid]["name"],
                         "stage": ctx.prospects[pid]["stage_key"], "owner": _owner(ctx, ctx.owns[pid])})
    return {"pairing_at": None if ctx.pairing is None else _iso(ctx.pairing["at"]), "rows": rows}


def bell(store: S.Store, viewer_idx: int, now: datetime) -> dict:
    """🔔 — 나에게 온 알림만(남겨 둔 것 포함) · 문구는 ``alerts.render`` 한 곳."""
    _need_time(now)
    since = now.astimezone(KST).date() - timedelta(days=BELL_DAYS - 1)
    items = []
    for r in store.my_alerts(viewer_idx, since):
        try:
            title, lines = AL.render(r["template"], r["source"], r["codes"], r["params"])
        except AL.RenderError:
            title, lines = "알림", ()
        items.append({"recipient_id": r["recipient_id"], "kind": r["kind"], "day": r["day"], "severity": r["severity"],
                      "title": title, "lines": list(lines), "link": r["link_path"], "status": r["status"],
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
