"""회귀 — 맞춤제안서 v3: 로직분석 인계 자료 → 제안서 재료(facts)·문장(copy) (2026-10-26)

지키는 것:
  ① facts — 보고서 숫자를 그대로 옮긴다(검색량·경쟁강도·리뷰·평점 내림·상세 점수·SEO·순위 미노출·
     데이터랩 최고 달·평균·요일(0 제외)·진입 점수·공략 키워드(정보성·높음 제외)·월 표기).
  ② copy(규칙 문장) — 모든 칸이 차고 · 금지어·금액·태그 없음 · validate 를 스스로 통과한다(사실값에 없는 숫자 0).
  ③ validate — AI 문장 중 낯선 숫자·금액·금지어·모르는 칸·너무 긴 칸은 버린다.
  ④ generate — 키 없으면 규칙 문장 · 가짜 AI 응답 중 통과한 칸만 바꾼다 · AI 가 죽어도 규칙 문장.
  ⑤ enrich — v3 가 아니면 원본 그대로 · v3 면 facts/copy/copyMeta 를 붙이고 원본 dict 는 안 고친다 ·
     재료 정리가 실패해도 예외 없이 원본을 돌려준다.
  ⑥ 조사 j() — 받침에 맞게 은/는·이/가·을/를.
  ⑦ main.py 가 /api/sales-bundle 에서 v3 일 때만 enrich 를 부른다(소스 검사).
"""
import copy as _copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..")))
sys.path.insert(0, HERE)

import proposal_copy as pc  # noqa: E402
import proposal_facts as pf  # noqa: E402
import proposal_v3 as pv  # noqa: E402
from proposal_fixture import bundle  # noqa: E402

passed = failed = 0


def ok(cond, name):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL:", name)


# ① facts
f = pf.build(bundle())
ok(f["main"]["keyword"] == "블렌드원두", "분석 키워드")
ok(f["main"]["total"] == 110, "검색량 합 110")
ok(f["main"]["comp"] == "높음", "경쟁강도 높음")
ok(f["review"]["count"] == 50, "리뷰 50")
ok(f["review"]["rating"] == 4.8, "평점은 보고서처럼 내림 4.8")
ok(f["detail"]["score"] == 81 and f["detail"]["grade"] == "우수", "상세 81 우수")
ok("동영상" in (f["detail"]["missing"] or []), "상세 빠진 것에 동영상")
ok(f["seo"]["score"] == 31, "SEO 31")
ok(f["rank"]["status"] == "미노출", "순위 미노출")
ok(f["datalab"]["peakMonthNames"][:1] == ["2026년 4월"], "최고 달 이름")
ok(f["datalab"]["avgIndex"] == 29, "평균 지수 29")
ok(f["datalab"]["peakDay"] == "수", "가장 많은 요일 수")
ok(f["entry"]["score"] == 50, "진입 점수 50")
ok(f["bid"] == {"pc1": 2400, "mobile1": 1800, "pc5": 700, "minPc": 70, "minMobile": 70}, "입찰가 모양")
tg = [t["keyword"] for t in f["keywords"]["targets"]]
ok(tg[:2] == ["커피원두", "원두1KG"], "공략 키워드 앞 둘")
ok("커피원두추천" not in tg, "정보성 키워드는 공략에서 뺀다")
ok("아라비카커피" not in tg, "경쟁 높음은 공략에서 뺀다")
ok(f["flags"]["exposureGap"] is True, "노출 결손 신호")
ok(f["flags"]["hasCompetitors"] is False, "경쟁 상품 없음 표시")
ok(pf.month_name("26.4") == "2026년 4월" and pf.month_name("2026-11") == "2026년 11월", "월 표기")
ok(pf.month_name("이상한값") == "이상한값", "못 읽으면 그대로")
ok(pf.to_int("< 10") == 5, "'< 10' 은 5")
json.dumps(f, ensure_ascii=False)  # 직렬화 가능해야 보관된다

# 빈 자료에도 예외 없이 돈다
empty = pf.build({"v3": True, "keyword": "x"})
ok(empty["rank"]["status"] in ("미확인", "미노출"), "빈 자료 순위")
ok(isinstance(pc.template(empty), dict), "빈 자료 규칙 문장")

# ② 규칙 문장
c = pc.template(f)
ok(set(c) == set(pc.FIELDS), "모든 칸이 찬다")
ok(all(isinstance(v, str) and v.strip() for v in c.values()), "빈 칸 없음")
good, bad = pc.validate(c, f)
ok(bad == [], "규칙 문장은 스스로 검사를 통과한다: %s" % bad)
ok(not any(w in v for v in c.values() for w in ("보장", "반드시", "확실히", "100%", "무조건")), "금지어 없음")
ok("29" in c["timing.b"] and "2026년 4월" in c["timing.b"], "시기 문장")
ok("원두/생두 상품을" in c["diag.situation"], "조사 을")
ok(f["keywords"]["targetsMissingInName"] == ["커피원두"], "상품명에 빠진 공략 키워드")
ok("'커피원두'" in c["summary.problem"] and "원두1KG" not in c["summary.problem"], "이미 상품명에 있는 키워드는 「없다」고 안 쓴다")
ok("원두1KG" not in c["data.gap1"], "부족한 부분도 빠진 것만")
gc = pc.template(pf.build(bundle()))
ok(gc == c, "같은 입력이면 같은 문장")

# ③ validate
v_ok, v_bad = pc.validate({
    "summary.now": "평점 4.8점과 리뷰 50건을 갖췄습니다.",
    "summary.problem": "월 매출 300만원이 기대됩니다.",
    "summary.solution": "반드시 1위를 만듭니다.",
    "diag.situation": "판매량이 1234건입니다.",
    "없는칸": "x",
    "summary.conclusion": "가" * 999,
}, f)
reasons = dict(v_bad)
ok("summary.now" in v_ok, "사실 숫자만 쓴 칸은 통과")
ok(reasons.get("summary.problem") == "금액", "금액은 버림")
ok(reasons.get("summary.solution") == "금지어", "금지어는 버림")
ok(str(reasons.get("diag.situation", "")).startswith("낯선 숫자"), "낯선 숫자는 버림")
ok(reasons.get("없는칸") == "모르는 칸", "모르는 칸은 버림")
ok(reasons.get("summary.conclusion") == "너무 김", "너무 긴 칸은 버림")


# ④ generate
r = pc.generate(f, api_key=None)
ok(r["copy"] == c and r["source"]["ai"] == [], "키 없으면 규칙 문장")


class _Blk:
    def __init__(self, t):
        self.text = t


class _Msg:
    def __init__(self, t):
        self.content = [_Blk(t)]


class FakeClient:
    def __init__(self, text=None, boom=False):
        self.text, self.boom, self.calls = text, boom, 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        if self.boom:
            raise RuntimeError("down")
        return _Msg(self.text)


fake = FakeClient("```json\n" + json.dumps({
    "summary.now": "리뷰 50건, 평점 4.8점의 신뢰를 이미 갖추셨습니다.",
    "summary.problem": "광고비 500만원이면 됩니다.",
}, ensure_ascii=False) + "\n```")
r = pc.generate(f, client=fake)
ok(fake.calls == 1, "AI 1회 호출")
ok(r["copy"]["summary.now"].startswith("리뷰 50건, 평점"), "통과한 칸만 AI 문장")
ok(r["copy"]["summary.problem"] == c["summary.problem"], "버린 칸은 규칙 문장")
ok(r["source"]["ai"] == ["summary.now"], "출처 기록")
r = pc.generate(f, client=FakeClient(boom=True))
ok(r["copy"] == c and any("AI 호출 실패" in p for p in r["aiProblems"]), "AI 가 죽어도 규칙 문장")
r = pc.generate(f, client=FakeClient("설명만 있고 JSON 없음"))
ok(r["copy"] == c, "JSON 아니면 규칙 문장")

# ⑤ enrich
raw = {"keyword": "a"}
ok(pv.enrich(raw) is raw, "v3 아니면 그대로")
src = bundle()
before = _copy.deepcopy(src)
out = pv.enrich(src, api_key="")
ok(src == before, "원본 dict 는 안 고친다")
ok(out["facts"]["main"]["keyword"] == "블렌드원두" and set(out["copy"]) == set(pc.FIELDS), "facts·copy 붙음")
ok(out["copyMeta"]["source"]["ai"] == [], "키 없으면 AI 칸 0")
ok(out["htmlDetail"] == src["htmlDetail"], "원본 자료는 함께 남는다")
broken = {"v3": True, "related": "깨진값", "datalab": 3, "htmlDetail": [1], "advertiser": "x", "volume": "y"}
try:
    out2 = pv.enrich(broken, api_key="")
    ok(isinstance(out2, dict), "깨진 자료에도 dict")
except Exception as e:  # noqa: BLE001
    ok(False, "깨진 자료에서 예외: %r" % e)
json.dumps(out, ensure_ascii=False)
ok("inputs" not in out, "입력값을 안 보내면 inputs 없음")
src_in = bundle()
src_in["inputs"] = {"salesMan": "3000", "adMan": 300.4, "evil": "<script>"}
out_in = pv.enrich(src_in, api_key="")
ok(out_in["inputs"] == {"salesMan": 3000, "adMan": 300}, "월 매출·월 광고비(만원)는 숫자만 남긴다")
for bad in ({"salesMan": -1}, {"salesMan": "abc"}, {"salesMan": True}, {"adMan": 10 ** 9}, "문자열", None):
    t = bundle(); t["inputs"] = bad
    ok("inputs" not in pv.enrich(t, api_key=""), "이상한 입력값은 버린다: %r" % (bad,))
broken_in = {"v3": True, "related": "깨진값", "datalab": 3, "inputs": {"salesMan": 100}}
ok(pv.enrich(broken_in, api_key="").get("inputs") == {"salesMan": 100}, "재료 정리 실패해도 입력값은 남는다")

# ⑥ 조사
ok(pc.j("상점", "은") == "상점은" and pc.j("스토어", "은") == "스토어는", "은/는")
ok(pc.j("원두", "을") == "원두를" and pc.j("생두상품", "을") == "생두상품을", "을/를")
ok(pc.j("'원두1KG'", "이") == "'원두1KG'이", "끝이 한글 아니면 받침 쪽")

# ⑦ main.py 배선
src_main = open(os.path.join(HERE, "..", "main.py"), encoding="utf-8").read()
i = src_main.find('@app.post("/api/sales-bundle")')
seg = src_main[i:i + 1600]
ok('payload.get("v3")' in seg and "proposal_v3.enrich(payload)" in seg, "v3 일 때 enrich")
ok("sales_bundle.put(conn, payload" in seg, "enrich 결과를 보관")

print(f"proposal_v3: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
