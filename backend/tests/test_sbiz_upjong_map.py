"""회귀 — 업종 선택 13종 ↔ 소상공인365 업종 분류 짝 맞춤 (2026-11-22)

왜 만들었나
  분류표(30일마다 다시 받는다)의 이름이 바뀌어 사전의 검색어가 죽어 있었다 — 「제과」·「호프」·「커피」 같은 말이
  분류표에서 사라져 「베이커리·제과」는 통째로 안 이어졌고(상권 카드가 조용히 빠짐), 「병원·의원」은 「동물병원」이,
  「주점·바」는 「일반 유흥 주점」이 맨 앞에 잡혔다.

지키는 것
  ① 화면의 업종 13종이 전부 분류에 이어진다 · 맨 앞 후보가 그 업종답다.
  ② 사전(_UPJONG_SEARCH_TERMS · _HINT_UPJONG)의 검색어는 전부 분류표에 실제로 있는 글자다(죽은 말 0).
  ③ 서버의 13종 목록이 화면(PlaceAnalysisPage.jsx)과 같다.
  ④ 분류표가 바뀌어 다시 어긋나면 unmapped_industry_labels 가 그 업종을 돌려준다(05:00 점검이 로그에 남긴다).

⚠️ fixtures/sbiz_upjong_tree.tsv = 2026-11-22 운영 캐시의 분류표 사본(공개 분류 이름 247개 · 업체 정보 아님).
   네트워크 0 — 분류표를 받아 오는 함수(_upjong_pairs)를 이 사본으로 바꿔 놓고 돌린다.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))

import sbiz365 as sb   # noqa: E402

passed = failed = 0


def ok(cond, msg):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("  ✗", msg)


PAIRS = [tuple(line.rstrip("\n").split("\t", 1))
         for line in open(os.path.join(HERE, "fixtures", "sbiz_upjong_tree.tsv"), encoding="utf-8") if "\t" in line]
ok(len(PAIRS) == 247, f"분류표 사본 247개: {len(PAIRS)}")
sb._upjong_pairs = lambda: PAIRS
NAMES = [n for _, n in PAIRS]


def leafs(label, hint="", limit=3):
    return [c["name"].split(">")[-1].strip() for c in sb._resolve_upjong_candidates(label, limit=limit, hint=hint)]


# ③ 서버 목록 = 화면 목록
src = open(os.path.join(HERE, "..", "..", "frontend", "js", "components", "PlaceAnalysisPage.jsx"), encoding="utf-8").read()
m = re.search(r"INDUSTRY_OPTIONS\s*=\s*\[(.*?)\]", src, re.S)
fe = re.findall(r"'([^']+)'", m.group(1)) if m else []
ok(tuple(fe) == sb.PLACE_INDUSTRY_LABELS and len(fe) == 13, f"서버 13종 목록이 화면과 같다: {fe}")

# ① 13종 전부 이어지고 맨 앞 후보가 그 업종답다
TOP = {
    "음식점": "백반/한정식", "카페·디저트": "카페", "베이커리·제과": "빵/도넛", "분식": "김밥/만두/분식",
    "주점·바": "요리 주점", "미용·뷰티": "미용실", "네일·에스테틱": "네일숍", "병원·의원": "내과/소아과 의원",
    "약국·건강": "약국", "헬스·피트니스·필라테스": "헬스장", "학원·교육": "입시·교과학원",
    "반려동물": "애완동물/애완용품 소매업", "숙박·펜션": "호텔/리조트",
}
for label in sb.PLACE_INDUSTRY_LABELS:
    got = leafs(label)
    ok(bool(got), f"{label} — 분류에 이어진다")
    ok(got[:1] == [TOP[label]], f"{label} — 맨 앞 후보 {TOP[label]}: {got}")
ok(sb.unmapped_industry_labels() == [], "13종 가운데 안 이어지는 업종 0")
ok("동물병원" not in leafs("병원·의원"), f"병원·의원 후보에 동물병원 없음: {leafs('병원·의원')}")
ok(not any("유흥" in x for x in leafs("주점·바")[:2]), f"주점·바 앞 후보에 유흥 주점 없음: {leafs('주점·바')}")
ok("독서실/스터디 카페" not in leafs("카페·디저트"), f"카페·디저트 후보에 독서실/스터디 카페 없음: {leafs('카페·디저트')}")
ok(leafs("네일·에스테틱")[:2] == ["네일숍", "피부 관리실"], f"네일·에스테틱 = 네일숍 · 피부 관리실: {leafs('네일·에스테틱')}")
ok(leafs("헬스·피트니스·필라테스")[:2] == ["헬스장", "요가/필라테스 학원"], f"헬스·피트니스·필라테스: {leafs('헬스·피트니스·필라테스')}")
ok(not any(sb._is_residual_bucket(n) for lb in sb.PLACE_INDUSTRY_LABELS
           for n in [c["name"] for c in sb._resolve_upjong_candidates(lb, limit=1)]), "맨 앞 후보가 기타·잔여 분류가 아니다")

# ② 죽은 검색어 0
dead = sorted({t for ts in sb._UPJONG_SEARCH_TERMS.values() for t in ts if not any(t in n for n in NAMES)})
ok(not dead, f"업종 사전에 분류표에 없는 검색어 없음: {dead}")
dead_h = sorted({t for ts in sb._HINT_UPJONG.values() for t in ts if not any(t in n for n in NAMES)})
ok(not dead_h, f"힌트 사전에 분류표에 없는 검색어 없음: {dead_h}")

# 업체명·키워드 힌트
ok(leafs("음식점", hint="예시빵집 식빵")[:1] == ["빵/도넛"], "힌트 '빵' → 빵/도넛")
ok(leafs("주점·바", hint="예시호프 맥주")[:1] == ["생맥주 전문"], "힌트 '호프' → 생맥주 전문")
ok(leafs("음식점", hint="예시버거 수제버거")[:1] == ["버거"], "힌트 '버거' → 버거")
ok(leafs("음식점", hint="예시커피 로스터리")[:1] == ["카페"], "힌트 '커피' → 카페")
ok(leafs("음식점", hint="바다횟집 광어")[:1] == ["횟집"] or leafs("음식점", hint="바다횟집 광어")[:1] == ["해산물 구이/찜"],
   f"업체명의 '바' 한 글자가 주점을 앞세우지 않는다: {leafs('음식점', hint='바다횟집 광어')}")
ok(leafs("음식점", hint="예시삼겹살 고기")[:1] == ["돼지고기 구이/찜"], "종전 힌트 그대로(삼겹살 → 돼지고기 구이/찜)")

# ④ 분류표 이름이 바뀌어 어긋나면 알려 준다
sb._upjong_pairs = lambda: [(c, n.replace("빵/도넛", "제과점")) for c, n in PAIRS]
ok(sb.unmapped_industry_labels() == ["베이커리·제과"], f"분류표에서 '빵/도넛' 이 사라지면 그 업종을 돌려준다: {sb.unmapped_industry_labels()}")
sb._upjong_pairs = lambda: None
ok(sb.unmapped_industry_labels() is None, "분류표를 못 받으면 None(「0개」와 다르다)")
sb._upjong_pairs = lambda: PAIRS

# 05:00 점검 — 어긋난 업종이 있을 때만 경고 한 줄 · 예외를 밖으로 내지 않는다
import sbiz_health   # noqa: E402


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, msg):
        self.lines.append(msg)


lg = _Log()
ok(sbiz_health.check_industry_map(lg) == [] and not lg.lines, "어긋난 업종이 없으면 경고도 없다")
sb._upjong_pairs = lambda: [(c, n.replace("빵/도넛", "제과점")) for c, n in PAIRS]
lg = _Log()
ok(sbiz_health.check_industry_map(lg) == ["베이커리·제과"] and len(lg.lines) == 1 and "베이커리·제과" in lg.lines[0],
   f"어긋난 업종을 경고 한 줄로 남긴다: {lg.lines}")
sb._upjong_pairs = lambda: None
lg = _Log()
ok(sbiz_health.check_industry_map(lg) is None and not lg.lines, "분류표를 못 받으면 None · 경고 없음(판정 못 함)")


def _boom():
    raise RuntimeError("x")


sb._upjong_pairs = _boom
lg = _Log()
ok(sbiz_health.check_industry_map(lg) is None and len(lg.lines) == 1, "점검이 터져도 예외를 밖으로 내지 않는다")
sb._upjong_pairs = lambda: PAIRS
# 스케줄러 배선(소스 검사 — 게이트에는 apscheduler 가 없다)
sch = open(os.path.join(HERE, "..", "scheduler.py"), encoding="utf-8").read()
i = sch.find("def _run_sbiz_health_probe")
j = sch.find("\ndef ", i + 10)
ok(re.search(r"^\s+check_industry_map\(logger\)\s*$", sch[i:j], re.M) is not None, "05:00 자가 점검이 업종 사전 점검을 부른다")

# 맨 앞 후보가 바뀌었으므로 옛 후보로 계산해 둔 상권 결과 캐시를 버린다(캐시 판 번호)
ok(sb.CACHE_NS != "v3", "업종 후보 규칙이 바뀌었으니 캐시 판 번호를 올렸다")

print(f"sbiz_upjong_map: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
