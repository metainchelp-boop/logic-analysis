"""순위 기록 순서 가드 — 코덱스 1.22.0 `_claim_rank_projection` 이식판 (2026-09-22 · 자체 개발 3차)

왜 필요한가
  1차(#256)부터 순위는 세 갈래로 적힌다 — 업로드 즉시(전량·양성만) · 08:00 배치의 수집분 재기록.
  그러면 **옛 전량 수집분이 새 양성 순위를 덮는** 순서 사고가 생긴다:
    10:00 전량 수집 A(300위 안에 없음 → None) → 10:30 부분 수집 B(찾음 · 37위) → 08:00 배치가 A 를 다시 재생 → None 으로 회귀.
  그래서 대상(축·id·키워드·날짜)마다 **마지막으로 적은 관측의 finishedAt** 을 남기고, 그보다 **오래된** 관측은 적지 않는다.

규칙
  · 같은 관측(같은 finishedAt)은 다시 적어도 된다(멱등 · 배치 재생).
  · 봉투 없는 구확장 업로드는 「지금」을 finishedAt 으로 삼는다 — 항상 최신이므로 종전과 똑같이 적힌다(무회귀).
  · 가드 조회가 실패하면 **거르지 않는다**(기록이 조용히 멈추는 쪽이 더 나쁜 고장 — 이 저장소 원칙).
⚠️ stdlib 만. DDL 은 멱등. 표 이름은 코덱스와 같다(`collector_rank_projections`).
"""
import logging
import time
from typing import Any, Dict, Iterable, Optional, Set, Tuple

logger = logging.getLogger(__name__)

DDL = """
CREATE TABLE IF NOT EXISTS collector_rank_projections (
    axis           TEXT NOT NULL,
    target_id      INTEGER NOT NULL,
    keyword        TEXT NOT NULL,
    collected_date TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    finished_at    INTEGER NOT NULL,
    PRIMARY KEY (axis, target_id, keyword, collected_date)
)
"""


def init_db(conn) -> None:
    conn.execute(DDL)


def finished_epoch(observation: Optional[Dict[str, Any]], now: Optional[float] = None) -> int:
    """관측 봉투의 finishedAt → epoch 초. 봉투가 없거나 못 읽으면 「지금」(= 항상 최신 · 종전 동작)."""
    now_i = int(now if now is not None else time.time())
    if not isinstance(observation, dict):
        return now_i
    raw = observation.get("finishedAt")
    if raw in (None, ""):
        return now_i
    try:
        from collector_time import as_instant
        return int(as_instant(raw).timestamp())
    except Exception:
        return now_i


def observation_key(observation: Optional[Dict[str, Any]]) -> str:
    if isinstance(observation, dict) and observation.get("observationId"):
        return str(observation["observationId"]).lower()
    return "legacy"


def claim(conn, axis: str, target_id: int, keyword: str, day: str, observation_id: str, finished_at: int) -> bool:
    """이 대상에 이 관측을 적어도 되는가. 더 새로운 관측이 이미 적혀 있으면 False."""
    try:
        init_db(conn)
        old = conn.execute("SELECT finished_at FROM collector_rank_projections "
                           "WHERE axis=? AND target_id=? AND keyword=? AND collected_date=?",
                           (axis, int(target_id), keyword, day)).fetchone()
        if old is not None and int(old[0]) > int(finished_at):
            return False
        conn.execute("""INSERT INTO collector_rank_projections
            (axis, target_id, keyword, collected_date, observation_id, finished_at) VALUES (?,?,?,?,?,?)
            ON CONFLICT(axis, target_id, keyword, collected_date) DO UPDATE SET
            observation_id=excluded.observation_id, finished_at=excluded.finished_at""",
                     (axis, int(target_id), keyword, day, observation_id, int(finished_at)))
        return True
    except Exception as e:
        logger.warning(f"[rank_guard] 순서 가드 조회 실패(거르지 않음) [{keyword}/{axis}:{target_id}]: {e}")
        return True


def newer_targets(conn, keyword: str, day: str, finished_at: int) -> Set[Tuple[str, int]]:
    """이 관측보다 **새로운** 관측이 이미 적힌 대상 집합 — 배치 재생 때 건너뛸 것."""
    try:
        init_db(conn)
        return {(r[0], int(r[1])) for r in conn.execute(
            "SELECT axis, target_id FROM collector_rank_projections "
            "WHERE keyword=? AND collected_date=? AND finished_at > ?", (keyword, day, int(finished_at)))}
    except Exception as e:
        logger.warning(f"[rank_guard] 순서 가드 조회 실패(거르지 않음) [{keyword}]: {e}")
        return set()


def purge_old(conn, days: int = 30) -> int:
    try:
        init_db(conn)
        cur = conn.execute("DELETE FROM collector_rank_projections WHERE collected_date < date('now','localtime', ?)",
                           (f"-{int(days)} day",))
        conn.commit()
        return cur.rowcount or 0
    except Exception:
        return 0
