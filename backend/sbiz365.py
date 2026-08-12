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
import time
from concurrent.futures import ThreadPoolExecutor
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
AGG_WORKERS = 8          # 대분류 종합 집계 동시 호출 수
AGG_MAX_CODES = 60       # 대분류당 조회할 소분류 상한
AGG_TIME_BUDGET = 12.0   # 대분류 종합 집계 시간 상한(초) — 초과분은 건너뛰고 있는 것만 집계
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


# 캐시 네임스페이스(스키마 버전).
# ⚠️ 캐시에 담기는 건 원문이 아니라 **우리가 가공한 결과**(단위 환산·집계)라,
# 가공 규칙을 바꾸면 TTL(14일)이 만료될 때까지 옛 규칙으로 계산된 값이 계속 나간다.
# 2026-08-05 실사고: 금액 단위를 천원→만원으로 고쳤는데 「업종 종합」만 옛 값(1/10)이
# 그대로 노출됐다(소분류 캐시는 키에 hint 가 붙어 우연히 재계산됐고, 종합 캐시는 키가 같아 적중).
# 앞으로 **가공 규칙을 바꾸면 이 숫자를 올릴 것** — 전 캐시가 한 번에 무효화된다.
CACHE_NS = "v3"


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
        # 옛 네임스페이스 잔재 정리(읽히지 않는 행이 계속 쌓이지 않게) — 프로세스당 1회
        conn.execute("DELETE FROM sbiz_cache WHERE cache_key NOT LIKE ?", (f"{CACHE_NS}:%",))
        conn.commit()
        _cache_table_ready = True
    return conn


def _cache_get(key: str, ttl_seconds: int):
    try:
        conn = _cache_conn()
        row = conn.execute(
            "SELECT payload, fetched_at FROM sbiz_cache WHERE cache_key = ?",
            (f"{CACHE_NS}:{key}",),
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
            (f"{CACHE_NS}:{key}",
             json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()),
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


# 소상공인365 금액 필드(saleAmt·minAmt·maxAmt·guAmt·siAmt·avgList[].saleAmt)의 단위.
# ⚠️ 종전엔 천원으로 보고 ×1000 했는데 화면 금액이 실제의 1/10 로 찍혔다.
# 2026-08-05 구로3동 실측으로 만원 확정(unit_check 프로브 원문):
#   돼지고기 구이/찜  평균 3,447 · 최저 1,757 · 최고 6,579 (업소 55)
#   소고기 구이/찜    평균 3,686 · 최저 2,734 · 최고 5,679 (업소 13)
#   국수/칼국수      평균 1,585 · 최저 1,268 · 최고 2,713 (업소 29)
# 천원이면 「구로동 고깃집 평균 월매출 3만원 · 최고 7만원」이 되어 성립하지 않는다.
# 만원이면 평균 3,447만원/최고 6,579만원 = 실제 상권 감각과 맞는다.
AMT_UNIT_WON = 10_000


def _won(v):
    """소상공인365 금액(만원 단위) → 원 단위 정수. 실패 시 None."""
    n = _num(v)
    return int(round(n * AMT_UNIT_WON)) if n is not None else None


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
def _region_coord(query: str):
    """검색어 → **(경도, 위도, 나온 곳 이름)**. 네이버 지역검색(local) 사용 — 이미 보유한 자격 재사용.
    mapx/mapy 는 WGS84×10^7 정수라 10^7 로 나눈다. 실패 시 None.

    ⚠️ 세 번째 값(title)은 **좌표를 믿어도 되는지** 판정하는 근거다. 지역명으로 검색하면
       동명의 상호가 먼저 잡히는데(2026-08-11 사고: '조원동' → 서울의 엉뚱한 업소),
       「{지역} 주민센터」로 찾아 나온 곳 이름이 실제로 그 동 주민센터면 좌표를 신뢰할 수 있다.
       기존 소비처는 coord[0]·coord[1] 만 쓰므로 튜플 확장은 무해하다."""
    cid = os.getenv("NAVER_CLIENT_ID", "").strip()
    csec = os.getenv("NAVER_CLIENT_SECRET", "").strip()
    if not (cid and csec and query):
        return None
    try:
        import urllib.parse
        import urllib.request
        url = ("https://openapi.naver.com/v1/search/local.json?"
               + urllib.parse.urlencode({"query": query, "display": 1}))
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
        # title 에 <b> 강조 태그가 섞여 오므로 걷어낸다
        import re as _re
        title = _re.sub(r"<[^>]+>", "", str(items[0].get("title") or ""))
        return x, y, title
    except Exception as e:
        logger.warning(f"[sbiz365] 좌표 확보 실패(무시): {e}")
        return None


def _region_stem(region: str) -> str:
    """지역명의 어간 — 풀주소면 마지막 토큰, 끝의 동/가/읍/면/리 접미와 숫자를 뗀다.
      '조원동' → '조원' · '서울 성동구 성수동' → '성수' · '성사2동' → '성사'
    행정동명 검증에 쓴다('조원' ⊂ '조원1동' ✅ / '조원' ⊄ '신대방2동' ❌)."""
    import re
    tail = (str(region or "").strip().split() or [""])[-1]
    tail = re.sub(r"\d+", "", tail)
    return re.sub(r"[동가읍면리]$", "", tail).strip()


def _admi_matches_region(admi: dict, region: str) -> bool:
    """행정동 매칭 결과가 정말 그 지역인지 확인.

    ⚠️ 2026-08-11 실측 사고: 지역검색에 지역명만 넣으면 **동명의 상호**가 먼저 잡힌다.
       '조원동'(수원 장안구)을 검색했더니 첫 결과가 서울의 어느 업소여서
       **신대방2동(11590680) 상권**이 붙었다 — 완전히 다른 동네 수치가 광고주 보고서에
       실릴 뻔했다. 좌표가 어디서 왔든, 나온 행정동 이름이 입력 지역과 맞는지 확인한다.
       ⚠️ 맞지 않으면 상권을 **생략**한다 — 틀린 상권은 없는 것보다 나쁘다."""
    stem = _region_stem(region)
    if not stem:
        return False
    nm = _norm((admi or {}).get("admiNm") or "")
    return bool(nm) and _norm(stem) in nm


# 시군구 후퇴를 허용할 최소 쏠림 비율 — 반경 안 상가의 이 비율 이상이 한 시군구면
# 그 시군구는 확정된 것으로 본다(실측: 성사동 100%·미사동 100%·구로동 63%·역삼동 82%).
GU_CONFIDENT_SHARE = 0.60


def _coord_to_admi(x, y):
    """좌표 → 행정동(admiCd 8자리) + 그 반경의 행정동·시군구 **분포**.

    ⚠️ 2026-08-05 실측: 소상공인365 내부 `getCoordToAdmPoint.json` 은 500, 다른 후보 경로도 전부 404.
    → **공공데이터포털 「소상공인시장진흥공단_상가(상권)정보」 공식 REST** 로 확보한다.

    ⚠️⚠️ 2026-08-12 실측 — 종전엔 `numOfRows=1` 로 **딱 1건**을 받아 그 업소의 행정동을 썼는데,
    경계 근처면 옆 동이 잡혀 통째로 어긋났다(역삼동 주민센터 좌표 → 1건째 '서초구 서초2동'
    → 상권 생략). 같은 반경을 **100건** 받아 세어 보면 '역삼1동 82%'로 명백하다.
    호출 수는 그대로(1회)이고 응답만 커진다 → **최빈 행정동**을 채택한다.
    덤으로 시군구 분포도 함께 돌려준다 — 동이 안 맞을 때 시군구로 후퇴할지 판정하는 근거."""
    key = _env_keys()["datago"]
    if not key:
        return None
    import collections
    import urllib.parse
    import urllib.request
    base = "http://apis.data.go.kr/B553077/api/open/sdsc2/storeListInRadius"
    for radius in ("500", "1000", "2000"):     # 외곽 지역은 반경을 넓혀 재시도
        try:
            qs = urllib.parse.urlencode({"radius": radius, "cx": x, "cy": y,
                                         "type": "json", "numOfRows": "100", "pageNo": "1"})
            url = f"{base}?serviceKey={key}&{qs}"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            items = ((data.get("body") or {}).get("items")) or []
            if not items:
                continue

            # 행정동은 코드까지 같이 세야 한다(같은 이름 다른 코드가 섞이면 안 된다)
            dong_cnt = collections.Counter()
            dong_meta = {}
            gu_cnt = collections.Counter()
            for it in items:
                cd = str(it.get("adongCd") or "").strip()
                if len(cd) != 8:
                    continue
                dong_cnt[cd] += 1
                dong_meta.setdefault(cd, it)
                gn = (it.get("signguNm") or "").strip()
                if gn:
                    gu_cnt[gn] += 1
            if not dong_cnt:
                continue

            admi_cd, _hit = dong_cnt.most_common(1)[0]
            it = dong_meta[admi_cd]
            sido, gu, dong = it.get("ctprvnNm"), it.get("signguNm"), it.get("adongNm")
            total = sum(gu_cnt.values()) or 1
            top_gu, top_gu_cnt = (gu_cnt.most_common(1)[0] if gu_cnt else (None, 0))
            # ⚠️ 2026-08-05 실측: getAvgAmtInfo 의 simpleLoc 은 **전체 주소 문자열**이어야 한다.
            #    사용자가 적은 지역명(구로동)·행정동명(구로3동)·빈 값은 전부 HTTP 500,
            #    '서울특별시 구로구 구로3동' 만 200. → 여기서 정식 주소를 만들어 함께 넘긴다.
            return {"admiCd": admi_cd,
                    "admiNm": dong,
                    "guNm": gu,
                    "sidoNm": sido,
                    "simpleLoc": " ".join(v for v in (sido, gu, dong) if v),
                    # 시군구 후퇴 판정용 — 이 반경에서 시군구가 얼마나 한 곳으로 몰렸나
                    "guTop": top_gu,
                    "guShare": round(top_gu_cnt / total, 3),
                    "sampled": len(items)}
        except Exception as e:
            logger.warning(f"[sbiz365] 행정동 조회 실패(radius={radius}·무시): {e}")
    return None


def _resolve_admi(region: str, biz_name: str = ""):
    """지역명 → 행정동. 결과는 (행정동×업종) 데이터와 같은 TTL 로 캐시해
    캐시 적중 시 좌표·행정동 변환 재호출을 없앤다. 실패 시 None.

    ⚠️ 검색어를 지역명 하나로 두면 **동명의 상호**가 먼저 잡혀 엉뚱한 동네가 나온다
       (2026-08-11 실측: '조원동' → 서울 신대방2동). 그래서
       ⑴ 업체명이 있으면 그 업체로 먼저 찾고(우리가 아는 그 가게의 실제 위치라 가장 정확)
       ⑵ 「{지역} 주민센터/행정복지센터」로 행정동 청사를 찾고
       ⑶ 마지막에 지역명 단독을 시도한다.
       각 후보는 **나온 행정동 이름이 입력 지역과 맞는지 검증**하고, 전부 어긋나면 None."""
    cache_key = f"sbiz:admi:{_norm(region)}"
    cached = _cache_get(cache_key, SBIZ_CACHE_TTL)
    # simpleLoc(정식 주소) 없이 캐시된 구버전 항목은 그대로 쓰면 매출 조회가 500 이므로 재해석한다.
    # 캐시된 값이라도 지역과 안 맞으면(구버전이 잘못 넣은 것) 버리고 다시 찾는다.
    # scope 가 없는 구버전 항목도 재해석한다(시군구 후퇴 판정을 못 하므로).
    if cached and cached.get("simpleLoc") and cached.get("scope"):
        if cached["scope"] == "gu" or _admi_matches_region(cached, region):
            return cached

    reg = (region or "").strip()
    if not reg:
        return None
    queries = []
    if (biz_name or "").strip():
        queries.append(f"{biz_name.strip()} {reg}")
    queries += [f"{reg} 주민센터", f"{reg} 행정복지센터", reg]

    fallback = None            # 동은 안 맞지만 시군구는 믿을 만한 후보(첫 것만 쓴다)
    seen = set()
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        coord = _region_coord(q)
        if not coord:
            continue
        admi = _coord_to_admi(coord[0], coord[1])
        if not admi:
            continue
        if _admi_matches_region(admi, reg):
            admi["scope"] = "dong"
            _cache_put(cache_key, admi)
            return admi

        logger.warning(f"[sbiz365] 행정동 불일치 — 검색어 {q!r} → {admi.get('admiNm')!r} "
                       f"(입력 지역 {reg!r})")
        # ⭐ 시군구 후퇴(2026-08-12 대표 확정) — 동 단위로 못 맞혀도 **시군구가 확실하면**
        #    그 범위로 넓혀 보고서를 낸다. 다만 아무 때나 넓히면 8/11 조원동 사고
        #    (엉뚱한 동네 수치가 광고주 보고서에 실릴 뻔)가 되살아나므로 조건을 셋 건다.
        if fallback is None and _gu_trustworthy(admi, reg, q, coord):
            fallback = dict(admi)
            fallback["scope"] = "gu"

    if fallback:
        logger.info(f"[sbiz365] 시군구 단위로 후퇴 — 지역 {reg!r} → {fallback.get('guNm')!r} "
                    f"(쏠림 {fallback.get('guShare')})")
        _cache_put(cache_key, fallback)
        return fallback
    logger.warning(f"[sbiz365] 행정동·시군구 모두 매칭 실패 — 지역 {reg!r}(상권 생략)")
    return None


def _gu_trustworthy(admi: dict, region: str, query: str, coord) -> bool:
    """시군구 단위로 후퇴해도 되는가 — 셋 다 만족해야 한다.

    ⑴ **반경 안 상가가 한 시군구로 쏠려 있을 것**(GU_CONFIDENT_SHARE 이상).
       경계에 걸쳐 두 시군구가 반반이면 어느 쪽인지 모른다.
    ⑵ **좌표를 믿을 근거가 있을 것** — 둘 중 하나:
       · 입력 지역에 시·군·구가 이미 있고 그것이 나온 시군구와 맞거나(예: '하남시 미사동')
       · 「{지역} 주민센터/행정복지센터」로 찾아 **나온 곳 이름에 그 지역명이 들어 있거나**
         (그 동 청사를 제대로 찾았다는 뜻 — 지역명 단독 검색이 동명의 상호에 걸린 경우와 갈린다)
    ⑶ 표본이 너무 적지 않을 것.

    ⚠️ 지역명 단독 질의(마지막 후보)에서 나온 좌표는 후퇴에 쓰지 않는다 — 그게 바로
       2026-08-11 사고('조원동' → 서울의 엉뚱한 업소 → 신대방2동)의 입력이었다.
    ⚠️ 같은 이름의 동이 여러 곳인 경우(수원 조원동 vs 관악구 조원동)는 이 검사로도 못 가른다.
       입력에 시·구를 적어야만 갈리며, 그건 화면 안내가 유도한다."""
    if (admi.get("guShare") or 0) < GU_CONFIDENT_SHARE:
        return False
    if (admi.get("sampled") or 0) < 10:
        return False

    gu = _norm(admi.get("guNm") or "")
    reg_n = _norm(region)
    # ⑵-1 입력에 시군구가 들어 있고 그게 나온 시군구와 맞는다
    if gu and gu in reg_n:
        return True
    # '고양시 덕양구' 처럼 두 단인 시군구는 앞 단(고양시)만 적었을 수도 있다
    for part in str(admi.get("guNm") or "").split():
        if part and _norm(part) in reg_n:
            return True
    # ⑵-2 주민센터/행정복지센터로 찾았고, **나온 곳이 정말 그 동네의 행정 청사**다.
    # ⚠️ 검증이 잡은 실결함(2026-08-12): 어간만 대조하면 「성사동」→「성사네고깃집」,
    #    「조원동」→「조원식당」 같은 **동명 상호**가 그대로 통과한다 — 그게 바로 8/11
    #    사고의 모양이다. 청사 이름표(주민센터·행정복지센터·동사무소)까지 함께 요구한다.
    title = _norm(coord[2] if (coord and len(coord) > 2) else "")
    stem = _norm(_region_stem(region))
    is_office = any(w in title for w in ("주민센터", "행정복지센터", "동사무소"))
    if ("주민센터" in query or "행정복지센터" in query) and is_office and stem and stem in title:
        return True
    return False


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
    # '주점'은 중분류명(주점·커피)에도 들어 있어 카페가 먼저 잡힌다 → 호프를 앞에 둔다
    "주점": ["호프", "주점"],
    "바": ["호프", "주점"],
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


def _is_residual_bucket(name: str) -> bool:
    """소분류명이 '기타/그 외' 잔여 버킷인지. ⚠️ 2026-08-05 실측 — 이 버킷들은 어느 행정동에서든
    점포당 매출이 0으로 나온다(구로3동: 그 외 기타 간이 음식점·기타 한식·기타 일식·기타 서양식 전부 0,
    반면 곱창 전골/구이 3,340천원·국/탕/찌개류 2,938천원). 대표 업종으로 골라선 안 된다."""
    last = str(name or "").split(">")[-1].strip()
    return last.startswith("기타") or ("그 외" in last) or ("분류 안된" in last)


def _hint_terms(hint: str):
    """업체명·키워드에서 소분류를 좁힐 낱말을 뽑는다.
    드롭다운은 「음식점」처럼 넓은 13종뿐이라, 삼겹살집인데 백반/한정식 평균이 잡히는 일이 생긴다
    (2026-08-05 구로3동 실측: 백반/한정식 2,970 vs 돼지고기 구이/찜 3,447 — 업종이 어긋나면 근거가 흔들림).
    업체명·키워드에 업종이 드러나 있으면 그걸 먼저 쓴다. 못 찾으면 종전 라벨 경로 그대로."""
    h = str(hint or "")
    if not h:
        return []
    out = []
    for word, terms in _HINT_UPJONG.items():
        if word in h:
            out.extend(terms)
    return list(dict.fromkeys(out))


# 업체명·키워드에 흔히 드러나는 낱말 → 소분류 트리 검색어.
# 값은 `getHierarchyTpbizCode` 소분류명에 실제로 들어 있는 문자열이어야 한다.
_HINT_UPJONG = {
    "삼겹살": ["돼지고기"], "돼지": ["돼지고기"], "goldsam": ["돼지고기"],
    "소고기": ["소고기"], "한우": ["소고기"], "갈비": ["소고기", "돼지고기"],
    "곱창": ["곱창"], "막창": ["곱창"], "대창": ["곱창"],
    "닭": ["닭/오리"], "오리": ["닭/오리"], "치킨": ["치킨"],
    "횟집": ["해산물"], "회": ["해산물"], "조개": ["해산물"], "해물": ["해산물"],
    "칼국수": ["국수/칼국수"], "국수": ["국수/칼국수"], "면": ["국수/칼국수"],
    "찌개": ["국/탕/찌개"], "탕": ["국/탕/찌개"], "국밥": ["국/탕/찌개"],
    "분식": ["김밥/만두/분식"], "김밥": ["김밥/만두/분식"], "떡볶이": ["김밥/만두/분식"],
    "피자": ["피자"], "햄버거": ["햄버거"], "파스타": ["서양식"], "스테이크": ["서양식"],
    "중국집": ["중식"], "짜장": ["중식"], "마라": ["중식"],
    "초밥": ["일식"], "스시": ["일식"], "돈까스": ["일식"], "라멘": ["일식"],
    "카페": ["커피"], "커피": ["커피"], "베이커리": ["제과"], "빵": ["제과"],
    "호프": ["호프"], "포차": ["호프"], "이자카야": ["호프"], "바": ["호프"],
}


def _resolve_upjong_candidates(industry_label: str, limit: int = 3, hint: str = ""):
    """업종 라벨(+업체명·키워드 힌트) → 소분류 후보 목록(우선순위 순, 최대 limit개).
    ⚠️ 종전에는 후보 중 '코드가 가장 큰 것' 하나만 골랐는데, 그게 하필 '그 외 기타…' 잔여 버킷이라
    상권 매출이 항상 0으로 나왔다(2026-08-05 실측). 이제 잔여 버킷을 뒤로 미루고, 실제 값이
    있는 후보를 만날 때까지 호출부가 순서대로 시도한다."""
    label = (industry_label or "").strip()
    if not label and not hint:
        return []
    pairs = _upjong_pairs()
    if not pairs:
        return []
    terms = list(_hint_terms(hint))   # 업체명·키워드에서 읽은 업종이 항상 우선
    for lk, ts in _UPJONG_SEARCH_TERMS.items():
        if label and (lk in label or label in lk):
            terms.extend(ts)
    if label:
        terms.append(label)  # 사전 미등재 라벨은 라벨 자체 부분일치 폴백

    # ⚠️ 검색어별로 따로 고르면 안 된다. '음식점'이라는 낱말은 트리에서 하필 잔여 버킷
    #    (기타 한식 음식점·기타 일식 음식점·그 외 기타 간이 음식점…)에만 들어 있어서,
    #    검색어 순서대로 끊으면 항상 0원짜리 버킷을 집는다. 전 검색어의 후보를 모은 뒤
    #    '잔여 버킷인가 → 검색어 우선순위 → 코드' 로 한 번에 정렬한다.
    scored, seen = [], set()
    for rank, term in enumerate(terms):
        if not term:
            continue
        for c, n in pairs:
            if term in n and c not in seen:
                seen.add(c)
                scored.append((_is_residual_bucket(n), rank, len(c), c, n))
    scored.sort()
    return [{"code": c, "name": n} for _, _, _, c, n in scored[:limit]]


def _resolve_upjong(industry_label: str):
    """업종 라벨 → 소분류 코드 1개(최우선 후보). 실패 시 None."""
    cands = _resolve_upjong_candidates(industry_label, limit=1)
    return cands[0] if cands else None


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


def _major_of(name: str) -> str:
    """소분류 경로('음식 > 한식 > 백반/한정식')의 대분류('음식')."""
    return str(name or "").split(">")[0].strip()


def _simple_loc_variants(admi: dict, region: str):
    """getAvgAmtInfo 의 simpleLoc 표기 후보(우선순위 순).
    ⚠️ 2026-08-05 실측: 지역마다 받아주는 형태가 다르다.
      · 서울 구로3동  → '서울특별시 구로구 구로3동' 만 200(동명 단독·빈 값은 500)
      · 경기 성사2동  → 위와 같은 4단 표기('경기도 고양시 덕양구 성사2동')로는 응답 없음
    시군구가 '고양시 덕양구' 처럼 두 단인 지역이 있어 조합을 몇 가지 시험해야 한다."""
    sido = (admi.get("sidoNm") or "").strip()
    gu = (admi.get("guNm") or "").strip()
    dong = (admi.get("admiNm") or "").strip()
    out = []
    for cand in (
        " ".join(x for x in (sido, gu, dong) if x),          # 서울특별시 구로구 구로3동
        " ".join(x for x in (sido, gu.replace(" ", ""), dong) if x),  # 경기도 고양시덕양구 성사2동
        " ".join(x for x in (gu, dong) if x),                # 고양시 덕양구 성사2동
        (admi.get("simpleLoc") or "").strip(),
        (region or "").strip(),
    ):
        if cand and cand not in out:
            out.append(cand)
    return out


def _pick_simple_loc(admi: dict, region: str, probe_code: str):
    """표기 후보 중 **서버가 응답하는 첫 표기**를 고른다(매출 0원이어도 응답이면 표기는 맞은 것).
    전부 무응답이면 None → 호출부가 상권 블록을 생략한다."""
    for loc in _simple_loc_variants(admi, region):
        if _fetch_avg(admi["admiCd"], probe_code, loc) is not None:
            return loc
    return None


def _aggregate_major(admi_cd: str, loc: str, major: str):
    """대분류 종합(예: 그 동네 '음식' 전체) — 업소수 가중평균 점포당 매출 + 총 업소수.

    ⚠️ 2026-08-05 실측: getAvgAmtInfo 는 **소분류 6자리 코드만** 받는다.
    상위분류 코드(I201·I20·I2·I)와 빈 값은 전부 무응답 → '업종 전체' 를 서버가 계산해 주지 않는다.
    그래서 대분류에 속한 소분류를 우리가 모두 조회해 직접 합산한다(구로3동 음식 = 43개 소분류 중
    29개에 값 존재 · 가중평균 약 3,059만원 · 895곳). 순차 조회는 24초라 병렬로 돌리고,
    시간 상한을 둬서 제안서 생성이 늘어지지 않게 한다. 결과는 다른 캐시와 같은 TTL 로 보관."""
    if not major:
        return None
    cache_key = f"sbiz:major:{admi_cd}|{_norm(major)}"
    cached = _cache_get(cache_key, SBIZ_CACHE_TTL)
    if cached is not None:
        return cached

    pairs = _upjong_pairs() or []
    codes = [c for c, n in pairs if _major_of(n) == major][:AGG_MAX_CODES]
    if not codes:
        return None

    started = time.time()

    skipped = []

    def one(code):
        if time.time() - started > AGG_TIME_BUDGET:   # 예산 초과분은 조용히 건너뜀
            skipped.append(code)
            return None
        got = _fetch_avg(admi_cd, code, loc)
        if not got:
            return None
        amt, cnt = _num(got.get("saleAmt")), _num(got.get("saleCnt"))
        return (amt, cnt) if (amt and cnt) else None

    rows = []
    try:
        with ThreadPoolExecutor(max_workers=AGG_WORKERS) as ex:
            rows = [r for r in ex.map(one, codes) if r]
    except Exception as e:
        logger.warning(f"[sbiz365] 대분류 집계 실패(무시): {e}")
        return None
    if not rows:
        return None

    tot_cnt = sum(c for _, c in rows)
    if not tot_cnt:
        return None
    weighted = sum(a * c for a, c in rows) / tot_cnt
    result = {
        "label": major,                     # '음식'·'미용' 등 대분류 이름
        "avgAmt": _won(weighted),           # 업소수 가중평균 점포당 월매출(원)
        "shopCnt": int(tot_cnt),            # 대분류 전체 업소수
        "kinds": len(rows),                 # 값이 잡힌 소분류 수
        "partial": bool(skipped),           # 시간 예산 때문에 못 본 소분류가 있는지
    }
    _cache_put(cache_key, result)
    return result


def get_place_sbiz(region: str, industry_label: str, hint: str = "",
                   biz_name: str = "") -> dict | None:
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
        hint = (hint or "").strip()
        if not region or not label:
            return None

        # 업체명이 있으면 좌표를 그 업체로 먼저 찾는다 — 지역명 단독 검색은 동명의 상호에
        # 걸려 엉뚱한 동네가 나온다(2026-08-11 실측 사고).
        admi = _resolve_admi(region, biz_name=biz_name)
        if not admi or not admi.get("admiCd"):
            return None
        candidates = _resolve_upjong_candidates(label, limit=3, hint=hint)
        if not candidates:
            return None

        # 힌트가 후보를 바꾸므로 캐시 키에도 넣는다(같은 동네 같은 라벨이어도 삼겹살집/칼국수집이 다른 업종).
        # ⚠️ scope 를 키에 넣는다 — 같은 admiCd 라도 동 모드/시군구 모드는 다른 결과다
        #    (시군구 모드는 헤드라인이 guAmt 이고 동 단위 축이 비어 있다).
        cache_key = (f"sbiz:simple:{admi['admiCd']}|{admi.get('scope') or 'dong'}"
                     f"|{_norm(label)}|{_norm(hint)}")
        cached = _cache_get(cache_key, SBIZ_CACHE_TTL)
        if cached is not None:
            return cached

        # simpleLoc = 행정동 정식 주소. 사용자 입력 지역명을 그대로 쓰면 500 이라 조립해서 넘긴다.
        # ⚠️ 지역마다 받아주는 표기가 달라(서울 '서울특별시 구로구 구로3동' 은 되는데
        #    경기 '경기도 고양시 덕양구 성사2동' 은 안 됨 — 시군구가 2단인 지역) 표기 후보를
        #    순서대로 시험해 **응답이 오는 표기 하나를 먼저 확정**한 뒤, 그 표기로 업종 후보를 돈다.
        #    (표기 확정에 최대 4콜 · 업종 후보에 최대 3콜 — 첫 표기가 맞으면 1콜로 끝난다)
        loc, avg, upjong = _pick_simple_loc(admi, region, candidates[0]["code"]), None, None
        if not loc:
            return None

        # 후보 업종을 순서대로 시도하고, 점포당 매출이 실제로 잡히는 첫 후보를 채택한다
        # (그 동네에 그 소분류 점포가 없으면 0원으로 와서 상권 슬라이드가 '0원'이 되어버림).
        for cand in candidates:
            got = _fetch_avg(admi["admiCd"], cand["code"], loc)
            if got and _num(got.get("saleAmt")):
                upjong, avg = cand, got
                break
        if avg is None:
            return None
        pop = _fetch_popular(admi["admiCd"], upjong["code"], avg.get("analyNo"))

        # ⭐ 시군구 후퇴 모드(2026-08-12 대표 확정) — 동 단위로 지역을 못 맞혔을 때.
        #    이때 행정동 기준 숫자(그 동의 점포당 매출·업소수·시계열·유동인구·대분류 종합)를
        #    그대로 내보내면 **우리가 확신하지 못하는 동네의 수치**를 광고주에게 보이는 셈이다.
        #    그래서 헤드라인을 시군구 평균(guAmt)으로 갈아끼우고 동 단위 축은 전부 비운다.
        #    ⚠️ 이 분기의 요점은 하나 — **단위가 다른 숫자를 한 카드에 섞지 않는다.**
        is_gu = (admi.get("scope") == "gu")
        if is_gu and _num(avg.get("guAmt")) is None:
            logger.warning("[sbiz365] 시군구 후퇴인데 시군구 평균이 없다 → 상권 생략")
            return None

        # 유동인구: topFive 에 우리 행정동이 있으면 dayAvg 확보(없으면 null — 가짜 값 금지)
        traffic = None
        if not is_gu and avg.get("dayAvg") is not None:
            traffic = {"dayAvg": avg["dayAvg"], "hours": None, "days": None, "weekendShare": None}

        # 업소수: 행정동 최신값(saleCnt) 우선, 없으면 shopSeries 마지막
        shop_cnt = _int_or_none(avg.get("saleCnt"))
        shop_series = avg.get("shopSeries") or []
        if shop_cnt is None and shop_series:
            shop_cnt = shop_series[-1].get("cnt")
        shops = None
        if not is_gu and shop_cnt is not None:
            shops = {"count": shop_cnt, "series": shop_series,
                     "momRate": avg.get("prevMonCntRate"), "yoyRate": avg.get("prevYearCntRate")}

        # 업종 대분류 종합 — 소분류를 우리가 합산(서버는 상위분류 코드를 안 받는다).
        # 시군구 모드에서는 건너뛴다 — 행정동 기준 합산이라 단위가 안 맞고, 병렬 8콜도 아낀다.
        major_block = None
        if not is_gu:
            try:
                major_block = _aggregate_major(admi["admiCd"], loc, _major_of(upjong.get("name")))
            except Exception as e:
                logger.warning(f"[sbiz365] 대분류 종합 생략(무시): {e}")

        # 매출 시계열(원 환산) — 시안 「시장의 크기」 추이선. 시군구 모드에서는 동 기준이라 비운다.
        sales_series = None
        if not is_gu:
            sales_series = [{"ym": r["ym"], "amt": _won(r["amt"])}
                            for r in (avg.get("series") or []) if r.get("amt") is not None] or None

        result = {
            "source": "sbiz365-simple",
            "baseYm": avg.get("stdYm"),
            # 어느 범위로 잰 수치인지 — 화면이 이 값으로 「…동 상권」/「…구 상권」을 가른다
            "scope": "gu" if is_gu else "dong",
            "scopeLabel": (admi.get("guNm") or "") if is_gu
                          else " ".join(v for v in (admi.get("guNm"), admi.get("admiNm")) if v),
            "district": {
                "admiCd": admi.get("admiCd"),
                # 시군구 모드에서는 동 이름을 내보내지 않는다(우리가 확신하지 못하는 값이다)
                "admiNm": None if is_gu else admi.get("admiNm"),
                "guNm": admi.get("guNm"),
            },
            # 어떤 소분류로 집계했는지 — 응답에 없으면 우리가 고른 후보의 소분류명으로 표기
            # (제안서에서 '무슨 업종 기준 수치인지'를 밝히기 위한 값).
            "industryNm": avg.get("upjongNm") or str(upjong.get("name") or "").split(">")[-1].strip(),
            # (아래 major·sales·salesSeries·shops·traffic 은 시군구 모드에서 동 단위 축을 비운다)
            # 업종 대분류 종합(예: 그 동네 '음식' 전체) — 업종 선택지를 세분화하지 않고도
            # '우리 동네 전체 시장' 을 보여주기 위한 축. 실패하면 그냥 없음(기존 표기 그대로).
            "major": major_block,
            "sales": {
                # 시군구 모드에서는 헤드라인이 **시군구 평균**이다(동 평균을 쓰면 안 되는 값이다)
                "avgAmt": _won(avg.get("guAmt") if is_gu else avg.get("saleAmt")),  # 점포당 월평균(원)
                # 최저·최고·증감·는 전부 행정동 기준이라 시군구 모드에서는 비운다
                "minAmt": None if is_gu else _won(avg.get("minAmt")),
                "maxAmt": None if is_gu else _won(avg.get("maxAmt")),
                "cnt": None,                            # 결제건수는 현 응답에 없음(saleCnt=업소수)
                "momRate": None if is_gu else avg.get("prevMonRate"),
                "yoyRate": None if is_gu else avg.get("prevYearRate"),
                # 벤치마크 — 시군구 모드에서는 헤드라인이 곧 시군구 평균이라 중복이므로 시도만 남긴다
                "guAvgAmt": None if is_gu else _won(avg.get("guAmt")),
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
