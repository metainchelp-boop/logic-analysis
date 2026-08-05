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
    """「지역명」 → 좌표(x, y).
    place_crawler 는 캡처 HTML 파서 전용이라 좌표 확보 함수가 현재 없다(2026-08-04 확인 —
    서버가 네이버에 직접 접속하지 않는 구조). 향후 place_crawler.get_region_coord(region)
    -> (x, y) 가 정의되면 여기서 자동 재사용한다. 현재는 None → 행정동 매칭 실패 →
    get_place_sbiz() None(제안서는 상권 블록 생략). 좌표/행정동 소스는 실응답 검증
    단계에서 확정한다(다른 탐색 경로 추가 금지 — 과설계 방지)."""
    try:
        import place_crawler
        fn = getattr(place_crawler, "get_region_coord", None)
        if callable(fn):
            c = fn(region)
            if c and len(c) >= 2 and c[0] is not None and c[1] is not None:
                return float(c[0]), float(c[1])
    except Exception as e:
        logger.warning(f"[sbiz365] 좌표 확보 실패(무시): {e}")
    return None


def _coord_to_admi(x, y):
    """좌표 → 행정동(admiCd 8자리). bigdata.sbiz.or.kr 내부 변환 JSON.
    파라미터 이름은 실응답 검증 전이라 통용 표기(x·y·xCrdn·yCrdn)를 함께 보낸다."""
    key = _env_keys()["simple"]
    resp = _http_json(
        "POST", f"{_BASE}/gis/api/getCoordToAdmPoint.json",
        params={"certKey": key},
        data={"x": x, "y": y, "xCrdn": x, "yCrdn": y, "certKey": key},
    )
    body = _pick(resp, ("admiCd",))
    if body is None:
        return None
    admi_cd = str(body.get("admiCd") or "").strip()
    if not admi_cd:
        return None
    return {"admiCd": admi_cd,
            "admiNm": body.get("admiNm") or body.get("dongNm")}


def _resolve_admi(region: str):
    """지역명 → 행정동. 결과는 (행정동×업종) 데이터와 같은 TTL 로 캐시해
    캐시 적중 시 좌표 변환 재호출을 없앤다. 실패 시 None."""
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
    """업종 트리 JSON 을 (code, name) 쌍으로 평탄화 — 키 이름 편차(…Cd/…Nm 계열) 흡수.
    한 행에 대·중·소분류가 같이 실리는 형태도 접두사 짝(…Cd ↔ …Nm)으로 전부 수집한다."""
    if isinstance(node, dict):
        for k, v in node.items():
            kl = str(k).lower()
            stem = None
            if kl.endswith("cd"):
                stem = k[:-2]
            elif kl.endswith("code"):
                stem = k[:-4]
            if stem is not None and isinstance(v, (str, int)) and str(v).strip():
                for nk in (stem + "Nm", stem + "nm", stem + "Name", stem + "name"):
                    nv = node.get(nk)
                    if isinstance(nv, str) and nv.strip():
                        out.append((str(v).strip(), nv.strip()))
                        break
        for v in node.values():
            if isinstance(v, (dict, list)):
                _flatten_upjong(v, out)
    elif isinstance(node, list):
        for v in node:
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
    """행정동×업종 평균 매출 정보. 전 필드 optional — 실패 시 None."""
    key = _env_keys()["simple"]
    resp = _http_json(
        "POST", f"{_BASE}/gis/simpleAnls/getAvgAmtInfo.json",
        params={"certKey": key},
        data={"admiCd": admi_cd, "upjongCd": upjong_cd,
              "simpleLoc": simple_loc, "certKey": key},
    )
    body = _pick(resp, ("saleAmt", "analyNo", "stdYm"))
    if body is None:
        return None
    std_ym = body.get("stdYm")
    return {
        "saleAmt": _num(body.get("saleAmt")),            # 천원 단위
        "maxAmt": _num(body.get("maxAmt")),
        "minAmt": _num(body.get("minAmt")),
        "saleCnt": _num(body.get("saleCnt")),
        "prevMonRate": _num(body.get("prevMonRate")),
        "prevYearRate": _num(body.get("prevYearRate")),
        # 아래 3개는 파싱만 해 캐시 payload 재조립 없이 후속 차수에서 쓸 수 있게 보관
        "prevMonCntRate": _num(body.get("prevMonCntRate")),
        "prevYearCntRate": _num(body.get("prevYearCntRate")),
        "baemin": body.get("baemin"),
        "analyNo": body.get("analyNo"),
        "stdYm": str(std_ym).strip() if std_ym is not None else None,
        "guNm": body.get("guNm"),
        "dongNm": body.get("dongNm"),
    }


def _fetch_popular(admi_cd: str, upjong_cd: str, analy_no):
    """행정동 유동인구(일평균·시간대 6구간·요일·주말 비중). 실패 시 None(부분 강등)."""
    key = _env_keys()["simple"]
    params = {"admiCd": admi_cd, "upjongCd": upjong_cd, "certKey": key}
    if analy_no:
        params["analyNo"] = analy_no
    resp = _http_json("GET", f"{_BASE}/gis/simpleAnls/getPopularInfo.json", params=params)
    if resp is None:
        return None
    if isinstance(resp, dict) and isinstance(resp.get("population"), dict):
        body = resp["population"]
    else:
        body = _pick(resp, ("dayAvg", "firstHour", "mon"))
    if body is None:
        return None
    hours = [_num(body.get(k)) for k in
             ("firstHour", "secondHour", "thirdHour", "fourthHour", "fifthHour", "sixthHour")]
    days = [_num(body.get(k)) for k in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")]
    out = {
        "dayAvg": _num(body.get("dayAvg")),
        "hours": hours if any(h is not None for h in hours) else None,
        "days": days if any(d is not None for d in days) else None,
        "weekendShare": _num(body.get("weekend")),
    }
    if all(v is None for v in out.values()):
        return None
    return out


# ============================================================
# 7. 공개 함수
# ============================================================
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

        result = {
            "source": "sbiz365-simple",
            "baseYm": avg.get("stdYm"),
            "district": {
                "admiCd": admi.get("admiCd"),
                "admiNm": avg.get("dongNm") or admi.get("admiNm"),
                "guNm": avg.get("guNm"),
            },
            "sales": {
                "avgAmt": _won(avg.get("saleAmt")),   # 천원 → 원 환산
                "minAmt": _won(avg.get("minAmt")),
                "maxAmt": _won(avg.get("maxAmt")),
                "cnt": _int_or_none(avg.get("saleCnt")),
                "momRate": avg.get("prevMonRate"),
                "yoyRate": avg.get("prevYearRate"),
            },
            "traffic": pop,
            # ── 실응답 검증 후 채울 자리(지금은 항상 null — 키만 예약) ──
            "shops": None,        # 업소현황(STOR 키·공공데이터포털 병행 검토)
            "sns": None,          # SNS 분석(snsAnaly)
            "theme": None,        # 테마상권 분석(hpReport)
            "salesSeries": None,  # 점포당 매출액 추이(SLSIDX 키)
        }
        _cache_put(cache_key, result)
        return result
    except Exception as e:
        logger.warning(f"[sbiz365] 상권 데이터 조립 실패(무시): {e}")
        return None
