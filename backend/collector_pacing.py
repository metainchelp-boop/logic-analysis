"""코덱스 1.22.0 이식 (2026-09-22 · 2차) — 기계별 간격 조절 상태 기계. 원문 그대로(stdlib). 우리 v2 조정에서 claim 간격에 쓴다."""
"""Deterministic worker pacing; the caller owns persistence, budgets and review.

Intervals stay between the approved base and four times that base. Paused state
never recovers through observations; only an explicit caller reset can clear it.
"""
import math

_FIELDS = {"schema", "intervalSeconds", "ewmaSeconds", "penalty", "paused", "pauseReason"}
_PAUSES = {"paused", "unknown", "blocked", "auth", "schema", "PAUSED_UNKNOWN",
           "PAUSED_BLOCK", "PAUSED_AUTH", "PAUSED_SCHEMA", "PAUSED_OPERATOR", "PAUSED_STORAGE"}


def _finite(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _result(base, ewma=None, penalty=1.0, paused=False, reason=None):
    interval = min(base * 4, max(base, ewma or base, base * penalty))
    return {"schema": 1, "intervalSeconds": interval, "ewmaSeconds": ewma,
            "penalty": penalty, "paused": paused, "pauseReason": reason}


def _valid(state):
    return (isinstance(state, dict) and set(state) == _FIELDS
            and type(state["schema"]) is int and state["schema"] == 1
            and _finite(state["intervalSeconds"]) and state["intervalSeconds"] > 0
            and (state["ewmaSeconds"] is None or
                 (_finite(state["ewmaSeconds"]) and state["ewmaSeconds"] >= 0))
            and _finite(state["penalty"]) and 1 <= state["penalty"] <= 4
            and type(state["paused"]) is bool
            and ((state["paused"] and isinstance(state["pauseReason"], str)
                  and 0 < len(state["pauseReason"]) <= 64)
                 or (not state["paused"] and state["pauseReason"] is None)))


def update(state=None, *, duration_seconds=None, action_count=None, outcome, base_interval):
    """Update JSON state from a successful job or an explicit transient error.

    Successful job duration is divided by its reserved external-action count.
    A 1/4 EWMA smooths samples. Transient errors double the penalty (up to 4x);
    successes reduce it by 1/4 each time. Neither mechanism raises budget caps.
    """
    if not _finite(base_interval) or base_interval <= 0 or not _finite(base_interval * 4):
        raise ValueError("INVALID_BASE_INTERVAL")
    base = float(base_interval)
    if state is not None and not _valid(state):
        return _result(base, penalty=4.0, paused=True, reason="INVALID_PACING_STATE")
    previous = state if state is not None else _result(base)
    ewma = previous["ewmaSeconds"]
    ewma = min(ewma, base * 4) if ewma is not None else None
    penalty = previous["penalty"]
    if previous["paused"]:
        return _result(base, ewma, 4.0, True, previous["pauseReason"])
    if outcome == "transient_error":
        return _result(base, ewma, min(4.0, max(2.0, penalty * 2)))
    if outcome != "success":
        reason = outcome.upper() if isinstance(outcome, str) and outcome in _PAUSES else "UNKNOWN_OUTCOME"
        return _result(base, ewma, 4.0, True, reason)
    if (not _finite(duration_seconds) or duration_seconds < 0
            or type(action_count) is not int or not _finite(action_count) or action_count <= 0):
        return _result(base, ewma, 4.0, True, "INVALID_PACING_METRICS")
    sample = min(duration_seconds / action_count, base * 4)
    ewma = sample if ewma is None else ewma * 0.75 + sample * 0.25
    return _result(base, ewma, max(1.0, penalty * 0.75))
