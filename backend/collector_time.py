"""Collector business dates are explicit Korean dates, never machine-local dates."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def as_instant(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        value = datetime.fromtimestamp(value, timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("An explicit time zone is required")
    return value.astimezone(timezone.utc)


def business_day(value=None):
    return as_instant(value).astimezone(KST).date().isoformat()


def kst_timestamp(value):
    """Existing rank tables store wall time; always use Korean wall time here."""
    return as_instant(value).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
