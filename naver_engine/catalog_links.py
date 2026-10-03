"""현재 전체 전산 원천의 짝 확인. 계약별 점검 context와 저장 pairing은 바꾸지 않는다."""
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime
import hashlib
import hmac
import json
import os
from typing import Optional

from app.naver_auto import matching as M, org_snapshot as O, scope as SC
from . import handles as H, inventory as I, links as L, store as S, views as W

_REF_KEY = os.urandom(32)
_REF_PREFIX = "catalog:"


def _json(value):
    def encode(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, (set, frozenset)):
            return sorted(item)
        raise TypeError("짝 확인 원천의 자료형이 다릅니다")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=encode)


@dataclass(frozen=True)
class Context:
    ctx: W.Ctx
    scope: SC.Scope
    companies: dict
    source_key: str
    source_state: str
    catalog_at: Optional[datetime]
    detail_ids: frozenset
    visible_ids: frozenset


def load(store, now, org, scope, selection="all", *, narrowed=False):
    """catalog가 한 번도 없을 때만 None. 실패/만료 수락본은 legacy로 되돌리지 않는다."""
    catalog, state = I.catalog_status(store, now)
    catalog_status = store.account_catalog_status()
    if catalog is None and catalog_status is None:
        return None
    if catalog is None:
        state = "failed"
    base = W.load(store, now, org)
    companies = {} if catalog is None else {row["possibility_id"]: row for row in catalog["items"]}
    owns, names = {}, {}
    for pid, company in companies.items():
        owns[pid] = (SC.Ownership(client_id=pid, main=None, match=SC.MATCH_UNKNOWN)
                     if company["stage_hidden"] or not company["stage_known"] else
                     SC.ownership_for_client(org, pid, pid, SC.MATCH_PID))
        key = M.loose_name(company["company_name"])
        if key is not None:
            names.setdefault(key, set()).add(pid)
    visible_ids = SC.clients_in(org, scope, owns, selection)
    snapshot = store.inventory_snapshot(now)
    source = {"catalog": catalog, "catalog_status": catalog_status,
              "accounts": list(base.accounts.values()), "accounts_at": store.accounts_read_at(),
              "accounts_sync": store.last_sync(S.SYNC_ACCOUNTS),
              "org": {"generated_at": org.generated_at,
                      "people": [asdict(p) for _, p in sorted(org.people.items())],
                      "teams": [asdict(t) for _, t in sorted(org.teams.items())],
                      "owners": [asdict(owner) for owner in org.owners]},
              "decisions": [asdict(d) for d in base.live_decisions + base.lost_decisions],
              # 기존 계약의 읽기 실패/종료일 근거가 있으면 확인에서도 버리지 않는다.
              "legacy": list(base.prospects.values()), "scope": asdict(scope), "selection": selection,
              "narrowed": narrowed}
    source_key = hashlib.sha256(_json(source).encode("utf-8")).hexdigest()
    if state == "accepted" and snapshot is None:
        state = "accounts-unavailable"
    if state == "accepted" and not O.allows_raising(base.freshness):
        state = "org-stale"
    rows = {}
    if state == "accepted":
        try:
            result, _ = I._matching(base, catalog)
            raw = L._rows(result, base.live_decisions, base.lost_decisions, store.account_times(),
                          set(companies), set())
            for row in raw:
                normalized = {"code": None, "same_name": None, "claimed_elsewhere": None,
                              "decision_id": None, "link": None, **row}
                rows.setdefault(row["possibility_id"], []).append(normalized)
        except M.BadInput:
            state = "matching-unavailable"
    context = replace(base, owns=owns, rows_by_pid={pid: tuple(rs) for pid, rs in rows.items()},
                      name_owners={key: frozenset(ids) for key, ids in names.items()})
    return Context(context, scope, companies, source_key, state,
                   None if catalog is None else datetime.fromisoformat(catalog["generated_at"]),
                   W.visible(base, scope), visible_ids)


def make_ref(context, row):
    identity = [context.source_key, row["possibility_id"], row["customer_id"], row["state"], row["code"]]
    return _REF_PREFIX + hmac.new(_REF_KEY, _json(identity).encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def pair_key(row):
    """새 목록에서 같은 짝을 찾는 표시용 키. 확인 resolver는 이 값을 받지 않는다."""
    identity = ["pair", row["possibility_id"], row["customer_id"]]
    return hmac.new(_REF_KEY, _json(identity).encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def find_ref(context, ref):
    if not isinstance(ref, str) or not ref.startswith(_REF_PREFIX) or len(ref) != len(_REF_PREFIX) + 32:
        return None
    for rows in context.ctx.rows_by_pid.values():
        for row in rows:
            if hmac.compare_digest(make_ref(context, row), ref):
                return row
    return None


def allowed(context, row):
    """기존 verified 범위만: 현재 명시 번호의 자동 짝/이름 불일치, 충돌과 이름 후보는 확인 불가."""
    ctx, scope = context.ctx, context.scope
    if context.source_state != "accepted" or scope.kind not in (SC.ALL, SC.MINE) or row is None:
        return False
    if row["state"] != S.PAIR_AUTO and not (row["state"] == S.PAIR_BLOCKED and row["code"] == M.B_NAME_DIFFERENT):
        return False
    pid, cid = row["possibility_id"], row["customer_id"]
    if pid not in context.visible_ids:
        return False
    own, company, account = ctx.owns.get(pid), context.companies.get(pid), ctx.accounts.get(cid)
    if own is None or SC.ACT_CONFIRM_LINK not in SC.allowed_actions(ctx.org, scope, own):
        return False
    if not company or company["stage_hidden"] or not company["stage_known"] or not account or account["present"] != 1:
        return False
    if W.link_holders(ctx, pid, cid) or row.get("claimed_elsewhere"):
        return False
    if any(d.possibility_id == pid and d.customer_id == cid for d in ctx.live_decisions):
        return False
    legacy, end = ctx.prospects.get(pid), None
    if legacy is not None:
        if legacy["stage_conflict"] or legacy["end_unreadable"]:
            return False
        end = None if legacy["latest_end_date"] is None else date.fromisoformat(legacy["latest_end_date"])
    return H.eligibility_reason(company["stage"], context.catalog_at, end, ctx.now) is None


def pending(context):
    ctx, scope = context.ctx, context.scope
    ids = context.visible_ids
    rows = []
    for pid in sorted(ids):
        for row in ctx.rows_by_pid.get(pid, ()):
            if row["state"] not in W.PENDING_STATES:
                continue
            cid = row["customer_id"]
            customer = cid is not None and row["code"] not in W.NOT_A_CUSTOMER
            holders = W.link_holders(ctx, pid, cid) if customer else frozenset()
            clear = customer and W.clear_for(ctx, scope, pid, row, holders)
            account = ctx.accounts.get(cid) if clear else None
            rows.append({"ref": make_ref(context, row), "pair_key": pair_key(row), "possibility_id": pid,
                         "name": context.companies[pid]["company_name"], "state": row["state"], "code": row["code"],
                         "tail": W.tail4(cid), "account_name": None if account is None else account["account_name"],
                         "same_name": row["same_name"],
                         "other_candidate": customer and (bool(row["claimed_elsewhere"]) or
                                                           row["code"] in W.CLAIM_CODES or bool(holders)),
                         "can_confirm": allowed(context, row), "can_reject": False,
                         "confirm_blocked": None, "detail_available": pid in context.detail_ids})
    decisions = [{"decision_id": d.decision_id, "possibility_id": d.possibility_id,
                  "name": context.companies[d.possibility_id]["company_name"],
                  "detail_available": d.possibility_id in context.detail_ids,
                  "decision": d.decision, "tail": W.tail4(d.customer_id),
                  "decided_by": W._person_name(ctx.org, d.decided_by), "decided_at": W._iso(d.decided_at)}
                 for d in ctx.live_decisions + ctx.lost_decisions
                 if d.possibility_id in ids and SC.ACT_CONFIRM_LINK in
                 SC.allowed_actions(ctx.org, scope, ctx.owns[d.possibility_id])]
    return {"source": "catalog", "source_state": context.source_state,
            "pairing_at": W._iso(context.catalog_at),
            "pairing_today": context.catalog_at is not None and context.catalog_at.astimezone(S.KST).date() == ctx.today,
            "rows": rows, "decisions": decisions}
