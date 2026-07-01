"""
data_quality.py — 분석 지표의 신뢰 등급(데이터 상태) 공통 모델.

모든 핵심 수치에 '어떻게 얻은 값인지'를 붙여, 화면은 신뢰 뱃지로,
AI는 불확실성 정보로 활용한다. 기존 응답 필드는 그대로 두고 부가 정보만 더한다.
(외부 의존성 없음 — 오프라인 단위 테스트 가능)
"""

# ── 데이터 상태 ──
MEASURED = "measured"              # HTML/API에서 직접 확인된 값
CROSS_VERIFIED = "cross_verified"  # 2개 경로가 일치 → 최고 신뢰
ESTIMATED = "estimated"            # 순위 등 간접 추정치
UNAVAILABLE = "unavailable"        # 확보 실패(값 없음, 0 아님)

# ── 상태 → 신뢰도 등급 ──
_CONFIDENCE = {
    CROSS_VERIFIED: "high",
    MEASURED: "medium",
    ESTIMATED: "low",
    UNAVAILABLE: "none",
}

# ── 상태 → 한글 라벨(화면 뱃지용) ──
_LABEL = {
    CROSS_VERIFIED: "교차확인",
    MEASURED: "실측",
    ESTIMATED: "추정",
    UNAVAILABLE: "미확인",
}


def confidence(status: str) -> str:
    """상태 → 신뢰도(high/medium/low/none)."""
    return _CONFIDENCE.get(status, "none")


def label(status: str) -> str:
    """상태 → 한글 라벨."""
    return _LABEL.get(status, "미확인")


def metric(value, status: str, sources=None, note: str = "") -> dict:
    """지표 하나의 신뢰 정보 dict (응답의 data_quality[...]에 넣는다)."""
    return {
        "value": value,
        "status": status,
        "confidence": confidence(status),
        "label": label(status),
        "sources": list(sources) if sources else [],
        "note": note,
    }


def status_from_presence(value) -> str:
    """값이 있으면 measured, 없으면(None) unavailable."""
    return MEASURED if value is not None else UNAVAILABLE


def cross_check(primary, secondary, tol=0, prefer="primary"):
    """
    두 경로 값을 대조해 (선택값, 상태, 비고)를 반환.
    - 둘 다 있고 오차 tol 이내로 일치 → cross_verified
    - 둘 다 있는데 불일치 → measured(선택값) + 불일치 비고
    - 한쪽만 있음 → measured(그 값)
    - 둘 다 없음 → unavailable
    """
    p_ok = primary is not None
    s_ok = secondary is not None
    if p_ok and s_ok:
        try:
            agree = abs(float(primary) - float(secondary)) <= tol
        except (TypeError, ValueError):
            agree = (primary == secondary)
        if agree:
            return primary, CROSS_VERIFIED, ""
        chosen = primary if prefer == "primary" else secondary
        return chosen, MEASURED, f"경로 불일치(primary={primary}, secondary={secondary})"
    if p_ok:
        return primary, MEASURED, ""
    if s_ok:
        return secondary, MEASURED, ""
    return None, UNAVAILABLE, ""
