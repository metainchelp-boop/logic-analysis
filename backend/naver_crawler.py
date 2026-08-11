"""
네이버 쇼핑 순위 분석 모듈 v2
- 공식 네이버 쇼핑 API 전용
- 웹 스크래핑 완전 제거 (VPS에서 HTTP 418 차단됨)
- nvMid 기반 상품 매칭
- 네이버 검색광고 API 키워드 볼륨 연동

⚠️ 중요: 네이버 공식 검색 API는 sort=sim(유사도순)만 지원하며,
  실제 네이버쇼핑 노출 순위(관련성순)와는 차이가 있을 수 있습니다.
  하지만 상품 발견 여부 및 대략적 경쟁력 파악에는 유용합니다.
"""
import requests
import hashlib
import hmac
import base64
import time
import re
import os
import logging
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)

# ==================== 환경변수 ====================
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
SEARCHAD_API_KEY = os.getenv("SEARCHAD_API_KEY", "")
SEARCHAD_SECRET_KEY = os.getenv("SEARCHAD_SECRET_KEY", "")
SEARCHAD_CUSTOMER_ID = os.getenv("SEARCHAD_CUSTOMER_ID", "")

# Bright Data 프록시 (상세페이지 크롤링용 - fallback)
BRD_API_KEY = os.getenv("NAVER_BRD_API_KEY", "")
BRD_API_URL = os.getenv("NAVER_BRD_API_URL", "")
BRD_API_ZONE = os.getenv("NAVER_BRD_API_ZONE", "")

# ScrapingBee API (상세페이지 크롤링 주 수단)
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", "")
SCRAPINGBEE_API_URL = "https://app.scrapingbee.com/api/v1/"


# ==================== SSRF 가드 ====================
# 서버가 사용자 입력 URL을 직접 fetch하므로, 네이버 계열 호스트만 허용한다.
# (내부망/클라우드 메타데이터(169.254.169.254)/localhost 접근 차단)
def is_allowed_fetch_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    return host == "naver.com" or host.endswith(".naver.com")


def _assert_allowed_fetch_url(url: str):
    if not is_allowed_fetch_url(url):
        raise ValueError("허용되지 않은 URL입니다 (네이버 도메인만 허용)")



# ==================== 유틸리티 ====================

def extract_product_id_from_url(product_url: str) -> Optional[str]:
    """상품 URL에서 nvMid / 상품 ID 추출"""
    if not product_url:
        return None

    # 네이버 쇼핑 URL: nvMid 파라미터
    parsed = urlparse(product_url)
    params = parse_qs(parsed.query)
    if 'nvMid' in params:
        return params['nvMid'][0]

    # 스마트스토어: /products/12345
    match = re.search(r'/products/(\d+)', product_url)
    if match:
        return match.group(1)

    # 카탈로그: /catalog/12345
    match = re.search(r'/catalog/(\d+)', product_url)
    if match:
        return match.group(1)

    return None


def extract_store_name_from_url(url: str) -> Optional[str]:
    """URL에서 스토어명 추출"""
    if not url:
        return None
    match = re.search(r'smartstore\.naver\.com/([^/]+)', url)
    if match:
        return match.group(1)
    return None


# ==================== 검색 API 일일 사용량 계측 (호출 다이어트 2026-07) ====================
#   일일 한도 25,000 소진(2026-07-20 실사고)을 '사전에' 감지하기 위한 자체 카운터.
#   재시도 포함 실제 HTTP 요청 단위로 계수(쿼터 소모 기준과 동일). 50콜마다 파일 영속화.
import threading as _threading
_search_usage_lock = _threading.Lock()
_search_usage = {"date": "", "count": 0}
SEARCH_API_DAILY_LIMIT = 25000
_SEARCH_USAGE_FILE = os.path.join(os.path.dirname(os.getenv("DB_PATH", "/app/data/logic_data.db")),
                                  "search_api_usage.json")


def _count_search_api_call():
    from datetime import date as _date
    today = _date.today().isoformat()
    with _search_usage_lock:
        if _search_usage["date"] != today:
            _search_usage["date"] = today
            _search_usage["count"] = 0
            try:  # 재시작 대비: 오늘자 파일 값 복원
                import json as _json
                with open(_SEARCH_USAGE_FILE, "r", encoding="utf-8") as _f:
                    _s = _json.load(_f)
                if _s.get("date") == today:
                    _search_usage["count"] = int(_s.get("count", 0))
            except Exception:
                pass
        _search_usage["count"] += 1
        c = _search_usage["count"]
        if c % 50 == 0:
            try:
                import json as _json
                with open(_SEARCH_USAGE_FILE, "w", encoding="utf-8") as _f:
                    _json.dump(_search_usage, _f)
            except Exception:
                pass
    _warn_at = int(SEARCH_API_DAILY_LIMIT * 0.9)
    if c == _warn_at or (c > _warn_at and c % 500 == 0):
        logger.warning(f"⚠️ 검색 API 일일 사용량 {c}/{SEARCH_API_DAILY_LIMIT} — 소진 임박(90%+)")
    return c


def get_search_api_usage_today() -> Dict:
    """오늘 검색 API 사용량(자체 계측) — 관리자 대시보드용."""
    from datetime import date as _date
    today = _date.today().isoformat()
    with _search_usage_lock:
        cnt = _search_usage["count"] if _search_usage["date"] == today else 0
    if cnt == 0:
        try:
            import json as _json
            with open(_SEARCH_USAGE_FILE, "r", encoding="utf-8") as _f:
                _s = _json.load(_f)
            if _s.get("date") == today:
                cnt = int(_s.get("count", 0))
        except Exception:
            pass
    return {"date": today, "count": cnt, "limit": SEARCH_API_DAILY_LIMIT,
            "pct": round(cnt / SEARCH_API_DAILY_LIMIT * 100, 1)}


# ==================== 네이버 쇼핑 공식 API ====================

def search_naver_shopping_api(keyword: str, display: int = 100, start: int = 1, sort: str = "sim", retry_on_429: bool = False,
                              enqueue_on_miss: bool = True) -> Dict:
    """
    네이버 검색 API - 쇼핑 검색

    - display: 한 번에 가져올 결과 수 (최대 100)
    - start: 시작 위치 (최대 1000)
    - sort: sim(유사도순), date(날짜순), asc(가격낮은순), dsc(가격높은순)
    - retry_on_429: True면 429 시 대기 후 재시도 (수동 분석용)

    ⚠️ sort=sim은 실제 네이버쇼핑 노출 순위(rel)와 다름
    """
    # ── 2026-08 쇼핑 검색 API 종료(404 SE05) 대응: 브라우저 수집분 우선 서빙 ──
    # 사내 크롬 확장이 새벽에 올린 수집분(2일 내)이 있으면 원본 API 형식 그대로 반환.
    # 없으면 요청 큐에 등록하고 아래 기존 API 경로로 폴백(API 부활 시 자동 원복 = 무회귀).
    # 이 한 지점으로 분석기·광고주 분석·키워드 노출·자동 분석이 전부 수집분 위에서 돈다.
    try:
        from collector import serve_from_collected
        _served = serve_from_collected(keyword, display=display, start=start,
                                       enqueue_on_miss=enqueue_on_miss)
    except Exception as _se:
        _served = None
        logger.warning(f"수집분 서빙 실패(무시, API 폴백): {_se}")
    if _served is not None:
        logger.info(f"수집분 서빙 '{keyword}': {_served.get('total', 0)}건 중 {len(_served.get('items', []))}건 (브라우저 수집)")
        return _served

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 API 키가 설정되지 않았습니다.")
        return {"error": "API 키 미설정", "items": [], "total": 0}

    url = "https://openapi.naver.com/v1/search/shop.json"
    params = {
        "query": keyword,
        "display": min(display, 100),
        "start": min(start, 1000),
        "sort": sort,
    }
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }

    max_retries = 3 if retry_on_429 else 2
    for attempt in range(max_retries + 1):
        try:
            _count_search_api_call()  # 일일 사용량 계측(재시도 포함 — 쿼터는 요청 단위로 소모됨)
            response = requests.get(url, params=params, headers=headers, timeout=10)
            # 429 Too Many Requests
            if response.status_code == 429:
                # 429는 "빠른 실패" 한다: 짧게 1회만 재시도(0.4초)하고 포기.
                # 네이버가 rate-limit 중일 때 길게(2/4/6초) 재시도해봐야 대부분
                # 다시 429로 실패하면서 워커를 최대 12초씩 점유 → 무거운 분석이
                # 적은 워커를 모두 묶어 가벼운 요청(my-clients 등)까지 502가 났다.
                if retry_on_429 and attempt < 1:
                    logger.warning(f"네이버 API 429 — 0.4초 후 1회 재시도 (keyword: {keyword})")
                    time.sleep(0.4)
                    continue
                logger.warning(f"네이버 API 429 Rate Limit — 건너뜀 (keyword: {keyword})")
                return {"error": "API 요청 한도 초과", "items": [], "total": 0}
            # 404 = 쇼핑 검색 API 서비스 종료(SE05, 2026-07-31). 재시도해도 소용없으니 즉시 반환
            if response.status_code == 404:
                logger.error(f"쇼핑 검색 API 404(서비스 종료) — 수집분도 없음 (keyword: {keyword})")
                return {"error": "쇼핑 검색 API 종료(수집분 없음)", "items": [], "total": 0}
            response.raise_for_status()
            data = response.json()
            logger.info(f"API 검색 '{keyword}': {data.get('total', 0)}건 중 {len(data.get('items', []))}건 조회")
            return data
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                logger.warning(f"네이버 API 재시도 ({attempt + 1}/{max_retries}): {e}")
                time.sleep(1.0 * (attempt + 1))
            else:
                logger.error(f"네이버 API 요청 실패 (재시도 소진): {e}")
                return {"error": str(e), "items": [], "total": 0}


def _parse_api_item(item: Dict, rank: int) -> Dict:
    """API 응답 아이템을 표준 포맷으로 변환"""
    # HTML 태그 제거 (title에 <b> 태그 포함됨)
    title = re.sub(r'<[^>]+>', '', item.get("title", ""))

    # productId 추출 (API 응답에 포함)
    product_id = str(item.get("productId", ""))
    if not product_id and item.get("link"):
        pid = extract_product_id_from_url(item["link"])
        if pid:
            product_id = pid

    return {
        "rank": rank,
        "product_id": product_id,
        "product_name": title,
        "price": _safe_int(item.get("lprice", 0)),
        "hprice": _safe_int(item.get("hprice")) if item.get("hprice") else None,
        "store_name": item.get("mallName", ""),
        "image_url": item.get("image", ""),
        "product_url": item.get("link", ""),
        "brand": item.get("brand", ""),
        "maker": item.get("maker", ""),
        "category1": item.get("category1", ""),
        "category2": item.get("category2", ""),
        "category3": item.get("category3", ""),
        "product_type": item.get("productType", ""),
        # API에서 리뷰/평점은 제공하지 않으므로 0으로 표시
        "review_count": 0,
        "rating": 0,
        "purchase_count": 0,
    }


def get_review_count(product_url: str) -> Optional[int]:
    """스마트스토어 내부 API로 '리뷰수'만 가볍게 조회 (리뷰 델타 추정용).
    실패하면 None 반환 — 호출부(순위 기록)가 절대 깨지지 않도록 완전 방어적."""
    try:
        store = extract_store_name_from_url(product_url)
        pno = extract_product_id_from_url(product_url)
        if not store or not pno:
            return None
        api_url = f"https://smartstore.naver.com/i/v1/stores/{store}/products/{pno}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/124.0.0.0 Mobile Safari/537.36",
            "Accept": "application/json",
            "Referer": f"https://smartstore.naver.com/{store}/products/{pno}",
        }
        resp = requests.get(api_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            ra = resp.json().get("reviewAmount", {})
            if isinstance(ra, dict):
                rc = ra.get("totalReviewCount")
                if rc is not None and int(rc) >= 0:
                    return int(rc)
    except Exception:
        pass
    return None


def search_products(keyword: str, max_results: int = 200, retry_on_429: bool = True) -> List[Dict]:
    """
    키워드로 상품 검색 (최대 1000개까지)
    여러 페이지를 자동으로 조회하여 합침
    retry_on_429: 429(호출제한) 시 재시도 — 상품 매칭이 간헐적으로 실패하는 것을 방지
    """
    all_products = []
    per_page = 100

    for start in range(1, min(max_results, 1000) + 1, per_page):
        result = search_naver_shopping_api(keyword, display=per_page, start=start, retry_on_429=retry_on_429)
        items = result.get("items", [])
        if not items:
            break

        for idx, item in enumerate(items):
            rank = start + idx
            all_products.append(_parse_api_item(item, rank))

        # API 호출 간격
        if start + per_page <= max_results:
            time.sleep(0.3)

    return all_products


# ==================== 상품 순위 찾기 ====================

def _normalize_name(name: str) -> str:
    """상품명 정규화: 공백/특수문자 제거, 소문자"""
    return re.sub(r'[\s\-_/·•\(\)\[\]【】]', '', name).lower()


def find_product_rank(keyword: str, product_url: str,
                      max_pages: int = 10, product_name: str = "",
                      cached_products: Optional[List[Dict]] = None) -> Tuple[Optional[int], Optional[int], List[Dict]]:
    """
    키워드 검색에서 특정 상품의 순위를 찾는다. (공식 API 기반)

    매칭 우선순위:
    1. productId(nvMid) 완전 일치
    2. 채널 productId가 API product_url에 포함 (채널ID는 고유값)
    3. 스토어명 일치 + 상품명 유사도 (폴백)

    ⚠️ 이 순위는 공식 API의 sort=sim(유사도순) 기준이며,
       실제 네이버쇼핑 노출 순위(sort=rel)와는 다를 수 있습니다.

    Returns:
        (rank_position, page_number, top_competitors)
    """
    target_product_id = extract_product_id_from_url(product_url)
    target_store_name = extract_store_name_from_url(product_url)
    top_competitors = []

    # max_pages * 100개 결과까지 검색
    # cached_products가 주어지면 재검색 없이 재사용 (중복 API 호출 방지) — 매칭 로직은 동일
    max_results = max_pages * 100
    products = cached_products if cached_products is not None else search_products(keyword, max_results=max_results)

    if not products:
        logger.warning(f"검색 결과 없음: '{keyword}'")
        return None, None, []

    # 상위 5개 = 경쟁 상품
    top_competitors = products[:5]

    # 스토어 슬러그 비교 헬퍼 (URL 슬러그 vs API 스토어명/URL 모두 비교)
    def _store_matches(product):
        """대상 스토어와 검색 결과 상품의 스토어가 같은지 확인"""
        if not target_store_name:
            return True  # 스토어명 없으면 검증 스킵
        # 1) API product_url에서 스토어 슬러그 추출하여 비교
        p_url_store = extract_store_name_from_url(product.get("product_url", ""))
        if p_url_store and p_url_store.lower() == target_store_name.lower():
            return True
        # 2) mallName과 직접 비교 (같은 경우도 있음)
        p_mall = (product.get("store_name") or "").lower()
        if p_mall and p_mall == target_store_name.lower():
            return True
        return False

    # --- 1차: ID 기반 정확 매칭 ---
    for product in products:
        matched = False

        # 1순위: productId(nvMid) 완전 일치
        if target_product_id and product.get("product_id"):
            if target_product_id == product["product_id"]:
                matched = True

        # 2순위: 채널 productId가 API product_url에 포함
        # ※ 네이버 API는 product_url을 /main/products/채널ID 형식으로 반환하므로
        #    스토어 슬러그 검증 없이 PID 포함만으로 매칭 (채널ID는 고유값)
        if not matched and target_product_id and product.get("product_url"):
            if target_product_id in product["product_url"]:
                matched = True

        if matched:
            page_number = (product["rank"] - 1) // 40 + 1
            logger.info(f"상품 발견(ID매칭)! '{keyword}' → {product['rank']}위 (페이지 {page_number})")
            return product["rank"], page_number, top_competitors

    # --- 2차: 스토어명 + 상품명 유사도 폴백 ---
    # 스토어명이 없거나 상품명을 모르면 스킵
    if not target_store_name:
        logger.info(f"상품 미발견: '{keyword}' (검색 범위: {len(products)}개, 스토어명 없어 유사도 매칭 불가)")
        return None, None, top_competitors

    # 상품명 확보: 파라미터로 받았거나, 스마트스토어 API에서 조회
    ref_name = product_name
    if not ref_name:
        try:
            info = get_product_info(product_url, keyword=keyword)
            ref_name = info.get("product_name", "")
        except Exception:
            pass
    if not ref_name:
        logger.info(f"상품 미발견: '{keyword}' (검색 범위: {len(products)}개, 상품명 미확보로 유사도 매칭 불가)")
        return None, None, top_competitors

    ref_norm = _normalize_name(ref_name)
    best_match = None
    best_score = 0

    for product in products:
        # 스토어 일치 검증 — tier-1과 동일한 헬퍼 사용.
        # (기존엔 API mallName(한글)과 URL 슬러그(영문)를 정확 비교해 거의 항상 불일치 →
        #  실제 노출 상품도 '미노출'로 오판하던 문제를 해소)
        if not _store_matches(product):
            continue

        p_norm = _normalize_name(product.get("product_name", ""))
        if not p_norm or not ref_norm:
            continue

        # 유사도: 긴 쪽이 짧은 쪽을 포함하면 높은 점수, 아니면 공통 글자 비율
        if ref_norm in p_norm or p_norm in ref_norm:
            score = 0.9 + 0.1 * (min(len(ref_norm), len(p_norm)) / max(len(ref_norm), len(p_norm)))
        else:
            # 공통 문자 비율 (순서 무관 집합 기반)
            common = len(set(ref_norm) & set(p_norm))
            total = max(len(set(ref_norm) | set(p_norm)), 1)
            score = common / total

        if score > best_score:
            best_score = score
            best_match = product

    # 유사도 70% 이상이면 매칭으로 판정
    if best_match and best_score >= 0.7:
        page_number = (best_match["rank"] - 1) // 40 + 1
        logger.info(f"상품 발견(유사도매칭)! '{keyword}' → {best_match['rank']}위 (유사도: {best_score:.2f}, 스토어: {target_store_name})")
        return best_match["rank"], page_number, top_competitors

    logger.info(f"상품 미발견: '{keyword}' (검색 범위: {len(products)}개, 최고 유사도: {best_score:.2f})")
    return None, None, top_competitors


def find_product_rank_from_cache(keyword: str, product_url: str,
                                  cached_products: List[Dict]) -> Tuple[Optional[int], Optional[int], List[Dict]]:
    """
    이미 조회된 상품 목록(cached_products)에서 순위를 찾는다. (API 호출 없음)
    스케줄러 통합 작업에서 1회 API 호출 결과를 재사용하기 위한 함수.

    Returns:
        (rank_position, page_number, top_competitors)
    """
    if not cached_products:
        return None, None, []

    target_product_id = extract_product_id_from_url(product_url)
    target_store_name = extract_store_name_from_url(product_url)
    top_competitors = cached_products[:5]

    for product in cached_products:
        matched = False

        # 1순위: productId(nvMid) 완전 일치
        if target_product_id and product.get("product_id"):
            if target_product_id == product["product_id"]:
                matched = True

        # 2순위: productId가 URL에 포함
        if not matched and target_product_id and product.get("product_url"):
            if target_product_id in product["product_url"]:
                matched = True

        # 3순위: 스토어명 일치 + productId 부분 매칭
        if not matched and target_store_name and product.get("store_name"):
            if target_store_name.lower() == product["store_name"].lower():
                if target_product_id and target_product_id in str(product.get("product_url", "")):
                    matched = True

        if matched:
            page_number = (product["rank"] - 1) // 40 + 1
            logger.info(f"[캐시] 상품 발견! '{keyword}' → {product['rank']}위 (페이지 {page_number})")
            return product["rank"], page_number, top_competitors

    logger.info(f"[캐시] 상품 미발견: '{keyword}' (검색 범위: {len(cached_products)}개)")
    return None, None, top_competitors


# ==================== 상품 정보 조회 ====================

# ── 상품정보 캐시 (B1) ──
# 같은 상품을 짧은 시간 내 반복 크롤하면 네이버를 중복 호출해 429를 유발한다.
# 성공 결과를 TTL 동안 캐시해 중복 호출을 제거한다. (uvicorn 워커별 메모리 캐시)
_PRODUCT_INFO_CACHE = {}      # product_url -> (timestamp, result_dict)
_PRODUCT_INFO_TTL = 900       # 15분


def get_product_info(product_url: str, keyword: str = "") -> Dict:
    """상품정보 조회 (TTL 캐시 래퍼). TTL 내 성공 결과가 있으면 네이버 재호출 없이 반환."""
    now = time.time()
    hit = _PRODUCT_INFO_CACHE.get(product_url)
    if hit and (now - hit[0]) < _PRODUCT_INFO_TTL:
        return dict(hit[1])  # 사본 반환 (호출측 변형 방지)
    result = _get_product_info_impl(product_url, keyword=keyword)
    # 의미있는 결과(상품명 확보)만 캐시 — 실패는 캐시하지 않아 다음 기회에 재시도
    if result and result.get("product_name"):
        if len(_PRODUCT_INFO_CACHE) > 5000:
            _PRODUCT_INFO_CACHE.clear()  # 단순 상한 (메모리 보호)
        _PRODUCT_INFO_CACHE[product_url] = (now, dict(result))
    return result


def _get_product_info_impl(product_url: str, keyword: str = "") -> Dict:
    """
    상품 URL에서 상품 정보 가져오기
    - 1차: 추적 키워드로 네이버 쇼핑 API 검색 → URL/productId 매칭 (빠르고 안정적)
    - 2차: 스토어명으로 네이버 쇼핑 API 검색 → productId 매칭 (폴백)
    - 3차: 상품 페이지 직접 방문 → og:meta 파싱 (VPS에서 429 가능성 있음)
    """
    product_id = extract_product_id_from_url(product_url) or ""
    store_name = extract_store_name_from_url(product_url) or ""

    result = {
        "product_name": "",
        "store_name": store_name,
        "image_url": "",
        "price": 0,
        "product_id": product_id,
        "product_url": product_url,
        "review_count": 0,
        "rating": 0,
        "category1": "",
        "category2": "",
        "category3": "",
    }

    def _match_item(item):
        """API 검색 결과 아이템이 대상 상품과 매칭되는지 확인"""
        item_pid = str(item.get("productId", ""))
        item_link = item.get("link", "")
        item_mall = (item.get("mallName", "") or "").lower()
        # 1순위: productId 정확 매칭
        if product_id and item_pid == product_id:
            return True
        # 2순위: URL에 productId 포함 + 스토어 검증 (다른 스토어 오염 방지)
        if product_id and product_id in item_link:
            if store_name:
                # URL 슬러그 비교 또는 mallName 비교
                if store_name.lower() in item_link.lower():
                    return True
                if item_mall and item_mall == store_name.lower():
                    return True
                return False  # 스토어 불일치 → 거부
            return True
        # 3순위: 스토어명 + 상품 링크에 스토어 슬러그 포함
        #   ⚠️ productId를 URL에서 뽑은 경우엔 스토어명만으로 매칭하지 않는다.
        #   productId가 있는데 1·2순위에서 안 잡혔다 = 같은 스토어의 '다른 상품' → 거부.
        #   (지정 상품 대신 스토어의 리뷰 많은 대표 상품으로 오매칭되던 버그 차단.)
        if not product_id and store_name and store_name.lower() in item_link.lower():
            return True
        return False

    def _fill_from_item(item):
        """API 검색 결과에서 상품 정보 채우기"""
        result["product_name"] = re.sub(r'<[^>]+>', '', item.get("title", ""))
        result["image_url"] = item.get("image", "")
        result["price"] = int(item.get("lprice", 0) or 0)
        result["store_name"] = item.get("mallName", store_name) or store_name
        # 카테고리 채우기 (광고주 분석의 '주요카테고리' 공란 방지)
        if item.get("category1"):
            result["category1"] = item.get("category1", "")
            result["category2"] = item.get("category2", "")
            result["category3"] = item.get("category3", "")

    # ===== 1차: 추적 키워드로 네이버 쇼핑 API 검색 (1000위까지, 가장 빠르고 안정적) =====
    if keyword:
        try:
            total_checked = 0
            # 호출 다이어트(2026-07): 10페이지(1,000위) 사냥 → 3페이지(300위).
            # 300위 밖 상품은 아래 스토어명 폴백이 정보를 잡아주므로 실사용 영향 미미,
            # 검색 API 소모 상한은 호출당 11 → 4로 감소(일일 25,000 한도 보호).
            for page_start in [1, 101, 201]:
                api_result = search_naver_shopping_api(keyword, display=100, start=page_start, retry_on_429=True)
                items = api_result.get("items", [])
                if not items:
                    break
                total_checked += len(items)
                for item in items:
                    if _match_item(item):
                        _fill_from_item(item)
                        logger.info(f"상품 정보 키워드 검색 성공: '{keyword}' → {result['product_name'][:30]} (start={page_start})")
                        return result
            logger.info(f"상품 정보 키워드 검색 미매칭: '{keyword}' (검색 범위: {total_checked}건)")
        except Exception as e:
            logger.warning(f"상품 정보 키워드 검색 실패: {e}")

    # ===== 2차: 스토어명으로 네이버 쇼핑 API 검색 =====
    if not result["product_name"] and store_name and product_id:
        try:
            # 스토어명은 수집 키워드가 아님 — 온디맨드 큐에 넣지 않는다(수집 예산 보호)
            api_result = search_naver_shopping_api(store_name, display=100, retry_on_429=True, enqueue_on_miss=False)
            for item in api_result.get("items", []):
                if _match_item(item):
                    _fill_from_item(item)
                    logger.info(f"상품 정보 스토어 검색 성공: '{store_name}' → {result['product_name'][:30]}")
                    return result
        except Exception as e:
            logger.warning(f"상품 정보 스토어 검색 실패: {e}")

    # ===== 3차: 상품 페이지 직접 접근 (VPS에서 429 가능성 있지만 시도) =====
    if not result["product_name"]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9",
            }
            _assert_allowed_fetch_url(product_url)  # SSRF 가드
            resp = requests.get(product_url, headers=headers, timeout=5, allow_redirects=True)
            if resp.status_code == 200 and len(resp.text) > 500:
                og_title = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', resp.text)
                if not og_title:
                    og_title = re.search(r'content=["\']([^"\']+)["\']\s+property=["\']og:title["\']', resp.text)
                if og_title:
                    result["product_name"] = og_title.group(1).strip()
                    if " : " in result["product_name"]:
                        result["product_name"] = result["product_name"].split(" : ")[0].strip()

                og_image = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', resp.text)
                if not og_image:
                    og_image = re.search(r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']', resp.text)
                if og_image:
                    result["image_url"] = og_image.group(1).strip()

                og_price = re.search(r'<meta\s+property=["\']product:price:amount["\']\s+content=["\']([^"\']+)["\']', resp.text)
                if not og_price:
                    og_price = re.search(r'content=["\']([^"\']+)["\']\s+property=["\']product:price:amount["\']', resp.text)
                if og_price:
                    try:
                        result["price"] = int(float(og_price.group(1).replace(",", "")))
                    except (ValueError, TypeError):
                        pass

                og_site = re.search(r'<meta\s+property=["\']og:site_name["\']\s+content=["\']([^"\']+)["\']', resp.text)
                if not og_site:
                    og_site = re.search(r'content=["\']([^"\']+)["\']\s+property=["\']og:site_name["\']', resp.text)
                if og_site:
                    result["store_name"] = og_site.group(1).strip()

                if result["product_name"]:
                    logger.info(f"상품 정보 페이지 파싱 성공: {result['product_name'][:40]}")
                    return result
        except Exception as e:
            logger.warning(f"상품 페이지 직접 접근 실패: {e}")

    if not result["product_name"]:
        logger.warning(f"상품 정보 조회 최종 실패: {product_url}")

    return result


# ==================== 네이버 검색광고 API (키워드 볼륨) ====================

def _generate_searchad_signature(timestamp: str, method: str, uri: str) -> str:
    """검색광고 API HMAC-SHA256 서명 생성 (base64 인코딩)"""
    message = f"{timestamp}.{method}.{uri}"
    signature = hmac.new(
        SEARCHAD_SECRET_KEY.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(signature).decode('utf-8')


def get_keyword_volume(keywords: List[str]) -> List[Dict]:
    """
    네이버 검색광고 API로 키워드별 검색량 조회

    Returns: [
        {
            "keyword": "키워드",
            "monthlyPcQcCnt": PC 월간 검색수,
            "monthlyMobileQcCnt": 모바일 월간 검색수,
            "monthlyAvePcClkCnt": PC 평균 클릭수,
            "monthlyAveMobileClkCnt": 모바일 평균 클릭수,
            "plAvgDepth": 광고 평균 노출수,
            "compIdx": 경쟁 지수 (높음/중간/낮음),
        }
    ]
    """
    if not SEARCHAD_API_KEY or not SEARCHAD_SECRET_KEY or not SEARCHAD_CUSTOMER_ID:
        logger.warning("검색광고 API 키가 설정되지 않았습니다.")
        return []

    uri = "/keywordstool"
    method = "GET"
    timestamp = str(int(time.time() * 1000))
    signature = _generate_searchad_signature(timestamp, method, uri)

    url = f"https://api.searchad.naver.com{uri}"
    headers = {
        "X-Timestamp": timestamp,
        "X-API-KEY": SEARCHAD_API_KEY,
        "X-Customer": SEARCHAD_CUSTOMER_ID,
        "X-Signature": signature,
    }
    # ⚠️ keywordstool 은 hintKeywords 에 공백이 있으면 400 을 낸다(2026-08-05 실측:
    #    '구로동 고기' → 400 Bad Request 3회 재시도 전부 실패). 같은 검색광고 계열인
    #    get_bid_estimates 는 이미 공백을 지우고 있다 — 동일 규칙을 여기에도 맞춘다.
    #    단일 낱말 키워드(기존 스토어 경로)는 지울 공백이 없어 동작 100% 동일.
    #    응답의 keyword 는 네이버가 정규화해 돌려주므로 형식 변화 없음.
    params = {
        "hintKeywords": ",".join((k or "").strip().replace(" ", "") for k in keywords),
        "showDetail": "1",
    }

    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            # 429 Too Many Requests 전용 처리
            if response.status_code == 429:
                logger.warning(f"검색광고 API 429 Rate Limit — 즉시 건너뜀")
                return []
            response.raise_for_status()
            data = response.json()

            results = []
            keyword_data_list = data.get("keywordList", [])
            # ── 요청 키워드 매칭 (2026-08-05, 두 세션 수정 통합) ──
            # 요청은 위에서 공백을 지워 보내고 네이버도 공백 없는 형태(영문은 대문자)로
            # 돌려주는데, 필터가 원문 리스트(공백 포함)와 비교하고 있었다 → '구로동 고기'
            # 처럼 공백이 들어간 키워드는 응답이 와도 전부 걸러져 **항상 0건**(실측).
            #   · 지역+키워드를 합성하는 플레이스/제안서 경로는 늘 공백이 있어 100% 해당
            #   · 스토어 경로에서도 검색량·클릭수·경쟁지수·평균 광고 개수가 통째로 비어
            #     "숫자에 편차가 있다"는 신고로 나타났다(이예은 2026-08-05)
            # → 비교 축을 공백 제거 + 소문자로 맞추고(영문 대문자 응답까지 수용),
            #   결과 표기는 **사용자가 입력한 원문**으로 되돌린다(화면·저장·다운스트림
            #   매칭이 입력 그대로 유지되도록). 낱말 키워드는 지울 공백이 없어 무회귀.
            def _norm_kw(v):
                return "".join(str(v or "").split()).lower()
            _req_map = {}
            for _k in keywords:
                _req_map.setdefault(_norm_kw(_k), _k)
            for kd in keyword_data_list:
                rel_keyword = kd.get("relKeyword", "")
                _matched = _req_map.get(_norm_kw(rel_keyword))
                if _matched is not None:
                    rel_keyword = _matched   # 화면·저장은 사용자 입력 표기로 통일
                    results.append({
                        "keyword": rel_keyword,
                        "monthlyPcQcCnt": _safe_int(kd.get("monthlyPcQcCnt")),
                        "monthlyMobileQcCnt": _safe_int(kd.get("monthlyMobileQcCnt")),
                        "monthlyAvePcClkCnt": _safe_float(kd.get("monthlyAvePcClkCnt")),
                        "monthlyAveMobileClkCnt": _safe_float(kd.get("monthlyAveMobileClkCnt")),
                        "plAvgDepth": _safe_int(kd.get("plAvgDepth")),
                        "compIdx": kd.get("compIdx", ""),
                    })

            logger.info(f"키워드 볼륨 조회: {len(results)}/{len(keywords)}건")
            return results

        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                logger.warning(f"검색광고 API 재시도 ({attempt + 1}/{max_retries}): {e}")
                time.sleep(1.0 * (attempt + 1))
            else:
                logger.error(f"검색광고 API 요청 실패 (재시도 소진): {e}")
                return []


def get_keyword_ideas(seed: str, limit: int = 200) -> List[Dict]:
    """검색광고 keywordstool 의 **연관 키워드 원본** — 요청 키워드 필터를 걸지 않는다.

    `get_keyword_volume` 은 「내가 물어본 키워드」만 돌려주도록 응답을 거르는데,
    keywordstool 은 원래 씨앗 키워드에서 파생된 연관 키워드를 수백 개 함께 준다.
    그 목록 자체가 필요한 경로(플레이스 분석의 연관·황금 키워드)를 위한 별도 함수 —
    기존 함수의 필터 규약을 건드리지 않으려고 새로 뺀다(스토어 경로 무회귀).

    Returns: [{"keyword", "monthlyPcQcCnt", "monthlyMobileQcCnt", "compIdx", "plAvgDepth"}]
             — 실패·키 미설정 시 [](호출측이 그 카드를 생략).
    """
    kw = (seed or "").strip().replace(" ", "")
    if not kw:
        return []
    if not SEARCHAD_API_KEY or not SEARCHAD_SECRET_KEY or not SEARCHAD_CUSTOMER_ID:
        return []

    uri = "/keywordstool"
    timestamp = str(int(time.time() * 1000))
    try:
        resp = requests.get(
            f"https://api.searchad.naver.com{uri}",
            params={"hintKeywords": kw, "showDetail": "1"},
            headers={
                "X-Timestamp": timestamp,
                "X-API-KEY": SEARCHAD_API_KEY,
                "X-Customer": SEARCHAD_CUSTOMER_ID,
                "X-Signature": _generate_searchad_signature(timestamp, "GET", uri),
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning(f"연관 키워드 조회 응답 {resp.status_code} (씨앗 '{kw}')")
            return []
        rows = (resp.json() or {}).get("keywordList", []) or []
    except Exception as e:
        logger.warning(f"연관 키워드 조회 실패(무시): {e}")
        return []

    out = []
    for kd in rows[: max(1, int(limit))]:
        rel = (kd.get("relKeyword") or "").strip()
        if not rel:
            continue
        out.append({
            "keyword": rel,
            "monthlyPcQcCnt": _safe_int(kd.get("monthlyPcQcCnt")),
            "monthlyMobileQcCnt": _safe_int(kd.get("monthlyMobileQcCnt")),
            "compIdx": kd.get("compIdx", ""),
            "plAvgDepth": _safe_int(kd.get("plAvgDepth")),
        })
    logger.info(f"연관 키워드 조회: {len(out)}건 (씨앗 '{kw}')")
    return out


def _searchad_post(uri: str, body: dict) -> dict:
    """검색광고 API POST 호출(서명 인증) — 실패 시 {} (호출측 폴백)."""
    if not SEARCHAD_API_KEY or not SEARCHAD_SECRET_KEY or not SEARCHAD_CUSTOMER_ID:
        return {}
    try:
        timestamp = str(int(time.time() * 1000))
        headers = {
            "X-Timestamp": timestamp,
            "X-API-KEY": SEARCHAD_API_KEY,
            "X-Customer": SEARCHAD_CUSTOMER_ID,
            "X-Signature": _generate_searchad_signature(timestamp, "POST", uri),
            "Content-Type": "application/json",
        }
        resp = requests.post(f"https://api.searchad.naver.com{uri}", json=body, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"검색광고 API {uri} 응답 {resp.status_code}: {resp.text[:150]}")
            return {}
        return resp.json() or {}
    except Exception as e:
        logger.warning(f"검색광고 API {uri} 실패: {e}")
        return {}


def get_bid_estimates(keyword: str) -> Dict:
    """파워링크 순위(1~5위)별 평균 노출 입찰가 + 최소 노출 입찰가 (건의 2026-07-22, 이예은).

    네이버 검색광고 공식 '입찰가 추정' API — 광고시스템 콘솔의 '예상 입찰가'와 같은 소스.
    검색량 조회와 동일 자격증명(검색 Open API 25,000 쿼터와 별개 시스템).
    실패·데이터 없음 시 {} 반환 → 프론트는 신규 표를 렌더하지 않아 기존 화면과 동일(시안 B)."""
    kw = (keyword or "").strip().replace(" ", "")
    if not kw:
        return {}
    out = {"pc": [], "mobile": [], "minBid": {}}
    for device, key in (("PC", "pc"), ("MOBILE", "mobile")):
        data = _searchad_post(
            "/estimate/average-position-bid/keyword",
            {"device": device, "items": [{"key": kw, "position": p} for p in range(1, 6)]},
        )
        rows = []
        for it in (data.get("estimate") or []):
            try:
                pos = int(it.get("position"))
                bid = int(it.get("bid"))
                if 1 <= pos <= 5 and bid > 0:
                    rows.append({"position": pos, "bid": bid})
            except (TypeError, ValueError):
                continue
        out[key] = sorted(rows, key=lambda r: r["position"])

        mdata = _searchad_post(
            "/estimate/exposure-minimum-bid/keyword",
            {"device": device, "period": "MONTH", "items": [kw]},
        )
        try:
            mbid = int(((mdata.get("estimate") or [{}])[0]).get("bid") or 0)
            if mbid > 0:
                out["minBid"][key] = mbid
        except (TypeError, ValueError, IndexError):
            pass

    if not out["pc"] and not out["mobile"]:
        return {}  # 데이터 없음 — 신규 표 미표시(안전 폴백)
    return out


def _safe_int(val) -> int:
    """안전한 int 변환 (< 10 등 문자열 처리)"""
    if val is None:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        # "< 10" 같은 값 처리
        cleaned = re.sub(r'[^0-9]', '', val)
        return int(cleaned) if cleaned else 0
    return 0


def _safe_float(val) -> float:
    """안전한 float 변환"""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = re.sub(r'[^0-9.]', '', val)
        # 다중 소수점 방지: 첫 번째 소수점만 유지
        parts = cleaned.split('.')
        if len(parts) > 2:
            cleaned = parts[0] + '.' + ''.join(parts[1:])
        try:
            return float(cleaned) if cleaned else 0.0
        except ValueError:
            return 0.0
    return 0.0


# ==================== 분석 코멘트 생성 ====================

def generate_rank_analysis(current_rank: Optional[int], previous_rank: Optional[int],
                           competitors: List[Dict], product_info: Dict) -> str:
    """순위 변동 원인 분석 코멘트 자동 생성"""
    comments = []

    if current_rank is None:
        comments.append("현재 검색 결과 상위 200위 내에서 발견되지 않았습니다.")
        comments.append("💡 개선 제안: 상품명 키워드 최적화, 리뷰 수 확보, 가격 경쟁력 점검이 필요합니다.")
        comments.append("ℹ️ 참고: API 유사도순(sim) 기준이므로 실제 노출 순위와 다를 수 있습니다.")
        return " ".join(comments)

    # 순위 변동 분석
    if previous_rank is not None:
        diff = previous_rank - current_rank
        if diff > 0:
            comments.append(f"📈 순위가 {diff}단계 상승했습니다! (이전 {previous_rank}위 → 현재 {current_rank}위)")
        elif diff < 0:
            comments.append(f"📉 순위가 {abs(diff)}단계 하락했습니다. (이전 {previous_rank}위 → 현재 {current_rank}위)")
        else:
            comments.append(f"➡️ 순위 변동 없음 ({current_rank}위 유지)")
    else:
        comments.append(f"📍 현재 API 기준 {current_rank}위에 위치합니다.")

    # 경쟁 상품 대비 분석
    if competitors:
        prices = [c.get("price", 0) for c in competitors if c.get("price", 0) > 0]
        if prices:
            avg_price = sum(prices) / len(prices)
            my_price = product_info.get("price", 0)

            if my_price > 0 and avg_price > 0:
                price_diff_pct = ((my_price - avg_price) / avg_price) * 100
                if price_diff_pct > 15:
                    comments.append(f"⚠️ 가격이 상위 경쟁 상품 평균보다 {price_diff_pct:.0f}% 높습니다.")
                elif price_diff_pct < -15:
                    comments.append(f"✅ 가격 경쟁력이 우수합니다. (평균 대비 {abs(price_diff_pct):.0f}% 저렴)")

    # 순위별 피드백
    if current_rank <= 10:
        comments.append("🏆 상위 10위! 현재 전략을 유지하세요.")
    elif current_rank <= 40:
        comments.append("👍 상위권 위치. 리뷰 확보와 가격 전략으로 더 올릴 수 있습니다.")
    elif current_rank <= 100:
        comments.append("📊 중위권. 상품명 SEO 최적화와 가격 경쟁력 강화를 추천합니다.")
    elif current_rank <= 200:
        comments.append("⚡ 하위권. 키워드 재설정과 상세페이지 개선이 우선입니다.")

    comments.append("ℹ️ 네이버 공식 API 기준 순위이며, 실제 검색 노출 순위와 차이가 있을 수 있습니다.")
    return " ".join(comments)


# ==================== 상세페이지 크롤링 & 분석 ====================

def _get_realistic_headers(referer: str = "") -> Dict:
    """최신 Chrome 브라우저를 모방하는 현실적인 HTTP 헤더"""
    h = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    if referer:
        h["Referer"] = referer
        h["Sec-Fetch-Site"] = "same-origin"
    return h


def _extract_smartstore_info(product_url: str) -> Tuple[Optional[str], Optional[str]]:
    """스마트스토어 URL에서 store_name과 product_no 추출"""
    # https://smartstore.naver.com/{store_name}/products/{product_no}
    match = re.search(r'smartstore\.naver\.com/([^/]+)/products/(\d+)', product_url)
    if match:
        return match.group(1), match.group(2)
    # 브랜드스토어: brand.naver.com/{store}/products/{no}
    match = re.search(r'brand\.naver\.com/([^/]+)/products/(\d+)', product_url)
    if match:
        return match.group(1), match.group(2)
    return None, None


def _extract_next_data_html(raw_html: str, product_url: str = "") -> Optional[str]:
    """
    스마트스토어 HTML의 <script id="__NEXT_DATA__"> 에서 상품 JSON을 추출하여
    분석 가능한 HTML로 변환. 429/200 상관없이 __NEXT_DATA__가 있으면 실제 상품 페이지.
    """
    import json as _json
    match = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw_html, re.DOTALL)
    if not match:
        return None
    try:
        next_data = _json.loads(match.group(1))
    except Exception:
        return None

    # props.pageProps 안에 상품 데이터가 있음
    page_props = next_data.get("props", {}).get("pageProps", {})
    if not page_props:
        return None

    # 여러 가능한 키에서 상품 정보 추출
    product = page_props.get("product", {}) or page_props.get("productDetail", {}) or {}
    if not product and "initialState" in page_props:
        # 일부 버전에서는 initialState.product
        product = page_props.get("initialState", {}).get("product", {}) or {}

    # 상품명
    name = product.get("name", "") or page_props.get("product", {}).get("name", "")
    if not name:
        # 상품 데이터가 없으면 rate-limit 페이지
        logger.info("__NEXT_DATA__ 있지만 상품 정보 없음 — rate-limit 페이지일 수 있음")
        return None

    # 상품 이미지
    images = product.get("productImages", []) or []
    img_tags = ""
    for img in images:
        url = img.get("url", "") if isinstance(img, dict) else str(img)
        if url:
            if not url.startswith("http"):
                url = f"https:{url}" if url.startswith("//") else url
            img_tags += f'<img src="{url}" class="product-image">\n'

    # 대표 이미지 추가
    representative = product.get("representImage", {})
    if isinstance(representative, dict) and representative.get("url"):
        rep_url = representative["url"]
        if not rep_url.startswith("http"):
            rep_url = f"https:{rep_url}" if rep_url.startswith("//") else rep_url
        img_tags = f'<img src="{rep_url}" class="product-image">\n' + img_tags

    # 상세 설명 (HTML)
    detail_html = ""
    detail_content = product.get("detailContents", {})
    if isinstance(detail_content, dict):
        detail_html = detail_content.get("detailContentText", "") or detail_content.get("editorContent", "") or ""
    elif isinstance(detail_content, str):
        detail_html = detail_content

    # 옵션/스펙
    options = product.get("optionCombinations", []) or product.get("options", {}).get("optionCombinations", [])
    spec_html = ""
    if options:
        spec_html = '<table class="spec-table"><tr><th>옵션</th><th>사양</th></tr>'
        for opt in options[:20]:
            opt_name = opt.get("optionName1", "") or opt.get("name", "")
            opt_val = opt.get("optionName2", "") or str(opt.get("price", ""))
            spec_html += f"<tr><td>{opt_name}</td><td>{opt_val}</td></tr>"
        spec_html += "</table>"

    # 배송
    delivery = product.get("delivery", {}) or page_props.get("delivery", {}) or {}
    delivery_html = ""
    if delivery:
        fee_info = delivery.get("deliveryFee", {})
        if isinstance(fee_info, dict):
            base_fee = fee_info.get("baseFee", -1)
            if base_fee == 0:
                delivery_html += '<span>무료배송</span> '
        if delivery.get("todayDispatch"):
            delivery_html += '<span>당일출고</span> '
        if delivery.get("quickDelivery"):
            delivery_html += '<span>오늘출발</span>'

    # 교환/반품
    after_service = product.get("afterServiceInfo", {}) or {}
    return_html = ""
    if after_service:
        guide = after_service.get("afterServiceGuideContent", "")
        if guide:
            return_html = f'<div class="return-info">교환/반품 안내: {guide}</div>'

    # 인증
    certs = product.get("certifications", []) or []
    cert_html = ""
    for c in certs:
        cn = c.get("name", "") if isinstance(c, dict) else str(c)
        if cn:
            cert_html += f'<span class="certification">{cn} 인증</span> '

    # 리뷰 수 / 평점 / 찜수 — __NEXT_DATA__ JSON에서 정확한 값 추출
    review_data = page_props.get("reviewAmount", {}) or product.get("reviewAmount", {}) or {}
    review_count = review_data.get("totalReviewCount", 0) if isinstance(review_data, dict) else 0
    review_score = review_data.get("averageReviewScore", 0) if isinstance(review_data, dict) else 0
    wish_count = page_props.get("wishCount", 0) or product.get("wishCount", 0)

    # 판매가 — __NEXT_DATA__ JSON에서 추출해 합성 HTML에 보존(주 크롤 경로 가격 유실 방지)
    try:
        _price_raw = (product.get("discountedSalePrice") or product.get("salePrice") or product.get("dispSalePrice")
                      or page_props.get("discountedSalePrice") or page_props.get("salePrice") or 0)
        price_val = int(float(_price_raw) or 0)
    except Exception:
        price_val = 0

    # 카테고리
    category = product.get("category", {}) or {}
    cat_name = category.get("wholeCategoryName", "") or ""

    # 태그
    tags = product.get("seoInfo", {}).get("sellerTags", []) or []
    tag_html = " ".join([f'#{t.get("text", "")}' for t in tags if isinstance(t, dict)])

    # HTML 조립 — 메타 태그로 정확한 API 값 보존 (후속 추출에서 최우선 사용)
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head><title>{name}</title>
<meta name="api-review-count" content="{review_count}">
<meta name="api-review-score" content="{review_score}">
<meta name="api-wish-count" content="{wish_count}">
<meta name="api-price" content="{price_val}">
</head>
<body>
<div class="product-detail">
  <h1>{name}</h1>
  {f'<div class="category">{cat_name}</div>' if cat_name else ''}
  <div class="product-images">{img_tags}</div>
  <div class="delivery-section">{delivery_html}</div>
  {f'<div class="return-section">{return_html}</div>' if return_html else ''}
  {spec_html}
  {f'<div class="certification-section">{cert_html}</div>' if cert_html else ''}
  {f'<div class="review-section">구매후기 {review_count}건</div>' if review_count > 0 else ''}
  {f'<div class="tag-section">{tag_html}</div>' if tag_html else ''}
  <div class="detail_content" id="product_detail">
    {detail_html}
  </div>
</div>
</body>
</html>"""
    logger.info(f"__NEXT_DATA__ → HTML 변환 완료: 이미지 {len(images)}장, 텍스트 {len(detail_html)}자, 리뷰 {review_count}건")
    return html


def _fetch_smartstore_api(product_url: str) -> Optional[str]:
    """
    스마트스토어 내부 API로 상품 상세 정보 가져오기 (JSON → 가상 HTML 변환)
    네이버 차단 우회: API 엔드포인트는 HTML 페이지보다 차단이 느슨함
    """
    store_name, product_no = _extract_smartstore_info(product_url)
    if not store_name or not product_no:
        logger.info(f"스마트스토어 URL 아님, API 스킵: {product_url[:60]}")
        return None

    # 스마트스토어 내부 API 엔드포인트들
    api_endpoints = [
        f"https://smartstore.naver.com/i/v1/stores/{store_name}/products/{product_no}",
        f"https://m.smartstore.naver.com/i/v1/stores/{store_name}/products/{product_no}",
    ]

    api_headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-S908B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": f"https://smartstore.naver.com/{store_name}/products/{product_no}",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    for endpoint in api_endpoints:
        try:
            logger.info(f"스마트스토어 API 시도: {endpoint[:80]}")
            resp = requests.get(endpoint, headers=api_headers, timeout=15)
            logger.info(f"스마트스토어 API 응답: status={resp.status_code}, len={len(resp.text)}")
            if resp.status_code == 200 and len(resp.text) > 500:
                data = resp.json()
                html = _convert_smartstore_json_to_html(data, product_url)
                if html and len(html) > 500:
                    logger.info(f"스마트스토어 API 성공: JSON→HTML {len(html)}자")
                    return html
        except Exception as e:
            logger.warning(f"스마트스토어 API 실패 ({endpoint[:50]}): {e}")
    return None


def _convert_smartstore_json_to_html(data: Dict, product_url: str = "") -> Optional[str]:
    """스마트스토어 JSON 응답을 분석 가능한 HTML로 변환"""
    try:
        # 상품 기본 정보
        channel = data.get("channel", {})
        product = data.get("product", {}) or data.get("contents", {})
        name = data.get("name", "") or product.get("name", "")

        # 상세 설명 HTML
        detail_html = ""
        detail_content = data.get("detailContents", {}) or product.get("detailContents", {})
        if isinstance(detail_content, dict):
            detail_html = detail_content.get("detailContentText", "") or detail_content.get("editorContent", "") or ""
        elif isinstance(detail_content, str):
            detail_html = detail_content

        # 상품 이미지
        images = data.get("productImages", []) or product.get("productImages", [])
        img_tags = ""
        for img in images:
            url = img.get("url", "") if isinstance(img, dict) else str(img)
            if url:
                if not url.startswith("http"):
                    url = f"https:{url}" if url.startswith("//") else f"https://shop-phinf.pstatic.net{url}"
                img_tags += f'<img src="{url}" class="product-image">\n'

        # 옵션/스펙 정보
        options = data.get("optionCombinations", []) or data.get("options", [])
        spec_html = ""
        if options:
            spec_html = '<table class="spec-table"><tr><th>옵션</th><th>가격</th></tr>'
            for opt in options[:20]:
                opt_name = opt.get("optionName1", "") or opt.get("name", "")
                opt_price = opt.get("price", "")
                spec_html += f"<tr><td>{opt_name}</td><td>{opt_price}</td></tr>"
            spec_html += "</table>"

        # 배송 정보
        delivery = data.get("delivery", {}) or {}
        delivery_html = ""
        if delivery:
            fee = delivery.get("deliveryFee", {})
            if isinstance(fee, dict) and fee.get("baseFee", 0) == 0:
                delivery_html += '<span class="delivery-info">무료배송</span> '
            delivery_type = delivery.get("deliveryType", "")
            if delivery_type:
                delivery_html += f'<span class="delivery-type">{delivery_type}</span> '
            today_dispatch = delivery.get("todayDispatch", False)
            if today_dispatch:
                delivery_html += '<span class="delivery-today">당일출고</span>'

        # 반품/교환 정보
        after_service = data.get("afterServiceInfo", {}) or {}
        return_html = ""
        if after_service:
            return_policy = after_service.get("afterServiceTelephoneNumber", "")
            return_guide = after_service.get("afterServiceGuideContent", "")
            if return_guide:
                return_html = f'<div class="return-info">교환/반품 안내: {return_guide}</div>'

        # 인증 정보
        certifications = data.get("certifications", []) or data.get("seoInfo", {}).get("certifications", [])
        cert_html = ""
        if certifications:
            for cert in certifications:
                cert_name = cert.get("name", "") if isinstance(cert, dict) else str(cert)
                cert_html += f'<span class="certification">{cert_name} 인증</span> '

        # 리뷰 수 / 평점 / 찜수 — API JSON에서 정확한 값 추출
        review_amount = data.get("reviewAmount", {})
        review_count = review_amount.get("totalReviewCount", 0) if isinstance(review_amount, dict) else 0
        review_score = review_amount.get("averageReviewScore", 0) if isinstance(review_amount, dict) else 0
        wish_count = data.get("wishCount", 0) or product.get("wishCount", 0)

        # 판매가 — API JSON에서 추출해 합성 HTML에 보존(가격 유실 방지)
        try:
            _price_raw = (data.get("discountedSalePrice") or data.get("salePrice") or data.get("dispSalePrice")
                          or product.get("discountedSalePrice") or product.get("salePrice") or 0)
            price_val = int(float(_price_raw) or 0)
        except Exception:
            price_val = 0

        # HTML 조립 — 메타 태그로 정확한 API 값 보존 (후속 추출에서 최우선 사용)
        html = f"""<!DOCTYPE html>
<html lang="ko">
<head><title>{name}</title>
<meta name="api-review-count" content="{review_count}">
<meta name="api-review-score" content="{review_score}">
<meta name="api-wish-count" content="{wish_count}">
<meta name="api-price" content="{price_val}">
</head>
<body>
<div class="product-detail">
  <h1>{name}</h1>
  <div class="product-images">{img_tags}</div>
  <div class="delivery-section">{delivery_html}</div>
  {f'<div class="return-section">{return_html}</div>' if return_html else ''}
  {spec_html}
  {f'<div class="certification-section">{cert_html}</div>' if cert_html else ''}
  {f'<div class="review-section">구매후기 {review_count}건</div>' if review_count > 0 else ''}
  <div class="detail_content" id="product_detail">
    {detail_html}
  </div>
</div>
</body>
</html>"""
        return html
    except Exception as e:
        logger.warning(f"JSON→HTML 변환 실패: {e}")
        return None


def _fetch_via_scrapingbee(target_url: str, render_js: bool = False, stealth: bool = False) -> Optional[str]:
    """
    ScrapingBee API로 페이지 가져오기 (주 수단)
    - 한국 IP 지원
    - 자동 프록시 로테이션
    - 선택적 JS 렌더링
    - transparent_status_code=True로 실제 응답 수용
    """
    if not SCRAPINGBEE_API_KEY:
        return None
    try:
        params = {
            "api_key": SCRAPINGBEE_API_KEY,
            "url": target_url,
            "render_js": "true" if render_js else "false",
            "block_resources": "false",
            "country_code": "kr",
            "transparent_status_code": "true",  # ScrapingBee가 500 덮어쓰지 않도록
        }
        if stealth:
            params["stealth_proxy"] = "true"  # 가장 강력한 우회 모드 (75 credits)
        else:
            params["premium_proxy"] = "true"  # 25 credits

        logger.info(f"ScrapingBee 요청: {target_url[:60]}... render_js={render_js}, stealth={stealth}")
        resp = requests.get(SCRAPINGBEE_API_URL, params=params, timeout=120)

        # ScrapingBee 에러/크레딧 헤더 확인
        sb_err = resp.headers.get("Spb-error-code") or resp.headers.get("Spb-error")
        sb_cost = resp.headers.get("Spb-cost")
        sb_credit_remaining = resp.headers.get("Spb-remaining-api-calls") or resp.headers.get("Spb-remaining-calls")
        if sb_credit_remaining:
            logger.info(f"ScrapingBee 남은 크레딧: {sb_credit_remaining}, 이번 비용: {sb_cost}")

        # HTML 본문이 충분하면 수용 (status와 무관)
        if len(resp.text) > 1000 and "<html" in resp.text.lower():
            logger.info(f"ScrapingBee 응답 수용: status={resp.status_code}, {len(resp.text)}자")
            return resp.text
        else:
            logger.warning(f"ScrapingBee 응답 비정상: status={resp.status_code}, len={len(resp.text)}, err={sb_err}, body={resp.text[:300]}")
    except Exception as e:
        logger.warning(f"ScrapingBee 요청 실패: {e}")
    return None


def _fetch_via_brd_api(target_url: str) -> Optional[str]:
    """Bright Data Web Unlocker API로 페이지 가져오기"""
    if not BRD_API_KEY or not BRD_API_URL:
        return None
    try:
        api_headers = {
            "Authorization": f"Bearer {BRD_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "zone": BRD_API_ZONE or "naver_logic",
            "url": target_url,
            "format": "raw",
            "method": "GET",
            "country": "kr",
        }
        logger.info(f"Bright Data API 요청: {target_url[:60]}... zone={payload['zone']}")
        resp = requests.post(BRD_API_URL, json=payload, headers=api_headers, timeout=60)
        # 응답 헤더에서 Bright Data 에러 확인
        brd_err = resp.headers.get("x-brd-err-code") or resp.headers.get("x-brd-error-code")
        brd_err_msg = resp.headers.get("x-brd-err-msg") or ""
        if brd_err:
            logger.warning(f"Bright Data 에러: code={brd_err}, msg={brd_err_msg}")
        if resp.status_code == 200 and len(resp.text) > 1000:
            logger.info(f"Bright Data API 성공: {len(resp.text)}자")
            return resp.text
        else:
            logger.warning(f"Bright Data API 응답 비정상: status={resp.status_code}, len={len(resp.text)}, headers={dict(resp.headers)}, body={resp.text[:300]}")
    except Exception as e:
        logger.warning(f"Bright Data API 요청 실패: {e}")
    return None


def fetch_detail_page_html(product_url: str) -> Optional[str]:
    """
    스마트스토어/네이버 상품 상세페이지 HTML 가져오기
    1차: ScrapingBee (주 수단, 한국 IP + premium proxy)
    2차: ScrapingBee JS 렌더링 (일반 모드 실패 시)
    3차: 스마트스토어 내부 JSON API
    4차: 향상된 직접 요청
    5차: Bright Data (fallback)
    """
    # SSRF 가드: 네이버 계열만 허용 (ScrapingBee/BRD 경유로 내부망 fetch 방지)
    if not is_allowed_fetch_url(product_url):
        logger.warning(f"[SSRF차단] 허용되지 않은 URL: {product_url[:80]}")
        return None

    # 1차: ScrapingBee premium (기본, 25 credits, transparent_status_code로 429도 수용)
    html = _fetch_via_scrapingbee(product_url, render_js=False, stealth=False)
    if html:
        next_data_html = _extract_next_data_html(html, product_url)
        if next_data_html:
            logger.info("ScrapingBee 결과에서 __NEXT_DATA__ 추출 성공")
            return next_data_html
        if "<html" in html.lower() and len(html) > 5000:
            return html

    # 2차: ScrapingBee stealth (75 credits, 가장 강력한 우회)
    html = _fetch_via_scrapingbee(product_url, render_js=False, stealth=True)
    if html:
        next_data_html = _extract_next_data_html(html, product_url)
        if next_data_html:
            return next_data_html
        if "<html" in html.lower() and len(html) > 5000:
            return html

    # 3차: ScrapingBee stealth + JS 렌더링 (80 credits, 최후의 수단)
    html = _fetch_via_scrapingbee(product_url, render_js=True, stealth=True)
    if html:
        next_data_html = _extract_next_data_html(html, product_url)
        if next_data_html:
            return next_data_html
        if "<html" in html.lower() and len(html) > 5000:
            return html

    # 3차: 스마트스토어 내부 JSON API
    html = _fetch_smartstore_api(product_url)
    if html:
        return html

    # 4차: 향상된 직접 요청
    headers = _get_realistic_headers(referer="https://search.shopping.naver.com/")
    try:
        logger.info(f"향상된 직접 요청 시도: {product_url[:60]}...")
        _assert_allowed_fetch_url(product_url)  # SSRF 가드
        with requests.Session() as session:  # 누수 방지: 컨텍스트 매니저로 자동 close
            session.headers.update(headers)
            resp = session.get(product_url, timeout=15, allow_redirects=True)

            if len(resp.text) > 1000:
                next_data_html = _extract_next_data_html(resp.text, product_url)
                if next_data_html:
                    logger.info(f"__NEXT_DATA__ 파싱 성공: {len(next_data_html)}자")
                    return next_data_html
                if resp.status_code == 200:
                    logger.info(f"향상된 직접 요청 성공: {len(resp.text)}자")
                    return resp.text
                else:
                    logger.warning(f"향상된 직접 요청: status={resp.status_code}, __NEXT_DATA__ 없음")
            else:
                logger.warning(f"향상된 직접 요청 실패: status={resp.status_code}, len={len(resp.text)}")
    except Exception as e:
        logger.warning(f"향상된 직접 요청 실패: {e}")

    # 5차: Bright Data API (fallback)
    html = _fetch_via_brd_api(product_url)
    if html:
        return html

    return None


# ==================== 찜 수 API 조회 ====================

# 찜수 회로차단기 (B2): 스마트스토어 상품페이지 스크래핑은 서버 IP에서 거의 항상
# 429로 막힌다(값도 못 얻으면서 부하·로그만 유발). 연속 429가 임계치를 넘으면
# 일정 시간 호출 자체를 멈춘다. 한 번이라도 정상 응답(200)을 받으면 카운터 초기화.
_WISH_BREAKER = {"fails": 0, "open_until": 0.0}
_WISH_BREAKER_THRESHOLD = 5     # 연속 429 5회 → 차단
_WISH_BREAKER_COOLDOWN = 600    # 600초(10분)간 호출 중단


def _fetch_wish_count_from_api(product_url: str) -> Optional[int]:
    """
    상품 URL에서 찜 수를 네이버 내부 API로 조회.
    SmartStore 상품 페이지를 서버에서 fetch하여 __PRELOADED_STATE__ 또는
    JSON 내 wishCount를 추출한다. 실패 시 None 반환.
    비용: 없음 (일반 HTTP 요청)
    """
    if not product_url:
        return None

    # 회로 열림(쿨다운) 상태면 네이버를 더 두드리지 않고 즉시 None
    if time.time() < _WISH_BREAKER["open_until"]:
        return None

    try:
        # 1) SmartStore URL에서 스토어명과 상품번호 추출
        m = re.search(r'smartstore\.naver\.com/([^/]+)/products/(\d+)', product_url)
        if not m:
            # 네이버 쇼핑 URL에서 product ID 추출 시도
            m2 = re.search(r'shopping\.naver\.com/.*?(\d{10,})', product_url)
            if not m2:
                return None
            # 네이버 쇼핑 URL은 직접 조회 불가
            return None

        store_name = m.group(1)
        product_no = m.group(2)

        # 2) SmartStore 상품 페이지를 서버에서 fetch
        url = f"https://smartstore.naver.com/{store_name}/products/{product_no}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'ko-KR,ko;q=0.9',
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        resp.raise_for_status()
        page_html = resp.text
        _WISH_BREAKER["fails"] = 0  # 정상 응답 → 연속 429 카운터 초기화

        # 3) __PRELOADED_STATE__ 에서 wishCount 검색
        state_m = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?})\s*;?\s*</script>', page_html, re.DOTALL)
        if state_m:
            import json as _json
            try:
                state = _json.loads(state_m.group(1))
                # 재귀 탐색
                def _find(obj, depth=0):
                    if depth > 6 or not isinstance(obj, dict):
                        return None
                    for k, v in obj.items():
                        kl = k.lower()
                        if kl in ('wishcount', 'zzimcount', 'keepcount', 'wishlistcount'):
                            try:
                                val = int(v)
                                if val >= 0:
                                    return val
                            except (ValueError, TypeError):
                                pass
                        if isinstance(v, dict):
                            r = _find(v, depth + 1)
                            if r is not None:
                                return r
                    return None
                wc = _find(state)
                if wc is not None:
                    logger.info(f"[찜수API] PRELOADED_STATE에서 찜수={wc} 추출 (store={store_name})")
                    return wc
            except Exception:
                pass

        # 4) raw HTML에서 JSON 키로 검색 (폴백)
        for fm in re.finditer(r'"(?:wishCount|zzimCount|keepCount)"\s*:\s*(\d+)', page_html):
            val = int(fm.group(1))
            if val >= 0:
                logger.info(f"[찜수API] raw JSON에서 찜수={val} 추출 (store={store_name})")
                return val

        logger.info(f"[찜수API] 찜수 추출 실패 (store={store_name}, product={product_no})")
        return None

    except Exception as e:
        # 429(레이트리밋) 연속 발생 시 회로 차단 → 쿨다운 동안 호출 중단
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 429:
            _WISH_BREAKER["fails"] += 1
            if _WISH_BREAKER["fails"] >= _WISH_BREAKER_THRESHOLD:
                _WISH_BREAKER["open_until"] = time.time() + _WISH_BREAKER_COOLDOWN
                _WISH_BREAKER["fails"] = 0
                logger.warning(f"[찜수API] 연속 429 {_WISH_BREAKER_THRESHOLD}회 → {_WISH_BREAKER_COOLDOWN // 60}분간 호출 중단(회로 차단)")
        logger.warning(f"[찜수API] 요청 실패: {e}")
        return None


# ==================== 리뷰 텍스트 추출 & 분석 ====================

_POSITIVE_KW = [
    '맛있', '달콤', '신선', '좋아', '만족', '추천', '깔끔', '재구매', '또 사', '또사',
    '감사', '훌륭', '최고', '완벽', '빠르', '맛나', '고소', '달달', '사랑', '행복',
    '감동', '대박', '넉넉', '든든', '알찬', '탱글', '촉촉', '부드러', '예쁘', '좋은',
    '잘 먹', '잘먹', '굿', '최상', '프리미엄', '고급', '두번째', '세번째',
]
_NEGATIVE_KW = [
    '건조', '상한', '작은', '비싸', '불만', '실망', '별로', '느리', '부족', '딱딱',
    '시큼', '못생', '파손', '상처', '곰팡이', '물러', '썩은', '찌그러', '깨진', '적은',
    '양이', '냄새', '변색', '문제', '환불', '교환', '짜증', '후회', '아쉬', '아깝',
]

# 부정 의미를 무효화하는 표현(부정 키워드 직후에 오면 오히려 긍정/중립)
_NEG_CANCEL_MARKERS = ('없', '않', '아니', '제거', '방지')
# 부정 키워드가 포함되어도 부정이 아닌 복합어(상품 특성/긍정 맥락)
_NEG_FALSE_COMPOUNDS = ('반건조', '건조기', '건조과일', '건조방식', '건조과정', '냄새제거', '냄새방지')


def _neg_keyword_hit(text: str, kw: str) -> bool:
    """맥락을 고려해 kw가 '진짜 부정'으로 쓰였는지 판정.
    - '반건조'처럼 상품 특성 복합어는 제외
    - '냄새없음 / 냄새 안 나요'처럼 부정어가 취소된 경우 제외
    (네이버 리뷰 맥락 오인식 #6 대응)"""
    idx = text.find(kw)
    while idx >= 0:
        ctx = text[max(0, idx - 2): idx + len(kw) + 2]
        if not any(fc in ctx for fc in _NEG_FALSE_COMPOUNDS):
            after = text[idx + len(kw): idx + len(kw) + 5]
            if not any(m in after for m in _NEG_CANCEL_MARKERS):
                return True  # 취소/복합어가 아닌 진짜 부정 출현
        idx = text.find(kw, idx + len(kw))
    return False


def _negative_hits(text: str) -> int:
    """맥락 고려 부정 키워드 종류 수 (감성 분류용)."""
    return sum(1 for kw in _NEGATIVE_KW if _neg_keyword_hit(text, kw))


def _extract_reviews(soup, html: str) -> list:
    """HTML에서 개별 구매자 리뷰 추출 (스마트스토어 상품 페이지)"""
    reviews = []
    seen_texts = set()  # 중복 방지

    # ── 방법 1: BeautifulSoup — blind '평점' 스팬 기반 ──
    for blind_span in soup.find_all('span', class_='blind'):
        blind_text = blind_span.get_text(strip=True).replace(' ', '')
        if '평점' not in blind_text:
            continue

        # 평점 추출: 부모의 직접 텍스트에서 숫자 추출
        parent = blind_span.parent
        if not parent:
            continue
        parent_text = parent.get_text(strip=True).replace(' ', '')
        rating_m = re.search(r'평점(\d)', parent_text)
        if not rating_m:
            continue
        rating = int(rating_m.group(1))
        if rating < 1 or rating > 5:
            continue

        # 리뷰 아이템 컨테이너 찾기 (li > button 구조)
        item = blind_span
        for _ in range(15):
            item = item.parent
            if not item:
                break
            if item.name == 'li':
                break
        if not item or item.name != 'li':
            continue

        # 모든 하위 span에서 태그와 리뷰 텍스트 추출
        tags = []
        review_text = ''
        for span in item.find_all('span'):
            if 'blind' in (span.get('class') or []):
                continue
            # 자식 span이 3개 이상이면 래퍼 → 건너뜀
            if len(span.find_all('span')) >= 3:
                continue
            text = span.get_text(strip=True).replace('\xa0', ' ')
            if not text or text.isdigit() or len(text) < 2:
                continue
            text_clean = text.replace(' ', '')
            if text_clean in ('평점', '이상품찜하기', '원가', '할인율', '판매가'):
                continue
            # "평점N" 패턴 필터 (예: "평점5", "평 점 5")
            if re.match(r'^평\s*점\s*\d$', text):
                continue
            if 2 <= len(text) <= 12 and len(text) < 13:
                if text not in tags:
                    tags.append(text)
            elif len(text) > 15 and len(text) > len(review_text):
                review_text = text

        if review_text and len(review_text) > 5:
            text_key = review_text[:50]
            if text_key not in seen_texts:
                seen_texts.add(text_key)
                # 감성 분류
                pos = sum(1 for kw in _POSITIVE_KW if kw in review_text)
                neg = _negative_hits(review_text)
                sentiment = 'negative' if neg > pos else ('positive' if pos > 0 else 'neutral')
                reviews.append({
                    'rating': rating,
                    'tags': tags[:5],
                    'text': review_text[:500],
                    'sentiment': sentiment,
                    'charCount': len(review_text),
                })

    # ── 방법 2: Regex 폴백 (BeautifulSoup 실패 시) ──
    if not reviews:
        page_text = soup.get_text(separator='|', strip=True) if soup else ''
        for m in re.finditer(
            r'>평\s*점\s*</span>\s*(\d)'
            r'(.*?)'
            r'</(?:button|li)>',
            html, re.DOTALL
        ):
            rating = int(m.group(1))
            block = m.group(2)
            # 블록에서 태그 제거하여 텍스트 추출
            block_text = re.sub(r'<[^>]+>', ' ', block)
            block_text = re.sub(r'\s+', ' ', block_text).strip()
            if len(block_text) < 10:
                continue
            # 짧은 토큰 = 태그, 긴 텍스트 = 리뷰
            parts = [p.strip() for p in block_text.split('  ') if p.strip()]
            tags = [p for p in parts if 2 <= len(p) <= 12][:5]
            long_parts = [p for p in parts if len(p) > 15]
            review_text = max(long_parts, key=len) if long_parts else block_text
            if len(review_text) > 5:
                text_key = review_text[:50]
                if text_key not in seen_texts:
                    seen_texts.add(text_key)
                    pos = sum(1 for kw in _POSITIVE_KW if kw in review_text)
                    neg = _negative_hits(review_text)
                    sentiment = 'negative' if neg > pos else ('positive' if pos > 0 else 'neutral')
                    reviews.append({
                        'rating': rating,
                        'tags': tags,
                        'text': review_text[:500],
                        'sentiment': sentiment,
                        'charCount': len(review_text),
                    })

    return reviews


def _analyze_reviews(reviews: list) -> dict:
    """추출된 리뷰 목록을 분석 (키워드, 감성, 태그 통계)"""
    if not reviews:
        return None

    total = len(reviews)
    avg_rating = round(sum(r['rating'] for r in reviews) / total, 1) if total else 0
    avg_chars = round(sum(r['charCount'] for r in reviews) / total) if total else 0

    # 감성 통계
    pos_count = sum(1 for r in reviews if r['sentiment'] == 'positive')
    neg_count = sum(1 for r in reviews if r['sentiment'] == 'negative')
    neu_count = total - pos_count - neg_count
    pos_ratio = round(pos_count / total * 100) if total else 0

    # 키워드 빈도 분석
    pos_kw_counts = {}
    neg_kw_counts = {}
    for r in reviews:
        text = r['text']
        for kw in _POSITIVE_KW:
            if kw in text:
                pos_kw_counts[kw] = pos_kw_counts.get(kw, 0) + 1
        for kw in _NEGATIVE_KW:
            if _neg_keyword_hit(text, kw):
                neg_kw_counts[kw] = neg_kw_counts.get(kw, 0) + 1

    positive_keywords = sorted(pos_kw_counts.items(), key=lambda x: -x[1])[:10]
    negative_keywords = sorted(neg_kw_counts.items(), key=lambda x: -x[1])[:10]

    # 태그 빈도 분석
    tag_counts = {}
    for r in reviews:
        for tag in r.get('tags', []):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    tag_stats = sorted(tag_counts.items(), key=lambda x: -x[1])[:10]

    # AI 인사이트 생성
    insights = []
    if positive_keywords:
        top_pos = ', '.join(f'"{kw}"' for kw, _ in positive_keywords[:3])
        insights.append(f'핵심 강점: {top_pos} 키워드가 자주 언급됩니다. 상세페이지에서 이 키워드를 더 강조하세요.')
    if negative_keywords:
        top_neg = ', '.join(f'"{kw}"' for kw, _ in negative_keywords[:3])
        insights.append(f'개선 포인트: {top_neg} 관련 부정 언급이 있습니다. 상품 설명에 이에 대한 안내를 추가하세요.')
    reorder_kws = ['재구매', '또 사', '또사', '두번째', '세번째']
    reorder_count = sum(1 for r in reviews if any(kw in r['text'] for kw in reorder_kws))
    if reorder_count > 0:
        insights.append(f'재구매 의향: {reorder_count}건의 리뷰에서 재구매 언급 — 리뷰 이벤트로 이런 후기를 더 유도하세요.')
    if avg_chars > 50:
        insights.append(f'리뷰 품질: 평균 {avg_chars}자 — 상세 리뷰가 많아 신뢰도 높음. 포토리뷰 유도 시 전환율 상승 기대.')
    elif avg_chars < 20:
        insights.append(f'리뷰 품질: 평균 {avg_chars}자로 짧은 편 — 포토/텍스트 리뷰 이벤트로 상세 후기를 유도하세요.')

    return {
        'totalExtracted': total,
        'avgRating': avg_rating,
        'avgChars': avg_chars,
        'sentiment': {
            'positive': pos_count,
            'negative': neg_count,
            'neutral': neu_count,
            'positiveRatio': pos_ratio,
        },
        'positiveKeywords': [{'keyword': kw, 'count': cnt} for kw, cnt in positive_keywords],
        'negativeKeywords': [{'keyword': kw, 'count': cnt} for kw, cnt in negative_keywords],
        'tagStats': [{'tag': tag, 'count': cnt} for tag, cnt in tag_stats],
        'insights': insights,
    }


def extract_store_display_name(html: str, product_url: str = "") -> Dict:
    """상세페이지 HTML에서 '표시용' 스토어/상호명을 추출한다 (2026-07-27).

    배경: get_product_info 는 쇼핑 API 매칭·상품페이지 방문이 모두 실패하면
    store_name 을 URL 슬러그로 남긴다. 슬러그가 이메일 아이디인 업체가 있어
    보고서 표지에 'chajju2009' 처럼 엉뚱한 값이 찍히는 신고가 있었다.
    직원이 붙여넣는 상세 HTML에는 실제 상호명이 들어 있으므로 여기서 뽑는다.

    ⚠️ 슬러그는 순위 매칭 키로 계속 쓰이므로 이 함수는 '표시용'만 반환하며,
       기존 store_name/매칭 로직은 건드리지 않는다.
    반환: {"name": str, "source": str}  — 못 찾으면 name=""
    """
    if not html:
        return {"name": "", "source": ""}

    slug = (extract_store_name_from_url(product_url) or "").strip().lower()
    # 스토어명으로 볼 수 없는 일반 문구(플랫폼명 등)
    # 공백을 제거한 형태로 비교한다("네이버 스마트스토어" 같은 변형까지 배제)
    generic = {"네이버", "네이버쇼핑", "스마트스토어", "네이버스마트스토어", "브랜드스토어",
               "네이버브랜드스토어", "smartstore", "naver", "navershopping", "쇼핑", "쇼핑몰"}

    def _clean(v):
        if not v:
            return ""
        s = str(v)
        # HTML/JSON 내 유니코드 이스케이프(\uXXXX) 복원
        if "\\u" in s:
            try:
                s = s.encode().decode("unicode_escape")
            except Exception:
                pass
        s = re.sub(r"\s+", " ", s).strip().strip('"\'')
        return s

    def _ok(v):
        """실제 상호명으로 볼 수 있는가 — 일반문구/슬러그/비정상 길이 배제"""
        if not v or not (1 < len(v) <= 60):
            return False
        low = v.lower()
        if re.sub(r"\s+", "", low) in generic:
            return False
        if slug and low == slug:      # 슬러그와 같으면 표시용으로 무의미
            return False
        return True

    # 1) 스마트스토어 임베드 JSON — 채널(스토어) 표시명이 가장 정확
    for pat, src in (
        (r'"channelName"\s*:\s*"([^"]{1,60})"', "channelName"),
        (r'"mallName"\s*:\s*"([^"]{1,60})"', "mallName"),
        (r'"storeName"\s*:\s*"([^"]{1,60})"', "storeName"),
    ):
        for m in re.finditer(pat, html):
            v = _clean(m.group(1))
            if _ok(v):
                return {"name": v, "source": src}

    # 2) 판매자 정보의 '상호명' (사업자 정보 영역) — 화면에 보이는 그 값
    try:
        from bs4 import BeautifulSoup as _BS
        text = _BS(html, "html.parser").get_text(" ", strip=True)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", html)
    m = re.search(r"상호(?:명)?\s*[:：]?\s*(.{1,60}?)\s*(?:대표자|사업자|고객센터|이메일|주소|통신판매|$)", text)
    if m:
        v = _clean(m.group(1))
        if _ok(v):
            return {"name": v, "source": "상호명"}

    # 3) og:site_name (플랫폼 일반명이면 위 _ok 에서 걸러짐)
    m = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']{1,60})["\']', html, re.I)
    if m:
        v = _clean(m.group(1))
        if _ok(v):
            return {"name": v, "source": "og:site_name"}

    return {"name": "", "source": ""}


def analyze_detail_page(html: str, product_url: str = "") -> Dict:
    """
    상세페이지 HTML을 분석하여 품질 지표를 추출
    Returns: {
        success: bool,
        metrics: { ... },
        scores: { ... },
        suggestions: [ ... ]
    }
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"success": False, "error": "beautifulsoup4 미설치"}

    # 파서는 순수 파이썬 "html.parser"를 사용한다. lxml(C 라이브러리) 파서는
    # 사용자가 붙여넣은 거대/비정상 스마트스토어 HTML에서 세그폴트로 워커
    # 프로세스를 통째로 죽여(파이썬 traceback 없이) 502를 유발했다.
    # html.parser는 순수 파이썬이라 세그폴트가 원천적으로 불가능하다.
    soup = BeautifulSoup(html, "html.parser")

    # ── 0. __NEXT_DATA__에서 단가·카테고리 직접 추출 (크롤 없이 단가·데이터랩 카테고리 공급) ──
    nd_price, nd_cat, nd_cat1 = 0, "", ""
    try:
        import json as _json
        _m = re.search(r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if _m:
            _pp = (((_json.loads(_m.group(1)).get("props") or {}).get("pageProps")) or {})
            _prod = _pp.get("product") or _pp.get("productDetail") or {}
            if isinstance(_prod, dict):
                nd_price = int(float(_prod.get("discountedSalePrice") or _prod.get("salePrice")
                                     or _prod.get("dispSalePrice") or _pp.get("discountedSalePrice")
                                     or _pp.get("salePrice") or 0) or 0)
                _cat = _prod.get("category") or {}
                nd_cat = (_cat.get("wholeCategoryName") or "") if isinstance(_cat, dict) else ""
                nd_cat1 = nd_cat.split(">")[0].strip() if nd_cat else ""
    except Exception:
        pass

    # 합성 HTML(주 크롤 경로)에는 __NEXT_DATA__ 스크립트가 없어 위에서 nd_price=0 →
    # 빌더가 보존한 api-price 메타에서 판매가 회수(가격 유실 방지)
    if not nd_price and soup:
        _pm = soup.find("meta", attrs={"name": "api-price"})
        if _pm:
            try:
                nd_price = int(float(_pm.get("content", "0")) or 0)
            except Exception:
                nd_price = 0

    # ── 1. 이미지 분석 ──
    all_imgs = soup.find_all("img")
    # 상세페이지 영역 이미지 (상품 상세 설명 내부)
    detail_area = soup.find("div", {"class": re.compile(r"detail|product.?detail|content_detail|se-viewer|_detail_content|detail_content", re.I)})
    if not detail_area:
        detail_area = soup.find("div", {"id": re.compile(r"detail|content|product_detail", re.I)})
    if not detail_area:
        detail_area = soup.find("div", {"class": "product-detail"})
    detail_imgs = detail_area.find_all("img") if detail_area else []

    # 이미지 소스 중 실제 상품 이미지 필터링 (아이콘/로고 제외)
    # ※ 스마트스토어 상세는 lazy-load라 실제 URL이 data-lazy-src/data-original/srcset에 있고
    #   <img src>는 1px 플레이스홀더인 경우가 많음 → 여러 속성을 함께 확인.
    #   또한 같은 URL이 래퍼로 중복 등장하므로 set으로 중복 제거(개수 과대/과소 방지).
    product_imgs = set()
    for img in (detail_imgs if detail_imgs else all_imgs):
        src = (img.get("src") or img.get("data-src") or img.get("data-lazy-src")
               or img.get("data-original") or img.get("data-img-src") or "")
        if not src and img.get("srcset"):
            src = img.get("srcset").split(",")[0].strip().split(" ")[0]
        # 작은 아이콘이나 트래킹 픽셀 제외
        width = img.get("width", "")
        height = img.get("height", "")
        if width and str(width).isdigit() and int(width) < 50:
            continue
        if height and str(height).isdigit() and int(height) < 50:
            continue
        sl = src.lower()
        if src and ("shop-phinf" in sl or "simage" in sl or "phinf" in sl or "blogpfthumb" in sl or ".jpg" in sl or ".jpeg" in sl or ".png" in sl or ".webp" in sl):
            product_imgs.add(src.split("?")[0])  # 쿼리스트링 제거 후 중복 제거

    total_images = len(product_imgs) if product_imgs else max(len(detail_imgs), 0)

    # ── 2. 텍스트 콘텐츠 분석 ──
    # 상세페이지 내 텍스트 추출
    if detail_area:
        detail_text = detail_area.get_text(separator=" ", strip=True)
    else:
        # body 전체에서 nav, header, footer 제외
        body = soup.find("body")
        if body:
            for tag in body.find_all(["nav", "header", "footer", "script", "style"]):
                tag.decompose()
            detail_text = body.get_text(separator=" ", strip=True)
        else:
            detail_text = soup.get_text(separator=" ", strip=True)
    text_length = len(detail_text)

    # ── 3. 동영상 분석 (중복 제거) ──
    videos = soup.find_all(["video", "iframe"])
    counted_elements = set()
    video_count = 0
    for v in videos:
        src = v.get("src", "") or v.get("data-src", "") or ""
        if "youtube" in src.lower() or "naver" in src.lower() or "vimeo" in src.lower() or v.name == "video":
            video_count += 1
            counted_elements.add(id(v))
    # 네이버 SmartEditor 동영상 감지 (이미 카운트된 video/iframe을 포함하는 div는 제외)
    video_divs = soup.find_all("div", {"class": re.compile(r"se-video|_video", re.I)})
    for vd in video_divs:
        child_videos = vd.find_all(["video", "iframe"])
        if not any(id(cv) in counted_elements for cv in child_videos):
            video_count += 1

    # ── 4. 테이블/스펙 정보 분석 ──
    tables = soup.find_all("table")
    has_spec_table = any(
        "스펙" in (t.get_text() or "") or "사양" in (t.get_text() or "") or "size" in (t.get_text() or "").lower()
        for t in tables
    ) if tables else False
    table_count = len(tables)

    # ── 5. 구매/배송 정보 감지 ──
    full_text_lower = html.lower()
    # 스마트스토어는 배송정보를 '무료 배송'(공백 포함)·JSON(freeDelivery/deliveryFee)로 표기하는
    # 경우가 많아, 공백 제거 후 매칭 + JSON 필드까지 함께 확인(배송정보 X 오탐 방지).
    _delivery_norm = full_text_lower.replace(" ", "")
    has_delivery_info = (
        any(kw in _delivery_norm for kw in ["무료배송", "당일출고", "당일발송", "로켓배송", "오늘출발", "오늘발송", "익일배송", "무료반품"])
        or '"freedelivery":true' in _delivery_norm
        or re.search(r'"deliveryfee"\s*:\s*0', _delivery_norm) is not None
        or re.search(r'(배송비|배송료)[^0-9]{0,6}(무료|0\s*원)', full_text_lower) is not None
    )
    has_return_info = any(kw in full_text_lower for kw in ["교환", "반품", "환불", "100%"])
    has_gift_info = any(kw in full_text_lower for kw in ["사은품", "증정", "선물", "덤"])

    # ── 6. 신뢰 요소 감지 ──
    has_certification = any(kw in full_text_lower for kw in ["인증", "kc인증", "haccp", "iso", "특허", "수상", "선정"])
    has_review_section = any(kw in full_text_lower for kw in ["구매후기", "리뷰", "고객후기", "사용후기"])

    # ── 7. GIF/애니메이션 감지 ──
    gif_count = len([img for img in all_imgs if ".gif" in (img.get("src", "") or "").lower()])

    # ── 8. 리뷰수 / 평점 / 찜수 추출 (SmartStore HTML) ──
    actual_review_count = None
    actual_rating = None
    actual_wish_count = None

    # 방법 0 (최우선): 메타 태그에서 API 정확값 추출
    # _convert_smartstore_json_to_html / _extract_next_data_html에서 API JSON 값을 메타 태그로 보존
    api_meta_review = soup.find("meta", attrs={"name": "api-review-count"}) if soup else None
    api_meta_score = soup.find("meta", attrs={"name": "api-review-score"}) if soup else None
    api_meta_wish = soup.find("meta", attrs={"name": "api-wish-count"}) if soup else None
    if api_meta_review:
        try:
            val = int(api_meta_review.get("content", "0"))
            if val >= 0:   # 진짜 0리뷰도 인정(음수만 배제) — 0을 '못 찾음'으로 오인해 fuzzy 폴백이 엉뚱한 숫자를 잡는 것 방지
                actual_review_count = val
                logger.info(f"[리뷰추출] 방법0 메타태그(API): 리뷰={actual_review_count}")
        except (ValueError, TypeError):
            pass
    if api_meta_score:
        try:
            val = round(float(api_meta_score.get("content", "0")), 2)
            if val > 0:
                actual_rating = val
                logger.info(f"[리뷰추출] 방법0 메타태그(API): 평점={actual_rating}")
        except (ValueError, TypeError):
            pass
    if api_meta_wish:
        try:
            val = int(api_meta_wish.get("content", "0"))
            if val > 0:
                actual_wish_count = val
                logger.info(f"[리뷰추출] 방법0 메타태그(API): 찜={actual_wish_count}")
        except (ValueError, TypeError):
            pass

    # 방법 1: JSON-LD (schema.org Product) — 방법 0에서 못 가져온 값만 보완
    import json as _json
    ld_scripts = soup.find_all("script", {"type": "application/ld+json"})
    for sc in ld_scripts:
        try:
            ld = _json.loads(sc.string or "")
            if isinstance(ld, list):
                ld = next((x for x in ld if isinstance(x, dict) and x.get("@type") == "Product"), None)
            if isinstance(ld, dict) and ld.get("@type") == "Product":
                ar = ld.get("aggregateRating", {})
                if isinstance(ar, dict):
                    if ar.get("reviewCount"):
                        actual_review_count = _safe_int(ar["reviewCount"])
                    if ar.get("ratingValue"):
                        actual_rating = round(_safe_float(ar["ratingValue"]), 2)
                logger.info(f"[리뷰추출] 방법1 JSON-LD: 리뷰={actual_review_count}, 평점={actual_rating}")
        except Exception:
            pass

    # 방법 2: window.__PRELOADED_STATE__ (Naver SmartStore SPA)
    # 각 필드 독립 체크 (방법 1에서 일부만 추출된 경우에도 나머지 보완)
    preloaded_match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?})\s*;?\s*</script>', html, re.DOTALL)
    if preloaded_match:
        try:
            state = _json.loads(preloaded_match.group(1))
            product_info = state.get("product", {}).get("A", {})
            if not product_info:
                product_info = state.get("product", {})
            if actual_review_count is None:
                rc = product_info.get("reviewCount") or product_info.get("totalReviewCount")
                if rc is not None:
                    actual_review_count = int(rc)
            if actual_rating is None:
                rt = product_info.get("reviewScore") or product_info.get("averageReviewScore")
                if rt is not None:
                    actual_rating = round(float(rt), 2)
            if actual_wish_count is None:
                wc = product_info.get("wishCount") or product_info.get("zzimCount")
                if wc is not None:
                    actual_wish_count = int(wc)
            # wishCount가 product.A 최상위에 없으면 하위 객체 재귀 탐색
            if actual_wish_count is None:
                def _find_wish(obj, depth=0):
                    if depth > 5 or not isinstance(obj, dict):
                        return None
                    for k, v in obj.items():
                        kl = k.lower()
                        if kl in ('wishcount', 'zzimcount', 'wish_count', 'zzim_count', 'wishlistcount', 'favoritecount'):
                            try:
                                val = int(v)
                                if val > 0:
                                    return val
                            except (ValueError, TypeError):
                                pass
                        if isinstance(v, dict):
                            r = _find_wish(v, depth + 1)
                            if r:
                                return r
                    return None
                wc_deep = _find_wish(state)
                if wc_deep:
                    actual_wish_count = wc_deep
            logger.info(f"[리뷰추출] 방법2 PRELOADED: 리뷰={actual_review_count}, 평점={actual_rating}, 찜={actual_wish_count}")
        except Exception:
            pass

    # 방법 3 (최후 fallback): BeautifulSoup 텍스트 기반 추출
    # 방법 0~2에서 모두 실패한 경우에만 실행됨 (각 필드별 if None 가드)
    # 주의: max 전략은 부정확할 수 있으므로 API/JSON 추출을 항상 우선
    page_text = soup.get_text(separator=" ", strip=True) if soup else ""

    if actual_review_count is None:
        # 1) JSON 리뷰수 키 우선 (가장 신뢰도 높음)
        json_review_vals = []
        for m in re.finditer(r'"(?:totalReviewCount|reviewCount)"\s*:\s*(\d+)', html):
            try:
                v = int(m.group(1))
                if v > 0:
                    json_review_vals.append(v)
            except Exception:
                pass
        if json_review_vals:
            actual_review_count = max(json_review_vals)
            logger.info(f"[리뷰추출] 방법3 JSON키: 리뷰={actual_review_count} (후보: {json_review_vals})")
        else:
            # 2) 라벨에 바로 붙은 숫자만 후보로 수집 (노이즈 큰 raw-HTML 패턴 제거)
            review_candidates = []
            for pat in [
                r'(?:리뷰|구매후기|상품평|review)\s*\(?\s*(\d[\d,]*)\s*\)?',
                r'(?:리뷰|구매후기|상품평)\s*:\s*(\d[\d,]*)',
            ]:
                for m in re.finditer(pat, page_text, re.I):
                    try:
                        val = int(m.group(1).replace(",", ""))
                        if val > 0:
                            review_candidates.append(val)
                    except Exception:
                        pass
            # 최댓값 대신 최빈값(mode) — 같은 총 리뷰수가 여러 번 반복 노출되는 특성 활용
            if review_candidates:
                from collections import Counter as _Counter
                actual_review_count = _Counter(review_candidates).most_common(1)[0][0]
                logger.info(f"[리뷰추출] 방법3 텍스트 fallback(최빈값): 리뷰={actual_review_count} (후보: {review_candidates})")

    if actual_rating is None:
        rating_candidates = []
        # 1) 라벨이 있는 패턴 (평점, 별점, 총 평점, 구매자 평점 등)
        for pat in [
            r'(?:평점|별점|rating|평균\s*평점|총\s*평점|구매자\s*(?:총\s*)?평점)\s*(\d\.\d\d?)',
            r'(\d\.\d\d?)\s*(?:점|\/\s*5)',
        ]:
            for m in re.finditer(pat, page_text, re.I):
                try:
                    val = round(float(m.group(1)), 2)
                    if 1.0 <= val <= 5.0:
                        rating_candidates.append(val)
                except Exception:
                    pass
        # 2) 리뷰 수 근처에서 X.XX 숫자 찾기 (스마트스토어는 라벨 없이 숫자만 표시)
        #    "리뷰" 텍스트 전후 200자 범위에서 소수점 숫자 추출
        for review_m in re.finditer(r'(?:리뷰|구매후기|상품평)', page_text, re.I):
            start = max(0, review_m.start() - 100)
            end = min(len(page_text), review_m.end() + 200)
            nearby_text = page_text[start:end]
            for num_m in re.finditer(r'(?<!\d)(\d\.\d\d?)(?!\d)', nearby_text):
                try:
                    val = round(float(num_m.group(1)), 2)
                    if 1.0 <= val <= 5.0:
                        rating_candidates.append(val)
                except Exception:
                    pass
        # 3) raw HTML: 별점 관련 class/aria 속성 근처 숫자
        for m in re.finditer(r'(?:star|rating|score|평점|별점)(?:[^>]*>)\s*(\d\.\d\d?)', html, re.I):
            try:
                val = round(float(m.group(1)), 2)
                if 1.0 <= val <= 5.0:
                    rating_candidates.append(val)
            except Exception:
                pass
        # 4) raw HTML: blind/sr-only 접근성 텍스트에서 평점 추출
        for m in re.finditer(r'class="[^"]*blind[^"]*"[^>]*>[^<]*?(\d\.\d\d?)', html, re.I):
            try:
                val = round(float(m.group(1)), 2)
                if 1.0 <= val <= 5.0:
                    rating_candidates.append(val)
            except Exception:
                pass

        logger.info(f"[리뷰추출] 방법3 평점 후보: {rating_candidates}")

        # 평점 결정: 소수점 2자리 값 우선, 같으면 최빈값
        if rating_candidates:
            from collections import Counter
            two_decimal = [r for r in rating_candidates if round(r * 100) % 10 != 0]
            if two_decimal:
                actual_rating = Counter(two_decimal).most_common(1)[0][0]
            else:
                actual_rating = Counter(rating_candidates).most_common(1)[0][0]

    if actual_wish_count is None:
        wish_candidates = []

        # 방법 3-A: raw HTML에서 JSON 키로 직접 검색 (가장 신뢰도 높음)
        # 페이지 내 어떤 script/JSON에든 "wishCount":30 또는 "zzimCount":30 형태가 있으면 추출
        for m in re.finditer(r'"(?:wishCount|zzimCount|wish_count|zzim_count|wishListCount|favoriteCount)"\s*:\s*(\d+)', html, re.I):
            try:
                val = int(m.group(1))
                if val > 0:
                    wish_candidates.append(val)
            except Exception:
                pass

        # 방법 3-B: raw HTML에서 "찜하기" blind/hidden 텍스트 근처 숫자 추출
        # 스마트스토어 구조: <span class="blind">찜하기</span> ... <em>30</em>
        for m in re.finditer(r'찜하기</(?:span|div|button|a)>(?:[^<]*<[^>]*>){0,8}?\s*(\d[\d,]*)\s*<', html):
            try:
                val = int(m.group(1).replace(",", ""))
                if val > 0:
                    wish_candidates.append(val)
            except Exception:
                pass

        # 방법 3-C: 텍스트 기반 패턴 매칭 (기존 + 유연한 패턴 추가)
        for pat in [
            r'(?:찜하기|찜한\s*상품|찜\s*수)\s*(\d[\d,]*)',
            r'(?:찜|zzim|wish)\s+(\d[\d,]+)',
            # "찜하기" 뒤 중간에 다른 텍스트가 있어도 30자 이내면 매칭
            r'찜하기.{0,30}?(\d[\d,]+)',
            # "관심상품" 패턴 (스마트스토어에서 찜 대신 사용하는 경우)
            r'(?:관심상품|관심\s*상품)\s*(?:추가)?\s*(\d[\d,]*)',
        ]:
            for m in re.finditer(pat, page_text, re.I):
                try:
                    val = int(m.group(1).replace(",", ""))
                    if val > 0:
                        wish_candidates.append(val)
                except Exception:
                    pass

        # 방법 3-D: raw HTML에서 zzim/wish 관련 class 근처 숫자
        for m in re.finditer(r'class="[^"]*(?:zzim|wish|bookmark|favorite)[^"]*"[^>]*>(?:[^<]*<[^>]*>){0,5}?\s*(\d[\d,]+)', html, re.I):
            try:
                val = int(m.group(1).replace(",", ""))
                if val > 0:
                    wish_candidates.append(val)
            except Exception:
                pass

        logger.info(f"[리뷰추출] 방법3 찜 후보: {wish_candidates}")

        # 찜 수 결정: 최빈값 우선, 비정상 큰 값(10만 이상) 필터
        if wish_candidates:
            # 10만 이상은 스토어 전체 찜수 등 비정상 값일 가능성 높음
            filtered = [v for v in wish_candidates if v < 100000]
            if not filtered:
                filtered = wish_candidates  # 모두 10만 이상이면 원본 사용
            # 최빈값 (가장 많이 등장한 값) 사용 — 여러 소스에서 동일 값이 나오면 신뢰도 높음
            from collections import Counter as _Counter
            most_common_val = _Counter(filtered).most_common(1)[0][0]
            actual_wish_count = most_common_val

    # ── 8-B. 찜 수 API 조회 (HTML에서 추출 실패 시) ──
    if actual_wish_count is None and product_url:
        api_wish = _fetch_wish_count_from_api(product_url)
        if api_wish is not None:
            actual_wish_count = api_wish
            logger.info(f"[리뷰추출] 찜수 API 조회 성공: {actual_wish_count}")

    logger.info(f"[리뷰추출] 최종결과: 리뷰={actual_review_count}, 평점={actual_rating}, 찜={actual_wish_count}")

    # ── 9. 페이지 총 크기 (대략적 스크롤 깊이) ──
    html_size_kb = round(len(html) / 1024, 1)

    # ── 점수 산출 ──
    scores = {}

    # 이미지 점수 (최적: 10~25장)
    if total_images >= 10 and total_images <= 25:
        scores["images"] = 100
    elif total_images >= 5:
        scores["images"] = 60 + min((total_images - 5) * 8, 40)
    elif total_images >= 1:
        scores["images"] = total_images * 12
    else:
        scores["images"] = 0

    # 텍스트 점수 (최적: 500~3000자)
    if text_length >= 500 and text_length <= 3000:
        scores["text"] = 100
    elif text_length >= 200:
        scores["text"] = 50 + min((text_length - 200) * 0.15, 50)
    elif text_length > 0:
        scores["text"] = max(text_length // 5, 5)
    else:
        scores["text"] = 0

    # 동영상 점수
    scores["video"] = min(video_count * 50, 100) if video_count > 0 else 0

    # 정보 완성도 점수
    info_score = 0
    if has_delivery_info: info_score += 25
    if has_return_info: info_score += 25
    if has_certification: info_score += 30
    if has_spec_table or table_count > 0: info_score += 20
    scores["info"] = min(info_score, 100)

    # 신뢰 요소 점수
    trust_score = 0
    if has_certification: trust_score += 40
    if has_review_section: trust_score += 30
    if has_gift_info: trust_score += 15
    if gif_count > 0 or video_count > 0: trust_score += 15
    scores["trust"] = min(trust_score, 100)

    # 종합 점수 (가중치)
    total = round(
        scores["images"] * 0.30 +
        scores["text"] * 0.20 +
        scores["video"] * 0.15 +
        scores["info"] * 0.20 +
        scores["trust"] * 0.15
    )
    scores["total"] = min(total, 100)

    # ── 개선 제안 생성 ──
    suggestions = []
    if total_images == 0:
        # 이미지 추출 실패(lazy-load 등)로 0장일 수 있어 '부족' 단정 대신 안내만 제공
        suggestions.append({"priority": "low", "area": "이미지", "text": "상세페이지 이미지를 자동으로 인식하지 못했습니다. 상세 설명 영역의 이미지가 정상 등록되어 있는지 확인해주세요."})
    elif total_images < 5:
        suggestions.append({"priority": "high", "area": "이미지", "text": f"상세페이지 이미지가 {total_images}장으로 부족합니다. 경쟁력 있는 상세페이지는 최소 10장 이상의 고화질 이미지를 사용합니다. 제품 사진, 사용 장면, 사이즈 비교, 패키지 등을 추가하세요."})
    elif total_images < 10:
        suggestions.append({"priority": "medium", "area": "이미지", "text": f"이미지 {total_images}장은 양호하지만, TOP 상품들은 평균 15~20장을 사용합니다. 사용 후기 이미지, 디테일 컷을 추가하면 전환율이 올라갑니다."})

    if text_length < 200:
        suggestions.append({"priority": "high", "area": "텍스트 콘텐츠", "text": f"상세 설명 텍스트가 {text_length}자로 매우 부족합니다. 제품 특장점, 사용법, 주의사항 등 최소 500자 이상의 설명을 추가하세요."})
    elif text_length < 500:
        suggestions.append({"priority": "medium", "area": "텍스트 콘텐츠", "text": f"텍스트 {text_length}자는 기본 수준입니다. 소재별 상세 설명, Q&A, 비교표 등을 추가하여 500자 이상으로 보강하세요."})

    if video_count == 0:
        suggestions.append({"priority": "medium", "area": "동영상", "text": "동영상이 없습니다. 제품 사용 영상 또는 언박싱 영상을 추가하면 상세페이지 체류 시간이 평균 2배 이상 증가하고, 전환율이 15~30% 상승합니다."})

    if not has_delivery_info:
        suggestions.append({"priority": "medium", "area": "배송 정보", "text": "무료배송/당일출고 등 배송 관련 정보가 명시되지 않았습니다. 배송 혜택을 상세페이지 상단에 강조하면 구매 결정에 큰 영향을 줍니다."})

    if not has_return_info:
        suggestions.append({"priority": "low", "area": "교환/반품", "text": "교환·반품·환불 정책이 명시되지 않았습니다. '100% 환불 보장' 등의 문구는 구매 장벽을 낮추는 핵심 요소입니다."})

    if not has_certification:
        suggestions.append({"priority": "medium", "area": "신뢰 요소", "text": "인증서, 수상 이력, 특허 등 신뢰 요소가 감지되지 않았습니다. KC인증, HACCP, 수상 배지 등이 있다면 상세페이지에 반드시 배치하세요."})

    if not has_review_section:
        suggestions.append({"priority": "low", "area": "리뷰 섹션", "text": "상세페이지 내 구매 후기 섹션이 없습니다. 대표 리뷰를 상세페이지에 직접 삽입하면 소셜 프루프 효과로 전환율이 향상됩니다."})

    # ── 리뷰 텍스트 추출 (개별 리뷰 본문 + 별점 + 태그) ──
    extracted_reviews = _extract_reviews(soup, html)
    review_text_analysis = _analyze_reviews(extracted_reviews) if extracted_reviews else None
    logger.info(f"[리뷰추출] 개별 리뷰 {len(extracted_reviews)}건 추출")

    # ── 이상탐지 가드: 추출값이 상식 범위를 벗어나면 '틀린 값' 대신 미확인(None) 처리 ──
    # 파싱 오류(자릿수 병합 등)·fuzzy 폴백 오탐으로 비현실적 값이 리포트에 실리는 것을 차단.
    if actual_review_count is not None and not (0 <= actual_review_count <= 2_000_000):
        logger.warning(f"[이상탐지] 리뷰수 {actual_review_count} 상식범위 초과 → 미확인 처리")
        actual_review_count = None
    if actual_rating is not None and not (0.0 < actual_rating <= 5.0):
        logger.warning(f"[이상탐지] 평점 {actual_rating} 상식범위 초과 → 미확인 처리")
        actual_rating = None
    if actual_wish_count is not None and not (0 <= actual_wish_count <= 20_000_000):
        logger.warning(f"[이상탐지] 찜수 {actual_wish_count} 상식범위 초과 → 미확인 처리")
        actual_wish_count = None
    if nd_price and not (100 <= nd_price <= 100_000_000):
        logger.warning(f"[이상탐지] 판매가 {nd_price} 상식범위 초과 → 미확인 처리")
        nd_price = 0

    # ── 데이터 신뢰 등급(data_quality): 각 수치가 실측/교차확인/미확인 중 무엇인지 부착(부가 정보) ──
    import data_quality as dq
    _sample_ratings = [r.get("rating") for r in (extracted_reviews or [])
                       if isinstance(r.get("rating"), (int, float)) and r.get("rating") > 0]
    _sample_avg = round(sum(_sample_ratings) / len(_sample_ratings), 1) if _sample_ratings else None
    # 평점: 메타/API 평점 vs 추출 리뷰 표본 평균 교차검증(±0.5 일치 시 '교차확인')
    _rating_val, _rating_status, _rating_note = dq.cross_check(actual_rating, _sample_avg, tol=0.5)
    _rating_sources = (["html_meta"] if actual_rating is not None else []) + (["review_sample"] if _sample_avg is not None else [])
    _price_val = nd_price or None
    data_quality = {
        "review_count": dq.metric(actual_review_count, dq.status_from_presence(actual_review_count),
                                  sources=["html_meta"] if actual_review_count is not None else []),
        "rating": dq.metric(_rating_val, _rating_status, sources=_rating_sources, note=_rating_note),
        "wish": dq.metric(actual_wish_count, dq.status_from_presence(actual_wish_count),
                          sources=["html_meta"] if actual_wish_count is not None else []),
        "price": dq.metric(_price_val, dq.status_from_presence(_price_val),
                           sources=["html_next_data"] if _price_val else []),
    }

    # reviewData: 실제 HTML에서 추출된 리뷰/평점/찜수 (없으면 None)
    review_data = None
    if actual_review_count is not None or actual_rating is not None or actual_wish_count is not None or extracted_reviews or nd_price or nd_cat:
        review_data = {
            "reviewCount": actual_review_count,
            "rating": actual_rating,
            "wishCount": actual_wish_count,
            "source": "html",
            "reviews": extracted_reviews,
            "reviewTextAnalysis": review_text_analysis,
            "price": nd_price or None,
            "category": nd_cat or None,
            "category1": nd_cat1 or None,
            "data_quality": data_quality,
        }

    return {
        "success": True,
        "metrics": {
            "total_images": total_images,
            "text_length": text_length,
            "video_count": video_count,
            "table_count": table_count,
            "gif_count": gif_count,
            "html_size_kb": html_size_kb,
            "has_delivery_info": has_delivery_info,
            "has_return_info": has_return_info,
            "has_gift_info": has_gift_info,
            "has_certification": has_certification,
            "has_review_section": has_review_section,
            "has_spec_table": has_spec_table,
        },
        "scores": scores,
        "suggestions": suggestions,
        "reviewData": review_data,
        # 표시용 스토어/상호명 (슬러그 오표기 방지 — 2026-07-27). 실패 시 name=""
        "storeInfo": extract_store_display_name(html, product_url),
    }
