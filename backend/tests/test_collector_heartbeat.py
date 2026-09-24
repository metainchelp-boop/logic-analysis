"""회귀 — 수집기 살아있음 신호(heartbeat) v1.21.0 (대표 확정 2026-09-22 · 수집기 자체 개발 1차)

지키는 것:
  ① collector_heartbeat 가 기계별 최신 행을 갱신하고(upsert) 상태 문구가 멈춘 이유를 우선순위대로 말한다.
  ② 서버 배선 — POST /heartbeat 가 토큰 검사(_auth)를 지나 record 를 부르고, /health 응답에 machines 가 additive 로 실린다.
  ③ 확장 배선 — armAlarms 5분 주기 · onAlarm · 멈춰 있어도 보냄 · manifest 1.21.0 (node 시험 heartbeat.test.js 와 짝).

⚠️ stdlib 만 — 배포 게이트에 fastapi 가 없다. ①은 실제 모듈을 가짜 DB 로, ②③은 소스 배선(호출 모양)으로.
"""
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
ROOT = os.path.dirname(BACKEND)
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


print("① collector_heartbeat — 가짜 DB")
import collector_heartbeat as hb
conn = sqlite3.connect(":memory:")
now = datetime(2026, 9, 22, 12, 0, 0)
r = hb.record(conn, {"instanceId": "m1", "workerNo": 1, "workerCount": 2, "extVersion": "1.21.0",
                     "reason": "alarm", "pausedByLocal": False, "blockedUntil": 0, "running": False,
                     "alarms": ["daily:1", "ondemand:1", "heartbeat:5"], "dayDone": 30, "dayTotal": 400}, now=now)
ok("🔴 첫 신호가 행을 만든다(seen_count 1)", r.get("instance_id") == "m1" and
   conn.execute("SELECT seen_count FROM collector_heartbeat WHERE instance_id='m1'").fetchone()[0] == 1)
hb.record(conn, {"instanceId": "m1", "workerNo": 1, "workerCount": 2, "pausedByLocal": True}, now=now + timedelta(minutes=5))
row = conn.execute("SELECT seen_count, paused_local, last_seen, first_seen FROM collector_heartbeat WHERE instance_id='m1'").fetchone()
ok("🔴 같은 기계의 다음 신호는 행을 늘리지 않고 갱신한다(seen_count 2 · paused 반영 · first_seen 유지)",
   row[0] == 2 and row[1] == 1 and row[2] == "2026-09-22 12:05:00" and row[3] == "2026-09-22 12:00:00"
   and conn.execute("SELECT COUNT(*) FROM collector_heartbeat").fetchone()[0] == 1)
ok("instanceId 없으면 저장하지 않는다(skipped)", hb.record(conn, {"workerNo": 2}, now=now).get("skipped") is True
   and conn.execute("SELECT COUNT(*) FROM collector_heartbeat").fetchone()[0] == 1)
ms = int((now + timedelta(hours=3)).timestamp() * 1000)
hb.record(conn, {"instanceId": "m2", "workerNo": 2, "workerCount": 2, "blockedUntil": ms, "running": False}, now=now + timedelta(minutes=5))
ok("epoch ms 인 blockedUntil 을 서버 로컬 시각 문자열로 저장한다",
   conn.execute("SELECT blocked_until FROM collector_heartbeat WHERE instance_id='m2'").fetchone()[0] == "2026-09-22 15:00:00")
ok("IP·키워드는 받아도 저장할 칸이 없다",
   not {"ip", "keyword"} & {r[1] for r in conn.execute("PRAGMA table_info(collector_heartbeat)")})

print("\n  상태 문구 — 우선순위(끊김 > 일시정지 > 캡차 쉼 > 화면 끔 > 수집 중 > 대기)")
t = now + timedelta(minutes=6)
rows = {m["instance_id"]: m for m in hb.machines(conn, now=t)}
ok("🔴 m1 = ⏸ 일시정지(사람)", rows["m1"]["status"].startswith("⏸ 일시정지") and rows["m1"]["stale"] is False)
ok("🔴 m2 = 🧱 캡차 쉼 + 재개 시각", rows["m2"]["status"].startswith("🧱 캡차 쉼") and "15:00" in rows["m2"]["status"])
rows = {m["instance_id"]: m for m in hb.machines(conn, now=now + timedelta(minutes=40))}
ok("🔴 15분 넘게 신호가 없으면 ⛔ 신호 끊김 N분 (일시정지보다 먼저)",
   rows["m1"]["status"].startswith("⛔ 신호 끊김 35분") and rows["m1"]["stale"] is True)
ok("machine 표기 = 번호/대수", rows["m1"]["machine"] == "1/2" and rows["m2"]["machine"] == "2/2")
hb.record(conn, {"instanceId": "m3", "running": True}, now=t)
hb.record(conn, {"instanceId": "m4", "pausedByScreen": True}, now=t)
hb.record(conn, {"instanceId": "m5"}, now=t)
rows = {m["instance_id"]: m for m in hb.machines(conn, now=t)}
ok("수집 중 / 화면 끔 / 대기(정상)", rows["m3"]["status"] == "▶ 수집 중" and rows["m4"]["status"] == "🛑 화면에서 꺼 둠" and rows["m5"]["status"] == "대기(정상)")
ok("summary_line 이 기계 수와 상태를 한 줄로", hb.summary_line(hb.machines(conn, now=t)).startswith("기계 5대 — "))
ok("표가 없는 DB 에서도 machines 는 빈 목록(죽지 않음)", hb.machines(sqlite3.connect(":memory:"), now=t) == [])

print("\n② 서버 배선 — collector.py")
c = read("backend/collector.py")
i = c.index('@router.post("/heartbeat")'); body = c[i:c.index("\nclass BlockReport", i)]
ok("🔴 POST /heartbeat 가 토큰 검사를 먼저 지난다", re.search(r"_auth\(x_collector_token\)", body) is not None)
# 2026-09-23: 배치 잠금 500 → write_with_retry 로 감싸며 payload 를 변수로 받는다(_payload = req.dict()) — 호출 모양 두 가지 허용
ok("🔴 record 를 실제로 부른다(req.dict())",
   re.search(r"_hb_record\(conn, req\.dict\(\)\)", body) is not None
   or (re.search(r"_payload = req\.dict\(\)", body) is not None and re.search(r"_hb_record\(c, _payload\)", body) is not None))
ok("HeartbeatReport 가 instanceId·pausedByLocal·blockedUntil·alarms 를 받는다",
   all(f in c[c.index("class HeartbeatReport"):i] for f in ("instanceId", "pausedByLocal", "blockedUntil", "alarms")))
ok("init_collector_db 가 heartbeat 표를 보장한다", re.search(r"from collector_heartbeat import ensure_table as _hb_ensure\s*\n\s*_hb_ensure\(conn\)", c) is not None)
h = c[c.index("def collect_health("):c.index("def _safe_int(")]
ok("🔴 /health 응답에 machines 가 additive 로 실린다(기존 키 유지)",
   '"machines": machines_list' in h and '"hoursSinceUpload": hours_since' in h and "_hb_machines(_c2)" in h)
ok("machines 조회 실패는 None(못 쟀다) — 빈 목록과 다르다", "machines_list = None" in h)

print("\n③ 확장 배선 — 요약(상세는 node heartbeat.test.js)")
bg = read("collector-extension/background.js")
# ⚙ v1.27.0 — 주기가 서버 설정(heartbeatMin)으로 옮겨졌다. 없으면 HEARTBEAT_PERIOD_MIN(5) — 기본값도 5.
ok("🔴 heartbeat 알람 5분 주기", "const HEARTBEAT_PERIOD_MIN = 5;" in bg
   and "chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: (typeof RT === 'object' && RT ? RT.heartbeatMin : HEARTBEAT_PERIOD_MIN)" in bg
   and "heartbeatMin: 5," in read("collector-extension/remote_settings.js"))
ok("🔴 sendHeartbeat 가 일시정지 값을 **읽어서 보낸다**(거르지 않는다)", "pausedByLocal: await isLocalPaused()," in bg)
_mv = re.search(r'"version":\s*"(\d+)\.(\d+)\.', read("collector-extension/manifest.json"))
ok("manifest 1.21.0 이상(살아있음 신호 포함)", bool(_mv) and (int(_mv.group(1)), int(_mv.group(2))) >= (1, 21))
ok("게이트에 node heartbeat 시험이 등록돼 있다", "collector-extension/tests/heartbeat.test.js" in read(".github/workflows/deploy.yml"))

print(f"\n{'✅' if not failed else '🔴'} 통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
