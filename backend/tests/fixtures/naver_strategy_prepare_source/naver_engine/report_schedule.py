"""Closed, network-free policy for explicitly delegated Claude report drafts.

This module grants no authority, sends no request and approves no report. Store
callers recheck the saved actor/narrowed scope and immutable proof in a transaction.
"""
from copy import deepcopy
from datetime import datetime, time, timedelta
import re

from . import reporting as R

KINDS = frozenset({"weekly", "monthly"})
STATES = frozenset({"waiting", "source_wait", "queued", "reserved", "provider_started", "response_received",
    "draft_saved", "failed", "unknown", "source_changed", "cancelled", "skipped"})
ACTIVE = frozenset({"waiting", "source_wait", "queued", "reserved", "provider_started", "response_received"})
TERMINAL = STATES - ACTIVE
DIAGNOSTIC_CODES = frozenset({"context-changed", "token-expired", "job-interrupted", "unknown",
    "timeout", "tls", "network", "protocol", "request-size", "response-size", "response-shape",
    "envelope-json", "document-json", "truncated", "configuration", "context-invalid",
    "document-invalid", "numeric-citation-required", "reference-unavailable", "unconnected-evidence", "http",
    "source-wait", "source-changed", "delegation-changed", "authority-changed", "strategy-exists",
    "provider-unavailable", "worker-unavailable", "cancelled", "resumed_backlog", "manual_generation_available"})
REASON_CODES = frozenset({"SOURCE_MISSING", "PERIOD_MISMATCH", "NOT_LATEST", "REPORT_DIRTY",
    "STRATEGY_EXISTS", "ACCOUNT_SCOPE_MISMATCH", "COVERAGE_MISMATCH", "BASIC_INCOMPLETE",
    "GENERAL_CONVERSIONS_INCOMPLETE", "TOTALS_UNAVAILABLE", "REPORT_NOT_READY",
    "REVALIDATION_PENDING", "SOURCE_TIME_UNVERIFIED", "SNAPSHOT_UNVERIFIED"})
MAX_VERSION = 2**53 - 1
MAX_ID = 2**63 - 1
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
JOB_FIELDS = frozenset("job_id version possibility_id account_key delegation_version actor narrowed period_key origin retry_of retry_of_version state report_id revision_fingerprint expected_strategy_version proof_hash created_at updated_at next_check_at provider_started_at response_received_at result_version diagnostic".split())
RECEIPT_FIELDS = frozenset({"request_id", "schedule_version", "job_id", "job_version"})


class ScheduleInvalid(ValueError):
    """Safe diagnostics contain no advertiser, provider text or source identity."""


def _invalid():
    raise ScheduleInvalid("예약 보고서의 항목과 값을 확인해 주세요")


def _fields(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        _invalid()


def _integer(value, minimum=0, maximum=MAX_VERSION):
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid()
    return value


def _hex(value, size, *, nullable=False):
    if nullable and value is None:
        return None
    if type(value) is not str or not (_HEX32 if size == 32 else _HEX64).fullmatch(value):
        _invalid()
    return value


def moment(value):
    try:
        if isinstance(value, str):
            if not 20 <= len(value) <= 40:
                _invalid()
            value = datetime.fromisoformat(value)
        if type(value) is not datetime or value.utcoffset() is None:
            _invalid()
        return value.astimezone(R.KST)
    except (ValueError, TypeError, OverflowError):
        _invalid()


def empty_document():
    return {"weekly": False, "monthly": False}


def normalize_document(value, *, approve=False):
    _fields(value, KINDS)
    if type(approve) is not bool or any(type(value[k]) is not bool for k in KINDS):
        _invalid()
    if approve and not any(value.values()):
        _invalid()
    return dict(value)


def period_from_key(key):
    try:
        if type(key) is not str or not 25 <= len(key) <= 40:
            _invalid()
        kind, start, end = key.split(":")
        if kind not in KINDS:
            _invalid()
        from datetime import date
        value = R.period(kind, date.fromisoformat(start))
        if value.key != key:
            _invalid()
        return value
    except (R.ReportInvalid, ValueError, TypeError, OverflowError):
        _invalid()


def _closed_at(period):
    try:
        return datetime.combine(period.end + timedelta(days=1), time(), tzinfo=R.KST)
    except (ValueError, OverflowError):
        _invalid()


def first_period(kind, approved_at):
    """First period that closes after approval, never a closed-but-not-due one."""
    approved = moment(approved_at)
    if type(kind) is not str or kind not in KINDS:
        _invalid()
    try:
        current = R.period(kind, approved.date())
        if _closed_at(current) <= approved:
            current = advance_period(current.key)
        return current
    except (R.ReportInvalid, ValueError, OverflowError):
        _invalid()


def advance_period(key):
    current = period_from_key(key)
    try:
        return R.period(current.kind, current.end + timedelta(days=1))
    except (R.ReportInvalid, ValueError, OverflowError):
        _invalid()


def due_periods(document, approved_at, now, cursors=None, *, limit=10):
    """Merge two bounded per-kind streams using reporting's canonical periods.

    Cursors point to the next unprocessed period. Persist them independently of
    queue retries; the Store's account/period UNIQUE receipt blocks paid replay.
    A disabled kind cannot consume the other kind's page budget.
    """
    document = normalize_document(document)
    approved, now = moment(approved_at), moment(now)
    if approved > now:
        _invalid()
    _integer(limit, 1, 10)
    if cursors is not None:
        _fields(cursors, KINDS)
    current = {}
    for kind in sorted(KINDS):
        first = first_period(kind, approved)
        raw = (cursors or {}).get(kind)
        item = first if raw is None else period_from_key(raw)
        if item.kind != kind or item.start < first.start or _closed_at(item) <= approved:
            _invalid()
        current[kind] = item
    periods = []
    for _ in range(limit):
        eligible = [p for kind, p in current.items() if document[kind] and p.due_at <= now]
        if not eligible:
            break
        chosen = min(eligible, key=lambda p: (p.due_at, p.key))
        periods.append({"period_key": chosen.key, **chosen.as_dict()})
        current[chosen.kind] = advance_period(chosen.key)
    return {"periods": periods, "next_cursors": {kind: current[kind].key for kind in sorted(KINDS)}}


def latest_due(kind, approved_at, now, cursor=None):
    """Resume at the latest due period only; older backlog is never paid backfill.

    Skipped periods are represented as a bounded range/count, not thousands of
    synthesized jobs. Store preserves existing report history and period receipts.
    """
    approved, now = moment(approved_at), moment(now)
    if approved > now:
        _invalid()
    first = first_period(kind, approved)
    current = first if cursor is None else period_from_key(cursor)
    if current.kind != kind or current.start < first.start:
        _invalid()
    result = {"period": None, "next_cursor": current.key, "skipped_count": 0,
        "skipped_from": None, "skipped_through": None, "reason_codes": []}
    try:
        latest = R.period(kind, now.date())
        # At most two preceding periods are needed: current, just closed but not
        # due, then the previous due one. No loop over elapsed years.
        for _ in range(2):
            if latest.due_at <= now:
                break
            latest = R.previous_period(latest)
        if latest.due_at > now or latest.start < current.start or _closed_at(latest) <= approved:
            return result
        count = ((latest.start - current.start).days // 7 if kind == "weekly" else
            (latest.start.year - current.start.year) * 12 + latest.start.month - current.start.month)
        result.update(period={"period_key": latest.key, **latest.as_dict()}, next_cursor=advance_period(latest.key).key)
        if count:
            result.update(skipped_count=count, skipped_from=current.key, skipped_through=R.previous_period(latest).key,
                reason_codes=["resumed_backlog", "manual_generation_available"])
        return result
    except (R.ReportInvalid, ValueError, OverflowError):
        _invalid()


def readiness(payload, validation, *, latest, dirty, strategy_exists, period_key=None, now=None):
    """Require selected-account numeric completeness AND current revalidation.

    Optional purchase/cart coverage is deliberately outside the general-platform
    report gate. Missing values stay missing; an observed zero is valid.
    """
    if any(type(flag) is not bool for flag in (latest, dirty, strategy_exists)):
        _invalid()
    if period_key is not None:
        period_from_key(period_key)
    at = moment(now) if now is not None else None
    if strategy_exists:
        return {"state": "skip", "reason_codes": ["STRATEGY_EXISTS"]}
    reasons = []
    if not latest:
        reasons.append("NOT_LATEST")
    if dirty:
        reasons.append("REPORT_DIRTY")
    if not isinstance(payload, dict):
        return {"state": "source_wait", "reason_codes": reasons + ["SOURCE_MISSING"]}
    try:
        period = period_from_key(payload.get("period_key"))
    except ScheduleInvalid:
        return {"state": "source_wait", "reason_codes": reasons + ["PERIOD_MISMATCH"]}
    if period_key is not None and period.key != period_key:
        reasons.append("PERIOD_MISMATCH")
    if payload.get("period") != period.as_dict():
        reasons.append("PERIOD_MISMATCH")
    if type(payload.get("revision_fingerprint")) is not str or not _HEX64.fullmatch(payload["revision_fingerprint"]):
        reasons.append("SNAPSHOT_UNVERIFIED")
    coverage = payload.get("coverage") or {}
    if not isinstance(coverage, dict):
        coverage = {}
    days = (period.end - period.start).days + 1
    if type(coverage.get("accounts")) is not int or coverage.get("accounts") != 1:
        reasons.append("ACCOUNT_SCOPE_MISMATCH")
    if (type(coverage.get("expected_account_days")) is not int or coverage.get("expected_account_days") != days):
        reasons.append("COVERAGE_MISMATCH")
    for field, reason in (("basic", "BASIC_INCOMPLETE"), ("conversion", "GENERAL_CONVERSIONS_INCOMPLETE")):
        count = coverage.get(field + "_complete_account_days")
        if coverage.get(field + "_complete") is not True or type(count) is not int or count != days:
            reasons.append(reason)
    totals = payload.get("totals")
    if not isinstance(totals, dict) or any(not R._number(totals.get(key)) for key in R.OUTPUT_FIELDS.values()):
        reasons.append("TOTALS_UNAVAILABLE")
    if payload.get("ready") is not True or payload.get("status") != "ready" or payload.get("missing") != [] or payload.get("blocked_reasons") != []:
        reasons.append("REPORT_NOT_READY")
    if (not isinstance(validation, dict) or validation.get("status") != "complete"
            or type(validation.get("pending_account_days")) is not int or validation.get("pending_account_days") != 0):
        reasons.append("REVALIDATION_PENDING")
    try:
        checked = moment((validation or {}).get("last_checked_at"))
        generated = moment(payload.get("generated_at"))
        if checked < period.due_at.replace(hour=0, minute=1) or generated < period.due_at or (at is not None and (checked > at or generated > at)):
            raise ScheduleInvalid()
    except (ScheduleInvalid, AttributeError, TypeError):
        reasons.append("SOURCE_TIME_UNVERIFIED")
    return {"state": "source_wait" if reasons else "ready", "reason_codes": list(dict.fromkeys(reasons))}


def _diagnostic(value):
    if value is None:
        return None
    _fields(value, {"code", "http_status"})
    if type(value["code"]) is not str or value["code"] not in DIAGNOSTIC_CODES:
        _invalid()
    if value["code"] == "http":
        _integer(value["http_status"], 100, 599)
    elif value["http_status"] is not None:
        _invalid()
    return dict(value)


def clean_job(value):
    """Validate bounded persisted metadata; never persist a JWT or AI response."""
    _fields(value, JOB_FIELDS)
    out = deepcopy(value)
    for key, size in (("job_id", 32), ("account_key", 64)):
        _hex(value[key], size)
    for key in ("version", "delegation_version"):
        _integer(value[key], 1)
    _integer(value["possibility_id"], 1, MAX_ID)
    _integer(value["actor"], 0, MAX_ID)
    if type(value["narrowed"]) is not bool or type(value["state"]) is not str or value["state"] not in STATES:
        _invalid()
    period_from_key(value["period_key"])
    if type(value["origin"]) is not str or value["origin"] not in {"automatic", "manual_retry"}:
        _invalid()
    if value["origin"] == "automatic":
        if value["retry_of"] is not None or value["retry_of_version"] is not None:
            _invalid()
    else:
        _hex(value["retry_of"], 32)
        _integer(value["retry_of_version"], 1)
        if value["retry_of"] == value["job_id"]:
            _invalid()
    for key, minimum, maximum in (("report_id", 1, MAX_ID), ("expected_strategy_version", 0, MAX_VERSION), ("result_version", 1, MAX_VERSION)):
        if value[key] is not None:
            _integer(value[key], minimum, maximum)
    for key in ("revision_fingerprint", "proof_hash"):
        _hex(value[key], 64, nullable=True)
    proof_keys = ("report_id", "revision_fingerprint", "expected_strategy_version", "proof_hash")
    if any(value[key] is None for key in proof_keys) and any(value[key] is not None for key in proof_keys):
        _invalid()
    requires_proof = value["state"] in {"queued", "reserved", "provider_started", "response_received", "draft_saved", "unknown"}
    if requires_proof and any(value[key] is None for key in proof_keys):
        _invalid()
    times = {}
    for key in ("created_at", "updated_at", "next_check_at", "provider_started_at", "response_received_at"):
        if value[key] is None and key not in {"created_at", "updated_at"}:
            times[key] = None
        else:
            times[key] = moment(value[key]); out[key] = times[key].isoformat()
    if times["created_at"] > times["updated_at"]:
        _invalid()
    for key in ("provider_started_at", "response_received_at"):
        if times[key] is not None and not times["created_at"] <= times[key] <= times["updated_at"]:
            _invalid()
    if times["response_received_at"] is not None and (times["provider_started_at"] is None or times["response_received_at"] < times["provider_started_at"]):
        _invalid()
    if value["state"] in {"waiting", "source_wait", "queued", "reserved", "skipped"} and (times["provider_started_at"] is not None or times["response_received_at"] is not None):
        _invalid()
    if value["state"] in {"provider_started", "response_received", "draft_saved", "unknown"} and times["provider_started_at"] is None:
        _invalid()
    if value["state"] in {"response_received", "draft_saved"} and times["response_received_at"] is None:
        _invalid()
    if (value["state"] == "draft_saved") != (value["result_version"] is not None):
        _invalid()
    out["diagnostic"] = _diagnostic(value["diagnostic"])
    if value["state"] in {"queued", "reserved", "provider_started", "response_received", "draft_saved"} and out["diagnostic"] is not None:
        _invalid()
    if value["state"] in {"failed", "unknown", "source_changed", "cancelled", "skipped"} and out["diagnostic"] is None:
        _invalid()
    if value["state"] == "skipped" and out["diagnostic"]["code"] != "resumed_backlog":
        _invalid()
    return out


def public_job(value):
    clean = clean_job(value)
    private = {"actor", "narrowed", "proof_hash"}
    return {**{key: val for key, val in clean.items() if key not in private},
        "cost_may_have_occurred": clean["provider_started_at"] is not None,
        "can_retry": clean["state"] in {"failed", "unknown", "source_changed"},
        "reason_codes": ["resumed_backlog", "manual_generation_available"] if clean["state"] == "skipped" else []}


def clean_request(value):
    """Exact typed mutation input; actor/narrowed come from current server scope."""
    if type(value) is not dict or type(value.get("action")) is not str:
        _invalid()
    action = value["action"]
    base = {"possibility_id", "account_key", "request_id", "action"}
    if action == "retry":
        _fields(value, base | {"job_id", "expected_job_version"})
        _hex(value["job_id"], 32)
        _integer(value["expected_job_version"], 1)
    elif action in {"save", "approve", "disable"}:
        _fields(value, base | {"expected_version"} | ({"document"} if action == "save" else set()))
        _integer(value["expected_version"])
        if action == "save":
            normalize_document(value["document"])
    else:
        _invalid()
    _integer(value["possibility_id"], 1, MAX_ID)
    _hex(value["account_key"], 64)
    _hex(value["request_id"], 32)
    return deepcopy(value)


def clean_receipt(value):
    """Public receipt; selection and actor/body binding stay in Store columns."""
    _fields(value, RECEIPT_FIELDS)
    _hex(value["request_id"], 32)
    _integer(value["schedule_version"], 1)
    if (value["job_id"] is None) != (value["job_version"] is None):
        _invalid()
    if value["job_id"] is not None:
        _hex(value["job_id"], 32)
        _integer(value["job_version"], 1)
    return deepcopy(value)
