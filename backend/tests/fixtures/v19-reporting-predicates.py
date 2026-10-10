"""Frozen reporting predicates for offline adapter tests; runtime imports reporting directly."""
from datetime import date, datetime, timedelta, timezone
import math

class ReportInvalid(ValueError):
    pass

KST = timezone(timedelta(hours=9))
MAX_NUMBER = 9007199254740991
BASIC_FIELDS = ('imp', 'clk', 'spend')
CONVERSION_FIELDS = ('conversions', 'conversion_value')

def _now(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ReportInvalid('시간대가 있는 시각이 필요합니다')
    return value.astimezone(KST)

def _number(value):
    return type(value) in (int, float) and 0 <= value <= MAX_NUMBER and math.isfinite(value)

def _collected(row, day, now):
    try:
        raw = row.get('checked_at')
        at = _now(datetime.fromisoformat(raw) if isinstance(raw, str) else raw)
        if at > now or at.date() <= date.fromisoformat(day):
            return None
        source = row.get('source_at')
        if source is not None:
            source = _now(datetime.fromisoformat(source) if isinstance(source, str) else source)
            if source > at or source.date() <= date.fromisoformat(day):
                return None
        return at.isoformat()
    except (TypeError, ValueError):
        return None
