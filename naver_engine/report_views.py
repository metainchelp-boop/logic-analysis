"""계정 보고서 조회. 현재 권한을 먼저 적용하며 저장 자료만 읽는다."""
from datetime import date, timedelta
import hashlib
import re

from app.naver_auto import matching as M, org_snapshot as O, scope as SC
from . import inventory as INV, management as MG, reporting as R, views as W


PAGE_SIZE = 20
SCHEDULE = {"timezone": "Asia/Seoul", "weekly": "월요일 10:00", "monthly": "매월 3일 10:00"}
PRIVATE_FIELDS = frozenset({"customer_id", "source_account_ids", "expected_customers_json",
    "source_manifest", "comparison_source_manifest", "matching_fingerprint", "campaign_fingerprint", "source_generation"})


class QueryInvalid(ValueError):
    pass


class SourceUnavailable(ValueError):
    pass


def account_key(customer_id):
    """표시 식별자일 뿐 권한 토큰이 아니다. 원천 고객 번호는 응답에 싣지 않는다."""
    return hashlib.sha256(str(customer_id).encode("ascii")).hexdigest()


def public_payload(value):
    """새 상세와 구 목록/이력 모두 중첩된 원천 식별자를 숨긴다."""
    if isinstance(value, dict):
        return {key: public_payload(item) for key, item in value.items()
                if not str(key).startswith("_") and key not in PRIVATE_FIELDS}
    if isinstance(value, (list, tuple)):
        return [public_payload(item) for item in value]
    return value


def _number(query, key, default=None):
    raw = query.get(key)
    if raw is None and default is not None:
        return default
    if not isinstance(raw, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", raw):
        raise QueryInvalid()
    return int(raw)


def _period(query, now):
    kind = query.get("kind", "weekly")
    if kind not in ("weekly", "monthly"):
        raise QueryInvalid()
    anchor = query.get("anchor")
    if anchor is not None:
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", anchor):
                raise ValueError()
            return R.period(kind, date.fromisoformat(anchor))
        except (ValueError, OverflowError):
            raise QueryInvalid() from None
    current = R.period(kind, now.astimezone(R.KST).date())
    while current.due_at > now:
        current = R.period(kind, current.start-timedelta(days=1))
    return current


def _context(ctx, store, scope, owns, selection):
    catalog, state = INV.catalog_status(store, ctx.now)
    if state != "accepted" or not O.allows_raising(ctx.freshness):
        raise SourceUnavailable()
    visible = SC.clients_in(ctx.org, scope, owns, selection)
    companies = {r["possibility_id"]: r for r in catalog["items"]
                 if r["possibility_id"] in visible and r["stage_known"] and not r["stage_hidden"]
                 and "".join((r["stage"] or "").split()) in MG.DAILY_STAGES}
    if store.inventory_snapshot(ctx.now) is None:
        raise SourceUnavailable()
    try:
        matched, _ = INV._matching(ctx, catalog, auto_evidence=INV.automatic_evidence(store))
    except M.BadInput:
        raise SourceUnavailable() from None
    pairs = {p.customer_id: p.possibility_id for p in matched.pairs}
    return companies, pairs


def accounts(ctx, store, scope, owns, query):
    if set(query)-{"selection", "kind", "anchor", "q", "page", "possibility_id"}:
        raise QueryInvalid()
    raw_page, search = query.get("page", "0"), query.get("q", "")
    if not re.fullmatch(r"0|[1-9][0-9]{0,5}", raw_page) or len(search) > 200 or any(ord(c) < 32 for c in search):
        raise QueryInvalid()
    page, period = int(raw_page), _period(query, ctx.now)
    selection = query.get("selection", "all")
    companies, pairs = _context(ctx, store, scope, owns, selection)
    if "possibility_id" in query:
        pid = _number(query, "possibility_id")
        if pid not in companies:
            raise SC.ClientNotVisible()
        companies = {pid: companies[pid]}
    rows = []
    for cid, pid in pairs.items():
        if pid not in companies:
            continue
        company, account = companies[pid], ctx.accounts[cid]
        rows.append({"possibility_id": pid, "company_name": company["company_name"],
                     "account_key": account_key(cid), "ad_account_no": str(account["ad_account_no"]) if account["ad_account_no"] is not None else None,
                     "account_name": account["account_name"], "owner": W._owner(ctx, owns[pid]),
                     "workflow": "".join((company["stage"] or "").split()), "period": period.as_dict(),
                     "status": "not_generated", "report_id": None, "revision_no": None,
                     "generated_at": None, "details_status": "legacy_unavailable"})
    linked = {row["possibility_id"] for row in rows}
    unlinked = len(set(companies)-linked)
    normalized = " ".join(search.split()).casefold()
    rows = [row for row in rows if normalized in " ".join(str(row[key] or "") for key in
            ("company_name", "account_name", "ad_account_no")).casefold()]
    rows.sort(key=lambda row: (row["company_name"] or "", row["account_name"] or "", row["account_key"]))
    total = len(rows)
    if page and page*PAGE_SIZE >= total:
        raise QueryInvalid()
    page_rows = rows[page*PAGE_SIZE:(page+1)*PAGE_SIZE]
    latest = {r["possibility_id"]: r for r in store.report_snapshots()
              if r["possibility_id"] in companies and r["period_key"] == period.key}
    snapshots = {}
    for row in page_rows:
        report = latest.get(row["possibility_id"])
        if report is None:
            continue
        rid = report["report_id"]
        if rid not in snapshots:
            snapshots[rid] = store.report_snapshot_detail(rid)
        raw = snapshots[rid]
        selected = _account_payload(raw["payload"], row["account_key"]) if raw else None
        if raw is None or (raw["payload"].get("format_version") == 2 and selected is None):
            continue
        row.update(report_id=rid, revision_no=report.get("revision_no"), generated_at=report["generated_at"],
                   status=selected["status"] if selected else "collecting",
                   details_status=selected.get("details", {}).get("status", "legacy_unavailable") if selected else "legacy_unavailable")
    return {"rows": page_rows, "total": total, "page": page,
            "page_size": PAGE_SIZE, "next_page": page+1 if (page+1)*PAGE_SIZE < total else None,
            "selection": selection, "period": period.as_dict(), "unlinked_companies": unlinked, "schedule": SCHEDULE}


def _members(payload):
    result = {}
    for raw in payload.get("_account_reports", {}):
        if isinstance(raw, (str, int)) and re.fullmatch(r"[1-9][0-9]{0,18}", str(raw)):
            cid = int(raw)
            result[account_key(cid)] = cid
    return result


def _account_payload(payload, key):
    cid = _members(payload).get(key)
    return payload.get("_account_reports", {}).get(str(cid)) if cid is not None else None


def _unavailable(payload):
    """옛 업체 합계를 계정의 값으로 가장하거나 현재 원천과 섞지 않는다."""
    return {"format_version": payload.get("format_version", 1), "period": public_payload(payload.get("period", {})),
            "period_key": payload.get("period_key"), "generated_at": payload.get("generated_at"),
            "status": "collecting", "ready": False, "totals": {name: None for name in R.OUTPUT_FIELDS.values()},
            "ratios": {name: None for name in ("ctr", "cpc", "roas", "cvr", "cpa")},
            "coverage": {"accounts": 1, "expected_account_days": payload.get("period", {}).get("days"),
                         "basic_complete": False, "conversion_complete": False,
                         "basic_complete_account_days": None, "conversion_complete_account_days": None},
            "missing": [], "missing_count": None,
            "details": {"status": "legacy_unavailable", "daily": [], "briefing": [],
                        "comparison": {"status": "insufficient_data"}, "management_records": [], "next_actions": []}}


def detail(ctx, store, scope, owns, query):
    if set(query)-{"report_id", "account_key", "possibility_id", "period_key"}:
        raise QueryInvalid()
    rid, key = _number(query, "report_id"), query.get("account_key")
    if not isinstance(key, str) or (key != "company" and not re.fullmatch(r"[0-9a-f]{64}", key)):
        raise QueryInvalid()
    companies, pairs = _context(ctx, store, scope, owns, "all")
    report = store.report_snapshot_detail(rid)
    if report is None or report["possibility_id"] not in companies:
        raise SC.ClientNotVisible()
    pid, payload = report["possibility_id"], report["payload"]
    if "possibility_id" in query and _number(query, "possibility_id") != pid:
        raise SC.ClientNotVisible()
    if "period_key" in query and query["period_key"] != report["period_key"]:
        raise SC.ClientNotVisible()
    # 보고서 자체가 가진 기간을 검증한다. 요청한 다른 판의 기간과 섞지 않는다.
    try:
        saved_period = payload["period"]
        period = R.period(saved_period["kind"], date.fromisoformat(saved_period["start"]))
        if period.key != report["period_key"] or saved_period["end"] != str(period.end):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise SC.ClientNotVisible() from None
    members = _members(payload)
    if key != "company" and key not in members:
        # 구형에는 계정별 저장 증거가 없다. 현재 확정 연결에 대해서만 미보관 화면을 제공한다.
        current = {account_key(cid): cid for cid, company in pairs.items() if company == pid}
        if payload.get("format_version") == 2 or key not in current:
            raise SC.ClientNotVisible()
        members = {key: current[key]}
        selected = _unavailable(payload)
    else:
        selected = payload if key == "company" else _account_payload(payload, key)
    if selected is None:
        raise SC.ClientNotVisible()
    if selected.get("period_key") != report["period_key"] or selected.get("period") != payload.get("period"):
        raise SC.ClientNotVisible()
    if key != "company" and "_expected_customers" in selected and selected["_expected_customers"] != [members[key]]:
        raise SC.ClientNotVisible()

    def identity(member_key, cid):
        # 재매칭된 계정의 새 이름/광고번호를 과거 업체 담당에게 넘기지 않는다.
        account = ctx.accounts.get(cid) if pairs.get(cid) == pid else None
        return {"account_key": member_key,
                "ad_account_no": str(account["ad_account_no"]) if account and account["ad_account_no"] is not None else None,
                "account_name": account["account_name"] if account else None}

    # aggregate의 account_index는 원천 계정 번호순이다. 공개 목록도 같은 순서로 맞춘다.
    included = [identity(member_key, cid) for member_key, cid in sorted(members.items(), key=lambda item: item[1])]
    chosen = identity(key, members[key]) if key != "company" else {
        "account_key": "company", "ad_account_no": None, "account_name": None}
    cleaned = public_payload(selected)
    missing = cleaned.get("missing")
    if isinstance(missing, list) and cleaned.get("details", {}).get("status") != "legacy_unavailable":
        cleaned.update(missing=missing[:100], missing_count=len(missing), missing_truncated=len(missing)>100)
    if "details" not in cleaned:
        cleaned["details"] = {"status": "legacy_unavailable", "daily": [], "briefing": [],
                              "comparison": {"status": "insufficient_data"}, "management_records": [], "next_actions": []}
    return {**{field: public_payload(report[field]) for field in ("report_id", "period_key", "revision_no",
                "revision_fingerprint", "generated_at", "review_status", "validation", "change_summary") if field in report},
            "possibility_id": pid, "company_name": companies[pid]["company_name"], "owner": W._owner(ctx, owns[pid]),
            "status": selected.get("status", report["status"]), "can_review": False, "payload": cleaned,
            "validation": public_payload(report.get("validation", {})) if key == "company" else
                          public_payload(selected.get("validation", {"status": "unknown", "scope": "account"})),
            "change_summary": public_payload(report.get("change_summary")) if key == "company" else
                              public_payload(selected.get("change_summary")),
            "scope": {"kind": "company" if key == "company" else "account", **chosen,
                      "accounts": included if key == "company" else [chosen]}}
