"""Exploratory paired-day diagnostic, never a calibrated statistical test.

The 28-day floor, lag seven, multiplier three, and four-block consistency
rule are explicit product heuristics. They do not establish coverage,
equivalence, random assignment, or a causal advertising winner.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import math

METHOD = "exploratory_paired_day_hac_v1"
MAX_NUMBER = 9007199254740991
FIELDS = ("impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt")
DECISION_FIELDS = frozenset({"version", "method", "evidence_grade", "decision", "recommended_arm", "winner",
    "causal_claim", "randomized", "formal_equivalence", "calibration_verified", "calibration", "effect_percent",
    "margin_percent", "band", "standard_error_percent", "paired_days", "bandwidth", "band_multiplier",
    "complete_week_blocks", "remainder_days", "preregistered", "reason_codes", "qualifiers"})
QUALIFIERS = ("exploratory_policy_not_calibrated", "observed_settings_not_full_history", "no_random_assignment",
    "general_platform_events_not_orders", "vat_basis_not_commerce_profit", "residual_days_in_full_estimate")
REASONS = frozenset({"NOT_APPROVED", "NOT_PREREGISTERED", "PLAN_CHANGED", "SOURCE_CHANGED", "SOURCE_UNAVAILABLE",
    "SOURCE_NOT_CURRENT", "SETTINGS_NOT_OBSERVED", "SETTINGS_DRIFT", "DAILY_COVERAGE_INCOMPLETE", "HORIZON_NOT_COMPLETE",
    "MEASUREMENT_LAG_UNDEFINED", "MEASUREMENT_LAG_NOT_MATURE", "SOURCE_CYCLE_UNAVAILABLE", "SOURCE_CYCLE_MISMATCH",
    "SOURCE_CYCLE_BEHIND", "CONVERSION_DEFINITION_MISMATCH", "VALUE_BASIS_MISMATCH", "MATERIAL_MARGIN_UNDEFINED",
    "SAMPLE_UNDEFINED", "CONTROL_SAMPLE_BELOW_PLAN", "TREATMENT_SAMPLE_BELOW_PLAN", "CONTROL_CLICKS_BELOW_PLAN",
    "TREATMENT_CLICKS_BELOW_PLAN", "CONTROL_CONVERSIONS_BELOW_PLAN", "TREATMENT_CONVERSIONS_BELOW_PLAN",
    "SPEND_UNAVAILABLE", "OBSERVED_SPEND_AT_CAP_NO_AD_STOP", "CONTROL_DAILY_CAP_EXCEEDED", "TREATMENT_DAILY_CAP_EXCEEDED",
    "REQUIRED_METRIC_UNAVAILABLE", "DENOMINATOR_UNAVAILABLE", "CONTROL_REFERENCE_UNAVAILABLE", "NONFINITE_DIAGNOSTIC",
    "ZERO_VARIANCE", "WEEK_BLOCK_UNAVAILABLE", "DIAGNOSTIC_AND_BLOCKS_INCONCLUSIVE"})
_RATIOS = {"ctr": ("clkCnt", "impCnt", 1), "cvr": ("ccnt", "clkCnt", 1),
           "cpa": ("salesAmt", "ccnt", -1), "roas": ("convAmt", "salesAmt", 1)}
KST = timezone(timedelta(hours=9))


class DiagnosticInvalid(ValueError):
    pass


def _number(value, *, signed=False, integer=False):
    return (type(value) in ((int,) if integer else (int, float))
            and (-MAX_NUMBER if signed else 0) <= value <= MAX_NUMBER and math.isfinite(value))


def _at(value):
    at = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(at, datetime) or at.utcoffset() is None: raise DiagnosticInvalid("시각 확인 필요")
    return at.astimezone(KST)


def required_fields(goal, minimum_conversions=None):
    if goal not in _RATIOS: raise DiagnosticInvalid("지표 확인 필요")
    n, d, _ = _RATIOS[goal]
    needed = {n, d, "salesAmt", "clkCnt"}
    if minimum_conversions is not None: needed.add("ccnt")
    return tuple(field for field in FIELDS if field in needed)


def empty_decision(margin=None):
    return dict(version=1, method=METHOD, evidence_grade="exploratory", decision="hold", recommended_arm=None,
        winner=None, causal_claim=False, randomized=False, formal_equivalence=False, calibration_verified=False,
        calibration="unvalidated_diagnostic", effect_percent=None, margin_percent=margin, band=None,
        standard_error_percent=None, paired_days=0, bandwidth=7, band_multiplier=3, complete_week_blocks=0,
        remainder_days=0, preregistered=False, reason_codes=[], qualifiers=list(QUALIFIERS[:3]))


def normalize_decision(value):
    """Closed, finite public facts. Never accepts promoted confidence claims."""
    if not isinstance(value, dict) or set(value) != DECISION_FIELDS: raise DiagnosticInvalid("진단 항목 확인 필요")
    if (type(value["version"]) is not int or value["version"] != 1 or value["method"] != METHOD
            or value["evidence_grade"] != "exploratory" or value["calibration"] != "unvalidated_diagnostic"
            or value["winner"] is not None or any(value[key] is not False for key in
                ("causal_claim", "randomized", "formal_equivalence", "calibration_verified"))
            or type(value["preregistered"]) is not bool
            or type(value["bandwidth"]) is not int or value["bandwidth"] != 7
            or type(value["band_multiplier"]) is not int or value["band_multiplier"] != 3):
        raise DiagnosticInvalid("진단 의미 확인 필요")
    for key, upper in (("paired_days", 30), ("complete_week_blocks", 4), ("remainder_days", 2)):
        if not _number(value[key], integer=True) or value[key] > upper: raise DiagnosticInvalid("진단 날짜 확인 필요")
    for key in ("effect_percent", "margin_percent", "standard_error_percent"):
        if value[key] is not None and not _number(value[key], signed=key == "effect_percent"): raise DiagnosticInvalid("진단 수치 확인 필요")
    if value["margin_percent"] is not None and not 0 < value["margin_percent"] <= 100: raise DiagnosticInvalid("관측 기준 확인 필요")
    band = value["band"]
    if band is not None and (not isinstance(band, dict) or set(band) != {"lower_percent", "upper_percent"}
            or any(not _number(v, signed=True) for v in band.values()) or band["lower_percent"] > band["upper_percent"]):
        raise DiagnosticInvalid("진단 밴드 확인 필요")
    for key, allowed in (("reason_codes", REASONS), ("qualifiers", QUALIFIERS)):
        if (not isinstance(value[key], list) or len(value[key]) > len(allowed)
                or any(not isinstance(v, str) or v not in allowed for v in value[key])
                or len(set(value[key])) != len(value[key])): raise DiagnosticInvalid("진단 설명 확인 필요")
    if not set(QUALIFIERS[:3]) <= set(value["qualifiers"]): raise DiagnosticInvalid("진단 한계 확인 필요")
    decision = value["decision"]
    if not isinstance(decision, str) or decision not in ("hold", "inconclusive", "conditional_preference", "within_material_margin"):
        raise DiagnosticInvalid("진단 상태 확인 필요")
    if decision == "conditional_preference":
        if value["recommended_arm"] not in ("control", "treatment"): raise DiagnosticInvalid("추천 대상 확인 필요")
    elif value["recommended_arm"] is not None: raise DiagnosticInvalid("추천 대상 확인 필요")
    if decision != "hold":
        if (value["paired_days"] < 28 or value["complete_week_blocks"] != 4
                or value["remainder_days"] != value["paired_days"]-28 or not value["preregistered"]
                or band is None or any(value[key] is None for key in ("effect_percent", "margin_percent", "standard_error_percent"))
                or value["standard_error_percent"] <= 0): raise DiagnosticInvalid("진단 완결 확인 필요")
        if value["reason_codes"] != (["DIAGNOSTIC_AND_BLOCKS_INCONCLUSIVE"] if decision == "inconclusive" else []):
            raise DiagnosticInvalid("진단 자격 확인 필요")
        expected = (value["effect_percent"]-3*value["standard_error_percent"], value["effect_percent"]+3*value["standard_error_percent"])
        if not (math.isclose(band["lower_percent"], expected[0], rel_tol=1e-12, abs_tol=1e-12)
                and math.isclose(band["upper_percent"], expected[1], rel_tol=1e-12, abs_tol=1e-12)): raise DiagnosticInvalid("진단 밴드 일치 확인 필요")
        margin = value["margin_percent"]
        if decision == "conditional_preference":
            if not (band["lower_percent"] > margin if value["recommended_arm"] == "treatment" else band["upper_percent"] < -margin):
                raise DiagnosticInvalid("추천 기준 확인 필요")
        if decision == "within_material_margin" and not -margin < band["lower_percent"] <= band["upper_percent"] < margin:
            raise DiagnosticInvalid("관측 차이 기준 확인 필요")
    return deepcopy(value)


def _effect(rows, goal):
    n, d, sign = _RATIOS[goal]
    totals = {arm: (math.fsum(row[arm]["fields"][n] for row in rows), math.fsum(row[arm]["fields"][d] for row in rows))
              for arm in ("control", "treatment")}
    if any(not _number(v) for pair in totals.values() for v in pair): raise ArithmeticError("NONFINITE_DIAGNOSTIC")
    if any(pair[1] <= 0 for pair in totals.values()): raise ArithmeticError("DENOMINATOR_UNAVAILABLE")
    rates = {arm: pair[0]/pair[1] for arm, pair in totals.items()}
    if not _number(rates["control"]) or rates["control"] <= 0: raise ArithmeticError("CONTROL_REFERENCE_UNAVAILABLE")
    if not _number(rates["treatment"]): raise ArithmeticError("NONFINITE_DIAGNOSTIC")
    effect = 100*sign*(rates["treatment"]/rates["control"]-1)
    if not _number(effect, signed=True): raise ArithmeticError("NONFINITE_DIAGNOSTIC")
    return effect, rates, totals


def assess(binding, snapshot, now, *, approved_at=None, current_plan=None, current_source_fingerprint=None):
    """Caller validates frozen binding/snapshot; all eligibility remains fail closed."""
    doc, criteria = binding["document"], binding["criteria"]
    out = empty_decision(doc["mde_percent"])
    reasons = out["reason_codes"]
    def hold(code):
        if code not in reasons: reasons.append(code)
        return normalize_decision(out)
    now = _at(now)
    if current_plan is not None and (current_plan.get("state") != "approved" or current_plan.get("version") != binding["plan_version"]): return hold("PLAN_CHANGED")
    if current_source_fingerprint is not None and current_source_fingerprint != binding["source_fingerprint"]: return hold("SOURCE_CHANGED")
    if approved_at is None: return hold("NOT_APPROVED")
    start, end = date.fromisoformat(doc["period_start"]), date.fromisoformat(doc["period_end"])
    out["preregistered"] = _at(approved_at) < datetime.combine(start, time(), KST) and _at(approved_at) <= now
    if not out["preregistered"]: return hold("NOT_PREREGISTERED")
    if now.date() <= end: return hold("HORIZON_NOT_COMPLETE")
    lag = doc["measurement_lag_days"]
    if lag is None: return hold("MEASUREMENT_LAG_UNDEFINED")
    if now.date() < end+timedelta(days=1+lag): return hold("MEASUREMENT_LAG_NOT_MATURE")
    margin = doc["mde_percent"]
    if margin is None: return hold("MATERIAL_MARGIN_UNDEFINED")
    if any(doc["declared_"+arm+"_sample"] is None for arm in ("control", "treatment")): return hold("SAMPLE_UNDEFINED")
    goal = doc["goal"]
    if goal in ("cvr", "cpa", "roas"):
        out["qualifiers"].append("general_platform_events_not_orders")
        if criteria["conversion_definition"] not in ("platform", "platform_all_conversions"): return hold("CONVERSION_DEFINITION_MISMATCH")
    if goal == "roas":
        out["qualifiers"].append("vat_basis_not_commerce_profit")
        if criteria["value_basis"] != "platform_conversion_value": return hold("VALUE_BASIS_MISMATCH")
    if snapshot is None: return hold("SOURCE_UNAVAILABLE")
    if snapshot["status"] not in ("ok", "partial") or not snapshot["configuration_verified"]: return hold("SOURCE_NOT_CURRENT")
    stability = snapshot["stability"]
    if stability["drift"]: return hold("SETTINGS_DRIFT")
    if not stability["coverage_complete"]: return hold("SETTINGS_NOT_OBSERVED")
    days = (end-start).days+1
    expected = [(start+timedelta(days=i)).isoformat() for i in range(days)]
    rows = snapshot["daily"]
    if not 28 <= days <= 30 or [row["day"] for row in rows] != expected: return hold("DAILY_COVERAGE_INCOMPLETE")
    out["paired_days"], out["remainder_days"] = days, days-28
    if days > 28: out["qualifiers"].append("residual_days_in_full_estimate")
    required = required_fields(goal, criteria["minimum_conversions"])
    cycles = set()
    for row in rows:
        for arm in ("control", "treatment"):
            record = row[arm]
            if record["missing"] or any(record["fields"][key] is None for key in required): return hold("REQUIRED_METRIC_UNAVAILABLE")
            if record["source_at"] is None: return hold("SOURCE_CYCLE_UNAVAILABLE")
            at = _at(record["source_at"])
            if at.date() < end+timedelta(days=1+lag): return hold("SOURCE_CYCLE_BEHIND")
            cycles.add(at)
            cap = doc[arm+"_daily_cap"]
            if cap is None or record["fields"]["salesAmt"] > cap: return hold(arm.upper()+"_DAILY_CAP_EXCEEDED")
    if len(cycles) != 1: return hold("SOURCE_CYCLE_MISMATCH")
    for arm in ("control", "treatment"):
        totals = {key: math.fsum(row[arm]["fields"][key] for row in rows) for key in required}
        sample_key = "impCnt" if goal == "ctr" else "clkCnt"
        if totals[sample_key] < doc["declared_"+arm+"_sample"]: return hold(arm.upper()+"_SAMPLE_BELOW_PLAN")
        if criteria["minimum_clicks"] is None or totals["clkCnt"] < criteria["minimum_clicks"]: return hold(arm.upper()+"_CLICKS_BELOW_PLAN")
        if criteria["minimum_conversions"] is not None and totals["ccnt"] < criteria["minimum_conversions"]: return hold(arm.upper()+"_CONVERSIONS_BELOW_PLAN")
    spend = math.fsum(row[arm]["fields"]["salesAmt"] for row in rows for arm in ("control", "treatment"))
    if not _number(spend) or doc["experiment_spend_cap"] is None: return hold("SPEND_UNAVAILABLE")
    if spend >= doc["experiment_spend_cap"]: return hold("OBSERVED_SPEND_AT_CAP_NO_AD_STOP")
    try:
        effect, rates, totals = _effect(rows, goal)
        n, d, sign = _RATIOS[goal]
        rc, rt = rates["control"], rates["treatment"]
        influence = []
        for row in rows:
            # Algebra avoids an unnecessary squared tiny control denominator.
            gc = (row["control"]["fields"][n]-rc*row["control"]["fields"][d])/(totals["control"][1]/days)
            gt = (row["treatment"]["fields"][n]-rt*row["treatment"]["fields"][d])/(totals["treatment"][1]/days)
            influence.append(100*sign*(gt/rc-(rt/rc)*(gc/rc)))
        if any(not _number(v, signed=True) for v in influence): return hold("NONFINITE_DIAGNOSTIC")
        mean = math.fsum(influence)/days
        u = [v-mean for v in influence]
        variance = (math.fsum(v*v for v in u)+2*math.fsum((1-k/8)*math.fsum(u[t]*u[t-k] for t in range(k, days)) for k in range(1, 8)))/(days*days)
        if not math.isfinite(variance) or variance < 0: return hold("NONFINITE_DIAGNOSTIC")
        if variance == 0: return hold("ZERO_VARIANCE")
        se = math.sqrt(variance)
        band = dict(lower_percent=effect-3*se, upper_percent=effect+3*se)
        if not _number(se) or any(not _number(v, signed=True) for v in band.values()): return hold("NONFINITE_DIAGNOSTIC")
        blocks = [_effect(rows[i:i+7], goal)[0] for i in range(0, 28, 7)]
        out.update(effect_percent=effect, standard_error_percent=se, band=band, complete_week_blocks=len(blocks))
        if band["lower_percent"] > margin and all(v > margin for v in blocks): out.update(decision="conditional_preference", recommended_arm="treatment")
        elif band["upper_percent"] < -margin and all(v < -margin for v in blocks): out.update(decision="conditional_preference", recommended_arm="control")
        elif -margin < band["lower_percent"] <= band["upper_percent"] < margin and all(-margin < v < margin for v in blocks): out["decision"] = "within_material_margin"
        else: out.update(decision="inconclusive", reason_codes=["DIAGNOSTIC_AND_BLOCKS_INCONCLUSIVE"])
    except (ArithmeticError, ValueError, OverflowError) as exc:
        code = str(exc)
        return hold(code if code in REASONS else "NONFINITE_DIAGNOSTIC")
    return normalize_decision(out)
