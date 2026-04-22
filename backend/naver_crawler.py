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


# ==================== 네이버 쇼핑 공식 API ====================

def search_naver_shopping_api(keyword: str, display: int = 100, start: int = 1, sort: str = "sim", retry_on_429: bool = False) -> Dict:
    """
    네이버 검색 API - 쇼핑 검색

    - display: 한 번에 가져올 결과 수 (최대 100)
    - start: 시작 위치 (최대 1000)
    - sort: sim(유사도순), date(날짜순), asc(가격낮은순), dsc(가격높은순)
    - retry_on_429: True면 429 시 대기 후 재시도 (수동 분석용)

    ⚠️ sort=sim은 실제 네이버쇼핑 노출 순위(rel)와 다름
    """
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
            response = requests.get(url, params=params, headers=headers, timeout=10)
            # 429 Too Many Requests
            if response.status_code == 429:
                if retry_on_429 and attempt < max_retries:
                    wait_sec = 2.0 * (attempt + 1)
                    logger.warning(f"네이버 API 429 — {wait_sec}초 대기 후 재시도 ({attempt + 1}/{max_retries}) (keyword: {keyword})")
                    time.sleep(wait_sec)
                    continue
                logger.warning(f"네이버 API 429 Rate Limit — 건너뜀 (keyword: {keyword})")
                return {"error": "API 요청 한도 초과", "items": [], "total": 0}
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
        "price": int(item.get("lprice", 0)),
        "hprice": int(item.get("hprice", 0)) if item.get("hprice") else None,
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


def search_products(keyword: str, max_results: int = 200) -> List[Dict]:
    """
    키워드로 상품 검색 (최대 1000개까지)
    여러 페이지를 자동으로 조회하여 합침
    """
    all_products = []
    per_page = 100

    for start in range(1, min(max_results, 1000) + 1, per_page):
        result = search_naver_shopping_api(keyword, display=per_page, start=start)
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

def find_product_rank(keyword: str, product_url: str,
                      max_pages: int = 10) -> Tuple[Optional[int], Optional[int], List[Dict]]:
    """
    키워드 검색에서 특정 상품의 순위를 찾는다. (공식 API 기반)

    매칭 우선순위:
    1. productId(nvMid) 완전 일치
    2. 스토어명 + 상품ID 부분 일치
    3. 스토어명 + 상품명 유사도

    ⚠️ 이 순위는 공식 API의 sort=sim(유사도순) 기준이며,
       실제 네이버쇼핑 노출 순위(sort=rel)와는 다를 수 있습니다.

    Returns:
        (rank_position, page_number, top_competitors)
    """
    target_product_id = extract_product_id_from_url(product_url)
    target_store_name = extract_store_name_from_url(product_url)
    top_competitors = []

    # max_pages * 100개 결과까지 검색
    max_results = max_pages * 100
    products = search_products(keyword, max_results=max_results)

    if not products:
        logger.warning(f"검색 결과 없음: '{keyword}'")
        return None, None, []

    # 상위 5개 = 경쟁 상품
    top_competitors = products[:5]

    for product in products:
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
            logger.info(f"상품 발견! '{keyword}' → {product['rank']}위 (페이지 {page_number})")
            return product["rank"], page_number, top_competitors

    logger.info(f"상품 미발견: '{keyword}' (검색 범위: {len(products)}개)")
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

def get_product_info(product_url: str, keyword: str = "") -> Dict:
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
    }

    def _match_item(item):
        """API 검색 결과 아이템이 대상 상품과 매칭되는지 확인"""
        item_pid = str(item.get("productId", ""))
        item_link = item.get("link", "")
        item_mall = (item.get("mallName", "") or "").lower()
        # productId 매칭 또는 URL에 productId 포함
        if product_id and ((item_pid == product_id) or (product_id in item_link)):
            return True
        # 스토어명 + 상품 링크에 스토어 슬러그 포함
        if store_name and store_name.lower() in item_link.lower():
            return True
        return False

    def _fill_from_item(item):
        """API 검색 결과에서 상품 정보 채우기"""
        result["product_name"] = re.sub(r'<[^>]+>', '', item.get("title", ""))
        result["image_url"] = item.get("image", "")
        result["price"] = int(item.get("lprice", 0) or 0)
        result["store_name"] = item.get("mallName", store_name) or store_name

    # ===== 1차: 추적 키워드로 네이버 쇼핑 API 검색 (1000위까지, 가장 빠르고 안정적) =====
    if keyword:
        try:
            total_checked = 0
            for page_start in [1, 101, 201, 301, 401, 501, 601, 701, 801, 901]:
                api_result = search_naver_shopping_api(keyword, display=100, start=page_start)
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
            api_result = search_naver_shopping_api(store_name, display=100)
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
    params = {
        "hintKeywords": ",".join(keywords),
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
            for kd in keyword_data_list:
                # 요청한 키워드만 필터 (연관 키워드 제외)
                rel_keyword = kd.get("relKeyword", "")
                if rel_keyword in keywords:
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

    # 리뷰 수
    review_data = page_props.get("reviewAmount", {}) or product.get("reviewAmount", {}) or {}
    review_count = review_data.get("totalReviewCount", 0) if isinstance(review_data, dict) else 0

    # 카테고리
    category = product.get("category", {}) or {}
    cat_name = category.get("wholeCategoryName", "") or ""

    # 태그
    tags = product.get("seoInfo", {}).get("sellerTags", []) or []
    tag_html = " ".join([f'#{t.get("text", "")}' for t in tags if isinstance(t, dict)])

    # HTML 조립
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head><title>{name}</title></head>
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

        # 리뷰 수
        review_count = data.get("reviewAmount", {}).get("totalReviewCount", 0) if isinstance(data.get("reviewAmount"), dict) else 0

        # HTML 조립
        html = f"""<!DOCTYPE html>
<html lang="ko">
<head><title>{name}</title></head>
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
        session = requests.Session()
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

def _fetch_wish_count_from_api(product_url: str) -> Optional[int]:
    """
    상품 URL에서 찜 수를 네이버 내부 API로 조회.
    SmartStore 상품 페이지를 서버에서 fetch하여 __PRELOADED_STATE__ 또는
    JSON 내 wishCount를 추출한다. 실패 시 None 반환.
    비용: 없음 (일반 HTTP 요청)
    """
    if not product_url:
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
                neg = sum(1 for kw in _NEGATIVE_KW if kw in review_text)
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
                    neg = sum(1 for kw in _NEGATIVE_KW if kw in review_text)
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
            if kw in text:
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

    soup = BeautifulSoup(html, "lxml")

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
    product_imgs = []
    for img in (detail_imgs if detail_imgs else all_imgs):
        src = img.get("src", "") or img.get("data-src", "") or ""
        # 작은 아이콘이나 트래킹 픽셀 제외
        width = img.get("width", "")
        height = img.get("height", "")
        if width and str(width).isdigit() and int(width) < 50:
            continue
        if height and str(height).isdigit() and int(height) < 50:
            continue
        if src and ("shop-phinf" in src or "simage" in src or "phinf" in src or "blogpfthumb" in src or ".jpg" in src.lower() or ".png" in src.lower() or ".webp" in src.lower()):
            product_imgs.append(src)

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

    # ── 3. 동영상 분석 ──
    videos = soup.find_all(["video", "iframe"])
    video_count = 0
    for v in videos:
        src = v.get("src", "") or v.get("data-src", "") or ""
        if "youtube" in src.lower() or "naver" in src.lower() or "vimeo" in src.lower() or v.name == "video":
            video_count += 1
    # 네이버 SmartEditor 동영상 감지
    video_divs = soup.find_all("div", {"class": re.compile(r"se-video|_video|movie", re.I)})
    video_count += len(video_divs)

    # ── 4. 테이블/스펙 정보 분석 ──
    tables = soup.find_all("table")
    has_spec_table = any(
        "스펙" in (t.get_text() or "") or "사양" in (t.get_text() or "") or "size" in (t.get_text() or "").lower()
        for t in tables
    ) if tables else False
    table_count = len(tables)

    # ── 5. 구매/배송 정보 감지 ──
    full_text_lower = html.lower()
    has_delivery_info = any(kw in full_text_lower for kw in ["무료배송", "당일출고", "당일발송", "로켓배송", "오늘출발"])
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

    # 방법 1: JSON-LD (schema.org Product)
    import json as _json
    ld_scripts = soup.find_all("script", {"type": "application/ld+json"})
    for sc in ld_scripts:
        try:
            ld = _json.loads(sc.string or "")
            if isinstance(ld, list):
                ld = next((x for x in ld if x.get("@type") == "Product"), None)
            if ld and ld.get("@type") == "Product":
                ar = ld.get("aggregateRating", {})
                if ar.get("reviewCount"):
                    actual_review_count = int(ar["reviewCount"])
                if ar.get("ratingValue"):
                    actual_rating = round(float(ar["ratingValue"]), 2)
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

    # 방법 3: BeautifulSoup 텍스트 기반 추출 (HTML 태그 제거 후 패턴 매칭)
    # 북마클릿으로 복사한 DOM은 태그가 섞여있어 raw HTML 정규식이 실패할 수 있음
    # 전략: 모든 매칭을 찾아서 가장 큰 값을 사용 (총 리뷰수가 항상 가장 큼)
    page_text = soup.get_text(separator=" ", strip=True) if soup else ""

    if actual_review_count is None:
        review_candidates = []
        # 텍스트에서 모든 "리뷰 N" 패턴을 찾아 후보 수집
        for pat in [
            r'(?:리뷰|구매후기|상품평|review)\s*(\d[\d,]*)',
            r'(?:리뷰|구매후기|상품평)\s*\(\s*(\d[\d,]*)\s*\)',
            r'(?:리뷰|구매후기|상품평)\s*:\s*(\d[\d,]*)',
        ]:
            for m in re.finditer(pat, page_text, re.I):
                try:
                    review_candidates.append(int(m.group(1).replace(",", "")))
                except Exception:
                    pass
        # raw HTML에서도 태그 사이 숫자 추출
        for m in re.finditer(r'(?:리뷰|구매후기|상품평)(?:[^<]*(?:<[^>]*>)[^<]*){0,5}?([\d,]+)', html):
            try:
                val = int(m.group(1).replace(",", ""))
                if val > 0:
                    review_candidates.append(val)
            except Exception:
                pass
        # 가장 큰 값 = 총 리뷰수
        if review_candidates:
            actual_review_count = max(review_candidates)

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

        # 가장 큰 값 = 총 찜수 (0 제외)
        if wish_candidates:
            actual_wish_count = max(wish_candidates)

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
    if total_images < 5:
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

    # reviewData: 실제 HTML에서 추출된 리뷰/평점/찜수 (없으면 None)
    review_data = None
    if actual_review_count is not None or actual_rating is not None or actual_wish_count is not None or extracted_reviews:
        review_data = {
            "reviewCount": actual_review_count,
            "rating": actual_rating,
            "wishCount": actual_wish_count,
            "source": "html",
            "reviews": extracted_reviews,
            "reviewTextAnalysis": review_text_analysis,
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
    }
