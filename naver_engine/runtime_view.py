"""Fixed nonpersonal runtime projection; reading it never grants collector authority."""
from datetime import datetime
import math

REASONS = {
    "starting": {"STARTING"}, "disabled": {"DISABLED"}, "stopped": {"STOPPED"},
    "stale": {"STALE"}, "source_sync": {"SOURCE_SYNC"}, "collecting": {"COLLECTING"},
    "waiting": {"WAITING", "BACKUP_RUNNING"}, "idle": {"IDLE"},
    "rate_paused": {"RATE_LIMITED"}, "error": {"RUNTIME_ERROR"},
    "blocked": {"SOURCE_NOT_READY", "SOURCE_CHANGED", "SOURCE_SYNC_FAILED",
                "SOURCE_CONFIRMATION_REQUIRED", "AUTH_REQUIRED"},
}
GREEN = frozenset({"source_sync", "collecting", "waiting", "idle"})
FIELDS = frozenset({"state", "indicator", "reason_code", "verified_at", "valid_for_seconds", "retry_at"})


def unavailable():
    return {"state": "unavailable", "indicator": "red", "reason_code": "UNAVAILABLE",
            "verified_at": None, "valid_for_seconds": 0, "retry_at": None}


def _timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        return False
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except (TypeError, ValueError, OverflowError):
        return False


def project(getter):
    """Reject unexpected fields/values; never serialize callback failures or raw configuration."""
    try:
        value = getter() if callable(getter) else None
        if type(value) is not dict or set(value) != FIELDS:
            return unavailable()
        state, reason = value["state"], value["reason_code"]
        if not isinstance(state, str) or not isinstance(reason, str) or reason not in REASONS.get(state, ()):
            return unavailable()
        if value["indicator"] != ("green" if state in GREEN else "red"):
            return unavailable()
        ttl = value["valid_for_seconds"]
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or not 0 <= ttl <= 3600:
            return unavailable()
        if value["verified_at"] is not None and not _timestamp(value["verified_at"]):
            return unavailable()
        if value["retry_at"] is not None and not _timestamp(value["retry_at"]):
            return unavailable()
        if state in GREEN and (ttl == 0 or value["verified_at"] is None):
            return {**unavailable(), "state": "stale", "reason_code": "STALE"}
        return dict(value)
    except Exception:
        return unavailable()
