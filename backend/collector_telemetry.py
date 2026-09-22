"""수집기 미전송 보관함 요약(uploadSummary) 검증 — 코덱스 1.22.0 `collector_telemetry` 이식판 (4차 · 2026-09-22)

확장이 heartbeat·v2 register 에 실어 보내는 「내 보관함에 아직 못 올린 것이 몇 건·몇 바이트·검토 필요 몇 건·
가장 오래된 관측 시각」이다. **순위 증거가 아니다** — 서버가 이것으로 순위를 적지 않는다. 화면·진단이 「이 기계에
못 올린 것이 쌓였다」를 보는 용도. 형식이 어긋나면 0 이 아니라 **INVALID(못 쟀다)** 로 가른다.
⚠️ stdlib 만.
"""
import json
from typing import Any, Dict, Optional, Tuple

MAX_OUTBOX_ITEMS = 100
MAX_OUTBOX_BYTES = 32 * 1024 * 1024
STALE_AFTER_SECONDS = 300
FIELDS = {"schema", "count", "payloadBytes", "reviewRequiredCount", "oldestObservedAt"}


def validate_upload_summary(value: Any, *, now: int) -> Dict[str, Any]:
    """어긋나면 ValueError — 호출자는 저장하지 않고 INVALID 로 남긴다."""
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("INVALID_UPLOAD_SUMMARY")
    limits = {"schema": (1, 1), "count": (0, MAX_OUTBOX_ITEMS),
              "payloadBytes": (0, MAX_OUTBOX_BYTES), "reviewRequiredCount": (0, value.get("count", 0))}
    for key, (minimum, maximum) in limits.items():
        v = value[key]
        if isinstance(v, bool) or type(v) is not int or type(maximum) is not int or not minimum <= v <= maximum:
            raise ValueError("INVALID_UPLOAD_SUMMARY")
    oldest = value["oldestObservedAt"]
    if oldest is not None and (isinstance(oldest, bool) or type(oldest) is not int or not 0 <= oldest <= now):
        raise ValueError("INVALID_UPLOAD_SUMMARY")
    if ((value["count"] == 0 and (value["payloadBytes"] != 0 or oldest is not None))
            or (value["count"] > 0 and value["payloadBytes"] == 0)):
        raise ValueError("INVALID_UPLOAD_SUMMARY")
    return dict(value)


def reported_upload_summary(summary_json: Optional[str], reported_at: Any, *, now: int,
                            session_id: Optional[str] = None, summary_session: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], str]:
    """저장된 보고를 읽기 전용으로 판정한다. 없음·손상·다른 세션 = **0 이 아니라** UNREPORTED/INVALID/SESSION_CHANGED."""
    if summary_json is None or summary_json == "":
        return None, "UNREPORTED"
    if session_id is not None and summary_session is not None and summary_session != session_id:
        return None, "SESSION_CHANGED"
    try:
        reported = int(reported_at)
        if isinstance(reported_at, bool) or not 0 <= reported <= now:
            raise ValueError()
        summary = validate_upload_summary(json.loads(summary_json), now=reported)
    except (ValueError, TypeError):
        return None, "INVALID"
    return {**summary, "reportedAt": reported}, ("STALE" if now - reported > STALE_AFTER_SECONDS else "FRESH")
