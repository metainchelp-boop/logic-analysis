"""자동화 계획의 현재 담당·계정 범위. 조회는 수집·AI·광고 변경을 시작하지 않는다."""
import re
from app.naver_auto import matching as M, org_snapshot as O, scope as SC
from . import approval_documents as D, handles as H, inventory as I, report_views as RV, setup_checks as SETUP


def ownership(ctx, company):
    pid = company["possibility_id"]
    return SC.ownership_for_client(ctx.org, pid, pid, SC.MATCH_PID)


def context(ctx, store, scope, selection="all"):
    catalog, state = I.catalog_status(store, ctx.now)
    if state != "accepted" or not O.allows_raising(ctx.freshness) or store.inventory_snapshot(ctx.now) is None:
        raise RV.SourceUnavailable()
    known = {r["possibility_id"]: r for r in catalog["items"] if r["stage_known"] and not r["stage_hidden"]}
    owns = {pid: ownership(ctx, row) for pid, row in known.items()}
    visible = SC.clients_in(ctx.org, scope, owns, selection)
    companies = {pid: row for pid, row in known.items() if pid in visible}
    try:
        matched, _ = I._matching(ctx, catalog, auto_evidence=I.automatic_evidence(store))
    except M.BadInput:
        raise RV.SourceUnavailable() from None
    pairs = {p.customer_id: p.possibility_id for p in matched.pairs}
    return companies, pairs


def resolve(ctx, store, scope, pid, key, selection="all"):
    companies, pairs = context(ctx, store, scope, selection)
    cids = [cid for cid, company in pairs.items() if company == pid and RV.account_key(cid) == key and cid in ctx.accounts]
    if pid not in companies or len(cids) != 1:
        raise SC.ClientNotVisible()
    return companies[pid], cids[0]


def view(ctx, store, scope, query):
    if set(query) - {"selection", "q", "page", "possibility_id", "account_key"}:
        raise RV.QueryInvalid()
    page, search, selection = query.get("page", "0"), query.get("q", ""), query.get("selection", "all")
    if (not isinstance(page, str) or not re.fullmatch(r"0|[1-9][0-9]{0,5}", page)
            or not isinstance(search, str) or len(search) > 200 or any(ord(c) < 32 for c in search)):
        raise RV.QueryInvalid()
    if ("possibility_id" in query) != ("account_key" in query):
        raise RV.QueryInvalid()
    companies, pairs = context(ctx, store, scope, selection)
    rows = []
    for cid, pid in pairs.items():
        if pid not in companies or cid not in ctx.accounts:
            continue
        company, account = companies[pid], ctx.accounts[cid]
        row = {"possibility_id": pid, "account_key": RV.account_key(cid), "company_name": company["company_name"],
               "account_name": account["account_name"], "ad_account_no": str(account["ad_account_no"]) if account["ad_account_no"] is not None else None,
               "workflow": H.stage_key(company["stage"])}
        if search.casefold() in " ".join(str(row[k] or "") for k in ("company_name", "account_name", "ad_account_no")).casefold():
            rows.append(row)
    rows.sort(key=lambda r: (r["company_name"] or "", r["account_name"] or "", r["account_key"]))
    page = int(page)
    if page and page * 100 >= len(rows):
        raise RV.QueryInvalid()
    out = {"accounts": rows[page*100:(page+1)*100], "total": len(rows), "page": page, "page_size": 100,
           "next_page": page+1 if (page+1)*100 < len(rows) else None, "selection": None, "plan": None,
           "can_edit": False, "can_approve": False, "execution_enabled": False, "policy": dict(D.POLICY),
           "provider_status": dict(D.PROVIDER_STATUS)}
    if "possibility_id" not in query:
        return out
    pid = RV._number(query, "possibility_id")
    key = query["account_key"]
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
        raise RV.QueryInvalid()
    cids = [cid for cid, company in pairs.items() if company == pid and RV.account_key(cid) == key and cid in ctx.accounts]
    if pid not in companies or len(cids) != 1:
        raise SC.ClientNotVisible()
    company, cid = companies[pid], cids[0]
    stage = H.stage_key(company["stage"])
    can_write = SC.ACT_APPROVE in SC.allowed_actions(ctx.org, scope, ownership(ctx, company))
    plan = store.automation_plan(pid, key)
    can_approve = can_write and stage in D.AUTO_STAGES
    if plan["approval_requires_lead"]:
        can_approve = can_approve and SC.can_approve(ctx.org, ownership(ctx, company), SC.LEVEL_LEAD,
            plan["author"]["actor"], scope.viewer_idx)
    projected = {"goal": plan["plan"]["goal"], "budget_plan": {"daily_budget": plan["plan"]["daily_spend_cap"]}}
    out.update(selection={"possibility_id": pid, "account_key": key, "workflow": stage}, plan=plan,
               can_edit=can_write and stage in D.EDIT_STAGES, can_approve=can_approve,
               learning_assets=store.learning_assets(pid, key),
               setup_checks=SETUP.project_setup(now=ctx.now, structure=store.structure_checks([cid], ctx.now).get(cid), plan=projected))
    return out
