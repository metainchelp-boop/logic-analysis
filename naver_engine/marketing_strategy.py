"""저장판 근거의 전략 초안. 저장·승인·광고 실행은 호출자의 별도 책임이다.

규칙 초안은 네트워크를 쓰지 않는다. 제공자 호출은 명시적으로 전달된 경우에만
수행하며, 모델의 숫자는 알려진 지표 참조로만 받아 서버에서 표시한다.
"""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
import math
import re

from . import report_enrichment as E, reporting as R


DOCUMENT_FIELDS = frozenset({"diagnosis", "direction", "appeal_points", "competitive_response",
    "weekly_plan", "monthly_plan", "funnel_comment", "ab_comment", "shared_comment"})
METRIC_FIELDS = ("current", "previous", "absolute", "percent")
COMPETITIVE_COMMENT = "상품·시장·경쟁 자료가 미연결 상태입니다. 경쟁 우위나 고객 특성을 확정하지 않고 출처가 있는 자료 연결 후 소구를 제안합니다."
FUNNEL_COMMENT = "현재 근거는 노출·클릭·일반 광고 전환입니다. 장바구니·구매·재구매와 고객 전체 여정은 미연결이며, 합산 수치로 특정 소재나 랜딩을 원인으로 확정하지 않습니다."
AB_COMMENT = "현재 자료는 계정×일 관찰 비교입니다. 실험군·배분·표본·전환 지연·외부 변경이 검증되지 않아 통제된 A/B 결과나 승자로 판정하지 않습니다."
_STATUS = frozenset({"ready", "no_previous", "scope_changed", "insufficient_data", "zero_denominator"})
_VALUE_STATUS = frozenset({"ready", "partial", "zero_denominator", "unavailable", "legacy_unavailable"})
_REF = re.compile(r"\{\{metric:([a-z_]+)\.(current|previous|absolute|percent)\}\}")
_CASE_REF = re.compile(r"\{\{case:([1-5])\.([a-z_]+(?:\.[a-z_]+)?)\}\}")
_PLAN_REF = re.compile(r"\{\{plan:(target_value|daily_spend_cap|absolute_bid_cap|experiment_days|loss_cap)\}\}")
_LABELS = {key: (label, unit) for key, label, unit, _ in E.METRICS}
TEXT_LIMITS = {"diagnosis": 1800, "direction": 1400, "competitive_response": 500,
               "funnel_comment": 600, "ab_comment": 600, "shared_comment": 3000}
PLAN_LIMITS = {"action": 300, "reason": 500, "criterion": 500}
PROMPT_VERSION = "marketing-strategy-v1"
LEARNING_PROMPT_VERSION = "marketing-strategy-learning-v2"
LEARNING_METADATA = {
    "industry": frozenset({"food", "pet", "home", "beauty", "fashion", "local_service", "b2b", "other"}),
    "goal": frozenset({"impressions", "clicks", "cpa", "roas", "ctr", "cvr"}),
    "ad_type": frozenset({"powerlink", "shopping", "brand", "place", "display", "other"}),
    "budget_band": frozenset({"under_300k", "300k_1m", "1m_3m", "over_3m"}),
}
_LEARNING_METRICS = frozenset({"impressions", "clicks", "spend", "conversions", "conversion_value"})
_OUTCOME_LABELS = {"observation": "관찰 자료", "unknown": "측정 근거 미확인", "winner": "검수된 실험 우세",
    "inconclusive": "판정 유보", "invalid": "실험 조건 부적합"}


def _learning_error():
    raise StrategyRefused("LEARNING_CONTEXT_INVALID")


def _learning_number(value, *, signed=False):
    try:
        return _number(value, signed=signed)
    except StrategyRefused:
        _learning_error()


def _learning_bool(value):
    if type(value) is not bool:
        _learning_error()
    return value


def _learning_period(evidence):
    try:
        start, end = (date.fromisoformat(evidence[key]) for key in ("period_start", "period_end"))
        days = (end-start).days+1
        if not 1 <= days <= 367:
            _learning_error()
        return days
    except (KeyError, TypeError, ValueError):
        _learning_error()


def _learning_metrics(evidence, *, conversions_usable):
    if not isinstance(evidence, dict) or not _LEARNING_METRICS <= set(evidence):
        _learning_error()
    values = {key: _learning_number(evidence[key]) for key in sorted(_LEARNING_METRICS)}
    if values["clicks"] is not None and values["impressions"] is not None and values["clicks"] > values["impressions"]:
        _learning_error()
    if not conversions_usable:
        values.update(conversions=None, conversion_value=None)
    return values


def _learning_context(value):
    """서버가 권한 확인 후 검색한 검수 사례만 받는다. ID·자유 문안은 모델에 보내지 않는다."""
    from . import learning_assets as LA
    if (not isinstance(value, dict) or set(value) != {"version", "cases"} or type(value["version"]) is not int
            or value["version"] != 1 or not isinstance(value["cases"], list) or len(value["cases"]) > 5):
        _learning_error()
    cases, references, identities = [], [], set()
    for index, item in enumerate(value["cases"], 1):
        if (not isinstance(item, dict) or set(item) != {"asset_id", "version", "kind", "metadata", "evidence", "assessment"}
                or not isinstance(item["asset_id"], str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", item["asset_id"])
                or type(item["version"]) is not int or not 1 <= item["version"] <= 2**53-1
                or item["asset_id"] in identities or item["kind"] not in {"performance", "setting_change", "experiment"}):
            _learning_error()
        identities.add(item["asset_id"])
        metadata = item["metadata"]
        if not isinstance(metadata, dict) or set(metadata) != set(LEARNING_METADATA):
            _learning_error()
        for key, allowed in LEARNING_METADATA.items():
            if metadata[key] is not None and (not isinstance(metadata[key], str) or metadata[key] not in allowed):
                _learning_error()
        evidence, assessment = item["evidence"], item["assessment"]
        if not isinstance(evidence, dict) or not isinstance(assessment, dict):
            _learning_error()
        outcome = assessment.get("outcome")
        if outcome not in _OUTCOME_LABELS:
            _learning_error()
        reasons = assessment.get("reason_codes")
        if (not isinstance(reasons, list) or len(reasons) > 16 or any(not isinstance(code, str)
                or code not in LA.REASON_CODES for code in reasons)):
            _learning_error()
        case = {"index": index, "kind": item["kind"], "metadata": deepcopy(metadata),
            "assessment": {"outcome": outcome, "reason_codes": list(reasons), "causal_claim": False}}
        if item["kind"] in {"performance", "experiment"}:
            complete = _learning_bool(evidence.get("measurement_complete"))
            mature = _learning_bool(evidence.get("lag_mature"))
            definition = evidence.get("conversion_definition")
            if definition not in LA.CONVERSION_DEFINITIONS:
                _learning_error()
            clean = {"days": _learning_period(evidence), "measurement_complete": complete, "lag_mature": mature,
                "conversion_definition": definition}
            usable = complete and mature and definition != "unknown"
            if item["kind"] == "performance":
                if outcome != "observation" or assessment.get("causal_claim") is not False:
                    _learning_error()
                clean.update(_learning_metrics(evidence, conversions_usable=usable))
            else:
                for key in ("randomized", "one_variable", "allocation_valid", "independent_units"):
                    clean[key] = _learning_bool(evidence.get(key))
                if evidence.get("goal") not in LEARNING_METADATA["goal"] or evidence.get("status") not in {"planned", "running", "completed", "stopped"}:
                    _learning_error()
                clean.update(goal=evidence["goal"], status=evidence["status"],
                    min_sample_per_arm=_learning_number(evidence.get("min_sample_per_arm")),
                    mde_percent=_learning_number(evidence.get("mde_percent")))
                if (type(clean["min_sample_per_arm"]) is not int or clean["min_sample_per_arm"] < 1
                        or clean["mde_percent"] is None or not 0 < clean["mde_percent"] <= 100):
                    _learning_error()
                clean.update(baseline_rate=_learning_number(evidence.get("baseline_rate")),
                    control_share=_learning_number(evidence.get("control_share")))
                if clean["control_share"] is None or not 0.1 <= clean["control_share"] <= 0.9:
                    _learning_error()
                if clean["baseline_rate"] is not None and not 0 < clean["baseline_rate"] < 1:
                    _learning_error()
                registered = evidence.get("preregistered_at")
                clean["preregistered"] = False
                if registered is not None:
                    try:
                        registered_at = datetime.fromisoformat(registered)
                        clean["preregistered"] = (registered_at.utcoffset() is not None and
                            registered_at.astimezone(R.KST).date() < date.fromisoformat(evidence["period_start"]))
                    except (TypeError, ValueError):
                        _learning_error()
                for arm in ("control", "treatment"):
                    clean[arm] = _learning_metrics(evidence.get(arm), conversions_usable=usable)
                winner = assessment.get("winner")
                if winner not in (None, "control", "treatment"):
                    _learning_error()
                qualified = (complete and mature and clean["randomized"] and clean["one_variable"]
                    and clean["allocation_valid"] and clean["independent_units"] and clean["status"] == "completed" and clean["preregistered"])
                if winner is not None and (outcome != "winner" or not qualified):
                    _learning_error()
                if assessment.get("causal_claim") is True and (winner is None or not qualified):
                    _learning_error()
                if type(assessment.get("causal_claim")) is not bool:
                    _learning_error()
                case["assessment"].update(winner=winner, causal_claim=assessment["causal_claim"])
                interval = assessment.get("confidence_interval")
                if interval is not None:
                    if not isinstance(interval, dict) or set(interval) != {"low", "high", "confidence"} or interval["confidence"] != 0.95:
                        _learning_error()
                    low, high = (_learning_number(interval[key], signed=True) for key in ("low", "high"))
                    if low is None or high is None or not -1 <= low <= high <= 1:
                        _learning_error()
                    case["assessment"]["confidence_interval"] = {"low": low, "high": high, "confidence": 0.95}
                if winner is not None:
                    denominator = "impressions" if clean["goal"] == "ctr" else "clicks" if clean["goal"] == "cvr" else None
                    required = assessment.get("required_sample_per_arm")
                    if (denominator is None or type(required) is not int or required > clean["min_sample_per_arm"]
                            or any(clean[arm][denominator] is None or clean[arm][denominator] < clean["min_sample_per_arm"] for arm in ("control", "treatment"))
                            or interval is None or (winner == "treatment" and interval["low"] <= 0)
                            or (winner == "control" and interval["high"] >= 0)):
                        _learning_error()
        else:
            if assessment.get("causal_claim") is not False or outcome != "observation":
                _learning_error()
            changed = evidence.get("changed_variable")
            if not isinstance(changed, str) or not re.fullmatch(r"[a-z_]{1,64}", changed):
                _learning_error()
            allowed_settings = {"goal", "target_value", "daily_spend_cap", "absolute_bid_cap", "experiment_days", "loss_cap", "bid", "daily_budget", "enabled"}
            if changed not in allowed_settings | {"multiple"} or evidence.get("execution") not in {"planned", "observed", "applied"}:
                _learning_error()
            clean = {"changed_variable": changed, "execution": evidence["execution"]}
            for side in ("before", "after"):
                settings = evidence.get(side)
                if not isinstance(settings, dict) or not set(settings) <= allowed_settings:
                    _learning_error()
                clean[side] = {}
                for key, setting in settings.items():
                    if key == "goal":
                        if setting is not None and setting not in LEARNING_METADATA["goal"]:
                            _learning_error()
                        clean[side][key] = setting
                    else:
                        clean[side][key] = _learning_bool(setting) if key == "enabled" and setting is not None else _learning_number(setting)
        case["evidence"] = clean
        cases.append(case)
        references.append({"asset_id": item["asset_id"], "version": item["version"]})
    return {"version": 1, "cases": cases}, references


def _plan_context(value):
    fields = {"goal", "target_value", "daily_spend_cap", "absolute_bid_cap", "experiment_days", "loss_cap"}
    if (not isinstance(value, dict) or set(value) != {"version", "state", "document"}
            or type(value["version"]) is not int or not 0 <= value["version"] <= 2**53-1
            or value["state"] not in {"empty", "draft", "approved"}
            or not isinstance(value["document"], dict) or set(value["document"]) != fields):
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    plan = value["document"]
    if plan["goal"] is not None and plan["goal"] not in {"impressions", "clicks", "cpa", "roas"}:
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    clean = {"state": value["state"], "goal": plan["goal"]}
    for key in fields - {"goal"}:
        try:
            clean[key] = _number(plan[key])
        except StrategyRefused:
            raise StrategyRefused("PLAN_CONTEXT_INVALID") from None
        if clean[key] is not None and not 0 < clean[key] <= 10**12:
            raise StrategyRefused("PLAN_CONTEXT_INVALID")
    days = clean["experiment_days"]
    if days is not None and (type(days) is not int or not 2 <= days <= 30):
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    if value["state"] == "approved" and (value["version"] < 1 or any(clean[key] is None for key in fields)
            or clean["loss_cap"] > clean["daily_spend_cap"] * days):
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    if (value["state"] == "empty" and (value["version"] != 0 or any(clean[key] is not None for key in fields))
            or value["state"] != "empty" and value["version"] < 1):
        raise StrategyRefused("PLAN_CONTEXT_INVALID")
    return clean, {"version": value["version"], "state": value["state"]}


class StrategyRefused(ValueError):
    """외부 응답·키·계정 정보 대신 고정 분류만 반환한다."""
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _number(value, *, signed=False):
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not (-E.MAX_NUMBER if signed else 0) <= value <= E.MAX_NUMBER:
        raise StrategyRefused("CONTEXT_INVALID")
    return value


def build_context(payload, *, learning_context=None, plan_context=None):
    """수치판을 순수 재계산한 뒤 allowlist만 복사한다. 권한·판 확인은 호출자가 한다."""
    try:
        saved = payload["period"]
        if saved["kind"] not in ("weekly", "monthly") or type(saved["days"]) is not int or not 1 <= saved["days"] <= 31:
            raise StrategyRefused("CONTEXT_INVALID")
        enriched = E.enrich(payload)
        metrics = []
        for item in enriched["metrics"]:
            if item["key"] not in _LABELS or item["status"] not in _STATUS or item["value_status"] not in _VALUE_STATUS:
                raise StrategyRefused("CONTEXT_INVALID")
            scope = item["scope"]
            metrics.append({"key": item["key"], "label": _LABELS[item["key"]][0], "unit": _LABELS[item["key"]][1],
                **{field: _number(item[field], signed=field in ("absolute", "percent")) for field in METRIC_FIELDS},
                "status": item["status"], "value_status": item["value_status"],
                "percentage_points": item["percentage_points"] is True,
                "scope": {"account_days": _number(scope["account_days"]),
                          "expected_account_days": _number(scope["expected_account_days"]),
                          "complete": scope["complete"] is True}})
        quality = enriched["quality"]
        public_quality = {key: _number(quality[key]) for key in ("expected_account_days", "missing_account_days", "missing_count")}
        for family in ("basic", "conversion", "paired"):
            public_quality[family] = {"complete": quality[family]["complete"] is True,
                "count": _number(quality[family]["count"]), "percent": _number(quality[family]["percent"])}
        comparison = payload.get("details", {}).get("comparison") or {}
        prior_days = comparison.get("period", {}).get("days")
        if prior_days is not None and (type(prior_days) is not int or not 1 <= prior_days <= 31):
            raise StrategyRefused("CONTEXT_INVALID")
        feedback = enriched["feedback"]
        result = {"version": 1, "period": {"kind": saved["kind"], "days": saved["days"], "previous_days": prior_days},
            "metrics": metrics, "quality": public_quality,
            "feedback": {kind: [{"metric_keys": [key for key in row["metric_keys"] if key in _LABELS]}
                                    for row in feedback[kind]] for kind in ("facts", "hypotheses", "actions")},
            "connected": {"product": False, "market": False, "purchase_definition": False, "experiment": False}}
        if learning_context is not None:
            result["learning"], _ = _learning_context(learning_context)
        if plan_context is not None:
            result["operating_plan"], _ = _plan_context(plan_context)
        return result
    except StrategyRefused:
        raise
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise StrategyRefused("CONTEXT_INVALID") from None


def _display(context, key, field):
    item = next((row for row in context["metrics"] if row["key"] == key), None)
    if (item is None or field not in METRIC_FIELDS or item[field] is None or
            (field != "current" and item["status"] != "ready")):
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    value = item[field]
    text = format(value, ",.2f").rstrip("0").rstrip(".") if type(value) is float else format(value, ",")
    unit = "%" if field == "percent" else "%p" if field == "absolute" and item["percentage_points"] else (
        "%" if item["unit"] == "percent" else "원" if item["unit"] == "money" else "")
    label = {"current": "현재", "previous": "직전", "absolute": "차이", "percent": "상대 증감률"}[field]
    partial = " · 일부 완결 자료 기준" if field == "current" and item["value_status"] == "partial" else ""
    return f"{item['label']} {label} {text}{unit}{partial}"


def _display_case(context, index, field):
    cases = context.get("learning", {}).get("cases", [])
    if not 1 <= index <= len(cases):
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    case = cases[index-1]
    if field == "outcome":
        return f"검수된 과거 사례 {index}: " + _OUTCOME_LABELS[case["assessment"]["outcome"]]
    if field == "reason":
        return "과거 사례의 측정·표본·실험 조건을 현재 계정에 적용하기 전에 다시 확인합니다"
    path = field.split(".")
    evidence = case["evidence"]
    if len(path) == 1 and path[0] in _LEARNING_METRICS | {"days", "min_sample_per_arm", "mde_percent"}:
        value = evidence.get(path[0])
    elif len(path) == 2 and path[0] in {"control", "treatment"} and path[1] in _LEARNING_METRICS:
        value = evidence.get(path[0], {}).get(path[1])
    elif len(path) == 2 and path[0] in {"before", "after"} and path[1] in {
            "target_value", "daily_spend_cap", "absolute_bid_cap", "experiment_days", "loss_cap", "bid", "daily_budget"}:
        value = evidence.get(path[0], {}).get(path[1])
    else:
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    if type(value) not in (int, float):
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    number = format(value, ",.2f").rstrip("0").rstrip(".") if type(value) is float else format(value, ",")
    unit = "원" if path[-1] in {"spend", "conversion_value", "daily_spend_cap", "absolute_bid_cap", "loss_cap", "bid", "daily_budget"} else "%" if path[-1] == "mde_percent" else "일" if path[-1] in {"days", "experiment_days"} else ""
    label = {"impressions": "노출", "clicks": "클릭", "spend": "광고비", "conversions": "광고 전환",
        "conversion_value": "플랫폼 전환금액", "days": "관측 기간", "min_sample_per_arm": "군별 계획 표본",
        "mde_percent": "계획 최소 차이", "target_value": "목표값", "daily_spend_cap": "일 예산 한도",
        "absolute_bid_cap": "절대 입찰 한도", "experiment_days": "계획 기간", "loss_cap": "손실 한도",
        "bid": "입찰값", "daily_budget": "일 예산"}[path[-1]]
    scope = {"control": "대조군 ", "treatment": "실험군 ", "before": "변경 전 ", "after": "변경 후 "}.get(path[0], "")
    return f"검수된 과거 사례 {index}의 {scope}{label} {number}{unit}"


def _display_plan(context, field):
    plan = context.get("operating_plan", {})
    value = plan.get(field)
    if type(value) not in (int, float):
        raise StrategyRefused("REFERENCE_UNAVAILABLE")
    label = {"target_value": "목표값", "daily_spend_cap": "일 예산 한도", "absolute_bid_cap": "절대 입찰 한도",
        "experiment_days": "계획 기간", "loss_cap": "손실 한도"}[field]
    number = format(value, ",.2f").rstrip("0").rstrip(".") if type(value) is float else format(value, ",")
    unit = "일" if field == "experiment_days" else "%" if field == "target_value" and plan.get("goal") == "roas" else "원" if field != "target_value" or plan.get("goal") == "cpa" else ""
    return ("승인 계획의 " if plan.get("state") == "approved" else "미승인 초안의 ") + label + " " + number + unit


def _with_learning_provenance(result, context, learning_context, plan_context):
    if learning_context is None and plan_context is None:
        return result
    references = _learning_context(learning_context)[1] if learning_context is not None else []
    plan_ref = _plan_context(plan_context)[1] if plan_context is not None else None
    canonical = json.dumps({"context": context, "learning_refs": references, "plan_ref": plan_ref},
        sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    result.update(prompt_version=LEARNING_PROMPT_VERSION, learning_refs=references,
        context_fingerprint=hashlib.sha256(canonical).hexdigest())
    if plan_ref is not None:
        result["plan_ref"] = plan_ref
    result["caveats"].append("학습 사례는 검수한 과거 기록입니다. 유사 조건의 재검증 없이 현재 성과·매출·인과 효과를 보장하지 않습니다.")
    return result


def _baseline(context):
    usable = [row["key"] for row in context["metrics"] if row["key"] in ("spend", "clicks", "conversions") and row["current"] is not None]
    observation = " · ".join("{{metric:"+key+".current}}" for key in usable) or "확인 가능한 성과 수치가 없습니다"
    incomplete = not all(context["quality"][family]["complete"] for family in ("basic", "conversion", "paired"))
    diagnosis = observation+". "+("자료가 미완결이므로 전체 성과 평가와 기간 비교를 보류합니다." if incomplete else
        "확인한 계정×일 범위의 관측값이며 원인이나 구매 효율 개선의 증거와는 구분합니다.")
    statuses = {row["status"] for row in context["metrics"]}
    if "scope_changed" in statuses:
        diagnosis += " 포함 계정 범위가 바뀌어 직전 기간 증감을 보류합니다."
    elif statuses == {"no_previous"}:
        diagnosis += " 직전 기간 저장판이 없어 증감을 판정하지 않습니다."
    else:
        changes = [row["key"] for row in context["metrics"] if row["key"] in ("clicks", "conversions", "cvr", "cpa")
                   and row["status"] == "ready" and row["absolute"] != 0]
        if changes:
            diagnosis += " 직전 기간 차이: "+" · ".join("{{metric:"+key+".absolute}}" for key in changes)+"."
    if context["period"]["previous_days"] not in (None, context["period"]["days"]):
        diagnosis += " 기간 길이가 달라 합계와 완결 자료의 일평균을 함께 확인합니다."
    direction = "전환 정의와 합의한 목표를 먼저 확인하고 유입·소재·랜딩 근거를 연결합니다. 상품 사실이 연결되기 전에는 구체 소구나 예산 확대를 확정하지 않습니다."
    if context.get("learning", {}).get("cases"):
        direction += " 검수된 과거 사례는 적용 조건을 재확인할 계획 근거로 사용하며, 과거 실험 결과를 현재 계정의 성과로 확정하지 않습니다."
    if context.get("operating_plan", {}).get("daily_spend_cap") is not None:
        direction += " {{plan:daily_spend_cap}}를 확인하고 적용 조건과 검수할 목표를 구체화합니다."
    weekly = [
        {"action": "전환 정의와 자료 완결 상태 확인", "reason": "일반 광고 전환과 구매 완료를 구분하고 미확인 자료를 점검합니다.", "criterion": "같은 계정·기간의 기본·전환 공동 완결과 목표 근거 확인"},
        {"action": "상품·검색 의도·소재·랜딩 자료 연결", "reason": "계정 합산 성과만으로 소구 효과나 특정 소재의 원인을 판단할 수 없습니다.", "criterion": "상품 사실·출처·조회 시각과 동일 기간의 세부 성과 확인"},
        {"action": "비교할 가설과 실험 계획 검토", "reason": "관찰 비교와 통제된 실험을 분리합니다.", "criterion": "주지표·실험 단위·배분·표본·전환 지연·최대 기간·중단 조건을 계획에 기록"}]
    monthly = [
        {"action": "기간별 성과와 운영 이력 대조", "reason": "기간 길이·계정 범위·외부 변경의 영향을 확인합니다.", "criterion": "동일 범위의 완결 자료와 합계·일평균을 함께 비교"},
        {"action": "소구·경쟁 대응 계획 검토", "reason": "상품과 공개 경쟁 자료가 연결된 뒤 선택 이유를 검증합니다.", "criterion": "비교 가능한 상품 조건·출처와 승인할 구체안 확보"},
        {"action": "결과에 따라 유지·보완·다음 실험 구분", "reason": "표본이 부족하거나 비교 조건이 다르면 승자를 선정하지 않습니다.", "criterion": "성숙한 전환·주지표·악화 방지 기준 충족 여부를 검수하고 별도 운영 승인"}]
    return {"diagnosis": diagnosis, "direction": direction, "appeal_points": [],
        "competitive_response": COMPETITIVE_COMMENT, "weekly_plan": weekly, "monthly_plan": monthly,
        "funnel_comment": FUNNEL_COMMENT, "ab_comment": AB_COMMENT,
        "shared_comment": diagnosis+" "+direction+" 상품·시장 근거 연결과 계획 검토 후 다음 방향을 정하겠습니다."}


def _render(value, context, references):
    if isinstance(value, str):
        def replace(match):
            key, field = match.groups()
            text = _display(context, key, field)
            reference = {"metric_key": key, "field": field}
            if reference not in references:
                references.append(reference)
            return text
        def replace_case(match):
            index, field = match.groups()
            text = _display_case(context, int(index), field)
            reference = {"case_index": int(index), "field": field}
            if reference not in references:
                references.append(reference)
            return text
        def replace_plan(match):
            field = match[1]
            reference = {"plan_field": field}
            if reference not in references:
                references.append(reference)
            return _display_plan(context, field)
        return _PLAN_REF.sub(replace_plan, _CASE_REF.sub(replace_case, _REF.sub(replace, value)))
    if isinstance(value, list):
        return [_render(item, context, references) for item in value]
    return {key: _render(item, context, references) for key, item in value.items()}


def rule_based(payload, *, learning_context=None, plan_context=None):
    """AI가 아닌 결정적 기본 초안. 데이터 조회·저장·외부 호출은 없다."""
    context = build_context(payload, learning_context=learning_context, plan_context=plan_context)
    references = []
    result = {"source": "rule_based", "model": None, "prompt_version": PROMPT_VERSION,
        "document": normalize_document(_render(_baseline(context), context, references)),
        "references": references, "caveats": ["규칙 기반 초안이며 AI 생성 결과가 아닙니다.",
        "광고 전환가치는 플랫폼 전환금액이며 실제 주문·결제 매출과 별도입니다.",
        "문안 승인은 광고 변경 승인이 아닙니다. 실행은 별도 승인·한도·권한 검증이 필요합니다."]}
    return _with_learning_provenance(result, context, learning_context, plan_context)


def document_template():
    """제공자에게 주는 닫힌 문서 예시. 미연결 항목의 경계 문구는 고정한다."""
    plan = [{"action": "자료와 계획 검토", "reason": "검증된 근거를 먼저 연결합니다.",
             "criterion": "목표·자료 완결·비교 조건을 확인한 뒤 별도 운영 승인"}]
    return {"diagnosis": "저장판의 확인 자료와 완결 상태를 먼저 검토합니다.",
        "direction": "원인 가설을 검증할 근거와 목표를 연결한 뒤 다음 계획을 검토합니다.",
        "appeal_points": [], "competitive_response": COMPETITIVE_COMMENT,
        "weekly_plan": deepcopy(plan), "monthly_plan": deepcopy(plan),
        "funnel_comment": FUNNEL_COMMENT, "ab_comment": AB_COMMENT,
        "shared_comment": "확인 자료를 바탕으로 진단과 다음 계획을 검토하겠습니다."}


def _text(value, limit, context, *, require_refs=True):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit or any(
            (ord(char) < 32 and char != "\n") or 0x7f <= ord(char) <= 0x9f or 0xd800 <= ord(char) <= 0xdfff or
            char in "<>" or 0x202a <= ord(char) <= 0x202e or 0x2066 <= ord(char) <= 0x2069 for char in value)):
        raise StrategyRefused("DOCUMENT_INVALID")
    if require_refs:
        for match in _REF.finditer(value):
            _display(context, *match.groups())
        for match in _CASE_REF.finditer(value):
            _display_case(context, int(match[1]), match[2])
        for match in _PLAN_REF.finditer(value):
            _display_plan(context, match[1])
        prose = _PLAN_REF.sub("", _CASE_REF.sub("", _REF.sub("", value)))
        if ("{{" in prose or "}}" in prose or any(char.isnumeric() for char in prose) or
                any(char in prose for char in "%％₩") or
                re.search(r"(?<![가-힣])(?:[일이삼사오육칠팔구십백천만억]+|한|두|세|네|다섯|여섯|일곱|여덟|아홉)\s*(?:원|배|퍼센트|건|회)", prose)):
            raise StrategyRefused("NUMERIC_CITATION_REQUIRED")
    return value.strip()


def normalize_document(document):
    """직원 편집용 형태·길이·일반 텍스트 검증. 숫자와 수동 근거 입력을 허용한다."""
    if not isinstance(document, dict) or set(document) != DOCUMENT_FIELDS:
        raise StrategyRefused("DOCUMENT_INVALID")
    clean = {key: _text(document[key], limit, None, require_refs=False) for key, limit in TEXT_LIMITS.items()}
    appeals = document["appeal_points"]
    if not isinstance(appeals, list) or len(appeals) > 3:
        raise StrategyRefused("DOCUMENT_INVALID")
    clean["appeal_points"] = []
    for row in appeals:
        limits = {"title": 100, "message": 300, "basis": 500}
        if not isinstance(row, dict) or set(row) != set(limits):
            raise StrategyRefused("DOCUMENT_INVALID")
        clean["appeal_points"].append({key: _text(row[key], limit, None, require_refs=False) for key, limit in limits.items()})
    for period in ("weekly_plan", "monthly_plan"):
        plans = document[period]
        if not isinstance(plans, list) or not 1 <= len(plans) <= 6:
            raise StrategyRefused("DOCUMENT_INVALID")
        clean[period] = []
        for row in plans:
            if not isinstance(row, dict) or set(row) != set(PLAN_LIMITS):
                raise StrategyRefused("DOCUMENT_INVALID")
            clean[period].append({key: _text(row[key], limit, None, require_refs=False) for key, limit in PLAN_LIMITS.items()})
    return clean


def _validate_template(document, context):
    clean = normalize_document(document)
    for key, limit in TEXT_LIMITS.items():
        clean[key] = _text(clean[key], limit, context)
    # 과거 검수 사례와 현재 계획은 현재 보고서의 상품·경쟁·구매·실험 증거가 아니다.
    # 모델이 현재 관찰을 실행한 실험이나 구매 여정으로 바꾸면 그대로 거절한다.
    if (document["appeal_points"] != [] or clean["competitive_response"] != COMPETITIVE_COMMENT or
            clean["funnel_comment"] != FUNNEL_COMMENT or clean["ab_comment"] != AB_COMMENT):
        raise StrategyRefused("UNCONNECTED_EVIDENCE")
    for period in ("weekly_plan", "monthly_plan"):
        for row in clean[period]:
            for key, limit in PLAN_LIMITS.items():
                row[key] = _text(row[key], limit, context)
    return clean


def validate_document(document, context):
    """모델의 닫힌 참조 문서를 검증하고 근거 수치를 치환한 일반 텍스트를 반환한다."""
    return normalize_document(_render(_validate_template(document, context), context, []))


def generate(payload, *, provider=None, learning_context=None, plan_context=None):
    """명시된 provider만 호출한다. 실패 시 기존 승인본을 대체할 결과를 만들지 않는다."""
    if provider is None:
        return rule_based(payload, learning_context=learning_context, plan_context=plan_context)
    context = build_context(payload, learning_context=learning_context, plan_context=plan_context)
    try:
        candidate = provider(deepcopy(context))
    except StrategyRefused:
        raise
    except Exception:
        raise StrategyRefused("PROVIDER_UNAVAILABLE") from None
    clean = _validate_template(candidate, context)
    references = []
    result = {"source": "claude", "model": getattr(provider, "model", None), "prompt_version": PROMPT_VERSION,
        "document": normalize_document(_render(clean, context, references)), "references": references,
        "caveats": ["AI 전략 초안이며 담당자 검토·문안 승인이 필요합니다.",
        "광고 전환가치는 플랫폼 전환금액이며 실제 주문·결제 매출과 별도입니다.",
        "문안 승인은 광고 변경 승인이 아닙니다. 실행은 별도 승인·한도·권한 검증이 필요합니다."]}
    return _with_learning_provenance(result, context, learning_context, plan_context)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def constant(value):
        raise ValueError()
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise StrategyRefused("PROVIDER_RESPONSE_INVALID") from None
