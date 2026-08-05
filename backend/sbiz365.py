# -*- coding: utf-8 -*-
"""
sbiz365.py — 소상공인365(bigdata.sbiz.or.kr) 상권 데이터 클라이언트 (맞춤제안서 상권 블록용)

- 대상은 포털 SPA 가 내부적으로 쓰는 JSON 경로(비공식 — 공식 오픈API 는 certKey iframe 임베드라
  수치 추출 불가). 언제든 형태가 바뀔 수 있으므로 전 구간 try/except 로 감싸고,
  어떤 실패도 None/부분 null 로 강등한다(로그는 warning 1줄). 재시도 없음·타임아웃 8초.
  → 제안서는 sbiz 블록이 None 이면 상권 섹션을 조용히 생략(플레이스 추적 폴백 선례와 동일).
- 키는 서버 .env 의 SBIZ365_KEY_*(전부 선택). SIMPLE 키가 없으면 모듈 전체 조용히 비활성
  — get_place_sbiz() 가 항상 None(기존 경로 무회귀).
- 신규 모듈·신규 캐시 테이블(sbiz_cache)만 추가하는 순수 additive.
  기존 쇼핑/플레이스 경로·전산(①) 소비 계약(portal-summary·seo/analyze 등)과 무접점.
"""
import os
import json
import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

_BASE = "https://bigdata.sbiz.or.kr"
_TIMEOUT = 8  # 초 — 재시도 없음(제안서 생성 흐름을 붙들지 않게)

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Referer": "https://bigdata.sbiz.or.kr/",
    "Accept": "application/json, text/plain, */*",
}

# 캐시 TTL — (행정동×업종) 데이터 14일 · 업종 트리 30일
SBIZ_CACHE_TTL = 14 * 24 * 3600
SBIZ_TREE_TTL = 30 * 24 * 3600


def _env_keys() -> dict:
    """서비스별 인증키(certKey) — 전부 선택. SIMPLE 외 5종은 후속 차수(상세분석·매출추이·
    업소현황·SNS·테마상권) 자리로, 지금은 읽기만 하고 사용하지 않는다."""
    return {
        "simple": os.getenv("SBIZ365_KEY_SIMPLE", "").strip(),
        "detail": os.getenv("SBIZ365_KEY_DETAIL", "").strip(),   # 상세분석(analyNo 발급 필요 — 2단계)
        "slsidx": os.getenv("SBIZ365_KEY_SLSIDX", "").strip(),   # 점포당 매출액 추이(salesSeries 예정)
        "stor":   os.getenv("SBIZ365_KEY_STOR", "").strip(),     # 업소현황(shops 예정)
        "sns":    os.getenv("SBIZ365_KEY_SNS", "").strip(),      # SNS 분석(sns 예정)
        "theme":  os.getenv("SBIZ365_KEY_THEME", "").strip(),    # 테마상권 분석(theme 예정)
        # 공공데이터포털 「소상공인시장진흥공단_상가(상권)정보」 — 행정동코드 매핑 전용
        # (소상공인365 내부 좌표→행정동 경로가 전부 막혀 이 공식 REST 로 대체·2026-08-05 검증)
        "datago": os.getenv("SBIZ_DATA_GO_KR_KEY", "").strip(),
    }


# ============================================================
# 1. HTTP — 단일 진입점(오프라인 테스트의 monkeypatch 지점)
# ============================================================
def _http_json(method: str, url: str, params=None, data=None):
    """비공식 JSON 호출. 실패는 어떤 형태든 None + warning 1줄."""
    try:
        if str(method).upper() == "POST":
            resp = requests.post(url, params=params, data=data,
                                 headers=_HEADERS, timeout=_TIMEOUT)
        else:
            resp = requests.get(url, params=params,
                                headers=_HEADERS, timeout=_TIMEOUT)
        if resp.status_code != 200:
            logger.warning(f"[sbiz365] HTTP {resp.status_code}: {url}")
            return None
        return resp.json()
    except Exception as e:
        logger.warning(f"[sbiz365] 요청 실패({url}): {e}")
        return None


# ============================================================
# 2. 캐시 — database.py 의 SQLite 연결 재사용, sbiz_cache 테이블 lazy 생성
#    (기존 init_db 를 건드리지 않는 additive 선택 — CREATE TABLE IF NOT EXISTS 멱등)
# ============================================================
_cache_table_ready = False


def _cache_conn():
    from database import _get_conn  # 지연 import — 모듈 로드 순서·테스트 격리
    global _cache_table_ready
    conn = _get_conn()
    if not _cache_table_ready:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sbiz_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT,
                fetched_at TEXT
            )
        """)
        conn.commit()
        _cache_table_ready = True
    return conn


def _cache_get(key: str, ttl_seconds: int):
    try:
        conn = _cache_conn()
        row = conn.execute(
            "SELECT payload, fetched_at FROM sbiz_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        fetched = datetime.fromisoformat(row["fetched_at"])
        if (datetime.now() - fetched).total_seconds() > ttl_seconds:
            return None
        return json.loads(row["payload"])
    except Exception as e:
        logger.warning(f"[sbiz365] 캐시 조회 실패(무시): {e}")
        return None


def _cache_put(key: str, payload):
    try:
        conn = _cache_conn()
        conn.execute(
            "INSERT OR REPLACE INTO sbiz_cache (cache_key, payload, fetched_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[sbiz365] 캐시 저장 실패(무시): {e}")


# ============================================================
# 3. 숫자·응답 파싱 유틸
# ============================================================
def _num(v):
    """'1,234'·'3.2'·정수 → float. 실패/빈값 → None."""
    if v is None:
        return None
    try:
        s = str(v).replace(",", "").strip()
        if not s or s in ("-", "null", "None"):
            return None
        return float(s)
    except Exception:
        return None


def _int_or_none(v):
    n = _num(v)
    return int(round(n)) if n is not None else None


def _won(v):
    """천원 단위 → 원 단위 정수. 실패 시 None."""
    n = _num(v)
    return int(round(n * 1000)) if n is not None else None


def _pick(resp, markers):
    """비공식 응답의 래핑 편차 흡수 — markers 중 하나를 가진 dict 를 얕게(1단계) 탐색."""
    if not isinstance(resp, dict):
        return None
    if any(m in resp for m in markers):
        return resp
    for v in resp.values():
        if isinstance(v, dict) and any(m in v for m in markers):
            return v
    return None


# ============================================================
# 4. 행정동 매칭 체인 — 지역명 → 좌표 → admiCd(행정동 8자리)
# ============================================================
def _region_coord(region: str):
    """「지역명」 → 좌표(경도, 위도). 네이버 지역검색(local) 사용 — 이미 보유한 자격 재사용.
    mapx/mapy 는 WGS84×10^7 정수라 10^7 로 나눈다. 실패 시 None."""
    cid = os.getenv("NAVER_CLIENT_ID", "").strip()
    csec = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not (cid and csec and region):
        return None
    try:
        import urllib.parse
        import urllib.request
        url = ("https://openapi.naver.com/v1/search/local.json?"
               + urllib.parse.urlencode({"query": region, "display": 1}))
        req = urllib.request.Request(url, headers={
            "X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        items = data.get("items") or []
        if not items:
            return None
        mx, my = items[0].get("mapx"), items[0].get("mapy")
        if mx is None or my is None:
            return None
        x, y = float(mx), float(my)
        if x > 1000:            # WGS84×10^7 정수 형식
            x, y = x / 1e7, y / 1e7
        return x, y
    except Exception as e:
        logger.warning(f"[sbiz365] 좌표 확보 실패(무시): {e}")
        return None


def _coord_to_admi(x, y):
    """좌표 → 행정동(admiCd 8자리).
    ⚠️ 2026-08-05 실측: 소상공인365 내부 `getCoordToAdmPoint.json` 은 500, 다른 후보 경로도 전부 404.
    → **공공데이터포털 「소상공인시장진흥공단_상가(상권)정보」 공식 REST** 로 확보한다.
    반경 안 상가 1건만 받아 그 업소의 `adongCd`(행정동코드)를 읽는 방식(검증 완료:
    강남역 반경 500m → adongCd 11650531 서초4동). 인증키는 **인코딩 키를 그대로** 붙인다
    (디코딩 키를 재인코딩하면 403)."""
    key = _env_keys()["datago"]
    if not key:
        return None
    import urllib.parse
    import urllib.request
    base = "http://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius"
    for radius in ("500", "1000", "2000"):     # 외곽 지역은 반경을 넓혀 재시도
        try:
            qs = urllib.parse.urlencode({"radius": radius, "cx": x, "cy": y,
                                         "type": "json", "numOfRows": "1", "pageNo": "1"})
            url = f"{base}?serviceKey={key}&{qs}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            items = ((data.get("body") or {}).get("items")) or []
            if not items:
                continue
            it = items[0]
            admi_cd = str(it.get("adongCd") or "").strip()
            if len(admi_cd) == 8:
                return {"admiCd": admi_cd,
                        "admiNm": it.get("adongNm"),
                        "guNm": it.get("signguNm")}
        except Exception as e:
            logger.warning(f"[sbiz365] 행정동 조회 실패(radius={radius}·무시): {e}")
    return None


def _resolve_admi(region: str):
    """지역명 → 행정동. 결과는 (행정동×업종) 데이터와 같은 TTL 로 캐시해
    캐시 적중 시 좌표·행정동 변환 재호출을 없앤다. 실패 시 None."""
    cache_key = f"sbiz:admi:{_norm(region)}"
    cached = _cache_get(cache_key, SBIZ_CACHE_TTL)
    if cached:
        return cached
    coord = _region_coord(region)
    if not coord:
        return None
    admi = _coord_to_admi(coord[0], coord[1])
    if admi:
        _cache_put(cache_key, admi)
    return admi


def _norm(s):
    return "".join(str(s or "").split()).lower()


# ============================================================
# 5. 업종 매핑 — 계층 업종 트리(30일 캐시)에서 소분류 코드 1개 선택
# ============================================================
# 제안서 오프라인 업종 라벨 → 트리 이름 부분일치 검색어(순서 = 우선순위)
_UPJONG_SEARCH_TERMS = {
    "음식점": ["음식점", "한식"],
    "카페": ["카페", "커피"],
    "디저트": ["디저트", "제과", "카페"],
    "베이커리": ["제과", "제빵", "베이커리"],
    "제과": ["제과", "제빵"],
    "분식": ["분식"],
    "주점": ["주점", "호프"],
    "바": ["주점", "호프"],
    "미용": ["미용", "헤어"],
    "뷰티": ["미용", "피부"],
    "네일": ["네일"],
    "에스테틱": ["피부", "에스테틱"],
    "병원": ["병원", "의원"],
    "의원": ["의원", "병원"],
    "약국": ["약국"],
    "건강": ["건강", "의원"],
    "헬스": ["헬스", "체력단련", "스포츠"],
    "피트니스": ["헬스", "체력단련", "스포츠"],
    "필라테스": ["필라테스", "요가"],
    "학원": ["학원"],
    "교육": ["학원", "교육"],
    "반려동물": ["애완", "반려", "동물"],
    "숙박": ["숙박", "호텔", "여관"],
    "펜션": ["펜션", "숙박"],
}


def _flatten_upjong(node, out):
    """업종 목록 → (code, name) 쌍. 실측 형식(2026-08-05 검증):
      [{"upjong3cd": "I21007", "tpbiznm": "음식 > 기타 간이 > 김밥/만두/분식"}, ...] 247건 평탄 리스트.
    tpbiznm 은 '대 > 중 > 소' 경로라 마지막 조각이 소분류명. 다른 키 이름 편차도 흡수한다."""
    if isinstance(node, list):
        for v in node:
            _flatten_upjong(v, out)
        return
    if not isinstance(node, dict):
        return
    code = None
    for k in ("upjong3cd", "upjong3Cd", "upjongCd", "code"):
        v = node.get(k)
        if isinstance(v, (str, int)) and str(v).strip():
            code = str(v).strip()
            break
    name = None
    for k in ("tpbiznm", "tpbizNm", "upjong3nm", "upjong3Nm", "name"):
        v = node.get(k)
        if isinstance(v, str) and v.strip():
            name = v.strip()
            break
    if code and name:
        out.append((code, name))
    for v in node.values():           # 중첩 구조도 대비(현 응답은 평탄)
        if isinstance(v, (dict, list)):
            _flatten_upjong(v, out)


def _upjong_pairs():
    """계층 업종 코드 트리 1회 호출 → (code, name) 쌍 목록. 30일 캐시. 실패 시 None."""
    cached = _cache_get("sbiz:upjong-tree", SBIZ_TREE_TTL)
    if cached:
        return [tuple(p) for p in cached]
    resp = _http_json("GET", f"{_BASE}/gis/api/getHierarchyTpbizCode",
                      params={"certKey": _env_keys()["simple"]})
    if resp is None:
        return None
    out = []
    try:
        _flatten_upjong(resp, out)
    except Exception as e:
        logger.warning(f"[sbiz365] 업종 트리 평탄화 실패(무시): {e}")
        return None
    pairs = list(dict.fromkeys(out))  # 중복 제거(순서 보존)
    if pairs:
        _cache_put("sbiz:upjong-tree", [list(p) for p in pairs])
    return pairs or None


def _resolve_upjong(industry_label: str):
    """업종 라벨 → 트리 소분류 코드 1개. 이름 부분일치, 매칭 중 코드가 가장 긴 항목
    (= 가장 깊은 분류)을 택한다. 실패 시 None."""
    label = (industry_label or "").strip()
    if not label:
        return None
    pairs = _upjong_pairs()
    if not pairs:
        return None
    terms = []
    for lk, ts in _UPJONG_SEARCH_TERMS.items():
        if lk in label or label in lk:
            terms.extend(ts)
    terms.append(label)  # 사전 미등재 라벨은 라벨 자체 부분일치 폴백
    for term in terms:
        if not term:
            continue
        hits = [(c, n) for c, n in pairs if term in n]
        if hits:
            hits.sort(key=lambda p: (len(p[0]), p[0]))
            code, name = hits[-1]
            return {"code": code, "name": name}
    return None


# ============================================================
# 6. 간단분석 조회 — 평균 매출(getAvgAmtInfo) + 유동인구(getPopularInfo)
# ============================================================
def _fetch_avg(admi_cd: str, upjong_cd: str, simple_loc: str):
    """행정동×업종 상권 정보. **GET 전용**(POST 는 500 — 2026-08-05 실측).
    실측 확인 필드(강남구 역삼1동×I21201 표본):
      saleAmt/maxAmt/minAmt/saleCnt(천원·건) · guAmt/siAmt(구·시 평균 = 벤치마크)
      prevMon*/prevYear*(증감) · avgList(월별 시계열) · storeCntAdmin(행정동 업소수 시계열)
      storeCnt(시도·시군구 업소수) · topFive(업종 상위 5개 행정동 + dayAvg 유동인구)
      upjongTypeMap(업종명) · analyNo · amtStdYm/storeStdYm(기준연월) · baemin
    전 필드 optional — 실패 시 None."""
    key = _env_keys()["simple"]
    resp = _http_json("GET", f"{_BASE}/gis/simpleAnls/getAvgAmtInfo.json",
                      params={"admiCd": admi_cd, "upjongCd": upjong_cd,
                              "simpleLoc": simple_loc, "certKey": key})
    body = _pick(resp, ("saleAmt", "avgList", "analyNo"))
    if body is None:
        return None

    def _arr(v):
        return v if isinstance(v, list) else []

    # 월별 매출 시계열 — [{crtrYm, saleAmt(천원)}] 최신순으로 오는 걸 과거→최신으로 정렬
    series = []
    for row in _arr(body.get("avgList")):
        if not isinstance(row, dict):
            continue
        ym, amt = row.get("crtrYm"), _num(row.get("saleAmt"))
        if ym and amt is not None:
            series.append({"ym": str(ym), "amt": amt})
    series.sort(key=lambda r: r["ym"])

    # 행정동 업소수 시계열 — storeCntAdmin: [{storeCnt, areaGb:'13'(행정동), yymm}]
    shop_series = []
    for row in _arr(body.get("storeCntAdmin")):
        if not isinstance(row, dict):
            continue
        ym, cnt = row.get("yymm"), _int_or_none(row.get("storeCnt"))
        if ym and cnt is not None:
            shop_series.append({"ym": str(ym), "cnt": cnt})
    shop_series.sort(key=lambda r: r["ym"])

    # 업종 상위 5개 행정동(전국) — 우리 행정동이 포함되면 그 dayAvg(유동인구)를 쓴다
    top5, day_avg = [], None
    for row in _arr(body.get("topFive")):
        if not isinstance(row, dict):
            continue
        item = {"admiCd": str(row.get("admiCd") or ""), "admiNm": row.get("admiNm"),
                "ctyNm": row.get("ctyNm"), "megaNm": row.get("megaNm"),
                "saleAmt": _num(row.get("saleAmt")), "storeCnt": _int_or_none(row.get("storeCnt")),
                "dayAvg": _int_or_none(row.get("dayAvg"))}
        top5.append(item)
        if item["admiCd"] and item["admiCd"] == str(admi_cd) and item["dayAvg"] is not None:
            day_avg = item["dayAvg"]

    up_map = body.get("upjongTypeMap") if isinstance(body.get("upjongTypeMap"), dict) else {}

    return {
        "saleAmt": _num(body.get("saleAmt")),              # 점포당 월평균(천원)
        "maxAmt": _num(body.get("maxAmt")),
        "minAmt": _num(body.get("minAmt")),
        "saleCnt": _num(body.get("saleCnt")),              # 행정동 업소수(=storeCntAdmin 최신)
        "guAmt": _num(body.get("guAmt")),                  # 시군구 평균(천원) — 벤치마크
        "siAmt": _num(body.get("siAmt")),                  # 시도 평균(천원) — 벤치마크
        "prevMonRate": _num(body.get("prevMonRate")),
        "prevYearRate": _num(body.get("prevYearRate")),
        "prevMonCntRate": _num(body.get("prevMonCntRate")),
        "prevYearCntRate": _num(body.get("prevYearCntRate")),
        "series": series,                                  # [{ym, amt(천원)}]
        "shopSeries": shop_series,                         # [{ym, cnt}]
        "topFive": top5,
        "dayAvg": day_avg,                                 # 우리 행정동이 top5 에 있을 때만
        "upjongNm": up_map.get("upjong3nm"),
        "baemin": body.get("baemin"),
        "analyNo": body.get("analyNo"),
        "stdYm": str(body.get("amtStdYm") or body.get("stdYmCh") or "").strip() or None,
        "storeStdYm": str(body.get("storeStdYm") or "").strip() or None,
    }


def _fetch_popular(admi_cd: str, upjong_cd: str, analy_no):
    """행정동 유동인구 상세.
    ⚠️ 2026-08-05 실측: `/gis/simpleAnls/getPopularInfo.json` 은 파라미터 조합 5종 전부 HTTP 500
    (admiCd만 / +upjongCd / +simpleLoc / +analyNo / +path). 포털 내부 경로가 바뀐 것으로 보여
    **현재는 사용하지 않는다**. 유동인구는 getAvgAmtInfo 의 topFive[].dayAvg 로 부분 확보하고,
    시간대·요일 분해는 미확보(2단계 — 상세분석 축 또는 경로 재확인 후).
    이 함수는 경로가 되살아났을 때를 위해 남겨두되 항상 None 을 반환한다."""
    return None


def get_place_sbiz(region: str, industry_label: str) -> dict | None:
    """지역명×업종 라벨 → 상권 데이터 블록(제안서 sbiz).
    반환 스키마(전 필드 optional·없으면 null) — FE 5차 배선이 이 스키마에 고정:
      {"source":"sbiz365-simple", "baseYm", "district":{admiCd,admiNm,guNm},
       "sales":{avgAmt(원),minAmt,maxAmt,cnt,momRate,yoyRate},
       "traffic":{dayAvg,hours[6],days[7],weekendShare}|null,
       "shops":null, "sns":null, "theme":null, "salesSeries":null}
    shops(업소현황)·sns(SNS 분석)·theme(테마상권)·salesSeries(매출 추이)는
    실응답 검증 후 채울 자리 — 지금은 항상 null.
    SIMPLE 키 미설정·매칭 실패·API 파손 등 어떤 실패도 None(제안서 상권 블록 생략)."""
    try:
        if not _env_keys()["simple"]:
            return None  # 키 미설정 → 모듈 전체 조용히 비활성
        region = (region or "").strip()
        label = (industry_label or "").strip()
        if not region or not label:
            return None

        admi = _resolve_admi(region)
        if not admi or not admi.get("admiCd"):
            return None
        upjong = _resolve_upjong(label)
        if not upjong:
            return None

        cache_key = f"sbiz:simple:{admi['admiCd']}|{upjong['code']}"
        cached = _cache_get(cache_key, SBIZ_CACHE_TTL)
        if cached is not None:
            return cached

        avg = _fetch_avg(admi["admiCd"], upjong["code"], region)
        if avg is None:
            return None
        pop = _fetch_popular(admi["admiCd"], upjong["code"], avg.get("analyNo"))

        # 유동인구: topFive 에 우리 행정동이 있으면 dayAvg 확보(없으면 null — 가짜 값 금지)
        traffic = None
        if avg.get("dayAvg") is not None:
            traffic = {"dayAvg": avg["dayAvg"], "hours": None, "days": None, "weekendShare": None}

        # 업소수: 행정동 최신값(saleCnt) 우선, 없으면 shopSeries 마지막
        shop_cnt = _int_or_none(avg.get("saleCnt"))
        shop_series = avg.get("shopSeries") or []
        if shop_cnt is None and shop_series:
            shop_cnt = shop_series[-1].get("cnt")
        shops = None
        if shop_cnt is not None:
            shops = {"count": shop_cnt, "series": shop_series,
                     "momRate": avg.get("prevMonCntRate"), "yoyRate": avg.get("prevYearCntRate")}

        # 매출 시계열(원 환산) — 시안 「시장의 크기」 추이선
        sales_series = [{"ym": r["ym"], "amt": _won(r["amt"])}
                        for r in (avg.get("series") or []) if r.get("amt") is not None] or None

        result = {
            "source": "sbiz365-simple",
            "baseYm": avg.get("stdYm"),
            "district": {
                "admiCd": admi.get("admiCd"),
                "admiNm": admi.get("admiNm"),
                "guNm": admi.get("guNm"),
            },
            "industryNm": avg.get("upjongNm"),
            "sales": {
                "avgAmt": _won(avg.get("saleAmt")),     # 점포당 월평균(원)
                "minAmt": _won(avg.get("minAmt")),
                "maxAmt": _won(avg.get("maxAmt")),
                "cnt": None,                            # 결제건수는 현 응답에 없음(saleCnt=업소수)
                "momRate": avg.get("prevMonRate"),
                "yoyRate": avg.get("prevYearRate"),
                "guAvgAmt": _won(avg.get("guAmt")),      # 시군구 평균 — 벤치마크
                "siAvgAmt": _won(avg.get("siAmt")),      # 시도 평균 — 벤치마크
            },
            "salesSeries": sales_series,                 # [{ym, amt(원)}] 월별 추이
            "shops": shops,                              # 업소수 + 시계열 + 증감
            "traffic": traffic,                          # dayAvg 만(시간대·요일은 2단계)
            "topFive": avg.get("topFive") or None,       # 업종 상위 5개 행정동(비교군)
            "delivery": avg.get("baemin"),
            # ── 미확보(2단계) — 실응답 검증 후 채울 자리 ──
            "sns": None,                                 # SNS 분석(snsAnaly)
            "theme": None,                               # 테마상권(hpReport)
        }
        _cache_put(cache_key, result)
        return result
    except Exception as e:
        logger.warning(f"[sbiz365] 상권 데이터 조립 실패(무시): {e}")
        return None
