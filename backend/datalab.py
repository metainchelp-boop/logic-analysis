"""
datalab.py — 네이버 데이터랩 쇼핑인사이트 API 연동
성별/연령대별 검색 비율, 검색량 트렌드, 시즌 예측, 요일별 패턴, 전년 대비 성장률, 카테고리 인기 키워드
"""
import os
import logging
import time
import threading
import requests
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

DATALAB_BASE = "https://openapi.naver.com/v1/datalab/shopping"

# ==================== 메모리 캐시 (TTL 1시간) ====================
_cache = {}           # { cache_key: { "data": dict, "ts": float } }
_cache_lock = threading.Lock()
CACHE_TTL = 3600      # 1시간 (초)
CACHE_MAX_SIZE = 200  # 최대 캐시 항목 수


def _cache_key(keyword: str, category: str, related: list = None) -> str:
    """키워드+카테고리+연관키워드 조합으로 캐시 키 생성"""
    if related:
        # related_keywords는 dict 리스트일 수 있음 ({"keyword": "...", ...})
        keys = []
        for r in related:
            if isinstance(r, dict):
                keys.append(r.get("keyword", str(r)))
            else:
                keys.append(str(r))
        rel = ",".join(sorted(keys))
    else:
        rel = ""
    return f"{keyword}|{category}|{rel}"


def _cache_get(key: str):
    """캐시에서 유효한 데이터 조회. 만료 시 None 반환"""
    with _cache_lock:
        entry = _cache.get(key)
        if entry and (time.time() - entry["ts"]) < CACHE_TTL:
            return entry["data"]
        if entry:
            del _cache[key]  # 만료된 항목 제거
    return None


def _cache_set(key: str, data: dict):
    """캐시에 데이터 저장. 최대 크기 초과 시 가장 오래된 항목 제거"""
    with _cache_lock:
        # 크기 제한: 초과 시 만료된 항목부터 정리, 그래도 초과하면 가장 오래된 것 제거
        if len(_cache) >= CACHE_MAX_SIZE:
            now = time.time()
            expired = [k for k, v in _cache.items() if (now - v["ts"]) >= CACHE_TTL]
            for k in expired:
                del _cache[k]
            if len(_cache) >= CACHE_MAX_SIZE:
                oldest_key = min(_cache, key=lambda k: _cache[k]["ts"])
                del _cache[oldest_key]
        _cache[key] = {"data": data, "ts": time.time()}

# ==================== 네이버 쇼핑 카테고리 코드 매핑 ====================
CATEGORY_MAP = {
    "패션의류": "50000000",
    "패션잡화": "50000001",
    "화장품/미용": "50000002",
    "디지털/가전": "50000003",
    "가구/인테리어": "50000004",
    "출산/육아": "50000005",
    "식품": "50000006",
    "스포츠/레저": "50000007",
    "생활/건강": "50000008",
    "여가/생활편의": "50000009",
    "면세점": "50000010",
    "도서": "50005542",
}

# 부분 매칭 (category1 텍스트 → 코드)
def _find_category_code(cat1_name: str) -> str:
    """카테고리 이름으로 코드 찾기 (부분 매칭)"""
    if not cat1_name:
        return "50000008"  # 기본: 생활/건강
    # 정확 매칭
    if cat1_name in CATEGORY_MAP:
        return CATEGORY_MAP[cat1_name]
    # 부분 매칭
    for name, code in CATEGORY_MAP.items():
        if cat1_name in name or name in cat1_name:
            return code
    # 키워드 기반 추측
    kw_map = {
        "패션": "50000000", "의류": "50000000", "옷": "50000000",
        "가방": "50000001", "신발": "50000001", "악세서리": "50000001",
        "화장": "50000002", "뷰티": "50000002", "미용": "50000002",
        "가전": "50000003", "전자": "50000003", "컴퓨터": "50000003", "디지털": "50000003",
        "가구": "50000004", "인테리어": "50000004", "홈": "50000004",
        "유아": "50000005", "아기": "50000005", "출산": "50000005",
        "식품": "50000006", "음식": "50000006", "먹거리": "50000006",
        "스포츠": "50000007", "레저": "50000007", "골프": "50000007", "운동": "50000007",
        "생활": "50000008", "건강": "50000008", "주방": "50000008",
    }
    for kw, code in kw_map.items():
        if kw in cat1_name:
            return code
    return "50000008"


def _datalab_headers():
    return {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }


def _datalab_post(endpoint: str, body: dict) -> dict:
    """데이터랩 API POST 호출 (공통)"""
    url = f"{DATALAB_BASE}/{endpoint}"
    try:
        resp = requests.post(url, json=body, headers=_datalab_headers(), timeout=10)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"Datalab API {endpoint} 응답 코드: {resp.status_code} — {resp.text[:200]}")
        return {}
    except Exception as e:
        logger.error(f"Datalab API {endpoint} 오류: {e}")
        return {}


# ==================== 성별 검색 비율 ====================
def get_gender_ratio(keyword: str, category_code: str) -> dict:
    """성별 검색 비율 (최근 1개월)"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "month",
        "category": category_code,
        "keyword": keyword,
    }
    data = _datalab_post("category/keyword/gender", body)
    if not data or "results" not in data:
        return {}

    results = data["results"]
    gender_data = {}
    for item in results:
        data_points = item.get("data", [])
        for pt in data_points:
            group = pt.get("group", "")
            ratio = pt.get("ratio", 0)
            if group:
                gender_data[group] = round(ratio, 1)  # 마지막(최신) 데이터 포인트가 덮어씀
    logger.info(f"성별 원본 데이터: {gender_data}")

    male = gender_data.get("m", 0)
    female = gender_data.get("f", 0)
    total = male + female
    if total > 0:
        male_pct = round(male / total * 100, 1)
        female_pct = round(female / total * 100, 1)
    else:
        male_pct = 50
        female_pct = 50

    return {"male": male_pct, "female": female_pct}


# ==================== 연령대별 검색 비율 ====================
def get_age_ratio(keyword: str, category_code: str) -> dict:
    """연령대별 검색 비율 (최근 1개월)"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "month",
        "category": category_code,
        "keyword": keyword,
    }
    data = _datalab_post("category/keyword/age", body)
    if not data or "results" not in data:
        return {}

    results = data["results"]
    age_data = {}
    for item in results:
        data_points = item.get("data", [])
        for pt in data_points:
            group = pt.get("group", "")
            ratio = pt.get("ratio", 0)
            if group:
                age_data[group] = round(ratio, 1)  # 마지막(최신) 데이터 포인트가 덮어씀
    logger.info(f"연령대 원본 데이터: {age_data}")

    # 그룹명 매핑 (API는 10, 20, 30, 40, 50, 60 반환)
    total = sum(age_data.values()) or 1
    age_labels = {"10": "10대", "20": "20대", "30": "30대", "40": "40대", "50": "50대", "60": "60대"}
    age_result = []
    for code in ["10", "20", "30", "40", "50", "60"]:
        raw = age_data.get(code, 0)
        pct = round(raw / total * 100, 1) if total > 0 else 0
        age_result.append({"label": age_labels.get(code, code + "대"), "ratio": pct})

    return {"ages": age_result}


# ==================== 12개월 검색량 트렌드 ====================
def get_trend_12m(keyword: str, category_code: str) -> dict:
    """최근 12개월 월별 검색 트렌드"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "month",
        "category": category_code,
        "keyword": [{"name": keyword, "param": [keyword]}],
    }
    data = _datalab_post("category/keywords", body)
    if not data or "results" not in data:
        return {}

    results = data.get("results", [])
    if not results:
        return {}

    points = results[0].get("data", [])
    months = []
    for pt in points:
        period = pt.get("period", "")
        ratio = round(pt.get("ratio", 0), 1)
        # period: "2025-04-01" → "4월"
        try:
            dt = datetime.strptime(period, "%Y-%m-%d")
            label = f"{dt.month}월"
        except Exception:
            label = period
        months.append({"period": period, "label": label, "ratio": ratio})

    if not months:
        return {}

    ratios = [m["ratio"] for m in months]
    max_ratio = max(ratios)
    min_ratio = min(ratios)
    avg_ratio = round(sum(ratios) / len(ratios), 1)
    max_month = next(m["label"] for m in months if m["ratio"] == max_ratio)
    min_month = next(m["label"] for m in months if m["ratio"] == min_ratio)

    return {
        "months": months,
        "maxRatio": max_ratio, "minRatio": min_ratio, "avgRatio": avg_ratio,
        "maxMonth": max_month, "minMonth": min_month,
        "range": round(max_ratio - min_ratio, 1),
    }


# ==================== 시즌별 수요 예측 ====================
def get_season_prediction(trend_data: dict) -> dict:
    """12개월 트렌드 데이터로 시즌별 수요 지수 계산"""
    months = trend_data.get("months", [])
    if len(months) < 6:
        return {}

    # 월 → 시즌 매핑
    season_months = {
        "봄": [3, 4, 5],
        "여름": [6, 7, 8],
        "가을": [9, 10, 11],
        "겨울": [12, 1, 2],
    }
    season_icons = {"봄": "🌸", "여름": "☀️", "가을": "🍂", "겨울": "❄️"}
    season_periods = {"봄": "3월 ~ 5월", "여름": "6월 ~ 8월", "가을": "9월 ~ 11월", "겨울": "12월 ~ 2월"}

    season_data = {}
    for m in months:
        try:
            dt = datetime.strptime(m["period"], "%Y-%m-%d")
            month_num = dt.month
        except Exception:
            continue
        for season, month_list in season_months.items():
            if month_num in month_list:
                if season not in season_data:
                    season_data[season] = []
                season_data[season].append(m["ratio"])

    seasons = []
    for season_name in ["봄", "여름", "가을", "겨울"]:
        vals = season_data.get(season_name, [])
        avg = round(sum(vals) / len(vals), 1) if vals else 0
        seasons.append({
            "name": season_name,
            "icon": season_icons[season_name],
            "period": season_periods[season_name],
            "index": avg,
        })

    # 등급 지정
    max_idx = max(s["index"] for s in seasons) if seasons else 1
    for s in seasons:
        ratio = s["index"] / max_idx * 100 if max_idx > 0 else 0
        if ratio >= 90:
            s["grade"] = "최성수기"
            s["gradeColor"] = "#22c55e"
            s["gradeBg"] = "#dcfce7"
        elif ratio >= 70:
            s["grade"] = "성수기"
            s["gradeColor"] = "#f59e0b"
            s["gradeBg"] = "#fef3c7"
        elif ratio >= 45:
            s["grade"] = "보통"
            s["gradeColor"] = "#64748b"
            s["gradeBg"] = "#f1f5f9"
        else:
            s["grade"] = "비수기"
            s["gradeColor"] = "#3b82f6"
            s["gradeBg"] = "#dbeafe"

    # 인사이트 생성
    peak = max(seasons, key=lambda x: x["index"]) if seasons else None
    insight = ""
    if peak:
        insight = f'이 키워드는 {peak["name"]}({peak["period"]})에 검색량이 최고조에 달합니다. 성수기 2~3개월 전부터 상품 준비 및 광고 세팅을 권장합니다.'

    return {"seasons": seasons, "insight": insight}


# ==================== 요일별 검색 패턴 ====================
def get_weekday_pattern(keyword: str, category_code: str) -> dict:
    """최근 4주 일별 데이터에서 요일 패턴 추출"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=28)).strftime("%Y-%m-%d")

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": "date",
        "category": category_code,
        "keyword": [{"name": keyword, "param": [keyword]}],
    }
    data = _datalab_post("category/keywords", body)
    if not data or "results" not in data:
        return {}

    results = data.get("results", [])
    if not results:
        return {}

    points = results[0].get("data", [])
    weekday_sums = defaultdict(list)
    day_names = ["월", "화", "수", "목", "금", "토", "일"]

    for pt in points:
        try:
            dt = datetime.strptime(pt["period"], "%Y-%m-%d")
            weekday = dt.weekday()  # 0=월 ~ 6=일
            weekday_sums[weekday].append(pt.get("ratio", 0))
        except Exception:
            continue

    days = []
    for i in range(7):
        vals = weekday_sums.get(i, [])
        avg = round(sum(vals) / len(vals), 1) if vals else 0
        days.append({"label": day_names[i], "index": avg})

    if not days:
        return {}

    # 100 기준으로 정규화
    max_val = max(d["index"] for d in days) if days else 1
    for d in days:
        d["normalized"] = round(d["index"] / max_val * 100, 1) if max_val > 0 else 0

    peak_day = max(days, key=lambda x: x["index"])
    low_day = min(days, key=lambda x: x["index"])

    return {
        "days": days,
        "peakDay": peak_day["label"],
        "lowDay": low_day["label"],
        "peakIndex": peak_day["normalized"],
        "lowIndex": low_day["normalized"],
    }


# ==================== 전년 동기 대비 성장률 ====================
def get_yoy_growth(keyword: str, category_code: str) -> dict:
    """전년 동기 대비 1개월/3개월/12개월 성장률 (병렬 API 호출)"""
    from concurrent.futures import ThreadPoolExecutor
    now = datetime.now()
    periods = [
        {"label": "1개월", "months": 1},
        {"label": "3개월", "months": 3},
        {"label": "12개월", "months": 12},
    ]

    # 6개 API 요청 본문을 미리 준비
    api_tasks = []
    for p in periods:
        cur_end = now.strftime("%Y-%m-%d")
        cur_start = (now - timedelta(days=30 * p["months"])).strftime("%Y-%m-%d")
        prev_end = (now - timedelta(days=365)).strftime("%Y-%m-%d")
        prev_start = (now - timedelta(days=365 + 30 * p["months"])).strftime("%Y-%m-%d")

        body_base = {
            "timeUnit": "month",
            "category": category_code,
            "keyword": [{"name": keyword, "param": [keyword]}],
        }
        api_tasks.append({
            "label": p["label"],
            "cur_body": {**body_base, "startDate": cur_start, "endDate": cur_end},
            "prev_body": {**body_base, "startDate": prev_start, "endDate": prev_end},
            "cur_start": cur_start, "cur_end": cur_end,
            "prev_start": prev_start, "prev_end": prev_end,
        })

    # 6개 API를 병렬 호출 (순차 60초 → 병렬 ~10초)
    def _fetch(body):
        return _datalab_post("category/keywords", body)

    all_bodies = []
    for t in api_tasks:
        all_bodies.append(t["cur_body"])
        all_bodies.append(t["prev_body"])

    with ThreadPoolExecutor(max_workers=6) as executor:
        api_results = list(executor.map(_fetch, all_bodies))

    # 결과 조합
    results = []
    for i, t in enumerate(api_tasks):
        data_cur = api_results[i * 2]
        data_prev = api_results[i * 2 + 1]

        cur_avg = 0
        prev_avg = 0
        if data_cur and "results" in data_cur and data_cur["results"]:
            pts = data_cur["results"][0].get("data", [])
            vals = [pt.get("ratio", 0) for pt in pts]
            cur_avg = round(sum(vals) / len(vals), 1) if vals else 0
        if data_prev and "results" in data_prev and data_prev["results"]:
            pts = data_prev["results"][0].get("data", [])
            vals = [pt.get("ratio", 0) for pt in pts]
            prev_avg = round(sum(vals) / len(vals), 1) if vals else 0

        if prev_avg > 0:
            growth = round((cur_avg - prev_avg) / prev_avg * 100, 1)
        else:
            growth = 0

        results.append({
            "label": t["label"],
            "currentAvg": cur_avg,
            "previousAvg": prev_avg,
            "growth": growth,
            "curPeriod": f'{t["cur_start"]} ~ {t["cur_end"]}',
            "prevPeriod": f'{t["prev_start"]} ~ {t["prev_end"]}',
        })

    return {"periods": results}


# ==================== 카테고리 인기 키워드 ====================
def get_category_popular_keywords(keyword: str, category_code: str, related_keywords: list = None) -> dict:
    """카테고리 내 연관 키워드의 트렌드 비교 → 인기 + 급상승 분류"""
    if not related_keywords or len(related_keywords) < 2:
        return {}

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_1m = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    start_2m = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    # 최대 5개씩 비교 (API 제한: 한 번에 최대 5개 키워드)
    kw_list = related_keywords[:10]

    popular = []
    rising = []

    # 2번에 나눠서 호출 (5개씩)
    for batch_start in range(0, len(kw_list), 5):
        batch = kw_list[batch_start:batch_start + 5]
        kw_params = [{"name": kw["keyword"], "param": [kw["keyword"]]} for kw in batch]

        # 최근 1개월 데이터
        body_cur = {
            "startDate": start_1m, "endDate": end_date,
            "timeUnit": "month",
            "category": category_code,
            "keyword": kw_params,
        }
        data_cur = _datalab_post("category/keywords", body_cur)

        # 전월 데이터
        body_prev = {
            "startDate": start_2m, "endDate": start_1m,
            "timeUnit": "month",
            "category": category_code,
            "keyword": kw_params,
        }
        data_prev = _datalab_post("category/keywords", body_prev)

        cur_map = {}
        prev_map = {}

        if data_cur and "results" in data_cur:
            for r in data_cur["results"]:
                name = r.get("title", "")
                pts = r.get("data", [])
                val = pts[-1].get("ratio", 0) if pts else 0
                cur_map[name] = val

        if data_prev and "results" in data_prev:
            for r in data_prev["results"]:
                name = r.get("title", "")
                pts = r.get("data", [])
                val = pts[-1].get("ratio", 0) if pts else 0
                prev_map[name] = val

        for kw in batch:
            name = kw["keyword"]
            cur_val = cur_map.get(name, 0)
            prev_val = prev_map.get(name, 0)
            volume = kw.get("totalVolume", 0)

            if prev_val > 0:
                growth = round((cur_val - prev_val) / prev_val * 100, 1)
            else:
                growth = 0

            entry = {
                "keyword": name,
                "volume": volume,
                "growth": growth,
                "currentIndex": round(cur_val, 1),
            }
            popular.append(entry)
            if growth > 20:
                rising.append(entry)

    # 인기 키워드: 현재 지수 기준 정렬
    popular.sort(key=lambda x: -x["currentIndex"])
    # 급상승: 성장률 기준 정렬
    rising.sort(key=lambda x: -x["growth"])

    return {
        "popular": popular[:10],
        "rising": rising[:5],
    }


# ==================== 통합 분석 함수 ====================
def analyze_datalab(keyword: str, category1: str = "", related_keywords: list = None) -> dict:
    """모든 데이터랩 분석을 한 번에 실행 (1시간 TTL 메모리 캐시 적용)"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("데이터랩: 네이버 API 키 미설정")
        return {}

    # 캐시 확인
    c_key = _cache_key(keyword, category1, related_keywords)
    cached = _cache_get(c_key)
    if cached:
        logger.info(f"데이터랩 캐시 히트: keyword={keyword}")
        return cached

    cat_code = _find_category_code(category1)
    logger.info(f"데이터랩 분석 시작 (API 호출): keyword={keyword}, category={category1}→{cat_code}")

    result = {}

    # 1. 성별 비율
    try:
        gender = get_gender_ratio(keyword, cat_code)
        if gender:
            result["gender"] = gender
    except Exception as e:
        logger.error(f"데이터랩 성별 오류: {e}")

    # 2. 연령대별 비율
    try:
        age = get_age_ratio(keyword, cat_code)
        if age:
            result["age"] = age
    except Exception as e:
        logger.error(f"데이터랩 연령대 오류: {e}")

    # 3. 12개월 트렌드
    try:
        trend = get_trend_12m(keyword, cat_code)
        if trend:
            result["trend"] = trend
    except Exception as e:
        logger.error(f"데이터랩 트렌드 오류: {e}")

    # 4. 시즌별 수요 예측 (트렌드 데이터 기반)
    if "trend" in result:
        try:
            season = get_season_prediction(result["trend"])
            if season:
                result["season"] = season
        except Exception as e:
            logger.error(f"데이터랩 시즌 오류: {e}")

    # 5. 요일별 검색 패턴
    try:
        weekday = get_weekday_pattern(keyword, cat_code)
        if weekday:
            result["weekday"] = weekday
    except Exception as e:
        logger.error(f"데이터랩 요일 오류: {e}")

    # 6. 전년 동기 대비 성장률
    try:
        growth = get_yoy_growth(keyword, cat_code)
        if growth:
            result["growth"] = growth
    except Exception as e:
        logger.error(f"데이터랩 성장률 오류: {e}")

    # 7. 카테고리 인기 키워드
    if related_keywords:
        try:
            cat_kw = get_category_popular_keywords(keyword, cat_code, related_keywords)
            if cat_kw:
                result["categoryKeywords"] = cat_kw
        except Exception as e:
            logger.error(f"데이터랩 카테고리 키워드 오류: {e}")

    logger.info(f"데이터랩 분석 완료: {list(result.keys())}")

    # 결과가 있으면 캐시에 저장
    if result:
        _cache_set(c_key, result)
        logger.info(f"데이터랩 캐시 저장: keyword={keyword} (캐시 크기: {len(_cache)})")

    return result
