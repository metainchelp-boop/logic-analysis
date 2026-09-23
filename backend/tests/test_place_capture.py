"""회귀 — 플레이스 캡처 판독 · 「N위 밖」 표시 (신고 #276 · 2026-09-23)

지키는 것:
  ① 필터 버튼(PlaceListFilterItem — 「거리순」·「영업중」)을 업체로 세지 않는다.
     실측: 업체 52곳인데 「판독된 업체 116곳」. 필터가 업체 **앞**에 오면 순위가 밀린다.
  ② 알 수 없는 형식은 id·name 에 더해 업체다운 칸(주소·업종·리뷰 수·좌표)이 있을 때만 업체로 친다.
     알려진 업체 형식(PlaceListBusinessesItem 등)은 칸과 무관하게 그대로 받는다(무회귀).
  ③ 무인 추적기(extension-place/place-runner.js pageExtract)가 **같은 규칙**이다 —
     같은 목록 데이터를 두 쪽에 넣어 업체·순위가 똑같이 나오는지 실제로 돌려 본다.
  ④ 네이버가 밝힌 전체 업체 수(total)를 읽는다(표시용 · 판정에 안 쓴다).
  ⑤ 비슷한 이름 후보는 보수적으로 — 신고 건처럼 이름이 정확한데 목록 밖인 경우엔 후보가 없어야
     「이름을 확인하라」는 헛된 문구가 안 뜬다. 흔한 낱말(「카페」)은 후보가 못 된다.
  ⑥ 서버 캡처 결과에 near·outside·total 이 additive 로 실리고, 목록 밖이면 「N위 밖」이라고 말한다.
     「아래로 스크롤한 뒤 복사」 안내는 뺐다(실측 — 붙여넣는 목록은 첫 한 묶음뿐).
  ⑦ 화면이 outside 를 받아 「N위 밖」으로 보이고, 옛 서버(칸 없음)면 종전 문구 그대로다.

⚠️ 게이트 환경엔 fastapi 가 없다 → place_crawler 는 직접 import(표준 라이브러리만),
   main.py·화면은 소스 배선으로 판정한다. 이름만 찾으면 주석에 걸리므로 **조건식·호출 모양**으로 본다.
⚠️ 이 저장소는 공개다 — 픽스처에 실제 업체명·검색어를 쓰지 않는다(전부 지어낸 이름).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

import place_crawler as pc  # noqa: E402

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# ── 픽스처: 네이버 목록 데이터 모양(지어낸 이름) ────────────────────────────
# 필터 버튼을 일부러 업체 **앞**에 둔다 — 종전 규칙이면 첫 업체가 2위로 밀린다.
def fixture():
    ap = {}
    ap["ROOT_QUERY"] = {
        '__typename': 'Query',
        'placeList({"input":{"query":"가상검색어"}})': {
            'businesses({"input":{"start":1}})': {
                "total": 335,
                "items": [{"__ref": "PlaceListBusinessesItem:111"}, {"__ref": "PlaceListBusinessesItem:222"},
                          {"__ref": "PlaceListBusinessesItem:444"}],
            },
            'filters': [{"__ref": "PlaceListFilterItem:거리순"}],
        },
        'placeList({"input":{"query":"가상검색어","sub":1}})': {
            'businesses({"input":{"start":1}})': {"total": 3, "items": []},
        },
    }
    ap["PlaceListFilterItem:거리순"] = {"__typename": "PlaceListFilterItem", "id": "거리순", "name": "거리순",
                                     "count": None, "value": "distance"}
    ap["PlaceListFilterItem:영업중"] = {"__typename": "PlaceListFilterItem", "id": "영업중", "name": "영업중",
                                     "count": 12, "value": "open"}
    ap["PlaceListBusinessesItem:111"] = {"id": "111", "name": "가나다 커피하우스", "address": "가상시 가상동 1",
                                         "category": "카페", "visitorReviewCount": "1,204"}
    ap["RestaurantAdSummary:333"] = {"id": "333", "name": "광고 업체", "adId": "nad-1", "category": "카페"}
    ap["PlaceListBusinessesItem:222"] = {"id": "222", "name": "라마바 베이커리", "roadAddress": "가상로 2"}
    ap["PlaceListBusinessesItem:444"] = {"id": "444", "name": "사아자 디저트"}          # 알려진 형식 — 칸 적어도 받는다
    ap["SomethingNew:555"] = {"id": "555", "name": "차카타 브런치", "x": "127.1", "y": "37.5"}   # 모르는 형식 + 좌표
    ap["SomethingNew:666"] = {"id": "666", "name": "정렬 기준"}                         # 모르는 형식 · 칸 없음 → 업체 아님
    ap["PlaceListFilterItem:주차"] = {"__typename": "PlaceListFilterItem", "id": "주차", "name": "주차",
                                    "address": "혹시 칸이 있어도"}                        # 필터는 칸이 있어도 제외
    return ap


def html_of(ap):
    return "<html><body><script>window.__APOLLO_STATE__ = " + json.dumps(ap, ensure_ascii=False) + \
           ";</script></body></html>"


EXPECTED = [("가나다 커피하우스", 1, False), ("광고 업체", None, True), ("라마바 베이커리", 2, False),
            ("사아자 디저트", 3, False), ("차카타 브런치", 4, False)]

print("\n① 필터 버튼을 업체로 세지 않는다 · ② 모르는 형식은 업체다운 칸이 있을 때만")
parsed = pc.parse_place_search(html_of(fixture()))
got = [(it["name"], it.get("rank"), bool(it.get("is_ad"))) for it in parsed["items"]]
ok("업체 목록이 기대와 정확히 같다(필터 3개·칸 없는 모르는 형식 제외)", got == EXPECTED, f"got={got}")
organic = [it for it in parsed["items"] if not it.get("is_ad")]
ok("오가닉 4곳(종전 규칙이면 필터·모르는 항목까지 8곳)", len(organic) == 4, f"n={len(organic)}")
ok("필터가 앞에 있어도 첫 업체는 1위(밀리지 않는다)", got and got[0][1] == 1)
names = {it["name"] for it in parsed["items"]}
ok("「거리순」·「영업중」·「주차」 필터가 목록에 없다", not ({"거리순", "영업중", "주차"} & names))
ok("칸 없는 모르는 형식(「정렬 기준」)은 제외", "정렬 기준" not in names)
ok("알려진 형식은 칸이 적어도 받는다(무회귀)", "사아자 디저트" in names)
ok("리뷰 수 정수화 그대로(1,204 → 1204)", parsed["items"][0].get("visitor_reviews") == 1204)
ok("_is_business_entry — 필터는 업체다운 칸이 있어도 거짓",
   pc._is_business_entry("PlaceListFilterItem:x", {"id": "x", "name": "x", "address": "a"}) is False)
ok("_is_business_entry — 알려진 형식은 id·name 만 있어도 참",
   pc._is_business_entry("RestaurantListSummary:1", {"id": "1", "name": "n"}) is True)
ok("_is_business_entry — 모르는 형식 + 칸 없음 = 거짓",
   pc._is_business_entry("Other:1", {"id": "1", "name": "n", "count": 3}) is False)
ok("_is_business_entry — 모르는 형식 + 업종 칸 = 참",
   pc._is_business_entry("Other:1", {"id": "1", "name": "n", "businessCategory": "cafe"}) is True)

print("\n④ 네이버가 밝힌 전체 업체 수(표시용)")
ok("parse_place_search 가 total 을 싣는다(목록이 가장 긴 placeList 의 값)", parsed.get("total") == 335,
   f"total={parsed.get('total')}")
ok("빈 입력도 total 키를 준다(None)", pc.parse_place_search("").get("total", "없음") is None)
ok("ROOT_QUERY 없으면 None", pc._list_total({"A:1": {}}) is None)
ok("total 이 참·거짓 값이면 무시", pc._list_total({"ROOT_QUERY": {"placeList(x)": {"businesses(y)": {
    "total": True, "items": []}}}}) is None)
ok("total 이 숫자가 아니면 무시", pc._list_total({"ROOT_QUERY": {"placeList(x)": {"businesses(y)": {
    "total": "335", "items": []}}}}) is None)

print("\n  find_place_rank 무회귀")
r = pc.find_place_rank(parsed, target_name="라마바 베이커리")
ok("이름으로 찾으면 오가닉 2위", r["state"] == "노출" and r["rank"] == 2, str(r))
r = pc.find_place_rank(parsed, target_doc_id="444")
ok("번호로 찾으면 3위", r["state"] == "노출" and r["rank"] == 3, str(r))
r = pc.find_place_rank(parsed, target_name="없는 가게")
ok("없으면 미노출", r["state"] == "미노출", str(r))
r = pc.find_place_rank(parsed, target_name="광고 업체")
ok("광고는 순위로 치지 않는다(미노출)", r["state"] == "미노출", str(r))

print("\n⑤ 비슷한 이름 후보는 보수적으로")
items = parsed["items"]
ok("신고 건 모양 — 정확한 이름이 목록 밖이면 후보 없음",
   pc.similar_name_candidate("하파타 공방", items) is None)
c = pc.similar_name_candidate("라마바 베이커리 본점", items)
ok("입력이 더 길고 목록 이름이 통째로 들어 있으면 후보(「…본점」 ↔ 「…」)",
   bool(c) and c["name"] == "라마바 베이커리" and c["rank"] == 2, str(c))
c = pc.similar_name_candidate("가나다 커피하우즈", items)
ok("오타 한 글자는 후보", bool(c) and c["name"] == "가나다 커피하우스", str(c))
ok("흔한 낱말만 겹치면 후보 아님(「카페」)",
   pc.similar_name_candidate("동네 카페", [{"name": "카페", "rank": 1}]) is None)
ok("짧은 한글 이름끼리 우연히 비슷한 정도(0.5)는 후보 아님",
   pc.similar_name_candidate("가나다라", [{"name": "가나마바", "rank": 1}]) is None)
ok("광고는 후보로 보지 않는다",
   pc.similar_name_candidate("광고 업체 본점", items) is None)
ok("이름이 비었으면 None", pc.similar_name_candidate("", items) is None)


print("\n③ 무인 추적기(pageExtract)가 같은 규칙인가 — 실제로 돌려 본다")
node = shutil.which("node")
if not node:
    ok("node 가 있어야 이 검사를 돌린다(게이트는 setup-node 이후에 둔다)", False)
else:
    runner = read("extension-place/place-runner.js")
    m = re.search(r"^function pageExtract\(\) \{.*?^\}", runner, re.DOTALL | re.MULTILINE)
    ok("pageExtract 함수를 찾았다", bool(m))
    if m:
        harness = (
            "var ap = " + json.dumps(fixture(), ensure_ascii=False) + ";\n"
            "global.setTimeout = function (fn) { setImmediate(fn); };\n"
            "global.window = { __APOLLO_STATE__: ap, scrollTo: function () {} };\n"
            "global.document = { querySelectorAll: function () { return []; },\n"
            "  scrollingElement: { scrollTop: 0, scrollHeight: 1000 }, body: { scrollHeight: 1000 } };\n"
            "global.getComputedStyle = function () { return { overflowY: 'visible' }; };\n"
            "global.location = { href: 'https://pcmap.place.naver.com/test' };\n"
            + m.group(0) + "\n"
            "pageExtract().then(function (r) { process.stdout.write(JSON.stringify(r)); });\n"
        )
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "h.js")
            with open(p, "w", encoding="utf-8") as f:
                f.write(harness)
            out = subprocess.run([node, p], capture_output=True, text=True, timeout=30)
        ok("추적기 실행이 끝났다", out.returncode == 0, out.stderr[-300:])
        try:
            jr = json.loads(out.stdout or "{}")
        except Exception:
            jr = {}
        jgot = [(it.get("name"), it.get("rank"), bool(it.get("ad"))) for it in (jr.get("items") or [])]
        ok("추적기 결과 = 서버 판독기 결과(이름·순위·광고 여부까지 동일)", jgot == got, f"js={jgot}")
        ok("추적기도 필터 버튼을 세지 않는다", not ({"거리순", "영업중", "주차"} & {n for n, _, _ in jgot}))
        ok("추적기 리뷰 수 정수화 그대로(1204)", (jr.get("items") or [{}])[0].get("vr") == 1204)

    man = json.loads(read("extension-place/manifest.json"))
    ok("추적기 버전이 1.1.1 이상(팝업이 이 값을 보여 준다 — 교체 확인용)",
       tuple(int(x) for x in man["version"].split(".")) >= (1, 1, 1), man.get("version"))


print("\n⑥ 서버 캡처 결과 — near·outside·total · 「N위 밖」 문구")
main_src = read("backend/main.py")
i0 = main_src.find("def _place_seo_analyze(")
i1 = main_src.find("\ndef ", i0 + 10)
body = main_src[i0:i1]
ok("_place_seo_analyze 본문을 찾았다", i0 > 0 and i1 > i0)
ok("비슷한 이름은 목록이 읽혔고 못 찾았을 때만 계산",
   re.search(r"if _provided and _organic and not _matched:\s*\n\s*try:\s*\n\s*_near = place_crawler\."
             r"similar_name_candidate\(_target_raw, _organic\)", body) is not None)
ok("capture 에 near 가 실린다", re.search(r'"near":\s*_near', body) is not None)
ok("outside = 붙였고·읽혔고·못 찾았고·비슷한 이름도 없을 때",
   re.search(r'"outside":\s*bool\(_provided and _organic and not _matched and not _near\)', body) is not None)
ok("capture 에 total 이 실린다(표시용)", re.search(r'"total":\s*parsed\.get\("total"\)', body) is not None)
i_near = body.find("elif _near:")
i_nm = body.find("elif not _matched:")
ok("비슷한 이름 분기가 「못 찾음」 분기보다 먼저", 0 < i_near < i_nm, f"{i_near} {i_nm}")
seg_nm = body[i_nm:i_nm + 900] if i_nm > 0 else ""
ok("못 찾음 문구가 「N위 밖」을 말한다", "위 밖입니다" in seg_nm and "len(_organic)" in seg_nm)
ok("못 찾음 문구에서 「업체명이 등록명과 같은지」 선권유가 빠졌다",
   "업체명이 플레이스 등록명과 같은지" not in body)
seg_rd = body[body.find("elif not _organic:"):i_near]
ok("판독 실패 문구에서 「아래로 스크롤」 안내가 빠졌다(효과 없음 실측)", "스크롤" not in seg_rd and len(seg_rd) > 0)
ok("판독 실패 문구는 목록 화면에서 다시 복사하라고 한다", "검색결과 목록 화면" in seg_rd)
ok("비슷한 이름 문구가 후보 이름·순위를 싣는다",
   "_near.get('name')" in body[i_near:i_nm] and "_near.get('rank')" in body[i_near:i_nm])
ok("이름이 비었을 때 「」 대신 「내 업체」", '_target_nm = _target_raw or "내 업체"' in body)


print("\n⑦ 화면 — outside 를 받아 「N위 밖」 · 옛 서버면 종전 문구")
jsx = read("frontend/js/components/PlaceAnalysisPage.jsx")
ok("경고 머리말이 outside 면 「이 검색어에서는 N위 밖입니다」",
   re.search(r"cap\.outside \? \('이 검색어에서는 ' \+ \(cap\.organic \|\| 0\) \+ '위 밖입니다'\)", jsx) is not None)
ok("비슷한 이름이면 이름 확인 머리말", "cap.near ? '비슷한 이름이 있습니다" in jsx)
ok("옛 서버(칸 없음)면 종전 머리말 「내 업체를 찾지 못했습니다」 그대로",
   re.search(r":\s*'내 업체를 찾지 못했습니다'\)\)", jsx) is not None)
ok("목록 밖은 경고색이 아니라 중립 상자", "(cap.outside ? ' neutral' : '')" in jsx)
ok("KPI 가 「N위 밖」", re.search(r"\(_cap\.outside && _cap\.organic\) \? \(_cap\.organic \+ '위 밖'\) : '순위 밖'", jsx)
   is not None)
ok("KPI 부제가 「첫 N곳 기준」", "'’ 첫 ' + _cap.organic + '곳 기준'" in jsx)
css = read("frontend/css/place.css")
ok("중립 상자 스타일이 있다", ".capwarn.neutral" in css)
ok("중립 상자가 화면 바탕(--pa-bg)과 같은 색이 아니다(같으면 상자가 사라진다)",
   re.search(r"\.capwarn\.neutral\{background:var\(--pa-card\)", css) is not None)
_vers = [re.search(r"css/place\.css\?v=([0-9.]+)", read(f)) for f in ("frontend/index.html", "frontend/index.bundle.html")]
ok("place.css 캐시 표식을 올렸다(6.6.1 이상 · 두 index 같음 — 안 올리면 옛 CSS 가 남는다)",
   all(_vers) and _vers[0].group(1) == _vers[1].group(1)
   and tuple(int(x) for x in _vers[0].group(1).split(".")) >= (6, 6, 1))


print(f"\n결과: {passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
