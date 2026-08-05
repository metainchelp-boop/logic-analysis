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
import faulthandler

# 네이티브 크래시(SIGSEGV/SIGABRT 등) 발생 시 파이썬 스택을 stderr에 덤프한다.
# 워커가 커널 로그(dmesg)에 안 찍히는 방식으로 죽을 때 정확한 크래시 위치를
# docker logs에서 확인하기 위함. (동작 변화 없음, 진단 전용)
faulthandler.enable()

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
from seo_generate import router as seo_generate_router, init_seo_db
from collector import router as collector_router, init_collector_db
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
    get_keyword_product_and_count, delete_tracked_keyword,
    save_ranking, get_ranking_history, save_competitor_snapshot,
    get_notification_settings, update_notification_settings
)
from naver_crawler import (
    find_product_rank, get_product_info,
    generate_rank_analysis, extract_product_id_from_url,
    extract_store_name_from_url, search_products,
    get_keyword_volume
)
from scheduler import start_scheduler, stop_scheduler, reschedule_report
from kakao_notify import is_configured as is_solapi_configured
import place_crawler  # 플레이스(지역 검색) 업종 어댑터 — vertical="place" 분기에서만 사용

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

    # 보관 개수: 1.2GB×5 ≈ 6GB. 이전 14개(약 17GB)는 36GB 디스크에서 과다 → 디스크 풀 유발.
    MAX_BACKUPS = 5

    def _list_backups():
        return sorted(
            f for f in os.listdir(backup_dir)
            if f.startswith("logic_analysis_backup_") and f.endswith(".db")
        )

    def _prune(keep):
        try:
            bks = _list_backups()
            while len(bks) > keep:
                old = bks.pop(0)
                os.remove(os.path.join(backup_dir, old))
                logger.info(f"  🗑️ 오래된 백업 삭제: {old}")
        except Exception as _pe:
            logger.warning(f"백업 정리 실패(무시): {_pe}")

    # 1) 잦은 재시작 시 백업 폭증 방지: 최근 6시간 내 백업이 있으면 새 백업 생략(개수 정리만)
    try:
        _existing = _list_backups()
        if _existing:
            _latest = os.path.join(backup_dir, _existing[-1])
            _age = time.time() - os.path.getmtime(_latest)
            if _age < 6 * 3600:
                logger.info(f"ℹ️ 최근({int(_age/60)}분 전) 백업 존재 — 시작 시 백업 생략")
                _prune(MAX_BACKUPS)
                return
    except Exception:
        pass

    # 2) 새 백업 전에 먼저 정리해 공간 확보(꽉 찬 상태에서 백업 실패 방지)
    _prune(MAX_BACKUPS - 1)

    # 3) 디스크 여유 가드: 여유 < DB크기×1.5면 백업 생략(디스크 풀로 앱 마비 방지)
    try:
        _db_size = os.path.getsize(db_path)
        _free = shutil.disk_usage(backup_dir).free
        if _free < _db_size * 1.5:
            logger.error(
                f"⚠️ 디스크 여유 부족(여유 {_free//(1024**2)}MB < 필요 {int(_db_size*1.5)//(1024**2)}MB) "
                f"— 백업 생략. 디스크 정리가 필요합니다!"
            )
            return
    except Exception:
        pass

    # 4) 백업 생성
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
        # 실패 시 부분 파일 제거(공간 점유 방지) 후 파일 복사 fallback
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        except Exception:
            pass
        try:
            shutil.copy2(db_path, backup_path)
            logger.info(f"✅ DB 백업 완료 (파일 복사): {backup_path}")
        except Exception as e2:
            try:
                if os.path.exists(backup_path):
                    os.remove(backup_path)
            except Exception:
                pass
            logger.error(f"❌ DB 백업 실패: {e2}")

    # 5) 최종 보관 개수 정리
    _prune(MAX_BACKUPS)


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
    init_seo_db()
    init_collector_db()   # 수집기 테이블(collected_serp)

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
app.include_router(seo_generate_router)
app.include_router(collector_router)  # 브라우저 수집기(크롬 확장) — 2026-08-03 쇼핑 API 종료 대응


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
    # 분석 화면에서 이미 확보한 실제 스토어명(상세 HTML·광고주 리포트) — 등록 시
    # 쇼핑 검색으로 이름을 못 구해 URL 슬러그가 저장되는 문제의 예방 힌트(선택)
    store_name_hint: Optional[str] = None

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


# ── 쇼핑 크롤 공유 헬퍼 (과부하 방지) ──────────────────────────────
# 여러 직원/워커(uvicorn 5개)가 같은 키워드를 짧은 시간에 크롤하면 네이버 쇼핑 API를
# 중복 호출한다. 이를 3시간 DB 공유 캐시(database.shopping_search_cache)로 1회로 합쳐
# 일일 한도(25,000) 소진·과부하를 막는다.
#   - read_cache=True : 캐시 우선(분석·스냅샷용, 3시간 staleness 허용)
#   - read_cache=False: 항상 새로 크롤(실시간 조회용)하되 결과는 캐시에 채워 후속 분석과 공유
# 캐시 조회/저장 실패는 전부 방어적으로 무시하고 직접 크롤로 폴백 → 기능은 절대 멈추지 않음.
def _shared_crawl(keyword: str, max_results: int = 500, read_cache: bool = True, ttl: int = None) -> list:
    from naver_crawler import search_products as _sp
    products = None
    cache_ok = False
    try:
        from database import get_cached_shopping_search, save_cached_shopping_search
        cache_ok = True
        if read_cache:
            products = get_cached_shopping_search(keyword, max_results, ttl=ttl)
            if products is not None:
                logger.info(f"[크롤캐시] 히트 '{keyword}' ({len(products)}개) — 네이버 재호출 없음")
    except Exception as _ce:
        logger.warning(f"[크롤캐시] 우회(직접 크롤): {_ce}")
        products, cache_ok = None, False
    if products is None:
        products = _sp(keyword, max_results=max_results, retry_on_429=True)
        if cache_ok:
            try:
                save_cached_shopping_search(keyword, max_results, products)
            except Exception as _ce:
                logger.warning(f"[크롤캐시] 저장 우회: {_ce}")
    return products


# --- 실시간 순위 조회 ---
@app.post("/api/rank/check")
def check_rank(req: RankCheckRequest, current_user: dict = Depends(get_current_user)):
    """키워드 + 상품URL로 실시간 순위 조회 (인증 필수, viewer 제한은 handleSearch에서 관리)"""
    try:
        product_info = get_product_info(req.product_url, keyword=req.keyword)
        # 호출 다이어트(2026-07): '항상 신규 크롤(5콜)' → 10분 단기 캐시 허용.
        # 네이버 쇼핑 순위는 분 단위로 변하지 않아 실시간성 손실 없이 검색 API 소모를 크게 줄임.
        _prods = _shared_crawl(req.keyword, 500, ttl=600)
        rank, page, competitors = find_product_rank(
            keyword=req.keyword,
            product_url=req.product_url,
            max_pages=5,
            product_name=product_info.get("product_name", ""),
            cached_products=_prods,
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
    extra_keywords: List[str] = []   # 연관/황금 키워드 등 추가 후보 (대체 추천용)

@app.post("/api/rank/keyword-exposure")
def keyword_exposure(req: KeywordExposureRequest, current_user: dict = Depends(get_current_user)):
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

        # 후보 키워드 구성: 검색한 '메인 키워드'를 맨 앞에 포함(그 키워드의 노출 여부를
        #   함께 보여줘야 함) + 연관/황금 키워드(추가) + 상품명 키워드, 최대 10개
        main_kw_raw = (req.keyword or "").strip()
        main_kw = main_kw_raw.lower()
        extra = [k.strip() for k in (req.extra_keywords or []) if k and k.strip()]
        # R6: 내 상품 키워드(메인+상품명 토큰)를 우선 채우고, 연관/급상승(extra)은 '참고용'으로 뒤에.
        #     노출률 분모는 내 상품 키워드만 사용 → 사과·양하 같은 무관 연관어로 노출률이 왜곡되던 문제 방지.
        own_candidates, _seen = [], set()
        if main_kw_raw:
            own_candidates.append(main_kw_raw)
            _seen.add(main_kw)
        for k in sorted(keywords):
            kl = k.strip().lower()
            if not kl or kl in _seen:
                continue
            _seen.add(kl)
            own_candidates.append(k.strip())
            if len(own_candidates) >= 6:  # 후보 축소(10→6): 라이브 크롤 수를 줄여 예산 내 완주율↑·스피너 단축
                break
        ref_candidates = []
        for k in extra:
            kl = k.strip().lower()
            if not kl or kl in _seen:
                continue
            _seen.add(kl)
            ref_candidates.append(k.strip())
            if len(own_candidates) + len(ref_candidates) >= 8:  # 총 12→8
                break
        candidates = own_candidates + ref_candidates
        own_set = set(c.strip().lower() for c in own_candidates)

        if not candidates:
            return {"success": True, "data": {"product_name": product_name, "results": [], "recommended": []}}

        # 병렬로 순위 조회 (max_pages=2 = 상위 200위까지, find_product_rank는 429 재시도 적용됨)
        # ⚠️ 부하/속도: 키워드 여러 개를 라이브로 조회하므로 200위로 제한(400→200)해
        #    호출량을 절반으로 줄여 응답을 빠르게(스피너 단축)·429 완화. 상품 자체 키워드는
        #    통상 상위 200위 안에서 노출되므로 실사용 손실은 작다.
        results = []
        def check_one(kw):
            try:
                _prods = _shared_crawl(kw, 200)  # 공유 캐시(3h) → 반복/동시 노출조회 중복 크롤 제거
                rank, page, _ = find_product_rank(kw, req.product_url, max_pages=2, cached_products=_prods)
                return {"keyword": kw, "rank": rank, "page": page}
            except Exception:
                return {"keyword": kw, "rank": None, "page": None}

        # ⏱️ 벽시계 예산: 이 시간 안에 끝난 키워드만 모으고, 지연된 키워드는 '미조회(None)'로 채워
        #    '부분 결과라도 항상 반환'한다. 느린 네이버 조회로 요청이 프록시 타임아웃(≈60s)에 걸려
        #    노출 분석 섹션이 통째로 사라지던 문제 방지(504 대신 부분 성공).
        # 후보를 8개로 줄이고 워커를 6으로 늘려(≈2웨이브) 대부분 예산 안에 끝나게 한다.
        # 예산은 12→18s로(FE 25s 타임아웃·프록시 60s보다 여유) 상향해 마지막 웨이브까지 완주율↑.
        EXPOSURE_BUDGET_SEC = 18
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=6)
        futures = {executor.submit(check_one, kw): kw for kw in candidates}
        done_kws = set()
        try:
            for future in concurrent.futures.as_completed(futures, timeout=EXPOSURE_BUDGET_SEC):
                results.append(future.result())
                done_kws.add(futures[future])
        except concurrent.futures.TimeoutError:
            logger.warning(
                f"keyword-exposure 예산({EXPOSURE_BUDGET_SEC}s) 초과 — 부분 결과 반환 "
                f"({len(done_kws)}/{len(candidates)} 키워드)"
            )
        # 예산 내 미완료 키워드는 미조회(None)로 채워 부분 결과 유지
        for _fut, _kw in futures.items():
            if _kw not in done_kws:
                results.append({"keyword": _kw, "rank": None, "page": None})
        executor.shutdown(wait=False, cancel_futures=True)

        # 내 상품 키워드 vs 참고(연관/급상승) 구분
        for r in results:
            r["source"] = "own" if r["keyword"].strip().lower() in own_set else "related"

        # 순위 있는 것 우선, 순위순 정렬
        results.sort(key=lambda x: (x["rank"] is None, x["rank"] or 9999))

        # 대체 추천: 노출 중인(순위 있는) '메인 키워드 외' 키워드 상위 5개
        recommended = [r for r in results if r["rank"] is not None and r["keyword"].strip().lower() != main_kw][:5]

        own_results = [r for r in results if r["source"] == "own"]
        return {
            "success": True,
            "data": {
                "product_name": product_name,
                "keyword": req.keyword,
                # 노출률 분모 = 내 상품 키워드만(무관 연관어 제외 — R6)
                "total_keywords": len(own_candidates),
                "exposed_count": sum(1 for r in own_results if r["rank"] is not None),
                "results": results,
                "recommended": recommended,
            }
        }
    except Exception as e:
        logger.error(f"키워드 노출 분석 실패: {e}")
        raise HTTPException(status_code=500, detail="키워드 노출 분석 중 오류가 발생했습니다.")


# --- 상품 추적 등록 ---
@app.post("/api/products/track")
def track_product(req: ProductAddRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """상품 + 키워드 추적 등록 (유저별 격리)"""
    try:
        # 상품 정보 가져오기
        product_info = get_product_info(req.product_url)
        product_id_str = extract_product_id_from_url(req.product_url)

        # 스토어명이 URL 슬러그로 남으면(검색 미매칭·페이지 접근 실패) 분석 화면이
        # 이미 확보한 실제 이름(store_name_hint)으로 대체 — 슬러그 저장 신고(2026-08-04) 예방
        _slug = (extract_store_name_from_url(req.product_url) or "").strip()
        _hint = (req.store_name_hint or "").strip()
        _got = (product_info.get("store_name") or "").strip()
        if _hint and _hint.lower() != _slug.lower() and (not _got or _got.lower() == _slug.lower()):
            product_info["store_name"] = _hint

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
    # 리뷰수 1회 조회 (상품당) — 리뷰 델타 기반 판매추정용. 실패해도 순위체크엔 무영향.
    _review_count = None
    try:
        from naver_crawler import get_review_count
        _review_count = get_review_count(product_url)
    except Exception:
        _review_count = None
    for kw_info in keyword_ids:
        try:
            _prods = _shared_crawl(kw_info["keyword"], 500)  # 공유 캐시(3h) → 과부하 방지
            # ── 수집 실패 가드 (2026-08-04 전수조사에서 발견된 오염 잔존 경로) ──
            # 검색 결과를 하나도 못 받았으면 '순위 없음'이 아니라 '수집 실패'다.
            # 신규 등록 직후엔 키워드가 아직 미수집이라 거의 항상 여기 걸리는데,
            # None 을 저장하면 허위 '미노출' 이력이 남는다(8/1~3 1,992건 오염과 동일 기전).
            # 저장을 건너뛰면 온디맨드 수집(1~5분) 후 재체크 때 정상값이 첫 기록이 된다.
            if not _prods:
                logger.warning(f"초기/재체크 [{kw_info['keyword']}] 검색 결과 0건 — 수집 실패로 보고 순위 저장 건너뜀")
                continue
            # 등록 시 슬러그로 저장된 스토어명을 수집 SERP의 실제 mallName으로 보정
            try:
                from database import heal_tracked_product_info
                heal_tracked_product_info(product_id, product_url, _prods)
            except Exception:
                pass
            rank, page, competitors = find_product_rank(
                keyword=kw_info["keyword"],
                product_url=product_url,
                max_pages=5,
                cached_products=_prods,
            )
            save_ranking(
                product_id=product_id,
                keyword_id=kw_info["keyword_id"],
                keyword=kw_info["keyword"],
                rank_position=rank,
                page_number=page,
                check_type="initial",
                review_count=_review_count
            )
            if competitors:
                save_competitor_snapshot(kw_info["keyword_id"], competitors[:5])
        except Exception as e:
            logger.error(f"초기 순위 체크 실패 [{kw_info['keyword']}]: {e}")


# --- 추적 상품 목록 ---
@app.get("/api/products")
def list_products(current_user: dict = Depends(get_current_user)):
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

        # 상품명이 비어있거나 스토어명이 URL 슬러그(등록 시 확보 실패 잔재)면
        # 목록에 추가 (응답은 즉시 반환, 업데이트는 백그라운드)
        _slug = (extract_store_name_from_url(p.get("product_url") or "") or "").strip().lower()
        _store = (p.get("store_name") or "").strip()
        if (not p.get("product_name") or p["product_name"].strip() == ''
                or not _store or _store.lower() == _slug):
            needs_info_update.append(p)

        result.append(p)

    # 빈 상품 정보는 백그라운드에서 업데이트 (응답 지연 방지)
    if needs_info_update:
        from starlette.background import BackgroundTask

        # def(동기)로 둬야 Starlette가 스레드풀에서 실행 → 블로킹 get_product_info가
        # 이벤트 루프를 막지 않음 (async def면 루프에서 await되어 워커 전체가 멈춤)
        def _update_empty_products(items):
            for p in items:
                try:
                    keywords = p.get("keywords", [])
                    search_keyword = keywords[0]["keyword"] if keywords and isinstance(keywords[0], dict) else ""
                    info = get_product_info(p["product_url"], keyword=search_keyword)
                    slug = (extract_store_name_from_url(p.get("product_url") or "") or "").strip().lower()
                    cur_name = (p.get("product_name") or "").strip()
                    cur_store = (p.get("store_name") or "").strip()
                    new_name = (info.get("product_name") or "").strip()
                    new_store = (info.get("store_name") or "").strip()
                    # 이름은 비었을 때만 채우고, 스토어명은 슬러그/빈 값을 실제 이름으로만 교체
                    # (정상 값은 절대 덮지 않음 · 재조회가 또 슬러그를 주면 쓰기 생략)
                    name_fix = bool(new_name) and not cur_name
                    store_fix = (bool(new_store) and new_store.lower() != slug
                                 and (not cur_store or cur_store.lower() == slug))
                    if not name_fix and not store_fix:
                        continue
                    conn2 = sqlite3.connect(DB_PATH, timeout=10)
                    try:
                        conn2.execute("PRAGMA busy_timeout=30000")
                        conn2.execute("""
                            UPDATE tracked_products SET
                                product_name=?, store_name=?,
                                image_url=COALESCE(NULLIF(image_url,''), ?),
                                price=CASE WHEN COALESCE(price,0)=0 THEN ? ELSE price END,
                                updated_at=datetime('now','localtime')
                            WHERE id=?
                        """, (new_name if name_fix else cur_name,
                              new_store if store_fix else cur_store,
                              info.get("image_url") or "", info.get("price") or 0, p["id"]))
                        conn2.commit()
                        logger.info(f"[bg] 상품 정보 보정: ID={p['id']} → "
                                    f"{(new_name if name_fix else cur_name)[:30]} / {(new_store if store_fix else cur_store)[:20]}")
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
def remove_product(product_id: int, current_user: dict = Depends(get_current_user)):
    """추적 상품 삭제 (소유권 확인)"""
    delete_tracked_product(product_id, user_id=current_user["id"], is_admin=_is_admin(current_user))
    return {"success": True, "message": "상품이 삭제되었습니다."}


# --- 키워드 개별 삭제 (건의 2026-07-22, 이예은) ---
@app.delete("/api/keywords/{keyword_id}")
def remove_keyword(keyword_id: int, current_user: dict = Depends(get_current_user)):
    """추적 키워드 1개 삭제 — 소유권 검증 + 마지막 1개 보호.
    남기는 다른 키워드의 순위 이력은 유지되고, 해당 키워드의 이력만 함께 삭제된다.
    키워드 0개 상품을 막기 위해 마지막 1개는 삭제 불가(상품 정리는 상품 삭제 사용)."""
    _verify_keyword_ownership(keyword_id, current_user)  # 404/403 처리
    info = get_keyword_product_and_count(keyword_id)
    if not info:
        raise HTTPException(status_code=404, detail="키워드를 찾을 수 없습니다.")
    if info["count"] <= 1:
        raise HTTPException(
            status_code=400,
            detail="마지막 키워드는 삭제할 수 없습니다. 상품 전체를 정리하려면 상품 삭제를 이용하세요."
        )
    delete_tracked_keyword(keyword_id)
    return {"success": True, "message": "키워드가 삭제되었습니다."}


# --- 순위 이력 조회 ---
@app.get("/api/rank/history/{keyword_id}")
def rank_history(keyword_id: int, days: int = 30, current_user: dict = Depends(get_current_user)):
    """키워드별 순위 변동 이력 (소유권 검증)"""
    _verify_keyword_ownership(keyword_id, current_user)
    days = min(max(days, 1), 365)
    history = get_ranking_history(keyword_id, days=days)
    return {"success": True, "data": history}


# --- 수동 순위 체크 ---
@app.post("/api/rank/refresh/{product_id}")
def refresh_rank(product_id: int, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
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
# ── 파워링크 순위별 입찰가 (건의 2026-07-22) — 1시간 메모리 캐시 ──
import threading as _bid_threading
_bid_cache = {}
_bid_cache_lock = _bid_threading.Lock()


class BidEstimateRequest(BaseModel):
    keyword: str


@app.post("/api/keyword/bid-estimate")
def keyword_bid_estimate(req: BidEstimateRequest, current_user: dict = Depends(get_current_user)):
    """파워링크 1~5위 평균 노출 입찰가 + 최소 노출가 (네이버 검색광고 공식 추정, 인증 필수).
    데이터 없음/실패 시 data={} — 프론트는 신규 표를 렌더하지 않음(기존 화면 유지)."""
    try:
        kw = (req.keyword or "").strip()[:100]
        if not kw:
            return {"success": False, "detail": "키워드를 입력해주세요."}
        now = time.time()
        with _bid_cache_lock:
            hit = _bid_cache.get(kw)
            if hit and now - hit[1] < 3600:
                return {"success": True, "data": hit[0], "cached": True}
        from naver_crawler import get_bid_estimates
        data = get_bid_estimates(kw)
        if data:  # 성공한 결과만 캐시 — 실패는 다음 요청에서 재시도
            with _bid_cache_lock:
                if len(_bid_cache) > 300:
                    _bid_cache.clear()
                _bid_cache[kw] = (data, now)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"입찰가 추정 조회 실패: {e}")
        return {"success": False, "detail": "입찰가 추정 조회 중 오류가 발생했습니다."}


@app.post("/api/keyword/volume")
def keyword_volume(keywords: List[str], current_user: dict = Depends(get_current_user)):
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
def get_notify_settings(current_user: dict = Depends(require_role(UserRole.ADMIN))):
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
def update_notify_settings(req: NotificationSettingsRequest, current_user: dict = Depends(require_role(UserRole.ADMIN))):
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
def export_report(req: ReportExportRequest, current_user: dict = Depends(get_current_user)):
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
def detail_page_analyze(req: DetailPageAnalysisRequest, current_user: dict = Depends(get_current_user)):
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
                # 표시용 스토어/상호명 — 보고서 표지의 슬러그 오표기 방지(2026-07-27)
                "storeInfo": result.get("storeInfo") or {"name": "", "source": ""},
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
    cached_review_count: Optional[int] = None   # HTML 실측 리뷰수(있으면 순위 추정 대신 최우선 사용)
    cached_rating: Optional[float] = None        # HTML 실측 평점
    # --- 플레이스(지역 검색) 업종 전용 (기본 shopping 유지 → 기존 요청·응답 무영향) ---
    vertical: Optional[str] = "shopping"         # "place" 면 아래 플레이스 어댑터로 분기
    place_html: Optional[str] = None             # 직원 브라우저 캡처 검색결과 HTML(순위·경쟁사)
    target_doc_id: Optional[str] = None          # 내 업체 플레이스 doc-id(순위 매칭)
    target_name: Optional[str] = None            # 내 업체명(doc-id 없을 때 매칭 폴백)
    region: Optional[str] = None                 # 지역(동/구/시) — 업체 식별키·표시용
    place: Optional[Dict[str, Any]] = None       # 담당자 보완 지표(저장수·예약·사진·소식 등)


def _place_business_key(req: "SeoAnalysisRequest", region: str = "") -> str:
    """업체 식별키 — doc_id 우선, 없으면 정규화한 업체명+지역(캡처마다 안정적)."""
    if req.target_doc_id:
        return f"doc:{req.target_doc_id}"
    name = place_crawler._norm(req.target_name or "")
    reg = place_crawler._norm(region or req.region or "")
    return f"nm:{name}|{reg}" if name else ""


def _place_seo_analyze(req: "SeoAnalysisRequest", current_user: dict = None):
    """플레이스 전용 SEO 진단 — place_crawler 어댑터로 파싱·순위·점수화.
    반환 envelope 를 쇼핑 seo_analyze 와 동일 형태로 맞춰 프론트 리포트 셸을 재사용한다."""
    try:
        parsed = place_crawler.parse_place_search(req.place_html or "")
        place_in = dict(req.place or {})
        # 내 업체 순위(3-state: 노출/미노출/미확인)
        rank_info = place_crawler.find_place_rank(
            parsed,
            target_doc_id=req.target_doc_id,
            target_name=req.target_name or place_in.get("name"),
        )
        if rank_info.get("rank"):
            place_in["rank"] = rank_info["rank"]
        # 캡처에 내 업체가 노출됐으면 방문자·블로그 리뷰를 자동 측정값으로 채움
        # (담당자가 직접 입력한 값이 있으면 그 값을 우선 — 하이브리드).
        _matched = rank_info.get("matched") or {}
        for _mk in ("visitor_reviews", "blog_reviews"):
            if place_in.get(_mk) is None and _matched.get(_mk) is not None:
                place_in[_mk] = _matched.get(_mk)
        # 경쟁사(상위 오가닉·내 업체 제외) — 캡처에서 리뷰 지표만 확보
        competitors = []
        for it in parsed.get("items", []):
            if it.get("is_ad"):
                continue
            if req.target_doc_id and str(it.get("doc_id")) == str(req.target_doc_id):
                continue
            if _matched and it is _matched:   # 이름 매칭된 내 업체도 제외
                continue
            competitors.append({
                "name": it.get("name"),
                "rank": it.get("rank"),
                "visitor_reviews": it.get("visitor_reviews"),
                "blog_reviews": it.get("blog_reviews"),
                "rating": it.get("rating"),
            })
        scored = place_crawler.score_place(place_in, competitors=competitors)
        region = req.region or parsed.get("region") or ""
        business_key = _place_business_key(req, region)

        # 순위 이력 누적(하루 1점) — 플레이스는 캡처로만 순위가 확보되므로 분석 시점에 저장.
        # 실패해도 분석 응답은 정상 반환(무회귀).
        try:
            if business_key and req.keyword:
                from database import save_place_rank
                save_place_rank(
                    business_key=business_key,
                    keyword=req.keyword,
                    rank_position=rank_info.get("rank"),
                    rank_state=rank_info.get("state") or "",
                    business_name=req.target_name or "",
                    region=region,
                    user_id=(current_user or {}).get("id", 0),
                )
        except Exception as _e:
            logger.warning(f"플레이스 순위 이력 저장 건너뜀: {_e}")

        return {
            "success": True,
            "data": {
                "vertical": "place",
                "keyword": req.keyword,
                "region": region,
                "category": parsed.get("category"),
                "business_key": business_key,
                "business_name": req.target_name or "",
                "rank_state": rank_info.get("state"),
                "rank": rank_info.get("rank"),
                "page": rank_info.get("page"),
                "scores": scored["scores"],
                "weights": scored["weights"],
                "labels": scored.get("labels"),
                "data_quality": scored.get("data_quality"),
                "suggestions": scored.get("suggestions"),
                "competitors": competitors[:5],
                "analyzed_at": datetime.now().isoformat(),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"플레이스 분석 실패: {e}")
        raise HTTPException(status_code=500, detail="플레이스 분석 중 오류가 발생했습니다.")


@app.get("/api/place/rank-history")
def place_rank_history_api(business: str = "", keyword: str = "", days: int = 30,
                          current_user: dict = Depends(get_current_user)):
    """플레이스 (업체·키워드) 일자별 순위 시계열 — §2 추적 차트용."""
    try:
        from database import get_place_rank_history
        d = min(max(int(days or 30), 7), 365)
        series = get_place_rank_history(business, keyword, days=d)
        return {"success": True, "data": {"business_key": business, "keyword": keyword, "series": series}}
    except Exception as e:
        logger.error(f"플레이스 순위 이력 조회 실패: {e}")
        return {"success": False, "error": "순위 이력 조회 중 오류가 발생했습니다."}


@app.get("/api/place/keywords")
def place_tracked_keywords_api(business: str = "", current_user: dict = Depends(get_current_user)):
    """플레이스 업체가 추적(분석)한 키워드 + 각 최신 순위/상태 — §2 키워드 칩용."""
    try:
        from database import get_place_tracked_keywords
        kws = get_place_tracked_keywords(business)
        return {"success": True, "data": {"business_key": business, "keywords": kws}}
    except Exception as e:
        logger.error(f"플레이스 추적 키워드 조회 실패: {e}")
        return {"success": False, "error": "추적 키워드 조회 중 오류가 발생했습니다."}


class PlaceProposalEnrichRequest(BaseModel):
    name: str = ""                       # 업체(광고주)명
    region: str = ""                     # 지역(동/구/시)
    keyword: str = ""                    # 대표 키워드(지역 미포함 가능 — 서버가 합성)
    place_id: Optional[str] = None       # 플레이스 ID(있으면 순위 매칭 정확도 ↑)
    industry: str = ""                   # 업종 라벨(선택 — 소상공인365 상권 데이터 매칭용)


def _pe_int(x):
    """검색량 문자열('12,300'·'< 10') → 정수. 실패 시 0."""
    try:
        return int(str(x).replace("<", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0


@app.post("/api/place/proposal-enrich")
def place_proposal_enrich(req: PlaceProposalEnrichRequest,
                          current_user: dict = Depends(get_current_user)):
    """맞춤제안서(플레이스) 실데이터 enrich — 검색량·무인 추적 순위·순위 이력·추적 키워드를
    한 번에 반환한다. 스토어 제안서의 directEnrich(검색량·순위·데이터랩)와 같은 취지의 플레이스판.
    ★ 신규 경로 — 전산(①) 소비 계약(portal-summary·seo/analyze 등)과 무접점.
    데이터 없는 필드는 비워서(null/[]) 반환 → 제안서가 예시 수치로 폴백(무회귀)."""
    try:
        from database import get_place_rank_history, get_place_tracked_keywords
        from naver_crawler import get_keyword_volume as _kw_vol

        name = (req.name or "").strip()
        region = (req.region or "").strip()
        base_kw = (req.keyword or "").strip()
        if not base_kw:
            return {"success": False, "error": "키워드가 필요합니다."}

        # 업체 식별키 — doc:{place_id} 우선, 없으면 nm:{정규화명}|{정규화지역}
        # (플레이스 무인 추적 save_place_rank·수동 분석 _place_business_key 와 동일 규칙)
        if req.place_id:
            business_key = f"doc:{str(req.place_id).strip()}"
        else:
            nm = place_crawler._norm(name)
            rg = place_crawler._norm(region)
            business_key = f"nm:{nm}|{rg}" if nm else ""

        # 지역+키워드 합성(추적·제안서 동일 규칙 — 지역 포함 시 순위 재현성)
        combined_kw = _combine_region_keyword(region, base_kw)

        # 1) 검색량(검색광고 API) — 실패/미조회 시 null(가짜 0 금지)
        volume = None
        comp_idx = None
        try:
            v0 = ((_kw_vol([combined_kw]) or [{}])[0]) or {}
            pc, mo = v0.get("monthlyPcQcCnt"), v0.get("monthlyMobileQcCnt")
            if pc is not None or mo is not None:
                volume = _pe_int(pc) + _pe_int(mo)
            comp_idx = v0.get("compIdx")
        except Exception as e:
            logger.warning(f"[proposal-enrich] 검색량 조회 실패(무시): {e}")

        # 2) 무인 추적 순위 이력(최근 90일) + 최신 순위·상태 (Q3 순위 추이 슬라이드)
        rank = None
        rank_state = ""
        rank_series = []
        if business_key:
            rank_series = get_place_rank_history(business_key, combined_kw, days=90)
            if rank_series:
                last = rank_series[-1]
                rank = last.get("rank")
                rank_state = last.get("state") or ""

        # 3) 이 업체가 추적 중인 키워드 전체 + 각 최신 순위·검색량 (지역 황금 키워드 축·실데이터)
        keyword_rows = []
        try:
            tracked = get_place_tracked_keywords(business_key) if business_key else []
            tk = [t.get("keyword") for t in tracked[:8] if t.get("keyword")]
            vmap = {}
            if tk:
                for vr in (_kw_vol(tk) or []):
                    kn = vr.get("keyword")
                    if kn is not None:
                        vmap[str(kn)] = vr
            for t in tracked[:8]:
                kw = t.get("keyword")
                vr = vmap.get(str(kw), {}) if kw else {}
                pc, mo = vr.get("monthlyPcQcCnt"), vr.get("monthlyMobileQcCnt")
                vol = (_pe_int(pc) + _pe_int(mo)) if (pc is not None or mo is not None) else None
                keyword_rows.append({
                    "keyword": kw, "volume": vol,
                    "rank": t.get("rank"), "state": t.get("state") or "",
                    "compIdx": vr.get("compIdx"),
                })
        except Exception as e:
            logger.warning(f"[proposal-enrich] 키워드 표 구성 실패(무시): {e}")

        # 4) 소상공인365 상권 데이터(가산) — 키 미설정·매칭 실패·API 파손 시 None
        #    → 제안서가 상권 슬라이드만 조용히 생략(기존 필드·동작 전부 불변).
        sbiz_block = None
        try:
            from sbiz365 import get_place_sbiz
            sbiz_block = get_place_sbiz(region, req.industry)
        except Exception as e:
            logger.warning(f"[proposal-enrich] 상권 데이터 조회 실패(무시): {e}")

        return {"success": True, "data": {
            "connected": True,
            "isPlace": True,
            "sbiz": sbiz_block,        # 상권 블록(소상공인365) — null이면 상권 슬라이드 생략
            "businessKey": business_key,
            "keyword": combined_kw,
            "volume": volume,               # 월 검색량(실측) — null=미확인
            "compIdx": comp_idx,
            "rank": rank,                   # 무인 추적 최신 순위 — null=미추적/미노출
            "rankState": rank_state,        # 노출/미노출/미확인
            "rankSeries": rank_series,      # Q3 순위 추이 [{date,rank,state}]
            "trackedKeywords": keyword_rows,  # 지역 황금 키워드 축(추적 중 키워드+검색량+순위)
            "hasTracking": bool(rank_series),
        }}
    except Exception as e:
        logger.error(f"[proposal-enrich] 실패: {e}")
        return {"success": False, "error": "제안서 데이터 조회 중 오류가 발생했습니다."}


# ==================== 플레이스 무인 추적 (v6.7) ====================
# 확장 프로그램(플레이스 순위 추적기)이 매일 자동 수집한 순위를 브리지(로그인된 웹앱)로
# 전달받아 기록한다. 전 경로 신규 /api/place/* — seo/analyze 등 전산(①) 소비 계약과 무접점.

class PlaceTrackCreateRequest(BaseModel):
    business_name: str
    region: str
    keywords: List[str]
    place_id: Optional[str] = None


class PlaceTrackPatchRequest(BaseModel):
    active: bool


class PlaceIngestItem(BaseModel):
    target_id: Optional[int] = None
    keyword: str
    business_name: Optional[str] = None
    region: Optional[str] = None
    place_id: Optional[str] = None       # 수집 중 매칭된 doc_id(있으면 레지스트리 self-heal)
    rank: Optional[int] = None
    state: Optional[str] = None          # 노출/미노출/미확인 — find_place_rank 3-state 어휘


class PlaceIngestRequest(BaseModel):
    results: List[PlaceIngestItem]
    ran_at: Optional[str] = None
    source: Optional[str] = None         # 'daily' | 'manual' — 기록용


def _place_registry_business_key(place_id: str, business_name: str, region: str) -> str:
    """레지스트리/배치용 업체 식별키 — _place_business_key 와 동일 공식(단일 조인 키 유지)."""
    if place_id:
        return f"doc:{place_id}"
    name = place_crawler._norm(business_name or "")
    reg = place_crawler._norm(region or "")
    return f"nm:{name}|{reg}" if name else ""


def _place_track_denied(current_user) -> bool:
    """플레이스 순위 추적 편집 권한 — 스토어 순위 추적과 동일 범주(2026-08-04 대표 확정):
    영업사원(viewer)은 열람만 가능(등록·삭제·수집·기록 불가), 관리팀(manager)·관리자는 전체 가능."""
    return (current_user or {}).get("role") == "viewer"


_PLACE_TRACK_DENY_MSG = ("플레이스 순위 추적 등록·관리는 관리팀만 가능합니다. "
                         "영업 대상 분석은 「📍 플레이스 분석」 탭을 이용해주세요. (스토어 순위 추적과 동일 기준)")


def _combine_region_keyword(region: str, keyword: str) -> str:
    """추적 키워드는 항상 지역 포함(순위 재현성 — 2026-08-04 스파이크 실측).
    이미 지역이 들어있으면 그대로(중복 방지) — 맞춤제안서 합성 규칙과 동일."""
    kw = (keyword or "").strip()
    reg = (region or "").strip()
    if not reg:
        return kw
    if place_crawler._norm(reg) in place_crawler._norm(kw):
        return kw
    return f"{reg} {kw}"


@app.get("/api/place/track-targets")
def place_track_targets_list(active: int = 0, current_user: dict = Depends(get_current_user)):
    """추적 대상 목록 + 각 (업체·키워드) 최신 순위.
    - 기본(화면): user_id별 격리 — 본인 등록분만, admin/superadmin 전체(스토어 tracked_products 와 동일).
    - active=1(확장 러너 동기화 전용): 전체 활성 대상 — 무인 수집은 추적 PC 세션 권한과 무관하게
      전 직원 등록분을 커버해야 하므로 격리 예외(내부 도구·업체명/키워드만 노출)."""
    try:
        from database import list_place_track_targets, get_place_tracked_keywords
        if active:
            targets = list_place_track_targets(active_only=True)
        else:
            targets = list_place_track_targets(
                active_only=False,
                user_id=(current_user or {}).get("id"),
                is_admin=_is_admin(current_user or {}),
            )
        # 업체별 최신 순위 채움(레지스트리는 소규모라 업체 단위 조회로 충분)
        latest_cache = {}
        for t in targets:
            bk = _place_registry_business_key(t["place_id"], t["business_name"], t["region"])
            t["business_key"] = bk
            if not bk:
                t["last"] = None
                continue
            if bk not in latest_cache:
                latest_cache[bk] = {k["keyword"]: k for k in get_place_tracked_keywords(bk)}
            k = latest_cache[bk].get(t["keyword"])
            t["last"] = ({"rank": k["rank"], "state": k["state"], "checked_at": k["checked_at"]}
                         if k else None)
        return {"success": True, "data": {"targets": targets}}
    except Exception as e:
        logger.error(f"플레이스 추적 목록 조회 실패: {e}")
        return {"success": False, "error": "추적 목록 조회 중 오류가 발생했습니다."}


@app.post("/api/place/track-targets")
def place_track_targets_create(req: PlaceTrackCreateRequest,
                               current_user: dict = Depends(get_current_user)):
    """추적 대상 등록 — (업체 × 키워드) 행 생성. 키워드는 지역 자동 합성(중복 방지)."""
    try:
        if _place_track_denied(current_user):
            return {"success": False, "error": _PLACE_TRACK_DENY_MSG}
        name = (req.business_name or "").strip()
        region = (req.region or "").strip()
        if not name:
            return {"success": False, "error": "업체명을 입력해주세요."}
        if not region:
            return {"success": False, "error": "지역을 입력해주세요. (예: 성수동 — 순위 재현에 필요)"}
        kws = []
        for kw in (req.keywords or []):
            combined = _combine_region_keyword(region, kw)
            if combined and combined not in kws:
                kws.append(combined)
        if not kws:
            return {"success": False, "error": "추적 키워드를 1개 이상 입력해주세요."}
        if len(kws) > 10:
            return {"success": False, "error": "키워드는 업체당 최대 10개까지 등록할 수 있습니다."}
        from database import add_place_track_targets
        added = add_place_track_targets(
            business_name=name, region=region, keywords=kws,
            place_id=(req.place_id or "").strip(),
            user_id=(current_user or {}).get("id", 0),
        )
        return {"success": True, "data": {"added": added, "keywords": kws}}
    except Exception as e:
        logger.error(f"플레이스 추적 등록 실패: {e}")
        return {"success": False, "error": "추적 등록 중 오류가 발생했습니다."}


@app.patch("/api/place/track-targets/{target_id}")
def place_track_targets_patch(target_id: int, req: PlaceTrackPatchRequest,
                              current_user: dict = Depends(get_current_user)):
    """추적 대상 활성/일시중지."""
    try:
        if _place_track_denied(current_user):
            return {"success": False, "error": _PLACE_TRACK_DENY_MSG}
        from database import set_place_track_target_active
        ok = set_place_track_target_active(
            target_id, req.active,
            user_id=(current_user or {}).get("id"), is_admin=_is_admin(current_user or {}))
        return {"success": bool(ok)}
    except Exception as e:
        logger.error(f"플레이스 추적 토글 실패: {e}")
        return {"success": False, "error": "변경 중 오류가 발생했습니다."}


@app.delete("/api/place/track-targets/{target_id}")
def place_track_targets_delete(target_id: int, current_user: dict = Depends(get_current_user)):
    """추적 대상 삭제(순위 이력은 보존 — 재등록 시 이어짐)."""
    try:
        if _place_track_denied(current_user):
            return {"success": False, "error": _PLACE_TRACK_DENY_MSG}
        from database import delete_place_track_target
        ok = delete_place_track_target(
            target_id,
            user_id=(current_user or {}).get("id"), is_admin=_is_admin(current_user or {}))
        return {"success": bool(ok)}
    except Exception as e:
        logger.error(f"플레이스 추적 삭제 실패: {e}")
        return {"success": False, "error": "삭제 중 오류가 발생했습니다."}


@app.post("/api/place/ingest")
def place_ingest(req: PlaceIngestRequest, current_user: dict = Depends(get_current_user)):
    """무인 수집 결과 배치 기록 — 항목별 save_place_rank(하루 1점·멱등) 재사용.
    한 항목 실패가 배치를 막지 않도록 건별 무해 실패.
    (권한 게이트 없음 — 스토어 수집기 기록 경로와 동일. 추적 PC 세션 권한과 무관하게 무인 기록이 끊기지 않아야 함)"""
    try:
        from database import save_place_rank, heal_place_track_target_place_id
        saved, skipped = 0, 0
        for item in (req.results or []):
            try:
                bk = _place_registry_business_key(
                    (item.place_id or "").strip(), item.business_name or "", item.region or "")
                if not bk or not (item.keyword or "").strip():
                    skipped += 1
                    continue
                state = (item.state or "").strip() or ("노출" if item.rank else "미확인")
                save_place_rank(
                    business_key=bk,
                    keyword=item.keyword.strip(),
                    rank_position=item.rank,
                    rank_state=state,
                    business_name=item.business_name or "",
                    region=item.region or "",
                    user_id=(current_user or {}).get("id", 0),
                )
                saved += 1
                # 첫 노출로 doc_id 를 알아냈으면 레지스트리에 채움(self-heal)
                if item.target_id and item.place_id:
                    heal_place_track_target_place_id(item.target_id, item.place_id)
            except Exception as _ie:
                skipped += 1
                logger.warning(f"플레이스 ingest 항목 건너뜀: {_ie}")
        return {"success": True, "data": {"saved": saved, "skipped": skipped}}
    except Exception as e:
        logger.error(f"플레이스 ingest 실패: {e}")
        return {"success": False, "error": "수집 결과 기록 중 오류가 발생했습니다."}


@app.post("/api/seo/analyze")
def seo_analyze(req: SeoAnalysisRequest, current_user: dict = Depends(get_current_user)):
    """상품 SEO 종합 진단 (인증 필수)"""
    try:
        # 플레이스 업종은 전용 어댑터로 분기(기본 shopping 은 아래 기존 경로 100% 그대로)
        if (req.vertical or "shopping") == "place":
            return _place_seo_analyze(req, current_user)
        # 캐시된 데이터가 있으면 재활용, 없으면 API 호출
        if req.cached_product_info:
            product_info = req.cached_product_info
            # product_name이 비어있으면 cached_competitors에서 product_id로 보완
            if not product_info.get("product_name") and req.cached_competitors:
                _fix_pid = extract_product_id_from_url(req.product_url) or ""
                if _fix_pid:
                    _matched_cp = None
                    # 1차: product_id 필드 직접 비교
                    for _cp in req.cached_competitors:
                        if str(_cp.get("product_id", "")) == _fix_pid:
                            _matched_cp = _cp
                            logger.info(f"SEO product_id 필드 매칭: {_cp.get('product_name', '')[:30]}")
                            break
                    # 2차: product_url에 PID 포함 (네이버 API link = /main/products/채널ID)
                    if not _matched_cp:
                        for _cp in req.cached_competitors:
                            if _fix_pid in (_cp.get("product_url") or ""):
                                _matched_cp = _cp
                                logger.info(f"SEO URL-PID 매칭: {_cp.get('product_name', '')[:30]}")
                                break
                    if _matched_cp:
                        product_info["product_name"] = _matched_cp.get("product_name", "")
                        product_info["price"] = _matched_cp.get("price", 0)
                        product_info["brand"] = _matched_cp.get("brand", "")
                        product_info["store_name"] = _matched_cp.get("store_name", "")
                        product_info["category1"] = _matched_cp.get("category1", "")
                        product_info["category2"] = _matched_cp.get("category2", "")
                        logger.info(f"SEO cached_product_info 보완 성공: {_matched_cp.get('product_name', '')[:30]}")
                    else:
                        logger.warning(f"SEO 매칭 실패: target_pid={_fix_pid} — product_id/URL 모두 불일치")
        elif req.cached_product_name:
            # cached_product_name이 있으면 get_product_info 불필요 → API 절약 + 429 방지
            product_info = {"product_name": req.cached_product_name}
            # cached_competitors에서 자기 상품 정보 보완 (가격/브랜드/카테고리)
            if req.cached_competitors:
                target_store = (extract_store_name_from_url(req.product_url) or "").lower()
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
        elif req.cached_competitors:
            # cached_product_info/name 없지만 competitors에서 스토어명으로 매칭 시도
            # → get_product_info() API 호출 없이 상품 정보 확보 (429 방지 핵심)
            product_info = {}
            target_store = (extract_store_name_from_url(req.product_url) or "").lower()
            target_pid = extract_product_id_from_url(req.product_url) or ""
            for _cp in req.cached_competitors:
                cp_store = (_cp.get("store_name") or "").lower()
                cp_url = (_cp.get("product_url") or "").lower()
                cp_pid = str(_cp.get("product_id", ""))
                cp_matched = False
                # 매칭 1: product_id 필드 직접 비교 (API productId = 스마트스토어 상품 ID)
                if target_pid and cp_pid and target_pid == cp_pid:
                    cp_matched = True
                # 매칭 2: productId가 URL에 포함
                elif target_pid and target_pid in cp_url:
                    cp_matched = True
                # 매칭 3: 스토어명 일치 또는 URL에 스토어 슬러그 포함
                elif target_store and (cp_store == target_store or target_store in cp_url):
                    cp_matched = True
                if cp_matched:
                    product_info = {
                        "product_name": _cp.get("product_name", ""),
                        "price": _cp.get("price", 0),
                        "brand": _cp.get("brand", ""),
                        "store_name": _cp.get("store_name", ""),
                        "category1": _cp.get("category1", ""),
                        "category2": _cp.get("category2", ""),
                    }
                    logger.info(f"SEO competitors 스토어 매칭 성공: {_cp.get('product_name', '')[:30]} (store: {target_store})")
                    break
            if not product_info:
                logger.info(f"SEO competitors 스토어 매칭 실패 — get_product_info 호출 (store: {target_store})")
                try:
                    product_info = get_product_info(req.product_url, keyword=req.keyword)
                except Exception as e:
                    logger.warning(f"get_product_info 실패 (빈 값 사용): {e}")
                    product_info = {}
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
                _prods = _shared_crawl(req.keyword, 500)  # 공유 캐시(3h) → 과부하 방지
                rank, page, competitors = find_product_rank(
                    keyword=req.keyword, product_url=req.product_url, max_pages=5,
                    product_name=product_name, cached_products=_prods
                )
            except Exception as e:
                logger.warning(f"find_product_rank 실패 (순위 없음 처리): {e}")
                rank, page, competitors = None, None, []

        # get_product_info 실패 시 (스마트스토어 ID ≠ nvMid) → 키워드 검색에서 productId로 보완
        # 캐시된 product_name이 있으면 폴백 불필요
        if not product_name and not req.cached_product_name:
            try:
                target_pid = extract_product_id_from_url(req.product_url) or ""
                target_store = extract_store_name_from_url(req.product_url) or ""
                # 주의: 이 모듈에 동명의 라우트(search_products)가 있어 import가 가려짐 → 크롤러 함수를 별칭으로 호출
                from naver_crawler import search_products as _sp_crawler
                _prods = _sp_crawler(req.keyword, max_results=200)
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
        # 프론트가 HTML 실측 리뷰/평점을 넘기면 최우선 사용(순위 추정·불안정한 스토어 API 대신)
        if req.cached_review_count is not None:
            actual_review_count = req.cached_review_count
            review_source = "actual"
            if req.cached_rating is not None and req.cached_rating > 0:
                actual_rating = req.cached_rating
        try:
            from naver_crawler import _extract_smartstore_info
            ss_store, ss_pno = _extract_smartstore_info(product_url)
            if ss_store and ss_pno and actual_review_count is None:   # 실측 캐시 없을 때만 스토어 API 시도
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
        vol_available = True
        if rank:
            # 키워드 볼륨: 캐시 우선, 없으면 API 호출
            if req.cached_total_volume is not None:
                total_vol = req.cached_total_volume
            else:
                try:
                    vol_data = get_keyword_volume([req.keyword])
                    vol = vol_data[0] if vol_data else None
                    total_vol = (vol.get("monthlyPcQcCnt", 0) + vol.get("monthlyMobileQcCnt", 0)) if vol else 0
                    vol_available = vol is not None   # 조회 자체는 성공(값이 0이어도 available)
                except Exception:
                    total_vol = 0
                    vol_available = False   # 볼륨 조회 실패 → '판매 0'이 아니라 '측정 불가'

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
            elif not vol_available:
                # 볼륨 조회 실패로 판매 추정 불가 → 순위 기반 보수적 폴백(리뷰/평점과 동일 원칙).
                # 일시적 API 실패가 랭크 상품의 판매점수를 0점으로 만들어 종합점수를 왜곡하는 것을 방지.
                if rank <= 5: sales_score = 60
                elif rank <= 10: sales_score = 45
                elif rank <= 20: sales_score = 35
                elif rank <= 40: sales_score = 25
                else: sales_score = 15
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
                elif product_category in comp_cats:   # 경쟁사 카테고리 목록에 정확히 존재(부분문자열 오탐 방지)
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

        # ── 데이터 신뢰 등급: 실측(스마트스토어 API) vs 추정(순위 기반)을 구분해 부착(부가 필드) ──
        import data_quality as dq
        _rev_measured = (review_source == "api")
        data_quality = {
            "review_count": dq.metric(est_reviews, dq.MEASURED if _rev_measured else dq.ESTIMATED,
                                      sources=["smartstore_api"] if _rev_measured else ["rank_based"]),
            "rating": dq.metric(est_rating, dq.MEASURED if (_rev_measured and est_rating) else dq.ESTIMATED,
                                sources=["smartstore_api"] if _rev_measured else ["rank_based"]),
            "monthly_sales": dq.metric(est_monthly_sales, dq.ESTIMATED, sources=["volume_ctr_model"]),
            "price": dq.metric((my_price or None), dq.status_from_presence(my_price or None),
                               sources=["crawl"] if my_price else []),
        }

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
                "data_quality": data_quality,
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
def search_products(req: ProductSearchRequest, current_user: dict = Depends(get_current_user)):
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
def related_keywords(req: RelatedKeywordRequest, current_user: dict = Depends(get_current_user)):
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
def analyze_product_names(req: ProductNameAnalysisRequest, current_user: dict = Depends(get_current_user)):
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
            {"word": word, "count": count, "ratio": round(count / max(1, min(len(req.product_names), 50)) * 100, 1)}
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

def compute_advertiser_report(keyword: str, product_url: str):
    """광고주 맞춤 분석 — 엔드포인트/스케줄러 공용 재사용 함수. {"success","data"} 반환."""
    from types import SimpleNamespace
    req = SimpleNamespace(keyword=keyword, product_url=product_url)
    try:
        from naver_crawler import search_naver_shopping_api, _parse_api_item

        # 1) 광고주 상품 정보 조회
        #    keyword를 함께 넘겨 빠른 키워드-검색 경로를 사용 → 가격/카테고리까지 채움
        #    (미전달 시 my_price 0원·주요카테고리 공란 발생)
        product_info = get_product_info(req.product_url, keyword=req.keyword)

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

        # 2~3) 키워드로 1회만 검색 → 순위 계산 + 1페이지(상위 80) 분석에 공용 사용
        #      (기존엔 find_product_rank 내부 검색 + 쇼핑 API 재검색으로 같은 키워드를 두 번 호출)
        #      매칭 로직은 그대로(cached_products로 결과만 재사용). retry_on_429=True로 429 빈결과 방지.
        # [A] 수집 깊이 1000→500 + [B] 3시간 공유 캐시. 같은 키워드를 여러 직원/워커가 분석하면
        #     _shared_crawl가 1회 크롤 결과를 공유(캐시 우선, 실패 시 직접 크롤 폴백 → 분석 안 멈춤).
        all_products = _shared_crawl(req.keyword, 500)
        rank, page, top_competitors = find_product_rank(
            keyword=req.keyword, product_url=req.product_url, max_pages=5,
            product_name=product_info.get("product_name", ""),
            cached_products=all_products,
        )
        page1_products = all_products[:80]
        if not page1_products:
            logger.warning(f"광고주분석: 쇼핑 API 결과 0건 (keyword={req.keyword}) → 평균가 산출 불가")

        # 4) 경쟁사 비교 분석 데이터 구성
        my_price = product_info.get("price", 0)
        my_name = product_info.get("product_name", "")

        # [R1] 자기상품 정보 보완: 순위는 잡혔는데(=순위검색에서 내 상품을 찾음) my_price/my_name이 비면
        #      같은 순위검색 결과(all_products)에서 내 상품을 재매칭해 채운다.
        #      (없으면 "상품 가격/상품명을 확인할 수 없습니다"가 뜨는데, 이미 순위로 존재하므로 모순)
        if (not my_name or not my_price) and rank and all_products:
            try:
                from naver_crawler import extract_product_id_from_url as _epid, extract_store_name_from_url as _estore
                _tpid = _epid(req.product_url) or ""
                _tstore = (_estore(req.product_url) or "").lower()
                for _p in all_products:
                    _u = (_p.get("product_url") or "")
                    _hit = (_tpid and (_tpid in _u or _tpid == _p.get("product_id", ""))) or (_tstore and _tstore in _u.lower())
                    if _hit:
                        if not my_name:
                            my_name = _p.get("product_name", "") or my_name
                            product_info["product_name"] = my_name
                        if not my_price:
                            my_price = _p.get("price", 0) or my_price
                            product_info["price"] = my_price
                        if not product_info.get("store_name"):
                            product_info["store_name"] = _p.get("store_name", "")
                        if not product_info.get("brand"):
                            product_info["brand"] = _p.get("brand", "")
                        if not product_info.get("category"):
                            product_info["category"] = _p.get("category2") or _p.get("category1") or ""
                        logger.info(f"[R1] 자기상품 정보 순위검색 결과로 보완: {(my_name or '')[:30]} / {my_price}원 (rank {rank})")
                        break
            except Exception as _e:
                logger.warning(f"[R1] 자기상품 보완 실패(무시): {_e}")

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
                _stripped = my_name.replace(" ", "")
                kw_pos = _stripped.lower().find(req.keyword.replace(" ", "").lower())
                if kw_pos < 0:
                    # 가드: my_has_keyword=True인데 매칭 실패한 예외 케이스
                    seo_insights.append(f"핵심 키워드 '{req.keyword}'가 상품명에 포함되어 있습니다.")
                else:
                    pos_pct = round(kw_pos / max(len(_stripped), 1) * 100)
                    _loc = "맨 앞" if pos_pct == 0 else f"{pos_pct}% 지점"
                    seo_insights.append(f"핵심 키워드 '{req.keyword}'가 상품명의 {_loc}에 위치합니다." + (" 앞부분 배치로 SEO에 유리합니다." if pos_pct < 30 else " 가능하면 앞부분(30% 이내)에 배치하면 노출 확률이 높아집니다."))
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


@app.post("/api/advertiser/analyze")
def advertiser_analyze(req: AdvertiserAnalysisRequest, current_user: dict = Depends(get_current_user)):
    """광고주 맞춤 분석 리포트 (인증 필수) — 공용 함수 위임"""
    return compute_advertiser_report(req.keyword, req.product_url)


# --- AI 피드백 통합 (1회 호출) ---
class AiFeedbackAllRequest(BaseModel):
    keyword: str
    sections: Dict[str, Any]  # {"volume": {...}, "competition": {...}, ...}
    client_name: Optional[str] = ""
    client_id: Optional[int] = 0
    call_type: Optional[str] = "manual"
    vertical: Optional[str] = "shopping"   # "place" 면 플레이스 페르소나 프롬프트/섹션 사용

@app.post("/api/ai/feedback-all")
async def ai_feedback_all(req: AiFeedbackAllRequest, current_user: dict = Depends(get_current_user)):
    """Claude AI 기반 통합 분석 피드백 — 전 섹션을 1회 API 호출로 생성"""
    try:
        import anthropic, json

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"success": False, "error": "ANTHROPIC_API_KEY가 설정되지 않았습니다."}

        client = anthropic.Anthropic(api_key=api_key)

        if (req.vertical or "shopping") == "place":
            section_labels = dict(place_crawler.PLACE_AI_SECTION_LABELS)
        else:
            section_labels = {
                "volume": ("검색량 분석", "PC/모바일 검색 비율, CTR, CPC 효율성을 수치로 분석하고 광고 vs SEO 투자 판단 근거를 제시하세요."),
                "market": ("시장 규모", "월 거래액, 마진율, BEP 시나리오를 분석하세요."),
                "competition": ("경쟁강도", "상품 수 대비 검색량, 브랜드 비율을 분석하세요. 목표는 내 순위 상태에 맞게 — 상위권(1~10위)이면 순위 방어·1위 추격·리뷰 격차 해소, 하위권이면 1페이지 진입 — 로 제시하세요."),
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
            # 1500자는 카테고리·수치 등 핵심 필드가 잘려 AI가 빈칸을 추측(환각)하는 원인 → 4000자로 완화
            if len(data_str) > 4000:
                data_str = data_str[:4000] + "...(생략)"
            section_blocks.append(f"[{label}]\n데이터: {data_str}\n분석 지시: {instruction}")

        if not section_blocks:
            return {"success": False, "error": "분석할 데이터가 없습니다."}

        combined_data = "\n\n---\n\n".join(section_blocks)

        # R5: 자기상태·시즌·리뷰격차는 '피드백 섹션'이 아니라 전 섹션 판단의 '컨텍스트'로 주입.
        #     (section_labels에 없어 위 루프에서 제외됨 → 여기서 명시적으로 앞단에 붙인다)
        _ctx_bits = []
        _ms = req.sections.get("mystatus")
        if isinstance(_ms, dict) and (_ms.get("myRank") is not None or _ms.get("myActualReviews") is not None):
            _ctx_bits.append(f"[내 상품 현황(반드시 반영)] {json.dumps(_ms, ensure_ascii=False, default=str)} "
                             f"— isDefender=true면 '신규 진입'이 아니라 '상위권 방어·1위 추격·리뷰 격차 해소' 관점으로 작성.")
        _sea = req.sections.get("season")
        if isinstance(_sea, dict):
            _ctx_bits.append(f"[시즌·월별 트렌드(반드시 인용)] {json.dumps(_sea, ensure_ascii=False, default=str)[:1500]} "
                             f"— 데이터에 트렌드/시즌이 있으므로 '데이터 없음'이라 말하지 말 것. 비수기면 낮은 수치는 비수기 탓임을 명시.")
        _rev = req.sections.get("review")
        if isinstance(_rev, dict):
            _ctx_bits.append(f"[리뷰 격차] {json.dumps(_rev, ensure_ascii=False, default=str)[:800]}")
        _context_block = ("\n\n".join(_ctx_bits) + "\n\n---\n\n") if _ctx_bits else ""

        if (req.vertical or "shopping") == "place":
            system_prompt = place_crawler.PLACE_AI_SYSTEM_PROMPT
        else:
            system_prompt = """당신은 메타아이앤씨(METAINC) 시니어 네이버 쇼핑 마케팅 컨설턴트입니다.
네이버 쇼핑 알고리즘(적합도·인기도·신뢰도)에 정통합니다.

작성 원칙:
- 광고주에게 1:1로 브리핑하듯 자연스러운 대화체로 작성하세요.
- 각 섹션별로 [섹션명] 구분자를 사용하되, 내용은 자연스럽게 서술하세요.
- 반드시 데이터 수치를 인용하며, 근거 없는 추상적 표현은 쓰지 마세요.
- 아이콘, 이모지, 특수기호(**, ##)는 사용하지 마세요.
- 각 섹션은 5~8줄 내외로, 현황→핵심 이슈→실행 전략 흐름으로 작성하세요.
- 마지막에 'METAINC 종합 인사이트'로 전체 요약과 핵심 액션 3가지를 짧게 정리하세요.

[사실성 규칙 — 반드시 준수]
- 제공된 데이터에 있는 사실·수치만 사용하세요. 데이터에 없는 내용을 지어내거나 단정하지 마세요.
- 카테고리·업종은 데이터에 명시된 값만 그대로 쓰고, 추측으로 다른 카테고리(예: 건강/뷰티/식품 등)를 섞거나 바꾸지 마세요. (예: 데이터가 '가구>소파'면 식품·건강 등을 언급하지 마세요.)
- 광고주의 운영 방식(매일 소재 제작, 메시지 마케팅 등)이나 외부 플랫폼·서비스(당근비즈니스/당근마켓, 쿠팡, 토스 등)는 데이터로 확인되지 않으면 언급하지 마세요. 특히 그 서비스의 성격(온라인/오프라인/지역기반 등)을 임의로 단정하지 마세요.
- 값이 0이거나 비어있는 항목(리뷰수, 평점, 판매가 등)은 '데이터 미수집(확인 필요)'으로 표현하고, 0을 실제 수치처럼 단정하지 마세요.
- 매출·판매량 등 '추정' 항목은 단정적 단일 숫자로 쓰지 말고, 데이터에 범위(예: estimatedMonthlyRange, estRevenueRange, revenueRange)가 있으면 그 범위로, 없으면 '약 N(추정)'처럼 추정임을 명시하세요. 추정 전환율은 가정값이며 실제와 다를 수 있음을 한 번 언급하세요.

[상태 인지 규칙 — 신규 진입자 vs 상위권 방어자 구분]
- 데이터의 mystatus(내 상품 현재 순위·실측 리뷰수·SEO점수)를 반드시 먼저 확인하세요.
- 내 상품이 이미 상위권(순위 1~10위)이거나 실측 리뷰가 상당수(예: 100건 이상)면, 이 광고주는 '신규 진입자'가 아니라 '상위권 방어자'입니다. 이 경우 '신규 진입', '1페이지 진입', '리뷰 N건 목표(현재 리뷰수보다 적은 값)', '진입 점수' 같은 표현을 절대 쓰지 마세요.
- 방어자에게는 '현 순위 방어·상위(1위) 추격', '경쟁사 대비 리뷰 격차 해소(현재 X건 → 상위 평균 Y건)', '성수기 선점', '객단가·재구매 강화' 관점으로 서술하세요.
- 리뷰 목표는 하드코딩 숫자가 아니라 데이터의 실측 리뷰수와 경쟁 평균의 격차를 근거로 제시하세요.
- 시즌/월별 지수 데이터가 있으면 반드시 인용하고 '데이터에 트렌드가 없다'고 말하지 마세요. 분석 시점이 비수기(현재 지수가 연중 최고 대비 낮음)면 낮은 수치는 비수기 때문임을 명시하고, 성수기 대비 선점 준비 관점으로 조언하세요."""

        # ★502 방지: 동기 Claude 호출을 별도 스레드로 실행해 이벤트 루프(워커 하트비트)를
        #  막지 않음. 이렇게 하면 생성이 길어져도 gunicorn 120s 타임아웃에 워커가 죽지 않음.
        import asyncio
        user_content = f"""키워드 '{req.keyword}'에 대한 전체 분석 데이터입니다.
각 섹션별로 분석 피드백을 작성해주세요.

{_context_block}{combined_data}

각 섹션을 [섹션명] 형태로 구분하여, 광고주 브리핑 형식으로 작성하세요."""

        def _call_claude():
            return client.messages.create(
                model="claude-sonnet-4-6",
                # 여러 섹션 + 마지막 'METAINC 종합 인사이트'까지 한 번에 생성하므로
                # 4000 토큰으로는 마지막 요약이 잘리는 사례가 있어 상향(8000).
                # max_tokens는 실제 생성된 토큰만 과금되어 비용 영향은 최소.
                max_tokens=8000,
                messages=[{"role": "user", "content": user_content}],
                system=system_prompt
            )

        message = await asyncio.to_thread(_call_claude)

        # 출력이 토큰 한도로 잘린 경우 감지 (인사이트가 중간에 끊기는 문제 추적용)
        if getattr(message, "stop_reason", None) == "max_tokens":
            logger.warning(
                f"[feedback-all] 응답이 max_tokens 한도로 잘렸습니다 "
                f"(keyword='{req.keyword}', output_tokens={getattr(message.usage, 'output_tokens', '?')}). "
                f"max_tokens 추가 상향을 검토하세요."
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
                model="claude-sonnet-4-6",
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
                model="claude-sonnet-4-6",
                user_id=current_user.get("id", 0),
                status="error", error_message=str(e)[:200]  # 내부 로그용
            )
        except Exception:
            pass
        return {"success": False, "error": "AI 통합 피드백 생성 중 오류가 발생했습니다."}


# --- API 사용량 조회 (superadmin 전용, v3.9.13) ---
@app.get("/api/admin/api-usage")
def get_api_usage(current_user: dict = Depends(get_current_user)):
    """API 사용량 대시보드 데이터 — superadmin 전용"""
    if current_user.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="접근 권한이 없습니다.")
    try:
        from database import get_api_usage_summary
        data = get_api_usage_summary(days=30)
        try:
            # 검색 API 자체 계측(호출 다이어트 2026-07) — 일일 25,000 한도 대비 현황
            from naver_crawler import get_search_api_usage_today
            data["searchApiToday"] = get_search_api_usage_today()
        except Exception:
            pass
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"API 사용량 조회 실패: {e}")
        return {"success": False, "error": "API 사용량 조회 중 오류가 발생했습니다."}


_NAVER_PROBE_CACHE = {"at": 0.0, "data": None}

@app.get("/api/diag/naver-probe")
def naver_probe():
    """네이버 검색 API 생사 진단 — 읽기 전용·일시 진단용.

    2026-07-31 '네이버 검색 > 쇼핑 API 종료' 공지 이후 순위 추적이 전부 '미노출'로
    나오는 원인을 서버에서 직접 확인하기 위한 임시 엔드포인트다.
    같은 키로 쇼핑(shop)과 블로그(blog)를 1회씩 호출해 비교한다
    — 쇼핑만 실패하면 종료 확정, 둘 다 실패하면 키·쿼터 등 계정 문제다.

    · 인증 없음: 진단자가 바로 열어봐야 하므로. 대신 아래를 지킨다.
      - 키·토큰·업체 정보 등 비밀값은 응답에 넣지 않는다(상태코드·건수·판정만).
      - 5분 캐시로 호출을 묶어 쿼터 낭비·외부 남용을 막는다(최악 576회/일 << 25,000).
      - 파라미터를 받지 않아 임의 검색 통로로 쓰일 수 없다.
    · 원인 확정 후 제거 예정.
    """
    import requests, json, re  # main.py 전역에 없어 함수 안에서 가져온다(진단 전용)
    from naver_crawler import NAVER_CLIENT_ID, NAVER_CLIENT_SECRET

    now = time.time()
    if _NAVER_PROBE_CACHE["data"] and (now - _NAVER_PROBE_CACHE["at"]) < 300:
        return {"success": True, "cached": True, "data": _NAVER_PROBE_CACHE["data"]}

    out = {"checkedAt": datetime.now().isoformat(),
           "keyConfigured": bool(NAVER_CLIENT_ID and NAVER_CLIENT_SECRET),
           "probes": {}}
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    for label, path in (("shop", "shop.json"), ("blog", "blog.json")):
        try:
            r = requests.get(f"https://openapi.naver.com/v1/search/{path}",
                             params={"query": "홍삼", "display": 1}, headers=headers, timeout=10)
            info = {"status": r.status_code, "total": None, "errorCode": None, "errorMessage": None}
            try:
                j = r.json()
                info["total"] = j.get("total")
                info["errorCode"] = j.get("errorCode")
                info["errorMessage"] = j.get("errorMessage")
            except Exception:
                pass
            out["probes"][label] = info
        except Exception as e:
            out["probes"][label] = {"status": None, "errorMessage": str(e)[:200]}

    # 검색광고 API(searchad — 검색량·연관키워드) 실호출 확인: 전수조사에서 유일한 '확인불가' 항목.
    # 1콜 소모(무해)·5분 캐시 안에서만. 실패해도 다른 진단은 그대로.
    try:
        from naver_crawler import get_keyword_volume
        _v = get_keyword_volume(["홍삼"])
        out["probes"]["searchad"] = {
            "ok": bool(_v), "rows": len(_v or []),
            "sampleVolume": (_v[0].get("monthlyPcQcCnt") if _v else None),
        }
    except Exception as _e:
        out["probes"]["searchad"] = {"ok": False, "errorMessage": str(_e)[:200]}

    # 최근 5일 순위 기록 통계 — '배치가 수집분을 실제로 소비해 순위를 기록했는가'를
    # 외부에서 확인하는 계기판(읽기 전용). 8/1~3 처럼 미노출 100% 면 파이프라인 이상.
    try:
        import sqlite3 as _sq3
        from client_dashboard import DB_PATH as _CD_DB3
        _c3 = _sq3.connect(_CD_DB3, timeout=10)
        _c3.row_factory = _sq3.Row
        out["rankDays"] = [dict(r) for r in _c3.execute("""
            SELECT substr(checked_at,1,10) AS d, COUNT(*) AS total,
                   SUM(CASE WHEN rank_position IS NULL THEN 1 ELSE 0 END) AS no_rank
            FROM client_rank_history
            WHERE checked_at >= date('now','localtime','-4 day')
            GROUP BY d ORDER BY d
        """).fetchall()]
        _c3.close()
    except Exception as _e:
        out["rankDays"] = {"error": str(_e)[:150]}

    # 추적 상품 스토어명 슬러그 계기 — 자가치유(2026-08-04 직원 신고 대응) 진행 관측용.
    # 슬러그 = URL에서 뽑은 스토어 아이디가 store_name 에 그대로 남은 상태. 개수만 노출(업체 정보 없음).
    try:
        import sqlite3 as _sq4
        from naver_crawler import extract_store_name_from_url as _esn
        from database import DB_PATH as _DB4
        _c4 = _sq4.connect(_DB4, timeout=5)
        _c4.row_factory = _sq4.Row
        _tot = _slugged = _empty = 0
        for _r in _c4.execute("SELECT product_url, store_name FROM tracked_products"):
            _tot += 1
            _st = (_r["store_name"] or "").strip()
            if not _st:
                _empty += 1
            elif _st.lower() == ((_esn(_r["product_url"] or "") or "").strip().lower()):
                _slugged += 1
        _c4.close()
        out["storeNameHeal"] = {"total": _tot, "slug": _slugged, "empty": _empty}
    except Exception as _e:
        out["storeNameHeal"] = {"error": str(_e)[:150]}

    sh, bl = out["probes"].get("shop", {}), out["probes"].get("blog", {})
    if sh.get("status") == 200 and (sh.get("total") or 0) > 0:
        out["verdict"] = "쇼핑 API 정상 — 미노출 원인은 다른 곳(순위 판정·상품 매칭 등)"
    elif bl.get("status") == 200 and sh.get("status") != 200:
        out["verdict"] = "쇼핑 API만 실패 — 서비스 종료로 확정 (같은 키로 블로그는 정상)"
    elif bl.get("status") != 200 and sh.get("status") != 200:
        out["verdict"] = "둘 다 실패 — 키 만료·쿼터 소진 등 계정 문제 가능성"
    else:
        out["verdict"] = "판정 불가 — probes 원문 확인 필요"

    # ── 대체 경로(크롤링) 실현 가능성 진단 ──
    # 공식 API가 사라진 이상 순위 산출은 검색 결과 크롤링뿐이라, 서버에서 실제로
    # 가져와지는지 후보별로 1회씩 확인한다. 상품 개수까지 세어 '접속만 되는' 경우와 구분.
    def _probe_crawl(label, url, via_bee=False):
        try:
            if via_bee:
                from naver_crawler import _fetch_via_scrapingbee, SCRAPINGBEE_API_KEY
                if not SCRAPINGBEE_API_KEY:
                    return {"ok": False, "note": "ScrapingBee 키 미설정"}
                body = _fetch_via_scrapingbee(url, render_js=False, stealth=True) or ""
                status = 200 if body else None
            else:
                from naver_crawler import _get_realistic_headers
                r = requests.get(url, headers=_get_realistic_headers(
                    referer="https://search.shopping.naver.com/"), timeout=15)
                status, body = r.status_code, (r.text or "")
            n = None
            try:
                if body.lstrip()[:1] in "{[":
                    j = json.loads(body)
                    for key in ("shoppingResult", "products"):
                        node = j.get(key) if isinstance(j, dict) else None
                        if isinstance(node, dict) and isinstance(node.get("products"), list):
                            n = len(node["products"]); break
                        if isinstance(node, list):
                            n = len(node); break
                elif "__NEXT_DATA__" in body:
                    n = body.count('"productTitle"') or body.count('"mallName"')
            except Exception:
                pass
            return {"ok": bool(body) and status == 200, "status": status,
                    "bytes": len(body), "productsParsed": n,
                    "blocked": bool(re.search(r"captcha|자동입력|비정상적", body[:4000], re.I)) if body else None}
        except Exception as e:
            return {"ok": False, "error": str(e)[:160]}

    q = "%ED%99%8D%EC%82%BC"  # 홍삼
    out["crawlProbes"] = {
        "searchJsonApi": _probe_crawl("json",
            f"https://search.shopping.naver.com/api/search/all?sort=rel&pagingIndex=1&pagingSize=40&query={q}"),
        "searchHtml": _probe_crawl("html",
            f"https://search.shopping.naver.com/search/all?query={q}"),
    }

    # ScrapingBee 는 위 헬퍼(_fetch_via_scrapingbee)가 HTML 응답만 수용하도록 돼 있어
    # JSON API 주소로는 성공해도 버려진다 → 여기서는 ScrapingBee 를 직접 호출해
    # 상태코드·에러헤더·남은 크레딧까지 그대로 본다(되살릴 수 있는지 판단용).
    def _probe_bee(url, stealth=True):
        try:
            from naver_crawler import SCRAPINGBEE_API_KEY, SCRAPINGBEE_API_URL
            if not SCRAPINGBEE_API_KEY:
                return {"ok": False, "note": "ScrapingBee 키 미설정"}
            params = {"api_key": SCRAPINGBEE_API_KEY, "url": url, "render_js": "false",
                      "block_resources": "false", "country_code": "kr",
                      "transparent_status_code": "true"}
            params["stealth_proxy" if stealth else "premium_proxy"] = "true"
            r = requests.get(SCRAPINGBEE_API_URL, params=params, timeout=90)
            body = r.text or ""
            n = None
            try:
                if body.lstrip()[:1] in "{[":
                    j = json.loads(body)
                    node = j.get("shoppingResult") if isinstance(j, dict) else None
                    if isinstance(node, dict) and isinstance(node.get("products"), list):
                        n = len(node["products"])
            except Exception:
                pass
            return {"ok": r.status_code == 200 and bool(body),
                    "status": r.status_code, "bytes": len(body), "productsParsed": n,
                    "spbError": r.headers.get("Spb-error-code") or r.headers.get("Spb-error"),
                    "creditsLeft": r.headers.get("Spb-remaining-api-calls") or r.headers.get("Spb-remaining-calls"),
                    "cost": r.headers.get("Spb-cost"),
                    "bodyHead": body[:200]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    # 비용을 좌우하는 두 변수를 실측한다.
    #  ① 프록시 등급: stealth 75크레딧 vs premium 25크레딧 — premium 이 통하면 비용 1/3
    #  ② 페이지당 개수: 40 vs 80 — 80이 통하면 300위 확보에 필요한 호출이 절반
    _u = "https://search.shopping.naver.com/api/search/all?sort=rel&pagingIndex=1&pagingSize={n}&query=" + q
    out["crawlProbes"]["beeStealth40"] = _probe_bee(_u.format(n=40), stealth=True)
    out["crawlProbes"]["beePremium40"] = _probe_bee(_u.format(n=40), stealth=False)
    out["crawlProbes"]["beeStealth80"] = _probe_bee(_u.format(n=80), stealth=True)

    # 비용 산정 기준 — 실제 추적 중인 키워드 수(중복 제외)
    try:
        import sqlite3 as _sq2
        from client_dashboard import DB_PATH as _CD_DB2
        _c2 = _sq2.connect(_CD_DB2, timeout=10)
        out["trackingScale"] = {
            "distinctKeywords": _c2.execute(
                "SELECT COUNT(DISTINCT keyword) FROM client_rank_history "
                "WHERE checked_at >= date('now','localtime','-2 day')").fetchone()[0],
            "rowsPerDay": _c2.execute(
                "SELECT COUNT(*) FROM client_rank_history "
                "WHERE substr(checked_at,1,10) = date('now','localtime')").fetchone()[0],
        }
        _c2.close()
    except Exception as e:
        out["trackingScale"] = {"error": str(e)[:200]}

    # 잘못 쌓인 순위 이력(수집 실패인데 미노출로 저장된 행) 규모 — 읽기 전용 집계
    try:
        import sqlite3 as _sq
        from client_dashboard import DB_PATH as _CD_DB
        _c = _sq.connect(_CD_DB, timeout=10)
        rows = _c.execute("""
            SELECT substr(checked_at,1,10) AS d, COUNT(*) AS total,
                   SUM(CASE WHEN rank_position IS NULL THEN 1 ELSE 0 END) AS nulls
            FROM client_rank_history
            WHERE checked_at >= date('now','localtime','-7 day')
            GROUP BY d ORDER BY d
        """).fetchall()
        _c.close()
        out["rankHistoryRecent"] = [{"date": r[0], "total": r[1], "미노출": r[2]} for r in rows]
    except Exception as e:
        out["rankHistoryRecent"] = {"error": str(e)[:200]}

    _NAVER_PROBE_CACHE["at"], _NAVER_PROBE_CACHE["data"] = now, out
    return {"success": True, "cached": False, "data": out}


# ==================== 데이터랩 쇼핑인사이트 ====================

class DatalabRequest(BaseModel):
    keyword: str
    category1: str = ""
    category2: str = ""
    category3: str = ""
    related_keywords: list = []

@app.post("/api/datalab/analyze")
def datalab_analyze(req: DatalabRequest, current_user: dict = Depends(get_current_user)):
    """네이버 데이터랩 쇼핑인사이트 통합 분석 (인증 필수)"""
    try:
        result = analyze_datalab(
            keyword=req.keyword,
            category1=req.category1,
            category2=req.category2,
            category3=req.category3,
            related_keywords=[{"keyword": k} if isinstance(k, str) else k for k in req.related_keywords],
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error(f"데이터랩 분석 실패: {e}")
        return {"success": False, "detail": "데이터랩 분석 중 오류가 발생했습니다."}


# --- 헬스체크 ---
@app.get("/api/health")
def health():
    return {"status": "ok", "version": "3.0.0", "timestamp": datetime.now().isoformat()}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5050, reload=True)
