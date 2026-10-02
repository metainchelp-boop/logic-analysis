"""현재 이관 계정 원장. 전산 존재/매칭/업무단계/수집 상태를 혼합하지 않는다."""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
import math

from app.naver_auto import matching as M, scope as SC
from . import erp_read as E, handles as H, links as L, store as S, views as W

WORKFLOWS = ("진행중", "전략관리", "사후관리", "재계약진행중", "환불중", "홀딩중", "환불완료", "계약만료", "미분류")
MAPPINGS = ("matched", "no_erp_record", "unclassified")
CATALOG_INTERVAL = timedelta(hours=1)
CATALOG_RETRY = timedelta(minutes=30)


def sync_catalog_due(store, now):
    state = store.account_catalog_status()
    if state is None:
        return True
    at = datetime.fromisoformat(state["at"])
    return at > now or now-at >= (CATALOG_INTERVAL if state["state"] == "accepted" else CATALOG_RETRY)


def sync_catalog(reader, store, now):
    """새 전체 목록과 번호를 모두 받은 뒤에만 원자적으로 교체한다."""
    try:
        body = reader.read_account_catalog()
        ids = reader.read_naver_customer_ids_snapshot()
        store.record_account_catalog(body, ids, now)
        return {"state": "accepted", "total": body["total"]}
    except (E.ErpError, S.StoreRefused):
        store.record_account_catalog_failure(now, "CATALOG_FAILED")
        return {"state": "failed", "code": "CATALOG_FAILED"}


def catalog_status(store, now):
    body, result = store.account_catalog(), store.account_catalog_status()
    if body is None:
        return body, "missing"
    if not result or result["state"] != "accepted":
        return body, "failed"
    at = datetime.fromisoformat(body["generated_at"])
    if not -timedelta(minutes=5) <= now-at <= CATALOG_INTERVAL * 2:
        return body, "stale"
    return body, "accepted"


def _matching(ctx, catalog, *, include_absent=False):
    current = {cid: {"customerId": cid, "adAccountNo": a["ad_account_no"], "adAccountName": a["account_name"]}
               for cid, a in ctx.accounts.items() if a["present"] == 1 or include_absent}
    # 전체 가망 × 계정의 이중 루프를 피한다. 번호 주장/사람 확인은 전부 유지하고,
    # 이름 후보는 같은 이름 또는 3글자 이상 포함 관계가 가능한 업체만 규칙 모듈에 넘긴다.
    names = {cid: M.loose_name(a["adAccountName"]) for cid, a in current.items()}
    grams, exact, account_grams = {}, {}, {}
    for cid, key in names.items():
        if key is None:
            continue
        exact.setdefault(key, set()).add(cid)
        parts = {key[i:i+3] for i in range(len(key)-2)}
        account_grams[cid] = parts
        for part in parts:
            grams.setdefault(part, set()).add(cid)
    # 계정 이름이 업체 이름 안에 들어가는 방향: 계정마다 가장 드문 3글자만 색인한다.
    # 실제 포함 관계라면 그 기준 3글자도 반드시 업체 이름 안에 있으므로 후보를 빠뜨리지 않는다.
    anchors = {}
    for cid, parts in account_grams.items():
        if parts:
            anchor = min(parts, key=lambda part: (len(grams[part]), part))
            anchors.setdefault(anchor, set()).add(cid)
    relevant = {r["possibility_id"] for r in catalog["ids"]}
    relevant.update(d.possibility_id for d in ctx.live_decisions)
    people, possible_accounts, related_cache = [], set(), {}
    for row in catalog["items"]:
        pid, name = row["possibility_id"], row["company_name"]
        key = M.loose_name(name)
        if key not in related_cache:
            related = set(exact.get(key, ()))
            parts = set() if key is None else {key[i:i+3] for i in range(len(key)-2)}
            if parts:
                # 업체 이름이 계정 이름 안에 들어가는 방향은 모든 3글자가 있어야 한다.
                # 공통 접두어 하나 때문에 모든 계정을 훑지 않도록 가장 작은 집합부터 교차한다.
                postings = sorted((grams.get(part, ()) for part in parts), key=len)
                forward = set(postings[0])
                for posting in postings[1:]:
                    if not forward:
                        break
                    forward.intersection_update(posting)
                related.update(cid for cid in forward if key in names[cid])
                reverse = set()
                for part in parts:
                    reverse.update(anchors.get(part, ()))
                related.update(cid for cid in reverse if names[cid] in key)
            related_cache[key] = tuple(related)
            # 동명이름은 한 번만 합치되 표시용 후보 상한/이미 매칭된 업체와 무관하게 모두 보존한다.
            possible_accounts.update(related)
        related = related_cache[key]
        if pid in relevant or related:
            people.append(M.ErpProspect(pid, name))
    ids = [M.ErpCredential(r["possibility_id"], r["vendor"], r["customer_id_raw"],
                           ad_account_no_raw=r["ad_account_no_raw"]) for r in catalog["ids"]]
    decisions = [M.HumanDecision(d.possibility_id, d.customer_id, d.decision) for d in ctx.live_decisions]
    return M.match(people, ids, current, decisions, accounts_complete=True), possible_accounts


def _known_balance(value):
    return type(value) in (int, float) and math.isfinite(value) and abs(value) <= 9007199254740991


def _lost_rows(ctx, store, catalog, visible, owns, ceo, selection):
    """수락된 과거 계정만 기존 부재 기준으로 센다. 현재 계정 합계/권한에는 섞지 않는다."""
    times = store.account_times()
    absent = {cid for cid, account in ctx.accounts.items() if account["present"] != 1
              and cid in times and L.link_state(times[cid])[0] == S.PAIR_BROKEN}
    if not absent:
        return []
    # 현재 번호 주장과 충돌하는 과거 계정을 직원 소유로 추정하지 않는다.
    result, _ = _matching(ctx, catalog, include_absent=True)
    pairs, duplicates = {}, set()
    for pair in result.pairs:
        if pair.customer_id in pairs:
            duplicates.add(pair.customer_id)
        pairs[pair.customer_id] = pair
    companies = {r["possibility_id"]: r for r in catalog["items"]}
    rows = []
    for cid in sorted(absent):
        pair = None if cid in duplicates else pairs.get(cid)
        company = companies.get(pair.possibility_id) if pair else None
        pid = company["possibility_id"] if company else None
        uncertain = company is None or company["stage_hidden"] or not company["stage_known"]
        if not ceo or selection not in ("all", "unassigned"):
            if pid not in visible or uncertain:
                continue
        elif selection == "unassigned" and pid is not None and pid not in visible:
            continue
        account = ctx.accounts[cid]
        stage = H.stage_key(company["stage"]) if not uncertain else "미분류"
        rows.append({"ad_account_no": None if account["ad_account_no"] is None else str(account["ad_account_no"]),
                     "customer_tail": W.tail4(cid), "account_name": account["account_name"],
                     "possibility_id": pid, "company_name": None if company is None else company["company_name"],
                     "mapping": "unclassified" if uncertain else "matched", "workflow": stage if stage in WORKFLOWS else "미분류",
                     "owner": W._owner(ctx, owns[pid]) if pid is not None else None,
                     "collection": {"status": "not_current", "checked_at": times[cid]["absent_last_at"].isoformat()},
                     "detail_available": False, "reason": "LINK_BROKEN"})
    return rows


def board(ctx, store, scope, selection="all", workflow="all", mapping="all", view="current"):
    if workflow not in ("all", *WORKFLOWS) or mapping not in ("all", *MAPPINGS) \
            or view not in ("current", "lost", "balance_known"):
        raise SC.SelectionRejected()
    catalog, state = catalog_status(store, ctx.now)
    companies = {} if catalog is None else {r["possibility_id"]: r for r in catalog["items"]}
    owns = {pid: SC.ownership_for_client(ctx.org, pid, pid, SC.MATCH_PID) for pid in companies}
    # 모든 요청에서 재판정. 잘못된 person/team 선택도 데이터가 0건이라고 조용히 허용하지 않는다.
    visible = SC.clients_in(ctx.org, scope, owns, selection)
    all_scope = SC.scope_of(ctx.org, scope.viewer_idx)
    ceo = scope == all_scope and scope.kind == SC.ALL
    at = store.accounts_read_at()
    accounts_current = store.inventory_snapshot(ctx.now) is not None
    pairs, ambiguous = {}, set()
    match_ok = state == "accepted" and accounts_current
    if match_ok:
        try:
            result, possible_accounts = _matching(ctx, catalog)
            for p in result.pairs:
                if p.customer_id in pairs:
                    ambiguous.add(p.customer_id)
                pairs[p.customer_id] = p
            ambiguous.update(possible_accounts - pairs.keys())
            ambiguous.update(c.customer_id for c in result.candidates)
            # 다른 업체의 차단된 주장이 이미 사람 확인으로 확정된 짝을 뒤집지 않는다.
            ambiguous.update(b.customer_id for b in result.blocked if b.customer_id is not None and b.customer_id not in pairs)
            ad_to_cid = {a["ad_account_no"]: cid for cid, a in ctx.accounts.items() if a["present"] == 1}
            for cred in catalog["ids"]:
                if cred["vendor"] != M.VENDOR_NAVER:
                    continue
                raw = cred["ad_account_no_raw"]
                target = ad_to_cid.get(int(raw)) if isinstance(raw, str) and raw.isascii() and raw.isdigit() else None
                cid, _ = M.parse_customer_id(cred["customer_id_raw"])
                ambiguous.update(c for c in (target, cid) if c in ctx.accounts and c not in pairs)
        except M.BadInput:
            match_ok = False
    checks = store.inventory_checks_on(ctx.today)
    rows, counts, stages = [], Counter({m: 0 for m in MAPPINGS}), Counter({s: 0 for s in WORKFLOWS})
    balances = []
    for cid, account in sorted(ctx.accounts.items()):
        if account["present"] != 1:
            continue
        pair = pairs.get(cid)
        company = companies.get(pair.possibility_id) if pair else None
        pid = pair.possibility_id if company else None
        uncertain = not match_ok or cid in ambiguous or (company and (company["stage_hidden"] or not company["stage_known"]))
        status = "unclassified" if uncertain else ("matched" if company else "no_erp_record")
        # 확정/번호 매칭 이외에는 직원에게 계정 존재·수집 지표·후보도 보이지 않는다.
        if not ceo or selection not in ("all", "unassigned"):
            if pid not in visible or uncertain:
                continue
        elif selection == "unassigned" and pid is not None and pid not in visible:
            continue
        key = H.stage_key(company["stage"]) if company and company["stage_known"] and not company["stage_hidden"] else ""
        stage = key if key in WORKFLOWS else "미분류"
        counts[status] += 1
        stages[stage] += 1
        check = checks.get(cid)
        balance = None if check is None else check.get("bizmoney")
        known = match_ok and _known_balance(balance)
        if known:
            balances.append(Decimal(str(balance)))
        if workflow not in ("all", stage) or mapping not in ("all", status):
            continue
        if view == "balance_known" and not known:
            continue
        owner = W._owner(ctx, owns[pid]) if pid is not None else None
        # 원천 지표를 전산 계약/보고서에 자동 귀속하거나 이전 이력을 덮어쓰지 않는다.
        rows.append({"ad_account_no": None if account["ad_account_no"] is None else str(account["ad_account_no"]),
                     "customer_tail": W.tail4(cid), "account_name": account["account_name"],
                     "possibility_id": pid, "company_name": None if company is None else company["company_name"],
                     "mapping": status, "workflow": stage, "erp_stage": None if company is None else company["stage"],
                     "owner": owner, "collection": check or {"status": "pending", "checked_at": None},
                     "detail_available": pid in ctx.prospects and ctx.prospects[pid]["present"] == 1 and not uncertain,
                     "reason": "SOURCE_UNAVAILABLE" if not match_ok else
                               ("MATCH_REVIEW" if uncertain else ("NO_ERP_MATCH" if company is None else None))})
    lost = []
    lost_ready = match_ok
    if lost_ready:
        try:
            lost = _lost_rows(ctx, store, catalog, visible, owns, ceo, selection)
        except M.BadInput:
            lost_ready = False
    if view == "lost":
        rows = [r for r in lost if workflow in ("all", r["workflow"]) and mapping in ("all", r["mapping"])]
    total = sum(counts.values())
    amount = int(sum(balances)) if balances else (0 if match_ok and total == 0 else None)
    if amount is not None and abs(amount) > 9007199254740991:
        amount = None  # JS가 정확하게 표시하지 못할 합계는 정상 잔액으로 보내지 않는다.
    summary = {"ready": match_ok, "current_total": total,
               "lost_count": len(lost) if lost_ready else None,
               "balance": {"known_count": len(balances), "total_count": total, "known_sum": amount,
                           "complete": match_ok and len(balances) == total and (total == 0 or amount is not None)}}
    return {"rows": rows, "total": total, "filtered_total": len(rows), "view": view, "summary": summary,
            "counts": dict(counts), "workflows": dict(stages), "selection": selection,
            "catalog_status": state, "catalog_at": None if catalog is None else catalog["generated_at"],
            "accounts_at": None if at is None else at.isoformat(), "accounts_current": accounts_current,
            "matching_ready": match_ok,
            "no_erp_note": "전산 전체 목록에서 연결 가능한 업체를 찾지 못했습니다. 실제 미등록 여부는 확인이 필요합니다."}


def staff_counts(ctx, store, scope):
    """직원에게는 본인 수만. 대표는 현재 이관 계정을 각 담당별로 중복 없이 센다."""
    out = {}
    matched = [r for r in board(ctx, store, scope)["rows"] if r["mapping"] == "matched"]
    per_pid = Counter(r["possibility_id"] for r in matched)
    owns = {pid: SC.ownership_for_client(ctx.org, pid, pid, SC.MATCH_PID) for pid in per_pid}
    for idx in scope.people:
        person = ctx.org.people.get(idx)
        if person is None or not person.active or not person.is_management:
            continue
        own_scope = SC.narrowed_scope_of(ctx.org, idx)
        ids = SC.clients_in(ctx.org, own_scope, owns)
        out[idx] = sum(per_pid[pid] for pid in ids)
    return out
