"""
브라우저 수집기(크롬 확장) 연동 — 2026-08-03

배경: 2026-07-31 네이버 '검색 > 쇼핑' API가 종료(404 SE05)되어 서버에서 검색 결과를
      가져올 방법이 사라졌다. 서버 IP 직접 요청은 봇으로 차단(418)된다.
      실제 사무실 PC의 브라우저는 정상 조회되므로, 사내 전용 크롬 확장이 새벽에
      검색 결과를 모아 이 API로 올려주고 배치는 그 값을 쓴다.

설계 원칙
  · 이 모듈은 '받아서 저장'만 한다. 순위 판정·분석은 기존 코드를 그대로 쓴다.
  · 인증은 전용 토큰(COLLECTOR_TOKEN) 하나. 미설정이면 전 경로를 막는다(기본 안전).
  · 수집분은 collected_serp 에 원본 그대로 쌓고, 배치가 그날치를 읽어간다.
  · 서버는 절대 네이버를 직접 호출하지 않는다(차단·약관 위험을 브라우저 쪽에 두지 않기 위함이 아니라,
    서버 IP로는 애초에 불가능하기 때문).
"""
import os
import json
import sqlite3
import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/collector", tags=["collector"])

DB_PATH = os.getenv("DB_PATH", "/app/data/logic_data.db")
COLLECTOR_TOKEN = os.getenv("COLLECTOR_TOKEN", "")

# 수집기가 한 번에 가져갈 키워드 상한 — PC 한 대가 새벽에 소화 가능한 양으로 제한
MAX_KEYWORDS = 1200


def init_collector_db():
    """수집 테이블 생성 (멱등)."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS collected_serp (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL,
                collected_date TEXT NOT NULL,
                total INTEGER DEFAULT 0,
                products_json TEXT NOT NULL,
                product_count INTEGER DEFAULT 0,
                source TEXT DEFAULT 'extension',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_collected_serp_uniq
                ON collected_serp(keyword, collected_date);
            CREATE INDEX IF NOT EXISTS idx_collected_serp_date
                ON collected_serp(collected_date);
        """)
        conn.commit()
        logger.info("수집 테이블 준비 완료")
    finally:
        conn.close()


def _auth(token: Optional[str]):
    """전용 토큰 검증 — 미설정이면 전 경로 차단(설정 실수로 열리는 것 방지)."""
    if not COLLECTOR_TOKEN:
        raise HTTPException(status_code=503, detail="수집기 토큰이 서버에 설정되지 않았습니다.")
    if not token or token != COLLECTOR_TOKEN:
        raise HTTPException(status_code=401, detail="수집기 인증 실패")


# ==================== 1) 수집할 키워드 목록 ====================

@router.get("/keywords")
def get_collect_keywords(x_collector_token: str = Header(None)):
    """확장이 오늘 수집할 키워드 목록을 받아간다.

    기존 배치(_run_rank_tracking)와 같은 출처를 쓴다 — 추적 상품 키워드 + 업체 분석 이력 키워드.
    오늘 이미 수집된 키워드는 빼고 준다(중간에 멈췄다 다시 켜도 이어서 진행).
    """
    _auth(x_collector_token)
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        kws = set()
        for sql in (
            "SELECT DISTINCT keyword FROM tracked_keywords",
            "SELECT DISTINCT keyword FROM client_analyses",
        ):
            try:
                for r in conn.execute(sql).fetchall():
                    k = (r["keyword"] or "").strip()
                    if k:
                        kws.add(k)
            except Exception as e:  # 테이블 구성이 다른 환경에서도 죽지 않게
                logger.warning(f"[collector] 키워드 조회 일부 실패({sql[:40]}): {e}")

        done = {r["keyword"] for r in conn.execute(
            "SELECT keyword FROM collected_serp WHERE collected_date = ?", (today,)).fetchall()}
        todo = sorted(kws - done)[:MAX_KEYWORDS]
        return {"success": True, "date": today,
                "total": len(kws), "done": len(done), "todo": len(todo),
                "keywords": todo}
    finally:
        conn.close()


# ==================== 2) 수집 결과 업로드 ====================

class SerpProduct(BaseModel):
    rank: int
    productId: Optional[str] = ""
    title: Optional[str] = ""
    link: Optional[str] = ""
    price: Optional[str] = ""
    mallName: Optional[str] = ""
    brand: Optional[str] = ""
    category1: Optional[str] = ""
    category2: Optional[str] = ""
    category3: Optional[str] = ""
    reviewCount: Optional[str] = ""


class SerpUpload(BaseModel):
    keyword: str
    total: int = 0
    products: List[SerpProduct] = []


@router.post("/serp")
def upload_serp(req: SerpUpload, x_collector_token: str = Header(None)):
    """확장이 키워드 1건 수집 결과를 올린다. 같은 날 같은 키워드는 덮어쓴다."""
    _auth(x_collector_token)
    kw = (req.keyword or "").strip()
    if not kw:
        raise HTTPException(status_code=400, detail="keyword 가 비어 있습니다.")
    # 빈 수집은 저장하지 않는다 — '수집 실패'가 '미노출'로 굳는 것을 막기 위함
    # (2026-08-01~03 실제로 1,992건이 그렇게 오염됐다.)
    if not req.products:
        raise HTTPException(status_code=400, detail="상품이 0건입니다. 수집 실패로 보고 저장하지 않습니다.")

    today = date.today().isoformat()
    payload = json.dumps([p.model_dump() for p in req.products], ensure_ascii=False)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("""
            INSERT INTO collected_serp (keyword, collected_date, total, products_json, product_count)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(keyword, collected_date) DO UPDATE SET
                total=excluded.total, products_json=excluded.products_json,
                product_count=excluded.product_count,
                created_at=datetime('now','localtime')
        """, (kw, today, req.total, payload, len(req.products)))
        conn.commit()
        return {"success": True, "keyword": kw, "saved": len(req.products)}
    finally:
        conn.close()


# ==================== 3) 수집 현황 ====================

@router.get("/status")
def collect_status(x_collector_token: str = Header(None)):
    """오늘 얼마나 모였는지 — 확장 팝업·운영자 확인용."""
    _auth(x_collector_token)
    today = date.today().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT collected_date, COUNT(*) AS keywords, SUM(product_count) AS products,
                   MAX(created_at) AS last_at
            FROM collected_serp
            WHERE collected_date >= date('now','localtime','-6 day')
            GROUP BY collected_date ORDER BY collected_date DESC
        """).fetchall()
        return {"success": True, "today": today,
                "days": [dict(r) for r in rows]}
    finally:
        conn.close()


def _safe_int(v):
    """문자열 가격('12,900')·None 등을 정수로. 실패 시 0."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(str(v).replace(",", "").replace("원", "").strip() or 0)
    except (ValueError, TypeError):
        return 0


def _normalize_collected(p: dict) -> dict:
    """수집분 상품 1건을 _parse_api_item(naver_crawler.py) 출력과 '완전히 같은 키'로 변환한다.

    ⚠️ 이 정규화가 없으면 순위 매칭(find_product_rank_from_cache 는 product_url·product_id 를 읽음)과
    분석(auto_analysis 는 product_name·store_name 을 읽음)이 전부 빈값·미스매치가 되어,
    수집이 정상이어도 화면은 계속 '미노출'로 나온다. price 도 int 여야 산술이 깨지지 않는다.
    수집기(SerpProduct)는 productId·title·link·mallName·price(문자열)로 저장하므로 여기서 매핑한다.
    """
    return {
        "rank": p.get("rank", 0),
        "product_id": str(p.get("productId", "") or ""),
        "product_name": p.get("title", "") or "",
        "price": _safe_int(p.get("price")),
        "hprice": None,
        "store_name": p.get("mallName", "") or "",
        "image_url": p.get("image", "") or "",
        "product_url": p.get("link", "") or "",
        "brand": p.get("brand", "") or "",
        "maker": p.get("brand", "") or "",
        "category1": p.get("category1", "") or "",
        "category2": p.get("category2", "") or "",
        "category3": p.get("category3", "") or "",
        "product_type": "",
        # 리뷰/평점/구매수는 SERP 목록에 없다(_parse_api_item 도 0). 리뷰는 상세 크롤링 경로에서만.
        "review_count": 0,
        "rating": 0,
        "purchase_count": 0,
        # 수집분 표식 — 디버깅·감사용
        "review_count_collected": _safe_int(p.get("reviewCount")),
    }


def load_collected(keyword: str, on_date: Optional[str] = None) -> Optional[dict]:
    """배치용 — 수집분에서 키워드 1건을 꺼내 _parse_api_item 포맷으로 정규화해 돌려준다.

    반환: {'total': int, 'prods': [ _parse_api_item 과 동일 키의 dict, … ]} 또는 None.
    scheduler 의 find_product_rank_from_cache·auto_analysis 가 그대로 소비할 수 있어야 한다.
    """
    on_date = on_date or date.today().isoformat()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute(
            "SELECT total, products_json FROM collected_serp WHERE keyword=? AND collected_date=?",
            (keyword, on_date)).fetchone()
        if not r:
            return None
        try:
            raw = json.loads(r["products_json"] or "[]")
        except json.JSONDecodeError:
            return None
        if not raw:
            return None
        prods = [_normalize_collected(p) for p in raw]
        return {"total": r["total"] or 0, "prods": prods}
    finally:
        conn.close()
