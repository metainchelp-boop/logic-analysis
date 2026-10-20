"""Bounded, versioned marketing evidence. Callers enforce current account access.

Every save/review/rejection appends a version. Review does not promote an observed
before/after association into a causal result. No network or advertising writes.
"""
from copy import deepcopy
from datetime import date, datetime, time
import hashlib
import json
import math
import re

from . import store as S
from . import observational_inference as OI
from . import randomized_inference as RI

MAX_CHARS = 24000
MAX_VERSION = 2**53 - 1
MAX_ASSETS = 500
KINDS = frozenset({"performance", "setting_change", "experiment"})
METADATA_ENUMS = {
    "industry": frozenset({"food", "pet", "home", "beauty", "fashion", "local_service", "b2b", "other"}),
    "goal": frozenset({"impressions", "clicks", "cpa", "roas", "ctr", "cvr"}),
    "ad_type": frozenset({"powerlink", "shopping", "brand", "place", "display", "other"}),
    "budget_band": frozenset({"under_300k", "300k_1m", "1m_3m", "over_3m"}),
}
SETTING_FIELDS = frozenset({"goal", "target_value", "daily_spend_cap", "absolute_bid_cap",
                            "experiment_days", "loss_cap", "bid", "daily_budget", "enabled"})
COUNTS = frozenset({"impressions", "clicks"})
METRICS = COUNTS | {"spend", "conversions", "conversion_value"}
CONVERSION_DEFINITIONS = frozenset({"purchase", "lead", "platform", "platform_all_conversions", "unknown"})
VALUE_BASES = frozenset({"platform_conversion_value", "paid_order_revenue", "gross_profit", "unknown"})
# The current automatic 08/09 collectors read ccnt/convAmt only. Supporting
# purchase/order/profit facts requires a new typed source schema, not plan labels.
AUTO_CONVERSION_DEFINITIONS = frozenset({"platform", "platform_all_conversions", "unknown"})
AUTO_VALUE_BASES = frozenset({"platform_conversion_value", "unknown"})
LESSON_CODES = frozenset({"collect_more_data", "verify_measurement", "verify_configuration",
    "respect_risk_limit", "monitor_execution", "retain_observation", "no_transferable_lesson"})
CONFOUNDER_CODES = frozenset({"non_randomized", "non_independent", "unequal_delivery", "multiple_changes",
    "measurement_incomplete", "lag_pending", "source_changed", "external_factors_unknown"})
AUTO_KINDS = frozenset({"experiment_observation", "execution_result"})
AUTO_ACTIONS = frozenset({"create_campaign", "create_adgroup", "create_keyword", "create_text_ad",
    "update_bid", "update_daily_budget", "set_user_lock"})
AUTO_STATUSES = {
    "experiment_observation": frozenset({"ok", "partial", "pending", "failed", "stale", "unavailable", "superseded"}),
    "execution_result": frozenset({"planned", "approved", "queued", "dispatched", "accepted", "unknown",
        "rejected", "cancelled", "stopped", "confirmed"}),
}
AUTO_MEASUREMENTS = frozenset({"complete", "partial", "unavailable", "not_applicable"})
_EXECUTION_STATES = frozenset({"planned", "observed", "applied", "dispatched", "unknown", "rejected", "cancelled", "stopped"})
_PERFORMANCE_FIELDS = frozenset({"period_start", "period_end", "source_at", "measurement_complete", "lag_mature",
    "conversion_definition", "value_basis"}) | METRICS
_EXPERIMENT_FACTS = frozenset({"source_status", "recorded_at", "source_at", "method", "declared_control_sample",
    "declared_treatment_sample", "measurement_lag_days", "experiment_spend_cap", "control_daily_cap",
    "treatment_daily_cap", "metric_role", "plan_goal", "value_basis", "baseline"})
RANDOMIZED_SCOPE = ("unobserved_targeting_landing_stability_assumed", "sampling_lag_soft_spend_cap",
    "constant_additive_effect_model_unverified")
_RANDOMIZED_FACTS = frozenset({"randomized_result", "observation_scope", "washout_hours", "minimum_impressions_per_block"})
_EXECUTION_FACTS = frozenset({"source_status", "recorded_at", "source_at", "decided_at", "dispatched_at", "confirmed_at",
    "action", "desired", "profile", "baseline", "followup"})
REASON_CODES = frozenset({"observed_performance", "planned_change", "observed_change", "applied_change",
    "no_causal_control", "running", "stopped", "horizon_not_complete", "not_preregistered",
    "not_randomized", "multiple_variables", "measurement_incomplete", "conversion_definition_unknown",
    "lag_not_mature", "allocation_invalid", "sample_ratio_mismatch", "missing_metrics", "invalid_binary_counts",
    "goal_requires_variance", "insufficient_sample", "predeclared_sample_below_power", "no_statistical_separation",
    "below_mde", "qualified_difference", "protocol_changed", "independent_units_unknown",
    "observed_comparison", "historical_model_conditional", "execution_dispatched", "execution_unknown", "execution_rejected",
    "execution_cancelled", "execution_stopped"})


def _refuse(message="학습 자산의 항목과 값을 확인해 주세요"):
    raise S.StoreRefused(message)


def _text(value, maximum=160):
    if (not isinstance(value, str) or len(value) > maximum or re.search(
            r"[<>\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", value)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
        _refuse()
    return value.strip()


def _integer(value, *, minimum=0, maximum=10**12):
    if type(value) is not int or not minimum <= value <= maximum:
        _refuse()
    return value


def _number(value, *, minimum=0, maximum=10**15):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        _refuse()
    return value


def _boolean(value):
    if type(value) is not bool:
        _refuse()
    return value


def _enum(value, choices, *, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or value not in choices:
        _refuse()
    return value


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        _refuse()
    try:
        if date.fromisoformat(value).isoformat() != value:
            _refuse()
    except ValueError:
        _refuse()
    return value


def _at(value):
    if not isinstance(value, str) or len(value) > 40:
        _refuse()
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            _refuse()
        return parsed
    except (ValueError, TypeError):
        _refuse()


def _fields(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        _refuse()


def _identity(possibility_id, account_key, asset_id=None):
    _integer(possibility_id, minimum=1, maximum=MAX_VERSION)
    if not isinstance(account_key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", account_key):
        _refuse()
    if asset_id is not None and (not isinstance(asset_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", asset_id)):
        _refuse()
    return f"{possibility_id}:{hashlib.sha256(account_key.encode()).hexdigest()}:"


def metadata_document(value):
    _fields(value, METADATA_ENUMS)
    return {key: _enum(value[key], choices, nullable=True) for key, choices in METADATA_ENUMS.items()}


def _codes(value, allowed):
    if not isinstance(value, list) or len(value) > 6 or any(not isinstance(item, str) or item not in allowed for item in value) or len(set(value)) != len(value):
        _refuse("교훈과 혼란 요인 코드를 확인해 주세요")
    return list(value)


def annotation_document(value):
    """Classification is a separate review input, never an edit of source facts."""
    _fields(value, {"metadata", "lesson_codes", "confounder_codes", "private_comment"})
    return {"metadata": metadata_document(value["metadata"]),
        "lesson_codes": _codes(value["lesson_codes"], LESSON_CODES),
        "confounder_codes": _codes(value["confounder_codes"], CONFOUNDER_CODES),
        "private_comment": _text(value["private_comment"], 1000)}


def normalize_auto_source(value):
    _fields(value, {"kind", "id", "revision", "protocol_version", "plan_version", "material_fingerprint"})
    kind = _enum(value["kind"], AUTO_KINDS)
    if not isinstance(value["id"], str) or not re.fullmatch(r"[0-9a-f]{32}", value["id"]):
        _refuse()
    if not isinstance(value["material_fingerprint"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["material_fingerprint"]):
        _refuse()
    for key in ("revision", "plan_version"):
        _integer(value[key], minimum=1, maximum=MAX_VERSION)
    if kind == "experiment_observation":
        _integer(value["protocol_version"], minimum=1, maximum=MAX_VERSION)
    elif value["protocol_version"] is not None:
        _refuse()
    return deepcopy(value)


def source_profile(value):
    _fields(value, {"conversion_definition", "value_basis"})
    return {"conversion_definition": _enum(value["conversion_definition"], CONVERSION_DEFINITIONS),
        "value_basis": _enum(value["value_basis"], VALUE_BASES)}


def auto_source_profile(value):
    """Validate actual collector semantics independently of the approved goal."""
    clean = source_profile(value)
    _enum(clean["conversion_definition"], AUTO_CONVERSION_DEFINITIONS)
    _enum(clean["value_basis"], AUTO_VALUE_BASES)
    return clean


def _performance(value):
    if value is None:
        return None
    _fields(value, _PERFORMANCE_FIELDS)
    out = deepcopy(value)
    out.update(_metrics({key: value[key] for key in METRICS}))
    for key in ("period_start", "period_end"):
        out[key] = _day(value[key])
    if out["period_start"] > out["period_end"] or (date.fromisoformat(out["period_end"]) - date.fromisoformat(out["period_start"])).days > 366:
        _refuse()
    for key in ("measurement_complete", "lag_mature"):
        out[key] = _boolean(value[key])
    out.update(auto_source_profile({key: value[key] for key in ("conversion_definition", "value_basis")}))
    if value["source_at"] is not None:
        _at(value["source_at"])
    if value["measurement_complete"] and (value["source_at"] is None or any(value[key] is None for key in METRICS)):
        _refuse("완결 성과에는 정확한 기간·시각·숫자가 필요합니다")
    return out


def _source_facts(value, source):
    kind = source["kind"]
    exploratory = (kind == "experiment_observation" and isinstance(value, dict)
        and value.get("method") == OI.METHOD)
    randomized = (kind == "experiment_observation" and isinstance(value, dict)
        and value.get("method") == RI.METHOD)
    fields = _EXPERIMENT_FACTS | {"exploratory_diagnostic"} if exploratory else _EXPERIMENT_FACTS
    if randomized:
        fields = fields | _RANDOMIZED_FACTS
    _fields(value, fields if kind == "experiment_observation" else _EXECUTION_FACTS)
    out = deepcopy(value)
    out["source_status"] = _enum(value["source_status"], AUTO_STATUSES[kind])
    recorded = _at(value["recorded_at"])
    for key in (("source_at",) if kind == "experiment_observation" else ("source_at", "decided_at", "dispatched_at", "confirmed_at")):
        if value[key] is not None and _at(value[key]) > recorded:
            _refuse("원천의 시각 순서를 확인해 주세요")
    if kind == "experiment_observation":
        out["method"] = _enum(value["method"], {"two_proportion_fixed_horizon_95_80_v1", "observational_only_v1", OI.METHOD, RI.METHOD}, nullable=True)
        if randomized:
            try:
                out["randomized_result"] = RI.normalize_result(value["randomized_result"])
            except (RI.InferenceInvalid, TypeError, ValueError):
                _refuse("과거 무작위 시간 블록 비교의 조건부 모형 결과를 확인해 주세요")
            if value["observation_scope"] != list(RANDOMIZED_SCOPE):
                _refuse("확인한 설정 범위와 미검증 모형 가정을 보존해 주세요")
            out["washout_hours"] = _integer(value["washout_hours"], minimum=1, maximum=23)
            out["minimum_impressions_per_block"] = _integer(value["minimum_impressions_per_block"], minimum=1, maximum=MAX_VERSION)
            if (value["value_basis"] != "unknown" or any(value[key] is not None for key in (
                    "declared_control_sample", "declared_treatment_sample", "control_daily_cap", "treatment_daily_cap", "baseline"))):
                _refuse("시간 블록 CTR 결과에 전환·매출이나 별도 표본 계획을 채울 수 없습니다")
        if exploratory:
            try:
                out["exploratory_diagnostic"] = (None if value["exploratory_diagnostic"] is None
                    else OI.normalize_decision(value["exploratory_diagnostic"]))
            except (OI.DiagnosticInvalid, TypeError, ValueError):
                _refuse("관찰 비교의 수치와 검증 수준을 확인해 주세요")
        for key in ("declared_control_sample", "declared_treatment_sample"):
            if value[key] is not None:
                out[key] = _integer(value[key], minimum=1, maximum=10**9)
        if value["measurement_lag_days"] is not None:
            out["measurement_lag_days"] = _integer(value["measurement_lag_days"], maximum=30)
        for key in ("experiment_spend_cap", "control_daily_cap", "treatment_daily_cap"):
            if value[key] is not None:
                out[key] = _number(value[key], minimum=1e-12, maximum=10**12)
        out["metric_role"] = _enum(value["metric_role"], {"primary", "proxy"})
        out["plan_goal"] = _enum(value["plan_goal"], METADATA_ENUMS["goal"])
        out["value_basis"] = _enum(value["value_basis"], AUTO_VALUE_BASES)
        if value["baseline"] is not None:
            _fields(value["baseline"], {"control", "treatment"})
            out["baseline"] = {key: _performance(value["baseline"][key]) for key in ("control", "treatment")}
    else:
        out["action"] = _enum(value["action"], AUTO_ACTIONS)
        out["desired"] = _settings(value["desired"])
        out["profile"] = auto_source_profile(value["profile"])
        for key in ("baseline", "followup"):
            out[key] = _performance(value[key])
        if value["confirmed_at"] is not None and (value["source_status"] != "confirmed" or value["dispatched_at"] is None or _at(value["confirmed_at"]) < _at(value["dispatched_at"])):
            _refuse("반영 확인에는 송신과 정확한 재조회 기록이 필요합니다")
        if value["source_status"] == "confirmed" and value["confirmed_at"] is None:
            _refuse("반영 확인 시각이 필요합니다")
        if value["source_status"] in {"accepted", "dispatched", "confirmed"} and value["dispatched_at"] is None:
            _refuse("송신 상태에는 실제 송신 기록이 필요합니다")
        if value["followup"] is not None and value["confirmed_at"] is None:
            _refuse("미확인 실행에 변경 후 실적을 연결할 수 없습니다")
        if value["followup"] is not None and date.fromisoformat(value["followup"]["period_start"]) <= _at(value["confirmed_at"]).astimezone(S.KST).date():
            _refuse("변경 후 관측은 반영 확인 다음 날부터의 별도 기간이어야 합니다")
    performances = (list((out["baseline"] or {}).values()) if kind == "experiment_observation" else [out["baseline"], out["followup"]])
    if any(perf is not None and perf["source_at"] is not None and _at(perf["source_at"]) > recorded for perf in performances):
        _refuse("원천 성과의 저장 시각을 확인해 주세요")
    return out


def source_summary(document):
    """Closed anonymous facts only; source identity and timestamps stay private."""
    source = normalize_auto_source(document["source_refs"]["auto_source"])
    facts, evidence = document["evidence"]["source_facts"], document["evidence"]
    if source["kind"] == "experiment_observation":
        measurement = "complete" if facts["source_status"] == "ok" and evidence["measurement_complete"] else "partial" if facts["source_status"] == "partial" else "unavailable"
        action = None
    else:
        perf = facts["followup"] or facts["baseline"]
        measurement = ("not_applicable" if perf is None else "complete" if perf["measurement_complete"] else "partial")
        action = facts["action"]
    return {"kind": source["kind"], "status": facts["source_status"], "action": action,
        "measurement": measurement, "causal_claim": False}


def normalize_source_summary(value):
    _fields(value, {"kind", "status", "action", "measurement", "causal_claim"})
    kind = _enum(value["kind"], AUTO_KINDS)
    _enum(value["status"], AUTO_STATUSES[kind])
    _enum(value["measurement"], AUTO_MEASUREMENTS)
    if value["causal_claim"] is not False:
        _refuse()
    if kind == "experiment_observation":
        if value["action"] is not None:
            _refuse()
    else:
        _enum(value["action"], AUTO_ACTIONS)
    return deepcopy(value)


def _compact_performance(value):
    if value is None:
        return None
    return {"days": (date.fromisoformat(value["period_end"]) - date.fromisoformat(value["period_start"])).days + 1,
        **{key: deepcopy(value[key]) for key in METRICS},
        **{key: value[key] for key in ("measurement_complete", "lag_mature", "conversion_definition", "value_basis")}}


def anonymous_evidence(document):
    """Typed source facts for STR; no source identity, raw dates or private text."""
    out = deepcopy(document["evidence"])
    if "auto_source" not in document["source_refs"]:
        return out
    facts = out.pop("source_facts")
    if document["kind"] == "experiment":
        allowed = _EXPERIMENT_FACTS - {"source_status", "recorded_at", "source_at", "baseline"}
        compact = {key: deepcopy(facts[key]) for key in allowed}
        if facts["method"] == OI.METHOD:
            compact["exploratory_diagnostic"] = deepcopy(facts["exploratory_diagnostic"])
        if facts["method"] == RI.METHOD:
            compact.update({key: deepcopy(facts[key]) for key in _RANDOMIZED_FACTS})
        compact["baseline"] = ({key: _compact_performance(facts["baseline"][key]) for key in ("control", "treatment")}
            if facts["baseline"] is not None else None)
    else:
        compact = {"desired": deepcopy(facts["desired"]), "profile": deepcopy(facts["profile"]),
            "baseline": _compact_performance(facts["baseline"]), "followup": _compact_performance(facts["followup"])}
    out["source_facts"] = compact
    return out


def auto_document(kind, *, title, evidence, source):
    """Server builder; permissions/current-source proof belong to the caller."""
    ref = normalize_auto_source(source)
    doc = {"kind": kind, "title": title, "metadata": dict.fromkeys(METADATA_ENUMS),
        "evidence": deepcopy(evidence), "source_refs": {"auto_source": ref}}
    if kind == "experiment":
        for key in ("randomized", "independent_units", "allocation_valid"):
            doc["evidence"][key] = False
    return normalize_document(doc)


def _metrics(value):
    _fields(value, METRICS)
    return {key: None if value[key] is None else
            (_integer(value[key]) if key in COUNTS else _number(value[key])) for key in sorted(METRICS)}


def _settings(value):
    if not isinstance(value, dict) or not set(value) <= SETTING_FIELDS:
        _refuse()
    out = {}
    for key, item in value.items():
        if item is None:
            out[key] = None
        elif key == "goal":
            out[key] = _enum(item, METADATA_ENUMS["goal"])
        elif key == "enabled":
            out[key] = _boolean(item)
        elif key == "experiment_days":
            out[key] = _integer(item, minimum=1, maximum=365)
        else:
            out[key] = _number(item)
    return out


def document_template(kind):
    """An incomplete draft template; dates and relevant measurements must be set."""
    _enum(kind, KINDS)
    metrics = {key: None for key in sorted(METRICS)}
    period = {"period_start": None, "period_end": None}
    if kind == "performance":
        evidence = {**period, **metrics, "measurement_complete": False,
                    "conversion_definition": "unknown", "lag_mature": False}
    elif kind == "setting_change":
        evidence = {"execution": "planned", "changed_variable": "multiple", "before": {}, "after": {}, "observed_at": None}
    else:
        evidence = {**period, "status": "running", "goal": "ctr", "min_sample_per_arm": 100,
            "baseline_rate": None, "mde_percent": 20, "control_share": 0.5, "preregistered_at": None,
            "randomized": False, "independent_units": False, "one_variable": False, "measurement_complete": False,
            "lag_mature": False, "allocation_valid": False, "conversion_definition": "unknown",
            "control": dict(metrics), "treatment": dict(metrics)}
    return {"kind": kind, "title": "", "metadata": {key: None for key in METADATA_ENUMS},
            "evidence": evidence, "source_refs": {}}


def normalize_document(value):
    _fields(value, {"kind", "title", "metadata", "evidence", "source_refs"})
    kind = _enum(value["kind"], KINDS)
    refs = value["source_refs"]
    if not isinstance(refs, dict) or not set(refs) <= {"report_id", "report_revision", "plan_version", "setting_version", "auto_source"}:
        _refuse()
    auto = normalize_auto_source(refs["auto_source"]) if "auto_source" in refs else None
    if auto is not None and (set(refs) != {"auto_source"} or kind != {"experiment_observation": "experiment", "execution_result": "setting_change"}[auto["kind"]]):
        _refuse()
    evidence = value["evidence"]
    _fields(evidence, set(document_template(kind)["evidence"]) | ({"source_facts"} if auto else set()))
    clean = deepcopy(evidence)
    if auto:
        clean["source_facts"] = _source_facts(evidence["source_facts"], auto)
    if kind in ("performance", "experiment"):
        for key in ("period_start", "period_end"):
            clean[key] = _day(evidence[key])
        if clean["period_start"] > clean["period_end"] or (date.fromisoformat(clean["period_end"]) - date.fromisoformat(clean["period_start"])).days > 366:
            _refuse("성과 관측 기간을 확인해 주세요")
        clean["measurement_complete"] = _boolean(evidence["measurement_complete"])
        clean["lag_mature"] = _boolean(evidence["lag_mature"])
        clean["conversion_definition"] = _enum(evidence["conversion_definition"],
            AUTO_CONVERSION_DEFINITIONS if auto else CONVERSION_DEFINITIONS)
    if kind == "performance":
        clean.update(_metrics({key: evidence[key] for key in METRICS}))
    elif kind == "setting_change":
        clean["execution"] = _enum(evidence["execution"], _EXECUTION_STATES if auto else {"planned", "observed", "applied"})
        clean["changed_variable"] = _enum(evidence["changed_variable"], SETTING_FIELDS | {"multiple"})
        clean["before"] = _settings(evidence["before"])
        clean["after"] = None if auto and evidence["after"] is None else _settings(evidence["after"])
        if evidence["observed_at"] is not None:
            _at(evidence["observed_at"])
        if clean["execution"] in {"observed", "applied"} and evidence["observed_at"] is None:
            _refuse("실제 세팅의 관측 시각이 필요합니다")
        compared = clean["source_facts"]["desired"] if auto and clean["after"] is None else clean["after"]
        changed = {key for key in set(clean["before"]) | set(compared)
                   if clean["before"].get(key) != compared.get(key)}
        if clean["changed_variable"] != "multiple" and changed != {clean["changed_variable"]}:
            _refuse("세팅 변경 항목과 전후 값을 확인해 주세요")
        if auto:
            status = clean["source_facts"]["source_status"]
            expected = ({"confirmed": "applied", "accepted": "dispatched", "approved": "planned", "queued": "planned"}.get(status, status))
            if clean["execution"] != expected or (status != "confirmed" and (clean["after"] is not None or clean["observed_at"] is not None)):
                _refuse("송신·미확인과 실제 반영 확인을 구분해 주세요")
            if status == "confirmed" and (clean["after"] is None or clean["observed_at"] != clean["source_facts"]["confirmed_at"]):
                _refuse("변경 후 값은 실제 반영 재조회에서만 가져올 수 있습니다")
            if status == "confirmed" and any(clean["after"].get(key) != item for key, item in clean["source_facts"]["desired"].items()):
                _refuse("반영 확인과 승인된 의도값이 다릅니다")
    else:
        clean["status"] = _enum(evidence["status"], {"running", "completed", "stopped"})
        clean["goal"] = _enum(evidence["goal"], {"ctr", "cvr", "cpa", "roas"})
        for key, validate in (("min_sample_per_arm", lambda v: _integer(v, minimum=1, maximum=10**9)),
                ("mde_percent", lambda v: _number(v, minimum=1e-12 if auto else 0.1, maximum=100)),
                ("control_share", lambda v: _number(v, minimum=0.1, maximum=0.9))):
            clean[key] = None if auto and evidence[key] is None else validate(evidence[key])
        if evidence["baseline_rate"] is not None:
            clean["baseline_rate"] = _number(evidence["baseline_rate"], minimum=0.000001, maximum=0.999999)
        if evidence["preregistered_at"] is not None:
            _at(evidence["preregistered_at"])
        for key in ("randomized", "independent_units", "one_variable", "allocation_valid"):
            clean[key] = _boolean(evidence[key])
        if auto and any(clean[key] for key in ("randomized", "independent_units", "allocation_valid")):
            _refuse("플랫폼 관측 비교에는 무작위 배정과 독립 표본의 근거가 없습니다")
        for key in ("control", "treatment"):
            clean[key] = _metrics(evidence[key])
        if auto and clean["source_facts"]["method"] == RI.METHOD:
            if (clean["goal"] != "ctr" or clean["conversion_definition"] != "unknown" or any(
                    clean[key] is not None for key in ("min_sample_per_arm", "baseline_rate", "mde_percent", "control_share"))
                    or any(clean[arm][key] is not None for arm in ("control", "treatment") for key in ("conversions", "conversion_value"))):
                _refuse("과거 시간 블록 CTR의 표본·퍼센트포인트와 전환 지표를 구분해 주세요")
            result = clean["source_facts"]["randomized_result"]
            if (date.fromisoformat(clean["period_end"])-date.fromisoformat(clean["period_start"])).days+1 != 2*result["pair_count"]:
                _refuse("과거 시간 블록 쌍과 실제 관측 기간을 확인해 주세요")
            if result["decision"] != "hold" and (not clean["measurement_complete"] or not clean["lag_mature"]
                    or clean["status"] != "completed" or clean["source_facts"]["source_status"] != "ok"
                    or clean["preregistered_at"] is None or _at(clean["preregistered_at"]).astimezone(S.KST).date()>=date.fromisoformat(clean["period_start"])):
                _refuse("조건부 판정에는 완결된 과거 원천과 고정 기간·대기 조건이 필요합니다")
    for key, item in refs.items():
        if key == "auto_source":
            continue
        if key == "report_revision":
            if not _text(item, 160):
                _refuse()
        else:
            _integer(item, minimum=1, maximum=MAX_VERSION)
    return {"kind": kind, "title": _text(value["title"]), "metadata": metadata_document(value["metadata"]),
            "evidence": clean, "source_refs": deepcopy(refs)}


def _wilson(success, total):
    z = 1.959963984540054
    p, z2 = success / total, z * z
    middle = (p + z2 / (2 * total)) / (1 + z2 / total)
    radius = z * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total)) / (1 + z2 / total)
    return middle - radius, middle + radius


def _required_sample(baseline, mde_percent, control_share):
    if baseline is None:
        return None
    alternative = min(0.999999, baseline * (1 + mde_percent / 100))
    difference = alternative - baseline
    if difference <= 0:
        return None
    average = (baseline + alternative) / 2
    numerator = (1.959963984540054 * math.sqrt(2 * average * (1 - average)) +
                 0.8416212335729143 * math.sqrt(baseline * (1 - baseline) + alternative * (1 - alternative))) ** 2
    # Conservatively inflate both arm minima for unequal predeclared allocation.
    return math.ceil(numerator / difference**2 * max(control_share / (1 - control_share), (1 - control_share) / control_share))


def _spec_hash(document):
    evidence = document["evidence"]
    fields = ("period_start", "period_end", "goal", "min_sample_per_arm", "baseline_rate", "mde_percent",
              "control_share", "preregistered_at", "randomized", "independent_units", "one_variable", "conversion_definition")
    spec = {key: evidence[key] for key in fields}
    spec["metadata"] = document["metadata"]
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def assess(document, at, registration=None):
    """Calculate evidence quality and a fixed-horizon binary-rate difference.

    CPA/ROAS require event variance and cannot win from aggregate totals alone.
    Wilson/Newcombe bounds estimate the two-sided 95% rate-difference interval.
    """
    current = _at(at)
    kind, evidence = document["kind"], document["evidence"]
    result = {"outcome": "observation", "winner": None, "reason_codes": [], "causal_claim": False,
              "confidence_interval": None, "required_sample_per_arm": None}
    reasons = result["reason_codes"]
    if kind == "performance":
        reasons.extend(["observed_performance", "no_causal_control"])
        if not evidence["measurement_complete"]:
            reasons.append("measurement_incomplete")
        if not evidence["lag_mature"]:
            reasons.append("lag_not_mature")
        return result
    if kind == "setting_change":
        reasons.extend([{"planned": "planned_change", "observed": "observed_change", "applied": "applied_change",
            "dispatched": "execution_dispatched", "unknown": "execution_unknown", "rejected": "execution_rejected",
            "cancelled": "execution_cancelled", "stopped": "execution_stopped"}[evidence["execution"]], "no_causal_control"])
        return result
    if "auto_source" in document["source_refs"]:
        if evidence["source_facts"]["method"] == RI.METHOD:
            # The reserved automatic asset is a historical case, not this report's
            # current experiment. Its full conditional result lives in source_facts.
            reasons.extend(["observed_comparison", "no_causal_control", "historical_model_conditional"])
        else:
            reasons.extend(["observed_comparison", "no_causal_control", "not_randomized", "independent_units_unknown", "allocation_invalid"])
        if not evidence["measurement_complete"]:
            reasons.append("measurement_incomplete")
        if not evidence["lag_mature"]:
            reasons.append("lag_not_mature")
        if evidence["status"] == "stopped":
            reasons.append("stopped")
        return result
    result["outcome"] = "unknown"
    # Repeated impressions/clicks by the same person are not automatically
    # independent observations. Their experimental independence needs review.
    for key, reason in (("randomized", "not_randomized"), ("independent_units", "independent_units_unknown"), ("one_variable", "multiple_variables"),
                        ("allocation_valid", "allocation_invalid")):
        if not evidence[key]:
            reasons.append(reason)
    preregistered = evidence["preregistered_at"]
    starts = datetime.combine(date.fromisoformat(evidence["period_start"]), time(), tzinfo=S.KST)
    if (preregistered is None or _at(preregistered) >= starts or registration is None or
            _at(registration["at"]) >= starts):
        reasons.append("not_preregistered")
    if registration is not None and registration["spec_hash"] != _spec_hash(document):
        reasons.append("protocol_changed")
    if evidence["status"] == "stopped":
        reasons.append("stopped")
    if reasons:
        result["outcome"] = "invalid"
        return result
    if evidence["status"] == "running":
        reasons.append("running")
    if current.astimezone(S.KST).date() <= date.fromisoformat(evidence["period_end"]):
        reasons.append("horizon_not_complete")
    if not evidence["measurement_complete"]:
        reasons.append("measurement_incomplete")
    if not evidence["lag_mature"]:
        reasons.append("lag_not_mature")
    if evidence["goal"] != "ctr" and evidence["conversion_definition"] == "unknown":
        reasons.append("conversion_definition_unknown")
    if evidence["goal"] in ("cpa", "roas"):
        reasons.append("goal_requires_variance")
    if reasons:
        return result
    denominator, numerator = ("impressions", "clicks") if evidence["goal"] == "ctr" else ("clicks", "conversions")
    arms = [evidence["control"], evidence["treatment"]]
    if any(arm[denominator] is None or arm[numerator] is None for arm in arms):
        reasons.append("missing_metrics")
        return result
    if any(type(arm[denominator]) is not int or type(arm[numerator]) is not int or arm[denominator] <= 0 or arm[numerator] > arm[denominator] for arm in arms):
        result["outcome"] = "invalid"
        reasons.append("invalid_binary_counts")
        return result
    n0, n1 = (arm[denominator] for arm in arms)
    share, total = evidence["control_share"], n0 + n1
    chi_square = (n0 - total * share)**2 / (total * share) + (n1 - total * (1 - share))**2 / (total * (1 - share))
    if chi_square > 10.827566170662733:  # chi-square df=1, p<0.001 sample-ratio mismatch.
        result["outcome"] = "invalid"
        reasons.append("sample_ratio_mismatch")
        return result
    required = _required_sample(evidence["baseline_rate"], evidence["mde_percent"], share)
    result["required_sample_per_arm"] = required
    if required is None or evidence["min_sample_per_arm"] < required:
        result["outcome"] = "invalid"
        reasons.append("predeclared_sample_below_power")
        return result
    result["outcome"] = "inconclusive"
    if min(n0, n1) < evidence["min_sample_per_arm"]:
        reasons.append("insufficient_sample")
        return result
    low0, high0 = _wilson(arms[0][numerator], n0)
    low1, high1 = _wilson(arms[1][numerator], n1)
    p0, p1 = arms[0][numerator] / n0, arms[1][numerator] / n1
    difference = p1 - p0
    low = difference - math.sqrt((p1 - low1)**2 + (high0 - p0)**2)
    high = difference + math.sqrt((high1 - p1)**2 + (p0 - low0)**2)
    result["confidence_interval"] = {"low": low, "high": high, "confidence": 0.95}
    if low <= 0 <= high:
        reasons.append("no_statistical_separation")
        return result
    if abs(p1 - p0) < evidence["baseline_rate"] * evidence["mde_percent"] / 100:
        reasons.append("below_mde")
        return result
    result.update(outcome="winner", winner="treatment" if low > 0 else "control", causal_claim=True)
    reasons.append("qualified_difference")
    return result


def decode_record(row, key):
    """Validate a bounded stored row without touching the persistence connection."""
    if row is None:
        return None
    try:
        if type(row[0]) is not int or not 0 < row[0] <= MAX_CHARS or row[0] != len(row[1]):
            raise ValueError()
        value = json.loads(row[1])
        _fields(value, {"asset_id", "version", "state", "identity", "author", "reviewed_by", "reviewed_at", "document", "assessment", "registration", "request_digest"})
        _integer(value["version"], minimum=1, maximum=MAX_VERSION)
        _enum(value["state"], {"draft", "reviewed", "rejected"})
        _fields(value["identity"], {"possibility_id", "account_key"})
        identity = _identity(value["identity"]["possibility_id"], value["identity"]["account_key"], value["asset_id"])
        if key not in ("learning-head:" + identity + value["asset_id"],
                       "learning-version:" + identity + value["asset_id"] + f":{value['version']:016d}"):
            raise ValueError()
        _fields(value["author"], {"actor", "at"})
        if value["author"]["actor"] is not None:
            _integer(value["author"]["actor"], maximum=MAX_VERSION)
        elif "auto_source" not in value["document"].get("source_refs", {}):
            if (value["document"].get("kind") != "performance" or
                    not {"report_id", "report_revision"} <= set(value["document"].get("source_refs", {}))):
                raise ValueError()
        elif not value["asset_id"].startswith("auto-exp-" if value["document"]["kind"] == "experiment" else "auto-exec-"):
            raise ValueError()
        _at(value["author"]["at"])
        if value["state"] != "draft":
            _integer(value["reviewed_by"], maximum=MAX_VERSION)
            _at(value["reviewed_at"])
        elif value["reviewed_by"] is not None or value["reviewed_at"] is not None:
            raise ValueError()
        if not isinstance(value["request_digest"], str) or not re.fullmatch(r"[a-f0-9]{64}", value["request_digest"]):
            raise ValueError()
        if value["document"]["kind"] == "experiment":
            _fields(value["registration"], {"at", "spec_hash"})
            _at(value["registration"]["at"])
            if not isinstance(value["registration"]["spec_hash"], str) or not re.fullmatch(r"[a-f0-9]{64}", value["registration"]["spec_hash"]):
                raise ValueError()
        elif value["registration"] is not None:
            raise ValueError()
        if normalize_document(value["document"]) != value["document"] or assess(value["document"], value["reviewed_at"] or value["author"]["at"], value["registration"]) != value["assessment"]:
            raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, AttributeError, S.StoreRefused):
        raise S.StoreError("저장된 학습 자산을 확인해 주세요") from None


def _present(record):
    result = deepcopy(record)
    result.pop("request_digest", None)
    return result


def record(repository, possibility_id, account_key, actor, at, expected_version, asset_id, document=None, action="save"):
    """Compatibility entry; Store owns persistence and the caller's transaction."""
    return S.learning_asset_storage(repository).record(possibility_id, account_key, actor, at,
        expected_version, asset_id, document, action=action)


def list_assets(repository, possibility_id, account_key, limit=100, include_history=False, asset_id=None):
    return S.learning_asset_storage(repository).list_assets(possibility_id, account_key,
        limit=limit, include_history=include_history, asset_id=asset_id)


def get_asset(repository, possibility_id, account_key, asset_id):
    return S.learning_asset_storage(repository).get_asset(possibility_id, account_key, asset_id)


def retrieve(connection, possibility_id, account_key, metadata=None, limit=5):
    """Only reviewed same-account cases, with no advertiser/author/title/source refs.

    Invalid/stopped experiments remain useful negative evidence; their assessment
    explicitly prevents a winner or causal claim. No automatic cross-client reuse.
    """
    _integer(limit, minimum=1, maximum=5)
    wanted = metadata_document(metadata) if metadata is not None else {key: None for key in METADATA_ENUMS}
    applicable = []
    for item in list_assets(connection, possibility_id, account_key, limit=MAX_ASSETS):
        if item["state"] != "reviewed":
            continue
        if "auto_source" in item["document"]["source_refs"]:
            continue  # Automatic sources require LR's injected current-source review proof.
        known = item["document"]["metadata"]
        if any(wanted[key] is not None and known[key] is not None and wanted[key] != known[key] for key in wanted):
            continue
        score = sum(wanted[key] is not None and wanted[key] == known[key] for key in wanted)
        document = item["document"]
        safe = {"asset_id": item["asset_id"], "version": item["version"], "kind": document["kind"],
                "metadata": deepcopy(known), "evidence": deepcopy(document["evidence"]), "assessment": deepcopy(item["assessment"])}
        applicable.append((score, item["reviewed_at"], item["asset_id"], safe))
    applicable.sort(key=lambda item: item[:3], reverse=True)
    return {"version": 1, "cases": [item[3] for item in applicable[:limit]]}
