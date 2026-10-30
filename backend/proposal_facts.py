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

KST = timezone(timedelta(hours=9))

#: 판정이 바뀌면 화면이 옛 자료를 구분할 수 있게 올린다.
FACTS_VERSION = 1

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
    """연관 키워드 — 보고서 표와 같은 칸(검색량·PC·모바일·경쟁강도)."""
    rows, seen = [], set()
    for it in _l(_d(related).get("related_keywords")) + _l(_d(related).get("golden_keywords")):
        it = _d(it)
        kw = _clean(it.get("keyword"))
        if not kw or kw in seen:
            continue
        seen.add(kw)
        pc, mo = to_int(it.get("monthlyPcQcCnt")), to_int(it.get("monthlyMobileQcCnt"))
        total = to_int(it.get("totalVolume"))
        if total is None and (pc is not None or mo is not None):
            total = (pc or 0) + (mo or 0)
        rows.append({"keyword": kw, "total": total, "pc": pc, "mobile": mo,
                     "comp": comp_label(it.get("compIdx")),
                     "golden": bool(it.get("isGolden")) and not it.get("isStoreName")})
    return rows


def is_info_keyword(kw):
    return any(m in str(kw) for m in _INFO_MARKERS)


def pick_targets(rows, main_kw, n=6):
    """공략 키워드 — 검색량이 있고 경쟁이 「높음」이 아닌 구매형 말부터.

    ⚠️ 정보형 말(추천·후기 …)은 뺀다 — 광고·상품명이 아니라 체험단·블로그 몫이다.
    ⚠️ 낮음·중간이 모자라면 높음으로 채우지 않는다(「이길 수 있는 키워드」 장의 뜻이 깨진다).
    """
    pool = [r for r in rows if r["total"] and r["comp"] in ("낮음", "중간")
            and not is_info_keyword(r["keyword"]) and nospace(r["keyword"]) != nospace(main_kw)]
    pool.sort(key=lambda r: (0 if r["golden"] else 1, -(r["total"] or 0)))
    return pool[:n]


def group_keywords(rows, targets, main_kw):
    """키워드 확장 세 갈래 — 바로 사는 말 · 방식을 정하고 찾는 말 · 알아보는 말."""
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


def _datalab(dl):
    dl = _d(dl)
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
    popular = [{"keyword": _clean(p.get("keyword")), "volume": to_int(p.get("volume")), "growth": to_float(p.get("growth"))}
               for p in map(_d, _l(ck.get("popular"))) if _clean(p.get("keyword"))]
    rising = [{"keyword": _clean(p.get("keyword")), "volume": to_int(p.get("volume")), "growth": to_float(p.get("growth"))}
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
    """한 출처의 업종 경로 — 통째 경로(category)가 있으면 그것, 없으면 category1~4 를 잇는다."""
    whole = src.get("category")
    whole = _clean(whole) if isinstance(whole, str) else ""
    if whole:
        return whole
    return " > ".join(x for x in (_clean(src.get("category%d" % i)) for i in range(1, 5)) if x)


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
            "categoryLeaf": (re.split(r"\s*>\s*", cat)[-1] if cat else None)}


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
    rows = _keyword_rows(b.get("related"))
    targets = pick_targets(rows, main["keyword"])
    groups = group_keywords(rows, targets, main["keyword"])
    product = _product(b, hd, adv, ana)
    head = name_keyword_head(product["name"])
    targets_missing = [r["keyword"] for r in targets[:2] if nospace(r["keyword"]) not in nospace(head)]

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
        },
        "review": _review(hd, b.get("htmlReview")),
        "detail": _detail(hd),
        "seo": _seo(screen),
        "rank": _rank(adv, screen),
        "datalab": _datalab(b.get("datalab")),
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
