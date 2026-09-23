"""분석기별 사용량 — 회귀 시험 (2026-09-23)

무엇을 막는가: 플레이스 분석은 몇 번 쓰였는지 어디에도 안 남았다. 스토어는 화면이
`/api/cd/usage/increment` 로 `daily_usage` 에 세지만 플레이스 화면은 그 경로를 부르지 않는다.

지키는 것
  · 플레이스는 **따로** 센다(analyzer_usage) — 스토어 한도(daily_usage)에 더하지 않는다
    (더하면 플레이스를 돌린 만큼 영업사원 스토어 분석이 막힌다).
  · 세다가 실패해도 분석은 그대로 나간다.
  · 조회 실패를 「0회」로 찍지 않는다.

⚠️ 진짜 sqlite 파일(실제 스키마)로 실제 함수를 돌린다. 표준 라이브러리만 쓴다.
"""
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)

_pass = _fail = 0


def ok(name, cond):
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"  PASS  {name}")
    else:
        _fail += 1
        print(f"  FAIL  {name}")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def _fn(src, head):
    """head 로 시작하는 최상위 함수 본문(다음 최상위 정의 전까지)."""
    s = src[src.index(head):]
    body = s.index("\ndef ") + 1 if not s.startswith("def ") else 0   # 데코레이터 다음 자기 def 줄은 건너뛴다
    nxt = [i for i in (s.find("\n@", body), s.find("\ndef ", body), s.find("\nclass ", body)) if i > 0]
    return s[:min(nxt)] if nxt else s


_paths = []


def _fresh():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _paths.append(path)
    os.environ["DB_PATH"] = path
    sys.modules.pop("analyzer_usage", None)
    import analyzer_usage
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    # daily_usage 는 client_dashboard 스키마 그대로(스토어 분석 원장)
    c.execute("""CREATE TABLE daily_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL DEFAULT 0,
        usage_date TEXT NOT NULL, query_count INTEGER DEFAULT 0, UNIQUE(user_id, usage_date))""")
    c.commit()
    return path, analyzer_usage, c


T = "2026-09-23"

# ① 플레이스 한 번 = runs 1 · 실패는 fails 에도 1
path, au, c = _fresh()
ok("① 성공 기록", au.record(7, "place", ok=True, today=T) is True)
au.record(7, "place", ok=False, today=T)
au.record(7, "place", ok=True, today=T)
r = sqlite3.connect(path).execute(
    "SELECT runs, fails FROM analyzer_usage WHERE user_id=7 AND analyzer='place' AND usage_date=?", (T,)).fetchone()
ok("① 세 번 돌리고 한 번 실패 → runs 3 · fails 1", r == (3, 1))

# ② 스토어는 여기서 세지 않는다 — 두 곳에서 세면 숫자가 두 배가 된다
ok("② 스토어는 거절한다", au.record(7, "store", today=T) is False)
ok("② 모르는 분석기도 거절한다", au.record(7, "anything", today=T) is False)
n = sqlite3.connect(path).execute("SELECT COUNT(*) FROM analyzer_usage WHERE analyzer!='place'").fetchone()[0]
ok("② 거절한 것은 한 줄도 안 남는다", n == 0)

# ③ 합계 — 스토어는 daily_usage 그대로 · 플레이스는 따로 · 월·일 경계
c.executemany("INSERT INTO daily_usage(user_id, usage_date, query_count) VALUES(?,?,?)",
              [(7, T, 5), (8, T, 2), (7, "2026-09-01", 4), (7, "2026-08-31", 10)])
c.commit()
au.record(8, "place", today="2026-09-10")
au.record(8, "place", today="2026-08-31")
s = au.stats(c, today=T)
st, pl = s["by_analyzer"]["store"], s["by_analyzer"]["place"]
ok("③ 스토어 오늘 = daily_usage 오늘 합(7)", st["today"] == 7)
ok("③ 스토어 이번 달 = 5+2+4", st["this_month"] == 11)
ok("③ 스토어 누적 = 21", st["total"] == 21)
ok("③ 플레이스 오늘 3 · 이번 달 4 · 누적 5", (pl["today"], pl["this_month"], pl["total"]) == (3, 4, 5))
ok("③ 플레이스 오늘 실패 1", pl["fails_today"] == 1)
ok("③ 언제부터 셌는지 밝힌다(소급 불가)", pl["since"] == "2026-08-31")
ok("③ 직원별 플레이스", s["per_user"]["7"] == {"place_today": 3, "place_month": 3, "place_total": 3}
   and s["per_user"]["8"]["place_total"] == 2)

# ④ 플레이스를 세도 스토어 원장은 한 줄도 안 바뀐다(한도 무회귀)
before = [tuple(x) for x in c.execute("SELECT * FROM daily_usage ORDER BY id").fetchall()]
for _ in range(40):
    au.record(7, "place", today=T)
after = [tuple(x) for x in c.execute("SELECT * FROM daily_usage ORDER BY id").fetchall()]
ok("④ 플레이스 40회를 세도 daily_usage 불변", before == after)

# ⑤ 스토어 표가 없는 DB — 스토어는 None(= 못 쟀다), 플레이스는 그대로
fd, bare = tempfile.mkstemp(suffix=".db")
os.close(fd)
_paths.append(bare)
cb = sqlite3.connect(bare)
cb.row_factory = sqlite3.Row
au.record(1, "place", conn=cb, today=T)
s = au.stats(cb, today=T)
ok("⑤ daily_usage 없으면 스토어 None", s["by_analyzer"]["store"] is None)
ok("⑤ 플레이스는 그대로 1", s["by_analyzer"]["place"]["today"] == 1)

# ⑥ 아직 한 번도 안 셌으면 since 가 None — 화면이 「0회」가 아니라 「아직 기록 없음」이라 말할 근거
path, au, c = _fresh()
s = au.stats(c, today=T)
ok("⑥ 기록 전 since None", s["by_analyzer"]["place"]["since"] is None)

# ⑦ 실패가 밖으로 새지 않는다
os.environ["DB_PATH"] = os.path.dirname(path)    # 디렉터리 = 열 수 없는 DB
sys.modules.pop("analyzer_usage", None)
import analyzer_usage as au_bad  # noqa: E402
try:
    ok("⑦ record 실패는 False", au_bad.record(1, "place", today=T) is False)
    ok("⑦ stats 실패는 빈 dict(= 못 쟀다 · 0 과 다르다)", au_bad.stats(today=T) == {})
    ok("⑦ 이상한 사용자 번호도 안 터진다", isinstance(au.record("x", "place", conn=c, today=T), bool))
except Exception as e:  # pragma: no cover
    ok(f"⑦ 예외가 새어 나왔다: {e}", False)

# ⑧ 배선 — 플레이스 분석은 성공·실패 모두 센다(try/finally) · 우회 경로가 없다
main_src = _read("backend", "main.py")
seo = _fn(main_src, '@app.post("/api/seo/analyze")')
place_part = seo[seo.index('== "place":'):seo.index("# 캐시된 데이터가 있으면")]
ok("⑧ 플레이스 분기가 분석기 기록을 부른다", '_au_record((current_user or {}).get("id", 0), "place", ok=_pl_ok)' in place_part)
ok("⑧ 기록은 finally 안이다(예외로 끝나도 센다)",
   place_part.index("_place_seo_analyze(req, current_user)") < place_part.index("finally:")
   < place_part.index("_au_record("))
ok("⑧ 성공 판정은 응답의 success 로", '_pl_res.get("success")' in place_part)
ok("⑧ 세지 않고 바로 돌려주는 옛 경로가 없다", "return _place_seo_analyze(" not in seo)
ok("⑧ 기록 실패가 분석을 깨지 않는다(안쪽 try)", place_part.count("try:") >= 2)

# ⑨ 스토어 한도는 그대로 — 한도 판정·증가가 새 표를 읽거나 쓰지 않는다
cd_src = _read("backend", "client_dashboard.py")
chk = _fn(cd_src, '@router.get("/usage/check")')
inc = _fn(cd_src, '@router.post("/usage/increment")')
_chk_store = chk[chk.index("    conn = _get_conn()"):]   # 인자 없는 스토어 경로(플레이스 가지 뒤)
ok("⑨ 스토어 한도 판정은 daily_usage 만 본다", "daily_usage" in _chk_store and "analyzer_usage" not in _chk_store)
ok("⑨ 증가 경로도 daily_usage 만 쓴다", "INSERT INTO daily_usage" in inc and "analyzer_usage" not in inc)
ok("⑨ 영업사원 한도 상수는 30 그대로", "VIEWER_DAILY_LIMIT = 30" in cd_src)
app_src = _read("frontend", "js", "components", "App.jsx")
place_src = _read("frontend", "js", "components", "PlaceAnalysisPage.jsx")
ok("⑨ 스토어 화면은 여전히 화면에서 센다", "api.post('/cd/usage/increment')" in app_src)
ok("⑨ 플레이스 화면은 스토어 카운터를 부르지 않는다(두 번 세지 않게)", "/cd/usage/" not in place_src)

# ⑩ 조회 화면 — 기존 칸은 그대로, 분석기별은 가산
auth_src = _read("backend", "auth.py")
stats_fn = _fn(auth_src, '@router.get("/analysis-stats")')
ok("⑩ 설정 통계가 분석기별을 싣는다", '"by_analyzer": by_analyzer' in stats_fn)
ok("⑩ 기존 칸(total·today·this_month)은 그대로", '"total": total, "today": today_total, "this_month": month_total' in stats_fn)
ok("⑩ 직원별 플레이스 칸이 가산된다", '"place_today"' in stats_fn and '"place_total"' in stats_fn)
ok("⑩ 조회 실패면 직원별 플레이스 칸 3개 모두 None(0 아님)", stats_fn.count("if by_analyzer else None") == 3
   and "if by_analyzer else 0" not in stats_fn)
today_fn = _fn(cd_src, '@router.get("/today-stats")')
ok("⑩ 당일 요약에 플레이스 횟수 가산", '"place_analysis_count": place_count' in today_fn)
ok("⑩ 당일 요약의 기존 분석 횟수는 그대로", '"analysis_count": analysis_count' in today_fn)


# ⑪ 플레이스 하루 한도(대표 확정 2026-09-23 — 쇼핑과 같은 수준 · 따로 센다)
path, au, c = _fresh()
ok("⑪ 한도 상수 30(스토어와 같은 수준)", au.PLACE_VIEWER_DAILY_LIMIT == 30)
ok("⑪ 무제한 역할 목록이 스토어와 같다", au.UNLIMITED_ROLES == ("admin", "superadmin", "manager")
   and "role in ('admin', 'superadmin', 'manager')" in _read("backend", "client_dashboard.py"))
ok("⑪ 영업사원 30 · 관리자/매니저/최고관리자 무제한",
   au.limit_for("viewer", "place") == 30 and au.limit_for("manager", "place") == -1
   and au.limit_for("admin", "place") == -1 and au.limit_for("superadmin", "place") == -1)
ok("⑪ 역할이 비어도 한도는 걸린다(스토어와 같다)", au.limit_for(None, "place") == 30)
ok("⑪ 스토어는 이 모듈이 한도를 걸지 않는다", au.limit_for("viewer", "store") == -1)
for _ in range(29):
    au.record(9, "place", ok=True, conn=c, today=T)
c.commit()
chk = au.usage_check(9, "viewer", "place", conn=c, today=T)
ok("⑪ 29회면 아직 된다", chk["used"] == 29 and chk["remaining"] == 1 and chk["can_query"] is True)
au.record(9, "place", ok=True, conn=c, today=T); c.commit()
chk = au.usage_check(9, "viewer", "place", conn=c, today=T)
ok("⑪ 30회면 막힌다", chk["used"] == 30 and chk["remaining"] == 0 and chk["can_query"] is False)
for _ in range(5):
    au.record(10, "place", ok=False, conn=c, today=T)
au.record(10, "place", ok=True, conn=c, today=T); c.commit()
chk = au.usage_check(10, "viewer", "place", conn=c, today=T)
ok("⑪ 한도는 결과를 낸 횟수로 센다(서버 실패 5회는 빼고 1)", chk["used"] == 1 and chk["can_query"] is True)
chk = au.usage_check(9, "manager", "place", conn=c, today=T)
ok("⑪ 매니저는 30회를 넘어도 된다", chk["can_query"] is True and chk["limit"] == -1 and chk["remaining"] == -1)
ok("⑪ 어제 쓴 것은 오늘 한도에 안 들어간다",
   au.usage_check(9, "viewer", "place", conn=c, today="2026-09-24")["used"] == 0)
ok("⑪ 막힘 문구는 서버 숫자를 쓴다", au.limit_message({"limit": 30}) == "플레이스 분석 일일 제한(30회)을 초과했습니다. 내일 자정에 초기화됩니다.")
ok("⑪ 설정 통계가 한도를 싣는다", au.stats(c, today=T)["by_analyzer"]["place"]["viewer_daily_limit"] == 30)
os.environ["DB_PATH"] = os.path.dirname(path)
sys.modules.pop("analyzer_usage", None)
import analyzer_usage as au_bad2  # noqa: E402
bad = au_bad2.usage_check(9, "viewer", "place", today=T)
ok("⑪ 조회가 실패하면 막지 않는다(스토어와 같은 방향) · 실패 표시", bad["can_query"] is True and bad.get("error") is True)

# ⑫ 배선 — 서버가 막는다 · 막힌 시도는 세지 않는다 · 예외가 아니라 응답으로
main_src = _read("backend", "main.py")
seo = _fn(main_src, '@app.post("/api/seo/analyze")')
place_part = seo[seo.index('== "place":'):seo.index("# 캐시된 데이터가 있으면")]
i_chk, i_run = place_part.index("_au_check("), place_part.index("_place_seo_analyze(req, current_user)")
ok("⑫ 한도 확인이 분석보다 먼저다", i_chk < i_run)
ok("⑫ 막히면 429 응답을 직접 돌려준다(바깥 except 가 500 으로 바꾸지 않게)",
   "return JSONResponse(status_code=429" in place_part[i_chk:i_run] and "raise HTTPException(status_code=429" not in seo)
ok("⑫ 막힌 시도는 세지 않는다(기록 try 보다 앞에서 돌아간다)",
   place_part.index("return JSONResponse(status_code=429") < place_part.index("_pl_ok = False"))
ok("⑫ 막는 조건식 자체를 못박는다(문구만 남기고 조건을 꺼도 잡히게)",
   'if not _pl_chk.get("can_query", True):' in place_part[i_chk:i_run])
ok("⑫ 역할을 넘긴다", '(current_user or {}).get("role")' in place_part[i_chk - 200:i_chk + 200])
ok("⑫ 화면이 막힘 문구를 그대로 띄운다(detail)", '"detail": _au_msg(_pl_chk)' in place_part)
place_page = _read("frontend", "js", "components", "PlaceAnalysisPage.jsx")
ok("⑫ 플레이스 화면이 실패 응답의 detail 을 토스트로 띄운다", "toast.error((res && res.detail)" in place_page)
utils = _read("frontend", "js", "utils.js")
ok("⑫ 429 는 공용 오류 토스트가 덮지 않는다(401·403·500대만)", "status === 429" not in utils and "status >= 500" in utils)
chk_fn = _fn(cd_src, '@router.get("/usage/check")')
ok("⑫ /cd/usage/check 는 인자 없으면 종전 스토어 경로", 'if (analyzer or "").strip() == "place":' in chk_fn
   and "SELECT query_count FROM daily_usage" in chk_fn)
ok("⑫ /cd/usage/check?analyzer=place 는 같은 모양", "_au_check(current_user.get(\"id\", 0), current_user.get(\"role\"), \"place\")" in chk_fn)

# ⑬ 화면 — 설정 통계 · 대시보드 카드(옛 서버 무회귀)
stats_jsx = _read("frontend", "js", "components", "AnalysisStatsSection.jsx")
ok("⑬ 옛 서버(칸 없음)면 종전 화면", "hasOwnProperty.call(data, 'by_analyzer')" in stats_jsx)
ok("⑬ 조회 실패면 「0회」로 안 그린다", "사용량을 불러오지 못했습니다" in stats_jsx and "var showPlaceCols = !!place;" in stats_jsx)
dash = _read("frontend", "js", "components", "DashboardSummary.jsx")
ok("⑬ 대시보드 — 숫자가 올 때만 플레이스 문구", "typeof res.data.place_analysis_count === 'number'" in dash
   and "placeCount == null ? '수동 분석 횟수'" in dash)

for p in _paths:
    try:
        os.unlink(p)
    except OSError:
        pass

print(f"\n{'❌ 실패 %d건 / 전체 %d' % (_fail, _pass + _fail) if _fail else '분석기별 사용량 시험 전부 통과'}")
sys.exit(1 if _fail else 0)
