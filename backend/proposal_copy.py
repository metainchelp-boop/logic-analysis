"""맞춤제안서(v3) 문장 — 사실값(proposal_facts)으로 서술형 문장을 만든다 (2026-10-26).

두 겹으로 만든다.
  ① ``template(facts)`` — 규칙으로 쓰는 문장. **항상** 나온다(AI 가 없어도 제안서가 빈칸이 되지 않는다).
  ② ``generate(facts)`` — AI 가 같은 칸을 더 자연스럽게 다시 쓴다. ``validate`` 를 통과한 칸만
     ①을 덮는다. 통과 못 한 칸은 ①이 그대로 남는다.

⚠️ **AI 가 숫자를 지어내면 안 된다** — 검사(validate)는 문장 속 숫자가 사실값에서 나온
   숫자인지 하나하나 대조한다. 하나라도 낯선 숫자가 있으면 그 칸을 버린다.
⚠️ **매출·광고비 금액은 문장에 쓰지 않는다** — 월 매출·월 광고비는 화면에서 사람이 넣는 값이라
   이 단계에서는 모른다. 금액이 필요한 문장은 화면이 계산해 채운다.
⚠️ **「보장」 류 말 금지** — 제안서 하단 안내(「노출수·매출액을 보장하지 않습니다」)와 어긋난다.

⚠️ AI 호출은 ``generate`` 안에서만 일어나고 anthropic 은 그 안에서 import 한다
   — 배포 회귀 게이트는 anthropic 없이 이 파일을 import 한다.
"""

import json
import re

#: 기존 AI 피드백(/api/ai/feedback-all)과 같은 모델을 쓴다(한 곳에서 바꾸면 둘 다 바뀌지는 않으니 함께 볼 것).
MODEL = "claude-sonnet-4-6"

#: 칸 이름과 길이 상한(글자). AI 가 이 밖의 칸을 주면 버린다.
FIELDS = {
    "summary.conclusion": 90, "summary.now": 120, "summary.problem": 120, "summary.solution": 90,
    "diag.situation": 260, "diag.bottleneck": 260, "diag.opportunity": 260,
    "diag.pain1.b": 60, "diag.pain1.t": 140, "diag.pain2.b": 60, "diag.pain2.t": 140,
    "diag.pain3.b": 60, "diag.pain3.t": 140,
    "data.gap1": 70, "data.gap2": 70, "data.gap3": 70,
    "data.improve1": 70, "data.improve2": 70, "data.improve3": 70,
    "funnel.killer": 420,
    "voc.hook1.t": 60, "voc.hook1.use": 70, "voc.hook2.t": 60, "voc.hook2.use": 70,
    "voc.hook3.t": 60, "voc.hook3.use": 70, "voc.killer": 520,
    "h2h.killer": 380,
    "market.b": 90, "market.p": 90, "market.d": 90, "market.killer": 480,
    "timing.b": 120, "timing.killer": 420,
    "persona.killer": 380,
    "targets.killer": 380,
    "expand.killer": 360,
    "oppcost.lead": 220,
}

_BANNED = ("보장", "반드시", "확실히", "100%", "무조건", "1위 달성", "약속드")


# ───────────────────────── 조사 ─────────────────────────

_JOSA = {"은": ("은", "는"), "는": ("은", "는"), "이": ("이", "가"), "가": ("이", "가"),
         "을": ("을", "를"), "를": ("을", "를"), "과": ("과", "와"), "와": ("과", "와")}


def j(word, josa):
    """받침에 맞는 조사를 붙인다. 한글로 끝나지 않으면(영문·숫자·따옴표) 받침 있는 쪽을 쓴다."""
    w = str(word or "")
    a, b = _JOSA[josa]
    last = w.rstrip("'\"」)")[-1:] if w else ""
    if last and "가" <= last <= "힣":
        return w + (a if (ord(last) - 0xAC00) % 28 else b)
    return w + a


# ───────────────────────── 숫자 표기 ─────────────────────────

def n(v):
    try:
        return f"{int(v):,}"
    except Exception:
        return "-"


def _q(s):
    return f"'{s}'"


def _get(d, path, default=None):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
    return default if cur is None else cur


# ───────────────────────── ① 규칙 문장 ─────────────────────────

def template(f):
    store = _get(f, "store.name", "고객사")
    prod = _get(f, "product", {}) or {}
    main = _get(f, "main", {}) or {}
    kw = main.get("keyword") or "대표 키워드"
    rv = f.get("review") or {}
    dt = f.get("detail") or {}
    seo = f.get("seo") or {}
    rank = f.get("rank") or {}
    fl = f.get("flags") or {}
    kws = f.get("keywords") or {}
    targets = kws.get("targets") or []
    t1 = targets[0] if targets else None
    t2 = targets[1] if len(targets) > 1 else None
    dl = f.get("datalab") or {}
    pop = dl.get("categoryPopular") or []
    rising = dl.get("rising") or []

    def tk(t):
        return f"{_q(t['keyword'])}(월 {n(t['total'])}회)" if t else ""

    tpair = " · ".join(x for x in (tk(t1), tk(t2)) if x)
    # 상품명에 이미 들어 있는 키워드를 「없다」고 쓰지 않는다 — 빠진 것만 말한다.
    missing = set(kws.get("targetsMissingInName") or [])
    miss = [t for t in targets if t["keyword"] in missing][:2]
    mpair = " · ".join(tk(t) for t in miss)
    mnames = "·".join(_q(t["keyword"]) for t in miss)
    tnames = "·".join(_q(t["keyword"]) for t in targets[:2]) or "검색량이 큰 키워드"
    rank_txt = (f"{rank.get('rank')}위" if rank.get("status") == "노출"
                else ("상위권 노출이 확인되지 않은" if rank.get("status") == "미노출" else "순위를 확인하지 못한"))
    trust_txt = (f"리뷰 {n(rv.get('count'))}건·평점 {rv.get('rating')}점" if rv.get("count") else "리뷰 정보 미확인")
    detail_txt = (f"상세페이지 진단 {dt.get('score')}점({dt.get('grade')})" if dt.get("score") is not None else "")
    c = {}

    # 3줄 요약
    if fl.get("exposureGap"):
        c["summary.conclusion"] = f"{store}의 성장 병목은 노출 결손입니다 — 상품명·상세페이지·광고를 함께 고치면 90일 안에 반등할 수 있습니다"
        c["summary.now"] = f"{trust_txt}의 신뢰를 갖췄지만, {_q(kw)} 검색에서 {rank_txt} 상태입니다."
    else:
        c["summary.conclusion"] = f"{j(store, '은')} 이미 노출을 확보했습니다 — 전환과 재구매를 끌어올리면 매출 성장 속도를 높일 수 있습니다"
        c["summary.now"] = f"{_q(kw)} 검색 {rank_txt}에 {j(trust_txt, '을')} 확보한 상태입니다."
    c["summary.problem"] = (f"고객이 실제로 찾는 {j(mpair, '가')} 상품명 앞에 없어 검색 수요를 놓치고 있습니다."
                            if mpair else
                            f"{_q(kw)} 수요를 매출로 바꾸는 전환·재구매 장치가 더 필요합니다.")
    c["summary.solution"] = "12개 품목을 노출·전환·재구매 3축으로 통합 운영해 매출을 끌어올립니다."

    # 진단 서술
    price_txt = f"{n(prod.get('price'))}원에 판매하고 있으며, " if prod.get("price") else ""
    pname = (prod.get("categoryLeaf") + " 상품") if prod.get("categoryLeaf") else "상품"
    strength = ", ".join(f"'{s['keyword']}'" for s in (rv.get("strengths") or [])[:2])
    sit = f"{j(store, '은')} {j(pname, '을')} {price_txt}{trust_txt}의 신뢰 기반"
    sit += f"과 {detail_txt}의 완성도를 갖추고 있습니다." if detail_txt else "을 갖추고 있습니다."
    if strength:
        sit += f" 구매자는 {strength} 같은 말을 가장 많이 남기고 있어 상품 만족도는 높은 편입니다."
    c["diag.situation"] = sit
    bt = []
    if fl.get("nameMissesTargets") and t1:
        bt.append("그러나 상품명과 판매 키워드가 고객의 검색어와 어긋나 있습니다.")
    if main.get("total") is not None:
        bt.append(f"분석 키워드 {j(_q(kw), '는')} 월 {n(main.get('total'))}회 검색되고,")
    bt.append(f"현재 이 키워드에서 {rank_txt} 상태입니다." if rank.get("status") != "노출" else f"현재 {rank_txt}에 노출되고 있습니다.")
    if seo.get("score") is not None:
        bt.append(f"SEO 진단은 {seo['score']}점({seo['label']})입니다.")
    c["diag.bottleneck"] = " ".join(bt)
    if t1:
        op = f"같은 상품으로 {j(tpair, '를')} 공략할 수 있습니다."
        r0 = rising[0] if rising else None
        if r0 and r0.get("growth"):
            op += f" 특히 {j(_q(r0['keyword']), '는')} 최근 {r0['growth']}% 늘어난 급상승 키워드입니다."
        comps = {t["comp"] for t in targets[:2] if t.get("comp")}
        if comps:
            op += f" 경쟁강도가 '{'·'.join(sorted(comps))}'이므로, 상품명 정비와 쇼핑검색광고를 함께 진행하면 빠르게 노출을 늘릴 수 있습니다."
    else:
        op = "연관 키워드에서 검색량이 있는 구매형 말을 골라 상품명과 광고에 반영하면 노출 면적을 넓힐 수 있습니다."
    c["diag.opportunity"] = op

    pains = []
    if fl.get("exposureGap"):
        pains.append(("리뷰와 평점은 좋은데 신규 주문이 기대만큼 늘지 않으실 것입니다." if fl.get("trustOk") else
                      "신규 주문이 기대만큼 늘지 않으실 것입니다.",
                      "고객이 검색하는 말로 상품이 보이지 않아 처음 보는 고객이 상품을 만날 기회 자체가 적기 때문입니다."))
    else:
        pains.append(("노출은 되는데 매출로 이어지는 비율이 아쉬우실 것입니다.",
                      "들어온 고객을 결제까지 이끄는 상세페이지·후기·혜택 장치가 부족하면 노출이 매출로 바뀌지 않습니다."))
    pains.append(("광고를 해 봐도 쓴 돈만큼 효과가 있는지 확신하기 어려우셨을 것입니다.",
                  "검색량이 작은 말에 집중하면 클릭이 적고, 큰 키워드는 경쟁이 높아 비용 부담이 큽니다."
                  if (main.get("total") or 0) < 1000 else
                  "전환 추적 없이 광고를 운영하면 어떤 키워드가 매출로 이어졌는지 알 수 없습니다."))
    pains.append(("매출이 단골 재주문에 기대고 있어 성장이 정체된 느낌이 드실 것입니다.",
                  "신규 유입이 적으면 재구매 고객만으로는 매출이 오르기 어렵고, 수요가 몰리는 시기에 준비가 안 되어 있으면 그 기회도 경쟁사에 넘어갑니다."))
    for i, (b, t) in enumerate(pains[:3], 1):
        c[f"diag.pain{i}.b"], c[f"diag.pain{i}.t"] = b, t

    gaps, imp = [], []
    if mnames:
        gaps.append(f"상품명 앞부분에 검색량 큰 {j(mnames, '가')} 없습니다")
        imp.append(f"{j(mnames, '를')} 상품명 앞 30자 안에 배치")
    if dt.get("missing"):
        gaps.append(f"상세페이지에 {j('·'.join(dt['missing'][:2]), '이')} 없습니다")
    if main.get("comp") == "높음" or (main.get("adDepth") or 0) >= 5:
        ad = f"(평균 광고 {main.get('adDepth')}개)" if main.get("adDepth") else ""
        gaps.append(f"파워링크 경쟁이 높습니다{ad}")
    if (rv.get("count") or 0) < 100:
        imp.append("포토리뷰 30개 이상 확보로 전환 임계점 돌파")
    peak = dl.get("peakMonthNames") or []
    if peak:
        imp.append(f"수요가 가장 높았던 {peak[0]} 같은 시기 전에 광고·SEO 선점")
    while len(gaps) < 3:
        gaps.append(["전환 추적(픽셀) 장치가 없어 광고 성과 확인이 어렵습니다",
                     "재구매를 이끄는 메시지·이벤트 운영이 부족합니다",
                     "후기 콘텐츠(블로그·인스타)가 검색에 충분히 쌓이지 않았습니다"][len(gaps) % 3])
    while len(imp) < 3:
        imp.append(["쇼핑검색광고로 초기 노출과 판매 데이터 확보",
                    "리뷰·알림받기·쿠폰 이벤트로 재구매 유도",
                    "전환 추적 스크립트 설치로 광고 효율 측정"][len(imp) % 3])
    for i in range(3):
        c[f"data.gap{i+1}"], c[f"data.improve{i+1}"] = gaps[i], imp[i]

    # 퍼널
    weakest = fl.get("weakest")
    fk = f"{store}의 퍼널에서 가장 큰 누수는 「{weakest}」 단계입니다. "
    if weakest == "유입":
        fk += (f"{trust_txt}{(' · ' + detail_txt) if detail_txt else ''}은 들어온 고객을 구매로 바꿀 힘이 있다는 뜻이지만, "
               "고객이 검색하는 말로 상품이 보이지 않으면 그 힘을 쓸 기회가 없습니다. "
               "따라서 상품명 정비와 쇼핑검색광고로 유입을 먼저 열고, 그다음 상세페이지·포토리뷰로 전환을 한 단계 더 끌어올리는 순서가 맞습니다.")
    elif weakest == "신뢰":
        fk += "노출은 확보됐지만 후기·평점이 구매 결정을 받쳐 주지 못합니다. 체험단과 리뷰 이벤트로 신뢰 자산을 먼저 쌓아야 유입이 매출로 바뀝니다."
    elif weakest == "구매":
        fk += "들어온 고객이 상세페이지에서 결제로 넘어가지 못합니다. 상세페이지 구성과 첫 화면 문구를 구매 결정 순서에 맞춰 다시 짜는 것이 우선입니다."
    else:
        fk += "노출·신뢰·구매는 갖춰져 있으므로, 이벤트·메시지로 재구매를 끌어올리면 같은 고객에게서 매출이 더 나옵니다."
    c["funnel.killer"] = fk

    # 고객의 말
    sents = rv.get("sentences") or []
    strengths = [s["keyword"] for s in (rv.get("strengths") or [])]
    hooks = []
    for s in sents[:3]:
        hooks.append((f"\"{s[:28]}\"", "실제 리뷰 문장 · 썸네일·광고 소재 · 상세페이지 첫 화면"))
    while len(hooks) < 3:
        sw = strengths[len(hooks)] if len(strengths) > len(hooks) else None
        hooks.append((f"구매자가 먼저 말한 '{sw}' — 직접 확인해 보세요" if sw else "구매 후기로 확인하는 만족",
                      "강점 키워드 · 체험단 제목·광고 소재"))
    for i, (t, u) in enumerate(hooks[:3], 1):
        c[f"voc.hook{i}.t"], c[f"voc.hook{i}.use"] = t, u
    vk = ""
    if strengths:
        vk = f"구매자 리뷰에서 가장 많이 나온 말은 {', '.join(_q(s) for s in strengths[:4])}입니다. "
    vk += "위 문구는 모두 실제 리뷰 표현을 바탕으로 만들어 과장 없이 쓸 수 있습니다. "
    if rv.get("complaint"):
        vk += f"반대로 반복된 보완 요청(「{rv['complaint'][:40]}」)은 상세페이지에 미리 안내해 두면 구매 망설임을 줄일 수 있습니다. "
    vk += "이 강점 키워드를 체험단 가이드에도 필수로 넣어, 새로 쌓이는 후기가 같은 메시지를 반복하도록 설계합니다."
    c["voc.killer"] = vk

    # 정면 비교
    comp = f.get("competitors")
    if comp:
        c["h2h.killer"] = (f"1페이지 상품 {comp['count']}개의 평균 판매가는 {n(comp['avgPrice'])}원입니다. "
                           "가격만으로 싸우기보다 상품명 SEO와 리뷰로 자연 노출을 함께 확보해야 같은 예산으로 우위를 만들 수 있습니다.")
    else:
        hk = "이번 분석에서는 1페이지 경쟁 상품 값이 수집되지 않아 격차를 숫자로 계산하지 않았습니다. "
        if main.get("comp") == "높음":
            hk += f"다만 {j(_q(kw), '는')} 광고 경쟁이 '높음'인 키워드로 확인되었습니다. 경쟁사도 광고로 자리를 지키고 있다는 뜻이므로, 광고만으로 싸우기보다 상품명 SEO와 리뷰로 자연 노출을 함께 확보해야 같은 예산으로 우위를 만들 수 있습니다."
        else:
            hk += "경쟁 상품 정보를 받아 정밀 비교한 뒤 격차부터 좁힙니다."
        c["h2h.killer"] = hk

    # 시장 지형
    leaf = prod.get("categoryLeaf") or "이"
    c["market.b"] = f"{leaf} 카테고리에서 고객이 가장 많이 찾는 키워드를 데이터랩으로 분석했습니다."
    c["market.p"] = "고객은 상품의 세부 이름보다 넓은 말과 용량·용도 같은 말로 먼저 검색합니다."
    c["market.d"] = "고객의 검색어를 상품명·광고에 그대로 옮겨 수요를 받습니다."
    if pop:
        top = pop[0]
        mk = f"{leaf} 카테고리에서 가장 많이 찾는 말은 {_q(top['keyword'])}입니다. "
        r0 = rising[0] if rising else None
        if r0 and r0.get("growth"):
            mk += f"{j(_q(r0['keyword']), '는')} 최근 {r0['growth']}% 늘어 급상승 키워드에도 올랐습니다. "
        mk += "고객이 쓰는 이 말들을 상품명 앞부분과 광고 키워드에 넣으면 이미 있는 수요를 바로 받을 수 있습니다. "
        info = [p for p in pop if any(m in p["keyword"] for m in ("추천", "후기", "비교"))]
        if info:
            mk += f"반면 {_q(info[0]['keyword'])}처럼 정보를 찾는 말은 구매까지 거리가 멀어, 광고보다는 체험단·블로그 후기로 접근하는 편이 효율적입니다."
        c["market.killer"] = mk
    else:
        c["market.killer"] = "이번 분석에서는 카테고리 인기 키워드가 수집되지 않았습니다. 연관 키워드의 검색량을 기준으로 공략 순서를 정합니다."

    # 타이밍
    months = dl.get("months") or []
    if months:
        pk = dl.get("peakMonthNames") or []
        c["timing.b"] = (f"{_q(kw)} 검색은 평소 평균 {dl.get('avgIndex')} 수준이다가 {', '.join(pk[:2])}에 가장 높았습니다(최고 100 기준)."
                         if pk else f"{_q(kw)} 월별 검색 지수를 분석했습니다.")
    else:
        c["timing.b"] = f"{_q(kw)} 월별 검색 추이가 이번 분석에서 수집되지 않았습니다."
    c["timing.killer"] = ("마케팅은 수요가 몰릴 때에만 하는 것이 아닙니다. 평소에는 리뷰·SEO·콘텐츠 자산을 쌓아 매출 하락을 방어하고, "
                          "수요가 오르는 때에는 그 자산으로 최저 비용에 1페이지를 선점합니다. 수요가 몰릴 때 뒤늦게 광고를 켜면 모든 경쟁사가 "
                          "입찰에 뛰어들어 클릭 단가가 최고조가 됩니다 — 끊김 없는 연중 운영이 평소의 손실을 줄이고 수요 상승기의 이익을 키웁니다.")

    # 페르소나
    dev = f.get("device") or {}
    pk_day = dl.get("peakDay")
    pt = ""
    if dev:
        pt += f"검색은 모바일 {dev['mobile']}%·PC {dev['pc']}%로 일어나므로, "
        pt += ("모바일 화면에서 상품명과 썸네일이 잘 보이도록 최적화해야 합니다. " if dev["mobile"] >= 60
               else "두 기기 모두에서 상품명과 썸네일이 잘 보이도록 최적화해야 합니다. ")
    if pk_day:
        pt += f"요일로는 {pk_day}요일에 검색이 가장 많습니다. 광고 예산과 체험단 후기 게시, 재구매 메시지 발송을 그 요일 전후에 집중하면 같은 비용으로 더 높은 효율을 낼 수 있습니다."
    c["persona.killer"] = pt or "핵심 타깃이 검색하는 기기·요일 정보가 이번 분석에서 수집되지 않아, 운영 데이터로 확인한 뒤 예산을 집중합니다."

    # 공략 키워드
    if t1:
        c["targets.killer"] = (f"이 전략은 검색 수요는 있으면서 경쟁이 덜한 키워드부터 1페이지를 점령하는 방식입니다. {store}에는 {j(tnames, '가')} 1순위입니다. "
                               "검색량이 크면서도 경쟁강도가 높지 않아, 이 키워드로 먼저 노출·리뷰를 쌓은 뒤 다음 장의 연관 키워드로 넓혀 갑니다.")
    else:
        c["targets.killer"] = "경쟁이 낮거나 중간인 구매형 키워드가 이번 분석에서 확인되지 않았습니다. 세부 속성(용량·용도·대상) 키워드 조합으로 진입로를 만듭니다."
    c["expand.killer"] = (f"키워드는 한 번에 다 잡는 것이 아니라 순서가 핵심입니다. 공략 → 연관 → 대형의 단계적 확장이 같은 예산으로 가장 높은 전환과 노출을 만들어냅니다. "
                          f"분석 키워드 {j(_q(kw), '는')} 상품명에 유지하고, 연관 키워드는 2단계에서 공략합니다.")
    c["oppcost.lead"] = (f"{j(store, '은')} 리뷰와 상세페이지라는 '전환 자산'을 이미 갖추고 있어, 노출만 열리면 매출로 이어질 준비가 된 상태입니다."
                         if fl.get("trustOk") and fl.get("exposureGap") else
                         f"{store}의 성장 여지는 노출·전환·재구매 세 축을 함께 운영할 때 가장 크게 열립니다.")
    return c


# ───────────────────────── ② AI 문장 · 검사 ─────────────────────────

def _allowed_numbers(f):
    """문장에 나와도 되는 숫자 — 사실값에서 나온 것과 늘 쓰는 고정 숫자."""
    nums = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, bool):
            return
        elif isinstance(x, (int, float)):
            nums.add(_norm_num(x))
        elif isinstance(x, str):
            for m in re.findall(r"\d[\d,]*(?:\.\d+)?", x):
                nums.add(_norm_num(m))
    walk({k: v for k, v in f.items() if k != "ai"})
    # 늘 쓰는 고정 숫자(단계·기간·임계점) — 사실값이 아니라 제안서 원고의 숫자다.
    for k in (1, 2, 3, 4, 5, 12, 30, 90, 100, 40, 200, 300):
        nums.add(str(k))
    return nums


def _norm_num(x):
    s = str(x).replace(",", "")
    try:
        v = float(s)
        return str(int(v)) if v == int(v) else str(round(v, 1))
    except Exception:
        return s


def validate(ai, f):
    """AI 결과에서 쓸 수 있는 칸만 고른다. (통과한 칸 dict, 버린 칸과 이유 list)."""
    ok, bad = {}, []
    if not isinstance(ai, dict):
        return ok, [("*", "형식")]
    allowed = _allowed_numbers(f)
    store = _get(f, "store.name", "") or ""
    for key, val in ai.items():
        if key not in FIELDS:
            bad.append((key, "모르는 칸"))
            continue
        if not isinstance(val, str) or not val.strip():
            bad.append((key, "빈 값"))
            continue
        v = re.sub(r"\s+", " ", val).strip()
        if len(v) > FIELDS[key] * 1.15:
            bad.append((key, "너무 김"))
            continue
        if any(w in v for w in _BANNED):
            bad.append((key, "금지어"))
            continue
        if re.search(r"\d[\d,]*\s*(만\s*원|억|천\s*원)", v):
            bad.append((key, "금액"))
            continue
        strange = [m for m in re.findall(r"\d[\d,]*(?:\.\d+)?", v) if _norm_num(m) not in allowed]
        if strange:
            bad.append((key, "낯선 숫자 " + ",".join(strange[:3])))
            continue
        if "<" in v or ">" in v:
            bad.append((key, "태그"))
            continue
        ok[key] = v
    return ok, bad


def prompt(f, base):
    facts = {k: v for k, v in f.items() if k not in ("ai",)}
    return (
        "너는 온라인 쇼핑몰 마케팅 대행사의 제안서 작성자다. 아래 [사실값]만 근거로, [초안]의 각 칸을 "
        "고객(판매자)에게 보내는 제안서 문장으로 더 자연스럽고 설득력 있게 다시 써라.\n"
        "규칙:\n"
        "1) 존댓말(~습니다/~입니다). 과장·단정 금지. '보장','반드시','확실히','100%' 금지.\n"
        "2) 숫자는 [사실값]에 있는 숫자만 쓴다. 새 숫자·추정 수치를 만들지 마라. 금액(만원·억)은 쓰지 마라.\n"
        "3) 사실값에 없는 내용(경쟁사 이름, 판매량, 매출)은 쓰지 마라. 모르는 것은 쓰지 말고 넘어가라.\n"
        "4) 칸 이름은 [초안]과 똑같이, 각 칸 길이는 초안과 비슷하게. HTML 태그 금지.\n"
        "5) voc.hook*.t 는 실제 리뷰 표현을 살린 짧은 광고 문구(두 줄 이내)로 쓴다.\n"
        "6) JSON 객체 하나만 출력한다. 설명·코드블록 금지.\n\n"
        "[사실값]\n" + json.dumps(facts, ensure_ascii=False) + "\n\n"
        "[초안]\n" + json.dumps(base, ensure_ascii=False)
    )


def _parse_json(text):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        return json.loads(t[i:j + 1])
    except Exception:
        return None


def generate(f, api_key=None, client=None, model=MODEL, timeout=90):
    """규칙 문장 + (가능하면) AI 문장. AI 가 실패해도 규칙 문장은 그대로 돌려준다.

    돌려주는 것: {"copy": {...}, "source": {"ai": [칸...], "template": [칸...]}, "aiProblems": [...]}
    """
    base = template(f)
    result = {"copy": dict(base), "source": {"ai": [], "template": sorted(base)}, "aiProblems": []}
    if client is None and not api_key:
        result["aiProblems"].append("AI 키 없음 — 규칙 문장만 사용")
        return result
    try:
        if client is None:
            import anthropic   # 게이트에는 없다 — 여기서만 부른다
            client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        msg = client.messages.create(
            model=model, max_tokens=6000,
            messages=[{"role": "user", "content": prompt(f, base)}],
        )
        text = "".join(getattr(b, "text", "") for b in getattr(msg, "content", []) or [])
        ai = _parse_json(text)
        if ai is None:
            result["aiProblems"].append("AI 응답을 JSON 으로 읽지 못함")
            return result
        good, bad = validate(ai, f)
        result["copy"].update(good)
        result["source"]["ai"] = sorted(good)
        result["source"]["template"] = sorted(k for k in base if k not in good)
        result["aiProblems"] = [f"{k}: {why}" for k, why in bad][:30]
    except Exception as e:   # AI 가 죽어도 제안서는 나온다
        result["aiProblems"].append(f"AI 호출 실패: {type(e).__name__}")
    return result
