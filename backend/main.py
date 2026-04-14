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
from typing import Optional, List
from datetime import datetime
import os
import re
import time
import uvicorn
import logging

# v3 신규 모듈 임포트
from auth import router as auth_router, init_auth_db
from clients import router as clients_router, init_clients_db
from reports import router as reports_router, init_reports_db

logger = logging.getLogger(__name__)

# API 키 인증
API_KEY = os.getenv("API_KEY", "")
# 인증 면제 경로
AUTH_EXEMPT_PATHS = ["/api/health", "/docs", "/openapi.json", "/redoc", "/api/auth/login", "/api/auth/sso", "/api/reports/view/"]


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
    init_auth_db()
    init_clients_db()
    init_reports_db()
    start_scheduler()
    yield
    # Shutdown
    stop_scheduler()

app = FastAPI(
    title="로직 분석 프로그램 v2",
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
            logger.error(f"초기 순위 체크 실패 [{kw_info['keyword']}]: {e}")


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


# ==================== 보고서 내보내기 API ====================

class ReportExportRequest(BaseModel):
    format: str = "json"  # json | csv
    date_range: int = 30  # 최근 N일

@app.post("/api/report/export")
async def export_report(req: ReportExportRequest):
    """순위 데이터 보고서 내보내기"""
    try:
        products = get_all_tracked_products()
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
                     "total_keywords": sum(len(get_keywords_for_product(p["id"])) for p in products),
                     "generated_at": datetime.now().isoformat()}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"보고서 생성 실패: {str(e)}")


# ==================== SEO 종합 진단 API ====================

class SeoAnalysisRequest(BaseModel):
    product_url: str
    keyword: str

@app.post("/api/seo/analyze")
async def seo_analyze(req: SeoAnalysisRequest):
    """상품 SEO 종합 진단"""
    try:
        product_info = get_product_info(req.product_url)
        product_name = product_info.get("product_name", "")

        # 1. 상품명 키워드 포함 여부
        keyword_in_title = req.keyword.lower() in product_name.lower()
        title_length = len(product_name)

        # 2. 가격 경쟁력 분석
        rank, page, competitors = find_product_rank(
            keyword=req.keyword, product_url=req.product_url, max_pages=2
        )
        my_price = product_info.get("price", 0)
        comp_prices = [c.get("price", 0) for c in competitors if c.get("price", 0) > 0]
        avg_comp_price = sum(comp_prices) / len(comp_prices) if comp_prices else 0
        price_score = 0
        if my_price > 0 and avg_comp_price > 0:
            ratio = my_price / avg_comp_price
            if ratio <= 0.85:
                price_score = 100
            elif ratio <= 1.0:
                price_score = 80
            elif ratio <= 1.15:
                price_score = 60
            elif ratio <= 1.3:
                price_score = 40
            else:
                price_score = 20

        # 3. 상품명 최적화 점수
        title_score = 0
        if keyword_in_title:
            title_score += 40
        if 20 <= title_length <= 50:
            title_score += 30
        elif 10 <= title_length <= 70:
            title_score += 20
        else:
            title_score += 10
        # 특수문자 과다 체크
        special_chars = sum(1 for c in product_name if c in '!@#$%^&*()[]{}|<>★☆♥♡')
        if special_chars <= 2:
            title_score += 30
        elif special_chars <= 5:
            title_score += 15

        # 4. 순위 점수
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

        # 5. 종합 점수
        total_score = int(title_score * 0.3 + price_score * 0.25 + rank_score * 0.35 + (30 if product_info.get("image_url") else 0) * 0.1)

        # 6. 개선 제안 생성
        suggestions = []
        if not keyword_in_title:
            suggestions.append(f"상품명에 '{req.keyword}' 키워드를 포함시키세요.")
        if title_length < 15:
            suggestions.append("상품명이 너무 짧습니다. 핵심 키워드를 추가하세요.")
        elif title_length > 60:
            suggestions.append("상품명이 길어 가독성이 낮을 수 있습니다.")
        if special_chars > 3:
            suggestions.append("특수문자 사용을 줄이면 검색 노출에 유리합니다.")
        if my_price > avg_comp_price * 1.2 and avg_comp_price > 0:
            suggestions.append(f"경쟁 상품 대비 가격이 높습니다 (평균 {int(avg_comp_price):,}원).")
        if not rank:
            suggestions.append("200위 내 미노출 — 키워드 재설정 또는 상품명 최적화가 필요합니다.")
        if not suggestions:
            suggestions.append("전반적으로 양호합니다. 리뷰 확보에 집중하세요.")

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
                    "detail": {
                        "keyword_in_title": keyword_in_title,
                        "title_length": title_length,
                        "special_chars": special_chars,
                        "current_rank": rank,
                        "my_price": my_price,
                        "avg_competitor_price": int(avg_comp_price),
                    }
                },
                "suggestions": suggestions,
                "competitors": competitors[:5],
                "analyzed_at": datetime.now().isoformat(),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SEO 분석 실패: {str(e)}")


# ==================== 상품 검색 API (키워드로 쇼핑 상품 조회) ====================

class ProductSearchRequest(BaseModel):
    keyword: str
    count: int = 40

@app.post("/api/products/search")
async def search_products(req: ProductSearchRequest):
    """네이버 쇼핑에서 키워드로 상품 검색 (상위 N개)"""
    try:
        from naver_crawler import search_naver_shopping_api, _parse_api_item
        result = search_naver_shopping_api(req.keyword, display=min(req.count, 100))
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
        raise HTTPException(status_code=500, detail=f"상품 검색 실패: {str(e)}")


# ==================== 연관/황금 키워드 API ====================

class RelatedKeywordRequest(BaseModel):
    keyword: str

@app.post("/api/keywords/related")
async def related_keywords(req: RelatedKeywordRequest):
    """연관 키워드 + 황금 키워드 분석"""
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

            for kd in data.get("keywordList", []):
                rel_kw = kd.get("relKeyword", "")
                pc = _safe_int(kd.get("monthlyPcQcCnt"))
                mobile = _safe_int(kd.get("monthlyMobileQcCnt"))
                total_volume = pc + mobile
                comp_idx = kd.get("compIdx", "")

                # 황금키워드 판별: 검색량 적당 + 경쟁 낮음
                is_golden = (
                    100 <= total_volume <= 5000 and
                    comp_idx in ("낮음", "LOW", "")
                )

                all_keywords.append({
                    "keyword": rel_kw,
                    "monthlyPcQcCnt": pc,
                    "monthlyMobileQcCnt": mobile,
                    "totalVolume": total_volume,
                    "compIdx": comp_idx,
                    "isGolden": is_golden,
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
        raise HTTPException(status_code=500, detail=f"연관 키워드 분석 실패: {str(e)}")


# ==================== 상품명 키워드 분석 API ====================

class ProductNameAnalysisRequest(BaseModel):
    product_names: List[str]  # 분석할 상품명 목록
    keyword: str = ""  # 기준 키워드 (선택)

@app.post("/api/product-name/analyze")
async def analyze_product_names(req: ProductNameAnalysisRequest):
    """상품명에서 키워드 추출 및 빈도 분석"""
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
        raise HTTPException(status_code=500, detail=f"상품명 분석 실패: {str(e)}")


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
async def advertiser_analyze(req: AdvertiserAnalysisRequest):
    """광고주 맞춤 분석 리포트: 순위 현황 + 경쟁사 비교 + 1페이지 진입 전략"""
    try:
        from naver_crawler import search_naver_shopping_api, _parse_api_item

        # 1) 광고주 상품 정보 조회
        product_info = get_product_info(req.product_url)

        # 2) 키워드로 순위 검색
        rank, page, top_competitors = find_product_rank(
            keyword=req.keyword, product_url=req.product_url, max_pages=4
        )

        # 3) 상위 40개 상품 가져오기 (1페이지 분석용)
        shop_result = search_naver_shopping_api(req.keyword, display=40)
        shop_items = shop_result.get("items", [])
        page1_products = [_parse_api_item(item, idx + 1) for idx, item in enumerate(shop_items)]

        # 4) 경쟁사 비교 분석 데이터 구성
        my_price = product_info.get("price", 0)
        my_name = product_info.get("product_name", "")

        competitor_comparison = []
        prices = []
        review_counts = []
        name_lengths = []

        for p in page1_products[:20]:
            has_keyword = req.keyword.lower() in p.get("product_name", "").lower()
            comp_item = {
                "rank": p["rank"],
                "product_name": p["product_name"],
                "store_name": p["store_name"],
                "price": p["price"],
                "brand": p.get("brand", ""),
                "category": p.get("category2") or p.get("category1") or "-",
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

        # 5) 1페이지 진입 전략 분석
        strategies = []

        # 가격 전략
        if my_price > 0 and avg_price > 0:
            price_ratio = my_price / avg_price
            if price_ratio > 1.2:
                strategies.append({
                    "area": "가격",
                    "status": "개선 필요",
                    "severity": "high",
                    "current": f"{my_price:,}원",
                    "target": f"{avg_price:,}원 이하",
                    "detail": f"경쟁 상품 평균가 대비 {round((price_ratio - 1) * 100)}% 높음. 가격 조정 또는 할인 이벤트를 검토하세요."
                })
            elif price_ratio > 1.0:
                strategies.append({
                    "area": "가격",
                    "status": "보통",
                    "severity": "medium",
                    "current": f"{my_price:,}원",
                    "target": f"{avg_price:,}원 이하",
                    "detail": f"경쟁 상품 평균가와 비슷한 수준입니다. 추가 할인이나 묶음 판매를 고려하세요."
                })
            else:
                strategies.append({
                    "area": "가격",
                    "status": "양호",
                    "severity": "low",
                    "current": f"{my_price:,}원",
                    "target": f"현재 유지",
                    "detail": f"경쟁 상품 평균가({avg_price:,}원)보다 낮아 가격 경쟁력이 있습니다."
                })
        elif my_price == 0:
            strategies.append({
                "area": "가격",
                "status": "확인 불가",
                "severity": "medium",
                "current": "정보 없음",
                "target": f"평균 {avg_price:,}원 참고",
                "detail": "상품 가격 정보를 불러올 수 없습니다. URL을 확인하세요."
            })

        # 상품명 전략
        my_has_keyword = req.keyword.lower() in my_name.lower() if my_name else False
        my_name_len = len(my_name)
        if not my_has_keyword:
            strategies.append({
                "area": "상품명 키워드",
                "status": "개선 필요",
                "severity": "high",
                "current": "미포함",
                "target": f"'{req.keyword}' 포함",
                "detail": f"상품명에 '{req.keyword}' 키워드가 없습니다. 1페이지 상품의 {keyword_in_name_ratio}%가 키워드를 포함하고 있습니다."
            })
        else:
            strategies.append({
                "area": "상품명 키워드",
                "status": "양호",
                "severity": "low",
                "current": "포함됨",
                "target": "유지",
                "detail": f"상품명에 '{req.keyword}' 키워드가 잘 포함되어 있습니다."
            })

        if my_name_len > 0 and (my_name_len < 15 or my_name_len > 60):
            strategies.append({
                "area": "상품명 길이",
                "status": "개선 필요",
                "severity": "medium",
                "current": f"{my_name_len}자",
                "target": f"20~50자 (평균 {avg_name_length}자)",
                "detail": "1페이지 상품의 평균 상품명 길이는 {:.0f}자입니다. 적절한 길이로 조정하세요.".format(avg_name_length)
            })

        # 카테고리 전략
        if page1_products:
            cat_map = {}
            for p in page1_products[:20]:
                cat = p.get("category2") or p.get("category1") or "기타"
                cat_map[cat] = cat_map.get(cat, 0) + 1
            top_cat = max(cat_map, key=cat_map.get) if cat_map else "-"
            strategies.append({
                "area": "카테고리",
                "status": "참고",
                "severity": "info",
                "current": product_info.get("category", "-"),
                "target": top_cat,
                "detail": f"1페이지 상위 상품의 주요 카테고리는 '{top_cat}'입니다. 카테고리 설정을 확인하세요."
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
        raise HTTPException(status_code=500, detail=f"광고주 분석 실패: {str(e)}")


# --- 헬스체크 ---
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "3.0.0", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5050, reload=True)
