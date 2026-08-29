"""수집 즉시 순위 기록 — 24시간 분산 수집(2026-08-05)의 서버 짝.

배경: 종전에는 새벽 01~07시에 전 키워드를 모아두고 **08:00 배치가 한 번에** 순위를
기록했다. 그런데 한 IP 에서 6시간 동안 3,800여 회를 보내는 속도가 네이버의
「짧은 시간 내에 너무 많은 요청」 문턱을 건드려 IP 가 차단됐다(2026-08-05 실사고).

대응으로 수집을 24시간에 흩뿌리면, 08:00 시점엔 그날치의 3분의 1만 도착해 있어
「모아뒀다 한 번에 기록」 방식이 성립하지 않는다. 그래서 **키워드 1건이 올라온
바로 그 순간 그 키워드의 순위를 기록**한다. 배치 창 개념이 사라지고, 「수집분이
오늘/어제 것이어야 한다」는 서빙 창 의존도 함께 약해진다.

기록 규칙은 기존과 동일하게 **하루 1점**(당일 갱신)이라, 08:00 배치가 같은 키워드를
다시 기록해도 행이 늘지 않는다(양쪽 경로 공존 안전).
"""
import logging
import os
import sqlite3
from datetime import date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _tracked_targets(conn, keyword: str) -> List[Dict[str, Any]]:
    """이 키워드를 추적 중인 상품(축A)."""
    try:
        return [dict(r) for r in conn.execute("""
            SELECT k.id AS keyword_id, p.id AS product_id, p.product_url
              FROM tracked_keywords k
              JOIN tracked_products p ON p.id = k.product_id
             WHERE k.keyword = ?
        """, (keyword,))]
    except Exception as e:
        logger.warning(f"[rank_record] 추적 상품 조회 실패 [{keyword}]: {e}")
        return []


def _client_targets(conn, keyword: str) -> List[Dict[str, Any]]:
    """이 키워드를 쓰는 업체(축B).

    배치(`_collect_all_keywords`)와 같은 두 출처를 본다 —
      · `clients.main_keywords` 쉼표 목록
      · `client_analyses` 에 그 키워드 분석 이력이 있는 업체
    대상 조건도 배치와 같은 한 곳(tracking_eligibility)으로 판정한다.

    ⚠️ 2026-08-29: 종전엔 4조건(활성·자동분석·광고주·스토어)이 여기 따로 박혀 있어
       **추적 ON·추적 기간이 빠져 있었다** — 8/28 자격 통일이 배치·수집만 고치고
       이 즉시 기록 경로를 빠뜨린 것. 계약 끝난 업체도 다른 업체와 키워드가 겹치면
       수집이 올라올 때마다 여기로 계속 기록됐다. 같은 날 「그만 재기」 억제도 함께
       건다(억제 키워드는 이력 갈래로 되살아나면 안 된다 — 배치와 같은 규칙).
    """
    try:
        from tracking_eligibility import eligible_clients_sql
        rows = [dict(r) for r in conn.execute(
            eligible_clients_sql("id, name, main_keywords, naver_store_url"))]
    except Exception as e:
        logger.warning(f"[rank_record] 업체 조회 실패 [{keyword}]: {e}")
        return []
    try:
        analyzed = {r[0] for r in conn.execute(
            "SELECT DISTINCT client_id FROM client_analyses WHERE keyword = ?", (keyword,))}
    except Exception:
        analyzed = set()
    try:
        from keyword_mute import muted_map
        _muted = muted_map(conn)
    except Exception:
        _muted = {}

    out = []
    for c in rows:
        if not (c.get("naver_store_url") or "").strip():
            continue
        if keyword in _muted.get(c["id"], ()):
            continue   # 그만 재기 지정 — 이 업체 기록에는 적지 않는다
        if c["id"] in analyzed:
            out.append(c)
            continue
        listed = {k.strip() for k in (c.get("main_keywords") or "").split(",") if k.strip()}
        if keyword in listed:
            out.append(c)
    return out


def _save_client_rank_daily(conn, client_id: int, keyword: str, product_url: str,
                            rank: Optional[int], page: Optional[int], check_type: str):
    """업체 순위 — 당일 1점(스케줄러 `_save_client_rank` 와 같은 규칙)."""
    today = date.today().isoformat()
    row = conn.execute(
        """SELECT id FROM client_rank_history
            WHERE client_id=? AND keyword=? AND DATE(checked_at)=? AND check_type=?""",
        (client_id, keyword, today, check_type)).fetchone()
    if row:
        conn.execute(
            """UPDATE client_rank_history
                  SET rank_position=?, page_number=?, checked_at=datetime('now','localtime')
                WHERE id=?""", (rank, page, row["id"]))
    else:
        conn.execute(
            """INSERT INTO client_rank_history
                   (client_id, keyword, product_url, rank_position, page_number, check_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (client_id, keyword, product_url or '', rank, page, check_type))


def record_ranks_for_keyword(keyword: str, prods: List[Dict[str, Any]],
                             check_type: str = "scheduled") -> Dict[str, int]:
    """수집분 1건으로 그 키워드의 순위를 즉시 기록한다.

    prods = `collector._normalize_collected` 를 거친 목록(배치가 쓰던 것과 같은 형태).
    실패해도 예외를 밖으로 내지 않는다 — 업로드 자체는 성공시켜야 수집이 이어진다.
    """
    kw = (keyword or "").strip()
    if not kw or not prods:
        return {"products": 0, "clients": 0}

    try:
        from naver_crawler import find_product_rank_from_cache
        from database import save_ranking_daily
    except Exception as e:
        logger.warning(f"[rank_record] 순위 판정 모듈 로드 실패: {e}")
        return {"products": 0, "clients": 0}

    n_prod = n_client = 0
    conn = _conn()
    try:
        # ── 축A: 추적 상품 ──
        for t in _tracked_targets(conn, kw):
            try:
                rank, page, _competitors = find_product_rank_from_cache(
                    kw, t["product_url"], prods)
                save_ranking_daily(
                    product_id=t["product_id"], keyword_id=t["keyword_id"], keyword=kw,
                    rank_position=rank, page_number=page, check_type=check_type)
                n_prod += 1
                if rank is not None:
                    # 매칭된 순간에만 확보되는 실제 스토어명으로 슬러그 자가치유(공짜)
                    try:
                        from database import heal_tracked_product_info
                        heal_tracked_product_info(t["product_id"], t["product_url"], prods)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[rank_record] 상품 순위 기록 실패 [{kw}/{t.get('product_id')}]: {e}")

        # ── 축B: 업체 ──
        for c in _client_targets(conn, kw):
            try:
                rank, page, _ = find_product_rank_from_cache(kw, c["naver_store_url"], prods)
                _save_client_rank_daily(conn, c["id"], kw, c["naver_store_url"],
                                        rank, page, check_type)
                n_client += 1
            except Exception as e:
                logger.warning(f"[rank_record] 업체 순위 기록 실패 [{kw}/{c.get('id')}]: {e}")
        conn.commit()
    except Exception as e:
        logger.error(f"[rank_record] 순위 기록 중단 [{kw}]: {e}")
    finally:
        conn.close()

    if n_prod or n_client:
        logger.info(f"[rank_record] {kw} — 상품 {n_prod}건 · 업체 {n_client}건 순위 기록")
    return {"products": n_prod, "clients": n_client}
