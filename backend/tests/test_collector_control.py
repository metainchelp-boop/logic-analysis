"""회귀 — 수집 켜고 끄기 스위치 (대표 확정 2026-09-18)

지키는 것:
  ① 화면에서 끄면 그 기계가 멈춤으로 판정된다(전체·기계별).
  ② 판정 실패는 「멈춤」이 아니라 「돎」이다(fail-open).
  ③ /keywords 응답 배선과 확장의 회차 건너뜀·간격 가변이 살아 있다.

⚠️ stdlib 만 — 배포 게이트에 fastapi 가 없다. BE 배선·확장은 소스로 확인한다.
"""

import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

import collector_control as CC   # noqa: E402

passed = failed = 0


def ok(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}{(' — ' + extra) if extra else ''}")


def src(rel):
    with open(os.path.join(BACKEND, rel), encoding="utf-8") as f:
        return f.read()


def ext(rel):
    with open(os.path.join(os.path.dirname(BACKEND), rel), encoding="utf-8") as f:
        return f.read()


print("① 켜고 끄기 판정")
c = sqlite3.connect(":memory:")
CC.ensure_table(c)
CC.ensure_table(c)   # 멱등
ok("표 보장은 두 번 불러도 안전", True)
ok("기본은 아무도 안 멈춤", CC.is_paused(c, 0) is False and CC.is_paused(c, 1) is False)

CC.set_paused(c, 0, True, "대표")
ok("0번 기계를 끄면 0번만 멈춤", CC.is_paused(c, 0) is True and CC.is_paused(c, 1) is False)
CC.set_paused(c, 0, False, "대표")
ok("0번 기계를 다시 켜면 안 멈춤", CC.is_paused(c, 0) is False)

CC.set_paused(c, CC.ALL, True, "대표")
ok("전체(-1)를 끄면 모든 기계가 멈춤",
   CC.is_paused(c, 0) is True and CC.is_paused(c, 1) is True and CC.is_paused(c, 5) is True)
ok("전체 멈춤이면 worker 안 줘도 멈춤", CC.is_paused(c) is True)
CC.set_paused(c, CC.ALL, False, "대표")
ok("전체를 켜면 다시 다 돎", CC.is_paused(c, 0) is False and CC.is_paused(c) is False)

st = CC.get_state(c)
ok("상태 조회에 all·workers 가 있다", "all" in st and "workers" in st)

print("\n② fail-open — 판정 실패는 돎")
bad = sqlite3.connect(":memory:")   # 표가 없다
# ensure_table 이 만들어 주지만, 조회가 깨지는 상황을 흉내 — 잘못된 worker
ok("이상한 worker 값이 와도 안 멈춤(돎)", CC.is_paused(c, "abc") is False)
ok("음수 worker 는 전체 스위치만 본다", CC.is_paused(c, -5) is False)
# 표를 강제로 깨서 조회 실패를 만든다
brk = sqlite3.connect(":memory:")
brk.execute("CREATE TABLE collector_control(worker TEXT)")   # 스키마가 다르다
ok("표 스키마가 깨져도 멈추지 않는다(fail-open)", CC.is_paused(brk, 0) is False)

print("\n③ 서버 배선 — /keywords 가 멈춤을 본다")
col = src("collector.py")
ok("get_collect_keywords 가 is_paused 를 부른다",
   "from collector_control import is_paused" in col and "is_paused(conn, worker)" in col)
ok("🔴 멈춤이면 paused=True + 빈 키워드를 돌려준다",
   re.search(r'if is_paused\(conn, worker\):[\s\S]{0,200}"paused": True', col) is not None)
ok("제어 엔드포인트 GET/POST 가 있다",
   '@router.get("/control")' in col and '@router.post("/control")' in col)
ok("제어는 로그인 사용자 전용", "collector_control_set" in col and "get_current_user" in col)

print("\n④ 확장 — 회차 건너뜀 + 간격 가변")
bg = ext("collector-extension/background.js")
ok("응답에서 paused 를 읽는다", "paused = false" in bg or "paused =false" in bg)
ok("🔴 paused 면 회차를 건너뛴다",
   re.search(r"if \(paused\)\s*\{[\s\S]{0,200}return;", bg) is not None)
ok("간격 가변 함수 spreadGap 이 있다", "async function spreadGap" in bg)
ok("🔴 고정 30초 대신 남은시간÷남은개수를 쓴다",
   "spreadGap(_msLeft, _kwLeft)" in bg)
ok("🔴 고정 keywordGapMs 로 키워드 사이를 쉬지 않는다(가변으로 교체)",
   "await gapFor(CFG.keywordGapMs)" not in bg)
ok("최소 간격 40초를 지킨다", "SPREAD_MIN_MS" in bg and "40 * 1000" in bg)
ok("느리게 가기 상태면 2배 유지", re.search(r"isSlow\(\)\)\s*\?\s*g \* 2", bg) is not None)

mf = ext("collector-extension/manifest.json")
ok("확장 버전이 1.20.0 이다", '"version": "1.20.0"' in mf)

pop = ext("collector-extension/popup.js")
ok("팝업이 화면에서 꺼짐을 표시한다", "pausedByScreen" in pop and "화면에서 꺼" in pop)

print("\n⑤ 화면 — 제어 바")
fe = src("../frontend/js/components/RankTrackingSection.jsx")
ok("화면이 /collector/control 을 읽는다", "/collector/control" in fe)
ok("화면에 전체 켜기/끄기 버튼이 있다",
   "toggleCollector(-1" in fe and ("전체 수집 켜기" in fe or "전체 수집 끄기" in fe))

print("\n⑥ 확장 — 이 기계 로컬 일시정지/재개 (대표 지시 2026-09-18)")
bg2 = ext("collector-extension/background.js")
ok("로컬 일시정지 헬퍼가 있다", "async function isLocalPaused" in bg2 and "LOCAL_PAUSE_KEY" in bg2)
ok("조회 실패는 멈춤이 아니라 돎(fail-open)",
   re.search(r"async function isLocalPaused[\s\S]{0,300}catch \(e\) \{ return false;", bg2) is not None)
ok("🔴 runCollection 이 로컬 일시정지면 회차를 건너뛴다",
   re.search(r"if \(await isLocalPaused\(\)\) \{[\s\S]{0,200}running = false; return;", bg2) is not None)
ok("🔴 running='daily' 를 먼저 잡은 뒤 검사한다(이중 진입 방지)",
   re.search(r"running = 'daily';[\s\S]{0,400}if \(await isLocalPaused\(\)\)", bg2) is not None)
ok("runOnDemand 도 로컬 일시정지면 건너뛴다",
   re.search(r"running = 'ondemand';[\s\S]{0,400}if \(await isLocalPaused\(\)\) return;", bg2) is not None)
ok("setLocalPause 메시지를 처리한다(켬/끔)",
   "msg?.cmd === 'setLocalPause'" in bg2
   and "chrome.storage.local.set({ [LOCAL_PAUSE_KEY]: true })" in bg2
   and "chrome.storage.local.remove(LOCAL_PAUSE_KEY)" in bg2)

ph = ext("collector-extension/popup.html")
ok("🔴 팝업에 일시정지 버튼이 있다", 'id="localPause"' in ph)

pop2 = ext("collector-extension/popup.js")
ok("팝업이 버튼을 눌러 setLocalPause 를 보낸다",
   "cmd: 'setLocalPause'" in pop2 and "$('localPause').onclick" in pop2)
ok("팝업이 pausedByLocal 상태를 반영한다",
   "state.pausedByLocal === true" in pop2 and "일시정지" in pop2)

print(f"\n{'✅' if not failed else '🔴'} 통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
