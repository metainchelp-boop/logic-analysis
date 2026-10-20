"""불변 저장판의 공개 보조 지표. 원천 조회·저장·AI·광고 설정 변경을 하지 않는다."""
from decimal import Decimal
from datetime import date, timedelta
import math

from .reporting import MAX_NUMBER


METRICS = (
    ("spend", "광고비", "money", "basic"),
    ("conversion_value", "광고 전환가치", "money", "conversion"),
    ("conversions", "전환수", "number", "conversion"),
    ("roas", "ROAS", "percent", "paired"),
    ("cpa", "CPA", "money", "paired"),
    ("cvr", "CVR", "percent", "paired"),
    ("impressions", "노출수", "number", "basic"),
    ("clicks", "클릭수", "number", "basic"),
    ("ctr", "CTR", "percent", "basic"),
    ("cpc", "CPC", "money", "basic"),
    ("cpm", "CPM", "money", "basic"),
    ("value_per_conversion", "전환당 전환가치", "money", "paired"),
    ("spend_per_day", "일평균 광고비", "money", "basic"),
    ("clicks_per_day", "일평균 클릭수", "decimal", "basic"),
    ("impressions_per_day", "일평균 노출수", "decimal", "basic"),
    ("conversions_per_day", "일평균 전환수", "decimal", "conversion"),
    ("value_per_day", "일평균 전환가치", "money", "conversion"),
)


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= MAX_NUMBER else None


def _ratio(numerator, denominator, multiplier=1):
    if _number(numerator) is None or _number(denominator) is None or denominator == 0:
        return None
    return _number(numerator / denominator * multiplier)


def _scope(report, family):
    coverage, ratios = report.get("coverage", {}), report.get("ratios", {})
    expected = _number(coverage.get("expected_account_days"))
    count = _number(ratios.get("roas_account_days") if family == "paired" else
                    coverage.get(family+"_complete_account_days"))
    if expected is None or count is None or count > expected:
        count = None
    complete = bool(expected and count == expected)
    if family != "paired":
        complete = complete and coverage.get(family+"_complete") is True
    else:
        complete = complete and coverage.get("basic_complete") is True and coverage.get("conversion_complete") is True
    return {"family": family, "account_days": count, "expected_account_days": expected,
            "complete": complete, "description": "기본·전환 공동 계정×일" if family == "paired" else
            "기본 성과 계정×일" if family == "basic" else "전환 성과 계정×일"}


def _sum(values):
    total = sum((Decimal(str(value)) for value in values), Decimal(0))
    return _number(int(total) if total == int(total) else float(total))


def _daily_paired(report):
    """공동 완결인 날짜의 합계만 복원한다. 부분 합산 날짜의 다른 분모는 섞지 않는다."""
    try:
        saved = report["period"]
        start, end = date.fromisoformat(saved["start"]), date.fromisoformat(saved["end"])
        days = (end-start).days+1
        accounts = report["coverage"]["accounts"]
        daily = report["details"]["daily"] if "details" in report else report["daily"]
        if (type(accounts) is not int or accounts <= 0 or not 1 <= days <= 31 or saved["days"] != days
                or len(daily) != days or report["coverage"]["expected_account_days"] != accounts*days):
            return None
        by_day = {item["day"]: item for item in daily}
        if len(by_day) != days:
            return None
        paired, count = [], 0
        for offset in range(days):
            item = by_day[str(start+timedelta(days=offset))]
            scope = _scope(item, "paired")
            if item["coverage"]["accounts"] != accounts or scope["expected_account_days"] != accounts:
                return None
            if scope["account_days"] == 0:
                continue
            if not scope["complete"]:
                return None
            totals = {key: _number(item["totals"].get(key)) for key in
                      ("spend", "clicks", "conversions", "conversion_value")}
            if any(value is None for value in totals.values()):
                return None
            paired.append(totals)
            count += accounts
        if count != _scope(report, "paired")["account_days"] or not count:
            return None
        return {key: _sum(item[key] for item in paired) for key in paired[0]}
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _recovered_paired(report, account_reports=None):
    account_reports = report.get("_account_reports") if account_reports is None else account_reports
    if not account_reports:
        return _daily_paired(report)
    expected = report.get("_expected_customers", [])
    if (not expected or any(type(cid) is not int or cid <= 0 for cid in expected)
            or len(set(expected)) != len(expected) or len(expected) != report.get("coverage", {}).get("accounts")
            or set(account_reports) != {str(cid) for cid in expected}):
        return None
    restored, count = [], 0
    for cid in expected:
        account = account_reports[str(cid)]
        if (account.get("period") != report.get("period") or account.get("period_key") != report.get("period_key")
                or account.get("_expected_customers") != [cid] or account.get("coverage", {}).get("accounts") != 1):
            return None
        days = _scope(account, "paired")["account_days"]
        if days == 0:
            continue
        values = _daily_paired(account)
        if values is None or days is None:
            return None
        restored.append(values)
        count += days
    if not restored or count != _scope(report, "paired")["account_days"]:
        return None
    return {key: _sum(item[key] for item in restored) for key in restored[0]}


def _paired(report, account_reports=None):
    # 완결 분모가 같은 경우에만 전체 합계를 공동 합계로 사용할 수 있다.
    if _scope(report, "paired")["complete"]:
        return {key: _number(report.get("totals", {}).get(key)) for key in
                ("spend", "clicks", "conversions", "conversion_value")}
    ratios = report.get("ratios", {})
    values = {"spend": _number(ratios.get("roas_spend")), "clicks": _number(ratios.get("roas_clicks")),
              "conversions": _number(ratios.get("roas_conversions")),
              "conversion_value": _number(ratios.get("roas_conversion_value"))}
    if values["clicks"] is None or values["conversions"] is None:
        restored = _recovered_paired(report, account_reports)
        if restored and all(restored[key] == values[key] for key in ("spend", "conversion_value")):
            return restored
    return values


def _values(report, account_reports=None):
    totals = report.get("totals", {})
    values = {key: _number(totals.get(key)) for key in
              ("spend", "impressions", "clicks", "conversions", "conversion_value")}
    paired = _paired(report, account_reports)
    values.update(ctr=_ratio(values["clicks"], values["impressions"], 100),
                  cpc=_ratio(values["spend"], values["clicks"]),
                  cpm=_ratio(values["spend"], values["impressions"], 1000),
                  roas=_ratio(paired["conversion_value"], paired["spend"], 100),
                  cpa=_ratio(paired["spend"], paired["conversions"]),
                  cvr=_ratio(paired["conversions"], paired["clicks"], 100),
                  value_per_conversion=_ratio(paired["conversion_value"], paired["conversions"]))
    # 저장된 공동 비율은 이용하지만 비율로 공동 클릭·전환수를 역산하지 않는다.
    for key in ("cpa", "cvr"):
        if values[key] is None and _scope(report, "paired")["account_days"]:
            values[key] = _number(report.get("ratios", {}).get(key))
    days = _number(report.get("period", {}).get("days"))
    for key, total, family in (("spend_per_day", "spend", "basic"), ("clicks_per_day", "clicks", "basic"),
                               ("impressions_per_day", "impressions", "basic"),
                               ("conversions_per_day", "conversions", "conversion"),
                               ("value_per_day", "conversion_value", "conversion")):
        values[key] = _ratio(values[total], days) if _scope(report, family)["complete"] else None
    return values


def _value_status(report, key, value, family):
    scope = _scope(report, family)
    if value is not None:
        return "ready" if scope["complete"] else "partial"
    denominator = {"ctr": "impressions", "cpc": "clicks", "cpm": "impressions", "roas": "spend",
                   "cpa": "conversions", "cvr": "clicks", "value_per_conversion": "conversions"}.get(key)
    source = _paired(report) if family == "paired" else report.get("totals", {})
    if denominator and _number(source.get(denominator)) == 0:
        return "zero_denominator"
    if family == "paired" and scope["account_days"] and key == "value_per_conversion" and source.get("conversions") is None:
        return "legacy_unavailable"
    return "unavailable"


def _comparison(current, comparison, before, after, family, unit):
    status = "no_previous" if not comparison or not comparison.get("coverage", {}).get("accounts") else (
        "scope_changed" if comparison.get("status") == "scope_changed" or
        comparison.get("basic_status") == "scope_changed" or comparison.get("conversion_status") == "scope_changed" else
        "insufficient_data" if "not_due" in current.get("blocked_reasons", []) or not _scope(current, family)["complete"] or
        not _scope(comparison, family)["complete"] else "ready")
    absolute = percent = None
    if status == "ready":
        if before is None or after is None:
            status = "zero_denominator"
        else:
            absolute = float(Decimal(str(after))-Decimal(str(before)))
            percent = (absolute / before * 100) if before else None
            if percent is not None and not math.isfinite(percent):
                percent = None
            if before == 0 or percent is None:
                status = "zero_denominator"
    return {"absolute": absolute, "percent": percent, "percentage_points": unit == "percent", "status": status,
            "comparison_reason": {"no_previous": "직전 기간 자료 없음", "scope_changed": "계정 범위 변경 · 비교 보류",
                                  "insufficient_data": "필요 계정×일 자료 미완결 · 비교 보류",
                                  "zero_denominator": "분모 0 또는 계산 자료 없음"}.get(status)}


def _quality(report):
    result = {"expected_account_days": _scope(report, "basic")["expected_account_days"]}
    for family in ("basic", "conversion", "paired"):
        scope = _scope(report, family)
        result[family] = {"complete": scope["complete"], "count": scope["account_days"],
                          "percent": _ratio(scope["account_days"], scope["expected_account_days"], 100)}
    missing = report.get("missing", [])
    reasons = {}
    for item in missing:
        reason = item.get("reason", "unknown")
        reasons[reason] = reasons.get(reason, 0)+1
    expected, paired = result["expected_account_days"], result["paired"]["count"]
    result.update(missing_account_days=expected-paired if expected is not None and paired is not None else None,
                  missing_count=report.get("missing_count", len(missing)), missing_reasons=reasons,
                  missing_truncated=report.get("missing_truncated") is True,
                  missing_reasons_complete=report.get("missing_truncated") is not True and
                  report.get("missing_count", len(missing)) == len(missing),
                  missing_reasons_observed_count=len(missing),
                  validation_status=report.get("validation", {}).get("status", "unknown"))
    return result


def _display(value, unit="number", signed=False):
    if value is None:
        return "미확인"
    number = format(value, "+,.2f" if signed else ",.2f").rstrip("0").rstrip(".")
    return number+("원" if unit == "money" else "%" if unit == "percent" else "")


def _feedback(report, metrics, quality):
    by_key = {item["key"]: item for item in metrics}
    facts, hypotheses, actions = [], [], []

    def fact(text, keys):
        scope = by_key[keys[0]]["scope"]
        facts.append({"text": text, "metric_keys": keys,
                      "evidence": {"period_key": report.get("period_key"),
                                   "revision_fingerprint": report.get("revision_fingerprint"),
                                   "scope": scope["description"], "account_days": scope["account_days"],
                                   "expected_account_days": scope["expected_account_days"]}})

    def action(text, reason, keys, priority="medium"):
        actions.append({"text": text, "reason": reason, "metric_keys": keys, "priority": priority,
                        "owner": "담당자 확인 필요", "due_date": None, "approval_status": "proposed", "status": "proposed"})

    for family, keys in (("basic", ["spend", "impressions", "clicks"]),
                         ("conversion", ["conversions", "conversion_value"]),
                         ("paired", ["roas", "cpa", "cvr", "value_per_conversion"])):
        count = quality[family]["count"]
        expected = quality["expected_account_days"]
        data = " · ".join(by_key[key]["label"]+" "+_display(by_key[key]["current"], by_key[key]["unit"])
                          for key in keys)
        fact(f"{by_key[keys[0]]['scope']['description']} {_display(count)}/{_display(expected)} 기준: {data}.", keys)
    changed = [item for item in metrics if item["status"] == "ready" and item["absolute"] != 0]
    for key in ("spend", "clicks", "conversions", "roas", "cpa"):
        item = by_key[key]
        if item["status"] == "ready":
            suffix = "%p" if item["percentage_points"] else "원" if item["unit"] == "money" else ""
            fact(f"같은 계정의 직전 기간 대비 {item['label']} 차이는 "
                 f"{_display(item['absolute'], signed=True)}{suffix}, 상대 증감률은 "
                 f"{_display(item['percent'], 'percent', signed=True)}입니다.", [key])
    if quality["missing_account_days"]:
        action("빠진 계정×일과 지표군의 원천 완결 증거를 확인하세요.",
               f"공동 완결되지 않은 계정×일 {quality['missing_account_days']}개 · 비교와 일평균 산출 조건 확인",
               ["spend", "conversions", "roas"], "high")
    if any(item["status"] == "scope_changed" for item in metrics):
        action("양쪽 보고기간의 포함 계정 범위를 확인하세요.", "계정 범위가 바뀌어 합산 증감을 보류했습니다.",
               ["spend", "conversions"], "high")
    elif all(item["status"] == "no_previous" for item in metrics):
        action("같은 계정의 직전 기간 저장판과 완결 상태를 확인하세요.", "직전 기간 자료가 없어 증감을 산출하지 않았습니다.",
               ["spend", "conversions"])
    if any(item["value_status"] == "zero_denominator" or item["status"] == "zero_denominator" for item in metrics):
        action("0인 분모와 해당 지표의 전환·클릭·광고비 정의를 확인하세요.",
               "실제 0과 미확인을 구분하며, 분모 0인 비율·상대 증감률은 미산출합니다.", ["cpa", "cvr", "roas"])
    if changed:
        keys = [item["key"] for item in changed if item["key"] in ("clicks", "ctr", "conversions", "cvr")]
        if keys:
            hypotheses.append({"text": "유입 구성이나 전환 과정·추적 상태의 변화가 관측된 수치 변화와 관련됐을 가능성이 있습니다.",
                               "alternative": "일별 관측 차이, 상품·기간 구성, 전환 정의 차이도 설명 후보입니다. 현재 자료로 원인을 확정하지 않습니다.",
                               "required_evidence": ["같은 기간·계정의 캠페인 또는 유입 구성", "전환 정의·추적 정상 여부", "실제 변경 이력"],
                               "verification": "담당자가 전환 정의와 추적 상태를 먼저 대조한 뒤 추가 근거를 같은 기간으로 비교합니다.",
                               "metric_keys": keys})
            action("수치가 바뀐 지표의 전환 정의·추적 상태와 실제 변경 이력을 대조하세요.",
                   "관측된 증감은 원인이나 개선 효과의 증거와 별도입니다.", keys)
    action("확정 목표와 전환 정의를 확인한 뒤 판단 기준을 기록하세요.",
           "목표·벤치마크가 보관되지 않아 좋음·나쁨이나 매출 효과를 평가하지 않았습니다.", ["roas", "cpa", "conversions"])
    return {"facts": facts, "hypotheses": hypotheses, "actions": actions}


def enrich(payload):
    """공개 보조 결과만 새로 반환한다. 원본 totals/ratios·판 지문은 변경하지 않는다."""
    current = _values(payload)
    comparison = payload.get("details", {}).get("comparison")
    prior_accounts = {cid: account.get("details", {}).get("comparison", {}) for cid, account in
                      payload.get("_account_reports", {}).items()} if payload.get("_account_reports") else None
    prior_values = _values(comparison, prior_accounts) if comparison else {}
    metrics = []
    for key, label, unit, family in METRICS:
        value, before = current[key], prior_values.get(key)
        scope = _scope(payload, family)
        metrics.append({"key": key, "label": label, "unit": unit, "current": value, "previous": before,
                        **_comparison(payload, comparison, before, value, family, unit), "scope": scope,
                        "value_status": _value_status(payload, key, value, family)})
    caveats = ["광고 전환가치는 플랫폼 전환금액이며 실제 주문·결제 매출과 별도입니다.",
               "전환당 전환가치는 평균 주문금액이 아닙니다. 목표 확인 전 좋음·나쁨을 평가하지 않습니다."]
    days = _number(payload.get("period", {}).get("days"))
    prior_days = _number((comparison or {}).get("period", {}).get("days"))
    if days and prior_days and days != prior_days:
        caveats.append(f"현재 기간 {days}일과 직전 기간 {prior_days}일은 달력일 수가 다릅니다. 합계 증감과 완결 자료의 일평균 증감을 함께 확인하세요.")
    if "not_due" in payload.get("blocked_reasons", []):
        caveats.append("보고서 마감시각 전입니다. 현재 확인 수치와 완결률을 표시하되 직전 기간 비교는 보류합니다.")
    quality = _quality(payload)
    return {"version": 1, "metrics": metrics, "quality": quality,
            "feedback": _feedback(payload, metrics, quality), "period_caveats": caveats}


def contribution(company, account):
    """호출자가 같은 판의 권한을 검증한 계정에 대해 완결 지표군의 비중을 반환한다.

    현재 이름·식별자·권한 판단은 조회 계층이 맡는다. 계정 번호는 결과에 포함하지 않는다.
    """
    result = enrich(account)
    members, selected = company.get("_expected_customers", []), account.get("_expected_customers", [])
    same_period = (account.get("period") == company.get("period") and
                   account.get("period_key") == company.get("period_key") and
                   len(selected) == 1 and selected[0] in members)
    shares = {}
    for key in ("spend", "clicks", "impressions", "conversions", "conversion_value"):
        family = "conversion" if key in ("conversions", "conversion_value") else "basic"
        numerator, denominator = account.get("totals", {}).get(key), company.get("totals", {}).get(key)
        shares[key] = _ratio(numerator, denominator, 100) if same_period and (
            _scope(company, family)["complete"] and _scope(account, family)["complete"]
            and _number(numerator) is not None and _number(denominator) is not None and numerator <= denominator) else None
    result["shares"] = shares
    return result
