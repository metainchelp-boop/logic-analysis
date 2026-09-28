"""오래된 순위 표시 규칙 — 「마지막으로 확인한 날짜」가 오늘 기준으로 며칠 전인가 (대표 지시 2026-09-28)

왜 필요한가
  2026-09-24 저녁부터 네이버가 수집기의 2페이지 요청을 거절한다(418). 1페이지(1~40위)는 매일 재지만,
  1페이지에서 추적 대상을 못 찾으면 **아무것도 적지 않는다**(부분 수집 = 찾은 순위만 · 2026-09-22 규칙).
  ⇒ 41~300위에 있던 상품은 **9/24 에 적힌 순위가 그대로 「현재 순위」 칸에 남는다.** 화면이 그 값을
     오늘 값처럼 보여 주면 거짓말이 된다. 그래서 순위는 그대로 두고 **언제 값인지**를 함께 내려 준다.

규칙(한 곳)
  · 수집기는 하루 한 번, 24시간에 나눠 잰다(전일 데이터 기준 · 대표 확정 2026-09-23).
    ⇒ 오늘·어제 확인한 순위 = 최신. **2일 전부터 「오래된 순위」.**
  · 날짜를 못 읽으면 None(모른다) — 오래됐다고 단정하지 않는다.

⚠️ stdlib 만 — 배포 게이트에 fastapi 가 없어 이 모듈은 가짜 DB 로 직접 시험한다.
⚠️ 순위 값·정렬·집계(노출·10위 안)는 바꾸지 않는다 — 표시에 「며칠 전 값」만 더한다(additive).
⚠️ ① 전산 portal-summary(`seo.keywordVolume[]` 3필드 계약)는 건드리지 않는다.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, Optional

STALE_AFTER_DAYS = 2      # 오늘(0)·어제(1) = 최신 · 2일 전부터 오래된 값


def _as_date(value: Any) -> Optional[date]:
    s = str(value or "").strip()
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def stale_days(last_checked: Any, today: Any = None) -> Optional[int]:
    """마지막 확인일이 오늘로부터 며칠 전인가. 읽을 수 없으면 None. 미래 날짜는 0."""
    d = _as_date(last_checked)
    if d is None:
        return None
    t = today if isinstance(today, date) else (_as_date(today) or date.today())
    return max(0, (t - d).days)


def is_stale(days: Optional[int]) -> bool:
    return days is not None and days >= STALE_AFTER_DAYS


def last_known(conn, client_id: int, keywords: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """창(최근 N일) 밖까지 포함해 키워드별 **마지막 기록**(순위·시각). 조회 실패는 빈 dict.

    보드의 「기록 대기」 줄이 실제로는 예전에 잰 적이 있는 키워드인지 가르는 데 쓴다 —
    8일 창을 벗어난 오래된 키워드를 「아직 수집 시간대가 안 왔다」고 보여 주면 안 된다.
    """
    kws = [str(k).strip() for k in keywords if str(k or "").strip()]
    if not kws:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    try:
        ph = ",".join("?" * len(kws))
        rows = conn.execute(
            f"SELECT keyword, rank_position, checked_at FROM client_rank_history "
            f"WHERE client_id=? AND keyword IN ({ph}) "
            f"AND id IN (SELECT MAX(id) FROM client_rank_history WHERE client_id=? AND keyword IN ({ph}) "
            f"GROUP BY keyword)",
            [client_id, *kws, client_id, *kws]).fetchall()
        for r in rows:
            out[str(r[0]).strip()] = {"rank": r[1], "at": r[2]}
    except Exception:
        return {}
    return out
