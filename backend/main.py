"""
로직 분석 프로그램 v3 - 백엔드 API 서버
FastAPI 기반 - 에이전시 버전 (로그인/권한/광고주관리/보고서)
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime, date
import os
import time
import logging

# 타임존 설정 (Docker 컨테이너 UTC 대응 — KST 강제)
os.environ.setdefault('TZ', 'Asia/Seoul')
try:
    time.tzset()
except AttributeError:
    pass  # Windows에서는 tzset 미지원

# v3 신규 모듈 임포트
from fastapi import Depends
from auth import router as auth_router, init_auth_db, get_current_user, require_role, UserRole
from clients import router as clients_router, init_clients_db
from reports import router as reports_router, init_reports_db
from client_dashboard import router as cd_router, init_client_dashboard_db
from chat import router as chat_router, init_chat_db
from datalab import analyze_datalab

logger = logging.getLogger(__name__)

# API 키 인증 (빈 문자열이면 명시적 DEV_MODE 필요)
API_KEY = os.getenv("API_KEY", "")
_DEV_MODE = os.getenv("DEV_MODE", "").lower() in ("1", "true", "yes")
# 인증 면제 경로
AUTH_EXEMPT_PATHS = ["/api/health", "/docs", "/openapi.json", "/redoc", "/api/auth/login", "/api/reports/view/"]


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """API 키 기반 인증 미들웨어"""
    async def dispatch(self, request: Request, call_next):
        # 인증 면제 경로 확인
        if any(request.url.path.startswith(p) for p in AUTH_EXEMPT_PATHS):
            return await call_next(request)
        # OPTIONS (CORS preflight)는 통과
        if request.method == "OPTIONS":
            return await call_next(request)
        # API 키 미설정 → JWT 인증에 위임 (라우트 레벨에서 get_current_user가 보호)
        if not API_KEY:
            return await call_next(request)
        # API 키 검증
        provided_key = request.headers.get("X-API-Key", "")
        if provided_key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "인증 실패: 유효한 API 키가 필요합니다."}
            )
        return await call_next(request)

from database import (
    init_db, add_tracked_product, get_all_tracked_products,
    delete_tracked_product, add_tracked_keyword, get_keywords_for_product,
    save_ranking, get_ranking_history, save_competitor_snapshot,
    get_notification_settings, update_notification_settings
)
from naver_crawler import (
    find_product_rank, get_product_info,
    generate_rank_analysis, extract_product_id_from_url,
    get_keyword_volume
)
from scheduler import start_scheduler, stop_scheduler, reschedule_report
from kakao_notify import is_configured as is_solapi_configured

def _verify_db_integrity():
    """앱 시작 시 DB 경로 및 데이터 무결성 검증.
    볼륨 마운트 미스매치로 인한 데이터 손실을 조기에 감지한다."""
    import sqlite3
    db_path = os.getenv("DB_PATH", "/app/data/logic_data.db")
    db_dir = os.path.dirname(os.path.abspath(db_path))

    logger.info(f"📂 DB 경로: {os.path.abspath(db_path)}")
    logger.info(f"📂 DB 디렉토리: {db_dir}")

    # 1) DB 디렉토리가 볼륨 마운트인지 확인 (/app/data 여야 함)
    if not os.path.isdir(db_dir):
        logger.error(f"❌ DB 디렉토리가 존재하지 않습니다: {db_dir}")
        logger.error("   → Docker 볼륨 마운트를 확인하세요: -v /root/logic-analysis-deploy/data:/app/data")
        return

    # 2) DB 파일 존재 여부
    if not os.path.exists(db_path):
        logger.warning(f"⚠️ DB 파일이 없습니다 (신규 생성 예정): {db_path}")
        return

    # 3) DB 파일 크기 확인 (빈 DB 감지)
    db_size = os.path.getsize(db_path)
    logger.info(f"📊 DB 파일 크기: {db_size:,} bytes")
    if db_size < 4096:
        logger.warning(f"⚠️ DB 파일이 비정상적으로 작습니다 ({db_size} bytes). 데이터 손실 가능성!")

    # 4) 핵심 테이블 데이터 수 확인
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row

        tables_to_check = {
            'clients': '업체(광고주)',
            'users': '사용자',
            'tracked_products': '추적 상품',
            'client_analyses': '업체 분석 이력',
        }

        for table, label in tables_to_check.items():
            try:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                count = row['cnt'] if row else 0
                if count == 0 and table == 'clients':
                    logger.warning(f"⚠️ {label} 테이블이 비어있습니다! (이전 데이터 손실 가능성)")
                else:
                    logger.info(f"  ✅ {label}: {count}건")
            except Exception:
                logger.info(f"  ℹ️ {label} 테이블 미존재 (초기화 예정)")

        conn.close()
    except Exception as e:
        logger.error(f"❌ DB 무결성 검증 실패: {e}")


def _backup_db_on_startup():
    """앱 시작 시 DB 자동 백업 (데이터가 있는 경우에만)"""
    import sqlite3
    import shutil
    db_path = os.getenv("DB_PATH", "/app/data/logic_data.db")

    if not os.path.exists(db_path) or os.path.getsize(db_path) < 4096:
        return

    # clients 테이블에 데이터가 있을 때만 백업
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        row = conn.execute("SELECT COUNT(*) as cnt FROM clients").fetchone()
        client_count = row[0] if row else 0
        conn.close()

        if client_count == 0:
            logger.info("ℹ️ 업체 데이터 없음 — 시작 시 백업 건너뜀")
            return
    except Exception:
        return

    backup_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    # 현재 시각 기반 백업 파일명
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"logic_analysis_backup_{ts}.db")

    try:
        # SQLite online backup API 사용 (WAL 안전)
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(backup_path)
        src.backup(dst)
        dst.close()
        src.close()
        logger.info(f"✅ DB 백업 완료: {backup_path} (업체 {client_count}건)")
    except Exception as e:
        # 백업 실패해도 fallback: shutil.copy2
        try:
            shutil.copy2(db_path, backup_path)
            logger.info(f"✅ DB 백업 완료 (파일 복사): {backup_path}")
        except Exception as e2:
            logger.error(f"❌ DB 백업 실패: {e2}")

    # 오래된 백업 정리 (최대 14개 = 약 2주분 보관)
    try:
        backups = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith("logic_analysis_backup_") and f.endswith(".db")
        ])
        while len(backups) > 14:
            old = backups.pop(0)
            os.remove(os.path.join(backup_dir, old))
            logger.info(f"  🗑️ 오래된 백업 삭제: {old}")
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app):
    # Startup
    missing = []
    if not os.getenv("NAVER_CLIENT_ID"):
        missing.append("NAVER_CLIENT_ID")
    if not os.getenv("NAVER_CLIENT_SECRET"):
        missing.append("NAVER_CLIENT_SECRET")
    if missing:
        logger.warning(f"⚠️ 필수 환경변수 미설정: {', '.join(missing)} — 순위 조회 기능이 동작하지 않습니다.")
    if not API_KEY:
        logger.warning("⚠️ API_KEY 미설정 — API 키 미들웨어 비활성화 (JWT 인증은 라우트 레벨에서 동작)")

    # DB 무결성 검증 (테이블 초기화 전)
    _verify_db_integrity()

    init_db()
    init_auth_db()
    init_clients_db()
    init_reports_db()
    init_client_dashboard_db()
    init_chat_db()

    # DB 무결성 검증 후 백업 (테이블 초기화 이후)
    _backup_db_on_startup()

    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()

app = FastAPI(
    title="로직 분석 프로그램 v3",
    description="네이버 쇼핑 키워드 분석 + 상품 노출 순위 추적",
    version="3.0.0",
    lifespan=lifespan,
)

# CORS 설정 - 허용 도메인 제한
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "https://logic.metainc.co.kr").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# API 키 인증 미들웨어 등록
app.add_middleware(ApiKeyAuthMiddleware)

# v3 라우터 등록 (인증/광고주/보고서)
app.include_router(auth_router)
app.include_router(clients_router)
app.include_router(reports_router)
app.include_router(cd_router)
app.include_router(chat_router)


# ==================== 유저 격리 헬퍼 ====================

def _is_admin(user: dict) -> bool:
    """관리자(admin/superadmin) 여부 확인"""
    return user.get("role") in ("admin", "superadmin")


def _verify_keyword_ownership(keyword_id: int, current_user: dict):
    """키워드 → 상품 → 사용자 소유권 체인 검증"""
    if _is_admin(current_user):
        return True
    from database import _get_conn
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT tp.user_id FROM tracked_keywords tk
            JOIN tracked_products tp ON tk.product_id = tp.id
            WHERE tk.id = ?
        """, (keyword_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="키워드를 찾을 수 없습니다.")
        if row["user_id"] != current_user.get("id"):
            raise HTTPException(status_code=403, detail="해당 데이터에 대한 접근 권한이 없습니다.")
        return True
    finally:
        conn.close()


# ==================== 요청/응답 모델 ====================

class ProductAddRequest(BaseModel):
    product_url: str
    keywords: List[str]

    @field_validator('product_url')
    @classmethod
    def validate_url(cls, v):
        if not v or len(v) > 2000:
            raise ValueError('유효한 상품 URL을 입력하세요')
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL은 http:// 또는 https://로 시작해야 합니다')
        return v

    @field_validator('keywords')
    @classmethod
    def validate_keywords(cls, v):
        if not v or len(v) == 0:
            raise ValueError('키워드를 1개 이상 입력하세요')
        if len(v) > 20:
            raise ValueError('키워드는 최대 20개까지 등록 가능합니다')
        for kw in v:
            if not kw.strip() or len(kw) > 100:
                raise ValueError(f'유효하지 않은 키워드: {kw[:30]}')
        return v

class RankCheckRequest(BaseModel):
    keyword: str
    product_url: str
    check_type: str = "realtime"  # realtime | daily

    @field_validator('keyword')
    @classmethod
    def validate_keyword(cls, v):
        if not v or not v.strip() or len(v) > 100:
            raise ValueError('유효한 키워드를 입력하세요 (1~100자)')
        return v.strip()

    @field_validator('product_url')
    @classmethod
    def validate_url(cls, v):
        if not v or not v.startswith(('http://', 'https://')):
            raise ValueError('유효한 상품 URL을 입력하세요')
        return v

class NotificationSettingsRequest(BaseModel):
    notify_enabled: Optional[bool] = None
    receiver_phone: Optional[str] = None
    report_time: Optional[str] = None  # "HH:MM" 형식

    @field_validator('receiver_phone')
    @classmethod
    def validate_phone(cls, v):
        if v is not None and v != "":
            cleaned = re.sub(r'[^0-9]', '', v)
            if not re.match(r'^01[0-9]\d{7,8}$', cleaned):
                raise ValueError('유효한 전화번호 형식이 아닙니다 (예: 01012345678)')
        return v

    @field_validator('report_time')
    @classmethod
    def validate_report_time(cls, v):
        if v is not None and v != "":
            match = re.match(r'^(\d{1,2}):(\d{2})$', v)
            if not match:
                raise ValueError('시간 형식이 올바르지 않습니다 (예: 09:00)')
            hour, minute = int(match.group(1)), int(match.group(2))
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                raise ValueError('유효한 시간 범위가 아닙니다 (00:00 ~ 23:59)')
        return v


# ==================== API 엔드포인트 ====================


# --- 실시간 순위 조회 ---
@app.post("/api/rank/check")
async def check_rank(req: RankCheckRequest, current_user: dict = Depends(get_current_user)):
    """키워드 + 상품URL로 실시간 순위 조회 (인증 필수, viewer 제한은 handleSearch에서 관리)"""
    try:
        product_info = get_product_info(req.product_url, keyword=req.keyword)
        rank, page, competitors = find_product_rank(
            keyword=req.keyword,
            product_url=req.product_url,
            max_pages=10,
            product_name=product_info.get("product_name", "")
        )
        analysis = generate_rank_analysis(rank, None, competitors, product_info)

        return {
            "success": True,
            "data": {
                "keyword": req.keyword,
                "product_url": req.product_url,
                "rank_position": rank,
                "page_number": page,
                "product_info": product_info,
                "top_competitors": competitors[:5],
                "analysis": analysis,
                "checked_at": datetime.now().isoformat(),
            }
        }
    except Exception as e:
        logger.error(f"순위 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="순위 조회 중 오류가 발생했습니다.")


# --- 키워드별 노출 순위 분석 ---
class KeywordExposureRequest(BaseModel):
    product_url: str
    product_name: str = ""
    keyword: str = ""

@app.post("/api/rank/keyword-exposure")
async def keyword_exposure(req: KeywordExposureRequest, current_user: dict = Depends(get_current_user)):
    """상품명에서 키워드를 추출하고 각 키워드별 노출 순위를 조회"""
    import re, concurrent.futures
    try:
        # 상품명 확보
        product_name = req.product_name
        if not product_name:
            info = get_product_info(req.product_url, keyword=req.keyword)
            product_name = info.get("product_name", "")
        if not product_name:
            return {"success": False, "detail": "상품명을 가져올 수 없습니다."}

        # 상품명에서 키워드 토큰 추출
        # 특수문자/괄호 제거, 숫자+단위 합치기
        clean = re.sub(r'[^\w\s가-힣]', ' ', product_name)
        tokens = [t for t in clean.split() if len(t) >= 2]

        # 1단어 + 2단어 조합 키워드 생성
        keywords = set()
        for t in tokens:
            # 순수 숫자만인 토큰 제외
            if not re.match(r'^\d+$', t):
                keywords.add(t)
        for i in range(len(tokens) - 1):
            combo = tokens[i] + ' ' + tokens[i+1]
            if not re.match(r'^\d+\s\d+$', combo):
                keywords.add(combo)

        if not keywords:
            return {"success": True, "data": {"product_name": product_name, "results": []}}

        # 병렬로 순위 조회 (max_pages=3으로 제한 — 속도 최적화)
        results = []
        def check_one(kw):
            try:
                rank, page, _ = find_product_rank(kw, req.product_url, max_pages=3)
                return {"keyword": kw, "rank": rank, "page": page}
            except Exception:
                return {"keyword": kw, "rank": None, "page": None}

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(check_one, kw): kw for kw in keywords}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

        # 순위 있는 것 우선, 순위순 정렬
        results.sort(key=lambda x: (x["rank"] is None, x["rank"] or 9999))

        return {
            "success": True,
            "data": {
                "product_name": product_name,
                "total_keywords": len(keywords),
                "exposed_count": sum(1 for r in results if r["rank"] is not None),
                "results": results
            }
        }
    except Exception as e:
        logger.error(f"키워드 노출 분석 실패: {e}")
        raise HTTPException(status_code=500, detail="키워드 노출 분석 중 오류가 발생했습니다.")


# --- 상품 추적 등록 ---
@app.post("/api/products/track")
async def track_product(req: ProductAddRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """상품 + 키워드 추적 등록 (유저별 격리)"""
    try:
        # 상품 정보 가져오기
        product_info = get_product_info(req.product_url)
        product_id_str = extract_product_id_from_url(req.product_url)

        # DB에 상품 등록 (user_id 포함)
        db_product_id = add_tracked_product(
            product_url=req.product_url,
            product_name=product_info.get("product_name"),
            store_name=product_info.get("store_name"),
            image_url=product_info.get("image_url"),
            price=product_info.get("price"),
            product_id=product_id_str,
            user_id=current_user["id"],
        )

        # 키워드 등록
        keyword_ids = []
        for kw in req.keywords:
            kid = add_tracked_keyword(db_product_id, kw)
            keyword_ids.append({"keyword": kw, "keyword_id": kid})

        # 백그라운드에서 첫 순위 체크 실행
        background_tasks.add_task(
            run_initial_rank_check, db_product_id, req.product_url, keyword_ids
        )

        return {
            "success": True,
            "data": {
                "product_id": db_product_id,
                "product_info": product_info,
                "keywords": keyword_ids,
                "message": "상품이 등록되었습니다. 첫 순위 체크를 시작합니다."
            }
        }
    except Exception as e:
        logger.error(f"상품 등록 실패: {e}")
        raise HTTPException(status_code=500, detail="상품 등록 중 오류가 발생했습니다.")


def run_initial_rank_check(product_id: int, product_url: str, keyword_ids: List[dict]):
    """초기 순위 체크 (백그라운드 - sync로 실행하여 스레드풀 활용)"""
    for kw_info in keyword_ids:
        try:
            rank, page, competitors = find_product_rank(
                keyword=kw_info["keyword"],
                product_url=product_url,
                max_pages=10
            )
            save_ranking(
                product_id=product_id,
                keyword_id=kw_info["keyword_id"],
                keyword=kw_info["keyword"],
                rank_position=rank,
                page_number=page,
                check_type="initial"
            )
            if competitors:
                save_competitor_snapshot(kw_info["keyword_id"], competitors[:5])
        except Exception as e:
            logger.error(f"초기 순위 체크 실패 [{kw_info['keyword']}]: {e}")


# --- 추적 상품 목록 ---
@app.get("/api/products")
async def list_products(current_user: dict = Depends(get_current_user)):
    """추적 중인 상품 목록 (유저별 격리)
    최적화: 빈 상품 정보 재조회를 백그라운드로 분리, 키워드 벌크 조회"""
    import sqlite3
    from database import DB_PATH

    products = get_all_tracked_products(user_id=current_user["id"], is_admin=_is_admin(current_user))

    # --- 최적화: 키워드를 벌크로 한 번에 조회 ---
    if products:
        product_ids = [p["id"] for p in products]
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            placeholders = ','.join('?' * len(product_ids))
            all_keywords = conn.execute(f"""
                SELECT tk.*,
                    (SELECT r.rank_position FROM rankings r
                     WHERE r.keyword_id = tk.id
                     ORDER BY r.checked_at DESC LIMIT 1) as latest_rank,
                    (SELECT r.checked_at FROM rankings r
                     WHERE r.keyword_id = tk.id
                     ORDER BY r.checked_at DESC LIMIT 1) as last_checked
                FROM tracked_keywords tk
                WHERE tk.product_id IN ({placeholders})
                ORDER BY tk.created_at ASC
            """, product_ids).fetchall()

            # product_id별로 그룹핑
            kw_map = {}
            for kw in all_keywords:
                kw_dict = dict(kw)
                pid = kw_dict['product_id']
                kw_map.setdefault(pid, []).append(kw_dict)
        finally:
            conn.close()
    else:
        kw_map = {}

    result = []
    needs_info_update = []  # 빈 상품명 목록 (백그라운드 처리용)

    for p in products:
        p["keywords"] = kw_map.get(p["id"], [])

        # 상품명이 비어있으면 목록에 추가 (응답은 즉시 반환, 업데이트는 백그라운드)
        if not p.get("product_name") or p["product_name"].strip() == '':
            needs_info_update.append(p)

        result.append(p)

    # 빈 상품 정보는 백그라운드에서 업데이트 (응답 지연 방지)
    if needs_info_update:
        from starlette.background import BackgroundTask

        async def _update_empty_products(items):
            for p in items:
                try:
                    keywords = p.get("keywords", [])
                    search_keyword = keywords[0]["keyword"] if keywords and isinstance(keywords[0], dict) else ""
                    info = get_product_info(p["product_url"], keyword=search_keyword)
                    if info.get("product_name"):
                        conn2 = sqlite3.connect(DB_PATH, timeout=10)
                        try:
                            conn2.execute("PRAGMA busy_timeout=30000")
                            conn2.execute("""
                                UPDATE tracked_products SET
                                    product_name=?, store_name=?, image_url=?, price=?,
                                    updated_at=datetime('now','localtime')
                                WHERE id=?
                            """, (info["product_name"], info["store_name"],
                                  info["image_url"], info["price"], p["id"]))
                            conn2.commit()
                            logger.info(f"[bg] 상품 정보 재조회 성공: ID={p['id']} → {info['product_name'][:30]}")
                        finally:
                            conn2.close()
                except Exception as e:
                    logger.warning(f"[bg] 상품 정보 재조회 실패: ID={p['id']}: {e}")

        background_tasks_obj = BackgroundTask(_update_empty_products, needs_info_update)
        from starlette.responses import JSONResponse
        return JSONResponse(
            content={"success": True, "data": result},
            background=background_tasks_obj
        )

    return {"success": True, "data": result}


# --- 상품 삭제 ---
@app.delete("/api/products/{product_id}")
async def remove_product(product_id: int, current_user: dict = Depends(get_current_user)):
    """추적 상품 삭제 (소유권 확인)"""
    delete_tracked_product(product_id, user_id=current_user["id"], is_admin=_is_admin(current_user))
    return {"success": True, "message": "상품이 삭제되었습니다."}


# --- 순위 이력 조회 ---
@app.get("/api/rank/history/{keyword_id}")
async def rank_history(keyword_id: int, days: int = 30, current_user: dict = Depends(get_current_user)):
    """키워드별 순위 변동 이력 (소유권 검증)"""
    _verify_keyword_ownership(keyword_id, current_user)
    days = min(max(days, 1), 365)
    history = get_ranking_history(keyword_id, days=days)
    return {"success": True, "data": history}


# --- 수동 순위 체크 ---
@app.post("/api/rank/refresh/{product_id}")
async def refresh_rank(product_id: int, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """특정 상품의 모든 키워드 순위 재체크"""
    products = get_all_tracked_products(user_id=current_user["id"], is_admin=_is_admin(current_user))
    product = next((p for p in products if p["id"] == product_id), None)
    if not product:
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다.")

    keywords = get_keywords_for_product(product_id)
    kw_list = [{"keyword": k["keyword"], "keyword_id": k["id"]} for k in keywords]

    background_tasks.add_task(
        run_initial_rank_check, product_id, product["product_url"], kw_list
    )

    return {"success": True, "message": "순위 재체크를 시작합니다."}


# --- 키워드 볼륨 조회 ---
@app.post("/api/keyword/volume")
async def keyword_volume(keywords: List[str], current_user: dict = Depends(get_current_user)):
    """키워드 검색량 조회 (인증 필수)"""
    try:
        # 키워드 길이 제한 (100자 초과 방지)
        keywords = [k[:100] for k in keywords[:20] if k and k.strip()]
        if not keywords:
            return {"success": False, "detail": "유효한 키워드를 입력해주세요."}
        data = get_keyword_volume(keywords)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"키워드 볼륨 조회 실패: {e}")
        raise HTTPException(status_code=500, detail="키워드 볼륨 조회 중 오류가 발생했습니다.")


# ==================== 알림톡 API ====================

# --- 알림 설정 조회 ---
@app.get("/api/notify/settings")
async def get_notify_settings(current_user: dict = Depends(require_role(UserRole.ADMIN))):
    """현재 알림 설정 조회 (인증 필수)"""
    settings = get_notification_settings()
    return {
        "success": True,
        "data": {
            **settings,
            "solapi_configured": is_solapi_configured(),
        }
    }


# --- 알림 설정 변경 ---
@app.put("/api/notify/settings")
async def update_notify_settings(req: NotificationSettingsRequest, current_user: dict = Depends(require_role(UserRole.ADMIN))):
    """알림 설정 변경 (admin 전용)"""
    try:
        settings = update_notification_settings(
            notify_enabled=req.notify_enabled,
            receiver_phone=req.receiver_phone,
            report_time=req.report_time
        )

        # 리포트 시간이 변경되면 스케줄러도 업데이트
        if req.report_time:
            try:
                parts = req.report_time.split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    reschedule_report(hour, minute)
                else:
                    raise ValueError(f"유효하지 않은 시간: {req.report_time}")
            except (ValueError, IndexError) as e:
                logger.error(f"리포트 시간 파싱 실패: {req.report_time} - {e}")

        return {"success": True, "data": settings}
    except Exception as e:
        logger.error(f"설정 변경 실패: {e}")
        raise HTTPException(status_code=500, detail="설정 변경 중 오류가 발생했습니다.")


# ==================== 보고서 내보내기 API ====================

class ReportExportRequest(BaseModel):
    format: str = "json"  # json | csv
    date_range: int = 30  # 최근 N일

@app.post("/api/report/export")
async def export_report(req: ReportExportRequest, current_user: dict = Depends(get_current_user)):
    """순위 데이터 보고서 내보내기 (유저별 격리)"""
    try:
        products = get_all_tracked_products(user_id=current_user["id"], is_admin=_is_admin(current_user))
        report_data = []

        for p in products:
            keywords = get_keywords_for_product(p["id"])
            for kw in keywords:
                history = get_ranking_history(kw["id"], days=req.date_range)
                report_data.append({
                    "product_name": p.get("product_name", ""),
                    "store_name": p.get("store_name", ""),
                    "keyword": kw["keyword"],
                    "latest_rank": kw.get("latest_rank"),
                    "history_count": len(history),
                    "history": history,
                })

        if req.format == "csv":
            import csv, io
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["상품명", "스토어", "키워드", "순위", "페이지", "체크타입", "체크일시"])
            for item in report_data:
                for h in item["history"]:
                    writer.writerow([
                        item["product_name"], item["store_name"], item["keyword"],
                        h.get("rank_position", ""), h.get("page_number", ""),
                        h.get("check_type", ""), h.get("checked_at", ""),
                    ])
            return {
                "success": True,
                "data": {"format": "csv", "content": output.getvalue(),
                         "generated_at": datetime.now().isoformat()}
            }

        return {
            "success": True,
            "data": {"format": "json", "items": report_data,
                     "total_products": len(products),
                     "total_keywords": len(report_data),
                     "generated_at": datetime.now().isoformat()}
        }
    except Exception as e:
        logger.error(f"보고서 생성 실패: {e}")
        raise HTTPException(status_code=500, detail="보고서 생성 중 오류가 발생했습니다.")


# ==================== SEO 종합 진단 API ====================

class DetailPageAnalysisRequest(BaseModel):
    html: str
    product_url: Optional[str] = ""

@app.post("/api/seo/detail-page")
async def detail_page_analyze(req: DetailPageAnalysisRequest, current_user: dict = Depends(get_current_user)):
    """상세페이지 품질 분석 (인증 필수)"""
    try:
        from naver_crawler import analyze_detail_page

        html = (req.html or "").strip()
        if not html or len(html) < 100:
            return {
                "success": False,
                "detail": "HTML 내용이 비어있거나 너무 짧습니다. 상세페이지의 HTML 전체를 업로드해주세요."
            }

        # HTML 용량 상한(10MB)
        if len(html) > 10 * 1024 * 1024:
            return {
                "success": False,
                "detail": "HTML 용량이 너무 큽니다 (최대 10MB)."
            }

        result = analyze_detail_page(html, req.product_url or "")
        if not result.get("success"):
            return {"success": False, "detail": result.get("error", "분석 실패")}

        return {
            "success": True,
            "data": {
                "metrics": result["metrics"],
                "scores": result["scores"],
                "suggestions": result["suggestions"],
                "reviewData": result.get("reviewData"),
            }
        }
    except Exception as e:
        logger.error(f"상세페이지 분석 오류: {e}")
        raise HTTPException(status_code=500, detail="상세페이지 분석 중 오류가 발생했습니다.")


class SeoAnalysisRequest(BaseModel):
    product_url: str
    keyword: str
    # 프론트엔드에서 메인 분석 데이터를 전달받아 중복 API 호출 방지
    cached_rank: Optional[int] = None
    cached_product_name: Optional[str] = None
    cached_competitors: Optional[list] = None
    cached_product_info: Optional[dict] = None
    cached_total_volume: Optional[int] = None

@app.post("/api/seo/analyze")
async def seo_analyze(req: SeoAnalysisRequest, current_user: dict = Depends(get_current_user)):
    """상품 SEO 종합 진단 (인증 필수)"""
    try:
        # 캐시된 데이터가 있으면 재활용, 없으면 API 호출
        if req.cached_product_info:
            product_info = req.cached_product_info
        elif req.cached_product_name:
            # cached_product_name이 있으면 get_product_info 불필요 → API 절약 + 429 방지
            product_info = {"product_name": req.cached_product_name}
            # cached_competitors에서 자기 상품 정보 보완 (가격/브랜드/카테고리)
            if req.cached_competitors:
                from naver_crawler import extract_store_name_from_url as _ext_store
                target_store = (_ext_store(req.product_url) or "").lower()
                for _cp in req.cached_competitors:
                    cp_store = (_cp.get("store_name") or "").lower()
                    cp_url = (_cp.get("product_url") or "").lower()
                    # 스토어명 일치 또는 URL 포함으로 매칭
                    if (target_store and (cp_store == target_store or target_store in cp_url)):
                        product_info["price"] = _cp.get("price", 0)
                        product_info["brand"] = _cp.get("brand", "")
                        product_info["store_name"] = _cp.get("store_name", "")
                        product_info["category1"] = _cp.get("category1", "")
                        product_info["category2"] = _cp.get("category2", "")
                        logger.info(f"SEO product_info 캐시 보완: {_cp.get('store_name', '')}")
                        break
        else:
            try:
                product_info = get_product_info(req.product_url, keyword=req.keyword)
            except Exception as e:
                logger.warning(f"get_product_info 실패 (빈 값 사용): {e}")
                product_info = {}
        product_name = req.cached_product_name or product_info.get("product_name", "")
        product_url = req.product_url or ""

        if req.cached_rank is not None:
            rank = req.cached_rank
            page = (rank - 1) // 40 + 1 if rank > 0 else None
            competitors = req.cached_competitors or []
        else:
            try:
                rank, page, competitors = find_product_rank(
                    keyword=req.keyword, product_url=req.product_url, max_pages=10,
                    product_name=product_name
                )
            except Exception as e:
                logger.warning(f"find_product_rank 실패 (순위 없음 처리): {e}")
                rank, page, competitors = None, None, []

        # get_product_info 실패 시 (스마트스토어 ID ≠ nvMid) → 키워드 검색에서 productId로 보완
        # 캐시된 product_name이 있으면 폴백 불필요
        if not product_name and not req.cached_product_name:
            try:
                from naver_crawler import extract_product_id_from_url as _extract_pid
                from naver_crawler import extract_store_name_from_url as _extract_store
                from naver_crawler import search_products as _sp
                target_pid = _extract_pid(req.product_url) or ""
                target_store = _extract_store(req.product_url) or ""
                _prods = _sp(req.keyword, max_results=200)
                for _p in _prods:
                    p_url = _p.get("product_url", "")
                    p_pid = _p.get("product_id", "")
                    p_mall = (_p.get("store_name", "") or "").lower()
                    # 매칭 1: productId 정확 일치
                    matched = target_pid and target_pid == p_pid
                    # 매칭 2: productId가 URL에 포함 + 스토어 검증 (다른 스토어 오염 방지)
                    if not matched and target_pid and target_pid in p_url:
                        if target_store:
                            store_in_url = target_store.lower() in p_url.lower()
                            store_in_mall = p_mall == target_store.lower()
                            matched = store_in_url or store_in_mall
                        else:
                            matched = True
                    # 매칭 3: 스토어명이 URL에 포함 (스토어 슬러그 비교)
                    if not matched and target_store:
                        matched = target_store.lower() in p_url.lower()
                    if matched:
                        product_name = _p.get("product_name", "")
                        product_info["product_name"] = product_name
                        product_info["price"] = _p.get("price", 0)
                        product_info["image_url"] = _p.get("image_url", "")
                        product_info["store_name"] = _p.get("store_name", "") or target_store
                        product_info["brand"] = _p.get("brand", "")
                        product_info["category1"] = _p.get("category1", "")
                        product_info["category2"] = _p.get("category2", "")
                        logger.info(f"SEO 보완 매칭 성공: {product_name[:30]} (pid: {target_pid})")
                        break
            except Exception as e:
                logger.warning(f"SEO 폴백 검색 실패 (스킵): {e}")

        # --- 기본 데이터 수집 ---
        # 띄어쓰기 무시 비교 (상품명 "생 멸치" ↔ 키워드 "생멸치" 매칭)
        keyword_in_title = req.keyword.replace(" ", "").lower() in product_name.replace(" ", "").lower() if product_name else False
        title_length = len(product_name)
        special_chars = sum(1 for c in product_name if c in '!@#$%^&*()[]{}|<>★☆♥♡')

        my_price = product_info.get("price", 0)
        comp_prices = [c.get("price", 0) for c in competitors if c.get("price", 0) > 0]
        avg_comp_price = sum(comp_prices) / len(comp_prices) if comp_prices else 0

        # --- 10개 평가지표 계산 ---

        # 1. 상품명 최적화 (15%)
        title_score = 0
        if keyword_in_title:
            title_score += 40
        if 20 <= title_length <= 50:
            title_score += 30
        elif 10 <= title_length <= 70:
            title_score += 20
        else:
            title_score += 10
        if special_chars <= 2:
            title_score += 30
        elif special_chars <= 5:
            title_score += 15

        # 2. 가격 경쟁력 (12%)
        price_score = 0
        price_ratio = 0
        if my_price > 0 and avg_comp_price > 0:
            price_ratio = round(my_price / avg_comp_price, 2)
            if price_ratio <= 0.85:
                price_score = 100
            elif price_ratio <= 1.0:
                price_score = 80
            elif price_ratio <= 1.15:
                price_score = 60
            elif price_ratio <= 1.3:
                price_score = 40
            else:
                price_score = 20

        # 3. 검색 순위 (15%)
        rank_score = 0
        if rank:
            if rank <= 10:
                rank_score = 100
            elif rank <= 20:
                rank_score = 80
            elif rank <= 40:
                rank_score = 60
            elif rank <= 100:
                rank_score = 40
            else:
                rank_score = 20

        # 4. 리뷰 점수 (12%) — 스마트스토어 API에서 실제 값 조회, 실패 시 추정
        review_score = 0
        est_reviews = 0
        actual_review_count = None
        actual_rating = None
        review_source = "estimated"
        try:
            from naver_crawler import _extract_smartstore_info
            ss_store, ss_pno = _extract_smartstore_info(product_url)
            if ss_store and ss_pno:
                import requests as _req
                ss_api_url = f"https://smartstore.naver.com/i/v1/stores/{ss_store}/products/{ss_pno}"
                ss_headers = {
                    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36",
                    "Accept": "application/json",
                    "Referer": f"https://smartstore.naver.com/{ss_store}/products/{ss_pno}",
                }
                ss_resp = _req.get(ss_api_url, headers=ss_headers, timeout=10)
                if ss_resp.status_code == 200:
                    ss_data = ss_resp.json()
                    review_amount = ss_data.get("reviewAmount", {})
                    if isinstance(review_amount, dict):
                        rc = review_amount.get("totalReviewCount", 0)
                        rs = review_amount.get("averageReviewScore", 0)
                        if rc is not None and rc >= 0:
                            actual_review_count = int(rc)
                        if rs is not None and rs > 0:
                            actual_rating = float(rs)
                    if actual_review_count is not None:
                        review_source = "api"
                        logger.info(f"SEO 리뷰 실제값 조회 성공: {actual_review_count}건, 평점 {actual_rating}")
        except Exception as e:
            logger.warning(f"SEO 리뷰 실제값 조회 실패 (추정값 사용): {e}")

        if actual_review_count is not None:
            est_reviews = actual_review_count
            if actual_review_count >= 500: review_score = 95
            elif actual_review_count >= 200: review_score = 80
            elif actual_review_count >= 80: review_score = 60
            elif actual_review_count >= 30: review_score = 40
            elif actual_review_count >= 10: review_score = 25
            elif actual_review_count >= 1: review_score = 15
            else: review_score = 5
        else:
            if rank:
                if rank <= 5: est_reviews = 500; review_score = 95
                elif rank <= 10: est_reviews = 200; review_score = 80
                elif rank <= 20: est_reviews = 80; review_score = 60
                elif rank <= 40: est_reviews = 30; review_score = 40
                elif rank <= 100: est_reviews = 10; review_score = 25
                else: est_reviews = 3; review_score = 10
            if not rank: review_score = 5; est_reviews = 0

        # 5. 상품 평점 (8%) — 실제값 우선, 없으면 추정
        rating_score = 0
        est_rating = 0.0
        if actual_rating is not None and actual_rating > 0:
            est_rating = actual_rating
            if actual_rating >= 4.5: rating_score = 90
            elif actual_rating >= 4.0: rating_score = 75
            elif actual_rating >= 3.5: rating_score = 60
            elif actual_rating >= 3.0: rating_score = 45
            else: rating_score = 30
        else:
            if rank:
                if rank <= 10: est_rating = 4.7; rating_score = 90
                elif rank <= 20: est_rating = 4.5; rating_score = 75
                elif rank <= 40: est_rating = 4.3; rating_score = 60
                elif rank <= 100: est_rating = 4.0; rating_score = 45
                else: est_rating = 3.8; rating_score = 30
            if not rank: est_rating = 0; rating_score = 5

        # 6. 판매실적 추정 (10%) — 순위 기반 CTR × 전환율 역산
        sales_score = 0
        est_monthly_sales = 0
        if rank:
            # 키워드 볼륨: 캐시 우선, 없으면 API 호출
            if req.cached_total_volume is not None:
                total_vol = req.cached_total_volume
            else:
                try:
                    vol_data = get_keyword_volume([req.keyword])
                    vol = vol_data[0] if vol_data else None
                    total_vol = (vol.get("monthlyPcQcCnt", 0) + vol.get("monthlyMobileQcCnt", 0)) if vol else 0
                except Exception:
                    total_vol = 0

            ctr_map = {1: 0.08, 2: 0.06, 3: 0.05, 4: 0.04, 5: 0.03}
            ctr = ctr_map.get(rank, 0.015 if rank <= 10 else 0.008 if rank <= 20 else 0.003 if rank <= 40 else 0.001)
            est_monthly_sales = max(1, round(total_vol * ctr * 0.035)) if total_vol > 0 else 0

            if est_monthly_sales >= 100:
                sales_score = 95
            elif est_monthly_sales >= 50:
                sales_score = 80
            elif est_monthly_sales >= 20:
                sales_score = 60
            elif est_monthly_sales >= 5:
                sales_score = 40
            elif est_monthly_sales >= 1:
                sales_score = 20
        if not rank:
            sales_score = 5

        # 7. 카테고리 적합도 (8%)
        category_score = 0
        product_category = product_info.get("category2", "") or product_info.get("category1", "")
        if product_category:
            # 경쟁사 카테고리 중 가장 많은 것과 비교
            comp_cats = [c.get("category2", "") or c.get("category1", "") for c in competitors if c.get("category2") or c.get("category1")]
            if comp_cats:
                from collections import Counter
                most_common_cat = Counter(comp_cats).most_common(1)[0][0] if comp_cats else ""
                if product_category == most_common_cat:
                    category_score = 100
                elif product_category in " ".join(comp_cats):
                    category_score = 60
                else:
                    category_score = 30
            else:
                category_score = 50  # 비교 불가
        else:
            category_score = 20

        # 8. 판매처/브랜드 파워 (8%)
        brand_score = 0
        product_brand = product_info.get("brand", "")
        is_smartstore = "smartstore.naver.com" in product_url
        if product_brand:
            brand_score += 40
        if is_smartstore:
            brand_score += 30  # 스마트스토어 = 네이버 플랫폼 우대
        if product_info.get("store_name"):
            brand_score += 30
        brand_score = min(brand_score, 100)

        # 9. 네이버페이 여부 (6%)
        naverpay_score = 0
        has_naverpay = is_smartstore  # 스마트스토어는 기본 네이버페이
        if has_naverpay:
            naverpay_score = 100
        else:
            # 외부 쇼핑몰도 네이버페이 연동 가능 (확인 불가하므로 50점)
            naverpay_score = 50

        # 10. 최신성 점수 (6%) — 순위 기반 간접 추정
        freshness_score = 0
        if rank:
            if rank <= 20:
                freshness_score = 80  # 상위 노출 = 최근 활성화 가능성 높음
            elif rank <= 40:
                freshness_score = 60
            elif rank <= 100:
                freshness_score = 40
            else:
                freshness_score = 20
        if not rank:
            freshness_score = 10

        # --- 종합 점수 (가중 합산) ---
        weights = {
            'title': 0.15, 'price': 0.12, 'rank': 0.15,
            'review': 0.12, 'rating': 0.08, 'sales': 0.10,
            'category': 0.08, 'brand': 0.08, 'naverpay': 0.06,
            'freshness': 0.06
        }
        total_score = int(
            title_score * weights['title'] +
            price_score * weights['price'] +
            rank_score * weights['rank'] +
            review_score * weights['review'] +
            rating_score * weights['rating'] +
            sales_score * weights['sales'] +
            category_score * weights['category'] +
            brand_score * weights['brand'] +
            naverpay_score * weights['naverpay'] +
            freshness_score * weights['freshness']
        )

        # --- 개선 제안 ---
        suggestions = []
        if product_name and not keyword_in_title:
            suggestions.append(f"상품명에 '{req.keyword}' 키워드를 포함시키세요.")
        if title_length < 15:
            suggestions.append("상품명이 너무 짧습니다. 핵심 키워드와 속성을 추가하세요.")
        elif title_length > 60:
            suggestions.append("상품명이 너무 길면 가독성이 떨어집니다. 50자 이내를 권장합니다.")
        if special_chars > 3:
            suggestions.append("특수문자 사용을 줄이면 검색 노출에 유리합니다.")
        if price_ratio > 1.2 and avg_comp_price > 0:
            suggestions.append(f"경쟁 상품 대비 가격이 {int((price_ratio-1)*100)}% 높습니다. 가격 조정을 검토하세요.")
        if not rank:
            suggestions.append("200위 내 미노출 — 키워드 재설정 또는 상품명 최적화가 필요합니다.")
        if review_score < 50:
            suggestions.append("리뷰 수가 부족합니다. 구매 후기 이벤트나 포토리뷰 유도를 추천합니다.")
        if not has_naverpay:
            suggestions.append("네이버페이 연동 시 구매 전환율과 노출 순위가 개선됩니다.")
        if brand_score < 50:
            suggestions.append("브랜드명을 등록하고 스마트스토어 입점을 고려하세요.")
        if not suggestions:
            suggestions.append("전반적으로 양호합니다! 리뷰 확보와 찜 유도에 집중하세요.")

        return {
            "success": True,
            "data": {
                "product_info": product_info,
                "keyword": req.keyword,
                "scores": {
                    "total": total_score,
                    "title": title_score,
                    "price": price_score,
                    "rank": rank_score,
                    "review": review_score,
                    "rating": rating_score,
                    "sales": sales_score,
                    "category": category_score,
                    "brand": brand_score,
                    "naverpay": naverpay_score,
                    "freshness": freshness_score,
                    "detail": {
                        "keyword_in_title": keyword_in_title,
                        "title_length": title_length,
                        "special_chars": special_chars,
                        "current_rank": rank,
                        "my_price": my_price,
                        "avg_competitor_price": int(avg_comp_price),
                        "price_ratio": price_ratio,
                        "est_reviews": est_reviews,
                        "est_rating": est_rating,
                        "review_source": review_source,
                        "est_monthly_sales": est_monthly_sales,
                        "has_naverpay": has_naverpay,
                        "is_smartstore": is_smartstore,
                        "product_brand": product_brand,
                        "product_category": product_category,
                    }
                },
                "weights": weights,
                "suggestions": suggestions,
                "competitors": competitors[:5],
                "analyzed_at": datetime.now().isoformat(),
            }
        }
    except Exception as e:
        logger.error(f"SEO 분석 실패: {e}")
        raise HTTPException(status_code=500, detail="SEO 분석 중 오류가 발생했습니다.")


# ==================== 상품 검색 API (키워드로 쇼핑 상품 조회) ====================

class ProductSearchRequest(BaseModel):
    keyword: str
    count: int = 40

@app.post("/api/products/search")
async def search_products(req: ProductSearchRequest, current_user: dict = Depends(get_current_user)):
    """네이버 쇼핑에서 키워드로 상품 검색 (인증 필수)"""
    try:
        from naver_crawler import search_naver_shopping_api, _parse_api_item
        result = search_naver_shopping_api(req.keyword, display=min(req.count, 100), retry_on_429=True)
        items = result.get("items", [])
        products = [_parse_api_item(item, idx + 1) for idx, item in enumerate(items)]
        return {
            "success": True,
            "data": {
                "keyword": req.keyword,
                "total": result.get("total", 0),
                "products": products,
                "searched_at": datetime.now().isoformat(),
            }
        }
    except Exception as e:
        logger.error(f"상품 검색 실패: {e}")
        raise HTTPException(status_code=500, detail="상품 검색 중 오류가 발생했습니다.")


# ==================== 연관/황금 키워드 API ====================

class RelatedKeywordRequest(BaseModel):
    keyword: str

@app.post("/api/keywords/related")
async def related_keywords(req: RelatedKeywordRequest, current_user: dict = Depends(get_current_user)):
    """연관 키워드 + 황금 키워드 분석 (인증 필수)"""
    try:
        # 네이버 검색광고 API에서 연관 키워드 가져오기
        from naver_crawler import (
            get_keyword_volume as _get_kw_vol,
            SEARCHAD_API_KEY, SEARCHAD_SECRET_KEY, SEARCHAD_CUSTOMER_ID,
            _generate_searchad_signature, _safe_int, _safe_float
        )
        import requests as req_lib

        all_keywords = []

        # 검색광고 API 연관 키워드 조회 (retry 포함)
        if SEARCHAD_API_KEY and SEARCHAD_SECRET_KEY and SEARCHAD_CUSTOMER_ID:
            uri = "/keywordstool"
            method = "GET"
            url = f"https://api.searchad.naver.com{uri}"
            params = {"hintKeywords": req.keyword, "showDetail": "1"}
            data = {}
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    timestamp = str(int(time.time() * 1000))
                    signature = _generate_searchad_signature(timestamp, method, uri)
                    headers = {
                        "X-Timestamp": timestamp,
                        "X-API-KEY": SEARCHAD_API_KEY,
                        "X-Customer": SEARCHAD_CUSTOMER_ID,
                        "X-Signature": signature,
                    }
                    resp = req_lib.get(url, params=params, headers=headers, timeout=10)
                    resp.raise_for_status()
                    data = resp.json()
                    break
                except Exception as retry_err:
                    if attempt < max_retries:
                        import logging as _log
                        _log.getLogger(__name__).warning(f"검색광고 API 재시도 ({attempt+1}/{max_retries}): {retry_err}")
                        time.sleep(0.5)
                    else:
                        import logging as _log
                        _log.getLogger(__name__).warning(f"검색광고 API 요청 실패 (재시도 소진): {retry_err}")

            # 스토어명/사업자명 필터용 패턴
            import re as _re
            # 스토어명/브랜드명 패턴: 영문+숫자 조합(shop123), 한글 고유명사 느낌(OO상사, OO몰)
            store_suffixes = ['스토어', '몰', '마켓', '샵', 'store', 'shop', 'mall', 'market',
                              '공식', '본사', '직영', '판매', '무역', '상사', '유통', '컴퍼니',
                              '코리아', '글로벌', '엔터', '그룹', '홈', '닷컴', '.com', '.co.kr']

            def _is_likely_store_name(kw, seed):
                """스토어명/사업자명일 가능성이 높은 키워드 필터링"""
                kw_lower = kw.lower().strip()
                seed_lower = seed.lower().strip()
                # 1. 시드 키워드의 핵심 단어가 포함되지 않으면 노이즈
                seed_words = [w for w in seed_lower.split() if len(w) >= 2]
                has_seed_match = any(w in kw_lower for w in seed_words) if seed_words else (seed_lower in kw_lower)
                # 2. 스토어/사업자 접미사 체크
                has_store_suffix = any(s in kw_lower for s in store_suffixes)
                # 3. 영문만으로 구성된 짧은 키워드 (브랜드명 가능성)
                is_short_english = len(kw) <= 12 and _re.match(r'^[a-zA-Z0-9]+$', kw)
                # 스토어명 판정: 시드 키워드와 무관 + 스토어 접미사 포함, 또는 시드와 무관한 영문 단독
                if has_store_suffix and not has_seed_match:
                    return True
                if is_short_english and not has_seed_match:
                    return True
                return False

            for kd in data.get("keywordList", []):
                rel_kw = kd.get("relKeyword", "")
                pc = _safe_int(kd.get("monthlyPcQcCnt"))
                mobile = _safe_int(kd.get("monthlyMobileQcCnt"))
                total_volume = pc + mobile
                comp_idx = kd.get("compIdx", "")

                # 스토어명/사업자명 필터
                is_store = _is_likely_store_name(rel_kw, req.keyword)

                # 황금키워드 판별: 검색량 적당 + 경쟁 낮음 + 스토어명 아님 + 시드 키워드 관련성
                seed_words = [w for w in req.keyword.lower().split() if len(w) >= 2]
                has_relevance = any(w in rel_kw.lower() for w in seed_words) if seed_words else (req.keyword.lower() in rel_kw.lower())

                is_golden = (
                    100 <= total_volume <= 5000 and
                    comp_idx in ("낮음", "LOW", "") and
                    not is_store and
                    has_relevance
                )

                all_keywords.append({
                    "keyword": rel_kw,
                    "monthlyPcQcCnt": pc,
                    "monthlyMobileQcCnt": mobile,
                    "totalVolume": total_volume,
                    "compIdx": comp_idx,
                    "isGolden": is_golden,
                    "isStoreName": is_store,
                    "monthlyAvePcClkCnt": _safe_float(kd.get("monthlyAvePcClkCnt")),
                    "monthlyAveMobileClkCnt": _safe_float(kd.get("monthlyAveMobileClkCnt")),
                })

        # 정렬: 황금키워드 우선, 그 다음 검색량순
        golden = sorted([k for k in all_keywords if k["isGolden"]], key=lambda x: -x["totalVolume"])
        others = sorted([k for k in all_keywords if not k["isGolden"]], key=lambda x: -x["totalVolume"])

        return {
            "success": True,
            "data": {
                "seed_keyword": req.keyword,
                "golden_keywords": golden[:20],
                "related_keywords": others[:30],
                "total_found": len(all_keywords),
                "analyzed_at": datetime.now().isoformat(),
            }
        }
    except Exception as e:
        logger.error(f"연관 키워드 분석 실패: {e}")
        raise HTTPException(status_code=500, detail="연관 키워드 분석 중 오류가 발생했습니다.")


# ==================== 상품명 키워드 분석 API ====================

class ProductNameAnalysisRequest(BaseModel):
    product_names: List[str]  # 분석할 상품명 목록
    keyword: str = ""  # 기준 키워드 (선택)

@app.post("/api/product-name/analyze")
async def analyze_product_names(req: ProductNameAnalysisRequest, current_user: dict = Depends(get_current_user)):
    """상품명에서 키워드 추출 및 빈도 분석 (인증 필수)"""
    try:
        import re as re_mod
        from collections import Counter

        all_words = []
        name_analyses = []

        for name in req.product_names[:50]:  # 최대 50개
            # 특수문자 제거 후 단어 분리
            cleaned = re_mod.sub(r'[^\w\s가-힣a-zA-Z0-9]', ' ', name)
            words = [w.strip() for w in cleaned.split() if len(w.strip()) >= 2]
            all_words.extend(words)

            # 개별 상품명 분석
            analysis = {
                "original": name,
                "word_count": len(words),
                "char_count": len(name),
                "words": words,
                "has_keyword": req.keyword.lower() in name.lower() if req.keyword else None,
                "special_char_count": sum(1 for c in name if c in '!@#$%^&*()[]{}|<>★☆♥♡~'),
            }
            name_analyses.append(analysis)

        # 빈도 분석
        word_freq = Counter(all_words)
        top_keywords = [
            {"word": word, "count": count, "ratio": round(count / len(req.product_names) * 100, 1)}
            for word, count in word_freq.most_common(30)
        ]

        # 2글자 조합 (바이그램) 분석
        bigrams = []
        for name in req.product_names[:50]:
            cleaned = re_mod.sub(r'[^\w\s가-힣a-zA-Z0-9]', ' ', name)
            words = [w.strip() for w in cleaned.split() if len(w.strip()) >= 2]
            for i in range(len(words) - 1):
                bigrams.append(f"{words[i]} {words[i+1]}")

        bigram_freq = Counter(bigrams)
        top_bigrams = [
            {"phrase": phrase, "count": count}
            for phrase, count in bigram_freq.most_common(15)
        ]

        # 평균 상품명 길이
        avg_length = sum(len(n) for n in req.product_names) / len(req.product_names) if req.product_names else 0

        return {
            "success": True,
            "data": {
                "total_analyzed": len(req.product_names),
                "avg_name_length": round(avg_length, 1),
                "top_keywords": top_keywords,
                "top_bigrams": top_bigrams,
                "name_analyses": name_analyses[:20],
                "keyword_coverage": (
                    round(sum(1 for a in name_analyses if a["has_keyword"]) / len(name_analyses) * 100, 1)
                    if req.keyword and name_analyses else None
                ),
                "analyzed_at": datetime.now().isoformat(),
            }
        }
    except Exception as e:
        logger.error(f"상품명 분석 실패: {e}")
        raise HTTPException(status_code=500, detail="상품명 분석 중 오류가 발생했습니다.")


# ==================== 광고주 맞춤 분석 리포트 API ====================

class AdvertiserAnalysisRequest(BaseModel):
    keyword: str
    product_url: str

    @field_validator('keyword')
    @classmethod
    def validate_keyword(cls, v):
        if not v or not v.strip() or len(v) > 100:
            raise ValueError('유효한 키워드를 입력하세요 (1~100자)')
        return v.strip()

    @field_validator('product_url')
    @classmethod
    def validate_url(cls, v):
        if not v or not v.startswith(('http://', 'https://')):
            raise ValueError('유효한 상품 URL을 입력하세요')
        return v

@app.post("/api/advertiser/analyze")
async def advertiser_analyze(req: AdvertiserAnalysisRequest, current_user: dict = Depends(get_current_user)):
    """광고주 맞춤 분석 리포트 (인증 필수)"""
    try:
        from naver_crawler import search_naver_shopping_api, _parse_api_item

        # 1) 광고주 상품 정보 조회
        product_info = get_product_info(req.product_url)

        # get_product_info 실패 시 (스마트스토어 ID ≠ nvMid) → 키워드 검색에서 productId로 보완
        if not product_info.get("product_name"):
            from naver_crawler import extract_product_id_from_url as _extract_pid
            from naver_crawler import extract_store_name_from_url as _extract_store
            from naver_crawler import search_products as _sp
            target_pid = _extract_pid(req.product_url) or ""
            target_store = _extract_store(req.product_url) or ""
            _prods = _sp(req.keyword, max_results=200)
            for _p in _prods:
                p_url = _p.get("product_url", "")
                p_pid = _p.get("product_id", "")
                matched = target_pid and (target_pid in p_url or target_pid == p_pid)
                if not matched and target_store:
                    matched = target_store.lower() in p_url.lower()
                if matched:
                    product_info["product_name"] = _p.get("product_name", "")
                    product_info["price"] = _p.get("price", 0)
                    product_info["image_url"] = _p.get("image_url", "")
                    product_info["store_name"] = _p.get("store_name", "") or target_store
                    product_info["brand"] = _p.get("brand", "")
                    product_info["category"] = _p.get("category2") or _p.get("category1") or ""
                    logger.info(f"광고주분석 보완 매칭 성공: {product_info['product_name'][:30]} (pid: {target_pid})")
                    break

        # 2) 키워드로 순위 검색
        rank, page, top_competitors = find_product_rank(
            keyword=req.keyword, product_url=req.product_url, max_pages=10,
            product_name=product_info.get("product_name", "")
        )

        # 3) 상위 40개 상품 가져오기 (1페이지 분석용)
        shop_result = search_naver_shopping_api(req.keyword, display=80)
        shop_items = shop_result.get("items", [])
        page1_products = [_parse_api_item(item, idx + 1) for idx, item in enumerate(shop_items)]

        # 4) 경쟁사 비교 분석 데이터 구성
        my_price = product_info.get("price", 0)
        my_name = product_info.get("product_name", "")

        competitor_comparison = []
        prices = []
        review_counts = []
        name_lengths = []

        for p in page1_products[:80]:
            has_keyword = req.keyword.lower() in p.get("product_name", "").lower()
            comp_item = {
                "rank": p["rank"],
                "product_name": p["product_name"],
                "store_name": p["store_name"],
                "price": p["price"],
                "brand": p.get("brand", ""),
                "category": ' > '.join([x for x in [p.get("category1",""), p.get("category2",""), p.get("category3","")] if x]) or "-",
                "image_url": p.get("image_url", ""),
                "product_type": p.get("product_type", ""),
                "has_keyword_in_name": has_keyword,
                "name_length": len(p["product_name"]),
            }
            competitor_comparison.append(comp_item)
            if p["price"] > 0:
                prices.append(p["price"])
            name_lengths.append(len(p["product_name"]))

        # 통계 계산
        avg_price = int(sum(prices) / len(prices)) if prices else 0
        min_price = min(prices) if prices else 0
        max_price = max(prices) if prices else 0
        avg_name_length = round(sum(name_lengths) / len(name_lengths), 1) if name_lengths else 0
        keyword_in_name_ratio = round(
            sum(1 for c in competitor_comparison if c["has_keyword_in_name"]) / len(competitor_comparison) * 100, 1
        ) if competitor_comparison else 0

        # 5) 마케터 관점 심층 전략 분석
        strategies = []
        # 띄어쓰기 무시 비교 (상품명 "생 멸치" ↔ 키워드 "생멸치" 매칭)
        my_has_keyword = req.keyword.replace(" ", "").lower() in my_name.replace(" ", "").lower() if my_name else False
        my_name_len = len(my_name)

        # ── 경쟁사 패턴 심층 분석 ──
        top5 = page1_products[:5] if page1_products else []
        top10 = page1_products[:10] if page1_products else []

        # 가격대 분포 분석
        price_bands = {"저가": 0, "중가": 0, "고가": 0}
        if avg_price > 0:
            for p in prices:
                if p < avg_price * 0.7:
                    price_bands["저가"] += 1
                elif p > avg_price * 1.3:
                    price_bands["고가"] += 1
                else:
                    price_bands["중가"] += 1
        dominant_band = max(price_bands, key=price_bands.get) if any(price_bands.values()) else "중가"

        # 브랜드 집중도 분석
        brand_map = {}
        store_map = {}
        for p in page1_products[:80]:
            b = p.get("brand") or ""
            s = p.get("store_name") or ""
            if b:
                brand_map[b] = brand_map.get(b, 0) + 1
            if s:
                store_map[s] = store_map.get(s, 0) + 1
        top_brands = sorted(brand_map.items(), key=lambda x: -x[1])[:3]
        top_stores = sorted(store_map.items(), key=lambda x: -x[1])[:3]
        total_analyzed = min(len(page1_products), 80)
        brand_concentration = (top_brands[0][1] / max(total_analyzed, 1) * 100) if top_brands else 0

        # 카테고리 분석 (대>중>소 계층 경로)
        cat_map = {}
        for p in page1_products[:80]:
            parts = [x for x in [p.get("category1",""), p.get("category2",""), p.get("category3","")] if x]
            cat = ' > '.join(parts) if parts else "기타"
            cat_map[cat] = cat_map.get(cat, 0) + 1
        top_cat = max(cat_map, key=cat_map.get) if cat_map else "-"
        cat_share = round(cat_map.get(top_cat, 0) / max(total_analyzed, 1) * 100)

        # 상품명 키워드 위치 패턴 분석
        kw_front_count = 0  # 키워드가 상품명 앞부분(30%)에 위치
        kw_total = 0
        for p in page1_products[:80]:
            pname = p.get("product_name", "")
            kw_pos = pname.lower().find(req.keyword.lower())
            if kw_pos >= 0:
                kw_total += 1
                if kw_pos < len(pname) * 0.3:
                    kw_front_count += 1

        # 상위 5개 공통 키워드 패턴 추출
        from collections import Counter
        all_words = []
        for p in top5:
            words = p.get("product_name", "").replace("[", " ").replace("]", " ").replace("/", " ").split()
            all_words.extend([w for w in words if len(w) >= 2 and w.lower() != req.keyword.lower()])
        common_words = [w for w, c in Counter(all_words).most_common(8) if c >= 2]

        # TOP10 평균가
        top5_prices = [p["price"] for p in top5 if p.get("price", 0) > 0]
        top5_avg = int(sum(top5_prices) / len(top5_prices)) if top5_prices else avg_price

        # ── 전략 1: 가격 포지셔닝 & 소구점 전략 ──
        price_insights = []
        price_actions = []
        if my_price > 0 and avg_price > 0:
            price_ratio = my_price / avg_price
            top5_ratio = my_price / top5_avg if top5_avg > 0 else 1
            if price_ratio > 1.2:
                price_insights.append(f"현재 가격({my_price:,}원)이 경쟁 평균({avg_price:,}원) 대비 {round((price_ratio-1)*100)}% 높습니다. 이 가격대에서는 '프리미엄 소구'가 필수입니다.")
                price_insights.append(f"1페이지 가격 분포: 저가 {price_bands['저가']}개 | 중가 {price_bands['중가']}개 | 고가 {price_bands['고가']}개 — {dominant_band} 상품이 지배적입니다.")
                price_actions.append("프리미엄 전략: 상세페이지에 '원재료 차별화', '제조 공정', '인증' 등 가격 정당성을 시각적으로 어필하세요.")
                price_actions.append(f"가격 심리 전략: {avg_price:,}원대 쿠폰(첫구매 할인, 리뷰 적립)으로 실구매가를 경쟁가 수준으로 맞추세요.")
                price_actions.append("묶음/세트 구성으로 개당 단가를 낮추면 가격 비교에서 유리해집니다.")
            elif price_ratio < 0.8:
                price_insights.append(f"현재 가격({my_price:,}원)이 경쟁 평균({avg_price:,}원) 대비 {round((1-price_ratio)*100)}% 저렴합니다. 가성비를 핵심 소구점으로 활용하세요.")
                price_insights.append(f"TOP10 평균({top5_avg:,}원)과 비교하면 진입 장벽이 낮아 초기 판매량 확보에 유리합니다.")
                price_actions.append("상품명/썸네일에 '가성비', '최저가', '특가' 등 가격 메리트를 직접 표기하세요.")
                price_actions.append("저가 포지션의 약점(품질 의심)을 상세페이지 리뷰 섹션과 인증서로 보완하세요.")
                price_actions.append(f"마진 여유가 있다면 '무료배송' 또는 '사은품 증정'으로 전환율을 높이세요.")
            else:
                price_insights.append(f"현재 가격({my_price:,}원)이 경쟁 평균({avg_price:,}원)과 유사한 적정가 구간입니다.")
                price_insights.append(f"가격 차별화가 어려운 구간이므로 '비가격 경쟁력'이 핵심입니다.")
                price_actions.append("같은 가격이면 '무료배송', '당일출고', '사은품'이 클릭률을 좌우합니다.")
                price_actions.append("네이버페이 적립, 카드 즉시할인 등 체감 할인 요소를 적극 활용하세요.")
                price_actions.append("후기 수가 적다면 '리뷰 이벤트'로 초기 신뢰도를 확보하는 게 가격보다 중요합니다.")
        else:
            price_insights.append(f"상품 가격 정보를 확인할 수 없습니다. 1페이지 평균가는 {avg_price:,}원입니다.")
            price_actions.append(f"경쟁 상품 가격대({min_price:,}~{max_price:,}원)를 참고해 포지셔닝을 결정하세요.")
            price_actions.append(f"TOP10 평균가({top5_avg:,}원) 이하로 진입하면 초기 클릭률 확보에 유리합니다.")

        # 가격 전략별 추천 광고 품목
        price_recs = []
        if my_price > 0 and avg_price > 0 and my_price / avg_price > 1.2:
            price_recs = [
                {"name": "체험단 마케팅", "reason": "프리미엄 가격의 정당성을 실사용 후기로 증명하여 구매 전환율을 높일 수 있습니다."},
                {"name": "고객 참여형 이벤트", "reason": "알림받기·리뷰 이벤트로 가격 부담을 상쇄하는 혜택을 제공하세요."},
                {"name": "올해의 시상·수상·선정 상패", "reason": "수상 이력은 프리미엄 가격의 가장 강력한 근거입니다. 썸네일과 상세페이지에 배치하세요."},
            ]
        elif my_price > 0 and avg_price > 0 and my_price / avg_price < 0.8:
            price_recs = [
                {"name": "쇼핑검색광고", "reason": "가격 경쟁력이 있으므로 광고 노출만 확보하면 클릭률과 전환율이 높을 수 있습니다."},
                {"name": "CPA 리워드 마케팅", "reason": "저렴한 가격 + 리워드 혜택으로 초기 구매 건수를 빠르게 쌓을 수 있습니다."},
                {"name": "성과형 디스플레이 광고", "reason": "가성비 소구로 넓은 타겟에게 노출 시 전환 효율이 높습니다."},
            ]
        else:
            price_recs = [
                {"name": "고객 참여형 이벤트", "reason": "비슷한 가격대에서는 리뷰 이벤트·알림받기로 체감 혜택을 만들어 차별화하세요."},
                {"name": "마케팅 메세지", "reason": "기존 고객에게 재구매 유도 메세지를 발송하여 반복 매출을 확보하세요."},
            ]

        strategies.append({
            "area": "가격 포지셔닝 & 소구점",
            "icon": "💰",
            "severity": "high" if my_price > 0 and avg_price > 0 and my_price / avg_price > 1.2 else "low" if my_price > 0 and avg_price > 0 and my_price / avg_price < 0.8 else "medium",
            "insights": price_insights,
            "actions": price_actions,
            "recommendations": price_recs,
        })

        # ── 전략 2: 상품명 SEO 최적화 전략 ──
        seo_insights = []
        seo_actions = []
        if my_name:
            if my_has_keyword:
                kw_pos = my_name.replace(" ", "").lower().find(req.keyword.replace(" ", "").lower())
                pos_pct = round(kw_pos / max(len(my_name.replace(" ", "")), 1) * 100)
                seo_insights.append(f"핵심 키워드 '{req.keyword}'가 상품명의 {pos_pct}% 지점에 위치합니다." + (" 앞부분 배치로 SEO에 유리합니다." if pos_pct < 30 else " 가능하면 앞부분(30% 이내)에 배치하면 노출 확률이 높아집니다."))
            else:
                seo_insights.append(f"상품명에 '{req.keyword}' 키워드가 없습니다. 1페이지 상품 중 {keyword_in_name_ratio}%가 포함하고 있어 필수 삽입이 필요합니다.")
                seo_actions.append(f"상품명 앞부분에 '{req.keyword}'를 반드시 추가하세요. 키워드 앞부분 배치가 검색 노출에 가장 큰 영향을 줍니다.")

            seo_insights.append(f"현재 상품명 길이: {my_name_len}자 (1페이지 평균: {avg_name_length:.0f}자)")
            if kw_total > 0:
                seo_insights.append(f"1페이지 상품 중 {round(kw_front_count/max(kw_total,1)*100)}%가 키워드를 상품명 앞쪽에 배치하고 있습니다.")

            if common_words:
                seo_actions.append(f"TOP10 상품에서 반복 등장하는 키워드: [{', '.join(common_words[:5])}] — 이 중 빠진 단어가 있다면 상품명에 추가를 검토하세요.")
            seo_actions.append(f"네이버 쇼핑은 상품명 앞 40자를 중요하게 봅니다. 핵심 키워드를 앞에, 부가 정보(용량, 수량)는 뒤에 배치하세요.")
            seo_actions.append("특수문자(★, ●, ♥)는 네이버 알고리즘에서 감점 요인입니다. 대괄호[  ]와 슬래시만 사용하세요.")
        else:
            seo_insights.append("상품명 정보를 불러올 수 없습니다.")
            if common_words:
                seo_actions.append(f"1페이지 TOP10 공통 키워드: [{', '.join(common_words[:5])}] — 상품명 작성 시 참고하세요.")

        seo_recs = [
            {"name": "SEO 최적화", "reason": "상품명·카테고리·속성값 전반을 전문가가 진단하고 최적화하여 자연 검색 노출을 극대화합니다."},
            {"name": "쇼핑검색광고 자동입찰 프로그램", "reason": "SEO 최적화와 병행하면 자연 순위 + 광고 순위 동시 노출로 CTR을 2~3배 높일 수 있습니다."},
        ]
        if not my_has_keyword:
            seo_recs.append({"name": "쇼핑검색광고", "reason": "상품명 최적화 전까지 광고로 즉시 노출을 확보하여 판매 데이터를 축적하세요."})

        strategies.append({
            "area": "상품명 SEO 최적화",
            "icon": "🔍",
            "severity": "high" if not my_has_keyword else "low",
            "insights": seo_insights,
            "actions": seo_actions,
            "recommendations": seo_recs,
        })

        # ── 전략 3: 경쟁 환경 & 차별화 방향 ──
        comp_insights = []
        comp_actions = []
        if top_brands:
            brand_names = ', '.join([f"{b[0]}({b[1]}개)" for b in top_brands])
            comp_insights.append(f"상위 노출 브랜드: {brand_names}")
            if brand_concentration >= 30:
                comp_insights.append(f"상위 1개 브랜드가 {brand_concentration:.0f}%를 점유 — 브랜드 독점형 시장입니다. 정면 경쟁보다 틈새 소구가 유효합니다.")
                comp_actions.append("독점 브랜드와 다른 USP(Unique Selling Point)를 찾으세요. 예: 소량 패키지, 특수 원재료, 지역 특산, 수제/프리미엄 등")
            else:
                comp_insights.append(f"특정 브랜드 독점 없이 다양한 셀러가 경쟁 중 — 신규 진입 기회가 열려 있습니다.")
                comp_actions.append("브랜드 파워보다 '상세페이지 퀄리티'와 '리뷰 수'가 승부를 가릅니다.")

        if top_stores:
            store_names = ', '.join([s[0] for s in top_stores[:3]])
            comp_insights.append(f"주요 경쟁 스토어: {store_names}")

        comp_insights.append(f"주요 카테고리: '{top_cat}' (점유율 {cat_share}%)")
        if cat_share >= 70:
            comp_actions.append(f"카테고리를 '{top_cat}'으로 반드시 맞추세요. 다른 카테고리 설정 시 노출 자체가 불리합니다.")
        else:
            comp_actions.append(f"'{top_cat}' 카테고리가 가장 많지만 다양한 카테고리가 공존합니다. 상품 특성에 맞는 카테고리를 선택하되, 상위 상품과 같은 카테고리면 유리합니다.")

        if rank:
            if rank <= 10:
                comp_actions.append("이미 1페이지 상위권입니다. 현재 포지션을 유지하면서 클릭률(CTR)과 전환율 개선에 집중하세요.")
            elif rank <= 40:
                target_rank = max(1, rank - 10)
                comp_actions.append(f"현재 {rank}위로 1페이지 내 위치합니다. {target_rank}위권 진입을 목표로 리뷰 확보와 판매량 부스팅이 필요합니다.")
            else:
                comp_actions.append(f"현재 {rank}위(1페이지 밖)입니다. 네이버 쇼핑 광고(파워링크/쇼핑검색광고)로 초기 노출을 확보한 뒤, 판매 실적으로 자연 순위를 끌어올리는 2단계 전략을 추천합니다.")
        else:
            comp_actions.append("검색 결과에 노출되지 않고 있습니다. 네이버 쇼핑 광고 집행 + 상품명 최적화를 동시에 진행해 초기 데이터를 쌓으세요.")

        comp_recs = []
        if not rank or rank > 40:
            comp_recs = [
                {"name": "쇼핑검색광고", "reason": "1페이지 밖이라면 광고가 가장 빠른 노출 확보 수단입니다. 초기 판매 실적을 쌓아 자연 순위를 끌어올리세요."},
                {"name": "외부 플랫폼 광고", "reason": "쿠팡·토스·당근 등 외부 채널로 유입 경로를 다변화하면 네이버 의존도를 낮추고 총 매출을 키울 수 있습니다."},
                {"name": "성과형 디스플레이 광고", "reason": "네이버 메인·서브 지면에 배너 노출로 브랜드 인지도와 스토어 유입을 동시에 확보합니다."},
            ]
        elif rank > 10:
            comp_recs = [
                {"name": "쇼핑검색광고 자동입찰 프로그램", "reason": "자동입찰로 효율적인 광고비 운용 + 상위 노출을 유지하여 자연 순위 상승을 가속화합니다."},
                {"name": "외부 매체 광고", "reason": "모비온·구글GDN·메타광고로 리타겟팅하면 이탈 고객을 재유입하여 전환율을 높입니다."},
                {"name": "픽셀 설치", "reason": "고객 모수를 확보하면 리타겟팅 광고의 정확도가 올라가 광고 효율이 크게 개선됩니다."},
            ]
        else:
            comp_recs = [
                {"name": "언론 기사", "reason": "상위권 유지 단계에서는 뉴스 기사 배포로 브랜드 신뢰도를 강화하여 경쟁사와 격차를 벌리세요."},
                {"name": "올해의 시상·수상·선정 상패", "reason": "수상 이력 확보 시 썸네일·상세페이지에 배치하면 클릭률과 전환율 모두 상승합니다."},
                {"name": "SNS 영상 광고", "reason": "유튜브·인스타그램 영상으로 브랜드 팬층을 확보하면 자연 검색량 자체가 증가합니다."},
            ]

        strategies.append({
            "area": "경쟁 환경 & 차별화 방향",
            "icon": "⚔️",
            "severity": "high" if (not rank or rank > 40) else "medium" if rank > 10 else "low",
            "insights": comp_insights,
            "actions": comp_actions,
            "recommendations": comp_recs,
        })

        # ── 전략 4: 전환율 극대화 (상세페이지 & 리뷰) ──
        conv_insights = []
        conv_actions = []
        if rank and rank <= 40:
            conv_insights.append(f"1페이지에 노출되고 있으나, 노출 → 클릭 → 구매 전환 파이프라인에서 각 단계의 이탈을 최소화해야 합니다.")
        else:
            conv_insights.append("노출이 확보되면 전환율이 매출을 결정합니다. 미리 상세페이지와 리뷰를 준비해두세요.")

        conv_actions.append("썸네일 최적화: 1페이지 경쟁 상품과 나란히 놓고 비교해보세요. 흰 배경 + 제품 클로즈업 + 핵심 문구 1줄이 클릭률이 가장 높습니다.")
        conv_actions.append("상세페이지 첫 3스크롤이 구매를 결정합니다. ①핵심 베네핏 ②사용 후기/인증 ③스펙 비교표 순서로 구성하세요.")
        conv_actions.append("리뷰 30개 이상이 전환율 임계점입니다. 초기에 '포토리뷰 이벤트'로 빠르게 확보하세요. 텍스트 리뷰보다 포토리뷰가 2.3배 전환에 기여합니다.")
        conv_actions.append("구매 결정 장벽을 낮추세요: '100% 환불 보장', '무료 교환', '당일 출고' 문구가 전환율을 평균 15~25% 높입니다.")

        conv_recs = [
            {"name": "체험단 마케팅", "reason": "실사용 포토리뷰가 누적되면 상세페이지 체류 시간과 구매 전환율이 동시에 상승합니다."},
            {"name": "고객 참여형 이벤트", "reason": "리뷰 이벤트로 포토리뷰 30개 이상을 빠르게 확보하세요. 전환율 임계점을 돌파하는 가장 효율적인 방법입니다."},
            {"name": "CPA 리워드 마케팅", "reason": "구매 완료 시 리워드를 제공하면 초기 판매 건수를 빠르게 확보하고 리뷰도 동시에 쌓을 수 있습니다."},
            {"name": "픽셀 설치", "reason": "방문 고객 데이터를 수집하면 리타겟팅 광고로 이탈 고객을 재전환할 수 있어 전환율이 크게 개선됩니다."},
        ]

        strategies.append({
            "area": "전환율 극대화 전략",
            "icon": "🎯",
            "severity": "medium",
            "insights": conv_insights,
            "actions": conv_actions,
            "recommendations": conv_recs,
        })

        # ── 전략 5: 실행 로드맵 (즉시/1주/1개월) ──
        roadmap_actions = []
        # 즉시
        immediate = []
        if not my_has_keyword:
            immediate.append(f"상품명에 '{req.keyword}' 키워드 추가")
        if my_price > 0 and avg_price > 0 and my_price / avg_price > 1.2:
            immediate.append("첫구매 쿠폰 또는 할인 이벤트 설정")
        immediate.append("썸네일 이미지 경쟁사 대비 점검 및 개선")
        immediate.append("배송 정보(당일출고, 무료배송) 확인 및 강조")
        roadmap_actions.append(f"[즉시 실행] {' / '.join(immediate)}")

        # 1주 내
        week1 = ["포토리뷰 이벤트 기획 및 시작", "상세페이지 상단 3스크롤 리뉴얼"]
        if not rank or rank > 40:
            week1.append("네이버 쇼핑검색광고 세팅 (일예산 3~5만원 권장)")
        roadmap_actions.append(f"[1주 내] {' / '.join(week1)}")

        # 1개월 내
        month1 = ["리뷰 30개 이상 확보 목표", "검색 순위 변동 모니터링 (본 도구 활용)"]
        if rank and rank <= 40:
            month1.append(f"목표 순위: {max(1, rank-10)}위권 진입")
        else:
            month1.append("목표: 1페이지(40위 이내) 진입")
        roadmap_actions.append(f"[1개월 내] {' / '.join(month1)}")

        roadmap_recs = []
        if not rank or rank > 40:
            roadmap_recs = [
                {"name": "쇼핑검색광고", "reason": "[즉시] 1페이지 미노출 상태에서 가장 빠르게 노출을 확보하는 핵심 수단입니다."},
                {"name": "체험단 마케팅", "reason": "[1주 내] 리뷰 0건에서 시작한다면, 체험단으로 포토리뷰 10~20개를 2주 내 확보하세요."},
                {"name": "SEO 최적화", "reason": "[즉시~1주] 상품명·카테고리·속성 최적화는 모든 전략의 기반입니다. 가장 먼저 진행하세요."},
                {"name": "마케팅 메세지", "reason": "[1개월] 구매 고객에게 재구매·리뷰 유도 메세지를 발송하여 지속 성장 구조를 만드세요."},
            ]
        elif rank > 10:
            roadmap_recs = [
                {"name": "쇼핑검색광고 자동입찰 프로그램", "reason": "[즉시] 효율적 입찰로 광고비를 절감하면서 상위 노출을 유지하세요."},
                {"name": "고객 참여형 이벤트", "reason": "[1주 내] 리뷰 이벤트로 전환율 임계점(30개)을 돌파하세요."},
                {"name": "외부 매체 광고", "reason": "[1개월] 리타겟팅으로 이탈 고객을 재유입하여 매출을 극대화하세요."},
            ]
        else:
            roadmap_recs = [
                {"name": "SNS 영상 광고", "reason": "[1주 내] 상위권 유지 중이므로 브랜드 인지도를 키워 자연 검색량을 늘리세요."},
                {"name": "언론 기사", "reason": "[1개월] 뉴스 기사로 브랜드 권위를 확보하면 경쟁사 진입 장벽이 됩니다."},
                {"name": "올해의 시상·수상·선정 상패", "reason": "[1개월] 수상 배지를 썸네일에 표시하면 CTR이 평균 20% 이상 상승합니다."},
            ]

        strategies.append({
            "area": "실행 로드맵",
            "icon": "📋",
            "severity": "info",
            "insights": [
                f"'{req.keyword}' 키워드로 1페이지 진입/상위권 달성을 위한 단계별 실행 계획입니다.",
                "각 단계를 순서대로 실행하면 가장 효율적으로 순위를 개선할 수 있습니다."
            ],
            "actions": roadmap_actions,
            "recommendations": roadmap_recs,
        })

        # 전체 종합 점수 계산
        score = 50
        if rank:
            if rank <= 10:
                score += 30
            elif rank <= 40:
                score += 15
            elif rank <= 100:
                score += 5
        if my_has_keyword:
            score += 10
        if my_price > 0 and avg_price > 0 and my_price <= avg_price:
            score += 10
        score = min(score, 100)

        return {
            "success": True,
            "data": {
                "keyword": req.keyword,
                "product_url": req.product_url,
                "product_info": product_info,
                "ranking": {
                    "current_rank": rank,
                    "page_number": page,
                    "total_searched": len(page1_products),
                    "is_on_page1": rank is not None and rank <= 40,
                },
                "competitor_comparison": {
                    "items": competitor_comparison,
                    "stats": {
                        "avg_price": avg_price,
                        "min_price": min_price,
                        "max_price": max_price,
                        "avg_name_length": avg_name_length,
                        "keyword_in_name_ratio": keyword_in_name_ratio,
                    },
                },
                "entry_strategy": {
                    "overall_score": score,
                    "strategies": strategies,
                },
                "analyzed_at": datetime.now().isoformat(),
            }
        }
    except Exception as e:
        logger.error(f"광고주 분석 실패: {e}")
        raise HTTPException(status_code=500, detail="광고주 분석 중 오류가 발생했습니다.")


# --- AI 피드백 통합 (1회 호출) ---
class AiFeedbackAllRequest(BaseModel):
    keyword: str
    sections: Dict[str, Any]  # {"volume": {...}, "competition": {...}, ...}
    client_name: Optional[str] = ""
    client_id: Optional[int] = 0
    call_type: Optional[str] = "manual"

@app.post("/api/ai/feedback-all")
async def ai_feedback_all(req: AiFeedbackAllRequest, current_user: dict = Depends(get_current_user)):
    """Claude AI 기반 통합 분석 피드백 — 전 섹션을 1회 API 호출로 생성"""
    try:
        import anthropic, json

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"success": False, "error": "ANTHROPIC_API_KEY가 설정되지 않았습니다."}

        client = anthropic.Anthropic(api_key=api_key)

        section_labels = {
            "volume": ("검색량 분석", "PC/모바일 검색 비율, CTR, CPC 효율성을 수치로 분석하고 광고 vs SEO 투자 판단 근거를 제시하세요."),
            "market": ("시장 규모", "월 거래액, 마진율, BEP 시나리오를 분석하세요."),
            "competition": ("경쟁강도", "상품 수 대비 검색량, 브랜드 비율을 분석하고 1페이지 진입을 위한 현실적 목표(리뷰수, 판매건수)를 제시하세요."),
            "related": ("연관 키워드", "구매의도/정보탐색/브랜드 키워드를 분류하고 공략 우선순위와 활용법을 제시하세요."),
            "trend": ("키워드 트렌드", "시즌성, 성장 추세를 분석하고 광고/재고/SEO 최적 타이밍을 제시하세요."),
            "golden": ("골든 키워드", "검색량 대비 경쟁도가 낮은 키워드 우선순위와 상품명 최적화 예시를 제시하세요."),
            "competitor": ("경쟁사 비교", "경쟁사 가격/리뷰/상품명을 비교하고 차별화 전략을 제시하세요."),
            "sales": ("판매량 추정", "순위별 매출 시나리오와 투자 대비 수익률(ROAS)을 분석하세요."),
            "strategy": ("진입 전략", "가격/상품명/카테고리/리뷰별 개선 우선순위와 1주~3개월 실행 계획을 제시하세요."),
        }

        # 데이터가 있는 섹션만 프롬프트에 포함
        section_blocks = []
        for sec_key, sec_data in req.sections.items():
            if sec_data is None:
                continue
            label_info = section_labels.get(sec_key)
            if not label_info:
                continue
            label, instruction = label_info
            data_str = json.dumps(sec_data, ensure_ascii=False, default=str)
            if len(data_str) > 1500:
                data_str = data_str[:1500] + "...(생략)"
            section_blocks.append(f"[{label}]\n데이터: {data_str}\n분석 지시: {instruction}")

        if not section_blocks:
            return {"success": False, "error": "분석할 데이터가 없습니다."}

        combined_data = "\n\n---\n\n".join(section_blocks)

        system_prompt = """당신은 메타아이앤씨(METAINC) 시니어 네이버 쇼핑 마케팅 컨설턴트입니다.
네이버 쇼핑 알고리즘(적합도·인기도·신뢰도)에 정통합니다.

작성 원칙:
- 광고주에게 1:1로 브리핑하듯 자연스러운 대화체로 작성하세요.
- 각 섹션별로 [섹션명] 구분자를 사용하되, 내용은 자연스럽게 서술하세요.
- 반드시 데이터 수치를 인용하며, 근거 없는 추상적 표현은 쓰지 마세요.
- 아이콘, 이모지, 특수기호(**, ##)는 사용하지 마세요.
- 각 섹션은 5~8줄 내외로, 현황→핵심 이슈→실행 전략 흐름으로 작성하세요.
- 마지막에 'METAINC 종합 인사이트'로 전체 요약과 핵심 액션 3가지를 짧게 정리하세요."""

        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{
                "role": "user",
                "content": f"""키워드 '{req.keyword}'에 대한 전체 분석 데이터입니다.
각 섹션별로 분석 피드백을 작성해주세요.

{combined_data}

각 섹션을 [섹션명] 형태로 구분하여, 광고주 브리핑 형식으로 작성하세요."""
            }],
            system=system_prompt
        )

        full_text = message.content[0].text if message.content else ""

        # API 사용량 로깅 (v3.9.13)
        try:
            from database import save_api_usage_log
            usage = message.usage  # input_tokens, output_tokens
            inp_tok = getattr(usage, 'input_tokens', 0)
            out_tok = getattr(usage, 'output_tokens', 0)
            cost = (inp_tok * 3 + out_tok * 15) / 1_000_000  # Sonnet 4 pricing
            save_api_usage_log(
                endpoint="feedback-all",
                keyword=req.keyword,
                client_name=getattr(req, 'client_name', '') or '',
                client_id=getattr(req, 'client_id', 0) or 0,
                call_type=getattr(req, 'call_type', 'manual') or 'manual',
                model="claude-sonnet-4-20250514",
                input_tokens=inp_tok,
                output_tokens=out_tok,
                cost_usd=cost,
                user_id=current_user.get("id", 0),
                status="success"
            )
        except Exception as log_err:
            logger.warning(f"API 사용량 로깅 실패 (무시): {log_err}")

        # 섹션별로 분리하여 반환
        import re
        feedback_dict = {}
        # [섹션명] 패턴으로 분리
        parts = re.split(r'\[([^\]]+)\]', full_text)
        # parts[0]은 첫 구분자 이전 텍스트 (보통 빈 문자열)
        # parts[1]=섹션명, parts[2]=내용, parts[3]=섹션명, parts[4]=내용, ...
        label_to_key = {v[0]: k for k, v in section_labels.items()}
        label_to_key["METAINC 종합 인사이트"] = "summary"
        for i in range(1, len(parts) - 1, 2):
            sec_name = parts[i].strip()
            sec_content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            matched_key = label_to_key.get(sec_name, sec_name)
            feedback_dict[matched_key] = sec_content

        # 파싱 실패 시 전체 텍스트를 summary로 반환
        if not feedback_dict:
            feedback_dict["summary"] = full_text

        return {
            "success": True,
            "data": {
                "keyword": req.keyword,
                "feedbacks": feedback_dict,
                "full_text": full_text,
                "generated_at": datetime.now().isoformat()
            }
        }
    except ImportError:
        return {"success": False, "error": "anthropic 패키지가 설치되지 않았습니다. pip install anthropic"}
    except Exception as e:
        logger.error(f"AI 통합 피드백 생성 실패: {e}")
        # 실패도 로깅
        try:
            from database import save_api_usage_log
            save_api_usage_log(
                endpoint="feedback-all", keyword=req.keyword,
                model="claude-sonnet-4-20250514",
                user_id=current_user.get("id", 0),
                status="error", error_message=str(e)[:200]  # 내부 로그용
            )
        except Exception:
            pass
        return {"success": False, "error": "AI 통합 피드백 생성 중 오류가 발생했습니다."}


# --- API 사용량 조회 (superadmin 전용, v3.9.13) ---
@app.get("/api/admin/api-usage")
async def get_api_usage(current_user: dict = Depends(get_current_user)):
    """API 사용량 대시보드 데이터 — superadmin 전용"""
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    try:
        from database import get_api_usage_summary
        data = get_api_usage_summary(days=30)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"API 사용량 조회 실패: {e}")
        return {"success": False, "error": "API 사용량 조회 중 오류가 발생했습니다."}


# ==================== 데이터랩 쇼핑인사이트 ====================

class DatalabRequest(BaseModel):
    keyword: str
    category1: str = ""
    related_keywords: list = []

@app.post("/api/datalab/analyze")
async def datalab_analyze(req: DatalabRequest, current_user: dict = Depends(get_current_user)):
    """네이버 데이터랩 쇼핑인사이트 통합 분석 (인증 필수)"""
    try:
        result = analyze_datalab(
            keyword=req.keyword,
            category1=req.category1,
            related_keywords=[{"keyword": k} if isinstance(k, str) else k for k in req.related_keywords],
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"데이터랩 분석 실패: {e}")
        return {"success": False, "detail": "데이터랩 분석 중 오류가 발생했습니다."}


# --- 헬스체크 ---
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.0.0", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5050, reload=True)
