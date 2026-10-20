"""Source-bound observational comparisons and conditional experimental planning.

No assignment ledger or advertising executor exists here. Every assessment
therefore has winner=None and causal_claim=False, including complete data.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re

from . import inspection_fields as IF, operating_criteria as OC, observational_inference as OI

KST = timezone(timedelta(hours=9))
MAX_NUMBER = 9007199254740991
FIELDS = ("impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt")
KINDS = tuple(IF.IDS)
METHODS = ("two_proportion_fixed_horizon_95_80_v1", "observational_only_v1", OI.METHOD)
DOCUMENT_FIELDS = frozenset({"schema_version", "single_variable", "hypothesis", "goal", "control_key", "treatment_key",
    "period_start", "period_end", "measurement_lag_days", "sample_share", "mde_percent", "declared_control_sample",
    "declared_treatment_sample", "method", "experiment_spend_cap", "control_daily_cap", "treatment_daily_cap"})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_BINDING = frozenset({"version", "document", "scope", "plan_version", "source_fingerprint", "arms", "baseline", "criteria"})
_ARM = frozenset({"kind", "id", "parent_id", "campaign_id", "settings"})
_BASELINE = frozenset({"period_start", "period_end", "fields", "complete", "missing", "source_at", "checked_at"})
_ROW = frozenset({"fields", "missing", "complete", "source_at", "checked_at"})
SNAPSHOT_FIELDS = frozenset({"version", "status", "period_start", "period_end", "source_fingerprint", "arms",
                           "configuration_verified", "checked_at"})
STABILITY_FIELDS = frozenset({"qualifier", "expected_days", "observed_days", "missing_days", "drift", "coverage_complete",
    "first_checked_at", "last_checked_at", "limitations"})
STABILITY_LIMITATIONS = ("intraday_changes_unobserved", "unobserved_fields_unknown")


class ExperimentInvalid(ValueError):
    pass


def _bad(message="실험 계획·대상·원천의 항목을 확인해 주세요"):
    raise ExperimentInvalid(message)


def _number(value, low=0, high=MAX_NUMBER, integer=False):
    return type(value) in ((int,) if integer else (int, float)) and low <= value <= high and math.isfinite(value)


def moment(value):
    try:
        at = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(at, datetime) or at.utcoffset() is None: _bad()
        return at.astimezone(KST)
    except (TypeError, ValueError, OverflowError):
        _bad("실험 원천의 시각을 확인해 주세요")


def _day(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value): _bad()
        result = date.fromisoformat(value)
        if result.isoformat() != value: _bad()
        return result
    except (TypeError, ValueError, OverflowError):
        _bad("실험 기간을 확인해 주세요")


def fingerprint(value):
    try:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    except (TypeError, ValueError, OverflowError):
        _bad()


def _text(value, limit, nullable=False):
    if value is None and nullable: return None
    if (not isinstance(value, str) or len(value) > limit or re.search(r"[<>\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]", value)
            or any(0xD800 <= ord(c) <= 0xDFFF for c in value)): _bad()
    return value.strip()


def _label(value, fallback):
    try:
        text = _text(value, 140)
        if not text or re.search(r"https?://|www\.|\b(?:cmp|grp|kwd|nad)-|[\w.-]+\.[A-Za-z]{2,}(?:\b|/)|@", text, re.I): return fallback
        return text
    except ExperimentInvalid: return fallback


def empty_protocol():
    return {**dict.fromkeys(DOCUMENT_FIELDS), "schema_version": 1, "hypothesis": ""}


def normalize_protocol(value):
    if not isinstance(value, dict) or set(value) != DOCUMENT_FIELDS or type(value["schema_version"]) is not int or value["schema_version"] != 1: _bad()
    out = deepcopy(value)
    out["single_variable"] = _text(value["single_variable"], 160, True)
    out["hypothesis"] = _text(value["hypothesis"], 1000)
    for name, options in (("goal", ("ctr", "cvr", "cpa", "roas")), ("method", METHODS)):
        if value[name] is not None and (not isinstance(value[name], str) or value[name] not in options): _bad()
    for name in ("control_key", "treatment_key"):
        if value[name] is not None and (not isinstance(value[name], str) or not _HEX.fullmatch(value[name])): _bad()
    for name in ("period_start", "period_end"):
        if value[name] is not None: _day(value[name])
    if value["period_start"] and value["period_end"]:
        if not 1 <= (_day(value["period_end"])-_day(value["period_start"])).days+1 <= 30: _bad()
    for name, low, high, integer in (("measurement_lag_days", 0, 30, True), ("sample_share", .1, .9, False),
        ("mde_percent", 1e-12, 100, False), ("declared_control_sample", 1, 10**9, True),
        ("declared_treatment_sample", 1, 10**9, True), ("experiment_spend_cap", 1e-12, 10**12, False),
        ("control_daily_cap", 1e-12, 10**12, False), ("treatment_daily_cap", 1e-12, 10**12, False)):
        if value[name] is not None and not _number(value[name], low, high, integer): _bad()
    if out["control_key"] is not None and out["control_key"] == out["treatment_key"]: _bad("두 군의 대상은 서로 달라야 합니다")
    return out


def normalize_arm(value, customer_id):
    if not isinstance(value, dict) or set(value) != _ARM or value["kind"] not in KINDS: _bad()
    kind = value["kind"]
    if not IF.valid_id(value["id"], kind) or not IF.valid_id(value["campaign_id"], "campaign"): _bad()
    try:
        settings = IF.sanitize_record(kind, value["settings"], customer_id, value["parent_id"])
    except (TypeError, ValueError): _bad()
    if settings != value["settings"] or settings[IF.IDS[kind]] != value["id"]: _bad()
    if kind == "campaign" and (value["parent_id"] is not None or value["campaign_id"] != value["id"]): _bad()
    if kind == "adgroup" and value["parent_id"] != value["campaign_id"]: _bad()
    if kind == "keyword" and settings.get("nccCampaignId") not in (None, value["campaign_id"]): _bad()
    return deepcopy(value)


def _fields(value):
    if not isinstance(value, dict) or set(value) != set(FIELDS): _bad()
    for name, number in value.items():
        if number is not None and not _number(number, integer=name in FIELDS[:2]): _bad()
    return deepcopy(value)


def _baseline(row, start, end):
    if row is None:
        return dict(period_start=start, period_end=end, fields=dict.fromkeys(FIELDS), complete=False,
                    missing=True, source_at=None, checked_at=None)
    if not isinstance(row, dict) or set(row) != _BASELINE or type(row["complete"]) is not bool or type(row["missing"]) is not bool: _bad()
    if not 1 <= (_day(end)-_day(start)).days+1 <= 31: _bad()
    _fields(row["fields"])
    if row["period_start"] != start or row["period_end"] != end: _bad()
    for name in ("checked_at", "source_at"):
        if row[name] is not None: moment(row[name])
    if row["source_at"] is not None and (row["checked_at"] is None or moment(row["source_at"]) > moment(row["checked_at"])): _bad()
    if row["complete"] and (row["missing"] or any(row["fields"][key] is None for key in FIELDS) or row["source_at"] is None or row["checked_at"] is None): _bad()
    if row["complete"] and moment(row["source_at"]).date() <= _day(end): _bad()
    if row["missing"] and any(number is not None for number in row["fields"].values()): _bad()
    return deepcopy(row)


def candidate_catalog(observation, *, possibility_id, customer_id, account_key):
    if (not _number(possibility_id, 1, MAX_NUMBER, True) or not _number(customer_id, 1, MAX_NUMBER, True)
            or not isinstance(account_key, str) or not _HEX.fullmatch(account_key)): _bad()
    out = dict(version=1, status="unavailable", source_fingerprint=None, scope=None, period_start=None,
               period_end=None, items=[], _arms={}, _baseline={}, reason_codes=["SOURCE_UNAVAILABLE"])
    if not isinstance(observation, dict): return out
    if (observation.get("status") != "ok" or observation.get("complete") is not True or observation.get("stale") is not False
            or observation.get("possibility_id") != possibility_id or observation.get("customer_id") != customer_id): return out
    try:
        generation = moment(observation["generation"]).isoformat()
        stage_revision = _text(observation["stage_revision"], 160)
        if not stage_revision: _bad()
        start, end = observation["period_start"], observation["period_end"]
        if not 1 <= (_day(end)-_day(start)).days+1 <= 31: _bad()
        entities = observation["entities"]
        if not isinstance(entities, dict) or len(entities) > 10000: _bad()
        arms, baselines = {}, {}
        for key, row in sorted(entities.items()):
            if not isinstance(row, dict) or row.get("entity") not in KINDS: _bad()
            arm = normalize_arm({"kind": row["entity"], **{name: row[name] for name in ("id", "parent_id", "campaign_id", "settings")}}, customer_id)
            if key != arm["kind"]+":"+arm["id"]: _bad()
            if arm["kind"] != "campaign":
                parent_kind = "campaign" if arm["kind"] == "adgroup" else "adgroup"
                parent = entities.get(parent_kind+":"+arm["parent_id"])
                if not isinstance(parent, dict) or parent.get("campaign_id") != arm["campaign_id"]: _bad()
            arms[key] = arm
            baselines[key] = _baseline(observation.get("performance", {}).get(key), start, end)
        scope = dict(possibility_id=possibility_id, customer_id=customer_id, account_key=account_key,
                     stage_revision=stage_revision, generation=generation)
        stable_scope = {key: value for key, value in scope.items() if key != "generation"}
        source = fingerprint([stable_scope, arms])
        out.update(status="ready", source_fingerprint=source, scope=scope, period_start=start, period_end=end, reason_codes=[])
        for index, (key, arm) in enumerate(arms.items(), 1):
            opaque = fingerprint(["experiment-candidate-v1", stable_scope, arm])
            settings = arm["settings"]
            creative = settings.get("ad") or {}
            label = _label(settings.get("name") or settings.get("keyword") or creative.get("headline") or creative.get("title") or settings.get("type"), "대상")+" · "+str(index)
            path = []
            if arm["kind"] != "campaign":
                campaign = entities["campaign:"+arm["campaign_id"]]["settings"]
                path.append(_label(campaign.get("name"), "캠페인"))
            if arm["kind"] in ("keyword", "ad"):
                group = entities["adgroup:"+arm["parent_id"]]["settings"]
                path.append(_label(group.get("name"), "광고 그룹"))
            path.append(label)
            out["items"].append(dict(key=opaque, kind=arm["kind"], label=label, path=path))
            out["_arms"][opaque], out["_baseline"][opaque] = arm, baselines[key]
        return out
    except (KeyError, TypeError, ValueError, OverflowError):
        return dict(out, status="unavailable", source_fingerprint=None, scope=None, items=[], _arms={}, _baseline={}, reason_codes=["SOURCE_INVALID"])


def _plan(view):
    if (not isinstance(view, dict) or view.get("state") != "approved" or not _number(view.get("version"), 1, MAX_NUMBER, True)): _bad("현재 승인된 운영 계획이 필요합니다")
    value = view.get("plan") if "plan" in view else view.get("document")
    try:
        if not isinstance(value, dict) or set(value) != OC.V2_FIELDS: _bad()
        OC.normalize_extra(value, approve=True)
        if not isinstance(value["goal"], str) or value["goal"] not in ("impressions", "clicks", "cpa", "roas"): _bad()
        if any(not _number(value[name], 1e-12, 10**12) for name in ("target_value", "daily_spend_cap", "absolute_bid_cap", "loss_cap")): _bad()
        if not _number(value["experiment_days"], 2, 30, True): _bad()
        _text(value["notes"], 1000)
    except (OC.CriteriaInvalid, TypeError, ValueError): _bad("현재 승인된 v2 운영 기준이 필요합니다")
    return deepcopy(value)


def _role(plan_goal, goal):
    allowed = {"impressions": {"ctr": "proxy"}, "clicks": {"ctr": "proxy"},
               "cpa": {"cpa": "primary", "cvr": "proxy"}, "roas": {"roas": "primary"}}
    if goal is None: return None
    role = allowed.get(plan_goal, {}).get(goal)
    if role is None: _bad("실험 지표와 승인 계획의 목표가 다릅니다")
    return role


def bind_protocol(document, plan_view, catalog, now, *, approve=False, registered_at=None):
    doc, plan, now = normalize_protocol(document), _plan(plan_view), moment(now)
    if not isinstance(catalog, dict) or catalog.get("status") != "ready" or not catalog.get("scope") or not _HEX.fullmatch(catalog.get("source_fingerprint") or ""): _bad("현재 대상 관측이 필요합니다")
    if moment(catalog["scope"]["generation"]) > now: _bad()
    role = _role(plan["goal"], doc["goal"])
    if doc["measurement_lag_days"] is not None and doc["measurement_lag_days"] != plan["measurement_lag_days"]: _bad("측정 대기는 승인 운영 기준과 같아야 합니다")
    arms, baseline = {}, {}
    for name in ("control", "treatment"):
        key = doc[name+"_key"]
        if key is not None:
            if key not in catalog["_arms"]: _bad("대상이 바뀌었습니다. 현재 목록에서 다시 선택해 주세요")
            arms[name] = normalize_arm(catalog["_arms"][key], catalog["scope"]["customer_id"])
            baseline[name] = deepcopy(catalog["_baseline"][key])
        else: arms[name], baseline[name] = None, None
    if all(arms.values()) and (arms["control"]["kind"] != arms["treatment"]["kind"] or arms["control"]["id"] == arms["treatment"]["id"]): _bad("서로 다른 같은 종류 대상만 비교할 수 있습니다")
    if doc["period_start"] is not None and doc["period_start"] < plan["period_start"]: _bad("승인 운영 기간을 벗어났습니다")
    if doc["period_end"] is not None and doc["period_end"] > plan["period_end"]: _bad("승인 운영 기간을 벗어났습니다")
    if doc["period_start"] and doc["period_end"] and (_day(doc["period_end"])-_day(doc["period_start"])).days+1 > plan["experiment_days"]: _bad("승인된 실험 기간 상한을 넘었습니다")
    if doc["experiment_spend_cap"] is not None and doc["experiment_spend_cap"] > plan["loss_cap"]: _bad("승인된 실험 광고비 위험 한도를 넘었습니다")
    if all(doc[name] is not None for name in ("control_daily_cap", "treatment_daily_cap")) and doc["control_daily_cap"]+doc["treatment_daily_cap"] > plan["daily_spend_cap"]: _bad("두 군의 하루 상한 합이 계정 상한을 넘었습니다")
    criteria = {**plan, "plan_goal": plan["goal"], "metric_role": role}
    stable_scope = {key: value for key, value in catalog["scope"].items() if key != "generation"}
    bound = dict(version=1, document=doc, scope=deepcopy(catalog["scope"]), plan_version=plan_view["version"],
        source_fingerprint=fingerprint([stable_scope, arms]), arms=arms, baseline=baseline, criteria=criteria)
    if doc["method"] == OI.METHOD:
        parents = dict(campaign=None, adgroup=None)
        selected = [arm for arm in arms.values() if arm is not None]
        if selected:
            if (any(arm["kind"] != "ad" for arm in selected)
                    or len({(arm["parent_id"], arm["campaign_id"]) for arm in selected}) != 1):
                _bad("탐색 비교는 같은 광고 그룹의 서로 다른 동일 유형 광고를 선택해 주세요")
            first = selected[0]
            for kind, identifier in (("campaign", first["campaign_id"]), ("adgroup", first["parent_id"])):
                matches = [arm for arm in catalog["_arms"].values() if arm["kind"] == kind and arm["id"] == identifier]
                if len(matches) != 1: _bad("현재 부모 캠페인·광고 그룹 관측이 필요합니다")
                parents[kind] = normalize_arm(matches[0], catalog["scope"]["customer_id"])
            if any(not isinstance(arm["settings"].get("type"), str) or not arm["settings"]["type"] for arm in selected):
                _bad("광고 유형의 실제 관측이 필요합니다")
            if len(selected) == 2 and selected[0]["settings"].get("type") != selected[1]["settings"].get("type"):
                _bad("같은 유형 광고만 탐색 비교할 수 있습니다")
        bound.update(version=2, parents=parents, source_fingerprint=fingerprint([stable_scope, arms, parents]))
    if approve:
        required = DOCUMENT_FIELDS-{"schema_version", "mde_percent", "sample_share", "declared_control_sample", "declared_treatment_sample"}
        if any(doc[name] is None or doc[name] == "" for name in required): _bad("대상·가설·기간·지표·광고비·측정 기준을 모두 확인해 주세요")
        start, end = _day(doc["period_start"]), _day(doc["period_end"])
        days = (end-start).days+1
        monthly_capacity = sum(row["capacity"] for row in OC._months(start, end, plan["daily_spend_cap"], plan["monthly_spend_cap"]))
        if doc["experiment_spend_cap"] > min(monthly_capacity, days*(doc["control_daily_cap"]+doc["treatment_daily_cap"])): _bad("실험 광고비 상한과 기간·월·두 군 상한을 확인해 주세요")
        if doc["method"] == METHODS[0]:
            registration = moment(registered_at) if registered_at is not None else now
            starts = datetime.combine(start, time(), KST)
            if registration > now or registration >= starts: _bad("조건부 실험 설계는 시작 전에 등록하고 승인해야 합니다")
            if doc["goal"] != "ctr" or any(doc[name] is None for name in ("mde_percent", "sample_share", "declared_control_sample", "declared_treatment_sample")): _bad("지원하는 CTR 검정 방법과 명시 표본·MDE·배분이 필요합니다")
            design = planning(bound, now)
            if design["state"] != "conditional": _bad("조건부 설계의 원천·표본·기간·예산을 확인해 주세요")
        elif doc["method"] == OI.METHOD:
            registration = moment(registered_at) if registered_at is not None else now
            if registration > now or registration >= datetime.combine(start, time(), KST): _bad("탐색 비교도 시작 전에 등록하고 승인해야 합니다")
            if not 28 <= days <= 30: _bad("탐색 비교는 연속 28~30일의 고정 기간이 필요합니다")
            if any(doc[name] is None for name in ("mde_percent", "declared_control_sample", "declared_treatment_sample")):
                _bad("담당자의 관측 차이 기준·양 군 표본을 명시해 주세요")
        elif end >= now.date(): _bad("관측 비교는 끝난 과거 기간을 선택해 주세요")
    return bound


def current_binding(binding, plan_view, catalog, now):
    """Revalidate current selected configuration, retaining approved baseline facts.

    A new inspection generation or another entity's change is not a new
    experimental protocol. Latest unavailable source still blocks this check.
    """
    frozen = validate_binding(binding)
    current = bind_protocol(frozen["document"], plan_view, catalog, now)
    if (frozen["plan_version"] != current["plan_version"] or frozen["criteria"] != current["criteria"]
            or frozen["source_fingerprint"] != current["source_fingerprint"]):
        _bad("현재 승인 계획·대상 설정·소유가 변경되었습니다")
    return True


def validate_binding(binding):
    if not isinstance(binding, dict) or type(binding.get("version")) is not int or binding["version"] not in (1, 2): _bad()
    v2 = binding["version"] == 2
    if set(binding) != _BINDING | ({"parents"} if v2 else set()): _bad()
    if normalize_protocol(binding["document"]) != binding["document"]: _bad()
    if v2 != (binding["document"]["method"] == OI.METHOD): _bad()
    scope = binding["scope"]
    if (not isinstance(scope, dict) or set(scope) != {"possibility_id", "customer_id", "account_key", "stage_revision", "generation"}
            or not _number(scope["possibility_id"], 1, MAX_NUMBER, True) or not _number(scope["customer_id"], 1, MAX_NUMBER, True)
            or not isinstance(scope["account_key"], str) or not _HEX.fullmatch(scope["account_key"])
            or not isinstance(binding["source_fingerprint"], str) or not _HEX.fullmatch(binding["source_fingerprint"])
            or not _number(binding["plan_version"], 1, MAX_NUMBER, True)): _bad()
    moment(scope["generation"]); _text(scope["stage_revision"], 160)
    if (not isinstance(binding["arms"], dict) or not isinstance(binding["baseline"], dict)
            or set(binding["arms"]) != {"control", "treatment"} or set(binding["baseline"]) != {"control", "treatment"}): _bad()
    stable_scope = {key: value for key, value in scope.items() if key != "generation"}
    for name, arm in binding["arms"].items():
        if arm is not None:
            normalize_arm(arm, scope["customer_id"])
            if binding["document"][name+"_key"] != fingerprint(["experiment-candidate-v1", stable_scope, arm]): _bad()
            row = binding["baseline"][name]
            if not isinstance(row, dict): _bad()
            _baseline(row, row["period_start"], row["period_end"])
        elif binding["baseline"][name] is not None or binding["document"][name+"_key"] is not None: _bad()
    a, b = binding["arms"]["control"], binding["arms"]["treatment"]
    if a is not None and b is not None and (a["kind"] != b["kind"] or a["id"] == b["id"]): _bad()
    if not isinstance(binding["criteria"], dict) or set(binding["criteria"]) != OC.V2_FIELDS | {"plan_goal", "metric_role"}: _bad()
    plan = _plan({"state": "approved", "version": binding["plan_version"], "plan": {key: binding["criteria"][key] for key in OC.V2_FIELDS}})
    if binding["criteria"].get("plan_goal") != plan["goal"] or binding["criteria"].get("metric_role") != _role(plan["goal"], binding["document"]["goal"]): _bad()
    proof = [stable_scope, binding["arms"]]
    if v2:
        parents = binding["parents"]
        if not isinstance(parents, dict) or set(parents) != {"campaign", "adgroup"}: _bad()
        for kind, arm in parents.items():
            if arm is not None and (normalize_arm(arm, scope["customer_id"])["kind"] != kind): _bad()
        selected = [arm for arm in binding["arms"].values() if arm is not None]
        if selected:
            if any(arm["kind"] != "ad" for arm in selected) or any(arm is None for arm in parents.values()): _bad()
            campaign, group = parents["campaign"], parents["adgroup"]
            if group["parent_id"] != campaign["id"] or any(arm["parent_id"] != group["id"] or arm["campaign_id"] != campaign["id"] for arm in selected): _bad()
            if any(not isinstance(arm["settings"].get("type"), str) or not arm["settings"]["type"] for arm in selected): _bad()
            if len(selected) == 2 and selected[0]["settings"].get("type") != selected[1]["settings"].get("type"): _bad()
        elif any(arm is not None for arm in parents.values()): _bad()
        proof.append(parents)
    if binding["source_fingerprint"] != fingerprint(proof): _bad()
    return deepcopy(binding)


def planning(binding, now):
    binding, now = validate_binding(binding), moment(now)
    doc, plan = binding["document"], binding["criteria"]
    result = dict(state="hold", reason_codes=[], missing=[], baseline_rate=None, alternative_rate=None,
        required_control_sample=None, required_treatment_sample=None, estimated_days=None, estimated_spend=None,
        estimated_control_spend=None, estimated_treatment_spend=None,
        method=doc["method"], alpha=None, power=None, conditional=True, baseline_history_verified=False,
        cost_basis="platform_salesAmt_vat_included", budget_vat_alignment_verified=False, remaining_balance=None,
        assumptions=["독립 Bernoulli 표본을 가정한 설계 추정", "실제 무작위 배정·고정 기간 필요", "과거 기간 전체 설정 동일성 미확인", "각 군의 기존 노출량·단가 유지 가정, 실제 트래픽 재배분 미확인", "미래 노출·단가·집행·성과를 보장하지 않음"])
    reasons = result["reason_codes"]
    if doc["method"] == OI.METHOD:
        result.update(state="exploratory", conditional=False, reason_codes=["EXPLORATORY_UNCALIBRATED_METHOD"],
            assumptions=["탐색적 운영 휴리스틱이며 통계 보증·인과 승자 판정이 아님", "연속 28~30일 실제 자료·매일 관련 설정 관측 필요",
                         "상대 관측 차이 기준과 명시 표본·기간·광고비를 승인 전에 정함", "진단 밴드는 paired HAC SE의 3배이며 보정된 신뢰구간이 아님"])
        return result
    if doc["method"] == METHODS[1]:
        result.update(state="observation_only", reason_codes=["OBSERVATIONAL_METHOD"])
        return result
    if doc["method"] != METHODS[0]: result["missing"].append("method")
    if doc["goal"] != "ctr": reasons.append("CTR_DESIGN_ONLY")
    for name in ("mde_percent", "sample_share", "declared_control_sample", "declared_treatment_sample", "period_start", "period_end", "experiment_spend_cap", "control_daily_cap", "treatment_daily_cap"):
        if doc[name] is None: result["missing"].append(name)
    base = binding["baseline"].get("control")
    good = _baseline_ready(base, now, ("impCnt", "clkCnt"))
    if not good: reasons.append("BASELINE_UNAVAILABLE")
    elif base["fields"]["impCnt"] <= 0 or not 0 < base["fields"]["clkCnt"] < base["fields"]["impCnt"]: reasons.append("BASELINE_RATE_INVALID")
    if result["missing"] or reasons: return result
    p0 = base["fields"]["clkCnt"]/base["fields"]["impCnt"]
    p1 = p0*(1+doc["mde_percent"]/100)
    result.update(baseline_rate=p0, alternative_rate=p1, alpha=.05, power=.8)
    if not p0 < p1 < 1: reasons.append("ALTERNATIVE_RATE_INVALID"); return result
    r = (1-doc["sample_share"])/doc["sample_share"]
    pooled = (p0+r*p1)/(1+r)
    raw = (1.959963984540054*math.sqrt(pooled*(1-pooled)*(1+1/r)) +
           .8416212335729143*math.sqrt(p0*(1-p0)+p1*(1-p1)/r))**2/(p1-p0)**2
    if not math.isfinite(raw) or raw > 10**9 or raw*r > 10**9: reasons.append("SAMPLE_OUT_OF_RANGE"); return result
    n0, n1 = math.ceil(raw), math.ceil(math.ceil(raw)*r)
    result.update(required_control_sample=n0, required_treatment_sample=n1)
    if doc["declared_control_sample"] < n0 or doc["declared_treatment_sample"] < n1: reasons.append("DECLARED_SAMPLE_TOO_SMALL")
    treatment = binding["baseline"].get("treatment")
    if _baseline_ready(treatment, now, ("impCnt",)) and treatment["period_start"] == base["period_start"] and treatment["period_end"] == base["period_end"]:
        days = (_day(base["period_end"])-_day(base["period_start"])).days+1
        target0, target1 = max(n0, doc["declared_control_sample"]), max(n1, doc["declared_treatment_sample"])
        if base["fields"]["impCnt"] > 0 and treatment["fields"]["impCnt"] > 0:
            volume_days = max(math.ceil(target0*days/base["fields"]["impCnt"]), math.ceil(target1*days/treatment["fields"]["impCnt"]))
            result["estimated_days"] = volume_days
            estimate0 = None if base["fields"]["salesAmt"] is None else target0*base["fields"]["salesAmt"]/base["fields"]["impCnt"]
            estimate1 = None if treatment["fields"]["salesAmt"] is None else target1*treatment["fields"]["salesAmt"]/treatment["fields"]["impCnt"]
            if _number(estimate0) and _number(estimate1) and _number(estimate0+estimate1):
                result.update(estimated_control_spend=estimate0, estimated_treatment_spend=estimate1, estimated_spend=estimate0+estimate1)
                horizon = (_day(doc["period_end"])-_day(doc["period_start"])).days+1
                for name, estimate in (("control", estimate0), ("treatment", estimate1)):
                    cap = doc[name+"_daily_cap"]
                    if estimate > cap*horizon: reasons.append(name.upper()+"_DAILY_CAP_INSUFFICIENT")
                    budget_days = estimate/cap
                    if math.isfinite(budget_days) and budget_days <= MAX_NUMBER:
                        result["estimated_days"] = max(result["estimated_days"], math.ceil(budget_days))
                    else: reasons.append("BUDGET_HORIZON_OUT_OF_RANGE")
    if result["estimated_days"] is None: reasons.append("VOLUME_ESTIMATE_UNAVAILABLE")
    elif result["estimated_days"] > (_day(doc["period_end"])-_day(doc["period_start"])).days+1: reasons.append("ESTIMATED_HORIZON_EXCEEDS_PLAN")
    if result["estimated_spend"] is None: reasons.append("COST_ESTIMATE_UNAVAILABLE")
    elif result["estimated_spend"] > doc["experiment_spend_cap"]: reasons.append("ESTIMATED_SPEND_EXCEEDS_CAP")
    if not reasons: result["state"] = "conditional"
    return result


def _baseline_ready(row, now, required_fields=FIELDS):
    if not isinstance(row, dict) or row.get("missing") is not False: return False
    try:
        start, end = _day(row["period_start"]), _day(row["period_end"])
        source, checked = moment(row["source_at"]), moment(row["checked_at"])
        return (0 <= (end-start).days <= 30 and end < now.date() and source.date() > end and source <= checked <= now
                and all(row["fields"][key] is not None for key in required_fields))
    except (KeyError, TypeError, ValueError, OverflowError): return False


def normalize_snapshot(value, binding, now):
    binding, now = validate_binding(binding), moment(now)
    v2 = binding["version"] == 2
    if (not isinstance(value, dict) or set(value) != SNAPSHOT_FIELDS | ({"daily", "stability"} if v2 else set())
            or type(value["version"]) is not int or value["version"] != binding["version"]
            or value["status"] not in ("ok", "pending", "partial", "failed", "stale", "unavailable")
            or value["source_fingerprint"] != binding["source_fingerprint"]
            or (value["period_start"], value["period_end"]) != (binding["document"]["period_start"], binding["document"]["period_end"])
            or type(value["configuration_verified"]) is not bool or not isinstance(value["arms"], dict)
            or set(value["arms"]) != {"control", "treatment"}): _bad()
    if value["checked_at"] is not None and moment(value["checked_at"]) > now: _bad()
    if v2:
        daily = value["daily"]
        if not isinstance(daily, list) or len(daily) > 30: _bad()
        seen = []
        for day in daily:
            if not isinstance(day, dict) or set(day) != {"day", "control", "treatment"}: _bad()
            _day(day["day"])
            if not value["period_start"] <= day["day"] <= value["period_end"]: _bad()
            for arm in ("control", "treatment"):
                if not isinstance(day[arm], dict) or set(day[arm]) != _ROW: _bad()
                _fields(day[arm]["fields"])
            seen.append(day["day"])
        if seen != sorted(set(seen)): _bad()
        normalize_stability(value["stability"], value["period_start"], value["period_end"], now)
        for arm in ("control", "treatment"):
            for field in FIELDS:
                parts = [day[arm]["fields"][field] for day in daily]
                expected = None if len(parts) != len(daily) or not daily or any(v is None for v in parts) else math.fsum(parts)
                if value["arms"].get(arm) is not None and value["arms"][arm]["fields"][field] != expected: _bad()
    all_rows = list(value["arms"].values()) + ([day[arm] for day in value["daily"] for arm in ("control", "treatment")] if v2 else [])
    for row in all_rows:
        if row is None: continue
        if not isinstance(row, dict) or set(row) != _ROW or type(row["complete"]) is not bool or type(row["missing"]) is not bool: _bad()
        _fields(row["fields"])
        if row["missing"] and (row["complete"] or any(number is not None for number in row["fields"].values())): _bad()
        if row["checked_at"] is None or moment(row["checked_at"]) > now: _bad()
        if row["source_at"] is not None and moment(row["source_at"]) > moment(row["checked_at"]): _bad()
        if row["complete"] and (row["source_at"] is None or moment(row["source_at"]).date() <= _day(value["period_end"]) or any(number is None for number in row["fields"].values())): _bad()
    return deepcopy(value)


def normalize_stability(value, start, end, now):
    if (not isinstance(value, dict) or set(value) != STABILITY_FIELDS or value["qualifier"] != "observed_stability"
            or type(value["drift"]) is not bool or type(value["coverage_complete"]) is not bool
            or value["limitations"] != list(STABILITY_LIMITATIONS)): _bad()
    expected = [(_day(start)+timedelta(days=i)).isoformat() for i in range((_day(end)-_day(start)).days+1)]
    if value["expected_days"] != expected: _bad()
    observed = value["observed_days"]
    if not isinstance(observed, list) or any(not isinstance(day, str) for day in observed) or observed != sorted(set(observed)) or not set(observed) <= set(expected): _bad()
    if value["missing_days"] != sorted(set(expected)-set(observed)) or value["coverage_complete"] != (not value["missing_days"] and not value["drift"]): _bad()
    first, last = value["first_checked_at"], value["last_checked_at"]
    if observed:
        if first is None or last is None or not moment(first) <= moment(last) <= moment(now): _bad()
        if moment(first).date().isoformat() != observed[0] or moment(last).date().isoformat() != observed[-1]: _bad()
    elif first is not None or last is not None: _bad()
    return deepcopy(value)


def _ratios(fields, criteria):
    def ratio(n, d, factor=1):
        if fields[n] is None or fields[d] in (None, 0): return None
        value = fields[n]/fields[d]*factor
        return value if _number(value) else None
    conversion = criteria["conversion_definition"] == "platform"
    value = conversion and criteria["value_basis"] == "platform_conversion_value"
    return dict(ctr=ratio("clkCnt", "impCnt", 100), cpc=ratio("salesAmt", "clkCnt"),
                cvr=ratio("ccnt", "clkCnt", 100) if conversion else None,
                cpa=ratio("salesAmt", "ccnt") if conversion else None,
                roas=ratio("convAmt", "salesAmt", 100) if value else None)


def assess(binding, snapshot, now, *, approved_at=None, current_plan=None, current_source_fingerprint=None):
    binding, now = validate_binding(binding), moment(now)
    if binding["version"] == 2:
        return _assess_exploratory(binding, snapshot, now, approved_at=approved_at, current_plan=current_plan,
                                   current_source_fingerprint=current_source_fingerprint)
    doc, criteria = binding["document"], binding["criteria"]
    reasons = ["ASSIGNMENT_PROOF_UNAVAILABLE", "EXECUTION_NOT_CONNECTED"]
    out = dict(outcome="hold", winner=None, causal_claim=False, randomized=False, preregistered=False,
        metric_role=criteria["metric_role"], plan_goal=criteria["plan_goal"], goal=doc["goal"],
        conversion_definition=criteria["conversion_definition"], value_basis=criteria["value_basis"],
        reason_codes=reasons, arms={"control": None, "treatment": None}, differences=None,
        checked_at=None, period_start=doc["period_start"], period_end=doc["period_end"],
        planning=planning(binding, now), stopped_for_spend=False, measurement_confirmed=False,
        attribution_final=False, history_verified=False, execution_enabled=False)
    if current_plan is not None:
        if current_plan.get("version") != binding["plan_version"] or current_plan.get("state") != "approved" or _plan(current_plan) != {key: criteria[key] for key in OC.V2_FIELDS}:
            reasons.append("PLAN_CHANGED"); return out
    if current_source_fingerprint is not None and current_source_fingerprint != binding["source_fingerprint"]:
        reasons.append("SOURCE_CHANGED"); return out
    if approved_at is None: reasons.append("NOT_APPROVED"); return out
    approved = moment(approved_at)
    if approved > now: _bad()
    if doc["method"] == METHODS[0] and doc["period_start"]:
        out["preregistered"] = approved < datetime.combine(_day(doc["period_start"]), time(), KST)
        if not out["preregistered"]: reasons.append("NOT_PREREGISTERED")
    if snapshot is None: reasons.append("SOURCE_UNAVAILABLE"); return out
    snapshot = normalize_snapshot(snapshot, binding, now)
    if snapshot["status"] not in ("ok", "partial") or snapshot["configuration_verified"] is not True:
        reasons.append("SOURCE_"+snapshot["status"].upper()); return out
    out["checked_at"] = snapshot["checked_at"]
    if any(row is None for row in snapshot["arms"].values()): reasons.append("PARTIAL_METRICS"); return out
    rows = snapshot["arms"]
    for name, row in rows.items():
        out["arms"][name] = dict(fields=deepcopy(row["fields"]), metrics=dict.fromkeys(("ctr", "cpc", "cvr", "cpa", "roas")))
    if any(row["source_at"] is None for row in rows.values()): reasons.append("SOURCE_CYCLE_UNAVAILABLE"); return out
    cycles = {moment(row["source_at"]) for row in rows.values()}
    if len(cycles) != 1: reasons.append("SOURCE_CYCLE_MISMATCH"); return out
    if any(moment(row["source_at"]).date() <= _day(doc["period_end"]) for row in rows.values()): reasons.append("SOURCE_CYCLE_BEHIND"); return out
    if snapshot["status"] == "partial" or any(not row["complete"] for row in rows.values()): reasons.append("PARTIAL_METRICS")
    for name, row in rows.items(): out["arms"][name]["metrics"] = _ratios(row["fields"], criteria)
    out["outcome"] = "observation"
    goal = doc["goal"]
    a, b = (out["arms"][name]["metrics"].get(goal) for name in ("control", "treatment"))
    if a is not None and b is not None:
        relative = None if a == 0 else (b/a-1)*100
        absolute = b-a
        out["differences"] = dict(absolute=absolute if math.isfinite(absolute) and abs(absolute) <= MAX_NUMBER else None,
                                 relative_percent=relative if relative is not None and math.isfinite(relative) and abs(relative) <= MAX_NUMBER else None)
    else: reasons.append("GOAL_METRIC_UNAVAILABLE")
    if criteria["conversion_definition"] != "platform" and goal in ("cvr", "cpa", "roas"): reasons.append("CONVERSION_DEFINITION_MISMATCH")
    if goal == "roas" and criteria["value_basis"] != "platform_conversion_value": reasons.append("VALUE_BASIS_MISMATCH")
    if doc["period_end"] is not None:
        if doc["measurement_lag_days"] is None: reasons.append("MEASUREMENT_LAG_UNDEFINED")
        else:
            mature = _day(doc["period_end"])+timedelta(days=1+doc["measurement_lag_days"])
            if now.date() < mature: reasons.append("MEASUREMENT_LAG_NOT_MATURE")
    if doc["method"] == METHODS[0] and doc["period_end"] and now.date() <= _day(doc["period_end"]): reasons.append("HORIZON_NOT_COMPLETE")
    for name in ("control", "treatment"):
        required = doc["declared_"+name+"_sample"]
        denominator = out["arms"][name]["fields"]["impCnt" if goal == "ctr" else "clkCnt"]
        if required is not None and (denominator is None or denominator < required): reasons.append(name.upper()+"_SAMPLE_BELOW_PLAN")
    spend = None if any(row["fields"]["salesAmt"] is None for row in rows.values()) else sum(row["fields"]["salesAmt"] for row in rows.values())
    if doc["experiment_spend_cap"] is not None and spend is not None and spend >= doc["experiment_spend_cap"]:
        out["stopped_for_spend"] = True; reasons.append("OBSERVED_SPEND_AT_CAP_NO_AD_STOP")
    if goal in ("cpa", "roas"): reasons.append("VARIANCE_UNAVAILABLE")
    return out


def _assess_exploratory(binding, snapshot, now, *, approved_at, current_plan, current_source_fingerprint):
    doc, criteria = binding["document"], binding["criteria"]
    if snapshot is not None: snapshot = normalize_snapshot(snapshot, binding, now)
    diagnostic = OI.assess(binding, snapshot, now, approved_at=approved_at, current_plan=current_plan,
                           current_source_fingerprint=current_source_fingerprint)
    if current_plan is not None and (current_plan.get("state") != "approved"
            or _plan(current_plan) != {key: criteria[key] for key in OC.V2_FIELDS}):
        diagnostic = OI.empty_decision(doc["mde_percent"]); diagnostic["reason_codes"] = ["PLAN_CHANGED"]
    display_current = (snapshot is not None and snapshot["status"] in ("ok", "partial")
                       and not set(diagnostic["reason_codes"]) & {"PLAN_CHANGED", "SOURCE_CHANGED", "NOT_APPROVED"})
    out = dict(outcome="observation" if display_current else "hold",
        winner=None, causal_claim=False, randomized=False, preregistered=diagnostic["preregistered"],
        metric_role=criteria["metric_role"], plan_goal=criteria["plan_goal"], goal=doc["goal"],
        conversion_definition=criteria["conversion_definition"], value_basis=criteria["value_basis"],
        reason_codes=["ASSIGNMENT_PROOF_UNAVAILABLE", "EXECUTION_NOT_CONNECTED"]+diagnostic["reason_codes"],
        arms={"control": None, "treatment": None}, differences=None, checked_at=snapshot["checked_at"] if display_current else None,
        period_start=doc["period_start"], period_end=doc["period_end"], planning=planning(binding, now),
        stopped_for_spend="OBSERVED_SPEND_AT_CAP_NO_AD_STOP" in diagnostic["reason_codes"], measurement_confirmed=False,
        attribution_final=False, history_verified=False, execution_enabled=False, observational_decision=diagnostic)
    if display_current:
        for arm, row in snapshot["arms"].items():
            if row is not None: out["arms"][arm] = dict(fields=deepcopy(row["fields"]), metrics=_ratios(row["fields"], criteria))
    return out
