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

# ⚠️ 「데이터랩(검색어트렌드)」는 네이버가 **신규 등록을 막아둔** API 다(2026-08-11 실측 —
# 개발자센터에서 기존 앱에 추가하면 "신규로 등록할 수 없는 API가 선택되었습니다" 로 거절).
# 그래서 이 API 만 **그 권한을 이미 가진 다른 앱**의 키로 부른다. 나머지 경로
# (지역검색·쇼핑검색·쇼핑인사이트)는 종전 NAVER_CLIENT_ID/SECRET 그대로 —
# 주력 경로의 일일 한도를 다른 서비스와 섞지 않기 위해 **의도적으로 분리**한다.
# 미설정이면 기존 키로 폴백(= 지금과 동일 동작, 트렌드만 401 로 조용히 비활성).
DATALAB_SEARCH_CLIENT_ID = os.getenv("DATALAB_SEARCH_CLIENT_ID", "") or NAVER_CLIENT_ID
DATALAB_SEARCH_CLIENT_SECRET = os.getenv("DATALAB_SEARCH_CLIENT_SECRET", "") or NAVER_CLIENT_SECRET

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


# ==================== 중/소분류 카테고리 코드 런타임 확인 ====================
#   근본 개선(건의 2026-07, 양근형): 인기·급상승 키워드를 상품의 소분류(예: 차류) 기준으로
#   산정하면 '쌀 10kg' 같은 무관 키워드는 그 카테고리 검색 비중이 0이라 자연 탈락한다
#   (실측: 식품 기준 쌀10kg 지수 100 → 콤부차 세분류 기준 데이터 없음).
#   코드는 데이터랩 쇼핑인사이트 공개 카테고리 조회로 '필요할 때만' 확인 후 영구 캐시
#   (추측 코드 금지). 확인 실패 시 대분류 폴백 → 기존 동작과 동일.
DATALAB_TREE_URL = "https://datalab.naver.com/shoppingInsight/getCategory.naver"
_cat_code_cache = {}
_cat_code_lock = threading.Lock()
CAT_CODE_FILE = os.path.join(os.path.dirname(os.getenv("DB_PATH", "/app/data/logic_data.db")),
                             "datalab_category_codes.json")
# 공식 데이터랩 코드표(find_category)로 검증된 시드 — 재기동 직후 워밍업
_VERIFIED_SEED = {
    "식품|음료|생수": "50002032",
    "식품|음료|탄산수": "50002033",
    "식품|건강식품|인삼": "50001902",
    "식품|건강식품|건강환/정": "50001899",
    "식품|건강식품|꿀": "50001905",
}


def _cat_cache_load():
    with _cat_code_lock:
        if _cat_code_cache:
            return
        _cat_code_cache.update(_VERIFIED_SEED)
        try:
            import json as _json
            with open(CAT_CODE_FILE, "r", encoding="utf-8") as f:
                saved = _json.load(f)
            if isinstance(saved, dict):
                _cat_code_cache.update({str(k): str(v) for k, v in saved.items()})
        except Exception:
            pass


def _cat_cache_put(key: str, cid: str):
    with _cat_code_lock:
        _cat_code_cache[key] = cid
        try:
            import json as _json
            with open(CAT_CODE_FILE, "w", encoding="utf-8") as f:
                _json.dump(_cat_code_cache, f, ensure_ascii=False, indent=1)
        except Exception:
            pass  # 파일 저장 실패해도 메모리 캐시로 동작


def _fetch_category_children(cid: str) -> list:
    """cid의 하위 카테고리 [{name, cid}] 조회 — 실패 시 빈 리스트(호출측 대분류 폴백)."""
    try:
        resp = requests.get(
            DATALAB_TREE_URL, params={"cid": cid},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://datalab.naver.com/shoppingInsight/sCategory.naver",
            }, timeout=6)
        if resp.status_code != 200:
            logger.warning(f"카테고리 트리 조회 {resp.status_code} (cid={cid})")
            return []
        data = resp.json()
    except Exception as e:
        logger.warning(f"카테고리 트리 조회 실패(cid={cid}): {e}")
        return []
    # 응답 형태 방어적 파싱: name + cid(catId)를 가진 dict 리스트를 재귀 탐색
    def _walk(node):
        if isinstance(node, list):
            found = [x for x in node if isinstance(x, dict) and x.get("name") and (x.get("cid") or x.get("catId"))]
            if found:
                return found
            for x in node:
                r = _walk(x)
                if r:
                    return r
        elif isinstance(node, dict):
            for v in node.values():
                r = _walk(v)
                if r:
                    return r
        return []
    return [{"name": str(c.get("name", "")).strip(), "cid": str(c.get("cid") or c.get("catId"))}
            for c in _walk(data)]


def _resolve_subcategory_cid(cat1: str, cat2: str = "", cat3: str = ""):
    """상품의 중/소분류명으로 데이터랩 코드를 확인. 성공 시 (cid, 기준명), 실패 시 (None, '')."""
    c1 = (cat1 or "").strip()
    names = [n.strip() for n in (cat2, cat3) if n and n.strip()]
    if not c1 or not names or c1 not in CATEGORY_MAP:
        return None, ""
    _cat_cache_load()
    key = "|".join([c1] + names)
    with _cat_code_lock:
        hit = _cat_code_cache.get(key)
    if hit:
        return hit, names[-1]
    cur = CATEGORY_MAP[c1]
    resolved_name = ""
    for name in names:
        children = _fetch_category_children(cur)
        if not children:
            break
        norm = name.replace(" ", "")
        match = next((c for c in children if c["name"] == name), None) \
            or next((c for c in children if c["name"].replace(" ", "") == norm), None)
        if not match:
            part = [c for c in children if norm in c["name"].replace(" ", "") or c["name"].replace(" ", "") in norm]
            match = part[0] if len(part) == 1 else None
        if not match:
            break  # 더 못 내려가면 지금까지 해석된 깊이 사용
        cur, resolved_name = match["cid"], match["name"]
    if cur == CATEGORY_MAP[c1] or not resolved_name:
        return None, ""
    _cat_cache_put(key, cur)
    logger.info(f"카테고리 코드 확인: {key} → {cur} ({resolved_name})")
    return cur, resolved_name


def _datalab_headers():
    return {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }


_quota_block_until = [0.0]  # 일일 한도(1000회) 소진 감지 시 자정(KST)까지 호출 중단 — epoch


def datalab_quota_exhausted() -> bool:
    """일일 한도 소진 상태인가 (자정 리셋 전까지 True)."""
    return time.time() < _quota_block_until[0]


def _mark_quota_exhausted():
    now = datetime.now()  # 컨테이너 TZ=Asia/Seoul
    reset_at = (now + timedelta(days=1)).replace(hour=0, minute=0, second=30, microsecond=0)
    _quota_block_until[0] = reset_at.timestamp()
    logger.warning(f"데이터랩 일일 한도 소진(010) — {reset_at}까지 호출 중단·안내 문구 전환")


def _datalab_post(endpoint: str, body: dict) -> dict:
    """데이터랩 API POST 호출 (공통) — 429(호출초과)/일시오류 시 백오프 재시도.
    제안서 enrich는 짧은 시간에 성별·연령·트렌드 등 여러 호출을 몰아치므로
    초당 제한에 걸려 빈값이 오던 문제 방지(다수 직원 동시 사용 대비).
    단 일일 한도 소진(errorCode 010)은 자정 전 재시도가 무의미 → 즉시 중단하고
    자정까지 호출 자체를 스킵(재시도 폭주·로그 홍수 방지, 2026-08-04 대표 지시)."""
    if datalab_quota_exhausted():
        return {}
    url = f"{DATALAB_BASE}/{endpoint}"
    for attempt in range(4):
        try:
            resp = requests.post(url, json=body, headers=_datalab_headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 429 and ('"errorCode":"010"' in resp.text or "Query limit exceeded" in resp.text or "쿼리 한도" in resp.text):
                _mark_quota_exhausted()
                return {}
            if resp.status_code == 429 and attempt < 3:
                wait = 0.8 * (attempt + 1)   # 0.8→1.6→2.4s — 초당 제한 버스트를 넘길 수 있게 강화
                logger.warning(f"Datalab {endpoint} 429 — {wait}s 후 재시도 ({attempt + 1}/4)")
                time.sleep(wait)
                continue
            logger.warning(f"Datalab API {endpoint} 응답 코드: {resp.status_code} — {resp.text[:200]}")
            return {}
        except Exception as e:
            logger.error(f"Datalab API {endpoint} 오류: {e}")
            if attempt < 3:
                time.sleep(0.5)
                continue
            return {}
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
    if total <= 0:
        # 응답은 왔지만 실데이터 없음(레이트리밋 등) — 50/50을 지어내지 않는다.
        # 빈값 반환 → 지표 캐시에 저장 안 됨 → 검수 재조회가 실데이터로 채움.
        return {}
    return {"male": round(male / total * 100, 1), "female": round(female / total * 100, 1)}


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

    # 응답은 왔지만 전 연령 0 = 실데이터 없음 — 0% 배열을 지어내지 않는다(검수 재조회 대상)
    if not age_data or sum(age_data.values()) <= 0:
        return {}

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
def get_trend_24m(keyword: str, category_code: str) -> dict:
    """최근 24개월 월별 검색 트렌드 (API 1건으로 트렌드+성장률 모두 커버)"""
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

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
    all_months = []
    for pt in points:
        period = pt.get("period", "")
        ratio = round(pt.get("ratio", 0), 1)
        try:
            dt = datetime.strptime(period, "%Y-%m-%d")
            label = f"{dt.month}월"
        except Exception:
            label = period
        all_months.append({"period": period, "label": label, "ratio": ratio})

    if not all_months:
        return {}

    # 프론트에 보낼 최근 12개월 (트렌드 차트용)
    recent_12 = all_months[-12:] if len(all_months) > 12 else all_months

    ratios = [m["ratio"] for m in recent_12]
    max_ratio = max(ratios)
    min_ratio = min(ratios)
    avg_ratio = round(sum(ratios) / len(ratios), 1)
    max_month = next(m["label"] for m in recent_12 if m["ratio"] == max_ratio)
    min_month = next(m["label"] for m in recent_12 if m["ratio"] == min_ratio)

    return {
        "months": recent_12,
        "allMonths": all_months,  # 성장률 계산용 (24개월 전체)
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

    # 전 요일 지수 0 = 실데이터 없음 — '최고 월요일(0)' 같은 허구 표시를 만들지 않는다
    if all(d["index"] <= 0 for d in days):
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
def get_yoy_growth_from_trend(trend_data: dict) -> dict:
    """24개월 트렌드 데이터에서 전년 동기 대비 성장률 계산 (API 호출 0건)"""
    all_months = trend_data.get("allMonths", [])
    if len(all_months) < 13:
        logger.warning(f"YoY 성장률: 데이터 부족 ({len(all_months)}개월, 최소 13개월 필요)")
        return {}

    # period를 datetime으로 변환
    month_map = {}
    for m in all_months:
        try:
            dt = datetime.strptime(m["period"], "%Y-%m-%d")
            month_map[dt.strftime("%Y-%m")] = m["ratio"]
        except Exception:
            continue

    now = datetime.now()
    periods = [
        {"label": "1개월", "months": 1},
        {"label": "3개월", "months": 3},
        {"label": "12개월", "months": 12},
    ]

    results = []
    peak = max(month_map.values()) if month_map else 0   # 연중 최고 지수(비수기 판정 기준)
    for p in periods:
        n = p["months"]
        cur_vals = []
        prev_vals = []
        # 캘린더 월 기준으로 버킷팅 (30일 근사는 월말 근처에서 월을 건너뛰거나 중복시킴)
        base_idx = now.year * 12 + (now.month - 1)
        for i in range(n):
            m_idx = base_idx - i
            y, mo = divmod(m_idx, 12)
            cur_key = f"{y:04d}-{mo + 1:02d}"
            if cur_key in month_map:
                cur_vals.append(month_map[cur_key])

            # 전년 동월 (윤년 무관 — 연도만 -1)
            prev_key = f"{y - 1:04d}-{mo + 1:02d}"
            if prev_key in month_map:
                prev_vals.append(month_map[prev_key])

        cur_avg = round(sum(cur_vals) / len(cur_vals), 1) if cur_vals else 0
        prev_avg = round(sum(prev_vals) / len(prev_vals), 1) if prev_vals else 0

        # 계절성 노이즈 방지: 기준/현재 지수가 연중 최고 대비 매우 낮으면(비수기) 성장률 %는
        # 미세 지수의 산물이라 오해를 부른다(예: 1.1→0 = -100%). 이 경우 reliable=false로 표시.
        low_signal = bool(peak) and (prev_avg < peak * 0.2 or cur_avg < peak * 0.2)
        if prev_avg > 0:
            growth = round((cur_avg - prev_avg) / prev_avg * 100, 1)
        else:
            growth = 0
            low_signal = True

        logger.info(f"YoY 성장률 {p['label']}: cur_avg={cur_avg}, prev_avg={prev_avg}, growth={growth}% low_signal={low_signal}")

        results.append({
            "label": p["label"],
            "currentAvg": cur_avg,
            "previousAvg": prev_avg,
            "growth": growth,
            "reliable": not low_signal,   # False면 비수기 미세지수 → 화면에서 '참고(비수기)'로 순화
        })

    # 현재 시점이 비수기인지(현재월 지수가 연중 최고 대비 낮음) — 화면 배너/맥락용
    cur_month_key = f"{now.year:04d}-{now.month:02d}"
    cur_month_idx = month_map.get(cur_month_key, 0)
    off_season = bool(peak) and cur_month_idx < peak * 0.3
    return {"periods": results, "offSeason": off_season, "currentIndex": cur_month_idx, "peakIndex": peak}


# ==================== 카테고리 인기 키워드 ====================
def get_category_popular_keywords(keyword: str, category_code: str, related_keywords: list = None,
                                  sub_cid: str = None, sub_name: str = "") -> dict:
    """카테고리 내 연관 키워드의 트렌드 비교 → 인기 + 급상승 분류.

    sub_cid(상품 중/소분류 코드)가 있으면 그 기준으로 먼저 산정 — 무관 키워드(예: '쌀 10kg')는
    그 카테고리 검색 비중이 0이라 자연 탈락한다(건의 2026-07, 실측 검증). 결과가 빈약하면
    (인기 3개 미만 또는 급상승 0건) 대분류 기준으로 폴백해 기존 동작을 보장한다
    (2026-07-20 '급상승 빈칸' 사고 재발 방지 — 어떤 경우에도 기존보다 나빠지지 않음)."""
    if not related_keywords or len(related_keywords) < 2:
        return {}

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_2m = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")

    # 최대 5개씩 비교 (API 제한: 한 번에 최대 5개 키워드)
    kw_list = related_keywords[:10]

    def _compute(code):
        popular, rising = [], []
        # 2번에 나눠서 호출 (5개씩) — 최근 2개월 한 번에 조회하여 전월 대비 성장률 계산
        for batch_start in range(0, len(kw_list), 5):
            batch = kw_list[batch_start:batch_start + 5]
            kw_params = [{"name": kw["keyword"], "param": [kw["keyword"]]} for kw in batch]
            body = {
                "startDate": start_2m, "endDate": end_date,
                "timeUnit": "month",
                "category": code,
                "keyword": kw_params,
            }
            data = _datalab_post("category/keywords", body)

            cur_map, prev_map = {}, {}
            if data and "results" in data:
                for r in data["results"]:
                    name = r.get("title", "")
                    pts = r.get("data", [])
                    if len(pts) >= 2:
                        cur_map[name] = pts[-1].get("ratio", 0)
                        prev_map[name] = pts[-2].get("ratio", 0)
                    elif len(pts) == 1:
                        cur_map[name] = pts[0].get("ratio", 0)

            for kw in batch:
                name = kw["keyword"]
                cur_val = cur_map.get(name, 0)
                prev_val = prev_map.get(name, 0)
                growth = round((cur_val - prev_val) / prev_val * 100, 1) if prev_val > 0 else 0
                entry = {
                    "keyword": name,
                    "volume": kw.get("totalVolume", 0),
                    "growth": growth,
                    "currentIndex": round(cur_val, 1),
                }
                popular.append(entry)
                if growth > 20:
                    rising.append(entry)

        popular.sort(key=lambda x: -x["currentIndex"])   # 인기: 현재 지수
        rising.sort(key=lambda x: -x["growth"])          # 급상승: 성장률
        return popular, rising

    # 1차: 상품 소분류 기준 — 카테고리 밖 키워드(지수 0)는 인기 목록에서 자연 제외
    if sub_cid:
        popular, rising = _compute(sub_cid)
        popular = [e for e in popular if e["currentIndex"] > 0]
        if len(popular) >= 3 and len(rising) >= 1:
            return {
                "popular": popular[:10],
                "rising": rising[:5],
                "basis": sub_name,
                "note": f"🔎 '{sub_name}' 카테고리 기준 인기·급상승 키워드입니다. "
                        f"급상승 키워드를 상품명 · 태그에 반영하면 시즌 트렌드 수혜를 빠르게 받을 수 있습니다.",
            }
        logger.info(f"카테고리 키워드: '{sub_name}' 기준 빈약(인기 {len(popular)}·급상승 {len(rising)}) → 대분류 폴백")

    # 2차(기본): 대분류 기준 — 기존 동작 그대로
    popular, rising = _compute(category_code)
    return {
        "popular": popular[:10],
        "rising": rising[:5],
    }


# ==================== 통합 분석 함수 ====================
def analyze_datalab(keyword: str, category1: str = "", related_keywords: list = None,
                    category2: str = "", category3: str = "") -> dict:
    """모든 데이터랩 분석을 한 번에 실행 (지표별 1시간 TTL 캐시).

    ★ 지표별 개별 캐시(2026-07 검수 시스템): 성공한 지표는 보존하고 실패(빈값) 지표만
      다음 호출에서 재조회한다 → 검수 재조회 시 성공분은 API를 다시 쓰지 않아
      쿼터 낭비 없이 실데이터를 채울 수 있다. (기존 '전체 캐시'는 성별·연령이 빠지면
      성공한 트렌드까지 통째로 버려 재실행마다 쿼터를 태우는 악순환이 있었음.)"""
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("데이터랩: 네이버 API 키 미설정")
        return {}

    cat_code = _find_category_code(category1)
    kbase = f"{keyword}|{cat_code}"
    logger.info(f"데이터랩 분석 시작: keyword={keyword}, category={category1}→{cat_code}")

    _paced = [False]

    def _cached(mkey, fetch):
        """지표 캐시 우선, 미스면 호출. 연속 실호출 사이 간격(0.25s)으로 429 버스트 예방.
        성공(truthy)만 캐시 — 실패는 다음 호출에서 자동 재조회."""
        hit = _cache_get(mkey)
        if hit is not None:
            return hit
        if _paced[0]:
            time.sleep(0.25)
        _paced[0] = True
        val = fetch()
        if val:
            _cache_set(mkey, val)
        return val

    result = {}

    # 1. 성별 비율
    try:
        gender = _cached(kbase + "#gender", lambda: get_gender_ratio(keyword, cat_code))
        if gender:
            result["gender"] = gender
    except Exception as e:
        logger.error(f"데이터랩 성별 오류: {e}")

    # 2. 연령대별 비율
    try:
        age = _cached(kbase + "#age", lambda: get_age_ratio(keyword, cat_code))
        if age:
            result["age"] = age
    except Exception as e:
        logger.error(f"데이터랩 연령대 오류: {e}")

    # 3. 24개월 트렌드 (트렌드 차트 + 성장률 + 시즌 모두 커버, API 1건)
    trend_raw = None
    try:
        trend_raw = _cached(kbase + "#trend", lambda: get_trend_24m(keyword, cat_code))
        if trend_raw:
            # 프론트에는 allMonths 제외 (내부 성장률 계산용)
            result["trend"] = {k: v for k, v in trend_raw.items() if k != "allMonths"}
    except Exception as e:
        logger.error(f"데이터랩 트렌드 오류: {e}")

    # 4. 시즌별 수요 예측 (트렌드 데이터 기반, API 0건)
    if trend_raw:
        try:
            season = get_season_prediction(trend_raw)
            if season:
                result["season"] = season
        except Exception as e:
            logger.error(f"데이터랩 시즌 오류: {e}")

    # 5. 요일별 검색 패턴
    try:
        weekday = _cached(kbase + "#weekday", lambda: get_weekday_pattern(keyword, cat_code))
        if weekday:
            result["weekday"] = weekday
    except Exception as e:
        logger.error(f"데이터랩 요일 오류: {e}")

    # 6. 전년 동기 대비 성장률 (24개월 트렌드에서 계산, API 0건)
    if trend_raw:
        try:
            growth = get_yoy_growth_from_trend(trend_raw)
            if growth:
                result["growth"] = growth
        except Exception as e:
            logger.error(f"데이터랩 성장률 오류: {e}")

    # 7. 카테고리 인기 키워드 (키에 중/소분류·연관키워드 반영)
    if related_keywords:
        try:
            ck_key = _cache_key(keyword, "|".join([category1 or "", category2 or "", category3 or ""]),
                                related_keywords) + "#catkw"

            def _fetch_catkw():
                sub_cid, sub_name = _resolve_subcategory_cid(category1, category2, category3)
                return get_category_popular_keywords(keyword, cat_code, related_keywords,
                                                     sub_cid=sub_cid, sub_name=sub_name)

            cat_kw = _cached(ck_key, _fetch_catkw)
            if cat_kw:
                result["categoryKeywords"] = cat_kw
        except Exception as e:
            logger.error(f"데이터랩 카테고리 키워드 오류: {e}")

    # 한도 소진 안내 — 가산 필드(quotaNotice)라 기존 소비자(전산 ①·제안서) 무영향.
    # 캐시로 이미 확보된 지표는 그대로 표시되고, 빈 지표의 사유만 화면에 안내한다.
    if datalab_quota_exhausted():
        result["quotaNotice"] = ("네이버 데이터랩 일일 호출 한도(1,000회)가 소진되어 일부 지표를 새로 불러올 수 없습니다. "
                                 "한도는 매일 자정에 자동 초기화됩니다. 이미 수집된 지표는 정상 표시됩니다.")

    logger.info(f"데이터랩 분석 완료: {list(result.keys())}")
    return result


# ============================================================
# 통합검색어 트렌드 (/v1/datalab/search) — 플레이스(지역 업종) 전용 (2026-08-11)
# ============================================================
# ⚠️ 위 지표들이 쓰는 `DATALAB_BASE` 는 **쇼핑인사이트**라 요청에 쇼핑 카테고리 코드가
#    반드시 들어간다 → 카페·미용·병원 같은 오프라인 업종에는 쓸 수 없다(코드 자체가 없음).
#    통합검색어 트렌드는 **키워드만으로** 조회되므로 플레이스에 그대로 적용된다.
#    같은 계정·같은 일일 한도(1,000회)를 공유하므로 소진 가드(`datalab_quota_exhausted`)를
#    그대로 재사용하고, 실패·소진 시에는 전부 {} 를 돌려 화면이 그 카드만 생략하게 한다.
#
# 호출 예산(키워드 1개당, 캐시 미적중 시): 추이 1 + 요일 1 + 성별 2 + 연령 4 = **8회**.
# 캐시(1시간)에 걸리면 0회. 소진 상태면 첫 호출에서 즉시 빠져나온다.

DATALAB_SEARCH_URL = "https://openapi.naver.com/v1/datalab/search"

# 안전 밸브 — 일일 한도가 빠듯해지면 재배포 없이 서버 .env 에서 끌 수 있다.
# (`PORTAL_SEO_AUTO_ENABLED` 선례. 끄면 검색 트렌드 카드만 조용히 사라지고 나머지는 그대로)
PLACE_TREND_ENABLED = os.getenv("PLACE_TREND_ENABLED", "true").strip().lower() not in ("false", "0", "off", "no")

_WEEKDAY_LABEL = ["월", "화", "수", "목", "금", "토", "일"]


# 이 앱 키에 「통합검색어 트렌드」 사용 권한(스코프)이 없으면 401 errorCode 024 가 온다.
# 재시도해도 소용없고, 한 번의 분석에 2콜이 전부 401 로 낭비되므로 프로세스 수명 동안 끈다.
# (2026-08-11 실측: "Scope Status Invalid : Authentication failed." — 네이버 개발자센터에서
#  해당 앱에 데이터랩 검색어트렌드 API 를 추가 등록하면 해제된다. 등록 후엔 재기동만 하면 됨)
_search_scope_denied = [False]


def _datalab_search_headers():
    """통합검색어 트렌드 전용 헤더 — 쇼핑인사이트와 **다른 앱 키**를 쓸 수 있다."""
    return {
        "X-Naver-Client-Id": DATALAB_SEARCH_CLIENT_ID,
        "X-Naver-Client-Secret": DATALAB_SEARCH_CLIENT_SECRET,
        "Content-Type": "application/json",
    }


def datalab_search_uses_separate_key() -> bool:
    """트렌드가 별도 앱 키를 쓰는 중인가(진단·로그용 — 키 값은 노출하지 않는다)."""
    return bool(os.getenv("DATALAB_SEARCH_CLIENT_ID", "").strip())


def _datalab_search_post(body: dict) -> dict:
    """통합검색어 트렌드 POST — 쇼핑인사이트와 동일한 한도 가드·백오프를 공유한다."""
    if datalab_quota_exhausted() or _search_scope_denied[0]:
        return {}
    for attempt in range(3):
        try:
            resp = requests.post(DATALAB_SEARCH_URL, json=body, headers=_datalab_search_headers(), timeout=10)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                if not _search_scope_denied[0]:
                    _search_scope_denied[0] = True
                    _which = ("DATALAB_SEARCH_CLIENT_ID(전용 키)"
                              if datalab_search_uses_separate_key() else "NAVER_CLIENT_ID(기본 키)")
                    logger.warning(
                        f"데이터랩 통합검색어 트렌드 권한 없음 — 지금 쓰는 {_which} 앱에 해당 API 가 등록돼 있지 않습니다. "
                        "네이버는 이 API 의 신규 등록을 막아둔 상태라, **이미 등록된 앱**의 키를 "
                        "DATALAB_SEARCH_CLIENT_ID / DATALAB_SEARCH_CLIENT_SECRET 로 넣고 재기동해야 켜집니다. "
                        f"(응답: {resp.text[:120]})")
                return {}
            if resp.status_code == 429 and ('"errorCode":"010"' in resp.text
                                            or "Query limit exceeded" in resp.text
                                            or "쿼리 한도" in resp.text):
                _mark_quota_exhausted()
                return {}
            if resp.status_code == 429 and attempt < 2:
                time.sleep(0.8 * (attempt + 1))
                continue
            logger.warning(f"Datalab search 응답 코드: {resp.status_code} — {resp.text[:200]}")
            return {}
        except Exception as e:
            logger.error(f"Datalab search 오류: {e}")
            if attempt < 2:
                time.sleep(0.5)
                continue
            return {}
    return {}


def _search_body(keyword: str, start: str, end: str, time_unit: str,
                 gender: str = "", ages=None) -> dict:
    body = {
        "startDate": start, "endDate": end, "timeUnit": time_unit,
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}],
    }
    if gender:
        body["gender"] = gender
    if ages:
        body["ages"] = list(ages)
    return body


def _search_points(data: dict) -> list:
    """응답 → [{period, ratio}] (없으면 [])"""
    try:
        results = (data or {}).get("results") or []
        if not results:
            return []
        return [{"period": p.get("period", ""), "ratio": float(p.get("ratio") or 0)}
                for p in (results[0].get("data") or [])]
    except Exception:
        return []


def _search_sum(data: dict) -> float:
    return round(sum(p["ratio"] for p in _search_points(data)), 2)


def get_search_trend(keyword: str) -> dict:
    """플레이스용 검색 수요 — 최근 12개월 추이 · 성수기/비수기 · 요일 패턴.

    반환(전 필드 optional — 없으면 그 축을 화면이 생략):
      {"keyword", "months":[{period,label,ratio}], "peakMonth","lowMonth","yoyRate",
       "weekdays":[{label,ratio}], "peakWeekday"}
    실패·한도 소진·키 미설정 시 {}(카드 자체를 렌더하지 않는다)."""
    kw = (keyword or "").strip()
    if not PLACE_TREND_ENABLED:
        return {}
    if not kw or not DATALAB_SEARCH_CLIENT_ID or not DATALAB_SEARCH_CLIENT_SECRET:
        return {}
    if datalab_quota_exhausted():
        return {}

    ck = f"placetrend|{kw}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached

    today = datetime.now()
    out = {"keyword": kw}

    # ① 최근 13개월 월별 추이 — 12개월 표시 + 전년 동월 대비 성장률
    try:
        start13 = (today - timedelta(days=395)).strftime("%Y-%m-01")
        pts = _search_points(_datalab_search_post(
            _search_body(kw, start13, today.strftime("%Y-%m-%d"), "month")))
        months = []
        for p in pts:
            try:
                dt = datetime.strptime(p["period"], "%Y-%m-%d")
                label = f"{dt.month}월"
            except Exception:
                label = p["period"]
            months.append({"period": p["period"], "label": label, "ratio": round(p["ratio"], 1)})
        if months:
            recent = months[-12:]
            out["months"] = recent
            top = max(recent, key=lambda m: m["ratio"])
            bot = min(recent, key=lambda m: m["ratio"])
            # 전 구간이 같은 값이면 성수기라 부를 수 없다(비교 대상 없음).
            if top["ratio"] > bot["ratio"]:
                out["peakMonth"] = top["label"]
                out["lowMonth"] = bot["label"]
            if len(months) >= 13 and months[-13]["ratio"] > 0:
                out["yoyRate"] = round((months[-1]["ratio"] - months[-13]["ratio"])
                                       / months[-13]["ratio"] * 100, 1)
    except Exception as e:
        logger.warning(f"[검색트렌드] 월별 추이 실패(무시): {e}")

    # ② 요일 패턴 — 최근 12주 일별을 요일로 접는다
    try:
        start90 = (today - timedelta(days=84)).strftime("%Y-%m-%d")
        pts = _search_points(_datalab_search_post(
            _search_body(kw, start90, today.strftime("%Y-%m-%d"), "date")))
        buckets = defaultdict(list)
        for p in pts:
            try:
                dt = datetime.strptime(p["period"], "%Y-%m-%d")
            except Exception:
                continue
            buckets[dt.weekday()].append(p["ratio"])
        if buckets:
            wk = []
            for i in range(7):
                vals = buckets.get(i) or []
                if vals:
                    wk.append({"label": _WEEKDAY_LABEL[i], "ratio": round(sum(vals) / len(vals), 1)})
            if wk:
                out["weekdays"] = wk
                hi = max(wk, key=lambda x: x["ratio"])
                lo = min(wk, key=lambda x: x["ratio"])
                if hi["ratio"] > lo["ratio"]:
                    out["peakWeekday"] = hi["label"]
    except Exception as e:
        logger.warning(f"[검색트렌드] 요일 패턴 실패(무시): {e}")

    # ⚠️ 성별·연령 축은 **의도적으로 없다**(2026-08-11 실측으로 폐기).
    # 통합검색어 트렌드는 **요청 단위로 최대값을 100 으로 정규화**해 돌려준다 —
    # 같은 구간을 필터만 바꿔 7회 호출한 결과가 전부 max=100·합계 326~333 이었다
    # (필터없음 326.0 / 남 326.8 / 여 329.3 / 20대 326.7 / 30대 326.9 / 40대 333.0 / 50대+ 327.7).
    # 즉 남/여, 연령대끼리는 **서로 다른 자로 잰 값**이라 나눠도 늘 균등(50:50, 25×4)이 나온다.
    # 그 값을 「주 이용층」이라 적어 사장님께 내보내는 건 실측을 가장한 허수이므로 축 자체를 뺐다.
    # (덤으로 키워드당 호출이 8회 → 2회로 줄어 일일 한도 부담도 크게 준다.)
    # 되살리려면 「한 응답 안에서 성별·연령 비중이 함께 오는」 다른 원천이 필요하다.

    # 아무 축도 못 채웠으면 카드를 만들지 않는다(빈 껍데기 렌더 방지).
    if not any(k in out for k in ("months", "weekdays")):
        return {}
    _cache_set(ck, out)
    return out
