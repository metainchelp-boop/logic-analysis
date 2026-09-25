"""회귀 — 관리팀 순위 읽기 도우미(사람이 넘긴 화면 · 대표 확정 2026-09-24)

지키는 것
  ① 인증 — 도우미 토큰은 수집기 토큰과 다르다(관리팀 PC 가 수집기 경로를 못 부른다) · 수집기 토큰 없으면 전부 막힘
  ② PC 번호만 받는다(1~99) — 이름·계정 칸이 없다(대표 확정 ③)
  ③ 1위부터 끊김 없는 순위만 받는다 · 중복·빈 번호 거절 · 300위 넘으면 자름 · 300위/결과 끝이면 완료
  ④ 기록 — 부분이면 찾은 순위만(positive_only) · 완료면 전 대상(300위 밖 포함) + 수집분 저장
            · 부분이어도 대상을 다 찾으면 그날 완료 표시(수집기와 같은 표) · 못 찾으면 표시 없음
  ⑤ ④ 첫 주 대조 스위치 — 로그인 화면을 기록에서 뺄 수 있다(빼면 순위 기록 함수를 부르지 않는다)
  ⑥ 할 일 목록 — 끝난 것 제외 · 수집기가 해 보고 못 끝낸 것부터 · 다른 PC 가 방금 본 것 표시
  ⑦ 운영 통계 PC 번호별 · 대조(같은 날 수집분과) · 보관정책 · 조회 실패는 None(0 과 섞지 않음)
  ⑧ 배선 — 추적 키워드가 아니면 아무것도 저장 안 함 · 로그에 검색어 안 찍음 · 라우터 등록 · 배포 제외 폴더
⚠️ stdlib 만.
"""
import json
import os
import re
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE); ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


def raises(fn, status=None):
    try:
        fn()
    except hv.HumanViewError as e:
        return status is None or e.status_code == status
    return False


import human_view as hv
import collector_observation as co


def prods(n, start=1):
    return [{"rank": i, "productId": str(1000 + i), "nvMid": str(1000 + i), "title": f"t{i}", "link": f"https://x/{i}"}
            for i in range(start, start + n)]


def body(n=40, **kw):
    b = {"keyword": "캠핑의자", "products": prods(n), "pagesRead": max(1, (n + 39) // 40), "loggedIn": "out"}
    b.update(kw)
    return b


def fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    conn = sqlite3.connect(path)
    co.init_observation_db(conn)
    hv.init_db(conn)
    conn.execute("CREATE TABLE collected_serp (keyword TEXT, collected_date TEXT, total INTEGER, products_json TEXT, "
                 "product_count INTEGER, meta_json TEXT, created_at TEXT, PRIMARY KEY(keyword, collected_date))")
    conn.commit()
    return conn


print("① 인증")
T = "collector-secret-token"
d = hv.derive_token(T)
ok("도우미 토큰은 수집기 토큰과 다르다", d and d != T and len(d) == 40)
ok("같은 수집기 토큰이면 늘 같은 도우미 토큰", d == hv.derive_token(T))
ok("맞는 토큰 통과", hv.token_ok(d, T))
ok("수집기 토큰을 그대로 넣으면 거절", not hv.token_ok(T, T))
ok("빈 토큰 거절", not hv.token_ok("", T) and not hv.token_ok(None, T))
ok("수집기 토큰이 서버에 없으면 전부 막힘", hv.derive_token("") == "" and not hv.token_ok("", "") and not hv.token_ok("x", ""))

print("② PC 번호만")
ok("PC 번호 3", hv.pc_no("3") == 3)
ok("PC 번호 0 거절", raises(lambda: hv.pc_no("0"), 400))
ok("PC 번호 100 거절", raises(lambda: hv.pc_no(100), 400))
ok("PC 번호 없음 거절", raises(lambda: hv.pc_no(None), 400))
_c = sqlite3.connect(":memory:"); hv.init_db(_c)
_cols = [r[1] for r in _c.execute("PRAGMA table_info(human_view_uploads)")]
ok("기록 표에 이름·계정 칸이 없다", _cols and not any(x in c for c in _cols for x in ("name", "user", "employee", "account", "email")), str(_cols))

print("③ 검증")
it = hv.validate(body(40))
ok("40위까지 부분", it["covered"] == 40 and not it["complete"] and it["loggedIn"] == "out")
ok("순위가 2부터 시작하면 거절", raises(lambda: hv.validate(body(products=prods(5, start=2))), 422))
ok("중간이 빠지면 거절", raises(lambda: hv.validate(body(products=[prods(1)[0], dict(prods(3)[2])])), 422))
dup = prods(3); dup[2] = dict(dup[2], productId=dup[0]["productId"])
ok("같은 상품 두 번 거절", raises(lambda: hv.validate(body(products=dup)), 422))
nop = prods(2); nop[1] = dict(nop[1], productId="")
ok("상품 번호 빈 줄 거절", raises(lambda: hv.validate(body(products=nop)), 422))
ok("상품 0건 거절", raises(lambda: hv.validate(body(products=[])), 400))
ok("검색어 없음 거절", raises(lambda: hv.validate(body(keyword="  ")), 400))
ok("pagesRead 0 거절", raises(lambda: hv.validate(body(pagesRead=0)), 400))
ok("모르는 로그인 값은 unknown", hv.validate(body(loggedIn="maybe"))["loggedIn"] == "unknown")
it300 = hv.validate(body(320, pagesRead=8))
ok("300위 넘으면 300에서 자르고 완료", it300["covered"] == 300 and it300["complete"])
ok("결과 끝이면 12위까지여도 완료", hv.validate(body(12, endOfResults=True))["complete"])
ok("결과 끝은 true 일 때만(문자열 거절)", not hv.validate(body(12, endOfResults="true"))["complete"])

print("④ 기록")
calls = []


def rec(ret):
    def _r(positive_only):
        calls.append(positive_only)
        return dict(ret)
    return _r


stored = []
conn = fresh_db()
calls.clear()
r = hv.ingest(conn, hv.validate(body(40)), "2026-09-24", 2, rec({"products": 1, "clients": 0, "targets_total": 2, "targets_found": 1}),
              lambda: stored.append(1))
ok("부분 → 찾은 순위만 기록", calls == [True] and r["status"] == "partial" and not stored)
ok("부분 · 하나 못 찾음 → 완료 표시 없음", co.found_done_keywords(conn, "2026-09-24") == set())
calls.clear()
r = hv.ingest(conn, hv.validate(body(80, pagesRead=2)), "2026-09-24", 2,
              rec({"products": 2, "clients": 0, "targets_total": 2, "targets_found": 2}), lambda: stored.append(1))
ok("부분 · 대상 전부 찾음 → 그날 완료 표시(수집기와 같은 표)", r["status"] == "partial_all_found"
   and co.found_done_keywords(conn, "2026-09-24") == {"캠핑의자"} and not stored)
ok("완료 표시 출처가 사람(PC 번호)", conn.execute("SELECT observation_id FROM collector_found_done").fetchone()[0] == "human:pc2")
calls.clear()
r = hv.ingest(conn, hv.validate(body(80, pagesRead=2, keyword="무선청소기")), "2026-09-24", 1,
              rec({"products": 0, "clients": 0, "targets_total": 0, "targets_found": 0}), lambda: stored.append(1))
ok("대상 0개면 완료로 치지 않는다", r["status"] == "partial" and "무선청소기" not in co.found_done_keywords(conn, "2026-09-24"))
calls.clear(); stored.clear()
r = hv.ingest(conn, hv.validate(body(300, pagesRead=8, keyword="유기농 쌀")), "2026-09-24", 1,
              rec({"products": 1, "clients": 1, "targets_total": 2, "targets_found": 1}), lambda: stored.append(1))
ok("300위까지 → 전 대상 기록(positive_only=False) + 수집분 저장", calls == [False] and stored == [1] and r["status"] == "complete")


def boom():
    raise RuntimeError("x")


calls.clear()
r = hv.ingest(conn, hv.validate(body(12, endOfResults=True, keyword="작은키워드")), "2026-09-24", 1,
              rec({"targets_total": 1, "targets_found": 0}), boom)
ok("수집분 저장이 실패해도 순위는 적힌다", calls == [False] and r["status"] == "complete_unsaved")
rows = conn.execute("SELECT keyword, pc, covered, complete, recorded, targets_total, targets_found, logged_in, top_ids "
                    "FROM human_view_uploads ORDER BY id").fetchall()
ok("업로드마다 기록 한 줄", len(rows) == 5)
ok("기록 줄 — PC·범위·완료·찾은 수", rows[1][1:7] == (2, 80, 0, 1, 2, 2), str(rows[1]))
ok("기록 줄 — 앞 40개 상품 번호만(비교용)", len(json.loads(rows[3][8])) == 40)

print("⑤ 첫 주 대조 스위치")
orig = hv.LOGGED_IN_RECORD
try:
    hv.LOGGED_IN_RECORD = False
    calls.clear()
    r = hv.ingest(conn, hv.validate(body(40, loggedIn="in", keyword="로그인키워드")), "2026-09-24", 3,
                  rec({"targets_total": 1, "targets_found": 1}), lambda: stored.append(1))
    ok("로그인 화면 기록을 끄면 순위 기록 함수를 아예 안 부른다", calls == [] and r["status"] == "compare_only" and not r["recorded"])
    ok("…하지만 대조용 줄은 남긴다", conn.execute("SELECT recorded FROM human_view_uploads WHERE keyword='로그인키워드'").fetchone()[0] == 0)
    calls.clear()
    hv.ingest(conn, hv.validate(body(40, loggedIn="out", keyword="로그아웃키워드")), "2026-09-24", 3,
              rec({"targets_total": 1, "targets_found": 0}), lambda: None)
    ok("로그아웃 화면은 그대로 기록", calls == [True])
finally:
    hv.LOGGED_IN_RECORD = orig
ok("기본값 = 로그인 화면도 기록(대표 확정 ④ 첫 주)", hv.LOGGED_IN_RECORD is True)

print("⑥ 할 일 목록")
uni = {"캠핑의자": True, "유기농 쌀": True, "무선청소기": False, "새키워드": True, "해본키워드": True, "작은키워드": True}
done = {"유기농 쌀"} | co.found_done_keywords(conn, "2026-09-24")
td = hv.todo(conn, uni, "2026-09-24", done, {"해본키워드": "2026-09-24 10:00:00"}, pc=1)
kws = [r["keyword"] for r in td["keywords"]]
ok("끝난 것(수집분·완료 표시)은 빠진다", "유기농 쌀" not in kws and "캠핑의자" not in kws)
ok("수집기가 해 보고 못 끝낸 것이 맨 앞", kws[0] == "해본키워드", str(kws))
row = {r["keyword"]: r for r in td["keywords"]}
ok("사람이 이어 본 범위가 보인다", row["무선청소기"]["covered"] == 80)
ok("내 PC(1번)가 본 것은 「다른 PC」로 안 뜬다", row["무선청소기"]["busyPc"] is None, str(row["무선청소기"]))
row2 = {r["keyword"]: r for r in hv.todo(conn, uni, "2026-09-24", done, {}, pc=2)["keywords"]}
ok("다른 PC(2번)에서는 「1번이 방금 봄」", row2["무선청소기"]["busyPc"] == 1, str(row2["무선청소기"]))
ok("합계 칸", td["total"] == 6 and td["done"] == 2 and td["todo"] == 4, str({k: td[k] for k in ('total', 'done', 'todo')}))
ok("유니버스에 없는 키워드는 목록에 없다", "로그인키워드" not in kws)

print("⑦ 통계·대조·보관")
st = hv.stats(conn, "2026-09-24")
pcs = {p["pc"]: p for p in st["pcs"]}
ok("PC 번호별로 묶인다", set(pcs) == {1, 2, 3})
ok("PC 2 — 대상 다 찾은 키워드 1", pcs[2]["allFound"] == 1 and pcs[2]["keywords"] == 1)
ok("PC 1 — 300위 완료 키워드 1", pcs[1]["complete"] == 1)
ok("로그인 상태별 수", st["login"].get("in") == 1 and st["login"].get("out") >= 5)
ok("최근 줄에 이름 칸이 없다", st["recent"] and all(set(x) <= {"keyword", "pc", "covered", "complete", "found", "targets",
                                                           "loggedIn", "recorded", "at"} for x in st["recent"]))
same = [{"productId": str(1000 + i)} for i in range(1, 41)]
conn.execute("INSERT INTO collected_serp VALUES ('캠핑의자','2026-09-24',0,?,40,'{}','x')", (json.dumps(same),))
shuffled = [same[i ^ 1] for i in range(40)]   # 짝끼리 자리만 바꿈 — 같은 상품·다른 자리
conn.execute("INSERT INTO collected_serp VALUES ('로그인키워드','2026-09-24',0,?,40,'{}','x')", (json.dumps(shuffled),))
conn.commit()
lc = hv.login_compare(conn, "2026-09-20")
ok("대조 — 수집분과 같은 순서면 samePos 1.0", lc["out"]["pairs"] == 2 and lc["out"]["samePos"] == 1.0, str(lc))
ok("대조 — 자리만 바뀌면 같은 자리 0 · 겹침 1.0", lc["in"]["pairs"] == 1 and lc["in"]["samePos"] == 0.0 and lc["in"]["overlap"] == 1.0, str(lc["in"]))
ok("대조 — 짝이 없으면 None(0 이 아니다)", lc["unknown"]["samePos"] is None and lc["unknown"]["pairs"] == 0)
bad = sqlite3.connect(":memory:")
ok("통계 조회 실패는 None", hv.stats(bad, "2026-09-24") == {"pcs": None, "login": None, "recent": None})
ok("대조 조회 실패는 None", hv.login_compare(bad, "2026-09-20")["in"] is None)
ok("보관정책 실패는 -1", hv.purge_old(bad) == -1)
conn.execute("UPDATE human_view_uploads SET received_at = datetime('now','localtime','-40 day') WHERE keyword='작은키워드'")
conn.commit()
ok("보관정책 — 30일 지난 줄만 지운다", hv.purge_old(conn) == 1
   and conn.execute("SELECT COUNT(*) FROM human_view_uploads").fetchone()[0] == 6)

print("⑧ 배선")
src = open(os.path.join(BACKEND, "human_view_routes.py"), encoding="utf-8").read()
page = src[src.index("async def human_page"):src.index('@router.get("/token")')]
gate = page.find("if kw not in uni:")
ok("추적 키워드가 아니면 저장보다 먼저 돌려보낸다", 0 < gate < page.find("hv.ingest(") and gate < page.find("INSERT INTO collected_serp"),
   "거름 줄이 없거나 저장 뒤에 있다")
ok("…그때 accepted:false", '"accepted": False, "reason": "not-tracked"' in page)
logs = re.findall(r"logger\.\w+\((f?\"[^\n]*)", src)
ok("로그에 검색어를 싣지 않는다", logs and not any("{kw}" in l or "keyword" in l or "{item['keyword']}" in l for l in logs), str(logs))
ok("유니버스·완료는 수집기와 같은 함수", "C._keyword_universe(conn)" in src and "found_done_keywords" in src)
ok("토큰 화면은 최고관리자만", 'current_user.get("role") != "superadmin"' in src)
ok("통계는 로그인 직원만", "def human_stats(current_user: dict = Depends(get_current_user))" in src)
main = open(os.path.join(BACKEND, "main.py"), encoding="utf-8").read()
ok("라우터 등록", "from human_view_routes import router as human_view_router" in main and "app.include_router(human_view_router)" in main)
dep = open(os.path.join(ROOT, ".github", "workflows", "deploy.yml"), encoding="utf-8").read()
ok("확장 폴더는 배포 제외(고쳐도 서버가 안 바뀐다)", "- 'extension-human/**'" in dep)
ok("이 시험과 확장 시험이 게이트에 있다", "python backend/tests/test_human_view.py" in dep and "node extension-human/tests/hv_core.test.js" in dep)

print(f"\n{passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
