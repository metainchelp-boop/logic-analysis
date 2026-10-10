"""영업 전용 읽기 투영. 관리 담당·내부 메모·보고서 초안은 이 경계를 통과하지 않는다."""
from datetime import timedelta
import math
import re

from app.naver_auto import matching as M, scope as SC
from . import inventory as INV, report_views as RV, store as S

PAGE_SIZE = 100
SOURCE_MAX_AGE = timedelta(hours=2)
GETS = frozenset({"/me", "/sales/clients", "/sales/detail", "/sales/report"})
METRICS = {"impressions": "impressions", "clicks": "clicks", "cost": "spend",
           "conversions": "conversions", "revenue": "conversion_value"}
RATIOS = ("ctr", "cpc", "cvr", "cpa", "roas")


def require_source(store, org, now):
    saved = store.org_current()
    latest = store.last_sync(S.SYNC_ORG)
    hold = store.hold(S.SYNC_ORG)
    if (not saved or not org.sales_source_present or not latest or latest["outcome"] != S.SYNC_ACCEPTED
            or (hold and hold["used_at"] is None)
            or not timedelta(0) <= now-org.generated_dt <= SOURCE_MAX_AGE
            or now.astimezone(S.KST).date() != org.generated_dt.astimezone(S.KST).date()):
        raise RV.SourceUnavailable()


def _context(ctx, store, scope):
    if scope.kind != SC.SALES_READ or SC.scope_of(ctx.org, scope.viewer_idx) != scope:
        raise SC.ClientNotVisible()
    require_source(store, ctx.org, ctx.now)
    catalog, status = INV.catalog_status(store, ctx.now)
    if status != "accepted":
        raise RV.SourceUnavailable()
    pids = {pid for pid, seller in ctx.org.sales_contracts if seller == scope.viewer_idx}
    # 반드시 전체 원천에서 연결 충돌을 판정한 다음 판매 범위와 교차한다.
    companies = {row["possibility_id"]: row for row in catalog["items"]
                 if row["possibility_id"] in pids and row["stage_known"] is True
                 and row["stage_hidden"] is False and row["stage"] == "진행중"}
    if store.inventory_snapshot(ctx.now) is None:
        raise RV.SourceUnavailable()
    try:
        matched, _ = INV._matching(ctx, catalog, auto_evidence=INV.automatic_evidence(store))
    except M.BadInput:
        raise RV.SourceUnavailable() from None
    pairs = {row.customer_id: row.possibility_id for row in matched.pairs
             if row.possibility_id in companies and row.customer_id in ctx.accounts
             and ctx.accounts[row.customer_id]["present"] == 1}
    return companies, pairs


def _value(value):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 2**53-1 else None


def _metrics(selected):
    totals, ratios = (selected or {}).get("totals", {}), (selected or {}).get("ratios", {})
    return {**{name: _value(totals.get(raw)) for name, raw in METRICS.items()},
            **{name: _value(ratios.get(name)) for name in RATIOS}}


def _selected(report, cid, period):
    if not report or report["period_key"] != period.key:
        return None
    payload = report["payload"]
    selected = RV._account_payload(payload, RV.account_key(cid))
    if (payload.get("format_version") != 2 or not isinstance(selected, dict)
            or selected.get("_expected_customers") != [cid]
            or selected.get("period") != payload.get("period")
            or selected.get("period_key") != period.key
            or payload.get("period", {}).get("kind") != period.kind
            or payload.get("period", {}).get("start") != str(period.start)
            or payload.get("period", {}).get("end") != str(period.end)):
        return None
    return selected


def _account(ctx, cid, report, period):
    account = ctx.accounts[cid]
    selected = _selected(report, cid, period)
    return {"account_key": RV.account_key(cid), "account_name": account["account_name"],
            "ad_account_no": str(account["ad_account_no"]) if account["ad_account_no"] is not None else None,
            "status": RV._collection_status(selected) if selected else "not_generated",
            "report_id": report["report_id"] if selected else None, "metrics": _metrics(selected)}


def clients(ctx, store, scope, query, *, detail=False):
    allowed = {"kind", "anchor", "pid"} if detail else {"kind", "anchor", "q", "page"}
    if set(query)-allowed:
        raise RV.QueryInvalid()
    period = RV._period(query, ctx.now)
    companies, pairs = _context(ctx, store, scope)
    if detail:
        pid = RV._number(query, "pid")
        if pid not in companies:
            raise SC.ClientNotVisible()
        companies = {pid: companies[pid]}
    search = query.get("q", "")
    raw_page = query.get("page", "1")
    if (not isinstance(search, str) or len(search) > 200 or
            not isinstance(raw_page, str) or not re.fullmatch(r"[1-9][0-9]{0,5}", raw_page)):
        raise RV.QueryInvalid()
    page, normalized = int(raw_page), " ".join(search.split()).casefold()
    grouped = {pid: sorted(cid for cid, company in pairs.items() if company == pid) for pid in companies}
    ordered = [pid for pid, row in companies.items() if normalized in " ".join(
        [row["company_name"] or ""] + [str(ctx.accounts[cid].get(field) or "")
         for cid in grouped[pid] for field in ("account_name", "ad_account_no")]).casefold()]
    ordered.sort(key=lambda pid: (companies[pid]["company_name"] or "", pid))
    total = len(ordered)
    if page > 1 and (page-1)*PAGE_SIZE >= total:
        raise RV.QueryInvalid()
    pids = ordered[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
    latest = store.report_latest_ids(period.key, pids)
    items = []
    for pid in pids:
        report = store.report_snapshot_detail(latest[pid]) if pid in latest else None
        items.append({"possibility_id": pid, "company_name": companies[pid]["company_name"], "stage": "진행중",
                      "connection_status": "connected" if grouped[pid] else "pending",
                      "accounts": [_account(ctx, cid, report, period) for cid in grouped[pid]]})
    result = {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE,
              "period": period.as_dict(), "source_as_of": ctx.org.generated_at,
              "next_page": page+1 if page*PAGE_SIZE < total else None}
    return {**result, **items[0]} if detail else result


def report(ctx, store, scope, query):
    if set(query)-{"pid", "account_key", "kind", "anchor"}:
        raise RV.QueryInvalid()
    pid, key = RV._number(query, "pid"), query.get("account_key")
    if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
        raise RV.QueryInvalid()
    period = RV._period(query, ctx.now)
    companies, pairs = _context(ctx, store, scope)
    current = {RV.account_key(cid): cid for cid, company in pairs.items() if company == pid}
    if pid not in companies or key not in current:
        raise SC.ClientNotVisible()
    rid = store.report_latest_ids(period.key, [pid]).get(pid)
    saved = store.report_snapshot_detail(rid) if rid else None
    selected = _selected(saved, current[key], period)
    if selected is None or not saved.get("revision_fingerprint"):
        raise SC.ClientNotVisible()
    notes = store.report_notes(rid, key, saved["revision_fingerprint"])
    shared = notes.get("shared")
    if (not isinstance(shared, dict) or shared.get("state") != "approved"
            or shared.get("metadata", {}).get("report_id") != rid
            or shared["metadata"].get("account_key") != key
            or shared["metadata"].get("revision_fingerprint") != saved["revision_fingerprint"]):
        raise SC.ClientNotVisible()
    return {"company_name": companies[pid]["company_name"], "possibility_id": pid,
            **_account(ctx, current[key], saved, period), "period": period.as_dict(),
            "generated_at": saved["generated_at"], "checked_at": ctx.now.isoformat(), "comparison": None,
            "comment": {name: shared.get(name) for name in ("shared_comment", "next_plan", "plan_due", "targets")},
            "approval_version": shared["version"]}
