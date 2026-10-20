"""Exact paired assignment inference under an explicit constant CTR shift model.

Units are predeclared time blocks, never impressions or users. The calling
source adapter must verify the full assignment, compliance and source ledger.
Accepted structural assumptions are not verified by this calculation.
"""
from bisect import bisect_left, bisect_right
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
import math
import re


METHOD = "randomized_paired_ctr_constant_shift_v1"
ASSIGNMENT_SCHEME = "independent_fair_within_pair"
ASSUMPTIONS = ("constant_additive_effect", "no_interference", "no_carryover")
KST = timezone(timedelta(hours=9))
MAX_PAIRS = 15
MAX_COUNT = 2**63-1
PROTOCOL_FIELDS = frozenset(("version", "method", "registered_at", "period_start", "period_end", "pair_count",
                            "measurement_lag_days", "superiority_margin_pp", "equivalence_margin_pp", "assumptions"))
EVIDENCE_FIELDS = frozenset(("assignment_scheme", "assignment_verified", "compliance_complete", "source_complete",
                            "settings_stable", "stopped_early", "pairs"))
P_VALUE_FIELDS = ("sharp_no_effect_two_sided", "superiority_treatment", "superiority_control",
                  "equivalence_lower", "equivalence_upper")
REASONS = frozenset(("ASSUMPTIONS_NOT_DECLARED", "NOT_PREREGISTERED", "HORIZON_NOT_COMPLETE", "LAG_NOT_MATURE",
                    "ASSIGNMENT_UNVERIFIED", "COMPLIANCE_INCOMPLETE", "SOURCE_INCOMPLETE", "SETTINGS_CHANGED",
                    "STOPPED_EARLY", "PAIR_COUNT_MISMATCH", "BLOCK_CALENDAR_MISMATCH", "PAIR_ARMS_INVALID",
                    "REQUIRED_METRIC_UNAVAILABLE", "ZERO_IMPRESSIONS", "INVALID_CTR_COUNTS",
                    "INSUFFICIENT_RANDOMIZATION_RESOLUTION", "NO_DECISION"))
QUALIFIERS = (
    "constant_additive_effect_assumed_not_verified", "no_interference_and_no_carryover_assumed_not_verified",
    "equal_weight_block_ctr_percentage_points_not_pooled_ctr", "randomization_unit_is_time_block_not_user_or_impression",
    "conditional_on_complete_preregistered_assignment_and_compliance", "not_heterogeneous_average_effect_inference",
    "closed_conservative_endpoints_outward_binary64", "ctr_potential_outcomes_in_0_100_no_support_clipping",
    "non_significance_is_not_equivalence", "fixed_horizon_single_primary_contrast",
)
RESULT_FIELDS = frozenset(("version", "method", "evidence_grade", "decision", "winner", "randomized", "causal_claim",
                          "assumptions_verified", "effect_pp", "interval95_pp", "interval90_pp",
                          "superiority_margin_pp", "equivalence_margin_pp", "pair_count", "assignment_count",
                          "p_values", "reason_codes", "qualifiers"))
INTERVAL_FIELDS = frozenset(("lower_pp", "upper_pp", "lower_unbounded", "upper_unbounded"))


class InferenceInvalid(ValueError):
    pass


def _exact(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields): raise InferenceInvalid("INVALID_SHAPE")


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high: raise InferenceInvalid("INVALID_INTEGER")
    return value


def _number(value, low=-100, high=100):
    if type(value) not in (int, float): raise InferenceInvalid("INVALID_NUMBER")
    try:
        if not math.isfinite(value) or not low <= value <= high: raise InferenceInvalid("INVALID_NUMBER")
    except (OverflowError, TypeError): raise InferenceInvalid("INVALID_NUMBER") from None
    return value


def _day(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise InferenceInvalid("INVALID_DAY")
    try: return date.fromisoformat(value)
    except ValueError: raise InferenceInvalid("INVALID_DAY") from None


def _moment(value):
    if isinstance(value, str) and len(value) <= 40:
        try: value = datetime.fromisoformat(value)
        except ValueError: raise InferenceInvalid("INVALID_MOMENT") from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise InferenceInvalid("INVALID_MOMENT")
    try: return value.astimezone(KST)
    except (OverflowError, ValueError): raise InferenceInvalid("INVALID_MOMENT") from None


def _fraction(value):
    return value if isinstance(value, Fraction) else Fraction(str(value))


def _differences(value):
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= MAX_PAIRS:
        raise InferenceInvalid("INVALID_PAIR_COUNT")
    result = []
    for item in value:
        if isinstance(item, Fraction):
            if abs(item) > 100: raise InferenceInvalid("INVALID_EFFECT")
            result.append(item)
        else: result.append(_fraction(_number(item)))
    return result


def _subset_means(differences):
    # Every nonempty subset corresponds to precisely one sign vector except
    # the all-positive vector. Enumeration is bounded by 2**15 assignments.
    sums, sizes = [Fraction(0)], [0]
    for difference in differences:
        size = len(sums)
        sums.extend(sums[j]+difference for j in range(size))
        sizes.extend(sizes[j]+1 for j in range(size))
    return sorted(sums[j]/sizes[j] for j in range(1, len(sums)))


def _tails(means, delta):
    total = len(means)+1
    return dict(greater=1+bisect_right(means, delta), less=1+len(means)-bisect_left(means, delta), denominator=total)


def exact_tails(differences, delta):
    """Inclusive exact one-sided tail counts, retaining ties and observed draw."""
    differences = _differences(differences)
    if isinstance(delta, Fraction):
        if abs(delta) > 100: raise InferenceInvalid("INVALID_MARGIN")
    else: delta = _fraction(_number(delta))
    return _tails(_subset_means(differences), delta)


def _interval(means, tail):
    k = (tail.numerator*(len(means)+1))//tail.denominator
    if k == 0: return (None, None)
    return (means[k-1], means[len(means)-k])


def exact_intervals(differences):
    """Closed rational endpoints; None is an unbounded side, never zero."""
    means = _subset_means(_differences(differences))
    return {"95": _interval(means, Fraction(1, 40)), "90": _interval(means, Fraction(1, 20))}


def _outward(value, lower):
    rounded = float(value)
    exact_rounded = Fraction.from_float(rounded)
    if (lower and exact_rounded > value) or (not lower and exact_rounded < value):
        rounded = math.nextafter(rounded, -math.inf if lower else math.inf)
    return rounded


def _public_interval(interval):
    lower, upper = interval
    return dict(lower_pp=None if lower is None else _outward(lower, True),
                upper_pp=None if upper is None else _outward(upper, False),
                lower_unbounded=lower is None, upper_unbounded=upper is None)


def _blank_interval():
    return dict(lower_pp=None, upper_pp=None, lower_unbounded=False, upper_unbounded=False)


def _p(numerator, denominator):
    return dict(numerator=numerator, denominator=denominator)


def _decision(result):
    interval95, interval90 = result["interval95_pp"], result["interval90_pp"]
    superiority = result["superiority_margin_pp"]; equivalence = result["equivalence_margin_pp"]
    p = result["p_values"]
    if (interval95["lower_pp"] is not None and interval95["lower_pp"] > superiority
            and p["superiority_treatment"]["numerator"]*40 <= p["superiority_treatment"]["denominator"]):
        return "winner", "treatment"
    if (interval95["upper_pp"] is not None and interval95["upper_pp"] < -superiority
            and p["superiority_control"]["numerator"]*40 <= p["superiority_control"]["denominator"]):
        return "winner", "control"
    if (interval90["lower_pp"] is not None and interval90["lower_pp"] > -equivalence
            and interval90["upper_pp"] is not None and interval90["upper_pp"] < equivalence
            and p["equivalence_lower"]["numerator"]*20 <= p["equivalence_lower"]["denominator"]
            and p["equivalence_upper"]["numerator"]*20 <= p["equivalence_upper"]["denominator"]):
        return "equivalent", None
    return "inconclusive", None


def assess(protocol, evidence, *, now):
    """Consume a server-bound complete schedule proof; never infer compliance.

    Valid but incomplete evidence produces hold. Malformed/unsupported shapes
    raise InferenceInvalid. Neither explicit assumptions nor synthetic tests
    prove constant effects, no interference or sufficient washout in real ads.
    """
    _exact(protocol, PROTOCOL_FIELDS); _exact(evidence, EVIDENCE_FIELDS)
    if type(protocol["version"]) is not int or protocol["version"] != 1 or protocol["method"] != METHOD:
        raise InferenceInvalid("UNSUPPORTED_METHOD")
    pairs = _integer(protocol["pair_count"], 2, MAX_PAIRS)
    lag = _integer(protocol["measurement_lag_days"], 0, 30)
    superiority = _number(protocol["superiority_margin_pp"], 0, 100)
    equivalence = _number(protocol["equivalence_margin_pp"], 0, 100)
    if equivalence == 0 or equivalence > superiority: raise InferenceInvalid("INVALID_MARGIN_ORDER")
    _exact(protocol["assumptions"], ASSUMPTIONS)
    if any(type(v) is not bool for v in protocol["assumptions"].values()): raise InferenceInvalid("INVALID_ASSUMPTION")
    if evidence["assignment_scheme"] != ASSIGNMENT_SCHEME: raise InferenceInvalid("UNSUPPORTED_ASSIGNMENT")
    for key in EVIDENCE_FIELDS-{"assignment_scheme", "pairs"}:
        if type(evidence[key]) is not bool: raise InferenceInvalid("INVALID_PROOF")
    if not isinstance(evidence["pairs"], list) or len(evidence["pairs"]) > MAX_PAIRS:
        raise InferenceInvalid("INVALID_PAIRS")
    start, end = _day(protocol["period_start"]), _day(protocol["period_end"])
    registration, at = _moment(protocol["registered_at"]), _moment(now)
    if (end-start).days+1 != pairs*2: raise InferenceInvalid("INVALID_PERIOD")
    try:
        starts = datetime.combine(start, time.min, KST)
        closes = datetime.combine(end+timedelta(days=1), time.min, KST)
        mature = closes+timedelta(days=lag)
    except (OverflowError, ValueError): raise InferenceInvalid("INVALID_PERIOD") from None
    reasons = []
    if not all(protocol["assumptions"].values()): reasons.append("ASSUMPTIONS_NOT_DECLARED")
    if registration >= starts or registration > at: reasons.append("NOT_PREREGISTERED")
    if at < closes: reasons.append("HORIZON_NOT_COMPLETE")
    elif at < mature: reasons.append("LAG_NOT_MATURE")
    for field, code in (("assignment_verified", "ASSIGNMENT_UNVERIFIED"), ("compliance_complete", "COMPLIANCE_INCOMPLETE"),
                        ("source_complete", "SOURCE_INCOMPLETE"), ("settings_stable", "SETTINGS_CHANGED")):
        if not evidence[field]: reasons.append(code)
    if evidence["stopped_early"]: reasons.append("STOPPED_EARLY")
    if len(evidence["pairs"]) != pairs: reasons.append("PAIR_COUNT_MISMATCH")
    keys, days, differences = set(), [], []
    for pair in evidence["pairs"]:
        _exact(pair, ("pair_key", "first", "second"))
        key = pair["pair_key"]
        if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{64}", key) is None: raise InferenceInvalid("INVALID_PAIR_KEY")
        if key in keys: raise InferenceInvalid("DUPLICATE_PAIR_KEY")
        keys.add(key); rates = {}
        for row in (pair["first"], pair["second"]):
            _exact(row, ("day", "arm", "imp", "clk")); day = _day(row["day"]); days.append(day)
            if row["arm"] not in ("control", "treatment"): raise InferenceInvalid("INVALID_ARM")
            if row["arm"] in rates: reasons.append("PAIR_ARMS_INVALID")
            imp, clk = row["imp"], row["clk"]
            if imp is not None: _integer(imp, 0, MAX_COUNT)
            if clk is not None: _integer(clk, 0, MAX_COUNT)
            if imp is None or clk is None:
                reasons.append("REQUIRED_METRIC_UNAVAILABLE"); rates[row["arm"]] = None
            elif imp == 0:
                reasons.append("ZERO_IMPRESSIONS"); rates[row["arm"]] = None
            elif clk > imp:
                reasons.append("INVALID_CTR_COUNTS"); rates[row["arm"]] = None
            else: rates[row["arm"]] = Fraction(100*clk, imp)
        if set(rates) != {"control", "treatment"}: reasons.append("PAIR_ARMS_INVALID")
        elif all(value is not None for value in rates.values()): differences.append(rates["treatment"]-rates["control"])
    expected = [start+timedelta(days=j) for j in range(2*pairs)]
    if sorted(days) != expected: reasons.append("BLOCK_CALENDAR_MISMATCH")
    result = dict(version=1, method=METHOD, evidence_grade="randomized_model_conditional", decision="hold", winner=None,
                  randomized=evidence["assignment_verified"], causal_claim=False, assumptions_verified=False,
                  effect_pp=None, interval95_pp=_blank_interval(), interval90_pp=_blank_interval(),
                  superiority_margin_pp=superiority, equivalence_margin_pp=equivalence, pair_count=pairs,
                  assignment_count=0, p_values={key: None for key in P_VALUE_FIELDS},
                  reason_codes=list(dict.fromkeys(reasons)), qualifiers=list(QUALIFIERS))
    if reasons: return normalize_result(result)
    means = _subset_means(differences); total = len(means)+1
    zero = _tails(means, Fraction(0))
    positive = _tails(means, _fraction(superiority)); negative = _tails(means, -_fraction(superiority))
    lower = _tails(means, -_fraction(equivalence)); upper = _tails(means, _fraction(equivalence))
    result.update(effect_pp=float(sum(differences)/pairs), assignment_count=total,
                  interval95_pp=_public_interval(_interval(means, Fraction(1, 40))),
                  interval90_pp=_public_interval(_interval(means, Fraction(1, 20))),
                  p_values=dict(sharp_no_effect_two_sided=_p(min(total, 2*min(zero["greater"], zero["less"])), total),
                                superiority_treatment=_p(positive["greater"], total), superiority_control=_p(negative["less"], total),
                                equivalence_lower=_p(lower["greater"], total), equivalence_upper=_p(upper["less"], total)))
    result["decision"], result["winner"] = _decision(result)
    if result["decision"] == "inconclusive":
        result["reason_codes"] = ["INSUFFICIENT_RANDOMIZATION_RESOLUTION" if result["interval95_pp"]["lower_unbounded"] else "NO_DECISION"]
    return normalize_result(result)


def normalize_result(value):
    """Closed result guard for UI/learning; never promotes a causal claim."""
    _exact(value, RESULT_FIELDS)
    if (type(value["version"]) is not int or value["version"] != 1 or value["method"] != METHOD
            or value["evidence_grade"] != "randomized_model_conditional"):
        raise InferenceInvalid("INVALID_RESULT")
    if value["causal_claim"] is not False or value["assumptions_verified"] is not False or type(value["randomized"]) is not bool:
        raise InferenceInvalid("INVALID_RESULT_CLAIM")
    pairs = _integer(value["pair_count"], 2, MAX_PAIRS)
    total = _integer(value["assignment_count"], 0, 2**MAX_PAIRS)
    _number(value["superiority_margin_pp"], 0, 100); _number(value["equivalence_margin_pp"], 0, 100)
    if value["equivalence_margin_pp"] == 0 or value["equivalence_margin_pp"] > value["superiority_margin_pp"]:
        raise InferenceInvalid("INVALID_MARGIN_ORDER")
    if value["effect_pp"] is not None: _number(value["effect_pp"])
    _exact(value["p_values"], P_VALUE_FIELDS)
    for interval in (value["interval95_pp"], value["interval90_pp"]):
        _exact(interval, INTERVAL_FIELDS)
        for side in ("lower", "upper"):
            number, unbounded = interval[side+"_pp"], interval[side+"_unbounded"]
            if type(unbounded) is not bool or (unbounded and number is not None): raise InferenceInvalid("INVALID_INTERVAL")
            if number is not None: _number(number)
        if interval["lower_pp"] is not None and interval["upper_pp"] is not None and interval["lower_pp"] > interval["upper_pp"]:
            raise InferenceInvalid("INVALID_INTERVAL")
    codes = value["reason_codes"]
    if (not isinstance(codes, list) or len(codes) > len(REASONS) or any(type(code) is not str or code not in REASONS for code in codes)
            or len(set(codes)) != len(codes) or value["qualifiers"] != list(QUALIFIERS)):
        raise InferenceInvalid("INVALID_QUALIFICATION")
    if total == 0:
        if (value["decision"] != "hold" or value["winner"] is not None or value["effect_pp"] is not None or not codes
                or any(item is not None for item in value["p_values"].values())
                or value["interval95_pp"] != _blank_interval() or value["interval90_pp"] != _blank_interval()
                or any(code in ("NO_DECISION", "INSUFFICIENT_RANDOMIZATION_RESOLUTION") for code in codes)):
            raise InferenceInvalid("INVALID_HOLD")
    else:
        if total != 2**pairs or not value["randomized"] or value["effect_pp"] is None: raise InferenceInvalid("INVALID_ASSIGNMENT_COUNT")
        for item in value["p_values"].values():
            _exact(item, ("numerator", "denominator")); _integer(item["numerator"], 1, total)
            if type(item["denominator"]) is not int or item["denominator"] != total: raise InferenceInvalid("INVALID_P_VALUE")
        for interval in (value["interval95_pp"], value["interval90_pp"]):
            for side in ("lower", "upper"):
                if interval[side+"_unbounded"] != (interval[side+"_pp"] is None): raise InferenceInvalid("INVALID_INTERVAL")
        lower95, upper95 = value["interval95_pp"]["lower_pp"], value["interval95_pp"]["upper_pp"]
        lower90, upper90 = value["interval90_pp"]["lower_pp"], value["interval90_pp"]["upper_pp"]
        if ((lower95 is not None and (lower90 is None or lower95 > lower90))
                or (upper95 is not None and (upper90 is None or upper95 < upper90))): raise InferenceInvalid("INVALID_INTERVAL_NESTING")
        if ((lower90 is not None and value["effect_pp"] < lower90)
                or (upper90 is not None and value["effect_pp"] > upper90)):
            raise InferenceInvalid("INVALID_EFFECT_INTERVAL")
        decision, winner = _decision(value)
        expected = [] if decision != "inconclusive" else ["INSUFFICIENT_RANDOMIZATION_RESOLUTION" if value["interval95_pp"]["lower_unbounded"] else "NO_DECISION"]
        if value["decision"] != decision or value["winner"] != winner or codes != expected: raise InferenceInvalid("INVALID_DECISION")
    # Canonical JSON-compatible copies: no private IDs or source text enter here.
    return {**value, "interval95_pp": dict(value["interval95_pp"]), "interval90_pp": dict(value["interval90_pp"]),
            "p_values": {key: None if item is None else dict(item) for key, item in value["p_values"].items()},
            "reason_codes": list(codes), "qualifiers": list(QUALIFIERS)}
