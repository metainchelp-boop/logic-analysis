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
            CREATE TABLE IF NOT EXISTS collect_requests (
                keyword TEXT PRIMARY KEY,
                requested_at TEXT DEFAULT (datetime('now','localtime')),
                status TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0
            );
        """)
        # 멱등 컬럼 가드 — attempts 없는 구스키마로 생성된 DB에도 안전하게 추가
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(collect_requests)").fetchall()}
            if "attempts" not in cols:
                conn.execute("ALTER TABLE collect_requests ADD COLUMN attempts INTEGER DEFAULT 0")
        except Exception as e:
            logger.warning(f"[collector] attempts 컬럼 가드 실패(무시): {e}")
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
    # 상품명·링크가 대부분 비면 확장 toProduct 필드 매핑 오류다 — 조용히 저장하면
    # 배치·분석이 빈 이름으로 오염되므로 여기서 소리내어 거부한다.
    filled = sum(1 for p in req.products if (p.title or "").strip() or (p.link or "").strip())
    if filled < max(1, int(len(req.products) * 0.2)):
        raise HTTPException(status_code=422,
                            detail="상품명·링크가 대부분 비어 있습니다 — 확장 필드 매핑 오류 의심. 팝업의 '수집 원본 샘플'을 확인하세요.")

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
        # 이 키워드가 요청 큐(주간 온디맨드)에 있었다면 완료 처리
        conn.execute("UPDATE collect_requests SET status='done' WHERE keyword=?", (kw,))
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
        pending = conn.execute(
            "SELECT COUNT(*) FROM collect_requests WHERE status='pending' AND attempts < 5").fetchone()[0]
        return {"success": True, "today": today, "pendingRequests": pending,
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
# ==================== 4) 주간 온디맨드 요청 큐 ====================

@router.get("/requests")
def get_pending_requests(x_collector_token: str = Header(None)):
    """확장이 1분 주기로 폴링 — 직원이 낮에 새 키워드를 분석하면 여기 쌓인다.

    소량(상한 10)만 내려 IP 부하를 묶는다. 수집·업로드되면 upload_serp 가 done 처리.
    """
    _auth(x_collector_token)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        # 오래된 완료분 정리(테이블 비대 방지)
        conn.execute("DELETE FROM collect_requests WHERE status='done' AND requested_at < datetime('now','localtime','-7 day')")
        # 5회 소진 후에도 재요청이 없는 사장 pending 도 7일 뒤 정리(계기판·테이블 비대 방지)
        conn.execute("DELETE FROM collect_requests WHERE status='pending' AND attempts >= 5 AND requested_at < datetime('now','localtime','-7 day')")
        # 전달 5회가 넘도록 수집이 안 된 키워드(오타·결과 0건)는 제외 — 1분마다 영원히
        # 재시도해 네이버를 계속 두드리는 폭주를 막는다. 직원이 그 키워드를 다시 분석하면
        # _enqueue_request 가 attempts 를 리셋해 5회 더 시도한다.
        rows = conn.execute("""
            SELECT keyword FROM collect_requests
            WHERE status='pending' AND attempts < 5
            ORDER BY requested_at ASC LIMIT 10
        """).fetchall()
        kws = [r["keyword"] for r in rows]
        if kws:
            conn.executemany(
                "UPDATE collect_requests SET attempts = attempts + 1 WHERE keyword=?",
                [(k,) for k in kws])
        conn.commit()
        return {"success": True, "keywords": kws}
    finally:
        conn.close()


def _enqueue_request(keyword: str):
    """수집분이 없는 키워드를 요청 큐에 넣는다(중복 무해 — 멱등).

    이미 done 인 키워드도 다시 pending 으로 되돌린다 — done 은 '그날 수집됨'일 뿐이라
    2일 이상 지나 서빙이 다시 miss 나면 재수집이 필요하기 때문.
    """
    kw = (keyword or "").strip()
    if not kw:
        return
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            conn.execute("""
                INSERT INTO collect_requests (keyword, status)
                VALUES (?, 'pending')
                ON CONFLICT(keyword) DO UPDATE SET
                    status='pending',
                    requested_at=datetime('now','localtime'),
                    attempts=0
                WHERE collect_requests.status != 'pending'
                   OR collect_requests.attempts >= 5
            """, (kw,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"[collector] 요청 큐 등록 실패(무시): {e}")


# ==================== 5) 검색 API 대체 서빙 ====================

def _to_api_item(p: dict) -> dict:
    """수집분 상품 1건 → 네이버 검색 API 원본 item 형식(역변환).

    search_naver_shopping_api 의 반환을 그대로 흉내내기 위한 것.
    소비자는 전부 _parse_api_item 을 거치므로, 그 함수가 읽는 키
    (title·productId·link·lprice·mallName·brand·maker·image·category1~3·productType)만 맞추면 된다.
    """
    return {
        "title": p.get("title", "") or "",
        "productId": str(p.get("productId", "") or ""),
        "link": p.get("link", "") or "",
        "lprice": str(_safe_int(p.get("price"))),
        "hprice": "",
        "mallName": p.get("mallName", "") or "",
        "image": "",
        "brand": p.get("brand", "") or "",
        "maker": p.get("brand", "") or "",
        "category1": p.get("category1", "") or "",
        "category2": p.get("category2", "") or "",
        "category3": p.get("category3", "") or "",
        "productType": "",
    }


def serve_from_collected(keyword: str, display: int = 100, start: int = 1,
                         enqueue_on_miss: bool = True) -> Optional[dict]:
    """죽은 쇼핑 검색 API 를 수집분으로 대체 서빙한다.

    search_naver_shopping_api 최상단에서 호출된다(원본 API 응답과 같은 형식으로 반환).
    · 오늘/어제(2일 내) 수집분이 있으면 → {'total':…, 'items':[원본형식…]} 로 페이징 서빙
    · 없으면 → 요청 큐에 등록하고 None (호출부가 기존 API 경로로 폴백 — API 부활 시 무회귀)

    이 한 지점으로 분석기·광고주 분석·키워드 노출·자동 분석이 전부 수집분 위에서 돌게 된다.
    낮 분석은 새벽(03시) 스냅샷 기준이라 '실시간'은 아니지만, 순위·시장 구도가 하루 안에
    급변하는 경우는 드물어 실사용상 차이가 작다.
    """
    kw = (keyword or "").strip()
    if not kw:
        return None
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("""
            SELECT total, products_json, collected_date FROM collected_serp
            WHERE keyword=? AND collected_date >= date('now','localtime','-1 day')
            ORDER BY collected_date DESC LIMIT 1
        """, (kw,)).fetchone()
    finally:
        conn.close()
    if not r:
        if enqueue_on_miss:
            _enqueue_request(kw)
        return None
    try:
        raw = json.loads(r["products_json"] or "[]")
    except json.JSONDecodeError:
        return None
    if not raw:
        return None
    raw.sort(key=lambda p: p.get("rank", 0) or 0)
    end = start + max(1, min(display, 100)) - 1
    page = [_to_api_item(p) for p in raw if start <= (p.get("rank", 0) or 0) <= end]
    # collectedDate: 순위 기록 배치가 '오늘분인지' 판별하는 데 쓴다 — 어제 스냅샷이
    # 오늘 순위로 기록되는 것(수집 실패 가드 우회)을 막기 위한 필수 표식.
    return {"total": r["total"] or len(raw), "start": start,
            "display": len(page), "items": page,
            "collectorServed": True, "collectedDate": r["collected_date"]}
