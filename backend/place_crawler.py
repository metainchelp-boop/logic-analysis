# -*- coding: utf-8 -*-
"""
place_crawler.py — 네이버 플레이스(지도) 데이터 어댑터 (신규 업종 프리셋)

기존 쇼핑(스마트스토어) 엔진과 "같은 반환 형태"를 유지하는 플레이스 전용 모듈.
- 서버가 네이버에 직접 접속하지 않는다(플레이스는 서버 크롤링이 차단됨·순위가 GPS 개인화).
  → 직원 브라우저에서 북마클릿으로 캡처해 붙여넣은 "검색결과 페이지 HTML"을 파싱한다.
- 점수 반환 형태(scores/weights/data_quality/suggestions/competitors)를 seo_analyze 와 맞춰,
  프론트 리포트 셸(AnalysisResults)·AI 코멘트 파이프라인을 그대로 재사용할 수 있게 한다.

이 파일은 기존 쇼핑 경로(main.py/naver_crawler.py)를 전혀 건드리지 않는 순수 추가 모듈이다.
main.py 에 vertical="place" 분기로 연결하는 배선은 별도 단계.

지표·가중치·AI 프롬프트 문구는 팀 노하우로 최종 확정하는 "계약서" 초안값이다.
"""

import re
import json

try:
    import data_quality as dq
except Exception:  # 단독 실행/테스트 환경 폴백
    dq = None


# ============================================================
# 1. 플레이스 로컬 10지표 + 가중치 (합 = 1.00) — 확정 대상 초안
# ============================================================
PLACE_METRIC_WEIGHTS = {
    "rank":            0.15,  # 플레이스 노출 순위
    "relevance":       0.14,  # 대표키워드·업체명 적합도
    "visitor_review":  0.14,  # 방문자(영수증) 리뷰
    "blog_review":     0.12,  # 블로그 리뷰
    "save":            0.10,  # 저장수(즐겨찾기)
    "photo":           0.08,  # 사진·메뉴 충실도
    "booking":         0.08,  # 예약·톡톡·주문 세팅
    "review_keyword":  0.07,  # 리뷰 반응(키워드형)
    "activity":        0.06,  # 소식·활성도
    "info":            0.06,  # 업체정보 충실도
}

PLACE_METRIC_LABEL = {
    "rank":            "플레이스 노출 순위",
    "relevance":       "대표키워드·업체명 적합도",
    "visitor_review":  "방문자(영수증) 리뷰",
    "blog_review":     "블로그 리뷰",
    "save":            "저장수(즐겨찾기)",
    "photo":           "사진·메뉴 충실도",
    "booking":         "예약·톡톡·주문 세팅",
    "review_keyword":  "리뷰 반응(키워드형)",
    "activity":        "소식·활성도",
    "info":            "업체정보 충실도",
}

# 자동수집(측정) vs 담당자 보완(입력) 경계 — 하이브리드
PLACE_MEASURED_KEYS = {"rank", "visitor_review", "blog_review", "relevance", "review_keyword", "photo"}
PLACE_INPUT_KEYS = {"save", "booking", "activity", "info"}


# ============================================================
# 2. 캡처 페이지 파싱 (DOM 순서 + __APOLLO_STATE__ 이중 안전장치)
# ============================================================
def extract_region_and_type(html):
    """검색 질의의 지역/업종을 nlu 정보에서 추출(있으면). 없으면 (None, None)."""
    region = None
    category = None
    m = re.search(r'"nlu_?query"\s*:\s*"([^"]+)"', html)
    if m:
        region = m.group(1)
    m2 = re.search(r'"region"\s*:\s*"([^"]+)"', html)
    if m2:
        region = region or m2.group(1)
    m3 = re.search(r'"category"\s*:\s*"([^"]+)"', html)
    if m3:
        category = m3.group(1)
    return region, category


def _parse_apollo(html):
    """window.__APOLLO_STATE__ JSON 을 통째로 파싱(있으면). 실패 시 {}."""
    m = re.search(r'__APOLLO_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>', html, re.DOTALL)
    if not m:
        m = re.search(r'__APOLLO_STATE__\s*=\s*(\{.*)', html, re.DOTALL)
        if not m:
            return {}
    raw = m.group(1)
    # 뒤에 붙은 코드 제거를 위해 최대 균형 괄호까지만 취함
    depth = 0
    end = None
    for i, ch in enumerate(raw):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return {}
    try:
        return json.loads(raw[:end])
    except Exception:
        return {}


def _items_from_apollo(apollo):
    """__APOLLO_STATE__ 에서 업체 항목을 추출. 구조화 소스(1순위)."""
    items = []
    for key, val in apollo.items():
        if not isinstance(val, dict):
            continue
        is_ad = ("Ad" in key) or ("nad" in str(val.get("adId", "")).lower())
        is_biz = key.startswith("PlaceListBusinessesItem") or key.startswith("RestaurantListSummary") \
            or key.startswith("RestaurantAdSummary") or ("id" in val and ("name" in val))
        if not is_biz:
            continue
        name = val.get("name") or val.get("businessName")
        if not name:
            continue
        items.append({
            "doc_id": str(val.get("id") or val.get("businessId") or ""),
            "name": name,
            "category": val.get("category") or val.get("categoryCodeList", None),
            "rating": _to_float(val.get("visitorReviewScore") or val.get("rating")),
            "visitor_reviews": _to_int(val.get("visitorReviewCount")),
            "blog_reviews": _to_int(val.get("blogCafeReviewCount") or val.get("blogReviewCount")),
            "is_ad": bool(is_ad),
        })
    return items


def _items_from_dom(html):
    """DOM 등장 순서로 doc-id 추출(폴백). 광고(nad)와 오가닉 구분."""
    items = []
    # 오가닉: data-nmb_res-doc-id / 광고: data-nmb_rese-doc-id(nad 포함)
    pattern = re.compile(r'data-nmb_(res|rese)-doc-id="([^"]+)"')
    seen = set()
    for m in pattern.finditer(html):
        kind, doc = m.group(1), m.group(2)
        is_ad = (kind == "rese") or ("nad" in doc.lower())
        key = doc
        if key in seen:
            continue
        seen.add(key)
        items.append({"doc_id": doc, "name": None, "category": None,
                      "rating": None, "visitor_reviews": None, "blog_reviews": None,
                      "is_ad": is_ad})
    return items


def parse_place_search(html):
    """
    캡처한 플레이스 검색결과 HTML → 순서 있는 업체 목록.
    반환: {region, category, items:[{rank, doc_id, name, category, rating,
           visitor_reviews, blog_reviews, is_ad}]}
    rank 는 광고(is_ad) 를 제외한 오가닉 순번(1부터).
    """
    if not html:
        return {"region": None, "category": None, "items": []}

    region, category = extract_region_and_type(html)

    apollo = _parse_apollo(html)
    items = _items_from_apollo(apollo) if apollo else []
    if not items:
        items = _items_from_dom(html)

    # 오가닉 순위 부여(광고 제외)
    organic_rank = 0
    for it in items:
        if it.get("is_ad"):
            it["rank"] = None
        else:
            organic_rank += 1
            it["rank"] = organic_rank

    return {"region": region, "category": category, "items": items}


def find_place_rank(parsed, target_doc_id=None, target_name=None):
    """
    파싱 결과에서 내 업체 순위를 찾는다. 3-state.
    반환: {state: "노출"|"미노출"|"미확인", rank: int|None, page: int|None, matched: dict|None}
    - 미확인: 파싱 항목 자체가 없음(캡처 안 함/실패)
    - 미노출: 목록엔 있으나 내 업체 없음
    - 노출: 오가닉 순위 확정
    """
    items = parsed.get("items") or []
    if not items:
        return {"state": "미확인", "rank": None, "page": None, "matched": None}

    def _match(it):
        if target_doc_id and str(it.get("doc_id")) == str(target_doc_id):
            return True
        if target_name and it.get("name") and _norm(target_name) in _norm(it["name"]):
            return True
        return False

    for it in items:
        if not it.get("is_ad") and _match(it):
            rank = it.get("rank")
            page = ((rank - 1) // 10 + 1) if rank else None
            return {"state": "노출", "rank": rank, "page": page, "matched": it}

    return {"state": "미노출", "rank": None, "page": None, "matched": None}


# ============================================================
# 3. 플레이스 점수화 (쇼핑 seo_analyze 와 같은 반환 envelope)
# ============================================================
def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def _rank_score(rank):
    if not rank:
        return 10
    if rank <= 3:
        return 100
    if rank <= 5:
        return 85
    if rank <= 10:
        return 68
    if rank <= 20:
        return 45
    if rank <= 30:
        return 28
    return 15


def _relative_score(mine, peers, floor=20):
    """경쟁사(peers) 중앙값 대비 상대 점수. peers 없으면 절대 임계로 폴백은 호출부에서."""
    peers = [p for p in (peers or []) if p]
    if not peers or not mine:
        return None
    med = sorted(peers)[len(peers) // 2]
    if med <= 0:
        return None
    ratio = mine / med
    return int(_clamp(floor + ratio * 55))


def _abs_review_score(n):
    if not n:
        return 15
    if n >= 500:
        return 100
    if n >= 300:
        return 85
    if n >= 150:
        return 68
    if n >= 50:
        return 45
    return 28


def score_place(place, competitors=None):
    """
    place: 내 업체 지표 dict — {rank, relevance(0~100 or None), visitor_reviews, blog_reviews,
           saves, photos, has_booking, has_talk, has_order, news_days, rep_keyword(bool),
           info_complete(0~100 or None), review_keyword_focus(0~100 or None)}
    competitors: [{visitor_reviews, blog_reviews, saves}, ...] (상대 점수용, 선택)
    반환: {scores{}, weights, total, data_quality{}, suggestions[]}
    """
    place = place or {}
    comp = competitors or []
    v_reviews = [c.get("visitor_reviews") for c in comp]
    b_reviews = [c.get("blog_reviews") for c in comp]
    saves = [c.get("saves") for c in comp]

    s = {}
    s["rank"] = _rank_score(place.get("rank"))

    rel = place.get("relevance")
    s["relevance"] = int(_clamp(rel)) if rel is not None else (75 if place.get("rep_keyword") else 50)

    s["visitor_review"] = _relative_score(place.get("visitor_reviews"), v_reviews) \
        or _abs_review_score(place.get("visitor_reviews"))
    s["blog_review"] = _relative_score(place.get("blog_reviews"), b_reviews) \
        or _abs_review_score(place.get("blog_reviews"))
    s["save"] = _relative_score(place.get("saves"), saves) \
        or (55 if (place.get("saves") or 0) >= 500 else 30)

    photos = place.get("photos") or 0
    s["photo"] = int(_clamp(30 + photos * 0.7)) if photos else 20

    bk = 0
    bk += 45 if place.get("has_booking") else 0
    bk += 35 if place.get("has_talk") else 0
    bk += 20 if place.get("has_order") else 0
    s["booking"] = int(_clamp(bk))

    rk = place.get("review_keyword_focus")
    s["review_keyword"] = int(_clamp(rk)) if rk is not None else 55

    nd = place.get("news_days")
    if nd is None:
        s["activity"] = 40
    elif nd <= 3:
        s["activity"] = 95
    elif nd <= 7:
        s["activity"] = 78
    elif nd <= 14:
        s["activity"] = 55
    elif nd <= 30:
        s["activity"] = 38
    else:
        s["activity"] = 20

    info = place.get("info_complete")
    s["info"] = int(_clamp(info)) if info is not None else 70

    total = int(sum(s[k] * PLACE_METRIC_WEIGHTS[k] for k in PLACE_METRIC_WEIGHTS))

    # 개선 제안(규칙 기반)
    suggestions = []
    if s["save"] < 50:
        suggestions.append("저장수(즐겨찾기)가 상위권 대비 부족합니다. 리뷰 이벤트·SNS로 저장을 유도하세요.")
    if s["blog_review"] < 55:
        suggestions.append("블로그 리뷰 발행이 둔화됐습니다. 지역 체험단으로 블로그 자산을 늘리세요.")
    if s["activity"] < 55:
        suggestions.append("소식이 오래 갱신되지 않았습니다. 신메뉴·이벤트 소식을 주 1회 발행하세요.")
    if not place.get("rep_keyword"):
        suggestions.append("대표키워드가 미등록입니다. 리뷰 키워드 결에 맞춰 대표키워드를 등록하세요.")
    if s["rank"] and s["rank"] >= 68 and s["visitor_review"] >= 68:
        suggestions.append("리뷰·평점은 경쟁력이 있습니다. 저장·블로그만 보강하면 순위 상승 여지가 큽니다.")
    if not suggestions:
        suggestions.append("전반적으로 양호합니다. 방문자 리뷰 최신성과 예약 전환 유지에 집중하세요.")

    return {
        "scores": {"total": total, **s},
        "weights": dict(PLACE_METRIC_WEIGHTS),
        "labels": dict(PLACE_METRIC_LABEL),
        "data_quality": _place_data_quality(place),
        "suggestions": suggestions,
    }


def _place_data_quality(place):
    """측정/입력 신뢰 등급 부착(부가 필드). data_quality 모듈 있으면 재사용."""
    if dq is None:
        # 폴백: 단순 표기
        out = {}
        for k in PLACE_MEASURED_KEYS:
            out[k] = {"status": "measured"}
        for k in PLACE_INPUT_KEYS:
            out[k] = {"status": "input"}
        return out
    out = {}
    out["visitor_review"] = dq.metric(place.get("visitor_reviews"),
                                      dq.MEASURED, sources=["place_capture"])
    out["blog_review"] = dq.metric(place.get("blog_reviews"),
                                   dq.MEASURED, sources=["place_capture"])
    out["rank"] = dq.metric(place.get("rank"),
                            dq.status_from_presence(place.get("rank")), sources=["place_capture"])
    out["save"] = dq.metric(place.get("saves"),
                            dq.status_from_presence(place.get("saves")), sources=["manual_input"])
    out["booking"] = dq.metric(1 if place.get("has_booking") else None,
                               dq.status_from_presence(place.get("has_booking")), sources=["manual_input"])
    return out


# ============================================================
# 4. 플레이스 AI 종합 코멘트 프리셋 (기존 ai_feedback_all 프롬프트 자리 교체용)
#    - 모델·호출·파싱·렌더는 기존 그대로 재사용, 페르소나 문구만 플레이스용.
# ============================================================
PLACE_AI_SECTION_LABELS = {
    "summary":     ("종합 진단", "플레이스 경쟁력을 한 문단으로 요약하고 등급(예: B+)과 핵심 병목을 제시"),
    "rank":        ("노출 순위", "지역+키워드 기준 현재 순위와 1페이지 진입/방어 관점의 조언"),
    "review":      ("리뷰 진단", "방문자·블로그 리뷰 최신성·양·키워드 결을 상위권과 비교해 진단"),
    "competition": ("경쟁 비교", "상위 노출 업체 대비 이기는/지는 지표를 수치로 대조하고 격차 원인"),
    "opportunity": ("기회 발굴", "노출 가능 후보 키워드와 개선 우선순위(무엇을 왜 얼마나)"),
    "strategy":    ("전략·결론", "12주 관점의 실행 순서와 기대 효과"),
}

PLACE_AI_SYSTEM_PROMPT = (
    "당신은 네이버 플레이스(지역 검색·지도) 상위노출 로직에 정통한 로컬 마케팅 컨설턴트입니다.\n"
    "플레이스 순위는 '지역명+키워드' 기준의 상대 노출이며, 핵심 축은 적합도(업체명·대표키워드·업종),\n"
    "인기도(방문자·블로그 리뷰·저장수·예약/톡톡 활성), 거리/정확도입니다. 네이버 별점은 폐지됐으므로\n"
    "평점 대신 방문자 리뷰 수·최신성과 리뷰 키워드(분위기·맛·사진 등)를 근거로 판단합니다.\n"
    "\n"
    "작성 규칙:\n"
    "- 광고주(사장님)에게 1:1로 브리핑하듯 자연스러운 대화체 문단으로 작성합니다.\n"
    # ⚠️ 마크다운 금지 줄은 스토어(쇼핑) 프롬프트와 같은 규칙 — 화면이 마크다운을 렌더하지 않아
    #    ###·** 가 기호 그대로 노출된다(2026-08-11 직원 신고). 스토어엔 처음부터 있었고 여기만 빠져 있었다.
    "- 아이콘·이모지·마크다운 특수기호(##, ###, **, 표, 코드블록)는 쓰지 않습니다 — 화면에 기호가"
    " 그대로 노출됩니다. 나열이 필요하면 문장으로 풀거나 '1. 2. 3.' 번호만 씁니다.\n"
    "- 반드시 제공된 실데이터(순위·리뷰·저장·경쟁사 지표)에 근거해 구체적 수치로 말합니다.\n"
    # ⚠️ 미확인 지표를 실측처럼 단정하면 **사실이 아닌 진단이 사장님께 나간다**(2026-08-12 실보고서:
    #    10지표가 전부 기본값인데 AI 가 「예약 점수 0점 = 예약 연동이 전혀 안 돼 있다」라고 단정).
    #    화면은 「미확인」이라 밝히는데 AI 만 단정하면 보고서 안에서 두 말이 충돌한다.
    "- **값이 확인되지 않은(미확인) 지표는 판단·비교의 근거로 쓰지 않습니다.**"
    " 데이터에 unknown_metrics 로 표시된 항목은 점수를 인용하지 말고, 그 숫자로 상태를 단정하지도 마세요"
    "(예: 예약 점수가 0이라고 「연동이 안 돼 있다」고 쓰면 안 됩니다 — 확인이 안 된 것뿐입니다).\n"
    "- 미확인 항목은 「아직 확인되지 않았다 · 확인하면 무엇을 알 수 있다」로 짧게 짚고,"
    " 처방은 확인된 지표와 시장·상권 데이터를 근거로 씁니다.\n"
    "- '무엇이 부족한가'가 아니라 '무엇을·왜·얼마나 하면 몇 위가 되는가'로 처방을 씁니다.\n"
    "- 상위권과의 격차는 저장수·블로그 리뷰에서 벌어지는 경우가 많으니 정면 비교로 병목을 특정합니다.\n"
    "- 근거가 약한 예측은 '추정'임을 명시하고 과장하지 않습니다.\n"
    "- 각 섹션은 5~8줄 내외로, 현황 → 핵심 이슈 → 실행 전략 흐름으로 씁니다.\n"
    "- 각 섹션은 [섹션명] 머리표로 구분해 출력합니다."
)


# ============================================================
# 5. 유틸
# ============================================================
def _norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def _to_int(v):
    try:
        if v is None:
            return None
        return int(re.sub(r"[^\d]", "", str(v)) or 0)
    except Exception:
        return None


def _to_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


if __name__ == "__main__":
    # 가중치 합 검증
    assert abs(sum(PLACE_METRIC_WEIGHTS.values()) - 1.0) < 1e-9, "가중치 합이 1.00이 아님"

    # 파싱 자체 검증(축약 샘플 — 오가닉/광고 구분·순위)
    sample = (
        '<li><a data-nmb_rese-doc-id="nad-1071830988"></a><span>천상가옥</span></li>'
        '<li><a data-nmb_res-doc-id="1251057335"></a><span>비아트 성수</span></li>'
        '<li><a data-nmb_res-doc-id="1250235967"></a><span>기댈빙</span></li>'
        '<li><a data-nmb_res-doc-id="2019126383"></a><span>성수르치아바타</span></li>'
    )
    parsed = parse_place_search(sample)
    organic = [i for i in parsed["items"] if not i["is_ad"]]
    assert organic[0]["rank"] == 1 and organic[0]["doc_id"] == "1251057335"
    r = find_place_rank(parsed, target_doc_id="2019126383")
    assert r["state"] == "노출" and r["rank"] == 3, r

    # 점수화 검증(성수동 감성카페 예시)
    res = score_place(
        {"rank": 8, "relevance": 55, "visitor_reviews": 312, "blog_reviews": 148,
         "saves": 1020, "photos": 96, "has_booking": True, "has_talk": True, "has_order": False,
         "news_days": 18, "rep_keyword": False, "info_complete": 80, "review_keyword_focus": 72},
        competitors=[{"visitor_reviews": 1240, "blog_reviews": 402, "saves": 5800},
                     {"visitor_reviews": 880, "blog_reviews": 356, "saves": 4120},
                     {"visitor_reviews": 640, "blog_reviews": 288, "saves": 3050}],
    )
    assert 0 <= res["scores"]["total"] <= 100
    print("place_crawler self-test OK · total =", res["scores"]["total"])
    print("scores:", res["scores"])
