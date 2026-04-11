"""
로직 분석 프로그램 v2 - 백엔드 API 서버
FastAPI 기반
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
import os
import re
import uvicorn
import logging

logger = logging.getLogger(__name__)

# API 키 인증
API_KEY = os.getenv("API_KEY", "")
# 인증 면제 경로
AUTH_EXEMPT_PATHS = ["/api/health", "/docs", "/openapi.json", "/redoc"]


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """API 키 기반 인증 미들웨어"""
    async def dispatch(self, request: Request, call_next):
        # 인증 면제 경로 확인
        if any(request.url.path.startswith(p) for p in AUTH_EXEMPT_PATHS):
            return await call_next(request)
        # OPTIONS (CORS preflight)는 통과
        if request.method == "OPTIONS":
            return await call_next(request)
        # API 키 미설정 시 인증 비활성화 (개발 모드)
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
    get_latest_competitors,
    get_notification_settings, update_notification_settings,
    get_notification_logs
)
from naver_crawler import (
    find_product_rank, get_product_info,
    generate_rank_analysis, extract_product_id_from_url,
    get_keyword_volume
)
from scheduler import start_scheduler, stop_scheduler, reschedule_report
from kakao_notify import (
    is_configured as is_solapi_configured,
    send_test_notification,
    collect_daily_rank_changes,
    generate_daily_report_text
)

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
        logger.warning("⚠️ API_KEY 미설정 — 인증 없이 모든 요청 허용됩니다. (개발 모드)")
    init_db()
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()

app = FastAPI(
    title="로직 분석 프로그램 v2",
    description="네이버 쇼핑 키워드 분석 + 상품 노출 순위 추적",
    version="2.0.0",
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

class KeywordAddRequest(BaseModel):
    product_id: int
    keyword: str

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
async def check_rank(req: RankCheckRequest):
    """키워드 + 상품URL로 실시간 순위 조회"""
    try:
        rank, page, competitors = find_product_rank(
            keyword=req.keyword,
            product_url=req.product_url,
            max_pages=2
        )
        product_info = get_product_info(req.product_url)
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
        raise HTTPException(status_code=500, detail=f"순위 조회 실패: {str(e)}")


# --- 상품 추적 등록 ---
@app.post("/api/products/track")
async def track_product(req: ProductAddRequest, background_tasks: BackgroundTasks):
    """상품 + 키워드 추적 등록"""
    try:
        # 상품 정보 가져오기
        product_info = get_product_info(req.product_url)
        product_id_str = extract_product_id_from_url(req.product_url)

        # DB에 상품 등록
        db_product_id = add_tracked_product(
            product_url=req.product_url,
            product_name=product_info.get("product_name"),
            store_name=product_info.get("store_name"),
            image_url=product_info.get("image_url"),
            price=product_info.get("price"),
            product_id=product_id_str,
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
        raise HTTPException(status_code=500, detail=f"상품 등록 실패: {str(e)}")


def run_initial_rank_check(product_id: int, product_url: str, keyword_ids: List[dict]):
    """초기 순위 체크 (백그라운드 - sync로 실행하여 스레드풀 활용)"""
    for kw_info in keyword_ids:
        try:
            rank, page, competitors = find_product_rank(
                keyword=kw_info["keyword"],
                product_url=product_url,
                max_pages=2
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
            logger.error(f""초기 순위 체크 실패 [{kw_info['keyword']}]: {e}")


# --- 추적 상품 목록 ---
@app.get("/api/products")
async def list_products():
    """추적 중인 상품 목록"""
    products = get_all_tracked_products()
    result = []
    for p in products:
        keywords = get_keywords_for_product(p["id"])
        p["keywords"] = keywords
        result.append(p)
    return {"success": True, "data": result}


# --- 상품 삭제 ---
@app.delete("/api/products/{product_id}")
async def remove_product(product_id: int):
    """추적 상품 삭제"""
    delete_tracked_product(product_id)
    return {"success": True, "message": "상품이 삭제되었습니다."}


# --- 키워드 추가 ---
@app.post("/api/keywords/add")
async def add_keyword(req: KeywordAddRequest):
    """기존 상품에 키워드 추가"""
    kid = add_tracked_keyword(req.product_id, req.keyword)
    return {"success": True, "data": {"keyword_id": kid, "keyword": req.keyword}}


# --- 순위 이력 조회 ---
@app.get("/api/rank/history/{keyword_id}")
async def rank_history(keyword_id: int, days: int = 30):
    """키워드별 순위 변동 이력 (최근 N일)"""
    days = min(max(days, 1), 365)
    history = get_ranking_history(keyword_id, days=days)
    return {"success": True, "data": history}


# --- 경쟁 상품 조회 ---
@app.get("/api/competitors/{keyword_id}")
async def competitors(keyword_id: int):
    """키워드별 상위 경쟁 상품"""
    comps = get_latest_competitors(keyword_id)
    return {"success": True, "data": comps}


# --- 수동 순위 체크 ---
@app.post("/api/rank/refresh/{product_id}")
async def refresh_rank(product_id: int, background_tasks: BackgroundTasks):
    """특정 상품의 모든 키워드 순위 재체크"""
    products = get_all_tracked_products()
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
async def keyword_volume(keywords: List[str]):
    """키워드 검색량 조회 (네이버 검색광고 API)"""
    try:
        data = get_keyword_volume(keywords)
        return {"success": True, "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"키워드 볼륨 조회 실패: {str(e)}")


# ==================== 알림톡 API ====================

# --- 알림 설정 조회 ---
@app.get("/api/notify/settings")
async def get_notify_settings():
    """현재 알림 설정 조회"""
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
async def update_notify_settings(req: NotificationSettingsRequest):
    """알림 설정 변경"""
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
        raise HTTPException(status_code=500, detail=f"설정 변경 실패: {str(e)}")


# --- 테스트 알림 발송 ---
@app.post("/api/notify/test")
async def test_notification():
    """테스트 알림 발송"""
    try:
        result = send_test_notification()
        return {"success": result.get("success", False), "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"테스트 알림 실패: {str(e)}")


# --- 알림 발송 이력 ---
@app.get("/api/notify/logs")
async def notify_logs(limit: int = 20):
    """알림 발송 이력 조회"""
    limit = min(max(limit, 1), 100)
    logs = get_notification_logs(limit)
    return {"success": True, "data": logs}


# --- 리포트 미리보기 ---
@app.get("/api/notify/preview")
async def preview_report():
    """현재 데이터 기반 리포트 미리보기"""
    try:
        rank_data = collect_daily_rank_changes()
        report_text = generate_daily_report_text(rank_data)
        return {
            "success": True,
            "data": {
                "report_text": report_text,
                "rank_data": rank_data,
                "generated_at": datetime.now().isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"리포트 생성 실패: {str(e)}")


# --- 헬스체크 ---
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "2.1.0", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5050, reload=True)
