"""
업체별 분석 관리 대시보드 API
기존 main.py 수정 없이 새 파일로 추가 — include_router 2줄만 추가
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date
import sqlite3
import os
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cd", tags=["client-dashboard"])

DB_PATH = os.getenv("DB_PATH", "logic_data.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_client_dashboard_db():
    """업체 대시보드용 테이블 생성 (기존 테이블 수정 없음)"""
    conn = _get_conn()
    try:
        conn.executescript("""
            /* 업체별 분석 스냅샷 — 재분석 시 덮어쓰기 */
            CREATE TABLE IF NOT EXISTS client_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                product_url TEXT DEFAULT '',
                analysis_json TEXT NOT NULL DEFAULT '{}',
                volume_json TEXT DEFAULT '{}',
                related_json TEXT DEFAULT '{}',
                shop_products_json TEXT DEFAULT '[]',
                advertiser_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_client_analyses_key
            ON client_analyses(client_id, keyword);

            /* 업체별 순위 추적 이력 — 일자별 누적 */
            CREATE TABLE IF NOT EXISTS client_rank_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                product_url TEXT DEFAULT '',
                rank_position INTEGER,
                page_number INTEGER,
                check_type TEXT DEFAULT 'manual',
                checked_at TEXT DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_client_rank_lookup
            ON client_rank_history(client_id, keyword, checked_at);

            /* 일일 조회 횟수 제한 */
            CREATE TABLE IF NOT EXISTS daily_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 0,
                usage_date TEXT NOT NULL,
                query_count INTEGER DEFAULT 0,
                UNIQUE(user_id, usage_date)
            );
        """)
        conn.commit()
        logger.info("[ClientDashboard] DB tables initialized")
    except Exception as e:
        logger.error(f"[ClientDashboard] DB init error: {e}")
    finally:
        conn.close()


# ==================== Request / Response Models ====================

class SaveAnalysisRequest(BaseModel):
    client_id: int
    keyword: str
    product_url: Optional[str] = ''
    analysis_data: Optional[dict] = {}
    volume_data: Optional[dict] = {}
    related_data: Optional[dict] = {}
    shop_products: Optional[list] = []
    advertiser_data: Optional[dict] = {}


class SaveRankRequest(BaseModel):
    client_id: int
    keyword: str
    product_url: Optional[str] = ''
    rank_position: Optional[int] = None
    page_number: Optional[int] = None
    check_type: Optional[str] = 'manual'


# ==================== 업체 목록 ====================

@router.get("/my-clients")
async def my_clients(user_id: int = 0):
    """등록된 업체 목록 + 최근 분석 요약"""
    conn = _get_conn()
    try:
        # user_id=0 이면 전체 조회 (관리자), 아니면 본인 업체만
        if user_id > 0:
            clients = conn.execute("""
                SELECT c.*,
                    (SELECT COUNT(*) FROM client_analyses ca WHERE ca.client_id = c.id) as analysis_count,
                    (SELECT MAX(ca.updated_at) FROM client_analyses ca WHERE ca.client_id = c.id) as last_analyzed
                FROM clients c
                WHERE c.status = 'active' AND c.created_by = ?
                ORDER BY c.updated_at DESC
            """, (user_id,)).fetchall()
        else:
            clients = conn.execute("""
                SELECT c.*,
                    (SELECT COUNT(*) FROM client_analyses ca WHERE ca.client_id = c.id) as analysis_count,
                    (SELECT MAX(ca.updated_at) FROM client_analyses ca WHERE ca.client_id = c.id) as last_analyzed
                FROM clients c
                WHERE c.status = 'active'
                ORDER BY c.updated_at DESC
            """).fetchall()

        result = []
        for c in clients:
            row = dict(c)
            # 이 업체에 저장된 분석 키워드 목록
            analyses = conn.execute("""
                SELECT keyword, product_url, updated_at
                FROM client_analyses
                WHERE client_id = ?
                ORDER BY updated_at DESC
            """, (c['id'],)).fetchall()
            row['analyzed_keywords'] = [dict(a) for a in analyses]

            # 최근 순위 요약
            latest_ranks = conn.execute("""
                SELECT keyword, rank_position, checked_at
                FROM client_rank_history
                WHERE client_id = ?
                AND id IN (
                    SELECT MAX(id) FROM client_rank_history
                    WHERE client_id = ?
                    GROUP BY keyword
                )
            """, (c['id'], c['id'])).fetchall()
            row['latest_ranks'] = [dict(r) for r in latest_ranks]

            result.append(row)

        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"[my-clients] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== 분석 결과 저장/조회 ====================

@router.post("/analyze")
async def save_analysis(req: SaveAnalysisRequest):
    """분석 결과 저장 (기존 키워드면 덮어쓰기, 새 키워드면 추가)"""
    conn = _get_conn()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 업체 존재 확인
        client = conn.execute("SELECT id FROM clients WHERE id = ?", (req.client_id,)).fetchone()
        if not client:
            raise HTTPException(status_code=404, detail="업체를 찾을 수 없습니다.")

        existing = conn.execute(
            "SELECT id FROM client_analyses WHERE client_id = ? AND keyword = ?",
            (req.client_id, req.keyword)
        ).fetchone()

        params = (
            req.product_url,
            json.dumps(req.analysis_data, ensure_ascii=False),
            json.dumps(req.volume_data, ensure_ascii=False),
            json.dumps(req.related_data, ensure_ascii=False),
            json.dumps(req.shop_products, ensure_ascii=False),
            json.dumps(req.advertiser_data, ensure_ascii=False),
            now,
        )

        if existing:
            conn.execute("""
                UPDATE client_analyses
                SET product_url=?, analysis_json=?, volume_json=?,
                    related_json=?, shop_products_json=?, advertiser_json=?,
                    updated_at=?
                WHERE client_id=? AND keyword=?
            """, params + (req.client_id, req.keyword))
            msg = "분석 결과가 업데이트되었습니다."
        else:
            conn.execute("""
                INSERT INTO client_analyses
                (client_id, keyword, product_url, analysis_json, volume_json,
                 related_json, shop_products_json, advertiser_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (req.client_id, req.keyword) + params[:6] + (now, now))
            msg = "분석 결과가 저장되었습니다."

        conn.commit()
        return {"success": True, "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[save-analysis] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/{client_id}/analysis")
async def get_analysis(client_id: int, keyword: Optional[str] = None):
    """저장된 분석 결과 조회"""
    conn = _get_conn()
    try:
        if keyword:
            row = conn.execute(
                "SELECT * FROM client_analyses WHERE client_id=? AND keyword=?",
                (client_id, keyword)
            ).fetchone()
            if not row:
                return {"success": False, "message": "저장된 분석 결과가 없습니다."}
            data = _parse_analysis_row(row)
            return {"success": True, "data": data}
        else:
            rows = conn.execute(
                "SELECT * FROM client_analyses WHERE client_id=? ORDER BY updated_at DESC",
                (client_id,)
            ).fetchall()
            return {"success": True, "data": [_parse_analysis_row(r) for r in rows]}
    except Exception as e:
        logger.error(f"[get-analysis] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


def _parse_analysis_row(row):
    """DB row를 JSON 파싱된 dict로 변환"""
    d = dict(row)
    for key, json_key in [
        ('analysis_json', 'analysis_data'),
        ('volume_json', 'volume_data'),
        ('related_json', 'related_data'),
        ('shop_products_json', 'shop_products'),
        ('advertiser_json', 'advertiser_data'),
    ]:
        try:
            d[json_key] = json.loads(d.pop(key, '{}'))
        except (json.JSONDecodeError, TypeError):
            d[json_key] = {}
    return d


# ==================== 순위 추적 이력 ====================

@router.post("/rank-save")
async def save_rank(req: SaveRankRequest):
    """순위 체크 결과 저장 (일자별 누적)"""
    conn = _get_conn()
    try:
        conn.execute("""
            INSERT INTO client_rank_history
            (client_id, keyword, product_url, rank_position, page_number, check_type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (req.client_id, req.keyword, req.product_url,
              req.rank_position, req.page_number, req.check_type))
        conn.commit()
        return {"success": True, "message": "순위 기록이 저장되었습니다."}
    except Exception as e:
        logger.error(f"[save-rank] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/{client_id}/rank-history")
async def get_rank_history(client_id: int, keyword: Optional[str] = None, days: int = 90):
    """순위 추적 이력 조회"""
    conn = _get_conn()
    try:
        if keyword:
            rows = conn.execute("""
                SELECT * FROM client_rank_history
                WHERE client_id=? AND keyword=?
                AND checked_at >= datetime('now','localtime', ?)
                ORDER BY checked_at ASC
            """, (client_id, keyword, f'-{days} days')).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM client_rank_history
                WHERE client_id=?
                AND checked_at >= datetime('now','localtime', ?)
                ORDER BY checked_at ASC
            """, (client_id, f'-{days} days')).fetchall()

        return {"success": True, "data": [dict(r) for r in rows]}
    except Exception as e:
        logger.error(f"[rank-history] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ==================== 일일 조회 제한 ====================

@router.get("/usage/check")
async def check_usage(user_id: int = 0):
    """일일 조회 횟수 확인"""
    conn = _get_conn()
    try:
        today = date.today().isoformat()
        row = conn.execute(
            "SELECT query_count FROM daily_usage WHERE user_id=? AND usage_date=?",
            (user_id, today)
        ).fetchone()
        count = row['query_count'] if row else 0

        # 사용자 역할에 따른 제한
        user = conn.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
        role = user['role'] if user else 'readonly'
        limit = -1 if role in ('admin', 'manager') else 3  # -1 = 무제한

        return {
            "success": True,
            "data": {
                "used": count,
                "limit": limit,
                "remaining": limit - count if limit > 0 else -1,
                "can_query": limit < 0 or count < limit
            }
        }
    except Exception as e:
        logger.error(f"[check-usage] {e}")
        return {"success": True, "data": {"used": 0, "limit": -1, "remaining": -1, "can_query": True}}
    finally:
        conn.close()


@router.post("/usage/increment")
async def increment_usage(user_id: int = 0):
    """조회 횟수 1 증가"""
    conn = _get_conn()
    try:
        today = date.today().isoformat()
        conn.execute("""
            INSERT INTO daily_usage (user_id, usage_date, query_count)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id, usage_date)
            DO UPDATE SET query_count = query_count + 1
        """, (user_id, today))
        conn.commit()
        return {"success": True}
    except Exception as e:
        logger.error(f"[increment-usage] {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
