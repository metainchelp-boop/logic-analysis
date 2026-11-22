"""맞춤제안서(v3) 사실값 — 로직분석 보고서가 받아 둔 자료를 제안서가 쓰는 값으로 정리한다 (2026-10-26).

⚠️ **왜 서버에서 만드나**
   제안서 화면(전산 /proposal/v3/)은 **그리기만** 한다. 무엇을 「확인됨」으로, 무엇을
   「미확인」으로 볼지는 **이 파일 한 곳**에서 정한다 — 화면과 문장 생성(proposal_copy)이
   같은 판정을 쓰게 하기 위해서다(갈리면 숫자는 「미노출」인데 문장은 「12위」가 된다).

⚠️ **지어내지 않는다**
   보고서에 없는 값은 ``None`` 으로 둔다. 화면은 그 자리에 「미확인」을 쓴다.
   ``0`` 으로 채우지 않는다 — 0 은 「재 보니 0」이고 None 은 「안 쟀다」이다(종전 사고:
   경쟁 지형 0원 · 1P 평균가 0원).

⚠️ **월 매출 · 월 광고비는 여기서 다루지 않는다**
   보고서에 없는 두 값이다. 화면에서 사람이 넣고, 그 둘이 들어가는 계산(기대 매출·
   절감액·방치 비용)도 화면이 한다.

⚠️ **의존성 없음(표준 라이브러리만)** — 배포 회귀 게이트가 fastapi 없이 import 한다.
"""

import re
from datetime import datetime, timedelta, timezone

import keyword_fit

KST = timezone(timedelta(hours=9))

#: 판정이 바뀌면 화면이 옛 자료를 구분할 수 있게 올린다.
#: 2 (2026-11-16) — 키워드 적합도 판정(keyword_fit) 도입: targets·groups·golden·rows 는 통과분만,
#:   탈락은 keywords.excluded(사유 코드 · 검색량 상위만) · 문장 검사용 전체 목록은 keywords.banned ·
#:   판정 정보는 keywords.gate · 인기어·급상승어에 fit 표시.
FACTS_VERSION = 2

#: 정보성(알아보는) 검색어 표지 — 구매까지 거리가 먼 말. 광고보다 체험단·블로그로 간다.
_INFO_MARKERS = ("추천", "후기", "비교", "순위", "종류", "효능", "효과", "방법", "차이", "만들기",
                 "레시피", "뜻", "가격비교", "브랜드", "랭킹", "best", "BEST")

#: 상세페이지 필수 항목(analyze_detail_page metrics) — 화면 문구는 보고서와 같은 말로.
_DETAIL_ITEMS = (
    ("has_delivery_info", "배송 정보"),
    ("has_return_info", "교환·반품"),
    ("has_gift_info", "사은품"),
    ("has_certification", "인증"),
    ("has_review_section", "후기"),
    ("has_spec_table", "스펙(사양) 표"),
)

#: 보완 요청 문장으로 볼 표지(부정 키워드가 비어도 「~해 주세요」 류 요청은 잡는다).
_REQUEST_MARKERS = ("요청", "아쉬", "개선", "바랍니다", "했으면", "좋겠", "업그레이드", "불편", "다만")


# ───────────────────────── 작은 도구 ─────────────────────────

def to_int(v):
    """네이버 검색량 칸은 「< 10」 같은 글자로도 온다. 못 읽으면 None."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    if s.startswith("<"):
        return 5      # 「< 10」 — 화면도 10 미만으로 본다(0 이 아니다)
    m = re.match(r"^-?\d+(\.\d+)?$", s)
    if not m:
        return None
    return int(float(s))


def to_float(v):
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def comp_label(c):
    """경쟁강도 라벨을 보고서와 같은 세 말(낮음·중간·높음)로."""
    s = str(c or "").strip()
    m = {"LOW": "낮음", "낮음": "낮음", "MEDIUM": "중간", "MID": "중간", "보통": "중간", "중간": "중간",
         "HIGH": "높음", "높음": "높음"}
    return m.get(s, m.get(s.upper(), None))


def _d(x):
    return x if isinstance(x, dict) else {}


def _l(x):
    return x if isinstance(x, list) else []


def _clean(s, n=None):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    if n and len(s) > n:
        s = s[:n].rstrip() + "…"
    return s


def nospace(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


# ───────────────────────── 부분별 정리 ─────────────────────────

def _main_volume(bundle):
    vol = _l(bundle.get("volume"))
    v0 = _d(vol[0]) if vol else {}
    pc, mo = to_int(v0.get("monthlyPcQcCnt")), to_int(v0.get("monthlyMobileQcCnt"))
    total = (pc or 0) + (mo or 0) if (pc is not None or mo is not None) else None
    return {
        "keyword": _clean(bundle.get("keyword")),
        "total": total, "pc": pc, "mobile": mo,
        "clicksPc": to_float(v0.get("monthlyAvePcClkCnt")),
        "clicksMobile": to_float(v0.get("monthlyAveMobileClkCnt")),
        "comp": comp_label(v0.get("compIdx")),
        "adDepth": to_int(v0.get("plAvgDepth")),
    }


def _keyword_rows(related):
    """연관 키워드 — 보고서 표와 같은 칸(검색량·PC·모바일·경쟁강도).

    ``pool``(2026-11-16 가산) — 연관어 응답이 검색량 상위 50개만 남겨 관련 있는 중소 키워드가 잘리던 것을
    막으려고 서버가 상위 300개를 함께 준다. 옛 저장 보고서에는 없다(없으면 종전 50개만)."""
    rows, seen = [], set()
    src = (_l(_d(related).get("related_keywords")) + _l(_d(related).get("golden_keywords"))
           + _l(_d(related).get("pool")))
    for it in src:
        it = _d(it)
        kw = _clean(it.get("keyword"))
        if not kw or nospace(kw) in seen:
            continue
        seen.add(nospace(kw))
        pc, mo = to_int(it.get("monthlyPcQcCnt")), to_int(it.get("monthlyMobileQcCnt"))
        total = to_int(it.get("totalVolume"))
        if total is None and (pc is not None or mo is not None):
            total = (pc or 0) + (mo or 0)
        rows.append({"keyword": kw, "total": total, "pc": pc, "mobile": mo,
                     "comp": comp_label(it.get("compIdx")),
                     "golden": bool(it.get("isGolden")) and not it.get("isStoreName")})
    return rows


def is_info_keyword(kw):
    return any(m in str(kw) for m in _INFO_MARKERS) or keyword_fit.is_info_intent(kw)


def pick_targets(rows, main_kw, n=6):
    """공략 키워드 — **적합도 판정을 통과한 행만 받는다**(build 가 거른 뒤 부른다).

    대표 확정(2026-11-16): 경쟁 「높음」으로 **확인된** 것만 빼고(미확인은 둔다) 검색량 많은 순. 황금 우선 정렬은 없앴다.
    ⚠️ 정보형 말(추천·후기·레시피 …)은 뺀다 — 광고·상품명이 아니라 체험단·블로그 몫이다.
    ⚠️ 2026-11-13 초콜릿 판매자 제안서 사고: 종전엔 판정 없이 경쟁 「중간」이면 통과해 '빼빼로'(387,900)가 1순위가 됐다.
    """
    pool = [r for r in rows if r["total"] and r["comp"] != "높음"
            and not is_info_keyword(r["keyword"]) and nospace(r["keyword"]) != nospace(main_kw)]
    pool.sort(key=lambda r: -(r["total"] or 0))
    return pool[:n]


def group_keywords(rows, targets, main_kw):
    """키워드 확장 세 갈래 — 바로 사는 말 · 방식을 정하고 찾는 말 · 알아보는 말. rows 는 판정 통과분."""
    tset = {r["keyword"] for r in targets}
    buy = [r for r in targets][:5]
    info = [r for r in rows if r["total"] and is_info_keyword(r["keyword"])]
    info.sort(key=lambda r: -(r["total"] or 0))
    used = tset | {r["keyword"] for r in info[:3]} | {nospace(main_kw)}
    method = [r for r in rows if r["total"] and r["keyword"] not in used
              and nospace(r["keyword"]) not in used and not is_info_keyword(r["keyword"])]
    method.sort(key=lambda r: -(r["total"] or 0))
    return {"buy": buy, "method": method[:4], "info": info[:3]}


def _review(html_detail, review_data):
    rd = _d(review_data) or _d(_d(html_detail).get("reviewData"))
    if not rd:
        return None
    ta = _d(rd.get("reviewTextAnalysis"))
    reviews = [_d(r) for r in _l(rd.get("reviews"))]
    count = to_int(rd.get("reviewCount"))
    rating = to_float(rd.get("rating"))
    sent = _d(ta.get("sentiment"))
    strengths = [{"keyword": _clean(k.get("keyword")), "count": to_int(k.get("count")) or 0}
                 for k in map(_d, _l(ta.get("positiveKeywords"))) if _clean(k.get("keyword"))]
    # 구매자 실제 문장 — 긍정 리뷰에서 짧고 구체적인 한 마디(과장 없이 원문 일부).
    sentences, complaints = [], []
    for r in reviews:
        txt = _clean(r.get("text"))
        if not txt:
            continue
        parts = [p.strip() for p in re.split(r"(?<=[.!?…~])\s+|\n", txt) if p.strip()]
        for p in parts:
            if any(m in p for m in _REQUEST_MARKERS):
                complaints.append(_clean(p, 80))
        if r.get("sentiment") == "positive":
            best = None
            for p in parts:
                if any(m in p for m in _REQUEST_MARKERS):
                    continue
                if 8 <= len(p) <= 60 and (best is None or len(p) > len(best)):
                    best = p
            if best:
                sentences.append(_clean(best, 60))
    neg = [_clean(k.get("keyword")) for k in map(_d, _l(ta.get("negativeKeywords"))) if _clean(k.get("keyword"))]
    return {
        "count": count,
        # 보고서는 평점을 내림으로 보인다(4.88 → 4.8) — 같은 숫자를 쓴다.
        "rating": (int(rating * 10) / 10) if rating is not None else None,
        "sampleN": to_int(ta.get("totalExtracted")) or (len(reviews) or None),
        "positivePct": to_int(sent.get("positiveRatio")),
        "avgChars": to_int(ta.get("avgChars")),
        "strengths": strengths[:8],
        "sentences": sentences[:4],
        "complaint": complaints[0] if complaints else None,
        "negativeKeywords": neg[:5],
        "tags": [_clean(t.get("tag")) for t in map(_d, _l(ta.get("tagStats"))) if _clean(t.get("tag"))][:4],
    }


def _detail(html_detail):
    hd = _d(html_detail)
    if not hd:
        return None
    m, sc = _d(hd.get("metrics")), _d(hd.get("scores"))
    has, missing = [], []
    for key, label in _DETAIL_ITEMS:
        if key not in m:
            continue
        (has if m.get(key) else missing).append(label)
    video = to_int(m.get("video_count"))
    if video == 0:
        missing.append("동영상")
    total = to_int(sc.get("total"))
    return {
        "score": total,
        "grade": None if total is None else ("우수" if total >= 70 else "보통" if total >= 40 else "개선 필요"),
        "images": to_int(m.get("total_images")),
        "video": video,
        "textLen": to_int(m.get("text_length")),
        "has": has, "missing": missing,
    }


def _rank(advertiser, screen):
    """순위 — 보고서가 **찾아낸** 값만. 못 찾았으면 「미노출」, 아예 안 쟀으면 None."""
    adv = _d(advertiser)
    rk = _d(adv.get("ranking"))
    seo = _d(_d(_d(screen).get("seo")).get("scores"))
    detail = _d(seo.get("detail"))
    rank = to_int(rk.get("current_rank"))
    if rank is None:
        rank = to_int(detail.get("current_rank"))
    if rank is not None and rank > 0:
        return {"status": "노출", "rank": rank, "page": to_int(rk.get("page_number")) or ((rank - 1) // 40 + 1),
                "searched": to_int(rk.get("total_searched"))}
    if rk or adv:
        searched = to_int(rk.get("total_searched"))
        return {"status": "미노출", "rank": None, "page": None,
                "searched": searched if searched and searched > 0 else None}
    return {"status": "미확인", "rank": None, "page": None, "searched": None}


def month_name(label):
    """데이터랩 월 표기('26.4' · '2026-04' · '202604')를 사람 말(2026년 4월)로. 못 읽으면 그대로."""
    s = str(label or "").strip()
    m = re.match(r"^(\d{2})\.(\d{1,2})$", s) or re.match(r"^(\d{4})[-.](\d{1,2})", s) or re.match(r"^(\d{4})(\d{2})$", s)
    if not m:
        return s
    y, mo = m.group(1), int(m.group(2))
    if len(y) == 2:
        y = "20" + y
    return f"{y}년 {mo}월"


def _datalab(dl, gate=None):
    """⚠️ categoryPopular·rising 은 **카테고리 전체 지표**라 그대로 두되, 항목마다 ``fit``(이 상품에 맞는 말인가)을
    붙인다. 장표 표는 그대로 그리고, 문장은 fit 인 것만 말한다(11/13 사고: 인기어 1위 '빼빼로데이'를 「상품명에 넣으라」고 썼다)."""
    dl = _d(dl)

    def fit(kw):
        if gate is None:
            return None
        return nospace(kw) == gate.main_ns or gate.ok(kw)
    tr = _d(dl.get("trend"))
    months = []
    for m in _l(tr.get("months")):
        m = _d(m)
        lab, val = _clean(m.get("label") or m.get("period")), to_float(m.get("ratio"))
        if lab and val is not None:
            months.append([lab, round(val, 1)])
    peak = None
    if months:
        mx = max(v for _, v in months)
        peak = [l for l, v in months if v == mx]
    wd = _d(dl.get("weekday"))
    days = []
    for d in _l(wd.get("days")):
        d = _d(d)
        lab, val = _clean(d.get("label")), to_float(d.get("index"))
        # ⚠️ 0 은 「수집 빈칸」으로 본다(보고서 토·일 0 사례) — 0 인 날을 「검색 없음」으로 그리지 않는다.
        if lab and val is not None and val > 0:
            days.append([lab, round(val, 1)])
    if days:
        mx = max(v for _, v in days)
        days = [[l, round(v / mx * 100, 1)] for l, v in days]
    peak_day = max(days, key=lambda x: x[1])[0] if days else None
    g = _d(dl.get("gender"))
    ages = [{"label": _clean(a.get("label")), "ratio": to_float(a.get("ratio"))}
            for a in map(_d, _l(_d(dl.get("age")).get("ages"))) if _clean(a.get("label"))]
    ck = _d(dl.get("categoryKeywords"))
    popular = [{"keyword": _clean(p.get("keyword")), "volume": to_int(p.get("volume")), "growth": to_float(p.get("growth")),
                "fit": fit(_clean(p.get("keyword")))}
               for p in map(_d, _l(ck.get("popular"))) if _clean(p.get("keyword"))]
    rising = [{"keyword": _clean(p.get("keyword")), "volume": to_int(p.get("volume")), "growth": to_float(p.get("growth")),
               "fit": fit(_clean(p.get("keyword")))}
              for p in map(_d, _l(ck.get("rising"))) if _clean(p.get("keyword"))]
    avg = round(sum(v for _, v in months) / len(months)) if months else None
    return {
        "months": months, "peakMonths": peak, "avgIndex": avg,
        "peakMonthNames": [month_name(x) for x in (peak or [])],
        "weekday": days, "peakDay": peak_day,
        "gender": ({"male": to_float(g.get("male")), "female": to_float(g.get("female"))}
                   if g.get("male") is not None else None),
        "ages": ages or None,
        "categoryPopular": popular[:8], "rising": rising[:5],
        "categoryBasis": _clean(ck.get("basis")) or None,
    }


def _strategies(advertiser):
    es = _d(_d(advertiser).get("entry_strategy"))
    out = []
    for s in map(_d, _l(es.get("strategies"))):
        area = _clean(s.get("area"))
        if not area or area == "실행 로드맵":
            continue
        recs = []
        for r in _l(s.get("recommendations")):
            if isinstance(r, dict):
                name = _clean(r.get("name") or r.get("service") or r.get("title"))
                desc = _clean(r.get("desc") or r.get("description") or r.get("reason"), 70)
                if name:
                    recs.append({"name": name, "desc": desc})
            elif _clean(r):
                recs.append({"name": _clean(r, 40), "desc": ""})
        out.append({
            "area": area,
            "urgent": s.get("severity") == "high",
            "insights": [_clean(x, 120) for x in _l(s.get("insights")) if _clean(x)][:3],
            "recs": recs[:4],
        })
    score = to_int(es.get("overall_score"))
    return {"score": score,
            "label": None if score is None else ("양호" if score >= 70 else "보통" if score >= 40 else "개선 필요"),
            "cards": out[:4]}


def _competitors(advertiser, shop_products):
    """1페이지 경쟁 — 값이 **실제로 있을 때만**. 비어 있으면 None(0원으로 그리지 않는다)."""
    cc = _d(_d(advertiser).get("competitor_comparison"))
    st, items = _d(cc.get("stats")), _l(cc.get("items"))
    prices = [to_int(_d(i).get("price")) for i in items]
    prices = [p for p in prices if p and p > 0]
    if not prices:
        prices = [to_int(_d(p).get("price")) for p in _l(shop_products)[:40]]
        prices = [p for p in prices if p and p > 0]
    if not prices:
        return None
    avg = to_int(st.get("avg_price")) or int(sum(prices) / len(prices))
    return {"count": len(prices), "avgPrice": avg if avg and avg > 0 else None,
            "minPrice": min(prices), "maxPrice": max(prices)}


def _seo(screen):
    seo = _d(_d(screen).get("seo"))
    total = to_int(_d(seo.get("scores")).get("total"))
    if total is None:
        return None
    sug = []
    for s in _l(seo.get("suggestions")):
        t = _clean(s.get("text") if isinstance(s, dict) else s, 90)
        if t:
            sug.append(t)
    return {"score": total, "label": "양호" if total >= 70 else "보통" if total >= 40 else "개선 필요",
            "suggestions": sug[:4]}


def _bid(screen):
    """파워링크 공식 입찰가(화면 CpcBidEstimateSection 이 받은 /keyword/bid-estimate 그대로).

    모양: {"pc": [{"position":1,"bid":..}...], "mobile": [...], "minBid": {"pc":..,"mobile":..}}
    """
    b = _d(_d(screen).get("bid"))
    if not b:
        return None

    def pos(rows, n):
        for r in _l(rows):
            if isinstance(r, dict) and to_int(r.get("position")) == n:
                return to_int(r.get("bid"))
        return None

    mb = _d(b.get("minBid"))
    out = {"pc1": pos(b.get("pc"), 1), "mobile1": pos(b.get("mobile"), 1),
           "pc5": pos(b.get("pc"), 5), "mobile5": pos(b.get("mobile"), 5),
           "minPc": to_int(mb.get("pc")), "minMobile": to_int(mb.get("mobile"))}
    out = {k: v for k, v in out.items() if v}
    return out or None


def _category_path(src):
    """한 출처의 업종 경로 — 통째 경로(category)가 있으면 그것, 없으면 category1~4 를 잇는다.
    글자가 아닌 값(숫자·참거짓·묶음)은 버린다 — 「123」 같은 값이 다음 출처의 진짜 업종을 가리지 않게."""
    def text(v):
        return _clean(v) if isinstance(v, str) else ""
    whole = text(src.get("category"))
    if whole:
        return whole
    return " > ".join(x for x in (text(src.get("category%d" % i)) for i in range(1, 5)) if x)


def _product(bundle, html_detail, advertiser, analysis):
    pi = _d(_d(advertiser).get("product_info"))
    tp = _d(_d(analysis).get("targetProductInfo"))
    rd = _d(_d(html_detail).get("reviewData"))
    name = _clean(bundle.get("productName") or pi.get("product_name") or tp.get("product_name"))
    price = to_int(pi.get("price")) or to_int(tp.get("price")) or to_int(rd.get("price"))
    # 업종 — 상품 페이지 → 광고주 분석(productId 로 맞춘 상품) → 키워드 분석 순.
    # ⚠️ 신고 #301(2026-10-30): 상품 페이지에서 못 읽으면 광고주 분석이 받아 둔 업종을 안 보고 「업종 미확인」이 됐다.
    cat = _category_path(rd) or _category_path(pi) or _category_path(tp)
    return {"name": name or None, "price": price if price and price > 0 else None,
            "category": re.sub(r"\s*>\s*", " > ", cat) or None,
            "categoryLeaf": (re.split(r"\s*>\s*", cat)[-1] if cat else None),
            # 판매자 태그(2026-11-16 가산) — 상세 진단이 읽은 것. 키워드 적합도 판정에 쓴다. 없으면 [].
            "tags": _seller_tags(html_detail, pi)}


def _seller_tags(html_detail, pi):
    for src in (_d(html_detail).get("sellerTags"), pi.get("tags"),
                [t.get("text") for t in map(_d, _l(_d(pi.get("seoInfo")).get("sellerTags")))]):
        tags = [_clean(t) for t in _l(src) if isinstance(t, str) and _clean(t)]
        if tags:
            return list(dict.fromkeys(tags))[:20]
    return []


def _competitor_names(advertiser, shop_products):
    """검색 결과 1페이지의 타사 스토어명·브랜드·제조사(판정의 타사 브랜드 규칙에 쓴다)."""
    names = []
    for it in map(_d, _l(_d(_d(advertiser).get("competitor_comparison")).get("items"))):
        names += [it.get("store_name"), it.get("mall_name"), it.get("brand"), it.get("maker")]
    for p in map(_d, _l(shop_products)[:80]):
        names += [p.get("store_name") or p.get("mallName") or p.get("mall_name"), p.get("brand"), p.get("maker")]
    return [n for n in names if isinstance(n, str) and n.strip()]


def make_gate(bundle, now=None, product=None):
    """인계 자료 한 벌 → 키워드 적합도 판정기. 제안서와 /api/keywords/fit 이 같은 것을 쓴다."""
    b = _d(bundle)
    hd, adv, ana = _d(b.get("htmlDetail")), _d(b.get("advertiser")), _d(b.get("analysis"))
    product = product or _product(b, hd, adv, ana)
    now = now or datetime.now(KST)
    store = " ".join(x for x in (_clean(b.get("name")), _clean(_d(hd.get("storeInfo")).get("name"))) if x)
    return keyword_fit.Gate(dict(product, store=store), _clean(b.get("keyword")), today=now,
                            competitor_names=_competitor_names(adv, b.get("shopProducts")))


def gate_rows(rows, gate):
    """연관 키워드 행 → (통과 행, 탈락 목록). 탈락 목록에는 영업자 확인용으로 키워드·검색량·사유만 남긴다.
    정보 탐색어는 통과(정보 그룹으로 감)이지만 공략에서 빠진 사실을 남기려고 사유 info_intent 로도 적는다."""
    passed, excluded = gate.split(rows)
    out = [{"keyword": r["keyword"], "total": r.get("total"), "reason": r["reason"]} for r in excluded]
    out += [{"keyword": r["keyword"], "total": r.get("total"), "reason": "info_intent"} for r in passed if r.get("infoIntent")]
    out.sort(key=lambda r: -(r.get("total") or 0))
    for r in passed:
        r.pop("infoIntent", None)
    return passed, out


#: 묶음·화면에 싣는 탈락 키워드 수(검색량 상위). 문장 검사는 이 한도와 무관하게 전부 본다(banned_keys).
EXCLUDED_SHOWN = 60


def banned_keys(excluded):
    """탈락 목록 전체 → 문장에 나오면 안 되는 말(공백 뗀 글자 · 중복 없음). 정보 탐색어는 정보 그룹에 쓰이므로 뺀다."""
    out = []
    for r in excluded or []:
        if r.get("reason") == "info_intent":
            continue
        ns = nospace(r.get("keyword"))
        if len(ns) >= 2 and ns not in out:
            out.append(ns)
    return out


def _store_name(bundle, html_detail):
    si = _d(_d(html_detail).get("storeInfo"))
    return _clean(bundle.get("name") or si.get("name")) or "고객사"


def name_keyword_head(product_name, n=30):
    return (product_name or "")[:n]


# ───────────────────────── 한 번에 ─────────────────────────

def build(bundle, now=None):
    """인계 자료 → 제안서 사실값. 어떤 칸이 비어도 예외를 내지 않는다(그 칸이 None 이 될 뿐)."""
    b = _d(bundle)
    hd = _d(b.get("htmlDetail"))
    adv = _d(b.get("advertiser"))
    ana = _d(b.get("analysis"))
    screen = _d(b.get("screen"))
    now = now or datetime.now(KST)

    main = _main_volume(b)
    product = _product(b, hd, adv, ana)
    # 키워드 적합도 판정 — 이 상품을 찾는 말만 남긴다(2026-11-13 '빼빼로' 사고). 이 아래 키워드는 전부 통과분이다.
    gate = make_gate(b, now=now, product=product)
    rows, excluded = gate_rows(_keyword_rows(b.get("related")), gate)
    targets = pick_targets(rows, main["keyword"])
    groups = group_keywords(rows, targets, main["keyword"])
    head = name_keyword_head(product["name"])
    # 상품명 처방 — 시즌어('수능초콜릿')는 며칠 뒤 지나가므로 상품명에 넣으라고 하지 않는다(공략·광고 키워드로는 남긴다).
    targets_missing = [r["keyword"] for r in targets[:2] if keyword_fit.name_worthy(r["keyword"])
                       and nospace(r["keyword"]) not in nospace(head)]

    rel = _d(b.get("related"))
    golden = [r for r in rows if r["golden"]]

    device = None
    if main["pc"] is not None and main["mobile"] is not None and (main["pc"] + main["mobile"]) > 0:
        mob = round(main["mobile"] / (main["pc"] + main["mobile"]) * 100)
        device = {"mobile": mob, "pc": 100 - mob}

    facts = {
        "version": FACTS_VERSION,
        "generatedAt": now.strftime("%Y-%m-%d %H:%M"),
        "reportDate": now.strftime("%Y.%m.%d"),
        "store": {"name": _store_name(b, hd), "url": _clean(b.get("storeUrl")) or None},
        "product": product,
        "main": main,
        "device": device,
        "keywords": {
            "rows": rows[:30],
            "total": to_int(rel.get("total_found")) or len(rows) or None,
            "golden": golden[:5],
            "targets": targets,
            "groups": groups,
            "targetsMissingInName": targets_missing,
            # ⚠️ 영업자 확인용 — 고객용 장표·문장에 쓰지 않는다(deck.js 는 읽지 않는다). 검색량 상위 EXCLUDED_SHOWN 개만 싣는다.
            "excluded": excluded[:EXCLUDED_SHOWN],
            "excludedTotal": len(excluded),
            # ⚠️ 문장 검사용 — 탈락 **전부**(정보 탐색어 제외 · 공백 뗀 글자). 위 표시 한도와 따로 둔다:
            #    한도 밖(61번째~) 탈락어를 AI 문장이 권해도 검사에 걸리게 하려는 것이다(proposal_copy._banned_keywords).
            "banned": banned_keys(excluded),
            "gate": gate.describe(),
        },
        "review": _review(hd, b.get("htmlReview")),
        "detail": _detail(hd),
        "seo": _seo(screen),
        "rank": _rank(adv, screen),
        "datalab": _datalab(b.get("datalab"), gate),
        "entry": _strategies(adv),
        "competitors": _competitors(adv, b.get("shopProducts")),
        "bid": _bid(screen),
        "ai": _clean(_d(screen.get("ai")).get("full_text"), 6000) or None,
    }
    facts["flags"] = flags(facts)
    return facts


def flags(f):
    """화면·문장이 함께 쓰는 판정 — 갈리지 않게 한 곳에서."""
    rank = _d(f.get("rank"))
    rv = _d(f.get("review"))
    dt = _d(f.get("detail"))
    kw = _d(f.get("keywords"))
    exposure_gap = rank.get("status") != "노출" or (rank.get("rank") or 999) > 40
    trust_ok = (rv.get("count") or 0) >= 30 and (rv.get("rating") or 0) >= 4.5
    detail_ok = (dt.get("score") or 0) >= 70
    weakest = "유입" if exposure_gap else ("신뢰" if not trust_ok else ("구매" if not detail_ok else "재구매"))
    return {
        "exposureGap": exposure_gap,
        "trustOk": trust_ok,
        "detailOk": detail_ok,
        "nameMissesTargets": bool(kw.get("targetsMissingInName")),
        "weakest": weakest,
        "hasCompetitors": bool(f.get("competitors")),
        "hasSeason": bool(_d(f.get("datalab")).get("months")),
        "hasWeekday": bool(_d(f.get("datalab")).get("weekday")),
        "hasDemographics": bool(_d(f.get("datalab")).get("gender") or _d(f.get("datalab")).get("ages")),
    }
