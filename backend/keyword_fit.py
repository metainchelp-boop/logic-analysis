"""키워드 적합도 판정 — 이 키워드가 **이 상품을 찾는 말**인가 (2026-11-16).

⚠️ **왜 만들었나 (2026-11-13 초콜릿 판매자 제안서 사고)**
   파베초콜릿 판매자 제안서에 공략 키워드로 '빼빼로'(월 387,900)·'수제빼빼로'가 올라가
   요약 숫자 · 상품명 처방(「앞 30자에 '빼빼로'를 넣기」) · 키워드 확장 장표가 전부 빼빼로로 채워졌다.
   상품명 첫 키워드 '생초콜릿'은 한 번도 나오지 않았다.
   원인 = 연관어를 **검색량·경쟁강도로만** 골랐고, 그 말이 이 상품을 찾는 말인지 보는 단계가 없었다.

⚠️ **특정 단어 블랙리스트로 막지 않는다.** '빼빼로'가 빠지는 것은 아래 일반 규칙의 결과다
   (빼빼로에는 핵심 명사 '초콜릿'이 없다 → no_core). 한우·홍삼·베이글·도루묵에서도 같은 코드가 돈다.

판정 순서(후보 하나마다, 먼저 걸린 사유 하나를 돌려준다)
  1 modifier_only     수식어·단위를 떼면 2자 미만      ('수제선물세트')
  2 noise             흔한 무관 노이즈                 ('당근마켓')
  3 no_core           핵심 명사를 포함하지 않음        ('빼빼로' ← 파베초콜릿)
  4 low_overlap       상품명·태그·카테고리와 글자 겹침 부족
  5 season_passed     시즌어인데 생성일 기준 2~75일 창 밖('빼빼로데이' ← 11/13)
  6 competitor_brand  타사 스토어·브랜드명 포함        ('예시네무뼈닭발')
  7 other_form        다른 형태 상품                   ('토마토주스' ← 방울토마토)
  ─ 통과한 것 중 —
  8 info_intent       정보 탐색어 — 공략 키워드(상품명·광고)에서만 빼고 groups.info 로 보낸다

⚠️ 의존성 없음(표준 라이브러리만) — 배포 회귀 게이트가 fastapi 없이 import 한다.
⚠️ 참조 구현: 로컬 제안서 생성기 `proposal_local/facts.py`(덤프 107건 표본 검증). 규칙·사전은 그대로 옮겼고
   달라진 것은 ① 사유 코드를 돌려준다 ② 설·추석·수능은 연도별 실제 날짜표를 쓴다 둘뿐이다.
"""

import re
import unicodedata
from datetime import date, datetime

#: 판정 규칙이 바뀌면 올린다(묶음에 함께 저장 — 어느 규칙으로 걸렀는지 나중에 안다).
GATE_VERSION = 3   # 2: 같은 종류의 다른 상품(other_variety) · 시즌어는 상품명 처방에서 뺌(2026-11-16)
                   # 3: 다른 형태 판정 — 같은 형태의 다른 표기(주스·쥬스) · 끝 분류가 그 종류일 때의 종류 이름 꼬리('베이글빵')(2026-11-22)

REASONS = {
    "modifier_only": "수식어만 남음",
    "noise": "무관한 흔한 말",
    "no_core": "상품 핵심 명사 없음",
    "low_overlap": "상품명·태그·카테고리와 겹침 부족",
    "season_passed": "시즌이 지났거나 너무 멂",
    "competitor_brand": "타사 스토어·브랜드명",
    "other_form": "다른 형태의 상품",
    "other_variety": "같은 종류의 다른 상품",
    "info_intent": "정보 탐색어(체험단·블로그용)",
}

# ── 키워드 분류 사전 ────────────────────────────────────────────────────────
# 관련도 판정 전에 후보에서 떼어내는 수식어(이것만 겹치는 것은 관련 있다고 보지 않는다 — '수제빼빼로' 사고 방지)
GENERIC_MODIFIERS = ["수제", "국내산", "국산", "추천", "선물세트", "선물", "세트", "맛있는", "매운", "프리미엄", "대용량", "당일",
                     "산지직송", "무료배송", "냉동", "냉장", "신선", "제철", "특가", "할인", "즉석", "간편", "홈", "가정용", "업소용",
                     "만들기", "레시피", "효능", "보관법", "손질", "주문", "구매", "가격", "온라인", "배송", "택배", "인기", "베스트",
                     "유명", "맛집", "브랜드", "정품", "도매", "소매", "벌크", "박스", "묶음", "소포장", "실속", "고급", "명품", "답례품"]
# 시즌어: 문자열 → 날짜 규칙. 오늘 기준 SEASON_MIN_DAYS~SEASON_WINDOW_DAYS 일 남았을 때만 통과.
#   고정일은 (월, 일), 해마다 바뀌는 날은 _VARIABLE_DATES 표를 쓴다.
SEASON_WORDS = [("빼빼로데이", (11, 11)), ("빼빼로", (11, 11)), ("수능", "수능"), ("발렌타인", (2, 14)), ("화이트데이", (3, 14)),
                ("크리스마스", (12, 25)), ("성탄", (12, 25)), ("할로윈", (10, 31)), ("어버이날", (5, 8)), ("스승의날", (5, 15)),
                ("설선물", "설"), ("설날", "설"), ("추석", "추석"), ("신년", (1, 1)), ("졸업", (2, 15)), ("입학", (3, 2))]
SEASON_WINDOW_DAYS = 75
SEASON_MIN_DAYS = 2   # 당일·전날은 이미 늦다(대표 확정 2026-11-16 「지시서 그대로 2일」)
# 해마다 날짜가 바뀌는 날(양력). 서버에 공휴일 자료가 없어 표로 둔다 — 2031년부터는 아래 _FALLBACK 을 쓰니 표를 늘릴 것.
#   ⚠️ 수능: 2026(2027학년도)은 11/19 다(평가원 시행계획). 지시서의 11/13 은 2025년 날짜였다.
_VARIABLE_DATES = {
    "설": {2026: (2, 17), 2027: (2, 7), 2028: (1, 27), 2029: (2, 13), 2030: (2, 3)},
    "추석": {2026: (9, 25), 2027: (9, 15), 2028: (10, 3), 2029: (9, 22), 2030: (9, 12)},
    "수능": {2025: (11, 13), 2026: (11, 19)},
}
_FALLBACK = {"설": (2, 1), "추석": (9, 25), "수능": (11, 15)}   # 표에 없는 해 — 임시값
# 상품과 무관한데 글자가 겹치는 흔한 노이즈(앱·타 브랜드명)
NOISE_WORDS = ["당근마켓", "패딩", "k2", "k95", "부업", "가볼만한곳"]
# 정보 탐색 의도어 — 구매 의도가 없어 '공략 키워드'(상품명·광고)에는 넣지 않고 groups.info(체험단·블로그)로만 보낸다
INFO_INTENT_WORDS = ["레시피", "만들기", "만드는법", "효능", "칼로리", "보관법", "보관방법", "손질", "요리법", "먹는법", "맛집",
                     "부작용", "차이", "유래", "뜻", "고르는법", "삶는법", "굽는법", "다이어트"]
# 경쟁 스토어·브랜드명에서 떼어낼 꼬리말(남은 2자 이상이 후보에 들어 있으면 타사 브랜드 키워드로 보고 제외)
_BRAND_SUFFIXES = ["주식회사", "(주)", "㈜", "정과", "식품", "푸드", "농원", "농장", "수산", "축산", "상회", "마켓", "스토어", "연구소",
                   "몰", "샵", "숍", "마을", "본가", "직판장", "유통", "에프엔비", "f&b", "산업", "컴퍼니", "코리아"]
# 다른 형태 상품·요리 이름(11-13 방울토마토 판매자 실측: 대추방울토마토에 '토마토마리네이드'·'토마토주스'·'토마토요리'가 공략 키워드로 올라옴)
OTHER_FORM_WORDS = ["마리네이드", "주스", "쥬스", "즙", "잼", "요리", "소스", "샐러드", "피클", "스프", "수프", "케첩", "케찹", "말랭이",
                    "칩", "파스타", "카레", "장아찌", "분말", "가루", "효소", "음료", "라떼", "볶음", "무침", "조림", "찜", "청", "차", "전", "국",
                    "탕", "빵", "떡", "튀김", "스무디", "에이드", "식초", "와인", "막걸리"]
# 같은 형태를 가리키는 다른 표기 — 상품 쪽에 이것이 있으면 이미 그 형태의 상품이다('토마토주스' 파는 집의 '토마토쥬스').
_FORM_SAME_SPELLING = {"주스": ("쥬스",), "쥬스": ("주스",), "케첩": ("케찹",), "케찹": ("케첩",),
                       "스프": ("수프",), "수프": ("스프",)}
# 한 글자 「종류 이름」 꼬리 — 'X빵'·'X차'·'X떡' 은 X 가 그 종류의 하나일 때 같은 상품을 부르는 말이다('베이글빵' = 베이글).
#   X 가 그 종류인지는 글자만으로 알 수 없다('쌀빵' ← 쌀 은 재료에서 만든 다른 상품). 그래서 **종류 이름 사전**으로 보되,
#   근거는 **상품의 실제 끝 분류**다: 카테고리 끝 분류(를 '/'·'·' 로 나눈 조각)가 사전에 있는 종류 이름과 **정확히 같고**,
#   후보가 메인 키워드를 통째로 품었을 때만 같은 형태로 본다.
#   ⛔ 카테고리 윗단계('과자/베이커리')는 근거가 아니다 — 초콜릿·쿠키도 그 밑에 있다('파베초콜릿빵' 은 다른 형태).
#   ⛔ 메인 키워드가 사전에 있다는 것도 근거가 아니다 — 맛·재료 이름일 수 있다('얼그레이 쿠키' 의 '얼그레이차',
#      '인절미 스낵' 의 '인절미떡' 은 다른 형태). 둘 다 교차검증에서 재현된 회귀다.
#   ⚠️ 끝 분류가 없거나 사전에 없는 종류면 종전처럼 탈락한다(영업자 화면 「제외된 키워드」에 사유와 함께 보인다).
_FORM_KINDS = {
    "빵": ("베이글", "바게트", "크루아상", "크로와상", "치아바타", "깜빠뉴", "캄파뉴", "브리오슈", "포카치아",
           "스콘", "머핀", "도넛", "도너츠", "카스테라", "카스텔라", "프레첼", "프레즐", "모닝롤"),
    "차": ("보이", "루이보스", "캐모마일", "카모마일", "페퍼민트", "히비스커스", "얼그레이", "우롱", "자스민", "재스민", "다즐링", "마테"),
    "떡": ("인절미", "송편", "백설기", "절편"),
}
_UNIT_RX = re.compile(r"\d+(?:\.\d+)?\s*(?:kg|g|ml|l|개입|개|팩|병|box|박스|인분|매|장|cm|mm)?", re.I)
_SPLIT_RX = r"[\s,/·()\[\]]+"


# ───────────────────────── 작은 도구 ─────────────────────────

def _nfc(s):
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


def nospace(s) -> str:
    return re.sub(r"\s+", "", _nfc(str(s or ""))).lower()


def strip_modifiers(k) -> str:
    """공백·범용 수식어·숫자+단위('20kg', '10개입')를 떼어 핵심 글자만 남긴다."""
    s = nospace(k)
    s = _UNIT_RX.sub("", s)
    for m in sorted(GENERIC_MODIFIERS, key=len, reverse=True):
        s = s.replace(m, "")
    return s


def _lcs_len(a: str, b: str) -> int:
    """최장 공통 부분 문자열 길이."""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _tags(product):
    return [str(t) for t in (product.get("tags") or []) if isinstance(t, str) and t.strip()]


# ───────────────────────── 상품 쪽 기준 ─────────────────────────

def anchors(product: dict, keyword: str) -> list:
    """글자 겹침을 잴 기준 — 상품명 토큰 · 태그 · 카테고리 끝 분류 · 메인 키워드(수식어 뗀 것)."""
    out = []
    for tok in re.split(_SPLIT_RX, product.get("name") or ""):
        t = strip_modifiers(tok)
        if len(t) >= 2:
            out.append(t)
    for tag in _tags(product):
        t = strip_modifiers(tag)
        if len(t) >= 2:
            out.append(t)
    leaf = product.get("categoryLeaf") or ""
    if len(nospace(leaf)) >= 2:
        out.append(nospace(leaf))
    k = strip_modifiers(keyword) or nospace(keyword)
    if len(k) >= 2:
        out.append(k)
    return list(dict.fromkeys(out))


def core_anchors(product: dict, keyword: str) -> list:
    """상품의 '핵심 명사' — 메인 키워드와, 상품명 토큰·태그·카테고리 잎이 메인 키워드와 공유하는 글자(2자 이상).
    예) 무뼈닭발 → ['무뼈닭발', '닭발', '무뼈'], 파베초콜릿 → ['파베초콜릿', '초콜릿'], 베이글 → ['베이글'].
    검색광고 API 는 연관어를 수백~수천 개 주므로(코스트코·침대·제주공항·조개구이…) 글자 겹침만으로는 부족하고,
    후보가 이 핵심 명사를 **포함**해야 공략 후보로 본다."""
    k = strip_modifiers(keyword) or nospace(keyword)
    out = [k] if len(k) >= 2 else []
    parts = list(re.split(_SPLIT_RX, product.get("name") or ""))
    parts += _tags(product)
    parts += re.split(r"[/>]", product.get("categoryLeaf") or "")
    for tok in parts:
        t = strip_modifiers(tok)
        if len(t) < 2 or not k:
            continue
        best = ""
        for i in range(len(t)):
            for j in range(i + 2, len(t) + 1):
                sub = t[i:j]
                if sub in k and len(sub) > len(best):
                    best = sub
        if len(best) >= 2 and best not in out:
            out.append(best)
    return out


def competitor_brand_tokens(names, product: dict, keyword: str = "") -> list:
    """타사 스토어명·브랜드·제조사에서 2자 이상 핵심어를 뽑는다(우리 상품명·스토어·카테고리·태그에 있는 것은 제외).
    '예시네정과' → '예시네' 처럼 꼬리말을 뗀다.

    ⚠️ 참조 구현보다 하나 더 거른다 — 범용 수식어('수제' 등)이거나 우리 핵심 명사 안에 든 말('초콜릿')은
       브랜드로 보지 않는다. 태그가 없을 때 '밀크'라는 브랜드 하나가 '밀크초콜릿'을 지우지 않게 하기 위해서다."""
    own = nospace((product.get("name") or "") + (product.get("store") or "") + (product.get("category") or "")
                  + "".join(_tags(product)))
    cores = core_anchors(product, keyword) if keyword else []
    out = []
    for n in names or []:
        s = nospace(n)
        if not s or s in ("-", "none", "null"):
            continue
        for suf in sorted(_BRAND_SUFFIXES, key=len, reverse=True):
            if s.endswith(suf) and len(s) - len(suf) >= 2:
                s = s[: -len(suf)]
                break
        if len(s) < 2 or s in own or s in out or s in GENERIC_MODIFIERS:
            continue
        if any(s in c for c in cores):
            continue
        out.append(s)
    return out


# ───────────────────────── 개별 판정 ─────────────────────────

def is_noise(candidate) -> bool:
    c = nospace(candidate)
    return any(w in c for w in NOISE_WORDS)


def is_info_intent(candidate) -> bool:
    s = nospace(candidate)
    return any(w in s for w in INFO_INTENT_WORDS)


def relevance_reason(candidate, anc, cores=None):
    """관련도 사유 — None 이면 관련 있음."""
    core = strip_modifiers(candidate)
    if len(core) < 2:
        return "modifier_only"
    if is_noise(candidate):
        return "noise"
    if cores is not None:
        c = nospace(candidate)
        if not any(x and x.lower() in c for x in cores):
            return "no_core"
    best = max((_lcs_len(core, a) for a in anc), default=0)
    if best >= 2 and (best >= 3 or best / len(core) >= 0.5):
        return None
    return "low_overlap"


def is_relevant(candidate, anc, cores=None) -> bool:
    """후보에서 범용 수식어를 떼고 남은 글자가 상품명 토큰·태그·카테고리·메인 키워드와 2자 이상 겹쳐야 한다
    (겹침이 3자 이상이거나 남은 글자의 절반 이상). cores 를 주면 후보가 핵심 명사 중 하나를 포함해야 한다."""
    return relevance_reason(candidate, anc, cores) is None


def _event_date(rule, year):
    if isinstance(rule, tuple):
        m, d = rule
    else:
        m, d = _VARIABLE_DATES.get(rule, {}).get(year) or _FALLBACK[rule]
    try:
        return date(year, m, d)
    except ValueError:
        return None


def season_word(candidate):
    """후보에 든 시즌어(첫 번째) — 없으면 None."""
    c = nospace(candidate)
    for word, rule in SEASON_WORDS:
        if word in c:
            return word, rule
    return None


def days_until(candidate, today: date):
    """후보 시즌어의 다음 행사까지 남은 날 — 시즌어가 아니면 None."""
    hit = season_word(candidate)
    if not hit:
        return None
    _, rule = hit
    best = None
    for y in (today.year, today.year + 1):
        ev = _event_date(rule, y)
        if ev is None:
            continue
        delta = (ev - today).days
        if delta >= 0 and (best is None or delta < best):
            best = delta
    return best


def season_ok(candidate, today: date) -> bool:
    if not season_word(candidate):
        return True
    delta = days_until(candidate, today)
    return delta is not None and SEASON_MIN_DAYS <= delta <= SEASON_WINDOW_DAYS


def is_competitor_brand(candidate, brand_tokens) -> bool:
    s = nospace(candidate)
    return any(b in s for b in brand_tokens if len(b) >= 2)


def is_other_form(candidate, product: dict, keyword: str = "") -> bool:
    """다른 형태의 상품인가 — 후보가 형태 말(주스·즙·빵 …)로 끝나는데 상품 쪽은 그 형태가 아닐 때.

    상품이 이미 그 형태라는 근거(하나라도 있으면 다른 형태가 아니다)
      ① 상품명·카테고리(끝 분류 포함)·판매자 태그에 그 형태 말이 있다           ('토마토주스' 파는 집)
      ② 같은 형태의 다른 표기가 있다(주스·쥬스 · 케첩·케찹 · 스프·수프)          ('토마토쥬스')
      ③ 한 글자 종류 이름(빵·차·떡) — 상품의 **끝 분류**가 그 종류 이름(사전)과 정확히 같고
         후보가 메인 키워드를 통째로 품었다('베이글빵' ← 끝 분류가 '베이글'). keyword 를 주지 않으면 ③은 보지 않는다.
    """
    c = nospace(candidate)
    ctx = nospace(" ".join([product.get("name") or "", str(product.get("category") or ""),
                            str(product.get("categoryLeaf") or "")] + _tags(product)))
    main = (strip_modifiers(keyword) or nospace(keyword)) if keyword else ""
    # 끝 분류 — categoryLeaf, 없으면 category 경로의 마지막 조각. '식빵/베이글' 은 ['식빵', '베이글'] 로 나눠 본다.
    leaf = str(product.get("categoryLeaf") or "") or re.split(r"\s*>\s*", str(product.get("category") or ""))[-1]
    leaf_parts = [nospace(x) for x in re.split(r"[/·,]", leaf) if nospace(x)]
    for w in OTHER_FORM_WORDS:
        if not (c.endswith(w) and len(c) > len(w) + (1 if len(w) >= 2 else 2)):
            continue
        if w in ctx or any(a in ctx for a in _FORM_SAME_SPELLING.get(w, ())):
            continue
        kinds = _FORM_KINDS.get(w)
        if kinds and main and main in c[: -len(w)] and any(seg in kinds for seg in leaf_parts):
            continue
        return True
    return False


def _context(product: dict) -> str:
    return nospace(" ".join([product.get("name") or "", str(product.get("category") or ""),
                             product.get("categoryLeaf") or "", product.get("store") or ""] + _tags(product)))


def is_other_variety(candidate, product: dict, keyword: str, cores) -> bool:
    """같은 종류의 다른 상품 — 메인 키워드보다 짧은 핵심 명사('초콜릿')만 공유하고, 그 앞뒤에 붙은 말이
    우리 상품명·태그·카테고리 어디에도 없을 때. 예) 파베초콜릿 상품에 '화이트초콜릿'·'말차생초콜릿',
    무뼈닭발 상품에 '국물닭발'·'튤립닭발'.
    ⛔ 블랙리스트가 아니다 — 붙은 말이 상품 쪽에 있으면 통과한다('생초콜릿'의 '생', 판매자 태그 '다크초콜릿'의 '다크').
       범용 수식어('수제')·시즌어('수능')·정보 탐색어('만들기')는 떼고 본다.
       메인 키워드를 통째로 품은 말('플레인베이글'·'파베초콜릿선물')은 이 판정을 받지 않는다(부록 B 그대로)."""
    main = strip_modifiers(keyword) or nospace(keyword)
    c = strip_modifiers(candidate)
    if not main or not c or main in c:
        return False
    for w, _ in SEASON_WORDS:
        c = c.replace(w, "")
    for w in sorted(INFO_INTENT_WORDS, key=len, reverse=True):
        c = c.replace(w, "")
    hit = max((x for x in (cores or []) if x and x != main and x in c), key=len, default="")
    if not hit:
        return False
    ctx = _context(product)
    i = c.find(hit)
    pieces = [c[:i], c[i + len(hit):]]
    return any(pc and pc not in ctx for pc in pieces)


def name_worthy(candidate) -> bool:
    """「상품명에 넣을 말」로 처방해도 되는가 — 시즌어는 며칠 뒤 지나가므로 상품명에는 넣지 않는다(광고·공략 키워드로는 쓴다)."""
    return season_word(candidate) is None and not is_info_intent(candidate)


# ───────────────────────── 한 상품의 판정기 ─────────────────────────

class Gate:
    """한 상품·한 생성일에 대한 판정기. 후보마다 ``reason(kw)`` — None 이면 통과(정보 탐색어 여부는 따로)."""

    def __init__(self, product: dict, keyword: str, today=None, competitor_names=None):
        self.product = {
            "name": product.get("name") or "",
            "category": product.get("category") or "",
            "categoryLeaf": product.get("categoryLeaf") or "",
            "tags": _tags(product),
            "store": product.get("store") or "",
        }
        self.keyword = keyword or ""
        self.main_ns = nospace(keyword)
        if isinstance(today, datetime):
            today = today.date()
        self.today = today or date.today()
        self.anchors = anchors(self.product, self.keyword)
        self.cores = core_anchors(self.product, self.keyword)
        self.brands = competitor_brand_tokens(competitor_names, self.product, self.keyword)

    def reason(self, kw):
        r = relevance_reason(kw, self.anchors, self.cores)
        if r:
            return r
        if not season_ok(kw, self.today):
            return "season_passed"
        if is_competitor_brand(kw, self.brands):
            return "competitor_brand"
        if is_other_form(kw, self.product, self.keyword):
            return "other_form"
        if is_other_variety(kw, self.product, self.keyword, self.cores):
            return "other_variety"
        return None

    def ok(self, kw) -> bool:
        return self.reason(kw) is None

    def split(self, rows, key="keyword"):
        """행 목록 → (통과 행, 탈락 행[사유 붙임]). 메인 키워드 자신은 어느 쪽에도 넣지 않는다.
        통과 행 중 정보 탐색어에는 ``infoIntent: True`` 를 붙인다(공략에서만 빠진다)."""
        passed, excluded = [], []
        for r in rows or []:
            kw = r.get(key) if isinstance(r, dict) else r
            if not kw or nospace(kw) == self.main_ns:
                continue
            row = dict(r) if isinstance(r, dict) else {key: kw}
            why = self.reason(kw)
            if why:
                row["reason"] = why
                excluded.append(row)
            else:
                if is_info_intent(kw):
                    row["infoIntent"] = True
                passed.append(row)
        return passed, excluded

    def describe(self):
        """묶음에 저장할 판정 정보(영업자 확인용)."""
        return {"version": GATE_VERSION, "date": self.today.isoformat(), "cores": self.cores[:6],
                "brandTokens": len(self.brands), "hasTags": bool(self.product["tags"])}
