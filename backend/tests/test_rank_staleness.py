"""회귀 — 오래된 순위에 「며칠 전 값」 표시 (대표 지시 2026-09-28)

지키는 것
  ① 규칙 한 곳(rank_staleness) — 오늘·어제 = 최신 · 2일 전부터 오래됨 · 날짜를 못 읽으면 None(단정 안 함)
  ② last_known — 창(최근 N일) 밖까지 키워드별 **마지막** 기록(순위·시각) · 다른 업체 기록은 안 섞임 · 실패는 빈 dict
  ③ 배선 — rank_board 행에 stale_days·stale · 예전에 잰 적 있는 「기록 대기」는 pending_reason='stale'
           · 창 크기는 루프 변수가 아니라 _window_days · kpis.stale · rank_overview 업체별 stale · 추적 상품 목록 stale
  ④ 화면 — 서버가 준 stale 만 그린다(화면이 날짜를 다시 계산하지 않음) · 순위 값·정렬·노출 집계는 그대로
  ⑤ ① 전산 portal-summary 는 건드리지 않는다(3필드 계약)
⚠️ 게이트엔 fastapi 가 없다 → ①② 는 직접 import, ③④⑤ 는 소스 배선으로 본다(주석에 안 걸리게 호출 모양으로).
"""
import os
import re
import sqlite3
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE); ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
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


import rank_staleness as rs   # noqa: E402

T = date(2026, 9, 28)
print("① 규칙")
ok("오늘 = 0일 · 최신", rs.stale_days("2026-09-28 10:00:00", T) == 0 and not rs.is_stale(0))
ok("어제 = 1일 · 최신(전일 기준 수집)", rs.stale_days("2026-09-27 23:59:59", T) == 1 and not rs.is_stale(1))
ok("그제 = 2일 · 오래됨", rs.stale_days("2026-09-26", T) == 2 and rs.is_stale(2))
ok("9/24 = 4일 · 오래됨", rs.stale_days("2026-09-24 16:00:00", T) == 4 and rs.is_stale(4))
ok("못 읽으면 None · 오래됐다고 단정 안 함", rs.stale_days("", T) is None and rs.stale_days("abc", T) is None
   and rs.stale_days(None, T) is None and not rs.is_stale(None))
ok("미래 날짜는 0", rs.stale_days("2026-10-01", T) == 0)
ok("오늘 인자를 문자열로 줘도 된다", rs.stale_days("2026-09-26", "2026-09-28") == 2)
ok("기준선 = 2", rs.STALE_AFTER_DAYS == 2)

print("② last_known")
c = sqlite3.connect(":memory:")
c.execute("CREATE TABLE client_rank_history (id INTEGER PRIMARY KEY, client_id INT, keyword TEXT, "
          "rank_position INT, page_number INT, checked_at TEXT)")
rows = [(1, "a", 30, "2026-09-10 09:00:00"), (1, "a", 12, "2026-09-18 09:00:00"),
        (1, "b", None, "2026-09-12 09:00:00"), (2, "a", 3, "2026-09-27 09:00:00")]
for cid, kw, r, at in rows:
    c.execute("INSERT INTO client_rank_history(client_id, keyword, rank_position, checked_at) VALUES (?,?,?,?)",
              (cid, kw, r, at))
lk = rs.last_known(c, 1, ["a", "b", "zz", " "])
ok("가장 마지막 기록(9/18 12위)", lk.get("a") == {"rank": 12, "at": "2026-09-18 09:00:00"}, str(lk))
ok("미노출(None) 기록도 마지막으로 인정", lk.get("b") == {"rank": None, "at": "2026-09-12 09:00:00"})
ok("기록 없는 키워드는 없음", "zz" not in lk)
ok("다른 업체(2번) 기록은 안 섞임", lk["a"]["rank"] != 3)
ok("빈 목록은 빈 dict", rs.last_known(c, 1, []) == {})
ok("표가 없으면 빈 dict(예외 안 냄)", rs.last_known(sqlite3.connect(":memory:"), 1, ["a"]) == {})

print("③ 서버 배선")
cd = read("backend/client_dashboard.py")
rb = cd.split("def rank_board(", 1)[1].split("\nclass TrackKeywordRequest", 1)[0]
ok("보드 행에 stale_days · stale", '"stale_days": _rs.stale_days(latest["at"])' in rb
   and '"stale": bool(_rs and _rs.is_stale(_rs.stale_days(latest["at"])))' in rb)
ok("「기록 대기」 중 예전 기록 있는 줄 → stale", 'b["pending_reason"] = "stale"' in rb
   and "_rs.last_known(conn, client_id" in rb and 'b["last_known"] = {"rank": _k.get("rank"), "at": _k.get("at")}' in rb)
ok("막힌 업체 사유(blocked)는 덮지 않는다", 'b.get("pending_reason") != "blocked"' in rb)
ok("창 크기는 _window_days(루프 변수 days 아님)", "_window_days = days" in rb
   and 'str(_window_days) + "일 안에 새 기록이 없습니다"' in rb and 'str(days) + "일 안에' not in rb)
ok("kpis.stale", 'kpis["stale"] = sum(1 for b in board if b.get("stale"))' in rb)
ok("순위 값·정렬·노출 집계 식은 그대로", 'board.sort(key=lambda b: (b["rank"] is None' in rb
   and '"exposed": sum(1 for b in board if b["rank"] is not None)' in rb)
ro = cd.split("def rank_overview(", 1)[1].split("def rank_board(", 1)[0]
ok("rank_overview 업체별 stale", 'e["stale"] += 1' in ro and 'item["stale"] = e.get("stale", 0)' in ro
   and "_rs.is_stale(_rs.stale_days(latest_d))" in ro)
mn = read("backend/main.py")
ok("추적 상품 목록 키워드 stale", "kw_dict['stale_days'] = _sd" in mn and "kw_dict['stale'] = _rs.is_stale(_sd)" in mn)

print("④ 화면")
ut = read("frontend/js/utils.js")
chip = ut.split("window.rankStaleChip = function rankStaleChip(stale, days, at) {", 1)
ok("공용 배지 함수", len(chip) == 2)
body = chip[1].split("\n};", 1)[0] if len(chip) == 2 else ""
ok("서버 stale 이 거짓이면 안 그림", "if (!stale || days === null || days === undefined) return null;" in body)
ok("화면이 날짜를 다시 계산하지 않음", "Date.now" not in body and "new Date" not in body and ">= 2" not in body)
kr = read("frontend/js/components/KeywordRankPage.jsx")
ok("보드 순위 칸 배지", "window.rankStaleChip(b.stale, b.stale_days, b.last_checked))" in kr)
ok("오래된 순위는 회색", "color: b.stale ? '#94a3b8' : (b.rank <= 10 ? '#16a34a' : '#0f172a')" in kr)
ok("stale 대기 줄은 예전 값 + 배지", "b.pending && b.pending_reason === 'stale'" in kr
   and "window.rankStaleChip(true, b.stale_days, b.last_checked)" in kr)
ok("펼침 카드도 「첫 수집 대기」로 속이지 않음", "b.pending && b.pending_reason === 'stale') st = " in kr)
ok("오래된 순위의 전일 대비는 흐리게", "b.stale ? { opacity: 0.4 } : {}" in kr)
ok("도우미 칸 — 배열이 아니면 미확인(화면 전체가 죽지 않게)", "d && (!Array.isArray(pcs) ?" in kr)
ok("안내문은 서버 수가 있을 때만", "(kpis.stale || 0) > 0 && React.createElement('div'" in kr)
ok("업체 목록 「오래된 순위 N개」", "(c.stale || 0) > 0 && React.createElement('span'" in kr and "'오래된 순위 ' + c.stale + '개'" in kr)
rt = read("frontend/js/components/RankTrackingSection.jsx")
ok("추적 상품 화면 두 곳", rt.count("window.rankStaleChip(k.stale, k.stale_days, k.last_checked)") == 2)
man = read("frontend/build.manifest.json")
ok("utils 가 컴포넌트보다 먼저 로드", man.index('"js/utils.js"') < man.index("RankTrackingSection.jsx") < man.index("KeywordRankPage.jsx"))

print("⑤ ① 계약 무접촉")
ps = cd.split("def portal_summary(", 1)[1][:6000] if "def portal_summary(" in cd else ""
ok("portal-summary 에 stale 가산 없음", ps != "" and "stale" not in ps and "rank_staleness" not in ps)

print("⑥ 게이트")
ok("이 시험이 게이트에 있다", "python backend/tests/test_rank_staleness.py" in read(".github/workflows/deploy.yml"))

print(f"\n{passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
