"""권한으로 좁힌 저장 원천의 월간 집계. 이 경로에서 외부 수집을 시작하지 않는다."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import math

KST = timezone(timedelta(hours=9))
MAX_NUMBER = 9007199254740991


def _number(value):
    return type(value) in (int, float) and 0 <= value <= MAX_NUMBER and math.isfinite(value)


def _sum(values):
    result = sum((Decimal(str(v)) for v in values), Decimal(0))
    if result > MAX_NUMBER:
        return None
    return int(result) if result == int(result) else float(result)


def _ratio(numerator, denominator, multiplier=1):
    if numerator is None or not denominator:
        return None
    result = numerator / denominator * multiplier
    return result if _number(result) else None


def _collected(check, now, start, end):
    if not isinstance(check, dict) or str(check.get("period_start")) != start.isoformat() \
            or str(check.get("period_end")) != end.isoformat():
        return None
    try:
        at = datetime.fromisoformat(check["checked_at"])
        if at.tzinfo is None or at > now or at.astimezone(KST).date() != now.astimezone(KST).date():
            return None
        return at.astimezone(KST).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


def aggregate(rows, checks, now, *, ready):
    today = now.astimezone(KST).date()
    start, end = today.replace(day=1), today - timedelta(days=1)
    days = max(0, (end-start).days+1)
    valid, times, statuses = {}, [], Counter()
    groups, mapping = defaultdict(list), Counter()
    delivery, configuration = Counter(), Counter()
    for row in rows:
        cid = row["customer_id"]
        mapping[row["mapping"]] += 1
        if row["mapping"] == "matched" and row.get("possibility_id") is not None:
            groups[row["possibility_id"]].append(cid)
        check = checks.get(cid)
        at = _collected(check, now, start, end) if ready and days else None
        complete = at is not None and check.get("status") == "ok" \
            and all(_number(check.get(key)) for key in ("imp", "clk", "spend"))
        status = check.get("status") if at is not None else "pending"
        if complete:
            valid[cid] = check
            times.append(at)
            statuses["complete"] += 1
        elif status in ("partial", "reading"):
            statuses["partial"] += 1
        elif status in ("retry", "ok"):
            statuses["retry"] += 1
        elif status in ("limited", "reauth_required"):
            statuses["limited"] += 1
        else:
            statuses["pending"] += 1
        # 전일 비용 하나가 0인 것만으로 미집행이라고 판단하지 않는다.
        daily = row.get("collection") or {}
        values = [daily.get(k) for k in ("yday_imp", "yday_clk", "yday_spend")]
        if ready and daily.get("status") == "ok" and all(_number(v) for v in values):
            delivery["active" if any(values) else "inactive"] += 1
        else:
            delivery["unknown"] += 1
        enabled = check.get("enabled_campaigns") if at else None
        count = check.get("campaign_count") if at else None
        if type(enabled) is int and type(count) is int and 0 <= enabled <= count:
            configuration["enabled" if enabled else "disabled"] += 1
        else:
            configuration["unknown"] += 1
    known = list(valid.values())
    may_sum = ready and days and (known or not rows)
    totals = {target: _sum(r[source] for r in known) if may_sum else None
              for source, target in (("imp", "impressions"), ("clk", "clicks"), ("spend", "spend"))}
    # 0 전환매출은 추적 미설정과 구분할 근거가 없다. 해당 계정의 비용도 ROAS 분모에서 제외한다.
    conversions = [r for r in known if _number(r.get("conversion_value")) and r["conversion_value"] > 0]
    revenue = _sum(r["conversion_value"] for r in conversions) if conversions else None
    roas_spend = _sum(r["spend"] for r in conversions) if conversions else None
    totals["conversion_value"] = revenue
    complete_groups = [ids for ids in groups.values() if all(cid in valid for cid in ids)]
    group_sources = [valid[cid] for ids in complete_groups for cid in ids]
    group_n = len(complete_groups)
    averages = {"advertiser_impressions": _ratio(_sum(r["imp"] for r in group_sources), group_n),
                "advertiser_clicks": _ratio(_sum(r["clk"] for r in group_sources), group_n),
                "advertiser_daily_spend": _ratio(_sum(r["spend"] for r in group_sources), group_n * days),
                "daily_spend": _ratio(totals["spend"], days)}
    return {"ready": ready,
            "period": {"start": start.isoformat(), "end": end.isoformat(),
                       "days": days, "timezone": "Asia/Seoul"},
            "accounts": {"total": len(rows), "matched": mapping["matched"],
                         "unmatched": mapping["no_erp_record"], "unclassified": mapping["unclassified"]},
            "advertisers": {"total": len(groups), "complete": group_n, "unknown": len(groups)-group_n},
            "coverage": {**{key+"_accounts": statuses[key] for key in
                            ("complete", "pending", "partial", "retry", "limited")},
                         "oldest_collected_at": min(times) if times else None,
                         "newest_collected_at": max(times) if times else None},
            "totals": totals, "averages": averages,
            "ratios": {"ctr": _ratio(totals["clicks"], totals["impressions"], 100),
                       "cpc": _ratio(totals["spend"], totals["clicks"]),
                       "roas": _ratio(revenue, roas_spend, 100), "roas_accounts": len(conversions),
                       "roas_spend": roas_spend, "roas_conversion_value": revenue},
            "delivery": {key: delivery[key] for key in ("active", "inactive", "unknown")},
            "configuration": {key: configuration[key] for key in ("enabled", "disabled", "unknown")}}


def board(ctx, store, scope, selection="all"):
    # 기존 담당자·현재 이관 경계를 통과한 행만 집계하고 내부 고객번호는 응답에 넣지 않는다.
    from . import inventory as INV
    source = INV.board(ctx, store, scope, selection, _include_customer_ids=True)
    start, end = ctx.today.replace(day=1), ctx.today-timedelta(days=1)
    checks = store.monthly_checks_on(start, end) if start <= end else {}
    result = aggregate(source["rows"], checks, ctx.now, ready=source["matching_ready"])
    return {**result, "selection": selection, "accounts_at": source["accounts_at"],
            "catalog_at": source["catalog_at"], "catalog_status": source["catalog_status"]}
