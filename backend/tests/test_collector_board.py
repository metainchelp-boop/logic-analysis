"""회귀 — 🛰 수집 현황판(대표 지시 2026-09-25 「매번 여기서 물어볼 수 없어」)

지키는 것
  ① 막힘 보고를 이름으로 판정하지 않는다(9/18 교훈) — 진짜 차단(퍼즐·차단 문구)과 진단 보고(2페이지 불변·응답 요약)를 갈라 센다
  ② 오늘 완료 = 300위까지 본 것 ∪ 대상 다 찾은 것(겹치면 한 번) · 부분 = 둘 다 아닌 시도 키워드
  ③ 못 읽은 값은 None(0 과 섞지 않는다) — 표가 없을 때 · 유니버스를 못 읽었을 때 · 기계 신호를 못 읽었을 때
  ④ 판정 줄 — 진짜 차단 1건이면 「문제」 · 기계 끊김 · 설정 대기 · 미전송 · 분할 겹침/누락 · 오늘 순위 기록
  ⑤ 3일 넘게 조용한 기계 줄은 「옛 설치본」으로 따로 뺀다(9/25 c5de44 오독 방지)
  ⑥ 분할 검사는 수집기와 같은 split_rule 로 센다(겹침·누락 0)
  ⑦ 배선 — 경로는 최고관리자만(대표 확정 「나만 보게 해」) · 화면 번들·메뉴·주소 등록 · 화면이 null 을 「미확인」으로 그린다 · 게이트 등록
⚠️ stdlib 만.
"""
import os
import re
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__)); BACKEND = os.path.dirname(HERE); ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)
passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


import collector_board as cb   # noqa: E402
import split_rule              # noqa: E402

TODAY = "2026-09-25"
YDAY = "2026-09-24"


def make_db(with_optional=True):
    c = sqlite3.connect(":memory:")
    c.executescript("""
    CREATE TABLE collected_serp (keyword TEXT, collected_date TEXT, created_at TEXT);
    CREATE TABLE collector_blocks (id INTEGER PRIMARY KEY, at TEXT, keyword TEXT, paging_index INTEGER, err TEXT,
                                   title TEXT, href TEXT, body TEXT, ext_version TEXT, note TEXT);
    CREATE TABLE client_rank_history (checked_at TEXT, rank_position INTEGER);
    CREATE TABLE rankings (checked_at TEXT);
    """)
    if with_optional:
        c.executescript("""
        CREATE TABLE collector_found_done (keyword TEXT, collected_date TEXT, received_at TEXT);
        CREATE TABLE collector_observations (keyword TEXT, collected_date TEXT, kind TEXT, received_at TEXT,
                                             reason TEXT, projected INTEGER DEFAULT 0);
        CREATE TABLE human_view_uploads (collected_date TEXT);
        """)
    return c


def seed(c):
    # 오늘: 300위까지 본 것 a,b · 대상 다 찾은 것 b(겹침),c · 부분 d,e · 시도 f 는 없음
    for k, h in (("a", "09"), ("b", "10")):
        c.execute("INSERT INTO collected_serp VALUES (?,?,?)", (k, TODAY, f"{TODAY} {h}:05:00"))
    for k, h in (("b", "10"), ("c", "11")):
        c.execute("INSERT INTO collector_found_done VALUES (?,?,?)", (k, TODAY, f"{TODAY} {h}:06:00"))
    obs = [("a", "full", "09", "", 1), ("b", "positive", "10", "", 1), ("c", "positive", "11", "", 1),
           ("d", "positive", "12", "STALE_PAGE", 0), ("d", "positive", "13", "STALE_PAGE", 0),
           ("e", "positive", "13", "budget", 0)]
    for k, kind, h, r, p in obs:
        c.execute("INSERT INTO collector_observations VALUES (?,?,?,?,?,?)", (k, TODAY, kind, f"{TODAY} {h}:07:00", r, p))
    c.execute("INSERT INTO collected_serp VALUES ('a', ?, ?)", (YDAY, f"{YDAY} 09:00:00"))
    # 막힘 보고 — 오늘 진짜 1(BLOCK_TEXT) · 진단 3(STALE_PAGE 2 · TAP_PROBE 1) · 기타 1 · 어제 진짜 1
    blocks = [(f"{TODAY} 12:00:00", "d", 2, "STALE_PAGE(클릭 뒤 내용 불변)"),
              (f"{TODAY} 12:30:00", "d", 2, "STALE_PAGE(클릭 뒤 내용 불변)"),
              (f"{TODAY} 12:31:00", "d", 2, "TAP_PROBE"),
              (f"{TODAY} 14:00:00", "e", 3, "BLOCK_TEXT(보안 확인)"),
              (f"{TODAY} 15:00:00", "e", 1, "REDIRECT"),
              (f"{YDAY} 23:00:00", "x", 2, "CAPTCHA")]
    for at, k, pg, err in blocks:
        c.execute("INSERT INTO collector_blocks (at, keyword, paging_index, err, ext_version) VALUES (?,?,?,?,?)",
                  (at, k, pg, err, "1.27.0"))
    c.execute("INSERT INTO human_view_uploads VALUES (?)", (TODAY,))
    c.executemany("INSERT INTO client_rank_history VALUES (?,?)",
                  [(f"{TODAY} 09:00:00", 3), (f"{TODAY} 10:00:00", None), (f"{YDAY} 09:00:00", 5)])
    c.execute("INSERT INTO rankings VALUES (?)", (f"{TODAY} 15:43:29",))
    c.commit()


def machine(no, count, mins, match=True, pending=0, ver="1.27.0"):
    return {"worker_no": no, "worker_count": count, "machine": f"{no}/{count}", "minutes_since": mins,
            "stale": mins is None or mins > 15, "settingsMatch": match, "ext_version": ver,
            "uploadSummary": {"count": pending, "payloadBytes": pending * 10, "oldestObservedAt": None,
                              "reviewRequiredCount": 0, "schema": 1}}


NOW = datetime(2026, 9, 25, 16, 0, 0)
UNI = ["a", "b", "c", "d", "e", "f", "g", "h"]

print("① 막힘 보고 — 진짜 차단과 진단 보고를 가른다")
ok("사유 앞머리 코드", cb.code_of("STALE_PAGE(클릭 뒤 내용 불변)") == "STALE_PAGE" and cb.code_of("") == "UNKNOWN")
ok("진짜 차단 분류", all(cb.classify(x) == "real" for x in ("BLOCK_TEXT", "CAPTCHA", "HTTP_418")))
ok("진단 보고 분류", all(cb.classify(x) == "diag" for x in ("STALE_PAGE", "TAP_PROBE", "NO_PAGER", "SAME_AS_PREV")))
ok("모르는 사유는 기타(진짜 차단으로 부풀리지 않음)", cb.classify("REDIRECT") == "other")
c = make_db(); seed(c)
b = cb.block_breakdown(c, TODAY)
ok("오늘 진짜 1 · 진단 3 · 기타 1", b and (b["real"], b["diag"], b["other"]) == (1, 3, 1), str(b))
ok("사유별 줄에 라벨", any(x["code"] == "STALE_PAGE" and "진단" in x["label"] and x["count"] == 2 for x in b["codes"]))
bw = cb.block_breakdown(c, YDAY)
ok("어제부터면 CAPTCHA 까지 진짜 2", bw["real"] == 2)
rr = cb.recent_real_blocks(c, YDAY)
ok("진짜 차단 목록엔 진짜만(최신 먼저)", [r["code"] for r in rr] == ["BLOCK_TEXT", "CAPTCHA"], str(rr))

print("② 오늘 숫자")
d = cb.day_numbers(c, TODAY)
ok("완료 = 300위까지 ∪ 대상 다 찾음(b 한 번) = 3", d["completed"] == 3, str(d))
ok("300위까지 2 · 대상 다 찾음 2", d["full"] == 2 and d["found"] == 2)
ok("부분 = 완료 아닌 시도 키워드(d,e) = 2", d["partial"] == 2)
ok("시도 6 · 도우미 1 · 진짜 1 · 진단 3", (d["attempts"], d["human"], d["realBlocks"], d["diagBlocks"]) == (6, 1, 1, 3), str(d))
dy = cb.day_numbers(c, YDAY)
ok("어제 하루 구간만(오늘 것 섞이지 않음)", dy["completed"] == 1 and dy["realBlocks"] == 1 and dy["diagBlocks"] == 0, str(dy))
h = cb.history(c, TODAY)
ok("14일 · 오래된 날부터 · 마지막이 오늘", len(h) == 14 and h[-1]["day"] == TODAY and h[-2]["day"] == YDAY)
hr = cb.hourly(c, TODAY)
ok("시간대 24칸", len(hr) == 24)
ok("10시 완료 = 수집분 1 + 대상 다 찾음 1", hr[10]["completed"] == 2 and hr[13]["attempts"] == 2, str(hr[10]) + str(hr[13]))
sr = cb.stop_reasons(c, TODAY)
ok("멈춘 이유는 반영 안 된 시도만(STALE_PAGE 2 먼저 · 라벨)", sr[0]["reason"] == "STALE_PAGE" and sr[0]["count"] == 2 and "진단" in sr[0]["label"] and sum(x["count"] for x in sr) == 3, str(sr))

print("③ 못 읽은 값은 None")
c2 = make_db(with_optional=False)
d2 = cb.day_numbers(c2, TODAY)
ok("관측 원장이 없으면 부분·시도는 None(0 아님)", d2["partial"] is None and d2["attempts"] is None, str(d2))
c3 = sqlite3.connect(":memory:")
ok("막힘 표가 없으면 None", cb.block_breakdown(c3, TODAY) is None and cb.recent_real_blocks(c3, TODAY) is None)
ok("수집분 표가 없으면 None", cb.day_numbers(c3, TODAY)["full"] is None)
ok("순위 표가 없으면 None", cb.rank_writes(c3, TODAY)["clients"] is None)
out_none = cb.build(c, TODAY, None, split_ok=split_rule.split_ok, machines_rows=None, now=NOW)
ok("유니버스를 못 읽으면 전체·안 봄·분할 None", out_none["summary"]["universe"] is None and out_none["summary"]["notTried"] is None
   and out_none["split"] is None)
lv = {v["key"]: v["level"] for v in out_none["verdicts"]}
ok("못 읽은 칸의 판정은 unknown(좋다고 치지 않음)", lv.get("machines") == "unknown" and lv.get("split") == "unknown", str(lv))

print("④ 판정 줄")
rows = [machine(1, 2, 3), machine(2, 2, 4)]
out = cb.build(c, TODAY, UNI, split_ok=split_rule.split_ok, machines_rows=rows, now=NOW)
lv = {v["key"]: v for v in out["verdicts"]}
ok("진짜 차단 1건 → 문제", lv["block"]["level"] == "bad" and "1건" in lv["block"]["text"])
ok("두 대 다 살아 있으면 기계 정상", lv["machines"]["level"] == "ok", lv["machines"]["text"])
ok("오늘 순위 기록 있으면 정상", lv["writes"]["level"] == "ok" and "업체 2줄" in lv["writes"]["text"], lv["writes"]["text"])
ok("아직 안 봄 = 8 − 완료 3 − 부분 2 = 3", out["summary"]["notTried"] == 3 and out["summary"]["universe"] == 8)
out2 = cb.build(c, TODAY, UNI, split_ok=split_rule.split_ok, machines_rows=[machine(1, 2, 3), machine(2, 2, 40)], now=NOW)
lv2 = {v["key"]: v for v in out2["verdicts"]}
ok("한 대 끊기면 확인 + 끊긴 기계 이름", lv2["machines"]["level"] == "warn" and "2/2" in lv2["machines"]["text"], lv2["machines"]["text"])
out3 = cb.build(c, TODAY, UNI, split_ok=split_rule.split_ok, machines_rows=[], now=NOW)
ok("신호가 하나도 없으면 문제", {v["key"]: v["level"] for v in out3["verdicts"]}["machines"] == "bad")
out4 = cb.build(c, TODAY, UNI, split_ok=split_rule.split_ok,
                machines_rows=[machine(1, 2, 3, match=False, pending=4), machine(2, 2, 3)], now=NOW)
lv4 = {v["key"]: v for v in out4["verdicts"]}
ok("설정 불일치 → 확인", lv4["settings"]["level"] == "warn" and "1/2" in lv4["settings"]["text"])
ok("미전송 4건 → 확인", lv4["outbox"]["level"] == "warn" and "4건" in lv4["outbox"]["text"])
c4 = make_db(); c4.commit()
early = cb.build(c4, TODAY, UNI, split_ok=split_rule.split_ok, machines_rows=rows, now=datetime(2026, 9, 25, 7, 0))
late = cb.build(c4, TODAY, UNI, split_ok=split_rule.split_ok, machines_rows=rows, now=datetime(2026, 9, 25, 12, 0))
ok("아침 9시 전 순위 기록 0은 미확인(아직 이르다)", {v["key"]: v["level"] for v in early["verdicts"]}["writes"] == "unknown")
ok("9시 넘어 0이면 확인", {v["key"]: v["level"] for v in late["verdicts"]}["writes"] == "warn")
ok("진짜 차단 0 → 정상", {v["key"]: v["level"] for v in early["verdicts"]}["block"] == "ok")

print("⑤ 옛 설치본")
rows5 = [machine(1, 2, 3), machine(2, 2, 4), machine(1, 1, 3 * 24 * 60 + 1, ver="1.26.0")]
out5 = cb.build(c, TODAY, UNI, split_ok=split_rule.split_ok, machines_rows=rows5, now=NOW)
ok("3일 넘게 조용한 줄은 옛 설치본으로", len(out5["machines"]) == 2 and len(out5["oldMachines"]) == 1)
ok("옛 설치본은 판정에 안 끼어든다(기계 정상)", {v["key"]: v["level"] for v in out5["verdicts"]}["machines"] == "ok")

print("⑥ 분할 검사")
sp = cb.split_check([f"키워드{i}" for i in range(500)], 2, split_rule.split_ok)
ok("두 대 · 겹침 0 · 누락 0 · 합 500", sp["overlap"] == 0 and sp["missing"] == 0 and sum(sp["perWorker"]) == 500, str(sp))
bad = cb.split_check(["a", "b"], 2, lambda k, w, n: True)
ok("규칙이 겹치면 겹침으로 잡는다", bad["overlap"] == 2)
none = cb.split_check(["a"], 2, lambda k, w, n: False)
ok("아무도 안 맡으면 누락으로 잡는다", none["missing"] == 1)
lvb = {v["key"]: v["level"] for v in cb.verdicts({"real": 0}, [], bad, {"clients": 1}, 12)}
ok("겹침이 있으면 분할 판정 문제", lvb["split"] == "bad")

print("⑦ 배선")
col = open(os.path.join(BACKEND, "collector.py"), encoding="utf-8").read()
m = re.search(r'@router\.get\("/board"\)\s*\ndef collector_board\(current_user: dict = Depends\(get_current_user\)\):(.*?)\n\ndef ', col, re.S)
ok("경로 /api/collector/board 는 로그인 필요", bool(m))
body = m.group(1) if m else ""
ok("최고관리자만(대표 확정 「나만 보게 해」)", 'current_user.get("role") != "superadmin"' in body and "403" in body)
ok("유니버스를 못 읽으면 None(0 개로 치지 않음)", "uni = None" in body and "uni = []" not in body)
ok("분할은 수집기와 같은 split_ok", "split_ok=_split_ok" in body)
FE = os.path.join(ROOT, "frontend")
page = open(os.path.join(FE, "js", "components", "CollectorBoardPage.jsx"), encoding="utf-8").read()
ok("화면이 /collector/board 를 부른다", "api.get('/collector/board')" in page)
ok("화면이 null 을 「미확인」으로", "'미확인'" in page and "v === null || v === undefined" in page)
ok("화면이 진짜 차단과 진단 보고를 갈라 쓴다", "진짜 차단" in page and "진단 보고" in page)
ok("화면도 최고관리자가 아니면 안내만(서버를 부르지 않음)", "var isViewer = currentUser.role !== 'superadmin'" in page and "if (isViewer) return;" in page)
ok("5분마다 새로 불러온다", "_CB_REFRESH_MS = 5 * 60 * 1000" in page and "setInterval(load, _CB_REFRESH_MS)" in page)
import json  # noqa: E402
man = json.load(open(os.path.join(FE, "build.manifest.json"), encoding="utf-8"))
ok("번들에 들어가고 스타일 상수 파일(KeywordRankPage) 뒤·App 앞", "js/components/CollectorBoardPage.jsx" in man
   and man.index("js/components/KeywordRankPage.jsx") < man.index("js/components/CollectorBoardPage.jsx") < man.index("js/components/App.jsx"))
app = open(os.path.join(FE, "js", "components", "App.jsx"), encoding="utf-8").read()
ok("주소 #collector 등록 · 화면 연결", "'collector'" in app.split("validPages", 1)[1].split("]", 1)[0]
   and "window.CollectorBoardPage" in app)
shell = open(os.path.join(FE, "js", "components", "AppShellBar.jsx"), encoding="utf-8").read()
ok("왼쪽 메뉴에 수집 현황판(최고관리자만)", "role === 'superadmin' && { page: 'collector'" in shell and "collector: '쇼핑 / 수집 현황판'" in shell)
dep = open(os.path.join(ROOT, ".github", "workflows", "deploy.yml"), encoding="utf-8").read()
ok("이 시험이 게이트에 있다", "python backend/tests/test_collector_board.py" in dep)

print(f"\n{passed} 통과 · {failed} 실패")
sys.exit(1 if failed else 0)
