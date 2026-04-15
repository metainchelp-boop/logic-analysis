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

# Bright Data 프록시 (상세페이지 크롤링용)
BRD_API_KEY = os.getenv("NAVER_BRD_API_KEY", "")
BRD_API_URL = os.getenv("NAVER_BRD_API_URL", "")
BRD_API_ZONE = os.getenv("NAVER_BRD_API_ZONE", "")


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

def search_naver_shopping_api(keyword: str, display: int = 100, start: int = 1, sort: str = "sim") -> Dict:
    """
    네이버 검색 API - 쇼핑 검색

    - display: 한 번에 가져올 결과 수 (최대 100)
    - start: 시작 위치 (최대 1000)
    - sort: sim(유사도순), date(날짜순), asc(가격낮은순), dsc(가격높은순)

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

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            logger.info(f"API 검색 '{keyword}': {data.get('total', 0)}건 중 {len(data.get('items', []))}건 조회")
            return data
        except requests.exceptions.RequestException as e:
            if attempt < max_retries:
                logger.warning(f"네이버 API 재시도 ({attempt + 1}/{max_retries}): {e}")
                time.sleep(0.5 * (attempt + 1))
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
                      max_pages: int = 2) -> Tuple[Optional[int], Optional[int], List[Dict]]:
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


# ==================== 상품 정보 조회 ====================

def get_product_info(product_url: str) -> Dict:
    """
    상품 URL에서 상품 정보 가져오기
    - 웹 스크래핑 대신 URL 파싱 + API 검색으로 정보 수집
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

    # 스토어명이 있으면 스토어명으로 API 검색하여 상품 정보 보완
    if store_name:
        try:
            api_result = search_naver_shopping_api(store_name, display=20)
            for item in api_result.get("items", []):
                item_pid = str(item.get("productId", ""))
                item_link = item.get("link", "")

                # productId 또는 URL로 매칭
                if (product_id and item_pid == product_id) or \
                   (product_id and product_id in item_link):
                    result["product_name"] = re.sub(r'<[^>]+>', '', item.get("title", ""))
                    result["image_url"] = item.get("image", "")
                    result["price"] = int(item.get("lprice", 0))
                    result["store_name"] = item.get("mallName", store_name)
                    logger.info(f"상품 정보 조회 성공: {result['product_name'][:30]}")
                    break
        except Exception as e:
            logger.warning(f"상품 정보 API 조회 실패: {e}")

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

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=10)
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
                time.sleep(0.5 * (attempt + 1))
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

def _build_brd_proxies() -> Optional[Dict]:
    """Bright Data 프록시 설정 빌드"""
    if not BRD_API_KEY or not BRD_API_URL:
        return None
    # BRD_API_URL: 호스트:포트 형태 (예: brd.superproxy.io:22225)
    # BRD_API_ZONE: 존 이름 (예: residential_proxy1)
    # BRD_API_KEY: 인증 비밀번호
    if BRD_API_ZONE:
        proxy_url = f"http://{BRD_API_ZONE}:{BRD_API_KEY}@{BRD_API_URL}"
    else:
        proxy_url = f"http://{BRD_API_KEY}@{BRD_API_URL}"
    return {"http": proxy_url, "https": proxy_url}


def fetch_detail_page_html(product_url: str) -> Optional[str]:
    """
    스마트스토어/네이버 상품 상세페이지 HTML 가져오기
    1차: Bright Data 프록시 경유
    2차: 직접 요청 (fallback)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }

    # 1차: Bright Data 프록시
    proxies = _build_brd_proxies()
    if proxies:
        try:
            logger.info(f"Bright Data 프록시로 상세페이지 요청: {product_url[:60]}...")
            resp = requests.get(product_url, headers=headers, proxies=proxies, timeout=30, verify=False)
            if resp.status_code == 200 and len(resp.text) > 1000:
                logger.info(f"상세페이지 HTML 수신 성공: {len(resp.text)}자")
                return resp.text
            else:
                logger.warning(f"프록시 응답 비정상: status={resp.status_code}, len={len(resp.text)}")
        except Exception as e:
            logger.warning(f"Bright Data 프록시 요청 실패: {e}")

    # 2차: 직접 요청 (VPS에서는 보통 418 차단됨)
    try:
        logger.info(f"직접 요청 시도: {product_url[:60]}...")
        resp = requests.get(product_url, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 1000:
            logger.info(f"직접 요청 성공: {len(resp.text)}자")
            return resp.text
        else:
            logger.warning(f"직접 요청 실패: status={resp.status_code}")
    except Exception as e:
        logger.warning(f"직접 요청 실패: {e}")

    return None


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
    detail_area = soup.find("div", {"class": re.compile(r"detail|product.?detail|content_detail|se-viewer|_detail_content", re.I)})
    if not detail_area:
        detail_area = soup.find("div", {"id": re.compile(r"detail|content|product_detail", re.I)})
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

    # ── 8. 페이지 총 크기 (대략적 스크롤 깊이) ──
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
    }
