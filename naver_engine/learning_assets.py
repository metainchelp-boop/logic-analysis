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
import sqlite3

from . import store as S

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
COUNTS = frozenset({"impressions", "clicks", "conversions"})
METRICS = COUNTS | {"spend", "conversion_value"}
CONVERSION_DEFINITIONS = frozenset({"purchase", "lead", "platform", "unknown"})
REASON_CODES = frozenset({"observed_performance", "planned_change", "observed_change", "applied_change",
    "no_causal_control", "running", "stopped", "horizon_not_complete", "not_preregistered",
    "not_randomized", "multiple_variables", "measurement_incomplete", "conversion_definition_unknown",
    "lag_not_mature", "allocation_invalid", "sample_ratio_mismatch", "missing_metrics", "invalid_binary_counts",
    "goal_requires_variance", "insufficient_sample", "predeclared_sample_below_power", "no_statistical_separation",
    "below_mde", "qualified_difference", "protocol_changed", "independent_units_unknown"})


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
    evidence = value["evidence"]
    _fields(evidence, document_template(kind)["evidence"])
    clean = deepcopy(evidence)
    if kind in ("performance", "experiment"):
        for key in ("period_start", "period_end"):
            clean[key] = _day(evidence[key])
        if clean["period_start"] > clean["period_end"] or (date.fromisoformat(clean["period_end"]) - date.fromisoformat(clean["period_start"])).days > 366:
            _refuse("성과 관측 기간을 확인해 주세요")
        clean["measurement_complete"] = _boolean(evidence["measurement_complete"])
        clean["lag_mature"] = _boolean(evidence["lag_mature"])
        clean["conversion_definition"] = _enum(evidence["conversion_definition"], CONVERSION_DEFINITIONS)
    if kind == "performance":
        clean.update(_metrics({key: evidence[key] for key in METRICS}))
    elif kind == "setting_change":
        clean["execution"] = _enum(evidence["execution"], {"planned", "observed", "applied"})
        clean["changed_variable"] = _enum(evidence["changed_variable"], SETTING_FIELDS | {"multiple"})
        clean["before"], clean["after"] = _settings(evidence["before"]), _settings(evidence["after"])
        if evidence["observed_at"] is not None:
            _at(evidence["observed_at"])
        if clean["execution"] != "planned" and evidence["observed_at"] is None:
            _refuse("실제 세팅의 관측 시각이 필요합니다")
        changed = {key for key in set(clean["before"]) | set(clean["after"])
                   if clean["before"].get(key) != clean["after"].get(key)}
        if clean["changed_variable"] != "multiple" and changed != {clean["changed_variable"]}:
            _refuse("세팅 변경 항목과 전후 값을 확인해 주세요")
    else:
        clean["status"] = _enum(evidence["status"], {"running", "completed", "stopped"})
        clean["goal"] = _enum(evidence["goal"], {"ctr", "cvr", "cpa", "roas"})
        clean["min_sample_per_arm"] = _integer(evidence["min_sample_per_arm"], minimum=1, maximum=10**9)
        clean["mde_percent"] = _number(evidence["mde_percent"], minimum=0.1, maximum=100)
        clean["control_share"] = _number(evidence["control_share"], minimum=0.1, maximum=0.9)
        if evidence["baseline_rate"] is not None:
            clean["baseline_rate"] = _number(evidence["baseline_rate"], minimum=0.000001, maximum=0.999999)
        if evidence["preregistered_at"] is not None:
            _at(evidence["preregistered_at"])
        for key in ("randomized", "independent_units", "one_variable", "allocation_valid"):
            clean[key] = _boolean(evidence[key])
        for key in ("control", "treatment"):
            clean[key] = _metrics(evidence[key])
    refs = value["source_refs"]
    if not isinstance(refs, dict) or not set(refs) <= {"report_id", "report_revision", "plan_version", "setting_version"}:
        _refuse()
    for key, item in refs.items():
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
        reasons.extend([{"planned": "planned_change", "observed": "observed_change", "applied": "applied_change"}[evidence["execution"]], "no_causal_control"])
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
    if any(arm[denominator] <= 0 or arm[numerator] > arm[denominator] for arm in arms):
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


def _load(connection, key):
    row = connection.execute("SELECT length(value),substr(value,1,?) FROM naver_auto_meta WHERE key=?", (MAX_CHARS + 1, key)).fetchone()
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
        elif (value["document"].get("kind") != "performance" or
              not {"report_id", "report_revision"} <= set(value["document"].get("source_refs", {}))):
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


def record(connection, possibility_id, account_key, actor, at, expected_version, asset_id, document=None, action="save"):
    """Append within the caller's transaction; a savepoint also protects standalone use."""
    identity = _identity(possibility_id, account_key, asset_id)
    if actor is not None:
        _integer(actor, maximum=MAX_VERSION)
    _at(at)
    _integer(expected_version, maximum=MAX_VERSION - 1)
    _enum(action, {"save", "review", "reject"})
    if action != "save" and document is not None:
        _refuse()
    clean = normalize_document(document) if action == "save" else None
    if actor is None and (action != "save" or clean["kind"] != "performance" or
                          not {"report_id", "report_revision"} <= set(clean["source_refs"])):
        _refuse("시스템 관측은 확인된 보고서에서만 저장할 수 있습니다")
    if clean is not None and clean["kind"] == "setting_change" and clean["evidence"]["observed_at"] is not None and _at(clean["evidence"]["observed_at"]) > _at(at):
        _refuse("미래의 세팅을 관측 결과로 저장할 수 없습니다")
    request = {"actor": actor, "expected_version": expected_version, "action": action, "document": clean}
    digest = hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    head = "learning-head:" + identity + asset_id
    history = "learning-version:" + identity + asset_id + ":"
    connection.execute("SAVEPOINT learning_asset_record")
    try:
        prior = _load(connection, history + f"{expected_version + 1:016d}")
        if prior is not None and prior["request_digest"] == digest:
            connection.execute("RELEASE SAVEPOINT learning_asset_record")
            return _present(prior)
        current = _load(connection, head)
        if (current["version"] if current else 0) != expected_version:
            _refuse("학습 자산이 변경되었습니다. 최신 판을 다시 확인해 주세요")
        if action != "save":
            if current is None or current["state"] != "draft":
                _refuse("학습 자산의 초안을 먼저 확인해 주세요")
            clean = current["document"]
        if current is not None and current["document"]["kind"] != clean["kind"]:
            _refuse("학습 자산 종류는 새 자산으로 기록해 주세요")
        registration = (current["registration"] if current is not None else
                        {"at": at, "spec_hash": _spec_hash(clean)} if clean["kind"] == "experiment" else None)
        saved = {"asset_id": asset_id, "version": expected_version + 1,
            "state": {"save": "draft", "review": "reviewed", "reject": "rejected"}[action],
            "identity": {"possibility_id": possibility_id, "account_key": account_key},
            "author": {"actor": actor, "at": at} if action == "save" else current["author"],
            "reviewed_by": None if action == "save" else actor, "reviewed_at": None if action == "save" else at,
            "document": clean, "assessment": assess(clean, at, registration), "registration": registration, "request_digest": digest}
        raw = json.dumps(saved, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(raw) > MAX_CHARS:
            _refuse("학습 자산이 너무 큽니다")
        connection.execute("INSERT INTO naver_auto_meta(key,value) VALUES(?,?)", (history + f"{saved['version']:016d}", raw))
        connection.execute("INSERT INTO naver_auto_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (head, raw))
        connection.execute("RELEASE SAVEPOINT learning_asset_record")
        return _present(saved)
    except Exception as error:
        connection.execute("ROLLBACK TO SAVEPOINT learning_asset_record")
        connection.execute("RELEASE SAVEPOINT learning_asset_record")
        if isinstance(error, sqlite3.IntegrityError):
            raise S.StoreRefused("학습 자산이 변경되었습니다. 최신 판을 다시 확인해 주세요") from None
        raise


def list_assets(connection, possibility_id, account_key, limit=100, include_history=False, asset_id=None):
    identity = _identity(possibility_id, account_key, asset_id)
    _integer(limit, minimum=1, maximum=MAX_ASSETS)
    _boolean(include_history)
    prefix = ("learning-version:" if include_history else "learning-head:") + identity
    if asset_id is not None:
        prefix += asset_id + (":" if include_history else "")
    keys = connection.execute("SELECT key FROM naver_auto_meta WHERE key>=? AND key<? ORDER BY key DESC LIMIT ?", (prefix, prefix + "\uffff", limit)).fetchall()
    out = []
    for row in keys:
        if asset_id is not None and not include_history and row[0] != prefix:
            continue
        item = _load(connection, row[0])
        if item["identity"] != {"possibility_id": possibility_id, "account_key": account_key}:
            raise S.StoreError("저장된 학습 자산의 범위를 확인해 주세요")
        out.append(_present(item))
    return out


def get_asset(connection, possibility_id, account_key, asset_id):
    identity = _identity(possibility_id, account_key, asset_id)
    item = _load(connection, "learning-head:" + identity + asset_id)
    if item is None:
        return None
    if item["identity"] != {"possibility_id": possibility_id, "account_key": account_key} or item["asset_id"] != asset_id:
        raise S.StoreError("저장된 학습 자산의 범위를 확인해 주세요")
    return _present(item)


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
