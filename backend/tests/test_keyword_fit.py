"""회귀 — 키워드 적합도 판정 (2026-11-16 · 초콜릿 판매자 제안서 사고)

지키는 것:
  ① 판정기 — 부록 B(로컬 제안서 생성기 시험)를 그대로: 수식어·단위 제거 · 노이즈 · 핵심 명사 포함 ·
     시즌 창 · 다른 형태 상품 · 타사 브랜드 · 정보 탐색어.
  ② 사유 코드 — 탈락마다 정해진 8개 코드 중 하나.
  ③ 제안서 재료(proposal_facts.build) — 초콜릿 판매자 사례에서 빼빼로 계열이 targets·groups·상품명 처방·golden 어디에도 없다.
     생초콜릿·수제초콜릿이 통과한다. 탈락 목록과 사유가 묶음에 남는다.
  ④ 닭발 — 정보 탐색어 '닭발레시피'는 공략 아님(groups 정보/방식으로), 타사 '예시네정과' 의 '예시네무뼈닭발' 탈락.
  ⑤ 문장(proposal_copy) — 규칙 문장에 탈락 키워드가 없다 · 인기어를 「상품명에 넣을 말」로 처방하지 않는다 ·
     AI 문장이 탈락 키워드·지난 시즌을 말하면 그 칸을 버린다 · 프롬프트에 생성일과 규칙이 들어간다.

⚠️ 수능 — 2026년(2027학년도) 수능은 11/19 다. 지시서는 11/13 을 「당일」로 봤지만 실제 달력 기준으로
   11/13 은 6일 전이라 시즌 창(2~75일, 대표 확정 「지시서 그대로 2일」) 안이다 ⇒ 수능초콜릿은 **통과**가 맞다.
"""
import json
import os
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

import keyword_fit as kf          # noqa: E402
import proposal_copy as pc        # noqa: E402
import proposal_facts as pf       # noqa: E402

passed = failed = 0


def ok(cond, msg):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("  ✗", msg)


TODAY = date(2026, 11, 13)


def keywords_of(gate, rows):
    """부록 B 의 build_keywords 대신 — 통과(정보 탐색어 제외) 검색량순 6개."""
    p, _ = gate.split(rows)
    p = [r for r in p if not r.get("infoIntent")]
    p.sort(key=lambda r: -(r.get("total") or 0))
    return [r["keyword"] for r in p][:6]


# ───────────── ① 부록 B — 판정기 ─────────────

# 수식어·단위
anc = kf.anchors({"name": "제주 구좌당근 햇당근 흙 주스용 산지직송 5kg 10kg", "tags": ["당근즙"], "categoryLeaf": "당근"}, "당근")
ok(not kf.is_relevant("쌀20KG", anc), "'0kg' 글자 겹침으로 통과하던 사고")
ok(not kf.is_relevant("당근마켓", anc), "노이즈")
ok(kf.is_relevant("당근주스", anc), "당근주스 관련")
ok(kf.is_relevant("구좌당근", anc), "구좌당근 관련")
ok(not kf.is_relevant("수제선물세트", anc), "수식어만 남으면 무관")

# 시즌 창
ok(not kf.season_ok("빼빼로데이 선물", date(2026, 11, 13)), "빼빼로데이 11/13 지남")
ok(kf.season_ok("빼빼로데이 선물", date(2026, 10, 20)), "빼빼로데이 10/20 22일 전")
ok(kf.season_ok("크리스마스 초콜릿", date(2026, 11, 13)), "크리스마스 42일 전")
ok(not kf.season_ok("발렌타인 초콜릿", date(2026, 11, 13)), "발렌타인 93일 전 — 너무 멂")
ok(kf.season_ok("발렌타인 초콜릿", date(2026, 1, 20)), "발렌타인 1/20 통과")
ok(kf.season_ok("수제초콜릿", date(2026, 11, 13)), "시즌어 아님")
ok(kf.season_ok("수능초콜릿", date(2026, 11, 13)), "수능 11/19 — 6일 전 통과(실제 달력)")
ok(not kf.season_ok("수능초콜릿", date(2026, 11, 18)), "수능 전날 — 늦음")
ok(not kf.season_ok("수능초콜릿", date(2026, 11, 19)), "수능 당일 — 늦음")
ok(not kf.season_ok("수능초콜릿", date(2026, 11, 20)), "수능 지남")
ok(kf.season_ok("수능선물", date(2025, 11, 1)) and not kf.season_ok("수능선물", date(2025, 11, 13)), "2025 수능 11/13")
ok(kf.days_until("설선물", date(2026, 11, 16)) == 83 and not kf.season_ok("설선물", date(2026, 11, 16)), "2027 설 2/7 — 11/16 기준 83일")
ok(kf.season_ok("설선물", date(2026, 11, 24)), "2027 설 — 11/24 부터 75일 안")
ok(kf.season_ok("추석선물세트", date(2026, 9, 1)) and not kf.season_ok("추석선물세트", date(2026, 9, 26)), "2026 추석 9/25")

# 핵심 명사(검색광고 연관어 닮은꼴)
bagel = {"name": "1달러 베이글 수제 화덕 당일생산", "categoryLeaf": "식빵/베이글",
         "tags": ["아침대용", "코스트코베이글", "수제베이글", "저당베이글", "베이글토스트", "아침식사메뉴"]}
ok(kf.core_anchors(bagel, "베이글") == ["베이글"], "베이글 핵심 명사")
rows = [{"keyword": k, "total": v} for k, v in [("코스트코", 983400), ("침대", 110100), ("프렌치토스트", 34230), ("저당밥솥", 20770),
                                               ("아침메뉴추천", 16600), ("수제베이글", 3000), ("플레인베이글", 2500), ("베이글 맛집", 9000)]]
names = keywords_of(kf.Gate(bagel, "베이글", TODAY), rows)
ok(names == ["수제베이글", "플레인베이글"], f"베이글 공략 = 수제·플레인 (맛집은 정보탐색어): {names}")

carrot = {"name": "제주 구좌당근 햇당근 흙 주스용 산지직송 5kg 10kg", "categoryLeaf": "당근", "tags": ["제주당근", "당근주스"]}
cores, anc = kf.core_anchors(carrot, "당근"), kf.anchors(carrot, "당근")
ok(not kf.is_relevant("제주공항", anc, cores) and not kf.is_relevant("제주호텔", anc, cores), "제주공항·호텔 탈락")
ok(kf.is_relevant("당근주스", anc, cores) and kf.is_relevant("흙당근", anc, cores), "당근주스·흙당근 통과")

fish = {"name": "동해안 당일조업 제철 알도루묵 알배기도루묵", "categoryLeaf": "기타생선", "tags": ["도루묵구이", "도루묵찌개"]}
cores, anc = kf.core_anchors(fish, "도루묵"), kf.anchors(fish, "도루묵")
ok(not kf.is_relevant("조개구이", anc, cores) and not kf.is_relevant("메로구이", anc, cores), "조개구이·메로구이 탈락")
ok(kf.is_relevant("알도루묵", anc, cores) and kf.is_relevant("도루묵 제철", anc, cores), "알도루묵·도루묵 제철 통과")

choc = {"name": "프리미엄 생초콜릿 수제초콜릿 파베초콜릿", "categoryLeaf": "초콜릿", "tags": ["다크초콜릿", "발렌타인데이"]}
ok("초콜릿" in kf.core_anchors(choc, "파베초콜릿"), "초콜릿 핵심 명사")

chicken = {"name": "직화 무뼈 닭발 매운 뼈없는 숯불 닭발 국내산 200g", "categoryLeaf": "닭양념육", "tags": ["닭발", "숯불닭발"]}
cores, anc = kf.core_anchors(chicken, "무뼈닭발"), kf.anchors(chicken, "무뼈닭발")
ok("닭발" in cores, "닭발 핵심 명사")
ok(not kf.is_relevant("숯불", anc, cores) and kf.is_relevant("튤립닭발", anc, cores), "숯불 탈락·튤립닭발 통과")

# 다른 형태 상품
prod = {"name": "대추방울토마토 산지직송 GAP 로얄과 2kg", "category": "식품>농산물>채소>토마토", "tags": ["방울토마토"]}
ok(kf.is_other_form("토마토마리네이드", prod) and kf.is_other_form("토마토주스", prod) and kf.is_other_form("토마토요리", prod),
   "토마토 마리네이드·주스·요리 = 다른 형태")
ok(not kf.is_other_form("방울토마토", prod) and not kf.is_other_form("스테비아방울토마토", prod), "방울토마토 = 같은 형태")
ok(not kf.is_other_form("토마토주스", {"name": "착즙 토마토주스 1L", "category": "식품>음료"}), "주스 파는 집엔 주스가 맞음")
ok(not kf.is_other_form("녹차", {"name": "제주 녹차 잎차"}), "녹차 — 짧은 말은 안 자름")

# 다른 형태 — 같은 상품을 부르는 말은 떨어뜨리지 않는다(2026-11-21 · 교차검증 지적: 베이글 상품의 '베이글빵' 오탐)
bagel2 = {"name": "플레인 베이글", "category": "식품>과자/베이커리>베이글", "categoryLeaf": "베이글", "tags": []}
gb2 = kf.Gate(bagel2, "베이글", TODAY)
ok(gb2.reason("베이글빵") is None and gb2.reason("수제베이글빵") is None, "베이글빵 — 베이글은 빵의 한 종류라 같은 상품(종류 이름 사전)")
ok(kf.Gate(bagel, "베이글", TODAY).reason("베이글빵") is None, "끝 분류가 '식빵/베이글' 인 베이글 상품의 베이글빵")
ok(kf.Gate({"name": "착즙 100% 제주 감귤 1L", "categoryLeaf": "과일주스"}, "감귤", TODAY).reason("감귤주스") is None,
   "카테고리 끝 분류에 그 형태가 있으면 같은 형태(상품명·태그에 '주스'가 없어도)")
ok(kf.Gate({"name": "제주 감귤 5kg", "categoryLeaf": "감귤"}, "감귤", TODAY).reason("감귤주스") == "other_form", "과일 파는 집의 감귤주스는 다른 형태")
ok(kf.Gate({"name": "유기농 캐모마일 티백 50개입"}, "캐모마일", TODAY).reason("캐모마일차") is None, "캐모마일차 — 티백 상품의 '차'는 같은 상품")
ok(not kf.is_other_form("토마토쥬스", {"name": "착즙 토마토주스 1L", "category": "식품>음료"}), "같은 형태의 다른 표기(주스·쥬스)")
ok(not kf.is_other_form("토마토케찹", {"name": "유기농 토마토케첩"}), "같은 형태의 다른 표기(케첩·케찹)")
# 재료에서 만든 다른 상품은 그대로 탈락한다(보강이 문을 넓히지 않는다)
sweet = {"name": "해남 꿀고구마 3kg", "category": "식품>농산물>채소>고구마", "categoryLeaf": "고구마"}
gs = kf.Gate(sweet, "고구마", TODAY)
ok(gs.reason("고구마빵") == "other_form" and gs.reason("고구마칩") == "other_form" and gs.reason("고구마라떼") == "other_form",
   "고구마 → 고구마빵·칩·라떼 = 다른 형태")
ok(kf.Gate({"name": "플레인 베이글"}, "베이글", TODAY).reason("베이글빵") is None, "카테고리가 비어도 메인 키워드가 빵의 종류면 같은 상품")
# ⛔ 카테고리 윗단계('과자/베이커리')는 근거가 아니다 — 초콜릿도 그 밑에 있다(2026-11-22 교차검증 재현: '파베초콜릿빵' 이 새로 통과했다)
gcb = kf.Gate({"name": "생초콜릿 파베초콜릿", "category": "식품>과자/베이커리>초콜릿", "categoryLeaf": "초콜릿", "tags": []}, "파베초콜릿", TODAY)
ok(gcb.reason("파베초콜릿빵") == "other_form", "베이커리 카테고리의 초콜릿 상품 — '파베초콜릿빵' 은 다른 형태")
ok(gcb.reason("초콜릿빵") == "other_form", "메인 키워드를 통째로 품지 않은 '초콜릿빵' 도 다른 형태")
ok(kf.Gate({"name": "수제 초콜릿", "category": "식품>과자/베이커리>초콜릿", "categoryLeaf": "초콜릿"}, "초콜릿", TODAY)
   .reason("초콜릿빵") == "other_form", "메인 키워드가 '초콜릿'이어도 '초콜릿빵' 은 다른 형태(초콜릿은 빵의 종류가 아니다)")
ok(kf.Gate({"name": "통밀 베이글", "categoryLeaf": "베이글"}, "통밀베이글", TODAY).reason("베이글빵") == "other_form",
   "메인 키워드를 통째로 품지 않으면 종류가 맞아도 다른 형태로 둔다(알려진 한계)")
ok(kf.Gate({"name": "수제 휘낭시에"}, "휘낭시에", TODAY).reason("휘낭시에빵") == "other_form", "사전에 없는 종류는 종전처럼 탈락(알려진 한계)")
ok(kf.is_other_form("베이글빵", bagel2) and not kf.is_other_form("베이글빵", bagel2, "베이글"), "종류 이름 꼬리 판정은 메인 키워드를 알 때만")
ok(kf.is_other_form("베이글주스", bagel2, "베이글") and kf.is_other_form("베이글떡", bagel2, "베이글"), "빵의 종류는 '빵' 꼬리에만 통한다")
ok(kf.Gate({"name": "콩고물 인절미 1kg"}, "인절미", TODAY).reason("인절미떡") is None, "인절미떡 — 인절미는 떡의 한 종류")

# 타사 브랜드
toks = kf.competitor_brand_tokens(["예시네정과", "우리닭발", "수제", "밀크"], chicken, "무뼈닭발")
ok("예시네" in toks, "예시네정과 → 예시네")
ok("수제" not in toks, "범용 수식어는 브랜드로 안 봄")
ok(kf.competitor_brand_tokens(["밀크"], choc, "파베초콜릿") == ["밀크"], "핵심 명사와 무관한 브랜드는 남김")
ok(kf.competitor_brand_tokens(["초콜릿"], {"name": "x"}, "파베초콜릿") == [], "핵심 명사 안에 든 말은 브랜드 아님")

# ───────────── ② 사유 코드 ─────────────
g = kf.Gate({"name": "프리미엄 생초콜릿 수제초콜릿 파베초콜릿", "category": "식품>젤리/사탕/초콜릿>초콜릿",
             "categoryLeaf": "초콜릿"}, "파베초콜릿", TODAY, competitor_names=["달콤하우스"])
ok(g.reason("수제선물세트") == "modifier_only", "사유 modifier_only")
ok(g.reason("빼빼로") == "no_core", "사유 no_core — 빼빼로")
ok(g.reason("빼빼로데이초콜릿") == "season_passed", "사유 season_passed")
ok(g.reason("달콤하우스초콜릿") == "competitor_brand", "사유 competitor_brand")
ok(g.reason("초콜릿케이크빵") == "other_form", "사유 other_form")
ok(g.reason("초콜릿당근마켓") == "noise", "사유 noise")
p, x = g.split([{"keyword": "초콜릿만들기", "total": 10}, {"keyword": "파베초콜릿", "total": 9}])
ok(p and p[0].get("infoIntent") and not x, "정보 탐색어 = 통과 + infoIntent 표시")
ok(not any(r["keyword"] == "파베초콜릿" for r in p + x), "메인 키워드 자신은 어느 쪽에도 없음")
ok(set(kf.REASONS) == {"modifier_only", "no_core", "low_overlap", "noise", "season_passed", "competitor_brand",
                       "other_form", "other_variety", "info_intent"}, "사유 코드 9개(판본 2: other_variety 가산)")

# 같은 종류의 다른 상품(판본 2) — 짧은 핵심 명사만 공유하고 붙은 말이 상품 쪽에 없으면 탈락
ok(g.reason("화이트초콜릿") == "other_variety", "화이트초콜릿 = 같은 종류의 다른 상품")
ok(g.reason("말차생초콜릿") == "other_variety", "말차생초콜릿 = 다른 맛")
ok(g.reason("생초콜릿") is None and g.reason("수제초콜릿") is None, "붙은 말이 상품명에 있으면 통과(생·수제)")
ok(g.reason("수능초콜릿") is None, "시즌어는 떼고 본다")
ok(g.reason("초콜릿선물") is None and g.reason("파베초콜릿선물") is None, "범용 수식어·메인 키워드 포함은 통과")
gt = kf.Gate({"name": "프리미엄 생초콜릿 수제초콜릿 파베초콜릿", "tags": ["화이트초콜릿"]}, "파베초콜릿", TODAY)
ok(gt.reason("화이트초콜릿") is None, "판매자 태그에 있으면 통과 — 블랙리스트 아님")
gb = kf.Gate(bagel, "베이글", TODAY)
ok(gb.reason("플레인베이글") is None, "메인 키워드를 품은 말은 이 판정을 받지 않음(부록 B 플레인베이글)")
gd = kf.Gate(chicken, "무뼈닭발", TODAY)
ok(gd.reason("국물닭발") == "other_variety" and gd.reason("튤립닭발") == "other_variety", "닭발 — 국물·튤립 = 다른 상품")
ok(gd.reason("숯불닭발") is None and gd.reason("매운닭발") is None, "닭발 — 숯불(상품명)·매운(수식어) 통과")
ok(gd.reason("무뼈족발") in ("no_core", "low_overlap", "other_variety"), "무뼈족발 탈락")

# 상품명 처방 — 시즌어·정보 탐색어는 넣지 않는다
ok(not kf.name_worthy("수능초콜릿") and not kf.name_worthy("파베초콜릿만들기") and kf.name_worthy("수제초콜릿"),
   "name_worthy — 시즌어·정보 탐색어 제외")
ok(g.describe()["date"] == "2026-11-13" and g.describe()["version"] == kf.GATE_VERSION, "판정 정보")

# ───────────── ③ 초콜릿 판매자 사례 — 제안서 재료 ─────────────

def rk(k, total, pc=None, mo=None, comp="중간"):
    return {"keyword": k, "monthlyPcQcCnt": pc, "monthlyMobileQcCnt": mo, "totalVolume": total, "compIdx": comp}


CHOCO = {
    "v3": True, "keyword": "파베초콜릿", "name": "예시초콜릿",
    "storeUrl": "https://smartstore.naver.com/example/products/123",
    "productName": "프리미엄 생초콜릿 수제초콜릿 파베초콜릿",
    "volume": [{"relKeyword": "파베초콜릿", "monthlyPcQcCnt": 1310, "monthlyMobileQcCnt": 8200, "compIdx": "중간"}],
    "related": {
        "related_keywords": [rk("빼빼로", 387900, 58300, 329600), rk("수제빼빼로", 41160, 5360, 35800),
                             rk("빼빼로만들기", 88300), rk("수능초콜릿", 20670, 4670, 16000), rk("동결건조딸기", 9910, 1660, 8250),
                             rk("화이트초콜릿", 9060), rk("빼빼로데이", 235700), rk("빼빼로선물", 23340),
                             rk("발렌타인데이", 31310), rk("화이트데이", 26240), rk("파베초콜릿만들기", 3000)],
        "golden_keywords": [rk("수제초콜릿", 8860, 3100, 5760, "낮음") | {"isGolden": True},
                            rk("생초콜릿", 7200, None, None, "") | {"isGolden": True}],
        "total_found": 400,
    },
    "advertiser": {"product_info": {"product_name": "프리미엄 생초콜릿 수제초콜릿 파베초콜릿", "price": 18500},
                   "competitor_comparison": {"items": [{"store_name": "로이스몰", "brand": "로이스", "price": 30000}]}},
    "htmlDetail": {"reviewData": {"category": "식품>젤리/사탕/초콜릿>초콜릿", "reviewCount": 63, "rating": 4.9},
                   "sellerTags": ["다크초콜릿", "밀크초콜릿", "수제초콜릿선물", "초콜릿선물", "초콜릿포장", "발렌타인데이",
                                  "결혼기념일선물", "여자친구선물"]},
    "datalab": {"categoryKeywords": {
        "popular": [{"keyword": "빼빼로데이", "volume": 235700}, {"keyword": "초콜릿", "volume": 120000},
                    {"keyword": "빼빼로", "volume": 387900}, {"keyword": "빼빼로만들기", "volume": 88300},
                    {"keyword": "초콜릿선물", "volume": 30000}],
        "rising": [{"keyword": "빼빼로데이", "volume": 235700, "growth": 1661.1}]}},
}
NOW = datetime(2026, 11, 13, 10, 0, tzinfo=pf.KST)
f = pf.build(CHOCO, now=NOW)
kw = f["keywords"]
tg = [t["keyword"] for t in kw["targets"]]
for bad in ("빼빼로", "수제빼빼로", "빼빼로만들기", "동결건조딸기", "빼빼로데이", "빼빼로선물"):
    ok(bad not in tg, f"공략 키워드에 {bad} 없음")
ok("수제초콜릿" in tg and "생초콜릿" in tg, f"수제초콜릿·생초콜릿 통과: {tg}")
ok("수능초콜릿" in tg, "수능초콜릿 — 실제 수능(11/19) 6일 전이라 통과")
ok("파베초콜릿만들기" not in tg, "정보 탐색어는 공략 아님")
vols = {r["keyword"]: r["total"] for r in kw["targets"]}
ok(tg == sorted(tg, key=lambda k: -vols[k]), "검색량순")
ok(tg.index("수제초콜릿") < tg.index("생초콜릿"), "수제초콜릿(8,860) → 생초콜릿(7,200)")
ok("생초콜릿" not in kw["targetsMissingInName"], "상품명에 이미 있는 생초콜릿은 처방 안 함")
ok("수능초콜릿" not in kw["targetsMissingInName"], "시즌어는 상품명 처방 안 함(공략에는 남음)")
ok("화이트초콜릿" not in tg, "화이트초콜릿 공략 아님")
ok(not any("빼빼로" in m for m in kw["targetsMissingInName"]), "상품명 처방에 빼빼로 없음")
allg = [x["keyword"] for grp in kw["groups"].values() for x in grp]
ok(not any("빼빼로" in w for w in allg), f"groups 어디에도 빼빼로 없음: {allg}")
ok(not any("빼빼로" in w["keyword"] for w in kw["golden"]), "golden 에 빼빼로 없음")
ok(not any("빼빼로" in w["keyword"] for w in kw["rows"]), "rows(표)에 빼빼로 없음")
ok("파베초콜릿만들기" in [x["keyword"] for x in kw["groups"]["info"]], "정보 탐색어는 groups.info 로")
ex = {x["keyword"]: x["reason"] for x in kw["excluded"]}
ok(ex.get("빼빼로") == "no_core" and ex.get("수제빼빼로") == "no_core" and ex.get("동결건조딸기") == "no_core", f"탈락 사유: {ex}")
ok(ex.get("발렌타인데이") == "no_core", "발렌타인데이 — 핵심 명사 없음(판정은 관련도부터)")
ok(ex.get("파베초콜릿만들기") == "info_intent", "정보 탐색어는 사유 info_intent 로도 남김(공략 제외)")
ok(ex.get("화이트초콜릿") == "other_variety", "화이트초콜릿 사유 = 같은 종류의 다른 상품")
ok(kw["gate"]["date"] == "2026-11-13" and kw["gate"]["hasTags"] is True, "판정 정보 저장")
ok(f["product"].get("tags", [])[:2] == ["다크초콜릿", "밀크초콜릿"], "판매자 태그를 product 에 실음")
ok(f["version"] >= 2, "사실값 판본 올림")
pop = {p["keyword"]: p["fit"] for p in f["datalab"]["categoryPopular"]}
ok(pop.get("빼빼로데이") is False and pop.get("빼빼로") is False and pop.get("초콜릿선물") is True, f"인기어 적합 표시: {pop}")
ok(f["datalab"]["rising"][0]["fit"] is False, "급상승어 빼빼로데이 = 부적합")
json.dumps(f, ensure_ascii=False)

# 같은 상품, 날짜만 바꾸면 시즌어가 따라 움직인다
f2 = pf.build(CHOCO, now=datetime(2026, 10, 20, tzinfo=pf.KST))
ok("빼빼로데이" in {x["keyword"]: 1 for x in f2["keywords"]["excluded"]}, "빼빼로데이 — 10/20 에도 핵심 명사 없음으로 탈락")
f3 = pf.build(CHOCO, now=datetime(2026, 11, 19, tzinfo=pf.KST))
ok("수능초콜릿" not in [t["keyword"] for t in f3["keywords"]["targets"]], "수능 당일 생성 — 수능초콜릿 탈락")

# 경쟁 「높음」으로 확인된 것만 뺀다(미확인은 둔다) — 대표 확정 2026-11-16
b = json.loads(json.dumps(CHOCO))
b["related"]["related_keywords"].append(rk("다크초콜릿", 50000, comp="높음"))
f4 = pf.build(b, now=NOW)
ok("다크초콜릿" not in [t["keyword"] for t in f4["keywords"]["targets"]], "경쟁 높음 제외")
ok("생초콜릿" in [t["keyword"] for t in f4["keywords"]["targets"]], "경쟁 미확인(생초콜릿)은 남김")

# 적합 키워드가 하나도 없으면 비워 둔다(엉뚱한 말로 채우지 않는다)
b = json.loads(json.dumps(CHOCO))
b["related"] = {"related_keywords": [rk("빼빼로", 387900), rk("동결건조딸기", 9910)], "golden_keywords": []}
f5 = pf.build(b, now=NOW)
ok(f5["keywords"]["targets"] == [] and f5["keywords"]["targetsMissingInName"] == [], "적합 없으면 targets 비움")
ok(all(not v for v in f5["keywords"]["groups"].values()), "groups 도 비움")

# pool(검색량 상위 300) — 상위 50 밖의 관련 키워드도 판정 대상
b = json.loads(json.dumps(CHOCO))
b["related"]["pool"] = [rk("말차생초콜릿", 1500), rk("밀크초콜릿", 1400)]
f6 = pf.build(b, now=NOW)
ok("밀크초콜릿" in [t["keyword"] for t in f6["keywords"]["targets"]] or
   "밀크초콜릿" in [x["keyword"] for g_ in f6["keywords"]["groups"].values() for x in g_], "pool 의 관련 키워드도 쓴다(판매자 태그 밀크초콜릿)")
ok({x["keyword"]: x["reason"] for x in f6["keywords"]["excluded"]}.get("말차생초콜릿") == "other_variety", "pool 의 다른 맛은 탈락")

# ───────────── ④ 닭발 — 정보 탐색어 · 타사 브랜드 ─────────────
DAKBAL = {
    "v3": True, "keyword": "무뼈닭발", "name": "테스트닭발",
    "productName": "직화 무뼈 닭발 매운 뼈없는 숯불 닭발 국내산 200g",
    "related": {"related_keywords": [rk("닭발레시피", 30000), rk("예시네무뼈닭발", 12000), rk("숯불닭발", 9000),
                                     rk("국물닭발", 7000), rk("무뼈닭발맛집", 5000), rk("숯불", 80000), rk("튤립닭발", 3000)],
                "golden_keywords": []},
    "advertiser": {"product_info": {"product_name": "직화 무뼈 닭발 매운 뼈없는 숯불 닭발 국내산 200g", "category1": "식품",
                                    "category2": "축산", "category3": "닭고기", "category4": "닭양념육"},
                   "competitor_comparison": {"items": [{"store_name": "예시네정과", "brand": ""},
                                                        {"store_name": "닭발명가", "brand": "닭발명가"}]}},
    "htmlDetail": {"sellerTags": ["닭발", "숯불닭발"]},
}
fd = pf.build(DAKBAL, now=NOW)
names = [t["keyword"] for t in fd["keywords"]["targets"]]
ok("닭발레시피" not in names and "예시네무뼈닭발" not in names, f"닭발 공략: {names}")
ok(any("닭발" in n for n in names), "닭발 계열 공략 키워드 있음")
non_buy = [x["keyword"] for grp in ("method", "info") for x in fd["keywords"]["groups"][grp]]
ok("닭발레시피" in non_buy, f"닭발레시피는 방식/정보 그룹으로: {non_buy}")
ok({x["keyword"]: x["reason"] for x in fd["keywords"]["excluded"]}.get("예시네무뼈닭발") == "competitor_brand", "예시네 = 타사 브랜드")
ok("숯불" not in names, "숯불 단독 탈락")

# ───────────── ⑤ 문장 ─────────────
c = pc.template(f)
txt = json.dumps(c, ensure_ascii=False)
ok("빼빼로" not in txt, "규칙 문장에 빼빼로 없음")
ok("상품명 앞부분과 광고 키워드에 넣으면" not in c["market.killer"], "인기어를 상품명 처방으로 쓰지 않음")
ok("'초콜릿선물'" in c["market.killer"] or "'초콜릿'" in c["market.killer"], f"적합한 인기어만 언급: {c['market.killer'][:80]}")
good, bad = pc.validate(c, f)
ok(not bad, f"규칙 문장은 스스로 검사 통과: {bad[:3]}")
ai = {"summary.problem": "고객이 많이 찾는 '빼빼로'가 상품명에 없어 수요를 놓치고 있습니다.",
      "timing.killer": "다가오는 어버이날 시즌을 앞두고 미리 준비해야 합니다.",
      "diag.opportunity": "같은 상품으로 '수제초콜릿'·'생초콜릿'을 공략할 수 있습니다.",
      "voc.hook1.t": "\"어버이날 선물로 샀어요\"",
      "voc.hook2.t": "\"빼빼로보다 맛있어요\""}
good, bad = pc.validate(ai, f)
why = dict(bad)
ok("summary.problem" not in good and "탈락 키워드" in why.get("summary.problem", ""), f"탈락 키워드 언급 칸 버림: {why}")
ok("timing.killer" not in good and "시즌" in why.get("timing.killer", ""), "지난·먼 시즌을 다가온다고 쓰면 버림")
ok("diag.opportunity" in good, "공략 키워드만 언급한 칸은 통과")
ok("voc.hook1.t" in good, "리뷰 인용 칸(voc)은 시즌 검사에서 뺀다")
ok("voc.hook2.t" not in good, "리뷰 인용 칸이라도 탈락 키워드는 버림")
ok("387" not in "".join(sorted(pc._allowed_numbers(f))) or "387900" not in pc._allowed_numbers(f), "탈락 키워드 검색량은 허용 숫자 아님")
pr = pc.prompt(f, c)
ok("2026-11-13" in pr and "facts.keywords.targets" in pr, "프롬프트에 생성일·공략 키워드 규칙")
ok("빼빼로" not in pr, "프롬프트 사실값에도 탈락 키워드 없음")

# 탈락어가 표시 한도(60개)보다 많아도 문장 검사는 전부 본다(2026-11-21 · 교차검증 지적: 61번째 이후 탈락어가 AI 문장 검사를 빠져나감)
b = json.loads(json.dumps(CHOCO))
b["related"]["pool"] = [rk(f"빼빼로맛{i:03d}", 300000 - i) for i in range(70)]
f7 = pf.build(b, now=NOW)
k7 = f7["keywords"]
ok(len(k7["excluded"]) == pf.EXCLUDED_SHOWN and k7["excludedTotal"] >= 78, f"표시 목록은 한도까지 · 전체 개수는 따로: {len(k7['excluded'])}/{k7.get('excludedTotal')}")
ok("화이트초콜릿" not in [x["keyword"] for x in k7["excluded"]], "화이트초콜릿은 표시 목록(검색량 상위 60) 밖")
ok("화이트초콜릿" in k7["banned"] and "빼빼로맛069" in k7["banned"], "문장 검사용 목록에는 탈락어가 전부 있다")
ok("파베초콜릿만들기" not in k7["banned"], "정보 탐색어는 금지어가 아니다(정보 그룹에 쓴다)")
ai7 = {"summary.problem": "상품명 앞쪽에 '화이트초콜릿'을 넣어 수요를 받으세요.",
       "diag.opportunity": "같은 상품으로 '수제초콜릿'·'생초콜릿'을 공략할 수 있습니다."}
good, bad = pc.validate(ai7, f7)
ok("summary.problem" not in good and "탈락 키워드" in dict(bad).get("summary.problem", ""), f"표시 한도 밖 탈락어를 권하는 문장도 버림: {bad}")
ok("diag.opportunity" in good, "공략 키워드만 언급한 칸은 그대로 통과")
sf7 = pc.safe_facts(f7)["keywords"]
ok("banned" not in sf7 and "excluded" not in sf7 and "excludedTotal" not in sf7, "AI 에 보여 주는 사실값에는 탈락 목록이 없다")
ok("화이트초콜릿" not in pc.prompt(f7, pc.template(f7)) and "빼빼로맛" not in pc.prompt(f7, pc.template(f7)), "프롬프트에도 탈락어 없음")
ok(not pc.validate(pc.template(f7), f7)[1], "규칙 문장은 스스로 검사 통과(탈락어가 많아도)")
old7 = json.loads(json.dumps(f)); old7["keywords"].pop("banned", None)
ok("summary.problem" not in pc.validate(ai, old7)[0], "banned 칸이 없는 묶음은 종전처럼 excluded 로 검사")
src_pf = open(os.path.join(HERE, "..", "proposal_facts.py"), encoding="utf-8").read()
ok('"banned": banned_keys(excluded)' in src_pf, "묶음에 문장 검사용 전체 목록을 싣는다")

# 공략 키워드가 없을 때 문장이 어색하지 않다
c5 = pc.template(f5)
ok("빼빼로" not in json.dumps(c5, ensure_ascii=False), "적합 없음 — 문장에 빼빼로 없음")
ok(c5["targets.killer"] and "''" not in json.dumps(c5, ensure_ascii=False), "빈 따옴표 없음")

# main.py — 연관어 pool · /api/keywords/fit 배선(소스 검사, fastapi 없음)
src_main = open(os.path.join(HERE, "..", "main.py"), encoding="utf-8").read()
i = src_main.find('@app.post("/api/keywords/related")')
ok('"pool"' in src_main[i:i + 7000], "연관어 응답에 pool 가산")
ok('@app.post("/api/keywords/fit")' in src_main and "keyword_fit" in src_main, "/api/keywords/fit 경로")
ok('"excludedTotal": len(excluded)' in src_main, "판정 API 가 탈락 전체 개수를 준다")
src_cr = open(os.path.join(HERE, "..", "naver_crawler.py"), encoding="utf-8").read()
ok('"sellerTags"' in src_cr and "def extract_seller_tags" in src_cr, "상세 진단에 판매자 태그 추출")
ok(kf.GATE_VERSION >= 3, "판정 판본")

print(f"keyword_fit: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
