"""운영 화면 「어제 결과 · 오늘 진행」 요약 — 코덱스 1.22.0 `/collector/v2/daily` 이식판 (5차 · 2026-09-22)

우리 식으로 다시 쓴 점
  · 완료 = 그날 `collected_serp` 에 저장된 키워드 수(전량·조기 종료) — 관측 원장이 있으면 부분(positive) 수도 따로 센다.
  · 대상 = 오늘 유니버스(호출자가 넘김) — v2 원장이 있으면 원장 수를 우선.
  · 미해결 = collector_catalog.unresolved_count (못 재면 None).
  · 기계 = heartbeat machines (uploadSummary 포함) — v2 워커가 아니어도 보인다(종전 경로 기계).
  · 실패·못 잰 값은 **None** 으로 남긴다(0 으로 찍지 않는다).
⚠️ stdlib 만 · 읽기 전용.
"""
from datetime import date, timedelta
from typing import Any, Dict, Optional


def _has_table(conn, name: str) -> bool:
    try:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None
    except Exception:
        return False


def _count(conn, sql, args=()) -> Optional[int]:
    try:
        r = conn.execute(sql, args).fetchone()
        return int(r[0]) if r and r[0] is not None else 0
    except Exception:
        return None


def day_block(conn, day: str, universe_total: Optional[int]) -> Dict[str, Any]:
    """한 날의 완료·부분·남음."""
    completed = _count(conn, "SELECT COUNT(*) FROM collected_serp WHERE collected_date=?", (day,))
    # 🎯 대표 확정(2026-09-24) — 부분 수집이어도 추적 대상을 다 찾은 키워드는 「완료」로 센다(수집 쪽 판정과 같은 규칙).
    _found = _has_table(conn, "collector_found_done")
    if _found:
        completed = _count(conn, "SELECT COUNT(*) FROM (SELECT keyword FROM collected_serp WHERE collected_date=? "
                                 "UNION SELECT keyword FROM collector_found_done WHERE collected_date=?)", (day, day))
    partial = None
    if _has_table(conn, "collector_observations"):
        if _found:
            partial = _count(conn, "SELECT COUNT(DISTINCT keyword) FROM collector_observations "
                                   "WHERE collected_date=? AND kind='positive' AND keyword NOT IN "
                                   "(SELECT keyword FROM collector_found_done WHERE collected_date=?)", (day, day))
        else:
            partial = _count(conn, "SELECT COUNT(DISTINCT keyword) FROM collector_observations "
                                   "WHERE collected_date=? AND kind='positive'", (day,))
    jobs_total = None
    if _has_table(conn, "collector_coord_jobs"):
        jobs_total = _count(conn, "SELECT COUNT(*) FROM collector_coord_jobs WHERE day=? AND kind='daily'", (day,))
        if jobs_total == 0:
            jobs_total = None
    total = jobs_total if jobs_total is not None else universe_total
    remaining = (max(0, total - completed) if (total is not None and completed is not None) else None)
    return {"day": day, "total": total, "completed": completed, "partial": partial, "remaining": remaining}


def summary(conn, today: str, universe_total: Optional[int], unresolved: Optional[int],
            machines: Any, control: Any, pending_requests: Optional[int], enabled: bool, server_now: int) -> Dict[str, Any]:
    yesterday = (date.fromisoformat(today) - timedelta(days=1)).isoformat()
    t = day_block(conn, today, universe_total)
    t["unresolved"] = unresolved
    y = day_block(conn, yesterday, None)
    return {"protocol": 2, "enabled": enabled, "serverNow": server_now, "day": today, "yesterdayDay": yesterday,
            "today": t, "yesterday": y, "machines": machines if isinstance(machines, list) else None,
            "control": control if isinstance(control, dict) else None, "pendingRequests": pending_requests}
